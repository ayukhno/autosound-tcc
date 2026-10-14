"""`shell_gate.judge_action` — the one gate omp and Codex answer from (tcc#181, W-10 task 5).

It is `OmpSession._auto_allowed` and the decision half of `_gate`, lifted unchanged. The table
below is what omp answered before the move, gate by gate; the parity test runs the same rows
through omp's own `_gate`, so the day the two disagree, one of them changed.

Each cell: `pass` — runs unasked; `pass!` — runs unasked under `never` and is said in the dialog
(`Unasked`); `ask` — the Arbiter is asked; `ask!` — asked as «cannot be undone» (`auto`).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future

import pytest

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
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
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
    ("always-allowed tool", "write", '{"path": "/etc/hosts"}', ("write",),
     {GATE_WRITES: "pass", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("always-allowed dangerous bash", "bash", "Command: rm -rf ~/", ("bash",),
     {GATE_WRITES: "pass", GATE_FOREIGN: "pass", GATE_AUTO: "pass", GATE_NEVER: "pass!"}),
    ("PowerShell read", "bash", "Command: powershell -c 'Get-ChildItem ~'", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("PowerShell delete", "bash", "Command: powershell -c 'Remove-Item -Recurse -Force ~'", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("a writer with an effect", "bash", "Command: python3 rew_tool/apply.py --preset FULL", (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("unknown tool", "browser_open", '{"url": "x"}', (),
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
]


def _command(detail: str) -> str:
    """omp's split of `Command: …`, as `OmpSession._gate` makes it."""
    return detail.split("Command:", 1)[-1].strip() if "Command:" in detail else detail


def _cell(verdict: Verdict) -> str:
    if verdict.allowed:
        return "pass!" if verdict.unasked else "pass"
    return "ask!" if verdict.reason == "gateIrreversible" else "ask"


def _rows():
    for name, tool, detail, ticked, cells in OMP_TABLE:
        for gate in GATES:
            yield pytest.param(tool, detail, ticked, gate, cells[gate], id=f"{name}-{gate}")


@pytest.mark.parametrize("tool, detail, ticked, gate, cell", list(_rows()))
def test_the_table(tool, detail, ticked, gate, cell, tmp_path):
    verdict = judge_action(tool, detail, gate=gate, always_allowed=frozenset(ticked),
                           read_roots=_read_roots_for(tmp_path), command=_command(detail))

    assert _cell(verdict) == cell
    if verdict.unasked:
        assert verdict.unasked == _command(detail)
    if not verdict.allowed:
        assert verdict.title == f"Дозволити {tool}?"
        # Under `auto` the question is the command itself; otherwise what the tool wants.
        assert verdict.detail == (_command(detail) if cell == "ask!" else detail)


def test_a_writer_is_asked_about_by_its_effect(tmp_path):
    verdict = judge_action("bash", "Command: python3 rew_tool/apply.py --preset FULL",
                           gate=GATE_WRITES, read_roots=_read_roots_for(tmp_path),
                           command="python3 rew_tool/apply.py --preset FULL")

    assert verdict.tool == "effectLedger"
    assert verdict.title == "Дозволити bash?"


# ---- omp's own gate gives the table's answers --------------------------------------------------

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
    session, sent, events = _omp_gate(tmp_path, tool, detail, ticked, gate)
    verdict = judge_action(tool, detail, gate=gate, always_allowed=frozenset(ticked),
                           read_roots=session._read_roots, command=_command(detail))

    assert session._auto_allowed(tool, detail) is verdict.allowed
    if verdict.allowed:
        assert session.bridge.requests == []
        assert sent[0]["value"] == "Approve"
    else:
        (request,) = session.bridge.requests
        assert (request.tool, request.title, request.detail, request.reason) == (
            verdict.tool, verdict.title, verdict.detail, verdict.reason)
    unasked = [event.command for event in events if isinstance(event, Unasked)]
    assert unasked == ([verdict.unasked] if verdict.unasked else [])
    assert _cell(verdict) == cell


# ---- Codex's vocabulary reads the same table ---------------------------------------------------

#: (Codex tool, what Codex sends, the omp row it must answer like)
CODEX_ROWS = [
    ("Bash", "ls -la", "bash", "Command: ls -la"),
    ("Bash", "rm -rf ~/", "bash", "Command: rm -rf ~/"),
    ("Bash", "echo done > process/plan.json", "bash", "Command: echo done > process/plan.json"),
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


@pytest.mark.parametrize("ticked", ["Bash", "bash"])
def test_a_tick_holds_in_either_spelling(ticked, tmp_path):
    """The bar remembers the name it asked under (`Bash` for Codex and the SDK, `bash` for omp);
    both stand for the same tool, so a tick in either stops the asking."""
    verdict = judge_action("Bash", "rm -rf ~/", gate=GATE_AUTO, always_allowed={ticked},
                           read_roots=_read_roots_for(tmp_path))

    assert verdict.allowed


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
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("Remove-Item -Recurse $HOME",
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    (r'"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe" -Command '
     r'"Remove-Item -Recurse -Force C:\Users"',
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
    ("Get-ChildItem",
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("Remove-Item -Recurse -Force build",
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "pass", GATE_NEVER: "pass"}),
    ("Get-Content 'C:\\x\\y.txt",  # a quote that never closes: unknown is not safe
     {GATE_WRITES: "ask", GATE_FOREIGN: "ask", GATE_AUTO: "ask!", GATE_NEVER: "pass!"}),
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
