"""What can run on this machine right now, and in one word why not.

One place answers it, so the pickers, the reviewer footer and `get_tcc_state` cannot disagree
(spec: docs/superpowers/specs/2026-09-13-model-availability-design.md). Most of the answer already
exists elsewhere — whether the CLI is installed (`Choice.available`), whether Claude is signed in
(`claude_sdk.signed_in`), whether an entry was only remembered (`model_choices.unconfirmed`). This
unit owns the two facts nothing else holds: what refused this launch, and what is still being read.

In memory, for this launch only: a refusal stays red until the next start, a successful call, or
the reload button. No `ui` import — words for people live in `ui/tcc/availability_view.py`.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

NOT_INSTALLED = "not_installed"
SIGN_IN = "sign_in"
LOCATION = "location"
REFUSED = "refused"
NOT_CHECKED = "not_checked"
PRIORITY = (NOT_INSTALLED, SIGN_IN, LOCATION, REFUSED, NOT_CHECKED)

#: For the agent, in `get_tcc_state` — English, like the rest of that payload.
PHRASES = {
    NOT_INSTALLED: "its CLI is not installed on this machine",
    SIGN_IN: "not signed in to Claude on this machine",
    LOCATION: "not available in your region",
    REFUSED: "the last call to it was refused",
    NOT_CHECKED: "not checked yet since TCC started",
}


@dataclass(frozen=True)
class Status:
    ready: bool
    reason: Optional[str] = None
    detail: str = ""


_lock = threading.Lock()
_refusals: dict[str, tuple[str, str]] = {}
_reading: set[str] = set()


def begin_reading(harnesses: Iterable[str]) -> None:
    with _lock:
        _reading.update(harnesses)


def finish_reading(harness: str) -> None:
    with _lock:
        _reading.discard(harness)


def refused(key: str, reason: str, detail: str = "") -> None:
    with _lock:
        _refusals[key] = (reason, detail)


def succeeded(key: str) -> None:
    with _lock:
        _refusals.pop(key, None)


def forget_refusals() -> None:
    with _lock:
        _refusals.clear()


def reset() -> None:
    """Everything back to a fresh launch. For tests."""
    global _startup
    with _lock:
        _refusals.clear()
        _reading.clear()
    _startup = None


def status(choice, *, signed_in: Optional[Callable[[], Optional[bool]]] = None,
           unconfirmed: Optional[Callable[[object], bool]] = None) -> Status:
    """Ready, or the most serious reason it is not (see `PRIORITY`)."""
    if signed_in is None:
        from autosound_tcc.core import claude_sdk
        signed_in = claude_sdk.signed_in
    if unconfirmed is None:
        from autosound_tcc.core import model_choices
        unconfirmed = model_choices.unconfirmed
    found: list[tuple[str, str]] = []
    if not getattr(choice, "available", True):
        found.append((NOT_INSTALLED, ""))
    if choice.harness == "sdk" and signed_in() is False:
        found.append((SIGN_IN, ""))
    with _lock:
        refusal = _refusals.get(choice.key)
        being_read = choice.harness in _reading
    if refusal:
        found.append(refusal)
    if being_read or unconfirmed(choice):
        found.append((NOT_CHECKED, ""))
    if not found:
        return Status(True)
    reason, detail = min(found, key=lambda item: PRIORITY.index(item[0]))
    return Status(False, reason, detail)


def record_reviewer_outcome(key: str, result, *, reaches=None) -> None:
    """One reviewer call's outcome into the state: an answer clears a refusal, a refusal sets one.

    A clipboard package for a vendor this machine has no transport for is the designed fallback and
    records nothing; so does a project that is not ready to be reviewed yet."""
    from autosound_tcc.core import critic, model_choices

    if not key:
        return
    if result.ok:
        succeeded(key)
        return
    if result.mode != critic.MODE_CLIPBOARD:
        return
    harness, _, model = key.partition(":")
    choice = model_choices.Choice(harness=harness or "omp", model=model or key, label=key)
    if not (reaches or model_choices.critic_reaches)(choice):
        return
    reason = critic.refusal_reason(result.detail)
    if reason:
        # The detail is what a tooltip shows: the one thing to do when it can be named, the CLI's
        # own words when it cannot.
        refused(key, reason, critic.remedy(result.detail, harness=harness) or result.detail)


#: How long a Windows start waits inside its console for the catalogues (the Arbiter, 2026-09-13).
STARTUP_MODELS_CAP_S = 8.0
#: What the start's read asks. Not codex: it is found through PATH when a picker is filled, and a
#: harness marked as being read that the read never asks stays "not checked" until it is over.
_STARTUP_HARNESSES = ("agy", "sdk")
_startup: "Optional[StartupReading]" = None


def read_catalogues() -> None:
    """Ask every CLI now, forced: a CLI installed since the last start is noticed on this one.

    A harness is finished only once its own read came back. One that raises stays NOT_CHECKED —
    nothing answered for it — and the exception goes up to `StartupReading`, which logs it; a
    successful ↻ read settles it later (spec: Error handling)."""
    from autosound_tcc.core import claude_sdk, model_choices

    begin_reading(_STARTUP_HARNESSES)
    model_choices.refresh_cli_catalogue(force=True)
    finish_reading("agy")
    claude_sdk.probe_signed_in(force=True)
    finish_reading("sdk")


class StartupReading:
    """The start's catalogue read, on its own thread, with an event that says it is over."""

    def __init__(self, read=None) -> None:
        self._read = read or read_catalogues
        self.done = threading.Event()

    def start(self) -> "StartupReading":
        threading.Thread(target=self._run, name="tcc-read-models", daemon=True).start()
        return self

    def _run(self) -> None:
        try:
            self._read()
        except Exception:  # noqa: BLE001 — a failed read leaves models red, never a failed start
            logging.getLogger("autosound_tcc").exception("startup model reading failed")
        finally:
            self.done.set()

    def wait(self, cap: float) -> bool:
        return self.done.wait(cap)


def start_startup_reading(read=None) -> StartupReading:
    global _startup
    _startup = StartupReading(read)
    return _startup


def startup_reading() -> Optional[StartupReading]:
    return _startup
