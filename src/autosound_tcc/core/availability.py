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

from autosound_tcc.core import codex_cli

NOT_INSTALLED = "not_installed"
#: Codex found but known older than `codex_cli.MIN_VERSION`: the detail is its version (tcc#181).
TOO_OLD = "too_old"
SIGN_IN = "sign_in"
LOCATION = "location"
REFUSED = "refused"
NOT_CHECKED = "not_checked"
PRIORITY = (NOT_INSTALLED, TOO_OLD, SIGN_IN, LOCATION, REFUSED, NOT_CHECKED)

#: For the agent, in `get_tcc_state` — English, like the rest of that payload.
PHRASES = {
    NOT_INSTALLED: "its CLI is not installed on this machine",
    TOO_OLD: "its CLI is too old for TCC: install TCC's own copy (Settings → Install Codex)",
    SIGN_IN: "not signed in to its own account on this machine (Claude or Codex)",
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
#: Keys that ANSWERED this launch — the reviewer picker's green (finding 55, tcc#58). Ready is only
#: "nothing known against it"; this is the one positive fact.
_answered: set[str] = set()
#: The pins a reviewer's last run set aside with its own model, as the method named them (tcc#113):
#: a model the run did NOT go as, so the footer and `get_tcc_state` can name a stale pin.
_set_aside: dict[str, list] = {}


def begin_reading(harnesses: Iterable[str]) -> None:
    with _lock:
        _reading.update(harnesses)


def finish_reading(harness: str) -> None:
    with _lock:
        _reading.discard(harness)


def refused(key: str, reason: str, detail: str = "") -> None:
    with _lock:
        _refusals[key] = (reason, detail)
        _answered.discard(key)


def succeeded(key: str) -> None:
    with _lock:
        _refusals.pop(key, None)
        _answered.add(key)


def answered(key: str) -> bool:
    """Whether a call to `key` came back with an answer this launch."""
    with _lock:
        return key in _answered


def set_aside(key: str, pins: list) -> None:
    """What `key`'s last run set aside; an empty list clears it — the pin was removed."""
    with _lock:
        if pins:
            _set_aside[key] = [dict(pin) for pin in pins]
        else:
            _set_aside.pop(key, None)


def pins_set_aside(key: str) -> list:
    """The pins `key`'s last run set aside, [] when none or not known."""
    with _lock:
        return [dict(pin) for pin in _set_aside.get(key, [])]


def forget_refusals(harness: Optional[str] = None) -> None:
    """Forget what refused this launch: every row (the reload button), or one route's rows.

    A key saved in «Ключ рецензента» answers the API rows' refusals and nothing else — a CLI's
    refusal is its login's or its region's, not the key's (finding 128, tcc#117)."""
    with _lock:
        if harness is None:
            _refusals.clear()
            return
        for key in [key for key in _refusals if key.startswith(f"{harness}:")]:
            del _refusals[key]


def forget_rows(belongs: Callable[[str], bool]) -> None:
    """Forget what the rows `belongs` picks out learned this launch, the refusal and the answer
    both: a key deleted in «Ключ рецензента» takes its own API rows' red and green with it, and
    nobody else's (tcc#127, review M3)."""
    with _lock:
        for key in [key for key in _refusals if belongs(key)]:
            del _refusals[key]
        for key in [key for key in _answered if belongs(key)]:
            _answered.discard(key)


def reset() -> None:
    """Everything back to a fresh launch. For tests."""
    global _startup
    with _lock:
        _refusals.clear()
        _reading.clear()
        _answered.clear()
        _set_aside.clear()
    _startup = None


def status(choice, *, signed_in: Optional[Callable[[], Optional[bool]]] = None,
           unconfirmed: Optional[Callable[[object], bool]] = None,
           reviewer: bool = False,
           codex_signed_in: Optional[Callable[[], Optional[bool]]] = None) -> Status:
    """Ready, or the most serious reason it is not (see `PRIORITY`).

    `reviewer`: the choice is judged as a reviewer's, whose Claude child runs without
    `ANTHROPIC_API_KEY` (tcc#127) — only the login signs it in (`claude_sdk.signed_in`).

    Codex's login is `codex_cli.signed_in()`, which the start's read fills with the model list
    (one app-server, after agy and the SDK) and ↻ again; only a False is «sign in»."""
    if codex_signed_in is None:
        codex_signed_in = codex_cli.signed_in
    if signed_in is None:
        from autosound_tcc.core import claude_sdk

        def signed_in() -> Optional[bool]:
            return claude_sdk.signed_in(reviewer=reviewer)
    if unconfirmed is None:
        from autosound_tcc.core import model_choices
        unconfirmed = model_choices.unconfirmed
    found: list[tuple[str, str]] = []
    if not getattr(choice, "available", True):
        found.append(_codex_too_old() if choice.harness == "codex" else (NOT_INSTALLED, ""))
    if choice.harness == "sdk" and signed_in() is False:
        found.append((SIGN_IN, ""))
    if choice.harness == "codex" and codex_signed_in() is False:
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


def _codex_too_old() -> tuple[str, str]:
    """Why a Codex row cannot run: found and known too old — with its version — or not found.
    Cached readings only (`codex_cli.too_old`): the pickers ask on the GUI thread (tcc#181, the
    Arbiter's Windows pass: a 0.152.0 read «not installed»)."""
    found = codex_cli.find()
    if codex_cli.too_old(found):
        return TOO_OLD, codex_cli.version_text(codex_cli.known_version(found))
    return NOT_INSTALLED, ""


def record_reviewer_outcome(key: str, result, *, reaches=None) -> None:
    """One reviewer call's outcome into the state: an answer clears a refusal, a refusal sets one,
    and the pins the run set aside replace the last run's (tcc#113).

    A clipboard package for a vendor this machine has no transport for is the designed fallback and
    records nothing; so does a project that is not ready to be reviewed yet."""
    from autosound_tcc.core import critic, model_choices

    if not key:
        return
    # None when the run named no model by the flag, or never ran: nothing learned either way.
    pins = getattr(result, "pins_set_aside", None)
    if pins is not None:
        set_aside(key, pins)
    if result.ok:
        succeeded(key)
        return
    # `choose_model` for a model that WAS named: its route does not serve it — `gemini-2.5-flash`
    # came back 404 that way and TCC went on calling the reviewer ready (finding 85, tcc#74).
    if result.mode not in (critic.MODE_CLIPBOARD, critic.MODE_REFUSED, critic.MODE_CHOOSE_MODEL):
        return
    harness, _, model = key.partition(":")
    choice = model_choices.Choice(harness=harness or "omp", model=model or key, label=key)
    if not (reaches or model_choices.critic_reaches)(choice):
        return
    reason = critic.refusal_reason(result.detail)
    if result.mode == critic.MODE_CHOOSE_MODEL:
        reason = reason or REFUSED
    if reason == LOCATION:
        # The CLI's own line, kept: the sentence around it — the model, the route, what that route
        # offers instead — is said in the person's language by `availability_view.detail` (hub #262).
        refused(key, reason, _own_line(result.detail, critic._LOCATION_WORDS)
                or critic.remedy(result.detail, harness=harness))
    elif reason:
        # The detail is what a tooltip shows: the one thing to do when it can be named, the CLI's
        # own words when it cannot.
        refused(key, reason, critic.remedy(result.detail, harness=harness) or result.detail)


def _own_line(detail: str, words) -> str:
    """The line of a CLI's refusal that says the region — as it said it."""
    return next((line.strip() for line in (detail or "").splitlines()
                 if any(word in line.lower() for word in words)), "")


def being_read(harness: str) -> bool:
    """Whether `harness`'s list is still being read — the Claude rows while `claude`'s own list is
    (`sdk-cli`) too. A row missing then is «not read yet», never «gone» (the group review)."""
    with _lock:
        return harness in _reading or (harness == "sdk" and "sdk-cli" in _reading)


#: How long a Windows start waits inside its console for the catalogues (the Arbiter, 2026-09-13).
STARTUP_MODELS_CAP_S = 8.0
#: What the start's read asks: agy and the API's Claude list first, each finished the moment its
#: own answer is in; then Codex's list and `claude`'s (`sdk-cli`), after them, so a slow one holds
#: nothing else (the group review). `sdk-cli` is no harness: it only keeps a Claude row missing
#: from the shipped list from reading as «gone» while `claude` is asked (`being_read`).
_STARTUP_HARNESSES = ("agy", "sdk", "codex", "sdk-cli")
_startup: "Optional[StartupReading]" = None


def read_catalogues() -> None:
    """Ask every CLI now, forced: a CLI installed since the last start is noticed on this one.

    A harness is finished only once its own read came back. One that raises stays NOT_CHECKED —
    nothing answered for it — and the exception goes up to `StartupReading`, which logs it; a
    successful ↻ read settles it later (spec: Error handling)."""
    from autosound_tcc.core import claude_sdk, model_choices

    begin_reading(_STARTUP_HARNESSES)

    def done(route: str) -> None:
        if route == "agy":
            finish_reading("agy")

    model_choices.refresh_cli_catalogue(force=True, cli_lists=False, done=done)
    finish_reading("agy")  # settled by its own fetch already; here for a read that skipped it
    claude_sdk.probe_signed_in(force=True)
    finish_reading("sdk")
    # Not forced: Codex once per launch, `claude` only when its binary changed (a console per
    # start on Windows otherwise); ↻ asks both again.
    model_choices.ask_cli_lists()
    finish_reading("codex")
    finish_reading("sdk-cli")


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
