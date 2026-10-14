"""The one JSON-RPC client over stdio for `codex app-server` (W-10, tcc#181).

Shared by the session, the model list and sign-in. Qt-free; async, on the caller's asyncio loop.

* `AppServer` — one long-lived `codex app-server`: `open()` (`initialize` with `experimentalApi`,
  then `initialized`), `request()`, `notify()`, `respond()` — the ONLY writer of answers to the
  server's own requests, and it refuses a second answer to one id and an answer after the server
  withdrew the request (`serverRequest/resolved`). Notifications arrive in order on
  `notifications`; None there means the process ended.
* `ask()` / `ask_blocking()` — one-shot exchanges (the model list, a probe): spawn, open, the calls
  in order with stdin held open until the last reply (`codex app-server` 0.162.1 exits at stdin's
  end before it answers), close.

The wire: binary pipes, one frame per line, `json.dumps(...).encode() + b"\\n"` — never a `\\r`, on
Windows too. Lines are read with a large limit (a `thread/resume` reply runs past asyncio's 64 KiB)
and decoded as strict UTF-8 one at a time; a line that is not UTF-8 or not JSON is logged and
skipped, never fatal. stderr is drained all the time (a full pipe would stall the server) and its
last lines are kept for the reason a failure gives.
"""

from __future__ import annotations

import asyncio
import collections
import inspect
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence, Union

from autosound_tcc import __version__
from autosound_tcc.core import app_log, child

#: One frame is one line; a resumed thread's history is far longer than asyncio's 64 KiB default.
FRAME_LIMIT_BYTES = 64 * 1024 * 1024
#: How many stderr lines are kept for a failure's reason.
STDERR_LINES = 20
#: The frame log stops growing here (one closing line says so).
LOG_CAP_BYTES = 8 * 1024 * 1024
#: How long `open()` waits for `initialize` by default.
OPEN_TIMEOUT_S = 30.0
#: The text a secret is replaced with in the frame log.
REDACTED = "<redacted>"

CLIENT_INFO = {"name": "autosound-tcc", "title": "Autosound TCC", "version": __version__}

#: JSON-RPC's own codes, for answers TCC gives the server.
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603


class RpcError(Exception):
    """The server answered a request with a JSON-RPC error."""

    def __init__(self, code: Any, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def __repr__(self) -> str:
        return f"RpcError({self.code!r}, {self.message!r})"


class ConnectionLost(Exception):
    """The process could not start, or ended (stdout closed) before the answer came."""

    def __init__(self, message: str, *, returncode: Optional[int] = None,
                 stderr_tail: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr_tail = stderr_tail


@dataclass(frozen=True)
class Notify:
    """A notification among `ask()`'s calls; a request is a plain `(method, params)` pair."""

    method: str
    params: Optional[dict] = None


Call = Union[Notify, tuple]
OnRequest = Callable[[dict], Any]


class _FrameLog:
    """JSONL of every frame both ways, capped, secrets replaced. Never raises."""

    def __init__(self, path: Union[str, Path, None], secrets: Sequence[str], cap: int) -> None:
        self.path = Path(path) if path else None
        # Longest first, so a secret that contains another is replaced whole. Both spellings: the
        # raw value and its JSON-escaped form (a token with `"` or `\` in it).
        forms = set()
        for s in secrets:
            if s:
                forms.add(s)
                forms.add(json.dumps(s)[1:-1])
        self.secrets = sorted(forms, key=len, reverse=True)
        self.cap = cap
        self.written = 0
        self.full = False

    def redact(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, REDACTED)
        return text

    def write(self, direction: str, payload: Any) -> None:
        if self.path is None or self.full:
            return
        try:
            line = self.redact(json.dumps({"t": round(time.time(), 3), "dir": direction,
                                           "msg": payload}, ensure_ascii=False)) + "\n"
            data = line.encode("utf-8")
            if self.written + len(data) > self.cap:
                self.full = True
                data = (json.dumps({"dir": "note", "msg": f"log cap of {self.cap} bytes reached; "
                                                          f"no more frames written"}) + "\n").encode()
            with self.path.open("ab") as fh:
                fh.write(data)
            self.written += len(data)
        except Exception:  # noqa: BLE001 — a log that fails must not take the session with it
            pass


class AppServer:
    """One `codex app-server` process and the JSON-RPC conversation with it."""

    def __init__(self, argv: Sequence[str], *, cwd: Union[str, Path, None] = None,
                 env: Optional[dict] = None, spawn_kwargs: Optional[dict] = None,
                 log: Union[str, Path, None] = None, on_request: Optional[OnRequest] = None,
                 secret_env: Iterable[str] = (), log_cap: int = LOG_CAP_BYTES) -> None:
        self.argv = list(argv)
        self.cwd = str(cwd) if cwd is not None else None
        self.env = env
        self.spawn_kwargs = dict(spawn_kwargs or {})
        self.on_request = on_request
        source = env if env is not None else os.environ
        self._log = _FrameLog(log, [source.get(name, "") for name in secret_env], log_cap)
        self.notifications: asyncio.Queue = asyncio.Queue()
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._stderr: collections.deque = collections.deque(maxlen=STDERR_LINES)
        self._next_id = 0
        self._pending: dict = {}       # our request id -> Future
        self._open: dict = {}          # server request id -> method, still unanswered
        self._answered: set = set()    # server request ids answered
        self._withdrawn: dict = {}     # server request id -> was it still pending when withdrawn
        self._tasks: set = set()       # on_request coroutines in flight
        self._write_lock = asyncio.Lock()
        self._ended = False
        self._lost: Optional[ConnectionLost] = None
        self._closing: Optional[asyncio.Task] = None

    # --- state ---------------------------------------------------------------------------------

    @property
    def stderr_tail(self) -> str:
        """The last stderr lines (up to `STDERR_LINES`), newest last."""
        return "\n".join(self._stderr)

    @property
    def returncode(self) -> Optional[int]:
        return self._proc.returncode if self._proc is not None else None

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc is not None else None

    @property
    def ended(self) -> bool:
        return self._ended

    def _note(self, message: str, *args) -> None:
        app_log.logger().warning("codex_rpc: " + message, *args)
        self._log.write("note", message % args if args else message)

    # --- start -----------------------------------------------------------------------------------

    async def open(self, timeout: float = OPEN_TIMEOUT_S) -> dict:
        """Spawn, `initialize`, `initialized`; the `initialize` result. An end before the answer
        (a bad `-c` makes app-server exit 1 at start) is `ConnectionLost` with the stderr tail."""
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self.argv, cwd=self.cwd, env=self.env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, limit=FRAME_LIMIT_BYTES, **self.spawn_kwargs)
        except OSError as exc:
            self._ended = True
            self.notifications.put_nowait(None)
            raise ConnectionLost(f"cannot start {self.argv[0] if self.argv else '?'}: {exc}") from exc
        self._log.write("note", {"argv": [self._log.redact(a) for a in self.argv]})
        self._stderr_task = asyncio.ensure_future(self._drain_stderr())
        self._reader = asyncio.ensure_future(self._read_frames())
        try:
            result = await self.request("initialize", {
                "clientInfo": CLIENT_INFO, "capabilities": {"experimentalApi": True}},
                timeout=timeout)
            await self.notify("initialized")
        except BaseException:
            await self.close(grace=0.5)
            raise
        return result

    # --- writing ---------------------------------------------------------------------------------

    def _write(self, msg: dict) -> bool:
        """One frame out, without waiting. False when the pipe is gone."""
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdin.is_closing() or self._ended:
            return False
        frame = {"jsonrpc": "2.0", **msg}
        self._log.write("out", frame)
        try:
            proc.stdin.write(json.dumps(frame).encode("utf-8") + b"\n")
        except (OSError, RuntimeError):
            return False
        return True

    async def _send(self, msg: dict) -> None:
        if not self._write(msg):
            raise self._lost_error("before the frame could be sent")
        try:
            async with self._write_lock:
                await self._proc.stdin.drain()  # type: ignore[union-attr]
        except (OSError, RuntimeError) as exc:
            raise self._lost_error(f"while writing ({exc})") from exc

    async def request(self, method: str, params: Optional[dict] = None,
                      timeout: float = 60.0) -> dict:
        """Send a request and wait for its answer: the `result`, `RpcError`, `ConnectionLost`, or
        `TimeoutError` after `timeout` seconds (the request is then forgotten)."""
        if self._ended:
            raise self._lost_error("before the request")
        rid = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[rid] = future
        msg: dict = {"id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        try:
            await self._send(msg)
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"{method}: no answer in {timeout:g} s") from None
        finally:
            self._pending.pop(rid, None)

    async def notify(self, method: str, params: Optional[dict] = None) -> None:
        msg: dict = {"method": method}
        if params is not None:
            msg["params"] = params
        await self._send(msg)

    def respond(self, rid: Any, result: Any = None, error: Optional[dict] = None) -> bool:
        """Answer the server's request `rid` — the only way an answer is written. Refused (False,
        logged): a second answer, an answer after `serverRequest/resolved`, an id never received,
        and any answer once the process has ended."""
        if rid in self._answered:
            self._note("a second answer to server request %r refused", rid)
            return False
        if rid in self._withdrawn:
            self._note("an answer to server request %r refused: the server withdrew it", rid)
            return False
        if rid not in self._open:
            self._note("an answer to server request %r refused: no such request", rid)
            return False
        msg: dict = {"id": rid}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = {} if result is None else result
        if not self._write(msg):
            self._note("an answer to server request %r not sent: the process has ended", rid)
            return False
        del self._open[rid]
        self._answered.add(rid)
        return True

    def resolved(self, rid: Any) -> bool:
        """The server withdrew request `rid`: True only if it was still unanswered (the dialog
        should go); False for one already answered or withdrawn — `serverRequest/resolved` also
        arrives for those. Either way no answer to `rid` is written after this.

        The reader calls this itself the moment `serverRequest/resolved` arrives, so a gate that
        finishes later cannot answer a withdrawn request; the session reads the outcome from
        `withdrawn(rid)`."""
        if rid in self._open:
            del self._open[rid]
            self._withdrawn[rid] = True
            return True
        self._withdrawn.setdefault(rid, False)
        return False

    def withdrawn(self, rid: Any) -> bool:
        """Whether `serverRequest/resolved` took `rid` back while it was still pending."""
        return bool(self._withdrawn.get(rid))

    # --- reading ---------------------------------------------------------------------------------

    async def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        rest = b""
        try:
            while True:
                chunk = await proc.stderr.read(65536)
                if not chunk:
                    break
                rest += chunk
                *lines, rest = rest.split(b"\n")
                for raw in lines:
                    self._keep_stderr(raw)
                if len(rest) > 65536:
                    self._keep_stderr(rest)
                    rest = b""
        except (OSError, asyncio.CancelledError):
            pass
        if rest:
            self._keep_stderr(rest)

    def _keep_stderr(self, raw: bytes) -> None:
        line = raw.decode("utf-8", "replace").rstrip()
        if line:
            self._stderr.append(line[:2000])

    async def _read_frames(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        try:
            while True:
                try:
                    raw = await proc.stdout.readline()
                except ValueError as exc:  # a line past FRAME_LIMIT_BYTES: dropped, the rest read
                    self._note("a frame over the line limit skipped: %s", exc)
                    continue
                if not raw:
                    break
                self._take_line(raw)
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            await self._on_end()

    def _take_line(self, raw: bytes) -> None:
        raw = raw.rstrip(b"\r\n")
        if not raw.strip():
            return
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            self._note("a line that is not UTF-8 skipped (%s)", exc)
            return
        try:
            msg = json.loads(text)
        except ValueError:
            self._note("a line that is not JSON skipped: %s", text[:200])
            return
        if not isinstance(msg, dict):
            self._note("a JSON line that is not an object skipped: %s", text[:200])
            return
        self._log.write("in", msg)
        if "method" in msg and "id" in msg:
            self._on_server_request(msg)
        elif "method" in msg:
            if msg.get("method") == "serverRequest/resolved":
                rid = (msg.get("params") or {}).get("requestId")
                self.resolved(rid)
            self.notifications.put_nowait(msg)
        elif "id" in msg:
            future = self._pending.get(msg["id"])
            if future is None or future.done():
                self._note("an answer to request %r nobody waits for", msg.get("id"))
                return
            error = msg.get("error")
            if error is not None:
                if isinstance(error, dict):
                    future.set_exception(RpcError(error.get("code"), str(error.get("message", "")),
                                                  error.get("data")))
                else:
                    future.set_exception(RpcError(None, str(error)))
            else:
                result = msg.get("result")
                future.set_result(result if isinstance(result, dict) else {})

    def _on_server_request(self, msg: dict) -> None:
        rid, method = msg["id"], msg["method"]
        if rid in self._open or rid in self._answered:
            self._note("server request id %r (%s) arrived again; ignored", rid, method)
            return
        self._open[rid] = method
        if self.on_request is None:
            self.respond(rid, error={"code": METHOD_NOT_FOUND,
                                     "message": f"TCC does not handle {method}"})
            return
        try:
            outcome = self.on_request(msg)
        except Exception as exc:  # noqa: BLE001 — the handler's failure must not stop the reader
            self._handler_failed(rid, method, exc)
            return
        if inspect.isawaitable(outcome):
            task = asyncio.ensure_future(outcome)
            self._tasks.add(task)

            def done(t: asyncio.Task) -> None:
                self._tasks.discard(t)
                if not t.cancelled() and t.exception() is not None:
                    self._handler_failed(rid, method, t.exception())

            task.add_done_callback(done)

    def _handler_failed(self, rid: Any, method: str, exc: BaseException) -> None:
        self._note("the handler of server request %r (%s) failed: %r", rid, method, exc)
        if rid in self._open:
            self.respond(rid, error={"code": INTERNAL_ERROR, "message": f"TCC failed: {exc}"})

    async def _on_end(self) -> None:
        """stdout closed: let stderr and the exit code arrive, then fail what waits."""
        self._ended = True
        if self._stderr_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._stderr_task), 1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._proc is not None and self._proc.returncode is None:
            try:
                await asyncio.wait_for(asyncio.shield(self._proc.wait()), 1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._lost = self._lost_error("before it answered")
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(self._lost)
        self._log.write("note", {"ended": self.returncode, "stderr": self._log.redact(self.stderr_tail)})
        self.notifications.put_nowait(None)

    def _lost_error(self, when: str) -> ConnectionLost:
        if self._lost is not None:
            return self._lost
        code = self.returncode
        said = f"ended (exit {code})" if code is not None else "closed its output"
        tail = self.stderr_tail
        last = "\n".join(tail.splitlines()[-5:])
        message = f"{said} {when}" + (f": {last}" if last else "")
        return ConnectionLost(message, returncode=code, stderr_tail=tail)

    # --- stop ------------------------------------------------------------------------------------

    async def close(self, grace: float = 5.0) -> None:
        """Close stdin, give the process `grace` seconds to leave, then terminate it and kill its
        tree (`child.kill_tree`). Idempotent; a second call waits for the first."""
        if self._closing is None:
            self._closing = asyncio.ensure_future(self._close(grace))
        await asyncio.shield(self._closing)

    async def _close(self, grace: float) -> None:
        proc = self._proc
        for task in list(self._tasks):
            task.cancel()
        if proc is not None:
            try:
                if proc.stdin is not None and not proc.stdin.is_closing():
                    proc.stdin.close()
            except (OSError, RuntimeError):
                pass
            if not await self._waited(proc, grace):
                if sys.platform.startswith("win"):
                    # `terminate()` is TerminateProcess there: the tree walk needs the parent alive.
                    child.kill_tree(proc)  # type: ignore[arg-type]
                else:
                    try:
                        proc.terminate()
                    except (OSError, ProcessLookupError):
                        pass
                    if not await self._waited(proc, min(grace, 2.0)):
                        child.kill_tree(proc)  # type: ignore[arg-type]
                await self._waited(proc, child.REAP_TIMEOUT_S)
        for task in (self._reader, self._stderr_task):
            if task is None:
                continue
            try:
                await asyncio.wait_for(asyncio.shield(task), 2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
                task.cancel()
        if self._reader is None and not self._ended:
            self._ended = True
            self.notifications.put_nowait(None)

    @staticmethod
    async def _waited(proc: asyncio.subprocess.Process, seconds: float) -> bool:
        if proc.returncode is not None:
            return True
        try:
            await asyncio.wait_for(proc.wait(), max(seconds, 0.0))
            return True
        except asyncio.TimeoutError:
            return False


async def ask(binary: str, calls: Sequence[Call], *, timeout: float, cwd=None, env=None,
              args: Sequence[str] = ()) -> list:
    """One-shot: `binary app-server *args`, open, `calls` in order, close. A call is
    `(method, params)` for a request or `Notify(method, params)`; the list has one entry per call —
    the request's result dict or its `RpcError`, `{}` for a notification. `timeout` bounds the
    whole exchange (`TimeoutError`); an end before the answers is `ConnectionLost`."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    server = AppServer([binary, "app-server", *args], cwd=cwd, env=env,
                       spawn_kwargs=child.flags())
    try:
        await server.open(timeout=timeout)
        out: list = []
        for call in calls:
            if isinstance(call, Notify):
                await server.notify(call.method, call.params)
                out.append({})
                continue
            method, params = call
            left = deadline - loop.time()
            if left <= 0:
                raise TimeoutError(f"{method}: no time left of {timeout:g} s")
            try:
                out.append(await server.request(method, params, timeout=left))
            except RpcError as exc:
                out.append(exc)
        return out
    finally:
        await server.close(grace=child.REAP_TIMEOUT_S)


def ask_blocking(binary: str, calls: Sequence[Call], *, timeout: float, cwd=None, env=None,
                 args: Sequence[str] = ()) -> list:
    """`ask()` for a worker thread with no event loop of its own."""
    return asyncio.run(ask(binary, calls, timeout=timeout, cwd=cwd, env=env, args=args))
