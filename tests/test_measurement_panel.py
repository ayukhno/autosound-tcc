"""Headless tests for the measurement panel's Read button (item 1, 2026-07-27) — the REW HTTP
calls themselves are never exercised here (that needs a live REW instance); these fake the
`RewBridge` surface and drive the worker/handlers directly and synchronously instead of racing a
real QThread."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from autosound_tcc.ui.tcc import i18n  # noqa: E402
from autosound_tcc.ui.tcc.channel_order_dialog import ChannelOrderDialog  # noqa: E402
from autosound_tcc.ui.tcc.mock_data import MEAS_SESSIONS  # noqa: E402
from autosound_tcc.state import measurement_view  # noqa: E402
from autosound_tcc.core import capture_import  # noqa: E402
from autosound_tcc.ui.tcc.measurement_panel import (  # noqa: E402
    MeasurementPanel,
    with_method,
    _RewRenameWorker,
    _RewScanWorker,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _FakeBridge:
    def __init__(
        self,
        measurements: dict,
        curve=None,
        raises: Exception | None = None,
        rename_fails_at: int | None = None,
    ) -> None:
        self._measurements = measurements
        self._curve = curve or ([1.0, 2.0, 3.0], [0.0, 0.0, 0.0], None)
        self._raises = raises
        self._rename_fails_at = rename_fails_at
        self.renamed: list[tuple[str, str]] = []

    def measurements(self) -> dict:
        if self._raises:
            raise self._raises
        return self._measurements

    def frequency_response(self, mid):
        return self._curve

    def rename_measurement(self, mid, title):
        if self._rename_fails_at is not None and len(self.renamed) == self._rename_fails_at:
            raise RuntimeError("REW rejected the rename")
        self.renamed.append((mid, title))


def test_the_worker_asks_rew_once_and_hands_back_the_whole_answer():
    """One HTTP call, not one per measurement — and the whole record per measurement, because the
    import dialog needs the uuid and the date, not just the title."""
    _app()
    answer = {"1": {"title": "m-L_10 (sw)", "uuid": "a", "date": "2026-Aug-25 20:11:31"},
              "15": {"title": "sub_10 (sw)", "uuid": "b", "date": "2026-Aug-25 20:12:31"}}
    worker = _RewScanWorker(_FakeBridge(answer))
    results = []
    worker.done.connect(lambda r: results.append(r))

    worker.run()  # call synchronously -- no real thread, no race

    assert results == [answer]


def test_the_worker_reports_a_dead_rew_rather_than_raising_on_a_thread():
    _app()
    worker = _RewScanWorker(_FakeBridge({}, raises=ConnectionRefusedError("no REW")))
    errors = []
    worker.failed.connect(lambda msg: errors.append(msg))

    worker.run()

    assert len(errors) == 1 and "ConnectionRefusedError" in errors[0]


def test_read_offers_the_list_instead_of_folding_it_into_the_card(tmp_path, monkeypatch):
    """The change this whole step is: ⤓ used to fold every title REW held into the grid. On the
    run that produced the redesign that was 102 titles — 16 expected, 86 appended as "additional"
    rows, a card 1864 px tall inside a card called "IN FOCUS NOW" (user, 2026-09-02)."""
    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc import measurement_panel as mp

    _app()
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)
    before = len(panel._rows)
    opened = {}

    class _Dialog:
        def __init__(self, measurements, **kwargs):
            opened["measurements"] = measurements
            opened["kwargs"] = kwargs

        def exec(self):
            return QDialog.DialogCode.Accepted

        def taken(self):
            return []

        def renames(self):
            return []

    monkeypatch.setattr(mp, "CaptureImportDialog", _Dialog)
    panel._on_import_offer({"1": {"title": "somebody-elses_99 (sw)", "uuid": "z",
                                  "date": "2026-Aug-25 20:11:31"}})

    assert len(panel._rows) == before, "nothing enters the card without a tick"
    assert opened["measurements"], "and the tuner is shown what REW answered"
    assert i18n.t("capImportDone").format(n=0) in panel._status_label.text()


def test_the_dialog_is_told_what_the_round_is_waiting_for(tmp_path, monkeypatch):
    """"As many as we expect" is the round's own count, not a number somebody guessed."""
    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc import measurement_panel as mp

    _app()
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)
    seen = {}

    class _Dialog:
        def __init__(self, measurements, **kwargs):
            seen.update(kwargs)

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(mp, "CaptureImportDialog", _Dialog)
    panel._on_import_offer({"1": {"title": "x", "uuid": "z", "date": ""}})

    assert seen["waiting"] == sum(1 for row in panel._rows if row.status == "wait")
    assert seen["has_task"] is True


def test_a_rew_holding_nothing_is_said_rather_than_shown_as_an_empty_table():
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)

    panel._on_import_offer({})

    assert i18n.t("measReadNoMeas") in panel._status_label.text()
    assert panel._read_btn.isEnabled()


def test_what_the_project_took_in_is_known_even_with_rew_closed(tmp_path, monkeypatch):
    """The half that survives. "Captured" used to mean "REW is showing a title like that RIGHT
    NOW", so the checklist emptied itself when REW was shut — or filtered, which is worse, because
    a filter is invisible from here."""
    from autosound_tcc.core import config

    _app()
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    rows = capture_import.candidates(
        {"1": {"title": "w-L_02 (sw)", "uuid": "u1", "date": "2026-Aug-25 20:11:31"}}, tmp_path)
    capture_import.record_imported(rows, project_dir=tmp_path)

    panel = MeasurementPanel()  # a fresh panel, nothing read this session

    assert panel.known_titles() == ["w-L_02 (sw)"]


def test_read_failed_shows_error_and_reenables_button():
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    panel._read_btn.setEnabled(False)
    panel._on_read_failed("boom")
    assert panel._read_btn.isEnabled()
    assert "boom" in panel._status_label.text()


def test_row_shows_full_name_with_method_suffix():
    """User request 2026-07-28: the row label previews the REAL name a capture gets in REW --
    "<id> (<method>)" -- not just the bare channel id."""
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    row = next(r for r in panel._rows if r.item_name == "sw_10" and r.method_suffix == "sw")
    assert row._name_label.text() == "sw_10 (sw) · 2"  # the mock's own capture count, unrelated
    group_row = next(r for r in panel._rows if r.item_name == "SW+Ws_10")
    assert group_row.method_suffix == "rta"  # RTA-GROUP is still "(rta)", not a third suffix


def test_channel_order_dialog_defaults_to_first_available_method():
    _app()
    dialog = ChannelOrderDialog({"sw": [("A", "A · Front L"), ("B", "B · Front R")]})
    assert dialog.get_method() == "sw"
    assert dialog.get_order() == ["A", "B"]


def test_channel_order_dialog_switches_method_and_preserves_each_lists_order():
    _app()
    dialog = ChannelOrderDialog({"sw": [("A", "A"), ("B", "B")], "rta": [("C", "C"), ("D", "D")]})
    assert dialog.get_order() == ["A", "B"]

    from PySide6.QtWidgets import QPushButton

    rta_btn = next(b for b in dialog.findChildren(QPushButton) if b.text() == "RTA")
    rta_btn.click()
    assert dialog.get_method() == "rta"
    assert dialog.get_order() == ["C", "D"]

    sw_btn = next(b for b in dialog.findChildren(QPushButton) if b.text() == "SW")
    sw_btn.click()
    assert dialog.get_method() == "sw"
    assert dialog.get_order() == ["A", "B"]  # switching away and back didn't lose the sw list


def test_channel_order_dialog_omits_button_for_missing_method():
    _app()
    dialog = ChannelOrderDialog({"sw": [("A", "A")]})
    from PySide6.QtWidgets import QPushButton

    labels = {b.text() for b in dialog.findChildren(QPushButton)}
    assert "RTA" not in labels and "RTA GROUP" not in labels


def test_channel_order_dialog_no_methods_has_no_order():
    _app()
    dialog = ChannelOrderDialog({})
    assert dialog.get_method() is None
    assert dialog.get_order() == []


def test_scan_worker_emits_measurements_dict():
    _app()
    measurements = {"1": {}, "2": {}, "3": {}}
    worker = _RewScanWorker(_FakeBridge(measurements))
    results = []
    worker.done.connect(lambda m: results.append(m))
    worker.run()
    assert results == [measurements]


def test_scan_worker_emits_failed_on_exception():
    _app()
    worker = _RewScanWorker(_FakeBridge({}, raises=ConnectionRefusedError("no REW")))
    errors = []
    worker.failed.connect(lambda msg: errors.append(msg))
    worker.run()
    assert len(errors) == 1


def test_the_rename_worker_addresses_measurements_by_uuid_not_by_position():
    """The measurement of 2026-09-02: the user swapped two rows in REW by hand and the API returned
    the same measurements with those two ordinals exchanged — every uuid, title and date unchanged.
    A pair built when the table was drawn would rename the wrong graph, which is the exact failure
    the method's identity hygiene is written against."""
    _app()
    # REW's answer AFTER the swap: u_late is now ordinal 1, u_early is 2.
    bridge = _FakeBridge({"1": {"title": "m-L_49rep (sw)", "uuid": "u_late"},
                          "2": {"title": "r-R_49 (sw)", "uuid": "u_early"}})
    worker = _RewRenameWorker(bridge, [("u_early", "w-L_02 (sw)")])
    results = []
    worker.done.connect(lambda r: results.append(r))

    worker.run()

    assert bridge.renamed == [("2", "w-L_02 (sw)")], "the ordinal is looked up now, not remembered"
    assert results == [[("u_early", "w-L_02 (sw)")]]


def test_a_measurement_that_vanished_between_the_list_and_apply_stops_the_batch():
    """Deleted, or hidden by a filter switched on since the table was drawn. Either way there is
    nothing to rename, and guessing one by position is how `m-R` data ends up labelled `m-L`."""
    _app()
    bridge = _FakeBridge({"1": {"title": "still here", "uuid": "u1"}})
    worker = _RewRenameWorker(bridge, [("u1", "w-L_02 (sw)"), ("gone", "w-R_02 (sw)")])
    failures = []
    worker.failed.connect(lambda msg, renamed: failures.append((msg, renamed)))

    worker.run()

    message, renamed = failures[0]
    assert "w-R_02 (sw)" in message
    assert renamed == [("u1", "w-L_02 (sw)")], "and what did go through is reported as gone through"


def test_the_rename_worker_stops_at_the_first_refusal_and_says_how_far_it_got():
    _app()
    bridge = _FakeBridge({"1": {"title": "a", "uuid": "u1"}, "2": {"title": "b", "uuid": "u2"},
                          "3": {"title": "c", "uuid": "u3"}}, rename_fails_at=1)
    worker = _RewRenameWorker(bridge, [("u1", "w-L"), ("u2", "w-R"), ("u3", "tw-L")])
    failures = []
    worker.failed.connect(lambda msg, renamed: failures.append((msg, renamed)))

    worker.run()

    message, renamed = failures[0]
    assert "REW rejected the rename" in message
    assert renamed == [("u1", "w-L")], "before the failing second call, and no further"


def test_only_what_carries_its_new_name_is_written_down(tmp_path, monkeypatch):
    """A measurement whose rename never happened is still called what it was called. Recording it
    under a name it does not have would put a title in the checklist that nothing in REW answers
    to; left out, it comes back on the next press, untouched and still unprocessed."""
    from autosound_tcc.core import capture_import, config

    _app()
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)
    answer = {"1": {"title": "Measurement 1", "uuid": "u1", "date": "2026-Aug-25 20:10:00"},
              "2": {"title": "Measurement 2", "uuid": "u2", "date": "2026-Aug-25 20:10:10"},
              "3": {"title": "Measurement 3", "uuid": "u3", "date": "2026-Aug-25 20:10:20"}}
    panel._taking = capture_import.candidates(answer, tmp_path)
    panel._renaming = [("u1", "w-L_02 (sw)"), ("u2", "w-R_02 (sw)")]

    panel._on_import_rename_failed("REW rejected the rename", [("u1", "w-L_02 (sw)")])

    stored = capture_import.load_imported(tmp_path)
    assert set(stored) == {"u1", "u3"}, "u2 was asked for and did not get it: it comes back"
    assert stored["u1"]["title"] == "w-L_02 (sw)"
    assert stored["u3"]["title"] == "Measurement 3", "nobody asked to rename that one"


def test_a_batch_that_went_through_is_written_down_under_its_new_names(tmp_path, monkeypatch):
    from autosound_tcc.core import capture_import, config

    _app()
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)
    answer = {"1": {"title": "Measurement 1", "uuid": "u1", "date": "2026-Aug-25 20:10:00"}}
    panel._taking = capture_import.candidates(answer, tmp_path)
    panel._renaming = [("u1", "w-L_02 (sw)")]

    panel._on_import_renamed([("u1", "w-L_02 (sw)")])

    assert capture_import.imported_titles(tmp_path) == ["w-L_02 (sw)"]
    assert i18n.t("capImportRenamed").format(n=1, renamed=1) in panel._status_label.text()


def test_method_channel_pairs_uses_meas_order_by_default():
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    pairs = panel._method_channel_pairs()
    assert set(pairs) == {"sw", "rta", "rta_group"}
    # MEAS.groups[0]'s own item order, untouched -- label is the full REW name (id + method
    # suffix, user request 2026-07-28), id itself (first element) stays bare.
    assert pairs["sw"][0] == ("sw_10", "sw_10 (sw)")


def test_method_channel_pairs_prefers_saved_order_over_meas_default():
    _app()
    panel = MeasurementPanel(preset_provider=lambda: "TESTPRESET")
    all_sw = panel._method_channel_pairs()["sw"]
    panel._settings.setValue(panel._capture_order_key("sw"), '["m-L_10", "sw_10"]')
    pairs = panel._method_channel_pairs()
    assert pairs["sw"][:2] == [("m-L_10", "m-L_10 (sw)"), ("sw_10", "sw_10 (sw)")]
    # A partial saved order never drops channels MEAS still has -- the rest trail on, unchanged.
    assert len(pairs["sw"]) == len(all_sw)
    assert set(pairs["sw"]) == set(all_sw)


def test_shutdown_waits_for_running_worker_before_returning():
    """The fix for the real 2026-07-27 crash (QThread destroyed while still running): shutdown()
    must not return while a worker is still alive."""
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    panel._bridge = _FakeBridge({"1": {"title": "m-L_10 (sw)"}})
    panel._worker = _RewScanWorker(panel._bridge)
    panel._worker.start()
    panel.shutdown()
    assert not panel._worker.isRunning()


def test_shutdown_is_a_noop_with_no_workers():
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    panel.shutdown()  # must not raise with every worker still None


def test_capture_order_key_is_per_preset_and_method():
    _app()
    panel = MeasurementPanel(preset_provider=lambda: "SQ")
    assert panel._capture_order_key("sw") == "ui/capture_order/SQ/sw"
    panel_no_preset = MeasurementPanel()
    assert panel_no_preset._capture_order_key("rta") == "ui/capture_order/default/rta"


def test_session_dropdown_lists_all_sessions_live_one_marked():
    """The series is spelled in words (F-010): `v6` reads as a version of something, and the same
    axis was printed `_0` in the curve window. A round id (`cap_001`) is a different axis and
    keeps the journal's own name, which is what tells the two apart in one list."""
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    items = [panel._session_combo.itemText(i) for i in range(panel._session_combo.count())]
    assert items == ["series 10 ●", "series 9", "series 8"]
    assert [panel._session_combo.itemData(i) for i in range(panel._session_combo.count())] == \
        ["v10", "v9", "v8"], "the id is what the panel is keyed on and it did not change"


def test_picking_a_past_session_moves_its_step_onto_the_picker_and_disables_live_actions():
    """User request 2026-07-28: what the round is for, and live-only actions (Read/assign-names)
    disabled when browsing history, since they always target the live session.

    Since 2026-08-21 that text is a HINT on the picker rather than a banner beside it: as a widget
    it ate the width the picker needed and elided the very words it existed for -- "Використа"
    for a past round, "Фаза −1 ·" for the live one. A hint never elides.
    """
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    assert not panel._version.isVisibleTo(panel), "no banner, live or past"
    assert "Series 10" in panel._session_tip.text()
    assert panel._read_btn.isEnabled()

    panel.show_session("v9")
    assert "Used in step 2.2" in panel._session_tip.text()
    assert not panel._read_btn.isEnabled()
    assert panel._session_combo.currentData() == "v9"  # combo follows programmatic switches too

    panel.show_session("v10")
    assert "Series 10" in panel._session_tip.text()
    assert panel._read_btn.isEnabled()


def test_the_session_picker_is_never_narrower_than_the_id_it_shows():
    """`minimumContentsLength` is counted in `x` widths and a round id is not made of `x`."""
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)
    combo = panel._session_combo
    widest = max(combo.fontMetrics().horizontalAdvance(combo.itemText(i))
                 for i in range(combo.count()))
    assert combo.minimumWidth() > widest


def test_picking_session_via_combo_switches_the_grid():
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    panel._session_combo.setCurrentIndex(panel._session_combo.findData("v8"))
    assert panel._viewing_id == "v8"
    assert panel._rows[0].item_name == "sw_8"


def test_the_panel_remembers_what_rew_holds():
    """`known_titles()` was called by the checklist and by the supervisor's audit, and the panel
    never defined it — so both silently ran on "REW holds nothing": a checklist that could not
    mark anything captured from REW, and an audit that could not back a step with a measurement."""
    _app()
    panel = MeasurementPanel()
    seen: list = []
    panel.titlesChanged.connect(lambda: seen.append(1))

    panel._remember_titles(["sw_1 (sw)", "tw-L_1 (rta)", ""])

    assert panel.known_titles() == ["sw_1 (sw)", "tw-L_1 (rta)"]  # blanks are not titles
    assert seen  # and the window is told, so the checklist can be rebuilt

    seen.clear()
    panel._remember_titles(["sw_1 (sw)"])
    assert not seen  # nothing new: no signal, and no needless capture check


def test_replacing_a_running_worker_does_not_abort_the_process():
    """Assigning over an attribute that holds a RUNNING QThread destroys it on the spot, and Qt
    answers that with `qFatal` — the whole process aborts, mid-session (real crash report,
    2026-08-07: `QThread::~QThread()` reached through `Sbk_QWidget_setattro`)."""
    from PySide6.QtCore import QThread

    class _Slow(QThread):
        def run(self) -> None:
            self.msleep(120)

    _app()
    panel = MeasurementPanel()
    first = _Slow()
    panel._replace_worker("_worker", first)
    first.start()

    second = _Slow()
    panel._replace_worker("_worker", second)  # must not raise, and must not abort

    assert not first.isRunning()  # waited out before being dropped
    assert panel._worker is second
    second.wait(2000)


# ---- title identity and the method suffix (user, 2026-08-07) -----------------


def test_the_method_is_not_appended_to_a_name_that_already_carries_it():
    """`c_1 (sw) (sw)` — the row rendering learned this once, then the capture-order dialog was
    built from the same names and printed it all over again."""
    assert with_method("tw-L_1 (sw)", "sw") == "tw-L_1 (sw)"
    assert with_method("tw-L_1", "sw") == "tw-L_1 (sw)"
    assert with_method("  tw-L_1  ", "rta") == "tw-L_1 (rta)"


def test_language_switch_keeps_a_real_capture_task_on_screen():
    """The 2026-08-11 bug: sixteen captures read from REW, switch to English, empty card.

    `retranslate()` ended with an unconditional `set_no_project()` -- written when the mock was the
    only thing the panel could hold, and never revisited when `set_sessions()` gave it a real task.
    """
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)
    panel._set_status("capImportDone", n=1)
    rows_before = len(panel._rows)
    assert rows_before

    before = i18n.current_language()
    try:
        i18n.set_language("en" if before == "uk" else "uk")
        panel.retranslate()
        assert len(panel._rows) == rows_before
        assert not panel._no_project_label.isVisible()
        # ...and the status line speaks the new language rather than staying frozen mid-sentence.
        assert panel._status_label.text() == i18n.t("capImportDone").format(n=1)
    finally:
        i18n.set_language(before)


def test_language_switch_keeps_the_no_project_message_when_there_is_no_task():
    """The other half: without a derived task the card must stay empty, not fall back to the mock
    grid -- a project has never taken "capture series v10" over invented channel names."""
    _app()
    panel = MeasurementPanel()  # constructor ends in set_no_project()
    before = i18n.current_language()
    try:
        i18n.set_language("en" if before == "uk" else "uk")
        panel.retranslate()
        assert panel._rows == []
        assert panel._no_project_label.text() == i18n.t("measNoTask")
    finally:
        i18n.set_language(before)


def _no_capture_session():
    from autosound_tcc.ui.tcc.mock_data import MeasSession

    return [MeasSession(id="v3", version={"en": "Phase 1 · no capture",
                                          "uk": "Фаза 1 · без замірів"}, groups=())]


def test_a_phase_that_captures_nothing_says_so_instead_of_showing_an_empty_grid():
    """User, 2026-08-11: phase 1 rendered as a live legend over no rows, which reads as a mock left
    on screen. `measurement_view.build_session` returns that session deliberately — it is an answer,
    so it has to look like one."""
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(_no_capture_session())
    assert panel._rows == []
    assert panel._no_project_label.text() == i18n.t("measPhaseNoCapture")
    assert not panel._legend.isVisibleTo(panel)  # no rows, so no colours to explain


def test_a_phase_that_captures_nothing_still_offers_the_list(tmp_path, monkeypatch):
    """It used to be a crash risk: placing an "additional" row in a session with no columns indexed
    an empty list inside a signal handler. Nothing is placed now — but the tuner may still want to
    take something in, so the dialog opens and is told the round expects nothing."""
    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc import measurement_panel as mp

    _app()
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    panel = MeasurementPanel()
    panel.set_sessions(_no_capture_session())
    seen = {}

    class _Dialog:
        def __init__(self, measurements, **kwargs):
            seen.update(kwargs)

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(mp, "CaptureImportDialog", _Dialog)
    panel._on_import_offer({"1": {"title": "sub_3 (sw)", "uuid": "u", "date": ""}})

    assert panel._rows == []
    assert seen["has_task"] is False


def test_switching_session_drops_a_status_line_about_the_previous_grid():
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)
    panel._set_status("capImportDone", n=1)
    assert panel._status_label.text()
    panel.set_sessions(_no_capture_session())
    assert panel._status_label.text() == ""


def test_the_session_picker_shows_a_whole_round_id():
    """`cap_001 ●` was eliding to "cap_00…" — a picker whose entries cannot be told apart from one
    another (user, 2026-08-11)."""
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(_no_capture_session()[:1] + [
        __import__("autosound_tcc.ui.tcc.mock_data", fromlist=["MeasSession"]).MeasSession(
            id="cap_001", version={"en": "past", "uk": "минула"}, groups=()
        )
    ])

    combo = panel._session_combo
    hint = combo.sizeHint().width()
    metrics = combo.fontMetrics().horizontalAdvance("cap_001 ●")

    assert hint >= metrics, f"picker asks for {hint}px, the id needs {metrics}px"


def test_the_legend_speaks_the_window_s_language():
    """Four hard-coded English words above a Ukrainian panel, with three of the four translations
    already in the table and unused (found 2026-08-12). `legSkip` was the one genuinely missing."""
    from PySide6.QtWidgets import QLabel

    from autosound_tcc.ui.tcc.measurement_panel import _LEGEND

    _app()
    panel = MeasurementPanel()
    labels = [w for w in panel._legend.findChildren(QLabel)
              if w.property("class") == "meas-legend-label"]
    assert len(labels) == len(_LEGEND)

    try:
        i18n.set_language("uk")
        panel.retranslate()  # MainWindow's own language switch calls exactly this

        assert [w.text() for w in labels] == [i18n.t(key) for _s, key in _LEGEND]
        assert labels[0].text() != "waiting", "the legend actually changed"
    finally:
        i18n.set_language("en")
    panel.retranslate()
    assert [w.text() for w in labels] == [i18n.t(key) for _s, key in _LEGEND]


def test_every_string_the_app_asks_for_exists_in_both_languages():
    """A key present in one table and not the other renders as the key itself. `legSkip` had no
    Ukrainian at all, and nothing said so until someone switched the language and looked."""
    en, uk = set(i18n.T["en"]), set(i18n.T["uk"])

    assert not en - uk, f"no Ukrainian for: {sorted(en - uk)}"
    assert not uk - en, f"Ukrainian-only keys: {sorted(uk - en)}"
