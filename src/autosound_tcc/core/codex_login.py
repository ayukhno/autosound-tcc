"""Signing in to Codex from a TCC button (W-10, tcc#181, task 9).

The Arbiter (2026-10-14): every user under their own Codex account, signed in by a TCC button that
opens the browser. One `codex app-server` (`codex_rpc.AppServer`, spawned on the native binary
`codex_cli.usable()` names — never a shim) carries the whole exchange:

* `begin()` — `account/login/start {"type": "chatgpt"}`; the `authUrl` the window opens in the
  browser (`QDesktopServices.openUrl`, the UI's job). Codex listens for the browser's answer on a
  fixed port, `127.0.0.1:1455` («Learned in task 1»); a port another program holds is refused by
  Codex itself, and its own sentence is `SignInError`'s.
* `wait(timeout)` — until `account/login/completed`: its `success`, its `error` kept as the
  sentence (`error`). After a success the login and the model list are read afresh
  (`codex_cli.forget()` and a forced `probe()`), on the same worker.
* `cancel()` — `account/login/cancel` for the login started; any thread, never blocking.
* `close()` — idempotent; a login still pending is cancelled first, then the child is closed and
  reaped (`AppServer.close`: stdin, grace, terminate, `child.kill_tree`).

Qt-free and synchronous: the exchange runs on an event loop of its own, in a thread of its own, so
a worker can block in `wait()` and still hear `cancelled()`. **Worker thread only** for `begin`,
`wait` and `close`.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import Any, Callable, Optional

from autosound_tcc.core import app_log, child, codex_cli, codex_rpc

#: Starting app-server and getting the address back.
BEGIN_TIMEOUT_S = 30.0
#: How long a person may take in the browser.
WAIT_TIMEOUT_S = 600.0
#: How often `wait` looks at its caller's `cancelled()`.
POLL_S = 0.1
#: The cancel's own answer, and the `completed` that follows it.
CANCEL_TIMEOUT_S = 5.0


class SignInError(Exception):
    """The sign-in could not start; the text is the one sentence the person reads (Codex's own
    when Codex refused)."""


def binary() -> str:
    """The native Codex the sign-in spawns, or `SignInError`."""
    found = codex_cli.usable()
    if found is None:
        raise SignInError("Codex is not installed (or is too old) on this computer")
    return found.path


class SignIn:
    """One sign-in: `begin`, then `wait` (or `cancel`), then `close`."""

    def __init__(self) -> None:
        self.url = ""
        #: Why it did not succeed: Codex's own sentence, or TCC's for a timeout.
        self.error = ""
        #: A cancel was asked for (the button, or the window closing).
        self.cancelled = False
        #: The app-server, for a look at its exit after `close()`.
        self.server: Optional[codex_rpc.AppServer] = None
        self._login_id: Optional[str] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._completed: Optional[asyncio.Future] = None
        self._cancel_sent = False
        self._finished = False
        self._closed = False
        self._lock = threading.Lock()

    # --- the loop ------------------------------------------------------------------------------

    def _start_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.new_event_loop()
        ready = threading.Event()

        def run() -> None:
            asyncio.set_event_loop(loop)
            loop.call_soon(ready.set)
            loop.run_forever()

        self._thread = threading.Thread(target=run, name="tcc-codex-sign-in", daemon=True)
        self._thread.start()
        ready.wait()
        self._loop = loop
        return loop

    def _run(self, coro, timeout: float) -> Any:
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError(f"no answer in {timeout:g} s") from None

    # --- begin -----------------------------------------------------------------------------------

    def begin(self, timeout: float = BEGIN_TIMEOUT_S) -> str:
        """Start the sign-in; the address to open in the browser. `SignInError` with a sentence
        when Codex is missing, does not start, or refuses (a busy callback port)."""
        path = binary()
        self._start_loop()
        try:
            self.url = self._run(self._begin(path, timeout), timeout + 5.0)
        except SignInError:
            self.close()
            raise
        except (codex_rpc.ConnectionLost, TimeoutError, OSError) as exc:
            self.close()
            raise SignInError(f"Codex did not start the sign-in: {exc}") from exc
        return self.url

    async def _begin(self, path: str, timeout: float) -> str:
        loop = asyncio.get_running_loop()
        self._completed = loop.create_future()
        self.server = codex_rpc.AppServer([path, "app-server"], spawn_kwargs=child.flags(),
                                          on_notification=self._on_notification)
        await self.server.open(timeout=timeout)
        asyncio.ensure_future(self._watch_end(self.server, self._completed))
        try:
            reply = await self.server.request("account/login/start", {"type": "chatgpt"},
                                              timeout=timeout)
        except codex_rpc.RpcError as exc:
            raise SignInError(exc.message or f"Codex refused the sign-in ({exc.code})") from exc
        url = reply.get("authUrl") if isinstance(reply, dict) else None
        if not url:
            raise SignInError("Codex started a sign-in but gave no address to open")
        self._login_id = reply.get("loginId")
        return str(url)

    def _on_notification(self, msg: dict) -> None:
        """In the reader: the `completed` for this login settles `wait`."""
        if msg.get("method") != "account/login/completed":
            return
        params = msg.get("params") or {}
        theirs = params.get("loginId")
        if self._login_id and theirs and theirs != self._login_id:
            return
        if self._completed is not None and not self._completed.done():
            self._completed.set_result(params)

    @staticmethod
    async def _watch_end(server: codex_rpc.AppServer, completed: asyncio.Future) -> None:
        """Codex ending before it said how the sign-in went is a failure, with its last words."""
        while True:
            item = await server.notifications.get()
            if item is None:
                break
        if not completed.done():
            tail = server.stderr_tail.strip().splitlines()
            completed.set_result({"success": False,
                                  "error": "Codex ended before the sign-in finished"
                                           + (f": {tail[-1]}" if tail else "")})

    # --- wait ------------------------------------------------------------------------------------

    def wait(self, timeout: float = WAIT_TIMEOUT_S,
             cancelled: Callable[[], bool] = lambda: False) -> bool:
        """Block until Codex says how the sign-in ended: True on success. `cancelled()` is read
        every `POLL_S`; when it says so the sign-in is cancelled and this returns False. After a
        success the login and the models are read again (`codex_cli.forget` + `probe(force=True)`).
        The app-server is closed before this returns."""
        if self._loop is None or self._completed is None:
            raise SignInError("the sign-in was not started")
        done = asyncio.run_coroutine_threadsafe(self._await_completed(), self._loop)
        deadline = timeout
        waited = 0.0
        params: dict = {}
        try:
            while True:
                try:
                    params = done.result(POLL_S)
                    break
                except concurrent.futures.TimeoutError:
                    waited += POLL_S
                if cancelled() and not self.cancelled:
                    self.cancel()
                if waited >= deadline and not self._cancel_sent:
                    self.error = f"the sign-in was not finished in {int(timeout // 60)} min"
                    self._send_cancel()
                if waited >= deadline + CANCEL_TIMEOUT_S:
                    done.cancel()
                    break
        finally:
            self._finished = True
            self.close()
        success = bool(params.get("success"))
        if not success and not self.error and not self.cancelled:
            self.error = str(params.get("error") or "Codex said the sign-in did not succeed")
        if success:
            self.error = ""
            # Found again and asked again; the versions already read are kept — a wipe made
            # `find()` answer an old Codex on PATH until the probe ended (task 9's review, M1).
            codex_cli.forget()
            try:
                codex_cli.probe(force=True)
            except Exception as exc:  # noqa: BLE001 — the sign-in succeeded whatever the re-read says
                app_log.logger().warning("codex sign-in: done, but the probe after it failed: %s: %s",
                                         type(exc).__name__, exc)
        app_log.logger().info("codex sign-in: %s", "done" if success else
                              "cancelled" if self.cancelled else f"failed ({self.error})")
        return success

    async def _await_completed(self) -> dict:
        assert self._completed is not None
        return await asyncio.shield(self._completed)

    # --- cancel and close ----------------------------------------------------------------------

    def cancel(self) -> None:
        """Ask Codex to drop the sign-in. Any thread; returns at once; once only."""
        self.cancelled = True
        self._send_cancel()

    def _send_cancel(self) -> None:
        with self._lock:
            if self._cancel_sent or self._loop is None or self._loop.is_closed():
                return
            if self._completed is not None and self._completed.done():
                return
            self._cancel_sent = True
        asyncio.run_coroutine_threadsafe(self._cancel(), self._loop)

    async def _cancel(self) -> None:
        server = self.server
        if server is None or server.ended or not self._login_id:
            return
        try:
            await server.request("account/login/cancel", {"loginId": self._login_id},
                                 timeout=CANCEL_TIMEOUT_S)
        except (codex_rpc.RpcError, codex_rpc.ConnectionLost, TimeoutError) as exc:
            app_log.logger().warning("codex sign-in: the cancel was not answered: %s", exc)

    def close(self) -> None:
        """Cancel a pending sign-in, close the app-server, stop the loop. Idempotent."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        loop = self._loop
        if loop is None:
            return
        try:
            self._run(self._close(), CANCEL_TIMEOUT_S + child.REAP_TIMEOUT_S + 10.0)
        except (TimeoutError, RuntimeError, codex_rpc.ConnectionLost) as exc:
            app_log.logger().warning("codex sign-in: close did not finish: %s", exc)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            if self._thread is not None:
                self._thread.join(5.0)
            if not loop.is_running():
                loop.close()

    async def _close(self) -> None:
        pending = self._completed is not None and not self._completed.done()
        if pending and self._login_id and not self._cancel_sent:
            self._cancel_sent = True
            self.cancelled = True
            await self._cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._completed), CANCEL_TIMEOUT_S)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001 — closing regardless
                pass
        if self.server is not None:
            await self.server.close(grace=child.REAP_TIMEOUT_S)
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()


__all__ = ["SignIn", "SignInError", "binary"]
