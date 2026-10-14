"""Codex on this machine (`core/codex_cli.py`, W-10 tcc#181 task 4): where it is, its version, its
login and model list, and the argv pieces a Codex session starts with.

Finding runs on fake trees (`find(environ=, home=, windows=)` — the real `find` bound at import,
since `conftest` stands a «none» in for the machine's). The probe runs against the stand-in from
task 1 (`tests/fakes/fake_codex_app_server.py`) behind a `codex` wrapper; no real Codex runs here.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import pytest

from autosound_tcc.core import codex_cli, model_choices, session_routes
from autosound_tcc.core.codex_cli import Found
from autosound_tcc.core.model_choices import Choice

#: The real ones: `conftest` stands in «none» and «no list» for every test.
_REAL_FIND = codex_cli.find
_REAL_ASK_CODEX = model_choices._ask_codex_models

HERE = Path(__file__).parent
FAKE = HERE / "fakes" / "fake_codex_app_server.py"
FIXTURES = HERE / "fixtures" / "codex"
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="a POSIX script stands in for codex")

NATIVE = b"\xcf\xfa\xed\xfe native codex"  # not a script: no `#!`


@pytest.fixture(autouse=True)
def _no_system_folders(monkeypatch):
    """`/opt/homebrew/bin` is this developer's: the trees here are the tests' own."""
    monkeypatch.setattr(codex_cli, "SYSTEM_FOLDERS", ())


def _file(path: Path, data: bytes = NATIVE, mode: int = 0o755) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)
    return path


def _find(tmp_path, *, path="", windows=False, environ=None):
    env = {"PATH": path, **(environ or {})}
    return _REAL_FIND(environ=env, home=tmp_path / "home", windows=windows)


# ---- find: macOS ----------------------------------------------------------------------------


def test_a_codex_on_path_is_found_there(tmp_path):
    binary = _file(tmp_path / "bin" / "codex")
    found = _find(tmp_path, path=str(tmp_path / "bin"))
    assert found == Found(str(binary), codex_cli.SOURCE_PATH)


def test_a_codex_the_dock_path_misses_is_found_in_its_folder(tmp_path):
    """A Dock-started app has no `~/.local/bin` on PATH: the folder is looked in by name."""
    binary = _file(tmp_path / "home" / ".local" / "bin" / "codex")
    found = _find(tmp_path, path=str(tmp_path / "empty"))
    assert found == Found(str(binary), codex_cli.SOURCE_FOLDER)


@POSIX_ONLY
def test_a_node_shim_resolves_to_the_native_codex_beside_its_package(tmp_path):
    """npm's `codex` is a link to `codex.js` — a Dock app has no `node` to run it; the native binary
    the package bundles is what TCC starts."""
    prefix = tmp_path / "home" / ".npm-global"
    package = prefix / "lib" / "node_modules" / "@openai" / "codex"
    script = _file(package / "bin" / "codex.js", b"#!/usr/bin/env node\nimport('x')\n")
    native = _file(package / "node_modules" / "@openai" / "codex-darwin-arm64" / "vendor"
                   / "aarch64-apple-darwin" / "codex" / "codex")
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "codex").symlink_to(script)

    found = _find(tmp_path)

    assert found == Found(str(native), codex_cli.SOURCE_FOLDER, str(prefix / "bin" / "codex"))


@POSIX_ONLY
def test_a_node_shim_with_no_native_codex_is_not_usable(tmp_path):
    _file(tmp_path / "bin" / "codex", b"#!/usr/bin/env node\nrequire('x')\n")
    assert _find(tmp_path, path=str(tmp_path / "bin")) is None


# ---- find: Windows ---------------------------------------------------------------------------


def _npm_tree(root: Path, *, with_exe=True) -> Path:
    npm = root / "Roaming" / "npm"
    _file(npm / "codex.cmd", b'@ECHO off\r\nnode "%~dp0\\node_modules\\@openai\\codex\\bin\\codex.js" %*\r\n')
    _file(npm / "codex.ps1", b"#!/usr/bin/env pwsh\r\n")
    _file(npm / "codex", b"#!/bin/sh\nexec node ...\n")
    if with_exe:
        return _file(npm / "node_modules" / "@openai" / "codex" / "node_modules" / "@openai"
                     / "codex-win32-x64" / "vendor" / "x86_64-pc-windows-msvc" / "codex"
                     / "codex.exe")
    return npm


def test_on_windows_an_npm_cmd_shim_resolves_to_the_bundled_exe(tmp_path):
    """`%APPDATA%\\npm\\codex.cmd` is cmd.exe running node: never spawned. The `codex.exe` its
    package bundles is."""
    exe = _npm_tree(tmp_path)
    appdata = str(tmp_path / "Roaming")

    found = _find(tmp_path, path=f"{tmp_path / 'nothing'};{tmp_path / 'still-nothing'}",
                  windows=True, environ={"APPDATA": appdata})

    assert found is not None and found.path == str(exe)
    assert found.source == codex_cli.SOURCE_FOLDER
    assert found.shim.endswith("codex.cmd")


def test_on_windows_a_shim_with_no_exe_is_not_usable(tmp_path):
    _npm_tree(tmp_path, with_exe=False)
    assert _find(tmp_path, windows=True, environ={"APPDATA": str(tmp_path / "Roaming")}) is None


def test_on_windows_path_is_split_on_semicolons_and_only_an_exe_counts(tmp_path):
    _file(tmp_path / "a" / "codex", b"#!/bin/sh\n")  # git-bash's shim: not on Windows' terms
    exe = _file(tmp_path / "b" / "codex.exe")
    found = _find(tmp_path, path=f"{tmp_path / 'a'};{tmp_path / 'b'}", windows=True)
    assert found == Found(str(exe), codex_cli.SOURCE_PATH)


# ---- find: TCC's own copy, the cache -------------------------------------------------------


def test_tccs_own_copy_is_found_last_where_task_9_puts_it(tmp_path):
    own = codex_cli.tcc_copy_path(home=tmp_path / "home", environ={}, windows=False)
    assert own.parts[-6:] == ("autosound-tcc", "codex", codex_cli.PIN, "codex_cli_bin", "bin",
                              "codex")
    _file(own)
    assert _find(tmp_path) == Found(str(own), codex_cli.SOURCE_TCC)


def test_tccs_own_copy_on_windows_is_under_localappdata(tmp_path):
    local = tmp_path / "Local"
    own = codex_cli.tcc_copy_path(environ={"LOCALAPPDATA": str(local)}, windows=True)
    assert own == local / "autosound-tcc" / "codex" / codex_cli.PIN / "codex_cli_bin" / "bin" / \
        "codex.exe"
    _file(own)
    assert _find(tmp_path, windows=True, environ={"LOCALAPPDATA": str(local)}) == Found(
        str(own), codex_cli.SOURCE_TCC)


def test_a_codex_known_too_old_gives_way_to_tccs_own_copy(tmp_path, monkeypatch):
    """The blocker's advice — install TCC's copy — has to work with an old Codex still on PATH
    (task 9): one whose version was read too old is passed over for TCC's copy, and is still
    what `find` answers when there is nothing else, so the blocker can say «too old»."""
    old = _file(tmp_path / "bin" / "codex")
    found_old = Found(str(old), codex_cli.SOURCE_PATH)
    assert _find(tmp_path, path=str(old.parent)) == found_old
    monkeypatch.setitem(codex_cli._VERSIONS, codex_cli._stamp(found_old), (0, 150, 0))
    assert _find(tmp_path, path=str(old.parent)) == found_old, "nothing else: still said"
    own = _file(codex_cli.tcc_copy_path(home=tmp_path / "home", environ={}, windows=False))
    assert _find(tmp_path, path=str(old.parent)) == Found(str(own), codex_cli.SOURCE_TCC)


@POSIX_ONLY
def test_a_probe_that_reads_a_too_old_codex_asks_tccs_own_copy_instead(tmp_path, monkeypatch):
    old = _says(tmp_path, "codex-cli 0.150.0")
    monkeypatch.setattr(codex_cli, "dock_folders", lambda **_kw: [])
    monkeypatch.setattr(codex_cli, "find", _REAL_FIND)
    home = tmp_path / "home"
    monkeypatch.setattr(codex_cli.Path, "home", lambda: home)
    monkeypatch.setenv("PATH", str(Path(old.path).parent))
    own = codex_cli.tcc_copy_path(home=home, environ={}, windows=False)
    _file(own, f"#!{sys.executable}\nprint('codex-cli {codex_cli.PIN}')\n".encode())
    asked: list[str] = []
    monkeypatch.setattr(codex_cli, "_run_probe", lambda found: asked.append(found.path)
                        or codex_cli.Probe(signed_in=True, asked=True))
    codex_cli.forget()

    said = codex_cli.probe()

    assert asked == [str(own)] and said.signed_in is True
    assert codex_cli.find() == Found(str(own), codex_cli.SOURCE_TCC)
    codex_cli.forget()


def test_the_version_read_is_told_without_running_anything(tmp_path, monkeypatch):
    found = Found(str(_file(tmp_path / "bin" / "codex")), codex_cli.SOURCE_PATH)
    assert codex_cli.known_version(found) is None
    monkeypatch.setitem(codex_cli._VERSIONS, codex_cli._stamp(found), (0, 150, 0))
    assert codex_cli.known_version(found) == (0, 150, 0)


def test_find_is_cached_until_forget(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli, "find", _REAL_FIND)
    monkeypatch.setattr(codex_cli, "dock_folders", lambda **_kw: [])
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    codex_cli.forget()
    assert codex_cli.find() is None
    binary = _file(tmp_path / "bin" / "codex")
    assert codex_cli.find() is None, "cached: no new look until ↻"
    codex_cli.forget()
    assert codex_cli.find() == Found(str(binary), codex_cli.SOURCE_PATH)
    codex_cli.forget()


# ---- version ---------------------------------------------------------------------------------


def _says(tmp_path, line: str, count: Path | None = None) -> Found:
    body = f"#!{sys.executable}\nimport sys\n"
    if count is not None:
        body += f"open({str(count)!r}, 'a').write('x')\n"
    body += f"print({line!r})\n"
    return Found(str(_file(tmp_path / "v" / "codex", body.encode())), codex_cli.SOURCE_PATH)


@POSIX_ONLY
def test_the_version_is_read_once_per_binary(tmp_path):
    count = tmp_path / "count"
    found = _says(tmp_path, "codex-cli 0.163.2", count)
    assert codex_cli.version(found) == (0, 163, 2)
    assert codex_cli.version(found) == (0, 163, 2)
    assert count.read_text() == "x"
    assert not codex_cli.too_old(found)


@POSIX_ONLY
def test_a_codex_older_than_the_minimum_is_not_usable_and_not_asked(tmp_path, monkeypatch):
    found = _says(tmp_path, "codex-cli 0.150.0")
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    monkeypatch.setattr(codex_cli.codex_rpc, "AppServer", None)  # a spawn here would raise

    assert codex_cli.usable() == found, "not read yet: nothing known against it"
    said = codex_cli.probe()

    assert codex_cli.too_old(found) and codex_cli.usable() is None
    assert "0.150.0" in said.why and "0.162.0" in said.why
    assert codex_cli.signed_in() is None


@POSIX_ONLY
def test_an_unknown_version_is_used_with_a_warning(tmp_path, caplog):
    found = _says(tmp_path, "something else")
    with caplog.at_level(logging.WARNING):
        assert codex_cli.version(found) is None
    assert not codex_cli.too_old(found)
    assert "could not be read" in caplog.text


# ---- probe, against the stand-in -----------------------------------------------------------


def _stand_in(tmp_path, monkeypatch, scenario: Path | str) -> Found:
    wrapper = _file(tmp_path / "fake-bin" / "codex", (
        f"#!{sys.executable}\nimport os, sys\n"
        f"os.execv(sys.executable, [sys.executable, {str(FAKE)!r}, *sys.argv[1:]])\n").encode())
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", str(scenario))
    monkeypatch.setenv("FAKE_CODEX_TIMEOUT", "5")
    found = Found(str(wrapper), codex_cli.SOURCE_PATH)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    return found


@POSIX_ONLY
def test_a_signed_out_codex_reads_as_signed_out(tmp_path, monkeypatch):
    _stand_in(tmp_path, monkeypatch, "signed-out")
    assert codex_cli.signed_in() is None, "not asked yet: never a fault"

    said = codex_cli.probe()

    assert said.signed_in is False and codex_cli.signed_in() is False
    assert said.models == () and said.why, "no list — and why"


def _frame(direction, msg):
    return json.dumps({"dir": direction, "t": 0.0, "msg": msg})


@POSIX_ONLY
def test_every_page_of_the_model_list_is_read_in_one_app_server(tmp_path, monkeypatch):
    m1 = {"id": "gpt-a", "model": "gpt-a", "displayName": "GPT-A", "supportedReasoningEfforts": [
        {"reasoningEffort": "high"}, {"reasoningEffort": "xhigh"}]}
    m2 = {"id": "gpt-b", "model": "gpt-b", "displayName": "GPT-B"}
    hidden = {"id": "old", "model": "old", "hidden": True}
    scenario = tmp_path / "paged.jsonl"
    scenario.write_text("\n".join([
        _frame("out", {"id": 1, "method": "initialize"}),
        _frame("in", {"id": 1, "result": {}}),
        _frame("out", {"method": "initialized"}),
        _frame("out", {"id": 2, "method": "account/read"}),
        _frame("in", {"id": 2, "result": {"account": {"type": "chatgpt"}, "requiresOpenaiAuth": True}}),
        _frame("out", {"id": 3, "method": "model/list"}),
        _frame("in", {"id": 3, "result": {"data": [m1, hidden], "nextCursor": "p2"}}),
        _frame("out", {"id": 4, "method": "model/list"}),
        _frame("in", {"id": 4, "result": {"data": [m2], "nextCursor": None}}),
    ]) + "\n", encoding="utf-8")
    _stand_in(tmp_path, monkeypatch, scenario)

    said = codex_cli.probe()

    assert said.signed_in is True and said.why == ""
    assert [m["model"] for m in said.models] == ["gpt-a", "gpt-b"]
    assert codex_cli.supported_efforts("gpt-a") == ("high", "xhigh")
    assert codex_cli.probe() is said, "once, until ↻"


def test_the_picker_rows_come_from_the_probe_and_a_failed_one_says_why(monkeypatch):
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "codex")
    monkeypatch.setattr(codex_cli, "probe", lambda **_kw: codex_cli.Probe(
        signed_in=True, asked=True, models=({"model": "gpt-a", "displayName": "GPT-A"},)))
    assert [(c.key, c.label) for c in _REAL_ASK_CODEX()] == [("codex:gpt-a", "GPT-A")]
    assert model_choices._LIST_WHY["codex"] == ""

    monkeypatch.setattr(codex_cli, "probe", lambda **_kw: codex_cli.Probe(
        asked=True, why="codex app-server: boom"))
    assert _REAL_ASK_CODEX() == []
    assert model_choices._LIST_WHY["codex"] == "codex app-server: boom"


def test_after_an_install_or_a_sign_in_the_rows_come_from_the_probe_just_run(monkeypatch):
    """Task 9: the worker that installed or signed Codex in has just probed; the pickers' rows are
    built from that answer, with no second app-server."""
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "codex")
    monkeypatch.setattr(model_choices, "_save_cached_catalogue", lambda: None)
    monkeypatch.setattr(model_choices, "_CLI_CACHE", {})
    monkeypatch.setattr(codex_cli, "probe", None)  # a spawn here would raise
    monkeypatch.setattr(codex_cli, "_PROBE", codex_cli.Probe(
        signed_in=True, asked=True, models=({"model": "gpt-a", "displayName": "GPT-A"},)))

    model_choices.store_codex_rows()

    assert [c.key for c in model_choices._CLI_CACHE["codex"]] == ["codex:gpt-a"]


# ---- picker and launch -----------------------------------------------------------------------


def test_codex_rows_are_offered_once_to_the_generator_and_the_reviewer(monkeypatch):
    monkeypatch.setattr(model_choices, "_CLI_CACHE", {"codex": [
        Choice(harness="codex", model="gpt-a", label="GPT-A", provider="openai")]})
    generator = model_choices.choices([])
    reviewer = model_choices.critic_choices([])
    assert "codex:gpt-a" in [c.key for c in generator]
    keys = [c.key for c in reviewer]
    assert len(keys) == len(set(keys)), "no row twice"
    assert keys.count("codex:gpt-a") == 1


def test_a_codex_pick_is_not_refused_at_launch_now_that_it_has_its_session(tmp_path, monkeypatch):
    """Task 6 lifted the «not yet» refusal; a Codex found, not known too old and not known signed
    out starts (its own blockers, task 9: `test_codex_menu`)."""
    found = Found(str(_file(tmp_path / "bin" / "codex")), codex_cli.SOURCE_PATH)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    pick = Choice(harness="codex", model="gpt-a", label="GPT-A", provider="openai")
    assert session_routes.blocker(pick, server=object()) is None


@pytest.mark.parametrize("level, supported, sent", [
    ("high", ("low", "high", "xhigh", "max"), "high"),
    ("xhigh", ("high", "xhigh"), "xhigh"),
    ("xhigh", ("low", "high"), "high"),
    ("max", ("high", "xhigh", "max"), "max"),
    ("max", ("high", "xhigh"), "xhigh"),
    ("max", ("high",), "high"),
    ("max", (), "high"),
])
def test_tccs_effort_is_clamped_to_what_the_model_takes(level, supported, sent):
    assert model_choices.codex_effort(level, supported) == sent


# ---- argv pieces -----------------------------------------------------------------------------


def _config_read() -> dict:
    for line in (FIXTURES / "config-skills.jsonl").read_text(encoding="utf-8").splitlines():
        msg = json.loads(line).get("msg") or {}
        if "result" in msg and "config" in (msg.get("result") or {}):
            return msg["result"]
    raise AssertionError("no config/read answer in the fixture")


def _pairs(args: list[str]) -> list[str]:
    assert args[::2] == ["-c"] * (len(args) // 2)
    return args[1::2]


def test_isolation_turns_off_only_the_servers_the_config_has():
    """A `-c mcp_servers.<name>.enabled=false` for a server that is not there kills the start
    (task 1): only names `config/read` lists."""
    pairs = _pairs(codex_cli.isolation_args(_config_read()))
    servers = sorted(p for p in pairs if p.startswith("mcp_servers."))
    assert servers == ["mcp_servers.computer-use.enabled=false",
                       "mcp_servers.home-assistant.enabled=false",
                       "mcp_servers.node_repl.enabled=false"]
    for feature in codex_cli.OFF_FEATURES:
        assert f"features.{feature}=false" in pairs
    assert "features.remote_plugin=false" in pairs
    for fixed in ("notify=[]", "project_doc_max_bytes=0", "skills.bundled.enabled=false",
                  'shell_environment_policy.exclude=["TCC_MCP_TOKEN"]'):
        assert fixed in pairs


def test_a_server_name_minus_c_cannot_carry_is_left_out_and_named():
    config = {"config": {"mcp_servers": {"tcc": {}, "fine_one": {}, "my server": {},
                                         "a.b": {}}}}
    pairs = _pairs(codex_cli.isolation_args(config))
    assert [p for p in pairs if p.startswith("mcp_servers.")] == ["mcp_servers.fine_one.enabled=false"]
    assert codex_cli.unsafe_server_names(config) == ["my server", "a.b"]


def test_every_feature_the_recording_shows_enabled_is_on_a_list():
    """A new default-on Codex feature would leak into TCC's sessions: the test fails when a
    re-recorded `config/read` shows one on neither list."""
    assert codex_cli.unknown_enabled_features(_config_read()) == []
    assert set(codex_cli.HARMLESS_FEATURES) == {"api_key_model_discovery", "auth_elicitation",
                                                "mentions_v2"}
    assert codex_cli.unknown_enabled_features(
        {"config": {"features": {"mentions_v2": True, "new_thing": True, "off": False}}}) == ["new_thing"]


def test_tccs_tools_go_in_by_url_with_the_token_named_never_written():
    args = codex_cli.tcc_tool_args("http://127.0.0.1:8765/mcp", timeout_sec=1900)
    pairs = _pairs(args)
    assert pairs == [
        'mcp_servers.tcc.url="http://127.0.0.1:8765/mcp"',
        'mcp_servers.tcc.env_http_headers={"X-TCC-Token"="TCC_MCP_TOKEN"}',
        "mcp_servers.tcc.tool_timeout_sec=1900",
        'mcp_servers.tcc.default_tools_approval_mode="approve"',
    ]


# ---- availability and the reviewer ---------------------------------------------------------


def test_a_signed_out_codex_asks_to_sign_in_and_an_unknown_login_says_nothing(monkeypatch):
    from autosound_tcc.core import availability

    row = Choice(harness="codex", model="gpt-a", label="GPT-A", provider="openai")
    fine = dict(unconfirmed=lambda _c: False)
    assert availability.status(row, **fine).ready, "not probed: never a fault"
    monkeypatch.setattr(codex_cli, "_PROBE", codex_cli.Probe(signed_in=False, asked=True))
    assert availability.status(row, **fine).reason == availability.SIGN_IN
    sdk = Choice(harness="sdk", model="claude-opus-5", label="x")
    assert availability.status(sdk, signed_in=lambda: True, **fine).ready, "Codex's login only"


def test_the_reviewer_finds_the_codex_tcc_found_by_its_folder_on_path(monkeypatch, tmp_path):
    """TCC's own copy is on no PATH: the method's search for `codex` finds it through the folder
    TCC puts first."""
    from autosound_tcc.core import critic

    own = tmp_path / "codex" / "codex_cli_bin" / "bin" / "codex"
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: Found(str(own), codex_cli.SOURCE_TCC))
    env = critic.critic_bin_override(harness="codex", environ={"PATH": os.pathsep.join(
        ["/usr/bin", str(own.parent)])})
    assert env["AUTOSOUND_CRITIC_BIN"] == "codex"
    assert env["PATH"].split(os.pathsep) == [str(own.parent), "/usr/bin"]

    monkeypatch.setattr(codex_cli, "find", lambda **_kw: None)
    assert critic.critic_bin_override(harness="codex", environ={"PATH": "/usr/bin"}) == {}
