"""THROWAWAY PROTOTYPE — the «Режим контролю» layout (TODO F-069), for the Arbiter to click through.

Not for merging: it lives on branch `proto-layout-control` only, so the Arbiter can judge the
shape on his own project before anything is built for real (his word, 2026-09-22: «не забудь зі
мною обговорити як це буде виглядати ... прототип»). Everything here reuses the window's real
panels — nothing is mocked except where noted.

What it does, from his description (DECISIONS-W-2 A9–A13):

* one button toggles «Активний TCC» / «Режим контролю»;
* TCC takes the right half of the screen; the frontmost Terminal window, if Terminal is running,
  is put on the left half (macOS, best effort);
* the top window is full width, with tabs: «Моніторинг» (a read-only feed of what TCC sees of
  the terminal session, plus the bus buttons), «Таблиця-V» (virtual channels), «Таблиця-О»
  (outputs), then the one-parameter views as they are today (EQ, level, delays, phases);
* TCC's own confirmation request sits in a strip ABOVE the tabs and appears only when one
  arises (the terminal auto-confirms by default);
* below, the left and right panels side by side, equal, with a movable border between them and
  between them and the top.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import config
from autosound_tcc.ui.tcc.detail_pane import DetailPane
from autosound_tcc.ui.tcc.group_table import GroupTable

#: How many journal events the feed shows, newest last.
_FEED_EVENTS = 60


def _event_line(event: dict) -> str:
    """One journal event as one line of the feed — time, kind, and the one field that says what."""
    at = str(event.get("at") or "")[11:16]
    kind = str(event.get("type") or "?")
    what = (event.get("name") or event.get("title") or event.get("step") or event.get("question")
            or event.get("phase") or event.get("capture") or "")
    what = str(what).replace("\n", " ")
    if len(what) > 140:
        what = what[:139] + "…"
    return f"<span style='color:#8b97a6'>{at}</span> &nbsp;<b>{kind}</b> &nbsp;{what}"


class _MonitorFeed(QWidget):
    """«Моніторинг»: read-only. What TCC can see of a session running in a terminal — the process
    journal it writes (phases, steps, capture rounds, decisions) — plus the two bus buttons."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self._feed = QTextBrowser()
        self._feed.setOpenExternalLinks(False)
        layout.addWidget(self._feed, 1)
        buttons = QHBoxLayout()
        done = QPushButton("Готово — заміри взято")
        done.setProperty("class", "reason-btn")
        done.clicked.connect(lambda: getattr(window, "_on_capture_ready", lambda: None)())
        listen = QPushButton("Прослухати")
        listen.setProperty("class", "reason-btn")
        listen.clicked.connect(lambda: getattr(window, "_open_listening", lambda: None)())
        note = QLabel("Писати — у терміналі. Ці кнопки йдуть сигналом на шину.")
        note.setProperty("class", "phead-sub")
        buttons.addWidget(done)
        buttons.addWidget(listen)
        buttons.addWidget(note, 1)
        layout.addLayout(buttons)
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def refresh(self) -> None:
        journal = config.project_dir() / "process" / "journal.jsonl"
        try:
            lines = journal.read_text(encoding="utf-8").splitlines()[-_FEED_EVENTS:]
        except OSError:
            self._feed.setHtml("<i>Журналу процесу ще нема — стрічка наповниться, щойно сесія в "
                               "терміналі почне писати.</i>")
            return
        rows = []
        for line in lines:
            try:
                rows.append(_event_line(json.loads(line)))
            except ValueError:
                continue
        self._feed.setHtml("<br>".join(rows))
        bar = self._feed.verticalScrollBar()
        bar.setValue(bar.maximum())


def _group(view, group_id: str):
    return next((g for g in getattr(view, "groups", ()) or () if g.id == group_id), None)


def _table_tab(view, group_id: str, empty: str) -> QWidget:
    group = _group(view, group_id)
    if group is None:
        label = QLabel(empty)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label
    table = GroupTable()
    table.set_group(group)
    return table


def _param_tab(view, field: str) -> QWidget:
    pane = DetailPane()
    pane.set_view(view)
    pane.open_param(field)
    pane.setVisible(True)
    # The pane's own tab row would repeat the tabs above it; the tab IS the choice here.
    head = pane.layout().itemAt(0).widget()
    if head is not None:
        head.setVisible(False)
    return pane


def _eq_tab(view) -> QWidget:
    pane = DetailPane()
    pane.set_view(view)
    outputs = _group(view, "physical_outputs")
    if outputs is not None:
        pane.open_table(outputs)
    pane.setVisible(True)
    return pane


class ControlLayout:
    """Enter and leave the control layout on a live `MainWindow`, reparenting its real panels."""

    def __init__(self, window) -> None:
        self.window = window
        self.active = False
        self._container: Optional[QSplitter] = None
        self._saved_geometry = None
        self._confirm_home: Optional[tuple] = None

    def toggle(self) -> None:
        self.leave() if self.active else self.enter()

    def enter(self) -> None:
        w = self.window
        if self.active:
            return
        self._saved_geometry = w.geometry()
        view = getattr(w, "_view", None)

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(4)
        # TCC's own confirmation, moved out of the hidden dialog. It shows itself only when a
        # request arrives, which is what «as it arises» asks for.
        bar = w._dialog.confirm_bar
        home = bar.parentWidget().layout()
        self._confirm_home = (home, home.indexOf(bar))
        top_layout.addWidget(bar)

        tabs = QTabWidget()
        tabs.addTab(_MonitorFeed(w), "Моніторинг")
        tabs.addTab(_table_tab(view, "virtual_channels", "У цього DSP немає віртуальних каналів"),
                    "Таблиця-V")
        tabs.addTab(_table_tab(view, "physical_outputs", "Виходів ще нема — немає реєстру"),
                    "Таблиця-О")
        tabs.addTab(_eq_tab(view), "EQ")
        for field, label in (("gain_db", "Рівень"), ("ta_ms", "Затримки"), ("phase_deg", "Фази")):
            tabs.addTab(_param_tab(view, field), label)
        top_layout.addWidget(tabs, 1)

        bottom = QSplitter(Qt.Orientation.Horizontal)
        bottom.setChildrenCollapsible(False)
        bottom.addWidget(w._left)
        bottom.addWidget(w._right)
        bottom.setSizes([1, 1])

        container = QSplitter(Qt.Orientation.Vertical)
        container.setChildrenCollapsible(False)
        container.addWidget(top)
        container.addWidget(bottom)
        container.setSizes([420, 480])
        self._container = container

        outer = w._main_splitter.parentWidget().layout()
        outer.insertWidget(outer.indexOf(w._main_splitter), container, 1)
        w._main_splitter.setVisible(False)

        self._compact(True)
        self._place_on_screen()
        self.active = True

    def leave(self) -> None:
        w = self.window
        if not self.active:
            return
        w._main_splitter.insertWidget(0, w._left)
        w._main_splitter.insertWidget(2, w._right)
        layout, index = self._confirm_home
        layout.insertWidget(index, w._dialog.confirm_bar)
        w._main_splitter.setVisible(True)
        if self._container is not None:
            self._container.setParent(None)
            self._container.deleteLater()
            self._container = None
        self._compact(False)
        if self._saved_geometry is not None:
            w.setGeometry(self._saved_geometry)
        self.active = False

    def _compact(self, on: bool) -> None:
        """Make the header and the footer fit half a screen.

        Measured 2026-09-22 on the Passat: the header's minimum is ~1525 px and the footer's ~800,
        against half of a 1512 px MacBook screen. In control mode: the language, zoom and theme
        controls leave the header (the menu has all three), the field captions go, the preset and
        target shrink; the in-app Generator's model and effort leave the footer — the session runs
        in the terminal, so they steer nothing; the reviewer stays, because `call_critic` uses it.
        """
        w = self.window
        hidden = [w._preset_field_lbl, w._target_field_lbl, w._lang_combo,
                  w._zoom_label.parentWidget(), w._theme_btn,
                  w._ai_main_lbl, w._ai_main_combo, w._ai_effort_lbl, w._ai_effort_combo]
        if on:
            self._was_visible = {id(x): x.isVisible() for x in hidden}
            for widget in hidden:
                widget.setVisible(False)
            self._preset_state = (w._preset_combo.minimumWidth(), w._preset_combo.sizeAdjustPolicy())
            w._preset_combo.setMinimumWidth(0)
            w._preset_combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            w._preset_combo.setMinimumContentsLength(8)
            w._preset_combo.setMaximumWidth(140)
            self._target_policy = w._target_label.sizePolicy()
            w._target_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            w._target_label.setMinimumWidth(60)
            w._target_label.setMaximumWidth(170)
            self._menu_text = w._menu_btn.text()
            w._menu_btn.setText("☰")
            w._critic_status.setMinimumWidth(0)
        else:
            for widget in hidden:
                widget.setVisible(getattr(self, "_was_visible", {}).get(id(widget), True))
            minimum, policy = getattr(self, "_preset_state", (0, None))
            w._preset_combo.setMinimumWidth(minimum)
            if policy is not None:
                w._preset_combo.setSizeAdjustPolicy(policy)
            w._preset_combo.setMaximumWidth(16777215)
            w._target_label.setMaximumWidth(16777215)
            w._target_label.setMinimumWidth(0)
            if getattr(self, "_target_policy", None) is not None:
                w._target_label.setSizePolicy(self._target_policy)
            if getattr(self, "_menu_text", None):
                w._menu_btn.setText(self._menu_text)

    def _place_on_screen(self) -> None:
        """TCC on the right half; the frontmost Terminal window on the left (macOS, if running)."""
        w = self.window
        screen = w.screen().availableGeometry()
        half = screen.width() // 2
        w.setMinimumWidth(0)
        w.setGeometry(screen.x() + half, screen.y(), half, screen.height())
        if sys.platform != "darwin":
            return
        script = (
            'tell application "System Events" to set running to (name of processes) contains "Terminal"\n'
            'if running then\n'
            f'  tell application "Terminal" to if (count of windows) > 0 then set bounds of front window to '
            f'{{{screen.x()}, {screen.y()}, {screen.x() + half}, {screen.y() + screen.height()}}}\n'
            'end if'
        )
        try:
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass  # best effort: a prototype that cannot move a window still shows the layout
