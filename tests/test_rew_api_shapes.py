"""Wire-shape guard for the vendored `rew_api` write endpoints.

TCC's `write_rew_filters` MCP tool and its measurement panel both write to REW through this
module, and every bug it has had was a *shape* bug that a live REW rejects (or, worse, accepts and
silently ignores):

* `set_filters` PUT a bare array -- REW answers `400 Expected BEGIN_OBJECT but was BEGIN_ARRAY`;
* `set_equaliser` sent `{"name": ...}` -- REW answers `400 No manufacturer in the request`;
* a filter using `gain` instead of `gaindB` is accepted with a 200 and stored at **0 dB**, so a
  proposed cut silently becomes a flat filter.

None of those needs a running REW to catch: they are visible in the request the module builds. The
shapes asserted here were verified against a live REW on 2026-07-28 and match what the skill's own
`references/tooling/rew-api-quirks.md` §"Writing filters" documents -- these tests exist so the
code cannot drift away from that research again.
"""

from __future__ import annotations

import json

import pytest

from autosound_tcc.core import vendor_loader

pytestmark = pytest.mark.skipif(
    not vendor_loader.is_available(), reason="rew_tool submodule not checked out"
)


@pytest.fixture
def rew(monkeypatch):
    """The vendored module with its HTTP layer replaced by a recorder.

    Patches `urllib.request.urlopen` inside the module rather than its `_get`/`_post`/`_put`
    helpers, so the verb, path and JSON body a real REW would receive are all observable.
    """
    api = vendor_loader.load_rew_api()
    sent: list[dict] = []

    class _Response:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=None):
        if isinstance(req, str):  # a GET built from a bare URL
            sent.append({"method": "GET", "url": req, "body": None, "timeout": timeout})
            return _Response(b"[]")
        body = req.data.decode() if req.data else None
        sent.append(
            {
                "method": req.get_method(),
                "url": req.full_url,
                "body": json.loads(body) if body else None,
                "timeout": timeout,
            }
        )
        return _Response(b'{"message": "ok"}')

    monkeypatch.setattr(api.urllib.request, "urlopen", fake_urlopen)
    return api, sent


def test_every_call_carries_a_timeout(rew):
    """No timeout means an unreachable REW hangs the caller -- fatal from a Qt thread."""
    api, sent = rew

    api.get_filters(1)
    api.set_filters(1, [{"index": 1, "type": "None", "enabled": True}])

    assert all(call["timeout"] for call in sent)
    assert api._TIMEOUT_S <= 10


def test_set_filters_posts_an_object_not_a_bare_array(rew):
    """The original bug: REW rejects a bare array with `Expected BEGIN_OBJECT but was BEGIN_ARRAY`."""
    api, sent = rew
    bands = [{"index": 1, "type": "PK", "enabled": True, "frequency": 1000.0, "gaindB": -3.0, "q": 2.0}]

    api.set_filters(7, bands)

    call = sent[-1]
    assert call["method"] == "POST"
    assert call["url"].endswith("/measurements/7/filters")
    assert isinstance(call["body"], dict), "a bare array is rejected at REW's JSON layer"
    assert call["body"] == {"filters": bands}


def test_set_filter_puts_a_single_filter_object(rew):
    """The per-slot form: PUT on the same path takes one FilterSetting, not a collection."""
    api, sent = rew
    band = {"index": 3, "type": "PK", "enabled": True, "frequency": 500.0, "gaindB": 2.0, "q": 1.0}

    api.set_filter(7, band)

    call = sent[-1]
    assert call["method"] == "PUT"
    assert call["url"].endswith("/measurements/7/filters")
    assert call["body"] == band


def test_set_equaliser_sends_manufacturer_and_model(rew):
    """A bare name is answered with `400 No manufacturer in the request`."""
    api, sent = rew

    api.set_equaliser(2, "Generic", "Extended")

    call = sent[-1]
    assert call["method"] == "POST"
    assert call["url"].endswith("/measurements/2/equaliser")
    assert call["body"] == {"manufacturer": "Generic", "model": "Extended"}
    assert "name" not in call["body"]


def test_rename_measurement_puts_the_title(rew):
    api, sent = rew

    api.rename_measurement(4, "c_01 (sw) noXO")

    call = sent[-1]
    assert call["method"] == "PUT"
    assert call["url"].endswith("/measurements/4")
    assert call["body"] == {"title": "c_01 (sw) noXO"}


def test_the_gain_key_is_gaindb_everywhere_it_is_documented():
    """`gain` is accepted by REW with a 200 and stored as 0 dB -- the quietest failure this API
    has, so the warning must stay next to the function that writes filters."""
    api = vendor_loader.load_rew_api()

    doc = api.set_filters.__doc__ or ""

    assert "gaindB" in doc
    assert "0 dB" in doc, "the silent-flat-filter consequence must be spelled out, not implied"


def test_docstrings_name_the_verified_payloads():
    """Cheap guard against someone 'simplifying' these back to the shapes REW rejects."""
    api = vendor_loader.load_rew_api()

    assert "POST" in (api.set_filters.__doc__ or "")
    assert "manufacturer" in (api.set_equaliser.__doc__ or "")
