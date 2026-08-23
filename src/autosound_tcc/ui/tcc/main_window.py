"""The main TCC window — layout skeleton ported from the web prototype
(`data/private/prototype/tcc-main.html`): header / left DSP panel / center (detail + AI dialog) /
right (plan-fact + measurement task) / footer, matching the prototype's CSS grid areas
`head`/`left`/`center`/`right`/`foot`.

M1 scope only: the shell, theme, and empty section placeholders. The real content of each panel
lands in later milestones (see the plan file / task list) — this file will keep growing as each
section gets wired to real data, but the outer structure built here should not need to change.
"""

from __future__ import annotations

import atexit
import os
import threading
import re
import sys
import time
import weakref
from pathlib import Path

from PySide6.QtCore import (
    QFileSystemWatcher,
    QPoint,
    QProcess,
    QThread,
    QTimer,
    QUrl,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QFileDialog,
    QMenu,
    QMessageBox,
    QToolButton,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import (
    install_report,
    app_log,
    claude_sdk,
    config,
    self_check,
    contract_check,
    critic,
    model_choices,
    model_overrides,
    omp_session,
    process_writer,
    project_settings,
    terminal_launcher,
    updates,
)
from autosound_tcc.core.contract_check import ContractReport
from autosound_tcc.core.mcp_server import TccMcpServer
from autosound_tcc.core.rew_bridge import RewBridge
from autosound_tcc.core.tuning_session import TuningSession
from autosound_tcc.state import (
    acoustics_view,
    measurement_view,
    plan_audit,
    process_view,
    project_view,
    proposal_view,
)
from autosound_tcc.core import signal_bus
from autosound_tcc.state.dsp_state import ProjectView, load_project_view, rig_view
from autosound_tcc.ui.tcc import copy_menu, i18n
from autosound_tcc.ui.tcc.agent_worker import AgentWorker
from autosound_tcc.ui.tcc.qt_bridge import QtUiBridge
from autosound_tcc.ui.tcc.detail_pane import DetailPane
from autosound_tcc.ui.tcc.diagnostics_panel import DiagnosticsDialog
from autosound_tcc.ui.tcc.dialog_panel import DialogPanel
from autosound_tcc.ui.tcc.feedback_dialog import FeedbackDialog
from autosound_tcc.ui.tcc import dsp_tree
from autosound_tcc.ui.tcc.dsp_tree import DspTreeWidget
from autosound_tcc.ui.tcc.measurement_panel import MeasurementPanel, TrafficLight
from autosound_tcc.ui.tcc.model_config_dialog import ModelConfigDialog
from autosound_tcc.ui.tcc.new_project_dialog import NewProjectDialog
from autosound_tcc.ui.tcc.resonalyze_import_dialog import ResonalyzeImportDialog
from autosound_tcc.ui.tcc.app_settings import get_settings
from autosound_tcc.ui.tcc.labels import ElidedLabel
from autosound_tcc.ui.tcc.plan_panel import PlanPanel
from autosound_tcc.ui.tcc import rounded_tooltip
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
# Imported from the curve view because that is where it was written and where it is used most.
# It belongs beside `rounded_tooltip`, whose widget it formats for, and moving it there is a
# separate change: `curve_view.py` is being edited in another thread of work right now, and a
# helper's address is not worth a merge conflict.
from autosound_tcc.ui.tcc.curve_view import tip_html
from autosound_tcc.ui.tcc.sidebar_section import (
    CollapsibleGroup,
    SidebarSection,
    clear_layout,
)
from autosound_tcc.ui.tcc.status_strip import StatusStrip
from autosound_tcc.ui.tcc.theme import apply_caps, apply_theme, current_theme
from autosound_tcc.ui.tcc.theme import mini_combo as theme_mini_combo

_THEME_KEY = "ui/theme"
_ZOOM_KEY = "ui/zoom"
_LANG_KEY = "ui/lang"
# Which models drive this project lives WITH the project (`.tcc/tcc-project.json`): opening a
# second folder must not silently re-point the first. Which omp models this machine can reach is
# the opposite -- a fact about the user's accounts, not about any project -- so it stays global.
_GENERATOR_KEY = "generator"          # per project: the picked Choice.key
_CRITIC_KEY = "critic"                # per project: the picked Choice.key for the reviewer
_GATE_KEY = "gate"                    # per project: which writes still ask the Arbiter
_EFFORT_KEY = "effort"                # per project: how hard the Generator is asked to think
_ALWAYS_KEY = "always_allowed"        # per project: tools the Arbiter stopped being asked about
_ACTIVE_OMP_KEY = "ai/active_omp"     # per user: selectors marked usable on this machine

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
# When a channel request stops being "just asked" and starts being a fact worth flagging. The
# model answers a signal within a turn; a minute of silence means the turn is long, the queue was
# missed, or nobody is listening -- all three are things the Arbiter should see rather than guess.
_TOGGLE_LATE_S = 60
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
    labels (the language picker was collapsing "EN"/"UK" down to "E"/"U", and on Windows every
    list came back elided — see `theme.MiniCombo`)."""
    return theme_mini_combo()


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


def _tier_label(tier_id: str) -> str:
    """A channel tier's name for a Project-params row, in the panel's own language.

    `i18n.t` answers with the key itself when it has never heard of one, which for a tier the
    skill invents would print `chanSum_rear_fill` at a person. An unknown tier falls back to the
    id read as words -- the same thing the summary did for every tier before it was translated.
    """
    key = f"chanSum_{tier_id}"
    label = i18n.t(key)
    return tier_id.replace("_", " ").capitalize() if label == key else label


def _tier_count(total: int, off: int) -> str:
    """`8` when every channel is in play, `8 (1 off)` when one is not. No `(0 off)` noise."""
    return i18n.t("chanSumOff").format(total=total, off=off) if off else str(total)


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
    # Both sides give ground, in proportion, and neither can widen the panel. The value used to
    # refuse to shrink at all, on the grounds that it is the fact the row exists to show -- and one
    # model id (`google/deep-research-preview-04-2026`, 314 px against a 198 px viewport) then made
    # the whole left column scroll sideways, putting every row's right-hand end past the edge, the
    # channel ON/OFF switches included. Letting the key take the whole cut is no better: "По…" and
    # "D…" name nothing. Whatever is cut on either side is in the tooltip.
    k = ElidedLabel(key, min_width=40)
    k.setProperty("class", "pk")
    layout.addWidget(k, stretch=5)
    v = ElidedLabel(value, min_width=40)
    v.setProperty("class", "pv")
    v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(v, stretch=6)
    if trailing is not None:
        layout.addWidget(trailing)
    # Right-click, not selection: a selectable label captures the mouse, and these rows sit in
    # panels where a click means something. `ElidedLabel` is asked for its FULL text, so what lands
    # on the clipboard is the fact rather than whatever survived the elide.
    copy_menu.enable_copy(
        row,
        value=lambda: copy_menu.full_text(v),
        row=lambda: f"{copy_menu.full_text(k)}: {copy_menu.full_text(v)}",
        hint=lambda: v.toolTip() or k.toolTip(),
    )
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


def _mark_missing(combo, entries, warn: bool = False) -> None:
    """Red when the current choice is not among `entries`, plain when it is.

    Recomputed on every selection change, not only when the list is rebuilt. It was set once at
    fill time, so a combo that had ever been red STAYED red through every later pick — the Arbiter
    chose a model that exists and the field went on claiming it did not (user, 2026-08-12).

    `warn` is the other tint — the choice exists but is not what it appears to be — and it is
    passed in rather than applied by the caller afterwards because both write the same `class`
    property: whoever wrote second used to erase the other's answer.
    """
    current = str(combo.currentData() or "")
    # A route whose CLI is not installed counts as missing here, even though its row is now on the
    # list (greyed, saying what it needs). The row exists so the option is discoverable; the field
    # still has to say that what it currently holds cannot run.
    missing = bool(current) and not any(
        choice.key == current and choice.available for choice in entries
    )
    classes = "mini-select" + (" is-missing" if missing else "") + (" is-warn" if warn else "")
    combo.setProperty("class", classes)
    combo.style().unpolish(combo)
    combo.style().polish(combo)


def _sdk_login_note(choice) -> tuple[str, str]:
    """"You picked Claude and this machine has no Claude login" — headline and detail, or both empty.

    Only for a `False` from `signed_in()`. `None` means the probe could not tell (no CLI to ask, a
    timeout, output we do not recognise) and must stay silent: sending somebody to redo a login
    that was fine is a worse error than saying nothing.
    """
    if choice is None or getattr(choice, "harness", "") != "sdk":
        return "", ""
    if claude_sdk.signed_in() is not False:
        return "", ""
    return i18n.t("sdkNoLogin"), i18n.t("sdkNoLoginTip").format(cmd=claude_sdk.LOGIN_HINT)


def _cap_combo_width(combo) -> None:
    """Stop a combo's WIDEST MENU ROW from setting the width of its closed box.

    A model row reads "SDK · Claude Opus 5 · recommended pair · free", and by default a QComboBox
    sizes itself to fit the longest one of those even while showing a short label. Two of them in
    the footer is most of a screen spent on text nobody is looking at, and it squeezed the reviewer
    status down to "gem…". The menu still shows every row in full; only the closed box is capped.
    """
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(16)
    combo.setMaximumWidth(260)


def _replacements_for(key: str, entries: list) -> list:
    """`entries`, ordered so the sensible stand-ins for `key` come first.

    Same vendor first (user, 2026-08-11). A replacement is meant to be the nearest thing that
    still runs, and the list is alphabetical by route otherwise — so the default selection was
    whatever happened to sort first. That is how a Gemini reviewer became a Claude one, which is
    not a replacement at all: it is the end of cross-vendor review, chosen by a combo box.
    """
    wanted = key.partition(":")[2] or key
    marker = next(
        (vendor for token, vendor in model_choices._CRITIC_VENDOR_MARKERS if token in wanted.lower()),
        "",
    )
    if not marker:
        return list(entries)
    same = [c for c in entries if model_choices.vendor_of(c) == marker]
    other = [c for c in entries if model_choices.vendor_of(c) != marker]
    return same + other


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
        self._child = None

    def run(self) -> None:
        self.result.emit(contract_check.run(self._project_dir, register=self._took_child))

    def _took_child(self, child) -> None:
        self._child = child

    def cancel(self) -> None:
        """End the check now rather than at its 30 s timeout.

        Killing the child is the only lever that works: this thread is blocked reading the child's
        output, so it reads no interrupt flag. Waiting the full timeout instead would freeze a
        window on its way out for half a minute, and NOT waiting means Qt destroys a running
        QThread -- which is not a warning but a `qFatal`, i.e. the whole process aborts. Seen
        exactly that way, as a macOS crash report with `_ContractWorker` still in `poll`.
        """
        child = self._child
        if child is not None and child.poll() is None:
            child.kill()


# Every window ever built, weakly. The point is the `atexit` hook below: a process that ends
# without closing its window -- a script, a test, anything driving the window headlessly -- gets
# its threads stopped anyway. Weak so that holding this list never keeps a window alive.
_live_windows: "weakref.WeakSet[MainWindow]" = weakref.WeakSet()


_quit_hook_connected = False


def _connect_quit_hook(app) -> None:
    """Connect `_stop_all_workers` to `aboutToQuit` exactly once per process."""
    global _quit_hook_connected
    if _quit_hook_connected:
        return
    app.aboutToQuit.connect(_stop_all_workers)
    _quit_hook_connected = True


def _stop_all_workers() -> None:
    """Stop every live window's background threads at interpreter exit.

    Registered here rather than only on the window because PySide's own shutdown -- which destroys
    the QThread objects, and calls `qFatal` if one is still running -- is itself an `atexit`
    handler, registered when QtCore is imported. `atexit` runs last-registered-first, and this is
    registered later, so it runs before PySide gets there.
    """
    for window in list(_live_windows):
        try:
            window.stop_workers()
        except RuntimeError:
            pass  # its C++ side is already gone; nothing left to stop


atexit.register(_stop_all_workers)


class _CliCatalogueWorker(QThread):
    """Ask the local CLIs what they can run, off the GUI thread.

    `agy models` fetches over the network. The pickers are built while the window is being
    constructed, so asking there would freeze the launch — and a route that answers slowly must
    not be a route that looks absent.
    """

    done = Signal()

    def run(self) -> None:
        model_choices.refresh_cli_catalogue()
        # Same thread, same reason: `claude auth status` is a subprocess, and the pickers are
        # built during construction. Asking there would put a process launch in front of the
        # first paint on every startup.
        claude_sdk.probe_signed_in()
        self.done.emit()

    quiet = Signal(list)  # routes that are installed and answered with nothing


class _CaptureCheckWorker(QThread):
    """Run the skill's capture verdict off the GUI thread (SCR-040).

    It pulls every expected measurement out of REW through the skill's own checker, so it is the
    slowest of TCC's background calls and the one that must never run inline: the window would
    freeze for seconds while somebody is sitting in a car waiting to move the mic.
    """

    result = Signal(str)  # the checker's own output, or the refusal verbatim

    def __init__(self, project_dir) -> None:
        super().__init__()
        self._project_dir = project_dir

    def run(self) -> None:
        try:
            self.result.emit(process_writer.check_captures(self._project_dir))
        except process_writer.ProcessWriterError as exc:
            self.result.emit(str(exc))


class MainWindow(QMainWindow):
    # An error was written to the log. A plain signal because `threading.excepthook` fires on the
    # thread that failed, and touching a widget from there is undefined behaviour -- Qt marshals
    # it back onto the GUI thread for us.
    loggedError = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.loggedError.connect(self._show_logged_error)
        self.resize(1280, 820)
        _live_windows.add(self)

        self._settings = get_settings()
        self._mode = self._settings.value(_THEME_KEY, None) or _detect_system_mode()
        self._zoom = float(self._settings.value(_ZOOM_KEY, 1.0))
        self._view: ProjectView | None = None
        self._has_project = False  # set for real by _load_project(); read by _refresh_process()
        # What the Arbiter asked of a channel and has not been answered about yet: the wait
        # `_on_channel_toggle` writes onto the row, keyed by (group, channel). Here, at the top,
        # because the first `_rebuild_system_params()` runs while the window is still being built
        # and every switch row asks whether it is waiting. It lives on the window and not on the
        # button because the buttons are rebuilt whenever the project reloads and the request
        # outlives them. The timer only runs while something is waiting.
        self._pending_toggles: dict[tuple[str, str], dict] = {}
        self._toggle_buttons: dict[tuple[str, str], QPushButton] = {}
        self._pending_timer = QTimer(self)
        self._pending_timer.setInterval(1000)
        self._pending_timer.timeout.connect(self._tick_pending_toggles)
        # F-020. Delivery rides into the next turn, and until this there had to BE a next turn:
        # a click was answered whenever the Arbiter happened to say something else. Polled rather
        # than pushed from the bus, because `push()` is called on the GUI thread but `ack()` is
        # not, and a timer here asks the question where the answer can be acted on.
        self._nudged_signal_ids: set[str] = set()
        self._nudge_timer = QTimer(self)
        self._nudge_timer.setInterval(2000)
        self._nudge_timer.timeout.connect(self._nudge_for_open_signals)
        self._nudge_timer.start()
        self._rew_online: bool | None = None  # None = not checked yet -- read before _build_left()
        # Diagnostics (TCC-TZ.md §8). Set up before _build_header(), which adds the button that
        # opens the dialog, and before _load_project(), which re-runs the check.
        self._contract_report: ContractReport | None = None
        self._contract_worker: _ContractWorker | None = None
        self._diag_dialog: DiagnosticsDialog | None = None
        #: What the curve window was last plotting, per capture series — see
        #: `_open_curves_from_panel`. In memory only, and deliberately: it is "what am I working on
        #: right now", which is a fact about this sitting rather than about the project, and a
        #: remembered set restored a week later would reopen an argument that has been settled.
        self._curve_last: dict[str, list[str]] = {}
        self._preset_override: str | None = self._settings.value("ui/preset", None)
        i18n.set_language(self._settings.value(_LANG_KEY, "en"))
        # Which project folder is actually open matters the moment you run TCC against more than
        # one (user request 2026-07-29) -- there's no in-app project switcher yet, only
        # AUTOSOUND_PROJECT_DIR/the QSettings-persisted choice, so the title is the only place
        # that's visible before digging into the DSP tree.
        # ...with both versions at the end. The title bar is in every screenshot anybody sends, so
        # it is the cheapest place a version can live: no tab to open, nothing to ask for (user,
        # 2026-08-19). Two numbers, because a bug is against a PAIR — the app and the method — and
        # either one alone leaves the other to be guessed.
        self._title_note = ""
        self._set_title()

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
        # An unhandled exception now goes to a log file rather than to the terminal TCC was
        # launched from (core/app_log.py). Silence would be worse than the terminal was, though:
        # a failure the user cannot see is a failure they report as "it just did nothing".
        app_log.set_ui_sink(self._on_logged_error)

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
        # A side panel is a fixed column with a handle, not something that resizes itself. Without
        # this a single long row grew the panel, the panel grew the window, and a maximised window
        # grew past the screen edge -- reported exactly that way. The handle still works.
        for side in (self._left, self._right):
            side.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            side.setMinimumWidth(200)
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
        self._meas_panel.titlesChanged.connect(self._on_rew_titles_changed)
        self._capture_check: "_CaptureCheckWorker | None" = None

        # One contract check at launch, so the status strip can say "this project has N problems"
        # before the user goes looking. Same escape hatch as the two workers above.
        self._start_contract_check()

        # What the local CLIs offer, fetched in the background and folded into the pickers when it
        # lands. Until then those routes are simply absent rather than the window being late.
        self._cli_catalogue = _CliCatalogueWorker()
        self._cli_catalogue.done.connect(self._on_cli_catalogue_ready)
        if os.environ.get("AUTOSOUND_TCC_MCP", "1") != "0":
            self._cli_catalogue.start()
            # Ask once, on the same switch: whatever turns off the background work of a test run
            # turns this off too, so no suite ever reaches GitHub for a title bar.
            self._check_for_updates()

        # Quitting is not closing: Cmd-Q, a signal, or `QApplication.quit()` end the loop without
        # any window's `closeEvent` necessarily running, and whatever is still on a thread then is
        # destroyed under Qt -- which aborts. Both routes lead to the same cleanup.
        app = QApplication.instance()
        if app is not None:
            # The MODULE function, not `self.stop_workers`. A bound method handed to a Qt signal
            # is a strong reference held by the QApplication for the life of the process, so every
            # window ever built stayed alive — `_live_windows` is a WeakSet precisely so that does
            # not happen, and this one line defeated it. In the app that is one leaked window per
            # project switch; in the test suite it is quadratic, because `setStyleSheet` re-polishes
            # every widget in the process and there were ninety windows' worth by the end
            # (measured 2026-08-12: window #1 0.26 s, #25 1.81 s). `_stop_all_workers` walks the
            # WeakSet, so it does the same job holding nothing.
            _connect_quit_hook(app)

    # ---- header / footer -------------------------------------------------

    def _build_header(self) -> QFrame:
        header = _panel()
        header.setProperty("class", "panel phead")  # header itself IS a .panel in the prototype
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(14)

        # Leftmost, and since 2026-08-23 it is the application's MAIN MENU: "let us make this
        # the main menu and gather everything there logically" (user). It carries the whole
        # window's vocabulary in five sections, so a person looking for a thing has ONE place to
        # look instead of a header, a footer, a left-column button and two popups.
        #
        # A button that says MENU, and the project name beside it as plain text (user, same day).
        # The two had been one control -- a dropdown whose label was the project -- which made the
        # menu look like a project picker and the project name look like a thing to press. Now the
        # button says what it opens, and the name says what you are working on.
        self._menu_btn = QToolButton()
        self._menu_btn.setText(i18n.t("menuButton"))
        self._menu_btn.setProperty("class", "reason-btn project-btn")
        self._menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._build_main_menu()
        layout.addWidget(self._menu_btn)

        # Elided rather than wrapped or truncated: project folders are dated and long
        # (`passat-block-a-v7-2026-08-20`), and the header is not allowed to grow to fit one.
        # The full path is on the tooltip.
        # `Maximum`, not the default `Ignored`: this label is a VALUE (the docstring's own word)
        # -- it asks for its natural width and only gives ground when the header would otherwise
        # widen. With `Ignored` it took whatever was left, which at this size was almost nothing,
        # and the name sat on top of the preset label beside it.
        self._project_label = ElidedLabel(
            "", min_width=120, policy=QSizePolicy.Policy.Maximum
        )
        self._project_label.setProperty("class", "kv-val")
        layout.addWidget(self._project_label)
        self._refresh_project_button()

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

        # Always visible (not just in the no-project states). The project files and the ledger are
        # watched now, but a watcher is a best effort -- a network or synced folder may not report,
        # and a project opened from a path whose parents changed underneath it will not -- so this
        # stays as the one manual "reload from disk" a user can always reach, regardless of which
        # left-panel accordion section happens to be collapsed (user request 2026-07-29: the
        # earlier left-panel version was easy to lose track of).
        self._header_refresh_btn = QPushButton("↻")
        self._header_refresh_btn.setProperty("class", "icon-btn")
        self._header_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_refresh_btn.clicked.connect(self._reload_from_disk)
        self._refresh_tip = attach_tip(self._header_refresh_btn, i18n.t("refreshProjectTip"))
        layout.addWidget(self._header_refresh_btn)

        # Diagnostics sits next to the reload button on purpose: both answer "what is actually on
        # disk right now", and §8 wants that question reachable in every mode, not buried in a menu.
        # A gear, not the old medical mark: what opens here is the state of the installation and
        # the repairs for it, and ⚕ read as something clinical nobody could place. Orange, the
        # app's accent, because this is the button somebody is looking for when something is wrong
        # (user, 2026-08-19).
        self._diag_btn = QPushButton("⚙")
        self._diag_btn.setProperty("class", "icon-btn diag-btn")
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

    # ---- the main menu ------------------------------------------------------

    def _tip_menu(self, parent) -> QMenu:
        """A menu styled and tipped like the rest of the app.

        `setToolTipsVisible` is deliberately NOT used: the platform tooltip's window frame stays
        square on macOS whatever the QSS says, which is the exact limitation `rounded_tooltip`
        exists for. The menu drives the shared rounded popup as the highlight moves instead.
        """
        menu = QMenu(parent)
        menu.setProperty("class", "support-menu")
        menu.hovered.connect(self._show_action_tip)
        menu.aboutToHide.connect(rounded_tooltip.RoundedTooltip.instance().hide_tip)
        return menu

    def _menu_section(self, menu: QMenu, key: str) -> None:
        """A visible section heading.

        NOT `QMenu.addSection`, which is the obvious call and draws nothing here: with a custom
        stylesheet Qt renders a section as a plain separator and drops its text on the floor
        (grabbed the menu and looked -- five headings, none of them visible). A disabled action
        is text a style cannot swallow, and it is unclickable, which is what a heading is.
        """
        if not menu.isEmpty():
            menu.addSeparator()
        # Upper case in the text, because QSS has no `text-transform` -- and the caps are how
        # every other label in this window says "this names what is under it" (`apply_caps`).
        heading = menu.addAction(i18n.t(key).upper())
        heading.setEnabled(False)

    def _build_main_menu(self) -> None:
        """Everything the window can do, in one menu, in five sections.

        Rebuilt rather than retranslated: a menu's labels are set once at construction, so before
        this the items kept the language they were born in while the rest of the window switched
        around them. `_retranslate` calls this again, which is also what keeps the language
        check marks honest.

        The order is the order of a working day, not an alphabet: which project · what the
        session is doing · how the window looks · the tools beside the work · where to ask for
        help. Frequently-used items keep their own buttons in the chrome as well -- a menu that
        is the only way to reach a thing you press ten times an hour is not a kindness.
        """
        menu = self._tip_menu(self._menu_btn)

        self._menu_section(menu, "menuProject")
        self._open_project_action = menu.addAction(i18n.t("projectOpen"))
        self._open_project_action.setToolTip(i18n.t("projectOpenTip"))
        self._open_project_action.triggered.connect(self._choose_project_folder)
        self._new_project_action = menu.addAction(i18n.t("projectNew"))
        self._new_project_action.setToolTip(i18n.t("projectNewTip"))
        # Through a lambda, not straight: `triggered` carries the action's `checked` flag, which
        # would land in `seed` and make "new project" mean "copy the car" the day somebody makes
        # this action checkable.
        self._new_project_action.triggered.connect(
            lambda _checked=False: self._open_new_project_dialog()
        )
        # Its own line, because it is a different intent from "new project", not a different
        # button for it: this one starts from a car that is already described (user, 2026-08-23 --
        # "call it 'copy the car' and say in the hint that it is the car, the equipment and the
        # installation"). It opens the same dialog with the copying already chosen.
        self._copy_car_action = menu.addAction(i18n.t("menuCopyCar"))
        self._copy_car_action.setToolTip(i18n.t("menuCopyCarTip"))
        self._copy_car_action.triggered.connect(
            lambda _checked=False: self._open_new_project_dialog(seed=True)
        )
        self._reload_action = menu.addAction(i18n.t("menuReload"))
        self._reload_action.setToolTip(i18n.t("refreshProjectTip"))
        self._reload_action.triggered.connect(self._reload_from_disk)

        self._menu_section(menu, "menuSession")
        # Menu wording, not the buttons': "▶ Session in TCC" and "⧉ Terminal" are labels for
        # things you can SEE, sized to a footer. A menu line has room to say what it does.
        self._session_action = menu.addAction(i18n.t("menuStartSession"))
        self._session_action.triggered.connect(self._start_tuning_session)
        self._terminal_action = menu.addAction(i18n.t("menuTerminal"))
        self._terminal_action.triggered.connect(self._open_terminal)
        self._save_state_action = menu.addAction(i18n.t("projectSaveState"))
        self._save_state_action.setToolTip(i18n.t("projectSaveStateTip"))
        self._save_state_action.triggered.connect(self._save_project_state)
        self._fresh_session_action = menu.addAction(i18n.t("projectFreshSession"))
        self._fresh_session_action.setToolTip(i18n.t("projectFreshSessionTip"))
        self._fresh_session_action.triggered.connect(self._start_fresh_session)
        self._models_action = menu.addAction(i18n.t("menuModels"))
        self._models_action.setToolTip(i18n.t("menuModelsTip"))
        self._models_action.triggered.connect(self._open_model_config)
        gate_menu = self._tip_menu(menu)
        gate_menu.setTitle(i18n.t("gateMode"))
        menu.addMenu(gate_menu)
        self._gate_actions = {}
        for mode, label in ((omp_session.GATE_WRITES, "gateWrites"),
                            (omp_session.GATE_FOREIGN, "gateForeign"),
                            (omp_session.GATE_AUTO, "gateAuto")):
            action = gate_menu.addAction(i18n.t(label))
            action.setCheckable(True)
            action.setToolTip(i18n.t("gateAutoTip" if mode == omp_session.GATE_AUTO
                                     else "gateModeTip"))
            action.triggered.connect(lambda _c=False, m=mode: self._set_gate_mode(m))
            self._gate_actions[mode] = action

        self._menu_section(menu, "menuView")
        theme_action = menu.addAction("◐ " + i18n.t("menuTheme"))
        theme_action.triggered.connect(self._toggle_theme)
        lang_menu = self._tip_menu(menu)
        lang_menu.setTitle(i18n.t("menuLanguage"))
        menu.addMenu(lang_menu)
        for code, label in (("en", i18n.t("langNameEn")), ("uk", i18n.t("langNameUk"))):
            action = lang_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(i18n.current_language() == code)
            action.triggered.connect(lambda _c=False, l=code: self._on_language_selected(l))
        zoom_in_action = menu.addAction(i18n.t("menuZoomIn"))
        zoom_in_action.triggered.connect(self._zoom_in)
        zoom_out_action = menu.addAction(i18n.t("menuZoomOut"))
        zoom_out_action.triggered.connect(self._zoom_out)

        self._menu_section(menu, "menuTools")
        diag_action = menu.addAction(i18n.t("menuDiagnostics"))
        diag_action.setToolTip(i18n.t("diagBtnTip"))
        diag_action.triggered.connect(self._open_diagnostics)
        # In TOOLS, not in project (user, 2026-08-23): "it does not import a session, it takes
        # the settings -- crossovers, delays, EQ". He is right, and the old placement said
        # otherwise. Nothing about a project changes here: a file is read, every value is checked
        # against the processor, and the answer is a report. That is a tool, beside diagnostics
        # and the target-curve tool -- and it has nothing to do with the AI session either.
        self._import_action = menu.addAction(i18n.t("riImport"))
        self._import_action.setToolTip(i18n.t("riImportTip"))
        self._import_action.triggered.connect(self._open_resonalyze_import)
        target_action = menu.addAction(i18n.t("menuTargetTool"))
        target_action.setToolTip(i18n.t("targetToolTip"))
        target_action.triggered.connect(self._open_target_curve_tool)

        self._menu_section(menu, "menuHelp")
        feedback_action = menu.addAction("💬 " + i18n.t("fbBig"))
        feedback_action.setToolTip(i18n.t("fbBigTip"))
        feedback_action.triggered.connect(self._open_feedback)
        # The same two channels, and the same wording, as the method's own README -- GitHub
        # Sponsors for people with an account, the Monobank jar as the one-tap fallback. Not a
        # choice TCC makes on the user's behalf.
        github_action = menu.addAction(i18n.t("supportGithub"))
        github_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(_GITHUB_SPONSORS_URL))
        )
        mono_action = menu.addAction(i18n.t("supportMonobank"))
        mono_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(_MONOBANK_JAR_URL)))

        previous = self._menu_btn.menu()
        self._menu_btn.setMenu(menu)
        if previous is not None:
            # Deferred, never here: this can run from inside a language action's own handler, and
            # destroying the menu that emitted it is the crash shape this app has paid for twice.
            previous.deleteLater()
        # The check marks and enabled states the freshly built actions do not have yet.
        self._sync_menu_state()

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
        _cap_combo_width(ai_main)
        self._ai_main_combo = ai_main
        ai_main.currentIndexChanged.connect(self._on_generator_model_changed)
        layout.addWidget(ai_main)
        # The Generator has no same-vendor question — picking Claude to argue with Claude is only
        # wrong for the REVIEWER — but it has the one the Critic also has: a Claude route on a
        # machine nobody has logged in on. `available()` says the SDK is installed and stays true
        # forever; only `signed_in()` knows whether it can answer. A fresh Mac offered three
        # Claude models and could not have run any of them (2026-08-13).
        self._main_warn = QPushButton("!")
        self._main_warn.setProperty("class", "warn-mark")
        self._main_warn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._main_warn.setFixedSize(18, 18)
        self._main_warn.setVisible(False)
        self._main_warn.clicked.connect(self._explain_main_warning)
        self._main_warn_tip = attach_tip(self._main_warn, "")
        self._main_warn_detail = ""
        layout.addWidget(self._main_warn)

        # Beside the model, because it is fixed for the session exactly like the model is: the
        # Agent SDK takes effort at client construction, so this is a choice made when a session
        # starts and not one the Arbiter can reach for halfway through a hard step. Nothing below
        # `high` is offered -- it is not a tuning setting -- and nothing escalates on its own.
        self._ai_effort_lbl = QLabel(i18n.t("aiEffort"))
        self._ai_effort_lbl.setProperty("class", "kv-lbl")
        apply_caps(self._ai_effort_lbl, spacing_px=1.2)
        layout.addWidget(self._ai_effort_lbl)
        ai_effort = _mini_combo()
        for level in model_choices.EFFORT_LEVELS:
            ai_effort.addItem(i18n.t(f"effort_{level}"), level)
            ai_effort.setItemData(
                ai_effort.count() - 1, i18n.t(f"effortTip_{level}"), Qt.ItemDataRole.ToolTipRole
            )
        self._ai_effort_combo = ai_effort
        ai_effort.currentIndexChanged.connect(self._on_effort_changed)
        layout.addWidget(ai_effort)

        self._ai_critic_lbl = QLabel(i18n.t("aiCritic"))
        self._ai_critic_lbl.setProperty("class", "kv-lbl")
        apply_caps(self._ai_critic_lbl, spacing_px=1.2)
        layout.addWidget(self._ai_critic_lbl)
        # Same registry as the generator picker: one list, one place to configure. What differs
        # is reachability -- the reviewer script is Gemini-shaped (SCR-033), so anything else
        # lands in clipboard mode and says so here rather than after the wait.
        ai_critic = _mini_combo()
        _cap_combo_width(ai_critic)
        self._ai_critic_combo = ai_critic
        ai_critic.currentIndexChanged.connect(self._on_critic_model_changed)
        layout.addWidget(ai_critic)

        # Both combos exist now, so one pass fills them from the one registry.
        self._reload_model_choices()
        self._running_model: Optional[str] = None

        # What the picker's own label cannot say: this machine sends that key somewhere else, or
        # the reviewer ended up on the Generator's vendor. Both were happening on a live tune
        # while the footer read "AGY · Gemini 3.1 Pro (High) · recommended pair" (2026-08-11).
        # Empty and hidden when there is nothing to report -- a permanently-visible caveat is a
        # caveat nobody reads.
        # A red "!" and nothing else (user, 2026-08-11). It was a sentence, and a sentence in this
        # row is a footer that pushes the window off the screen; elided to fit, it was a sentence
        # nobody could read. A mark is legible at any width, and the reason belongs where there is
        # room for it — one click away.
        self._critic_warn = QPushButton("!")
        self._critic_warn.setProperty("class", "warn-mark")
        self._critic_warn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._critic_warn.setFixedSize(18, 18)
        self._critic_warn.setVisible(False)
        self._critic_warn.clicked.connect(self._explain_critic_warning)
        self._critic_warn_tip = attach_tip(self._critic_warn, "")
        self._critic_warn_detail = ""
        layout.addWidget(self._critic_warn)

        # Which reviewer answered last, on what model, how long ago (TCC-Concept §4: the advisor
        # panel's "engaged? which AI+model? last called when").
        # Elides for the same reason as the warning beside it: a model name plus "4 h ago" is as
        # long as the model's name happens to be, and a footer that asks for its natural width
        # takes the window's right edge off the screen with it.
        self._critic_status = ElidedLabel(i18n.t("criticNever"), min_width=130)
        self._critic_status.setProperty("class", "kv-val")
        layout.addWidget(self._critic_status)

        # Two ways to bring an AI to this project, both explicit. Neither starts on launch: one
        # spends the user's tokens, the other opens a window on their desktop, and an app that
        # does either just because it was opened is an app people stop opening.
        self._session_btn = QPushButton(i18n.t("startSession"))
        self._session_btn.setProperty("class", "reason-btn")
        self._session_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._session_btn.clicked.connect(self._start_tuning_session)
        self._restart_tip = attach_tip(self._session_btn, "")
        layout.addWidget(self._session_btn)
        self._update_session_button()

        self._terminal_btn = QPushButton(i18n.t("openTerminal"))
        self._terminal_btn.setProperty("class", "reason-btn")
        self._terminal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._terminal_btn.clicked.connect(self._open_terminal)
        # Front-end B is real and tested, but it is not in the workflow being built right now:
        # showing a second way in before the first one is finished only splits attention.
        self._terminal_btn.setHidden(True)
        layout.addWidget(self._terminal_btn)

        layout.addStretch(1)

        # Back in the footer by name (user, 2026-08-23), and ALSO in the main menu's help
        # section. They were moved out on the reasoning that two links and a form are what a menu
        # is for; the reasoning was mine and the button is his. Saying thank you and reporting a
        # bug are the two things a person does on impulse, and an impulse does not open a menu.
        coffee_btn = QPushButton(i18n.t("coffeeBtn"))
        coffee_btn.setProperty("class", "coffee-btn")
        coffee_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        coffee_btn.clicked.connect(self._open_support_menu)
        self._coffee_btn = coffee_btn
        layout.addWidget(coffee_btn)

        self._feedback_btn = QPushButton("💬 " + i18n.t("fbBig"))
        self._feedback_btn.setProperty("class", "feedback-btn")
        self._feedback_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._feedback_btn.clicked.connect(self._open_feedback)
        self._feedback_tip = attach_tip(self._feedback_btn, i18n.t("fbBigTip"))
        layout.addWidget(self._feedback_btn)

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

    def _rew_dots(self):
        """Every widget showing REW reachability: the System-params row and the measurement card's
        header. Both are optional here because this is called during construction, before the one
        that is built later exists, and on a language switch, which destroys and rebuilds the first
        of them."""
        for attr in ("_rew_dot", "_meas_rew_dot"):
            dot = getattr(self, attr, None)
            if dot is not None:
                yield dot

    def _retip_rew_dots(self) -> None:
        tip = i18n.t("rewOnlineTip") if self._rew_online else i18n.t("rewOfflineTip")
        for dot in self._rew_dots():
            dot.setToolTip(tip)

    def _rebuild_system_params(self) -> None:
        """System params: REW's default local port (always shown) plus whatever equipment facts
        `project.json` has (DSP/amps/mic/source -- SCR-015 point 1, `project_view.load_system_params`).
        Rebuilt from scratch so a language switch re-translates the "REW port" label and a project
        switch picks up the new project's facts (same pattern as `_set_project_params`). Rebuilds
        the REW-online dot too (clear_layout destroys the old instance) from `self._rew_online`,
        which is what survives across rebuilds."""
        clear_layout(self._system_section.body_layout())
        self._rew_dot = TrafficLight(self._rew_status_class())
        self._retip_rew_dots()  # the new instance, and the header's, in the current language
        self._system_section.body_layout().addWidget(
            _kv_row(i18n.t("rewPort"), _REW_DEFAULT_PORT, trailing=self._rew_dot)
        )
        # NOT gated on `_has_project`: that means "project.json exists", and the DSP is known
        # from `dsp_profile.json` long before it. Hiding a fact TCC already has because a later
        # file has not been written yet is how the panel came to say "no data" next to a profile
        # the session had just finalised.
        rows = project_view.load_system_params()
        for label, value in rows:
            self._system_section.body_layout().addWidget(_kv_row(label, value))
        self._add_channel_switches()

    def _rebuild_acoustics(self) -> None:
        """The car's acoustic flaw map — what this cabin does, and what may be done about it.

        Rebuilt from scratch on project load and language switch, same pattern as System params.
        The rows are the skill's measurements; the colour is its verdict. Nothing here judges a
        curve — `project.py flaw` already refused to record a null as notchable, which is the one
        rule in this map with teeth (SCR-015).
        """
        clear_layout(self._audio_section.body_layout())
        flaws = acoustics_view.load_flaws()
        if not flaws:
            # Before phase 0 there is nothing measured, and that is the ordinary state of a new
            # project rather than a fault: the intake fills this in.
            self._audio_placeholder = self._placeholder_label(i18n.t("acousticsNone"))
            self._audio_section.body_layout().addWidget(self._audio_placeholder)
            return
        for flaw in flaws:
            self._audio_section.body_layout().addWidget(self._flaw_row(flaw))

    def _flaw_row(self, flaw) -> QWidget:
        """`188 Hz · Q5 · +5.5 dB` on one line, the verdict on the next, the reason on hover."""
        widget = QWidget()
        widget.setProperty("class", "paramrow")
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(12, 4, 12, 4)
        outer.setSpacing(1)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        # The dot IS the verdict: correctable, leave alone, never boost, or fixed by something
        # that is not EQ. A reader scanning the column should not have to read words to see it.
        top.addWidget(TrafficLight(flaw.tone))
        head = ElidedLabel(flaw.headline, min_width=60)
        head.setProperty("class", "pk")
        top.addWidget(head, 1)
        action = QLabel(i18n.t(f"flawAction_{flaw.action}"))
        action.setProperty("class", "stag")
        top.addWidget(action)
        if flaw.is_hypothesis:
            # Said in words, not only in the dot's colour: "not settled yet" is the kind of thing
            # a reader has to be able to see without knowing the palette.
            unsure = QLabel(i18n.t("flawHypothesis"))
            unsure.setProperty("class", "stag stag-attempt")
            top.addWidget(unsure)
        outer.addLayout(top)

        detail = ", ".join(flaw.channels) if flaw.channels else i18n.t("flawAllChannels")
        line = ElidedLabel(f"{i18n.t('flawKind_' + flaw.kind)} · {detail}", min_width=60)
        line.setProperty("class", "cline2")
        outer.addWidget(line)

        # The tip is the row's whole substance -- a headline says WHAT was measured, and only
        # this says why it was called that and what it was read off. It used to be `why` and the
        # evidence glued together with `<br>` at the tooltip's default size: two unrelated things
        # in one grey paragraph, and the reader had to guess where the reasoning stopped and the
        # file names began (user, 2026-08-18: "хінти перегляньте, щоб читались зрозуміло").
        # Now it is laid out like the curve window's: a bold head naming the flaw the way a person
        # would say it, the reasoning as its own paragraph, and the captures under a label of
        # their own.
        why = flaw.why or ""
        evidence = ", ".join(flaw.evidence)
        # NOT `head`: that name is the headline LABEL a few lines up, and shadowing it made
        # `copy_menu.full_text(head)` read a string instead of a widget -- the copy menu lost its
        # "copy value" entry and the row it offered began with a stray separator (caught by
        # `test_copy_menu.py`, which the author of this line had not run).
        tip_head = " · ".join(part for part in (
            flaw.headline,
            i18n.t(f"flawKind_{flaw.kind}"),
            ", ".join(flaw.channels) or i18n.t("flawAllChannels"),
            i18n.t(f"flawAction_{flaw.action}"),
        ) if part)
        body = "\n\n".join(part for part in (
            why,
            f"{i18n.t('flawEvidenceHead')}\n{evidence}" if evidence else "",
        ) if part) or i18n.t("flawNoWhy")
        # Doubt is the tip's own colour as well as the dot's: a hypothesis reads as a verdict when
        # its text looks like every other row's.
        tip = attach_tip(widget, tip_html(body, head=tip_head, warn=flaw.is_hypothesis))
        # The row that most needs copying: the whole point of the flaw map is that "do not EQ-boost
        # this null" outlives the session that found it, and the reason and the captures it was
        # read off are on hover. A verdict that can only be hovered cannot be quoted to anyone.
        copy_menu.enable_copy(
            widget,
            value=lambda: copy_menu.full_text(head),
            row=lambda: " · ".join((
                copy_menu.full_text(head),
                i18n.t(f"flawAction_{flaw.action}"),
                copy_menu.full_text(line),
            )),
            hint=lambda: copy_menu.plain(tip.text()),
        )
        return widget

    def _add_channel_switches(self) -> None:
        """Every channel the DSP has, in use or not, each with its ON/OFF.

        Not in the DSP tree: that is the working surface and shows what is being worked on (user,
        2026-08-06). Here the point *is* to see the whole rig at once — which slots are in play,
        which are spare — so an unused channel is a row rather than an absence, and switching one
        is one click away from where you noticed it.

        Each group folds. A Helix Ultra lists every slot of every tier, and unfolded that is some
        forty rows pushing the REW port and the equipment facts — the rest of this section — off
        the top of the panel. The header carries `on/total` so a folded group still answers "how
        much of this tier is in play".
        """
        view = getattr(self, "_view", None)
        if view is None:
            return
        self._toggle_buttons = {}
        for group in view.groups:
            rows = group.rows_ordered()
            if not rows:
                continue
            live = len(group.rows_visible())
            section = CollapsibleGroup(
                f"sys/{group.id}",
                # The tree's own naming, so the two panels call a tier the same thing and neither
                # prints the profile's parenthetical list of the rows just below it.
                dsp_tree.group_label(group),
                self._settings,
                count=f"{live}/{len(rows)}",
            )
            for row in rows:
                section.body_layout().addWidget(self._channel_switch_row(group.id, row))
            self._system_section.body_layout().addWidget(section)

    def _channel_switch_row(self, group_id: str, row) -> QWidget:
        on = not (row.hidden or row.off)
        widget = QWidget()
        widget.setProperty("class", "paramrow")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(12, 3, 12, 3)
        layout.setSpacing(6)
        name = ElidedLabel(f"{row.slot} · {row.name}" if row.slot else row.name)
        name.setProperty("class", "pk" if on else "pv-dim")
        layout.addWidget(name, stretch=1)
        # The label is the ACTION, not the state (user, 2026-08-07): a live channel showed a green
        # "ON", which reads as a status badge until you press it and are asked to switch it off.
        # The state is on the row itself -- an off channel's name is dimmed -- and the colour here
        # previews the result rather than reporting the present: switching one on is the accented
        # move, switching one off is the quiet one.
        button = QPushButton(i18n.t("chanTurnOff") if on else i18n.t("chanTurnOn"))
        button.setProperty("class", f"chan-toggle chan-toggle-{'off' if on else 'on'}")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(i18n.t("chanToggleTip"))
        button.clicked.connect(
            lambda _c=False, g=group_id, n=row.name, o=on: self._ask_channel_toggle(g, n, not o)
        )
        layout.addWidget(button)
        # Kept so the waiting state can be written onto the button a second at a time rather than
        # by rebuilding this whole section every tick -- which would fold the groups the Arbiter
        # had opened. Rebuilt with the rows, so a stale widget is never held.
        self._toggle_buttons[(group_id, row.name)] = button
        if (group_id, row.name) in self._pending_toggles:
            self._paint_pending_toggle(group_id, row.name)
        return widget

    def _ask_channel_toggle(self, group_id: str, channel: str, on: bool) -> None:
        """Confirm before asking for it — in both directions.

        Switching a channel off can cost its EQ, crossover and delay, and switching one on is a
        structural change that reaches the glossary and the virtual tier. Neither is a toggle you
        want to fire on a mis-click, and TCC cannot undo either: the ledger is the skill's.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(i18n.t("chanToggleConfirmTitle"))
        box.setText(i18n.t("chanToggleConfirmOn" if on else "chanToggleConfirmOff").format(
            channel=channel
        ))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self._on_channel_toggle(group_id, channel, on)

    def _app_config_rows(self) -> list[tuple[str, str]]:
        """What TCC itself is set to, next to what the rig is.

        These were only visible in the footer and the menus, so "which model is answering me"
        meant hunting for the control that sets it. They are system params in the same sense the
        mic is: chosen once, then relied on.
        """
        generator = self._project_setting(_GENERATOR_KEY)
        critic = self._project_setting(_CRITIC_KEY)
        entries = model_choices.choices([]) + model_choices.critic_choices([])

        def label_for(key: str) -> str:
            if not key:
                return i18n.t("modelUnchosen")
            choice = model_choices.find(entries, key)
            return choice.label if choice else key.split(":", 1)[-1]

        gate = self._project_setting(_GATE_KEY) or omp_session.GATE_DEFAULT
        effort = model_choices.resolve_effort(self._project_setting(_EFFORT_KEY))
        return [
            (i18n.t("cfgLanguage"), i18n.t("langNameUk") if i18n.current_language() == "uk"
                                    else i18n.t("langNameEn")),
            (i18n.t("cfgGenerator"), label_for(generator)),
            # Beside the model, because it is half of the same fact: a record that names the model
            # but not how hard it was asked to think does not say what actually ran.
            (i18n.t("cfgEffort"), i18n.t(f"effort_{effort}")),
            (i18n.t("cfgCritic"), label_for(critic)),
            (i18n.t("cfgTheme"), i18n.t("cfgThemeDark" if self._mode == "dark"
                                        else "cfgThemeLight")),
            (i18n.t("cfgGate"), i18n.t({omp_session.GATE_WRITES: "gateWrites",
                                        omp_session.GATE_FOREIGN: "gateForeign",
                                        omp_session.GATE_AUTO: "gateAuto"}.get(gate, "gateAuto"))),
        ]

    def _set_rew_online(self, online: bool) -> None:
        self._rew_online = online
        for dot in self._rew_dots():
            dot.set_status(self._rew_status_class())
        self._retip_rew_dots()

    # ---- diagnostics (TCC-TZ.md §8) -----------------------------------------

    def _reload_from_disk(self) -> None:
        """The header's ↻: re-read the project AND re-run the contract check.

        One button, because "what changed on disk" is one question — a terminal-driven session
        that rewrote the ledger usually rewrote the process state and project facts too.
        """
        self._safe_load_project()
        self._start_contract_check()

    def _safe_load_project(self) -> None:
        """Re-read the project without letting a bad file take the window with it.

        The ledger is written by a language model, and one wrote `slot: 1` where the schema says a
        letter. `QLabel(int)` raised inside a Qt slot -- which does not propagate, it aborts the
        process -- and the whole app went with it mid-session, after eight measurements.

        Nothing here decides the file is wrong or repairs it: TCC does not write project data. It
        keeps the last good view on screen and says what happened, which is the difference between
        a panel that cannot draw and a session that ends.
        """
        try:
            self._load_project()
        except Exception as exc:  # noqa: BLE001 - a rendering fault must not end the session
            self._status_strip.notify(
                i18n.t("projectRenderFailed").format(error=str(exc)[:200]), level="warn"
            )

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

    def _on_curves_requested(self, request: dict) -> None:
        """`show_curves` from the model. Arrives on the GUI thread — the bridge's signal is queued.

        The note is appended to the composer rather than shown and forgotten: it is the model
        saying what it wants looked at, and it belongs in the transcript beside the answer.
        """
        note = str(request.get("note") or "").strip()
        if note:
            self._dialog.put_in_composer(note)
        self._open_curves(
            list(request.get("titles") or []),
            markers=list(request.get("markers") or []),
            kind=str(request.get("kind") or "impulse"),
        )

    def _open_curves_from_panel(self, titles: list) -> None:
        """The measurement panel's own Curves button: open on ONE curve, or on the last set.

        User, 2026-08-19: "при відкритті вікна показувати одну першу (перший раз для нового сету)
        чи ті що були попереднього разу (в поточній сесії роботи), а НЕ ВСІ". The button offers
        everything the series holds, and a series is nine or eighteen measurements — plotting all
        of them is a picture of nothing, takes a REW call each, and then has to be undone chip by
        chip before any actual question can be asked.

        So: whatever was last looked at in THIS series, and the first title when this series has
        not been opened yet. Everything else is still one tick away — `_open_curves` hands the
        window every title REW holds as the choose menu's options, which is what makes opening
        narrow safe rather than limiting.

        Filtered against what the panel is offering NOW: a remembered title that the series no
        longer holds (a re-measured round, a renamed capture) would be a window asking REW for a
        curve nobody has.

        The MODEL's own path does not come through here — `_on_curves_requested` names its titles
        out loud and gets exactly those.
        """
        wanted = [str(t) for t in titles if str(t).strip()]
        last = self._curve_last.get(self._curve_series_key())
        # The whole offer goes through as `available` even though only part of it is plotted.
        # `_open_curves` otherwise builds the options from the titles it is given plus what REW is
        # known to hold — and the panel falls back to the EXPECTED names when nothing has been read
        # yet (`_on_curves_clicked`), which are in neither list. Narrowing without this would take
        # the rest of the round off the choose menu, which is the opposite of the ask.
        self._open_curves(
            [t for t in (last or []) if t in wanted] or wanted[:1], available=wanted
        )

    def _curve_series_key(self) -> str:
        """Which capture series the "what was looked at last" memory is filed under.

        The same key the curve window scopes its delay bank by (`viewing_session_id`): a title
        belongs to a series, and a set remembered from one round is not the set to reopen after
        the panel has been switched to another.
        """
        try:
            return self._meas_panel.viewing_session_id() or ""
        except Exception:  # noqa: BLE001 — a panel read must never keep the window from opening
            return ""

    def _remember_curve_selection(self, titles: list) -> None:
        """Whatever the curve window is plotting now, against the series it was chosen in."""
        self._curve_last[self._curve_series_key()] = [str(t) for t in titles if str(t).strip()]

    def _open_curves(
        self, titles: list, markers: Optional[list] = None, kind: str = "impulse",
        available: Optional[list] = None,
    ) -> None:
        """Open the curve window over `titles`, with the model's reading marked if there is one.

        Signature is the one an MCP tool will call: titles the model names, and where it read the
        answer. Exactly what it is given, never a slice of it — the panel's own button decides how
        much to open with before it calls here (`_open_curves_from_panel`).

        `available` is what the window may OFFER, over and above what is plotted. Left out it is
        the titles plus everything REW is known to hold, which is right for the model's own call;
        the panel passes its whole round, because it is the one caller that deliberately plots less
        than it was asked about.
        """
        from autosound_tcc.core import delay_bank
        from autosound_tcc.ui.tcc.curve_dialog import CurveDialog

        titles = [str(t) for t in titles if str(t).strip()]
        if not titles:
            self._status_strip.notify(i18n.t("curveNothing"), level="warn")
            return
        available = sorted(
            set(titles) | set(available or []) | set(self._meas_panel.known_titles())
        )
        dialog = getattr(self, "_curve_dialog", None)
        # Every title asked for, not the first two. This was the last pair-shaped slice on the
        # path (the window used to hold two pickers); the model names as many measurements as it
        # wants looked at, the panel's button offers a whole task, and the chip row is where the
        # tuner takes one off again.
        if dialog is None:
            dialog = CurveDialog(
                titles, markers=markers or [], kind=kind, available=available, parent=self
            )
            # The reading lands in the composer rather than being sent: it is the Arbiter's
            # statement, and they see and edit it before it goes out. Nothing is recorded behind
            # them.
            dialog.readingSent.connect(self._dialog.put_in_composer)
            # Not modal, and above the window (user, 2026-08-11): the point is reading a curve
            # WHILE talking about it, and a modal window makes you close the evidence to answer.
            dialog.setWindowFlag(Qt.WindowType.Tool, True)
            # What each channel is set to NOW, read fresh on every use rather than captured: this
            # window stays open across a whole alignment pass, and a snapshot taken when it opened
            # would be checking a proposal against an hour-old ledger. It is the only thing that
            # lets the panel say a −0.15 ms correction takes a channel below zero.
            dialog.set_delays_provider(
                lambda: delay_bank.current_delays(self._view) if self._view is not None else {}
            )
            # Which capture series the measurement panel is showing. Read fresh, like the ledger
            # above: the Arbiter switches series in the panel while this window stays open.
            dialog.set_session_provider(self._meas_panel.viewing_session_id)
            self._meas_panel.sessionChanged.connect(lambda _id: dialog.session_switched())
            # What is on screen, remembered per series, so the panel's button reopens on it
            # rather than on the whole round (`_open_curves_from_panel`). Here rather than in the
            # dialog because the dialog is re-pointed at other questions and outlives none of
            # them; this window outlives all of them.
            dialog.selectionChanged.connect(self._remember_curve_selection)
            self._curve_dialog = dialog
        else:
            # ONE window, re-pointed. Building a second is not merely wasteful: pyqtgraph's
            # PlotItem constructs parentless QMenus every time, and enough construct/destroy
            # cycles segfault the process from inside its own `__init__` (2026-08-12).
            dialog.reset(titles, markers=markers or [], kind=kind, available=available)
        dialog.show()
        dialog.raise_()

    def _open_diagnostics(self) -> None:
        if self._diag_dialog is None:
            self._diag_dialog = DiagnosticsDialog(self)
            self._diag_dialog.refreshRequested.connect(self._start_contract_check)
            # The other half of D-6: TCC cannot write the skill's files, so it carries the
            # checker's finding to the thing that can. Into the composer, not out — the Arbiter
            # reads it before it is sent, like every other statement of theirs.
            self._diag_dialog.askRequested.connect(self._dialog.put_in_composer)
            self._diag_dialog.set_report(self._contract_report)
        elif self._contract_report is not None:
            self._diag_dialog.set_report(self._contract_report)
        # The facts only a running window has, refreshed on every open rather than captured once:
        # the server may have been restarted, and a report that names a dead port is worse than one
        # that names none.
        self._diag_dialog.set_install_extra(self._install_facts())
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
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # One scroll for the whole column. Each section scrolls its own body, so with two or three
        # of them open the bottom ones were unreachable -- the DSP tree had a scrollbar and the
        # sections above it simply ran off the panel (user, 2026-08-06).
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        left_scroll.setWidget(inner)
        outer.addWidget(left_scroll)

        # Project first: it is the car in front of you. System params is the rig and the app's
        # own settings, which you set once and then stop looking at (user, 2026-08-06 -- this
        # reverses the 2026-07-28 order, which put the setup block on top before there was any
        # project content to compete with it).
        self._project_section = SidebarSection(
            "project_params", i18n.t("projectParams"), self._settings, default_collapsed=True
        )
        layout.addWidget(self._project_section)

        self._system_section = SidebarSection(
            "system_params", i18n.t("systemParams"), self._settings, default_collapsed=True
        )
        self._rebuild_system_params()
        layout.addWidget(self._system_section)

        self._audio_section = SidebarSection(
            "audio_analysis", i18n.t("audioAnalysis"), self._settings, default_collapsed=True
        )
        self._rebuild_acoustics()
        layout.addWidget(self._audio_section)

        self._dsp_section = SidebarSection(
            "dsp", i18n.t("dspPanel"), self._settings, default_collapsed=False
        )
        # No stretch. It was here so the tree would fill the panel instead of sitting at its
        # content height with a gap under it (user, 2026-07-28) -- and what it actually did was
        # hand the tree the leftover viewport and let it scroll inside the column's own scroll.
        # The gap is answered by the trailing stretch below, which costs the tree nothing.
        layout.addWidget(self._dsp_section)

        self._left_status = QLabel("")
        self._left_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._left_status.setProperty("class", "phead-sub")
        self._left_status.setWordWrap(True)
        self._left_status.setContentsMargins(12, 16, 12, 16)
        self._dsp_section.body_layout().addWidget(self._left_status)

        # Only offered for the genuine "no project here at all" case (_show_left_status's
        # offer_create=True) -- the other _show_left_status branches describe a project that
        # exists but is broken, where "create new" would be the wrong fix.
        # Kept, hidden: "which project" now lives in the header menu, and two controls for one
        # act were what made "create" and "open" look like different things. The dialog behind it
        # is still the only path that runs the DSP-profile interview, so this is a hidden seam
        # rather than a deletion -- see the note in `_open_new_project_dialog`.
        self._create_project_btn = QPushButton(i18n.t("createProject"))
        self._create_project_btn.setProperty("class", "reason-btn")
        self._create_project_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._create_project_btn.clicked.connect(
            lambda _checked=False: self._open_new_project_dialog()
        )
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
        self._tree.toggleRequested.connect(self._on_channel_toggle)
        self._dsp_section.body_layout().addWidget(self._tree)
        # The empty room lives at the bottom of the column, under the last section, rather than
        # inside whichever section was asked to soak it up. That is what makes the whole column
        # one scroll: every section is exactly as tall as its contents, and what does not fit
        # becomes scroll rather than a private scrollbar two levels down.
        layout.addStretch(1)

        return panel

    # ---- project loading ----------------------------------------------------

    def _load_project(self) -> None:
        """Load the DSP capability profile + the current preset's ledger, and hand the result to
        the tree. Degrades to a status message rather than crashing — no profile / no ledger /
        a broken file are all things a half-set-up project can legitimately be in."""
        # The demo transcript goes the moment there is a real project to confuse it with. It was
        # only dropped on the "no project" branch, so opening a real one and not starting a session
        # left invented EQ values ("PK 1120 -2.5 Q2.2") on screen under a real project's name.
        self._dialog.clear_mock()
        profile_path = config.dsp_profile_path()
        if not profile_path.is_file():
            self._show_left_status(i18n.t("leftNoProfile"), offer_create=True)
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
            # No ledger yet -- which is not the same as nothing to show. A project that has been
            # described (or seeded from another car) already names every channel and its tier, so
            # the rig can be drawn now and the VALUES arrive with the first snapshot. Before this
            # the panel was empty with a note, and somebody who had just copied a car reasonably
            # read that as "the copy did not work".
            prof = profile.get("dsp_profile", profile)
            rig = rig_view(profile)
            # VISIBLE rows, not rows: today `project.json` names a `tier` only on the SPARE slots
            # (SCR-042 -- "which tier it is spare OF"), because for a working channel the LEDGER
            # is what says which tier it is in. So on a project with no ledger this currently
            # yields the spares alone, all `hidden`, and a tree of nothing is worse than the note.
            # Deliberately NOT inferred from `role`: guessing a channel into a tier is precisely
            # what the method refuses to do, and a second guesser in the window is how the two
            # halves start disagreeing. The day `tier` is written for every channel, this branch
            # lights up on its own.
            if not any(group.rows_visible() for group in rig.groups):
                self._show_left_status(
                    f"{prof.get('vendor', '?')} {prof.get('name', '?')}\n\n"
                    + i18n.t("leftNoLedger")
                )
                return
            self._has_project = True
            self._dsp_section.set_sub(f"{prof.get('vendor', '?')} {prof.get('name', '?')}")
            # The note STAYS, above the tree: rows with no values are honest only while something
            # says why they have none.
            self._left_status.setText(i18n.t("leftNoLedger"))
            self._left_status.setVisible(True)
            self._create_project_btn.setVisible(False)
            self._tree.setVisible(True)
            self._view = rig
            self._rebuild_system_params()
            self._rebuild_acoustics()
            self._tree.set_view(rig)
            self._set_project_params(rig)
            self._refresh_open_detail()
            self._slot_label.setText("")
            self._save_label.setText("")
            self._target_label.setText("")
            self._refresh_process()
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
        # BEFORE the rebuild, not after: System params renders its channel switches off `_view`
        # (`_add_channel_switches`), so rebuilding first read the previous load's view -- absent on
        # the first one. That is why the channel sections were missing at startup and appeared
        # after "Refresh" (user, 2026-08-07): the second load found the first load's view. They
        # were also a load behind ever after, which nobody could see because the two agreed.
        self._view = view
        self._rebuild_system_params()
        # The flaw map comes out of the same `project.json` as everything else on this path, and
        # was the one panel a reload did not touch: built at startup, refreshed on a language
        # switch, and never again -- so a flaw the skill recorded mid-session only appeared after
        # a restart (user, 2026-08-21). Its own docstring already claimed this call existed.
        self._rebuild_acoustics()
        self._tree.set_view(view)
        self._set_project_params(view)
        self._refresh_open_detail()

        self._slot_label.setText(view.slot_label or "")
        self._save_label.setText(view.save or "")
        self._target_label.setText(f"{view.target} ↗" if view.target else "")
        self._version_label.setText(view.version or "")
        self._show_banked_delta(view.version, preset)

    def _open_new_project_dialog(self, seed: bool = False) -> None:
        """Folder + vendor/model + (in-app Claude OR a detected terminal CLI). Either path hands
        off to a fresh `MainWindow` pointed at the new folder rather than trying to hot-reload
        this window's subsystems (MCP server, process watcher, DSP tree) live -- every one of them
        already loads fresh from `config.project_dir()` in `__init__`, so a brand new window is a
        full, correct "restart pointed at the new project" with no new teardown code needed beyond
        the `closeEvent` this window already has."""
        dialog = NewProjectDialog(self, seed_first=seed)
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

        if dialog.project_dir is None:
            return

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
        # Reached with NO interview and no terminal when the project was seeded from another one
        # and came with its DSP profile: there is nothing left to onboard, so the new window IS
        # the answer. It says what it inherited rather than opening silently on somebody else's
        # facts.
        if dialog.seeded is not None and dialog.seeded_from is not None:
            said = i18n.t("npSeedDone").format(
                source=dialog.seeded_from.name, files=", ".join(dialog.seeded.written)
            )
            # A profile can be inherited AND incomplete. Saying how many of its facts are still
            # unconfirmed is the difference between a `null` that looks settled and one that is
            # a to-do -- the same three-valued honesty the import window renders.
            still_open = getattr(dialog.seeded, "profile_open", 0)
            if still_open:
                said = f"{said} {i18n.t('npSeedOpen').format(open=still_open)}"
            new_window._status_strip.notify(said)
        if dialog.open_terminal_cli is not None:
            language_name = i18n.t("langNameUk" if i18n.current_language() == "uk" else "langNameEn")
            hint = i18n.t("npOnboardingHint").format(
                vendor=dialog.onboarding_vendor,
                model=dialog.onboarding_model,
                language=language_name,
            )
            if dialog.seeded is not None and dialog.seeded_from is not None:
                # The CLI must be told the folder is not empty. Without this it opens on a
                # project full of inherited facts and starts the intake from "what car is it",
                # which is the cost the seeding exists to remove.
                hint = f"{hint} {i18n.t('npSeedHint').format(source=dialog.seeded_from.name)}"
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

    def _open_resonalyze_import(self) -> None:
        """Read-only on purpose. The dialog converts and checks; banking the rows is the tuning
        gate's job (`state/apply.py`), which validates against HEAD and produces the settings
        sheet somebody enters by hand -- a window that wrote ledger state past it would be a
        second way in."""
        ResonalyzeImportDialog(config.project_dir(), self).exec()

    def _open_feedback(self) -> None:
        FeedbackDialog(_FEEDBACK_URL, _FEEDBACK_FORM_URL, self).exec()

    def _open_support_menu(self) -> None:
        """The coffee button's own popup, opening UPWARD from the footer (user, 2026-07-28).

        The same two channels as the method's README -- GitHub Sponsors for people with an
        account, the Monobank jar as the no-account one-tap fallback. They are in the main menu
        too; this is the impulse path, and it costs one click instead of three.
        """
        menu = self._tip_menu(self)
        github_action = menu.addAction(i18n.t("supportGithub"))
        github_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(_GITHUB_SPONSORS_URL))
        )
        mono_action = menu.addAction(i18n.t("supportMonobank"))
        mono_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(_MONOBANK_JAR_URL)))
        top_left = self._coffee_btn.mapToGlobal(QPoint(0, 0))
        menu.adjustSize()
        menu.exec(QPoint(top_left.x(), top_left.y() - menu.sizeHint().height()))

    def _open_target_curve_tool(self, _event=None) -> None:
        QDesktopServices.openUrl(QUrl(f"{_TARGET_CURVE_TOOL_URL}?lang={i18n.current_language()}"))

    def _on_preset_index(self, _index: int) -> None:
        preset = self._preset_combo.currentData()
        if not preset or preset == self._preset_override:
            return
        self._preset_override = preset
        self._settings.setValue("ui/preset", preset)
        self._load_project()

    def _show_left_status(self, message: str, offer_create: bool = False) -> None:
        """No loaded DSP view right now -- all four `_load_project` failure branches route here.

        What this means is narrow, and it used to be read far too widely: "there is no
        `dsp_profile.json` yet" is not "there is no project". A folder mid-interview has a plan,
        a journal and a process state and no profile, and this method was blanking all of them --
        visibly on `↻` ("Проєкт не відкрито" over a plan that was on screen a second earlier) and
        invisibly on every `enter_phase`/`add_step`, since recording refreshes the window.

        So the panels that have their own source are no longer cleared from here; they are asked
        to re-read it. `_has_project` keeps its old meaning -- the DSP view -- and stops being
        consulted about the process.
        """
        self._has_project = False
        self._tree.setVisible(False)
        self._left_status.setText(message)
        self._left_status.setVisible(True)
        self._create_project_btn.setVisible(False)
        self._rebuild_system_params()
        self._set_project_params(None)
        self._detail.close_pane()
        self._dialog.clear_for_no_project()
        self._refresh_process()

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
        # Which models answer, which language, which permissions -- those are decisions about
        # *this project*, kept in its own `tcc-project.json`. System params is the rig: the DSP,
        # the amps, the mic, the REW port. They were in the wrong section (user, 2026-08-06).
        for label, value in self._app_config_rows():
            self._project_section.body_layout().addWidget(_kv_row(label, value))
        # The project folder is a git repo by the skill's own design, and none of it was visible:
        # "am I on the branch I think, is anything unsaved?" meant leaving the app.
        for label, value in project_view.git_facts():
            self._project_section.body_layout().addWidget(_kv_row(label, value))
        summary_rows = project_view.load_channel_summary() if view else ()
        open_questions = project_view.load_open_questions() if view else ()
        for tier_id, total, off in summary_rows:
            self._project_section.body_layout().addWidget(
                _kv_row(_tier_label(tier_id), _tier_count(total, off))
            )
        if open_questions:
            # In a group of their own, with a count. They used to be loose chips appended straight
            # under the channel-summary rows, so a paragraph about rear-fill routing read as an
            # explanation of the "Virtual channels 8" line above it -- the Arbiter's own reading
            # of the panel (2026-08-21: "а що оце після числа віртуальних каналів за інфа?").
            # Folded by default: this is the intake's own to-do list, not the state of the car.
            group = CollapsibleGroup(
                "open_questions",
                i18n.t("openQuestionsTitle"),
                self._settings,
                count=str(len(open_questions)),
            )
            for question in open_questions:
                chip = self._placeholder_label(f"🟡 {question}")
                # Not the muted grey every other placeholder wears: these are the only rows in
                # the panel that are asking for something (user, 2026-08-21). And selectable +
                # copyable, because the answer to one is usually pasted somewhere else -- a
                # question you cannot copy is one you retype by hand.
                chip.setProperty("class", "phead-sub open-q")
                chip.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                copy_menu.enable_copy(
                    chip,
                    value=lambda c=chip: c.selectedText() or c.text().lstrip("🟡 "),
                    row=lambda c=chip: c.text().lstrip("🟡 "),
                )
                group.body_layout().addWidget(chip)
            self._project_section.body_layout().addWidget(group)

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
        self._dialog.startRequested.connect(self._on_dialog_start_requested)
        self._dialog.turnFinished.connect(self._supervise_turn)
        self._dialog.arbiterAnswered.connect(self._record_decision)
        self._dialog.confirm_bar.alwaysAllowed.connect(self._remember_always_allowed)
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
        # The REW-online dot, a second time, at the right end of this header (user request
        # 2026-08-11). It already exists in System params, but that is in the left sidebar and
        # this is the card whose Read button fails when REW is closed -- the answer to "why did
        # nothing turn green" should be visible without looking away from the question. Same
        # `_rew_online` state and same `TrafficLight` widget, so there is one status shown twice,
        # not two statuses that can disagree.
        self._meas_rew_lbl = QLabel("REW")
        self._meas_rew_lbl.setProperty("class", "phead-sub")
        self._meas_rew_dot = TrafficLight(self._rew_status_class())
        meas_head.layout().addWidget(self._meas_rew_lbl)
        meas_head.layout().addWidget(self._meas_rew_dot)
        self._retip_rew_dots()
        meas_layout.addWidget(meas_head)
        self._meas_panel = MeasurementPanel(
            preset_provider=lambda: self._view.preset if self._view else "",
        )
        meas_layout.addWidget(self._meas_panel)
        layout.addWidget(meas_panel)

        # A step's measurement icon opens that capture series in the panel below (user request
        # 2026-07-28).
        self._plan_panel.sessionRequested.connect(self._meas_panel.show_session)
        self._meas_panel.curvesRequested.connect(self._open_curves_from_panel)

        return container

    # ---- theme -------------------------------------------------------------

    def _apply_theme(self, mode: str) -> None:
        app = QApplication.instance()
        apply_theme(app, mode, scale=self._zoom)
        # After the sheet, never before: the size being copied is the styled one.
        QTimer.singleShot(0, self._match_icon_buttons)
        self._mode = mode
        self._settings.setValue(_THEME_KEY, mode)
        self._repolish_all()
        # The curve window is not in this window's widget tree and would not repaint from the
        # stylesheet even if it were: pyqtgraph draws with explicit pens.
        curves = getattr(self, "_curve_dialog", None)
        if curves is not None:
            try:
                curves.apply_theme()
            except RuntimeError:
                self._curve_dialog = None  # closed and deleted since

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
        # Zoom scales every font in the sheet, so the box being copied has just changed size.
        QTimer.singleShot(0, self._match_icon_buttons)
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


        # The plan was the only thing watched, so the left column kept saying "no data yet" beside
        # a `project.json` the session had just written -- it only caught up on the next launch.
        # Reported after a completed phase -1: the car, the amps and the open questions were all
        # on disk and none of them were on screen.
        self._project_watcher = QFileSystemWatcher(self)
        self._project_watcher.fileChanged.connect(self._on_project_file_changed)
        self._project_watcher.directoryChanged.connect(self._on_project_file_changed)
        # Coalesced: the skill writes several files in a row, and each one must not cost a full
        # rebuild of the tree.
        self._project_reload = QTimer(self)
        self._project_reload.setSingleShot(True)
        self._project_reload.setInterval(400)
        self._project_reload.timeout.connect(self._reload_project_files)
        self._arm_project_watcher()

    def _watched_project_files(self) -> list[str]:
        project_dir = config.chosen_project_dir()
        if project_dir is None:
            return []
        paths = [str(project_dir / name) for name in ("project.json", "dsp_profile.json")]
        # The ledger too: a snapshot the skill commits from a terminal is the single most visible
        # thing a session does — a channel gains a crossover, the version in the header moves —
        # and until now the only way to see it was the ↻ button. HEAD is a file (it is rewritten in
        # place, so nothing but a file watch catches it); the preset dir is watched separately for
        # the new `v_NNN.json` beside it.
        root = config.state_root()
        paths += [str(root / preset / "HEAD") for preset in config.available_presets(root)]
        return paths

    def _watched_project_dirs(self) -> list[str]:
        """`state/` and each preset under it. A directory watch is what catches a file that did not
        exist when the watcher was armed — the first `v_001.json`, or a second preset appearing —
        which a file watch by definition cannot."""
        root = config.state_root()
        if config.chosen_project_dir() is None or not root.is_dir():
            return []
        return [str(root)] + [str(root / preset) for preset in config.available_presets(root)]

    def _arm_project_watcher(self) -> None:
        """(Re)watch the project's own files. Re-armed after every change: an atomic write replaces
        the inode and the watcher silently drops the path, which is why this is not a one-off."""
        watcher = getattr(self, "_project_watcher", None)
        if watcher is None:
            return
        for path in self._watched_project_files():
            if Path(path).exists() and path not in watcher.files():
                watcher.addPath(path)
        for path in self._watched_project_dirs():
            if path not in watcher.directories():
                watcher.addPath(path)

    def _on_project_file_changed(self, *_args) -> None:
        self._arm_project_watcher()
        self._project_reload.start()

    def _reload_project_files(self) -> None:
        """Re-read what the skill wrote and put it on screen."""
        self._arm_project_watcher()
        self._safe_load_project()

    def _refresh_process(self, *_args) -> None:
        state = process_view.load_state()
        if state is None and process_view.has_process_state():
            # The file is there but did not read as state: the skill is mid-write, or wrote
            # something this version cannot parse. Either way the plan on screen is the last thing
            # known to be true, and blanking it turns a half-second of writing into "the phases
            # disappeared" -- reported exactly that way, with them coming back on the next turn.
            return
        if state is None:
            # "No plan yet" and "no project open" are different empty states with different fixes,
            # and the difference is whether a folder is open -- not whether the DSP profile has
            # been written, which happens much later and used to blank a plan that existed.
            self._plan_panel.set_plan(None if config.chosen_project_dir() else ())
            # The capture task is derived from the DSP view, so its empty state follows that and
            # not the folder -- a project with a profile and no captures yet is not "no project".
            if not self._has_project:
                self._meas_panel.set_no_project(i18n.t("noProjectMeas"))
            return
        # SCR-014: what a `config_change` invalidated, computed once and used by both panels --
        # a step's "recheck" chip and a capture's unusable colour are the same fact.
        stale = process_view.stale_channels()
        plan = process_view.to_plan(state, stale)
        # The "факт" half: a step the skill closed whose evidence names nothing that exists. The
        # skill's gate counts evidence and cannot read it, so a model that narrates its work
        # closes every step it touches -- watched doing exactly that, four phases in one sitting
        # with `dsp_profile.json` alone on disk (SCR-035).
        titles = getattr(self._meas_panel, "known_titles", lambda: [])()
        unbacked = {u.step_id for u in plan_audit.unbacked_steps(state, rew_titles=titles)}
        if unbacked:
            plan = process_view.mark_unbacked(plan, unbacked)
        self._plan_panel.set_plan(plan)
        self._refresh_capture_task(state)
        self._notify_stale(stale)
        self._notify_missing_records(state)

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
        # `_show_left_status` can reach here while the window is still being built, before the
        # watcher exists; the refresh itself is still worth doing, the re-arming is not.
        if getattr(self, "_process_watcher", None) is None:
            return
        path = str(process_view.state_file())
        if path not in self._process_watcher.files():
            self._process_watcher.addPath(path)

    def _on_channel_toggle(self, group_id: str, channel: str, on: bool) -> None:
        """The Arbiter asked for a channel to be switched on or off.

        A SIGNAL, not a write. Enabling a channel changes the ledger, and the ledger is the skill's
        to write (D-6) -- so this goes on the bus, the model picks it up with `get_pending_signals`,
        and the tree follows once the change is recorded. The alternative, writing it here, would
        be TCC's first edit to project data and a second author for the one file whose whole value
        is having one.

        Which is exactly why the row has to SAY that. Between the click and the model's answer the
        row used to look untouched, so the honest reading of it was "nothing happened" -- and the
        Arbiter clicked again, and four `channel_toggle` signals sat in the queue for seven
        minutes (2026-08-21, F-009 point 4). Asking the same thing twice now refreshes the wait
        instead of raising a second signal.
        """
        server = self._mcp_server
        if server is None:
            self._dialog._add_system_message(i18n.t("noSessionForSignal"))
            return
        # The server outlives any session -- it is up before the first message and after the last
        # -- so "the server is here" is not "somebody is listening". Saying "the model will record
        # this" with no session running promises something that cannot happen until one starts,
        # which read as the AI being broken (user, 2026-08-21: "враження, що ШІ не запускається").
        # The request is NOT dropped: the bus keeps it and the first turn of the next session
        # carries it, which is exactly what happened when they typed "Привіт".
        listening = self._dialog.has_agent()
        key = (group_id, channel)
        waiting = self._pending_toggles.get(key)
        if waiting is not None and waiting["on"] == on and server.bus.is_open(waiting["id"]):
            # The same request, still open. A second signal would only make the model do the same
            # work twice and would say nothing new.
            waiting["at"] = time.time()
            self._paint_pending_toggle(group_id, channel)
            self._dialog._add_system_message(i18n.t("chanToggleAlreadyAsked").format(
                channel=channel
            ))
            return
        signal = server.bus.push(
            signal_bus.CHANNEL_TOGGLE, group=group_id, channel=channel, on=on
        )
        self._pending_toggles[key] = {"on": on, "at": time.time(), "id": signal.id}
        self._paint_pending_toggle(group_id, channel)
        self._pending_timer.start()
        self._dialog._add_system_message(
            i18n.t("chanToggleSent" if listening else "chanToggleQueued").format(
                channel=channel, state=i18n.t("chanOn" if on else "chanOff")
            )
        )

    def _paint_pending_toggle(self, group_id: str, channel: str) -> None:
        """Write the wait onto the one button it belongs to, counting.

        A count and not a spinner: "asked 4s ago" and "asked 2 minutes ago" are different facts
        about the same screen, and only one of them means something is wrong.
        """
        entry = self._pending_toggles.get((group_id, channel))
        button = self._toggle_buttons.get((group_id, channel))
        if entry is None or button is None:
            return
        waited = int(time.time() - entry["at"])
        late = waited >= _TOGGLE_LATE_S
        try:
            button.setText(i18n.t("chanToggleLate" if late else "chanToggleWaiting").format(
                secs=waited
            ))
            button.setProperty("class", "chan-toggle chan-toggle-" + ("late" if late else "wait"))
            button.setToolTip(i18n.t("chanToggleWaitTip"))
            button.style().unpolish(button)
            button.style().polish(button)
        except RuntimeError:
            # Its C++ half went with a rebuild between the tick and here; the next rebuild will
            # register the replacement.
            self._toggle_buttons.pop((group_id, channel), None)

    def _tick_pending_toggles(self) -> None:
        """Once a second: age the waits, and drop the ones the model has closed.

        Closed means acknowledged on the bus -- applied, refused or superseded (F-009's `ack`).
        TCC deliberately does not decide that for itself: it did not make the change and cannot
        know it happened until the party that writes the ledger says so.
        """
        server = self._mcp_server
        finished = [
            key for key, entry in self._pending_toggles.items()
            if server is None or not server.bus.is_open(entry["id"])
        ]
        for key in finished:
            self._pending_toggles.pop(key, None)
        for group_id, channel in list(self._pending_toggles):
            self._paint_pending_toggle(group_id, channel)
        if finished:
            # Back to whatever the ledger now says -- which is a different question from "the
            # request closed", and the only honest answer to it is a re-read.
            self._rebuild_system_params()
        if not self._pending_toggles:
            self._pending_timer.stop()

    def _nudge_for_open_signals(self) -> None:
        """Give an un-answered signal a turn of its own, once.

        ONCE per signal, tracked by id: if the model reads the queue and does nothing about it,
        starting another turn would be a loop that spends the Arbiter's money to repeat itself.
        A signal that has been offered a turn and ignored stays open -- the row still says it is
        waiting, `get_tcc_state` still says the count out loud, and every later turn still carries
        it. What it does not get is a second turn of its own.

        The ids are dropped once the bus has closed them, so a channel switched off and on again
        later is a new request and gets its own turn.
        """
        server = self._mcp_server
        if server is None:
            return
        open_ids = {sid for sid in self._nudged_signal_ids if server.bus.is_open(sid)}
        self._nudged_signal_ids = open_ids
        count = server.bus.pending_count
        if not count:
            return
        brief = server.bus.unacked_brief()
        fresh = [line for line in brief.splitlines() if "id " in line]
        ids = {line.rsplit("id ", 1)[-1].rstrip(")") for line in fresh}
        if ids <= open_ids:
            return  # nothing here that has not already been handed a turn
        if self._dialog.nudge_for_signals(count, i18n.t("signalNudgePrompt")):
            self._nudged_signal_ids = open_ids | ids

    def _notify_missing_records(self, state: dict) -> None:
        """Say when a decision the method leans on exists only in the conversation.

        The supervisor's second rule (`plan_audit.missing_records`). Said once per fact rather than
        on every refresh: the file is polled, the Arbiter is not.
        """
        missing = plan_audit.missing_records(state)
        seen = getattr(self, "_missing_said", set())
        if not missing:
            # It was recorded. The strip was telling the truth and has stopped being true, and a
            # warning that outlives its cause teaches people to ignore the strip.
            if seen:
                self._status_strip.clear()
                self._missing_said = set()
            return
        for record in missing:
            if record.what in seen:
                continue
            seen.add(record.what)
            self._status_strip.notify(
                i18n.t("missingRecord").format(what=i18n.t(record.what), why=i18n.t(record.why))
            )
        self._missing_said = seen

    def _show_banked_delta(self, version: Optional[str], preset: Optional[str]) -> None:
        """When a version arrives with a banked delta, put THAT on screen as the settings card.

        The card the Arbiter keys from should carry the values the ledger banked, not the values a
        model re-rendered into chat — the same argument as `dsp-state-current` being generated
        rather than hand-written (SCR-026). Shown once per version: this runs on every project
        reload, and the watcher fires more than once for a single commit.
        """
        if not version or not preset or version == getattr(self, "_delta_shown", None):
            return
        delta = proposal_view.load_delta(version, preset)
        # No delta file is the ordinary case — a seeded baseline, a hand-written ledger, a project
        # older than this. Remembered anyway, so a reload does not re-ask the disk for it.
        self._delta_shown = version
        if delta is None:
            return
        self._dialog._add_system_message(proposal_view.to_html(delta))

    def _on_cli_catalogue_ready(self) -> None:
        """Fold the local CLIs into the pickers, and say so when one answered with nothing.

        Silence would read as "that route does not exist on this machine", which is the belief
        that sends somebody to the metered one — the whole reason the routes are labelled at all.
        """
        self._reload_model_choices()
        quiet = model_choices.cli_routes_without_models()
        if quiet:
            self._status_strip.notify(
                i18n.t("cliRouteQuiet").format(routes=", ".join(quiet)), level="warn"
            )

    def _on_rew_titles_changed(self) -> None:
        """REW's list changed — redraw the checklist, and check what the round asked for (SCR-040).

        Checking is arithmetic and needs no model, so it runs here rather than waiting for one to
        think of it. Only while a round is open and only when something it expects has actually
        turned up: the check pulls every expected measurement out of REW, and doing that on every
        scan of an unrelated project would make the panel expensive to look at.
        """
        state = process_view.load_state()
        if state:
            self._refresh_capture_task(state)
        round_ = process_view.capture_round() or {}
        if not round_ or round_.get("closed"):
            return
        titles = set(self._meas_panel.known_titles())
        outstanding = [
            title
            for title in round_.get("expected", [])
            if title in titles
            and not (((round_.get("taken") or {}).get(title) or {}).get("verified") or {}).get("ok")
        ]
        if not outstanding:
            return
        if self._capture_check is not None and self._capture_check.isRunning():
            return  # one check at a time; the next title change re-triggers it
        self._capture_check = _CaptureCheckWorker(config.project_dir())
        self._capture_check.result.connect(self._on_capture_check_done)
        self._capture_check.start()

    def _on_capture_check_done(self, output: str) -> None:
        """Put the verdict on screen. The checker's own words, not a paraphrase.

        An unusable capture is a retake the Arbiter has to decide on, and deciding it needs the
        reason -- "silence in band" and "covers 200-2000 Hz, asked for 20-20000" lead to different
        actions at the car.
        """
        bad = [line for line in (output or "").splitlines() if line.startswith("UNUSABLE")]
        if bad:
            self._status_strip.notify("<br>".join(bad), level="warn")
        # The panel reads the recorded verdict, not this text.
        state = process_view.load_state()
        if state:
            self._refresh_capture_task(state)

    def _record_decision(self, question: str, answer: str) -> None:
        """The Arbiter ruled on something in the dialog — put it in the journal (SCR-030).

        Written by TCC because TCC is where the answer is machine-readable: an option they clicked,
        against the question as it was put. The model can record one too (`record_decision` on the
        MCP surface), but only if it thinks to; the click is not in doubt.

        Best effort, and quiet about failing: a ruling that could not be journalled must not eat the
        answer the session is waiting on. The strip says so, the turn continues.
        """
        project = config.chosen_project_dir()
        if project is None or not (question or "").strip() or not (answer or "").strip():
            return
        try:
            process_writer.record_decision(project, question, answer)
        except process_writer.ProcessWriterError as exc:
            self._status_strip.notify(f"journal: {exc}", level="warn")

    def _supervise_turn(self) -> None:
        """Reconcile the plan against the disk at the end of every turn.

        The panels already follow the files, but a watcher only fires when something is WRITTEN,
        and the failure this exists for is the opposite: a turn that talked and recorded nothing.
        Running here means the check happens on every turn, written or not.

        It reports to the Arbiter in the dialog, not only as a chip in the plan: a model that
        closes steps it cannot prove is a fact about the conversation, and the conversation is
        where the person deciding whether to trust it is looking. Said once per step -- a warning
        repeated every turn is a warning nobody reads.
        """
        state = process_view.load_state()
        if not state:
            return
        titles = getattr(self._meas_panel, "known_titles", lambda: [])()
        unbacked = plan_audit.unbacked_steps(state, rew_titles=titles)
        said = getattr(self, "_unbacked_said", set())
        fresh = [entry for entry in unbacked if entry.step_id not in said]
        if not fresh:
            return
        for entry in fresh:
            said.add(entry.step_id)
        self._unbacked_said = said
        self._dialog._add_system_message(
            i18n.t("supervisorUnbacked").format(
                steps="<br>".join(f"· {entry.step_name or entry.step_id}" for entry in fresh)
            )
        )

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
        sessions = measurement_view.build_sessions(phase, self._capture_version(state), titles)
        if sessions:
            self._meas_panel.set_sessions(sessions)
            # The plan's per-step measurement icon reads the same list: a step gets one when a
            # round's captures are named in its evidence (SCR-035 makes sure they are).
            self._plan_panel.set_sessions(sessions)

    _CAPTURE_SERIES = re.compile(r"_(\d+)\s*\((?:sw|rta)\)", re.IGNORECASE)

    def _capture_version(self, state: Optional[dict] = None) -> int:
        """The series the current phase's captures are named with.

        `_N` is the config a measurement was taken under (naming-and-structure §3), so this used to
        read the ledger's HEAD. That is wrong whenever the ledger moves for a reason that is not a
        config change: naming the virtual-channel tier bumped `v_001 → v_002`, and the checklist
        jumped to series 2 before series 1 had been captured. Watched twice, on two projects.

        The plan already carries the answer. The skill writes its phase-0 steps as
        "Baseline solo: tw-L_1 (sw) + tw-L_1 (rta)" — the round it means, in its own words — so
        when a step in the active phase names a series, that wins. The ledger stays the fallback
        for a plan that names none.
        """
        for step in (state or {}).get("plan") or []:
            if not isinstance(step, dict) or str(step.get("phase")) != str(
                (state or {}).get("active_phase")
            ):
                continue
            found = self._CAPTURE_SERIES.search(str(step.get("name") or ""))
            if found:
                return int(found.group(1))
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
        self._mcp_error = ""
        self._bridge = QtUiBridge(self)
        self._bridge.confirmationRequested.connect(self._dialog.confirm_bar.enqueue)
        self._bridge.clipboardRequested.connect(lambda text: QGuiApplication.clipboard().setText(text))
        self._bridge.proposalReceived.connect(self._on_proposal)
        self._bridge.critiqueReceived.connect(self._on_critique)
        self._bridge.curvesReceived.connect(self._on_curves_requested)
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
            # Kept, because the status strip shows the LAST notification and this one is minutes
            # older than the moment it matters: the chat says the server is not running when a
            # session is launched, and until now it could not say why (user, on Windows 11,
            # 2026-08-19). Logged too, with the traceback, so a report can carry the cause.
            self._mcp_error = f"{type(exc).__name__}: {exc}"
            app_log.logger().exception("the MCP server did not start: %s", exc)
            self._status_strip.notify(f"MCP: {exc}", level="warn")

    def _match_icon_buttons(self) -> None:
        """Pin the diagnostics button to the reload button's size, whatever the platform did.

        Both are header icon buttons and must read as a pair. The gear is deliberately the larger
        GLYPH of the two, and a larger font grows a QPushButton — so the box is taken from the
        neighbour rather than described twice in the stylesheet, which is how they came out
        different sizes on Windows and on macOS at once. Re-run on every theme or zoom change,
        because both move the metrics this is copying.
        """
        if not hasattr(self, "_diag_btn") or not hasattr(self, "_header_refresh_btn"):
            return
        self._diag_btn.setFixedSize(self._header_refresh_btn.sizeHint())

    def _set_title(self) -> None:
        """The project, then both versions — and a word when something newer exists.

        Two numbers, because a bug is against a PAIR, the app and the method, and either alone
        leaves the other to be guessed. The update word is here rather than in a badge because
        this is where the versions already are, and it is the line a person reads without being
        asked to (user, 2026-08-19).
        """
        versions = " · ".join(
            part for part in (
                f"TCC {install_report.app_version()}" if install_report.app_version() else "",
                f"skill {install_report.skill_version()}" if install_report.skill_version() else "",
                self._title_note,
            ) if part
        )
        self.setWindowTitle(
            f"Tuning Command Center — GitHub/autosound-tcc @ {config.project_dir()}"
            + (f"  ({versions})" if versions else "")
        )

    def _check_for_updates(self) -> None:
        """Ask GitHub once, in the background, and say so in the title if there is something newer.

        A plain daemon thread and a timer, not a QThread: PySide's import hook makes Qt-owned
        threads crawl through anything that imports, and a QThread destroyed while running is
        `qFatal` (measured; see `core/install_report.py`). Nothing here touches Qt off the main
        thread — the timer reads the result.

        Silent when offline, and silent when up to date: the title is not a place to report that
        nothing happened.
        """
        holder: dict = {}

        def ask() -> None:
            try:
                holder["result"] = updates.check_all()
            except Exception:  # noqa: BLE001 — a question nobody answered changes nothing on screen
                holder["result"] = ()

        threading.Thread(target=ask, name="tcc-title-updates", daemon=True).start()
        tries = {"n": 0}
        timer = QTimer(self)

        def poll() -> None:
            tries["n"] += 1
            if "result" not in holder and tries["n"] < 120:
                return
            timer.stop()
            if any(getattr(status, "newer", False) for status in holder.get("result", ())):
                self._title_note = i18n.t("titleUpdate")
                self._set_title()

        timer.timeout.connect(poll)
        timer.setInterval(500)
        timer.start()

    def _install_facts(self) -> dict:
        """What the installation report cannot ask for itself: this window's own live state."""
        server = self._mcp_server
        facts = {
            "MCP": (server.url if server is not None and getattr(server, "serving", False)
                    else (getattr(self, "_mcp_error", "") or "not running")),
        }
        model = getattr(self, "_running_model", None)
        if model:
            facts["session"] = str(model)
        return facts

    def _publish_snapshot(self) -> None:
        """Mirror what's on screen into the bridge, for `get_tcc_state` to read off-thread."""
        self._bridge.set_snapshot(
            preset=self._preset_override or config.resolve_preset(),
            project_dir=str(config.project_dir()),
            param_edit_mode=self._dialog.is_editing,
            theme=self._mode,
            # The intake's first question is "which language?", and the answer has been on screen
            # since before the session started -- the app is already speaking it. Reported so the
            # skill can close that step instead of asking (SCR-037's rule, applied to the one fact
            # the payload was still missing).
            ui_language=i18n.current_language(),
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
        return model_choices.resolve(self._critic_choices, str(key)).choice

    def _on_critic_model_changed(self, _index: int) -> None:
        """The footer picker steers the reviewer subprocess through its own env var."""
        _mark_missing(self._ai_critic_combo, self._critic_choices)
        self._refresh_critic_warning()
        choice = self._critic_choice()
        if choice is None:
            return
        project_settings.set_value(config.tcc_dir(), _CRITIC_KEY, choice.key)
        self._bridge.set_snapshot(critic_model=choice.model)

    def _refresh_critic_warning(self) -> None:
        """Say when the reviewer is not what the picker appears to promise.

        Two ways it stops being an independent review, both of them silent until now:

        * **Substituted** — the stored key is aliased on this machine, so the model that answers is
          not the one named. `resolve()` has always known (it is in `get_tcc_state` as
          `substituted`, which is how the model found out); the footer did not say it.
        * **Same vendor as the Generator** — the skill's fallback rung when the chosen reviewer is
          unreachable. It still reviews, but cross-vendor anti-anchoring is the whole reason the
          reviewer is a different vendor, and losing it quietly is exactly SCR-041's failure: a
          downgrade that agrees with you instead of erroring.
        """
        warn = getattr(self, "_critic_warn", None)
        if warn is None:
            return
        key = str(self._ai_critic_combo.currentData() or "")
        resolved = model_choices.resolve(self._critic_choices, key)
        notes, tips = [], []
        if resolved.note:
            notes.append(i18n.t("criticSubstituted"))
            tips.append(resolved.note)
        # Third condition, and the only one backed by evidence rather than configuration: who
        # actually answered last. A live session proved the other two can both look clean while a
        # different model does the reviewing — the script falls back from the API to a local CLI
        # and that CLI runs whatever it is set to (2026-08-12).
        actual = self_check.reviewer_mismatch()
        if actual:
            notes.append(i18n.t("criticAnswered").format(model=actual[1]))
            tips.append(i18n.t("selfReviewerDiffDetail").format(wanted=actual[0], answered=actual[1]))
        generator = self._generator_choice()
        chosen = resolved.choice
        if chosen is not None and generator is not None:
            # `vendor_of`, not `critic_vendor`: the latter falls back to google for a name it
            # does not recognise, which would make any two unknown models look like a matched pair.
            vendor = model_choices.vendor_of(chosen)
            if vendor and vendor == model_choices.vendor_of(generator):
                notes.append(i18n.t("criticSameVendor"))
                tips.append(i18n.t("criticSameVendorTip").format(vendor=vendor))
        # ...and the one the Generator has too: the Claude route with nothing to authenticate with.
        login_note, login_tip = _sdk_login_note(chosen)
        if login_note:
            notes.append(login_note)
            tips.append(login_tip)
        headline = " · ".join(notes)
        warn.setVisible(bool(notes))
        # Hover says WHAT, the click says why — the same split the diagnostics button uses, and the
        # reason a mark can stand in for a sentence at all.
        self._critic_warn_tip.set_text(headline)
        self._critic_warn_detail = "\n\n".join([headline] + tips) if headline else ""
        # The picker itself is tinted, so the thing that is wrong is the thing that looks wrong —
        # a mark beside a normal-looking field still leaves you hunting for what it refers to.
        _mark_missing(self._ai_critic_combo, self._critic_choices, warn=bool(notes))

    def _refresh_main_warning(self) -> None:
        """The Generator's own caveat, and it is only ever one.

        No same-vendor question here — a Claude reviewed by a Claude is the failure, a Claude
        GENERATING is just a choice — so this says the single thing that can be wrong about the
        route itself: it is Claude's, and this machine has no login for it.
        """
        warn = getattr(self, "_main_warn", None)
        if warn is None:
            return
        note, tip = _sdk_login_note(self._generator_choice())
        warn.setVisible(bool(note))
        self._main_warn_tip.set_text(note)
        self._main_warn_detail = f"{note}\n\n{tip}" if note else ""
        _mark_missing(self._ai_main_combo, self._model_choices, warn=bool(note))

    def _explain_main_warning(self) -> None:
        if not self._main_warn_detail:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(i18n.t("aiMain"))
        box.setText(self._main_warn_detail)
        box.exec()

    def _explain_critic_warning(self) -> None:
        if not self._critic_warn_detail:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(i18n.t("criticWarnTitle"))
        box.setText(self._critic_warn_detail)
        box.exec()

    def _refresh_critic_status(self) -> None:
        self._refresh_critic_warning()
        entry = critic.last_call(self._mcp_server.project_dir if self._mcp_server else None)
        if not entry:
            self._critic_status.setText(i18n.t("criticNever"))
            return
        # Short (user, 2026-08-11): the model name alone, and how long ago. The word "Critic" is
        # already three widgets to the left, and the vendor prefix is in the picker beside it.
        model = str(entry.get("model") or entry.get("mode", "?"))
        self._critic_status.setText(f"{model.split('/')[-1]} · {_ago(entry.get('at', ''))}")

    def _on_dialog_start_requested(self, text: str) -> None:
        """The Arbiter typed the first message instead of clicking start — same intent."""
        if self._generator_choice() is None:
            self._dialog._add_system_message(i18n.t("startSessionNoModel"))
            self._dialog._set_busy(False)
            return
        self._start_tuning_session(opening=text)

    def _start_tuning_session(self, opening: Optional[str] = None) -> None:
        """Front-end A: run the skill in-process and stream it into the dialog panel."""
        worker = getattr(self, "_agent_worker", None)
        if worker is not None:
            # Same model: nothing to do. A different one: the running conversation ends, because
            # neither harness can swap a model under a live session.
            if self._running_model == self._ai_main_combo.currentData():
                return
            self._hand_off_then_restart(worker)
            return
        self._launch_session(opening)

    # ---- handing the project over between sessions -------------------------

    def _hand_off_then_restart(self, worker) -> None:
        self._hand_off(worker, "restart")

    def _hand_off(self, worker, mode: str) -> None:
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
        self._handoff_mode = mode
        # One handoff, three reasons, and the message has to say which: "before the model changes"
        # under a plain Save is TCC narrating something the Arbiter did not ask for.
        self._dialog._add_system_message(i18n.t({
            "save": "sessionHandoffSave",
            "fresh": "sessionHandoffFresh",
            "quit": "sessionHandoffQuit",
        }.get(mode, "sessionHandoff")))
        self._session_btn.setEnabled(False)
        if mode == "quit":
            # The window is already on its way out and only waits for this turn -- for up to
            # `_HANDOFF_TIMEOUT_MS`, which is three minutes of a window that looks frozen. Say so
            # where a wait is normally reported, and stop the composer's queue from dispatching
            # into a session being wound down: a message typed here used to be sent the instant
            # the handoff turn ended, starting a fresh turn as the window closed (user,
            # 2026-08-21, whose "як справи?" is what left a worker mid-turn during teardown).
            self._status_strip.notify(i18n.t("quitSaving"), level="info")
            self._dialog.hold_queue_for_quit()
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
        mode = getattr(self, "_handoff_mode", "restart")
        worker = getattr(self, "_agent_worker", None)
        if worker is not None:
            for signal in (worker.turn_done, worker.failed):
                try:
                    signal.disconnect(self._finish_handoff)
                except (RuntimeError, TypeError):
                    pass
        if mode == "save":
            # The point was to get the project onto disk, not to end the conversation.
            self._dialog._add_system_message(i18n.t("sessionSaved"))
            self._update_session_button()
            return
        if mode == "quit":
            # The window is already on its way out and only waited for this turn. `_quitting` is
            # what stops the second `close()` asking the same question again.
            self.close()
            return
        if worker is not None:
            worker.shutdown()
        self._agent_worker = None
        self._running_model = None
        self._dialog._add_system_message(
            i18n.t("sessionFresh") if mode == "fresh" else i18n.t("sessionRestarted")
        )
        self._launch_session(fresh=mode == "fresh")

    def _launch_session(self, opening: Optional[str] = None, fresh: bool = False) -> None:
        if self._mcp_server is None:
            # WITH the reason. "Start TCC again" is advice that does not survive a second failure,
            # and the cause was already known minutes ago — it just had nowhere to go.
            reason = getattr(self, "_mcp_error", "")
            where = app_log.log_path()
            self._dialog._add_system_message(
                "⚠️ " + i18n.t("mcpDown")
                + (f" {reason}" if reason else "")
                + (f"\n{i18n.t('mcpDownLog')} {where}" if where else "")
            )
            return

        server = self._mcp_server
        choice = self._generator_choice()
        if choice is None:
            return
        if choice.harness == "omp" and not omp_session.is_available():
            self._dialog._add_system_message(i18n.t("ompMissing"))
            return
        probe = TuningSession(project_dir=server.project_dir)  # cheap: only reads the registry
        # "Start a new session" means an empty context on purpose: the project's state is on disk
        # and the new session reads it, which is cheaper than carrying a long transcript that has
        # already been written down.
        resumed = probe.resumed_from is not None and not fresh
        # Fixed for the session's whole life on both routes (the SDK takes it at client
        # construction), so it is read here, once, at the moment the session is built.
        effort = model_choices.resolve_effort(self._project_setting(_EFFORT_KEY))
        if choice.harness == "omp":
            # omp reads the project's own `.mcp.json`, which the MCP server wrote on start, so it
            # needs no url/token of its own.
            factory = lambda: omp_session.OmpSession(  # noqa: E731
                project_dir=server.project_dir,
                bridge=self._bridge,
                model=choice.model,
                resume=resumed,
                gate=self._project_setting(_GATE_KEY) or omp_session.GATE_DEFAULT,
                always_allowed=self._always_allowed(),
                effort=effort,
            )
        else:
            factory = lambda: TuningSession(  # noqa: E731
                project_dir=server.project_dir,
                mcp_url=server.url,
                mcp_token=server.token,
                bridge=self._bridge,
                model=choice.model,
                gate=self._project_setting(_GATE_KEY) or omp_session.GATE_DEFAULT,
                always_allowed=self._always_allowed(),
                effort=effort,
            )
        self._agent_worker = AgentWorker(session_factory=factory, opening_prompt=opening)
        self._dialog.attach_agent(
            self._agent_worker,
            server.bus,
            resumed=resumed,
            phase=server.registry.current_phase(),
            model=choice.label,
        )
        self._running_model = choice.key
        # On the record before the first token: the journal otherwise starts at whatever the model
        # happens to write first, and a session that ran for an hour and recorded nothing then
        # looks exactly like one that never happened -- which is the case план-факт is for. Best
        # effort: a project whose skill is not vendored still gets to run a session.
        try:
            process_writer.record_session(
                server.project_dir, choice.harness, choice.model, resumed=resumed
            )
            # A project with no process state at all starts in intake, and TCC opening it means
            # event one does not depend on which model the user brought (SCR-031: the re-run
            # watched a model read `enter-phase -1` verbatim and ask its questions instead). Only
            # when there is nothing — an existing phase is the skill's to move, never TCC's.
            if not process_view.has_process_state(server.project_dir):
                process_writer.enter_phase(server.project_dir, "-1")
        except process_writer.ProcessWriterError as exc:
            self._status_strip.notify(f"journal: {exc}", level="warn")
        self._agent_worker.start()
        self._update_session_button()
        self._refresh_project_button()

    # ---- which model, and therefore which harness --------------------------

    def _active_omp(self) -> list[str]:
        raw = self._settings.value(_ACTIVE_OMP_KEY, "")
        return [selector for selector in str(raw).split(",") if selector]

    def _project_setting(self, key: str) -> str:
        return project_settings.get(config.tcc_dir(), key, "") or ""

    def _always_allowed(self) -> frozenset[str]:
        """Tools the Arbiter ticked "don't ask again" on, for this project."""
        raw = self._project_setting(_ALWAYS_KEY)
        return frozenset(part for part in raw.split(",") if part)

    def _remember_always_allowed(self, tool: str) -> None:
        """One tick, one kind, and it survives the session -- Claude Code's own prompt works this
        way. Narrowing the gate deliberately is the opposite of learning to click through it."""
        allowed = set(self._always_allowed()) | {tool}
        project_settings.set_value(config.tcc_dir(), _ALWAYS_KEY, ",".join(sorted(allowed)))
        self._dialog._add_system_message(i18n.t("autoAllowed").format(tool=tool))
        self._push_gate_to_session()

    def _push_gate_to_session(self) -> None:
        """Apply the permission settings to the session that is already running.

        Both dials were read once, when the session object was built, so changing them mid-turn
        changed a file and nothing else: the Arbiter switched to "do not ask", ticked "stop asking
        about Bash", and was asked about Bash again. A setting that only takes effect next launch
        is a setting that does not work.
        """
        worker = getattr(self, "_agent_worker", None)
        session = getattr(worker, "session", None) if worker is not None else None
        if session is None:
            return
        # Plain attributes on both adapters, read at the moment a permission is judged, so
        # assigning them is the whole of "apply now" -- no restart, no queue, no thread hop.
        if hasattr(session, "gate"):
            session.gate = self._project_setting(_GATE_KEY) or omp_session.GATE_DEFAULT
        if hasattr(session, "always_allowed"):
            session.always_allowed = self._always_allowed()

    def _reload_model_choices(self) -> None:
        """Refill both pickers from one registry, keeping selections that survived.

        A stored choice that no longer exists is the case this whole path is built around: models
        retire, and the name in a project's settings outlives them. It must not resolve to silence
        (a Start button that does nothing) or to the first row (a reviewer nobody picked) — see
        `_offer_replacement`.
        """
        active = self._active_omp()
        self._model_choices = model_choices.choices(active)
        self._critic_choices = model_choices.critic_choices(active)
        generator = self._project_setting(_GENERATOR_KEY)
        critic = self._project_setting(_CRITIC_KEY)
        self._fill_combo(self._ai_main_combo, self._model_choices, generator)
        self._fill_combo(self._ai_critic_combo, self._critic_choices, critic, critic=True)
        # An unset project reads as the default rather than as an empty row: unlike the model,
        # there is no honest "not chosen yet" here -- some level always runs.
        level = model_choices.resolve_effort(self._project_setting(_EFFORT_KEY))
        blocked = self._ai_effort_combo.blockSignals(True)
        self._ai_effort_combo.setCurrentIndex(max(0, self._ai_effort_combo.findData(level)))
        self._ai_effort_combo.blockSignals(blocked)
        for key, entries in ((generator, self._model_choices), (critic, self._critic_choices)):
            if key and not model_choices.resolve(entries, str(key)).ok:
                self._offer_replacement(str(key), entries)
        self._refresh_main_warning()
        self._refresh_critic_warning()

    def _offer_replacement(self, key: str, entries: list) -> None:  # noqa: D401
        """A model this project uses is gone. Say so, and let the Arbiter map it to another.

        The mapping is stored as an ALIAS rather than by rewriting this project's setting, because
        the dead name is written down in more places than TCC can reach — other projects, journal
        entries, whatever the skill prescribed. One indirection fixes all of them at once; editing
        one project's setting fixes exactly one.

        Asked once per key per session: a dialog that reappears on every reload is a dialog people
        dismiss without reading.
        """
        asked = getattr(self, "_replacement_asked", set())
        if key in asked or not entries:
            return
        asked.add(key)
        self._replacement_asked = asked

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(i18n.t("modelGoneTitle"))
        box.setText(i18n.t("modelGone").format(model=key))
        combo = QComboBox(box)
        for choice in _replacements_for(key, entries):
            combo.addItem(f"{choice.route} · {choice.label}", choice.key)
        box.layout().addWidget(combo, 1, 1)
        box.setStandardButtons(
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        )
        if box.exec() != QMessageBox.StandardButton.Ok:
            # Declining is a real answer: the model may come back, or the Arbiter may want to pick
            # deliberately later. Nothing is written, and the picker keeps saying nothing is chosen.
            return
        model_overrides.set_alias(key, str(combo.currentData()), why=i18n.t("modelGoneWhy"))
        self._status_strip.notify(
            i18n.t("modelAliased").format(old=key, new=str(combo.currentData()))
        )
        self._reload_model_choices()

    @staticmethod
    def _fill_combo(combo, entries, wanted: str, critic: bool = False) -> None:
        blocked = combo.blockSignals(True)
        combo.clear()
        for choice in entries:
            notes = []
            # No badges that restate the row. "Recommended pair" went because the row is already
            # BOLD; "reduced effort" went after it, because the label already ends in (Low) and
            # nobody can say from either how low that is (user, 2026-08-12). What a badge must do
            # is add a fact the row does not carry.
            if choice.free:
                notes.append(i18n.t("modelFree"))
            if not choice.available:
                # A route this machine could have and does not. Shown, greyed, saying what it
                # needs — see `Choice.available`.
                notes.append(i18n.t("modelInstallCli").format(cli=choice.harness))
            elif critic and not model_choices.critic_reaches(choice):
                notes.append(i18n.t("modelClipboardOnly"))
            if model_choices.unconfirmed(choice):
                # Remembered from a previous launch, not confirmed by the CLI this time. Shown and
                # marked rather than dropped (user, 2026-08-11): an option that may not work is a
                # different thing from one that will, and both are different from an option that
                # is not in the list — which is how the recommended pair came to report itself
                # absent while `agy models` was answering perfectly well from a terminal.
                notes.append(i18n.t("modelUnconfirmed"))
            suffix = f"  ·  {' · '.join(notes)}" if notes else ""
            # EVERY route is prefixed, not just the SDK. The same model reached two ways is two
            # different accounts -- a subscription CLI and a metered broker -- and an unlabelled
            # entry reads as "the normal one", which is the assumption that quietly spends money
            # (reported 2026-08-07: an API balance gone negative next to an unused subscription).
            combo.addItem(f"{choice.route} · {choice.label}{suffix}", choice.key)
            row = combo.count() - 1
            tip = f"{choice.route_note}\n{choice.model}"
            combo.setItemData(row, tip, Qt.ItemDataRole.ToolTipRole)
            if not choice.available:
                # Not selectable, and greyed by the style rather than by a colour written here:
                # a row nobody can pick has to look like one before it is clicked.
                item = combo.model().item(row)
                if item is not None:
                    item.setEnabled(False)
            if model_choices.recommended(choice, critic=critic):
                # Bold, and by CLASS — so a new Opus or a new Pro is marked the day it appears,
                # with no release for it. The old literal match would simply have stopped bolding
                # anything, silently (2026-08-12).
                font = combo.font()
                font.setBold(True)
                combo.setItemData(row, font, Qt.ItemDataRole.FontRole)

        index = combo.findData(wanted) if wanted else -1
        missing = bool(wanted) and index < 0
        if missing:  # noqa: SIM102 - the branches below are three different states, not one
            # The chosen model is not on offer here. Shown in red and still selected, rather than
            # dropped: a picker that silently moves to another row is how a project came to be
            # reviewed by a model nobody chose, and how three permanent aliases got written
            # (2026-08-12). What is wrong stays visible and stays selected until a human moves it.
            combo.insertItem(0, i18n.t("modelMissingRow").format(key=wanted), wanted)
            combo.setItemData(0, QColor(current_theme().warn), Qt.ItemDataRole.ForegroundRole)
            combo.setItemData(0, i18n.t("modelMissingTip"), Qt.ItemDataRole.ToolTipRole)
            index = 0
        elif index < 0 and not critic:
            # Nothing chosen yet: say so rather than pre-selecting the first entry. A model that
            # was never picked must not be startable by someone who did not notice a default.
            combo.insertItem(0, i18n.t("modelUnchosen"), "")
            index = 0
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(blocked)
        _mark_missing(combo, entries)

    def _generator_choice(self) -> Optional[model_choices.Choice]:
        key = self._ai_main_combo.currentData()
        return model_choices.resolve(self._model_choices, str(key)).choice

    def _on_generator_model_changed(self, _index: int) -> None:
        # `_refresh_main_warning` marks the combo itself, so no separate `_mark_missing` here —
        # two writers of the same `class` property is how one of the two tints kept vanishing.
        self._refresh_main_warning()
        # Changing the Generator can create (or clear) the same-vendor warning on the reviewer:
        # it is a property of the PAIR, not of either picker alone.
        self._refresh_critic_warning()
        choice = self._generator_choice()
        if choice is None:
            self._update_session_button()
            return
        project_settings.set_value(config.tcc_dir(), _GENERATOR_KEY, choice.key)
        # The placeholder has served its purpose the moment a real model is chosen -- but it is
        # dropped *after* this signal has finished being delivered. Removing an item from a combo
        # inside that combo's own `currentIndexChanged` frees the view's internals while Qt is
        # still walking them: a segfault, reported after picking a model (2026-08-06), and the
        # same shape as deleting a widget from its own event handler.
        QTimer.singleShot(0, self._drop_model_placeholder)
        self._update_session_button()
        # The panel names the model, so it must not lag the picker.
        QTimer.singleShot(0, lambda: self._set_project_params(getattr(self, "_view", None)))

    def _on_effort_changed(self, _index: int) -> None:
        """The Arbiter changed how hard the Generator thinks.

        Takes effect on the NEXT session, not this one — both adapters fix the level when the
        session is built. Said out loud rather than left to be discovered: a control that looks
        live and is not is worse than one that says when it applies.
        """
        level = model_choices.resolve_effort(self._ai_effort_combo.currentData())
        project_settings.set_value(config.tcc_dir(), _EFFORT_KEY, level)
        if self._agent_worker is not None:
            self._dialog._add_system_message(i18n.t("effortNextSession"))
        QTimer.singleShot(0, lambda: self._set_project_params(getattr(self, "_view", None)))

    def _drop_model_placeholder(self) -> None:
        try:
            placeholder = self._ai_main_combo.findData("")
            if placeholder >= 0:
                self._ai_main_combo.removeItem(placeholder)
        except RuntimeError:
            return  # the window closed between the signal and this callback

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

        # The button exists for one thing the composer cannot express: swapping the model of a
        # conversation that is already running. Starting is what sending the first message does,
        # so a second control for that is one more thing to explain -- it stays out of the way
        # until it has something to say.
        restart = running and choice is not None and self._running_model not in (None, choice.key)
        self._session_btn.setHidden(not restart)
        if restart:
            self._session_btn.setText(i18n.t("restartSession").format(model=choice.label))
            self._session_btn.setEnabled(True)
            self._restart_tip.set_text(i18n.t("restartSessionTip"))
        self._refresh_project_button()

    def _open_model_config(self) -> None:
        dialog = ModelConfigDialog(self._active_omp(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._settings.setValue(_ACTIVE_OMP_KEY, ",".join(dialog.active))
        # Deferred out of the dialog's own accept path: refilling both combos tears down and
        # rebuilds their item views, and doing that while the dialog is still unwinding is the
        # same class of fault as the placeholder removal above.
        QTimer.singleShot(0, self._reload_after_model_config)

    def _reload_after_model_config(self) -> None:
        try:
            self._reload_model_choices()
            self._update_session_button()
        except RuntimeError:
            return

    # ---- the project menu ---------------------------------------------------

    def _show_action_tip(self, action) -> None:
        tip = action.toolTip()
        popup = rounded_tooltip.RoundedTooltip.instance()
        if not tip or tip == action.text():
            popup.hide_tip()
            return
        popup.show_at(QCursor.pos(), tip)

    def _set_gate_mode(self, mode: str) -> None:
        project_settings.set_value(config.tcc_dir(), _GATE_KEY, mode)
        self._refresh_project_button()
        self._push_gate_to_session()
        # The panel shows the mode, so it must not lag the menu. `None` is the honest argument:
        # the config rows do not depend on the DSP view, and the project facts are re-read anyway.
        self._set_project_params(getattr(self, "_view", None))

    def _sync_menu_state(self) -> None:
        """The menu's own state: which gate is ticked, and what a session-less window cannot do.

        Split out of `_refresh_project_button` because `_build_main_menu` needs exactly this and
        nothing else -- it runs while the header is still being assembled, before the project
        label it would otherwise touch exists.
        """
        current = self._project_setting(_GATE_KEY) or omp_session.GATE_DEFAULT
        for mode, action in getattr(self, "_gate_actions", {}).items():
            action.setChecked(mode == current)
        running = getattr(self, "_agent_worker", None) is not None
        self._save_state_action.setEnabled(running)
        self._fresh_session_action.setEnabled(running)

    def _refresh_project_button(self) -> None:
        """The name of the project in the header, plus the menu state that goes with it."""
        self._sync_menu_state()
        chosen = config.chosen_project_dir()
        self._project_label.setText(f"⌂ {chosen.name}" if chosen else i18n.t("projectNone"))
        self._project_label.setToolTip(str(chosen) if chosen else "")

    def _choose_project_folder(self) -> None:
        """Pick the folder this window works on. An empty one is a valid new project.

        TCC does not judge the contents: the intake fills a new folder, so choosing a folder and
        creating a project are one act rather than two controls that can disagree.

        Switching folders is not done in place. The MCP server, the session registry, the file
        watchers and every panel bind to one folder at startup, so a live swap would be a partial
        teardown pretending to be a setting -- the user is told to open TCC again instead.
        """
        previous = config.chosen_project_dir()
        start = previous or Path.home()
        picked = QFileDialog.getExistingDirectory(self, i18n.t("projectOpen"), str(start))
        if not picked:
            return
        folder = Path(picked)
        if previous is not None and folder == previous:
            return
        # Switching cannot happen in place -- see the docstring -- but "remembered for next time"
        # is not what anyone means by choosing a folder, and a line in the status strip is easy to
        # miss: the window simply stayed where it was, which is how this was reported. So TCC
        # relaunches itself on the new folder, once the Arbiter says it may.
        if not self._confirm_switch(folder):
            return
        config.set_project_dir(folder)
        self._relaunch_on(folder)

    def _confirm_switch(self, folder: Path) -> bool:
        answer = QMessageBox.question(
            self,
            i18n.t("projectSwitchTitle"),
            i18n.t("projectSwitchBody").format(name=folder.name),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok,
        )
        return answer == QMessageBox.StandardButton.Ok

    def _relaunch_on(self, folder: Path) -> None:
        """Start a second TCC on `folder` and close this one.

        `--project-dir` rather than trusting the remembered choice, so the new process lands where
        the user pointed even if something else rewrites the setting in between.
        """
        argv = [] if getattr(sys, "frozen", False) else [sys.argv[0]]
        argv += ["--project-dir", str(folder)]
        if not QProcess.startDetached(sys.executable, argv):
            self._status_strip.notify(i18n.t("projectReopen"), level="warn")
            return
        self.close()

    def _flush_own_state(self) -> str:
        """Everything TCC itself decides, on disk now. Returns the label of what it wrote.

        These are written as they change, so this is normally a no-op — which is exactly why it is
        worth doing on demand: "normally" is not "always", and a setting whose write is spread
        across a dozen handlers has a dozen chances to be the one that got missed. Re-asserting the
        pickers costs a file write and removes the whole class of question.
        """
        tcc_dir = config.tcc_dir()
        for key, value in (
            (_GENERATOR_KEY, self._ai_main_combo.currentData()),
            (_CRITIC_KEY, self._ai_critic_combo.currentData()),
            (_EFFORT_KEY, self._ai_effort_combo.currentData()),
        ):
            # An empty selection is the "nothing chosen yet" placeholder, not a choice to record —
            # writing it would turn "I have not picked a model" into "I picked no model".
            if value:
                project_settings.set_value(tcc_dir, key, str(value))
        # Window-level preferences (collapse states, font scale, capture order) live in QSettings,
        # which writes on its own schedule; a Save that returns before that happened is a Save that
        # did not.
        self._settings.sync()
        choice = self._generator_choice()
        return choice.label if choice else ""

    def _save_project_state(self) -> None:
        """Save what TCC owns, then ask the model to save what it knows.

        In that order, and the first half unconditionally (user, 2026-08-07). Save used to be
        nothing BUT the handoff, so with no session running it did nothing at all — no write, no
        message, no way to tell the difference between "saved" and "ignored" — and with one running
        it only ever asked the model, never settling TCC's own choices.
        """
        self._flush_own_state()
        worker = getattr(self, "_agent_worker", None)
        if worker is not None:
            self._hand_off(worker, "save")
            return
        # No session to ask, and that is not a failure: what TCC owns is now on disk, and saying so
        # is the difference between a button that did nothing and one that had nothing more to do.
        self._dialog._add_system_message(i18n.t("savedTccOnly"))
        self._status_strip.notify(i18n.t("savedTccOnly"))

    def _start_fresh_session(self) -> None:
        """Save, then start over with an empty context on the same project and model."""
        # Same order as a plain Save: the new session is built from these settings, so settling
        # them first is what makes "start fresh" pick up a model chosen a moment ago.
        self._flush_own_state()
        worker = getattr(self, "_agent_worker", None)
        if worker is not None:
            self._hand_off(worker, "fresh")

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

    def _on_logged_error(self, message: str, path) -> None:
        """Called from `app_log` when something was written to the log. Never from a worker
        thread's own stack -- `threading.excepthook` runs on the failing thread, so this touches
        widgets via a queued signal rather than directly."""
        self.loggedError.emit(f"{message}", str(path))

    def _show_logged_error(self, message: str, path: str) -> None:
        self._status_strip.notify(
            i18n.t("logError").format(error=message, path=path), level="warn"
        )

    def stop_workers(self) -> None:
        """Bring every background thread this window owns to a stop.

        Called from `closeEvent` and again from the application's `aboutToQuit`, because the two
        do not imply each other: a window can be closed while the app lives on, and an app can be
        quit (Cmd-Q, a signal) without any window being closed. Safe to run twice -- each branch
        checks whether its thread is still running.

        Not optional tidiness. Qt destroying a still-running QThread is a `qFatal`, which aborts
        the process, and that is not hypothetical: a crash report with `_ContractWorker` blocked
        in `poll` during interpreter shutdown (2026-08-06) is what prompted this.
        """
        # Before the threads: the sink holds a bound method of this window, and a log line
        # arriving after Qt has torn the window down would call into a deleted C++ object.
        app_log.set_ui_sink(None)
        ping = getattr(self, "_rew_ping", None)
        if ping is not None and ping.isRunning():
            ping.wait(2000)
        # The contract check is the worker most likely to still be going: it starts at launch and
        # takes as long as a Python subprocess plus a REW probe. Cancel first, then wait -- waiting
        # out its own 30 s timeout would freeze a window on its way out.
        contract = getattr(self, "_contract_worker", None)
        if contract is not None and contract.isRunning():
            contract.cancel()
            contract.wait(3000)
        # Same rule as the contract worker: a running QThread destroyed by Qt is a `qFatal`.
        check = getattr(self, "_capture_check", None)
        if check is not None and check.isRunning():
            check.wait(5000)
        catalogue = getattr(self, "_cli_catalogue", None)
        if catalogue is not None and catalogue.isRunning():
            catalogue.wait(5000)
        # The MCP server is a background thread this window owns, and it used to be stopped ONLY
        # in `closeEvent` — so a quit that does not close a window (Cmd-Q, a signal) left a daemon
        # thread running uvicorn's asyncio loop into interpreter shutdown, and the process died
        # there. Seen as a macOS crash report with `mcp_server._serve` on the stack, and
        # reproducible in the suite about one run in five (2026-08-12). Idempotent, like every
        # other branch here.
        server = getattr(self, "_mcp_server", None)
        if server is not None:
            server.stop()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # A live session holds things only the model can write down. Quitting used to shut it down
        # mid-thought without a word (user, 2026-08-07): whatever it had not yet put on disk was
        # gone, and nothing said so. Asking rather than saving on its own is deliberate — the save
        # costs a model turn, and a quit that silently blocks on one reads as a hang.
        worker = getattr(self, "_agent_worker", None)
        if worker is not None and not getattr(self, "_quitting", False):
            answer = self._ask_save_before_quit()
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            self._flush_own_state()  # instant and free either way
            if answer == QMessageBox.StandardButton.Save:
                self._quitting = True
                self._hand_off(worker, "quit")
                event.ignore()  # `_finish_handoff` closes the window once the turn lands
                return
        self._flush_own_state()
        self.stop_workers()
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
        super().closeEvent(event)  # the MCP server went down with `stop_workers()` above

    def _ask_save_before_quit(self):
        """Save, discard, or stay. Discard is not the default — losing a turn's worth of tuning is
        cheaper to avoid than to explain afterwards."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(i18n.t("quitSaveTitle"))
        box.setText(i18n.t("quitSaveBody"))
        box.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        # Qt writes its own labels on standard buttons, in ITS language: "Save / Discard / Cancel"
        # in English under a Ukrainian UI (user, 2026-08-19, with the screenshot). The three verbs
        # are ours to name — and naming them is also the difference between "Discard" and a word
        # that says what is lost.
        for button, key in (
            (QMessageBox.StandardButton.Save, "quitSaveSave"),
            (QMessageBox.StandardButton.Discard, "quitSaveDiscard"),
            (QMessageBox.StandardButton.Cancel, "quitSaveCancel"),
        ):
            widget = box.button(button)
            if widget is not None:
                widget.setText(i18n.t(key))
        # Qt sized the buttons for the labels it wrote; ours are longer, and without this the new
        # text is CLIPPED rather than the button grown (seen in a dark-theme render, 2026-08-19).
        box.adjustSize()
        return box.exec()

    def _on_language_selected(self, lang: str) -> None:
        i18n.set_language(lang)
        self._settings.setValue(_LANG_KEY, lang)
        self._retranslate()
        # A running session reads the language out of `get_tcc_state`; switching it here and not
        # republishing would leave the model writing files in the language of an hour ago.
        self._publish_snapshot()

    def _retranslate(self) -> None:
        """Re-set every already-built widget's text. Header/footer labels created via `_phead`
        aren't re-queried automatically (no live template binding) -- this is the "wire
        retranslate" step the plan calls for, done by direct re-assignment rather than a full
        observer registry, since the widget count is still small enough for that to be simple
        and correct."""
        # The menu's items keep the language they were BORN in -- a label is set once -- so the
        # main menu is rebuilt rather than re-set. It is also what makes the language check marks
        # follow the choice that was just made.
        self._build_main_menu()
        self._menu_btn.setText(i18n.t("menuButton"))
        self._theme_btn.setText("◐ " + i18n.t("theme"))
        self._feedback_btn.setText("💬 " + i18n.t("fbBig"))
        self._feedback_tip.set_text(i18n.t("fbBigTip"))
        self._coffee_btn.setText(i18n.t("coffeeBtn"))
        self._project_section.set_title(i18n.t("projectParams"))
        self._system_section.set_title(i18n.t("systemParams"))
        self._rebuild_system_params()
        self._audio_section.set_title(i18n.t("audioAnalysis"))
        self._rebuild_acoustics()
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
        self._refresh_critic_warning()
        for i in range(self._preset_combo.count()):
            self._preset_combo.setItemText(i, _preset_label(self._preset_combo.itemData(i)))
        self._plan_panel.retranslate()
        self._meas_panel.retranslate()
        if not self._has_project:
            # The panel's own empty state is "no capture task derived yet", which is a different
            # sentence from "no project open" -- and it cannot resolve the latter itself, since it
            # only ever sees the already-resolved string MainWindow passed in, not the i18n key.
            self._meas_panel.set_no_project(i18n.t("noProjectMeas"))
        self._create_project_btn.setText(i18n.t("createProject"))
        self._dialog.retranslate()
        # The tree builds its group headers / params-row labels from i18n at set_view() time and
        # has no live binding, so rebuild it in the new language (cheap -- a handful of widgets).
        if self._view is not None:
            self._tree.set_view(self._view)
