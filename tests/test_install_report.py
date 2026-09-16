"""What is installed, as one pasteable block — and never an exception."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

from autosound_tcc.core import install_report


def test_every_section_is_present_and_the_text_is_pasteable():
    text = install_report.as_text()

    for head in ("[Autosound TCC]", "[The method]", "[Command-line tools]", "[This machine]",
                 "[Where things are]"):
        assert head in text
    assert "\t" not in text, "aligned with spaces, so it survives a chat and a screenshot"


def test_a_tool_that_is_not_there_is_a_line_and_not_a_crash(tmp_path, monkeypatch):
    """A report that dies on one missing tool reports nothing at all — and "not found" IS the
    finding, most of the time."""
    # An empty PATH rather than a stubbed `shutil.which`: the lookup runs in a child process, where
    # a stub in this one does not reach (tcc#31).
    monkeypatch.setenv("PATH", str(tmp_path))

    text = install_report.as_text()

    assert "not found" in text
    assert "[Command-line tools]" in text


def _executable(directory, name):
    """A file a lookup can find: executable on POSIX, a PATHEXT name on Windows."""
    path = directory / name
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_the_tool_lookup_is_not_starved_by_a_busy_main_thread(tmp_path, monkeypatch):
    """tcc#31. The tools section runs on a worker thread, and `shutil.which` there hands the GIL
    over on every file check: 4989 checks for 8 tools on the Windows runner, 56.7 s while the main
    thread ran Python and 0.047 s while it did not. Listing each directory once still took 15.7 s.

    The same shape — a long PATH where most tools are not found — made long enough to show on any
    platform, with the main thread spinning the whole time. The section must come back in seconds.
    """
    # About 8000 file checks either way: a check per directory per tool, times PATHEXT on Windows.
    # Relative entries, resolved against the working directory the way `shutil.which` does, because
    # absolute temp paths this many run past 32767 characters and Windows refuses such a variable.
    monkeypatch.chdir(tmp_path)
    directories = []
    for index in range(90 if sys.platform == "win32" else 1000):
        directory = tmp_path / f"b{index}"
        directory.mkdir()
        directories.append(directory.name)
    monkeypatch.setenv("PATH", os.pathsep.join(directories))
    result = {}

    def work():
        started = time.monotonic()
        result["section"] = install_report.tools()
        result["took"] = time.monotonic() - started

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    deadline = time.monotonic() + 60
    spins = 0
    while worker.is_alive() and time.monotonic() < deadline:
        spins += 1  # Python bytecode on this thread: what a busy GUI thread does to the worker

    assert not worker.is_alive(), "the lookup did not finish within a minute"
    assert result["took"] < 5, f"the lookup took {result['took']:.1f} s with the main thread busy"
    assert {item.value for item in result["section"].items} == {"not found"}


def test_the_child_finds_exactly_what_shutil_which_finds(tmp_path, monkeypatch):
    """Moving the lookup must not change its answer: PATH order, PATHEXT order on Windows, a
    directory named like a tool, a file that is not executable, a directory that is not there."""
    first, second, empty, plain = (tmp_path / name for name in ("first", "second", "empty", "plain"))
    for directory in (first, second, empty, plain):
        directory.mkdir()
    for directory in (first, second):
        _executable(directory, "uv")
        _executable(directory, "uv.exe")
    _executable(second, "gh")
    _executable(second, "gh.cmd")
    (plain / "git").write_text("not a program", encoding="utf-8")
    (plain / "git").chmod(0o644)
    (first / "claude").mkdir()
    (first / "claude.exe").mkdir()
    monkeypatch.setenv("PATH", os.pathsep.join(
        str(directory) for directory in (empty, tmp_path / "missing", first, plain, second)))
    names = [exe for exe, _what in install_report._TOOLS]

    expected = {name: shutil.which(name) for name in names}

    assert expected["uv"] and expected["gh"], "the fixture must give shutil.which something to find"
    assert install_report._which_all(names) == expected


def _child_that_cannot_run(*_args, **_kwargs):
    raise OSError("no interpreter")


def _child_that_says_nonsense(*args, **_kwargs):
    return subprocess.CompletedProcess(args, 0, "not json", "")


@pytest.mark.parametrize("child", [_child_that_cannot_run, _child_that_says_nonsense])
def test_when_the_child_cannot_answer_the_lookup_is_done_here(tmp_path, monkeypatch, child):
    """Slow under load beats no answer: the section still says where each tool is."""
    _executable(tmp_path, "uv")
    _executable(tmp_path, "uv.exe")
    monkeypatch.setenv("PATH", str(tmp_path))
    expected = shutil.which("uv")
    monkeypatch.setattr(install_report.subprocess, "run", child)

    assert expected
    assert install_report._which_all(["uv"]) == {"uv": expected}


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


def _commit(root):
    """Turn a fake clone into a real one-commit repository, and give back its sha."""
    import subprocess

    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True, check=True).stdout.strip()

    git("init", "--quiet")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "the method")
    return git("rev-parse", "HEAD")


def test_the_report_carries_the_commit_the_method_is_at(tmp_path, monkeypatch):
    """HUB-001. The version in `plugin.json` is a signature kept by hand — in the method's own
    repository it has been seen to disagree with the tag — so it cannot identify what the app was
    running. Without the commit, no screenshot, bug report or diagnostic dump carried an
    identifier for the method at all. Whole, not shortened: this is the pasteable artifact.

    Since F-036 it is also the ONLY place the app shows the commit — the title bar and the update
    row keep the version alone, and this report is what somebody pastes into a chat."""
    from autosound_tcc.core import vendor_loader

    real = _fake_clone(tmp_path / "clone")
    sha = _commit(tmp_path / "clone")
    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, str(real))

    assert install_report.skill_sha() == sha

    text = install_report.as_text()
    assert sha in text, "the whole sha, so it can be handed back to git"
    assert "3.0.8" in text, "and the version beside it, because that is what a person quotes"


def test_a_method_outside_a_repository_says_nothing_rather_than_guessing(tmp_path, monkeypatch):
    from autosound_tcc.core import vendor_loader

    real = _fake_clone(tmp_path / "clone")  # a manifest, but never a `git init`
    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, str(real))

    assert install_report.skill_sha() == ""
    assert "not a git checkout" in install_report.as_text()


def test_gits_error_text_is_not_mistaken_for_a_commit(monkeypatch, tmp_path):
    """`_run` hands back STDERR when git fails, so the answer has to be recognised rather than
    trusted: "fatal: not a git repository" in the field that identifies the method would be worse
    than an empty one, because it looks like data."""
    from autosound_tcc.core import vendor_loader

    real = _fake_clone(tmp_path / "clone")
    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, str(real))
    monkeypatch.setattr(install_report, "_run",
                        lambda argv: "fatal: not a git repository (or any of the parent…)")

    assert install_report.skill_sha() == ""


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


def test_the_pasteable_block_carries_no_account_name(tmp_path, monkeypatch):
    """The report is composed to be pasted into a public issue, and on macOS and Windows every
    path in it opens with the account name of the person pasting (autosound-hub HUB-054).

    The home directory is substituted rather than the paths inspected: what is being checked is
    that the mask reads the home of the machine the report is made ON, at the moment it is made.
    """
    from pathlib import Path

    home = tmp_path / "beta-tester-account"
    (home / ".config").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))          # macOS, Linux
    monkeypatch.setenv("USERPROFILE", str(home))   # Windows
    monkeypatch.setattr(install_report.app_log, "log_path",
                        lambda: home / "Library" / "Logs" / "tcc.log")
    monkeypatch.setattr(install_report.model_overrides, "config_dir", lambda: home / ".config")

    text = install_report.as_text(install_report.report(
        project_dir=home / "projects" / "golf",
        with_tools=False,
        extra={"python": str(home / ".venv" / "bin" / "python")},
    ))

    assert "beta-tester-account" not in text
    # The diagnostic value is untouched: WHERE things are relative to home is still there, and
    # `str(Path(...))` so the separators are the ones this platform actually prints.
    assert str(Path("~/projects/golf")) in text
    assert str(Path("~/Library/Logs/tcc.log")) in text
    assert str(Path("~/.venv/bin/python")) in text


def test_a_home_that_is_the_root_masks_nothing(monkeypatch):
    """`/` as a home would turn every absolute path into `~…` — that hides the report, not a name."""
    monkeypatch.setattr(install_report.Path, "home", classmethod(lambda _cls: install_report.Path("/")))

    assert install_report._mask_home("/usr/bin/python") == "/usr/bin/python"


def test_a_project_linked_to_another_skill_says_so(tmp_path, monkeypatch):
    """SKL-028: both adapters read `<project>/.claude/skills/autosound-tuning`, and
    `link_skill_into` leaves an existing link alone whatever it points at — deliberately, because
    a person may have wired a working tree there. The cost of that decision is silence: set
    AUTOSOUND_SKILL_DIR, and the session still runs the OLD link while every report names the new
    directory. The break this catches is exactly that mismatch going unmentioned."""
    from autosound_tcc.core import install_report

    elsewhere = tmp_path / "some-other-checkout"
    (elsewhere / "skills" / "autosound-tuning").mkdir(parents=True)
    link = tmp_path / "project" / ".claude" / "skills" / "autosound-tuning"
    link.parent.mkdir(parents=True)
    link.symlink_to(elsewhere / "skills" / "autosound-tuning", target_is_directory=True)

    section = install_report._skill(tmp_path / "project")
    rows = {item.label: item for item in section.items}

    assert "project link" in rows
    assert str(elsewhere) in rows["project link"].detail


def test_a_project_linked_to_the_shipped_skill_says_nothing_alarming(tmp_path):
    """The row exists either way — a report that only speaks when something is wrong teaches a
    reader that silence means "not checked"."""
    from autosound_tcc.core import install_report, vendor_loader

    link = tmp_path / ".claude" / "skills" / "autosound-tuning"
    link.parent.mkdir(parents=True)
    link.symlink_to(vendor_loader.skill_dir().resolve(), target_is_directory=True)

    rows = {item.label: item for item in install_report._skill(tmp_path).items}

    assert rows["project link"].value == "this one"


class _Dist:
    """A stand-in for `importlib.metadata.distribution(...)` holding one `direct_url.json`."""

    def __init__(self, text):
        self._text = text

    def read_text(self, name):
        return self._text if name == "direct_url.json" else None


def test_the_ref_a_package_was_installed_at_is_read_from_direct_url(monkeypatch):
    """uv writes the ref beside the commit (uv 0.12.3, measured 2026-09-16, `@v0.1.39`)."""
    raw = ('{"url":"https://github.com/ayukhno/autosound-tcc","vcs_info":{"vcs":"git",'
           '"commit_id":"6ad4f82bb4ad694fb333c17cf63a8c0981000034","requested_revision":"v0.1.39"}}')
    monkeypatch.setattr(install_report, "distribution", lambda name: _Dist(raw))

    assert install_report.requested_revision() == "v0.1.39"
    assert install_report.install_source() == (
        "https://github.com/ayukhno/autosound-tcc", "6ad4f82bb4ad694fb333c17cf63a8c0981000034")

    monkeypatch.setattr(install_report, "distribution", lambda name: _Dist(None))
    assert install_report.requested_revision() == ""
    assert install_report.install_source() == ("", "")


def test_a_candidate_build_says_which_candidate_it_is():
    assert install_report.shown_version("0.1.38", "beta-v0.2.0-rc1") == "0.1.38 (beta-v0.2.0-rc1)"
    assert install_report.shown_version("0.1.39", "v0.1.39") == "0.1.39"
    assert install_report.shown_version("0.1.39", "") == "0.1.39"


def test_the_installation_block_names_the_candidate(monkeypatch):
    monkeypatch.setattr(install_report, "install_source", lambda: ("git+…", "a" * 40))
    monkeypatch.setattr(install_report, "requested_revision", lambda: "beta-v0.2.0-rc1")
    monkeypatch.setattr(install_report, "_package_version",
                        lambda name: "0.1.38" if name == "autosound-tcc" else "")

    assert install_report._app().items[0].value == "0.1.38 (beta-v0.2.0-rc1)"

