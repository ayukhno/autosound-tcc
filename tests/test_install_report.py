"""What is installed, as one pasteable block — and never an exception."""

from __future__ import annotations

from autosound_tcc.core import install_report


def test_every_section_is_present_and_the_text_is_pasteable():
    text = install_report.as_text()

    for head in ("[Autosound TCC]", "[The method]", "[Command-line tools]", "[This machine]",
                 "[Where things are]"):
        assert head in text
    assert "\t" not in text, "aligned with spaces, so it survives a chat and a screenshot"


def test_a_tool_that_is_not_there_is_a_line_and_not_a_crash(monkeypatch):
    """A report that dies on one missing tool reports nothing at all — and "not found" IS the
    finding, most of the time."""
    monkeypatch.setattr(install_report.shutil, "which", lambda _name: None)

    text = install_report.as_text()

    assert "not found" in text
    assert "[Command-line tools]" in text


def test_a_probe_that_hangs_or_explodes_is_swallowed(monkeypatch):
    def _boom(*_a, **_kw):
        raise OSError("no such thing")

    monkeypatch.setattr(install_report.subprocess, "run", _boom)

    assert install_report.as_text()  # still a report


def test_the_windows_facts_the_window_passes_in_are_in_the_report():
    text = install_report.as_text(install_report.report(extra={"MCP": "not running: ValueError"}))

    assert "MCP" in text and "not running: ValueError" in text


def _fake_clone(root):
    """A skill repository shaped like the installer's: a manifest at the top, the skill inside."""
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "autosound-tuning", "version": "3.0.8"}', encoding="utf-8")
    skill = root / "skills" / "autosound-tuning" / "rew_tool"
    skill.mkdir(parents=True)
    for name in ("rew_api.py", "project.py", "contract.py"):
        (skill / name).write_text("", encoding="utf-8")
    return root / "skills" / "autosound-tuning"


def test_the_version_is_read_through_the_installers_link(tmp_path, monkeypatch):
    """What every installed machine looks like and no developer's does: the skill is reached
    through a symlink (macOS) or a junction (Windows) into the clone. Two levels up from the LINK
    is ~/.claude — no manifest, not a git checkout — which is why the title bar said "(TCC 0.1.2)"
    with nothing beside it and the update row said "not a git checkout" (user, Windows,
    2026-08-19)."""
    from autosound_tcc.core import vendor_loader

    real = _fake_clone(tmp_path / "clone")
    link = tmp_path / "home" / ".claude" / "skills" / "autosound-tuning"
    link.parent.mkdir(parents=True)
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, str(link))

    assert vendor_loader.skill_dir() == link, "the link is what TCC finds and reports"
    assert vendor_loader.skill_repo_root() == (tmp_path / "clone").resolve()
    assert install_report.skill_version() == "3.0.8"


def test_a_skill_folder_in_no_repository_says_so_rather_than_guessing(tmp_path, monkeypatch):
    from autosound_tcc.core import vendor_loader

    skill = tmp_path / "loose" / "rew_tool"
    skill.mkdir(parents=True)
    for name in ("rew_api.py", "project.py", "contract.py"):
        (skill / name).write_text("", encoding="utf-8")
    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, str(tmp_path / "loose"))

    assert vendor_loader.skill_repo_root() is None
    assert install_report.skill_version() == ""


def test_a_source_checkout_reports_the_version_in_its_own_tree(monkeypatch, tmp_path):
    """A venv installed once and never again reported `TCC 0.0.1` from a tree at 0.1.6. For a
    checkout the truth is the file being edited, not the metadata left behind by an old install."""
    monkeypatch.setattr(install_report, "install_source", lambda: ("", ""))
    monkeypatch.setattr(install_report, "_package_version", lambda name: "0.0.1")

    version = install_report.app_version()

    import tomllib
    from pathlib import Path
    here = tomllib.loads(
        (Path(install_report.__file__).parents[3] / "pyproject.toml").read_text(encoding="utf-8"))
    assert version == here["project"]["version"] != "0.0.1"


def test_an_installed_build_keeps_its_metadata_version(monkeypatch):
    """Installed from git, the metadata IS the build — no reaching for a pyproject that is not there."""
    monkeypatch.setattr(install_report, "install_source", lambda: ("git+…", "a" * 40))
    monkeypatch.setattr(install_report, "_package_version", lambda name: "0.1.6")

    assert install_report.app_version() == "0.1.6"
