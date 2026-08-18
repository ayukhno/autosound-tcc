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
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from autosound_tcc.core import config, delay_bank
from autosound_tcc.core.rew_bridge import RewBridge
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.curve_view import _TRACE_TOKENS, CurveView, Trace
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
    """Fetch each named measurement's curve. One `by_name` + one curve call per title."""

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
                    # No magnitude and no phase on this one: an impulse IS the time domain, and
                    # there is nothing here to carry into a frequency-domain sum.
                    traces.append(Trace(title, x, np.asarray(samples, dtype=float), **facts))
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
        """`titles` is what to plot. `available` is everything REW holds, for the two pickers —
        pass it and the Arbiter can change their mind about which pair is being argued about
        without closing the window and finding a different button."""
        super().__init__(parent)
        self.setWindowTitle(i18n.t("curveTitle"))
        self.resize(880, 560)
        self._kind = kind_for(titles, kind)
        self._markers = list(markers)
        self._bridge = bridge or RewBridge()
        self._worker: Optional[_CurveWorker] = None
        #: Why what is on screen is not what was asked for, in words. Empty when nothing was
        #: refused — the status line is then free to disappear, as it did before.
        self._note = ""
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

        # Two pickers, because a disagreement is nearly always about a pair. The second may be
        # empty: one curve is a legitimate thing to argue about too.
        self._pickers: list[QComboBox] = []
        options = list(available) or list(titles)
        if options:
            picker_row = QHBoxLayout()
            picker_row.setSpacing(8)
            for index in range(2):
                combo = QComboBox()
                combo.setProperty("class", "mini-select")
                if index:
                    combo.addItem(i18n.t("curveNoSecond"), "")
                for title in options:
                    combo.addItem(title, title)
                wanted = titles[index] if index < len(titles) else ""
                at = combo.findData(wanted)
                combo.setCurrentIndex(at if at >= 0 else 0)
                combo.currentIndexChanged.connect(self._on_selection_changed)
                picker_row.addWidget(combo, 1)
                self._pickers.append(combo)
            layout.addLayout(picker_row)

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
        self._bank_label = QLabel("")
        self._bank_label.setProperty("class", "phead-sub")
        self._bank_label.setWordWrap(True)
        bank_row.addWidget(self._bank_label, stretch=1)
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
        self._settle_kind(kind)

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
        """What each of the two channels is set to now — both, because both may carry a proposal
        and the reading states a total for each."""
        for index, trace in enumerate(self._view._traces[:2]):
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
        for index, trace in enumerate(self._view._traces[:2]):
            # Both, every time. Each driver carries its own delay now, so there is nothing to move
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
        """The banked set under the plot, and the same numbers beside the titles in the pickers.

        In the pickers because that is where the Arbiter is choosing the next pair: seeing that
        w-L already carries +0.198 ms is what stops the same channel being read twice against two
        different partners and banked twice with different answers.
        """
        bank = delay_bank.load(session=self._session())
        if bank:
            shown = ", ".join(f"{title} {ms:+.3f}" for title, ms in sorted(bank.items()))
            series = self._session()
            head = i18n.t("curveBankLabel")
            if series:
                # Named, because the same channel can carry a different correction in another
                # series and a list with no series on it says which one is being looked at.
                head = i18n.t("curveBankLabelIn").format(set=series)
            self._bank_label.setText(f"{head} {shown}")
        else:
            self._bank_label.setText(i18n.t("curveBankEmpty"))
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
        """
        if not seen:
            return []
        suffixes = {t.partition(" ")[2] for t in seen}
        options = [str(c.itemData(row) or "") for c in self._pickers[:1]
                   for row in range(c.count())]
        return [
            title for title in options
            if title and title not in seen and title.partition(" ")[2] in suffixes
        ]

    def _on_clear_bank(self) -> None:
        """Forget this series' readings, and put the curves on screen back where they were drawn.

        Guarded and in this order for a reason. Clearing the store first and zeroing the plot
        afterwards wrote the pair straight back in: zeroing emits `delayChanged`, the handler
        banks BOTH curves on screen, and the one that was not selected still held its delay. The
        user pressed Clear and watched a single value survive — the other curve's (2026-08-12).
        """
        self._restoring = True
        try:
            target = self._view.delay_target()
            for index in range(len(self._view._traces[:2])):
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
        an MMM capture takes the impulse and the phase away with it."""
        self._settle_kind(self._kind)

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
        self._note = (
            "" if self._kind == asked else i18n.t("curveRtaOnly").format(titles=", ".join(rta))
        )
        self._apply_kind()
        self._reload()

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
        """Grey out what cannot be shown — in the measurement pickers and in the kind picker both.

        Marked and left on screen rather than dropped, which is this app's habit for a choice that
        exists and does not apply here (`main_window._fill_combo` keeps an unavailable model
        visible and marked): a measurement REW holds and cannot draw in this mode is a different
        thing from one that is not there at all, and a list that silently shortens itself when the
        kind changes is a list nobody can read as the whole list.

        Both directions, because the mixed pair can be built from either end — an MMM capture
        chosen while the impulse is up, or the impulse asked for while one is already plotted.

        No text badge on the rows. A measurement's title already ends in `(rta)` and the kind rows
        are already named after their kind, so a badge would restate the row instead of adding a
        fact — which is why the model picker's own badges were taken off (user, 2026-08-12).
        """
        faint = QColor(current_theme().faint)
        # A magnitude is the one thing every capture holds, so on `fr` nothing is shut.
        rta_shut = self._kind != "fr"
        for combo in self._pickers:
            for row in range(combo.count()):
                title = str(combo.itemData(row) or "")
                self._mark_row(
                    combo, row, rta_shut and _is_rta(title), i18n.t("curveRtaTip"), faint
                )
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
        if not self._pickers:
            return list(self._titles)
        return [str(c.currentData() or "") for c in self._pickers if c.currentData()]

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
        # The status line ends up carrying the refusal note, if there is one, and disappears when
        # there is not. It is written HERE rather than where the note is decided because `_reload`
        # puts "Reading the curves from REW…" over whatever was there.
        self._status.setText(self._note)
        self._status.setVisible(bool(self._note))
        self._view.set_traces(traces)
        # A pair already argued about comes back with its answer on it. `set_traces` clears the
        # delay by design (a new pair is a new question); the bank is what makes coming BACK to a
        # pair different from meeting it for the first time.
        bank = delay_bank.load(session=self._session())
        # Restoring, not reading: `_bank_current_delay` must not see these calls, or the zeros
        # they pass through on the way would erase what they are restoring.
        self._restoring = True
        try:
            target = self._view.delay_target()
            for index, trace in enumerate(traces[:2]):
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

        Without one (the Arbiter opened this themselves), on each trace's own largest peak. For an
        impulse that is the arrival by the crudest possible reading, which makes the delta
        meaningful before anything has been touched — and a starting point that is obviously a
        guess invites correction better than two markers parked at zero.
        """
        if self._markers:
            positions = list(self._markers)
            names = [i18n.t("curveMarkerModel"), i18n.t("curveMarkerYou")]
            if len(positions) == 1:
                positions.append(positions[0])
            return positions[:2], names[:len(positions[:2])], []
        usable = [t for t in traces[:2] if len(t.x)]
        # One marker per curve, each in its curve's own colour: nobody has claimed a reading yet,
        # so calling the first one "the model's" would be a lie the colour tells.
        return ([_peak_x(t) for t in usable], [t.name for t in usable],
                list(_TRACE_TOKENS[:len(usable)]))

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
        options = list(available) or list(titles)
        for index, combo in enumerate(self._pickers):
            blocked = combo.blockSignals(True)
            combo.clear()
            if index:
                combo.addItem(i18n.t("curveNoSecond"), "")
            for title in options:
                combo.addItem(title, title)
            wanted = titles[index] if index < len(titles) else ""
            at = combo.findData(wanted)
            combo.setCurrentIndex(at if at >= 0 else 0)
            combo.blockSignals(blocked)
        # Re-read: the window outlives the project, and switching projects switches processors —
        # and switching projects switches the bank with it.
        self._apply_delay_resolution()
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
