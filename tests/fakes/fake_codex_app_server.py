#!/usr/bin/env python3
"""A stand-in for `codex app-server` (codex-cli 0.162.1): replays a recorded scenario over stdio.

TCC's Codex code spawns `[codex, "app-server", *args]`; put this file where `codex` would be. It
ignores the app-server's own arguments (`app-server`, `-c k=v`, `--enable X`, `--disable X`) and
takes its own from flags or, when spawned as `codex`, from the environment:

    --scenario NAME|PATH   FAKE_CODEX_SCENARIO   a file in tests/fixtures/codex/ (without .jsonl) or a path
    --work DIR             FAKE_CODEX_WORK       replaces <WORK> (Codex's cwd in the recording)
    --sub KEY=VALUE        FAKE_CODEX_SUB        more placeholders, `;`-separated in the env form
    --log PATH             FAKE_CODEX_LOG        JSONL: argv, every frame both ways, the verdict
    --timeout S            FAKE_CODEX_TIMEOUT    how long to wait for the client at one step (10)
    --pace F               FAKE_CODEX_PACE       sleep F x the recorded gap before each frame (0)
    --version                                    prints `codex-cli 0.162.1`

A scenario is the recording itself (one frame per line, `dir` "out" = client to Codex, "in" = Codex
to client, "eof" = the process dies). The replay walks it in order: an "in" frame is sent; an "out"
request waits for the client's request of the same method and the recorded response goes back
under the client's id; an "out" reply waits for the client's answer to that server request; an
"eof" frame writes its stderr, closes stdout and exits with its code. A client request the
recording does not have gets the answer from DEFAULTS, or a JSON-RPC error.

**The check.** Every server request this process sends must be answered exactly once, unless a
`serverRequest/resolved` withdrew it first — then it must not be answered at all. On stdin EOF the
verdict is written; a breach exits 3 with one `fake_codex_app_server: ASSERT …` line per request on
stderr. A step that waits longer than --timeout exits 4 (`… TIMEOUT …`).

Stdlib only.
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

VERSION = "codex-cli 0.162.1"
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "codex"
PREFIX = "fake_codex_app_server:"
EXIT_ASSERT, EXIT_TIMEOUT, EXIT_USAGE = 3, 4, 2

DEFAULTS: dict[str, dict] = {
    "initialize": {"userAgent": "fake-codex/0.162.1", "codexHome": "<CODEX_HOME>",
                   "platformFamily": "unix", "platformOs": "macos"},
    "skills/extraRoots/set": {},
}


class Timeout(Exception):
    pass


def _say(line: str) -> None:
    sys.stderr.write(f"{PREFIX} {line}\n")
    sys.stderr.flush()


def _args(argv: list[str]) -> dict:
    env = os.environ
    opts = {"scenario": env.get("FAKE_CODEX_SCENARIO"), "work": env.get("FAKE_CODEX_WORK"),
            "log": env.get("FAKE_CODEX_LOG"), "timeout": float(env.get("FAKE_CODEX_TIMEOUT", "10")),
            "pace": float(env.get("FAKE_CODEX_PACE", "0")), "subs": {}, "version": False}
    for pair in filter(None, (env.get("FAKE_CODEX_SUB") or "").split(";")):
        k, _, v = pair.partition("=")
        opts["subs"][k] = v
    it = iter(argv)
    for a in it:
        if a == "--version":
            opts["version"] = True
        elif a in ("--scenario", "--work", "--log"):
            opts[a[2:]] = next(it)
        elif a in ("--timeout", "--pace"):
            opts[a[2:]] = float(next(it))
        elif a == "--sub":
            k, _, v = next(it).partition("=")
            opts["subs"][k] = v
        elif a in ("-c", "--config", "--enable", "--disable"):
            next(it, None)  # the app-server's own options: accepted, not used
    return opts


def _scenario_path(name: str) -> Path:
    p = Path(name)
    if p.suffix == ".jsonl" or p.exists():
        return p
    return FIXTURES / f"{name}.jsonl"


class Replay:
    def __init__(self, frames: list[dict], opts: dict) -> None:
        self.frames = frames
        self.timeout = opts["timeout"]
        self.pace = opts["pace"]
        subs = dict(opts["subs"])
        if opts.get("work"):
            subs["<WORK>"] = opts["work"]
        self.subs = {k: json.dumps(v)[1:-1] for k, v in subs.items()}
        self.log = open(opts["log"], "a", encoding="utf-8") if opts.get("log") else None
        self.inbox: "queue.Queue[dict | None]" = queue.Queue()
        self.client_closed = False
        self.idmap: dict = {}               # recorded client id -> the live client's id
        self.held: list[dict] = []          # client requests that arrived before their step
        self.sent: dict = {}                # server request id -> method
        self.answers: dict = {}             # server request id -> how many answers
        self.withdrawn: set = set()
        self.breaches: list[str] = []
        self.last_t = 0.0
        self.out = sys.stdout.buffer
        self._log({"argv": sys.argv[1:], "env": {"TCC_MCP_TOKEN": "TCC_MCP_TOKEN" in os.environ}})

    # --- io ----------------------------------------------------------------------------------

    def _log(self, obj: dict) -> None:
        if self.log:
            self.log.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.log.flush()

    def reader(self) -> None:
        for raw in sys.stdin.buffer:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                _say(f"unparseable line from the client: {line[:200]}")
                continue
            self._log({"dir": "out", "msg": msg})
            self.inbox.put(msg)
        self.inbox.put(None)

    def send(self, msg: dict, t: float | None = None) -> None:
        if self.pace and t is not None:
            time.sleep(max(0.0, (t - self.last_t) * self.pace))
        if t is not None:
            self.last_t = t
        text = json.dumps(msg, ensure_ascii=False)
        for k, v in self.subs.items():
            text = text.replace(k, v)
        self._log({"dir": "in", "msg": json.loads(text)})
        try:
            self.out.write(text.encode("utf-8") + b"\n")
            self.out.flush()
        except BrokenPipeError:
            pass

    # --- the client's messages ---------------------------------------------------------------

    def next_message(self) -> dict | None:
        if self.client_closed:
            return None
        try:
            msg = self.inbox.get(timeout=self.timeout)
        except queue.Empty:
            raise Timeout from None
        if msg is None:
            self.client_closed = True
        return msg

    def on_reply(self, msg: dict) -> None:
        rid = msg.get("id")
        if rid not in self.sent:
            self.breaches.append(f"the client answered id={rid!r}, which this server never sent")
            return
        self.answers[rid] = self.answers.get(rid, 0) + 1
        if rid in self.withdrawn:
            self.breaches.append(f"server request id={rid} ({self.sent[rid]}) answered after "
                                 f"serverRequest/resolved withdrew it")
        elif self.answers[rid] == 2:
            self.breaches.append(f"server request id={rid} ({self.sent[rid]}) answered more than once")

    def on_unscripted(self, msg: dict, future_methods: set[str]) -> None:
        """A client request that is not the current step: hold it for a later step, or answer now."""
        method = msg["method"]
        if method in future_methods:
            self.held.append(msg)
        elif method in DEFAULTS:
            self.send({"id": msg["id"], "result": DEFAULTS[method]})
        else:
            self.send({"id": msg["id"], "error": {"code": -32601,
                                                  "message": f"{PREFIX} no recorded answer for {method}"}})

    def wait_for(self, kind: str, key, future_methods: set[str]) -> dict | None:
        """Read client messages until one is the step `kind`/`key`. None = the client closed stdin."""
        if kind == "request":
            for i, msg in enumerate(self.held):
                if msg["method"] == key:
                    return self.held.pop(i)
        if kind == "reply" and self.answers.get(key):
            return {"id": key}
        while True:
            msg = self.next_message()
            if msg is None:
                return None
            is_reply = "method" not in msg and "id" in msg
            if is_reply:
                self.on_reply(msg)
                if kind == "reply" and msg.get("id") == key:
                    return msg
            elif "id" in msg:
                if kind == "request" and msg["method"] == key:
                    return msg
                self.on_unscripted(msg, future_methods)
            elif kind == "notification" and msg.get("method") == key:
                return msg

    # --- the walk ----------------------------------------------------------------------------

    def run(self) -> int:
        threading.Thread(target=self.reader, daemon=True).start()
        step_no = 0
        try:
            for step_no, f in enumerate(self.frames):
                m = f.get("msg") or {}
                future = {g["msg"]["method"] for g in self.frames[step_no + 1:]
                          if g["dir"] == "out" and "method" in (g.get("msg") or {}) and "id" in g["msg"]}
                if f["dir"] == "eof":
                    return self.die(f)
                if f["dir"] == "in":
                    self.emit(m, f.get("t"))
                    continue
                if "method" in m and "id" in m:
                    got = self.wait_for("request", m["method"], future)
                    if got is not None:
                        self.idmap[m["id"]] = got["id"]
                elif "method" in m:
                    got = self.wait_for("notification", m["method"], future)
                else:
                    got = self.wait_for("reply", m.get("id"), future)
                if got is None:
                    _say(f"the client closed stdin at frame {step_no + 1} of {len(self.frames)}")
                    break
            self.drain()
        except Timeout:
            f = self.frames[step_no]
            what = (f.get("msg") or {}).get("method") or f"the answer to id={(f.get('msg') or {}).get('id')}"
            _say(f"TIMEOUT {self.timeout:g}s waiting for the client: {what} (frame {step_no + 1})")
            self.verdict(final=False)
            return EXIT_TIMEOUT
        return self.verdict(final=True)

    def emit(self, m: dict, t: float | None) -> None:
        if "method" not in m and "id" in m:  # a response to a client request: the client's own id
            if m["id"] not in self.idmap:
                _say(f"recorded response id={m['id']} has no client request; skipped")
                return
            m = {**m, "id": self.idmap[m["id"]]}
        elif "method" in m and "id" in m:  # a server request
            self.sent[m["id"]] = m["method"]
            self.answers.setdefault(m["id"], 0)
        elif m.get("method") == "serverRequest/resolved":
            rid = (m.get("params") or {}).get("requestId")
            if rid in self.sent and not self.answers.get(rid):
                self.withdrawn.add(rid)
        self.send(m, t)

    def drain(self) -> None:
        """The recording is over: answer what still comes until the client closes stdin."""
        while True:
            try:
                msg = self.next_message()
            except Timeout:
                _say(f"the recording is over and the client kept stdin open for {self.timeout:g}s; stopping")
                return
            if msg is None:
                return
            if "method" not in msg and "id" in msg:
                self.on_reply(msg)
            elif "id" in msg:
                self.on_unscripted(msg, set())

    def die(self, f: dict) -> int:
        if self.pace and f.get("t") is not None:
            time.sleep(max(0.0, (f["t"] - self.last_t) * self.pace))
        sys.stderr.write((f.get("stderr") or "") + "\n")
        sys.stderr.flush()
        self.out.close()
        code = int(f.get("exit", 1))
        if self.verdict(final=False):
            return EXIT_ASSERT
        return code

    def verdict(self, final: bool) -> int:
        """`final`: the client closed — every request must be settled. Else only real breaches count."""
        breaches = list(self.breaches)
        if final:
            for rid, method in self.sent.items():
                if rid not in self.withdrawn and not self.answers.get(rid):
                    breaches.append(f"server request id={rid} ({method}) was never answered")
        for b in breaches:
            _say(f"ASSERT {b}")
        self._log({"verdict": {"sent": self.sent, "answers": self.answers, "withdrawn": sorted(self.withdrawn),
                               "breaches": breaches}})
        return EXIT_ASSERT if breaches else 0


def main(argv: list[str]) -> int:
    opts = _args(argv)
    if opts["version"]:
        print(VERSION)
        return 0
    if not opts["scenario"]:
        _say("no scenario: pass --scenario NAME|PATH or set FAKE_CODEX_SCENARIO")
        return EXIT_USAGE
    path = _scenario_path(opts["scenario"])
    try:
        frames = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as e:
        _say(f"cannot read scenario {path}: {e}")
        return EXIT_USAGE
    return Replay(frames, opts).run()


if __name__ == "__main__":
    code = main(sys.argv[1:])
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    # os._exit, not sys.exit: the stdin reader thread may still be blocked in a read, and a normal
    # interpreter shutdown then aborts (SIGABRT) on the stdin buffer's lock.
    os._exit(code)
