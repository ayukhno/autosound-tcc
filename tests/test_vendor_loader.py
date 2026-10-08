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
    from unittest.mock import patch

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


@pytest.mark.parametrize("where", [
    pytest.param("skills", id="skills-linked-out-of-the-project"),
    pytest.param("claude", id="claude-linked-out-of-the-project"),
    # The boundary's other side: «out of the project» is the folder `.claude/skills` IS, so a
    # project that keeps its skills in another folder of its own, linked in, still gets the link.
    pytest.param("own-folder", id="skills-linked-to-a-folder-of-the-project"),
])
def test_skills_that_lead_out_of_the_project_get_no_link_there(tmp_path, where):
    """R-ak (#169): with `.claude/skills` — or `.claude` itself — a link out of the project, to
    `~/.claude` say, a session start made TCC's link THERE: in a folder every other project that
    reads it shares, written by opening one. Nothing is written now, and the answer is None, which
    both adapters already handle as «no link could be made»."""
    import os

    outside = tmp_path / "home" / ".claude"
    (outside / "skills").mkdir(parents=True)
    project = tmp_path / "car"
    project.mkdir()
    if where == "skills":
        (project / ".claude").mkdir()
        (project / ".claude" / "skills").symlink_to(outside / "skills", target_is_directory=True)
    elif where == "claude":
        (project / ".claude").symlink_to(outside, target_is_directory=True)
    else:
        (project / "shared-skills").mkdir()
        (project / ".claude").mkdir()
        (project / ".claude" / "skills").symlink_to(project / "shared-skills",
                                                    target_is_directory=True)

    link = vendor_loader.link_skill_into(project)

    assert os.listdir(outside / "skills") == [], "nothing linked out of the project"
    if where == "own-folder":
        assert link == project / ".claude" / "skills" / vendor_loader.SKILL_NAME
        assert (project / "shared-skills" / vendor_loader.SKILL_NAME / "SKILL.md").is_file()
    else:
        assert link is None


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


def test_on_windows_a_refused_symlink_becomes_a_junction(tmp_path, monkeypatch):
    """Finding 103 (tcc#88): on the Windows VM the project had no `.claude/skills/autosound-tuning`
    and the session ran without the method. A symlink needs Developer Mode or an admin there
    (WinError 1314) and the refusal was swallowed; a junction needs neither — the skill's own
    installer links the same way (`install.ps1`)."""
    import sys
    import types
    from pathlib import Path

    from autosound_tcc.core import vendor_loader

    made = []
    fake = types.ModuleType("_winapi")
    fake.CreateJunction = lambda target, link: (made.append((target, link)), Path(link).mkdir())
    monkeypatch.setitem(sys.modules, "_winapi", fake)
    monkeypatch.setattr(vendor_loader.sys, "platform", "win32")
    monkeypatch.setattr(vendor_loader, "is_available", lambda: True)
    skill = tmp_path / "skill" / "autosound-tuning"
    skill.mkdir(parents=True)
    monkeypatch.setattr(vendor_loader, "skill_dir", lambda: skill)

    def refuse(self, target, target_is_directory=False):
        raise OSError(1314, "A required privilege is not held by the client")

    monkeypatch.setattr(Path, "symlink_to", refuse)

    link = vendor_loader.link_skill_into(tmp_path / "project")

    assert link is not None and link.exists()
    assert made and made[0][0] == str(skill.resolve())


# ---- an in-app update reads the method again (#126, the re-review of 697378d) ----------------
# The loader kept every vendored module for the whole run, so after «Оновити Скіл» every reader in
# the process -- `load_channels`, the measurement view, the stale check -- kept the method TCC
# started with until TCC was restarted. These tests run on a fake skill of their own, never on the
# real one: re-reading the real `rew_api` would undo the suite's dead REW port (conftest).

import sys  # noqa: E402
import threading  # noqa: E402
import types  # noqa: E402

_VENDOR_PREFIX = "autosound_tcc._vendor."


@pytest.fixture
def fake_skill(tmp_path, monkeypatch):
    """A skill folder whose `naming.py` says which version it is and imports a bare sibling the
    way the method's modules do (`sys.path` + `import`), with the real modules put back after."""
    rew_tool = tmp_path / "skill" / "rew_tool"
    rew_tool.mkdir(parents=True)
    for name in ("rew_api.py", "project.py", "contract.py"):
        (rew_tool / name).write_text("", encoding="utf-8")
    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, str(tmp_path / "skill"))
    monkeypatch.setattr(sys, "path", list(sys.path))
    kept = {k: m for k, m in sys.modules.items() if k.startswith(_VENDOR_PREFIX)}
    for name in kept:
        del sys.modules[name]
    try:
        yield rew_tool
    finally:
        for name in [k for k in sys.modules if k.startswith(_VENDOR_PREFIX)
                     or k in ("tcc_fake_sibling", "tcc_fake_gate")]:
            del sys.modules[name]
        sys.modules.update(kept)


def _write_method(rew_tool, version, *, broken=False):
    (rew_tool / "tcc_fake_sibling.py").write_text(f"VERSION = {version!r}\n", encoding="utf-8")
    (rew_tool / "naming.py").write_text(
        "import os, sys\n"
        "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
        "import tcc_fake_sibling\n"
        + ("raise ImportError('this method needs something TCC does not have')\n" if broken else "")
        + f"VERSION = {version!r}\nSIBLING = tcc_fake_sibling.VERSION\n",
        encoding="utf-8")


def test_a_reader_after_an_update_reads_the_new_method(fake_skill):
    _write_method(fake_skill, "v3.0.65")
    before = vendor_loader.load_naming()
    assert (before.VERSION, before.SIBLING) == ("v3.0.65", "v3.0.65")

    _write_method(fake_skill, "v3.0.66-longer")  # what the update put on disk
    assert vendor_loader.load_naming() is before, "nothing reads the disk again on its own"
    assert vendor_loader.reload_loaded() is True

    after = vendor_loader.load_naming()
    assert after is not before
    assert (after.VERSION, after.SIBLING) == ("v3.0.66-longer", "v3.0.66-longer"), \
        "the module and the sibling it imports bare are both the new method's"


def test_a_new_method_that_will_not_load_leaves_the_old_one_serving(fake_skill):
    """Never half of each: when the new files do not load in this process, every module the old
    method had goes back, and the update's line says to restart TCC (the panel's half)."""
    _write_method(fake_skill, "v3.0.65")
    before = vendor_loader.load_naming()
    sibling = sys.modules["tcc_fake_sibling"]

    _write_method(fake_skill, "v3.0.66-longer", broken=True)
    assert vendor_loader.reload_loaded() is False

    assert vendor_loader.load_naming() is before
    assert sys.modules["tcc_fake_sibling"] is sibling


def test_a_reload_with_nothing_loaded_loads_nothing(fake_skill):
    _write_method(fake_skill, "v3.0.66-longer", broken=True)

    assert vendor_loader.reload_loaded() is True
    assert not [k for k in sys.modules if k.startswith(_VENDOR_PREFIX)]


def test_a_reader_never_gets_a_module_another_thread_is_still_loading(fake_skill, monkeypatch):
    """A module is in `sys.modules` before its body has run (so it can refer to itself). A second
    reader that found it there was handed it half-built; it waits for the load now."""
    gate = types.ModuleType("tcc_fake_gate")
    gate.started, gate.release = threading.Event(), threading.Event()
    monkeypatch.setitem(sys.modules, "tcc_fake_gate", gate)
    (fake_skill / "naming.py").write_text(
        "import tcc_fake_gate\n"
        "tcc_fake_gate.started.set()\n"
        "tcc_fake_gate.release.wait(10)\n"
        "DONE = True\n", encoding="utf-8")
    got = {}
    first = threading.Thread(target=lambda: got.setdefault("first", vendor_loader.load_naming()))
    first.start()
    assert gate.started.wait(10)
    second = threading.Thread(target=lambda: got.setdefault("second", vendor_loader.load_naming()))
    second.start()
    second.join(0.3)
    try:
        assert "second" not in got, "the second reader was handed a module still loading"
    finally:
        gate.release.set()
        first.join(10)
        second.join(10)
    assert got["second"] is got["first"] and got["second"].DONE


def test_the_rew_bridge_follows_a_reloaded_api(monkeypatch):
    """The bridge kept the module it first loaded for its whole life; it asks the loader now."""
    from autosound_tcc.core.rew_bridge import RewBridge

    old, new = types.SimpleNamespace(BASE_URL="old"), types.SimpleNamespace(BASE_URL="new")
    current = [old]
    monkeypatch.setattr(vendor_loader, "load_rew_api", lambda: current[0])
    bridge = RewBridge()
    assert bridge.base_url == "old"
    current[0] = new
    assert bridge.base_url == "new"
    injected = RewBridge(old)
    assert injected.api is old, "an api handed in is kept"
