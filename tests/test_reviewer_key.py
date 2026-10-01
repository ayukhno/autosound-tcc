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


class _Method:
    """The method's script, as far as `reviewer_key` sees it: argv and stdin in, an answer out.

    `after_move` / `after_rm` are what `key status` says once `key move-shell` / `key rm` ran."""

    def __init__(self, status=_STATUS, set_rc=0, set_out="stored in the Keychain",
                 after_move=None, after_rm=None):
        self.calls: list[tuple[list[str], object]] = []
        self.status, self.set_rc, self.set_out = status, set_rc, set_out
        self.after_move, self.after_rm = after_move, after_rm

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
            return subprocess.CompletedProcess(args, 0, "✓ HKCU\\Environment: moved", "")
        if args[:2] == ["key", "rm"]:
            if self.after_rm is not None:
                self.status = self.after_rm
            return subprocess.CompletedProcess(
                args, 0, f"{args[2]}: прибрано зі сховища ключів", "")
        raise AssertionError(args)


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
    assert method.calls[-2][1] == secret + "\n"
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


def test_the_remove_offer_needs_a_stored_key_and_a_live_export(monkeypatch):
    """Finding 127: «треба мати питання чи видалити ключ … коли ключ вже є в сховищі і при цьому
    ще є в файлі». Asked after a save, only when both hold."""
    secret = "AIza" + "q" * 35
    cases = {
        "stored + exported": (_Method(status=_with(keystore="dpapi", exports=[_REGISTRY])), 1),
        "nothing exported": (_Method(status=_with(exports=[])), 0),
        "another var exported": (_Method(status=_with(exports=[
            {"var": "OPENAI_API_KEY", "file": "~/.zshrc", "line": 7}])), 0),
        "not stored (refused)": (_Method(set_rc=2), 0),
        "not stored (env only)": (
            _Method(status=_with(google={"used": "env", "keystore": False})), 0),
    }
    for name, (method, want) in cases.items():
        dialog, asked = _dialog(monkeypatch, method)
        dialog._field.setText(secret)
        dialog._on_save()
        assert len(asked) == want, name
        assert all(secret not in text for text in asked), name
        dialog.close()


def test_the_question_names_the_place_and_every_key_the_move_takes(monkeypatch):
    """`key move-shell` takes every export, not one: the others are named before the yes."""
    other = {"var": "OPENAI_API_KEY", "file": "~/.zshrc", "line": 7}
    dialog, asked = _dialog(monkeypatch, _Method(status=_with(exports=[_REGISTRY, other])))
    dialog._field.setText("AIza" + "n" * 35)
    dialog._on_save()
    assert len(asked) == 1
    assert "GEMINI_API_KEY" in asked[0] and "HKCU\\Environment" in asked[0]
    assert "OPENAI_API_KEY (~/.zshrc, рядок 7)" in asked[0]
    dialog.close()


def test_yes_moves_the_copy_out_and_keeps_the_pasted_key(monkeypatch):
    """The method's move stores the EXPORTED value — maybe an older key than the one just pasted —
    so the pasted one is stored again after it. Nothing but the provider goes on argv."""
    from autosound_tcc.ui.tcc import i18n

    gone = _with(keystore="dpapi", exports=[])
    method = _Method(status=_with(keystore="dpapi", exports=[_REGISTRY]), after_move=gone)
    dialog, asked = _dialog(monkeypatch, method, answer=True)
    secret = "AIza" + "p" * 35
    dialog._field.setText(secret)
    dialog._on_save()
    assert len(asked) == 1
    calls = [(args, stdin) for args, stdin in method.calls if args[:2] != ["key", "status"]]
    assert calls == [(["key", "set", "google"], secret + "\n"),
                     (["key", "move-shell", "--yes"], None),
                     (["key", "set", "google"], secret + "\n")]
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


def test_a_copy_the_method_did_not_move_is_said_to_be_still_there(monkeypatch):
    """`move-shell` leaves a line that sets the key by an expression, and says so; the window
    reads where the key is afterwards rather than trusting the yes."""
    from autosound_tcc.ui.tcc import i18n

    exported = _with(exports=[{"var": "GEMINI_API_KEY", "file": "~/.zshrc", "line": 3}])
    method = _Method(status=exported, after_move=exported)
    dialog, _ = _dialog(monkeypatch, method, answer=True)
    dialog._field.setText("AIza" + "m" * 35)
    dialog._on_save()
    assert i18n.t("rkNotRemoved").format(
        var="GEMINI_API_KEY", place="~/.zshrc, рядок 3") in dialog._result.text()
    dialog.close()


def test_remove_key_names_the_provider_only(monkeypatch):
    """`key rm <provider>` over argv: there is no value to send, and none is."""
    method = _Method()
    _use(monkeypatch, method)
    reviewer_key.status()
    removed, said = reviewer_key.remove_key("google")
    assert removed and said == "google: прибрано зі сховища ключів"
    assert method.calls[-1] == (["key", "rm", "google"], None)
    reviewer_key.status()
    assert method.calls[-1][0][:2] == ["key", "status"], "a removal drops the kept answer"
    assert reviewer_key.remove_key("nobody") == (False, "unknown provider 'nobody'")
    assert not any(args[:2] == ["key", "rm"] and args[2] == "nobody" for args, _ in method.calls)


def test_a_stored_key_has_a_delete_and_only_a_stored_one(monkeypatch):
    dialog, _ = _dialog(monkeypatch, _Method())
    assert not dialog._delete["google"].isHidden()
    assert dialog._delete["anthropic"].isHidden() and dialog._delete["openai"].isHidden()
    dialog.close()


def test_delete_asks_then_runs_key_rm_and_says_what_is_left(monkeypatch):
    from autosound_tcc.ui.tcc import i18n

    after = _with(exports=[], google={"used": "env", "keystore": False, "env": True})
    method = _Method(status=_with(exports=[]), after_rm=after)
    dialog, asked = _dialog(monkeypatch, method, answer=True)
    dialog._delete["google"].click()
    assert len(asked) == 1 and "GEMINI_API_KEY" in asked[0]
    assert (["key", "rm", "google"], None) in method.calls
    assert dialog._result.text() == i18n.t("rkDeletedLeft").format(
        var="GEMINI_API_KEY", where=i18n.t("rkUsed_env"))
    assert dialog._delete["google"].isHidden()
    dialog.close()


def test_delete_answered_no_removes_nothing(monkeypatch):
    method = _Method(status=_with(exports=[]))
    dialog, asked = _dialog(monkeypatch, method, answer=False)
    dialog._delete["google"].click()
    assert len(asked) == 1
    assert not any(args[:2] == ["key", "rm"] for args, _ in method.calls)
    assert not dialog._delete["google"].isHidden()
    dialog.close()


def test_the_window_opens_on_the_key_field_with_save_as_its_default(monkeypatch):
    """A dialog makes the first button in its focus chain the default — accent ring, bold, Enter.
    With «Видалити» first in the grid that was the delete; the window is for entering a key."""
    dialog, _ = _dialog(monkeypatch, _Method())
    dialog.show()
    QApplication.processEvents()
    assert dialog._save.isDefault()
    assert not any(button.isDefault() for button in dialog._delete.values())
    assert not dialog._move.isDefault()
    dialog.close()
