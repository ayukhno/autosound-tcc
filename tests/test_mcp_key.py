"""The MCP server's key stays one per project across restarts (#247).

A new `X-TCC-Token` per start left the terminal's Claude Code session holding the old one: «Dynamic
Client Registration rejected (HTTP 401)» until `/mcp` → reconnect. The key now lives in the project's
git-ignored `.tcc/mcp-token`. It is a secret on disk, so these tests look at what lands in the file,
what git would take, and what the server answers — never at how long anything took.

No `QWidget` here: the strip and the window's host are stand-ins, so nothing can open on a screen.
"""

from __future__ import annotations

import errno
import http.client
import importlib
import json
import logging
import os
import socket
import stat
import subprocess
import threading
import tracemalloc
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from autosound_tcc.core import app_log, config, mcp_key, mcp_server, own_store, vendor_loader
from autosound_tcc.core.mcp_server import TccMcpServer
from autosound_tcc.ui.tcc import i18n, mcp_view, menu_registry
from tests.test_project_seed import _source

_POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
_NOT_ROOT = pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0,
                               reason="root reads and writes past a file's mode")
_DAMAGED = [b"", b"\n\n", b"too-short", b"\xff\xfe\x00garbage-that-is-not-text-at-all!!",
            b"a key with spaces in it, which no header could carry"]
_DAMAGED_IDS = ["empty", "blank", "half-a-key", "not-text", "not-a-key"]


@pytest.fixture
def folder(tmp_path, monkeypatch) -> Path:
    project = tmp_path / "car"
    project.mkdir()
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(project))
    return project


def _key_file(project: Path) -> Path:
    return project / ".tcc" / "mcp-token"


def _spare_port() -> int:
    """A port nothing holds: tests running side by side must not scan from one fixed base."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _server(project: Path) -> TccMcpServer:
    return TccMcpServer(project_dir=project, preferred_port=_spare_port())


def _answer(server: TccMcpServer, token) -> int:
    """What the server says to a request carrying `token` (None: no header at all)."""
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token is not None:
        headers["X-TCC-Token"] = token
    request = urllib.request.Request(server.url, data=b"{}", method="POST", headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _advertised(project: Path):
    return json.loads((project / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"].get("tcc")


def _git(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True,
                          check=False)


@pytest.fixture
def repo(folder, tmp_path, monkeypatch) -> Path:
    """A real repository in `folder`, which this machine's own git settings cannot speak for: a
    global excludes file naming `.tcc/` would make a project git does not ignore look ignored."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global-gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-xdg"))
    assert _git(folder, "init", "-q").returncode == 0
    return folder


# ---- one key per project, across restarts ----


def test_two_starts_on_one_folder_have_one_key_and_it_is_in_the_file(folder):
    first = TccMcpServer(project_dir=folder)
    second = TccMcpServer(project_dir=folder)

    assert first.token == second.token
    assert _key_file(folder).read_text(encoding="utf-8").strip() == first.token


def test_another_folder_has_another_key(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()

    a, b = TccMcpServer(project_dir=tmp_path / "a"), TccMcpServer(project_dir=tmp_path / "b")

    assert a.token != b.token
    assert _key_file(tmp_path / "a").read_text(encoding="utf-8").strip() == a.token
    assert _key_file(tmp_path / "b").read_text(encoding="utf-8").strip() == b.token


def test_a_session_s_key_still_opens_the_restarted_server_and_nothing_else_does(folder):
    """The defect itself, as the terminal's session meets it, and `_TokenGuard` over real HTTP."""
    before = _server(folder)
    before.start()
    held_by_the_session = before.token
    before.stop()

    after = _server(folder)
    after.start()
    try:
        assert _answer(after, held_by_the_session) != 401, "the session's key was refused"
        assert _answer(after, None) == 401, "no key at all was let through"
        assert _answer(after, "not-" + held_by_the_session) == 401, "a wrong key was let through"
        assert _answer(after, "") == 401, "an empty key was let through"
    finally:
        after.stop()


@pytest.mark.parametrize("value", [b"\xff\xfe not ascii", "тест".encode("utf-8")],
                         ids=["latin1", "utf8"])
def test_a_key_header_that_is_not_ascii_is_refused_not_a_crash(folder, value):
    server = _server(folder)
    server.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=20)
        try:
            connection.putrequest("POST", "/mcp")
            connection.putheader("X-TCC-Token", value)
            connection.putheader("Content-Length", "2")
            connection.endheaders(b"{}")
            assert connection.getresponse().status == 401
        finally:
            connection.close()
        assert _answer(server, server.token) != 401, "and the right key still opens it"
    finally:
        server.stop()


# ---- an explicit reset ----


def test_a_reset_locks_out_the_old_key_and_advertises_the_new_one(folder):
    server = _server(folder)
    server.start()
    try:
        old = server.token

        server.reset_token()

        assert server.token != old and server.key_note == "reset"
        assert _answer(server, old) == 401, "a reset must invalidate what a running session holds"
        assert _answer(server, server.token) != 401
        assert _key_file(folder).read_text(encoding="utf-8").strip() == server.token
        assert _advertised(folder)["headers"]["X-TCC-Token"] == server.token
    finally:
        server.stop()
    assert TccMcpServer(project_dir=folder).token == server.token, "and the next start keeps it"


def test_a_reset_that_cannot_be_saved_still_changes_the_key_and_says_so(folder):
    server = _server(folder)
    server.start()
    try:
        old = server.token
        _key_file(folder).unlink()
        _key_file(folder).mkdir()  # nothing can be renamed over a folder

        server.reset_token()

        assert server.token != old and server.key_note == "run_only" and server.key_problem
        assert _answer(server, old) == 401 and _answer(server, server.token) != 401
    finally:
        server.stop()


# ---- never committed, never carried ----


def test_the_key_is_ignored_by_git_before_it_is_written(folder, monkeypatch):
    """Looked at the moment the file lands: `git status` a second later cannot tell the order."""
    assert _git(folder, "init", "-q").returncode == 0
    (folder / ".gitignore").write_text("*.log\n", encoding="utf-8")
    landed: list[bool] = []

    def watching(real):
        def call(src, dst, **kwargs):
            if Path(dst) == _key_file(folder):
                landed.append(_git(folder, "check-ignore", "-q", ".tcc/mcp-token").returncode == 0)
            real(src, dst, **kwargs)
        return call

    monkeypatch.setattr(os, "link", watching(os.link))  # a first key lands by a link
    monkeypatch.setattr(os, "replace", watching(os.replace))  # a later one by a rename

    TccMcpServer(project_dir=folder)

    assert landed == [True]
    assert "*.log" in (folder / ".gitignore").read_text(encoding="utf-8"), "the user's lines stay"


@pytest.mark.parametrize("broken", ["a-folder", "not-text"])
def test_no_key_is_written_where_git_could_not_be_told(folder, broken):
    """A `.gitignore` TCC cannot read or add to leaves `.tcc/` open to `git add -A`: nothing goes
    on disk, the server still has a key, and the reason is there to say."""
    gitignore = folder / ".gitignore"
    if broken == "a-folder":
        gitignore.mkdir()
    else:
        gitignore.write_bytes(b"\xff\xfe not utf-8\n")

    server = TccMcpServer(project_dir=folder)

    assert not _key_file(folder).exists()
    assert server.token and server.key_note == "run_only" and ".gitignore" in server.key_problem


def test_a_temp_file_left_by_a_kill_is_ignored_too(repo):
    """`.mcp.json` is written through `.mcp-XXXX.tmp` in the project's root: killed between the
    write and the rename, that file holds the key, and only `.tcc/` and `.mcp.json` were named."""
    TccMcpServer(project_dir=repo)

    assert _git(repo, "check-ignore", "-q", ".mcp-abc123.tmp").returncode == 0


def test_the_method_s_git_init_does_not_take_the_key(folder):
    """`project_repo.init` is `git add -A` on the folder (TCC's Git backup, and a seed's last act),
    and it leaves an existing `.gitignore` alone, so `.tcc/` must have been added to it already."""
    if not vendor_loader.is_available():
        pytest.skip("the vendored skill is not checked out")
    (folder / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (folder / "project.json").write_text("{}\n", encoding="utf-8")
    TccMcpServer(project_dir=folder)
    assert _key_file(folder).is_file()
    vendor_loader.load_project_seed()  # puts `rew_tool/` on `sys.path`
    repo = importlib.import_module("project_repo")

    ok, said = repo.init(str(folder))

    tracked = _git(folder, "ls-files").stdout.splitlines()
    assert ok and "project.json" in tracked, said
    assert not [path for path in tracked if path.startswith(".tcc/")], tracked


def test_a_seeded_project_does_not_inherit_the_key(tmp_path):
    try:
        seeder = vendor_loader.load_project_seed()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"the skill's project_seed is not in this checkout: {exc}")
    source = _source(tmp_path / "source")
    key = TccMcpServer(project_dir=source).token
    assert _key_file(source).is_file()
    target = tmp_path / "copy"

    seeder.seed(source, target)

    assert not _key_file(target).exists()
    assert not [p for p in target.rglob("*") if p.is_file() and key.encode() in p.read_bytes()]


# ---- the file's mode ----


@_POSIX_ONLY
def test_the_file_is_the_owner_s_alone(folder):
    TccMcpServer(project_dir=folder)

    assert stat.S_IMODE(_key_file(folder).stat().st_mode) == 0o600


@_POSIX_ONLY
def test_a_reset_file_is_the_owner_s_alone(folder):
    server = TccMcpServer(project_dir=folder)
    os.chmod(_key_file(folder), 0o644)

    server.reset_token()

    assert stat.S_IMODE(_key_file(folder).stat().st_mode) == 0o600


@_POSIX_ONLY
def test_a_file_others_can_read_is_closed_and_its_key_kept(folder):
    key = TccMcpServer(project_dir=folder).token
    os.chmod(_key_file(folder), 0o644)

    again = TccMcpServer(project_dir=folder)

    assert again.token == key and again.key_note == ""
    assert stat.S_IMODE(_key_file(folder).stat().st_mode) == 0o600


# ---- a key that cannot be had: TCC starts, with a guard, and says so ----


@pytest.mark.parametrize("damage", _DAMAGED, ids=_DAMAGED_IDS)
def test_a_damaged_file_gets_a_fresh_key_that_then_stays(folder, damage):
    key_file = _key_file(folder)
    key_file.parent.mkdir()
    key_file.write_bytes(damage)

    server = TccMcpServer(project_dir=folder)

    assert server.key_note == "replaced"
    assert len(server.token) >= 32 and server.token.encode() not in damage
    assert key_file.read_text(encoding="utf-8").strip() == server.token
    assert TccMcpServer(project_dir=folder).token == server.token


def test_a_folder_where_the_file_should_be_is_left_and_the_server_is_guarded(folder):
    """`read` refused: the bytes may be good, so nothing is written over them, and TCC starts."""
    _key_file(folder).mkdir(parents=True)

    server = _server(folder)
    server.start()
    try:
        assert server.key_note == "run_only" and "mcp-token" in server.key_problem
        assert _key_file(folder).is_dir()
        assert _answer(server, None) == 401 and _answer(server, server.token) != 401
    finally:
        server.stop()


@_NOT_ROOT
def test_an_unreadable_file_is_not_written_over(folder):
    key = TccMcpServer(project_dir=folder).token
    os.chmod(_key_file(folder), 0)
    try:
        server = TccMcpServer(project_dir=folder)

        assert server.key_note == "run_only" and server.token != key
    finally:
        os.chmod(_key_file(folder), 0o600)
    assert _key_file(folder).read_text(encoding="utf-8").strip() == key


@_NOT_ROOT
def test_a_read_only_folder_still_gets_a_guarded_server(folder):
    os.chmod(folder, 0o500)
    server = _server(folder)
    try:
        server.start()
        assert server.key_note == "run_only" and server.key_problem
        assert server.serving and server.config_error, "the advert failed, the server did not"
        assert _answer(server, None) == 401 and _answer(server, server.token) != 401
    finally:
        server.stop()
        os.chmod(folder, 0o700)
    assert not _key_file(folder).exists()


# ---- only a plain file, TCC's own, in TCC's own folder ----


_A_KEY = "k" * 40


def _elsewhere(tmp_path: Path) -> Path:
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "mcp-token").write_text(_A_KEY + "\n", encoding="utf-8")
    return other


@_POSIX_ONLY
@pytest.mark.parametrize("act", [mcp_key.load, mcp_key.reset], ids=["load", "reset"])
def test_a_tcc_folder_that_is_a_link_is_neither_read_nor_written_through(folder, tmp_path, act):
    """Whoever can plant the link would have read the key from, or put it into, a folder of theirs."""
    other = _elsewhere(tmp_path)
    (folder / ".tcc").symlink_to(other, target_is_directory=True)

    key = act(folder)

    assert key.note == "run_only" and key.token != _A_KEY and key.problem
    assert sorted(p.name for p in other.iterdir()) == ["mcp-token"]
    assert (other / "mcp-token").read_text(encoding="utf-8").strip() == _A_KEY


@_POSIX_ONLY
def test_a_key_file_that_is_a_link_is_not_followed_and_its_target_keeps_its_mode(folder, tmp_path):
    other = _elsewhere(tmp_path)
    os.chmod(other / "mcp-token", 0o644)
    _key_file(folder).parent.mkdir()
    _key_file(folder).symlink_to(other / "mcp-token")

    key = mcp_key.load(folder)

    assert key.note == "run_only" and key.token != _A_KEY
    assert _key_file(folder).is_symlink(), "left where it is"
    assert stat.S_IMODE((other / "mcp-token").stat().st_mode) == 0o644, "chmod followed the link"


@_POSIX_ONLY
def test_a_link_to_a_device_is_not_read_and_not_replaced(folder):
    _key_file(folder).parent.mkdir()
    _key_file(folder).symlink_to(os.devnull)

    key = mcp_key.load(folder)

    assert key.note == "run_only" and _key_file(folder).is_symlink()


@_POSIX_ONLY
def test_a_fifo_where_the_key_should_be_does_not_hang_the_start(folder):
    """This runs on the GUI thread: a plain `open` of a FIFO waits for a writer that never comes."""
    _key_file(folder).parent.mkdir()
    os.mkfifo(_key_file(folder))
    got: list = []
    reader = threading.Thread(target=lambda: got.append(mcp_key.load(folder)), daemon=True)
    reader.start()
    reader.join(20)
    if reader.is_alive():  # lets a thread stuck on the FIFO go; the test has already failed
        os.close(os.open(_key_file(folder), os.O_RDWR | os.O_NONBLOCK))
    assert got and got[0].note == "run_only", "the start hung on a FIFO"
    assert stat.S_ISFIFO(_key_file(folder).lstat().st_mode), "left where it is"


def test_an_enormous_file_is_not_read_whole(folder):
    """Sparse, so the test costs no disk: what is measured is what the read took into memory."""
    _key_file(folder).parent.mkdir()
    with open(_key_file(folder), "wb") as fh:
        fh.truncate(64 * 1024 * 1024)
    tracemalloc.start()
    try:
        key = mcp_key.load(folder)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < 1024 * 1024, f"read {peak} bytes into memory"
    assert key.note == "replaced", "a file that big is not a key"


@pytest.mark.parametrize("dies_in", ["fsync", "replace"])
def test_a_write_that_dies_halfway_leaves_the_old_key_whole(folder, monkeypatch, dies_in):
    server = TccMcpServer(project_dir=folder)
    key = server.token

    def dead(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(own_store.os, dies_in, dead)
    server.reset_token()
    monkeypatch.undo()

    assert _key_file(folder).read_text(encoding="utf-8").strip() == key
    assert [p.name for p in _key_file(folder).parent.iterdir() if p.name != "mcp-token"
            and p.name.endswith(".tmp")] == [], "no half-written temp stays behind"
    assert server.token != key and server.key_note == "run_only"


def test_a_project_with_no_chosen_folder_gets_a_key_and_no_file(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOSOUND_PROJECT_DIR", raising=False)
    monkeypatch.setattr(config, "_settings", lambda: SimpleNamespace(value=lambda *_a, **_k: ""))
    monkeypatch.setattr(config, "DEFAULT_STATE_ROOT", tmp_path / "nobody-chose-this")

    server = TccMcpServer()

    assert server.token and server.key_note == "no_folder"
    assert not list(tmp_path.rglob("mcp-token"))


# ---- two TCCs on one folder share a key, and are told apart by port ----


def test_two_tccs_share_a_key_and_one_quit_leaves_the_other_s_entry(folder):
    a, b = _server(folder), _server(folder)
    try:
        a.start()
        b.start()
        assert a.token == b.token and a.port != b.port

        a.stop()

        assert _advertised(folder)["url"] == b.url, "A's quit took B's advertisement"

        never_served = TccMcpServer(project_dir=folder)
        never_served.stop()
        assert _advertised(folder)["url"] == b.url, "one that never served has nothing to withdraw"

        a.stop()  # a second stop has nothing left to withdraw either
        assert _advertised(folder)["url"] == b.url
    finally:
        a.stop()
        b.stop()
    assert _advertised(folder) is None, "and B's own stop takes it"


def _died(server: TccMcpServer) -> None:
    """The serving thread is gone, as after a crash: `stop()` has not been called."""
    server._server.should_exit = True
    server._thread.join(20)
    assert server.stopped_reason


def test_a_server_that_died_leaves_the_entry_of_whoever_took_its_port(folder):
    """A's server is dead, B took the port: an entry naming that port is B's, and a leftover entry
    of A's own is the lesser harm."""
    a = _server(folder)
    a.start()
    _died(a)
    mcp_server.write_mcp_config(folder, a.port, "b-" * 20)

    a.stop()

    entry = _advertised(folder)
    assert entry and entry["headers"]["X-TCC-Token"] == "b-" * 20, "A's quit took B's entry"


def test_a_reset_on_a_dead_server_does_not_write_over_whoever_took_its_port(folder):
    a = _server(folder)
    a.start()
    try:
        _died(a)
        mcp_server.write_mcp_config(folder, a.port, "b-" * 20)

        a.reset_token()

        assert a.key_note == "reset"
        assert _advertised(folder)["headers"]["X-TCC-Token"] == "b-" * 20
    finally:
        a.stop()


def test_a_stopping_server_withdraws_while_the_port_is_still_its_own(folder, monkeypatch):
    """With one key per folder the port is all that tells two TCCs apart, and a port given back can
    be taken by the next TCC before the old one reads `.mcp.json`. So the entry goes first."""
    server = _server(folder)
    server.start()
    held: list[bool] = []
    real = mcp_server.forget_mcp_config

    def watching(*args, **kwargs):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(5)
            held.append(probe.connect_ex(("127.0.0.1", server.port)) == 0)
        real(*args, **kwargs)

    monkeypatch.setattr(mcp_server, "forget_mcp_config", watching)

    server.stop()

    assert held == [True]


def _beaten_to_it(folder: Path, monkeypatch) -> list:
    """Another TCC finishes its first start at the worst moment: after this one found no file,
    before this one writes. Forced rather than raced: a race a test has to win is no test."""
    real = own_store.write_secret
    theirs: list = []

    def they_get_there_first(path, text, **kwargs):
        monkeypatch.setattr(own_store, "write_secret", real)
        theirs.append(mcp_key.load(folder))
        return real(path, text, **kwargs)

    monkeypatch.setattr(own_store, "write_secret", they_get_there_first)
    return theirs


def test_the_first_start_of_two_tccs_ends_on_the_one_key_the_file_holds(folder, monkeypatch):
    theirs = _beaten_to_it(folder, monkeypatch)

    mine = mcp_key.load(folder)

    assert theirs[0].note == "made" and mine.note == "made"
    assert _key_file(folder).read_text(encoding="utf-8").strip() == theirs[0].token == mine.token
    assert [p.name for p in _key_file(folder).parent.iterdir()] == ["mcp-token"]


def test_the_first_writer_still_wins_on_a_folder_with_no_hard_links(folder, monkeypatch):
    """FAT, exFAT and some network shares refuse `os.link`; the name is then claimed by O_EXCL."""
    def refused(*_args, **_kwargs):
        raise OSError(errno.ENOTSUP, "Operation not supported")

    monkeypatch.setattr(own_store.os, "link", refused)
    theirs = _beaten_to_it(folder, monkeypatch)

    mine = mcp_key.load(folder)

    assert _key_file(folder).read_text(encoding="utf-8").strip() == theirs[0].token == mine.token
    assert [p.name for p in _key_file(folder).parent.iterdir()] == ["mcp-token"]
    if os.name != "nt":
        assert stat.S_IMODE(_key_file(folder).stat().st_mode) == 0o600


# ---- what is said, and what never is ----


class _Strip:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, bool]] = []

    def notify(self, text, level="info", sticky=False, **_kwargs) -> None:
        self.lines.append((text, level, sticky))


@pytest.mark.parametrize("note, key, level", [("made", "mcpKeyMade", "info"),
                                              ("replaced", "mcpKeyReplaced", "warn")])
def test_the_strip_says_a_session_must_reconnect_when_the_key_changed(note, key, level):
    strip = _Strip()

    mcp_view.say_started(SimpleNamespace(key_note=note, key_problem="", config_error=""), strip)

    assert strip.lines == [(i18n.t(key), level, False)]
    assert "/mcp" in strip.lines[0][0]


def test_the_strip_says_why_a_key_lasts_only_this_run_and_the_line_stands():
    strip = _Strip()

    mcp_view.say_started(SimpleNamespace(key_note="run_only", key_problem="some reason",
                                         config_error=""), strip)

    assert strip.lines == [(i18n.t("mcpKeyRunOnly").format(why="some reason"), "warn", True)]
    assert "some reason" in strip.lines[0][0] and "/mcp" in strip.lines[0][0]


@pytest.mark.parametrize("note", ["", "no_folder"])
def test_a_key_that_did_not_change_is_not_news(note):
    strip = _Strip()

    mcp_view.say_started(SimpleNamespace(key_note=note, key_problem="", config_error=""), strip)

    assert strip.lines == []


def test_the_strip_still_says_the_advert_failed():
    strip = _Strip()

    mcp_view.say_started(SimpleNamespace(key_note="", key_problem="", config_error="OSError: x"), strip)

    assert strip.lines == [(i18n.t("mcpNoConfig").format(error="OSError: x"), "warn", False)]


def _host(server, strip=None) -> SimpleNamespace:
    return SimpleNamespace(_mcp_server=server, _status_strip=strip or _Strip())


def test_the_reset_line_resets_and_the_strip_says_every_session_must_reconnect():
    calls: list[str] = []
    server = SimpleNamespace(key_note="", key_problem="", config_error="",
                             reset_token=lambda: (calls.append("reset"),
                                                  setattr(server, "key_note", "reset")))
    host = _host(server)
    entry = next(e for e in menu_registry.collect() if e.id == "mcp_key_reset")

    entry.on(host)

    assert calls == ["reset"]
    assert host._status_strip.lines == [(i18n.t("mcpKeyReset"), "warn", False)]
    assert "/mcp" in host._status_strip.lines[0][0]


def test_a_reset_says_a_second_open_tcc_needs_a_restart():
    """It reads the key once, at its start, so it keeps taking the old one until it restarts."""
    strip = _Strip()
    server = SimpleNamespace(key_note="reset", key_problem="", config_error="",
                             reset_token=lambda: None)

    mcp_view.reset_key(_host(server, strip))

    assert "second TCC" in strip.lines[0][0] and "restart" in strip.lines[0][0]


def test_a_reset_that_could_not_be_saved_says_so_and_about_the_second_tcc_too():
    strip = _Strip()
    server = SimpleNamespace(key_note="run_only", key_problem="some reason", config_error="",
                             reset_token=lambda: None)

    mcp_view.reset_key(_host(server, strip))

    assert strip.lines == [(i18n.t("mcpKeyResetRunOnly").format(why="some reason"), "warn", True)]
    assert "some reason" in strip.lines[0][0] and "second TCC" in strip.lines[0][0]


def test_the_reset_line_is_off_while_there_is_no_server():
    entry = next(e for e in menu_registry.collect() if e.id == "mcp_key_reset")

    assert entry.enabled(_host(None)) is False
    assert entry.enabled(_host(SimpleNamespace())) is True


def test_the_key_reaches_neither_the_log_nor_the_strip(folder, monkeypatch, app_log_told):
    lines: list[str] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record))

    keep = Keep()
    log = app_log.logger()
    level = log.level
    log.setLevel(logging.DEBUG)
    log.addHandler(keep)
    strip = _Strip()
    seen: set[str] = set()
    try:
        server = _server(folder)
        seen.add(server.token)
        server.start()
        mcp_view.say_started(server, strip)
        mcp_view.reset_key(_host(server, strip))
        seen.add(server.token)
        server.stop()

        _key_file(folder).unlink()  # the one that lasted only this run, and its reason, said too
        _key_file(folder).mkdir()
        unsaved = TccMcpServer(project_dir=folder)
        seen.add(unsaved.token)
        mcp_view.say_started(unsaved, strip)
    finally:
        log.removeHandler(keep)
        log.setLevel(level)

    assert len(seen) == 3, "the first key, the reset's and the unsaved run's"
    told = "\n".join(lines + list(app_log_told) + [text for text, _, _ in strip.lines])
    assert strip.lines, "the failure above was said"
    for key in seen:
        assert key not in told
