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


def test_bridge_wraps_loaded_api():
    from autosound_tcc.core.rew_bridge import RewBridge

    bridge = RewBridge()
    assert bridge.base_url == "http://localhost:4735"
    # Read-only guarantee: no write methods leak through the facade.
    for forbidden in ("set_filters", "set_equaliser", "measurement_command"):
        assert not hasattr(bridge, forbidden)
