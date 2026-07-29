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
