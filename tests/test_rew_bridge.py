"""RewBridge.is_reachable() -- the REW-online dot's connectivity probe (core/rew_bridge.py)."""

from __future__ import annotations

from autosound_tcc.core.rew_bridge import RewBridge


class _FakeApi:
    def __init__(self, measurements=None, raise_exc=None):
        self._measurements = measurements or {}
        self._raise = raise_exc

    def get_measurements(self):
        if self._raise is not None:
            raise self._raise
        return self._measurements


def test_is_reachable_true_when_the_call_succeeds():
    bridge = RewBridge(api=_FakeApi(measurements={"0": {"title": "x"}}))
    assert bridge.is_reachable() is True


def test_is_reachable_true_even_with_zero_measurements():
    """An empty response still means REW answered -- offline is a connection failure, not an
    empty project."""
    bridge = RewBridge(api=_FakeApi(measurements={}))
    assert bridge.is_reachable() is True


def test_is_reachable_false_on_any_exception():
    bridge = RewBridge(api=_FakeApi(raise_exc=ConnectionRefusedError("no REW listening")))
    assert bridge.is_reachable() is False


def test_a_curve_read_names_its_smoothing_and_a_read_without_one_takes_the_view():
    """hub #155 §2 (method v3.0.54): a reader asks REW for a smoothing on the read (`?smoothing=`);
    with none it gets whatever the Arbiter's view of that measurement holds."""
    class _Api:
        FINEST_SMOOTHING = "1/48"

        def __init__(self):
            self.asked = []

        def get_fr(self, mid, smoothing=None):
            self.asked.append(("fr", mid, smoothing))
            return [], [], None

        def get_group_delay(self, mid, smoothing=None):
            self.asked.append(("gd", mid, smoothing))
            return [], []

    api = _Api()
    bridge = RewBridge(api=api)

    bridge.frequency_response("7", smoothing=bridge.FINEST_SMOOTHING)
    bridge.group_delay("7", smoothing="1/12")
    bridge.frequency_response("8")

    assert api.asked == [("fr", "7", "1/48"), ("gd", "7", "1/12"), ("fr", "8", None)]


def test_a_method_older_than_named_smoothing_still_answers():
    """A method before v3.0.54 reads the view only; asking it for a smoothing must not fail the read."""
    class _OldApi:
        def get_fr(self, mid):
            return ["old"], [], None

    bridge = RewBridge(api=_OldApi())

    assert bridge.frequency_response("7", smoothing="1/48")[0] == ["old"]
    assert bridge.FINEST_SMOOTHING == "1/48"

