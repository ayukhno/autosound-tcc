"""The half of the noise test that needs a real model — run this on your own machine,
where your CLI is already authenticated. Nothing here holds credentials.

Drives one real turn through `opencode serve` against a real project, captures the whole
event stream, and reports what the turn actually left behind:

  * how much of the stream is renderable prose vs. tool chatter vs. neither
  * which `process/journal.jsonl` events the turn wrote (the (б) question — did the skill
    record the process, or only narrate it?)
  * the prompt floor, for comparison with the stub measurements

    opencode serve --port 4096 &
    python spike/real_turn.py <project_dir> --model anthropic/claude-opus-5 \
        --prompt "Resume this tuning project. Read state from disk, then tell me where we are."

Then render what it left:  python spike/render_dialog.py <project_dir> -o /tmp/real.html
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

T0 = time.time()


def log(*parts: object) -> None:
    print(f"[{time.time() - T0:6.2f}s]", *parts, flush=True)


def call(base: str, method: str, path: str, body: dict | None = None, timeout: float = 600.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        # The body is the whole diagnostic — a bare "HTTP 500" says nothing about
        # which model id or provider the server actually rejected.
        detail = exc.read().decode(errors="replace")[:1200]
        raise SystemExit(f"{method} {path} -> HTTP {exc.code}\n{detail}") from None
    return json.loads(raw) if raw.strip() else {}


def known_models(base: str) -> list[str]:
    """`providerID/modelID` pairs this server can actually reach, for the error path."""
    try:
        data = call(base, "GET", "/config/providers", timeout=20.0)
    except SystemExit:
        return []
    out = []
    for prov in data.get("providers", []) or []:
        pid = prov.get("id")
        for mid in (prov.get("models") or {}):
            out.append(f"{pid}/{mid}")
    return out


def turn_finished(base: str, sid: str) -> dict | None:
    """The last assistant message once nothing is still in flight, else None.

    A real turn on a big skill runs well past any sane socket timeout, so the POST
    that started it is not the thing to wait on — the session is.
    """
    try:
        msgs = call(base, "GET", f"/session/{sid}/message", timeout=30.0)
    except (SystemExit, socket.timeout, urllib.error.URLError):
        return None
    if not msgs:
        return None
    running = any((part.get("state") or {}).get("status") == "running"
                  for msg in msgs for part in (msg.get("parts") or [])
                  if part.get("type") == "tool")
    last = msgs[-1].get("info", {}) or {}
    if running or last.get("role") != "assistant" or not (last.get("time", {}) or {}).get("completed"):
        return None
    return msgs[-1]


def read_journal(project: Path) -> list[dict]:
    path = project / "process" / "journal.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--model", required=True, help="providerID/modelID, e.g. anthropic/claude-opus-5")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--base", default="http://127.0.0.1:4096")
    ap.add_argument("--out", type=Path, default=Path("/tmp/spike/real-turn.jsonl"))
    ap.add_argument("--timeout", type=float, default=1800.0,
                    help="seconds to wait on one turn; a cold skill run can pass 10 min")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    before = len(read_journal(args.project))
    kinds: Counter[str] = Counter()
    prose_chars = {"n": 0}
    permissions: list[dict] = []
    assistant_ids: set[str] = set()
    stop = threading.Event()

    def events() -> None:
        req = urllib.request.Request(args.base + "/event")
        with urllib.request.urlopen(req, timeout=900) as stream, \
                args.out.open("w", encoding="utf-8") as sink:
            for raw in stream:
                if stop.is_set():
                    return
                line = raw.decode(errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                sink.write(line[5:].strip() + "\n")
                try:
                    ev = json.loads(line[5:].strip())
                except ValueError:
                    continue
                kind = ev.get("type", "")
                kinds[kind] += 1
                props = ev.get("properties", {})
                if kind == "permission.asked":
                    permissions.append(props)
                    log("PERMISSION ASKED:", props.get("permission"),
                        json.dumps(props.get("metadata", {}))[:120],
                        "-> answer it in the UI, or POST /permission/<id>/reply {\"reply\":\"once\"}")
                info = props.get("info", {})
                if kind == "message.updated" and info.get("role") == "assistant":
                    assistant_ids.add(info.get("id"))
                part = props.get("part", {})
                # Only the assistant's own text counts as prose — an earlier version
                # measured the user's prompt and reported it as model output.
                if part.get("type") == "text" and part.get("messageID") in assistant_ids:
                    prose_chars["n"] = max(prose_chars["n"], len(part.get("text", "")))
                elif part.get("type") == "tool":
                    state = (part.get("state") or {}).get("status")
                    if state == "completed":
                        log("tool:", part.get("tool"))

    threading.Thread(target=events, daemon=True).start()
    time.sleep(0.8)

    session = call(args.base, "POST", "/session", {})
    sid = session.get("id")
    log("session", sid, "· project", args.project)
    provider, _, model = args.model.partition("/")
    available = known_models(args.base)
    if available and args.model not in available:
        hits = [m for m in available if model.split("-")[0] in m] or available[:25]
        raise SystemExit(f"{args.model!r} is not one of this server's models.\n"
                         f"Closest: {', '.join(hits[:25])}")
    log("prompting…")
    try:
        result = call(args.base, "POST", f"/session/{sid}/message",
                      {"model": {"providerID": provider, "modelID": model},
                       "parts": [{"type": "text", "text": args.prompt}]},
                      timeout=args.timeout)
    except socket.timeout:
        # The turn is server-side; only our read of it expired. Losing the report
        # here once already cost a full run, so fall back to polling the session.
        log(f"POST timed out after {args.timeout:.0f}s — turn is still on the server, polling…")
        deadline = time.time() + args.timeout
        result = None
        while result is None and time.time() < deadline:
            time.sleep(10)
            result = turn_finished(args.base, sid)
        if result is None:
            log("still unfinished at the deadline — reporting what exists so far")
            result = {}
    time.sleep(1.5)
    stop.set()

    after = read_journal(args.project)
    new = after[before:]
    tokens = (result.get("info", {}) or {}).get("tokens", {})

    print("\n=== turn ===")
    print("tokens:", json.dumps(tokens))
    print("event kinds:", json.dumps(dict(kinds.most_common(12)), indent=None))
    print("longest prose block:", prose_chars["n"], "chars")
    print("permission prompts:", len(permissions))
    print(f"\n=== journal events written by this turn: {len(new)} ===")
    for ev in new:
        print("  ", ev.get("type"), json.dumps({k: v for k, v in ev.items()
                                                if k not in ("at", "type")})[:140])
    if not new:
        print("  (none — the turn narrated the process without recording it; that is the gap)")
    print(f"\nstream saved to {args.out}")


if __name__ == "__main__":
    main()
