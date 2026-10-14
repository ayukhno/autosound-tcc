"""`shell_gate.judge_action` — the one gate omp and Codex answer from (tcc#181, W-10 task 5).

It began as `OmpSession._auto_allowed` and the decision half of `_gate`, lifted unchanged (54e6b96,
checked then against omp's old body over this table). The fixed answers below are the guard: omp's
own `_gate` is run against them, and `_gate` is shown to decide through `judge_action`.

Each cell: `pass` — runs unasked; `pass!` — runs unasked under `never` and is said in the dialog
(`Unasked`); `ask` — the Arbiter is asked; `ask!` — asked as «cannot be undone»
(`gateIrreversible`).

**Rows that changed for omp in the fix round (the Arbiter, 2026-10-14: «виправити повністю», even
though omp asks more often).** Before it, `foreign` let a line through as «only skill files» when
it was destructive or named other paths (a substring test: `rm -rf process/ ~` passed), and an
unknown tool name passed `auto` without a look. The second round made `foreign` an allow-list:
every simple command on a short list, every operand and redirection a skill path, the method's
writer only from the skill's own folder (its arguments are data). See `CHANGED_FOR_OMP`.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from pathlib import Path, PureWindowsPath

import pytest

from autosound_tcc.core import omp_session as omp_session_module
from autosound_tcc.core import shell_gate
from autosound_tcc.core.agent_events import Unasked
from autosound_tcc.core.mcp_server import ConfirmRequest
from autosound_tcc.core.omp_session import OmpSession
from autosound_tcc.core.shell_gate import (GATE_AUTO, GATE_FOREIGN, GATE_NEVER, GATE_WRITES,
                                           SHELL_POWERSHELL, Verdict, judge_action)
from autosound_tcc.core.tuning_session import _read_roots_for

GATES = (GATE_WRITES, GATE_FOREIGN, GATE_AUTO, GATE_NEVER)

#: (name, omp tool, omp detail, ticked tools, {gate: cell}) — the detail as omp sends it.
OMP_TABLE = [
    ("read-only bash", "bash", "Command: ls -la", (),
     {GATE_WRITES: "pass", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("dangerous bash", "bash", "Command: rm -rf ~/", (),
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("skill-file write by bash", "bash", "Command: echo done > process/plan.json", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("foreign write by bash", "bash", "Command: echo x > /tmp/out.txt", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("skill-file edit", "edit", '{"path": "process/plan.json"}', (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("foreign edit", "edit", '{"path": "/etc/hosts"}', (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("mcp__tcc tool", "mcp__tcc_copy_helix_eq", "Text: PK 1000", (),
     {GATE_WRITES: "pass", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("read tool", "read", '{"path": "notes.md"}', (),
     {GATE_WRITES: "pass", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("omp's inspect_image", "inspect_image", '{"path": "plot.png"}', (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("always-allowed tool", "write", '{"path": "/etc/hosts"}', ("write",),
     {GATE_WRITES: "pass", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("always-allowed dangerous bash", "bash", "Command: rm -rf ~/", ("bash",),
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("a Codex tick, a home wipe", "Bash", "cd ~ && rm -rf *", ("Bash",),
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("always-allowed ordinary bash", "bash", "Command: echo x > /tmp/out.txt", ("bash",),
     {GATE_WRITES: "pass", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("PowerShell read", "bash", "Command: powershell -c 'Get-ChildItem ~'", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("PowerShell delete", "bash", "Command: powershell -c 'Remove-Item -Recurse -Force ~'", (),
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("a writer with an effect", "bash", "Command: python3 rew_tool/apply.py --preset FULL", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("dangerous bash with a description", "bash", "Description: clear it\nCommand: rm -rf ~/", (),
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("an edit of a writer", "edit", '{"path": "rew_tool/apply.py"}', (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("unknown tool", "browser_open", '{"url": "x"}', (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "ask", GATE_NEVER: "pass!"}),
    # The `foreign` hole, closed: danger first, and owned paths anchored.
    ("skill path beside the home", "bash", "Command: rm -rf process/ ~", (),
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("a skill write, then the home", "bash", "Command: echo x > process/a.json; rm -rf ~", (),
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("a climb out of a skill path", "bash", "Command: rm -rf process/../../..", (),
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("$HOME beside a skill file", "bash", "Command: rm -rf $HOME state/x.json", (),
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("a skill name inside an absolute path", "bash", "Command: rm -rf /Users/x/state/", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("a backslash path beside a skill file", "bash",
     r"Command: Remove-Item -Recurse -Force C:\Users\me process/plan.json", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    # …and what the skill does in its own namespace still passes `foreign`.
    ("a skill temp removed", "bash", "Command: rm process/x.tmp", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("a skill file renamed", "bash", "Command: mv state/a.json state/b.json", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("a skill file written", "bash", "Command: echo x > process/a.json", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("a script in the project's state/", "bash", "Command: python3 state/process.py add-step", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("a skill file written, errors dropped", "bash",
     "Command: echo x > process/a.json 2>/dev/null", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    # The method's writer by the path its documents use — relative, so inside the project…
    ("the skill's writer by a relative path", "bash",
     "Command: python3 rew_tool/state/process.py ./process done lang ok", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    # …but not one by an absolute path or a climb: `state/process.py` anywhere is not the skill's.
    ("a writer's name by an absolute path", "bash",
     "Command: python3 /tmp/evil/state/process.py add-step", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("a writer's name by a climb", "bash", "Command: python3 ../x/state/process.py add-step", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("a skill file by an option's value", "bash",
     "Command: cp --target-directory=process/ state/a.json", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
]

#: What changed for omp in the fix round, and why — every other row is what omp answered before.
CHANGED_FOR_OMP = {
    # The `foreign` hole: these passed `foreign` unasked.
    "skill path beside the home": "foreign pass -> ask!: danger is checked before the skill pass",
    "a skill write, then the home": "foreign pass -> ask!: danger is checked before the skill pass",
    "a climb out of a skill path": "foreign pass -> ask!: `..` takes a path out of the namespace",
    "$HOME beside a skill file": "foreign pass -> ask!: `$HOME` is not the skill's",
    "a skill name inside an absolute path": "foreign pass -> ask: an owned name must START a "
                                            "relative path, not appear inside an absolute one",
    "a backslash path beside a skill file": "foreign pass -> ask: a backslash path is not the "
                                            "skill's",
    "a writer's name by an absolute path": "foreign pass -> ask: the writer counts only by a "
                                           "relative path",
    "a writer's name by a climb": "foreign pass -> ask: `..` takes a path out of the namespace",
    "a script in the project's state/": "foreign pass -> ask: only the writer in the skill's own "
                                        "folder is trusted; a script the project holds is not",
    # The question's words.
    "dangerous bash": "writes/foreign ask -> ask!",
    "dangerous bash with a description": "writes/foreign ask -> ask! (omp's Description: kept in "
                                         "the detail there; `auto` shows the command alone)",
    "an edit of a writer": "the question names the tool (`edit`), not `effectLedger`: an edit of "
                           "apply.py changes the script, it does not write a ledger",
    # The right reason: a command the danger check flags says «cannot be undone» in every gate.
    "PowerShell delete": "writes/foreign ask -> ask!",
    # Unknown names: `auto` passed them without a look, and `never` said nothing.
    "unknown tool": "auto pass -> ask; never pass -> pass!",
}


#: `foreign`, line by line (the second fix round of tcc#181: an allow-list, not a deny-list of
#: path-looking words). (name, line, shell, an omp row — run through omp's `_gate` too —, passes).
#: `{project}` and `{skill}` are the project folder and the method's copy (`_read_roots_for`).
P = SHELL_POWERSHELL
B = "bash"
WRITER = "rew_tool/state/process.py"
FOREIGN_ROWS = [
    # C1 — a bare word behind one owned path, and commands that are not on the list.
    ("a bare folder beside a skill file", "rm -rf measurements process/a.json", B, True, False),
    ("everything beside a skill file", "rm -rf * process/a.json", B, True, False),
    ("the repository beside a skill file", "rm -rf .git process/a.json", B, True, False),
    ("git, then a skill write", "git reset --hard; echo > process/a.json", B, True, False),
    ("chmod beside a skill file", "chmod -R 000 . process/a.json", B, True, False),
    ("python -c beside a skill file",
     "python3 -c 'import os; os.system(\"rm -rf ~\")' process/a.json", B, True, False),
    ("a PowerShell list beside a skill file",
     "Remove-Item -Recurse -Force measurements, process/a.json", P, True, False),
    ("a skill write, then a format",
     "Set-Content process/a.json -Value x; Format-Volume -DriveLetter C", P, True, False),
    # C2 — `cd` and `ln` never take the pass; `.` and `..` are paths.
    ("a link out of the namespace", "ln -s .. state/up", B, True, False),
    ("cd up, then a skill folder", "cd .. && rm -rf process/", B, True, False),
    ("cd to another car", "cd ..; cd other-car; rm -rf state/", B, True, False),
    ("cd into the project, then the home", "cd {project} && rm -rf process/ ~", B, False, False),
    ("cd elsewhere, then the writer", "cd /tmp && python3 {skill}/" + WRITER + " ./process show",
     B, False, False),
    # I3 — the writer is the one in the skill's own folder, run by an interpreter.
    ("a writer written into the project", "cat > evil/state/process.py", B, True, False),
    ("a writer the project holds", "python3 evil/state/process.py done", B, True, False),
    ("a script written into state/", "cat > state/evil.py", B, True, False),
    ("a script run from state/", "python3 state/evil.py", B, True, False),
    ("a shell script from process/", "bash process/run.sh", B, True, False),
    ("a copy into the skill's folder", "cp process/a.json {skill}/rew_tool/x.py", B, False, False),
    ("a write into the skill's folder", "echo x > {skill}/SKILL.md", B, False, False),
    ("the writer under python -c", "python3 -c 1 {skill}/" + WRITER, B, False, False),
    # What the skill does in its own namespace still passes.
    ("a skill folder emptied", "rm -rf process/old", B, False, True),
    ("a skill folder made", "mkdir -p process/runs", B, False, True),
    ("a skill file piped on", "cat state/a.json | tee process/b.json", B, False, True),
    ("a skill file by a heredoc", "cat <<'EOF' > process/a.json\n{{}}\nEOF", B, False, True),
    ("a skill glob", "rm process/*.tmp", B, False, True),
    ("a skill file by its absolute path", "rm {project}/process/x.tmp", B, False, True),
    ("a skill file set", "Set-Content process/a.json -Value x", P, False, True),
    ("a skill file made", "New-Item -ItemType File process/a.json", P, False, True),
    # I5 — PowerShell's own separator.
    ("a skill file by backslashes", r"Remove-Item .\process\a.json", P, False, True),
    ("the writer by backslashes", r"python rew_tool\state\process.py .\process done -1.1 project.json",
     P, False, True),
    # I4 — the method's own steps, as its documents write them (`vendor/autosound-tuning-skill/…`).
    ("method: show", "python3 " + WRITER + " {project}/process show", B, False, True),
    ("method: target", "python3 " + WRITER + " {project}/process target FLAT harman", B, False,
     True),
    ("method: handoff", "python3 " + WRITER + " {project}/process handoff", B, False, True),
    ("method: capture-protective",
     "python3 " + WRITER + " {project}/process capture-protective FL --hp 1000 LR 24", B, False,
     True),
    ("method: session-close", "python3 " + WRITER + " {project}/process session-close --check", B,
     False, True),
    ("method: enter-phase", "python3 " + WRITER + " {project}/process enter-phase -1", B, False,
     True),
    ("method: done with a file", "python3 " + WRITER +
     ' {project}/process done -1.2 "rew_analitic/reviewer-check.md"', B, False, True),
    ("method: done project.json", "python3 " + WRITER + ' {project}/process done -1.1 "project.json"',
     B, False, True),
    ("method: decision", "python3 " + WRITER +
     ' {project}/process decision "dialogue language" "uk" -1.1', B, False, True),
    ("method: capture-start", "python3 " + WRITER +
     " {project}/process capture-start final 'v7 L/R 1/48'", B, False, True),
    ("method: capture-knobs", "python3 " + WRITER + " {project}/process capture-knobs SubRC=4/4", B,
     False, True),
    ("method: capture-check", "python3 " + WRITER + " {project}/process capture-check --session", B,
     False, True),
    ("method: block", "python3 " + WRITER +
     ' {project}/process block -1.2 "the first ✗ line of reviewer-check.md"', B, False, True),
    ("method: --root", "python3 " + WRITER + " --root ./state registry render", B, False, True),
    # Third round. The writer's first operand is the folder it writes into: a skill path.
    ("the writer into /etc", "python3 {skill}/" + WRITER + " /etc done x", B, True, False),
    ("the writer into another car", "python3 " + WRITER + " ../other-car/process done -1.1 x", B,
     True, False),
    ("the writer into the home", "python3 " + WRITER + " ~/other/process show", B, True, False),
    ("the writer with --root elsewhere", "python3 " + WRITER + " --root /tmp/state registry render",
     B, True, False),
    ("the writer with nothing to write into", "python3 {skill}/" + WRITER, B, False, False),
    # After `--` every word is an operand.
    ("an option-looking word after --", "rm -rf -- -x process/a.json", B, True, False),
    ("a skill file after --", "rm -- process/a.json", B, False, True),
    # New-Item takes the pass as a file or a folder, never as a link.
    ("a junction out of the namespace", "New-Item -ItemType Junction -Path process/j -Value C:/Users",
     P, False, False),
    ("a junction to the parent", "New-Item -ItemType Junction -Path process/j -Value ..", P, False,
     False),
    ("a link inside the namespace",
     "New-Item -ItemType SymbolicLink -Path process/l -Value process/a.json", P, False, False),
    ("a skill folder by New-Item", "New-Item -ItemType Directory -Path process/runs", P, False, True),
    # The skill's root is TCC's to set, not the line's.
    ("the skill's root exported", "export AUTOSOUND_SKILL_ROOT=/tmp/evil", B, True, False),
    ("the skill's root set for the writer",
     'AUTOSOUND_SKILL_ROOT=/tmp/evil python3 "$AUTOSOUND_SKILL_ROOT/' + WRITER + '" ./process show',
     B, True, False),
    # …and by the paths a session's shell has: the skill's own, its variable, the project's link.
    ("method by the skill's absolute path",
     "python3 {skill}/" + WRITER + " {project}/process done lang ok", B, False, True),
    ("method after cd into the project",
     "cd {project} && python3 {skill}/" + WRITER + " ./process show", B, False, True),
    ("method by the skill's variable",
     'python3 "$AUTOSOUND_SKILL_ROOT/' + WRITER + '" ./process show', B, False, True),
    ("method through the project's link",
     "python3 .claude/skills/autosound-tuning/" + WRITER + " ./process show", B, False, True),
]

CHANGED_FOR_OMP.update({
    name: "foreign pass -> ask: " + why for name, why in [
        ("a bare folder beside a skill file", "a word that is not a skill path is not passed over"),
        ("everything beside a skill file", "`*` is not a skill path"),
        ("the repository beside a skill file", "`.git` is not a skill path"),
        ("git, then a skill write", "`git` is not on the allow-list"),
        ("chmod beside a skill file", "`chmod` is not on the allow-list"),
        ("python -c beside a skill file", "`python3 -c` is not the writer"),
        ("a PowerShell list beside a skill file", "`measurements` is not a skill path"),
        ("a skill write, then a format", "`Format-Volume` is not on the allow-list"),
        ("a link out of the namespace", "`ln` is not on the allow-list"),
        ("cd up, then a skill folder", "only a `cd` into the project itself leads a line"),
        ("cd to another car", "only a `cd` into the project itself leads a line"),
        ("a writer written into the project", "a `.py` path is not a skill file"),
        ("a writer the project holds", "only the writer in the skill's own folder is trusted"),
        ("a script written into state/", "a `.py` in state/ is not a skill file"),
        ("a script run from state/", "only the writer in the skill's own folder is trusted"),
        ("a shell script from process/", "`bash` is not on the allow-list"),
        ("the writer into /etc", "the writer's first operand is the folder it writes into"),
        ("the writer into another car", "the writer's first operand is the folder it writes into"),
        ("the writer into the home", "the writer's first operand is the folder it writes into"),
        ("the writer with --root elsewhere", "`--root` names the folder it writes into"),
        ("an option-looking word after --", "after `--`, `-x` is a file"),
        ("the skill's root exported", "only TCC sets the skill's root (it also asks under `auto`)"),
        ("the skill's root set for the writer", "only TCC sets the skill's root"),
    ]
})


def _command(detail: str) -> str:
    """omp's split of `Command: …`, as `OmpSession._judge` makes it."""
    return detail.split("Command:", 1)[-1].strip() if "Command:" in detail else detail


def _cell(verdict: Verdict) -> str:
    if verdict.allowed:
        return "pass!" if verdict.unasked else "pass"
    return "ask!" if verdict.reason == "gateIrreversible" else "ask"


def _rows(table=OMP_TABLE):
    for name, tool, detail, ticked, cells in table:
        for gate in GATES:
            yield pytest.param(tool, detail, ticked, gate, cells[gate], id=f"{name}-{gate}")


def test_every_changed_row_is_in_the_table():
    assert set(CHANGED_FOR_OMP) <= {row[0] for row in OMP_TABLE} | {
        row[0] for row in FOREIGN_ROWS if row[3]} | {row[0] for row in AUTO_LINK_ROWS}


@pytest.mark.parametrize("tool, detail, ticked, gate, cell", list(_rows()))
def test_the_table(tool, detail, ticked, gate, cell, tmp_path):
    verdict = judge_action(tool, detail, gate=gate, always_allowed=frozenset(ticked),
                           read_roots=_read_roots_for(tmp_path), command=_command(detail))

    assert _cell(verdict) == cell
    if verdict.unasked:
        assert verdict.unasked == _command(detail)
    if not verdict.allowed:
        assert verdict.title == f"Дозволити {tool}?"
        # Under `auto` «cannot be undone» shows the command alone; otherwise what omp sent.
        assert verdict.detail == (_command(detail) if gate == GATE_AUTO and cell == "ask!"
                                  else detail)


def _project(tmp_path):
    """A project with the method linked in, as TCC links it, and its two roots."""
    project = tmp_path / "car"
    project.mkdir()
    roots = _read_roots_for(project)
    link = project / ".claude" / "skills"
    link.mkdir(parents=True)
    (link / "autosound-tuning").symlink_to(roots[1], target_is_directory=True)
    return project, roots


@pytest.mark.parametrize("name, line, shell, omp, passes", FOREIGN_ROWS,
                         ids=[row[0] for row in FOREIGN_ROWS])
def test_foreign_line_by_line(name, line, shell, omp, passes, tmp_path, monkeypatch):
    project, roots = _project(tmp_path)
    # The platform's form of a path in a bash line is `/`-separated: unquoted, bash strips a
    # Windows `\` before any program sees it (`rm C:\Users\…\car/process/x.tmp` is `rm
    # C:Users…car/process/x.tmp`), so a line built with `str()` is one no bash on Windows runs —
    # the gate refusing it was right (Windows CI, PR #215). Identical on POSIX.
    form = (lambda path: Path(path).as_posix()) if shell == B else str
    line = line.format(project=form(project), skill=form(roots[1]))
    monkeypatch.setenv("AUTOSOUND_SKILL_ROOT", str(roots[1]))

    verdict = judge_action("Bash", line, gate=GATE_FOREIGN, read_roots=roots, shell=shell)

    assert verdict.allowed is passes, verdict


@pytest.mark.parametrize("name, line", [(row[0], row[1]) for row in FOREIGN_ROWS if row[3]],
                         ids=[row[0] for row in FOREIGN_ROWS if row[3]])
def test_omp_asks_about_the_foreign_holes(name, line, tmp_path):
    """The omp rows above through omp's own gate: each asks now (`CHANGED_FOR_OMP` says why)."""
    session, sent, _ = _omp_gate(tmp_path, "bash", f"Command: {line}", (), GATE_FOREIGN)

    assert len(session.bridge.requests) == 1 and sent[0]["value"] == "Deny"


def test_a_link_out_of_the_namespace_is_not_the_skills(tmp_path):
    """C2: `ln -s .. state/up` made earlier (it asked then) makes `state/up/` the project itself;
    the text alone reads as a skill folder, the disk does not."""
    project, roots = _project(tmp_path)
    (project / "state").mkdir()
    (project / "state" / "up").symlink_to("..", target_is_directory=True)
    (project / "state" / "runs").mkdir()

    for line in ("rm -rf state/up/", "rm -rf state/up/measurements", "rm state/up/*.json"):
        assert not judge_action("Bash", line, gate=GATE_FOREIGN, read_roots=roots).allowed, line
    # Where it lands decides: through the link to the project's own `process/` is the skill's.
    for line in ("rm -rf state/runs/", "rm -rf state/up/process/old"):
        assert judge_action("Bash", line, gate=GATE_FOREIGN, read_roots=roots).allowed, line


# ---- links: what a delete or a move reaches, and links made out of the project ----------------
#
# Third fix round (the Arbiter's «fix fully»): `ln -s ~ h` passed `auto`, and then `rm -rf h/` —
# macOS's `rm -rf link/` follows the link. The danger check (`bash_is_dangerous`) now resolves
# what `rm`/`mv`/`Remove-Item`/`Move-Item` reach against the project, and a link made to outside
# it is itself dangerous. The SDK route asks the same check, so these rows changed there too.

#: (name, line, shell) — each asks as «cannot be undone» under `auto`, in a project where `h` is a
#: link to a folder outside it and `process/j` one inside the skill's folder (`_linked_project`).
AUTO_LINK_ROWS = [
    ("rm through a link out", "rm -rf h/", B),
    ("rm below a link out", "rm -rf h/sub", B),
    ("rm of a link out", "rm -rf h", B),
    ("mv out through a link", "mv h/ elsewhere", B),
    ("mv into a link out", "mv process/a.json h/", B),
    ("rm of a glob over a link out", "rm -rf process/*", B),
    ("a link to the home", "ln -s ~ h2", B),
    ("a link to the root", "ln -s / r", B),
    ("a link to the project's parent", "ln -s .. up", B),
    ("a link to a folder outside", "ln -s {outside} x", B),
    ("a hard link to a system file", "ln /etc/hosts x", B),
    ("a junction by cmd", r"cmd /c mklink /J j C:\Users", B),
    ("a junction by PowerShell, from bash",
     "powershell -c 'New-Item -ItemType Junction -Path j -Value C:/Users'", B),
    ("a junction by PowerShell", "New-Item -ItemType Junction -Path process/j2 -Value C:/Users", P),
    ("a PowerShell link up", "New-Item -ItemType SymbolicLink -Path process/l -Value ..", P),
    ("a PowerShell delete over a nested link", "Remove-Item -Recurse -Force process", P),
    ("a PowerShell delete of a glob over a link", "Remove-Item -Recurse -Force process/*", P),
    ("a PowerShell move through a link", "Move-Item h/sub process/", P),
    # A link made by something else earlier in the same line: the disk is read before the line
    # runs, so a delete or a move of what is not there yet, after another statement, asks.
    ("a link by python, then rm",
     "python3 -c 'import os; os.symlink(os.path.expanduser(\"~\"), \"h3\")' && rm -rf h3/", B),
    ("a link by perl, then rm", "perl -e 'symlink($ENV{{HOME}},\"h4\")'; rm -rf h4/", B),
    ("an archive, then rm", "tar -xf evil.tar && rm -rf h5/", B),
    ("an archive, then mv", "tar -xf evil.tar; mv h5/ elsewhere", B),
    ("an archive, then a PowerShell delete",
     "Expand-Archive evil.zip .; Remove-Item -Recurse -Force h6", P),
]

#: …and what still passes `auto` there: links and deletes that stay inside the project.
AUTO_LINK_PASS = [
    ("a link inside the project", "ln -s ../process/a.json state/b", B),
    ("a plain skill file removed", "rm process/a.json", B),
    ("rm -rf of a folder holding a link", "rm -rf process", B),  # POSIX rm removes the link
    ("a folder by New-Item", "New-Item -ItemType Directory -Path process/runs", P),
    ("a PowerShell link inside", "New-Item -ItemType SymbolicLink -Path state/l -Value "
                                 "process/a.json", P),
    ("a missing folder removed, alone", "rm -rf h7/", B),
    ("a statement, then an existing file removed", "echo hi && rm process/a.json", B),
]

#: What changed for omp AND the SDK route (`TuningSession._can_use_tool` asks `bash_is_dangerous`
#: under `auto`): every bash row of `AUTO_LINK_ROWS` passed `auto` before, and asks now.
CHANGED_FOR_SDK = {
    name: "auto pass -> ask!: " + ("what it reaches lies outside the project through a link"
                                   if line.startswith(("rm", "mv")) else
                                   "a delete or move of what is not there yet, after another "
                                   "statement that could have made it a link"
                                   if " rm " in line or " mv " in line else
                                   "a link made to outside the project")
    for name, line, shell in AUTO_LINK_ROWS if shell == B
}
#: The Arbiter, 2026-10-14: a «don't ask again» tick never outranks «cannot be undone» — for omp,
#: the SDK route (`TuningSession._can_use_tool`) and Codex alike.
TICK = "the Arbiter, 2026-10-14: a tick never outranks cannot-be-undone"
CHANGED_FOR_SDK.update({
    "always-allowed dangerous bash": f"writes/foreign/auto pass -> ask!: {TICK}",
    "a Codex tick, a home wipe": f"writes/foreign/auto pass -> ask!: {TICK}",
})
CHANGED_FOR_OMP.update(CHANGED_FOR_SDK)


def _linked_project(tmp_path):
    """A project where `h` and `process/j` are links to a folder outside it."""
    project, roots = _project(tmp_path)
    outside = tmp_path / "outside"
    (outside / "sub").mkdir(parents=True)
    (project / "process").mkdir()
    (project / "state").mkdir()
    (project / "process" / "a.json").write_text("{}")
    (project / "h").symlink_to(outside, target_is_directory=True)
    (project / "process" / "j").symlink_to(outside, target_is_directory=True)
    return project, roots, outside


@pytest.mark.parametrize("name, line, shell", AUTO_LINK_ROWS, ids=[r[0] for r in AUTO_LINK_ROWS])
def test_a_link_out_of_the_project_asks_under_auto(name, line, shell, tmp_path):
    project, roots, outside = _linked_project(tmp_path)
    line = line.format(outside=outside)

    verdict = judge_action("Bash", line, gate=GATE_AUTO, read_roots=roots, shell=shell)

    assert _cell(verdict) == "ask!"


@pytest.mark.parametrize("name, line, shell", AUTO_LINK_PASS, ids=[r[0] for r in AUTO_LINK_PASS])
def test_a_link_inside_the_project_still_passes_auto(name, line, shell, tmp_path):
    project, roots, _ = _linked_project(tmp_path)

    assert judge_action("Bash", line, gate=GATE_AUTO, read_roots=roots, shell=shell).allowed


@pytest.mark.parametrize("name, line", [(r[0], r[1]) for r in AUTO_LINK_ROWS if r[2] == B],
                         ids=[r[0] for r in AUTO_LINK_ROWS if r[2] == B])
def test_omp_and_the_sdk_route_ask_about_a_link_out(name, line, tmp_path):
    """The same rows through omp's `_gate` and the SDK route's `_can_use_tool`, both under `auto`."""
    from autosound_tcc.core.tuning_session import TuningSession

    project, _, outside = _linked_project(tmp_path)
    line = line.format(outside=outside)
    session, sent, _ = _omp_gate(project, "bash", f"Command: {line}", (), GATE_AUTO)
    assert len(session.bridge.requests) == 1
    assert session.bridge.requests[0].reason == "gateIrreversible"

    sdk = TuningSession(project_dir=project, gate=GATE_AUTO)
    asked: list = []

    async def ask(*args, **kwargs):
        asked.append(args)
        return "asked"

    sdk._ask = ask
    asyncio.run(sdk._can_use_tool("Bash", {"command": line}, None))
    assert len(asked) == 1


def test_a_foreign_glob_over_a_link_asks(tmp_path):
    """C2 for globs: `process/*` matches `process/j`, a link out; each match's own landing counts."""
    project, roots, _ = _linked_project(tmp_path)

    for line, shell in (("rm -rf process/*", B), ("Remove-Item -Recurse -Force process/*", P),
                        ("rm process/*", B)):
        verdict = judge_action("Bash", line, gate=GATE_FOREIGN, read_roots=roots, shell=shell)
        assert not verdict.allowed, line


@pytest.mark.parametrize("gate", GATES)
@pytest.mark.parametrize("line, shell", [
    ("export AUTOSOUND_SKILL_ROOT=/tmp/evil", B),
    ("AUTOSOUND_SKILL_ROOT=/tmp/evil python3 x.py", B),
    ("unset AUTOSOUND_SKILL_ROOT", B),
    ("set AUTOSOUND_SKILL_ROOT=C:/evil", B),
    ("$env:AUTOSOUND_SKILL_ROOT = 'C:/evil'", P),
])
def test_setting_the_skills_root_always_asks(line, shell, gate, tmp_path):
    """A persistent shell would carry a root the line set, and the writer check trusts the root."""
    verdict = judge_action("Bash", line, gate=gate, read_roots=_read_roots_for(tmp_path),
                           shell=shell)

    # A line the bash reader cannot spell (`$env:…` as a command) asks as «cannot be undone» too.
    assert _cell(verdict) in (("pass!",) if gate == GATE_NEVER else ("ask", "ask!"))


def test_a_writer_the_project_holds_at_the_documents_path_is_not_the_skills(tmp_path):
    """`rew_tool/state/process.py` is the documents' path in the SKILL's folder; from the project
    it runs whatever the project holds there — so when it holds something, that must be the
    writer itself."""
    project, roots = _project(tmp_path)
    planted = project / "rew_tool" / "state"
    planted.mkdir(parents=True)
    (planted / "process.py").write_text("import os\n")

    verdict = judge_action("Bash", "python3 rew_tool/state/process.py ./process show",
                           gate=GATE_FOREIGN, read_roots=roots)

    assert not verdict.allowed


def test_a_writer_is_asked_about_by_its_effect(tmp_path):
    verdict = judge_action("bash", "Command: python3 rew_tool/apply.py --preset FULL",
                           gate=GATE_WRITES, read_roots=_read_roots_for(tmp_path),
                           command="python3 rew_tool/apply.py --preset FULL")

    assert verdict.tool == "effectLedger"
    assert verdict.title == "Дозволити bash?"


@pytest.mark.parametrize("tool", ["Edit", "edit"])
def test_an_edit_of_a_writer_asks_as_an_edit(tool, tmp_path):
    """The effect names what a command RUNS; an edit of `apply.py` changes the script, it does not
    write a ledger snapshot."""
    verdict = judge_action(tool, "rew_tool/apply.py", gate=GATE_WRITES,
                           read_roots=_read_roots_for(tmp_path))

    assert not verdict.allowed and verdict.tool == tool


def test_a_shell_it_cannot_read_is_refused(tmp_path):
    with pytest.raises(ValueError):
        judge_action("Bash", "ls", gate=GATE_AUTO, read_roots=_read_roots_for(tmp_path),
                     shell="cmd")


def test_omps_tools_are_all_known_to_the_gate():
    """An omp tool the gate did not know would ask under `auto` — and a tool omp enables must be
    one this table has a row for, not one it meets as a stranger."""
    known = shell_gate.OMP_TOOLS
    assert set(omp_session_module._ENABLED_TOOLS) <= known


# ---- omp's own gate gives the table's answers, and decides through judge_action ----------------

class _Bridge:
    def __init__(self) -> None:
        self.requests: list[ConfirmRequest] = []

    def snapshot(self) -> dict:
        return {}

    def request_confirmation(self, request: ConfirmRequest) -> "Future[bool]":
        self.requests.append(request)
        future: "Future[bool]" = Future()
        future.set_result(False)
        return future


def _omp_gate(tmp_path, tool, detail, ticked, gate):
    """What omp's `_gate` did with one permission frame: answered, asked (and how), said."""
    session = OmpSession(project_dir=tmp_path, bridge=_Bridge(), gate=gate,
                         always_allowed=frozenset(ticked))
    sent: list[dict] = []
    session._send = sent.append  # type: ignore[assignment]
    title = f"Allow tool: {tool}\n{detail}"

    async def run():
        await session._gate({"type": "extension_ui_request", "id": "f1", "method": "select",
                             "title": title, "options": ["Approve", "Deny"]})
        events = []
        while not session._events.empty():
            events.append(session._events.get_nowait())
        return events

    events = asyncio.run(run())
    return session, sent, events


@pytest.mark.parametrize("tool, detail, ticked, gate, cell", list(_rows()))
def test_omp_answers_the_table(tool, detail, ticked, gate, cell, tmp_path):
    """omp's whole gate, frame in and answer out, against the FIXED cells — not against
    `judge_action`, which would only compare the function with itself."""
    session, sent, events = _omp_gate(tmp_path, tool, detail, ticked, gate)

    unasked = [event.command for event in events if isinstance(event, Unasked)]
    if session.bridge.requests:
        (request,) = session.bridge.requests
        seen = "ask!" if request.reason == "gateIrreversible" else "ask"
    else:
        assert sent[0]["value"] == "Approve"
        seen = "pass!" if unasked else "pass"
    assert seen == cell
    assert unasked == ([_command(detail)] if cell == "pass!" else [])


@pytest.mark.parametrize("verdict", [
    Verdict(True),
    Verdict(True, unasked="rm -rf ~/"),
    Verdict(False, tool="effectLedger", title="Дозволити bash?", detail="d", reason="r"),
])
def test_omps_gate_decides_through_judge_action(verdict, tmp_path, monkeypatch):
    """omp keeps no decision of its own: what `judge_action` says is what `_gate` does."""
    calls = []

    def judge(tool, detail, **kwargs):
        calls.append((tool, detail, kwargs))
        return verdict

    monkeypatch.setattr(omp_session_module, "judge_action", judge)
    session, sent, events = _omp_gate(tmp_path, "bash", "Command: rm -rf ~/", ("x",),
                                      GATE_FOREIGN)

    ((tool, detail, kwargs),) = calls
    assert (tool, detail) == ("bash", "Command: rm -rf ~/")
    assert kwargs["command"] == "rm -rf ~/"
    assert kwargs["gate"] == GATE_FOREIGN and kwargs["always_allowed"] == frozenset({"x"})
    assert kwargs["read_roots"] == session._read_roots
    if verdict.allowed:
        assert session.bridge.requests == [] and sent[0]["value"] == "Approve"
    else:
        (request,) = session.bridge.requests
        assert (request.tool, request.title, request.detail, request.reason) == (
            verdict.tool, verdict.title, verdict.detail, verdict.reason)
        assert sent[0]["value"] == "Deny"
    assert [e.command for e in events if isinstance(e, Unasked)] == (
        [verdict.unasked] if verdict.unasked else [])


# ---- Codex's vocabulary reads the same table ---------------------------------------------------

#: (Codex tool, what Codex sends, the omp row it must answer like)
CODEX_ROWS = [
    ("Bash", "ls -la", "bash", "Command: ls -la"),
    ("Bash", "rm -rf ~/", "bash", "Command: rm -rf ~/"),
    ("Bash", "echo done > process/plan.json", "bash", "Command: echo done > process/plan.json"),
    ("Bash", "rm -rf process/ ~", "bash", "Command: rm -rf process/ ~"),
    ("Bash", "powershell -c 'Remove-Item -Recurse -Force ~'", "bash",
     "Command: powershell -c 'Remove-Item -Recurse -Force ~'"),
    ("Edit", "process/plan.json", "edit", '{"path": "process/plan.json"}'),
    ("Edit", "/etc/hosts", "edit", '{"path": "/etc/hosts"}'),
    ("mcp__tcc__get_tcc_state", "{}", "mcp__tcc_copy_helix_eq", ""),
]


@pytest.mark.parametrize("gate", GATES)
@pytest.mark.parametrize("tool, detail, omp_tool, omp_detail", CODEX_ROWS)
def test_codex_names_answer_as_omp_names(tool, detail, omp_tool, omp_detail, gate, tmp_path):
    roots = _read_roots_for(tmp_path)
    codex = judge_action(tool, detail, gate=gate, read_roots=roots)
    omp = judge_action(omp_tool, omp_detail, gate=gate, read_roots=roots,
                       command=_command(omp_detail))

    assert (codex.allowed, bool(codex.unasked), codex.reason) == (
        omp.allowed, bool(omp.unasked), omp.reason)
    if not codex.allowed:
        assert codex.title == f"Дозволити {tool}?"


@pytest.mark.parametrize("gate", GATES)
@pytest.mark.parametrize("tool", ["shell", "exec", "commandExecution", "apply_patch",
                                  "mcp__other__x"])
def test_a_name_the_gate_does_not_know_asks(tool, gate, tmp_path):
    """Not Codex's `Bash`/`Edit`, not omp's own, not TCC's: asked about under every gate that
    asks at all, and said under `never` — it was let through `auto` without a look."""
    verdict = judge_action(tool, "rm -rf ~/", gate=gate, read_roots=_read_roots_for(tmp_path))

    assert _cell(verdict) == ("pass!" if gate == GATE_NEVER else "ask")


@pytest.mark.parametrize("ticked", ["Bash", "bash"])
def test_a_tick_holds_in_either_spelling(ticked, tmp_path):
    """The bar remembers the name it asked under (`Bash` for Codex and the SDK, `bash` for omp);
    both stand for the same tool, so a tick in either stops the asking — for an ordinary command.
    For one that cannot be undone neither does (the Arbiter, 2026-10-14)."""
    roots = _read_roots_for(tmp_path)
    assert judge_action("Bash", "echo x > /tmp/out.txt", gate=GATE_WRITES,
                        always_allowed={ticked}, read_roots=roots).allowed
    assert _cell(judge_action("Bash", "rm -rf ~/", gate=GATE_AUTO, always_allowed={ticked},
                              read_roots=roots)) == "ask!"


def test_a_detail_that_says_command_cannot_hide_its_head(tmp_path):
    """omp's `Command: …` split is omp's, made by its caller: a Codex line that merely contains the
    word must be judged whole, or `rm -rf ~ # Command: ls` would read as `ls`."""
    verdict = judge_action("Bash", "rm -rf ~/ # Command: ls", gate=GATE_AUTO,
                           read_roots=_read_roots_for(tmp_path))

    assert not verdict.allowed and verdict.reason == "gateIrreversible"


# ---- PowerShell lines, whole --------------------------------------------------------------------

#: (line, {gate: cell}) — a line Codex runs in PowerShell, judged with `shell="powershell"`.
POWERSHELL_TABLE = [
    (r"Remove-Item -Recurse -Force C:\Users",
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("Remove-Item -Recurse $HOME",
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    (r'"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe" -Command '
     r'"Remove-Item -Recurse -Force C:\Users"',
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    (r"Remove-Item -Recurse -Force C:\Users\me process/plan.json",
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("Remove-Item -Recurse -Force $HOME state/x.json",
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("Get-ChildItem",
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("Remove-Item -Recurse -Force build",
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("Remove-Item process/x.tmp",
     {GATE_WRITES: "ask", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("Get-Content 'C:\\x\\y.txt",  # a quote that never closes: unknown is not safe
     {GATE_WRITES: "ask!", GATE_FOREIGN: "ask!", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
]


@pytest.mark.parametrize("gate", GATES)
@pytest.mark.parametrize("line, cells", POWERSHELL_TABLE)
def test_a_powershell_line(line, cells, gate, tmp_path):
    verdict = judge_action("Bash", line, gate=gate, read_roots=_read_roots_for(tmp_path),
                           shell=SHELL_POWERSHELL)

    assert _cell(verdict) == cells[gate]


def test_a_powershell_line_read_as_bash_would_lose_its_backslash(tmp_path):
    """Why `shell` exists: bash reads `C:\\Users` as `C:Users`, and a recursive delete of the
    users' folder passes `auto` unasked. PowerShell's own reader is added, never substituted."""
    line = r"Remove-Item -Recurse -Force C:\Users"
    roots = _read_roots_for(tmp_path)

    assert judge_action("Bash", line, gate=GATE_AUTO, read_roots=roots).allowed
    assert not judge_action("Bash", line, gate=GATE_AUTO, read_roots=roots,
                            shell=SHELL_POWERSHELL).allowed


def test_a_powershell_line_is_never_read_only(tmp_path, monkeypatch):
    """The read-only allowlist is bash's; a PowerShell line it would pass still asks."""
    monkeypatch.setattr(shell_gate, "bash_is_read_only", lambda command, roots: True)

    verdict = judge_action("Bash", "ls", gate=GATE_WRITES, read_roots=_read_roots_for(tmp_path),
                           shell=SHELL_POWERSHELL)

    assert not verdict.allowed


# ---- the danger classes, bash beside PowerShell (group fix C2) ---------------------------------

#: (danger class, shell, line) — every row asks as «cannot be undone» under `auto` and with a
#: «don't ask again» tick on `Bash`, and passes only under `never`, said there (`Unasked`). Before
#: the group fix PowerShell's disk cmdlets passed `auto` and a tick while bash's `mkfs` asked.
DANGER_TABLE = [
    ("recursive delete", B, "rm -rf ~/"),
    ("recursive delete", P, "Remove-Item -Recurse -Force $HOME"),
    ("recursive delete", P, r"ri -r C:\Users"),
    ("recursive delete", P, r'pwsh -Command "Remove-Item -Recurse C:\"'),
    ("format/wipe disk", B, "mkfs.ext4 /dev/sdb1"),
    ("format/wipe disk", B, "diskutil eraseDisk APFS X disk2"),
    ("format/wipe disk", P, "Format-Volume -DriveLetter D"),
    ("format/wipe disk", P, "format-volume -dr D -FileSystem NTFS"),
    ("format/wipe disk", P, "Clear-Disk -Number 1 -RemoveData"),
    ("format/wipe disk", P, "Get-Disk 1 | Clear-Disk -RemoveData -Confirm:$false"),
    ("format/wipe disk", P, r"Storage\Clear-Disk -Number 1"),
    ("format/wipe disk", P, "Remove-Partition -DriveLetter D"),
    ("format/wipe disk", P, "Initialize-Disk -Number 1 -PartitionStyle GPT"),
    ("format/wipe disk", P, "Set-Disk -Number 1 -PartitionStyle MBR"),
    ("format/wipe disk", P, "Remove-Volume -DriveLetter D"),
    ("format/wipe disk", P, "Reset-PhysicalDisk -FriendlyName PhysicalDisk1"),
    ("format/wipe disk", P, "diskpart /s wipe.txt"),
    ("format/wipe disk", P, "'select disk 1', 'clean' | diskpart.exe"),
    ("format/wipe disk", P, "Start-Process diskpart -Verb RunAs"),
    ("format/wipe disk", P, "format D: /q"),
    ("format/wipe disk", P, r"cipher /w:C:\ "),
    ("format/wipe disk", P, r"cmd /c cipher /W:D:\data"),
    ("format/wipe disk", P, 'powershell.exe -Command "Format-Volume -DriveLetter D"'),
    ("format/wipe disk", P, "pwsh -c 'Clear-Disk -Number 1 -RemoveData'"),
    ("format/wipe disk", P, "Invoke-Command { Remove-Partition -DriveLetter D }"),
    # Start-Process handing a line to cmd or PowerShell (the re-review's C): read as that shell's.
    ("format/wipe disk", P, "Start-Process cmd -ArgumentList '/c format D:'"),
    ("format/wipe disk", P, "Start-Process cmd '/c format D: /q /y'"),
    ("format/wipe disk", P, "Start-Process powershell -ArgumentList '-Command Format-Volume -DriveLetter D'"),
    ("format/wipe disk", P, "Start-Process powershell 'Clear-Disk 1 -RemoveData'"),
    ("format/wipe disk", P, "Start-Process -FilePath cmd.exe -ArgumentList '/c diskpart /s wipe.txt'"),
    ("format/wipe disk", P, "saps -Verb RunAs -FilePath pwsh -Args '-c','Clear-Disk 1 -RemoveData'"),
    ("format/wipe disk", P, "Start-Process cmd -ArgumentList '/c', 'format D: /q'"),
    ("format/wipe disk", P, "start -Wait cmd '/c format D:'"),
    ("format/wipe disk", P, "Start-Process pwsh -ArgumentList '-EncodedCommand AAAA'"),
    ("format/wipe disk", P, "Start-Process powershell.exe -ArgumentList '-enc AAAA'"),
    ("recursive delete", P, r"Start-Process cmd -ArgumentList '/c rd /s /q C:\Users'"),
    ("recursive delete", P,
     r"Start-Process powershell -ArgumentList '-c Remove-Item -Recurse -Force C:\Users'"),
    # A colon-bound quoted parameter is still a parameter (the narrow re-review, 1).
    ("format/wipe disk", P, "Start-Process cmd -ArgumentList:'/c format D:'"),
    ("format/wipe disk", P, "Start-Process -FilePath:cmd -ArgumentList:'/c format D:'"),
    ("format/wipe disk", P, "Start-Process -FilePath:'cmd.exe' -ArgumentList:\"/c format D:\""),
    ("recursive delete", P, r"Remove-Item -Path:'C:\Users' -Recurse:$true -Force"),
    ("recursive delete", P, r"Remove-Item -Recurse -LiteralPath:'C:\Users'"),
    ("recursive delete", P, r"Set-Location -Path:'C:\'; Remove-Item -Recurse *"),
    # WSL runs a bash line (the narrow re-review, 2).
    ("recursive delete", P, "wsl rm -rf ~"),
    ("recursive delete", P, "wsl.exe rm -rf ~"),
    ("recursive delete", P, "wsl -- rm -rf ~"),
    ("recursive delete", P, "wsl -e rm -rf /mnt/c/Users"),
    ("recursive delete", P, "wsl --exec rm -rf /mnt/c/Users"),
    ("recursive delete", P, "wsl -d Ubuntu -u root --cd / rm -rf /mnt/c/Users"),
    ("recursive delete", P, r"C:\Windows\System32\wsl.exe rm -rf ~"),
    ("recursive delete", P, r'"C:\Windows\System32\bash.exe" -c "rm -rf ~"'),
    ("recursive delete", P, "Start-Process wsl -ArgumentList '-e rm -rf /mnt/c/Users'"),
    ("recursive delete", P, "Start-Process wsl.exe 'rm -rf ~'"),
    ("recursive delete", P, "Start-Process bash -ArgumentList '-c \"rm -rf ~\"'"),
    ("recursive delete", B, "wsl rm -rf ~"),
    ("format/wipe disk", P, "wsl --unregister Ubuntu"),
    ("format/wipe disk", P, "wsl --shutdown"),
    ("format/wipe disk", P, "wsl -t Ubuntu"),
    ("format/wipe disk", P, "wsl -e mkfs.ext4 /dev/sdb1"),
    # Fable's final review, C1: recursion on the PRODUCER, a deleter fed by it (bash's xargs rule).
    ("recursive delete", B, "find ~ -type f | xargs rm -f"),
    ("recursive delete", P, "Get-ChildItem ~ -Recurse -File | Remove-Item -Force"),
    ("recursive delete", P, r"dir C:\Users -r -file | del"),
    ("recursive delete", P, "gci $HOME -Recurse | % { Remove-Item $_.FullName -Force }"),
    ("recursive delete", P, "Get-ChildItem ~ -Recurse | ForEach-Object { ri $_ }"),
    ("recursive delete", P, "foreach ($f in Get-ChildItem ~ -Recurse -File) { Remove-Item $f }"),
    ("recursive delete", P, "$all = gci ~ -r -file; $all | Remove-Item"),
    ("recursive delete", P, "Get-Content list.txt | Remove-Item"),
    ("recursive delete", P, "gci ~ -Recurse -File | Clear-Content"),
    ("recursive delete", B, "find ~ -delete"),
    ("recursive delete", B, "rsync -a --delete /tmp/empty/ ~/"),
    ("recursive delete", B, "rsync -r --delete-before x/ /Users/me/"),
    # I1: a delete or an overwrite of a wide glob, recursive or not.
    ("wide delete or overwrite", B, "rm ~/*"),
    ("wide delete or overwrite", B, "rm -f /Users/*/Desktop/*"),
    ("wide delete or overwrite", B, 'for f in ~/*; do rm "$f"; done'),
    ("wide delete or overwrite", B, "truncate -s 0 ~/*"),
    ("wide delete or overwrite", B, "echo | tee ~/*"),
    ("wide delete or overwrite", B, "shred -u ~/*"),
    ("wide delete or overwrite", B, "cd ~ && rm *"),
    ("wide delete or overwrite", P, r"Remove-Item ~\* -Force"),
    ("wide delete or overwrite", P, r"Remove-Item C:\Users\*\Desktop\* -Force"),
    ("wide delete or overwrite", P, r"del C:\Users\me\*"),
    ("wide delete or overwrite", P, r"cmd /c del /q C:\Users\me\*"),
    ("wide delete or overwrite", P, r"Clear-Content ~\*"),
    ("wide delete or overwrite", P, r"Set-Content -Path C:\Users\*\Desktop\* -Value ''"),
    # I2: classes one shell had and the other did not.
    ("shutdown", B, "shutdown -h now"),
    ("shutdown", B, "systemctl poweroff"),
    ("shutdown", B, "poweroff"),
    ("shutdown", P, "Stop-Computer -Force"),
    ("shutdown", P, "Restart-Computer -Force"),
    ("shutdown", P, "shutdown /s /t 0"),
    ("shutdown", P, "shutdown /r"),
    ("recursive permissions", B, "chmod -R 777 ~"),
    ("recursive permissions", P, r"icacls C:\Users /reset /T /C"),
    ("recursive permissions", P, r"icacls $HOME /grant Everyone:F /T"),
    ("recursive permissions", P, r"takeown /R /F C:\Users"),
    ("registry", B, "reg delete 'HKCU\\Software' /f"),
    ("registry", P, r"Remove-Item -Recurse -Force HKCU:\Software"),
    ("registry", P, r"reg delete HKCU\Software /f"),
    ("registry", P, r"Remove-Item -Recurse Registry::HKEY_LOCAL_MACHINE\SOFTWARE"),
    ("registry", P, r'reg delete "HKLM\SYSTEM" /f'),
    ("kill everything", B, "kill -9 -1"),
    ("kill everything", B, "kill -s KILL -1"),
    ("kill everything", B, "pkill -9 ."),
    ("kill everything", P, "Get-Process | Stop-Process -Force"),
    ("kill everything", P, "Stop-Process -Name * -Force"),
    ("kill everything", P, "taskkill /F /IM *"),
    ("kill everything", P, "gps | kill -Force"),
    ("code it cannot read", B, "crontab -r"),
    ("code it cannot read", P, "[IO.Directory]::Delete($HOME, $true)"),
    ("code it cannot read", P, "[System.IO.Directory]::Delete('C:\\Users\\me', $true)"),
    ("code it cannot read", P, "(Get-Item $HOME).Delete($true)"),
    ("code it cannot read", P, "[scriptblock]::Create('Remove-Item -Recurse ~').Invoke()"),
    ("code it cannot read", P, "& ([scriptblock]::Create('ri -r ~'))"),
    ("code it cannot read", P, "$d = [IO.DirectoryInfo]::new($HOME); $d.Delete($true)"),
    ("code it cannot read", P, "[IO.File]::WriteAllText(\"$HOME\\.bashrc\", '')"),
    ("code it cannot read", P, "iex $cmd"),
    ("code it cannot read", P, "Invoke-Expression (Get-Content x.ps1 -Raw)"),
    ("raw device overwrite", B, "dd if=/dev/zero of=/dev/disk2"),
    ("raw device overwrite", B, "echo x > /dev/disk2"),
    ("raw device overwrite", P, r"Set-Content -Path \\.\PhysicalDrive1 -Value 0"),
    ("raw device overwrite", P, r"dd if=zero.bin of=\\.\PhysicalDrive1"),
    ("raw device overwrite", P, r"[IO.File]::WriteAllBytes('\\.\PhysicalDrive0', $b)"),
]


DANGER_CLASSES = ("recursive delete", "format/wipe disk", "raw device overwrite",
                  "wide delete or overwrite", "shutdown", "recursive permissions", "registry",
                  "kill everything", "code it cannot read")


def _danger_id(row):
    return f"{row[0]}: {row[2]}"


@pytest.mark.parametrize("cls, shell, line", DANGER_TABLE, ids=[_danger_id(r) for r in DANGER_TABLE])
def test_each_danger_class_asks_in_bash_and_powershell_alike(cls, shell, line, tmp_path):
    roots = _read_roots_for(tmp_path)

    def judged(gate, ticked=()):
        return judge_action("Bash", line, gate=gate, always_allowed=frozenset(ticked),
                            read_roots=roots, shell=shell)

    for gate in (GATE_WRITES, GATE_FOREIGN, GATE_AUTO):
        assert _cell(judged(gate)) == "ask!", gate
        assert _cell(judged(gate, ("Bash",))) == "ask!", f"{gate} with a tick"
    never = judged(GATE_NEVER, ("Bash",))
    assert _cell(never) == "pass!" and never.unasked == line


def test_the_danger_table_covers_each_class_in_both_shells():
    assert {(cls, shell) for cls, shell, _ in DANGER_TABLE} == {
        (cls, shell) for cls in DANGER_CLASSES for shell in (B, P)}


@pytest.mark.parametrize("line", [
    "Get-Disk", "Get-Volume", "Get-Partition -DiskNumber 1", "cipher /c secret.txt",
    "Format-Table -AutoSize", "Get-Content notes.txt | Format-List",
    r"Get-Content \\?\C:\Users\me\notes.txt", "Start-Process notepad", "start notepad",
    "Start-Process notepad -ArgumentList 'readme.txt'", "Start-Process cmd -ArgumentList '/c dir'",
    "Start-Process powershell -ArgumentList '-c Get-ChildItem' -Wait", "Start-Process cmd",
    "wsl ls", "wsl -l", "wsl --list --verbose", "wsl --status", "wsl", "wsl -d Ubuntu",
    "wsl -e ls -la", "wsl -- cat notes.txt", "Start-Process wsl", "Remove-Item -Path:'x.tmp'",
    # Fable's round: the narrow side of each new class still passes `auto`.
    "Get-ChildItem *.tmp | Remove-Item", "gci process -Filter *.tmp | Remove-Item -Force",
    "Get-ChildItem build | ForEach-Object { Remove-Item $_.FullName }",
    r"Remove-Item process\*.tmp", "Remove-Item build -Recurse -Force", r"del build\*.o",
    "Clear-Content process/log.txt", "Get-ChildItem ~ -Recurse -Filter *.mdat",
    r"icacls process\a.json /grant me:F", r"icacls build /T /grant me:F",
    r"reg query HKCU\Software\Autosound", r"Remove-Item HKCU:\Software\AutosoundTCC\Cache -Recurse",
    "Stop-Process -Id 4242", "taskkill /PID 4242", "Get-Process rew | Select-Object Id",
    "(Get-Item process).FullName"])
def test_the_disk_class_does_not_take_in_reads(line, tmp_path):
    """Looking at disks, and `Format-Table`, are not wiping one: they pass `auto` as before."""
    assert judge_action("Bash", line, gate=GATE_AUTO, read_roots=_read_roots_for(tmp_path),
                        shell=SHELL_POWERSHELL).allowed


# ---- the tick rule, one table across the three routes (group fix I4) ---------------------------

#: The tick rows of `OMP_TABLE` — omp and Codex answer them from `judge_action` (`test_the_table`,
#: `test_omp_answers_the_table`); the SDK route answers them from `TuningSession._can_use_tool`.
TICK_ROWS = [row for row in OMP_TABLE if row[0] in (
    "a Codex tick, a home wipe", "always-allowed dangerous bash", "always-allowed ordinary bash")]
#: A PowerShell spelling a bash shell cannot run as written (bash eats `\\`, and `ri` is no bash
#: command): the SDK route's Bash tool never runs it, and its reader is bash's alone.
BASH_CANNOT_RUN = {r"ri -r C:\Users", r"Storage\Clear-Disk -Number 1",
                   r"C:\Windows\System32\wsl.exe rm -rf ~",
                   # Fable's round: PowerShell's pipeline of objects, its cmdlets and `iex` — no
                   # bash runs them; their bash twins are rows of their own (`find ~ | xargs rm`,
                   # `rm ~/*`, `kill -9 -1`, `chmod -R`, `reg delete '…'`).
                   "iex $cmd", "Get-Process | Stop-Process -Force", "gps | kill -Force",
                   "Stop-Process -Name * -Force", r"dir C:\Users -r -file | del",
                   "gci ~ -Recurse -File | Clear-Content",
                   "gci $HOME -Recurse | % { Remove-Item $_.FullName -Force }",
                   "Get-ChildItem ~ -Recurse -File | Remove-Item -Force",
                   "Get-ChildItem ~ -Recurse | ForEach-Object { ri $_ }",
                   "Get-Content list.txt | Remove-Item",
                   r"Remove-Item -Recurse -Force HKCU:\Software",
                   r"Remove-Item -Recurse Registry::HKEY_LOCAL_MACHINE\SOFTWARE",
                   r"Remove-Item C:\Users\*\Desktop\* -Force", r"del C:\Users\me\*",
                   r"Set-Content -Path C:\Users\*\Desktop\* -Value ''",
                   # unquoted `\`, which bash strips before the program sees it
                   r"icacls C:\Users /reset /T /C", r"takeown /R /F C:\Users",
                   r"reg delete HKCU\Software /f", r"cmd /c del /q C:\Users\me\*"}


def _sdk_cell(line: str, gate: str, ticked: tuple, tmp_path) -> str:
    """The SDK route's answer in the table's cells: what `_ask` was asked with, or what passed."""
    from autosound_tcc.core.tuning_session import TuningSession

    sdk = TuningSession(project_dir=tmp_path, gate=gate,
                        always_allowed=frozenset("Bash" for _ in ticked))
    asked: list[str] = []

    async def ask(tool, detail, payload, deny_reason, reason=""):
        asked.append(reason)
        return "asked"

    sdk._ask = ask
    result = asyncio.run(sdk._can_use_tool("Bash", {"command": line}, None))
    if asked:
        assert result == "asked"
        return "ask!" if asked == ["gateIrreversible"] else "ask"
    return "pass!" if sdk._unasked == [line] else "pass"


def test_the_tick_rows_cover_the_three_rows():
    assert len(TICK_ROWS) == 3


@pytest.mark.parametrize("tool, detail, ticked, gate, cell", list(_rows(TICK_ROWS)))
def test_the_sdk_route_answers_the_tick_rows_as_omp_and_codex_do(tool, detail, ticked, gate, cell,
                                                                  tmp_path):
    """A tick removes the question for an ordinary command and never for one that cannot be undone
    — on the SDK route too, under every gate; `never` passes and says it (the Arbiter,
    2026-10-14). `foreign` and `never` pinned here as well as `writes` and `auto`."""
    assert _sdk_cell(_command(detail), gate, ticked, tmp_path) == cell


@pytest.mark.parametrize("cls, shell, line",
                         [row for row in DANGER_TABLE if row[2] not in BASH_CANNOT_RUN],
                         ids=[_danger_id(r) for r in DANGER_TABLE if r[2] not in BASH_CANNOT_RUN])
def test_the_sdk_route_asks_about_each_danger_class(cls, shell, line, tmp_path):
    """C2's rows through the SDK route: asked under `auto`, and with a tick under every gate that
    asks; under `never` let through and said."""
    assert _sdk_cell(line, GATE_AUTO, (), tmp_path) == "ask!"
    for gate in (GATE_WRITES, GATE_FOREIGN, GATE_AUTO):
        assert _sdk_cell(line, gate, ("Bash",), tmp_path) == "ask!", gate
    assert _sdk_cell(line, GATE_NEVER, ("Bash",), tmp_path) == "pass!"


@pytest.mark.parametrize("line", [
    "rm process/*.tmp", "rm -f build/*.o", "rm ~/.cache/tcc-x.tmp", "truncate -s 0 process/log.txt",
    "echo x | tee process/out.txt", 'for f in process/*.tmp; do rm "$f"; done',
    "rsync -a --delete build/ dist/", "rsync -a ~/notes/ backup/", "kill 12345", "kill -9 4242",
    "pkill -f rew_tool/server.py", "chmod -R u+w build",
    "shutdown_report.sh", "crontab -l"])
def test_the_new_classes_leave_ordinary_bash_alone(line, tmp_path):
    assert judge_action("Bash", line, gate=GATE_AUTO, read_roots=_read_roots_for(tmp_path)).allowed


@pytest.mark.parametrize("line", [row[2] for row in DANGER_TABLE if row[0] == "code it cannot read"
                                  and row[1] == P])
def test_a_dotnet_call_asks_by_the_powershell_reader_s_own_rule(line):
    """These asked only because bash's reader trips on `[`/`(` (Fable's final review, I2): the
    PowerShell reader asks by rule — a .NET member call that deletes, writes or runs code, or
    `iex` of what the line does not spell."""
    assert shell_gate._powershell_line_is_dangerous(line, 0)


@pytest.mark.parametrize("gate", [GATE_WRITES, GATE_AUTO])
def test_omp_judges_the_whole_command_and_cuts_only_what_it_shows(gate, tmp_path):
    """Fable's final review, I3: the detail was cut at 400 characters BEFORE the gate read it, so
    `echo <400 a> ; rm -rf ~` was judged without its delete. The gate reads it whole; the bar
    shows at most 400 characters of it."""
    line = "echo " + "a" * 400 + " ; rm -rf ~"
    session, sent, _events = _omp_gate(tmp_path, "bash", f"Command: {line}", (), gate)

    (request,) = session.bridge.requests
    assert request.reason == "gateIrreversible"
    assert len(request.detail) <= 400


@pytest.mark.parametrize("path, inside", [
    ("C:/Users/Me/car/process/x.tmp", "process/x.tmp"),     # another case: one Windows folder
    ("c:/users/me/CAR/process", "process"),
    ("/c/Users/me/car/process/x.tmp", "process/x.tmp"),     # Git Bash's spelling of the drive
    ("/C/Users/Me/car", ""),
    ("C:/Users/me/car-other/process", None),
    ("D:/Users/me/car/process", None),
    ("/d/Users/me/car/process", None),
])
def test_an_absolute_windows_path_is_read_inside_the_project(path, inside):
    """The foreign rule anchors owned paths in the project; on Windows a bash line names the
    project as `C:/…` in any case or as Git Bash's `/c/…` — both are the project."""
    assert shell_gate._inside(path, PureWindowsPath(r"C:\Users\me\car")) == inside


def test_an_unquoted_windows_path_in_a_bash_line_is_not_the_projects(tmp_path, monkeypatch):
    """Why the Windows CI rows failed: bash strips an unquoted `\\` before `rm` sees the path, so
    `rm C:\\Users\\…\\car/process/x.tmp` deletes `C:Users…car/process/x.tmp` — not a skill file. The
    gate's refusal under `foreign` is right; the same file by `C:/…` passes (above)."""
    project, roots = _project(tmp_path)
    windows_like = "C:" + "\\".join(["", "Users", "runneradmin", "car"]) + "/process/x.tmp"

    verdict = judge_action("Bash", f"rm {windows_like}", gate=GATE_FOREIGN, read_roots=roots)

    assert not verdict.allowed
