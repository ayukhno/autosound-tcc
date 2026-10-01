"""«Ключ рецензента»: where the reviewer's key is, and a safe way to enter one (hub #197).

The screen never shows a key. It shows WHERE each provider's key is used from — the OS keystore,
the `critic-env` file, the environment, or nowhere — as the method's own `key status` reports it,
and it hands a new key to the method's `key set` over stdin (`core/reviewer_key`). A key still
exported from a shell profile is named with its file and line — on Windows, from the user's
environment variables, which have no line — beside the method's `key move-shell`, which asks before
it moves anything — so a click here opens it in a terminal and the Arbiter answers it there, and
nothing moves without his yes.

A save that leaves such a copy behind asks here whether to take it out, and a key in the store can
be deleted from it (`key rm`) — both the method's commands, never TCC's own edit (tcc#117).

A signed-in CLI (`agy`, `claude`, `codex`) needs no key at all; the screen says so, because the
subscription route is the first one, not the fallback.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from autosound_tcc.core import critic_env, reviewer_key, terminal_launcher
from autosound_tcc.ui.tcc import i18n

_NAMES = {"google": "Google (Gemini)", "anthropic": "Anthropic (Claude)", "openai": "OpenAI"}

#: Around the label of a plain button: `padding: 5px 14px` and a 1 px border on each side (theme.py,
#: "every button nobody gave a class to"), and a few pixels to spare.
_BUTTON_CHROME_PX = 2 * (14 + 1) + 8


def _fit_tinted(button: QPushButton) -> None:
    """Wide enough for the label in its TINTED state, not only its plain one (finding 126, tcc#117).

    A dialog makes its first or focused button the default, and `QPushButton:default` is
    `font-weight: 600`: the bold label is wider than the one `sizeHint` measured, and on Windows
    «Перенести (відкриє термінал)» lost a letter on each side. So the label is measured bold.
    """
    button.ensurePolished()
    bold = QFont(button.font())
    bold.setWeight(QFont.Weight.DemiBold)
    button.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(button.text()) + _BUTTON_CHROME_PX)


def _place(export: dict) -> str:
    """Where an exported copy sits, in words: `~/.zshrc, line 3`, or the Windows environment."""
    file = export.get("file", "?")
    # The registry has no line: the method marks it `line: None` (finding 125, tcc#117).
    if export.get("line") is None:
        return i18n.t("rkPlaceEnv").format(file=file)
    return i18n.t("rkPlaceFile").format(file=file, line=export["line"])


def _shell_line(export: dict) -> str:
    var, file = export.get("var", "?"), export.get("file", "?")
    if export.get("line") is None:
        # A Windows user variable: every program the user starts reads it, not only one started
        # from a terminal — and it has no line to print (finding 125, tcc#117).
        return i18n.t("rkShellEnv").format(var=var, file=file)
    return i18n.t("rkShell").format(var=var, file=file, line=export["line"])


class ReviewerKeyDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.t("rkTitle"))
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self._blurb = QLabel("")
        self._blurb.setWordWrap(True)
        self._blurb.setProperty("class", "fb-hint")
        layout.addWidget(self._blurb)

        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(16)
        self._where: dict[str, QLabel] = {}
        self._delete: dict[str, QPushButton] = {}
        for row, provider in enumerate(reviewer_key.PROVIDERS):
            self._grid.addWidget(QLabel(_NAMES[provider]), row, 0)
            where = QLabel("")
            where.setProperty("class", "kv-val")
            self._grid.addWidget(where, row, 1)
            self._where[provider] = where
            # A key in the store can leave it again: the method's `key rm` (finding 127).
            delete = QPushButton(i18n.t("rkDelete"))
            # Never the dialog's default: first in the focus chain, it took the accent ring and
            # Enter — and a delete is not the answer this window expects.
            delete.setAutoDefault(False)
            delete.clicked.connect(lambda _checked=False, p=provider: self._on_delete(p))
            _fit_tinted(delete)
            delete.setVisible(False)
            self._grid.addWidget(delete, row, 2)
            self._delete[provider] = delete
        self._grid.setColumnStretch(3, 1)
        layout.addLayout(self._grid)

        # A key still in a shell profile: its file and line, and the method's own move.
        self._shell = QLabel("")
        self._shell.setWordWrap(True)
        self._shell.setProperty("class", "kv-warn")
        self._shell.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._shell)
        self._move = QPushButton(i18n.t("rkMove"))
        self._move.clicked.connect(self._on_move)
        _fit_tinted(self._move)
        layout.addWidget(self._move, 0, Qt.AlignmentFlag.AlignLeft)

        entry = QHBoxLayout()
        self._provider = QComboBox()
        for provider in reviewer_key.PROVIDERS:
            self._provider.addItem(_NAMES[provider], provider)
        entry.addWidget(self._provider)
        self._field = QLineEdit()
        self._field.setEchoMode(QLineEdit.EchoMode.Password)
        self._field.setPlaceholderText(i18n.t("rkPlaceholder"))
        self._field.returnPressed.connect(self._on_save)
        entry.addWidget(self._field, 1)
        self._save = QPushButton(i18n.t("rkSave"))
        self._save.clicked.connect(self._on_save)
        _fit_tinted(self._save)
        entry.addWidget(self._save)
        layout.addLayout(entry)

        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._result)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(i18n.t("rkClose"))
        layout.addWidget(buttons)

        self.refresh(ask=True)
        # The window opens on the key field, so its default is «Зберегти», the button after it —
        # not whichever button comes first in the focus chain («Видалити», «Перенести»).
        self._field.setFocus()

    def refresh(self, *, ask: bool = False) -> None:
        """Show what the method says now. `ask` re-runs `key status` instead of the kept answer."""
        answer = reviewer_key.status(refresh=ask)
        supported = answer is not None
        if not supported:
            self._blurb.setText(i18n.t("rkOld").format(path=critic_env.machine_config_path()))
        else:
            store = answer.get("keystore") or "none"
            where = i18n.t(f"rkStore_{store}" if store in ("keychain", "dpapi") else "rkStore_none")
            self._blurb.setText(i18n.t("rkBlurb").format(store=where))
        providers = (answer or {}).get("providers", {})
        for provider, label in self._where.items():
            entry = providers.get(provider) if isinstance(providers.get(provider), dict) else {}
            used = entry.get("used", "none") if supported else ""
            label.setText(i18n.t(f"rkUsed_{used}") if used in ("keystore", "file", "env", "none")
                          else "—")
            self._delete[provider].setVisible(supported and entry.get("keystore") is True)
        exports = reviewer_key.shell_exports()
        self._shell.setVisible(bool(exports))
        self._move.setVisible(bool(exports))
        if exports:
            lines = [_shell_line(e) for e in exports]
            # The command by its name; the button runs it with this machine's full paths.
            self._shell.setText("\n".join(lines) + "\nautosound_ai.py key move-shell")
        for widget in (self._provider, self._field, self._save):
            widget.setEnabled(supported)

    @staticmethod
    def _entry(provider) -> dict:
        """The method's line for `provider` in its `key status`, or {} without one."""
        entry = ((reviewer_key.status() or {}).get("providers") or {}).get(provider)
        return entry if isinstance(entry, dict) else {}

    def _where_now(self, provider) -> str:
        """`GEMINI_API_KEY — in the secure store (this Mac's Keychain)`, or "" with no answer."""
        answer = reviewer_key.status(refresh=True) or {}
        entry = (answer.get("providers") or {}).get(provider)
        if not isinstance(entry, dict) or entry.get("used") not in ("keystore", "file", "env"):
            return ""
        where = i18n.t(f"rkUsed_{entry['used']}")
        store = answer.get("keystore")
        if entry["used"] == "keystore" and store in ("keychain", "dpapi"):
            where = f"{where} ({i18n.t(f'rkStore_{store}')})"
        return f"{entry.get('var') or provider} — {where}"

    def _on_save(self) -> None:
        value = self._field.text()
        # The field lets go of the key whatever happens next: it is the method's to keep.
        self._field.clear()
        if not value.strip():
            return
        provider = self._provider.currentData()
        stored, said = reviewer_key.set_key(provider, value)
        if not stored:
            del value
            self._result.setText(i18n.t("rkRefused").format(why=said) if said
                                 else i18n.t("rkNoAnswer"))
            self.refresh(ask=True)
            return
        # In the window's language, from the method's answer; the method's own sentence is
        # Ukrainian whatever the window speaks, so it is the hover (finding 42, tcc#65).
        lines = [i18n.t("rkSaved").format(where=self._where_now(provider) or said or "—")]
        tips = [said]
        # Stored — and the same variable still exported: the copy every program reads stays
        # behind unless asked about (finding 127, tcc#117). `value` is held until the answer,
        # and no longer: the method's move stores the EXPORTED value, which may be an older key
        # than the one just pasted, so the pasted one goes back over it.
        copies = self._copies_left(provider)
        if copies and self._confirm(self._remove_question(copies), i18n.t("rkRemoveYes"),
                                    default_yes=True):
            line, tip = self._remove_copies(provider, value, copies)
            lines.append(line)
            tips.append(tip)
        del value
        self._result.setText("\n".join(lines))
        self._result.setToolTip("\n".join(tip for tip in tips if tip))
        # The kept answer is current: `_where_now` asked, and each change after it dropped the
        # answer and the next read asked again. Asking once more is a second child for nothing.
        self.refresh()

    def _copies_left(self, provider) -> list[dict]:
        """The exports of `provider`'s variable, when its key is also stored — or []."""
        entry = self._entry(provider)
        if entry.get("used") not in ("keystore", "file"):
            return []
        return [e for e in reviewer_key.shell_exports() if e.get("var") == entry.get("var")]

    def _remove_question(self, copies: list[dict]) -> str:
        var = copies[0].get("var", "?")
        text = i18n.t("rkRemoveAsk").format(var=var, place="; ".join(_place(e) for e in copies))
        # `key move-shell` takes every export, not one: the others are named before the yes.
        others = [e for e in reviewer_key.shell_exports() if e.get("var") != var]
        if others:
            text += " " + i18n.t("rkRemoveAlso").format(
                others=", ".join(f"{e.get('var', '?')} ({_place(e)})" for e in others))
        return text

    def _remove_copies(self, provider, value: str, copies: list[dict]) -> tuple[str, str]:
        """Move the copies out through the method, put the pasted key back, say where it stands."""
        moved, said = reviewer_key.move_exports()
        line = ""
        if moved:
            again, why = reviewer_key.set_key(provider, value)
            if not again:
                line = "\n" + (i18n.t("rkRefused").format(why=why) if why
                               else i18n.t("rkNoAnswer"))
        # Read back, not assumed from the yes: the method leaves a line that sets the key by an
        # expression, and says so in its own words — the hover.
        var = copies[0].get("var", "?")
        left = [e for e in reviewer_key.shell_exports() if e.get("var") == var]
        place = "; ".join(_place(e) for e in (left or copies))
        head = (i18n.t("rkNotRemoved").format(var=var, place=place) if left
                else i18n.t("rkRemoved").format(place=place))
        return head + line, said

    def _on_delete(self, provider) -> None:
        var = self._entry(provider).get("var") or provider
        if not self._confirm(i18n.t("rkDeleteAsk").format(var=var), i18n.t("rkDelete"),
                             default_yes=False):
            return
        removed, said = reviewer_key.remove_key(provider)
        entry = self._entry(provider)  # asked again: `remove_key` dropped the kept answer
        if not removed or entry.get("keystore"):
            text = i18n.t("rkNotDeleted").format(var=var)
        elif entry.get("used") in ("file", "env"):
            text = i18n.t("rkDeletedLeft").format(var=var, where=i18n.t(f"rkUsed_{entry['used']}"))
        else:
            text = i18n.t("rkDeleted").format(var=var)
        self._result.setText(text)
        self._result.setToolTip(said)
        self.refresh()

    def _confirm(self, text: str, yes: str, *, default_yes: bool) -> bool:
        """A yes or a no, in the window's language. Its own method, so a test can answer it."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(i18n.t("rkTitle"))
        box.setText(text)
        accept = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
        keep = box.addButton(i18n.t("rkKeep"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(accept if default_yes else keep)
        box.exec()
        return box.clickedButton() is accept

    def _on_move(self) -> None:
        try:
            terminal_launcher.run_line(reviewer_key.move_shell_line())
        except (terminal_launcher.TerminalLaunchError, OSError) as exc:
            self._result.setText(str(exc))
            return
        self._result.setText(i18n.t("rkMoveOpened"))
