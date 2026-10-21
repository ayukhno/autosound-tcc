"""The REW dot's decision, out of the window (`ui/tcc/rew_status.py`, #219): which colour and which
words for what TCC last learned of REW — the probe's state, a read's, or the contract check's
`rew` block. Plain Python: what the person sees on the dot is decided here."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from autosound_tcc.core import rew_bridge
from autosound_tcc.core.rew_bridge import RewProbe
from autosound_tcc.ui.tcc import i18n, rew_status

_ERROR = RewProbe(rew_bridge.ANSWERED_ERROR, "HTTPError: HTTP Error 500: Internal Server Error")
_UNKNOWN = RewProbe(rew_bridge.UNKNOWN, "ConnectionRefusedError: no REW listening")


@pytest.mark.parametrize(("status", "dot"), [
    (None, "wait"),
    (RewProbe(rew_bridge.ONLINE), "done"),
    (RewProbe(rew_bridge.UNAVAILABLE, "RewUnavailable: refused"), "bad"),
    (_ERROR, "bad"),
    (_UNKNOWN, "wait"),
])
def test_only_rew_that_answered_is_green(status, dot):
    """REW answering an error was green or red by luck of the call: the dot said REW's list was
    read when it was not, or that REW was down while it was answering. Green is REW answering."""
    assert rew_status.dot(status) == dot


def test_each_state_has_its_own_words_on_the_dot():
    """Down says what it always said (start REW, the API is in the beta builds); an error names
    what REW answered; a failure TCC cannot place says it is not known, with the failure itself."""
    assert rew_status.tip(RewProbe(rew_bridge.ONLINE)) == i18n.t("rewOnlineTip")
    assert rew_status.tip(RewProbe(rew_bridge.UNAVAILABLE, "x")) == i18n.t("rewOfflineTip")
    assert rew_status.tip(_ERROR) == i18n.t("rewErrorTip").format(detail=_ERROR.detail)
    assert rew_status.tip(_UNKNOWN) == i18n.t("rewUnknownTip").format(detail=_UNKNOWN.detail)
    assert rew_status.tip(None) == i18n.t("rewUncheckedTip")
    assert len({rew_status.tip(s) for s in (None, _ERROR, _UNKNOWN)}) == 3


def test_the_curve_window_waits_for_rew_only_when_rew_is_down():
    """`rew_online()` False holds the curve window's read until REW is back: only for REW down."""
    assert rew_status.online(RewProbe(rew_bridge.ONLINE)) is True
    assert rew_status.online(RewProbe(rew_bridge.UNAVAILABLE)) is False
    assert rew_status.online(_ERROR) is None
    assert rew_status.online(_UNKNOWN) is None
    assert rew_status.online(None) is None


@pytest.mark.parametrize(("rew", "state"), [
    ({"reachable": True}, rew_bridge.ONLINE),
    ({"reachable": False, "state": "unavailable", "note": "REW not reachable (x) -- skipped"},
     rew_bridge.UNAVAILABLE),
    ({"reachable": True, "state": "error",
      "note": "REW answered with an error (HTTP Error 500) -- its measurement list was not read; "
              "skipped"}, rew_bridge.ANSWERED_ERROR),
    ({"reachable": True, "state": "protocol",
      "note": "REW answered something that is not a measurement list (x) -- skipped"},
     rew_bridge.ANSWERED_ERROR),
    # A method before v3.1.2 said `reachable: false` for any failure, with no state.
    ({"reachable": False, "note": "REW not reachable (boom) -- skipped"}, rew_bridge.UNKNOWN),
])
def test_the_contract_checks_rew_block_is_read_by_its_state(rew, state):
    """#219: the check's `rew.state` was never read — `reachable` alone, and the method says
    `reachable: true` for REW answering its list with an error: the dot went green over a list
    that was not read."""
    said = rew_status.from_contract(rew)
    assert said is not None and said.state == state
    if state != rew_bridge.ONLINE:
        assert said.detail == rew["note"]


@pytest.mark.parametrize("rew", [
    {}, {"reachable": False, "note": "skipped (--no-rew)"},
    {"reachable": None, "state": "config", "note": "skipped: REW was not asked -- no address"},
])
def test_a_contract_check_that_did_not_ask_rew_leaves_the_dot_alone(rew):
    """`--no-rew`, an address that is none: nothing was asked, so nothing is learned."""
    assert rew_status.from_contract(rew) is None


def test_the_old_answer_still_reads():
    """A bool from a caller of before (a test, an older signal) reads as it meant: answered, or
    down."""
    assert rew_status.coerce(True) == RewProbe(rew_bridge.ONLINE)
    assert rew_status.coerce(False) == RewProbe(rew_bridge.UNAVAILABLE)
    assert rew_status.coerce(_ERROR) is _ERROR and rew_status.coerce(None) is None


class _Dot:
    def __init__(self) -> None:
        self.status = self.tip = None

    def set_status(self, status) -> None:
        self.status = status

    def setToolTip(self, tip) -> None:  # noqa: N802 — Qt's name
        self.tip = tip


def _host(**extra):
    from autosound_tcc.ui.tcc.main_window import MainWindow

    dots = [_Dot(), _Dot()]
    host = SimpleNamespace(_rew_online=None, _curve_dialog=None, _rew_dots=lambda: iter(dots),
                           **extra)
    host._retip_rew_dots = lambda: MainWindow._retip_rew_dots(host)
    host._set_rew_online = lambda status: MainWindow._set_rew_online(host, status)
    return host, dots


def test_the_window_shows_rew_answering_an_error_on_both_dots():
    """Both dots, one state: an error is not green, and its words are on both."""
    host, dots = _host()
    host._set_rew_online(_ERROR)
    assert {(d.status, d.tip) for d in dots} == {
        ("bad", i18n.t("rewErrorTip").format(detail=_ERROR.detail))}


def test_a_contract_check_whose_rew_answered_an_error_does_not_turn_the_dot_green(monkeypatch):
    """The diagnostics' own REW answer reaches the dot by its state (#219)."""
    from autosound_tcc.core.contract_check import ContractReport
    from autosound_tcc.ui.tcc.main_window import MainWindow

    told = []
    host, dots = _host(_diag_dialog=None, _status_strip=SimpleNamespace(
        notify=lambda *a, **k: told.append(a)))
    report = ContractReport(ok=True, project_dir="/p", cross_checks={"rew": {
        "reachable": True, "state": "error",
        "note": "REW answered with an error (HTTP Error 500) -- its measurement list was not "
                "read; skipped"}})
    MainWindow._on_contract_result(host, report)
    assert {d.status for d in dots} == {"bad"}


def test_the_ping_carries_the_state_it_met():
    """The timer's probe hands the window the state, not a yes or no."""
    from autosound_tcc.ui.tcc.workers import _RewPingWorker

    class _Bridge:
        def probe(self):
            return _ERROR

    worker = _RewPingWorker(_Bridge())
    heard = []
    worker.result.connect(heard.append)
    worker.run()
    assert heard == [_ERROR]

