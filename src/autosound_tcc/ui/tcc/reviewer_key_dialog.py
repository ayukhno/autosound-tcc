"""«Ключ рецензента»: where the reviewer's key is, and a safe way to enter one (hub #197).

The screen never shows a key. It shows WHERE each provider's key is used from — the OS keystore,
the `critic-env` file, the environment, or nowhere — as the method's own `key status` reports it,
and it hands a new key to the method's `key set` over stdin (`core/reviewer_key`). A key still
exported from a shell profile is named with its file and line, beside the method's `key move-shell`,
which asks before it moves anything — so a click here opens it in a terminal and the Arbiter
answers it there, and nothing moves without his yes.

A signed-in CLI (`agy`, `claude`, `codex`) needs no key at all; the screen says so, because the
subscription route is the first one, not the fallback.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from autosound_tcc.core import critic_env, reviewer_key, terminal_launcher
from autosound_tcc.ui.tcc import i18n

_NAMES = {"google": "Google (Gemini)", "anthropic": "Anthropic (Claude)", "openai": "OpenAI"}


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
        for row, provider in enumerate(reviewer_key.PROVIDERS):
            self._grid.addWidget(QLabel(_NAMES[provider]), row, 0)
            where = QLabel("")
            where.setProperty("class", "kv-val")
            self._grid.addWidget(where, row, 1)
            self._where[provider] = where
        self._grid.setColumnStretch(2, 1)
        layout.addLayout(self._grid)

        # A key still in a shell profile: its file and line, and the method's own move.
        self._shell = QLabel("")
        self._shell.setWordWrap(True)
        self._shell.setProperty("class", "kv-warn")
        self._shell.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._shell)
        self._move = QPushButton(i18n.t("rkMove"))
        self._move.clicked.connect(self._on_move)
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
        exports = reviewer_key.shell_exports()
        self._shell.setVisible(bool(exports))
        self._move.setVisible(bool(exports))
        if exports:
            lines = [i18n.t("rkShell").format(var=e.get("var", "?"), file=e.get("file", "?"),
                                              line=e.get("line", "?")) for e in exports]
            # The command by its name; the button runs it with this machine's full paths.
            self._shell.setText("\n".join(lines) + "\nautosound_ai.py key move-shell")
        for widget in (self._provider, self._field, self._save):
            widget.setEnabled(supported)

    def _on_save(self) -> None:
        value = self._field.text()
        # The field lets go of the key whatever happens next: it is the method's to keep.
        self._field.clear()
        if not value.strip():
            return
        stored, said = reviewer_key.set_key(self._provider.currentData(), value)
        del value
        if stored:
            self._result.setText(i18n.t("rkSaved").format(where=said or "—"))
        else:
            self._result.setText(i18n.t("rkRefused").format(why=said) if said
                                 else i18n.t("rkNoAnswer"))
        self.refresh(ask=True)

    def _on_move(self) -> None:
        try:
            terminal_launcher.run_line(reviewer_key.move_shell_line())
        except (terminal_launcher.TerminalLaunchError, OSError) as exc:
            self._result.setText(str(exc))
            return
        self._result.setText(i18n.t("rkMoveOpened"))
