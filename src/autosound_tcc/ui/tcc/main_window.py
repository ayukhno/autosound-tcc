"""The main TCC window — layout skeleton ported from the web prototype
(`data/private/prototype/tcc-main.html`): header / left DSP panel / center (detail + AI dialog) /
right (plan-fact + measurement task) / footer, matching the prototype's CSS grid areas
`head`/`left`/`center`/`right`/`foot`.

M1 scope only: the shell, theme, and empty section placeholders. The real content of each panel
lands in later milestones (see the plan file / task list) — this file will keep growing as each
section gets wired to real data, but the outer structure built here should not need to change.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import config
from autosound_tcc.state.dsp_state import ProjectView, load_project_view
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.detail_pane import DetailPane
from autosound_tcc.ui.tcc.dialog_panel import DialogPanel
from autosound_tcc.ui.tcc.dsp_tree import DspTreeWidget
from autosound_tcc.ui.tcc.measurement_panel import MeasurementPanel
from autosound_tcc.ui.tcc.plan_panel import PlanPanel
from autosound_tcc.ui.tcc.theme import apply_theme

_SETTINGS_ORG = "autosound-tcc"
_SETTINGS_APP = "TCC"
_THEME_KEY = "ui/theme"
_ZOOM_KEY = "ui/zoom"
_LANG_KEY = "ui/lang"
_FEEDBACK_URL = "https://github.com/ayukhno/autosound-tcc/issues/new"
_ZOOM_MIN, _ZOOM_MAX, _ZOOM_STEP = 0.8, 1.5, 0.1


def _panel() -> QFrame:
    frame = QFrame()
    frame.setProperty("class", "panel")
    return frame


def _phead(title_key: str, sub_key: str | None = None) -> tuple[QWidget, QLabel, QLabel | None]:
    """A small-caps section header row (mirrors the prototype's `.phead`).

    Returns (widget, title_label, sub_label) so callers can retranslate the labels later and add
    trailing content (buttons, tabs) to the same row.
    """
    row = QWidget()
    row.setProperty("class", "phead")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(12, 8, 12, 8)
    layout.setSpacing(8)

    title = QLabel(i18n.t(title_key))
    title.setProperty("class", "phead-title")
    layout.addWidget(title)

    sub = None
    if sub_key:
        sub = QLabel(i18n.tx(i18n.t(sub_key)))
        sub.setProperty("class", "phead-sub")
        layout.addWidget(sub)

    layout.addStretch(1)
    return row, title, sub


def _detect_system_mode() -> str:
    """Dark unless the OS explicitly prefers light — mirrors the prototype's CSS default
    (bare `:root` is dark; `@media (prefers-color-scheme: light)` is the only thing that flips
    it without an explicit override)."""
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None:
        from PySide6.QtCore import Qt as _Qt

        if scheme() == _Qt.ColorScheme.Light:
            return "light"
    return "dark"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("autosound-tcc — Tuning Command Center")
        self.resize(1280, 820)

        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self._mode = self._settings.value(_THEME_KEY, None) or _detect_system_mode()
        self._zoom = float(self._settings.value(_ZOOM_KEY, 1.0))
        self._view: ProjectView | None = None
        self._preset_override: str | None = self._settings.value("ui/preset", None)
        i18n.set_language(self._settings.value(_LANG_KEY, "en"))

        root = QWidget()
        root.setObjectName("AppRoot")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        outer.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self._left = self._build_left()
        self._center = self._build_center()
        self._right = self._build_right()
        splitter.addWidget(self._left)
        splitter.addWidget(self._center)
        splitter.addWidget(self._right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([260, 900, 300])
        outer.addWidget(splitter, stretch=1)

        outer.addWidget(self._build_footer())

        self.setCentralWidget(root)
        self._apply_theme(self._mode)
        self._load_project()

    # ---- header / footer -------------------------------------------------

    def _build_header(self) -> QFrame:
        header = _panel()
        header.setProperty("class", "panel phead")  # header itself IS a .panel in the prototype
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(14)

        self._preset_combo = QComboBox()
        self._preset_combo.setProperty("class", "mini-select")
        self._preset_combo.currentTextChanged.connect(self._on_preset_selected)
        layout.addWidget(self._preset_combo)

        self._target_label = QLabel("")
        self._target_label.setProperty("class", "phead-sub")
        layout.addWidget(self._target_label)
        self._version_label = QLabel("")
        self._version_label.setProperty("class", "phead-sub")
        layout.addWidget(self._version_label)
        layout.addStretch(1)

        new_profile_btn = QPushButton("+ New DSP profile…")
        new_profile_btn.setProperty("class", "theme-btn")
        new_profile_btn.clicked.connect(self._on_new_dsp_profile)
        layout.addWidget(new_profile_btn)

        self._lang_combo = QComboBox()
        self._lang_combo.setProperty("class", "mini-select")
        self._lang_combo.addItems(["EN", "UK"])
        self._lang_combo.setCurrentText(i18n.current_language().upper())
        self._lang_combo.currentTextChanged.connect(
            lambda text: self._on_language_selected(text.lower())
        )
        layout.addWidget(self._lang_combo)

        zoom_out = QPushButton("A−")
        zoom_out.setProperty("class", "theme-btn")
        zoom_out.clicked.connect(self._zoom_out)
        layout.addWidget(zoom_out)
        self._zoom_label = QLabel(f"{round(self._zoom * 100)}%")
        self._zoom_label.setProperty("class", "phead-sub")
        layout.addWidget(self._zoom_label)
        zoom_in = QPushButton("A+")
        zoom_in.setProperty("class", "theme-btn")
        zoom_in.clicked.connect(self._zoom_in)
        layout.addWidget(zoom_in)

        self._theme_btn = QPushButton("◐ " + i18n.t("theme"))
        self._theme_btn.setProperty("class", "theme-btn")
        self._theme_btn.clicked.connect(self._toggle_theme)
        layout.addWidget(self._theme_btn)

        return header

    def _build_footer(self) -> QFrame:
        footer = _panel()
        footer.setProperty("class", "panel phead")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(14, 7, 14, 7)

        ai_main = QComboBox()
        ai_main.setProperty("class", "mini-select")
        ai_main.addItems(["Claude Opus 4.8", "Claude Sonnet 5", "Claude Fable 5"])
        layout.addWidget(QLabel("AI main"))
        layout.addWidget(ai_main)

        ai_critic = QComboBox()
        ai_critic.setProperty("class", "mini-select")
        ai_critic.addItems(["Gemini 3.1 Pro", "Gemini 3.5 Flash", "Claude Opus 4.8"])
        layout.addWidget(QLabel("AI critic"))
        layout.addWidget(ai_critic)

        layout.addStretch(1)

        feedback_btn = QPushButton("💬 Give feedback")
        feedback_btn.setProperty("class", "theme-btn")
        feedback_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(_FEEDBACK_URL))
        )
        layout.addWidget(feedback_btn)
        return footer

    def _on_new_dsp_profile(self) -> None:
        """Prompt for vendor/model, then open the existing onboarding chat
        (ui/tcc/profile_interview_dialog.py) for the current project directory."""
        vendor, ok = QInputDialog.getText(self, "New DSP profile", "Vendor (e.g. Musway):")
        if not ok or not vendor.strip():
            return
        model, ok = QInputDialog.getText(self, "New DSP profile", "Model (e.g. M6V4):")
        if not ok or not model.strip():
            return
        from autosound_tcc.ui.tcc.profile_interview_dialog import ProfileInterviewDialog

        dialog = ProfileInterviewDialog(config.project_dir(), vendor.strip(), model.strip(), self)
        dialog.exec()
        self._load_project()  # pick up the new/updated profile if one was saved

    # ---- left / center / right --------------------------------------------

    def _build_left(self) -> QFrame:
        panel = _panel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        head, self._left_title, _ = _phead("dspPanel")
        self._left_sub = QLabel("")
        self._left_sub.setProperty("class", "phead-sub")
        head.layout().insertWidget(head.layout().count() - 1, self._left_sub)
        layout.addWidget(head)

        self._left_status = QLabel("")
        self._left_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._left_status.setProperty("class", "phead-sub")
        self._left_status.setWordWrap(True)
        self._left_status.setContentsMargins(12, 16, 12, 16)
        layout.addWidget(self._left_status)

        self._tree = DspTreeWidget()
        self._tree.setVisible(False)
        # Connected once here (not in _load_project, which can now run multiple times across a
        # session -- preset switch, "New DSP profile..." -- and would otherwise stack duplicate
        # connections on the same long-lived tree instance).
        self._tree.tableRequested.connect(self._on_table_requested)
        self._tree.channelClicked.connect(self._on_channel_clicked)
        self._tree.eqRequested.connect(self._on_eq_requested)
        layout.addWidget(self._tree, stretch=1)

        return panel

    # ---- project loading ----------------------------------------------------

    def _load_project(self) -> None:
        """Load the DSP capability profile + the current preset's ledger, and hand the result to
        the tree. Degrades to a status message rather than crashing — no profile / no ledger /
        a broken file are all things a half-set-up project can legitimately be in."""
        profile_path = config.dsp_profile_path()
        if not profile_path.is_file():
            self._show_left_status(
                f"No DSP profile found.\nLooked for {profile_path}.\n"
                f"Run the DSP onboarding interview "
                f"(python -m autosound_tcc.dsp_profile_interview) to create one."
            )
            return
        try:
            from autosound_tcc.core import vendor_loader

            dsp_profile = vendor_loader.load_dsp_profile()
            profile = dsp_profile.load_profile(str(profile_path))
            dsp_profile.validate_profile(profile)
        except Exception as exc:  # noqa: BLE001 — surface any load/parse failure, don't crash
            self._show_left_status(f"Could not load DSP profile:\n{type(exc).__name__}: {exc}")
            return

        root = config.state_root()
        available = config.available_presets(root)
        preset = self._preset_override or config.resolve_preset(root) or (
            available[0] if available else None
        )
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        self._preset_combo.addItems(available)
        if preset:
            self._preset_combo.setCurrentText(preset)
        self._preset_combo.blockSignals(False)

        if preset is None:
            prof = profile.get("dsp_profile", profile)
            self._show_left_status(
                f"{prof.get('vendor', '?')} {prof.get('name', '?')}\n\n"
                f"No preset ledger found under {root}."
            )
            return
        try:
            view = load_project_view(str(root), preset, profile)
        except Exception as exc:  # noqa: BLE001
            self._show_left_status(f"Could not load ledger {preset!r}:\n{type(exc).__name__}: {exc}")
            return

        prof = profile.get("dsp_profile", profile)
        self._left_sub.setText(f"{prof.get('vendor', '?')} {prof.get('name', '?')}")
        self._left_status.setVisible(False)
        self._tree.setVisible(True)
        self._view = view
        self._tree.set_view(view)

        self._target_label.setText(f"Target: {view.target}" if view.target else "")
        self._version_label.setText(view.version or "")

    def _on_preset_selected(self, preset: str) -> None:
        if not preset or preset == self._preset_override:
            return
        self._preset_override = preset
        self._settings.setValue("ui/preset", preset)
        self._load_project()

    def _show_left_status(self, message: str) -> None:
        self._tree.setVisible(False)
        self._left_status.setText(message)
        self._left_status.setVisible(True)

    # ---- detail-pane wiring --------------------------------------------

    def _find_group(self, group_id: str):
        if self._view is None:
            return None
        return next((g for g in self._view.groups if g.id == group_id), None)

    def _on_table_requested(self, group_id: str) -> None:
        group = self._find_group(group_id)
        if group is not None:
            self._detail.open_table(group)

    def _on_channel_clicked(self, group_id: str, row_id: str) -> None:
        group = self._find_group(group_id)
        if group is not None:
            self._detail.open_table(group, select_row_id=row_id)

    def _on_eq_requested(self, group_id: str, row_id: str) -> None:
        group = self._find_group(group_id)
        if group is None:
            return
        row = next((r for r in group.rows if r.id == row_id), None)
        if row is not None:
            self._detail.open_eq(group, row)

    def _build_center(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._detail = DetailPane()
        layout.addWidget(self._detail)

        self._dialog_frame = _panel()
        dialog_layout = QVBoxLayout(self._dialog_frame)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        self._dialog = DialogPanel()
        self._dialog.editingChanged.connect(self._on_dialog_editing_changed)
        dialog_layout.addWidget(self._dialog)
        layout.addWidget(self._dialog_frame, stretch=1)

        return container

    def _on_dialog_editing_changed(self, editing: bool) -> None:
        self._dialog_frame.setProperty("class", "panel dialog-editing" if editing else "panel")
        self._dialog_frame.style().unpolish(self._dialog_frame)
        self._dialog_frame.style().polish(self._dialog_frame)

    def _build_right(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        plan_panel = _panel()
        plan_layout = QVBoxLayout(plan_panel)
        plan_layout.setContentsMargins(0, 0, 0, 0)
        plan_head, self._plan_title, self._plan_sub = _phead("planTitle", "planSub")
        plan_layout.addWidget(plan_head)
        self._plan_panel = PlanPanel()
        plan_layout.addWidget(self._plan_panel, stretch=1)
        layout.addWidget(plan_panel, stretch=1)

        meas_panel = _panel()
        meas_panel.setProperty("class", "panel meas-card")
        meas_layout = QVBoxLayout(meas_panel)
        meas_layout.setContentsMargins(0, 0, 0, 0)
        meas_head, self._meas_title, self._meas_sub = _phead("focus", "measSub")
        meas_layout.addWidget(meas_head)
        self._meas_panel = MeasurementPanel()
        meas_layout.addWidget(self._meas_panel)
        layout.addWidget(meas_panel)

        return container

    # ---- theme -------------------------------------------------------------

    def _apply_theme(self, mode: str) -> None:
        app = QApplication.instance()
        apply_theme(app, mode, scale=self._zoom)
        self._mode = mode
        self._settings.setValue(_THEME_KEY, mode)
        self._repolish_all()

    def _repolish_all(self) -> None:
        # Force a re-polish so already-visible widgets pick up the new stylesheet immediately.
        app = QApplication.instance()
        for widget in app.allWidgets():
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _toggle_theme(self) -> None:
        self._apply_theme("light" if self._mode == "dark" else "dark")

    def _set_zoom(self, zoom: float) -> None:
        self._zoom = round(min(_ZOOM_MAX, max(_ZOOM_MIN, zoom)), 2)
        self._settings.setValue(_ZOOM_KEY, self._zoom)
        apply_theme(QApplication.instance(), self._mode, scale=self._zoom)
        self._repolish_all()
        self._zoom_label.setText(f"{round(self._zoom * 100)}%")

    def _zoom_out(self) -> None:
        self._set_zoom(self._zoom - _ZOOM_STEP)

    def _zoom_in(self) -> None:
        self._set_zoom(self._zoom + _ZOOM_STEP)

    # ---- language -----------------------------------------------------------

    def _on_language_selected(self, lang: str) -> None:
        i18n.set_language(lang)
        self._settings.setValue(_LANG_KEY, lang)
        self._retranslate()

    def _retranslate(self) -> None:
        """Re-set every already-built widget's text. Header/footer labels created via `_phead`
        aren't re-queried automatically (no live template binding) -- this is the "wire
        retranslate" step the plan calls for, done by direct re-assignment rather than a full
        observer registry, since the widget count is still small enough for that to be simple
        and correct."""
        self._theme_btn.setText("◐ " + i18n.t("theme"))
        self._left_title.setText(i18n.t("dspPanel"))
        self._plan_title.setText(i18n.t("planTitle"))
        self._plan_sub.setText(i18n.t("planSub"))
        self._meas_title.setText(i18n.t("focus"))
        self._meas_sub.setText(i18n.t("measSub"))
        self._plan_panel.retranslate()
        self._meas_panel.retranslate()
        self._dialog.retranslate()
