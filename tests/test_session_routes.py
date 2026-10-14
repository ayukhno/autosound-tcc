"""Routing out of the window (`core/session_routes.py`, tcc #181 task 2): which session a pick gets,
what refuses a launch, which CLI the terminal opens, and which registry id a launch resumes.

The first half pins the WINDOW's behaviour through its own methods on a stand-in `self` — no full
window is built — and was green before the routing moved, so the move is shown to change nothing.
The second half tests `session_routes` as plain functions.
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from autosound_tcc.core import (  # noqa: E402
    child, critic, omp_session, session_routes, terminal_launcher)
from autosound_tcc.core.codex_session import CodexSession  # noqa: E402
from autosound_tcc.core.omp_session import OmpSession  # noqa: E402
from autosound_tcc.core.session_registry import SessionRegistry  # noqa: E402
from autosound_tcc.core.session_routes import Refusal  # noqa: E402
from autosound_tcc.core.tuning_session import TuningSession  # noqa: E402
from autosound_tcc.ui.tcc import i18n, mcp_view  # noqa: E402
from autosound_tcc.ui.tcc.main_window import MainWindow  # noqa: E402


@pytest.fixture
def built(monkeypatch):
    """Every session constructed, as (class, kwargs) — the constructors themselves do not run."""
    seen: list[tuple[type, dict]] = []

    def recorder(cls):
        def init(self, **kwargs):
            seen.append((cls, kwargs))
        return init

    monkeypatch.setattr(TuningSession, "__init__", recorder(TuningSession))
    monkeypatch.setattr(OmpSession, "__init__", recorder(OmpSession))
    monkeypatch.setattr(CodexSession, "__init__", recorder(CodexSession))
    return seen


@pytest.fixture
def language():
    was = i18n.current_language()
    yield i18n.set_language
    i18n.set_language(was)


def _server(tmp_path, **extra):
    fields = dict(stopped_reason=None, config_error="", project_dir=tmp_path,
                  registry=SessionRegistry(tmp_path / ".tcc"), url="http://127.0.0.1:1/mcp",
                  token="tok")
    fields.update(extra)
    return SimpleNamespace(**fields)


# ---- the window, pinned ---------------------------------------------------------------------


def _factory_host(gate="writes", allowed=frozenset({"Bash"})):
    state = {"gate": gate, "allowed": allowed}
    host = SimpleNamespace(_bridge=object(), _effective_gate=lambda: state["gate"],
                           _always_allowed=lambda: state["allowed"])
    return host, state


def test_an_sdk_pick_gets_the_sdk_session_with_the_servers_url_and_token(tmp_path, built, language):
    host, _ = _factory_host()
    server = _server(tmp_path)
    language("uk")
    choice = SimpleNamespace(harness="sdk", model="claude-opus-5")

    MainWindow._session_factory(host, choice, server, True, "high")()

    assert built == [(TuningSession, dict(
        project_dir=tmp_path, mcp_url="http://127.0.0.1:1/mcp", mcp_token="tok",
        bridge=host._bridge, model="claude-opus-5", gate="writes",
        always_allowed=frozenset({"Bash"}), effort="high", language="uk"))]


def test_an_omp_pick_gets_omp_with_resume_and_no_url_or_token(tmp_path, built, language):
    host, _ = _factory_host()
    language("uk")
    choice = SimpleNamespace(harness="omp", model="google/gemini")

    MainWindow._session_factory(host, choice, _server(tmp_path), True, None)()

    assert built == [(OmpSession, dict(
        project_dir=tmp_path, bridge=host._bridge, model="google/gemini", resume=True,
        gate="writes", always_allowed=frozenset({"Bash"}), effort=None, language="uk"))]


@pytest.mark.parametrize("harness", ["sdk", "omp"])
def test_the_gate_is_read_when_the_session_is_built_and_the_language_when_the_factory_is(
        tmp_path, built, language, harness):
    """The factory is made before `_ensure_machine_gate_answered` asks its question, and the
    session is built later on the worker's thread: the gate picked in between is the one it gets."""
    host, state = _factory_host()
    language("uk")
    factory = MainWindow._session_factory(
        host, SimpleNamespace(harness=harness, model="m"), _server(tmp_path), False, None)
    state["gate"], state["allowed"] = "never", frozenset({"Edit"})
    language("en")

    factory()

    kwargs = built[0][1]
    assert (kwargs["gate"], kwargs["always_allowed"], kwargs["language"]) == (
        "never", frozenset({"Edit"}), "uk")


class _Built(Exception):
    """The launch got past its refusals and asked for a factory."""


def _launch_host(tmp_path, choice, server):
    said: list[str] = []

    def factory(_choice, _server, resumed, effort):
        raise _Built(resumed)

    host = SimpleNamespace(
        _mcp_server=server, _mcp_error="", _generator_choice=lambda: choice,
        _dialog=SimpleNamespace(_add_system_message=lambda text, *a, **k: said.append(text)),
        _project_setting=lambda key: None, _session_factory=factory)
    return host, said


def _launch(host, fresh=False):
    """`resumed` when the launch reached the factory, or None when it was refused."""
    try:
        MainWindow._launch_session(host, fresh=fresh)
    except _Built as built:
        return built.args[0]
    return None


def test_a_missing_omp_refuses_the_launch_with_its_sentence(tmp_path, monkeypatch):
    monkeypatch.setattr(omp_session, "is_available", lambda: False)
    host, said = _launch_host(tmp_path, SimpleNamespace(harness="omp", model="g"),
                              _server(tmp_path))

    assert _launch(host) is None
    assert said == [i18n.t("ompMissing")]


def test_omp_without_its_mcp_json_refuses_the_launch_with_the_views_sentence(tmp_path, monkeypatch):
    monkeypatch.setattr(omp_session, "is_available", lambda: True)
    server = _server(tmp_path, config_error="PermissionError: read-only")
    host, said = _launch_host(tmp_path, SimpleNamespace(harness="omp", model="g"), server)

    assert _launch(host) is None
    assert said == [mcp_view.omp_without_config(server)]
    assert said == [i18n.t("mcpNoConfigOmp").format(error="PermissionError: read-only")]


def test_an_sdk_launch_is_not_refused_by_an_unwritten_mcp_json(tmp_path, monkeypatch):
    monkeypatch.setattr(omp_session, "is_available", lambda: False)
    server = _server(tmp_path, config_error="PermissionError: read-only")
    host, said = _launch_host(tmp_path, SimpleNamespace(harness="sdk", model="m"), server)

    assert _launch(host) is False
    assert said == []


@pytest.mark.parametrize("harness", ["sdk", "omp"])
def test_a_launch_resumes_when_the_registry_holds_an_open_id(tmp_path, monkeypatch, harness):
    """Today both routes read the one registry: the SDK id resumes the SDK route, and omp's
    `--continue` follows the same answer. «Fresh» says not resumed."""
    monkeypatch.setattr(omp_session, "is_available", lambda: True)
    server = _server(tmp_path)
    host, _ = _launch_host(tmp_path, SimpleNamespace(harness=harness, model="m"), server)

    assert _launch(host) is False, "no id yet"
    server.registry.sync_phase("2")
    server.registry.bind_session("2", "sess-1")
    assert _launch(host) is True
    assert _launch(host, fresh=True) is False
    server.registry.close_phase("2")
    assert _launch(host) is False, "a closed phase starts fresh"


def _terminal_host(tmp_path, choice, notes):
    return SimpleNamespace(
        _mcp_server=SimpleNamespace(project_dir=tmp_path), _generator_choice=lambda: choice,
        _status_strip=SimpleNamespace(notify=lambda text, **k: notes.append(text)),
        _control_layout=SimpleNamespace(active=False))


@pytest.mark.parametrize("harness, cli", [("sdk", "claude"), ("omp", "omp")])
def test_the_terminal_opens_the_cli_that_carries_the_pick(tmp_path, monkeypatch, harness, cli):
    seen, notes = {}, []
    monkeypatch.setattr(terminal_launcher, "launch",
                        lambda project_dir, **kw: seen.update(kw, project_dir=project_dir) or kw["cli"])
    monkeypatch.setattr(critic, "session_env", lambda project_dir: {"ENV": str(project_dir)})
    host = _terminal_host(tmp_path, SimpleNamespace(harness=harness, model="the-model"), notes)

    MainWindow._open_terminal(host)

    extra = ("--config", str(omp_session.overlay_path(tmp_path))) if harness == "omp" else ()
    assert seen == dict(project_dir=tmp_path, cli=cli, model="the-model", extra=extra,
                        env={"ENV": str(tmp_path)})
    assert notes == [i18n.t("terminalOpened").format(cli=cli)]


def test_a_terminal_that_cannot_open_says_why_on_the_strip(tmp_path, monkeypatch):
    def refuse(project_dir, **kw):
        raise terminal_launcher.TerminalLaunchError("'claude' is not on PATH")

    notes: list[str] = []
    monkeypatch.setattr(terminal_launcher, "launch", refuse)
    host = _terminal_host(tmp_path, SimpleNamespace(harness="sdk", model="m"), notes)

    MainWindow._open_terminal(host)

    assert notes == ["'claude' is not on PATH"]


def test_an_sdk_launch_never_resumes_a_codex_thread_and_omp_still_reads_any(tmp_path, monkeypatch):
    """The window asks the registry for its route's id (`resume_route`): a Codex thread id is not
    the SDK's to resume. omp keeps its rule — any live session in the phase."""
    monkeypatch.setattr(omp_session, "is_available", lambda: True)
    server = _server(tmp_path)
    server.registry.sync_phase("2")
    server.registry.bind_session("2", "thread-codex", route="codex")

    for harness, resumed in (("sdk", False), ("omp", True)):
        host, _ = _launch_host(tmp_path, SimpleNamespace(harness=harness, model="m"), server)
        assert _launch(host) is resumed, harness


def test_a_codex_pick_launches_and_resumes_only_a_codex_thread(tmp_path, built, monkeypatch):
    """#181 task 6: a Codex pick is no longer refused — it reaches the factory, which builds a
    `CodexSession`, and the launch reads the Codex route: an SDK id in the phase is not a thread
    Codex can continue, a Codex thread id is."""
    _codex_found(monkeypatch)
    server = _server(tmp_path)
    server.registry.sync_phase("2")
    server.registry.bind_session("2", "sdk-id", route="sdk")
    host, said = _launch_host(tmp_path, SimpleNamespace(harness="codex", model="gpt-a"), server)

    assert _launch(host) is False, "an SDK id is not Codex's to resume"
    server.registry.bind_session("2", "thread-1", route="codex")
    assert _launch(host) is True
    assert said == []

    factory_host, _ = _factory_host()
    MainWindow._session_factory(factory_host, SimpleNamespace(harness="codex", model="gpt-a"),
                                server, True, "max")()
    assert built and built[0][0] is CodexSession
    assert built[0][1]["resume"] is True and built[0][1]["mcp_token"] == "tok"


# ---- session_routes as plain functions ------------------------------------------------------


def _made(choice, tmp_path, gate=lambda: "writes", resumed=False):
    return session_routes.factory(
        choice, project_dir=tmp_path, bridge="the-bridge", mcp_url="http://u", mcp_token="tok",
        gate=gate, always_allowed=lambda: frozenset({"Bash"}), resumed=resumed, effort="max",
        language="de")


def test_factory_builds_each_routes_session(tmp_path, built):
    _made(SimpleNamespace(harness="sdk", model="claude-opus-5"), tmp_path)()
    _made(SimpleNamespace(harness="omp", model="google/gemini"), tmp_path, resumed=True)()
    _made(SimpleNamespace(harness="codex", model="gpt-a"), tmp_path, resumed=True)()

    assert built == [
        (TuningSession, dict(project_dir=tmp_path, mcp_url="http://u", mcp_token="tok",
                             bridge="the-bridge", model="claude-opus-5", gate="writes",
                             always_allowed=frozenset({"Bash"}), effort="max", language="de")),
        (OmpSession, dict(project_dir=tmp_path, bridge="the-bridge", model="google/gemini",
                          resume=True, gate="writes", always_allowed=frozenset({"Bash"}),
                          effort="max", language="de")),
        (CodexSession, dict(project_dir=tmp_path, bridge="the-bridge", model="gpt-a",
                            resume=True, gate="writes", always_allowed=frozenset({"Bash"}),
                            effort="max", language="de", mcp_url="http://u", mcp_token="tok",
                            journal=True)),
    ]


def test_the_factory_builds_a_real_codex_session(tmp_path, monkeypatch):
    """I6: `built` stands in a `**kwargs` constructor, which takes any keyword — a name the factory
    passes and `CodexSession.__init__` no longer has would pass there. This one is real; it starts
    no process (that is `start()`)."""
    session = _made(SimpleNamespace(harness="codex", model="gpt-a"), tmp_path, resumed=True)()

    assert isinstance(session, CodexSession)
    assert (session.project_dir, session.model, session.resume, session.journal) == (
        tmp_path, "gpt-a", True, True)
    assert (session.mcp_url, session.mcp_token, session.gate) == ("http://u", "tok", "writes")
    assert session.always_allowed == frozenset({"Bash"}) and session._server is None


@pytest.mark.parametrize("harness, resumed, written", [
    ("sdk", True, True), ("omp", True, True), ("codex", False, True), ("codex", True, False)])
def test_the_window_journals_every_launch_but_a_codex_resume(tmp_path, monkeypatch, harness,
                                                             resumed, written):
    """M7: a Codex launch that means to resume is journalled by the session, once `thread/resume`
    has said whether it held (`CodexSession.journal`); every other launch by the window, at once."""
    from autosound_tcc.core import process_writer
    calls: list = []
    monkeypatch.setattr(process_writer, "record_session",
                        lambda project_dir, harness, model, resumed=False:
                        calls.append((project_dir, harness, model, resumed)))

    session_routes.record_start(tmp_path, SimpleNamespace(harness=harness, model="m"), resumed)

    assert calls == ([(tmp_path, harness, "m", resumed)] if written else [])


def test_factory_builds_nothing_until_called_and_asks_the_gate_then(tmp_path, built):
    asked: list[str] = []
    factory = _made(SimpleNamespace(harness="sdk", model="m"), tmp_path,
                    gate=lambda: asked.append("gate") or "auto")
    assert built == [] and asked == []

    factory()

    assert asked == ["gate"] and built[0][1]["gate"] == "auto"


@pytest.mark.parametrize("harness, route", [("sdk", "sdk"), ("omp", None), ("codex", "codex")])
def test_resume_route_per_harness(harness, route):
    assert session_routes.resume_route(harness) == route


def test_blocker_refuses_omp_only(tmp_path, monkeypatch):
    unwritten = _server(tmp_path, config_error="PermissionError: ro")
    omp, sdk = SimpleNamespace(harness="omp"), SimpleNamespace(harness="sdk")
    _codex_found(monkeypatch)
    assert session_routes.blocker(SimpleNamespace(harness="codex"), unwritten) is None, \
        "Codex takes the url and token directly; its own blockers: test_codex_menu"

    monkeypatch.setattr(omp_session, "is_available", lambda: False)
    assert session_routes.blocker(omp, unwritten) == Refusal("ompMissing"), "missing comes first"
    assert session_routes.blocker(sdk, unwritten) is None
    monkeypatch.setattr(omp_session, "is_available", lambda: True)
    assert session_routes.blocker(omp, _server(tmp_path)) is None
    assert session_routes.blocker(omp, unwritten) == Refusal(
        "mcpNoConfigOmp", {"error": "PermissionError: ro"})


def test_omp_without_config_names_the_file_it_could_not_read_or_move(tmp_path):
    path = tmp_path / ".mcp.json"
    unread = SimpleNamespace(config_error="e", config_unreadable=path)
    unmoved = SimpleNamespace(config_error="e", config_unmoved=path, config_unreadable=path)

    assert session_routes.omp_without_config(unread) == Refusal(
        "mcpConfigUnreadOmp", {"path": path, "error": "e"})
    assert session_routes.omp_without_config(unmoved) == Refusal(
        "mcpConfigUnmovedOmp", {"path": path, "error": "e"}), "unmoved is said before unread"
    assert mcp_view.say(Refusal("ompMissing")) == i18n.t("ompMissing")


def _codex_found(monkeypatch, found=True):
    from autosound_tcc.core import codex_cli
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: (
        codex_cli.Found("/opt/codex", codex_cli.SOURCE_PATH) if found else None))


def _codex_line(project_dir):
    return ("-m", "autosound_tcc.core.codex_terminal", str(project_dir))


@pytest.mark.parametrize("harness, cli", [("sdk", "claude"), ("omp", "omp"), ("codex", "codex")])
def test_terminal_invocation_per_harness(tmp_path, monkeypatch, harness, cli):
    """A Codex pick opens Codex with TCC's tools (`codex_terminal`, task 8) — no longer `claude`."""
    _codex_found(monkeypatch)
    got = session_routes.terminal_invocation(SimpleNamespace(harness=harness, model="m"), tmp_path)

    if harness == "codex":
        assert got == (child.script_interpreter(), "m", _codex_line(tmp_path))
    else:
        extra = ("--config", str(omp_session.overlay_path(tmp_path))) if harness == "omp" else ()
        assert got == (cli, "m", extra)


def test_on_windows_the_codex_line_runs_python_exe_not_pythonw(tmp_path, monkeypatch):
    """The GUI runs under `pythonw.exe` — no console, so `codex_terminal`'s refusals would print
    to nowhere and Codex would get a console of its own (C1)."""
    from pathlib import Path
    windowed = r"C:\tools\autosound-tcc\Scripts\pythonw.exe"
    console = r"C:\tools\autosound-tcc\Scripts\python.exe"
    _codex_found(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", windowed)
    real = Path.exists
    monkeypatch.setattr(Path, "exists", lambda self, *a, **k: str(self) == console or real(
        self, *a, **k))

    cli, _model, _extra = session_routes.client_invocation(
        "codex", SimpleNamespace(harness="codex", model="m"), tmp_path)

    assert cli == console


@pytest.mark.parametrize("client", session_routes.TERMINAL_CLIENTS[1:])
@pytest.mark.parametrize("harness", ["sdk", "omp", "codex"])
def test_the_model_rides_only_to_the_client_that_carries_the_pick(tmp_path, monkeypatch, client,
                                                                    harness):
    """tcc #180: an SDK pick's model goes to Claude, omp's to OMP, Codex's to Codex; any other
    client keeps its own model."""
    _codex_found(monkeypatch)
    carries = {"sdk": "claude", "omp": "omp", "codex": "codex"}[harness]

    _cli, model, _extra = session_routes.client_invocation(
        client, SimpleNamespace(harness=harness, model="the-model"), tmp_path)

    assert model == ("the-model" if client == carries else None)


def test_omp_always_gets_its_overlay_and_agy_runs_bare(tmp_path, monkeypatch):
    pick = SimpleNamespace(harness="sdk", model="m")

    assert session_routes.client_invocation("omp", pick, tmp_path) == (
        "omp", None, ("--config", str(omp_session.overlay_path(tmp_path))))
    assert session_routes.client_invocation("agy", pick, tmp_path) == ("agy", None, ())
    assert session_routes.client_invocation("claude", pick, tmp_path) == ("claude", "m", ())


def test_codex_gone_at_click_time_is_the_launcher_s_error_not_another_client(tmp_path,
                                                                            monkeypatch):
    _codex_found(monkeypatch, found=False)

    with pytest.raises(terminal_launcher.TerminalLaunchError, match="Codex"):
        session_routes.client_invocation("codex", SimpleNamespace(harness="codex", model="m"),
                                         tmp_path)


# ---- the stop's journal line pairs the start's (the re-review of the group fix, I) ---------------


@pytest.mark.parametrize("harness, resumed, wrote", [
    ("sdk", False, True), ("sdk", True, True), ("omp", True, True), ("codex", False, True),
    ("codex", True, False)])
def test_record_start_says_whether_the_window_journalled(tmp_path, monkeypatch, harness, resumed,
                                                         wrote):
    """The window keeps the answer as `_session_open`: every route but a Codex resume is on the
    record before the first token, as before; a Codex resume is not the window's to pair."""
    from autosound_tcc.core import process_writer
    monkeypatch.setattr(process_writer, "record_session", lambda *a, **k: "ok")

    assert session_routes.record_start(
        tmp_path, SimpleNamespace(harness=harness, model="m"), resumed) is wrote


def _stop_host(window_wrote: bool, session) -> SimpleNamespace:
    said: list[str] = []
    return SimpleNamespace(
        _session_open=window_wrote, _agent_worker=SimpleNamespace(session=session),
        _status_strip=SimpleNamespace(notify=lambda text, **k: said.append(text)),
        _dialog=SimpleNamespace(_add_system_message=lambda *a, **k: None))


@pytest.fixture
def closes(monkeypatch, tmp_path):
    from autosound_tcc.core import config, process_writer
    calls: list = []
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(process_writer, "close_session",
                        lambda project_dir: calls.append(project_dir) or (True, ""))
    return calls


@pytest.mark.parametrize("why", ["the start failed before the journal", "session-start refused"])
def test_a_codex_resume_the_session_never_journalled_writes_no_close(closes, why):
    """(A) signed out, MethodRefused, CodexStartFailed, a Stop while starting; (B) `session-start`
    refused inside the session: either way no start is on the record, so no close is written."""
    host = _stop_host(False, SimpleNamespace(journaled=False))

    MainWindow._record_session_stop(host)

    assert closes == []


def test_a_codex_resume_the_session_journalled_is_closed_once(closes):
    session = SimpleNamespace(journaled=True)
    host = _stop_host(False, session)

    MainWindow._record_session_stop(host)
    MainWindow._record_session_stop(host)

    assert len(closes) == 1 and session.journaled is False


@pytest.mark.parametrize("session", [None, SimpleNamespace()])
def test_a_launch_the_window_journalled_is_closed_once_as_before(closes, session):
    host = _stop_host(True, session)

    MainWindow._record_session_stop(host)
    MainWindow._record_session_stop(host)

    assert len(closes) == 1 and host._session_open is False


def test_no_journalled_start_no_worker_no_close(closes):
    host = _stop_host(False, None)
    host._agent_worker = None

    MainWindow._record_session_stop(host)

    assert closes == []
