"""«Ключ рецензента»: where the reviewer's key is, and a safe way to enter one (hub #197).

The screen never shows a key. It shows WHERE each provider's key is used from — the OS keystore,
the `critic-env` file, the environment, or nowhere — as the method's own `key status` reports it,
and it hands a new key to the method's `key set` over stdin (`core/reviewer_key`). A key still
exported from a shell profile is named with its file and line — on Windows, from the user's
environment variables, which have no line — beside the method's `key move-shell`, which asks before
it moves anything — so a click here opens it in a terminal and the Arbiter answers it there, and
nothing moves without his yes.

A save that leaves such a copy behind asks here whether to take it out, and a copy beside a key
the OS keystore holds has «Видалити копію …» (finding 127, tcc#117): both through the method's own
`key move-shell <provider> --drop` (v3.0.65, hub #230), which removes that one export without
storing it — never TCC's own edit, and no pasted key held across the question.

A key the OS keystore holds has «Видалити ключ» on its row (finding 136, tcc#127): after a yes
that names every place the key is, an exported copy goes first (`move-shell <provider> --drop`,
while the store still holds the key), then the method's own `key rm <provider>`. The line after it
is read from the store, not from the exit, and names any copy still left.

A signed-in CLI (`agy`, `claude`, `codex`) needs no key at all; the screen says so, because the
subscription route is the first one, not the fallback.

Each of the method's `key` commands holds the window while it runs — on Windows `move-shell` writes
HKCU\\Environment and the broadcast takes about five seconds — so it runs under the wait cursor,
with every control off and a line saying what is running (VM-2, `_busy`). In the window's own
thread: the flow is one sequence with a question in the middle, and the pasted key is let go of
before that question; a worker would have to carry both across.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
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
        #: How many of the method's commands are running now (`_busy`); the controls are off then.
        self._busy_depth = 0
        #: Whether the method here can take a key (`refresh`): the entry is off when it cannot.
        self._supported = False
        #: The `--drop` probe went unanswered once while this window is open (`_takes_drop`).
        self._probe_silent = False
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
        #: «Видалити ключ» on each provider's row, shown while the OS keystore holds its key (`_show`).
        self._removes: dict[str, QPushButton] = {}
        for row, provider in enumerate(reviewer_key.PROVIDERS):
            self._grid.addWidget(QLabel(_NAMES[provider]), row, 0)
            where = QLabel("")
            where.setProperty("class", "kv-val")
            self._grid.addWidget(where, row, 1)
            self._where[provider] = where
            remove = QPushButton(i18n.t("rkRm"))
            # Never the dialog's default: Enter in the key field saves (see below).
            remove.setAutoDefault(False)
            remove.clicked.connect(lambda _checked=False, p=provider: self._on_remove(p))
            _fit_tinted(remove)
            remove.setVisible(False)
            self._grid.addWidget(remove, row, 2, Qt.AlignmentFlag.AlignLeft)
            self._removes[provider] = remove
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
        _fit_tinted(self._move)
        layout.addWidget(self._move, 0, Qt.AlignmentFlag.AlignLeft)
        # Under it, «Видалити копію …» per provider whose key the keystore holds (`_show_drops`):
        # one to a row, so two or three of them never crowd the window's width.
        self._drop_rows = QVBoxLayout()
        layout.addLayout(self._drop_rows)
        self._drops: dict[str, QPushButton] = {}

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
        # The window opens on the key field, so its default is «Зберегти», the button after it.
        # Otherwise a dialog makes the first button in its focus chain the default, «Перенести»
        # whenever it shows: Enter in the key field then saved AND opened the terminal.
        self._field.setFocus()

    def refresh(self, *, ask: bool = False) -> None:
        """Show what the method says now. `ask` re-runs `key status` instead of the kept answer."""
        if ask:
            # The re-read is the method's command too, and waits like one (VM-2).
            with self._busy("rkBusyRead"):
                self._show(reviewer_key.status(refresh=True))
            return
        self._show(reviewer_key.status())

    def _show(self, answer) -> None:
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
            # The key `key rm` deletes is the one in the OS keystore, wherever else a copy is.
            self._removes[provider].setVisible(supported and entry.get("keystore") is True)
        exports = reviewer_key.shell_exports()
        self._shell.setVisible(bool(exports))
        self._move.setVisible(bool(exports))
        if exports:
            lines = [_shell_line(e) for e in exports]
            # The command by its name; the button runs it with this machine's full paths.
            self._shell.setText("\n".join(lines) + "\nautosound_ai.py key move-shell")
        self._show_drops(providers if supported else {}, exports)
        self._supported = supported
        self._settle()

    def _controls(self) -> list:
        """What a click or a key lands on: the window's buttons, the provider and the key field —
        not the buttons of a question box it asked before (`_confirm`'s box stays its child)."""
        buttons = [b for b in self.findChildren(QPushButton) if b.window() is self]
        return [*buttons, self._provider, self._field]

    def _settle(self) -> None:
        """Every control as the window stands: all off while a method command runs (VM-2); else
        on, and the key entry only where the method can take a key."""
        busy = self._busy_depth > 0
        for widget in self._controls():
            widget.setEnabled(not busy)
        if not busy:
            for widget in (self._provider, self._field, self._save):
                widget.setEnabled(self._supported)

    @contextmanager
    def _busy(self, line: str | None = None):
        """While the method's `key` command runs: the wait cursor, every control off, and `line`
        in the result's place (VM-2, the Arbiter: «як показати значок очікування (бо там десь 5
        сек)»). The line is painted before the call blocks; it gives way to the line it covered
        unless the code inside wrote a new one.

        A click made meanwhile is dropped, not queued: the OS holds it until the event loop runs,
        so the loop runs here once more while the controls are still off.
        """
        outer = self._busy_depth == 0
        self._busy_depth += 1
        covered = (self._result.text(), self._result.toolTip())
        # A control turned off loses the focus; the key field, say, gets it back (Enter saves).
        focused = self.focusWidget()
        if line:
            self._result.setText(i18n.t(line))
            self._result.setToolTip("")
        if outer:
            self._settle()
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        if self.isVisible():
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        try:
            yield
        finally:
            self._busy_depth -= 1
            if line and self._result.text() == i18n.t(line):
                self._result.setText(covered[0])
                self._result.setToolTip(covered[1])
            if outer:
                if self.isVisible():
                    QApplication.processEvents()
                QApplication.restoreOverrideCursor()
                self._settle()
                if focused in (self._field, self._provider, self._save) and focused.isEnabled():
                    focused.setFocus()

    def _takes_drop(self) -> bool | None:
        """`reviewer_key.drops_exports()` — True, False, or None for no answer — asked at most once
        while this window is open (tcc#129). An answer the method gave is kept per script file
        anyway; no answer is not, and each ask holds the window up to the 20-s timeout: a save ran
        two in a row, in the save and in the repaint after it. A new window asks again."""
        if self._probe_silent:
            return None
        answer = reviewer_key.drops_exports()
        self._probe_silent = answer is None
        return answer

    def _show_drops(self, providers: dict, exports: list[dict]) -> None:
        """«Видалити копію …» for each exported key the OS keystore also holds (finding 127).

        That is the method's own condition for `--drop`: without the key in the keystore the export
        is the only copy, and the method refuses (hub #230). None from a method without the form —
        it would move and store every export instead (`reviewer_key.drops_exports`).
        """
        for button in self._drops.values():
            self._drop_rows.removeWidget(button)
            button.deleteLater()
        self._drops = {}
        exported = {e.get("var") for e in exports}
        held = [p for p in reviewer_key.PROVIDERS if isinstance(providers.get(p), dict)
                and providers[p].get("keystore") is True and providers[p].get("var") in exported]
        # The method is asked only when there is something to offer: the question is a child.
        if not held or self._takes_drop() is not True:
            return
        for provider in held:
            button = QPushButton(i18n.t("rkDropCopy").format(var=providers[provider]["var"]))
            # Never the dialog's default: Enter in the key field saves (see `__init__`).
            button.setAutoDefault(False)
            button.clicked.connect(lambda _checked=False, p=provider: self._on_drop(p))
            _fit_tinted(button)
            self._drop_rows.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
            self._drops[provider] = button

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
        # The method's part waits (VM-2); the question below does not.
        with self._busy("rkBusySave"):
            stored, said = reviewer_key.set_key(provider, value)
            # The method keeps it now. Nothing here holds it across the question below: the
            # method drops an exported copy without storing anything over the key just saved
            # (hub #230).
            del value
            if stored:
                where = self._where_now(provider)
                # Stored — and the same variable still exported: the copy every program reads
                # stays behind unless asked about (finding 127, tcc#117).
                copies = self._copies_left(provider)
                drops = self._takes_drop() if copies else False
        if not stored:
            self._result.setText(i18n.t("rkRefused").format(why=said) if said
                                 else i18n.t("rkNoAnswer"))
            self.refresh(ask=True)
            return
        # In the window's language, from the method's answer; the method's own sentence is
        # Ukrainian whatever the window speaks, so it is the hover (finding 42, tcc#65).
        lines = [i18n.t("rkSaved").format(where=where or said or "—")]
        tips = [said]
        if copies:
            var, place = copies[0].get("var", "?"), "; ".join(_place(e) for e in copies)
            if drops is None:
                # Not «too old»: the method did not say, and nothing is sent it may misread.
                lines.append(i18n.t("rkDropProbeNoAnswer").format(var=var, place=place))
            elif not drops:
                # An older method would move and store EVERY export for this yes (hub #230).
                lines.append(i18n.t("rkDropUpdate").format(var=var, place=place))
            elif self._confirm(i18n.t("rkRemoveAsk").format(var=var, place=place),
                               i18n.t("rkRemoveYes"), default_yes=True):
                line, tip = self._drop(provider, var, place)
                lines.append(line)
                tips.append(tip)
        self._result.setText("\n".join(lines))
        self._result.setToolTip("\n".join(tip for tip in tips if tip))
        # The kept answer is current: `_where_now` asked, and each change after it dropped the
        # answer and the next read asked again. Asking once more is a second child for nothing.
        self.refresh()

    def _copies_left(self, provider) -> list[dict]:
        """The exports of `provider`'s variable, when the OS keystore holds its key — or [].

        The keystore and not the machine file: `--drop` refuses without the key there, the export
        then being the only copy the method counts (hub #230)."""
        entry = self._entry(provider)
        if entry.get("keystore") is not True:
            return []
        return [e for e in reviewer_key.shell_exports() if e.get("var") == entry.get("var")]

    def _drop(self, provider, var: str, place: str) -> tuple[str, str]:
        """The method's `key move-shell <provider> --drop`, and the line its answer says.

        From the answer, not from a fresh `key status` (hub #230): removed, nothing to remove, or
        — refused, a crash, any code but 0, 1 and 3 — not removed, with the method's own words as
        the hover. The method here takes `--drop` (asked before the button or the question was
        offered), so no code reads as «update the method». The window re-reads the status
        afterwards for the rows, not for this line — under the same wait: the drop forgot the
        kept answer, so that read asks the method again (VM-2).
        """
        with self._busy("rkBusyDrop"):
            happened, said = reviewer_key.drop_export(provider)
            self.refresh()
        if happened is None:
            return i18n.t("rkDropNoAnswer"), said
        key = {reviewer_key.DROPPED: "rkRemoved",
               reviewer_key.NOTHING: "rkDropNothing"}.get(happened, "rkNotRemoved")
        return i18n.t(key).format(var=var, place=place), said

    def _on_drop(self, provider) -> None:
        """«Видалити копію …»: the exported copy out, the key in the keystore kept (finding 127)."""
        var = self._entry(provider).get("var") or "?"
        place = "; ".join(
            _place(e) for e in reviewer_key.shell_exports() if e.get("var") == var) or "—"
        if not self._confirm(i18n.t("rkDropAsk").format(var=var, place=place,
                                                        save=i18n.t("rkSave")),
                             i18n.t("rkDropYes"), default_yes=False):
            return
        line, tip = self._drop(provider, var, place)
        self._result.setText(line)
        self._result.setToolTip(tip)

    def _on_remove(self, provider) -> None:
        """«Видалити ключ»: the key out of every place the window can take it from, after a yes that
        names each of them, the provider and what stops — the API route (finding 136, tcc#127).

        In this order, under the wait (VM-2): an exported copy first, by the method's `move-shell
        <provider> --drop`, while the store still holds the key — `--drop` refuses once it does not,
        the copy being the only one, and the window would be left with no way to remove it but
        `move-shell`, which stores the key again (review I2). A drop that fails stops the delete
        there, and says so. Then the method's `key rm`; then the line from the store it left, never
        from the exit (`reviewer_key.remove_key`): «нічого не списується» only when no copy is
        left anywhere the window sees, and what is left named otherwise."""
        name = _NAMES[provider]
        var = self._entry(provider).get("var") or "?"
        exports = [e for e in reviewer_key.shell_exports() if e.get("var") == var]
        places = "; ".join([i18n.t("rkPlaceStore")] + [_place(e) for e in exports])
        ask = i18n.t("rkRmAsk").format(provider=name, places=places, save=i18n.t("rkSave"))
        kept = self._kept(provider, exports)
        if kept:
            ask += "\n\n" + i18n.t("rkRmAskKept").format(where="; ".join(kept))
        if not self._confirm(ask, i18n.t("rkDropYes"), default_yes=False):
            return
        tips: list[str] = []
        stop = ""
        with self._busy("rkBusyRm"):
            if exports:
                stop = self._drop_first(provider, var, exports, tips)
            if not stop:
                happened, left, said = reviewer_key.remove_key(provider)
                tips.append(said)
            # The rows, under the same wait: the kept answer is the one the last command re-read,
            # and after no answer this read asks again.
            self.refresh()
        if stop:
            line = f"{i18n.t('rkRmStopped').format(provider=name)} {stop}"
        else:
            line = self._removed_line(name, var, happened, left, places)
        self._result.setText(line)
        # The method's own sentences are Ukrainian whatever the window speaks (finding 42).
        self._result.setToolTip("\n".join(tip for tip in tips if tip))

    def _kept(self, provider, exports: list[dict]) -> list[str]:
        """The copies of `provider`'s key no command here removes: a line in the critic-env file,
        and the environment TCC was started with when no export it can drop explains it."""
        entry = self._entry(provider)
        file_ = entry.get("file")
        kept = []
        if isinstance(file_, dict) and not file_.get("blank"):
            kept.append(i18n.t("rkLeft_file"))
        if entry.get("env") is True and not exports:
            kept.append(i18n.t("rkLeft_env"))
        return kept

    def _drop_first(self, provider, var: str, exports: list[dict], tips: list[str]) -> str:
        """The exported copies dropped before the key leaves the store (review I2): "" to go on,
        or the line that says why the delete stopped here."""
        place = "; ".join(_place(e) for e in exports)
        drops = self._takes_drop()
        if drops is None:
            return i18n.t("rkDropProbeNoAnswer").format(var=var, place=place)
        if not drops:
            # An older method would move and store every export for this (hub #230).
            return i18n.t("rkDropUpdate").format(var=var, place=place)
        happened, said = reviewer_key.drop_export(provider)
        tips.append(said)
        if happened == reviewer_key.DROPPED:
            # And TCC's own copy of what it was started with — on Windows the HKCU value, from a
            # terminal the profile's — whose source is now gone: the reviewer runs TCC starts
            # would carry it until a restart.
            os.environ.pop(var, None)
            return ""
        if happened == reviewer_key.NOTHING:
            return ""
        return i18n.t("rkDropNoAnswer" if happened is None else "rkNotRemoved").format(
            var=var, place=place)

    @staticmethod
    def _removed_line(name: str, var: str, happened, left: tuple, places: str) -> str:
        """The line after `key rm`, from the store it left and the copies still there."""
        still = [i18n.t(f"rkLeft_{where}") for where in left] + [
            _place(e) for e in reviewer_key.shell_exports() if e.get("var") == var]
        left_line = i18n.t("rkRmLeft").format(where="; ".join(still)) if still else ""
        if happened == reviewer_key.REMOVED:
            return " ".join((i18n.t("rkRmDone").format(provider=name, places=places),
                             left_line or i18n.t("rkRmFree").format(provider=name)))
        if happened == reviewer_key.NOT_STORED:
            return " ".join(part for part in (i18n.t("rkRmNone").format(provider=name), left_line)
                            if part)
        if happened == reviewer_key.NOT_REMOVED:
            return i18n.t("rkRmFailed").format(provider=name)
        return i18n.t("rkRmNoAnswer")

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
