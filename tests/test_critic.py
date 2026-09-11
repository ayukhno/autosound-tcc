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


# --- "choose a model" is a QUESTION, not a failure (SKL-023) --------------------------------


_CHOICE_STDERR = """>> Модель рецензента не задано.
>> Моделі, які цей ключ може викликати (generateContent) -- вибери одну і закріпи її:
>>   AUTOSOUND_CRITIC_MODEL=<модель>   у ~/.config/autosound/critic-env
>>     gemini-pro-latest
>>     gemini-flash-latest
>>     gemini-3.1-pro-preview
>> `gemini-pro-latest` / `gemini-flash-latest` -- Google's own pointers to the current Pro / Flash.
"""


def _reviewer_exits(monkeypatch, code, stderr):
    import subprocess

    from autosound_tcc.core import critic

    # `preflight` also wants the project's own two files; this test is about the exit code, and
    # a missing contract would answer `not_ready` long before the subprocess is reached.
    monkeypatch.setattr(critic, "preflight", lambda project_dir=None: [])
    monkeypatch.setattr(critic, "is_available", lambda: True)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0] if a else [], code, "", stderr),
    )
    return critic


def test_a_key_that_cannot_call_the_named_model_asks_rather_than_fails(monkeypatch, tmp_path):
    """skill@af9d7e3: with no model named, or one the key cannot call, the reviewer prints the
    key's OWN list of models and exits 3. TCC read every non-zero exit the same way — "error, use
    the clipboard" — so the one thing that would fix it, the list, was thrown away and the Arbiter
    was sent to paste packages by hand instead of picking a model (2026-09-08: gemini-2.5-* went
    404 under a working key, and that is exactly this)."""
    critic = _reviewer_exits(monkeypatch, 3, _CHOICE_STDERR)

    result = critic.run("## package", project_dir=tmp_path)

    assert result.mode == critic.MODE_CHOOSE_MODEL
    assert result.models == [
        "gemini-pro-latest", "gemini-flash-latest", "gemini-3.1-pro-preview"
    ]
    assert result.mode != critic.MODE_ERROR


def test_a_real_failure_is_still_a_failure(monkeypatch, tmp_path):
    """The new branch is keyed on the exit code, so anything else keeps its old meaning."""
    critic = _reviewer_exits(monkeypatch, 1, ">> something actually broke\n")

    result = critic.run("## package", project_dir=tmp_path)

    assert result.mode == critic.MODE_ERROR
    assert result.models == []


def test_a_reviewer_binary_that_is_not_installed_does_not_win_over_one_that_is():
    """`GEMINI_BIN` outranks autodetection in the skill's reviewer, for historical reasons. On this
    machine it names `gemini` — a path Google closed — so every call tried that, failed, and fell
    back to the clipboard without ever trying `agy`, which IS installed. Eight calls, zero
    critiques, and the real reason never surfaced (Arbiter's own tally, 2026-09-11).

    `AUTOSOUND_CRITIC_BIN` is checked first by that same reviewer, so naming a working CLI there
    is the fix. Deliberately narrow: it acts only when the inherited name cannot work and a
    working one exists, and it never overrides a choice the person made themselves."""
    from autosound_tcc.core import critic

    installed = {"agy"}
    which = lambda name: f"/bin/{name}" if name in installed else None  # noqa: E731

    assert critic.critic_bin_override(
        environ={"GEMINI_BIN": "gemini"}, which=which) == {"AUTOSOUND_CRITIC_BIN": "agy"}

    assert critic.critic_bin_override(
        environ={"GEMINI_BIN": "agy"}, which=which) == {}, "an inherited name that works is left"

    assert critic.critic_bin_override(
        environ={"AUTOSOUND_CRITIC_BIN": "gemini", "GEMINI_BIN": "gemini"}, which=which) == {}, \
        "a choice the person made themselves is never overridden"

    assert critic.critic_bin_override(environ={}, which=which) == {}, "nothing inherited, nothing to fix"


def test_the_reviewer_pick_outranks_an_inherited_gemini_bin():
    """TCC-002, and the ordering IS the bug. The project said `critic: agy:gemini-3.1-pro-high`,
    the machine exported `GEMINI_BIN=gemini`, and the reviewer script reads the env var first — so
    ten calls in a row went to a CLI nobody chose, down a path Google has closed, and came back as
    clipboard packages with `model: null` (measured on the Arbiter's machine, 2026-09-11).

    TCC already sent the picked MODEL. Not sending the binary beside it is what let the two point
    at different reviewers."""
    from autosound_tcc.core import critic

    env = {"GEMINI_BIN": "gemini"}          # on PATH, and useless
    here = {"agy", "gemini"}

    picked = critic.critic_bin_override(
        harness="agy", environ=env, which=lambda name: name if name in here else None)
    assert picked == {"AUTOSOUND_CRITIC_BIN": "agy"}, "the Arbiter's pick wins"


def test_a_pick_this_machine_cannot_run_is_not_forced():
    """Replacing one dead name with another is worse than leaving it alone: the person would then
    be debugging a binary they never chose AND never installed."""
    from autosound_tcc.core import critic

    env = {"GEMINI_BIN": "gemini"}
    only_gemini = critic.critic_bin_override(
        harness="codex", environ=env, which=lambda name: name if name == "gemini" else None)

    assert only_gemini == {}, "codex was picked but is not installed — say nothing"


def test_a_binary_the_person_set_themselves_is_never_overridden():
    from autosound_tcc.core import critic

    env = {"AUTOSOUND_CRITIC_BIN": "my-own-reviewer", "GEMINI_BIN": "gemini"}
    assert critic.critic_bin_override(harness="agy", environ=env, which=lambda _n: "/x") == {}


def test_the_call_says_which_binary_it_went_out_with(tmp_path, monkeypatch, caplog):
    """Not saying it cost a whole round trip. `AUTOSOUND_CRITIC_BIN` goes into the CHILD's
    environment and nowhere else, so TCC's own `os.environ` shows `None` on a fixed build exactly
    as it does on a broken one — and a session on the machine read that as "the fix did not
    arrive" (2026-09-11). One line settles it: which binary, and who chose it."""
    import logging

    from autosound_tcc.core import critic

    monkeypatch.setattr(critic, "is_available", lambda: True)
    monkeypatch.setattr(critic, "preflight", lambda _p=None: [])   # a project with its files
    monkeypatch.setattr(critic, "script_path", lambda: tmp_path / "autosound_ai.py")
    monkeypatch.setattr(critic.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setenv("GEMINI_BIN", "gemini")
    monkeypatch.delenv("AUTOSOUND_CRITIC_BIN", raising=False)

    def explode(*_a, **_k):
        raise OSError("not actually running the reviewer in a test")

    monkeypatch.setattr(critic.subprocess, "run", explode)

    with caplog.at_level(logging.INFO):
        critic.run("a package", project_dir=tmp_path, harness="agy")

    said = "\n".join(r.getMessage() for r in caplog.records)
    assert "critic: bin=agy" in said, f"the binary is named, not inferred: {said}"
    assert "Arbiter's pick" in said, "and who decided it"


def test_the_clipboard_answer_says_what_the_cli_actually_replied():
    """Thirteen calls in a row reported `mode: clipboard` with nothing to act on, and the code was
    dutifully reporting the WRONG END of the same string: `tail` takes the last six lines, and in
    this mode those are always the banner the script prints on its way out. The reason is printed
    just above it and was pushed off the end every time (measured 2026-09-11)."""
    from autosound_tcc.core import critic

    stderr = (
        ">> Виклик agy...\n"
        ">> ⛔ agy повернув помилку: model 'gemini-3.8-flash-low' is not available\n"
        "==================================================\n"
        "▶ РУЧНИЙ РЕЖИМ: БУФЕР ОБМІНУ (CLIPBOARD MODE)\n"
        "==================================================\n"
        "👉 Тепер просто відкрийте будь-який ШІ-чат\n"
        " та натисніть Ctrl+V для вставки.\n"
        "🚀 КРУТО! Промпт скопійовано у буфер обміну!\n"
    )

    why = critic._why_clipboard(stderr)

    assert "is not available" in why, f"the CLI's own words, not the banner: {why!r}"
    assert "Ctrl+V" not in why, "and not the instructions that pushed them off the end"
