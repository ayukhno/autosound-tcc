"""Codex in the user's own terminal with TCC's tools (`core/codex_terminal.py`, W-10 Codex task 8).

The line the terminal runs is `python -m autosound_tcc.core.codex_terminal <project> [--model M]`.
It reads TCC's url and token from the project's `.mcp.json`, hands the token to Codex in the
environment only, and starts Codex with TCC's connection pieces — nothing of the session's own
switches: in a terminal the user's Codex config rules approvals and extras (the Arbiter, 2026-10-14).
No real Codex runs here: `find`, `version` and the exec are stood in.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from autosound_tcc.core import codex_cli, codex_terminal
from autosound_tcc.core.codex_cli import Found
from autosound_tcc.ui.tcc.strings import codex as codex_strings

#: The real `find`: `conftest` stands a «none» in for the machine's.
_REAL_FIND = codex_cli.find

TOKEN = "s3cret-token-0123456789"
URL = "http://127.0.0.1:8765/mcp"
BINARY = "/opt/codex/bin/codex"


def _write_config(project: Path, entry=None, *, raw: str | None = None) -> None:
    path = project / ".mcp.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
        return
    servers = {"other": {"type": "stdio", "command": "x"}}
    if entry is not False:
        servers["tcc"] = entry or {"type": "http", "url": URL, "headers": {"X-TCC-Token": TOKEN}}
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


@pytest.fixture
def started(monkeypatch):
    """What the module would have started: (argv, env, cwd), recorded instead of run."""
    calls: list[tuple[list[str], dict, str]] = []

    def record(argv, env, cwd):
        calls.append((list(argv), dict(env), str(cwd)))
        return 0

    monkeypatch.setattr(codex_terminal, "_start", record)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: Found(BINARY, codex_cli.SOURCE_PATH))
    monkeypatch.setattr(codex_cli, "version", lambda found: (0, 162, 1))
    monkeypatch.setattr(codex_cli, "too_old", lambda found: False)
    return calls


def _pairs(argv: list[str]) -> list[str]:
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == "-c"]


def test_the_token_rides_in_the_environment_never_in_argv(tmp_path, started):
    _write_config(tmp_path)

    assert codex_terminal.main([str(tmp_path)]) == 0

    ((argv, env, cwd),) = started
    assert argv[0] == BINARY, "the native binary, never a shim"
    assert all(TOKEN not in arg for arg in argv)
    assert env[codex_cli.TOKEN_ENV] == TOKEN
    assert cwd == str(tmp_path)
    pairs = _pairs(argv)
    assert f'mcp_servers.tcc.url="{URL}"' in pairs
    assert f'mcp_servers.tcc.env_http_headers={{"X-TCC-Token"="{codex_cli.TOKEN_ENV}"}}' in pairs
    assert any(p.startswith("mcp_servers.tcc.tool_timeout_sec=") for p in pairs)


def test_none_of_the_sessions_own_switches_reach_the_terminal(tmp_path, started):
    """Approvals and the user's extras are the user's own config's in a terminal."""
    _write_config(tmp_path)

    codex_terminal.main([str(tmp_path)])

    ((argv, _env, _cwd),) = started
    pairs = _pairs(argv)
    assert not any("default_tools_approval_mode" in p for p in pairs)
    isolation = set(_pairs(codex_cli.isolation_args({})))
    assert not isolation & set(pairs)
    assert len(pairs) == 3, pairs


def test_the_model_passes_through_as_codex_s_own_flag(tmp_path, started):
    _write_config(tmp_path)

    codex_terminal.main([str(tmp_path), "--model", "gpt-5.6-luna"])

    ((argv, _env, _cwd),) = started
    assert argv[argv.index("--model") + 1] == "gpt-5.6-luna"


def test_no_model_means_codex_keeps_its_own(tmp_path, started):
    _write_config(tmp_path)

    codex_terminal.main([str(tmp_path)])

    ((argv, _env, _cwd),) = started
    assert "--model" not in argv and "-m" not in argv


def test_the_terminal_and_the_session_build_the_connection_in_one_place():
    """The session keeps exactly what it passed; the terminal takes the connection part of it."""
    session = codex_cli.tcc_tool_args(URL, timeout_sec=1900)
    terminal = codex_cli.tcc_connection_args(URL, timeout_sec=1900)

    assert set(_pairs(session)) - set(_pairs(terminal)) == {
        'mcp_servers.tcc.default_tools_approval_mode="approve"'}
    assert set(_pairs(terminal)) < set(_pairs(session))


@pytest.mark.parametrize("case", ["no-file", "unreadable-json", "no-entry", "no-token", "no-url"])
def test_a_project_without_tcc_s_connection_is_one_sentence_and_a_failure(
        tmp_path, started, capsys, case):
    if case == "unreadable-json":
        _write_config(tmp_path, raw="{ not json")
    elif case == "no-entry":
        _write_config(tmp_path, False)
    elif case == "no-token":
        _write_config(tmp_path, {"type": "http", "url": URL, "headers": {}})
    elif case == "no-url":
        _write_config(tmp_path, {"type": "http", "headers": {"X-TCC-Token": TOKEN}})

    assert codex_terminal.main([str(tmp_path)]) != 0

    assert started == []
    said = capsys.readouterr()
    assert said.out == ""
    assert said.err.strip() and said.err.count("\n") == 1, said.err
    assert TOKEN not in said.err


def test_codex_not_found_is_one_sentence_and_a_failure(tmp_path, started, monkeypatch, capsys):
    _write_config(tmp_path)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: None)

    assert codex_terminal.main([str(tmp_path)]) != 0

    assert started == []
    err = capsys.readouterr().err
    assert "Codex" in err and "npm" not in err
    assert codex_strings.STRINGS["codexInstall"]["en"] in err, "names TCC's menu line"


def test_codex_too_old_is_one_sentence_and_a_failure(tmp_path, started, monkeypatch, capsys):
    _write_config(tmp_path)
    monkeypatch.setattr(codex_cli, "version", lambda found: (0, 100, 0))
    monkeypatch.setattr(codex_cli, "too_old", lambda found: True)

    assert codex_terminal.main([str(tmp_path)]) != 0

    assert started == []
    err = capsys.readouterr().err
    assert "0.100.0" in err and "0.162.0" in err


def test_a_failure_waits_for_enter_when_a_person_is_there(tmp_path, started, monkeypatch, capsys):
    """`exec` handed the terminal to this process: when it ends, a window that closes on exit
    would take the sentence with it."""
    waited = []
    monkeypatch.setattr(codex_terminal, "_person_is_there", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": waited.append(prompt) or "")

    assert codex_terminal.main([str(tmp_path)]) != 0

    assert len(waited) == 1


def test_posix_replaces_the_process_with_codex(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(codex_terminal.sys, "platform", "darwin")
    monkeypatch.setattr(codex_terminal.os, "chdir", lambda path: seen.update(cwd=str(path)))
    monkeypatch.setattr(codex_terminal.os, "execve",
                        lambda path, argv, env: seen.update(path=path, argv=argv, env=env))

    codex_terminal._start([BINARY, "-c", "x=1"], {"A": "1"}, tmp_path)

    assert seen == {"cwd": str(tmp_path), "path": BINARY, "argv": [BINARY, "-c", "x=1"],
                    "env": {"A": "1"}}


def test_windows_runs_codex_in_this_console_and_returns_its_code(monkeypatch, tmp_path):
    """`os.execv` does not replace the process on Windows: the child runs here, with this
    console's stdio, and its code is the exit code."""
    seen = {}

    class _Proc:
        def __init__(self, argv, **kw):
            seen.update(argv=argv, **kw)

        def wait(self):
            return 7

    monkeypatch.setattr(codex_terminal.sys, "platform", "win32")
    monkeypatch.setattr(codex_terminal.subprocess, "Popen", _Proc)

    assert codex_terminal._start([BINARY], {"A": "1"}, tmp_path) == 7

    assert seen["argv"] == [BINARY] and seen["env"] == {"A": "1"} and seen["cwd"] == str(tmp_path)
    assert "creationflags" not in seen, "no new console: the terminal is already one"
    assert "stdout" not in seen and "stdin" not in seen


@pytest.mark.skipif(os.name == "nt", reason="POSIX scripts stand in for codex")
def test_an_old_codex_on_path_gives_way_to_tccs_installed_copy(tmp_path, monkeypatch):
    """The review's I1: the terminal is a process of its own with no versions read yet, so an old
    `codex` on PATH came first, and the refusal sent the person to «Install Codex» — greyed in
    TCC, since its copy is installed. Read too old, it is passed over as the probe passes it."""
    import sys

    def script(path: Path, says: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!{sys.executable}\nprint('codex-cli {says}')\n")
        path.chmod(0o755)
        return path

    _write_config(tmp_path)
    old = script(tmp_path / "old-bin" / "codex", "0.100.0")
    home = tmp_path / "home"
    own = script(codex_cli.tcc_copy_path(home=home, environ={}, windows=False), codex_cli.PIN)
    monkeypatch.setattr(codex_cli, "find", _REAL_FIND)
    monkeypatch.setattr(codex_cli, "SYSTEM_FOLDERS", ())
    monkeypatch.setattr(codex_cli, "dock_folders", lambda **_kw: [])
    monkeypatch.setattr(codex_cli.Path, "home", lambda: home)
    monkeypatch.setenv("PATH", str(old.parent))
    codex_cli.forget()
    calls: list[list[str]] = []
    monkeypatch.setattr(codex_terminal, "_start", lambda argv, env, cwd: calls.append(argv) or 0)

    assert codex_terminal.main([str(tmp_path)]) == 0

    assert calls and calls[0][0] == str(own)
    codex_cli.forget()
