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
    with _lock:
        _refusals.clear()
        _reading.clear()


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
