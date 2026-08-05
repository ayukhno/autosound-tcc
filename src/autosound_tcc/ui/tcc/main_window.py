"""The main TCC window — layout skeleton ported from the web prototype
(`data/private/prototype/tcc-main.html`): header / left DSP panel / center (detail + AI dialog) /
right (plan-fact + measurement task) / footer, matching the prototype's CSS grid areas
`head`/`left`/`center`/`right`/`foot`.

M1 scope only: the shell, theme, and empty section placeholders. The real content of each panel
lands in later milestones (see the plan file / task list) — this file will keep growing as each
section gets wired to real data, but the outer structure built here should not need to change.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QFileSystemWatcher, QPoint, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import (
    config,
    contract_check,
    critic,
    model_choices,
    omp_session,
    terminal_launcher,
)
from autosound_tcc.core.contract_check import ContractReport
from autosound_tcc.core.mcp_server import TccMcpServer
from autosound_tcc.core.rew_bridge import RewBridge
from autosound_tcc.core.tuning_session import TuningSession
from autosound_tcc.state import measurement_view, process_view, project_view
from autosound_tcc.state.dsp_state import ProjectView, load_project_view
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.agent_worker import AgentWorker
from autosound_tcc.ui.tcc.qt_bridge import QtUiBridge
from autosound_tcc.ui.tcc.detail_pane import DetailPane
from autosound_tcc.ui.tcc.diagnostics_panel import DiagnosticsDialog
from autosound_tcc.ui.tcc.dialog_panel import DialogPanel
from autosound_tcc.ui.tcc.feedback_dialog import FeedbackDialog
from autosound_tcc.ui.tcc.dsp_tree import DspTreeWidget
from autosound_tcc.ui.tcc.measurement_panel import MeasurementPanel, TrafficLight
from autosound_tcc.ui.tcc.model_config_dialog import ModelConfigDialog
from autosound_tcc.ui.tcc.new_project_dialog import NewProjectDialog
from autosound_tcc.ui.tcc.app_settings import get_settings
from autosound_tcc.ui.tcc.plan_panel import PlanPanel
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.sidebar_section import SidebarSection, clear_layout
from autosound_tcc.ui.tcc.status_strip import StatusStrip
from autosound_tcc.ui.tcc.theme import apply_caps, apply_theme

_THEME_KEY = "ui/theme"
_ZOOM_KEY = "ui/zoom"
_LANG_KEY = "ui/lang"
_GENERATOR_KEY = "ai/generator"        # the picked Choice.key
_ACTIVE_OMP_KEY = "ai/active_omp"     # selectors the user marked usable
_CRITIC_KEY = "ai/critic"             # the picked Choice.key for the reviewer

# What the outgoing model is asked to do before its session ends. Written as instructions to a
# model, so it names the tools rather than describing the intent: an agent that "summarises the
# state" into prose has saved nothing the next session can read.
#
# OPEN, and it applies to every string TCC sends *to* a model, not only this one: which language
# should they be in? The skill sets a session language during intake and writes the project's
# files in it, so a command in another language is a second voice in the conversation. Two
# defensible answers -- follow the session language, or keep every system command in English
# (unambiguous for the model, never mistaken for the user's own words) -- and no reason yet to
# prefer one. English here is the status quo, not the decision.
_HANDOFF_PROMPT = (
    "This session is ending now and a different model will continue this project. Do not "
    "summarise for me — write the state down where the next session will read it. Close or "
    "record the current step with its evidence (finish_step / block_step / add_step as they "
    "apply), make sure report_phase agrees with process-state.json, and put anything you learned "
    "that is not yet on disk into autosound_context.md. Then say in one line what you wrote."
)
# An agent that never finishes must not strand the restart: the handoff saves what can be saved,
# it does not make the swap conditional on saving it.
_HANDOFF_TIMEOUT_MS = 180_000
_FEEDBACK_URL = "https://github.com/ayukhno/autosound-tcc/issues/new"
# TODO(user): paste the published Google Form viewform URL here (the one built last session — see
# memory reference-browse-google-forms). Empty = the modal's form option only copies to clipboard.
_FEEDBACK_FORM_URL = ""

# The skill's online target-curve visualizer (user request 2026-07-28) -- opened in the system
# browser when the header's "Target curve" value is clicked, `?lang=` matching the app's own
# current language (the tool's own param convention: en/uk).
_TARGET_CURVE_TOOL_URL = (
    "https://ayukhno.github.io/autosound-tuning-skill/skills/autosound-tuning/references/"
    "patterns/target-curves/target_curves_visualizer.html"
)

# Support links (user request 2026-07-28), same two channels + wording as the skill's own
# README (all locales) -- GitHub Sponsors first (no fees, familiar to devs with an account),
# Monobank jar as the no-account fallback (one tap, Apple Pay/Google Pay/card).
_GITHUB_SPONSORS_URL = "https://github.com/sponsors/ayukhno?frequency=one-time"
_MONOBANK_JAR_URL = "https://send.monobank.ua/jar/8wThVcodjm"

# REW's own default local HTTP port (see core/rew_bridge.py's module docstring -- the vendored
# `rew_api` talks to http://localhost:4735). Shown as a fact in the "System params" sidebar
# section (user request 2026-07-28); not yet read from or written to any config -- just a
# reference value until that section gets real equipment-config wiring (see SKILL-CHANGE-REQUESTS
# SCR-015).
_REW_DEFAULT_PORT = "4735"

# Human-readable preset names for the header picker (dir names FULL/SQ are the ledger keys).
_PRESET_LABELS = {
    "FULL": {"en": '"FULL" (daily)', "uk": '"FULL" (повсякденний)'},
    "SQ": {"en": '"SQ Jazzi v.2" (competition)', "uk": '"SQ Jazzi v.2" (змагальний)'},
}


def _preset_label(key: str) -> str:
    return i18n.tx(_PRESET_LABELS.get(key, {"en": key}))


def _mini_combo() -> QComboBox:
    """A themed `.mini-select` combo that grows to fit its content, so the popup never clips its
    labels (the language picker was collapsing "EN"/"UK" down to "E"/"U")."""
    combo = QComboBox()
    combo.setProperty("class", "mini-select")
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    return combo


_ZOOM_MIN, _ZOOM_MAX, _ZOOM_STEP = 0.8, 1.5, 0.1


def _ago(iso_timestamp: str) -> str:
    """Human "how long ago" for the reviewer status. Falls back to the raw stamp if unparseable."""
    from datetime import datetime, timezone

    try:
        then = datetime.fromisoformat(iso_timestamp)
    except (TypeError, ValueError):
        return iso_timestamp or "?"
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - then).total_seconds()
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{round(seconds / 60)} min ago"
    if seconds < 172800:
        return f"{round(seconds / 3600)} h ago"
    return f"{round(seconds / 86400)} d ago"


def _panel() -> QFrame:
    frame = QFrame()
    frame.setProperty("class", "panel")
    return frame


def _vline() -> QFrame:
    line = QFrame()
    line.setProperty("class", "zoomgroup-div")
    line.setFixedWidth(1)
    return line


def _kv_row(key: str, value: str, trailing: QWidget | None = None) -> QWidget:
    """A single `key -> value` display row, styled like the DSP tree's `.paramrow`/`.pk`/`.pv`
    (dsp_tree._ParamRow) so a lone fact (e.g. System params' REW port) reads consistently with the
    rest of the app without depending on that module-private class. `trailing` is an optional
    extra widget after the value (the REW-online dot)."""
    row = QWidget()
    row.setProperty("class", "paramrow")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(12, 5, 12, 5)
    layout.setSpacing(6)
    k = QLabel(key)
    k.setProperty("class", "pk")
    layout.addWidget(k)
    layout.addStretch(1)
    v = QLabel(value)
    v.setProperty("class", "pv")
    layout.addWidget(v)
    if trailing is not None:
        layout.addWidget(trailing)
    return row


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
    apply_caps(title, spacing_px=1.4)
    layout.addWidget(title)

    sub = None
    if sub_key:
        sub = QLabel(i18n.tx(i18n.t(sub_key)))
        sub.setProperty("class", "phead-sub")
        layout.addWidget(sub)

    layout.addStretch(1)
    return row, title, sub


def _force_project_dir_env(project_dir: Path) -> None:
    """Make `config.project_dir()` resolve to `project_dir` for the rest of THIS process's life.

    `config.set_project_dir()` only persists to QSettings, which `config.project_dir()` checks
    AFTER the `AUTOSOUND_PROJECT_DIR` env var -- if this process was itself launched with one set
    (a real, common launch pattern), a plain QSettings update would be silently outranked by the
    still-set env var for any `MainWindow` built in this same process. Only `AUTOSOUND_PROJECT_DIR`
    needs setting: `config.project_dir()` checks it first.
    """
    os.environ["AUTOSOUND_PROJECT_DIR"] = str(project_dir)


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


class _RewPingWorker(QThread):
    """One-shot connectivity probe for the System-params REW-online dot -- mirrors
    `measurement_panel._RewReadWorker`'s shape (a synchronous HTTP call off the GUI thread), but
    only ever runs once per launch. Ongoing freshness comes from `MeasurementPanel.rewStatusChanged`
    instead of a recurring poll here."""

    result = Signal(bool)

    def __init__(self, bridge: RewBridge) -> None:
        super().__init__()
        self._bridge = bridge

    def run(self) -> None:
        self.result.emit(self._bridge.is_reachable())


class _ContractWorker(QThread):
    """Run the skill's whole-project contract check off the GUI thread.

    It spawns a Python subprocess and (unless REW is skipped) probes REW over HTTP, so the GUI
    thread is exactly where it must not run -- same reason `_RewPingWorker` exists just above.
    """

    result = Signal(object)  # ContractReport

    def __init__(self, project_dir) -> None:
        super().__init__()
        self._project_dir = project_dir

    def run(self) -> None:
        self.result.emit(contract_check.run(self._project_dir))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.resize(1280, 820)

        self._settings = get_settings()
        self._mode = self._settings.value(_THEME_KEY, None) or _detect_system_mode()
        self._zoom = float(self._settings.value(_ZOOM_KEY, 1.0))
        self._view: ProjectView | None = None
        self._has_project = False  # set for real by _load_project(); read by _refresh_process()
        self._rew_online: bool | None = None  # None = not checked yet -- read before _build_left()
        # Diagnostics (TCC-TZ.md §8). Set up before _build_header(), which adds the button that
        # opens the dialog, and before _load_project(), which re-runs the check.
        self._contract_report: ContractReport | None = None
        self._contract_worker: _ContractWorker | None = None
        self._diag_dialog: DiagnosticsDialog | None = None
        self._preset_override: str | None = self._settings.value("ui/preset", None)
        i18n.set_language(self._settings.value(_LANG_KEY, "en"))
        # Which project folder is actually open matters the moment you run TCC against more than
        # one (user request 2026-07-29) -- there's no in-app project switcher yet, only
        # AUTOSOUND_PROJECT_DIR/the QSettings-persisted choice, so the title is the only place
        # that's visible before digging into the DSP tree.
        self.setWindowTitle(f"Tuning Command Center — GitHub/autosound-tcc @ {config.project_dir()}")

        root = QWidget()
        root.setObjectName("AppRoot")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        outer.addWidget(self._build_header())

        # "What TCC found on disk" (MCP status, terminal-launch result) -- shown in both modes,
        # never a dialog bubble (TCC-TZ.md §8).
        self._status_strip = StatusStrip()
        outer.addWidget(self._status_strip)

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
        self._load_process()
        self._start_mcp_server()

        # One-shot REW-online probe (System-params dot); ongoing freshness comes from a real
        # Read/Scan on the measurement panel instead of a recurring poll here. Same escape hatch
        # as the MCP server just above -- this is a real outbound network call, and the test suite
        # relies on AUTOSOUND_TCC_MCP=0 to stay off the network entirely.
        self._rew_ping: "_RewPingWorker | None" = None
        if os.environ.get("AUTOSOUND_TCC_MCP", "1") != "0":
            self._rew_ping = _RewPingWorker(RewBridge())
            self._rew_ping.result.connect(self._set_rew_online)
            self._rew_ping.start()
        self._meas_panel.rewStatusChanged.connect(self._set_rew_online)

        # One contract check at launch, so the status strip can say "this project has N problems"
        # before the user goes looking. Same escape hatch as the two workers above.
        self._start_contract_check()

    # ---- header / footer -------------------------------------------------

    def _build_header(self) -> QFrame:
        header = _panel()
        header.setProperty("class", "panel phead")  # header itself IS a .panel in the prototype
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(14)

        self._preset_field_lbl = QLabel(i18n.t("preset"))
        self._preset_field_lbl.setProperty("class", "kv-lbl")
        apply_caps(self._preset_field_lbl, spacing_px=1.2)
        layout.addWidget(self._preset_field_lbl)

        self._preset_combo = _mini_combo()
        self._preset_combo.currentIndexChanged.connect(self._on_preset_index)
        layout.addWidget(self._preset_combo)

        self._slot_label = QLabel("")
        self._slot_label.setProperty("class", "slot-val")
        layout.addWidget(self._slot_label)
        self._save_label = QLabel("")
        self._save_label.setProperty("class", "phead-sub")
        layout.addWidget(self._save_label)

        self._target_field_lbl = QLabel(i18n.t("target"))
        self._target_field_lbl.setProperty("class", "kv-lbl")
        apply_caps(self._target_field_lbl, spacing_px=1.2)
        layout.addWidget(self._target_field_lbl)
        self._target_label = QLabel("")
        self._target_label.setProperty("class", "kv-val kv-val-link")
        # QSS silently ignores `text-decoration` on QLabel -- the underline (a persistent "this
        # is a link" cue, not just a hover effect, user request 2026-07-28) has to be set on the
        # font directly, same workaround `_PhaseStepRow`'s strike-through uses.
        link_font = QFont(self._target_label.font())
        link_font.setUnderline(True)
        self._target_label.setFont(link_font)
        self._target_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._target_tip = attach_tip(self._target_label, i18n.t("targetToolTip"))
        self._target_label.mousePressEvent = self._open_target_curve_tool  # type: ignore[assignment]
        layout.addWidget(self._target_label)

        self._version_label = QLabel("")
        self._version_label.setProperty("class", "phead-sub")
        layout.addWidget(self._version_label)
        layout.addStretch(1)

        # Always visible (not just in the no-project states) -- there's no watcher for a ledger
        # or profile that appears/changes on disk (a terminal-driven session finishes with no
        # signal back here), so this is the one manual "reload from disk" a user can always reach,
        # regardless of which left-panel accordion section happens to be collapsed (user request
        # 2026-07-29: the earlier left-panel version was easy to lose track of).
        self._header_refresh_btn = QPushButton("↻")
        self._header_refresh_btn.setProperty("class", "zoomgroup-btn")
        self._header_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_refresh_btn.clicked.connect(self._reload_from_disk)
        self._refresh_tip = attach_tip(self._header_refresh_btn, i18n.t("refreshProjectTip"))
        layout.addWidget(self._header_refresh_btn)

        # Diagnostics sits next to the reload button on purpose: both answer "what is actually on
        # disk right now", and §8 wants that question reachable in every mode, not buried in a menu.
        self._diag_btn = QPushButton("⚕")
        self._diag_btn.setProperty("class", "zoomgroup-btn")
        self._diag_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._diag_btn.clicked.connect(self._open_diagnostics)
        self._diag_tip = attach_tip(self._diag_btn, i18n.t("diagBtnTip"))
        layout.addWidget(self._diag_btn)

        self._lang_combo = _mini_combo()
        # Display "УК" (Cyrillic, macOS's own convention for Ukrainian) not the Latin "UK" -- that
        # reads as United Kingdom, not Ukrainian (user request 2026-07-27). Display text is
        # decoupled from the actual language code via itemData, same pattern as the preset combo.
        self._lang_combo.addItem("EN", "en")
        self._lang_combo.addItem("УК", "uk")
        idx = self._lang_combo.findData(i18n.current_language())
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        # Safety margin on top of AdjustToContents -- two-letter items were the tightest case that
        # clipped against the drop-down arrow zone (see .mini-select padding in theme.py).
        self._lang_combo.setMinimumWidth(64)
        self._lang_combo.currentIndexChanged.connect(
            lambda _idx: self._on_language_selected(self._lang_combo.currentData())
        )
        layout.addWidget(self._lang_combo)

        zoom_group = QFrame()
        zoom_group.setProperty("class", "zoomgroup")
        zg_layout = QHBoxLayout(zoom_group)
        zg_layout.setContentsMargins(0, 0, 0, 0)
        zg_layout.setSpacing(0)

        zoom_out = QPushButton("A−")
        zoom_out.setProperty("class", "zoomgroup-btn")
        zoom_out.clicked.connect(self._zoom_out)
        zg_layout.addWidget(zoom_out)
        zg_layout.addWidget(_vline())
        self._zoom_label = QLabel(f"{round(self._zoom * 100)}%")
        self._zoom_label.setProperty("class", "zoomgroup-label")
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zg_layout.addWidget(self._zoom_label)
        zg_layout.addWidget(_vline())
        zoom_in = QPushButton("A+")
        zoom_in.setProperty("class", "zoomgroup-btn")
        zoom_in.clicked.connect(self._zoom_in)
        zg_layout.addWidget(zoom_in)
        layout.addWidget(zoom_group)

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

        # omp reports several hundred models and nobody has credentials for most of them, so the
        # user marks the ones they actually use rather than TCC guessing on their behalf.
        self._models_btn = QPushButton(i18n.t("configureModels"))
        self._models_btn.setProperty("class", "btn")
        self._models_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._models_btn.clicked.connect(self._open_model_config)
        layout.addWidget(self._models_btn)

        self._ai_main_lbl = QLabel(i18n.t("aiMain"))
        self._ai_main_lbl.setProperty("class", "kv-lbl")
        apply_caps(self._ai_main_lbl, spacing_px=1.2)
        layout.addWidget(self._ai_main_lbl)
        # The generator picker is also the harness picker: Claude runs through the Agent SDK
        # against the user's own CLI, everything else through omp (spike/HANDOFF.md 5-ter). The
        # user picks a model; which adapter carries it follows from that, explicitly rather than
        # by inference.
        ai_main = _mini_combo()
        self._ai_main_combo = ai_main
        ai_main.currentIndexChanged.connect(self._on_generator_model_changed)
        layout.addWidget(ai_main)


        self._ai_critic_lbl = QLabel(i18n.t("aiCritic"))
        self._ai_critic_lbl.setProperty("class", "kv-lbl")
        apply_caps(self._ai_critic_lbl, spacing_px=1.2)
        layout.addWidget(self._ai_critic_lbl)
        # Same registry as the generator picker: one list, one place to configure. What differs
        # is reachability -- the reviewer script is Gemini-shaped (SCR-033), so anything else
        # lands in clipboard mode and says so here rather than after the wait.
        ai_critic = _mini_combo()
        self._ai_critic_combo = ai_critic
        ai_critic.currentIndexChanged.connect(self._on_critic_model_changed)
        layout.addWidget(ai_critic)

        # Both combos exist now, so one pass fills them from the one registry.
        self._reload_model_choices()
        self._running_model: Optional[str] = None

        # Which reviewer answered last, on what model, how long ago (TCC-Concept §4: the advisor
        # panel's "engaged? which AI+model? last called when").
        self._critic_status = QLabel(i18n.t("criticNever"))
        self._critic_status.setProperty("class", "kv-val")
        layout.addWidget(self._critic_status)

        # Two ways to bring an AI to this project, both explicit. Neither starts on launch: one
        # spends the user's tokens, the other opens a window on their desktop, and an app that
        # does either just because it was opened is an app people stop opening.
        self._session_btn = QPushButton(i18n.t("startSession"))
        self._session_btn.setProperty("class", "reason-btn")
        self._session_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._session_btn.clicked.connect(self._start_tuning_session)
        layout.addWidget(self._session_btn)
        self._update_session_button()

        self._terminal_btn = QPushButton(i18n.t("openTerminal"))
        self._terminal_btn.setProperty("class", "reason-btn")
        self._terminal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._terminal_btn.clicked.connect(self._open_terminal)
        layout.addWidget(self._terminal_btn)

        layout.addStretch(1)

        coffee_btn = QPushButton(i18n.t("coffeeBtn"))
        coffee_btn.setProperty("class", "coffee-btn")
        coffee_btn.clicked.connect(self._open_support_menu)
        self._coffee_btn = coffee_btn
        layout.addWidget(coffee_btn)

        feedback_btn = QPushButton("💬 " + i18n.t("fbBig"))
        feedback_btn.setProperty("class", "feedback-btn")
        feedback_btn.clicked.connect(self._open_feedback)
        self._feedback_btn = feedback_btn
        layout.addWidget(feedback_btn)
        return footer

    # ---- left / center / right --------------------------------------------

    def _placeholder_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("class", "phead-sub")
        label.setWordWrap(True)
        label.setContentsMargins(12, 10, 12, 10)
        return label

    def _rew_status_class(self) -> str:
        if self._rew_online is None:
            return "wait"  # not checked yet -- same neutral dot the measurement legend uses
        return "done" if self._rew_online else "bad"

    def _rebuild_system_params(self) -> None:
        """System params: REW's default local port (always shown) plus whatever equipment facts
        `project.json` has (DSP/amps/mic/source -- SCR-015 point 1, `project_view.load_system_params`).
        Rebuilt from scratch so a language switch re-translates the "REW port" label and a project
        switch picks up the new project's facts (same pattern as `_set_project_params`). Rebuilds
        the REW-online dot too (clear_layout destroys the old instance) from `self._rew_online`,
        which is what survives across rebuilds."""
        clear_layout(self._system_section.body_layout())
        self._rew_dot = TrafficLight(self._rew_status_class())
        self._rew_dot.setToolTip(
            i18n.t("rewOnlineTip") if self._rew_online else i18n.t("rewOfflineTip")
        )
        self._system_section.body_layout().addWidget(
            _kv_row(i18n.t("rewPort"), _REW_DEFAULT_PORT, trailing=self._rew_dot)
        )
        rows = project_view.load_system_params() if self._has_project else ()
        if not rows:
            self._system_section.body_layout().addWidget(self._placeholder_label(i18n.t("noDataYet")))
            return
        for label, value in rows:
            self._system_section.body_layout().addWidget(_kv_row(label, value))

    def _set_rew_online(self, online: bool) -> None:
        self._rew_online = online
        self._rew_dot.set_status(self._rew_status_class())
        self._rew_dot.setToolTip(
            i18n.t("rewOnlineTip") if online else i18n.t("rewOfflineTip")
        )

    # ---- diagnostics (TCC-TZ.md §8) -----------------------------------------

    def _reload_from_disk(self) -> None:
        """The header's ↻: re-read the project AND re-run the contract check.

        One button, because "what changed on disk" is one question — a terminal-driven session
        that rewrote the ledger usually rewrote the process state and project facts too.
        """
        self._load_project()
        self._start_contract_check()

    def _start_contract_check(self) -> None:
        """Ask the skill's own checker what this project looks like on disk (`contract.py --json`).

        TCC renders that verdict, it does not compute its own: the skill owns the schemas. Skipped
        when the vendored checker isn't there (submodule not initialised) — the panel then says so
        instead of the window failing to open.

        `AUTOSOUND_TCC_MCP=0` is the test suite's "no background side-effects" switch (it already
        gates the MCP server and the REW ping); spawning a Python subprocess per constructed window
        belongs behind the same one.
        """
        if os.environ.get("AUTOSOUND_TCC_MCP", "1") == "0":
            return
        if self._contract_worker is not None and self._contract_worker.isRunning():
            return
        if not contract_check.is_available():
            self._on_contract_result(
                ContractReport(
                    ok=False,
                    project_dir=str(config.project_dir()),
                    error=f"contract.py not found at {contract_check.script_path()}",
                )
            )
            return
        if self._diag_dialog is not None:
            self._diag_dialog.set_report(None)  # "Checking…", not stale data
        self._contract_worker = _ContractWorker(config.project_dir())
        self._contract_worker.result.connect(self._on_contract_result)
        self._contract_worker.start()

    def _on_contract_result(self, report: ContractReport) -> None:
        self._contract_report = report
        if self._diag_dialog is not None:
            self._diag_dialog.set_report(report)
        if not report.available:
            self._status_strip.notify(
                i18n.t("diagStripError").format(error=report.error), level="warn"
            )
        elif not report.ok:
            self._status_strip.notify(
                i18n.t("diagStripIssues").format(n=len(report.issues())), level="warn"
            )

    def _open_diagnostics(self) -> None:
        if self._diag_dialog is None:
            self._diag_dialog = DiagnosticsDialog(self)
            self._diag_dialog.refreshRequested.connect(self._start_contract_check)
            self._diag_dialog.set_report(self._contract_report)
        elif self._contract_report is not None:
            self._diag_dialog.set_report(self._contract_report)
        self._diag_dialog.show()
        self._diag_dialog.raise_()
        self._diag_dialog.activateWindow()
        # A window that only ever shows a launch-time snapshot is a stale window; opening it is
        # also the clearest signal that the user wants the CURRENT answer.
        if self._contract_report is None:
            self._start_contract_check()

    def _build_left(self) -> QFrame:
        """The left panel is a top-level accordion (user request 2026-07-28): System params /
        Project params / Car audio analysis / DSP, each a collapsible `SidebarSection` styled flat
        like the DSP tree's own `.ghead` group headers (a border-bottom line, no card background --
        matching backgrounds top-to-bottom was a follow-up correction the same day). Only DSP and
        System params (partially) have real content today -- Project params comes from
        `project.json`'s own facts (see `_set_project_params`; D2, SKILL-SYNC-PLAN.md --
        `project_profile.json` is retired, the skill writes one file), and Car audio analysis
        stays a placeholder until the car-audio skill defines where that data comes from
        (SKILL-CHANGE-REQUESTS SCR-015). System params leads (user request 2026-07-28) since it's
        the one project-setup fact block most relevant before diving into DSP tuning."""
        panel = _panel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._system_section = SidebarSection(
            "system_params", i18n.t("systemParams"), self._settings, default_collapsed=True
        )
        self._rebuild_system_params()
        layout.addWidget(self._system_section)

        self._project_section = SidebarSection(
            "project_params", i18n.t("projectParams"), self._settings, default_collapsed=True
        )
        layout.addWidget(self._project_section)

        self._audio_section = SidebarSection(
            "audio_analysis", i18n.t("audioAnalysis"), self._settings, default_collapsed=True
        )
        self._audio_placeholder = self._placeholder_label(i18n.t("noDataYet"))
        self._audio_section.body_layout().addWidget(self._audio_placeholder)
        layout.addWidget(self._audio_section)

        self._dsp_section = SidebarSection(
            "dsp", i18n.t("dspPanel"), self._settings, default_collapsed=False
        )
        layout.addWidget(self._dsp_section, stretch=1)

        self._left_status = QLabel("")
        self._left_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._left_status.setProperty("class", "phead-sub")
        self._left_status.setWordWrap(True)
        self._left_status.setContentsMargins(12, 16, 12, 16)
        self._dsp_section.body_layout().addWidget(self._left_status)

        # Only offered for the genuine "no project here at all" case (_show_left_status's
        # offer_create=True) -- the other _show_left_status branches describe a project that
        # exists but is broken, where "create new" would be the wrong fix.
        self._create_project_btn = QPushButton(i18n.t("createProject"))
        self._create_project_btn.setProperty("class", "reason-btn")
        self._create_project_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._create_project_btn.clicked.connect(self._open_new_project_dialog)
        self._create_project_btn.setVisible(False)
        self._dsp_section.body_layout().addWidget(
            self._create_project_btn, alignment=Qt.AlignmentFlag.AlignCenter
        )

        self._tree = DspTreeWidget()
        self._tree.setVisible(False)
        # Connected once here (not in _load_project, which can now run multiple times across a
        # session -- preset switch, "New DSP profile..." -- and would otherwise stack duplicate
        # connections on the same long-lived tree instance).
        self._tree.tableRequested.connect(self._on_table_requested)
        self._tree.channelClicked.connect(self._on_channel_clicked)
        self._tree.eqRequested.connect(self._on_eq_requested)
        self._dsp_section.body_layout().addWidget(self._tree, stretch=1)

        return panel

    # ---- project loading ----------------------------------------------------

    def _load_project(self) -> None:
        """Load the DSP capability profile + the current preset's ledger, and hand the result to
        the tree. Degrades to a status message rather than crashing — no profile / no ledger /
        a broken file are all things a half-set-up project can legitimately be in."""
        profile_path = config.dsp_profile_path()
        if not profile_path.is_file():
            self._show_left_status(
                f"No DSP profile found.\nLooked for {profile_path}.",
                offer_create=True,
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
        # self._preset_override ("ui/preset") is a GLOBAL QSettings value, not scoped per project
        # (same class of bug state_root() had) -- a preset name left over from a DIFFERENT project
        # must not be trusted here just because it's non-empty; only honor it if it's actually one
        # of THIS project's real presets, otherwise fall through to auto-detect/None exactly as if
        # no override were set.
        preset = self._preset_override if self._preset_override in available else None
        if preset is None:
            preset = config.resolve_preset(root) or (available[0] if available else None)
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        for p in available:
            self._preset_combo.addItem(_preset_label(p), p)  # display label, key as userData
        if preset:
            idx = self._preset_combo.findData(preset)
            if idx >= 0:
                self._preset_combo.setCurrentIndex(idx)
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
        self._has_project = True
        self._dsp_section.set_sub(f"{prof.get('vendor', '?')} {prof.get('name', '?')}")
        self._left_status.setVisible(False)
        self._create_project_btn.setVisible(False)
        self._tree.setVisible(True)
        self._rebuild_system_params()
        self._view = view
        self._tree.set_view(view)
        self._set_project_params(view)
        self._refresh_open_detail()

        self._slot_label.setText(view.slot_label or "")
        self._save_label.setText(view.save or "")
        self._target_label.setText(f"{view.target} ↗" if view.target else "")
        self._version_label.setText(view.version or "")

    def _open_new_project_dialog(self) -> None:
        """Folder + vendor/model + (in-app Claude OR a detected terminal CLI). Either path hands
        off to a fresh `MainWindow` pointed at the new folder rather than trying to hot-reload
        this window's subsystems (MCP server, process watcher, DSP tree) live -- every one of them
        already loads fresh from `config.project_dir()` in `__init__`, so a brand new window is a
        full, correct "restart pointed at the new project" with no new teardown code needed beyond
        the `closeEvent` this window already has."""
        dialog = NewProjectDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if dialog.interview_dialog is not None:
            interview = dialog.interview_dialog
            project_dir = dialog.project_dir

            def _on_saved(_path: str) -> None:
                interview.close()
                if project_dir is not None:
                    _force_project_dir_env(project_dir)
                new_window = MainWindow()
                new_window.show()
                self.close()

            interview.profile_saved.connect(_on_saved)
            interview.show()
            return

        if dialog.open_terminal_cli is not None and dialog.project_dir is not None:
            # config.set_project_dir() (already called by NewProjectDialog._on_create) only
            # updates QSettings -- if THIS process was itself launched with AUTOSOUND_PROJECT_DIR
            # set, that env var still wins over QSettings for any MainWindow built in the same
            # process, so the "fresh window" below would silently reopen the OLD project without
            # this override.
            _force_project_dir_env(dialog.project_dir)
            # The new window's own _start_mcp_server() runs synchronously in __init__, before
            # .show() -- .mcp.json already exists for the new project by the time the terminal
            # opens, so there's no ordering race to wait out here.
            new_window = MainWindow()
            new_window.show()
            language_name = i18n.t("langNameUk" if i18n.current_language() == "uk" else "langNameEn")
            hint = i18n.t("npOnboardingHint").format(
                vendor=dialog.onboarding_vendor,
                model=dialog.onboarding_model,
                language=language_name,
            )
            try:
                terminal_launcher.launch(
                    dialog.project_dir,
                    cli=dialog.open_terminal_cli,
                    hint=hint,
                    model=dialog.onboarding_ai_model,
                )
            except terminal_launcher.TerminalLaunchError as exc:
                new_window._status_strip.notify(str(exc), level="warn")
            self.close()

    def _open_feedback(self) -> None:
        FeedbackDialog(_FEEDBACK_URL, _FEEDBACK_FORM_URL, self).exec()

    def _open_target_curve_tool(self, _event=None) -> None:
        QDesktopServices.openUrl(QUrl(f"{_TARGET_CURVE_TOOL_URL}?lang={i18n.current_language()}"))

    def _open_support_menu(self) -> None:
        """Two-item menu opening upward from the footer (user request 2026-07-28): GitHub
        Sponsors for people with a GitHub account, the Monobank jar as the no-account/one-tap
        fallback -- same two channels + wording as the skill's own README, not a choice TCC makes
        for the user."""
        menu = QMenu(self)
        menu.setProperty("class", "support-menu")
        github_action = menu.addAction(i18n.t("supportGithub"))
        github_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(_GITHUB_SPONSORS_URL))
        )
        mono_action = menu.addAction(i18n.t("supportMonobank"))
        mono_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(_MONOBANK_JAR_URL)))
        top_left = self._coffee_btn.mapToGlobal(QPoint(0, 0))
        menu.adjustSize()
        menu.exec(QPoint(top_left.x(), top_left.y() - menu.sizeHint().height()))

    def _on_preset_index(self, _index: int) -> None:
        preset = self._preset_combo.currentData()
        if not preset or preset == self._preset_override:
            return
        self._preset_override = preset
        self._settings.setValue("ui/preset", preset)
        self._load_project()

    def _show_left_status(self, message: str, offer_create: bool = False) -> None:
        """The one place that means "there's no real, loaded project view right now" -- all four
        `_load_project` failure branches route through here, so mock-clearing lives here rather
        than at one call site. Only the genuine no-profile-file-at-all branch passes
        `offer_create=True`; a broken profile/ledger is a project that exists, where "create new"
        would be the wrong offer."""
        self._has_project = False
        self._tree.setVisible(False)
        self._left_status.setText(message)
        self._left_status.setVisible(True)
        self._create_project_btn.setVisible(offer_create)
        self._rebuild_system_params()
        self._set_project_params(None)
        self._detail.close_pane()
        self._dialog.clear_for_no_project()
        self._plan_panel.set_plan(())
        self._meas_panel.set_no_project(i18n.t("noProjectMeas"))

    def _set_project_params(self, view: ProjectView | None) -> None:
        """(Re)builds the "Project params" section body from `project.json`'s channel-tier summary
        (SCR-016, e.g. "8 virtual channels (1 off)") and any `_open_questions` as onboarding TODO
        chips (`state.project_view`). Moved out of the DSP tree into its own top-level section
        (user request 2026-07-28): this data is project-level config, not part of the DSP ledger.

        It used to also render `project.json`'s `param_sections` — ready-made label/value rows for
        exactly these panels. Those were dropped in skill schema v3: they restated DSP/mic/source
        values that are already fields in the same file, so the file carried one fact in two
        shapes. Panels are built from the facts now (`_rebuild_system_params` does the same)."""
        clear_layout(self._project_section.body_layout())
        summary_rows = project_view.load_channel_summary() if view else ()
        open_questions = project_view.load_open_questions() if view else ()
        if not summary_rows and not open_questions:
            self._project_section.body_layout().addWidget(
                self._placeholder_label(i18n.t("noDataYet"))
            )
            return
        for label, value in summary_rows:
            self._project_section.body_layout().addWidget(_kv_row(label, value))
        for question in open_questions:
            chip = self._placeholder_label(f"🟡 {i18n.t('openQuestions')}: {question}")
            self._project_section.body_layout().addWidget(chip)

    # ---- detail-pane wiring --------------------------------------------

    def _find_group(self, group_id: str):
        if self._view is None:
            return None
        return next((g for g in self._view.groups if g.id == group_id), None)

    def _refresh_open_detail(self) -> None:
        """Keep an already-open table/EQ view in sync after a project reload (preset switch, "New
        DSP profile...") -- otherwise it keeps showing the previous preset's frozen `ProfileGroup`/
        `GroupRow` snapshot (MUTE state and everything else) until manually closed and reopened
        (user report 2026-07-28)."""
        group_id = self._detail.current_group_id()
        if group_id is None:
            return
        fresh_group = self._find_group(group_id)
        if fresh_group is None:
            self._detail.close_pane()
        else:
            self._detail.refresh_with(fresh_group)

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
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        self._detail = DetailPane()
        splitter.addWidget(self._detail)

        self._dialog_frame = _panel()
        dialog_layout = QVBoxLayout(self._dialog_frame)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        self._dialog = DialogPanel()
        self._dialog.editingChanged.connect(self._on_dialog_editing_changed)
        dialog_layout.addWidget(self._dialog)
        splitter.addWidget(self._dialog_frame)

        # Detail pane starts hidden (no channel selected yet); give the dialog the room until
        # a table/EQ view opens and the user drags the handle themselves.
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 600])
        return splitter

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
        self._meas_panel = MeasurementPanel(
            preset_provider=lambda: self._view.preset if self._view else "",
        )
        meas_layout.addWidget(self._meas_panel)
        layout.addWidget(meas_panel)

        # A step's measurement icon opens that capture series in the panel below (user request
        # 2026-07-28).
        self._plan_panel.sessionRequested.connect(self._meas_panel.show_session)

        return container

    # ---- theme -------------------------------------------------------------

    def _apply_theme(self, mode: str) -> None:
        app = QApplication.instance()
        apply_theme(app, mode, scale=self._zoom)
        self._mode = mode
        self._settings.setValue(_THEME_KEY, mode)
        self._repolish_all()

    def _repolish_all(self) -> None:
        """Force a re-polish so already-visible widgets pick up the new stylesheet immediately.

        Scoped to this window's own widget tree, not `QApplication.allWidgets()`. The app-wide
        walk touched every widget in the process -- including ones this window doesn't own and
        ones whose C++ side is already gone -- and PySide6 then hands back an object that isn't a
        QWidget at all (`'QSpacerItem' object has no attribute 'style'`, hit in the test suite as
        soon as other widgets existed alongside a window). Dialogs that need repolishing are
        parented to the window, so they are in `findChildren` anyway.
        """
        for widget in [self, *self.findChildren(QWidget)]:
            # findChildren(QWidget) has, more than once now (QSpacerItem, then QWidgetItem), handed
            # back a layout-item wrapper -- and its Python-side isinstance(widget, QWidget) can
            # still say True while its C++ identity is actually stale, so .style() itself can come
            # back as the wrong type. Checking `style`'s own type is what actually catches it;
            # checking `widget`'s type first was not enough.
            if not isinstance(widget, QWidget):
                continue
            style = widget.style()
            if not isinstance(style, QStyle):  # None, or a stray non-QStyle object either way
                continue
            style.unpolish(widget)
            style.polish(widget)

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

    # ---- process state (SCR-004) --------------------------------------------

    def _load_process(self) -> None:
        """Render the skill's real plan when the project has one; keep the mock when it doesn't.

        TCC is a consumer here — the skill owns `process/process-state.json` and is its only
        writer (SCR-004). Watching the file rather than polling means a phase the Generator enters
        in a terminal shows up in the panel without TCC being told.

        Note the phase numbering differs from the mock's: the skill's skeleton is −1..5, the mock
        illustrated 0..6. A project with real state legitimately looks different from the demo.
        """
        self._process_watcher = QFileSystemWatcher(self)
        self._process_watcher.fileChanged.connect(self._refresh_process)
        self._refresh_process()

    def _refresh_process(self, *_args) -> None:
        state = process_view.load_state()
        if state is None:
            # A real project that just hasn't started tuning yet keeps the mock; no project at
            # all (self._has_project False, set by _show_left_status) must NOT re-mock a plan
            # _load_project already cleared to real-empty -- this runs after _load_project every
            # time (including preset switches), so it can't just default to "keep the mock".
            self._plan_panel.set_plan(None if self._has_project else ())
            return
        # SCR-014: what a `config_change` invalidated, computed once and used by both panels --
        # a step's "recheck" chip and a capture's unusable colour are the same fact.
        stale = process_view.stale_channels()
        self._plan_panel.set_plan(process_view.to_plan(state, stale))
        self._refresh_capture_task(state)
        self._notify_stale(stale)

        review = process_view.reviewer(state)
        if review:
            self._critic_status.setText(
                i18n.t("criticStatus").format(
                    model=review.get("model") or review.get("vendor") or "?",
                    ago=_ago(review.get("at", "")),
                )
            )

        # Re-arm: an atomic write replaces the inode, so the watcher silently drops the path it
        # was watching. Re-adding after every change is what keeps this from firing exactly once.
        path = str(process_view.state_file())
        if path not in self._process_watcher.files():
            self._process_watcher.addPath(path)

    def _notify_stale(self, stale: dict) -> None:
        """Say it in the strip too. A tuner who has not opened the plan still has to learn that the
        car changed under their measurements — §8's rule, and the reason SCR-014 says "never
        silently"."""
        if not stale:
            return
        newest = max(stale.values(), key=lambda change: str(change.get("at") or ""))
        self._status_strip.notify(
            i18n.t("staleStrip").format(
                n=len(stale),
                codes=", ".join(sorted(stale)),
                what=newest.get("what") or newest.get("field") or "config change",
            ),
            level="warn",
        )

    def _refresh_capture_task(self, state: dict) -> None:
        """Derive the capture checklist from (phase x glossary x version) — SCR-004/SCR-008.

        Deliberately built from the measurement titles the panel already holds rather than by
        calling REW here: the panel owns a worker for that, and blocking the GUI thread on HTTP to
        redraw a checklist is how a window stops responding while the car is running.
        """
        phase = state.get("active_phase")
        if not phase:
            return
        titles = getattr(self._meas_panel, "known_titles", lambda: [])()
        session = measurement_view.build_session(phase, self._capture_version(), titles)
        if session is not None:
            self._meas_panel.set_sessions((session,))

    def _capture_version(self) -> int:
        """The DSP config version measurements are named against — the ledger's HEAD.

        `_N` is the config the measurement was taken under (naming-and-structure §3), so this has
        to follow the ledger rather than count capture rounds.
        """
        head = getattr(self._view, "version", None) if self._view else None
        try:
            return int(str(head).lstrip("v_") or 1)
        except (TypeError, ValueError):
            return 1

    # ---- AI backends --------------------------------------------------------

    def _start_mcp_server(self) -> None:
        """Publish TCC over MCP so an agent -- in-app or in the user's terminal -- can reach it.

        Always started, never gated behind a button: it costs nothing, spends no tokens, and being
        up before the user launches a CLI is the whole point of writing `.mcp.json` for them.
        A failure here is not fatal; TCC is still a usable state viewer without it.
        """
        # Set before anything that reads it: the status refresh below runs whether or not the
        # server ends up starting.
        self._mcp_server = None
        self._bridge = QtUiBridge(self)
        self._bridge.confirmationRequested.connect(self._dialog.confirm_bar.enqueue)
        self._bridge.clipboardRequested.connect(lambda text: QGuiApplication.clipboard().setText(text))
        self._bridge.proposalReceived.connect(self._on_proposal)
        self._bridge.critiqueReceived.connect(self._on_critique)
        # A terminal-driven onboarding session's finalize_profile lands here -- the in-app chat
        # doesn't need this, it already restarts into a fresh window off its own signal.
        self._bridge.profileReady.connect(self._load_project)
        # `report_phase` no longer writes anything -- it signals that the SKILL wrote something,
        # and this is where that signal lands (D-6). Broader than the process-state watcher in
        # `_load_process`: a phase move usually comes with a new ledger snapshot and new project
        # facts, which nothing else is watching.
        self._bridge.refreshRequested.connect(self._reload_from_disk)
        self._publish_snapshot()
        self._refresh_critic_status()

        if os.environ.get("AUTOSOUND_TCC_MCP", "1") == "0":
            # Opting out leaves TCC a state viewer with no local port open -- a legitimate choice
            # for anyone who doesn't want one, and what the test suite uses to stay off the
            # network.
            return
        try:
            self._mcp_server = TccMcpServer(bridge=self._bridge)
            self._mcp_server.start()
        except Exception as exc:  # port taken, unwritable project folder, ...
            self._mcp_server = None
            self._status_strip.notify(f"MCP: {exc}", level="warn")

    def _publish_snapshot(self) -> None:
        """Mirror what's on screen into the bridge, for `get_tcc_state` to read off-thread."""
        self._bridge.set_snapshot(
            preset=self._preset_override or config.resolve_preset(),
            project_dir=str(config.project_dir()),
            param_edit_mode=self._dialog.is_editing,
            theme=self._mode,
        )

    def _on_proposal(self, proposal: dict) -> None:
        text = (
            f"<b>{proposal.get('channel')}</b> · {proposal.get('param')}: "
            f"{proposal.get('from')} → <b>{proposal.get('to')}</b><br>{proposal.get('rationale', '')}"
        )
        self._dialog._add_system_message(text)

    def _on_critique(self, critique: dict) -> None:
        self._dialog.add_critique(critique)
        self._refresh_critic_status()

    def _critic_choice(self) -> Optional[model_choices.Choice]:
        key = self._ai_critic_combo.currentData()
        return model_choices.find(self._critic_choices, str(key)) if key else None

    def _on_critic_model_changed(self, _index: int) -> None:
        """The footer picker steers the reviewer subprocess through its own env var."""
        choice = self._critic_choice()
        if choice is None:
            return
        self._settings.setValue(_CRITIC_KEY, choice.key)
        self._bridge.set_snapshot(critic_model=choice.model)

    def _refresh_critic_status(self) -> None:
        entry = critic.last_call(self._mcp_server.project_dir if self._mcp_server else None)
        if not entry:
            self._critic_status.setText(i18n.t("criticNever"))
            return
        self._critic_status.setText(
            i18n.t("criticStatus").format(
                model=entry.get("model") or entry.get("mode", "?"),
                ago=_ago(entry.get("at", "")),
            )
        )

    def _start_tuning_session(self) -> None:
        """Front-end A: run the skill in-process and stream it into the dialog panel."""
        worker = getattr(self, "_agent_worker", None)
        if worker is not None:
            # Same model: nothing to do. A different one: the running conversation ends, because
            # neither harness can swap a model under a live session.
            if self._running_model == self._ai_main_combo.currentData():
                return
            self._hand_off_then_restart(worker)
            return
        self._launch_session()

    # ---- handing the project over between sessions -------------------------

    def _hand_off_then_restart(self, worker) -> None:
        """Ask the running agent to write down where the project stands, then swap models.

        A conversation is disposable; the files are the record ("machine files win"). Everything
        the outgoing model understood that is not in `process/journal.jsonl`, the process state and
        `autosound_context.md` is lost the moment its session ends -- and the incoming one starts by
        reading exactly those files. Killing the session first would throw away the one thing that
        makes the restart cheap.

        Costs a turn, on purpose. The alternative is a new session that rediscovers what the old
        one already knew, which costs more.
        """
        if getattr(self, "_handoff_timer", None) is not None:
            return  # already saving; a second click must not start a second handoff
        self._dialog._add_system_message(i18n.t("sessionHandoff"))
        self._session_btn.setEnabled(False)
        worker.turn_done.connect(self._finish_handoff)
        worker.failed.connect(self._finish_handoff)
        # An agent that never finishes the turn must not strand the restart -- the point of the
        # handoff is to save what can be saved, not to make the swap conditional on it.
        self._handoff_timer = QTimer(self)
        self._handoff_timer.setSingleShot(True)
        self._handoff_timer.timeout.connect(self._finish_handoff)
        self._handoff_timer.start(_HANDOFF_TIMEOUT_MS)
        worker.send(_HANDOFF_PROMPT)

    def _finish_handoff(self, *_args) -> None:
        timer, self._handoff_timer = getattr(self, "_handoff_timer", None), None
        if timer is None:
            return  # already finished: whichever of turn_done/failed/timeout lost the race
        timer.stop()
        worker = getattr(self, "_agent_worker", None)
        if worker is not None:
            for signal in (worker.turn_done, worker.failed):
                try:
                    signal.disconnect(self._finish_handoff)
                except (RuntimeError, TypeError):
                    pass
            worker.shutdown()
        self._agent_worker = None
        self._dialog._add_system_message(i18n.t("sessionRestarted"))
        self._launch_session()

    def _launch_session(self) -> None:
        if self._mcp_server is None:
            self._dialog._add_system_message("⚠️ MCP server is not running — start TCC again.")
            return

        server = self._mcp_server
        choice = self._generator_choice()
        if choice is None:
            return
        if choice.harness == "omp" and not omp_session.is_available():
            self._dialog._add_system_message(i18n.t("ompMissing"))
            return
        probe = TuningSession(project_dir=server.project_dir)  # cheap: only reads the registry
        resumed = probe.resumed_from is not None
        if choice.harness == "omp":
            # omp reads the project's own `.mcp.json`, which the MCP server wrote on start, so it
            # needs no url/token of its own.
            factory = lambda: omp_session.OmpSession(  # noqa: E731
                project_dir=server.project_dir,
                bridge=self._bridge,
                model=choice.model,
                resume=resumed,
            )
        else:
            factory = lambda: TuningSession(  # noqa: E731
                project_dir=server.project_dir,
                mcp_url=server.url,
                mcp_token=server.token,
                bridge=self._bridge,
                model=choice.model,
            )
        self._agent_worker = AgentWorker(session_factory=factory)
        self._dialog.attach_agent(
            self._agent_worker,
            server.bus,
            resumed=resumed,
            phase=server.registry.current_phase(),
        )
        self._running_model = choice.key
        self._agent_worker.start()
        self._update_session_button()

    # ---- which model, and therefore which harness --------------------------

    def _active_omp(self) -> list[str]:
        raw = self._settings.value(_ACTIVE_OMP_KEY, "")
        return [selector for selector in str(raw).split(",") if selector]

    def _reload_model_choices(self) -> None:
        """Refill both pickers from one registry, keeping selections that survived."""
        active = self._active_omp()
        self._model_choices = model_choices.choices(active)
        self._critic_choices = model_choices.critic_choices(active)
        self._fill_combo(
            self._ai_main_combo, self._model_choices, str(self._settings.value(_GENERATOR_KEY, ""))
        )
        self._fill_combo(
            self._ai_critic_combo,
            self._critic_choices,
            str(self._settings.value(_CRITIC_KEY, "")),
            critic=True,
        )

    @staticmethod
    def _fill_combo(combo, entries, wanted: str, critic: bool = False) -> None:
        blocked = combo.blockSignals(True)
        combo.clear()
        for choice in entries:
            notes = []
            if choice.free:
                notes.append(i18n.t("modelFree"))
            if critic and not model_choices.critic_reaches(choice):
                notes.append(i18n.t("modelClipboardOnly"))
            suffix = f"  ·  {' · '.join(notes)}" if notes else ""
            # Which harness carries the model is the licensing split (spike/HANDOFF.md 5-ter), so
            # it is named in the entry rather than left to be inferred from the vendor.
            prefix = "SDK · " if choice.harness == "sdk" else ""
            combo.addItem(f"{prefix}{choice.label}{suffix}", choice.key)
        index = combo.findData(wanted) if wanted else -1
        if index < 0 and not critic:
            # Nothing chosen yet: say so rather than pre-selecting the first entry. A model that
            # was never picked must not be startable by someone who did not notice a default.
            combo.insertItem(0, i18n.t("modelUnchosen"), "")
            index = 0
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(blocked)

    def _generator_choice(self) -> Optional[model_choices.Choice]:
        key = self._ai_main_combo.currentData()
        return model_choices.find(self._model_choices, str(key)) if key else None

    def _on_generator_model_changed(self, _index: int) -> None:
        choice = self._generator_choice()
        if choice is None:
            self._update_session_button()
            return
        self._settings.setValue(_GENERATOR_KEY, choice.key)
        # The placeholder has served its purpose the moment a real model is chosen.
        placeholder = self._ai_main_combo.findData("")
        if placeholder >= 0:
            self._ai_main_combo.removeItem(placeholder)
        self._update_session_button()

    def _update_session_button(self) -> None:
        """Say what clicking will do, in the three states a session can be in.

        Neither harness can change model mid-conversation -- the SDK takes it in
        `ClaudeAgentOptions` at connect, omp as `--model` when the process starts -- so picking a
        different model while one is running is a restart, and the button says restart rather than
        letting someone discover it after the fact.
        """
        choice = self._generator_choice()
        running = getattr(self, "_agent_worker", None) is not None
        if not running:
            self._dialog.set_idle_label(choice.label if choice else None)
        if choice is None:
            self._session_btn.setText(i18n.t("startSession"))
            self._session_btn.setEnabled(False)
            self._session_btn.setToolTip(i18n.t("startSessionNoModel"))
            return
        if running and self._running_model not in (None, choice.key):
            self._session_btn.setText(i18n.t("restartSession").format(model=choice.label))
            self._session_btn.setEnabled(True)
            self._session_btn.setToolTip(i18n.t("restartSessionTip"))
            return
        self._session_btn.setText(i18n.t("startSession"))
        self._session_btn.setEnabled(not running)
        self._session_btn.setToolTip(
            i18n.t("startSessionRunning") if running
            else i18n.t("startSessionReady").format(model=choice.label)
        )

    def _open_model_config(self) -> None:
        dialog = ModelConfigDialog(self._active_omp(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._settings.setValue(_ACTIVE_OMP_KEY, ",".join(dialog.active))
        self._reload_model_choices()
        self._update_session_button()

    def _open_terminal(self) -> None:
        """Front-end B: hand the project to the user's own CLI in their own terminal.

        Same choice as the in-app session, same reasoning: the model picker decides the harness,
        so the terminal opens on the CLI that carries it -- `claude` for an SDK choice, `omp` for
        an omp one -- rather than on whatever happens to be first on PATH. Two front-ends that
        disagree about which model is running would make the picker a lie in one of them.
        """
        project_dir = self._mcp_server.project_dir if self._mcp_server else config.project_dir()
        choice = self._generator_choice()
        if choice.harness == "omp":
            cli, model = "omp", choice.model
            # Without the overlay TCC's own tools stay behind xd:// and never reach the model --
            # the terminal would be quietly weaker than the in-app session for no visible reason.
            extra = ("--config", str(omp_session.overlay_path(project_dir)))
        else:
            cli, model, extra = "claude", choice.model, ()
        try:
            launched = terminal_launcher.launch(
                project_dir, cli=cli, model=model, extra=extra
            )
        except terminal_launcher.TerminalLaunchError as exc:
            self._status_strip.notify(str(exc), level="warn")
            return
        self._status_strip.notify(i18n.t("terminalOpened").format(cli=launched))

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # The one-shot ping is normally long finished by the time anyone closes the window, but
        # Qt destroying a still-running QThread is undefined behaviour regardless of how unlikely.
        ping = getattr(self, "_rew_ping", None)
        if ping is not None and ping.isRunning():
            ping.wait(2000)
        # Let any in-flight REW worker on the measurement panel finish before the window (and its
        # widgets) go away -- see MeasurementPanel.shutdown()'s docstring for why this matters.
        self._meas_panel.shutdown()
        # Deny anything the agent is still waiting on: an unanswered confirmation would otherwise
        # keep an MCP call parked until its timeout, long after the window it belonged to is gone.
        self._dialog.confirm_bar.reject_all()
        worker = getattr(self, "_agent_worker", None)
        if worker is not None:
            # Interrupt-then-wait, not just stop-then-wait: a worker mid-turn never reads the
            # stop sentinel, and Qt destroying a still-running QThread is undefined behaviour.
            worker.shutdown()
        if getattr(self, "_mcp_server", None) is not None:
            self._mcp_server.stop()
        super().closeEvent(event)

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
        self._project_section.set_title(i18n.t("projectParams"))
        self._system_section.set_title(i18n.t("systemParams"))
        self._rebuild_system_params()
        self._audio_section.set_title(i18n.t("audioAnalysis"))
        self._audio_placeholder.setText(i18n.t("noDataYet"))
        self._dsp_section.set_title(i18n.t("dspPanel"))
        self._set_project_params(self._view)
        self._plan_title.setText(i18n.t("planTitle"))
        self._plan_sub.setText(i18n.t("planSub"))
        self._meas_title.setText(i18n.t("focus"))
        self._meas_sub.setText(i18n.t("measSub"))
        self._preset_field_lbl.setText(i18n.t("preset"))
        self._target_field_lbl.setText(i18n.t("target"))
        self._target_tip.set_text(i18n.t("targetToolTip"))
        self._refresh_tip.set_text(i18n.t("refreshProjectTip"))
        self._diag_tip.set_text(i18n.t("diagBtnTip"))
        self._ai_main_lbl.setText(i18n.t("aiMain"))
        self._ai_critic_lbl.setText(i18n.t("aiCritic"))
        self._feedback_btn.setText("💬 " + i18n.t("fbBig"))
        self._coffee_btn.setText(i18n.t("coffeeBtn"))
        for i in range(self._preset_combo.count()):
            self._preset_combo.setItemText(i, _preset_label(self._preset_combo.itemData(i)))
        self._plan_panel.retranslate()
        self._meas_panel.retranslate()
        if not self._has_project:
            # MeasurementPanel.retranslate() deliberately skips rebuilding its grid while
            # set_no_project() is active (see its own comment) -- but that also means it can't
            # re-resolve the message text itself, since it only ever sees the already-resolved
            # string MainWindow passed in, not the i18n key.
            self._meas_panel.set_no_project(i18n.t("noProjectMeas"))
        self._create_project_btn.setText(i18n.t("createProject"))
        self._dialog.retranslate()
        # The tree builds its group headers / params-row labels from i18n at set_view() time and
        # has no live binding, so rebuild it in the new language (cheap -- a handful of widgets).
        if self._view is not None:
            self._tree.set_view(self._view)
