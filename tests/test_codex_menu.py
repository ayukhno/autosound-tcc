"""«Встановити Codex» and «Увійти в Codex» (`ui/tcc/codex_menu.py`, W-10 tcc#181 task 9), Codex's
launch blockers (`session_routes.blocker`) and the feature's strings (`strings/codex.py`).

The lines are a `menu_registry` provider: the window gains no line of its own but the one call in
`stop_workers`. Their state is asked by stat calls only; a click runs the work on a worker, never
on the GUI thread, and the result lands on the status strip.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import codex_cli, codex_install, codex_login, session_routes  # noqa: E402
from autosound_tcc.core.codex_cli import Found  # noqa: E402
from autosound_tcc.core.model_choices import Choice  # noqa: E402
from autosound_tcc.core.session_routes import Refusal  # noqa: E402
from autosound_tcc.ui.tcc import codex_menu, i18n, mcp_view, menu_registry, qt_shutdown  # noqa: E402
from autosound_tcc.ui.tcc.strings import codex as codex_strings  # noqa: E402

PICK = Choice(harness="codex", model="gpt-a", label="GPT-A", provider="openai")


def _app():
    return QApplication.instance() or QApplication([])


class _Strip:
    def __init__(self) -> None:
        self.lines: list[tuple[str, dict]] = []

    def notify(self, text, **kw) -> None:
        assert threading.current_thread() is threading.main_thread(), "the strip on the GUI thread"
        self.lines.append((text, kw))

    def texts(self) -> list[str]:
        return [text for text, _kw in self.lines]


def _host():
    reloaded: list[bool] = []
    return SimpleNamespace(_status_strip=_Strip(),
                           _reload_model_choices=lambda: reloaded.append(True),
                           reloaded=reloaded)


def _until(predicate, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        _app().processEvents()
        time.sleep(0.01)


def _entry(entry_id: str):
    return next(e for e in codex_menu.menu_entries() if e.id == entry_id)


def _found(tmp_path: Path) -> Found:
    binary = tmp_path / "bin" / "codex"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"\xcf\xfa\xed\xfe native")
    binary.chmod(0o755)
    return Found(str(binary), codex_cli.SOURCE_PATH)


@pytest.fixture
def no_subprocess(monkeypatch):
    """Asking a line's state runs nothing: `version` and `probe` would spawn Codex."""
    def boom(*_a, **_k):
        raise AssertionError("a subprocess on the GUI thread")

    monkeypatch.setattr(codex_cli, "version", boom)
    monkeypatch.setattr(codex_cli, "probe", boom)


# ---- the lines ------------------------------------------------------------------------------


def test_the_lines_are_a_provider_s_and_sit_under_the_models_in_settings():
    assert "autosound_tcc.ui.tcc.codex_menu" in menu_registry.PROVIDERS
    entries = menu_registry.collect()
    assert menu_registry.problems(entries, set(i18n.T["en"])) == []
    ids = [e.id for e in menu_registry.ordered(entries, "settings")]
    at = ids.index("models")
    assert ids[at + 1:at + 3] == ["codex_install", "codex_sign_in"]
    assert _entry("codex_install").text() == i18n.t("codexInstall")
    assert _entry("codex_sign_in").text() == i18n.t("codexSignIn")


def test_install_is_offered_when_codex_is_not_found(no_subprocess):
    host = _host()
    assert _entry("codex_install").enabled(host)
    assert not _entry("codex_sign_in").enabled(host), "nothing to sign in to"


def test_install_is_offered_when_the_codex_found_is_known_to_be_too_old(
        tmp_path, monkeypatch, no_subprocess):
    found = _found(tmp_path)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    monkeypatch.setitem(codex_cli._VERSIONS, codex_cli._stamp(found), (0, 150, 0))
    host = _host()
    assert _entry("codex_install").enabled(host)
    assert not _entry("codex_sign_in").enabled(host)


@pytest.mark.parametrize("signed_in, offered", [(None, True), (False, True), (True, False)])
def test_sign_in_is_offered_while_a_usable_codex_is_not_known_to_be_signed_in(
        tmp_path, monkeypatch, no_subprocess, signed_in, offered):
    found = _found(tmp_path)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    monkeypatch.setattr(codex_cli, "_PROBE", codex_cli.Probe(signed_in=signed_in, asked=True))
    host = _host()
    assert not _entry("codex_install").enabled(host), "a usable Codex is used"
    assert bool(_entry("codex_sign_in").enabled(host)) is offered


# ---- a click runs on a worker ---------------------------------------------------------------


def test_install_runs_on_a_worker_with_progress_and_says_done(monkeypatch, no_subprocess):
    _app()
    threads: list[bool] = []

    def install(progress, cancelled, **_kw):
        threads.append(threading.current_thread() is threading.main_thread())
        progress(50, 100)
        progress(100, 100)
        return Path("/x/codex")

    monkeypatch.setattr(codex_install, "install", install)
    monkeypatch.setattr(codex_menu, "after_install", lambda: None)
    host = _host()

    _entry("codex_install").on(host)
    assert not _entry("codex_install").enabled(host), "not twice at once"
    _until(lambda: i18n.t("codexInstalled") in host._status_strip.texts())

    assert threads == [False], "never on the GUI thread"
    texts = host._status_strip.texts()
    assert any(i18n.t("codexInstalling").split("{")[0] in t for t in texts)
    cancel_offer = host._status_strip.lines[0][1].get("action")
    assert cancel_offer and cancel_offer[0] == i18n.t("codexCancel")
    assert host.reloaded == [True], "the pickers read Codex's models again"


def test_an_install_error_is_its_sentence_on_the_strip(monkeypatch, no_subprocess):
    _app()

    def install(progress, cancelled, **_kw):
        raise codex_install.InstallError("disk said no", key="codexInstallDisk", error="full")

    monkeypatch.setattr(codex_install, "install", install)
    host = _host()

    _entry("codex_install").on(host)
    said = i18n.t("codexInstallDisk").format(error="full")
    _until(lambda: said in host._status_strip.texts())
    assert dict(host._status_strip.lines)[said].get("level") == "warn"


def test_the_strip_s_cancel_reaches_the_install_between_chunks(monkeypatch, no_subprocess):
    _app()
    seen: list[bool] = []

    def install(progress, cancelled, **_kw):
        progress(1, 100)
        deadline = time.monotonic() + 10
        while not cancelled():
            if time.monotonic() > deadline:
                raise AssertionError("never cancelled")
            time.sleep(0.01)
        seen.append(True)
        raise codex_install.InstallError("cancelled", key="codexInstallCancelled")

    monkeypatch.setattr(codex_install, "install", install)
    host = _host()
    _entry("codex_install").on(host)
    _until(lambda: host._status_strip.lines)

    host._status_strip.lines[0][1]["action"][1]()  # the strip's «Cancel»
    _until(lambda: i18n.t("codexInstallCancelled") in host._status_strip.texts())
    assert seen == [True]


class _FakeSignIn:
    """`codex_login.SignIn` without Codex: records the thread, waits for a cancel when told."""

    instances: list = []
    outcome = (True, "")
    block = False

    def __init__(self) -> None:
        self.threads: list[bool] = []
        self.cancelled = False
        self.error = ""
        self.closed = 0
        _FakeSignIn.instances.append(self)

    def begin(self, timeout=30.0) -> str:
        self.threads.append(threading.current_thread() is threading.main_thread())
        return "https://auth.openai.com/oauth/authorize?x=1"

    def wait(self, timeout=600, cancelled=lambda: False) -> bool:
        self.threads.append(threading.current_thread() is threading.main_thread())
        if _FakeSignIn.block:
            deadline = time.monotonic() + 10
            while not cancelled():
                if time.monotonic() > deadline:
                    raise AssertionError("never cancelled")
                time.sleep(0.01)
            self.cancelled = True
            return False
        ok, self.error = _FakeSignIn.outcome
        return ok

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def fake_sign_in(monkeypatch, tmp_path):
    _FakeSignIn.instances = []
    _FakeSignIn.outcome = (True, "")
    _FakeSignIn.block = False
    monkeypatch.setattr(codex_login, "SignIn", _FakeSignIn)
    opened: list[str] = []
    monkeypatch.setattr(codex_menu, "open_browser", opened.append)
    found = _found(tmp_path)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    monkeypatch.setattr(codex_menu, "after_sign_in", lambda: None)
    return opened


def test_sign_in_runs_on_a_worker_opens_the_browser_and_says_the_result(fake_sign_in,
                                                                         no_subprocess):
    _app()
    host = _host()

    _entry("codex_sign_in").on(host)
    _until(lambda: i18n.t("codexSignedIn") in host._status_strip.texts())

    (sign_in,) = _FakeSignIn.instances
    assert sign_in.threads == [False, False], "begin and wait off the GUI thread"
    assert sign_in.closed >= 1
    assert fake_sign_in == ["https://auth.openai.com/oauth/authorize?x=1"]
    finish = [kw for text, kw in host._status_strip.lines if text == i18n.t("codexFinishInBrowser")]
    assert finish and finish[0]["action"][0] == i18n.t("codexCancel"), "a cancel line while waiting"
    assert host.reloaded == [True]


def test_a_failed_sign_in_says_codex_s_sentence(fake_sign_in, no_subprocess):
    _app()
    _FakeSignIn.outcome = (False, "Login server error: no")
    host = _host()

    _entry("codex_sign_in").on(host)
    said = i18n.t("codexSignInFailed").format(error="Login server error: no")
    _until(lambda: said in host._status_strip.texts())


def test_the_strip_s_cancel_ends_a_waiting_sign_in(fake_sign_in, no_subprocess):
    _app()
    _FakeSignIn.block = True
    host = _host()
    _entry("codex_sign_in").on(host)
    _until(lambda: i18n.t("codexFinishInBrowser") in host._status_strip.texts())

    dict(host._status_strip.lines)[i18n.t("codexFinishInBrowser")]["action"][1]()
    _until(lambda: i18n.t("codexSignInCancelled") in host._status_strip.texts())
    assert _FakeSignIn.instances[0].cancelled


def test_a_closing_window_cancels_a_waiting_sign_in_and_leaves_nothing_running(
        fake_sign_in, no_subprocess):
    _app()
    _FakeSignIn.block = True
    host = _host()
    _entry("codex_sign_in").on(host)
    _until(lambda: i18n.t("codexFinishInBrowser") in host._status_strip.texts())
    worker = host._codex_job

    menu_registry.stop_workers(host)

    assert not worker.isRunning()
    assert worker not in qt_shutdown.detached()
    assert _FakeSignIn.instances[0].cancelled and _FakeSignIn.instances[0].closed >= 1


# ---- blockers -------------------------------------------------------------------------------


def test_no_codex_refuses_the_launch_naming_the_install_line():
    refusal = session_routes.blocker(PICK, server=object())
    assert refusal == Refusal("codexMissing")
    assert i18n.t("codexInstall") in mcp_view.say(refusal)


def test_a_codex_known_too_old_refuses_naming_the_install_line(tmp_path, monkeypatch):
    found = _found(tmp_path)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    monkeypatch.setitem(codex_cli._VERSIONS, codex_cli._stamp(found), (0, 150, 0))

    refusal = session_routes.blocker(PICK, server=object())

    assert refusal is not None and refusal.key == "codexTooOld"
    said = mcp_view.say(refusal)
    assert "0.150.0" in said and "0.162.0" in said and i18n.t("codexInstall") in said


def test_a_signed_out_codex_refuses_naming_the_sign_in_line(tmp_path, monkeypatch):
    found = _found(tmp_path)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    monkeypatch.setattr(codex_cli, "_PROBE", codex_cli.Probe(signed_in=False, asked=True))

    refusal = session_routes.blocker(PICK, server=object())

    assert refusal == Refusal("codexSignedOut")
    assert i18n.t("codexSignIn") in mcp_view.say(refusal)


def test_an_unread_version_and_an_unknown_login_refuse_nothing(tmp_path, monkeypatch,
                                                               no_subprocess):
    found = _found(tmp_path)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    assert session_routes.blocker(PICK, server=object()) is None
    monkeypatch.setitem(codex_cli._VERSIONS, codex_cli._stamp(found), None)  # read, unreadable
    assert session_routes.blocker(PICK, server=object()) is None


# ---- strings --------------------------------------------------------------------------------


def test_the_feature_table_is_joined_and_every_key_has_four_languages():
    from autosound_tcc.ui.tcc import strings

    assert "codex" in strings.FEATURES
    for key, row in codex_strings.STRINGS.items():
        assert set(row) == {"en", "uk", "pl", "de"}, key
        assert all(row[lang].strip() for lang in row), key
        for lang in ("uk", "pl", "de"):
            assert row[lang] != row["en"], (key, lang, "written, not the English left standing")
        fields = {lang: sorted(_fields(text)) for lang, text in row.items()}
        assert len({tuple(v) for v in fields.values()}) == 1, (key, fields)


def _fields(text: str) -> list[str]:
    import string

    return [name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name]


def test_the_blockers_name_the_lines_in_every_language():
    for lang, _key, _badge in i18n.LANGS:
        i18n.set_language(lang)
        try:
            assert i18n.t("codexInstall") in i18n.t("codexMissing"), lang
            assert i18n.t("codexInstall") in i18n.t("codexTooOld"), lang
            assert i18n.t("codexSignIn") in i18n.t("codexSignedOut"), lang
        finally:
            i18n.set_language("en")
