"""RewBridge.probe() -- the REW dot's probe, and REW's states read off the method's exceptions
(core/rew_bridge.py, #219)."""

from __future__ import annotations

import functools
from types import SimpleNamespace

import pytest

from autosound_tcc.core.rew_bridge import RewBridge


@pytest.fixture(autouse=True)
def _rews_state_not_learned_yet(monkeypatch):
    """Each test starts with nothing learned of REW: an unknown failure is logged once per change
    (`probe_of`), and the failure another test left would decide this one's log."""
    from autosound_tcc.core import rew_bridge

    monkeypatch.setattr(rew_bridge, "_last_failure", None)


class _FakeApi:
    def __init__(self, measurements=None, raise_exc=None):
        self._measurements = measurements or {}
        self._raise = raise_exc

    def get_measurements(self):
        if self._raise is not None:
            raise self._raise
        return self._measurements


def _rew_api():
    """The method's own `rew_api`, loaded as TCC loads it: by path, a namespaced copy — so its
    classes are never TCC's, and only `rew_state` on them tells REW's states apart (#219)."""
    from autosound_tcc.core import vendor_loader

    return vendor_loader.load_rew_api()


def test_a_probe_that_answers_is_online_even_with_zero_measurements():
    """An empty list still means REW answered: offline is REW not answering, not an empty project."""
    from autosound_tcc.core import rew_bridge

    for held in ({"0": {"title": "x"}}, {}):
        assert RewBridge(api=_FakeApi(measurements=held)).probe() == rew_bridge.RewProbe(
            rew_bridge.ONLINE)


def _http_error(code=500, said="Internal Server Error"):
    import urllib.error

    return urllib.error.HTTPError("http://localhost:4735/measurements", code, said, {}, None)


def _url_error():
    import urllib.error

    return urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))


@pytest.mark.parametrize(("raised", "state"), [
    (lambda api: api.RewUnavailable("connection refused", "http://localhost:4735"), "unavailable"),
    (lambda api: _http_error(), "error"),
    (lambda api: api.RewProtocolError("REW answered something that is not JSON"), "error"),
    (lambda api: api.RewWriteMismatch("slot 3 came back at 0 dB"), "error"),
    (lambda api: api.RewAddressError("REW_API_URL 'localhost' is no address"), "config"),
    # The standard library's transport errors, from a copy with no `rew_state` (the group review
    # of #219, G): REW down, as before #219 — never «unknown».
    (lambda api: _url_error(), "unavailable"),
    (lambda api: ConnectionRefusedError("no REW listening"), "unavailable"),
    (lambda api: TimeoutError("timed out"), "unavailable"),
    (lambda api: RuntimeError("a bug in the reader"), "unknown"),
])
def test_a_probe_says_which_of_rews_states_it_met(raised, state):
    """#219 (audit T-2/T-3): REW down, REW answering an error and a failure TCC cannot place were
    all «offline» — `is_reachable` read any exception as REW not running. The state is read off the
    method's class (`rew_state`; TCC's copy is namespaced, so never by `isinstance` on the
    method's classes); REW's 4xx/5xx is the standard library's own `HTTPError`, which carries none;
    and a failure with no state is «unknown», never «not running»."""
    exc = raised(_rew_api())
    probe = RewBridge(api=_FakeApi(raise_exc=exc)).probe()
    assert probe.state == state
    assert str(exc) in probe.detail


def test_a_probe_that_cannot_place_a_failure_logs_it(caplog):
    """«Unknown» is not a quiet state: the failure goes to the log whole, with its traceback, since
    the dot's words alone cannot say what it was."""
    import logging

    with caplog.at_level(logging.WARNING):
        RewBridge(api=_FakeApi(raise_exc=RuntimeError("a bug in the reader"))).probe()
    assert any("a bug in the reader" in r.getMessage() and r.exc_info for r in caplog.records)


def test_an_unknown_failure_is_logged_once_per_change_of_state(caplog):
    """The group review of #219, H: the ping asks REW every 30 s, and an «unknown» failure went to
    the log whole, traceback and all, on every ping. Once when REW's state becomes unknown; again
    only after it has been another."""
    import logging

    unknown = RewBridge(api=_FakeApi(raise_exc=RuntimeError("a bug in the reader")))
    with caplog.at_level(logging.WARNING):
        unknown.probe()
        unknown.probe()
        RewBridge(api=_FakeApi(measurements={})).probe()  # REW answered
        unknown.probe()
        unknown.probe()
    said = [r for r in caplog.records if "a bug in the reader" in r.getMessage()]
    assert len(said) == 2, [r.getMessage() for r in said]


def test_an_unknown_failure_of_another_kind_is_logged_and_a_scan_s_answer_resets(caplog):
    """W-11's final review, M2: the scan, an import and a rename ask REW too. After one unknown
    failure, another of a different kind went unlogged until a ping succeeded — and a scan that
    REW answered did not count as REW answering."""
    import logging

    from autosound_tcc.core import rew_bridge

    def met(exc):
        rew_bridge.probe_of(exc)  # as the scan, import and rename workers hand a failure on

    with caplog.at_level(logging.WARNING):
        met(RuntimeError("a bug in the reader"))
        met(ValueError("a bug in the import"))
        RewBridge(api=_FakeApi(measurements={})).measurements()  # the scan, answered
        met(ValueError("a bug in the import"))
    said = [r.getMessage() for r in caplog.records if "not known" in r.getMessage()]
    assert len(said) == 3, said
    assert "a bug in the import" in said[1]


def test_a_missing_state_is_unknown_never_not_found():
    """A method before v3.1.2 has no `rew_state`: its KeyError for a title is no proof the title is
    missing (`state_of` reads capability, never a version)."""
    from autosound_tcc.core import rew_bridge

    assert rew_bridge.method_state(KeyError("No measurement titled 'x'")) is None
    assert rew_bridge.status_of(KeyError("No measurement titled 'x'")) == rew_bridge.UNKNOWN
    assert rew_bridge.method_state(_rew_api().MeasurementNotFound("No measurement titled 'x'")) \
        == "not_found"


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

