"""The Critic wrapper (core/critic.py).

Driven against a stub reviewer script rather than the real one: the contract worth pinning is how
`autosound_ai.py` *reports* itself -- critique on stdout with a `— [role: model]` marker, progress
on stderr -- and above all that **clipboard fallback exits 0 with empty stdout**. A wrapper that
trusts the return code reports success and renders an empty critique, which is worse than an
error, because the whole point of the reviewer channel is that somebody actually pushed back.
"""

from __future__ import annotations

import json
import os
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


def test_a_relative_package_path_is_read_from_the_project(stubbed, tmp_path, monkeypatch):
    """The path TCC itself prints under a failed call is relative to the PROJECT, and TCC's own
    working folder is somewhere else: checked there, it named nothing and went to the reviewer as
    the package's text — «ви передали лише шлях до файлу» (finding 133, tcc#119)."""
    stubbed("print(open(sys.argv[2], encoding='utf-8').read())\nprint('— [critic: m]')\n")
    project = _project(tmp_path)
    reviews = project / "process" / "reviews"
    reviews.mkdir(parents=True)
    (reviews / "x-critic-package.md").write_text("the package the Generator wrote",
                                                 encoding="utf-8")
    elsewhere = tmp_path / "tcc-working-folder"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    relative = str(Path("process") / "reviews" / "x-critic-package.md")
    result = critic.run(relative, project_dir=project, python_executable=sys.executable)

    assert "the package the Generator wrote" in result.text
    assert not critic.package_dir(project).exists(), "read as that file, not composed from its name"


def test_a_package_path_that_names_no_file_is_refused_by_its_name(stubbed, tmp_path):
    """Sent as text it is a review of a file name; refused, it says which name found nothing."""
    stubbed("print('reviewed')\nprint('— [critic: m]')\n")
    project = _project(tmp_path)

    missing = str(Path("process") / "reviews" / "gone-critic-package.md")
    result = critic.run(missing, project_dir=project, python_executable=sys.executable)

    assert result.mode == critic.MODE_ERROR
    assert result.detail == f"no package file at {missing}"
    assert result.text == "", "the reviewer was never called"
    assert not critic.package_dir(project).exists()


def test_a_package_text_that_ends_in_a_path_still_goes_as_text(stubbed, tmp_path):
    """Only a single line is taken for a path: a real package may well end by citing one."""
    stubbed("print(open(sys.argv[2], encoding='utf-8').read())\nprint('— [critic: m]')\n")
    project = _project(tmp_path)
    package = "## Package\nThe crossover plan.\nPrevious review: process/reviews/earlier-critic.md"

    result = critic.run(package, project_dir=project, python_executable=sys.executable)

    assert result.ok
    assert "The crossover plan." in result.text
    assert len(list(critic.package_dir(project).glob("pkg_*.md"))) == 1


def test_model_choice_reaches_the_subprocess_env(stubbed, tmp_path):
    stubbed("print(os.environ.get('GEMINI_CRITIC_MODEL', 'unset'))\nprint('— [critic: m]')\n")
    project = _project(tmp_path)

    result = critic.run(
        "pkg", project_dir=project, model="Gemini 3.1 Pro", python_executable=sys.executable
    )

    assert result.text.strip() == "Gemini 3.1 Pro"


def test_advisor_reads_the_same_model_var_as_the_critic(stubbed, tmp_path):
    """This test used to assert the opposite, and it was right until `v3.0.49`.

    Two tasks with two model variables is what made hub SKL-032: TCC set the critic's, the advisor
    door looked for its own, found none, and thirteen calls came back as clipboard packages with
    `model: null`. Upstream merged the roles — the advisor's variables are no longer read, and a
    value left in one is named on stderr rather than obeyed — so the assertion inverts with it.
    """
    stubbed("print(os.environ.get('GEMINI_CRITIC_MODEL', 'unset'))\nprint('— [advisor: m]')\n")
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


def test_a_reviewer_that_timed_out_says_what_it_last_printed(stubbed, tmp_path):
    """A reviewer waiting on a sign-in prompt said only «timed out»: what it had printed was
    reaped after the kill and thrown away (the G1 review)."""
    stubbed("import sys, time\n"
            "print('open the browser to sign in', file=sys.stderr, flush=True)\n"
            "time.sleep(30)\n")
    project = _project(tmp_path)

    result = critic.run(
        "pkg", project_dir=project, timeout_s=1.0, python_executable=sys.executable
    )

    assert result.mode == critic.MODE_ERROR
    assert "timed out" in result.detail and "open the browser to sign in" in result.detail


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
        critic.child, "run_bounded",
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

    monkeypatch.setattr(critic.child, "run_bounded", explode)

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


def test_a_headless_refusal_names_the_rule_agy_asked_for_and_the_route_that_works():
    """tcc#36. The advice named `trustedWorkspaces`, and following it changed nothing: the project
    was added, the JSON checked, the same call re-run — a byte-identical refusal (Windows,
    2026-09-14). agy says what it wants in the same breath: an allow-rule under `permissions.allow`,
    because a headless run cannot ask. And the wide answer (`toolPermission: always-proceed`) must
    not come next after a narrow one that did nothing: that walks a person to "every folder" by
    elimination. What does work on that machine today is the clipboard step.

    The settings path was read out of the binary: `~/.gemini/antigravity-cli/settings.json`."""
    from autosound_tcc.core import critic

    said = ('jetski: no output produced — a tool required the "read_file" permission that headless '
            'mode cannot prompt for, so it was auto-denied. Add an allow-rule under permissions.allow '
            'in settings.json (e.g. read_file(<target>)). Alternatively, re-run with '
            '--dangerously-skip-permissions to auto-approve all tools.')
    fix = critic.remedy(said, harness="agy", project_dir="/cars/golf-r")

    assert critic.AGY_SETTINGS in fix, "which file"
    assert "permissions.allow" in fix, "the key agy asked for"
    assert "read_file(" in fix, "for the tool it named"
    assert "/cars/golf-r" in fix, "and where the project is"
    assert "trustedWorkspaces" not in fix, "the key that was followed and changed nothing"
    assert "always-proceed" not in fix, "no wide answer after a narrow one"
    assert "clipboard" in fix, "and the route that works meanwhile"


def test_the_refused_tool_is_named_as_agy_spelled_it():
    from autosound_tcc.core import critic

    fix = critic.remedy(">> agy: permission required for list_dir(project.json)", harness="agy")

    assert "list_dir(" in fix and "read_file" not in fix


def test_a_rejected_key_says_it_is_tried_first_and_costs_the_time():
    """It is not just wrong — it is wrong FIRST. Every call spends the API attempt before falling
    back to the CLI, which is the path that works on a subscription login."""
    from autosound_tcc.core import critic

    fix = critic.remedy("Gemini API: HTTP 400 Bad Request", harness="agy")

    assert "GEMINI_API_KEY" in fix and "BEFORE" in fix


def test_nothing_is_invented_when_the_words_are_not_recognised():
    """A CLI is free to reword its errors. A miss must degrade to "here is what it said" rather
    than to a confident instruction about the wrong thing."""
    from autosound_tcc.core import critic

    assert critic.remedy("something nobody has seen before", harness="agy") == ""
    assert critic.remedy("", harness="agy") == ""


def test_the_reviewer_is_given_one_model_variable_for_both_tasks(tmp_path, monkeypatch):
    """The advisor's model variables are no longer read (`v3.0.49`, hub SKL-032) — a value left in
    one is named on stderr, not obeyed. And writing one was the whole of #130: TCC set the
    critic's model, the advisor door looked for its own, found none, and the channel came back as
    a clipboard package with `model: null` thirteen times."""
    from autosound_tcc.core import critic

    seen = {}
    monkeypatch.setattr(critic, "is_available", lambda: True)
    monkeypatch.setattr(critic, "preflight", lambda _p=None: [])
    monkeypatch.setattr(critic, "script_path", lambda: tmp_path / "autosound_ai.py")
    monkeypatch.setattr(critic.shutil, "which", lambda name: f"/usr/bin/{name}")

    def capture(_argv, **kwargs):
        seen.update(kwargs.get("env") or {})
        raise OSError("not actually running the reviewer in a test")

    monkeypatch.setattr(critic.child, "run_bounded", capture)

    critic.run("a package", project_dir=tmp_path, role="advisor",
               model="gemini-3.1-pro-high", harness="agy")

    assert seen.get("GEMINI_CRITIC_MODEL") == "gemini-3.1-pro-high", "the one variable, always"
    for retired in ("GEMINI_ADVISOR_MODEL", "AUTOSOUND_ADVISOR_MODEL"):
        assert retired not in seen, f"{retired} is retired upstream; setting it teaches a lie"


def test_extra_env_reaches_the_subprocess(tmp_path, monkeypatch):
    """`extra_env` is for one call only, applied last -- the reviewer probe uses it to point
    `AUTOSOUND_PROJECT_DIR` at a throwaway folder without touching the real project's env."""
    from autosound_tcc.core import critic

    seen = {}
    monkeypatch.setattr(critic, "is_available", lambda: True)
    monkeypatch.setattr(critic, "preflight", lambda _p=None: [])
    monkeypatch.setattr(critic, "script_path", lambda: tmp_path / "autosound_ai.py")
    monkeypatch.setattr(critic.shutil, "which", lambda name: f"/usr/bin/{name}")

    def capture(_argv, **kwargs):
        seen.update(kwargs.get("env") or {})
        raise OSError("not actually running the reviewer in a test")

    monkeypatch.setattr(critic.child, "run_bounded", capture)

    critic.run("a package", project_dir=tmp_path, role="ask", harness="agy",
               extra_env={"AUTOSOUND_PROJECT_DIR": "/scratch/probe"})

    assert seen.get("AUTOSOUND_PROJECT_DIR") == "/scratch/probe"


def test_extra_env_outranks_the_mirror_project_dir_implies(tmp_path, monkeypatch):
    """The reviewer probe runs from the real project and sends the script's writes elsewhere: the
    `PROJECT_MIRROR` it passes must win over the one `project_dir` implies (final review,
    Important 4), or the clipboard package and the audit line land in the project."""
    from autosound_tcc.core import critic

    seen = {}
    monkeypatch.setattr(critic, "is_available", lambda: True)
    monkeypatch.setattr(critic, "preflight", lambda _p=None: [])
    monkeypatch.setattr(critic, "script_path", lambda: tmp_path / "autosound_ai.py")
    monkeypatch.setattr(critic.shutil, "which", lambda name: f"/usr/bin/{name}")

    def capture(_argv, **kwargs):
        seen.update(kwargs.get("env") or {})
        seen["cwd"] = kwargs.get("cwd")
        raise OSError("not actually running the reviewer in a test")

    monkeypatch.setattr(critic.child, "run_bounded", capture)

    critic.run("a package", project_dir=tmp_path, role="ask", harness="agy",
               extra_env={"PROJECT_MIRROR": "/scratch/probe/rew_analitic"})

    assert seen["PROJECT_MIRROR"] == "/scratch/probe/rew_analitic"
    assert seen["cwd"] == str(tmp_path), "the cwd is still the project"


def test_a_model_refused_for_this_location_says_so_rather_than_that_names_drift():
    """A Windows session, 2026-09-13: agy answered `error: Selected model is not supported in the
    selected location.` The remedy matched the word "model" and said model names drift and that ↻
    re-reads the list — but the CLI still lists that model, so ↻ changes nothing and the advice sends
    somebody round in a circle. What helps is a different model, and saying why."""
    from autosound_tcc.core import critic

    fix = critic.remedy("error: Selected model is not supported in the selected location.",
                        harness="agy")

    assert "location" in fix, "names the actual reason"
    assert "footer" in fix, "and the one thing to do"
    assert "drift" not in fix, "not the wrong reason"


def test_a_refusal_is_named_by_its_reason_or_not_at_all():
    from autosound_tcc.core import availability, critic

    assert critic.refusal_reason("error: Selected model is not supported in the selected location.") \
        == availability.LOCATION
    assert critic.refusal_reason("Gemini API: HTTP 400 Bad Request") == availability.REFUSED
    assert critic.refusal_reason("") is None


def test_a_refusal_is_its_own_mode_with_the_reasons_and_the_package(stubbed, tmp_path):
    """hub #154 §5 (method v3.0.53): a reviewer with no answer exits 4 and prints its reasons under
    "⛔ РЕЦЕНЗІЇ НЕ ОТРИМАНО", then the package for the clipboard rung. Read as an error, the tail
    was the package lines and the reasons were lost above them."""
    stubbed(
        "print('=' * 50, file=sys.stderr)\n"
        "print('⛔ РЕЦЕНЗІЇ НЕ ОТРИМАНО — нічого не збережено як рецензію:', file=sys.stderr)\n"
        "print(\"   · CLI 'agy': quota exhausted\", file=sys.stderr)\n"
        "print('     → wait for the reset or pick another model', file=sys.stderr)\n"
        "print('   Наступна сходинка — буфер обміну (нижче).', file=sys.stderr)\n"
        "print('=' * 50, file=sys.stderr)\n"
        "print('✓ Пакет (запит, не рецензія): /p/process/reviews/x-critic-package.md', file=sys.stderr)\n"
        "print('>> PACKAGE_FILE: process/reviews/x-critic-package.md', file=sys.stderr)\n"
        "print('=' * 50, file=sys.stderr)\n"
        "sys.exit(4)\n"
    )
    project = _project(tmp_path)

    result = critic.run("package", project_dir=project, python_executable=sys.executable)

    assert result.mode == critic.MODE_REFUSED
    assert result.ok is False
    assert "quota exhausted" in result.detail and "pick another model" in result.detail
    assert "PACKAGE_FILE" not in result.detail
    assert result.package == "process/reviews/x-critic-package.md"



def _env_seen_by_reviewer(tmp_path, monkeypatch, harness):
    from autosound_tcc.core import critic

    seen = {}
    monkeypatch.setattr(critic, "is_available", lambda: True)
    monkeypatch.setattr(critic, "preflight", lambda _p=None: [])
    monkeypatch.setattr(critic, "script_path", lambda: tmp_path / "autosound_ai.py")
    monkeypatch.setattr(critic.shutil, "which", lambda name: f"/usr/bin/{name}")

    def capture(_argv, **kwargs):
        seen.update(kwargs.get("env") or {})
        raise OSError("not actually running the reviewer in a test")

    monkeypatch.setattr(critic.child, "run_bounded", capture)
    critic.run("a package", project_dir=tmp_path, harness=harness, model="gemini-3.8-flash-high")
    return seen


def test_a_key_in_the_launching_shell_does_not_reroute_a_cli_pick_to_the_api(tmp_path, monkeypatch):
    """Finding 32: TCC handed the reviewer its whole environment, so a GEMINI_API_KEY in the shell
    that started TCC sent an `agy` pick down the API — where `gemini-3.8-flash-high` does not
    exist, a 404. With the CLI picked, the matching key stays out of the child's environment."""
    monkeypatch.setenv("GEMINI_API_KEY", "AQ." + "x" * 50)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")

    agy = _env_seen_by_reviewer(tmp_path, monkeypatch, "agy")
    assert "GEMINI_API_KEY" not in agy
    assert agy.get("OPENAI_API_KEY") == "sk-x", "only the key that reroutes THIS pick"


def test_an_api_pick_keeps_its_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AQ." + "x" * 50)
    assert "GEMINI_API_KEY" in _env_seen_by_reviewer(tmp_path, monkeypatch, "omp")


def test_a_session_shell_inherits_the_reviewer_the_arbiter_picked(tmp_path, monkeypatch):
    """Findings 17, 21: a session that ran the reviewer script itself was refused for "no model"
    although TCC had one picked. The session's environment now carries it."""
    from autosound_tcc.core import critic

    monkeypatch.setattr(critic, "configured", lambda _p: ("gemini-3.8-flash-high", "agy"))
    monkeypatch.setattr(critic, "critic_bin_override", lambda harness="": {"AUTOSOUND_CRITIC_BIN": "agy"})
    assert critic.session_env(tmp_path) == {"AUTOSOUND_CRITIC_MODEL": "gemini-3.8-flash-high",
                                            "AUTOSOUND_CRITIC_VIA": "cli",
                                            "AUTOSOUND_CRITIC_BIN": "agy"}
    monkeypatch.setattr(critic, "configured", lambda _p: ("", ""))
    assert critic.session_env(tmp_path) == {}


def test_the_session_is_told_to_reach_the_reviewer_through_tcc():
    from autosound_tcc.core import tuning_session

    assert "call_critic" in tuning_session.SYSTEM_PROMPT_APPEND
    # Finding 124: a session that did not know the ASK door sent its question as a review.
    assert "ask_reviewer" in tuning_session.SYSTEM_PROMPT_APPEND


def test_an_omp_pick_reaches_the_reviewer_by_omp_s_own_selector(tmp_path):
    """tcc#57 cut omp's `provider/` prefix, because the reviewer script ran no omp and the vendor's
    API or CLI takes no prefix. The Arbiter reversed it on 2026-09-27 (tcc#74): an OMP pick goes
    through omp, which needs its full selector; the bare name went to the API and came back 404."""
    from autosound_tcc.core import config, critic, model_choices, project_settings

    for key, sent in (("omp:google-antigravity/gemini-3.5-flash-lite",
                       "google-antigravity/gemini-3.5-flash-lite"),
                      ("agy:gemini-3.8-flash-high", "gemini-3.8-flash-high")):
        project_settings.set_value(config.tcc_dir(tmp_path), "critic", key)
        assert critic.configured(tmp_path)[0] == sent, key
        _, choice = model_choices.resolve_critic(key)
        assert model_choices.reviewer_model(choice) == sent, key


def test_the_omp_route_is_read_from_the_methods_own_list(tmp_path, monkeypatch):
    """No version pin (hub #216): the route exists when the method's script lists it in
    `VIA_ROUTES`, so the Arbiter can test it on the skill's working tree before the tag."""
    from autosound_tcc.core import critic

    script = tmp_path / "autosound_ai.py"
    monkeypatch.setattr(critic, "script_path", lambda: script)
    assert critic.omp_route_available() is False, "no script, no route"
    script.write_text('VIA_ROUTES = ("api", "cli", "clipboard")\n', encoding="utf-8")
    assert critic.omp_route_available() is False
    script.write_text('VIA_ROUTES = ("api", "cli", "omp", "clipboard")\n', encoding="utf-8")
    assert critic.omp_route_available() is True


def test_with_the_omp_route_an_omp_pick_runs_through_omp_only(tmp_path, monkeypatch):
    from autosound_tcc.core import config, critic, project_settings

    monkeypatch.setattr(critic, "omp_route_available", lambda: True)
    monkeypatch.setattr(critic, "is_available", lambda: True)
    monkeypatch.setattr(critic, "preflight", lambda _p=None: [])
    monkeypatch.setattr(critic, "script_path", lambda: tmp_path / "autosound_ai.py")
    seen = {}

    def _fake(argv, **kw):
        seen["argv"] = argv
        raise OSError("stop here")

    monkeypatch.setattr(critic.child, "run_bounded", _fake)
    critic.run("# hi", project_dir=tmp_path, model="google-antigravity/gemini-3.1-pro-high",
               harness="omp")
    assert seen["argv"][seen["argv"].index("--via") + 1] == "omp"

    project_settings.set_value(config.tcc_dir(tmp_path), "critic",
                               "omp:google-antigravity/gemini-3.1-pro-high")
    assert critic.session_env(tmp_path) == {
        "AUTOSOUND_CRITIC_MODEL": "google-antigravity/gemini-3.1-pro-high",
        "AUTOSOUND_CRITIC_BIN": "omp", "AUTOSOUND_CRITIC_VIA": "omp"}


def test_one_call_can_ask_for_the_api_route_and_keeps_the_key_for_it(tmp_path, monkeypatch):
    """tcc#59, finding 63: after a cut-off agy stream the method said «з ключем API — `--via api`
    для цього запуску», and `call_critic` could not ask for it — so the Generator ran the script
    itself, and the critique never reached the window. With a CLI picked, finding 32 keeps the API
    key out of the child; a run that asks for the API must keep it."""
    from autosound_tcc.core import critic

    monkeypatch.setenv("GEMINI_API_KEY", "AQ." + "x" * 50)
    seen = {}
    monkeypatch.setattr(critic, "is_available", lambda: True)
    monkeypatch.setattr(critic, "preflight", lambda _p=None: [])
    monkeypatch.setattr(critic, "script_path", lambda: tmp_path / "autosound_ai.py")
    monkeypatch.setattr(critic.shutil, "which", lambda name: f"/usr/bin/{name}")

    def capture(argv, **kwargs):
        seen["argv"], seen["env"] = list(argv), dict(kwargs.get("env") or {})
        raise OSError("not actually running the reviewer in a test")

    monkeypatch.setattr(critic.child, "run_bounded", capture)
    critic.run("a package", project_dir=tmp_path, harness="agy", model="gemini-3.8-flash-high",
               via="api")
    assert seen["argv"][-2:] == ["--via", "api"]
    assert "GEMINI_API_KEY" in seen["env"]

    critic.run("a package", project_dir=tmp_path, harness="agy", model="gemini-3.8-flash-high")
    # Without the ask, the pick's own route — its CLI (tcc#127).
    assert seen["argv"][-2:] == ["--via", "cli"] and "GEMINI_API_KEY" not in seen["env"]


def test_an_api_pick_runs_through_the_key_and_an_omp_pick_hands_a_session_nothing(tmp_path,
                                                                                   monkeypatch):
    """tcc#74: «API · …» is the key's route and nothing else, so the run asks the script for
    `--via api`; an OMP pick has no route in the script yet, and a session's own shell must not be
    handed a model it would take to the API under a cut-down name."""
    from autosound_tcc.core import config, critic, project_settings

    monkeypatch.setattr(critic, "is_available", lambda: True)
    monkeypatch.setattr(critic, "preflight", lambda _p=None: [])
    monkeypatch.setattr(critic, "script_path", lambda: tmp_path / "autosound_ai.py")
    seen = {}

    def _fake(argv, **kw):
        seen["argv"] = argv
        raise OSError("stop here")

    monkeypatch.setattr(critic.child, "run_bounded", _fake)
    critic.run("# hi", project_dir=tmp_path, model="gemini-pro-latest", harness="api")
    assert "--via" in seen["argv"] and seen["argv"][seen["argv"].index("--via") + 1] == "api"

    project_settings.set_value(config.tcc_dir(tmp_path), "critic",
                               "omp:google-antigravity/gemini-3.1-pro-high")
    assert critic.session_env(tmp_path) == {}


# ---- ask: a plain question on the reviewer's channel (tcc#116) --------------------------------


def test_ask_runs_the_methods_ask_task_in_a_project_with_no_tuning_files(stubbed, tmp_path):
    """Finding 124: «перевір критика зразу при старті через режим ASK» — at the start, so in a
    folder intake has not reached. The method's `ask` needs no contract and no context (skill#27),
    so TCC must not hold it back for the two files a review needs; the model goes over exactly as
    a review's does."""
    stubbed(
        "print('task=' + sys.argv[1])\n"
        "print('model=' + os.environ.get('GEMINI_CRITIC_MODEL', 'unset'))\n"
        "print('question=' + open(sys.argv[2], encoding='utf-8').read().strip())\n"
        "print('— [ask: gemini-3.1-pro-high]')\n"
    )
    bare = tmp_path / "fresh"
    bare.mkdir()

    result = critic.run("Are you there?", project_dir=bare, role=critic.ASK,
                        model="gemini-3.1-pro-high", python_executable=sys.executable)

    assert result.mode == critic.MODE_API_OR_CLI, result.detail
    assert "task=ask" in result.text
    assert "model=gemini-3.1-pro-high" in result.text
    assert "question=Are you there?" in result.text
    assert result.role == "ask" and result.model == "gemini-3.1-pro-high"
    # The same folder, asked for a review: still not ready, the two files are still missing.
    assert critic.run("pkg", project_dir=bare,
                      python_executable=sys.executable).mode == critic.MODE_NOT_READY


def test_a_question_is_sent_as_text_even_when_it_reads_like_a_package_path(stubbed, tmp_path):
    """A review's one-line `….md` is a package path (tcc#119); a question never is. «Що в
    process/reviews/old-critic.md?» sent as that file's contents, or refused as "no package file",
    would answer a question nobody asked."""
    stubbed("print(open(sys.argv[2], encoding='utf-8').read())\nprint('— [ask: m]')\n")
    project = _project(tmp_path)
    (project / "process" / "reviews").mkdir(parents=True)
    (project / "process" / "reviews" / "old-critic.md").write_text("THE OLD REVIEW", encoding="utf-8")

    for question in ("process/reviews/old-critic.md", "process/reviews/missing.md"):
        result = critic.run(question, project_dir=project, role=critic.ASK,
                            python_executable=sys.executable)
        assert result.ok, result.detail
        assert result.text.strip() == question


def test_the_ask_package_is_the_question_then_the_sessions_context():
    """The script puts the file under «GENERATOR'S QUESTION» and adds the project's own context as
    background itself; what the session adds goes under its own heading after the question."""
    with_context = critic.ask_package("  Is the channel alive?  ", "  Start of the session.  ")
    assert with_context.startswith("Is the channel alive?")
    assert with_context.index("Is the channel alive?") < with_context.index("Start of the session.")
    assert "## Context" in with_context

    bare = critic.ask_package("Is the channel alive?")
    assert bare.strip() == "Is the channel alive?"


# ---- the run's own model, by the method's `--model` (tcc#113, hub #226) ------------------------

#: The method's usage line from v3.0.65 (`main()`, naming `--model`) and the one before it. Pinned
#: to the vendored source below, as `test_reviewer_key` pins the usage `key help` prints.
_USAGE_WITH_MODEL = ("Використання: python3 scripts/autosound_ai.py [critic|advisor|ask|doctor] "
                     "<package_file.md> [trace.csv] [--via api|cli|omp|clipboard] [--model <id>] "
                     "[--provider google|anthropic|openai]")
_USAGE_BEFORE = ("Використання: python3 scripts/autosound_ai.py [critic|advisor|ask|doctor] "
                 "<package_file.md> [trace.csv]")


def _lost_pins_line(pick: str, pins, provider: str = "google") -> str:
    """The method's one stderr line naming what this run's `--model` set aside (`lost_pins`)."""
    lost = "; ".join(f"{var}={value} ({f'{path}, рядок {line}' if path else 'змінна середовища'})"
                     for var, value, path, line in pins)
    return (f">> --model {pick}: рецензент цього запуску — {pick} (провайдер {provider}); "
            f"не діють для нього: " + lost + ". Для інших запусків закріплене лишається типовим")


def _method_stub(usage: str) -> str:
    """The method's order, as far as these tests need it: its usage with no task; every line of
    the project's `.critic-env` written over the environment; `--model` (when its usage names it)
    before any of that; the pins it set aside named in one stderr line; the model in the marker."""
    takes = "--model" in usage
    return (
        "import json\n"
        f"if len(sys.argv) < 2:\n    print({usage!r})\n    sys.exit(1)\n"
        "args = sys.argv[1:]\n"
        "said = json.dumps(args)\n"
        "pick = None\n"
        f"if {takes!r} and '--model' in args:\n"
        "    i = args.index('--model'); pick = args[i + 1]; del args[i:i + 2]\n"
        "pins = []\n"
        "path = os.path.join(os.getcwd(), '.critic-env')\n"
        "if os.path.isfile(path):\n"
        "    for n, line in enumerate(open(path, encoding='utf-8').read().splitlines(), 1):\n"
        "        k, _, v = line.partition('=')\n"
        "        if k and v:\n"
        "            os.environ[k] = v\n"
        "            pins.append((k, v, path, n))\n"
        "model = pick or os.environ.get('AUTOSOUND_CRITIC_MODEL') or os.environ.get('GEMINI_CRITIC_MODEL')\n"
        "lost = [f'{k}={v} ({p}, рядок {n})' for k, v, p, n in pins if pick and v not in (pick, 'google')]\n"
        "if lost:\n"
        "    print(f'>> --model {pick}: рецензент цього запуску — {pick} (провайдер google); '\n"
        "          'не діють для нього: ' + '; '.join(lost) + '. Для інших запусків закріплене лишається типовим',\n"
        "          file=sys.stderr)\n"
        "print('argv=' + said)\n"
        "print('— [' + args[0] + ': ' + str(model) + ']')\n"
    )


def _capture_argv(tmp_path, monkeypatch) -> dict:
    """The reviewer's argv and env as `run` sends them, nothing actually run."""
    seen = {}
    monkeypatch.setattr(critic, "is_available", lambda: True)
    monkeypatch.setattr(critic, "preflight", lambda _p=None: [])
    monkeypatch.setattr(critic, "script_path", lambda: tmp_path / "autosound_ai.py")

    def capture(argv, **kwargs):
        seen["argv"], seen["env"] = list(argv), dict(kwargs.get("env") or {})
        raise OSError("not actually running the reviewer in a test")

    monkeypatch.setattr(critic.child, "run_bounded", capture)
    return seen


def test_the_pick_goes_by_the_model_flag_only_to_a_method_that_takes_it(tmp_path, monkeypatch):
    """Finding 130 (tcc#113): on the VM the footer said «API · gemini-3.1-pro-preview» and the run
    went as `gpt-5.6-terra` — every critic-env line is written over the environment, and the pick
    travelled as an environment variable. From v3.0.65 the method takes the run's own model as
    `--model`, which no pin outranks (hub #226). An older one would read the flag as the trace
    file, so it is handed the variable, as before. One place for every task."""
    seen = _capture_argv(tmp_path, monkeypatch)
    for role in ("critic", "advisor", critic.ASK):
        monkeypatch.setattr(critic, "takes_model_flag", lambda *_a, **_k: True)
        critic.run("a package", project_dir=tmp_path, role=role, model="gemini-3.1-pro-preview",
                   harness="api", provider="google")
        argv = seen["argv"]
        assert argv[argv.index("--model") + 1] == "gemini-3.1-pro-preview", (role, argv)
        assert argv[argv.index("--provider") + 1] == "google", (role, argv)
        assert argv[argv.index("--via") + 1] == "api", "the route still goes with it"

        monkeypatch.setattr(critic, "takes_model_flag", lambda *_a, **_k: False)
        critic.run("a package", project_dir=tmp_path, role=role, model="gemini-3.1-pro-preview",
                   harness="api", provider="google")
        assert "--model" not in seen["argv"] and "--provider" not in seen["argv"], seen["argv"]
        assert seen["env"]["GEMINI_CRITIC_MODEL"] == "gemini-3.1-pro-preview"


def test_the_provider_goes_only_when_tcc_knows_one_the_method_takes(tmp_path, monkeypatch):
    """`--provider` names the vendor when TCC knows it (hub #226); otherwise the model's name
    decides, in the method. An omp pick's vendor is omp's (tcc#74), and a name the method does not
    list it refuses as a usage error. With no model there is nothing to name, and nothing asked."""
    seen = _capture_argv(tmp_path, monkeypatch)
    asked = []
    monkeypatch.setattr(critic, "takes_model_flag", lambda *_a, **_k: asked.append(1) or True)

    critic.run("# hi", project_dir=tmp_path, model="google-antigravity/gemini-3.1-pro-high",
               harness="omp", provider="google")
    assert seen["argv"][seen["argv"].index("--model") + 1] == "google-antigravity/gemini-3.1-pro-high"
    assert "--provider" not in seen["argv"]

    critic.run("# hi", project_dir=tmp_path, model="house-reviewer", harness="agy",
               provider="google-antigravity")
    assert "--model" in seen["argv"] and "--provider" not in seen["argv"]

    asked.clear()
    critic.run("# hi", project_dir=tmp_path, harness="agy", provider="google")
    assert "--model" not in seen["argv"] and "--provider" not in seen["argv"]
    assert asked == [], "no model, no question to the method"


def test_whether_the_method_takes_model_is_read_from_its_usage_line(tmp_path, monkeypatch):
    """Not a version number (hub #226): the method takes `--model` when its usage line names it,
    as the omp route is read from `VIA_ROUTES` — the Arbiter tests on the skill's working tree
    before the tag, and a manifest's number is kept by hand (`install_report.skill_version`)."""
    script = tmp_path / "autosound_ai.py"
    monkeypatch.setattr(critic, "script_path", lambda: script)
    assert critic.takes_model_flag() is False, "no script, no flag"
    script.write_text(f"print({_USAGE_BEFORE!r})\n", encoding="utf-8")
    assert critic.takes_model_flag() is False
    script.write_text(f"print({_USAGE_WITH_MODEL!r})\n", encoding="utf-8")
    assert critic.takes_model_flag() is True


def test_a_pinned_critic_env_does_not_change_the_model_tcc_asked_for(stubbed, tmp_path,
                                                                     monkeypatch):
    """The VM's case end to end: the project's `.critic-env` pins another model and a provider.
    A method that takes `--model` answers with TCC's pick and names the pins it set aside; the one
    before it is handed the variable alone, and its pin wins — finding 130 as it happened."""
    project = _project(tmp_path)
    env_file = project / ".critic-env"
    env_file.write_text("AUTOSOUND_CRITIC_MODEL=gpt-5.6-terra\nAUTOSOUND_CRITIC_PROVIDER=openai\n",
                        encoding="utf-8")

    stubbed(_method_stub(_USAGE_WITH_MODEL))
    result = critic.run("pkg", project_dir=project, model="gemini-3.1-pro-preview", harness="api",
                        provider="google", python_executable=sys.executable)
    assert result.ok, result.detail
    assert result.model == "gemini-3.1-pro-preview"
    assert result.pins_set_aside == [
        {"variable": "AUTOSOUND_CRITIC_MODEL", "value": "gpt-5.6-terra", "file": str(env_file),
         "line": 1},
        {"variable": "AUTOSOUND_CRITIC_PROVIDER", "value": "openai", "file": str(env_file),
         "line": 2},
    ]

    stubbed(_method_stub(_USAGE_BEFORE))
    result = critic.run("pkg", project_dir=project, model="gemini-3.1-pro-preview", harness="api",
                        provider="google", python_executable=sys.executable)
    assert "--model" not in result.text, result.text
    assert result.model == "gpt-5.6-terra"
    assert result.pins_set_aside is None, "an older method reports no pins; none is invented"


def test_the_pins_a_run_set_aside_are_read_by_the_lines_shape():
    """By the flag that opens the line and its `VAR=value (where)` entries — not by its Ukrainian
    words. A Windows path may hold parentheses; a pin from the environment has no file."""
    machine = r"C:\Users\Tuner (Work)\AppData\Roaming\autosound\critic-env"
    line = _lost_pins_line("gemini-3.1-pro-preview", [
        ("AUTOSOUND_CRITIC_MODEL", "gpt-5.6-terra", machine, 1),
        ("AUTOSOUND_CRITIC_PROVIDER", "openai", machine, 2),
        ("AUTOSOUND_CRITIC_MODEL", "anthropic/claude-sonnet-5", "/p/rew_analitic/.critic-env", 3),
        ("GEMINI_CRITIC_MODEL", "gemini-2.5-pro", None, None),
    ])
    stderr = f"critic-env: рядок відкинуто\n{line}\n>> PACKAGE_FILE: process/x.md\n"

    assert critic._pins_set_aside(stderr) == [
        {"variable": "AUTOSOUND_CRITIC_MODEL", "value": "gpt-5.6-terra", "file": machine, "line": 1},
        {"variable": "AUTOSOUND_CRITIC_PROVIDER", "value": "openai", "file": machine, "line": 2},
        {"variable": "AUTOSOUND_CRITIC_MODEL", "value": "anthropic/claude-sonnet-5",
         "file": "/p/rew_analitic/.critic-env", "line": 3},
        {"variable": "GEMINI_CRITIC_MODEL", "value": "gemini-2.5-pro", "file": None, "line": None},
    ]
    assert critic._pins_set_aside(">> REVIEW_FILE: process/reviews/x.md\n") == []


def test_the_fake_usage_and_pins_line_are_the_vendored_methods_own():
    """The fakes above stand for the method's real words: its usage names `--model`, and
    `lost_pins` prints that line. Pinned to the vendored source so they cannot drift."""
    script = (Path(__file__).resolve().parents[1] / "vendor" / "autosound-tuning-skill" / "skills"
              / "autosound-tuning" / "scripts" / "autosound_ai.py")
    if not script.is_file():
        pytest.skip("the method's submodule is not checked out")
    source = script.read_text(encoding="utf-8")
    assert _USAGE_WITH_MODEL[_USAGE_WITH_MODEL.index("[--via"):] in source
    assert _USAGE_BEFORE.split("[trace.csv]")[0] in source
    for words in ('f">> {flags}: рецензент цього запуску — ', "(провайдер {provider}); ",
                  'f"не діють для нього: " + "; ".join(lost) + ". Для інших запусків закріплене '
                  'лишається типовим"',
                  "f\"{var}={value} ({f'{path}, рядок {line}' if path else 'змінна середовища'})\""):
        assert words in source, words


# ── VM-4 (tcc#113): the set-aside-pins line is no refusal ─────────────────────────────────────────

#: The VM's line, 2026-10-01: `ask_reviewer` answered over the API (gemini, 10.5 s) with a
#: critic-env pin set aside, and the result still said «the reviewer CLI refused the model».
_VM_PINS = _lost_pins_line("gemini-3.1-pro-preview", [
    ("AUTOSOUND_CRITIC_MODEL", "gpt-5.6-terra",
     r"C:\Users\Tuner\AppData\Roaming\autosound\critic-env", 1)])

#: What a reviewer CLI says when it refuses the model it was given, in its own words: the method's
#: recogniser (`_FAILURES`' `bad_model`, pinned to the vendored source below), agy's answer on a
#: clipboard fall, and the method's own 404 for a model the key cannot call.
_MODEL_REFUSALS = {
    "agy-invalid-selection": ('error: invalid model selection (--model "gemini-3.5-flash-medium" '
                              '--effort ""): model gemini-3.5-flash-medium is not recognized as a '
                              'known model or custom model in settings'),
    "unknown-model": "Error: unknown model gemini-9-ultra",
    "model-not-found": 'Model "gemini-9-ultra" not found',
    "agy-not-available": ">> ⛔ agy повернув помилку: model 'gemini-3.8-flash-low' is not available",
    "method-404": (">> Модель `gemini-2.5-flash` цей ключ викликати не може: HTTP 404 — This model "
                   "models/gemini-2.5-flash is no longer available to new users."),
    "method-omp-unknown": ">> Модель `google-antigravity/gemini-9` omp не знає: no such selector",
    "method-cli-unknown": ">> Модель `gemini-9` CLI 'agy' не знає: exit 1",
    # skill #85 (`cli_model_mismatch`): an API id stepped down to agy, which does not list it.
    "method-cli-mismatch": ("· CLI 'agy' не знає `gemini-3.1-pro-preview` (так модель називає API); "
                            "його моделі цієї лінії: gemini-3.1-pro-high, gemini-3.1-pro-low. Задай "
                            "AUTOSOUND_CRITIC_MODEL=<одна з них> -- сходинка сама модель не вгадує"),
}


def test_the_pins_line_is_no_refusal():
    """VM-4: the bare word «model» matched the pins line (`AUTOSOUND_CRITIC_MODEL=…`, hub #226),
    which #113 reads into the footer's note — never as a refusal, and never as a reason."""
    from autosound_tcc.core import critic

    tail = f"{_VM_PINS}\n>> REVIEW_ROUTE: api\n>> REVIEW_FILE: process/reviews/x-ask.md"
    assert critic.remedy(tail, harness="agy") == ""
    assert critic.remedy(_VM_PINS, harness="agy") == ""
    assert critic.refusal_reason(_VM_PINS) is None
    # «model» alone says nothing about a refusal; nor does the method taking the CLI for a model
    # the API does not know but the CLI serves.
    assert critic.remedy("the model answered in 10.5 s", harness="agy") == ""
    assert critic.remedy(">> API не знає `gemini-3.1-pro-high` (404), а CLI agy її знає: шлях — CLI",
                         harness="agy") == ""


@pytest.mark.parametrize("said", list(_MODEL_REFUSALS.values()), ids=list(_MODEL_REFUSALS))
def test_a_real_model_refusal_still_says_what_to_do(said):
    """The CLI's own refusals keep their hint — beside the pins line too, which the method prints
    before it calls anybody."""
    from autosound_tcc.core import availability, critic

    for detail in (said, f"{_VM_PINS}\n{said}"):
        assert "refused the model" in critic.remedy(detail, harness="agy"), detail
        assert critic.refusal_reason(detail) == availability.REFUSED


def test_the_model_refusal_words_are_the_vendored_methods_own():
    """The method's recogniser of a refused model, which `_MODEL_REFUSALS` stands for."""
    script = (Path(__file__).resolve().parents[1] / "vendor" / "autosound-tuning-skill" / "skills"
              / "autosound-tuning" / "scripts" / "autosound_ai.py")
    if not script.is_file():
        pytest.skip("the method's submodule is not checked out")
    source = script.read_text(encoding="utf-8")
    assert ('("bad_model", r"invalid model selection|not recognized as a known model|unknown model|'
            'Model \\"[^\\"]*\\" not found"),') in source
    for words in ("цей ключ викликати не може: HTTP 404", 'f"Модель `{model}` omp не знає: ',
                  'f"Модель `{model}` CLI \'{cli_bin}\' не знає: ',
                  "CLI 'agy' не знає `{model}` (так модель називає API)"):
        assert words in source, words


# ── VM-4 review, Important 2: the rejected-key note on a run that answered ──────────────────────

#: The method's step down from a failed API call to a CLI, with Gemini's words for a key it does
#: not take (`autosound_ai.py`: `>> Помилка виклику API ({e}). Спроба локального CLI...`).
_KEY_REJECTED = (">> Помилка виклику API (Помилка запиту до Gemini API: HTTP Error 400: Bad Request "
                 "— API key not valid. Please pass a valid API key.). Спроба локального CLI...")
#: An answered `--via api` run names the key it took — and says «api_key» while doing so.
_VIA_API_KEY = (">> --via api: ключ GEMINI_API_KEY із середовища; "
                "/Users/x/.config/autosound/critic-env (рядок 2) гасить його для інших запусків")


def test_an_answer_after_a_rejected_key_keeps_the_key_note():
    """The key was rejected and a CLI answered after it: the note is true — every call spends the
    API attempt first — and an answered result is the only place a session can learn it."""
    from autosound_tcc.core import critic

    note = critic.fallback_note(f"{_VM_PINS}\n{_KEY_REJECTED}\n>> REVIEW_ROUTE: cli")
    assert "`GEMINI_API_KEY` is set and the API rejected it" in note and "BEFORE" in note
    assert "refused the model" not in note


def test_the_key_note_on_an_answer_is_read_from_the_step_down_line_only():
    """Not from the whole tail: the `--via api` line names the key, the pins line names variables,
    and neither is a rejection."""
    from autosound_tcc.core import critic

    assert critic.fallback_note(f"{_VIA_API_KEY}\n>> REVIEW_ROUTE: api") == ""
    assert critic.fallback_note(_VM_PINS) == ""
    assert critic.fallback_note("Gemini API: HTTP 400 Bad Request") == "", "not the method's line"
    assert critic.fallback_note(">> Помилка виклику API (HTTP Error 503: Service Unavailable). "
                                "Спроба локального CLI...") == "", "a failure, not the key"
    # A line that names no vendor names no variable either: not Gemini's for every key.
    note = critic.fallback_note(">> Помилка виклику API (HTTP Error 400: Bad Request — API key "
                                "not valid). Спроба локального CLI...")
    assert "rejected it" in note and "GEMINI_API_KEY" not in note


def test_the_step_down_line_is_the_vendored_methods_own():
    script = (Path(__file__).resolve().parents[1] / "vendor" / "autosound-tuning-skill" / "skills"
              / "autosound-tuning" / "scripts" / "autosound_ai.py")
    if not script.is_file():
        pytest.skip("the method's submodule is not checked out")
    source = script.read_text(encoding="utf-8")
    for words in ('f">> Помилка виклику API ({e}). Спроба локального CLI..."',
                  'f"Помилка запиту до Gemini API: {e}', 'f">> --via api: ключ {hidden[0]} із середовища; '):
        assert words in source, words


# ── tcc#129: Anthropic's and OpenAI's rejected key is urllib's bare «HTTP Error 401» ──────────────

def _connect(provider: str, model: str) -> str:
    """The method's line before its API call, naming the vendor it calls."""
    return f">> Підключення до API ({provider}, {model}), чекаю до 300 с..."


#: The step down after an Anthropic or OpenAI call refused: `_post_json` lets urllib's own
#: exception through, so the line says the status and names neither the key nor the vendor.
_BARE = ">> Помилка виклику API (HTTP Error {code}: {why}). Спроба локального CLI..."
_BARE_401 = _BARE.format(code=401, why="Unauthorized")
_BARE_403 = _BARE.format(code=403, why="Forbidden")
_VENDOR_MODELS = {"anthropic": ("claude-opus-4-7", "ANTHROPIC_API_KEY"),
                  "openai": ("gpt-5.5", "OPENAI_API_KEY")}


@pytest.mark.parametrize("vendor", list(_VENDOR_MODELS))
def test_a_bare_401_from_anthropic_or_openai_is_a_rejected_key(vendor):
    """No key word matches «HTTP Error 401: Unauthorized», so those keys never got the note: read
    from the method's own step-down line, with the variable of the vendor it called."""
    from autosound_tcc.core import critic

    model, var = _VENDOR_MODELS[vendor]
    note = critic.fallback_note("\n".join((
        _connect(vendor, model), _BARE_401,
        f">> Виклик локального CLI 'x' ({vendor}), чекаю до 600 с...", ">> REVIEW_ROUTE: cli")))
    assert f"`{var}` is set and the API rejected it" in note and "BEFORE" in note


def test_a_403_is_not_read_as_a_rejected_key():
    """401 only (review of #129, Important 1). Anthropic's 403 is most often «Request not allowed»
    from a region, a proxy or a VPN — the key fine — and OpenAI's is a country it does not serve;
    the bare words cannot tell those from a key's permissions, so no note sends the Arbiter to
    replace a good key."""
    from autosound_tcc.core import critic

    for vendor, (model, _var) in _VENDOR_MODELS.items():
        assert critic.fallback_note(f"{_connect(vendor, model)}\n{_BARE_403}") == "", vendor
        assert critic.fallback_note(_BARE_403, vendor=vendor) == "", vendor
        refused = f"· API {vendor}: HTTP Error 403: Forbidden\n· CLI 'x': not signed in"
        assert "rejected it" not in critic.remedy(refused, harness="claude"), vendor
    assert critic.fallback_note(_BARE_403) == ""


def test_a_bare_401_with_no_vendor_line_names_no_variable():
    """The tail may have lost the line naming the vendor: the 401 is still one of the two keys
    (Gemini's are wrapped in its own words), so the note stands, naming no variable."""
    from autosound_tcc.core import critic

    note = critic.fallback_note(f"{_BARE_401}\n>> REVIEW_ROUTE: cli")
    assert "The API key is set and the API rejected it" in note
    assert "_API_KEY" not in note


def test_a_401_is_read_from_the_method_s_api_line_only():
    """A CLI's own 401 is its login, not the API key: `claude` says it of an expired sign-in. And
    Gemini's 401 is not the two vendors' case: its rejected key says «API key not valid»."""
    from autosound_tcc.core import critic

    cli_401 = ('>> ⛔ claude повернув помилку: API Error: 401 {"type":"error","error":{"type":'
               '"authentication_error","message":"OAuth token has expired."}}')
    failed = _BARE.format(code=503, why="Service Unavailable")
    assert critic.fallback_note(
        f"{_connect('anthropic', 'claude-opus-4-7')}\n{failed}\n{cli_401}") == ""
    assert "rejected it" not in critic.remedy(
        f"· CLI 'claude': {cli_401}\nНаступна сходинка — буфер обміну", harness="claude")
    gemini_401 = (">> Помилка виклику API (Помилка запиту до Gemini API: HTTP Error 401: "
                  "Unauthorized). Спроба локального CLI...")
    assert critic.fallback_note(f"{_connect('google', 'gemini-3-pro')}\n{gemini_401}") == ""


@pytest.mark.parametrize("vendor", list(_VENDOR_MODELS))
def test_a_refusal_after_a_bare_401_says_the_key(vendor):
    """A run that did not answer carries the method's refusal block, not its step-down line: the
    same words, on the block's own line for the API rung (`· API <vendor>: …`)."""
    from autosound_tcc.core import critic

    _model, var = _VENDOR_MODELS[vendor]
    refusal = (f"· API {vendor}: HTTP Error 401: Unauthorized\n"
               "· CLI 'x': not signed in\n"
               "Наступна сходинка — буфер обміну (нижче); з ключем API — `--via api` для цього "
               "запуску (setup-critic-channel.md §7).")
    assert f"`{var}` is set and the API rejected it" in critic.remedy(refusal, harness="claude")
    forbidden = refusal.replace("401: Unauthorized", "403: Forbidden")
    assert "rejected it" not in critic.remedy(forbidden, harness="claude"), "401 only"


def _answered_tail(vendor: str, model: str, *, nested: bool = False) -> str:
    """The method's stderr on a run whose API call was refused and whose CLI answered, as it prints
    it: the call, the step down, the CLI, the route and `_persist_review`'s three lines. The
    critic keeps the last six (`tail`), so the line naming the vendor is always cut."""
    cli = ({"anthropic": "claude", "openai": "codex"}[vendor])
    rel = "process/reviews/2026-10-02T10-00-00-critic.md"
    calling = (f">> Всередині агент-сесії (маркер CLAUDECODE): CLI '{cli}' запускаю без маркерів "
               "сесії, чекаю до 600 с" if nested else
               f">> Виклик локального CLI '{cli}' ({vendor}), чекаю до 600 с...")
    return "\n".join((
        _connect(vendor, model), _BARE_401, calling, ">> REVIEW_ROUTE: cli",
        f">> Текст рецензії збережено: {rel}", f">> REVIEW_FILE: {rel}",
        f">> Запиши посилання: process.py <project>/process reviewer <vendor> {model} --review {rel}",
    ))


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("vendor", list(_VENDOR_MODELS))
def test_an_answered_run_names_the_variable_its_tail_lost(stubbed, tmp_path, vendor, nested):
    """Review of #129, Minor 1: on an answered run the step-down line is the sixth from the end and
    the line naming the vendor the seventh, so the note never named the variable. `run` reads the
    vendor the method called from its whole stderr; the note takes it from there."""
    model, var = _VENDOR_MODELS[vendor]
    tail = _answered_tail(vendor, model, nested=nested)
    stubbed(f"print({tail!r}, file=sys.stderr)\nprint('pong')\nprint('— [critic: {model}]')\n")
    result = critic.run("package body", project_dir=_project(tmp_path),
                        python_executable=sys.executable)

    assert result.ok and result.api_vendor == vendor
    assert _connect(vendor, model) not in result.detail, "the tail lost it, as on the machine"
    assert critic.fallback_note(result.detail).startswith("The API key is set")
    note = critic.fallback_note(result.detail, vendor=result.api_vendor)
    assert f"`{var}` is set and the API rejected it" in note


def test_a_vendor_the_line_contradicts_is_not_named():
    """A bare 401 is Anthropic's or OpenAI's (`_post_json`): a vendor said to be Google names no
    variable, rather than the wrong one. And the method's own line outranks the caller's word."""
    from autosound_tcc.core import critic

    assert "_API_KEY" not in critic.fallback_note(_BARE_401, vendor="google")
    note = critic.fallback_note(f"{_connect('openai', 'gpt-5.5')}\n{_BARE_401}", vendor="anthropic")
    assert "`OPENAI_API_KEY`" in note


def test_the_api_lines_are_the_vendored_methods_own():
    script = (Path(__file__).resolve().parents[1] / "vendor" / "autosound-tuning-skill" / "skills"
              / "autosound-tuning" / "scripts" / "autosound_ai.py")
    if not script.is_file():
        pytest.skip("the method's submodule is not checked out")
    source = script.read_text(encoding="utf-8")
    for words in ('f">> Підключення до API ({provider}, {api_model}), чекаю до ',
                  'failures.append(f"API {provider}: {e}")', 'print(f"   · {line}", file=sys.stderr)',
                  "def _post_json(url, headers, body, timeout):"):
        assert words in source, words


@pytest.mark.parametrize("said", ["process/reviews/2026-10-01T10-00-00-ask.md",
                                  "process\\reviews\\2026-10-01T10-00-00-ask.md"])
def test_the_filed_text_is_named_by_a_path_every_os_reads(monkeypatch, tmp_path, said):
    """CI on Windows (tcc#116): the method files the text under `os.path.join`, so on Windows its
    `>> REVIEW_FILE:` line reads `process\\reviews\\…`, and that went into the bubble, the journal
    and the tool's answer as it was. A project-relative POSIX path is what a session, a resume and
    another machine read alike — for a review and a question both, which share this parse."""
    import subprocess

    from autosound_tcc.core import critic

    monkeypatch.setattr(critic, "preflight", lambda project_dir=None: [])
    monkeypatch.setattr(critic, "is_available", lambda: True)
    monkeypatch.setattr(critic.child, "run_bounded", lambda *a, **kw: subprocess.CompletedProcess(
        a[0] if a else [], 0, "pong", f">> REVIEW_FILE: {said}\n"))

    result = critic.run("## a question", project_dir=tmp_path, role=critic.ASK)

    assert result.mode == critic.MODE_API_OR_CLI
    assert result.review == "process/reviews/2026-10-01T10-00-00-ask.md"


# ---- a key in the OS store and a CLI pick (finding 136, tcc#127) ------------------------------

#: The VENDORED method, run in a child with its key store, its API callers and its CLI replaced:
#: the route is chosen by the method's own code, from TCC's own argv and environment, and nothing
#: leaves the machine. `sys.argv[1]` is the method's script, the rest TCC's argv after it. The
#: stored keys are fakes held in memory: never on argv, never printed — the API caller says only
#: whether it was handed the stored one.
_ROUTE_PROBE = r'''
import importlib.util, os, sys
method = sys.argv[1]
sys.argv = [method] + sys.argv[2:]
spec = importlib.util.spec_from_file_location("autosound_ai_route_probe", method)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def refuse(*_a, **_k):
    raise AssertionError("the probe runs nothing and calls nobody")

mod.subprocess.run = mod.subprocess.Popen = refuse
import urllib.request
urllib.request.urlopen = refuse
installed = set(filter(None, os.environ.get("PROBE_CLIS", "").split(",")))
mod.shutil.which = lambda name, *a, **k: f"/probe/bin/{name}" if name in installed else None
stored = {var: "probe-" + var.lower() + "-0123456789abcdef"
          for var in filter(None, os.environ.get("PROBE_STORED", "").split(","))}
fake = (stored.get, stored.__setitem__, lambda var: stored.pop(var, None) is not None)
for kind in list(mod._KEYSTORE_BACKENDS):
    mod._KEYSTORE_BACKENDS[kind] = fake
mod._KEYSTORE_BACKENDS["probe"] = fake
os.environ["AUTOSOUND_KEYSTORE"] = "probe"
mod._KEYSTORE_CACHE.clear()

def api(vendor):
    def call(key, model, prompt, *_rest):
        print(f"PROBE api {vendor} {'stored' if key in stored.values() else 'other'}", file=sys.stderr)
        return "an answer through the API", model
    return call

mod.call_gemini_api, mod.call_anthropic_api, mod.call_openai_api = (
    api("google"), api("anthropic"), api("openai"))
mod.list_gemini_models = refuse

def cli(provider, binary, model, prompt, timeout=None):
    print(f"PROBE cli {os.path.basename(binary)}", file=sys.stderr)
    # The NAMES of the vendor keys the CLI would be started with, by the method's own `child_env`.
    keys = [var for var in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
            if mod.child_env(binary).get(var)]
    print("PROBE-ENV " + ",".join(keys), file=sys.stderr)
    return "an answer through the CLI", None, None

mod.call_cli = cli
mod.list_cli_models = lambda: []
mod.copy_to_clipboard = lambda _text: False
mod.main()
'''

_STORED = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def _route_taken(tmp_path, monkeypatch, *, harness, model, provider, via="",
                 stored=_STORED, clis=("agy", "codex", "claude"), seen_keys=None,
                 exported=(), extra_env=None) -> str:
    """`api <vendor> stored` or `cli <binary>`: where the vendored method sent TCC's call, with
    `stored` in its OS key store, `exported` in TCC's environment and `clis` on PATH. `seen_keys`,
    a list, gets the names of the vendor keys the CLI would have been started with. `extra_env`
    is the call's own, as `critic.run` takes it."""

    if not critic.is_available():
        pytest.skip("the method's submodule is not checked out")
    probe = tmp_path / "route_probe.py"
    probe.write_text(_ROUTE_PROBE, encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    # No file of the machine's own is read: the method's machine file lives under these.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    for var in (*_STORED, "AUTOSOUND_CRITIC_BIN", "GEMINI_BIN", "AUTOSOUND_CRITIC_MODEL",
                "GEMINI_CRITIC_MODEL", "AUTOSOUND_CRITIC_PROVIDER", "AUTOSOUND_KEYSTORE",
                "AUTOSOUND_CRITIC_VIA"):
        monkeypatch.delenv(var, raising=False)
    for var in exported:
        monkeypatch.setenv(var, "env-key-0123456789abcdef")
    monkeypatch.setenv("PROBE_CLIS", ",".join(clis))
    monkeypatch.setenv("PROBE_STORED", ",".join(stored))
    monkeypatch.setattr(critic.shutil, "which",
                        lambda name, *a, **k: f"/probe/bin/{name}" if name in clis else None)
    real_run, seen = critic.child.run_bounded, {}

    def through_the_probe(argv, **kwargs):
        argv = [sys.executable, str(probe), *argv[1:]]
        seen["argv"] = argv
        proc = real_run(argv, **kwargs)
        seen["stderr"] = proc.stderr or ""
        return proc

    monkeypatch.setattr(critic.child, "run_bounded", through_the_probe)
    result = critic.run("# a question", project_dir=project, role=critic.ASK, model=model,
                        harness=harness, provider=provider, via=via, extra_env=extra_env)
    said = seen.get("stderr", "")
    shown = " ".join(seen.get("argv", [])) + said + result.text
    assert "probe-" not in shown and "env-key-" not in shown, "a key in sight"
    routes = [line.split(" ", 1)[1] for line in said.splitlines() if line.startswith("PROBE ")]
    assert len(routes) == 1, (result.mode, said)
    if seen_keys is not None:
        seen_keys.extend(name for line in said.splitlines() if line.startswith("PROBE-ENV ")
                         for name in line.split(" ", 1)[1].split(",") if name)
    return routes[0]


@pytest.mark.parametrize("harness,model,provider,cli", [
    ("agy", "gemini-3.1-pro-high", "google", "agy"),
    ("agy", "gemini-3.5-flash", "google", "agy"),
    ("agy", "claude-sonnet-4-6", "anthropic", "agy"),
    ("codex", "gpt-5.2-codex", "openai", "codex"),
    ("sdk", "claude-sonnet-5", "anthropic", "claude"),
])
def test_a_cli_pick_goes_to_its_cli_with_a_key_in_the_os_store(tmp_path, monkeypatch, harness,
                                                                model, provider, cli):
    """Finding 136 (tcc#127), measured on the vendored method itself: finding 32 keeps the key
    out of a CLI pick's environment, but the method reads its OS key store too and tries the API
    before the CLI whenever a key is there. Without a route named, an agy pick of a model with no
    effort tier and a codex pick went to the vendor's API on the stored key: money spent under a
    pick that said «subscription». The route of a CLI pick is its CLI."""
    assert _route_taken(tmp_path, monkeypatch, harness=harness, model=model,
                        provider=provider) == f"cli {cli}"


@pytest.mark.parametrize("harness,model,provider,var", [
    ("sdk", "claude-sonnet-5", "anthropic", "ANTHROPIC_API_KEY"),
    ("codex", "gpt-5.2-codex", "openai", "OPENAI_API_KEY"),
    ("agy", "gemini-3.1-pro-high", "google", "GEMINI_API_KEY"),
])
def test_a_cli_pick_never_hands_its_cli_the_vendor_key(tmp_path, monkeypatch, harness, model,
                                                       provider, var):
    """`claude -p` bills an `ANTHROPIC_API_KEY` in its environment over the subscription, as the
    other vendors' CLIs may: a key in the shell that started TCC reached the CLI of an «SDK · …»
    pick through the method's own environment (review of tcc#127, I1). Every login pick's child
    leaves its vendor's key out, as finding 32 did for agy and codex."""
    keys: list = []
    assert _route_taken(tmp_path, monkeypatch, harness=harness, model=model, provider=provider,
                        stored=(), exported=(var,), seen_keys=keys).startswith("cli ")
    assert var not in keys, keys


def test_an_sdk_pick_finds_the_claude_the_footer_found(tmp_path, monkeypatch):
    """A Dock-launched TCC has no `~/.local/bin` on PATH, so the method's PATH search found no
    `claude` where the footer had (`claude_sdk.cli_path`), and an «SDK · …» review went to the
    clipboard (review of tcc#127, M1). The pick's own CLI goes by its path."""
    from autosound_tcc.core import claude_sdk

    monkeypatch.setattr(claude_sdk, "cli_path", lambda: "/probe/home/.local/bin/claude")
    assert _route_taken(tmp_path, monkeypatch, harness="sdk", model="claude-sonnet-5",
                        provider="anthropic", clis=("agy", "codex")) == "cli claude"
    assert critic.critic_bin_override(harness="sdk", environ={}, which=lambda _n: None) == {
        "AUTOSOUND_CRITIC_BIN": "/probe/home/.local/bin/claude"}
    monkeypatch.setattr(claude_sdk, "cli_path", lambda: None)
    assert critic.critic_bin_override(harness="sdk", environ={}, which=lambda _n: None) == {}
    assert critic.critic_bin_override(harness="sdk", environ={"AUTOSOUND_CRITIC_BIN": "mine"},
                                      which=lambda _n: None) == {}, "the person's own choice"


def test_an_api_pick_still_goes_through_the_stored_key(tmp_path, monkeypatch):
    """«API · …» is the key's route (tcc#74), and a key in the store is what it runs on."""
    assert _route_taken(tmp_path, monkeypatch, harness="api", model="gemini-pro-latest",
                        provider="google") == "api google stored"


# ---- a session's own run of the method (hub #236 TCC-046, tcc#134) -----------------------------


@pytest.mark.parametrize("harness,model,provider,cli", [
    ("agy", "claude-sonnet-4-6", "anthropic", "agy"),
    ("codex", "gpt-5.2-codex", "openai", "codex"),
    ("sdk", "claude-sonnet-5", "anthropic", "claude"),
])
def test_a_sessions_own_run_of_the_method_follows_the_footers_route(tmp_path, monkeypatch, harness,
                                                                     model, provider, cli):
    """hub #236 (TCC-046), the method's v3.1.0: a session that runs the method itself names no
    `--via`, and with a key in the OS store such a run went to the vendor's API whatever the footer
    said — `call_critic` asks for the pick's CLI (tcc#127), a session's shell could not. The method
    now takes the route of a run that names none from `AUTOSOUND_CRITIC_VIA`, and TCC puts it in
    the session's environment beside the model: the run goes to the pick's CLI, which the method
    starts with no vendor key."""
    from autosound_tcc.core import claude_sdk

    monkeypatch.setattr(claude_sdk, "cli_path", lambda: "/probe/bin/claude")
    monkeypatch.setattr(critic.shutil, "which", lambda name, *a, **k: f"/probe/bin/{name}"
                        if name in ("agy", "codex", "claude") else None)
    monkeypatch.setattr(critic, "configured", lambda _p: (model, harness))
    session = critic.session_env(tmp_path)
    keys: list = []
    # No harness, so no `--via` on the call, as from a session's own shell: its environment is all
    # the run is told.
    # Review M1: the vendor's key is EXPORTED too, so `keys == []` proves the CLI child is started
    # without it, not merely that nothing was there to pass.
    var = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}[provider]
    route = _route_taken(tmp_path, monkeypatch, harness="", model=model, provider=provider,
                         seen_keys=keys, exported=(var,), extra_env=session)
    assert route == f"cli {cli}" and keys == [], (route, keys, session)


def test_a_session_is_handed_the_footers_route_in_the_methods_own_words(tmp_path, monkeypatch):
    """hub #236: «API · …» is the key's route, a login's pick its CLI and an OMP pick omp's — the
    routes `run` asks for by `--via` — and each a word the vendored method takes in
    `AUTOSOUND_CRITIC_VIA`: one it does not know it refuses, and every run of the session would
    stop on it. No pick names no route, and the method keeps its own default."""
    import re

    if not critic.is_available():
        pytest.skip("the method's submodule is not checked out")
    monkeypatch.setattr(critic, "critic_bin_override", lambda harness="": {})
    monkeypatch.setattr(critic, "omp_route_available", lambda: True)
    said = {}
    for route in ("api", "agy", "codex", "sdk", "omp"):
        monkeypatch.setattr(critic, "configured", lambda _p, r=route: ("a-model", r))
        said[route] = critic.session_env(tmp_path).get("AUTOSOUND_CRITIC_VIA")

    assert said == {"api": "api", "agy": "cli", "codex": "cli", "sdk": "cli", "omp": "omp"}
    text = critic.script_path().read_text(encoding="utf-8")
    assert "AUTOSOUND_CRITIC_VIA" in text, "the vendored method reads the variable"
    known = re.search(r"^VIA_ROUTES\s*=\s*\(([^)]*)\)", text, re.MULTILINE).group(1)
    assert all(f'"{via}"' in known for via in set(said.values())), known
    monkeypatch.setattr(critic, "configured", lambda _p: ("", ""))
    assert critic.session_env(tmp_path) == {}


# ---- agy's sign-in, as the method reads it (tcc#135; night review, M7) -------------------------

#: Taken at import, before `conftest` makes it answer nothing for every test.
_REAL_AGY_SIGN_IN = critic.agy_sign_in


def _fake_method(tmp_path: Path, name: str, body: str) -> Path:
    """A method folder of one file, `scripts/autosound_ai.py`, that loads a key into `os.environ`
    when it is imported -- as the real one loads its critic-env -- and then runs `body`."""
    scripts = tmp_path / name / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "autosound_ai.py"
    script.write_text("import os\nos.environ['GEMINI_API_KEY'] = 'AQ.fake-imported'\n" + body,
                      encoding="utf-8")
    return script


@pytest.fixture
def methods(monkeypatch, tmp_path):
    """Point `critic` at one of two fake methods: one that answers, one older without the reader."""
    made = {
        "answers": _fake_method(tmp_path, "answers",
                                "def agy_sign_in():\n    return ('adc', 'ADC (Google Cloud), x')\n"),
        "older": _fake_method(tmp_path, "older", "def run():\n    pass\n"),
    }
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def use(name: str) -> None:
        monkeypatch.setattr(critic, "script_path", lambda: made[name])

    return use


def test_agys_sign_in_is_the_methods_own_reading(methods, tmp_path):
    methods("answers")

    assert _REAL_AGY_SIGN_IN(tmp_path) == ("adc", "ADC (Google Cloud), x")


def test_agys_reading_hands_its_child_out_and_a_killed_one_says_nothing(methods, tmp_path):
    """Final review M2: the diagnostics' worker ends this child when the window closes; until then
    it was not the worker's to end. Killed, it is no reading rather than a wrong one."""
    methods("answers")
    taken: list = []

    assert _REAL_AGY_SIGN_IN(tmp_path, register=lambda proc: (taken.append(proc), proc.kill())) \
        is None
    assert len(taken) == 1


def test_an_older_method_without_the_reader_says_nothing(methods, tmp_path):
    methods("older")

    assert _REAL_AGY_SIGN_IN(tmp_path) is None


def test_asking_imports_nothing_into_tcc(methods, tmp_path):
    """The method loads its machine critic-env into `os.environ` when it is imported, keys
    included, and every child TCC starts inherits TCC's environment. So it is asked in a child."""
    methods("answers")
    before = dict(os.environ)

    _REAL_AGY_SIGN_IN(tmp_path)

    assert "GEMINI_API_KEY" not in os.environ
    assert dict(os.environ) == before
    assert "autosound_ai" not in sys.modules


def test_the_suite_never_runs_the_method_for_agys_sign_in(monkeypatch):
    """`conftest` answers for it, as for the reviewer key's `_ask`: the real reading runs this
    machine's method against its critic-env."""
    import subprocess

    from autosound_tcc.core import child

    spawned: list = []
    monkeypatch.setattr(child, "run_bounded",
                        lambda *a, **k: spawned.append(a) or subprocess.CompletedProcess(a, 0, "", ""))

    assert critic.agy_sign_in() is None
    assert spawned == [], "the method was run — the stub in conftest is gone"


def _reviewer_ready(monkeypatch, tmp_path):
    from autosound_tcc.core import critic

    monkeypatch.setattr(critic, "is_available", lambda: True)
    monkeypatch.setattr(critic, "preflight", lambda _p=None: [])
    monkeypatch.setattr(critic, "script_path", lambda: tmp_path / "autosound_ai.py")
    monkeypatch.setattr(critic.shutil, "which", lambda name: f"/usr/bin/{name}")
    return critic


def test_a_reviewer_that_never_answers_is_killed_on_windows(tmp_path, monkeypatch):
    """F16-1: the reviewer's call was one of three left on `subprocess.run`, which on Windows waits
    with no bound for pipes a grandchild holds (tcc#132)."""
    from tests import _hung_child

    critic = _reviewer_ready(monkeypatch, tmp_path)
    spawns = _hung_child.install(monkeypatch)

    result = critic.run("a package", project_dir=tmp_path, role="ask", harness="agy", timeout_s=1)

    assert result.mode == critic.MODE_ERROR and "timed out" in result.detail
    assert spawns.hung and all(child.killed for child in spawns.hung)


def test_the_reviewer_doctor_is_bounded_on_windows(tmp_path, monkeypatch):
    from tests import _hung_child

    critic = _reviewer_ready(monkeypatch, tmp_path)
    spawns = _hung_child.install(monkeypatch)

    said = critic.doctor(tmp_path, python_executable="python")

    assert said.startswith("doctor failed")
    assert spawns.hung and all(child.killed for child in spawns.hung)
