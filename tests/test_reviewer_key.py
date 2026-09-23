"""The reviewer's key, as the method reports it (hub #197, SKL-051)."""

from __future__ import annotations

import json
import os
import subprocess

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
    """The method's script, as far as `reviewer_key` sees it: argv and stdin in, an answer out."""

    def __init__(self, status=_STATUS, set_rc=0, set_out="stored in the Keychain"):
        self.calls: list[tuple[list[str], object]] = []
        self.status, self.set_rc, self.set_out = status, set_rc, set_out

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
        raise AssertionError(args)


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
