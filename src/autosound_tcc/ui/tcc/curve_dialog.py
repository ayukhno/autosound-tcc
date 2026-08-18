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

from PySide6.QtCore import QPoint, QRect, QSize, QThread, Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import config, curve_groups, delay_bank
from autosound_tcc.core.rew_bridge import RewBridge
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.curve_view import (
    CurveView,
    Trace,
    tip_html,
    trace_colour,
    trace_token,
)
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


class _FlowLayout(QLayout):
    """A row that wraps: items go left to right and start a new line when they run out of width.

    Here because a selection is as many measurements as the tuner wants — a whole side is four
    drivers and ALL+C is seven — and the alternatives are both wrong for a row that has to be
    READ. A QHBoxLayout squeezes seven chips until their names are ellipses, which is exactly the
    "saying (3) while listing two names" the Advisor refused; a scroll area hides the overflow,
    which is the same refusal wearing a different control.

    Hidden items take no space. That matters because the chips are pooled rather than destroyed
    (`CurveDialog._render_chips`), so the spares live in this layout for the whole session.

    No `__del__`. The Qt for Python example ships one that drains the layout on collection, and in
    this app a destructor running at a moment Python chooses is the exact shape of the segfaults
    `tests/test_curve_view.py` and `qt_shutdown.py` document: nothing here is ever removed anyway,
    so there is no leak to chase.
    """

    def __init__(self, parent: Optional[QWidget] = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    # ---- the five QLayout has to have -----------------------------------

    def addItem(self, item) -> None:  # noqa: N802 (Qt override)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 (Qt override)
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802 (Qt override)
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 (Qt override)
        return Qt.Orientation(0)

    # ---- height for width, which is the whole point ---------------------

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt override)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt override)
        return self._lay_out(QRect(0, 0, width, 0), place=False)

    def setGeometry(self, rect) -> None:  # noqa: N802 (Qt override)
        super().setGeometry(rect)
        self._lay_out(rect, place=True)

    def sizeHint(self):  # noqa: N802 (Qt override)
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802 (Qt override)
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(),
                            margins.top() + margins.bottom())

    def _lay_out(self, rect, place: bool) -> int:
        """Walk the items, wrapping at `rect`'s right edge; answer the height that took."""
        margins = self.contentsMargins()
        left = rect.x() + margins.left()
        right = rect.right() - margins.right()
        x, y, line_height = left, rect.y() + margins.top(), 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            hint = item.sizeHint()
            if x > left and x + hint.width() - 1 > right:
                x = left
                y += line_height + self.spacing()
                line_height = 0
            if place:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line_height = max(line_height, hint.height())
        return y + line_height + margins.bottom() - rect.y()


class _StayOpenMenu(QMenu):
    """A checkable menu that survives a tick.

    Qt closes a menu on every activation, which for a CHECKLIST means one opening per measurement:
    building a six-driver selection by hand was six trips through the same list, and the list is
    long — one sweep and one MMM capture per channel. Ticking a checkable row here toggles it and
    leaves the menu standing; anything that is not a checkable row behaves exactly as before.

    Safe only because the menu is never rebuilt while one of its actions is emitting — see
    `CurveDialog._fill_choose_menu`, which was already written that way and now has to be.
    """

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        action = self.activeAction()
        if action is not None and action.isEnabled() and action.isCheckable():
            action.trigger()
            return
        super().mouseReleaseEvent(event)


class _Chip(QFrame):
    """One chosen measurement, in the colour its curve is drawn in, with the × that takes it off.

    The row of these is the window's ONE visible selection, and it is there because the Advisor
    (Gemini 3.1 Pro, consulted at the user's request 2026-08-18) settled the two-rows-of-controls
    confusion with a rule worth quoting where it decides the design:

        "the tuner must always know exactly which physical measurements are contributing to the
        predicted sum on the screen … Do not hide the active state behind summaries, mode switches,
        or collapsed menus. Saying '(3)' while only listing two names, or tucking active curves
        inside a closed checklist, breaks trust. If a tuner commits a delay change based on a
        plotted sum, they must be 100% certain of what fed that sum."

    So the title is printed WHOLE. The delay radios shorten theirs beyond a pair to fit the row —
    here the row wraps instead (`_FlowLayout`), because a name that has to be decoded is not
    evidence.

    Reused rather than rebuilt: `show_title` re-points an existing chip. The × is clicked ON this
    widget, and destroying a widget from inside its own event handler is how this app has crashed
    before (`curve_view._ensure_target_buttons` keeps the delay radios for the same reason).
    """

    removed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = ""
        self.setProperty("class", "curve-chip")
        row = QHBoxLayout(self)
        row.setContentsMargins(9, 2, 5, 2)
        row.setSpacing(6)
        self._name = QLabel("")
        self._name.setProperty("class", "curve-chip-name")
        row.addWidget(self._name)
        self._x = QPushButton("✕")
        self._x.setProperty("class", "curve-chip-x")
        self._x.setCursor(Qt.CursorShape.PointingHandCursor)
        self._x.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._x.clicked.connect(lambda: self.removed.emit(self._title))
        attach_tip(self._x, "")
        row.addWidget(self._x)

    def title(self) -> str:
        return self._title

    def show_title(self, title: str, colour: QColor, removable: bool, drawn: bool = True) -> None:
        """Point this chip at `title`, wearing `colour`.

        `removable` is False for the last chip standing: a window plotting nothing leaves the
        previous curves on screen with an empty row beside them, which is precisely the picture the
        Advisor's rule forbids. `drawn` is False when REW could not produce this one — then the
        chip is faint and says so, because a chip that looks like the others while its curve is
        absent is the same lie in the other direction.

        The colour goes on as a per-widget stylesheet, not through the class: it is a different
        value per chip, and it has to be re-read on a theme switch — which is why it is written
        from `trace_colour` here and rewritten by `CurveDialog.apply_theme`. The selector keeps
        the sheet off the children (a selector-less one cascades).
        """
        self._title = str(title)
        self._name.setText(self._title)
        self._name.setStyleSheet(f"QLabel {{ color: {colour.name()}; }}")
        self.setStyleSheet(
            f'QFrame[class~="curve-chip"] {{ border-color: {colour.name()}; }}'
        )
        self._x.setEnabled(bool(removable))
        if getattr(self._x, "hover_tip", None) is not None:
            key = (
                "curveChipRemoveTip" if removable and drawn
                else "curveChipMissingTip" if not drawn
                else "curveChipOnlyTip"
            )
            self._x.hover_tip.set_text(tip_html(i18n.t(key).format(title=self._title)))


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
        """`titles` is what to plot. `available` is everything REW holds, for the choose menu and the
        group picker — pass it and the Arbiter can change their mind about which drivers are being
        argued about without closing the window and finding a different button."""
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

        #: Everything REW holds, whatever this kind can draw of it. The choose menu shows a SUBSET —
        #: see `_selectable` — so the full list has to live somewhere that is not a widget.
        self._options = list(available) or list(titles)
        #: The chosen measurements, in the order they will be plotted. THE selection: every control
        #: writes it through `_set_selection` and nothing else is consulted, because two controls
        #: each holding half a selection is how a window comes to draw one thing and report
        #: another — the failure the Advisor named (see `_Chip`).
        self._selection: list[str] = [str(t) for t in titles if t]
        #: What the last fetch actually came back with, in the order it is plotted. Not the same
        #: list as the selection whenever REW refused one of them, and that difference is what the
        #: chips are coloured from — see `_chip_colours`.
        self._plotted: list[str] = []
        #: The group whose members are on screen, and what it could not find. Kept so changing the
        #: version re-resolves the same group rather than clearing it.
        self._group: Optional[curve_groups.Group] = None
        self._group_note = ""
        self._groups = curve_groups.GlossaryGroups.load()
        self._syncing_selection = False
        #: Whether one of the choose menu's own actions is mid-`toggled` — see `_fill_choose_menu`, which
        #: must not destroy an action that is emitting.
        self._in_choose_toggle = False
        #: The chip widgets, grown and never shrunk — see `_render_chips`.
        self._chips: list[_Chip] = []
        self._chip_row: Optional[_FlowLayout] = None

        # The kind is a property of the WINDOW, not of a measurement: two curves in different
        # units on one pair of axes would be a picture of nothing. Switching it re-fetches. It is
        # the one control that did not move when the selection became a chip row, because it
        # answers "what is drawn" and not "which measurements".
        self._kind_combo = QComboBox()
        self._kind_combo.setProperty("class", "mini-select")
        for key in KINDS:
            self._kind_combo.addItem(i18n.t(f"curveKind_{key}"), key)
        self._kind_combo.setCurrentIndex(max(0, self._kind_combo.findData(self._kind)))
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        if self._options:
            layout.addWidget(self._build_chip_row())
            layout.addLayout(self._build_controls_row())
        else:
            layout.addWidget(self._kind_combo)

        self._status = QLabel(i18n.t("curveLoading"))
        self._status.setProperty("class", "phead-sub")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._view = CurveView(x_label=str(KINDS[self._kind]["label_x"]))
        self._view.on_send(self._on_send)
        self._view.delayChanged.connect(self._bank_current_delay)
        self._view.sumToggled.connect(self._on_sum_toggled)
        layout.addWidget(self._view, stretch=1)

        # Everything read so far, and one button that hands the whole set to the model. A delay is
        # only ever relative to the rest of the car, so one pair's number decides nothing — and
        # this window used to drop each one as soon as the next pair loaded (user, 2026-08-12).
        #
        # These do NOT get a row of their own any more. They go into the view's notes row, beside
        # "Σ forecast" and "Reading →" (`CurveView.add_note`), because three buttons of the same
        # kind on three stacked lines cost three rows of a window that has a strip to fit now
        # (user, 2026-08-18: "ось ці кнопки всі стануть в ряд в самому низу, щоб не займати
        # простір").
        #
        # The set behind a button that COUNTS it, not a line of small grey type running the width
        # of the window (user, 2026-08-18). The count is the part worth seeing without hovering:
        # seven readings on a nine-driver car is the fact that decides whether the set is worth
        # sending yet. The list itself is the tip.
        self._bank_btn = QPushButton("")
        self._bank_btn.setProperty("class", "clear-btn")
        self._bank_btn.setCursor(Qt.CursorShape.WhatsThisCursor)
        self._bank_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        attach_tip(self._bank_btn, "")
        self._view.add_note(self._bank_btn)
        # "Clear" is two different things and one button cannot be both: the delays are a set
        # being built up over an afternoon, the markers are one reading being dragged (user,
        # 2026-08-12). They sit at the right-hand end of the same row, past the stretch, so a note
        # appearing on the left never moves them; the ACTIONS go up with the controls.
        clear_label = QLabel(i18n.t("curveClearLabel"))
        clear_label.setProperty("class", "phead-sub")
        self._view.add_note_action(clear_label)
        self._bank_clear_btn = QPushButton(i18n.t("curveClearDelay"))
        self._bank_clear_btn.setProperty("class", "clear-btn")
        self._bank_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bank_clear_btn.clicked.connect(self._on_clear_bank)
        self._view.add_note_action(self._bank_clear_btn)
        self._markers_clear_btn = QPushButton(i18n.t("curveClearMarkers"))
        self._markers_clear_btn.setProperty("class", "clear-btn")
        self._markers_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._markers_clear_btn.clicked.connect(
            lambda: self._view.bring_markers_into_view(force=True)
        )
        self._view.add_note_action(self._markers_clear_btn)

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
        self._on_sum_toggled(self._view.sum_shown())
        self._settle_kind(kind)

    # ---- the ONE visible selection (CURVE-ANALYSIS-PLAN.md step 3, Advisor 2026-08-18) -----

    def _build_chip_row(self) -> QWidget:
        """The selection, as chips. The whole top row, and nothing else on it.

        It replaced two measurement pickers plus a `Choose… (n)` button, which between them gave
        the window two rows that both claimed to say what was plotted and could disagree about it
        ("щось у мене не виходить синхронізувати розуміння ось цих двох груп вибору"). The rule
        that settled it is quoted in `_Chip`, where it decides the design.

        The pickers are GONE rather than kept as a fast path (user, 2026-08-18, after seeing this
        row: "ти здорово придумав з групами, і тоді ось ці вибори не потрібні … весь вибір робимо
        або групами, або галочками в меню Обрати"). Their reason is the Advisor's: a second way of
        saying the same thing is what made the window confusing to start with. The one thing they
        did that is still needed — refusing an MMM capture on the impulse and the phase — moved to
        `_selectable`, which the choose menu is built from.

        Chips ALONE up here, with every control on the row below: the chips are the answer and
        that row is the question (user, 2026-08-18: "хай 'Обрати' буде основним, а групи це
        допомога швидкого вибору").

        A wrapping row (`_FlowLayout`) and not a squeezing one: seven chips must stay readable, and
        a name shortened to an ellipsis is not the evidence this row exists to be.
        """
        self._chip_holder = QWidget()
        # Without this the wrapping is computed and then ignored: a QWidgetItem only asks its
        # widget for a height-for-width when the widget's own size policy says it has one.
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self._chip_holder.setSizePolicy(policy)
        self._chip_row = _FlowLayout(self._chip_holder, spacing=6)
        self._render_chips()
        return self._chip_holder

    def _render_chips(self) -> None:
        """Draw the selection as chips, in the order the curves are plotted, each in its colour.

        Grown and never shrunk, and the spares are HIDDEN rather than deleted — the same rule
        `curve_view._ensure_target_buttons` follows for the delay radios, and for the same reason:
        the × is clicked ON a chip, and destroying a widget from inside its own event handler is
        how this app has crashed before. A hidden chip takes no width in the flow, so the row is
        the same picture either way.
        """
        if self._chip_row is None:
            return
        chosen = self._chosen()
        colours = self._chip_colours(chosen)
        while len(self._chips) < len(chosen):
            chip = _Chip(self._chip_holder)
            chip.removed.connect(self._on_chip_removed)
            self._chip_row.addWidget(chip)
            self._chips.append(chip)
        for index, chip in enumerate(self._chips):
            if index >= len(chosen):
                chip.setVisible(False)
                continue
            title = chosen[index]
            chip.show_title(
                title, colours[index],
                # The last one standing cannot be removed: `_reload` has nothing to fetch for an
                # empty selection, so the previous curves would stay on the plot beside an empty
                # row — a window drawing one thing while its selection says another, which is the
                # exact failure this row exists to prevent.
                removable=len(chosen) > 1,
                drawn=not self._plotted or title in self._plotted,
            )
            chip.setVisible(True)
        self._chip_row.invalidate()

    def _chip_colours(self, chosen: Sequence[str]) -> list[QColor]:
        """One colour per chip: the pen the curve of that title is actually drawn with.

        Position in the selection is the answer while a fetch is in flight, and it is the rule the
        plot itself follows — trace N takes colour N. It stops being the answer when REW refuses
        one of them: `_CurveWorker` drops that title and keeps the rest (per measurement, so one
        failure does not clear the screen), and every trace after the gap moves up a colour. A row
        coloured by position would then name the wrong driver for the whole tail of the selection,
        in the one situation where the tuner most needs to know what fed the sum.

        `_plotted` is what came back, and it is cleared the moment the selection changes, so it can
        never colour this row with the previous question's answer.
        """
        if not self._plotted:
            return [trace_colour(index) for index in range(len(chosen))]
        faint = QColor(current_theme().faint)
        return [
            trace_colour(self._plotted.index(title)) if title in self._plotted else faint
            for title in chosen
        ]

    def _on_chip_removed(self, title: str) -> None:
        """A × takes one driver out of the selection and leaves everything else exactly as it is.

        This is the Advisor's own workflow, and the reason the group picker had to stop owning the
        selection: "load a 'group' macro, look at the sum, and instantly isolate a problem by
        removing one driver (clicking × on a chip) to see how its absence affects the joint." So
        nothing here re-fills from the group and nothing resets — one name goes, and the sum is
        recomputed over what is left.
        """
        rest = [t for t in self._chosen() if t != title]
        if not rest:
            # Belt to the brace: the last chip's × is disabled, and this is what makes the rule
            # true even if some later caller reaches the signal another way.
            return
        self._clear_group()
        self._set_selection(rest)

    # ---- filling the selection from a group (CURVE-ANALYSIS-PLAN.md, step 3) -----

    def _build_controls_row(self) -> QHBoxLayout:
        """The row under the chips: how any selection is made, how one is filled fast, what is drawn.

        Order settled by the user (2026-08-18): "хай 'Обрати' буде основним, а групи це допомога
        швидкого вибору (поміняти їх місцями і все ок)". So `Choose…` comes first and gets the
        room — it is where ANY set can be made, one tick at a time — and the group + version pair
        follows it as the shortcut it is, labelled `fill:` rather than named as a second selector.

        The kind picker is at the far end, past the stretch. It moved down from the top row (user:
        "перенеси кнопку вибору режиму на рядок нижче") because it never chose measurements and
        standing alone above the window it read as though it did. Past the stretch rather than
        packed with the rest so that it does not slide sideways when the group pair comes and goes
        with the Σ toggle — and `Choose…`, being first, never moves at all.
        """
        row = QHBoxLayout()
        row.setSpacing(8)

        # Every measurement this kind can draw, ticked when it is in the selection. THE selector:
        # the count stays on it, unlike the version that stood over two pickers, because the chips
        # directly above now list every name it is counting. The Advisor's objection was to a
        # control "saying '(3)' while only listing two names" — a count under the full list is a
        # summary, not a substitute.
        self._choose_btn = QPushButton("")
        # `.zoom-btn` and not `.mini-select`: every `.mini-select` rule is written `QComboBox[...]`
        # and would not reach a QPushButton at all (the delay spin box learned this the hard way,
        # 2026-08-18). The two classes share their background, border, radius and font size, so a
        # button wearing this one sits in a row of combos without looking like a visitor.
        self._choose_btn.setProperty("class", "zoom-btn")
        self._choose_btn.setMinimumWidth(168)
        self._choose_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        attach_tip(self._choose_btn, tip_html(i18n.t("curveChooseTip")))
        self._choose_menu = _StayOpenMenu(self)
        self._choose_actions: dict[str, QAction] = {}
        self._choose_btn.setMenu(self._choose_menu)
        row.addWidget(self._choose_btn)
        self._fill_choose_menu()

        row.addWidget(self._build_group_box())
        row.addStretch(1)
        row.addWidget(self._kind_combo)
        return row

    def _build_group_box(self) -> QWidget:
        """The FILL tools: which group, at which config version. One widget, so it can be hidden.

        Two controls and not one, because they answer different questions and the second is the
        one that goes wrong quietly: `Ws` says which drivers, `_02` says which round of the car.
        A group resolved at the wrong version is a set of measurements taken under a DSP
        configuration nobody is looking at, and `curve_sum` would happily add them up and label it
        "two different cars" — a label nobody asked for.

        Its own QWidget rather than a bare layout because it comes and goes with the Σ toggle
        (`_on_sum_toggled`), and a hidden widget takes its spacing with it while a layout full of
        hidden widgets leaves a gap behind.
        """
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
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
        row.addStretch(1)
        self._sync_version_combo()
        self._group_box = box
        return box

    def _on_sum_toggled(self, on: bool) -> None:
        """Offer the group and version pickers only while a sum is on screen.

        User, 2026-08-18, with the screenshot: "поки я не включив суму немає сенсу показувати ось
        ці групи". Groups exist to build a sum — a group IS "these drivers, added up" — so with Σ
        off they are two combos answering a question nobody asked.

        Hidden NARROWLY, and this is the part that had to be got right. The chips and "+ add ▾"
        never hide: they are the selection, the Advisor's rule is that the selection is always
        visible, and with the measurement pickers gone they are the only way to change what is
        drawn — a window that hid them with Σ off would be a window you cannot use without the sum.
        The kind picker shares the row with the group combos and stays for the same reason, which
        is also why the row keeps its height and the plot below does not jump when Σ is toggled.

        Nothing is lost when the combos go away: every path that edits the chips has already let
        go of the group by then (`_clear_group`), and hiding a combo changes no selection.
        """
        box = getattr(self, "_group_box", None)
        if box is not None:
            box.setVisible(bool(on))

    def _fill_group_combo(self) -> None:
        """Every group this car has, with its TYPE on the row.

        `Ws` is a pair and `L` is a side, and a list of bare names does not say which — so the kind
        is printed beside each. With no glossary (no 3.x project, or no skill) the combo says so
        and stays disabled: the chips and the choose menu are unaffected, which is the point of the
        group being a FILL tool rather than the way a selection is made.
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
        capture is absent on the impulse and the phase — `_selectable`), and a menu half-rebuilt is
        a menu that can tick a measurement the window will not fetch.

        Never rebuilt while one of its own actions is emitting `toggled`. `clear()` DESTROYS the
        actions, and destroying the object a signal is being delivered from is this app's oldest
        way of ending a process (the same rule as deleting a widget inside its own event handler).
        It matters more now than when it was written: the menu STAYS OPEN across a tick
        (`_StayOpenMenu`), so the action that emitted is still on screen and still being pointed at.
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
        # The rows are new objects, so the delays `_render_bank` wrote beside the titles went with
        # the old ones. Guarded because this menu is built before the bank's own widgets are.
        if getattr(self, "_bank_btn", None) is not None:
            self._render_bank()

    def _sync_choose_ticks(self) -> None:
        """Tick the rows the window is plotting, and count them on the button.

        Signals blocked: `setChecked` emits `toggled`, and a tick set BY the selection arriving
        back at the handler that changes the selection is a loop with no bottom.

        The count is honest now in a way it was not before: the chips directly above name every
        one of them, so it summarises a list the tuner can see rather than standing in for one.
        """
        chosen = set(self._chosen())
        for title, action in self._choose_actions.items():
            blocked = action.blockSignals(True)
            action.setChecked(title in chosen)
            action.blockSignals(blocked)
        self._choose_btn.setText(i18n.t("curveChooseBtn").format(n=len(chosen)))

    def _selectable(self) -> list[str]:
        """What may be plotted on THIS kind.

        An MMM/RTA capture is ABSENT here on the impulse and the phase, not greyed (user,
        2026-08-18, overruling this window's habit for this one list). The reasoning is the
        window's own invariant: `kind_for` moves the window to the magnitude the moment an MMM
        capture is chosen, so while the kind is impulse or phase no MMM row can ever BE a chosen
        one. A row that can never be chosen is not a marked choice, it is noise — and these lists
        are long, one sweep and one MMM capture per channel. The KIND picker keeps its grey-out,
        because there the marked row is a choice somebody just asked for out loud.
        """
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
            # which beats an empty plot, and the status line says where it looked.
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

        Unticking the LAST one is refused, the same rule the last chip's × follows: with nothing
        selected `_reload` has nothing to fetch and the previous curves stay on the plot, which
        would leave the window drawing one thing while its selection says another. The tick goes
        back on rather than the window arguing about it.
        """
        if self._syncing_selection:
            return
        chosen = [
            row for row in self._selectable()
            if (row == title and on) or (row != title and row in self._chosen())
        ]
        self._in_choose_toggle = True
        try:
            if not chosen:
                self._sync_choose_ticks()
                return
            self._clear_group()
            self._set_selection(chosen)
        finally:
            self._in_choose_toggle = False

    def _clear_group(self) -> None:
        """Let go of the group, and say so on the picker that names it.

        Back to "— no group —", and that is the honest reading rather than a fallback: the group
        combo names what FILLED the chips, and once a chip has been taken out by hand the chips are
        no longer that group. Leaving `Ws` standing there would be the window claiming a set it is
        not drawing — and re-filling instead would destroy the Advisor's own workflow, which is to
        remove one driver and look at what the joint does without it.
        """
        self._group = None
        self._group_note = ""
        combo = getattr(self, "_group_combo", None)
        if combo is not None and combo.currentIndex() != 0:
            blocked = combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(blocked)

    def _set_selection(self, titles: Sequence[str]) -> None:
        """Make `titles` what the window is plotting, and put every control in step with it.

        The ONE writer of `_selection`, and everything else asks `_chosen()`. The chips name it,
        the choose menu ticks it, the version combo follows it — three renderings of one list, which
        is the whole point: two controls each holding half a selection is how a window comes to
        draw one thing and report another.

        Guarded against re-entry because putting a control in step emits the same signal that
        arrives when the tuner moves it by hand.
        """
        self._selection = [str(t) for t in titles if t]
        # What is on the plot is about the PREVIOUS selection until the fetch answers, so it stops
        # being allowed to colour the chips the moment this changes (see `_chip_colours`).
        self._plotted = []
        if getattr(self, "_version_combo", None) is None:
            # No chip row means no group row either (both are built only when there is a list of
            # measurements to offer), and then there is nothing to keep in step.
            self._settle_kind(self._kind)
            return
        self._syncing_selection = True
        try:
            self._render_chips()
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
        choose menu.

        In the choose menu because that is where the Arbiter is choosing what to look at next: seeing
        that w-L already carries +0.198 ms is what stops the same channel being read twice against
        two different partners and banked twice with different answers. It used to be on the picker
        rows, which is the same place by another name.
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
        for title, action in getattr(self, "_choose_actions", {}).items():
            ms = bank.get(title)
            action.setText(f"{title}  ·  {ms:+.3f} ms" if ms else title)

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

        Same KIND, by the capture-method suffix the titles carry: REW holds both the sweep and the
        RTA of every channel, and listing an RTA capture as an unplaced driver would be noise about
        a measurement that has no arrival at all. Whatever suffix the seen ones share is the family
        under discussion.

        A driver left at zero is NOT here — it is the reference, and it has an entry.

        Read off everything REW holds, not off the choose menu's rows: that menu shows only what the
        current kind can draw (`_selectable`), and which measurements exist is a fact about the
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

    def _settle_kind(self, asked: str) -> None:
        """Put the window on the kind this selection can answer, then fetch.

        `kind_for` has the last word, not the picker: an MMM capture in the selection carries
        neither an impulse nor a phase, so the window stays on the magnitude — and SAYS which
        measurement is the reason. Quietly fetching the sweeps alone was the other option and it is
        worse: that is the window deciding which of the chosen curves the Arbiter meant.
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

    def _mark_availability(self) -> None:
        """Grey out what cannot be shown in the KIND picker, and drop what cannot be drawn from
        the choose menu.

        Two different answers to the same question, on purpose. A kind is marked and left on
        screen, which is this app's habit for a choice that exists and does not apply here
        (`main_window._fill_combo` keeps an unavailable model visible and marked): it was asked
        for out loud and it is owed a reason. A measurement that cannot be drawn in this mode is
        not a refused request, it is one row of a long list that this kind has nothing to do with
        — see `_selectable`.

        Both directions, because the mixed selection can be built from either end — an MMM capture
        ticked while the impulse is up, or the impulse asked for while one is already plotted.

        No text badge on the rows. A measurement's title already ends in `(rta)` and the kind rows
        are already named after their kind, so a badge would restate the row instead of adding a
        fact — which is why the model picker's own badges were taken off (user, 2026-08-12).
        """
        faint = QColor(current_theme().faint)
        self._fill_choose_menu()
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

    def _chosen(self) -> list[str]:
        """What the window is plotting — the ONE answer, whoever set it last.

        The chips, the choose menu and the group picker all write `_selection`, all of them through
        `_set_selection`, and everything downstream reads this: the worker, the delay bank, the
        markers, `statement()`. Two controls each holding part of the truth is how a window comes
        to draw one set of curves and report another — which is the failure the Advisor's rule is
        about, and the reason `tests/test_curve_view.py` has a test that fails if a second writer
        ever appears.

        Falls back to the titles the window was opened on when the selection is empty. That can
        only happen before the first `_set_selection`: the last chip's × is disabled and the last
        tick cannot be taken off, precisely so a window is never drawing curves its selection does
        not name.
        """
        return [t for t in self._selection if t] or list(self._titles)

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
        # What came back, in the order it is drawn — and the chips are re-coloured off it, because
        # a title REW could not produce is missing from here while its chip is still on the row,
        # and from that point the two lists no longer agree about which colour belongs to whom.
        self._plotted = [str(trace.name) for trace in traces]
        self._render_chips()

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
        # The kind this new question will settle on decides which measurements are on offer, so it
        # is asked before the rows are rebuilt rather than after — `_settle_kind` below refills
        # them again from whatever it ends up on.
        self._kind = kind_for(titles, kind)
        # Straight from the caller, and NOT through `_set_selection`: that one fetches, and the
        # rest of this method is still re-reading the project the new titles belong to. What is on
        # the plot belongs to the previous question, so it stops colouring the chips here.
        self._selection = [str(t) for t in titles if t]
        self._plotted = []
        # Re-read, all three: the window outlives the project, and switching projects switches
        # processors, switches the bank — and switches the car whose glossary names the groups.
        self._apply_delay_resolution()
        self._groups = curve_groups.GlossaryGroups.load()
        if getattr(self, "_group_combo", None) is not None:
            self._clear_group()
            self._fill_group_combo()
            self._fill_choose_menu()
            self._render_chips()
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
        # Nor a chip, for exactly the same reason: its colour is the colour of a PEN, written per
        # widget from `trace_colour`, and the palette it was resolved against has just changed.
        self._render_chips()

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
