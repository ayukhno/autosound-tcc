"""The gate over what Codex on Windows really asks (W-10, the Arbiter's Windows pass, round 3).

Every `item/commandExecution/requestApproval` a Windows Codex sent on the Arbiter's VM, by shape:
the line PowerShell runs, with the person's folders replaced by a tmp project and the method's copy.
Codex sends `powershell.exe -Command <line>` with its argv joined the POSIX way, and the gate reads
it as Codex sent it — `_codex_join` makes that joint as Codex does (checked against the VM's log:
each of its 26 lines came out byte for byte).

Under `auto` every read passes, and so does every write and every delete of one file inside the
project: two of these reads and the delete asked as «cannot be undone» on the VM. Under `writes`
the writes and the deletes ask.
"""

from __future__ import annotations

import re

import pytest

from autosound_tcc.core import codex_session
from autosound_tcc.core.shell_gate import (GATE_AUTO, GATE_NEVER, GATE_WRITES, SHELL_POWERSHELL,
                                           judge_action)
from autosound_tcc.core.tuning_session import _read_roots_for

POWERSHELL = r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"
READ, WRITE, DELETE = "read", "write", "delete"

#: (kind, the line PowerShell runs). `{project}` is the project, `{skill}` the method's copy.
CORPUS = [
    (READ, r"Get-Content -Raw '{skill}\SKILL.md'"),
    (READ, r'python "{skill}\rew_tool\deployment.py" "{project}"'),
    (READ, r'python "{skill}\rew_tool\contract.py" check "{project}"'),
    (READ, r'python "{skill}\rew_tool\state\state.py" --root "{project}\state" registry render'),
    (READ, r'python "{skill}\rew_tool\project.py" "{project}" show'),
    (READ, r'python "{skill}\rew_tool\state\process.py" "{project}\process" show'),
    (READ, 'rg --files -g "tuning-changelog*" -g "phase_2_eq.md" -g "autosound_context.md" '
           '-g "project.json" -g "process-state.json"'),
    (READ, "Get-Content -Tail 100 'tuning-changelog.md'"),
    (READ, r"Get-Content -Raw 'docs\plans\_7-capture.md'"),
    (READ, "Get-Content -Raw 'autosound_context.md'"),
    (READ, r'Get-Content -Raw "{skill}\references\phases\phase_2_eq.md"'),
    (READ, r"Get-Content -Tail 30 'process\journal.jsonl'"),
    (READ, "if (Test-Path -LiteralPath 'test-tcc.txt') { Get-Content -Raw -LiteralPath "
           "'test-tcc.txt' } else { 'MISSING' }"),
    (READ, "if (Test-Path -LiteralPath 'test2.txt') { 'EXISTS' } else { 'MISSING' }"),
    (READ, "Get-Content -Encoding UTF8 -TotalCount 14 'tuning-changelog.md'"),
    (READ, r'Get-Content -Encoding UTF8 -Raw "{skill}\references\phases\virtual-first.md"'),
    (READ, r'python "{skill}\rew_tool\project.py" "{project}" show | ConvertFrom-Json | '
           "Select-Object schema_version,project_rev,car,source,dsp,language,project_type,presets,"
           "measurement"),
    # The two reads the VM asked about under `auto`: a hashtable and a cast, and `{ $_.Line }`.
    (READ, r'$state = python "{skill}\rew_tool\state\process.py" "{project}\process" show | '
           "ConvertFrom-Json; [PSCustomObject]@{schema_version=$state.schema_version; "
           "updated=$state.updated; active_phase=$state.active_phase; phases=$state.phases; "
           "capture=[PSCustomObject]@{id=$state.capture.id; n=$state.capture.n; "
           "expected_count=$state.capture.expected.Count; taken=$state.capture.taken}} | "
           "ConvertTo-Json -Depth 10"),
    (READ, r"Select-String -Path 'process\journal.jsonl' -Pattern "
           "'method|checkout|beta 3.1|3.1.0-rc1|2026-10-07' | Select-Object -Last 8 | "
           "ForEach-Object { $_.Line }"),
    (READ, r"Get-Content -Tail 5 'process\journal.jsonl'; Select-String -Path "
           r"'process\journal.jsonl' -Pattern '3.1.0-rc1|Stay on beta' | Select-Object -Last 1 | "
           "ForEach-Object { $_.Line }"),
    (WRITE, "Set-Content -LiteralPath 'test-tcc.txt' -Value 'hi' -NoNewline -Encoding utf8; "
            "Get-Content -Raw -LiteralPath 'test-tcc.txt'"),
    (WRITE, "Set-Content -LiteralPath 'test2.txt' -Value 'hi' -NoNewline -Encoding utf8; "
            "Get-Content -Raw -LiteralPath 'test2.txt'"),
    # Codex's own delete: the target resolved from a literal on the line, checked, removed.
    (DELETE, "$resolvedTarget = (Resolve-Path -LiteralPath 'test3.txt').Path; if ($resolvedTarget "
             r"-ne '{project}\test3.txt') { throw " + '"Unexpected target: $resolvedTarget" }; '
             "Remove-Item -LiteralPath $resolvedTarget; if (Test-Path -LiteralPath 'test3.txt') "
             "{ throw 'File still exists' }; 'Deleted and verified.'"),
    (DELETE, "Remove-Item -LiteralPath 'test3.txt'"),
    (DELETE, r"Remove-Item 'process\old.tmp' -Force"),
    (DELETE, "del test3.txt"),
    (DELETE, "ri test3.txt"),
]


def _codex_quote(word: str) -> str:
    """One argv word as Codex on Windows quotes it: bare when nothing needs quoting; `'…'` when it
    holds no `'` or `\\`; `"…"` (`\\` and `"` escaped) when it holds no `$` or backtick; otherwise
    stretches of each, a `'`/`\\` opening a double-quoted one and a `$`/backtick a single-quoted one."""
    if re.fullmatch(r"[\w@%+=:,./-]+", word):
        return word
    if not any(ch in word for ch in "'\\"):
        return f"'{word}'"

    def double(text: str) -> str:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    if not any(ch in word for ch in "$`"):
        return double(word)
    first = next(ch for ch in word if ch in "'\\$`")
    out, chunk, single = [], "", first in "$`"
    for ch in word:
        if chunk and (single and ch in "'\\" or not single and ch in "$`"):
            out.append(f"'{chunk}'" if single else double(chunk))
            chunk, single = "", not single
        chunk += ch
    out.append(f"'{chunk}'" if single else double(chunk))
    return "".join(out)


def _codex_join(line: str) -> str:
    return " ".join(_codex_quote(word) for word in (POWERSHELL, "-Command", line))


def test_the_joint_is_codexs():
    """The two shapes the VM's log holds, as it holds them (folders made neutral)."""
    line = "$t = (Resolve-Path -LiteralPath 'a.txt').Path; if ($t -ne 'C:\\p\\a.txt') { throw 'x' }"
    assert _codex_join(line) == (
        '"C:\\\\WINDOWS\\\\System32\\\\WindowsPowerShell\\\\v1.0\\\\powershell.exe" -Command '
        "'$t = (Resolve-Path -LiteralPath '\"'a.txt').Path; if (\"'$t -ne '\"'C:\\\\p\\\\a.txt') "
        "{ throw 'x' }\"")
    assert _codex_join("Select-String 'a' | ForEach-Object { $_.Line }").endswith(
        "-Command \"Select-String 'a' | ForEach-Object { \"'$_.Line }'")


def _lines(tmp_path):
    project = tmp_path / "car"
    (project / "process").mkdir(parents=True, exist_ok=True)
    roots = _read_roots_for(project)
    for kind, line in CORPUS:
        yield kind, _codex_join(line.replace("{project}", str(project))
                                .replace("{skill}", str(roots[1]))), roots


@pytest.mark.parametrize("at", range(len(CORPUS)))
def test_under_auto_every_read_and_every_write_or_delete_in_the_project_passes(at, tmp_path):
    kind, raw, roots = list(_lines(tmp_path))[at]
    shell = codex_session.shell_of(raw)
    assert shell == SHELL_POWERSHELL

    verdict = judge_action("Bash", raw, gate=GATE_AUTO, read_roots=roots, shell=shell)

    assert verdict.allowed and not verdict.unasked, (kind, codex_session.shown_command(raw))
    never = judge_action("Bash", raw, gate=GATE_NEVER, read_roots=roots, shell=shell)
    assert never.allowed and not never.unasked, "nothing `auto` would ask is said under `never`"


@pytest.mark.parametrize("at", [at for at, (kind, _) in enumerate(CORPUS) if kind != READ])
def test_under_writes_the_writes_and_the_deletes_ask(at, tmp_path):
    kind, raw, roots = list(_lines(tmp_path))[at]

    verdict = judge_action("Bash", raw, gate=GATE_WRITES, read_roots=roots,
                           shell=SHELL_POWERSHELL)

    assert not verdict.allowed, kind


def test_the_corpus_holds_reads_writes_and_deletes():
    kinds = [kind for kind, _ in CORPUS]
    assert kinds.count(READ) >= 20 and kinds.count(WRITE) == 2 and kinds.count(DELETE) == 5
