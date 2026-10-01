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

    monkeypatch.setattr(critic.subprocess, "run", capture)

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

    monkeypatch.setattr(critic.subprocess, "run", capture)

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

    monkeypatch.setattr(critic.subprocess, "run", capture)

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

    monkeypatch.setattr(critic.subprocess, "run", capture)
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

    monkeypatch.setattr(critic.subprocess, "run", _fake)
    critic.run("# hi", project_dir=tmp_path, model="google-antigravity/gemini-3.1-pro-high",
               harness="omp")
    assert seen["argv"][seen["argv"].index("--via") + 1] == "omp"

    project_settings.set_value(config.tcc_dir(tmp_path), "critic",
                               "omp:google-antigravity/gemini-3.1-pro-high")
    assert critic.session_env(tmp_path) == {
        "AUTOSOUND_CRITIC_MODEL": "google-antigravity/gemini-3.1-pro-high",
        "AUTOSOUND_CRITIC_BIN": "omp"}


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

    monkeypatch.setattr(critic.subprocess, "run", capture)
    critic.run("a package", project_dir=tmp_path, harness="agy", model="gemini-3.8-flash-high",
               via="api")
    assert seen["argv"][-2:] == ["--via", "api"]
    assert "GEMINI_API_KEY" in seen["env"]

    critic.run("a package", project_dir=tmp_path, harness="agy", model="gemini-3.8-flash-high")
    assert "--via" not in seen["argv"] and "GEMINI_API_KEY" not in seen["env"]


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

    monkeypatch.setattr(critic.subprocess, "run", _fake)
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

    monkeypatch.setattr(critic.subprocess, "run", capture)
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
}


def test_the_pins_line_is_no_refusal():
    """VM-4: the bare word «model» matched the pins line (`AUTOSOUND_CRITIC_MODEL=…`, hub #226),
    which #113 reads into the footer's note — never as a refusal, and never as a reason."""
    from autosound_tcc.core import critic

    tail = f"{_VM_PINS}\n>> REVIEW_ROUTE: api\n>> REVIEW_FILE: process/reviews/x-ask.md"
    assert critic.remedy(tail, harness="agy") == ""
    assert critic.remedy(_VM_PINS, harness="agy") == ""
    assert critic.refusal_reason(_VM_PINS) is None
    # «model» alone says nothing about a refusal.
    assert critic.remedy("the model answered in 10.5 s", harness="agy") == ""


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
                  'f"Модель `{model}` CLI \'{cli_bin}\' не знає: '):
        assert words in source, words
