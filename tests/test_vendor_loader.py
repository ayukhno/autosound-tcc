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
    # Read functions present; the module is isolated under a namespaced name.
    assert hasattr(api, "get_measurements")
    assert api.__name__ == "autosound_tcc._vendor.rew_api"
    # The port is asserted against the file the skill SHIPS, not against the loaded module's
    # attribute: the suite re-points `BASE_URL` at a dead one so that no test can reach a REW
    # somebody is mid-measurement on (tests/conftest.py, after exit 134 with REW live).
    #
    # It stopped being a literal on 2026-08-26 (`REW_API_URL` overrides it, for a REW on another
    # host). Two things are asserted rather than one, because the app depends on both: the DEFAULT
    # is still REW's own 4735 — the number the System-params row shows — and the override exists,
    # which is why that row derives what it shows instead of printing a constant.
    shipped = (vendor_loader.rew_tool_dir() / "rew_api.py").read_text(encoding="utf-8")
    assert '"http://localhost:4735"' in shipped
    assert "REW_API_URL" in shipped


def test_load_dsp_state():
    vstate = vendor_loader.load_dsp_state()
    assert hasattr(vstate, "PresetHistory")
    assert callable(vstate.samples_for)


def test_load_project():
    proj = vendor_loader.load_project()
    assert hasattr(proj, "Project")
    assert callable(proj.fact) and callable(proj.open_questions)
    assert proj.__name__ == "autosound_tcc._vendor.project"


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
    # The wiring, which is what this test is about: the facade reports whatever the loaded module
    # holds, rather than a copy of the address made when it was written.
    assert bridge.base_url == vendor_loader.load_rew_api().BASE_URL
    # Read-only guarantee: no write methods leak through the facade, EXCEPT the one narrow,
    # user-approved exception (rename_measurement, item 9, 2026-07-27 -- see rew_bridge.py's
    # module docstring). Don't widen this list without the same explicit sign-off.
    for forbidden in ("set_filters", "set_equaliser", "measurement_command"):
        assert not hasattr(bridge, forbidden)
    assert hasattr(bridge, "rename_measurement")


# ---- installing the skill into a project ------------------------------------


def test_a_project_gets_the_skill_tcc_ships(tmp_path):
    """Both adapters assume `<project>/.claude/skills/autosound-tuning` and nothing created it, so
    a project without it ran with whatever was in `~/.claude/skills` — in a real session, an old
    checkout whose references resolve nowhere."""
    from autosound_tcc.core import vendor_loader

    link = vendor_loader.link_skill_into(tmp_path)

    assert link == tmp_path / ".claude" / "skills" / "autosound-tuning"
    assert link.is_symlink()
    assert (link / "SKILL.md").is_file()
    assert link.resolve() == vendor_loader.SKILL_DIR.resolve()


def test_an_existing_link_is_left_alone(tmp_path):
    """The user may have wired a working tree there on purpose; replacing it under them would be
    worse than the problem this solves."""
    from autosound_tcc.core import vendor_loader

    theirs = tmp_path / "their-checkout"
    theirs.mkdir()
    link = tmp_path / ".claude" / "skills" / "autosound-tuning"
    link.parent.mkdir(parents=True)
    link.symlink_to(theirs, target_is_directory=True)

    vendor_loader.link_skill_into(tmp_path)

    assert link.resolve() == theirs.resolve()


def test_linking_reports_rather_than_raises_when_it_cannot(tmp_path, monkeypatch):
    """A session with a warning beats no session."""
    from autosound_tcc.core import vendor_loader

    monkeypatch.setattr(vendor_loader, "is_available", lambda: False)

    assert vendor_loader.link_skill_into(tmp_path) is None


def test_the_rew_row_names_the_endpoint_it_actually_reaches(monkeypatch):
    """The System-params row printed the constant `4735` until the method gave `rew_api.BASE_URL`
    a `REW_API_URL` override (2026-08-26). A row reading "4735" beside a green dot that had just
    reached another host is the label asserting something nobody checked — the dot right, the fact
    next to it wrong. So the row is derived, and this is what says so.

    The suite itself is the reason this cannot be left to inspection: `conftest._no_live_rew` points
    every test's REW at a dead port, so the "default" branch has to be arranged on purpose.
    """
    from autosound_tcc.ui.tcc import main_window

    api = vendor_loader.load_rew_api()

    monkeypatch.setattr(api, "BASE_URL", "http://localhost:4735")
    assert main_window._rew_endpoint_label() == "4735", "the ordinary case stays a bare port"

    monkeypatch.setattr(api, "BASE_URL", "http://studio-pc:4740")
    assert main_window._rew_endpoint_label() == "http://studio-pc:4740", \
        "and anything else is named in full rather than mislabelled as the default"
