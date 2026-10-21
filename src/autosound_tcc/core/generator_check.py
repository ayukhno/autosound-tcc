"""Whether the main AI's picked model answers on this login — checked when it is picked, as the
Critic's is (finding 160, tcc#222).

The Critic's check is a real call: a short `ask`, a green frame when it answered. The main AI's
routes each have a cheaper question that runs no model and bills nothing, and it is asked of the
lists TCC already keeps (`model_choices`) and the logins `availability` already reads — no second
cache and no second registry; this unit only decides:

* **Claude (SDK)** — `claude auth status`, then the person's own `claude` lists its models for
  this login (the SDK's `initialize` control request, answered before any turn).
* **Codex** — one `codex app-server`: `account/read` and `model/list` for this login.
* **omp** — no such question: `omp models` lists every provider's catalogue, not what this login
  runs. Said as «not checked», never drawn green.

No Qt here: the worker calls `run` off the GUI thread, the window shows `shown`, and `Checks` says
which answer belongs to the pick on screen — a later answer for an earlier pick is dropped.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from autosound_tcc.core import availability, claude_sdk, codex_cli, model_choices

#: The routes `run` can ask without running a model.
CHECKABLE = ("sdk", "codex")

LISTED = "listed"
NOT_LISTED = "not_listed"
SIGN_IN = availability.SIGN_IN
#: The route was asked and gave no list: why is the detail.
UNREAD = "unread"
#: The list came with rows that could not be read, and the pick is not among those that could:
#: it may be one of the others, so it is neither listed nor refused (the group review).
PARTIAL = "partial"
NOT_CHECKED = availability.NOT_CHECKED


@dataclass(frozen=True)
class Result:
    key: str
    state: str
    detail: str = ""
    at: float = 0.0


def run(choice) -> Result:
    """Ask `choice`'s route whether this login offers it. **Worker thread only.** The answer goes
    into the shared lists and logins first, so the pickers read it from where they always do."""
    key, at = choice.key, time.time()
    if choice.harness not in CHECKABLE:
        return Result(key, NOT_CHECKED, at=at)
    if choice.harness == "sdk":
        claude_sdk.probe_signed_in(force=True)
        if claude_sdk.signed_in() is False:
            return Result(key, SIGN_IN, at=at)
    rows, why = model_choices.read_route_list(choice.harness)
    if choice.harness == "codex" and codex_cli.signed_in() is False:
        return Result(key, SIGN_IN, at=at)
    if not rows:
        return Result(key, UNREAD, why, at)
    if any(row.model == choice.model for row in rows):
        return Result(key, LISTED, at=at)
    return Result(key, PARTIAL if model_choices.read_in_part(choice.harness) else NOT_LISTED, at=at)


@dataclass(frozen=True)
class Shown:
    """What the line beside the picker says: `note` and `tip` are i18n keys formatted with
    `args`; `frame` is the picker's own tint — "ok" (green), "missing" (red) or "" (plain)."""

    note: str = ""
    tip: str = ""
    args: dict = field(default_factory=dict)
    frame: str = ""


def shown(choice, result: Optional[Result], checking: bool) -> Shown:
    """The line for the pick on screen. Nothing before a pick was made; «checking» while asked."""
    if choice is None:
        return Shown()
    args = {"model": choice.model, "route": choice.route}
    if choice.harness not in CHECKABLE:
        return Shown("mainCheckNotChecked", "mainCheckNoWayTip", args)
    if checking:
        return Shown("mainCheckChecking", "mainCheckCheckingTip", args)
    if result is None or result.key != choice.key:
        return Shown()
    args["time"] = time.strftime("%H:%M", time.localtime(result.at))
    if result.state == LISTED:
        return Shown("mainCheckListed", "mainCheckListedTip", args, "ok")
    if result.state == NOT_LISTED:
        return Shown("mainCheckNotListed", "mainCheckNotListedTip", args, "missing")
    if result.state == SIGN_IN:
        return Shown("availPhraseSignIn", "mainCheckSignInTip", args, "missing")
    if result.state == PARTIAL:
        return Shown("mainCheckNotChecked", "mainCheckPartialTip", args)
    args["why"] = result.detail or "?"
    return Shown("mainCheckNotChecked", "mainCheckUnreadTip", args)


class Checks:
    """One check at a time, and only the pick on screen's answer kept.

    `picked` says which key to start a check for now (None: nothing to ask, or one is running —
    then the newest pick is asked when it ends, `ended`). `answered` keeps a result only when it is
    for the pick still on screen: a slow answer for an earlier pick must not paint the new one.

    A check runs from its start to its thread's end (`ended`), not to its answer: the answer comes
    at `done`, with the thread still unwinding until `finished`, and a pick between the two started
    a second thread and dropped the first one's last reference (the group review)."""

    def __init__(self) -> None:
        self.running = ""
        #: The key whose answer is still to come — the line says «checking» for it.
        self.asking = ""
        self.waiting = False
        self.result: Optional[Result] = None
        #: The running check's answer was kept for the pick on screen.
        self._kept = False

    def picked(self, choice) -> Optional[str]:
        if choice is None or choice.harness not in CHECKABLE:
            return None
        if self.running:
            self.waiting = True
            return None
        self.running = self.asking = choice.key
        self._kept = False
        return choice.key

    def checking(self, choice) -> bool:
        return choice is not None and (self.asking == choice.key or (
            self.waiting and choice.harness in CHECKABLE))

    def answered(self, result: Result, current: Optional[str]) -> bool:
        self.asking = ""
        if result.key != current:
            return False
        self.result = result
        self._kept = True
        return True

    def ended(self, choice) -> Optional[str]:
        """The check's thread is over: the pick that waited for it, if any, to ask now."""
        self.running = ""
        kept, self._kept = self._kept, False
        if not self.waiting:
            return None
        self.waiting = False
        if kept and choice is not None and self.result.key == choice.key:
            return None  # the answer that just came in was this pick's — not one from before
        return self.picked(choice)
