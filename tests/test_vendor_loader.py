"""Vendor-loader test — skips cleanly when the submodule isn't checked out.

So a fresh clone without `git submodule update --init` still runs the suite
green instead of erroring on a missing directory.
"""

from __future__ import annotations

import pytest

from autosound_tcc.core import vendor_loader

pytestmark = pytest.mark.skipif(
    not vendor_loader.is_available(),
    reason="rew_tool submodule not initialized (git submodule update --init)",
)


def test_load_rew_api():
    api = vendor_loader.load_rew_api()
    assert api.BASE_URL == "http://localhost:4735"
    # Read functions present; the module is isolated under a namespaced name.
    assert hasattr(api, "get_measurements")
    assert api.__name__ == "autosound_tcc._vendor.rew_api"


def test_load_dsp_state():
    vstate = vendor_loader.load_dsp_state()
    assert hasattr(vstate, "PresetHistory")
    assert callable(vstate.samples_for)


def test_get_post_put_pass_a_timeout():
    """A real, live-triggered incident (2026-07-27): `urlopen()` with no timeout let a REW-
    unreachable call hang a QThread forever, which crashed the whole app on shutdown ("QThread:
    Destroyed while thread is still running"). Guard against the timeout getting silently dropped
    in a future edit -- `_get`/`_post`/`_put` must always pass one."""
    from unittest.mock import MagicMock, patch

    api = vendor_loader.load_rew_api()
    with patch.object(api.urllib.request, "urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
        api._get("/measurements")
        api._post("/measurements/1/equaliser", {"name": "x"})
        api._put("/measurements/1", {"title": "x"})
    assert mock_urlopen.call_count == 3
    for call in mock_urlopen.call_args_list:
        assert call.kwargs.get("timeout") == api._TIMEOUT_S


def test_bridge_wraps_loaded_api():
    from autosound_tcc.core.rew_bridge import RewBridge

    bridge = RewBridge()
    assert bridge.base_url == "http://localhost:4735"
    # Read-only guarantee: no write methods leak through the facade, EXCEPT the one narrow,
    # user-approved exception (rename_measurement, item 9, 2026-07-27 -- see rew_bridge.py's
    # module docstring). Don't widen this list without the same explicit sign-off.
    for forbidden in ("set_filters", "set_equaliser", "measurement_command"):
        assert not hasattr(bridge, forbidden)
    assert hasattr(bridge, "rename_measurement")
