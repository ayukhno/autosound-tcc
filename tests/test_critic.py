"""The Critic wrapper (core/critic.py).

Driven against a stub reviewer script rather than the real one: the contract worth pinning is how
`autosound_ai.py` *reports* itself -- critique on stdout with a `— [role: model]` marker, progress
on stderr -- and above all that **clipboard fallback exits 0 with empty stdout**. A wrapper that
trusts the return code reports success and renders an empty critique, which is worse than an
error, because the whole point of the reviewer channel is that somebody actually pushed back.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from autosound_tcc.core import critic, vendor_loader


def _project(tmp_path: Path) -> Path:
    """A project folder complete enough to pass preflight."""
    mirror = tmp_path / "rew_analitic"
    mirror.mkdir(parents=True)
    (mirror / "data-contract-template.md").write_text("contract", encoding="utf-8")
    (mirror / "autosound_context.md").write_text("context", encoding="utf-8")
    return tmp_path


def _stub(tmp_path: Path, body: str) -> Path:
    """A stand-in reviewer script; `body` is Python run with argv = [role, package, trace?]."""
    path = tmp_path / "stub_reviewer.py"
    path.write_text("import sys, os\n" + body, encoding="utf-8")
    return path


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    """Point `critic` at a stub script the test supplies."""

    def install(body: str) -> Path:
        script = _stub(tmp_path, body)
        monkeypatch.setattr(critic, "script_path", lambda: script)
        return script

    return install


def test_answered_carries_the_critique_and_the_model(stubbed, tmp_path):
    stubbed(
        "print('The 175-stack risk is ruled out by measurement.')\n"
        "print()\nprint('— [critic: Gemini 3.1 Pro (High)]')\n"
    )
    project = _project(tmp_path)

    result = critic.run("package body", project_dir=project, python_executable=sys.executable)

    assert result.ok
    assert result.mode == critic.MODE_API_OR_CLI
    assert "175-stack" in result.text
    assert result.model == "Gemini 3.1 Pro (High)"
    assert "— [critic:" not in result.text, "the marker line is metadata, not part of the critique"


def test_clipboard_fallback_is_not_reported_as_an_answer(stubbed, tmp_path):
    """The trap: exit 0, nothing on stdout, everything on stderr."""
    stubbed(
        "print('>> CLI unavailable', file=sys.stderr)\n"
        "print('=' * 20, file=sys.stderr)\n"
        "print('▶ РУЧНИЙ РЕЖИМ: БУФЕР ОБМІНУ (CLIPBOARD MODE)', file=sys.stderr)\n"
        "sys.exit(0)\n"
    )
    project = _project(tmp_path)

    result = critic.run("package body", project_dir=project, python_executable=sys.executable)

    assert result.mode == critic.MODE_CLIPBOARD
    assert result.ok is False
    assert result.text == ""


def test_silence_is_an_error_not_a_critique(stubbed, tmp_path):
    stubbed("sys.exit(0)\n")
    project = _project(tmp_path)

    result = critic.run("package", project_dir=project, python_executable=sys.executable)

    assert result.mode == critic.MODE_ERROR
    assert "no output" in result.detail


def test_preflight_blocks_before_spawning_anything(tmp_path):
    """A missing context makes the script exit with a bare message -- catch it here instead.

    The CONTRACT is not in that list any more, and that is the fix: it belongs to the method and
    ships in the skill's `assets/`, so nothing copies it into a project and requiring it there
    made the reviewer permanently not-ready on every clean install (user, Windows, 2026-08-19).
    """
    bare = tmp_path / "not-a-project"
    bare.mkdir()

    problems = critic.preflight(bare)

    assert any("autosound_context.md" in p for p in problems)
    if vendor_loader.is_available():
        assert not any("data-contract-template.md" in p for p in problems), "the skill has it"


def test_the_contract_is_found_where_the_script_would_look(tmp_path):
    """The same places `autosound_ai.py` searches, in the same order: the mirror, the project
    root, `$AUTOSOUND_DIR`, then the skill. TCC checking only the first one is how it came to
    refuse a project the script would have run in."""
    project = tmp_path / "car"
    (project / "rew_analitic").mkdir(parents=True)
    (project / "autosound_context.md").write_text("the car", encoding="utf-8")

    assert critic.preflight(project) == [] or not vendor_loader.is_available()

    (project / "rew_analitic" / "data-contract-template.md").write_text("mine", encoding="utf-8")
    found = critic._find_for_script(project, "data-contract-template.md")

    assert found == project / "rew_analitic" / "data-contract-template.md", "a project copy wins"


def test_a_project_that_has_not_started_is_not_ready_rather_than_broken(tmp_path):
    """The first thing anyone does on a fresh project is ask TCC to check the reviewer, and the
    answer was two missing filenames under `Reviewer call failed` — which sends somebody
    debugging a channel that works (user, on a clean install 2026-08-13). The reviewer is
    stateless and re-reads the project every call; a folder that has not been through intake has
    nothing for it to read, and that is a state, not a fault."""
    result = critic.run("package", project_dir=tmp_path, python_executable=sys.executable)

    assert result.mode == critic.MODE_NOT_READY
    assert "autosound_context.md" in result.detail  # still says WHICH files, for the log


def test_a_missing_reviewer_script_is_still_an_error(tmp_path, monkeypatch):
    """The other half of the same check: no script is a broken install, and must not be softened
    into "your project has not started yet"."""
    monkeypatch.setattr(critic, "is_available", lambda: False)

    result = critic.run("package", project_dir=tmp_path, python_executable=sys.executable)

    assert result.mode == critic.MODE_ERROR


def test_markdown_is_persisted_so_the_call_is_auditable(stubbed, tmp_path):
    stubbed("print('ok')\nprint('— [critic: m]')\n")
    project = _project(tmp_path)

    critic.run("## Package\nbody", project_dir=project, python_executable=sys.executable)

    written = list(critic.package_dir(project).glob("pkg_*.md"))
    assert len(written) == 1
    assert "## Package" in written[0].read_text(encoding="utf-8")


def test_an_existing_package_file_is_used_as_is(stubbed, tmp_path):
    """The Generator often wrote the package already; don't copy it into a second location."""
    stubbed("print(open(sys.argv[2]).read())\nprint('— [critic: m]')\n")
    project = _project(tmp_path)
    existing = project / "rew_analitic" / "pkg_phase2_open.md"
    existing.write_text("already written by the Generator", encoding="utf-8")

    result = critic.run(str(existing), project_dir=project, python_executable=sys.executable)

    assert "already written by the Generator" in result.text
    assert not critic.package_dir(project).exists()


def test_model_choice_reaches_the_subprocess_env(stubbed, tmp_path):
    stubbed("print(os.environ.get('GEMINI_CRITIC_MODEL', 'unset'))\nprint('— [critic: m]')\n")
    project = _project(tmp_path)

    result = critic.run(
        "pkg", project_dir=project, model="Gemini 3.1 Pro", python_executable=sys.executable
    )

    assert result.text.strip() == "Gemini 3.1 Pro"


def test_advisor_role_uses_its_own_model_var(stubbed, tmp_path):
    stubbed("print(os.environ.get('GEMINI_ADVISOR_MODEL', 'unset'))\nprint('— [advisor: m]')\n")
    project = _project(tmp_path)

    result = critic.run(
        "pkg", project_dir=project, role="advisor", model="Flash", python_executable=sys.executable
    )

    assert result.text.strip() == "Flash"


def test_project_mirror_is_pointed_at_the_project(stubbed, tmp_path):
    """The script resolves the contract and context relative to PROJECT_MIRROR."""
    stubbed("print(os.environ['PROJECT_MIRROR'])\nprint('— [critic: m]')\n")
    project = _project(tmp_path)

    result = critic.run("pkg", project_dir=project, python_executable=sys.executable)

    assert result.text.strip() == str(project / "rew_analitic")


def test_a_hung_reviewer_is_killed_rather_than_waited_on(stubbed, tmp_path):
    stubbed("import time\ntime.sleep(30)\n")
    project = _project(tmp_path)

    result = critic.run(
        "pkg", project_dir=project, timeout_s=1.0, python_executable=sys.executable
    )

    assert result.mode == critic.MODE_ERROR
    assert "timed out" in result.detail


def test_calls_are_logged_append_only_and_the_last_one_is_readable(stubbed, tmp_path):
    stubbed("print('x')\nprint('— [critic: Gemini 3.1 Pro]')\n")
    project = _project(tmp_path)

    first = critic.run("pkg one", project_dir=project, python_executable=sys.executable)
    critic.log_call(first, None, project)
    second = critic.run("pkg two", project_dir=project, python_executable=sys.executable)
    critic.log_call(second, None, project)

    lines = critic.log_path(project).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["model"] == "Gemini 3.1 Pro"
    assert critic.last_call(project)["mode"] == critic.MODE_API_OR_CLI


def test_last_call_is_none_before_any_call(tmp_path):
    assert critic.last_call(tmp_path) is None
