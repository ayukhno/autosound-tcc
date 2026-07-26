"""The main TCC window — layout skeleton ported from the web prototype
(`data/private/prototype/tcc-main.html`): header / left DSP panel / center (detail + AI dialog) /
right (plan-fact + measurement task) / footer, matching the prototype's CSS grid areas
`head`/`left`/`center`/`right`/`foot`.

M1 scope only: the shell, theme, and empty section placeholders. The real content of each panel
lands in later milestones (see the plan file / task list) — this file will keep growing as each
section gets wired to real data, but the outer structure built here should not need to change.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import config
from autosound_tcc.state.dsp_state import load_project_view
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.dsp_tree import DspTreeWidget
from autosound_tcc.ui.tcc.theme import apply_theme

_SETTINGS_ORG = "autosound-tcc"
_SETTINGS_APP = "TCC"
_THEME_KEY = "ui/theme"


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

        placeholder = QLabel("PRESET · TARGET  (wired in M6)")
        placeholder.setProperty("class", "phead-sub")
        layout.addWidget(placeholder)
        layout.addStretch(1)

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
        placeholder = QLabel("model selectors · feedback  (wired in M6)")
        placeholder.setProperty("class", "phead-sub")
        layout.addWidget(placeholder)
        layout.addStretch(1)
        return footer

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
        preset = config.resolve_preset(root)
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
        self._tree.set_view(view)

    def _show_left_status(self, message: str) -> None:
        self._tree.setVisible(False)
        self._left_status.setText(message)
        self._left_status.setVisible(True)

    def _build_center(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._detail_panel = _panel()
        detail_layout = QVBoxLayout(self._detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_head, _, _ = _phead("dspPanel")
        detail_layout.addWidget(detail_head)
        self._detail_panel.setVisible(False)  # closed by default, like the prototype's .detail
        layout.addWidget(self._detail_panel)

        dialog_panel = _panel()
        dialog_layout = QVBoxLayout(dialog_panel)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        dialog_head, self._dialog_title, self._dialog_sub = _phead("dialog", "dialogSub")
        dialog_layout.addWidget(dialog_head)
        body = QLabel("AI dialog (M5)")
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setProperty("class", "phead-sub")
        dialog_layout.addWidget(body, stretch=1)
        layout.addWidget(dialog_panel, stretch=1)

        return container

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
        plan_body = QLabel("Plan (M4)")
        plan_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plan_body.setProperty("class", "phead-sub")
        plan_layout.addWidget(plan_body, stretch=1)
        layout.addWidget(plan_panel, stretch=1)

        meas_panel = _panel()
        meas_layout = QVBoxLayout(meas_panel)
        meas_layout.setContentsMargins(0, 0, 0, 0)
        meas_head, self._meas_title, self._meas_sub = _phead("focus", "measSub")
        meas_layout.addWidget(meas_head)
        meas_body = QLabel("Measurement task (M4)")
        meas_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        meas_body.setProperty("class", "phead-sub")
        meas_layout.addWidget(meas_body, stretch=1)
        layout.addWidget(meas_panel)

        return container

    # ---- theme -------------------------------------------------------------

    def _apply_theme(self, mode: str) -> None:
        app = QApplication.instance()
        apply_theme(app, mode)
        self._mode = mode
        self._settings.setValue(_THEME_KEY, mode)
        # Force a re-polish so already-visible widgets pick up the new stylesheet immediately.
        for widget in app.allWidgets():
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _toggle_theme(self) -> None:
        self._apply_theme("light" if self._mode == "dark" else "dark")
