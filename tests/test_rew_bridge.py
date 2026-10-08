"""RewBridge.is_reachable() -- the REW-online dot's connectivity probe (core/rew_bridge.py)."""

from __future__ import annotations

import functools
from types import SimpleNamespace

import pytest

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


def _counted(reader):
    """`reader`, with every call that reaches it written down — one it refuses as well, which a
    record kept inside the reader never sees. `functools.wraps` keeps the signature the bridge
    reads: `inspect.signature` follows `__wrapped__`."""
    calls: list = []

    @functools.wraps(reader)
    def door(*args, **kwargs):
        calls.append((args, kwargs))
        return reader(*args, **kwargs)

    door.calls = calls
    return door


def test_a_method_older_than_named_smoothing_still_answers():
    """A method before v3.0.54 reads the view only; asking it for a smoothing must not fail the
    read. It is read by what it declares (#170 F16-3): called once, without the smoothing — not
    asked first, refused, and asked again."""
    api = SimpleNamespace(get_fr=_counted(lambda mid: (["old"], [], None)))
    bridge = RewBridge(api=api)

    assert bridge.frequency_response("7", smoothing="1/48")[0] == ["old"]
    assert api.get_fr.calls == [(("7",), {})]
    assert bridge.FINEST_SMOOTHING == "1/48"


@pytest.mark.parametrize(("read", "reader"), [("frequency_response", "get_fr"),
                                              ("group_delay", "get_group_delay")])
def test_a_type_error_inside_a_reader_that_takes_smoothing_is_its_own(read, reader):
    """#170 F16-3: a reader that takes `smoothing` and fails INSIDE with a TypeError was taken for
    a method too old to take it — the error swallowed and the read made again without the
    smoothing, so the curve came back at the view's level as if it were the one asked for. The
    error is the reader's: it goes up, and the reader was called once."""
    def inside(mid, smoothing=None):
        if smoothing is not None:
            raise TypeError("unsupported operand type(s) for /: 'str' and 'int'")
        return ["the view's"], [], None

    api = SimpleNamespace(**{reader: _counted(inside)})

    with pytest.raises(TypeError, match="unsupported operand"):
        getattr(RewBridge(api=api), read)("7", smoothing="1/48")
    assert getattr(api, reader).calls == [(("7",), {"smoothing": "1/48"})]


def test_a_reader_that_takes_any_keyword_is_asked_for_the_smoothing():
    """`**kwargs` takes `smoothing` as surely as a parameter of that name does."""
    api = SimpleNamespace(get_fr=_counted(lambda mid, **_kw: ([], [], None)))

    RewBridge(api=api).frequency_response("7", smoothing="1/48")

    assert api.get_fr.calls == [(("7",), {"smoothing": "1/48"})]


class _Unreadable:
    """A reader `inspect.signature` cannot read — `__signature__` that is no signature (its
    TypeError) — answering whatever it is asked."""

    __signature__ = 42

    def __init__(self):
        self.calls: list = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return [], [], None


def _behind_a_builtin():
    """A reader with a builtin behind it — `max`, which has no signature to read (its ValueError)."""
    @functools.wraps(max)
    def door(*args, **kwargs):
        door.calls.append((args, kwargs))
        return [], [], None

    door.calls = []
    return door


@pytest.mark.parametrize("unreadable", [_Unreadable, _behind_a_builtin],
                         ids=["type-error", "value-error"])
def test_a_reader_whose_signature_cannot_be_read_is_asked_for_the_smoothing(unreadable):
    """A builtin or a C function: `inspect.signature` cannot say whether it takes `smoothing`. It
    is asked for it — the read either is the one asked for, or fails out loud; the other guess
    reads the view and passes it off as the asked smoothing without a word."""
    reader = unreadable()

    RewBridge(api=SimpleNamespace(get_fr=reader)).frequency_response("7", smoothing="1/48")

    assert reader.calls == [(("7",), {"smoothing": "1/48"})]

