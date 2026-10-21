"""The REW dot's decision (#219): which colour and which words for what TCC last learned of REW.
Plain Python, no Qt — the window keeps one `RewProbe` (`rew_bridge`) and asks this for the rest.

REW has three states beside answering (audit T-2/T-3): down, answering an error, and a failure TCC
cannot place. Each was «offline» before, or — through the contract check's `reachable: true` over
a list REW answered with an error — green.
"""

from __future__ import annotations

from typing import Optional

from autosound_tcc.core import rew_bridge
from autosound_tcc.core.rew_bridge import RewProbe
from autosound_tcc.ui.tcc import i18n

#: The traffic-light class per state. Unknown is the neutral dot, as «not asked yet» is: nothing is
#: known in either. An error is not green: REW is there, and its answer is no use.
_DOTS = {rew_bridge.ONLINE: "done", rew_bridge.UNAVAILABLE: "bad",
         rew_bridge.ANSWERED_ERROR: "bad"}

#: The contract check's states (`contract.py cross_check_rew`) as TCC's.
_CONTRACT = {"unavailable": rew_bridge.UNAVAILABLE, "error": rew_bridge.ANSWERED_ERROR,
             "protocol": rew_bridge.ANSWERED_ERROR, "write_mismatch": rew_bridge.ANSWERED_ERROR}


def coerce(status) -> Optional[RewProbe]:
    """`status` as a `RewProbe`: one as it is, None as not asked yet, and a bool — the answer the
    window's callers gave before (#219) — as REW answering, or down."""
    if status is None or isinstance(status, RewProbe):
        return status
    return RewProbe(rew_bridge.ONLINE if status else rew_bridge.UNAVAILABLE)


def dot(status: Optional[RewProbe]) -> str:
    """The dot's class: `wait` until asked and for a state not known, `done` for REW answering,
    `bad` for REW down or answering an error."""
    return "wait" if status is None else _DOTS.get(status.state, "wait")


def tip(status: Optional[RewProbe]) -> str:
    """The dot's hover, in the current language: the state, and for an error or an unknown failure
    the failure's own words."""
    if status is None:
        return i18n.t("rewUncheckedTip")
    if status.state == rew_bridge.ONLINE:
        return i18n.t("rewOnlineTip")
    if status.state == rew_bridge.UNAVAILABLE:
        return i18n.t("rewOfflineTip")
    key = "rewErrorTip" if status.state == rew_bridge.ANSWERED_ERROR else "rewUnknownTip"
    return i18n.t(key).format(detail=status.detail)


def online(status: Optional[RewProbe]) -> Optional[bool]:
    """For the curve window (`rew_online`): True when REW answered, False when it is down — the
    one state its read waits out — and None for every other, where waiting mends nothing."""
    if status is None:
        return None
    return {rew_bridge.ONLINE: True, rew_bridge.UNAVAILABLE: False}.get(status.state)


def from_contract(rew: dict) -> Optional[RewProbe]:
    """The contract check's `rew` block (`ContractReport.rew()`) as a `RewProbe`, or None to leave
    the dot as it is: no block, or a check that asked REW nothing — `--no-rew`, an address that is
    none — whose note starts «skipped», as the method says for both.

    By its `state` (the method's v3.1.2): `reachable: true` is also REW answering its list with an
    error, or with something that is no list. With no state — a success, or a method before v3.1.2,
    which said `reachable: false` for any failure — `reachable: true` is REW answering, and anything
    else is not known."""
    if not rew:
        return None
    note = str(rew.get("note") or "")
    if note.startswith("skipped"):
        return None
    state = rew.get("state")
    if state is None and rew.get("reachable") is True:
        return RewProbe(rew_bridge.ONLINE)
    return RewProbe(_CONTRACT.get(state, rew_bridge.UNKNOWN), note)
