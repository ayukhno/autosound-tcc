"""«Перевірити налаштування» (#272): the DSP row's button that sets the version on screen against the
preset file the DSP program saved, and the table the method's answer is shown in.

The button stands on a line of its own at the top of the DSP section, under its header (the
Arbiter, 2026-11-22): in the header beside «Збережено в DSP…» the row asked 375 px in English and 472
in Ukrainian of a column 237 px wide, so the button sat past the column's edge and every row of the
column was cut (PR #276's Linux shard). On its line it elides before it asks for room. It is on for a DSP whose
saved file the method reads (`dsp_file.reader_for`: the declaration of the copy the project runs);
for any other DSP, and on a copy that declares no reader, it is off, and its hover says why. A click asks for
the file and runs `state/apply.py <project> compare-file <version> FILE --json` in a worker
(`dsp_file.compare`): TCC decodes nothing, writes nothing beside the file, and never writes it.

The answer is shown as the method gives it: the rows of a comparison, sound first and each category
apart, an `unknown` never as a match; or the refusal — the journal's (exit 1), the file's (exit 2),
a file that changed while it was read (exit 3), which is never a result. The method's warning is
on every answer, in Ukrainian where the method gives one (`warning_uk`) and the window speaks it,
and a model the method was not checked on says so above the table.

Where the comparison has rows that differ and the family's reader lists `propose --from-file`, the
dialog offers «Зберегти як нову версію» (#273): `state/apply.py <project> propose --from-file FILE
--preset P` (`dsp_file.propose`) in a worker, under the method's writer lock, on the same file and
preset as the comparison. The method banks the version and names what it kept, did not take and
took short; TCC shows its text as printed and re-reads the window as after any write of the
method's. A refusal (exits 1-3) and a journal held by another writer (75) bank nothing and are said
in the method's words. One read is banked once: the button is not offered again after an answer,
and a file or a version on screen that moved since the comparison is not banked at all.

Out of `main_window.py`, which may not grow (`tests/test_structure_ratchet.py`): the window builds
one `FileCheck` and tells it each version it shows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit, QPushButton, QSizePolicy, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from autosound_tcc.core import app_log, config, dsp_file
from autosound_tcc.ui.tcc import i18n, qt_shutdown, shown_version, window_folder
from autosound_tcc.ui.tcc.labels import ElidedButton
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip


def _gone(exc: RuntimeError, where: str) -> None:
    """A `RuntimeError` met while putting an answer on screen, in the log: a widget whose C++ half
    went with its window (`Internal C++ object … already deleted`) at debug — the window closed,
    nothing to show it on — and anything else at warning, with its traceback."""
    if "already deleted" in str(exc):
        app_log.logger().debug("dsp file: %s: %s", where, exc)
    else:
        app_log.logger().warning("dsp file: %s: %s", where, exc, exc_info=True)


class _CompareWorker(QThread):
    """One `compare-file`, off the GUI thread: a child process and a file read."""

    result = Signal(object)  # dsp_file.Answer

    def __init__(self, project_dir, version: str, file_path: str, preset: Optional[str]) -> None:
        super().__init__()
        self._args = (project_dir, version, file_path, preset)
        qt_shutdown.watch(self)

    def run(self) -> None:
        try:
            answer = dsp_file.compare(*self._args)
        except Exception as exc:  # noqa: BLE001 - an answer to show, never a dead worker
            app_log.logger().exception("compare-file could not run")
            answer = dsp_file.Answer("failed", None, message=f"{type(exc).__name__}: {exc}")
        self.result.emit(answer)


class _ProposeWorker(QThread):
    """One `propose --from-file`, off the GUI thread: a write of the method's, under its lock."""

    result = Signal(object)  # dsp_file.Saved

    def __init__(self, project_dir, file_path: str, preset: Optional[str]) -> None:
        super().__init__()
        self._args = (project_dir, file_path, preset)
        qt_shutdown.watch(self)

    def run(self) -> None:
        try:
            saved = dsp_file.propose(*self._args)
        except Exception as exc:  # noqa: BLE001 - an answer to show, never a dead worker
            app_log.logger().exception("propose --from-file could not run")
            saved = dsp_file.Saved("failed", None, message=f"{type(exc).__name__}: {exc}")
        self.result.emit(saved)


def _globs(pattern: str) -> str:
    """A reader's pattern as a file dialog's filter: `.pct6` → `*.pct6`, `.PR<n>` → `*.PR*`."""
    head = pattern.split("<", 1)[0]
    return f"*{head}*" if "<" in pattern else f"*{pattern}"


def _value(value) -> str:
    """A journal's or a file's value as a cell says it: a band or a leg as compact JSON."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    return str(value)


def warning_of(answer: dsp_file.Answer) -> str:
    """The method's warning in the window's language where the method gives it in that one."""
    if i18n.current_language() == "uk" and answer.warning_uk:
        return answer.warning_uk
    return answer.warning


def result_word(result: str) -> str:
    """`match`, `differs`, and everything else `unknown`: never a match it was not."""
    return i18n.t({"match": "dspFileCheckMatch", "differs": "dspFileCheckDiffers"}.get(result,
                                                                                         "dspFileCheckUnknown"))


def category_word(category: str) -> str:
    key = f"dspFileCheckCategory_{category}"
    return i18n.t(key) if key in i18n.T.get(i18n.current_language(), {}) else category


def refusal_sentence(answer: dsp_file.Answer) -> str:
    message = answer.message
    if answer.kind == "not_run":
        return i18n.t("dspFileCheckNotRun").format(message=message)
    if answer.kind == "timed_out":
        return i18n.t("dspFileCheckTimedOut").format(message=message)
    if answer.kind == "busy":
        return i18n.t("dspFileCheckBusyWriter").format(message=message)
    if answer.kind == "failed":
        return i18n.t("dspFileCheckFailed").format(message=message)
    if answer.code == dsp_file.EXIT_CHANGED:
        return i18n.t("dspFileCheckRefusedChanged").format(message=message)
    if answer.code == dsp_file.EXIT_JOURNAL:
        return i18n.t("dspFileCheckRefusedJournal").format(message=message)
    return i18n.t("dspFileCheckRefusedFile").format(kind=answer.error_kind or "?", message=message)


def saved_sentence(saved: dsp_file.Saved) -> str:
    """What one `propose --from-file` came to, with the method's own line in it where it gave one."""
    message = saved.message
    if saved.kind == "banked":
        return i18n.t("dspFileSaveBanked").format(version=saved.version or "?")
    if saved.kind == "busy":
        return i18n.t("dspFileSaveBusyWriter").format(message=message)
    if saved.kind == "timed_out":
        return i18n.t("dspFileSaveTimedOut").format(message=message)
    if saved.kind == "stale":
        return i18n.t("dspFileSaveStale")
    if saved.kind == "head_unread":
        return i18n.t("dspFileSaveHeadUnread")
    if saved.kind == "not_run":
        return i18n.t("dspFileSaveNotRun").format(message=message)
    if saved.kind == "refused" and saved.code == dsp_file.EXIT_JOURNAL:
        return i18n.t("dspFileSaveRefusedJournal").format(message=message)
    if saved.kind == "refused" and saved.code == dsp_file.EXIT_CHANGED:
        return i18n.t("dspFileSaveRefusedChanged").format(message=message)
    if saved.kind == "refused":
        return i18n.t("dspFileSaveRefusedFile").format(message=message)
    return i18n.t("dspFileSaveFailed").format(message=message)


class CompareDialog(QDialog):
    """What one `compare-file` answered: the warning, the at-your-own-risk line, the table — or the
    refusal in its place. Not modal: it is read beside the DSP program's own screens.

    With `offer_save` and a row that differs, «Зберегти як нову версію» (#273): a click asks
    (`save_requested`) and `FileCheck` runs the method; `show_saved` puts its answer here."""

    save_requested = Signal()

    def __init__(self, answer: dsp_file.Answer, version: str, parent=None, offer_save: bool = False) -> None:
        super().__init__(parent)
        self.answer = answer
        #: The answer of the save asked from this read, once it is in.
        self.saved: Optional[dsp_file.Saved] = None
        name = answer.file_name or "?"
        self.setWindowTitle(i18n.t("dspFileCheckTitle").format(version=version, file=name))
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        self.title_label = QLabel(i18n.t("dspFileCheckTitle").format(version=version, file=name))
        self.title_label.setProperty("class", "phead-title")
        layout.addWidget(self.title_label)
        said = [i18n.t("dspFileCheckFileLine").format(md5=answer.md5)] if answer.md5 else []
        if answer.saved:
            said.append(i18n.t("dspFileCheckSavedLine").format(saved=answer.saved))
        if answer.device:
            said.append(i18n.t("dspFileCheckDeviceLine").format(device=answer.device))
        self.meta_label = self._label(" · ".join(said), layout)
        self.risk_label = self._label(i18n.t("dspFileCheckRisk") if answer.checked_model is False else "",
                                      layout, "warn")
        self.warning_label = self._label(warning_of(answer), layout)
        self.refusal_label = self._label("" if answer.kind == "compared" else refusal_sentence(answer),
                                         layout, "warn")
        self.table: Optional[QTableWidget] = None
        self.counts_label = self._label("", layout)
        if answer.kind == "compared":
            counts = {key: answer.counts.get(key, 0) for key in dsp_file.RESULTS}
            self.counts_label.setText(i18n.t("dspFileCheckCounts").format(**counts))
            self.counts_label.setVisible(True)
            self.table = self._table(answer.rows)
            layout.addWidget(self.table, 1)
        else:
            layout.addStretch(1)
        self.saved_label = self._label("", layout, "warn")
        self.saved_text = QPlainTextEdit(self)
        self.saved_text.setReadOnly(True)
        self.saved_text.setVisible(False)
        layout.addWidget(self.saved_text, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_button: Optional[QPushButton] = None
        if offer_save and dsp_file.differs(answer):
            self.save_button = QPushButton(i18n.t("dspFileSave"))
            self.save_tip = attach_tip(self.save_button, i18n.t("dspFileSaveTip"))
            self.save_button.clicked.connect(lambda _checked=False: self.save_requested.emit())
            buttons.addWidget(self.save_button)
        close = QPushButton(i18n.t("dspFileCheckClose"))
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def offers_save(self) -> bool:
        """Whether this read may still be banked: offered, and no answer yet but one that ran
        nothing — a busy journal's, or a HEAD that could not be read at the click. One read is one
        bank: a second click banks nothing more."""
        return self.save_button is not None and (self.saved is None or self.saved.kind in ("busy", "head_unread"))

    def saving(self) -> None:
        if self.save_button is not None:
            self.save_button.setEnabled(False)
            self.save_button.setText(i18n.t("dspFileSaving"))

    def show_saved(self, saved: dsp_file.Saved) -> None:
        """The method's answer to the save: the sentence, and its text as printed (on a bank: the
        warning, the model line, the version, what it kept, did not take and took short)."""
        self.saved = saved
        self.saved_label.setProperty("class", "phead-sub" if saved.kind == "banked" else "warn")
        self.saved_label.style().polish(self.saved_label)
        self.saved_label.setText(saved_sentence(saved))
        self.saved_label.setVisible(True)
        self.saved_text.setPlainText(saved.text)
        self.saved_text.setVisible(bool(saved.text))
        if self.save_button is not None:
            self.save_button.setText(i18n.t("dspFileSave"))
            self.save_button.setEnabled(self.offers_save())

    @staticmethod
    def _label(text: str, layout, cls: str = "phead-sub") -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setProperty("class", cls)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setVisible(bool(text))
        layout.addWidget(label)
        return label

    def _table(self, rows) -> QTableWidget:
        """A heading row per category, then its rows: parameter · journal · file · result."""
        table = QTableWidget(0, 4, self)
        table.setHorizontalHeaderLabels([i18n.t(key) for key in (
            "dspFileCheckColParameter", "dspFileCheckColJournal", "dspFileCheckColFile",
            "dspFileCheckColResult")])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        if not rows:
            self._put(table, [i18n.t("dspFileCheckNoRows")], heading=True)
        category = None
        for row in rows:
            if row.category != category:
                category = row.category
                self._put(table, [category_word(category)], heading=True)
            result = result_word(row.result)
            if row.result != "match" and row.reason:
                result = f"{result}: {row.reason}"
            self._put(table, [f"{row.channel} {row.parameter}".strip(), _value(row.journal),
                              _value(row.file), result], result=row.result)
        return table

    @staticmethod
    def _put(table: QTableWidget, cells: list[str], heading: bool = False, result: str = "") -> None:
        at = table.rowCount()
        table.insertRow(at)
        for column, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            if heading:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            item.setData(Qt.ItemDataRole.UserRole, "heading" if heading else result)
            table.setItem(at, column, item)
        if heading:
            table.setSpan(at, 0, 1, 4)


#: How long a window on its way out waits for a comparison before handing it over: one read of a
#: few kilobytes, which `method_cli` bounds at `dsp_file.TIMEOUT_S` anyway.
STOP_WAIT_MS = 2000


def header_buttons(window) -> "FileCheck":
    """The DSP section's two buttons, built for `window`. «Збережено в DSP…» (hub #198), in the
    header: the name this configuration went into the device under, shown on the per-project line,
    where the method records it, and only with a version — `window._cfg_btn`, its hover
    `window._cfg_tip`, as they were when the window built them itself. Then «Перевірити
    налаштування», on its own line at the top of the section's body, returned."""
    window._cfg_btn = QPushButton(i18n.t("cfgButton"))
    window._cfg_btn.setProperty("class", "link-btn")
    window._cfg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    window._cfg_tip = attach_tip(window._cfg_btn, i18n.t("cfgButtonTip"))
    window._cfg_btn.clicked.connect(window._open_save_config)
    window._cfg_btn.setVisible(False)
    window._dsp_section.add_header_widget(window._cfg_btn)
    return FileCheck(window)


class FileCheck(QObject):
    """The button at the top of the DSP section and the one comparison it runs at a time."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        # Elided by its font's metrics before it asks the column for room: a plain QPushButton
        # holds its whole text, and the text is the column's width in Ukrainian (`ElidedButton`).
        self.button = ElidedButton(i18n.t("dspFileCheck"), gives_way=True)
        self.button.setProperty("class", "link-btn")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.tip = attach_tip(self.button, "")
        self.button.clicked.connect(lambda _checked=False: self.pick())
        #: The button's line, first in the section's body: shown and hidden with the button.
        self.row = QWidget()
        line = QHBoxLayout(self.row)
        line.setContentsMargins(12, 0, 12, 6)
        line.addWidget(self.button)
        self._show(False)
        window._dsp_section.body_layout().insertWidget(0, self.row)
        self.reader: Optional[dsp_file.Reader] = None
        self._view = None
        #: The version the running comparison was asked for: the dialog names it, not a later one.
        self._asked = ""
        #: The last comparison's worker, kept until the next one starts as the window keeps its
        #: own (`_capture_check`): a thread whose last reference goes inside its own `finished`
        #: is freed by the collector at a moment nobody chose. `_busy` is the one between start
        #: and answer — `isRunning()` is still true while `run()` unwinds past the answer.
        self._worker: Optional[_CompareWorker] = None
        self._busy = False
        #: What the comparison read, for its save (#273): the same project, file, preset and
        #: reader, whatever the window shows by the time of the click.
        self._asked_project: Optional[Path] = None
        self._asked_path = ""
        self._asked_preset: Optional[str] = None
        self._asked_reader: Optional[dsp_file.Reader] = None
        #: The save's worker, held as the comparison's is; `_saving` from its start to its answer,
        #: and the dialog that asked, which the answer goes to.
        self._saver: Optional[_ProposeWorker] = None
        self._saving = False
        self._saving_dialog: Optional[CompareDialog] = None
        #: Set by `stop`: the window is on its way out, and a late answer opens nothing.
        self._stopped = False
        self.dialog: Optional[CompareDialog] = None
        i18n.on_language_changed(self.retranslate)

    # ---- what the button says -----------------------------------------------------------------

    def _project(self) -> Path:
        return window_folder.shown(self._window) or config.project_dir()

    def _version(self) -> Optional[str]:
        view = self._view
        return None if view is None else (getattr(view, "file_version", None) or view.version)

    def _preset(self) -> Optional[str]:
        loaded = getattr(self._window, "_loaded_preset", None)
        return loaded if isinstance(loaded, str) else getattr(self._view, "preset", None)

    def sync(self, view, profile) -> None:
        """Told each version the window shows: on at HEAD with a version, off (with why) for a DSP
        whose file the method does not read, hidden while another version is looked at."""
        self._view = view
        try:
            self.reader = dsp_file.reader_for(profile, self._project())
        except Exception:  # noqa: BLE001 - a lookup that fails turns the button off, never the window
            app_log.logger().exception("dsp file: the readers could not be looked up")
            self.reader = None
        self._show(bool(getattr(view, "version", None)) and shown_version.key_of(self._window) is None)
        self.button.setEnabled(self.reader is not None and not self._busy and not self._saving)
        self.retranslate()

    def _show(self, shown: bool) -> None:
        """The button and its line together: a hidden button on a shown line still takes its margins."""
        self.button.setVisible(shown)
        self.row.setVisible(shown)

    def tip_text(self) -> str:
        reader = self.reader
        if reader is None:
            found = dsp_file.readers(self._project())
            if not found:  # a copy that declares no reader (before v3.3.3): no list to name
                return i18n.t("dspFileCheckNoReadersTip")
            known = "; ".join(f"{r.pattern} ({r.family})" for r in found)
            return i18n.t("dspFileCheckOffTip").format(readers=known)
        said = i18n.t("dspFileCheckTip").format(version=self._version() or "?", pattern=reader.pattern)
        if not reader.reads(dsp_file.ATTEST):
            said += "\n\n" + i18n.t("dspFileCheckNoMarkTip")
        return said

    def retranslate(self) -> None:
        try:
            self.button.setText(i18n.t("dspFileCheckBusy" if self._busy else "dspFileCheck"))
        except RuntimeError as exc:  # its C++ half went with the window
            _gone(exc, "the button could not be re-said")
            return
        try:
            self.tip.set_text(self.tip_text())
        except Exception:  # noqa: BLE001 - a hover that cannot be said is no project that fails to load
            app_log.logger().exception("dsp file: the button's hover could not be said")
            self.tip.set_text("")

    # ---- the comparison -----------------------------------------------------------------------

    def pick(self) -> None:
        """Ask for the file, then compare it: nothing is run without one."""
        if self.reader is None or self._busy or not self._version():
            return
        filters = ";;".join([i18n.t("dspFileCheckFilter").format(family=self.reader.family,
                                                                 globs=_globs(self.reader.pattern)),
                             i18n.t("dspFileCheckAllFiles")])
        path, _chosen = QFileDialog.getOpenFileName(self._window, i18n.t("dspFileCheckPick"),
                                                    str(self._project()), filters)
        if path:
            self.start(path)

    def start(self, path: str) -> None:
        version = self._version()
        if (not version or self._busy or self._stopped or self._saving
                or (self._worker is not None and self._worker.isRunning())):
            return
        self._asked = version
        self._asked_project, self._asked_path = self._project(), str(path)
        self._asked_preset, self._asked_reader = self._preset(), self.reader
        worker = _CompareWorker(self._asked_project, version, path, self._asked_preset)
        worker.result.connect(self._on_answer)
        self._worker = worker
        self._busy = True
        self.button.setEnabled(False)
        self.retranslate()
        worker.start()

    @Slot(object)
    def _on_answer(self, answer) -> None:
        self._busy = False
        if self._stopped:
            # An answer queued before `stop` cut the signal: nothing opens on a window on its way
            # out. Not `_closing`: the window sets it BEFORE its close questions and resets it on
            # Cancel, and a window that stays must show what came meanwhile (group review S1).
            return
        try:
            self.button.setEnabled(self.reader is not None)
            self.retranslate()
            old, self.dialog = self.dialog, None
            if old is not None:
                # Deleted, not only closed: one dialog a check would otherwise stay for the session.
                old.close()
                old.deleteLater()
            reader = self._asked_reader
            self.dialog = CompareDialog(answer, self._asked, self._window,
                                        offer_save=reader is not None and reader.reads(dsp_file.PROPOSE))
            self.dialog.save_requested.connect(self.save)
            self.dialog.show()
        except RuntimeError as exc:  # the window closed while the file was read
            _gone(exc, "the comparison's answer could not be shown")
            return

    # ---- the save (#273) -----------------------------------------------------------------------

    def save(self) -> None:
        """«Зберегти як нову версію» on the dialog shown: `propose --from-file` on the file the
        comparison read, in a worker. Not while anything runs, and not on a read that moved: a file
        whose bytes are not the ones compared, another version on screen, or a journal whose HEAD
        is not the version compared, banks nothing — the rows the person saw are not what the
        method would read. HEAD is read from the journal now, not from the window's last load:
        `propose` builds on HEAD as it stands at its run, and another writer may have banked since
        the watcher last re-read the window (#273 review). No `--on`: the method's door stays HEAD."""
        dialog = self.dialog
        if (dialog is None or not dialog.offers_save() or self._saving or self._busy or self._stopped
                or (self._saver is not None and self._saver.isRunning())):
            return
        now = dsp_file.md5_of(self._asked_path)
        moved = bool(dialog.answer.md5) and now is not None and now != dialog.answer.md5
        head = dsp_file.journal_head(self._asked_project, self._asked_preset)
        if moved or (head is not None and head != self._asked) or self._version() != self._asked \
                or shown_version.key_of(self._window) is not None:
            dialog.show_saved(dsp_file.Saved("stale", None))
            return
        if head is None:
            # Not «changed»: whether it moved is not known — a `slots.json` mid-rewrite, no preset.
            dialog.show_saved(dsp_file.Saved("head_unread", None))
            return
        worker = _ProposeWorker(self._asked_project, self._asked_path, self._asked_preset)
        worker.result.connect(self._on_saved)
        self._saver, self._saving, self._saving_dialog = worker, True, dialog
        self.button.setEnabled(False)
        dialog.saving()
        worker.start()

    @Slot(object)
    def _on_saved(self, saved) -> None:
        self._saving = False
        if self._stopped:
            return  # a window on its way out: nothing shown, nothing re-read (not `_closing`: S1)
        dialog, self._saving_dialog = self._saving_dialog, None
        try:
            self.button.setEnabled(self.reader is not None)
            self.retranslate()
            if dialog is not None:
                dialog.show_saved(saved)
                if dialog.isHidden():
                    dialog.show()  # the answer to a write the person asked for is seen
        except RuntimeError as exc:  # the dialog or the window went while the method wrote
            _gone(exc, "the save's answer could not be shown")
        if saved.may_have_written:
            # As after the window's own write of the method's (`_open_save_config`): the ledger
            # is watched, but the new version should not wait for the watcher's debounce.
            reload = getattr(self._window, "_reload_project_files", None)
            if callable(reload):
                QTimer.singleShot(0, reload)

    def saving(self) -> Optional[QThread]:
        """The worker of the save asked for last, running or done; None before the first."""
        return self._saver

    def stop(self) -> None:
        """The window's `stop_workers`: a comparison still reading, or a save still writing, is
        asked to stop and handed over (`qt_shutdown.stop_or_detach`) with its answer cut, never
        left for Qt to destroy running — neither worker has a parent, so no sweep of the window's
        widgets finds it. A save handed over runs on to the method's answer: its child is the
        method's, and is not cut. Safe to run twice: the second finds them handed over already."""
        if self._stopped:
            return
        self._stopped = True
        for worker in (self._worker, self._saver):
            if worker is not None:
                qt_shutdown.stop_or_detach(worker, STOP_WAIT_MS, mute=(worker.result,))

    def running(self) -> Optional[QThread]:
        """The worker of the comparison asked for last, running or done; None before the first."""
        return self._worker
