"""The window `CurveView` lives in: pull the named measurements out of REW, show them, read back.

Opened when the model and the Arbiter disagree about a number — by the model itself, eventually,
through an MCP tool that names the measurements and its own reading. Until that lands, `show()`
is the entry point and it takes the same arguments the tool will.

The REW read runs on a QThread for the reason every other REW call in this app does: `rew_api`
speaks plain synchronous `urllib`, and a GUI thread that waits on HTTP is a window that stops
repainting while somebody is sitting in a car with the engine off.
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
)

from autosound_tcc.core import config, curve_groups, delay_bank
from autosound_tcc.core.rew_bridge import RewBridge
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.curve_view import CurveView, Trace, tip_html, trace_token
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.theme import current_theme

#: What can be plotted, and how each one is fetched and labelled. Impulse first because that is
#: where the argument that prompted this happened; the others are the same widget with a different
#: reader, added when they are actually asked for rather than because a menu looked incomplete.
KINDS = {
    "impulse": {"label_x": "ms", "scale_x": 1000.0, "log_x": False, "label_y": ""},
    "fr": {"label_x": "Hz", "scale_x": 1.0, "log_x": True, "label_y": "dB"},
    # Phase is where a crossover argument actually gets settled (Δφ at the joint, then Δt from
    # it), and reading it off a picture is the thing this window exists to replace. Only a sweep
    # carries one -- REW returns no phase for an MMM capture.
    "phase": {"label_x": "Hz", "scale_x": 1.0, "log_x": True, "label_y": "°"},
}
#: How far either side of the peak the impulse view opens on. A REW impulse spans −995 ms to
#: +1735 ms (measured); the arrival argument happens inside a couple of milliseconds of the peak,
#: and everything else is there for whoever zooms out.
_IMPULSE_WINDOW_MS = 4.0
#: What an FR view opens on. REW reports out to 47 kHz and down to 4 Hz; outside the audible band
#: it is measurement noise, and auto-ranging over it flattens the part being argued about.
_FR_BAND_HZ = (20.0, 20000.0)
#: The suffix a title carries when the capture behind it is an MMM/RTA one. A CONVENTION written
#: by the skill's naming grammar (`naming-and-structure.md`, §"Method suffix"), not a fact REW
#: reports: the API has no field for how a measurement was taken, so short of asking for the
#: impulse and being told 400, the name is the only thing there is to go on. The rest of TCC reads
#: the same suffix (`state/measurement_view.py`).
_RTA_SUFFIX = "(rta)"


def _is_rta(title: str) -> bool:
    """Whether this title names an MMM/RTA capture.

    Matched anywhere in the title rather than only at the end, because an experiment in flight
    tags the name AFTER the method suffix ("w-L_2 (rta) INV") — the same trailing "extra" the
    measurement panel's `_classify_title` already allows for — and a tagged capture is still an
    MMM one with no impulse in it.
    """
    return _RTA_SUFFIX in str(title).casefold()


def _title_facts(title: str) -> tuple[Optional[str], Optional[str]]:
    """`(DSP config version, capture method)` for a title, read with the SKILL's own grammar.

    The grammar belongs to the skill — `rew_tool/naming.py` owns it, changes it, and is what wrote
    these titles in the first place — so TCC asks it rather than keeping a regex that drifts. It
    answers `None` for a title that is not in the grammar at all (a REW list holds imports and
    room-sim results too), and "unknown" is a verdict `curve_sum` already has words for; it is not
    an error and must never be treated as one.

    Two fallbacks, both deliberate. Without the skill installed there is no grammar to ask, and the
    curve window is not the place to discover that — the sum simply comes out labelled unknown.
    And a title the grammar rejects can still say `(rta)` out loud: `w-L_02 (rta) INV` does not
    parse (the grammar allows nothing after the method suffix) but it is unmistakably an MMM
    capture, so `_is_rta` — the one implementation of that question in this window — answers it.
    """
    parsed = None
    try:
        from autosound_tcc.core import vendor_loader

        parsed = vendor_loader.load_naming().parse_name(title)
    except Exception:  # noqa: BLE001 — no skill, or a title it will not parse: both are "unknown"
        parsed = None
    version = str(parsed.get("version")) if parsed and parsed.get("version") else None
    method = str(parsed.get("method")) if parsed and parsed.get("method") else None
    if method is None and _is_rta(title):
        method = _RTA_SUFFIX.strip("()")
    return version, method


def _start_time_of(measurement) -> Optional[float]:
    """REW's own timing reference for a capture, in seconds, or None when it does not report one.

    Free of any extra HTTP: resolving a title already costs one `GET /measurements`, and taking
    the measurement object out of that same answer (`by_name`) costs nothing more than throwing it
    away did. Carried so the sum can REPORT it — `rew-api-quirks.md` is explicit that a spread of
    start times cannot be judged from the numbers alone, so nothing here judges it.
    """
    if not isinstance(measurement, dict):
        return None
    for key in ("timeOfIRStartSeconds", "startTime", "delay"):
        value = measurement.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def kind_for(titles: Sequence[str], asked: str = "") -> str:
    """Which curve ALL of these measurements can actually show.

    An MMM/RTA capture has no impulse response — REW answers 400 — and no phase — the field comes
    back null (`rew-api-quirks.md`). Asking for either is an error the Arbiter sees as a broken
    window (user, 2026-08-11).

    ONE such title decides it for the whole selection. The window plots a single kind on a single
    pair of axes, so a MIXED sweep+RTA pair asked for an impulse fetched both, failed on the RTA
    half, and put "no phase in this measurement" in front of the Arbiter: the first fix only
    caught the case where EVERY title was RTA, and the mixed one was reported again.

    A magnitude is the one thing every capture holds, so that is what such a selection shows —
    even when the caller asked for something else, because there is nothing else on offer and
    answering "impulse" here would only move the failure into the worker.
    """
    wanted = asked if asked in KINDS else "impulse"
    return "fr" if any(_is_rta(t) for t in titles) else wanted


def _peak_x(trace) -> float:
    """The x of the largest |y| — an impulse's arrival, read the crudest way there is.

    numpy, because a Python loop over 262 144 samples is a visible pause per trace.
    """
    y = np.asarray(trace.y, dtype=float)
    if not y.size:
        return 0.0
    return float(np.asarray(trace.x, dtype=float)[int(np.argmax(np.abs(y)))])


class _CurveWorker(QThread):
    """Fetch each named measurement's curve.

    One `by_name` plus one curve call per title — two on the impulse, where the second brings back
    the frequency domain the sum's strip is drawn from (`_spectrum`). Per measurement rather than
    per batch, so one curve REW cannot produce does not take the others off the screen with it.
    """

    done = Signal(list)  # list[Trace]
    failed = Signal(str)

    def __init__(self, bridge: RewBridge, titles: Sequence[str], kind: str) -> None:
        super().__init__()
        self._bridge = bridge
        self._titles = list(titles)
        self._kind = kind

    def run(self) -> None:
        traces: list[Trace] = []
        problems: list[str] = []
        for title in self._titles:
            # Per measurement, not per batch: one curve REW cannot produce must not take the other
            # one off the screen with it. The window shows what it has and names what it does not.
            try:
                # `by_name` rather than `find_id`: both cost exactly one `GET /measurements`, and
                # this one keeps the measurement object out of the answer instead of dropping it.
                # That object is where REW's timing reference is, and the sum reports it.
                mid, measurement = self._bridge.by_name(title)
                # What the title says about the capture, in the skill's own grammar. Read for
                # every kind, not only where a sum is drawn: they are facts about the measurement,
                # not about the curve, and the impulse view will want them when its own strip
                # lands.
                version, method = _title_facts(title)
                facts = {
                    "config_version": version,
                    "method": method,
                    "start_time_s": _start_time_of(measurement),
                }
                if self._kind == "impulse":
                    times, samples = self._bridge.impulse_response(mid)
                    # numpy from here down. These are 262 144 points per trace, and a Python list
                    # comprehension over them was the panel's actual cost, not the HTTP call
                    # (measured: fetch 0.03 s).
                    x = np.asarray(times, dtype=float) * KINDS["impulse"]["scale_x"]
                    traces.append(
                        Trace(title, x, np.asarray(samples, dtype=float),
                              **self._spectrum(mid), **facts)
                    )
                else:
                    # Both halves, from the one call that returns both. Keeping only the one being
                    # drawn is what used to make a sum impossible without a second round trip —
                    # and a sum needs the magnitude AND the phase of every driver in it.
                    freqs, mag, phase = self._bridge.frequency_response(mid)
                    values = phase if self._kind == "phase" else mag
                    if values is None:
                        raise ValueError("no phase in this measurement")
                    traces.append(
                        Trace(title, np.asarray(freqs, dtype=float),
                              np.asarray(values, dtype=float),
                              magnitude_db=(
                                  None if mag is None else np.asarray(mag, dtype=float)
                              ),
                              phase_deg=(
                                  None if phase is None else np.asarray(phase, dtype=float)
                              ),
                              **facts)
                    )
            except Exception as exc:  # noqa: BLE001 — a REW failure is a message, not a crash
                problems.append(f"{title}: {type(exc).__name__}")
        if not traces:
            self.failed.emit("; ".join(problems) or "no curves")
            return
        self.done.emit(traces)

    def _spectrum(self, mid) -> dict:
        """The frequency-domain half of an impulse capture, for the sum's strip under the plot.

        One extra REW call per measurement, taken every time rather than when Σ happens to be on:
        the toggle is flipped while the window is open and a strip that needed a re-fetch to appear
        would answer a second later than the question. It is the same 0.03 s call the frequency
        views already make, and REW hands back both halves at once.

        Its own `try`, and this is the point of the method: a measurement REW cannot give a
        response for must still be PLOTTED as an impulse. Losing the sum's inputs costs the strip,
        which then says it has no data; losing the trace would cost the curve the tuner opened the
        window for.
        """
        try:
            freqs, mag, phase = self._bridge.frequency_response(mid)
        except Exception:  # noqa: BLE001 — see docstring; the impulse is the payload here
            return {}
        if freqs is None or mag is None:
            return {}
        return {
            "freqs_hz": np.asarray(freqs, dtype=float),
            "magnitude_db": np.asarray(mag, dtype=float),
            "phase_deg": None if phase is None else np.asarray(phase, dtype=float),
        }


class CurveDialog(QDialog):
    """`titles` from REW, `markers` where the model says the answer is.

    `readingSent` carries the Arbiter's own reading back as a sentence — the caller decides what to
    do with it (put it in the dialog, record it as a `user_decision`), because deciding that here
    would put the recording in two places.
    """

    readingSent = Signal(str)

    def __init__(
        self,
        titles: Sequence[str],
        markers: Sequence[float] = (),
        kind: str = "impulse",
        bridge: Optional[RewBridge] = None,
        available: Sequence[str] = (),
        parent=None,
    ) -> None:
        """`titles` is what to plot. `available` is everything REW holds, for the pickers, the
        group picker and the checkbox list — pass it and the Arbiter can change their mind about
        which drivers are being argued about without closing the window and finding a different
        button."""
        super().__init__(parent)
        self.setWindowTitle(i18n.t("curveTitle"))
        self.resize(880, 560)
        self._kind = kind_for(titles, kind)
        self._markers = list(markers)
        self._bridge = bridge or RewBridge()
        self._worker: Optional[_CurveWorker] = None
        #: Why what is on screen is not what was asked for, in words. Empty when nothing was
        #: refused — the status line is then free to disappear, as it did before. `_note` is the
        #: whole line; `_refused_note` and `_group_note` are the two things that can be on it.
        self._note = ""
        self._refused_note = ""
        #: Which measurement the delay currently on screen is banked against, so that moving the
        #: radio moves the entry instead of leaving one behind on the other curve.
        self._restoring = False
        #: `() -> {channel code: ms}` — what the DSP is set to now, supplied by the window because
        #: this dialog has no business loading a ledger. Without it the panel simply does not
        #: state a total, which is honest; with it, it can say when a correction would take a
        #: channel below zero (user, 2026-08-12).
        self._delays_provider = None
        #: `() -> capture-series id`. The bank is scoped by it: switching the measurement panel
        #: back to an earlier series brings that series' own curves, so it must bring that series'
        #: own corrections too (user, 2026-08-12).
        self._session_provider = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        # Two pickers, KEPT, because a disagreement is nearly always about a pair and two combos
        # side by side is the shortest path to one. They are now a fast path into a selection that
        # can hold any number of measurements rather than the only way to say what is plotted —
        # see `_chosen`, which is the one place that answers "what is on screen".
        self._pickers: list[QComboBox] = []
        #: Everything REW holds, whatever this kind can draw of it. The pickers show a SUBSET —
        #: see `_fill_pickers` — so the full list has to live somewhere that is not a widget.
        self._options = list(available) or list(titles)
        #: The chosen measurements, in the order they will be plotted. THE selection: every control
        #: writes it and nothing else is consulted, because two controls each holding half a
        #: selection is how a window comes to draw one thing and report another.
        self._selection: list[str] = [str(t) for t in titles if t]
        #: The group whose members are on screen, and what it could not find. Kept so changing the
        #: version re-resolves the same group rather than clearing it.
        self._group: Optional[curve_groups.Group] = None
        self._group_note = ""
        self._groups = curve_groups.GlossaryGroups.load()
        self._syncing_selection = False
        #: Whether one of the checkbox menu's own actions is mid-`toggled` — see
        #: `_fill_choose_menu`, which must not destroy an action that is emitting.
        self._in_choose_toggle = False
        if self._options:
            picker_row = QHBoxLayout()
            picker_row.setSpacing(8)
            for index in range(2):
                combo = QComboBox()
                combo.setProperty("class", "mini-select")
                combo.currentIndexChanged.connect(self._on_selection_changed)
                picker_row.addWidget(combo, 1)
                self._pickers.append(combo)
            self._fill_pickers(titles)
            layout.addLayout(picker_row)
            layout.addLayout(self._build_group_row())

        # The kind is a property of the WINDOW, not of a measurement: two curves in different
        # units on one pair of axes would be a picture of nothing. Switching it re-fetches.
        self._kind_combo = QComboBox()
        self._kind_combo.setProperty("class", "mini-select")
        for key in KINDS:
            self._kind_combo.addItem(i18n.t(f"curveKind_{key}"), key)
        self._kind_combo.setCurrentIndex(max(0, self._kind_combo.findData(self._kind)))
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        if self._pickers:
            picker_row.addWidget(self._kind_combo)
        else:
            layout.addWidget(self._kind_combo)

        self._status = QLabel(i18n.t("curveLoading"))
        self._status.setProperty("class", "phead-sub")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._view = CurveView(x_label=str(KINDS[self._kind]["label_x"]))
        self._view.on_send(self._on_send)
        self._view.delayChanged.connect(self._bank_current_delay)
        layout.addWidget(self._view, stretch=1)

        # Everything read so far, and one button that hands the whole set to the model. A delay is
        # only ever relative to the rest of the car, so one pair's number decides nothing — and
        # this window used to drop each one as soon as the next pair loaded (user, 2026-08-12).
        bank_row = QHBoxLayout()
        bank_row.setContentsMargins(0, 0, 0, 0)
        bank_row.setSpacing(8)
        # The set behind a button that COUNTS it, not a line of small grey type running the width
        # of the window (user, 2026-08-18). The count is the part worth seeing without hovering:
        # seven readings on a nine-driver car is the fact that decides whether the set is worth
        # sending yet. The list itself is the tip.
        self._bank_btn = QPushButton("")
        self._bank_btn.setProperty("class", "clear-btn")
        self._bank_btn.setCursor(Qt.CursorShape.WhatsThisCursor)
        self._bank_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        attach_tip(self._bank_btn, "")
        bank_row.addWidget(self._bank_btn)
        bank_row.addStretch(1)
        # "Clear" is two different things and one button cannot be both: the delays are a set
        # being built up over an afternoon, the markers are one reading being dragged (user,
        # 2026-08-12). They sit down here together; the ACTIONS go up with the controls.
        clear_label = QLabel(i18n.t("curveClearLabel"))
        clear_label.setProperty("class", "phead-sub")
        bank_row.addWidget(clear_label)
        self._bank_clear_btn = QPushButton(i18n.t("curveClearDelay"))
        self._bank_clear_btn.setProperty("class", "clear-btn")
        self._bank_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bank_clear_btn.clicked.connect(self._on_clear_bank)
        bank_row.addWidget(self._bank_clear_btn)
        self._markers_clear_btn = QPushButton(i18n.t("curveClearMarkers"))
        self._markers_clear_btn.setProperty("class", "clear-btn")
        self._markers_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._markers_clear_btn.clicked.connect(
            lambda: self._view.bring_markers_into_view(force=True)
        )
        bank_row.addWidget(self._markers_clear_btn)
        layout.addLayout(bank_row)

        # The delay group's own action, beside the delay controls, named after the group — the
        # markers group has its own at the end of the row, and the Clear section below repeats
        # both names. Two verbs, four buttons, no button called "this is my reading".
        self._bank_ask_btn = QPushButton(i18n.t("curveSendDelays"))
        self._bank_ask_btn.setProperty("class", "composer-send")
        self._bank_ask_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bank_ask_btn.clicked.connect(self._on_ask_about_bank)
        self._view.add_delay_action(self._bank_ask_btn)

        self._titles = list(titles)
        self._apply_delay_resolution()
        self._render_bank()
        # Asked again over what the PICKERS ended up on, not over `titles`: a title the caller
        # named but `available` does not hold leaves its picker on some other measurement, and the
        # kind has to answer for what will actually be fetched.
        self._selection = self._from_pickers() if self._pickers else list(titles)
        self._settle_kind(kind)

    # ---- choosing more than two curves (CURVE-ANALYSIS-PLAN.md, step 3) -----

    def _build_group_row(self) -> QHBoxLayout:
        """The row that puts a whole group on screen: which group, at which config version.

        Two controls and not one, because they answer different questions and the second is the
        one that goes wrong quietly: `Ws` says which drivers, `_02` says which round of the car.
        A group resolved at the wrong version is a set of measurements taken under a DSP
        configuration nobody is looking at, and `curve_sum` would happily add them up and label it
        "two different cars" — a label nobody asked for.
        """
        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel(i18n.t("curveGroupLabel"))
        label.setProperty("class", "phead-sub")
        row.addWidget(label)

        self._group_combo = QComboBox()
        self._group_combo.setProperty("class", "mini-select")
        attach_tip(self._group_combo, tip_html(i18n.t("curveGroupTip")))
        self._fill_group_combo()
        self._group_combo.currentIndexChanged.connect(self._on_group_chosen)
        row.addWidget(self._group_combo, 2)

        self._version_combo = QComboBox()
        self._version_combo.setProperty("class", "mini-select")
        self._version_combo.setFixedWidth(96)
        attach_tip(self._version_combo, tip_html(i18n.t("curveGroupVersionTip")))
        self._version_combo.currentIndexChanged.connect(self._on_version_chosen)
        row.addWidget(self._version_combo)

        # A menu of checkable rows rather than a list widget: it costs one row of window whether
        # the car has six measurements or sixty, and this window is already tall. Plain QActions —
        # the QWidgetAction that `curve_view` goes to such lengths to avoid is a different animal.
        self._choose_btn = QPushButton("")
        # `.zoom-btn` and not `.mini-select`: every `.mini-select` rule is written `QComboBox[...]`
        # and would not reach a QPushButton at all (the delay spin box learned this the hard way,
        # 2026-08-18). The two classes share their background, border, radius and font size, so a
        # button wearing this one sits in a row of combos without looking like a visitor.
        self._choose_btn.setProperty("class", "zoom-btn")
        self._choose_btn.setMinimumWidth(132)
        self._choose_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        attach_tip(self._choose_btn, tip_html(i18n.t("curveChooseTip")))
        self._choose_menu = QMenu(self)
        self._choose_actions: dict[str, QAction] = {}
        self._choose_btn.setMenu(self._choose_menu)
        row.addWidget(self._choose_btn, 1)
        self._fill_choose_menu()
        self._sync_version_combo()
        return row

    def _fill_group_combo(self) -> None:
        """Every group this car has, with its TYPE on the row.

        `Ws` is a pair and `L` is a side, and a list of bare names does not say which — so the kind
        is printed beside each. With no glossary (no 3.x project, or no skill) the combo says so
        and stays disabled: the checkbox list below is unaffected, which is the point of having
        both.
        """
        combo = self._group_combo
        blocked = combo.blockSignals(True)
        combo.clear()
        groups = self._groups.groups()
        combo.addItem(i18n.t("curveGroupNone") if groups else i18n.t("curveGroupNoGlossary"), -1)
        for index, group in enumerate(groups):
            combo.addItem(
                f"{group.name} · {i18n.t('curveGroupKind_' + group.kind)}", index
            )
        combo.setCurrentIndex(0)
        combo.setEnabled(bool(groups))
        combo.blockSignals(blocked)

    def _fill_choose_menu(self) -> None:
        """One checkable row per measurement this kind can draw, ticked to match the selection.

        Rebuilt from scratch rather than reconciled: the row set changes with the kind (an MMM
        capture is absent on the impulse and the phase — `_fill_pickers`), and a menu half-rebuilt
        is a menu that can tick a measurement the window will not fetch.

        Never rebuilt while one of its own actions is emitting `toggled`. `clear()` DESTROYS the
        actions, and destroying the object a signal is being delivered from is this app's oldest
        way of ending a process (the same rule as deleting a widget inside its own event handler).
        Ticking a row cannot change which rows exist anyway — an MMM row is only reachable on the
        frequency response, which is where a selection with one in it puts the window regardless —
        so the tick path only has to re-tick, and that is what it does.
        """
        if getattr(self, "_choose_menu", None) is None:
            return
        if self._in_choose_toggle:
            self._sync_choose_ticks()
            return
        self._choose_menu.clear()
        self._choose_actions = {}
        for title in self._selectable():
            action = self._choose_menu.addAction(title)
            action.setCheckable(True)
            action.toggled.connect(lambda on, t=title: self._on_choose_toggled(t, on))
            self._choose_actions[title] = action
        self._sync_choose_ticks()

    def _sync_choose_ticks(self) -> None:
        """Tick the rows the window is plotting, and count them on the button.

        Signals blocked: `setChecked` emits `toggled`, and a tick set BY the selection arriving
        back at the handler that changes the selection is a loop with no bottom.
        """
        chosen = set(self._chosen())
        for title, action in self._choose_actions.items():
            blocked = action.blockSignals(True)
            action.setChecked(title in chosen)
            action.blockSignals(blocked)
        self._choose_btn.setText(i18n.t("curveChooseBtn").format(n=len(chosen)))

    def _selectable(self) -> list[str]:
        """What may be plotted on THIS kind — the same rule the two pickers follow."""
        return [t for t in self._options if self._kind == "fr" or not _is_rta(t)]

    def _sync_version_combo(self, select: Optional[str] = None) -> None:
        """Offer the config versions REW holds, standing on the one the question is about.

        The rule, in order: the version the chosen curves are already on when they agree — that is
        the round the tuner is working in — and otherwise the newest REW has for the group's own
        members. Not the newest overall: a car whose sub was re-measured at `_04` while the
        tweeters stopped at `_02` would offer the tweeters a version none of them has.

        `select` overrides both and is how a group resolved at one version keeps it.
        """
        combo = getattr(self, "_version_combo", None)
        if combo is None:
            return
        codes = self._group.members if self._group else ()
        versions = self._groups.versions_in(self._options, codes)
        wanted = (
            select
            or self._groups.version_of(self._chosen())
            or (versions[-1] if versions else None)
        )
        blocked = combo.blockSignals(True)
        combo.clear()
        for version in reversed(versions):  # newest first: it is the usual answer
            combo.addItem(f"_{version}", version)
        if wanted is not None and combo.findData(wanted) < 0:
            combo.addItem(f"_{wanted}", wanted)
        at = combo.findData(wanted) if wanted is not None else -1
        combo.setCurrentIndex(at if at >= 0 else 0)
        combo.setEnabled(combo.count() > 0)
        combo.blockSignals(blocked)

    def _on_group_chosen(self, _index: int) -> None:
        at = self._group_combo.currentData()
        groups = self._groups.groups()
        if not isinstance(at, int) or at < 0 or at >= len(groups):
            # Back to "no group". What is plotted does not change — the tuner is saying the
            # selection is theirs now, not the glossary's — but a note about a group nobody has
            # chosen has to go with it.
            self._group = None
            self._group_note = ""
            self._render_note()
            return
        self._group = groups[at]
        # The version combo follows the group before the group is resolved: a group's own members
        # decide which versions are on offer at all.
        self._sync_version_combo(select=str(self._version_combo.currentData() or "") or None)
        self._apply_group()

    def _on_version_chosen(self, _index: int) -> None:
        """A version is only a question when a group is chosen; on its own it changes nothing."""
        if self._group is not None:
            self._apply_group()

    def _apply_group(self) -> None:
        """Put the chosen group at the chosen version on screen, and NAME what is not there.

        A member with no `(sw)` capture at this version is not skipped. `curve_sum` sees only what
        it is handed, so it cannot tell the sum of the woofers from the sum of one woofer — this
        sentence is the only place in the whole path that can, which is why it is on screen rather
        than in a log.
        """
        version = str(self._version_combo.currentData() or "")
        if self._group is None or not version:
            return
        found = self._groups.resolve(self._group, version, self._options)
        names = ", ".join(found.missing)
        if not found.titles:
            # Nothing to change and nothing to fetch: the curves being looked at stay on screen,
            # which beats an empty plot, and the line under the pickers says where it looked.
            self._group_note = i18n.t("curveGroupEmpty").format(
                group=self._group.name, version=version
            )
            self._render_note()
            return
        self._group_note = "" if found.complete else i18n.t("curveGroupMissing").format(
            group=self._group.name, version=version, names=names
        )
        self._set_selection(list(found.titles))

    def _on_choose_toggled(self, title: str, on: bool) -> None:
        """A ticked row adds the measurement; an unticked one drops it. Order follows the list.

        Ticking by hand ends the group's claim on the selection: what is on screen is no longer
        "the woofers", so a note about a missing woofer would be about a set nobody is looking at.
        """
        if self._syncing_selection:
            return
        chosen = [
            row for row in self._selectable()
            if (row == title and on) or (row != title and row in self._chosen())
        ]
        self._in_choose_toggle = True
        try:
            self._clear_group()
            self._set_selection(chosen)
        finally:
            self._in_choose_toggle = False

    def _clear_group(self) -> None:
        """Let go of the group, and say so on the picker that names it."""
        self._group = None
        self._group_note = ""
        combo = getattr(self, "_group_combo", None)
        if combo is not None and combo.currentIndex() != 0:
            blocked = combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(blocked)

    def _set_selection(self, titles: Sequence[str]) -> None:
        """Make `titles` what the window is plotting, and put every control in step with it.

        One selection, several ways to say it: the two pickers show the first two of it (a pair is
        still the commonest question and they are still the quickest way to ask one), the menu
        ticks all of it, the version combo follows it. Guarded against re-entry because moving a
        picker emits the same signal that arrives when the tuner moves one by hand.
        """
        self._selection = [str(t) for t in titles if t]
        if getattr(self, "_version_combo", None) is None:
            # No pickers means no group row either (both are built only when there is a list of
            # measurements to offer), and then there is nothing to keep in step.
            self._settle_kind(self._kind)
            return
        self._syncing_selection = True
        try:
            for index, combo in enumerate(self._pickers):
                target = self._selection[index] if index < len(self._selection) else ""
                at = combo.findData(target)
                blocked = combo.blockSignals(True)
                combo.setCurrentIndex(at if at >= 0 else 0)
                combo.blockSignals(blocked)
            self._sync_choose_ticks()
            self._sync_version_combo(select=str(self._version_combo.currentData() or "") or None)
        finally:
            self._syncing_selection = False
        self._settle_kind(self._kind)

    # ---- the delay bank -----------------------------------------------------

    def set_delays_provider(self, provider) -> None:
        self._delays_provider = provider
        self._sync_channel_delay()

    def set_session_provider(self, provider) -> None:
        self._session_provider = provider
        self._render_bank()

    def session_switched(self) -> None:
        """The measurement panel moved to another capture series while this window was open.

        Only the bank is re-read. The curves stay: the Arbiter may well be switching series in
        order to compare, and yanking the plot out from under them would be the window deciding
        what they are doing.
        """
        self._render_bank()

    def _session(self) -> Optional[str]:
        if not self._session_provider:
            return None
        try:
            return self._session_provider() or None
        except Exception:  # noqa: BLE001 — a curve window must not die on a panel read
            return None

    def _current_delay_of(self, title: str):
        if not self._delays_provider or not title:
            return None
        try:
            return (self._delays_provider() or {}).get(delay_bank.code_of(title))
        except Exception:  # noqa: BLE001 — a curve window must not die on a ledger read
            return None

    def _sync_channel_delay(self) -> None:
        """What each channel on screen is set to now — every one of them, because every one may
        carry a proposal and the reading states a total for each."""
        for index, trace in enumerate(self._view._traces):
            self._view.set_channel_delay(self._current_delay_of(trace.name), index)

    def _bank_current_delay(self) -> None:
        """Remember what the Arbiter just read, against the measurement they read it on.

        Written on every change rather than on close: this window is left open across a whole
        alignment pass, and a crash or a forgotten close would take the afternoon's readings with
        it. Zero removes the entry — "needs no delay" and "not looked at yet" are different claims
        and only the second is honest about a curve nobody opened.

        Moving the radio MOVES the reading rather than copying it. One pair has one answer and it
        sits on one side; both sides banked at 0.198 ms would be the window claiming the Arbiter
        read the same gap twice. What it must not do is touch a delay banked on the OTHER curve
        from an earlier pair — those are two independent facts about two alignments, and they
        coexist happily.
        """
        if self._restoring:
            return
        for index, trace in enumerate(self._view._traces):
            # All of them, every time. Each driver carries its own delay now, so there is
            # nothing to move
            # from one entry to another — the radio only chooses which one you are typing into.
            # The arrival AS CAPTURED goes with it: a delay with no origin cannot be checked, and
            # checking the set is the only reason it is ever sent anywhere.
            delay_bank.put(
                trace.name, self._view.delay_ms(index),
                arrival_ms=_peak_x(trace) if self._kind == "impulse" else None,
                session=self._session(),
            )
        self._sync_channel_delay()
        self._render_bank()

    def _render_bank(self) -> None:
        """The banked set behind its own button, and the same numbers beside the titles in the
        pickers.

        In the pickers because that is where the Arbiter is choosing the next pair: seeing that
        w-L already carries +0.198 ms is what stops the same channel being read twice against two
        different partners and banked twice with different answers.
        """
        bank = delay_bank.load(session=self._session())
        head = i18n.t("curveBankLabel")
        if bank:
            shown = ", ".join(f"{title} {ms:+.3f}" for title, ms in sorted(bank.items()))
            series = self._session()
            if series:
                # Named, because the same channel can carry a different correction in another
                # series and a list with no series on it says which one is being looked at.
                head = i18n.t("curveBankLabelIn").format(set=series)
        else:
            shown = i18n.t("curveBankEmpty")
        self._bank_btn.setText(i18n.t("curveBankBtn").format(n=len(bank)))
        if getattr(self._bank_btn, "hover_tip", None) is not None:
            self._bank_btn.hover_tip.set_text(tip_html(shown, head=head))
        self._bank_ask_btn.setEnabled(bool(bank))
        self._bank_clear_btn.setEnabled(bool(bank))
        for combo in self._pickers:
            for row in range(combo.count()):
                title = str(combo.itemData(row) or "")
                if not title:
                    continue
                ms = bank.get(title)
                combo.setItemText(row, f"{title}  ·  {ms:+.3f} ms" if ms else title)

    def _on_ask_about_bank(self) -> None:
        """The whole set, to be LOOKED AT — never written.

        It goes into the composer like every other statement of the Arbiter's, so they read it
        before it is sent. Nothing about this touches a DSP: the model is being asked whether the
        picture holds together, not to apply it (user, 2026-08-12: "відправити на аналіз ШІ (не
        для запису)").
        """
        series = self._session()
        bank = delay_bank.load(session=series)
        text = delay_bank.as_sentence(
            bank, self._sample_rate_hz(), i18n.t, self._current_delay_of,
            at=delay_bank.arrivals(session=series),
            unplaced=self._unplaced(delay_bank.seen(session=series)),
            reference=delay_bank.references(session=series),
        )
        if text:
            self.readingSent.emit(text)

    def _unplaced(self, seen) -> list:
        """Measurements of the same kind as the ones already looked at, never opened in here.

        Same KIND, by the capture-method suffix the titles carry: the pickers hold both the sweep
        and the RTA of every channel, and listing an RTA capture as an unplaced driver would be
        noise about a measurement that has no arrival at all. Whatever suffix the seen ones share
        is the family under discussion.

        A driver left at zero is NOT here — it is the reference, and it has an entry.

        Read off everything REW holds, not off the picker rows: the pickers show only what the
        current kind can draw (`_fill_pickers`), and which measurements exist is a fact about the
        project rather than about the view somebody happens to be on.
        """
        if not seen:
            return []
        suffixes = {t.partition(" ")[2] for t in seen}
        return [
            title for title in self._options
            if title and title not in seen and title.partition(" ")[2] in suffixes
        ]

    def _on_clear_bank(self) -> None:
        """Forget this series' readings, and put the curves on screen back where they were drawn.

        Guarded and in this order for a reason. Clearing the store first and zeroing the plot
        afterwards wrote the pair straight back in: zeroing emits `delayChanged`, the handler
        banks EVERY curve on screen, and the ones that were not selected still held their delays.
        The user pressed Clear and watched a single value survive — the other curve's
        (2026-08-12). With a whole side plotted there would have been three survivors.
        """
        self._restoring = True
        try:
            target = self._view.delay_target()
            for index in range(len(self._view._traces)):
                self._view.set_delay_target(index)
                self._view.set_delay(0.0)
            self._view.set_delay_target(target)
        finally:
            self._restoring = False
        delay_bank.clear(session=self._session())
        self._render_bank()

    def _sample_rate_hz(self):
        return getattr(self._view, "_sample_rate_hz", None)

    def _apply_delay_resolution(self) -> None:
        """Step the delay control by what THIS processor accepts, from its own profile.

        Two different numbers, and the panel needs both. Helix takes 0.01 ms in its box while the
        hardware resolves samples (1/96 kHz = 0.010417 ms), which is why typing successive steps
        sometimes moves nothing and sometimes moves two — the user has watched it happen and had
        no way to explain it. MUSWAY shows thousandths on a step nobody here has confirmed. So the
        control steps by `delay.step_ms` where the profile states one, and the reading carries the
        sample count only when a sample rate is on record. Guessing either would put a number in
        front of the Arbiter that the DSP never agreed to.
        """
        step, rate = None, None
        try:
            import json

            raw = json.loads(config.dsp_profile_path().read_text(encoding="utf-8"))
            profile = raw.get("dsp_profile") if isinstance(raw.get("dsp_profile"), dict) else raw
            delay = profile.get("delay")
            if isinstance(delay, dict):
                step = delay.get("step_ms")
            rate = profile.get("sample_rate_hz")
        except Exception:  # noqa: BLE001 — no profile yet is the ordinary case, not a failure
            pass
        self._view.set_resolution(
            float(step) if isinstance(step, (int, float)) else None,
            float(rate) if isinstance(rate, (int, float)) else None,
        )

    def _on_kind_changed(self, _index: int) -> None:
        self._settle_kind(str(self._kind_combo.currentData() or "impulse"))

    def _on_selection_changed(self, _index: int) -> None:
        """The pair changed, and what it can show may have changed with it — swapping a sweep for
        an MMM capture takes the impulse and the phase away with it.

        Touching a picker means "these two": the selection collapses to the pair on screen, however
        many curves were plotted before. That is what the pickers are FOR, and the alternative —
        replacing one member of a six-curve set from a control that shows two of them — would let
        the window plot six curves while two combos describe the whole selection.
        """
        if self._syncing_selection:
            return
        self._clear_group()
        self._set_selection(self._from_pickers())

    def _settle_kind(self, asked: str) -> None:
        """Put the window on the kind this selection can answer, then fetch.

        `kind_for` has the last word, not the picker: an MMM capture in the pair carries neither
        an impulse nor a phase, so the window stays on the magnitude — and SAYS which measurement
        is the reason. Quietly fetching the sweep alone was the other option and it is worse: that
        is the window deciding which of the two curves the Arbiter meant.
        """
        asked = asked if asked in KINDS else "impulse"
        self._kind = kind_for(self._chosen(), asked)
        # In words as well as greyed out in the picker: a disabled row explains itself only to
        # somebody who thinks to hover it, and this one has just refused something that was asked
        # for out loud.
        rta = [t for t in self._chosen() if _is_rta(t)]
        self._refused_note = (
            "" if self._kind == asked else i18n.t("curveRtaOnly").format(titles=", ".join(rta))
        )
        self._render_note()
        self._apply_kind()
        self._reload()

    def _render_note(self) -> None:
        """Everything the window has to say about what it is showing, on the one status line.

        Both notes, not one: a group with a member missing and a kind that had to be overruled are
        two independent facts about the same selection, and whichever is dropped is the one the
        tuner needed.
        """
        self._note = " ".join(
            part for part in (self._refused_note, self._group_note) if part
        )
        self._status.setText(self._note)
        self._status.setVisible(bool(self._note))

    def _apply_kind(self) -> None:
        spec = KINDS[self._kind]
        self._view.set_unit(str(spec["label_x"]))
        self._view.set_y_unit(str(spec["label_y"]))
        self._view.set_log_x(bool(spec["log_x"]))
        # A frequency response is as often read for its level as for its frequency, so it opens
        # with both; an impulse is an arrival time and nothing else.
        self._view.set_axes_mode("vh" if self._kind in ("fr", "phase") else "v")
        # The kind picker is MOVED from here, not merely read: `kind_for` can overrule what was
        # asked for, and a combo still reading "impulse" above a frequency response is the window
        # lying about what is on screen.
        blocked = self._kind_combo.blockSignals(True)
        self._kind_combo.setCurrentIndex(max(0, self._kind_combo.findData(self._kind)))
        self._kind_combo.blockSignals(blocked)
        self._mark_availability()

    def _fill_pickers(self, wanted: Sequence[str] = ()) -> None:
        """Put the measurements this kind can actually draw into the two pickers.

        An MMM/RTA capture is ABSENT here on the impulse and the phase, not greyed (user,
        2026-08-18, overruling the habit for this one list). The reasoning is the window's own
        invariant: `kind_for` moves the window to the magnitude the moment an MMM capture is
        chosen, so while the kind is impulse or phase no MMM row can ever BE the chosen one. A row
        that can never be chosen is not a marked choice, it is noise — and these lists are long,
        one sweep and one MMM capture per channel.

        The kind picker keeps its grey-out, because there the marked row is a choice somebody just
        asked for out loud and is owed an explanation for.

        `wanted[index]` is what each picker should land on; whatever it is showing now is the
        fallback, which is what makes this safe to call from a selection change — choosing an MMM
        capture on the impulse view brings the whole family back and keeps the choice.
        """
        shown = [t for t in self._options if self._kind == "fr" or not _is_rta(t)]
        for index, combo in enumerate(self._pickers):
            target = str(wanted[index]) if index < len(wanted) else str(combo.currentData() or "")
            blocked = combo.blockSignals(True)
            combo.clear()
            if index:
                combo.addItem(i18n.t("curveNoSecond"), "")
            for title in shown:
                combo.addItem(title, title)
            at = combo.findData(target)
            combo.setCurrentIndex(at if at >= 0 else 0)
            combo.blockSignals(blocked)
        # The rows are new objects, so the delays `_render_bank` wrote beside the titles went with
        # the old ones. Guarded because the pickers are built before the bank's own widgets are.
        if getattr(self, "_bank_btn", None) is not None:
            self._render_bank()
        # The checkbox list obeys the same kind rule and has to follow the same change.
        self._fill_choose_menu()

    def _mark_availability(self) -> None:
        """Grey out what cannot be shown in the KIND picker, and drop what cannot be drawn from
        the measurement pickers.

        Two different answers to the same question, on purpose. A kind is marked and left on
        screen, which is this app's habit for a choice that exists and does not apply here
        (`main_window._fill_combo` keeps an unavailable model visible and marked): it was asked
        for out loud and it is owed a reason. A measurement that cannot be drawn in this mode is
        not a refused request, it is one row of a long list that this kind has nothing to do with
        — see `_fill_pickers`.

        Both directions, because the mixed pair can be built from either end — an MMM capture
        chosen while the impulse is up, or the impulse asked for while one is already plotted.

        No text badge on the rows. A measurement's title already ends in `(rta)` and the kind rows
        are already named after their kind, so a badge would restate the row instead of adding a
        fact — which is why the model picker's own badges were taken off (user, 2026-08-12).
        """
        faint = QColor(current_theme().faint)
        self._fill_pickers()
        has_rta = any(_is_rta(t) for t in self._chosen())
        for row in range(self._kind_combo.count()):
            key = str(self._kind_combo.itemData(row) or "")
            self._mark_row(
                self._kind_combo, row, has_rta and key != "fr", i18n.t("curveKindRtaTip"), faint
            )

    @staticmethod
    def _mark_row(combo: QComboBox, row: int, shut: bool, tip: str, faint: QColor) -> None:
        """One row's "not on offer here" state, set BOTH ways.

        The clearing half matters as much as the marking half: the kind goes back and forth all
        afternoon, and a row greyed once and never un-greyed is worse than one never marked.

        The colour is set explicitly rather than left to Qt's disabled palette because the
        `.mini-select` stylesheet pins `color` on the popup view, and a QSS colour wins over the
        palette in every state — a disabled row would otherwise look exactly like a live one.
        """
        item = combo.model().item(row)
        if item is not None:
            item.setEnabled(not shut)
        combo.setItemData(row, faint if shut else None, Qt.ItemDataRole.ForegroundRole)
        combo.setItemData(row, tip if shut else None, Qt.ItemDataRole.ToolTipRole)

    def _from_pickers(self) -> list[str]:
        return [str(c.currentData() or "") for c in self._pickers if c.currentData()]

    def _chosen(self) -> list[str]:
        """What the window is plotting — the ONE answer, whoever set it last.

        The two pickers, the group picker and the checkbox list all write `_selection`, and
        everything downstream reads this. Three controls each holding part of the truth is how a
        window comes to draw one set of curves and report another.

        Falls back to the pickers when the selection is empty, so unticking the last row leaves a
        curve on screen rather than a blank plot and a window with nothing to say.
        """
        if not self._pickers:
            return list(self._titles)
        return [t for t in self._selection if t] or self._from_pickers()

    def _reload(self) -> None:
        """Fetch whatever is selected. Waits out an in-flight worker rather than assigning over
        it: Qt aborts the process when a running QThread is destroyed, which the measurement
        panel learned the expensive way."""
        titles = self._chosen()
        if not titles:
            return
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(4000)
        self._status.setVisible(True)
        self._status.setText(i18n.t("curveLoading"))
        self._worker = _CurveWorker(self._bridge, titles, self._kind)
        self._worker.done.connect(self._on_curves)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_curves(self, traces: list) -> None:
        # The status line ends up carrying the notes, if there are any, and disappears when there
        # are not. It is written HERE as well as where each note is decided, because `_reload` puts
        # "Reading the curves from REW…" over whatever was there.
        self._render_note()
        self._view.set_traces(traces)
        # A curve already argued about comes back with its answer on it. `set_traces` clears the
        # delays by design (a new selection is a new question); the bank is what makes coming BACK
        # to a driver different from meeting it for the first time — and over a whole side that is
        # most of what is on screen, not one of two curves.
        bank = delay_bank.load(session=self._session())
        # Restoring, not reading: `_bank_current_delay` must not see these calls, or the zeros
        # they pass through on the way would erase what they are restoring.
        self._restoring = True
        try:
            target = self._view.delay_target()
            for index, trace in enumerate(traces):
                if trace.name in bank:
                    self._view.set_delay_target(index)
                    self._view.set_delay(bank[trace.name])
            self._view.set_delay_target(target)
        finally:
            self._restoring = False
        positions, names, tokens = self._starting_markers(traces)
        self._view.set_markers(positions, names, tokens)
        self._frame(traces, positions)
        self._sync_channel_delay()
        self._render_bank()

    def _frame(self, traces: list, positions: list) -> None:
        """Open on the part being argued about rather than on everything REW recorded."""
        if self._kind in ("fr", "phase"):
            self._view.focus_x(*_FR_BAND_HZ)
        elif positions:
            centre = sum(positions) / len(positions)
            self._view.focus_x(centre - _IMPULSE_WINDOW_MS, centre + _IMPULSE_WINDOW_MS)
        self._view.autoscale_y()

    def _starting_markers(self, traces: list):
        """Where the markers begin, and what to call them.

        With a reading from the model, ON it — and a second marker on top of the first, because
        dragging away from where the model read it IS the disagreement, so every millimetre of
        movement is deliberate.

        Without one (the Arbiter opened this themselves), on each trace's own largest peak — every
        trace, however many there are. For an impulse that is the arrival by the crudest possible
        reading, which makes the delta meaningful before anything has been touched, and over a
        whole side it is the picture the alignment is argued from: six arrivals, each one placed.
        A starting point that is obviously a guess invites correction better than markers parked at
        zero.

        The model's own reading stays a PAIR (model versus you) whatever is plotted: that pair is
        the disagreement the window exists to settle, and a third marker in it would have no owner.
        """
        if self._markers:
            positions = list(self._markers)
            names = [i18n.t("curveMarkerModel"), i18n.t("curveMarkerYou")]
            if len(positions) == 1:
                positions.append(positions[0])
            return positions[:2], names[:len(positions[:2])], []
        usable = [t for t in traces if len(t.x)]
        # One marker per curve, each in its curve's own colour: nobody has claimed a reading yet,
        # so calling the first one "the model's" would be a lie the colour tells.
        return ([_peak_x(t) for t in usable], [t.name for t in usable],
                [trace_token(i) for i in range(len(usable))])

    def reset(self, titles, markers=(), kind="impulse", available=()) -> None:
        """Re-point an existing window at a new question, instead of building another one.

        pyqtgraph's `PlotItem` builds several parentless QMenus and `QWidgetAction`s on every
        construction, whatever `enableMenu` says, and constructing/destroying enough of them
        segfaults the process from inside its own `__init__` — reproduced in the suite, and
        reachable in the app by opening this window twenty times during a tune (2026-08-12).
        One window, re-pointed, avoids the whole class rather than betting on the collector.
        """
        self._markers = [float(m) for m in (markers or [])]
        self._titles = list(titles)
        self._options = list(available) or list(titles)
        # The kind this new question will settle on decides which of them are on offer, so it is
        # asked before the rows are built rather than after — `_settle_kind` below refills them
        # again from whatever it ends up on.
        self._kind = kind_for(titles, kind)
        self._fill_pickers(titles)
        self._selection = self._from_pickers() if self._pickers else list(titles)
        # Re-read, all three: the window outlives the project, and switching projects switches
        # processors, switches the bank — and switches the car whose glossary names the groups.
        self._apply_delay_resolution()
        self._groups = curve_groups.GlossaryGroups.load()
        if getattr(self, "_group_combo", None) is not None:
            self._clear_group()
            self._fill_group_combo()
            self._fill_choose_menu()
            self._sync_version_combo()
        self._render_bank()
        # The kind combo is not moved here: `_settle_kind` -> `_apply_kind` does it, and a second
        # writer of the same index is exactly how a picker comes to disagree with the `self._kind`
        # the worker is fetching for.
        self._settle_kind(kind)

    def apply_theme(self) -> None:
        """Passed through from the window: a plot does not repaint from a stylesheet."""
        self._view.apply_theme()
        # Nor does a row foreground written as a hex value out of the palette that was current
        # when it was greyed out.
        self._mark_availability()

    def _on_failed(self, message: str) -> None:
        self._status.setVisible(True)
        self._status.setText(i18n.t("curveFailed").format(error=message))

    def _on_send(self, reading: str) -> None:
        if reading:
            self.readingSent.emit(reading)
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Qt aborts the process if a QThread is destroyed while running — the same `qFatal` the
        measurement panel's workers are guarded against."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(4000)
        super().closeEvent(event)
