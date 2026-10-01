"""The reviewer's key, as the method reports it (hub #197, SKL-051)."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import critic_env, reviewer_key  # noqa: E402

_STATUS = {
    "keystore": "keychain",
    "providers": {
        "google": {"var": "GEMINI_API_KEY", "used": "keystore", "file": None, "keystore": True,
                   "env": False, "shape": "AIza…"},
        "anthropic": {"var": "ANTHROPIC_API_KEY", "used": "none", "file": None, "keystore": False,
                      "env": False, "shape": ""},
        "openai": {"var": "OPENAI_API_KEY", "used": "none", "file": None, "keystore": False,
                   "env": False, "shape": ""},
    },
    "shell_exports": [{"var": "GEMINI_API_KEY", "file": "~/.zshrc", "line": 3}],
}


#: `key help` — no such subcommand — prints the usage line and exits 2, on every method that has
#: `key`. v3.0.65 names the provider and `--drop` in it (hub #230); v3.0.64 does not.
_USAGE_DROP = ("key set <provider> | key status [--json] | key rm <provider> | "
               "key move-shell [<provider>] [--drop] [--yes]")
_USAGE_OLD = "key set <provider> | key status [--json] | key rm <provider> | key move-shell [--yes]"


class _Method:
    """The method's script, as far as `reviewer_key` sees it: argv and stdin in, an answer out.

    `after_move` is what `key status` says once `key move-shell` ran; `move_rc` is the exit code
    `move-shell` answers with (hub #230: 0 removed, 1 nothing to do, 3 refused, 2 usage), and None
    is that child killed at `_run`'s timeout — `_run` returns None — after it changed whatever it
    changed. `drops` is a method that has `move-shell <provider> --drop` (v3.0.65)."""

    def __init__(self, status=_STATUS, set_rc=0, set_out="stored in the Keychain",
                 after_move=None, move_rc=0, move_out="✓ HKCU\\Environment: прибрано",
                 drops=True):
        self.calls: list[tuple[list[str], object]] = []
        self.status, self.set_rc, self.set_out = status, set_rc, set_out
        self.after_move, self.move_rc, self.move_out, self.drops = (
            after_move, move_rc, move_out, drops)

    def __call__(self, args, *, stdin=None):
        self.calls.append((list(args), stdin))
        if args[:2] == ["key", "status"]:
            if self.status is None:
                return subprocess.CompletedProcess(args, 2, "", "invalid choice: 'key'")
            return subprocess.CompletedProcess(args, 0, json.dumps(self.status), "")
        if args[:2] == ["key", "set"]:
            ok = self.set_rc == 0
            return subprocess.CompletedProcess(args, self.set_rc, self.set_out if ok else "",
                                               "" if ok else "not a key: too short")
        if args[:2] == ["key", "move-shell"]:
            if self.after_move is not None:
                self.status = self.after_move
            if self.move_rc is None:
                return None
            return subprocess.CompletedProcess(args, self.move_rc, self.move_out, "")
        if args == ["key", "help"]:
            return subprocess.CompletedProcess(
                args, 2, "", _USAGE_DROP if self.drops else _USAGE_OLD)
        raise AssertionError(args)

    def changes(self) -> list[tuple[list[str], object]]:
        """Every call but the reads: `key status` and the usage probe."""
        return [(a, i) for a, i in self.calls if a[:2] != ["key", "status"] and a != ["key", "help"]]


def _with(status=_STATUS, *, keystore=None, exports=None, **providers):
    """`status` with its store, some providers' entries and the exports replaced — a copy, never
    the shared one."""
    out = json.loads(json.dumps(status))
    if keystore is not None:
        out["keystore"] = keystore
    for provider, fields in providers.items():
        out["providers"][provider].update(fields)
    if exports is not None:
        out["shell_exports"] = exports
    return out


_REGISTRY = {"var": "GEMINI_API_KEY", "file": "HKCU\\Environment", "line": None}


#: The real `_ask`, captured at import — the suite's autouse fixture replaces it with "the method
#: cannot answer" so no test runs the method's script; these tests put it back over a fake `_run`.
_REAL_ASK = reviewer_key._ask


def _use(monkeypatch, method):
    monkeypatch.setattr(reviewer_key, "_run", method)
    monkeypatch.setattr(reviewer_key, "_ask", _REAL_ASK)
    # The usage probe's answer is kept per script file — the same file in every test here.
    monkeypatch.setattr(reviewer_key, "_DROPS", None)
    reviewer_key.forget()


def test_a_key_only_in_the_keystore_is_reachable(monkeypatch, tmp_path):
    """The blind footer of SKL-024, one store over: with the key in the Keychain, the file and the
    environment are both empty, and only the method can say the key is there."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    critic_env.forget()
    _use(monkeypatch, _Method())
    assert critic_env.has_key("GEMINI_API_KEY") is False
    assert reviewer_key.has_key("GEMINI_API_KEY") is True
    assert reviewer_key.has_key("ANTHROPIC_API_KEY") is False


def test_an_older_method_falls_back_to_the_file(monkeypatch, tmp_path):
    """Before the vendoring brings `key status`, nothing changes: the file still answers."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    config = tmp_path / "autosound" / "critic-env"
    config.parent.mkdir(parents=True)
    config.write_text("GEMINI_API_KEY=AIza-not-a-real-key\n", encoding="utf-8")
    critic_env.forget()
    _use(monkeypatch, _Method(status=None))
    assert reviewer_key.status() is None
    assert reviewer_key.has_key("GEMINI_API_KEY") is True


def test_a_key_goes_to_the_method_on_stdin_never_in_argv(monkeypatch):
    method = _Method()
    _use(monkeypatch, method)
    secret = "AIza" + "x" * 35
    stored, said = reviewer_key.set_key("google", "  " + secret + "\n")
    assert stored and said == "stored in the Keychain"
    args, stdin = method.calls[-1]
    assert args == ["key", "set", "google"]
    assert all(secret not in a for a in args), "argv is visible to every process"
    assert stdin == secret + "\n"


def test_a_refusal_says_why_and_the_answer_is_asked_again(monkeypatch):
    method = _Method(set_rc=2)
    _use(monkeypatch, method)
    reviewer_key.status()
    stored, said = reviewer_key.set_key("google", "short")
    assert not stored and said == "not a key: too short"
    reviewer_key.status()
    assert sum(1 for a, _ in method.calls if a[:2] == ["key", "status"]) == 2, \
        "a set drops the kept answer"


def test_no_key_reaches_the_log(monkeypatch):
    from autosound_tcc.core import app_log

    said = []
    monkeypatch.setattr(app_log.logger(), "info", lambda msg, *a: said.append(msg % a))
    _use(monkeypatch, _Method())
    secret = "AIza" + "y" * 35
    reviewer_key.set_key("google", secret)
    assert said and not any(secret in line for line in said)


def test_the_screen_shows_where_never_what(monkeypatch):
    from autosound_tcc.ui.tcc import i18n
    from autosound_tcc.ui.tcc.reviewer_key_dialog import ReviewerKeyDialog

    QApplication.instance() or QApplication([])
    method = _Method()
    _use(monkeypatch, method)
    asked = []
    monkeypatch.setattr(ReviewerKeyDialog, "_confirm",
                        lambda self, text, yes, **_kw: asked.append(text) or False)
    dialog = ReviewerKeyDialog()
    assert dialog._where["google"].text() == i18n.t("rkUsed_keystore")
    assert dialog._where["anthropic"].text() == i18n.t("rkUsed_none")
    assert not dialog._shell.isHidden() and "~/.zshrc" in dialog._shell.text()
    assert "autosound_ai.py key move-shell" in dialog._shell.text()

    secret = "AIza" + "z" * 35
    dialog._field.setText(secret)
    dialog._on_save()
    assert dialog._field.text() == "", "the field lets go of the key"
    assert secret not in dialog._result.text()
    assert all(secret not in text for text in asked)
    assert [stdin for args, stdin in method.calls if args[:2] == ["key", "set"]] == [secret + "\n"]
    dialog.close()


def test_the_move_runs_only_in_a_terminal_the_arbiter_answers(monkeypatch):
    """`key move-shell` asks before it moves — so TCC opens it where the Arbiter can answer, and
    never runs it quietly."""
    from autosound_tcc.core import terminal_launcher
    from autosound_tcc.ui.tcc.reviewer_key_dialog import ReviewerKeyDialog

    QApplication.instance() or QApplication([])
    _use(monkeypatch, _Method())
    opened = []
    monkeypatch.setattr(terminal_launcher, "run_line", opened.append)
    dialog = ReviewerKeyDialog()
    dialog._move.click()
    assert len(opened) == 1 and opened[0].endswith("key move-shell")
    dialog.close()


def test_an_older_method_disables_entry_and_says_why(monkeypatch):
    from autosound_tcc.ui.tcc.reviewer_key_dialog import ReviewerKeyDialog

    QApplication.instance() or QApplication([])
    _use(monkeypatch, _Method(status=None))
    dialog = ReviewerKeyDialog()
    assert not dialog._save.isEnabled() and not dialog._field.isEnabled()
    assert "critic-env" in dialog._blurb.text()
    assert dialog._shell.isHidden()
    dialog.close()


def test_the_key_really_reaches_the_childs_stdin(tmp_path, monkeypatch):
    """Found live against v3.0.60: `child.quiet()` closes stdin, and `input=` beside it is a
    ValueError — every tested path had replaced `_run`, so none saw it."""
    script = tmp_path / "autosound_ai.py"
    script.write_text("import sys; line = sys.stdin.readline().strip(); "
                      "print('got', len(line), 'chars') if sys.argv[1:3] == ['key', 'set'] "
                      "else sys.exit(3)", encoding="utf-8")
    monkeypatch.setattr(reviewer_key, "script_path", lambda: script)
    stored, said = reviewer_key.set_key("google", "AIza" + "k" * 35)
    assert stored and said == "got 39 chars"


def test_the_saved_line_speaks_the_window_s_language(monkeypatch):
    """tcc#65, finding 42: «Stored: GEMINI_API_KEY збережено: сховище Windows…» in an English
    window — TCC's prefix followed the UI, the method's sentence is Ukrainian whatever the UI says.
    The line is TCC's now, from the method's answer; its own words go to the hover."""
    from autosound_tcc.core import reviewer_key
    from autosound_tcc.ui.tcc import i18n
    from autosound_tcc.ui.tcc.reviewer_key_dialog import ReviewerKeyDialog

    QApplication.instance() or QApplication([])
    was = i18n.current_language()
    i18n.set_language("en")
    said = "GEMINI_API_KEY збережено: сховище Windows, зашифроване вашим входом (DPAPI)"
    monkeypatch.setattr(reviewer_key, "set_key", lambda provider, value: (True, said))
    monkeypatch.setattr(reviewer_key, "status", lambda refresh=False: {
        "keystore": "dpapi", "shell_exports": [],
        "providers": {"google": {"var": "GEMINI_API_KEY", "used": "keystore"}}})
    try:
        dialog = ReviewerKeyDialog()
        dialog._provider.setCurrentIndex(dialog._provider.findData("google"))
        dialog._field.setText("AQ." + "x" * 50)
        dialog._on_save()
        text = dialog._result.text()
        assert "збережено" not in text and "GEMINI_API_KEY" in text
        assert said in dialog._result.toolTip()
    finally:
        i18n.set_language(was)


# ── tcc#117: the window on Windows (findings 125–128) ────────────────────────────────────────────


def _dialog(monkeypatch, method, *, answer=False, lang="uk"):
    """The window over `method`, in `lang`, with its yes/no answered `answer` and recorded."""
    from autosound_tcc.ui.tcc import i18n
    from autosound_tcc.ui.tcc.reviewer_key_dialog import ReviewerKeyDialog

    QApplication.instance() or QApplication([])
    i18n.set_language(lang)
    _use(monkeypatch, method)
    asked: list[str] = []
    monkeypatch.setattr(ReviewerKeyDialog, "_confirm",
                        lambda self, text, yes, **_kw: asked.append(text) or answer)
    return ReviewerKeyDialog(), asked


@pytest.fixture(autouse=True)
def _language_back():
    from autosound_tcc.ui.tcc import i18n

    was = i18n.current_language()
    yield
    i18n.set_language(was)


def test_a_registry_export_has_no_line_and_names_every_program(monkeypatch):
    """Finding 125: «… у HKCU\\Environment, рядок None. Його бачить кожна програма, запущена з
    термінала» — the macOS sentence on Windows. A registry value has no line, and a user variable
    there is read by every program the user starts."""
    from autosound_tcc.ui.tcc import i18n

    dialog, _ = _dialog(monkeypatch, _Method(status=_with(keystore="dpapi", exports=[_REGISTRY])))
    text = dialog._shell.text()
    assert "None" not in text and "рядок" not in text
    assert "запущена з термінала" not in text
    assert "змінних середовища Windows (HKCU\\Environment)" in text
    assert "її бачить кожна програма" in text
    assert text.startswith(i18n.t("rkShellEnv").format(var="GEMINI_API_KEY",
                                                       file="HKCU\\Environment"))
    dialog.close()


def test_a_shell_profile_export_keeps_its_file_and_line(monkeypatch):
    dialog, _ = _dialog(monkeypatch, _Method())
    text = dialog._shell.text()
    assert "~/.zshrc, рядок 3" in text and "запущена з термінала" in text
    dialog.close()


def test_the_move_button_fits_its_bold_tinted_label(monkeypatch):
    """Finding 126: hovered or focused, «Перенести (відкриє термінал)» lost a letter on each side.
    A dialog makes its first or focused button the default, and `QPushButton:default` is bold
    (theme.py) — so the width is measured off the bold label, plus the plain button's padding."""
    from PySide6.QtGui import QFont, QFontMetrics

    dialog, _ = _dialog(monkeypatch, _Method())
    button = dialog._move
    bold = QFont(button.font())
    bold.setWeight(QFont.Weight.DemiBold)
    assert button.minimumWidth() >= QFontMetrics(bold).horizontalAdvance(button.text()) + 2 * 14
    dialog.close()


def _api_refused():
    from autosound_tcc.core import availability
    from autosound_tcc.core.model_choices import Choice

    api = Choice(harness="api", model="gemini-pro-latest", label="gemini-pro-latest",
                 provider="google")
    agy = Choice(harness="agy", model="gemini-3.1-pro-low", label="gemini-3.1-pro-low")
    for choice in (api, agy):
        availability.refused(choice.key, availability.REFUSED, "before the key existed")

    def state(choice):
        return availability.status(choice, signed_in=lambda: None, unconfirmed=lambda _c: False)
    return api, agy, state


def test_a_save_forgets_the_api_rows_refusals(monkeypatch):
    """Finding 128: the key saved, and the picker still read `API · … · відмова` until ↻. A stored
    key answers the API rows' refusals — and only theirs: AGY refused for its own reasons."""
    from autosound_tcc.core import availability

    api, agy, state = _api_refused()
    _use(monkeypatch, _Method())
    stored, _ = reviewer_key.set_key("google", "AIza" + "r" * 35)
    assert stored
    assert state(api).ready
    assert state(agy).reason == availability.REFUSED


def test_a_refused_save_forgets_nothing(monkeypatch):
    from autosound_tcc.core import availability

    api, _agy, state = _api_refused()
    _use(monkeypatch, _Method(set_rc=2))
    reviewer_key.set_key("google", "short")
    assert state(api).reason == availability.REFUSED


def test_the_window_s_save_lifts_the_api_rows_refusals(monkeypatch):
    api, _agy, state = _api_refused()
    dialog, _ = _dialog(monkeypatch, _Method(status=_with(exports=[])))
    dialog._field.setText("AIza" + "w" * 35)
    dialog._on_save()
    assert state(api).ready
    dialog.close()


def test_the_remove_offer_needs_a_key_in_the_keystore_and_a_live_export(monkeypatch):
    """Finding 127: «треба мати питання чи видалити ключ … коли ключ вже є в сховищі і при цьому
    ще є в файлі». Asked after a save, only when both hold — and «в сховищі» is the OS keystore:
    the method's `--drop` refuses without it, the export then being the only copy (hub #230)."""
    secret = "AIza" + "q" * 35
    cases = {
        "stored + exported": (_Method(status=_with(keystore="dpapi", exports=[_REGISTRY])), 1),
        "nothing exported": (_Method(status=_with(exports=[])), 0),
        "another var exported": (_Method(status=_with(exports=[
            {"var": "OPENAI_API_KEY", "file": "~/.zshrc", "line": 7}])), 0),
        "not stored (refused)": (_Method(set_rc=2), 0),
        "not stored (env only)": (
            _Method(status=_with(google={"used": "env", "keystore": False})), 0),
        "in the machine file only": (_Method(status=_with(google={
            "used": "file", "keystore": False,
            "file": {"path": "critic-env", "line": 2, "blank": False}})), 0),
    }
    for name, (method, want) in cases.items():
        dialog, asked = _dialog(monkeypatch, method)
        dialog._field.setText(secret)
        dialog._on_save()
        assert len(asked) == want, name
        assert all(secret not in text for text in asked), name
        dialog.close()


def test_the_question_names_only_its_own_copy(monkeypatch):
    """`key move-shell <provider>` moves that provider's export and no other (hub #230): the
    question is about one key, and another export is neither named nor touched."""
    other = {"var": "OPENAI_API_KEY", "file": "~/.zshrc", "line": 7}
    method = _Method(status=_with(keystore="dpapi", exports=[_REGISTRY, other]))
    dialog, asked = _dialog(monkeypatch, method, answer=True)
    dialog._field.setText("AIza" + "n" * 35)
    dialog._on_save()
    assert len(asked) == 1
    assert "GEMINI_API_KEY" in asked[0] and "HKCU\\Environment" in asked[0]
    assert "OPENAI_API_KEY" not in asked[0]
    assert [args for args, _ in method.changes() if args[:2] == ["key", "move-shell"]] == [
        ["key", "move-shell", "google", "--drop", "--yes"]]
    dialog.close()


def test_yes_drops_the_copy_and_holds_no_key(monkeypatch):
    """The method's `--drop` removes the export WITHOUT storing it (hub #230), so the key just
    pasted is stored once and let go of — nothing holds it across the question, and nothing
    stores it again. Only the provider goes on argv."""
    from autosound_tcc.ui.tcc import i18n

    gone = _with(keystore="dpapi", exports=[])
    method = _Method(status=_with(keystore="dpapi", exports=[_REGISTRY]), after_move=gone)
    dialog, asked = _dialog(monkeypatch, method, answer=True)
    secret = "AIza" + "p" * 35
    dialog._field.setText(secret)
    dialog._on_save()
    assert len(asked) == 1
    assert method.changes() == [(["key", "set", "google"], secret + "\n"),
                                (["key", "move-shell", "google", "--drop", "--yes"], None)]
    assert all(secret not in a for args, _ in method.calls for a in args)
    assert i18n.t("rkRemoved").format(
        place=i18n.t("rkPlaceEnv").format(file="HKCU\\Environment")) in dialog._result.text()
    assert dialog._shell.isHidden() and dialog._move.isHidden()
    dialog.close()


def test_no_leaves_the_copy_where_it_is(monkeypatch):
    method = _Method(status=_with(keystore="dpapi", exports=[_REGISTRY]))
    dialog, asked = _dialog(monkeypatch, method, answer=False)
    dialog._field.setText("AIza" + "o" * 35)
    dialog._on_save()
    assert len(asked) == 1
    assert not any(args[:2] == ["key", "move-shell"] for args, _ in method.calls)
    assert not dialog._shell.isHidden()
    dialog.close()


def _said(code):
    """The window's line for each of `move-shell --drop`'s exit codes (hub #230)."""
    from autosound_tcc.ui.tcc import i18n

    place = i18n.t("rkPlaceFile").format(file="~/.zshrc", line=3)
    return {
        0: i18n.t("rkRemoved").format(place=place),
        1: i18n.t("rkDropNothing").format(var="GEMINI_API_KEY"),
        3: i18n.t("rkNotRemoved").format(var="GEMINI_API_KEY", place=place),
        2: i18n.t("rkDropUpdate").format(var="GEMINI_API_KEY", place=place),
        None: i18n.t("rkDropNoAnswer"),
    }[code]


@pytest.mark.parametrize("code", [0, 1, 3, 2, None])
def test_the_result_is_read_from_the_exit_code(monkeypatch, code):
    """0 removed, 1 nothing to do, 3 refused or failed, 2 usage; None, no answer. Read from the
    code, not from a fresh `key status`: the status here says the copy is gone whatever the code
    — a reader of the status would say «Прибрано» for every one of them."""
    gone = _with(exports=[])
    method = _Method(after_move=gone, move_rc=code, move_out="✗ ~/.zshrc:3: the method's words")
    dialog, _ = _dialog(monkeypatch, method, answer=True)
    dialog._field.setText("AIza" + "m" * 35)
    dialog._on_save()
    assert _said(code) in dialog._result.text()
    others = [_said(c) for c in (0, 1, 3, 2, None) if c != code]
    assert not any(line in dialog._result.text() for line in others)
    if code is not None:
        assert "the method's words" in dialog._result.toolTip()
    dialog.close()


def test_another_provider_s_stored_key_no_longer_holds_the_yes(monkeypatch):
    """Under v3.0.64 a yes moved EVERY export, so an old OpenAI line beside a stored OpenAI key
    kept the question back. With one provider per command it is asked, and moves Gemini only."""
    other = {"var": "OPENAI_API_KEY", "file": "~/.zshrc", "line": 7}
    method = _Method(status=_with(keystore="dpapi", exports=[_REGISTRY, other],
                                  openai={"keystore": True, "used": "keystore"}))
    dialog, asked = _dialog(monkeypatch, method, answer=True)
    dialog._field.setText("AIza" + "h" * 35)
    dialog._on_save()
    assert len(asked) == 1
    assert [args for args, _ in method.changes() if args[:2] == ["key", "move-shell"]] == [
        ["key", "move-shell", "google", "--drop", "--yes"]]
    dialog.close()


def test_a_move_with_no_answer_stores_nothing_again(monkeypatch):
    """The re-store of v3.0.64's path is gone with the hold: one `key set`, whatever the drop
    answered."""
    method = _Method(status=_with(keystore="dpapi", exports=[_REGISTRY]), move_rc=None)
    dialog, _ = _dialog(monkeypatch, method, answer=True)
    dialog._field.setText("AIza" + "t" * 35)
    dialog._on_save()
    assert [args[:2] for args, _ in method.changes()] == [["key", "set"], ["key", "move-shell"]]
    dialog.close()


def test_an_older_method_is_never_sent_the_drop(monkeypatch):
    """v3.0.64 reads `move-shell google --drop --yes` as `move-shell --yes`: it moves AND STORES
    every export (hub #230). Its usage line has no `--drop`, so the window asks nothing, runs
    nothing, offers no «Видалити», and says to update the method."""
    from autosound_tcc.ui.tcc import i18n

    method = _Method(drops=False)
    dialog, asked = _dialog(monkeypatch, method, answer=True)
    assert dialog._drops == {}
    dialog._field.setText("AIza" + "u" * 35)
    dialog._on_save()
    assert asked == []
    assert not any(args[:2] == ["key", "move-shell"] for args, _ in method.calls)
    assert i18n.t("rkDropUpdate").format(
        var="GEMINI_API_KEY", place="~/.zshrc, рядок 3") in dialog._result.text()
    dialog.close()


def test_the_drop_is_asked_of_the_method_s_usage_once(monkeypatch):
    """Asked of what the method says it takes, not of its version number, and only once for one
    script file: the window repaints, the method does not change under it."""
    for drops in (True, False):
        method = _Method(drops=drops)
        _use(monkeypatch, method)
        assert reviewer_key.drops_exports() is drops
        assert reviewer_key.drops_exports() is drops
        assert method.calls == [(["key", "help"], None)]


def test_drop_export_names_the_provider_and_nothing_else(monkeypatch):
    method = _Method(move_rc=3, move_out="✗ refused")
    _use(monkeypatch, method)
    assert reviewer_key.drop_export("google") == (3, "✗ refused")
    assert method.calls == [(["key", "move-shell", "google", "--drop", "--yes"], None)]
    assert reviewer_key.drop_export("nobody")[0] == 2
    assert len(method.calls) == 1, "an unknown provider never reaches the method"


def test_a_copy_beside_a_key_in_the_keystore_has_a_delete(monkeypatch):
    """Finding 127, «… чи кнопку видалити»: the copy left outside the store, beside a key the
    keystore holds. Not for a key only exported (it is the only copy), and never the default."""
    from autosound_tcc.ui.tcc import i18n

    dialog, _ = _dialog(monkeypatch, _Method())
    assert list(dialog._drops) == ["google"]
    button = dialog._drops["google"]
    assert button.text() == i18n.t("rkDropCopy").format(var="GEMINI_API_KEY")
    assert not button.autoDefault() and not button.isHidden()
    dialog.close()

    dialog, _ = _dialog(monkeypatch, _Method(status=_with(
        google={"used": "env", "keystore": False})))
    assert dialog._drops == {}
    dialog.close()


def test_delete_asks_first_and_no_keeps_the_copy(monkeypatch):
    method = _Method()
    dialog, asked = _dialog(monkeypatch, method, answer=False)
    dialog._drops["google"].click()
    assert len(asked) == 1 and "GEMINI_API_KEY" in asked[0] and "~/.zshrc" in asked[0]
    assert method.changes() == []
    dialog.close()


def test_delete_drops_the_copy_and_the_button_goes_with_it(monkeypatch):
    from autosound_tcc.ui.tcc import i18n

    method = _Method(after_move=_with(exports=[]))
    dialog, _ = _dialog(monkeypatch, method, answer=True)
    dialog._drops["google"].click()
    assert method.changes() == [(["key", "move-shell", "google", "--drop", "--yes"], None)]
    assert i18n.t("rkRemoved").format(
        place=i18n.t("rkPlaceFile").format(file="~/.zshrc", line=3)) in dialog._result.text()
    assert dialog._drops == {} and dialog._shell.isHidden()
    dialog.close()


def test_the_window_opens_on_the_key_field_with_save_as_its_default(monkeypatch):
    """A dialog makes the first button in its focus chain the default — accent ring, bold, Enter.
    That was «Перенести» whenever it showed, and Enter in the key field opened the terminal."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from autosound_tcc.core import terminal_launcher

    opened = []
    monkeypatch.setattr(terminal_launcher, "run_line", opened.append)
    dialog, _ = _dialog(monkeypatch, _Method())
    dialog.show()
    QApplication.processEvents()
    assert dialog._save.isDefault() and not dialog._move.isDefault()
    QTest.keyClick(dialog._field, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert opened == []
    dialog.close()
