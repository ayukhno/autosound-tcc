"""«Перевірити налаштування» (#272): the DSP row's button that sets the version on screen against the
preset file the DSP program saved, and the table the method's answer is shown in.

The button sits in the DSP section's header beside «Збережено в DSP…». It is on for a DSP whose
saved file the method reads (`dsp_file.reader_for`: the method's declaration, or TCC's fallback
table on a pin without one); for any other DSP it is off, and its hover says why. A click asks for
the file and runs `state/apply.py <project> compare-file <version> FILE --json` in a worker
(`dsp_file.compare`): TCC decodes nothing, writes nothing beside the file, and never writes it.

The answer is shown as the method gives it: the rows of a comparison, sound first and each category
apart, an `unknown` never as a match; or the refusal — the journal's (exit 1), the file's (exit 2),
a file that changed while it was read (exit 3), which is never a result. The method's warning is
on every answer, in Ukrainian where the method gives one (`warning_uk`) and the window speaks it,
and a model the method was not checked on says so above the table.

Out of `main_window.py`, which may not grow (`tests/test_structure_ratchet.py`): the window builds
one `FileCheck` and tells it each version it shows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from autosound_tcc.core import app_log, config, dsp_file
from autosound_tcc.ui.tcc import i18n, qt_shutdown, shown_version, window_folder
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip


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
    if answer.kind == "failed":
        return i18n.t("dspFileCheckFailed").format(message=message)
    if answer.code == dsp_file.EXIT_CHANGED:
        return i18n.t("dspFileCheckRefusedChanged").format(message=message)
    if answer.code == dsp_file.EXIT_JOURNAL:
        return i18n.t("dspFileCheckRefusedJournal").format(message=message)
    return i18n.t("dspFileCheckRefusedFile").format(kind=answer.error_kind or "?", message=message)


class CompareDialog(QDialog):
    """What one `compare-file` answered: the warning, the at-your-own-risk line, the table — or the
    refusal in its place. Not modal: it is read beside the DSP program's own screens."""

    def __init__(self, answer: dsp_file.Answer, version: str, parent=None) -> None:
        super().__init__(parent)
        self.answer = answer
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
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton(i18n.t("dspFileCheckClose"))
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)

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
    """The DSP header's two buttons, in order, built for `window`. «Збережено в DSP…» (hub #198):
    the name this configuration went into the device under, shown on the per-project line, where the
    method records it, and only with a version — `window._cfg_btn`, its hover `window._cfg_tip`,
    as they were when the window built them itself. Then «Перевірити налаштування», returned."""
    window._cfg_btn = QPushButton(i18n.t("cfgButton"))
    window._cfg_btn.setProperty("class", "link-btn")
    window._cfg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    window._cfg_tip = attach_tip(window._cfg_btn, i18n.t("cfgButtonTip"))
    window._cfg_btn.clicked.connect(window._open_save_config)
    window._cfg_btn.setVisible(False)
    window._dsp_section.add_header_widget(window._cfg_btn)
    return FileCheck(window)


class FileCheck(QObject):
    """The button in the DSP header and the one comparison it runs at a time."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self.button = QPushButton(i18n.t("dspFileCheck"))
        self.button.setProperty("class", "link-btn")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tip = attach_tip(self.button, "")
        self.button.clicked.connect(lambda _checked=False: self.pick())
        self.button.setVisible(False)
        window._dsp_section.add_header_widget(self.button)
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
        self.button.setVisible(bool(getattr(view, "version", None)) and shown_version.key_of(self._window) is None)
        self.button.setEnabled(self.reader is not None and not self._busy)
        self.retranslate()

    def tip_text(self) -> str:
        reader = self.reader
        if reader is None:
            known = "; ".join(f"{r.pattern} ({r.family})" for r in dsp_file.readers(self._project()))
            return i18n.t("dspFileCheckOffTip").format(readers=known)
        said = i18n.t("dspFileCheckTip").format(version=self._version() or "?", pattern=reader.pattern)
        if not reader.reads(dsp_file.ATTEST):
            said += "\n\n" + i18n.t("dspFileCheckNoMarkTip")
        return said

    def retranslate(self) -> None:
        try:
            self.button.setText(i18n.t("dspFileCheckBusy" if self._busy else "dspFileCheck"))
        except RuntimeError:  # its C++ half went with the window
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
        if (not version or self._busy or self._stopped
                or (self._worker is not None and self._worker.isRunning())):
            return
        self._asked = version
        worker = _CompareWorker(self._project(), version, path, self._preset())
        worker.result.connect(self._on_answer)
        self._worker = worker
        self._busy = True
        self.button.setEnabled(False)
        self.retranslate()
        worker.start()

    @Slot(object)
    def _on_answer(self, answer) -> None:
        self._busy = False
        if self._stopped or getattr(self._window, "_closing", False):
            return  # an answer queued before `stop` cut the signal: nothing opens on a closing window
        try:
            self.button.setEnabled(self.reader is not None)
            self.retranslate()
            old, self.dialog = self.dialog, None
            if old is not None:
                # Deleted, not only closed: one dialog a check would otherwise stay for the session.
                old.close()
                old.deleteLater()
            self.dialog = CompareDialog(answer, self._asked, self._window)
            self.dialog.show()
        except RuntimeError:  # the window closed while the file was read
            return

    def stop(self) -> None:
        """The window's `stop_workers`: a comparison still reading is asked to stop and handed over
        (`qt_shutdown.stop_or_detach`) with its answer cut, never left for Qt to destroy running —
        the worker has no parent, so no sweep of the window's widgets finds it. Safe to run twice."""
        self._stopped = True
        worker = self._worker
        if worker is not None:
            qt_shutdown.stop_or_detach(worker, STOP_WAIT_MS, mute=(worker.result,))

    def running(self) -> Optional[QThread]:
        """The worker of the comparison asked for last, running or done; None before the first."""
        return self._worker
