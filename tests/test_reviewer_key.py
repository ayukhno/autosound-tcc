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
    changed. `drops` is a method that has `move-shell <provider> --drop` (v3.0.65). `after_rm`,
    `rm_rc`, `rm_out` and `rm_err` are the same for `key rm` (tcc#127); `mute_after_rm` is a
    `key status` with no answer once it ran."""

    def __init__(self, status=_STATUS, set_rc=0, set_out="stored in the Keychain",
                 after_move=None, move_rc=0, move_out="✓ HKCU\\Environment: прибрано",
                 move_err="", drops=True, mute_after_move=False, after_rm=None, rm_rc=0,
                 rm_out="GEMINI_API_KEY: прибрано зі сховища ключів", rm_err="",
                 mute_after_rm=False):
        self.calls: list[tuple[list[str], object]] = []
        self.status, self.set_rc, self.set_out = status, set_rc, set_out
        self.after_move, self.move_rc, self.move_out, self.move_err, self.drops = (
            after_move, move_rc, move_out, move_err, drops)
        #: `key status` gives no answer once `move-shell` ran (review of #112, minor 3).
        self.mute_after_move = mute_after_move
        self.after_rm, self.rm_rc, self.rm_out, self.rm_err, self.mute_after_rm = (
            after_rm, rm_rc, rm_out, rm_err, mute_after_rm)

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
            if self.mute_after_move:
                self.status = None
            if self.move_rc is None:
                return None
            return subprocess.CompletedProcess(args, self.move_rc, self.move_out, self.move_err)
        if args[:2] == ["key", "rm"]:
            if self.after_rm is not None:
                self.status = self.after_rm
            if self.mute_after_rm:
                self.status = None
            if self.rm_rc is None:
                return None
            return subprocess.CompletedProcess(args, self.rm_rc, self.rm_out, self.rm_err)
        if args == ["key", "help"]:
            if self.drops is None:
                return None  # the probe killed at `_run`'s timeout
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


#: The method's own exit-1 line for `move-shell google --drop --yes` with no export (hub #230).
_NOTHING = "· GEMINI_API_KEY у профілях оболонки не знайдено"
_TRACEBACK = ('Traceback (most recent call last):\n  File "autosound_ai.py", line 2249, in '
              'move_shell_run\nPermissionError: [Errno 13] Permission denied: \'/Users/x/.zshrc\'')


def _said(key):
    """The window's line for each answer of `move-shell --drop` (hub #230)."""
    from autosound_tcc.ui.tcc import i18n

    place = i18n.t("rkPlaceFile").format(file="~/.zshrc", line=3)
    return i18n.t(key).format(var="GEMINI_API_KEY", place=place)


_ANSWERS = {
    "removed": (0, "✓ ~/.zshrc:3: прибрано", "", "rkRemoved"),
    "nothing to do": (1, _NOTHING, "", "rkDropNothing"),
    "refused": (3, "✗ ~/.zshrc:3: the method's words", "", "rkNotRemoved"),
    # Python's own exit 1: an exception the method did not catch (review of #112, important 1).
    "a crash": (1, "", _TRACEBACK, "rkNotRemoved"),
    # The probe said the method takes `--drop`: any other code is a failure, not an old method.
    "usage": (2, "", "key move-shell [google|anthropic|openai] [--drop] [--yes]", "rkNotRemoved"),
    "a signal": (-9, "", "", "rkNotRemoved"),
    "no answer": (None, "", "", "rkDropNoAnswer"),
}


@pytest.mark.parametrize("case", list(_ANSWERS))
def test_the_result_is_read_from_the_method_s_answer(monkeypatch, case):
    """0 removed, 1 with the method's «не знайдено» nothing to do, 3 refused; anything else — a
    crash, a usage error, a signal — not removed; None, no answer. Read from the answer, not from a
    fresh `key status`: the status here says the copy is gone whatever happened, and a reader of
    the status would say «Прибрано» for every one of them."""
    code, out, err, key = _ANSWERS[case]
    method = _Method(after_move=_with(exports=[]), move_rc=code, move_out=out, move_err=err)
    dialog, _ = _dialog(monkeypatch, method, answer=True)
    dialog._field.setText("AIza" + "m" * 35)
    dialog._on_save()
    assert _said(key) in dialog._result.text(), case
    others = {_said(k) for k in ("rkRemoved", "rkDropNothing", "rkNotRemoved", "rkDropNoAnswer",
                                 "rkDropUpdate") if k != key}
    assert not any(line in dialog._result.text() for line in others), case
    if case == "a crash":
        assert "PermissionError" in dialog._result.toolTip() and "Traceback" not in \
            dialog._result.toolTip(), "the exception's own line, not the whole traceback"
    elif out or err:
        assert (out or err) in dialog._result.toolTip(), case
    dialog.close()


def test_no_answer_stands_alone_when_the_re_read_gets_none_either(monkeypatch):
    """The drop and the `key status` after it both unanswered: the rows above empty and the blurb
    says the method cannot keep keys. The line must not send the reader there for the answer."""
    from autosound_tcc.ui.tcc import i18n

    method = _Method(move_rc=None, mute_after_move=True)
    dialog, _ = _dialog(monkeypatch, method, answer=True)
    dialog._field.setText("AIza" + "w" * 35)
    dialog._on_save()
    assert i18n.t("rkDropNoAnswer") in dialog._result.text()
    assert dialog._blurb.text().startswith(i18n.t("rkOld").split("{")[0]), "the re-read got none"
    for lang in ("uk", "en"):
        assert any(word in i18n.T[lang]["rkDropNoAnswer"] for word in ("невідомо", "unknown")), lang
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


def test_a_probe_with_no_answer_is_not_kept(monkeypatch):
    """A probe killed at the timeout is no answer about `--drop`: None for this call — not False,
    which reads «update the method» (tcc#129) — and asked again on the next."""
    method = _Method(drops=None)
    _use(monkeypatch, method)
    assert reviewer_key.drops_exports() is None
    method.drops = True
    assert reviewer_key.drops_exports() is True
    assert method.calls == [(["key", "help"], None), (["key", "help"], None)]


def test_the_probe_has_three_answers(monkeypatch):
    """tcc#129: has `--drop`, has not, did not answer. A crash and a missing script say nothing
    about `--drop` either: no answer, not «too old»."""
    for drops, want in ((True, True), (False, False), (None, None)):
        _use(monkeypatch, _Method(drops=drops))
        assert reviewer_key.drops_exports() is want, drops

    def crashed(args, *, stdin=None):
        return subprocess.CompletedProcess(args, 1, "", _TRACEBACK)

    _use(monkeypatch, crashed)
    assert reviewer_key.drops_exports() is None

    # A child that printed nothing — killed by a signal, or gone before a word — said nothing about
    # `--drop` either: no answer, not «too old», and not kept (review of #129, Minor 2).
    for code in (-9, 2, 0):
        calls = []

        def silent(args, *, stdin=None, code=code):
            calls.append(args)
            return subprocess.CompletedProcess(args, code, "", "")

        _use(monkeypatch, silent)
        assert reviewer_key.drops_exports() is None, code
        assert reviewer_key.drops_exports() is None, code
        assert len(calls) == 2, "asked again: no answer is not kept"

    from pathlib import Path

    _use(monkeypatch, _Method())
    monkeypatch.setattr(reviewer_key, "script_path", lambda: Path("/nowhere/autosound_ai.py"))
    assert reviewer_key.drops_exports() is None


def test_a_probe_with_no_answer_says_so_and_runs_once_a_window(monkeypatch):
    """tcc#129: no answer read «the method is too old», and a save ran the 20-s probe twice in a
    row on the window's thread — in the save, then in the repaint after it. Now the line says the
    method did not answer, nothing is dropped, and the probe runs at most once while the window is
    open; a new window asks again."""
    from autosound_tcc.ui.tcc import i18n

    method = _Method(status=_with(keystore="dpapi", exports=[_REGISTRY]), drops=None)
    dialog, asked = _dialog(monkeypatch, method, answer=True)
    assert dialog._drops == {}, "no Delete is offered on no answer"
    for letter in "ab":
        dialog._field.setText("AIza" + letter * 35)
        dialog._on_save()
    place = i18n.t("rkPlaceEnv").format(file="HKCU\\Environment")
    said = i18n.t("rkDropProbeNoAnswer").format(var="GEMINI_API_KEY", place=place)
    assert said in dialog._result.text()
    assert i18n.t("rkDropUpdate").format(var="GEMINI_API_KEY", place=place) \
        not in dialog._result.text()
    assert asked == [] and not any(a[:2] == ["key", "move-shell"] for a, _ in method.calls)
    assert [a for a, _ in method.calls].count(["key", "help"]) == 1
    dialog.close()

    again, _ = _dialog(monkeypatch, method, answer=True)
    assert [a for a, _ in method.calls].count(["key", "help"]) == 2
    again.close()


def test_delete_with_a_probe_that_did_not_answer_deletes_nothing(monkeypatch):
    """«Видалити ключ» with an exported copy and no answer about `--drop`: neither the drop nor
    `key rm` (the copy would be stranded), and the line says the method did not answer."""
    from autosound_tcc.ui.tcc import i18n

    method = _Method(drops=None, after_rm=_GONE)
    dialog, _ = _rm_dialog(monkeypatch, method)
    dialog._removes["google"].click()
    assert method.changes() == []
    place = i18n.t("rkPlaceFile").format(file="~/.zshrc", line=3)
    assert dialog._result.text() == " ".join((
        i18n.t("rkRmStopped").format(provider="Google (Gemini)"),
        i18n.t("rkDropProbeNoAnswer").format(var="GEMINI_API_KEY", place=place)))
    assert [a for a, _ in method.calls].count(["key", "help"]) == 1
    dialog.close()


@pytest.mark.parametrize("lang", ["uk", "en"])
def test_no_answer_is_not_called_too_old(lang):
    from autosound_tcc.ui.tcc import i18n

    said = i18n.T[lang]["rkDropProbeNoAnswer"]
    assert any(word in said for word in ("не відповів", "did not answer")), said
    assert not any(word in said for word in ("Онови", "Update")), said
    # It sits under «Збережено: …»: «nothing was touched» read as if the save had not happened
    # either (review of #129, Minor 3). The copy is what was left.
    assert not any(word in said for word in ("нічого", "nothing")), said
    assert any(word in said for word in ("копію не чіпали", "the copy was left")), said


def test_the_fake_usage_and_nothing_found_are_the_vendored_method_s_own():
    """The fakes above stand for the method's real words: its usage line names `--drop`, and its
    one honest exit 1 says «не знайдено». Pinned to the vendored source so they cannot drift."""
    from pathlib import Path

    script = (Path(__file__).resolve().parents[1] / "vendor" / "autosound-tuning-skill" / "skills"
              / "autosound-tuning" / "scripts" / "autosound_ai.py")
    if not script.is_file():
        pytest.skip("the method's submodule is not checked out")
    source = script.read_text(encoding="utf-8")
    move_shell = _USAGE_DROP[_USAGE_DROP.index("key move-shell"):]
    assert move_shell in source
    assert reviewer_key._NOTHING_FOUND in source
    assert _NOTHING.endswith(reviewer_key._NOTHING_FOUND)


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
    assert reviewer_key.drop_export("google") == (reviewer_key.NOT_DROPPED, "✗ refused")
    assert method.calls == [(["key", "move-shell", "google", "--drop", "--yes"], None)]
    assert reviewer_key.drop_export("nobody")[0] == reviewer_key.NOT_DROPPED
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


# ── VM-2 (tcc#117): a wait sign while the method's key command runs ──────────────────────────────


class _Slow(_Method):
    """`_Method`, and what the window showed while each command ran: (command, the cursor, the
    controls still on, the result line). On Windows `move-shell` writes HKCU\\Environment and the
    broadcast holds the window about five seconds (VM-2)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.window = None
        self.seen: list[tuple] = []
        #: Called while the command runs, as the Arbiter's click lands in the frozen window.
        self.meanwhile = None

    def __call__(self, args, *, stdin=None):
        cursor = QApplication.overrideCursor()
        window = self.window
        self.seen.append((" ".join(args[:2]), cursor.shape() if cursor else None,
                          None if window is None else [w for w in _controls(window) if w.isEnabled()],
                          None if window is None else window._result.text()))
        if self.meanwhile is not None:
            self.meanwhile()
        return super().__call__(args, stdin=stdin)


def _controls(window) -> list:
    """Everything in the key window a click or a key lands on — not a question box's buttons."""
    from PySide6.QtWidgets import QPushButton

    buttons = [b for b in window.findChildren(QPushButton) if b.window() is window]
    return [*buttons, window._provider, window._field]


def _slow_dialog(monkeypatch, method, *, answer=True):
    """`_dialog` over `method`, which then watches the window; the question records the cursor."""
    from autosound_tcc.ui.tcc.reviewer_key_dialog import ReviewerKeyDialog

    dialog, _asked = _dialog(monkeypatch, method)
    method.window = dialog
    asked: list = []

    def confirm(self, text, yes, **_kw):
        cursor = QApplication.overrideCursor()
        asked.append(cursor.shape() if cursor else None)
        return answer

    monkeypatch.setattr(ReviewerKeyDialog, "_confirm", confirm)
    return dialog, asked


def _settled(dialog) -> None:
    """After the command: the cursor back, and every control on again."""
    assert QApplication.overrideCursor() is None
    assert all(w.isEnabled() for w in _controls(dialog))


def test_opening_the_window_waits_under_the_wait_cursor(monkeypatch):
    """The window asks the method's `key status` before it shows (VM-2)."""
    from PySide6.QtCore import Qt

    method = _Slow()
    dialog, _ = _slow_dialog(monkeypatch, method)
    reads = [s for s in method.seen if s[0] == "key status"]
    assert reads and all(shape == Qt.CursorShape.WaitCursor for _c, shape, _on, _l in reads)
    _settled(dialog)
    dialog.close()


def test_a_save_and_its_yes_wait_with_the_buttons_off_and_say_so(monkeypatch):
    """VM-2, «Прибрати» after a save: the Arbiter, «як показати значок очікування (бо там десь
    5 сек)». Every command under the wait cursor, every button off, and the line saying what is
    running — on screen before the call blocks. The question between them is not a wait."""
    from PySide6.QtCore import Qt

    from autosound_tcc.ui.tcc import i18n

    method = _Slow(status=_with(keystore="dpapi", exports=[_REGISTRY]),
                   after_move=_with(keystore="dpapi", exports=[]))
    dialog, asked = _slow_dialog(monkeypatch, method)
    method.seen.clear()
    dialog._field.setText("AIza" + "s" * 35)
    dialog._save.click()

    wait = Qt.CursorShape.WaitCursor
    by_command = {}
    for command, shape, on, line in method.seen:
        assert (shape, on) == (wait, []), (command, shape, on)
        by_command.setdefault(command, line)
    assert by_command["key set"] == i18n.t("rkBusySave")
    assert by_command["key move-shell"] == i18n.t("rkBusyDrop")
    assert asked == [None], "the question is asked without the wait cursor"
    assert i18n.t("rkBusyDrop") not in dialog._result.text()
    _settled(dialog)
    dialog.close()


def test_delete_waits_with_the_buttons_off_and_says_so(monkeypatch):
    """VM-2, «Видалити»: the same wait for the drop, and for the status re-read after it."""
    from PySide6.QtCore import Qt

    from autosound_tcc.ui.tcc import i18n

    method = _Slow(after_move=_with(exports=[]))
    dialog, _ = _slow_dialog(monkeypatch, method)
    method.seen.clear()
    dialog._drops["google"].click()

    commands = [command for command, *_ in method.seen]
    assert "key move-shell" in commands and "key status" in commands
    for command, shape, on, line in method.seen:
        assert (shape, on, line) == (Qt.CursorShape.WaitCursor, [], i18n.t("rkBusyDrop")), command
    assert dialog._result.text().startswith(i18n.t("rkRemoved").split("{")[0])
    _settled(dialog)
    dialog.close()


def test_a_refused_save_re_reads_under_the_wait_and_keeps_its_answer(monkeypatch):
    """The status re-read after a refusal waits too, and its line gives way to the refusal."""
    from PySide6.QtCore import Qt

    from autosound_tcc.ui.tcc import i18n

    method = _Slow(set_rc=2)
    dialog, _ = _slow_dialog(monkeypatch, method)
    method.seen.clear()
    dialog._field.setText("short")
    dialog._save.click()

    assert [(c, s, on) for c, s, on, _l in method.seen] == [
        ("key set", Qt.CursorShape.WaitCursor, []), ("key status", Qt.CursorShape.WaitCursor, [])]
    assert method.seen[1][3] == i18n.t("rkBusyRead")
    assert dialog._result.text() == i18n.t("rkRefused").format(why="not a key: too short")
    _settled(dialog)
    dialog.close()


def test_a_click_made_while_the_method_runs_is_dropped(monkeypatch):
    """The window is frozen, not closed: a click the OS holds behind the busy one reaches a button
    that is still off, and is dropped — not run once the method answers."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    method = _Slow(after_move=_with(exports=[]))
    dialog, _ = _slow_dialog(monkeypatch, method)
    dialog.show()
    QApplication.processEvents()
    saves = []
    dialog._save.clicked.connect(lambda: saves.append(1))

    def click_save():
        centre = QPointF(dialog._save.rect().center())
        for kind, held in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                           (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
            QApplication.postEvent(dialog._save, QMouseEvent(
                kind, centre, centre, Qt.MouseButton.LeftButton, held,
                Qt.KeyboardModifier.NoModifier))

    method.meanwhile = click_save
    dialog._drops["google"].click()
    method.meanwhile = None
    QApplication.processEvents()
    assert saves == []
    _settled(dialog)
    # Once the method answered, a click lands again.
    dialog._save.click()
    assert saves == [1]
    dialog.close()


def test_an_older_method_still_keeps_the_entry_off_after_the_wait(monkeypatch):
    """The wait hands the controls back as the window stands: no key entry for a method that
    cannot store one."""
    method = _Slow(status=None)
    dialog, _ = _slow_dialog(monkeypatch, method)
    assert QApplication.overrideCursor() is None
    assert not dialog._save.isEnabled() and not dialog._field.isEnabled()
    assert not dialog._provider.isEnabled()
    dialog.close()


# ── tcc#127: the stored key deleted (finding 136) ─────────────────────────────────────────────────

#: `key status` once the key left the store: nothing keeps one for Google any more.
_GONE = _with(exports=[], google={"used": "none", "keystore": False, "shape": None})
#: The method's words when the Keychain refused the delete: `_keychain_delete` is `returncode == 0`,
#: so a refusal reads «його не було» — exit 0 all the same.
_NOT_THERE = "GEMINI_API_KEY: у сховищі ключів його не було"
_RM_TRACEBACK = ('Traceback (most recent call last):\n  File "autosound_ai.py", line 491, in '
                 '_dpapi_delete\nPermissionError: [Errno 13] Permission denied: \'keys.dpapi\'')


def test_remove_key_names_the_provider_and_nothing_else(monkeypatch):
    method = _Method(status=_with(exports=[]), after_rm=_GONE)
    _use(monkeypatch, method)
    assert reviewer_key.remove_key("google")[0] == reviewer_key.REMOVED
    assert method.changes() == [(["key", "rm", "google"], None)]
    assert reviewer_key.remove_key("nobody")[0] == reviewer_key.NOT_REMOVED
    assert len(method.changes()) == 1, "an unknown provider never reaches the method"


_RM_ANSWERS = {
    # (exit, out, err, status after, what happened, the copies left)
    "removed": (0, "GEMINI_API_KEY: прибрано зі сховища ключів", "", _GONE,
                reviewer_key.REMOVED, ()),
    "removed, the file still has one": (
        0, "GEMINI_API_KEY: прибрано зі сховища ключів; лишився: файл ~/.config/autosound/critic-env",
        "", _with(_GONE, google={"used": "file", "file": {"path": "critic-env", "line": 2,
                                                          "blank": False}}),
        reviewer_key.REMOVED, ("file",)),
    "removed, the environment still has one": (
        0, "GEMINI_API_KEY: прибрано зі сховища ключів; лишився: змінна середовища", "",
        _with(_GONE, google={"used": "env", "env": True}), reviewer_key.REMOVED, ("env",)),
    # Both, though the method uses the file's: each is a copy (review I2).
    "removed, the file and the environment": (
        0, "GEMINI_API_KEY: прибрано зі сховища ключів; лишився: файл, змінна середовища", "",
        _with(_GONE, google={"used": "file", "env": True, "file": {
            "path": "critic-env", "line": 2, "blank": False}}),
        reviewer_key.REMOVED, ("file", "env")),
    # A blank line in the file is the machine's choice of the CLI, not a copy of the key.
    "removed, the file blanks it": (
        0, "GEMINI_API_KEY: прибрано зі сховища ключів", "",
        _with(_GONE, google={"file": {"path": "critic-env", "line": 2, "blank": True}}),
        reviewer_key.REMOVED, ()),
    # The Keychain refused and the method said «не було»: the store answers, not the words.
    "the store kept it": (0, _NOT_THERE, "", None, reviewer_key.NOT_REMOVED, ()),
    "a crash, the store kept it": (1, "", _RM_TRACEBACK, None, reviewer_key.NOT_REMOVED, ()),
    "a crash after the delete": (1, "", _RM_TRACEBACK, _GONE, reviewer_key.REMOVED, ()),
    "no answer": (None, "", "", _GONE, None, ()),
}


@pytest.mark.parametrize("case", list(_RM_ANSWERS))
def test_what_happened_is_read_from_the_store_after_key_rm(monkeypatch, case):
    """`key rm` exits 0 whether it removed the key, found none, or the Keychain refused the delete
    — that last one in the words «його не було». So what happened is the method's `key status`
    after it: still in the store is never «видалено», and a copy in the file or the environment
    — which `key rm` leaves alone — is named, since the API still has a key while it is there."""
    code, out, err, after, happened, left = _RM_ANSWERS[case]
    method = _Method(status=_with(exports=[]), after_rm=after, rm_rc=code, rm_out=out,
                     rm_err=err)
    _use(monkeypatch, method)
    got = reviewer_key.remove_key("google")
    assert got[:2] == (happened, left), case
    if case.startswith("a crash"):
        assert got[2] == "PermissionError: [Errno 13] Permission denied: 'keys.dpapi'", case
    elif code is not None:
        assert got[2] == out, case


def test_a_key_that_was_never_stored_is_nothing_removed(monkeypatch):
    method = _Method(status=_with(_GONE, google={"used": "env", "env": True}), rm_out=_NOT_THERE)
    _use(monkeypatch, method)
    assert reviewer_key.remove_key("google")[:2] == (reviewer_key.NOT_STORED, ("env",))


def test_no_status_after_the_delete_is_no_answer(monkeypatch):
    method = _Method(status=_with(exports=[]), mute_after_rm=True)
    _use(monkeypatch, method)
    assert reviewer_key.remove_key("google")[0] is None


def test_a_removal_forgets_only_that_provider_s_api_rows(monkeypatch):
    """What the provider's API rows learned on the key goes with it — the refusal and the green
    both (the save's own rule, finding 128): a deleted key answers nothing. Another vendor's API
    row answered on its own key, and AGY's refusal is its login's: both stay (review M3)."""
    from autosound_tcc.core import availability

    api, agy, state = _api_refused()
    gpt = "api:gpt-5.5"
    availability.succeeded(api.key)
    availability.succeeded(gpt)
    availability.refused(agy.key, availability.REFUSED, "its own login")
    _use(monkeypatch, _Method(status=_with(exports=[]), after_rm=_GONE))
    assert reviewer_key.remove_key("google")[0] == reviewer_key.REMOVED
    assert state(api).ready and not availability.answered(api.key)
    assert availability.answered(gpt)
    assert state(agy).reason == availability.REFUSED


def test_a_key_the_store_kept_forgets_nothing(monkeypatch):
    from autosound_tcc.core import availability

    api, _agy, state = _api_refused()
    _use(monkeypatch, _Method(status=_with(exports=[]), rm_out=_NOT_THERE))
    assert reviewer_key.remove_key("google")[0] == reviewer_key.NOT_REMOVED
    assert state(api).reason == availability.REFUSED


def test_the_fake_key_rm_is_the_vendored_method_s_own():
    """`key rm <provider>`, one provider and nothing else on argv, exit 0 with one line — and the
    Keychain's refusal read as «не було». Pinned to the vendored source so they cannot drift."""
    from pathlib import Path

    script = (Path(__file__).resolve().parents[1] / "vendor" / "autosound-tuning-skill" / "skills"
              / "autosound-tuning" / "scripts" / "autosound_ai.py")
    if not script.is_file():
        pytest.skip("the method's submodule is not checked out")
    source = script.read_text(encoding="utf-8")
    assert 'if sub == "rm" and len(args) == 2 and args[1] in _PROVIDERS:' in source
    assert "print(key_rm(args[1]))\n        return 0" in source
    assert '"прибрано зі сховища ключів" if gone else "у сховищі ключів його не було"' in source
    assert "return r.returncode == 0" in source


def _rm_dialog(monkeypatch, method, *, answer=True):
    return _dialog(monkeypatch, method, answer=answer)


def test_a_stored_key_has_a_delete_on_its_row(monkeypatch):
    """«краще видаляти ключ, щоб користувач не переживав що будуть списувати гроші» (the Arbiter,
    finding 136): one per provider whose key the OS store holds — the one `key rm` deletes —
    never the window's default."""
    from autosound_tcc.ui.tcc import i18n

    dialog, _ = _rm_dialog(monkeypatch, _Method(status=_with(
        exports=[], openai={"used": "keystore", "keystore": True})))
    shown = [p for p, button in dialog._removes.items() if not button.isHidden()]
    assert shown == ["google", "openai"]
    button = dialog._removes["google"]
    assert button.text() == i18n.t("rkRm") and not button.autoDefault()
    dialog.close()

    dialog, _ = _rm_dialog(monkeypatch, _Method(status=_with(
        exports=[], google={"used": "file", "keystore": False})))
    assert all(button.isHidden() for button in dialog._removes.values()), "nothing stored"
    dialog.close()


def test_delete_asks_first_naming_the_provider_and_what_stops(monkeypatch):
    from autosound_tcc.ui.tcc import i18n

    method = _Method(status=_with(exports=[]), after_rm=_GONE)
    dialog, asked = _rm_dialog(monkeypatch, method, answer=False)
    dialog._removes["google"].click()
    assert len(asked) == 1 and "Google (Gemini)" in asked[0] and "API" in asked[0]
    assert i18n.t("rkPlaceStore") in asked[0]
    assert method.changes() == []
    dialog.close()


def test_delete_from_the_store_only_says_nothing_is_charged(monkeypatch):
    from autosound_tcc.ui.tcc import i18n

    method = _Method(status=_with(exports=[]), after_rm=_GONE)
    dialog, _ = _rm_dialog(monkeypatch, method)
    dialog._removes["google"].click()
    assert method.changes() == [(["key", "rm", "google"], None)]
    name = "Google (Gemini)"
    assert dialog._result.text() == " ".join((
        i18n.t("rkRmDone").format(provider=name, places=i18n.t("rkPlaceStore")),
        i18n.t("rkRmFree").format(provider=name)))
    assert "прибрано" in dialog._result.toolTip(), "the method's own words on hover"
    assert dialog._removes["google"].isHidden()
    assert dialog._where["google"].text() == i18n.t("rkUsed_none")
    dialog.close()


def test_an_exported_copy_is_dropped_before_the_key_leaves_the_store(monkeypatch):
    """Review I2: `--drop` refuses once the store no longer holds the key — the copy would be the
    only one — and the window would be left with `move-shell`, which stores the key again. So the
    question names both places, the copy goes first, then `key rm`; and TCC's own copy of the
    variable, whose source is gone, goes with it."""
    from autosound_tcc.ui.tcc import i18n

    monkeypatch.setenv("GEMINI_API_KEY", "a-copy-tcc-was-started-with")
    method = _Method(after_move=_with(exports=[]), after_rm=_GONE)
    dialog, asked = _rm_dialog(monkeypatch, method)
    dialog._removes["google"].click()
    place = i18n.t("rkPlaceFile").format(file="~/.zshrc", line=3)
    places = f"{i18n.t('rkPlaceStore')}; {place}"
    assert len(asked) == 1 and places in asked[0]
    assert method.changes() == [(["key", "move-shell", "google", "--drop", "--yes"], None),
                                (["key", "rm", "google"], None)]
    assert "GEMINI_API_KEY" not in os.environ
    name = "Google (Gemini)"
    assert dialog._result.text() == " ".join((
        i18n.t("rkRmDone").format(provider=name, places=places),
        i18n.t("rkRmFree").format(provider=name)))
    dialog.close()


_STOPS = {
    "refused": (3, "rkNotRemoved"),
    "a crash": (1, "rkNotRemoved"),
    "no answer": (None, "rkDropNoAnswer"),
}


@pytest.mark.parametrize("case", list(_STOPS))
def test_a_copy_that_was_not_dropped_stops_the_delete(monkeypatch, case):
    """Without the copy gone, `key rm` would strand it: the delete stops there and says so, and
    the key stays in the store — and TCC's own variable stays too."""
    from autosound_tcc.ui.tcc import i18n

    monkeypatch.setenv("GEMINI_API_KEY", "a-copy-tcc-was-started-with")
    code, key = _STOPS[case]
    method = _Method(move_rc=code, move_out="✗ the method's words", after_rm=_GONE)
    dialog, _ = _rm_dialog(monkeypatch, method)
    dialog._removes["google"].click()
    assert method.changes() == [(["key", "move-shell", "google", "--drop", "--yes"], None)]
    place = i18n.t("rkPlaceFile").format(file="~/.zshrc", line=3)
    assert dialog._result.text() == " ".join((
        i18n.t("rkRmStopped").format(provider="Google (Gemini)"),
        i18n.t(key).format(var="GEMINI_API_KEY", place=place)))
    assert os.environ.get("GEMINI_API_KEY") == "a-copy-tcc-was-started-with"
    assert not dialog._removes["google"].isHidden(), "the key is still there to delete"
    dialog.close()


def test_an_older_method_with_a_copy_deletes_nothing(monkeypatch):
    """v3.0.64 would move and store every export for `--drop` (hub #230): no drop is sent, and no
    `key rm` either, since it would strand the copy."""
    from autosound_tcc.ui.tcc import i18n

    method = _Method(drops=False, after_rm=_GONE)
    dialog, _ = _rm_dialog(monkeypatch, method)
    dialog._removes["google"].click()
    assert method.changes() == []
    assert i18n.t("rkDropUpdate").format(
        var="GEMINI_API_KEY", place="~/.zshrc, рядок 3") in dialog._result.text()
    dialog.close()


def test_a_copy_the_window_cannot_remove_is_named_before_and_after(monkeypatch):
    """A key line in critic-env, and the environment TCC was started with when no export explains
    it: no command here removes them. The question says they stay; the line after names them and
    never says «нічого не списується»."""
    from autosound_tcc.ui.tcc import i18n

    copies = {"file": {"path": "critic-env", "line": 2, "blank": False}, "env": True}
    method = _Method(status=_with(exports=[], google=copies),
                     after_rm=_with(_GONE, google=copies))
    dialog, asked = _rm_dialog(monkeypatch, method)
    dialog._removes["google"].click()
    where = f"{i18n.t('rkLeft_file')}; {i18n.t('rkLeft_env')}"
    assert i18n.t("rkRmAskKept").format(where=where) in asked[0]
    name = "Google (Gemini)"
    assert dialog._result.text() == " ".join((
        i18n.t("rkRmDone").format(provider=name, places=i18n.t("rkPlaceStore")),
        i18n.t("rkRmLeft").format(where=where)))
    assert i18n.t("rkRmFree").format(provider=name) not in dialog._result.text()
    dialog.close()


@pytest.mark.parametrize("lang", ["uk", "en"])
@pytest.mark.parametrize("case,line", [
    ("removed", "rkRmDone"),
    ("removed, the file still has one", "rkRmDone"),
    ("removed, the environment still has one", "rkRmDone"),
    ("removed, the file and the environment", "rkRmDone"),
    ("the store kept it", "rkRmFailed"),
    ("a crash, the store kept it", "rkRmFailed"),
    ("no answer", "rkRmNoAnswer"),
])
def test_the_line_after_a_delete_is_true_on_every_answer(monkeypatch, lang, case, line):
    """No false «видалено» and no false «нічого не списується»: a store that kept the key, a crash
    or no answer each says its own line, and a copy left anywhere is named in place of the claim."""
    from autosound_tcc.ui.tcc import i18n

    code, out, err, after, _happened, left = _RM_ANSWERS[case]
    method = _Method(status=_with(exports=[]), after_rm=after, rm_rc=code, rm_out=out,
                     rm_err=err)
    dialog, _ = _rm_dialog(monkeypatch, method, answer=True)
    i18n.set_language(lang)
    dialog._removes["google"].click()
    text = dialog._result.text()
    name = "Google (Gemini)"
    assert text.startswith(i18n.t(line).format(provider=name, places=i18n.t("rkPlaceStore"))), \
        (case, text)
    free = i18n.t("rkRmFree").format(provider=name)
    assert (free in text) == (line == "rkRmDone" and not left), case
    if left:
        where = "; ".join(i18n.t(f"rkLeft_{w}") for w in left)
        assert i18n.t("rkRmLeft").format(where=where) in text, case
    else:
        assert i18n.t("rkRmLeft").split("{")[0] not in text, case
    dialog.close()


def test_delete_key_waits_with_the_buttons_off_and_says_so(monkeypatch):
    """VM-2's wait for `key rm` and the re-read after it: the wait cursor, every control off, and
    the line saying what runs."""
    from PySide6.QtCore import Qt

    from autosound_tcc.ui.tcc import i18n

    method = _Slow(status=_with(exports=[]), after_rm=_GONE)
    dialog, _ = _slow_dialog(monkeypatch, method)
    method.seen.clear()
    dialog._removes["google"].click()

    commands = [command for command, *_ in method.seen]
    assert commands[0] == "key rm" and "key status" in commands
    for command, shape, on, line in method.seen:
        assert (shape, on, line) == (Qt.CursorShape.WaitCursor, [], i18n.t("rkBusyRm")), command
    _settled(dialog)
    dialog.close()

    # And with a copy to drop first: the drop, `key rm` and the re-reads, one wait.
    method = _Slow(after_move=_with(exports=[]), after_rm=_GONE)
    dialog, _ = _slow_dialog(monkeypatch, method)
    method.seen.clear()
    dialog._removes["google"].click()
    commands = [command for command, *_ in method.seen]
    assert commands.index("key move-shell") < commands.index("key rm")
    for command, shape, on, line in method.seen:
        assert (shape, on, line) == (Qt.CursorShape.WaitCursor, [], i18n.t("rkBusyRm")), command
    _settled(dialog)
    dialog.close()


# ── Ruling 42 (W-5, #129 review): every key call waits, and a call that raises gives it all back ──


class _Raising(_Method):
    """`_Method`, with one command that raises instead of answering — past `_run`'s own catch."""

    def __init__(self, raises: str = "", **kwargs):
        super().__init__(**kwargs)
        self.raises = raises

    def __call__(self, args, *, stdin=None):
        if self.raises and " ".join(args[:2]) == self.raises:
            raise RuntimeError("the method's child blew up")
        return super().__call__(args, stdin=stdin)


def test_opening_on_a_call_that_raises_gives_the_cursor_back(monkeypatch):
    from autosound_tcc.ui.tcc.reviewer_key_dialog import ReviewerKeyDialog

    _dialog(monkeypatch, _Raising())[0].close()
    _use(monkeypatch, _Raising(raises="key status"))
    with pytest.raises(RuntimeError):
        ReviewerKeyDialog()
    assert QApplication.overrideCursor() is None


@pytest.mark.parametrize("act,raises,status", [
    ("re-read", "key status", _STATUS),
    ("save", "key set", _STATUS),
    ("save, the probe", "key help", _STATUS),
    ("delete the copy", "key move-shell", _STATUS),
    ("delete the key, its copy first", "key move-shell", _STATUS),
    ("delete the key", "key rm", _with(exports=[])),
])
def test_a_key_call_that_raises_gives_the_cursor_and_the_buttons_back(monkeypatch, act, raises,
                                                                      status):
    """Ruling 42: the key calls stay on the window's thread, under the wait cursor with every
    button off — and whatever the call does, the cursor comes back and the buttons go on again."""
    method = _Raising(status=status)
    dialog, _ = _dialog(monkeypatch, method, answer=True)
    dialog.show()
    QApplication.processEvents()
    if raises == "key help":
        reviewer_key._DROPS = None
    method.raises = raises
    with pytest.raises(RuntimeError):
        if act == "re-read":
            dialog.refresh(ask=True)
        elif act.startswith("save"):
            dialog._field.setText("AIza" + "r" * 35)
            dialog._on_save()
        elif act == "delete the copy":
            dialog._on_drop("google")
        else:
            dialog._on_remove("google")
    _settled(dialog)
    dialog.close()


def test_a_read_the_kept_answer_cannot_give_waits_too(monkeypatch):
    """A read of the kept answer starts the method's `key status` when something forgot the answer:
    then it is a key call like any other, and waits — the repaint after a save, and the reads
    before a delete's question."""
    from PySide6.QtCore import Qt

    method = _Slow()
    dialog, _ = _slow_dialog(monkeypatch, method, answer=False)
    for act in (dialog.refresh, lambda: dialog._on_drop("google"),
                lambda: dialog._on_remove("google")):
        reviewer_key.forget()
        method.seen.clear()
        act()
        assert [c for c, *_ in method.seen] == ["key status"]
        assert all((shape, on) == (Qt.CursorShape.WaitCursor, [])
                   for _c, shape, on, _l in method.seen), method.seen
        _settled(dialog)
    dialog.close()
