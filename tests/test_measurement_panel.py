"""Headless tests for the measurement panel's Read button (item 1, 2026-07-27) — the REW HTTP
calls themselves are never exercised here (that needs a live REW instance); these fake the
`RewBridge` surface and drive the worker/handlers directly and synchronously instead of racing a
real QThread."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc.channel_order_dialog import ChannelOrderDialog  # noqa: E402
from autosound_tcc.ui.tcc.mock_data import MEAS_SESSIONS  # noqa: E402
from autosound_tcc.state import measurement_view  # noqa: E402
from autosound_tcc.ui.tcc.measurement_panel import (  # noqa: E402
    MeasurementPanel,
    with_method,
    _RewReadWorker,
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


def test_worker_picks_highest_ordinal_id_and_emits_done():
    _app()
    bridge = _FakeBridge({"1": {"title": "old"}, "15": {"title": "sub_10 (sw)"}})
    worker = _RewReadWorker(bridge)
    results = []
    worker.done.connect(lambda r: results.append(r))
    worker.run()  # call synchronously -- no real thread, no race
    assert results == [{"id": "15", "title": "sub_10 (sw)", "n_points": 3}]


def test_worker_emits_failed_on_empty_measurements():
    _app()
    worker = _RewReadWorker(_FakeBridge({}))
    errors = []
    worker.failed.connect(lambda msg: errors.append(msg))
    worker.run()
    assert len(errors) == 1


def test_worker_emits_failed_on_exception():
    _app()
    worker = _RewReadWorker(_FakeBridge({}, raises=ConnectionRefusedError("no REW")))
    errors = []
    worker.failed.connect(lambda msg: errors.append(msg))
    worker.run()
    assert len(errors) == 1 and "ConnectionRefusedError" in errors[0]


def test_read_done_marks_matching_row():
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    # "sw_10" is already "done" in the mock grid's first (sw) group -- pick a "wait" row instead
    # so the transition this test checks is actually exercised.
    row = next(r for r in panel._rows if r.item_name == "m-L_10")
    assert row._dot.property("class") == "tl tl-wait"
    panel._on_read_done({"title": "m-L_10 (sw)", "n_points": 512})
    assert row._dot.property("class") == "tl tl-done"
    assert row._name_label.property("class") == "mn mn-done"
    assert panel._read_btn.isEnabled()


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


def test_read_done_with_modifier_colors_only_the_extra_text():
    """A REW title with a qualifier beyond "<id> (<method>)" is OK, not an error -- the row still
    matches, and the extra text renders blue (user request 2026-07-28)."""
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    row = next(r for r in panel._rows if r.item_name == "m-L_10" and r.method_suffix == "sw")
    panel._on_read_done({"title": "m-L_10 (sw) redo", "n_points": 512})
    html = row._name_label.text()
    assert "m-L_10 (sw)" in html
    assert "redo" in html
    assert "color:" in html  # the qualifier, and only the qualifier, is colored


def test_read_done_with_unmatched_title_adds_additional_row():
    """A REW title matching no expected channel at all is OK too -- it's added as a new row,
    flagged blue end-to-end, rather than silently dropped (user request 2026-07-28)."""
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    before = len(panel._rows)
    panel._on_read_done({"title": "extra-mic_10 (sw)", "n_points": 256})
    assert len(panel._rows) == before + 1
    new_row = panel._rows[-1]
    assert new_row.item_name == "extra-mic_10"
    assert new_row._additional is True
    assert "color:" in new_row._name_label.text()


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


def test_scan_match_reports_mismatch_when_short():
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    panel._pending_order = ["A", "B", "C", "D", "E"]
    panel._on_scan_done({"1": {}, "2": {}})
    text = panel._status_label.text()
    assert "2" in text and "5" in text


def test_scan_match_starts_rename_when_counts_line_up():
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    panel._bridge = _FakeBridge({})  # not used by _on_scan_done itself, just needs .rename_measurement
    panel._pending_order = ["w_L", "w_R"]
    panel._on_scan_done({"5": {}, "6": {}})
    assert panel._rename_worker is not None
    assert panel._rename_worker._pairs == [("5", "w_L"), ("6", "w_R")]
    # A real QThread was started (unlike the other worker tests, which call .run() directly) --
    # must join it before the test returns, or Qt aborts the process ("QThread: Destroyed while
    # thread is still running") once `panel`/`_rename_worker` get garbage-collected.
    panel._rename_worker.wait(2000)


def test_rename_worker_renames_in_order_and_emits_done():
    _app()
    bridge = _FakeBridge({})
    worker = _RewRenameWorker(bridge, [("5", "w_L"), ("6", "w_R")])
    results = []
    worker.done.connect(lambda r: results.append(r))
    worker.run()
    assert results == [[("5", "w_L"), ("6", "w_R")]]
    assert bridge.renamed == [("5", "w_L"), ("6", "w_R")]


def test_rename_worker_stops_at_first_failure_and_reports_progress():
    _app()
    bridge = _FakeBridge({}, rename_fails_at=1)
    worker = _RewRenameWorker(bridge, [("5", "w_L"), ("6", "w_R"), ("7", "tw_L")])
    failures = []
    worker.failed.connect(lambda msg, renamed: failures.append((msg, renamed)))
    worker.run()
    assert len(failures) == 1
    msg, renamed = failures[0]
    assert "REW rejected the rename" in msg
    assert renamed == [("5", "w_L")]  # stopped after the first success, before the failing 2nd call


def test_rename_done_and_failed_update_status_label():
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    panel._on_rename_done([("5", "w_L"), ("6", "w_R")])
    assert "2" in panel._status_label.text()

    panel._on_rename_failed("boom", [("5", "w_L")])
    text = panel._status_label.text()
    assert "boom" in text and "1" in text


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
    panel._worker = _RewReadWorker(panel._bridge)
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
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    items = [panel._session_combo.itemText(i) for i in range(panel._session_combo.count())]
    assert items == ["v10 ●", "v9", "v8"]


def test_picking_a_past_session_shows_its_step_and_disables_live_actions():
    """User request 2026-07-28: the title banner shows the task description for the live
    session, but the plan step(s) it was used for when browsing history; live-only actions
    (Read/assign-names) disable since they always target the live session, not what's shown."""
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    assert panel._version.text() == "Capture series v10"
    assert panel._read_btn.isEnabled()

    panel.show_session("v9")
    assert panel._version.text() == "Used in step 2.2"
    assert not panel._read_btn.isEnabled()
    assert not panel._assign_names_btn.isEnabled()
    assert panel._session_combo.currentData() == "v9"  # combo follows programmatic switches too

    panel.show_session("v10")
    assert panel._version.text() == "Capture series v10"
    assert panel._read_btn.isEnabled()


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


def test_a_zero_padded_rew_title_matches_the_row_that_expects_it(tmp_path, monkeypatch):
    """REW held `c_01 (sw)` while the expected row said `c_1 (sw)`, so matching on the characters
    found nothing and the read added an "additional" graph — beside the very same capture, which
    the derived checklist had already marked done off that title. One capture, two rows."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    (tmp_path / "glossary.json").write_text(
        json.dumps({"schema_version": 1,
                    "channels": [{"code": "c", "active": True}, {"code": "sw", "active": True}]}),
        encoding="utf-8",
    )
    _app()
    panel = MeasurementPanel()
    session = measurement_view.build_session("0", 1, [], tmp_path)
    assert session is not None
    panel.set_sessions((session,))

    row, extra = panel._classify_title("c_01 (sw)")

    assert row is not None and row.item_name == "c_1 (sw)"
    assert extra is None  # padding is not a qualifier, it is the same measurement


def test_the_method_is_not_appended_to_a_name_that_already_carries_it():
    """`c_1 (sw) (sw)` — the row rendering learned this once, then the capture-order dialog was
    built from the same names and printed it all over again."""
    assert with_method("tw-L_1 (sw)", "sw") == "tw-L_1 (sw)"
    assert with_method("tw-L_1", "sw") == "tw-L_1 (sw)"
    assert with_method("  tw-L_1  ", "rta") == "tw-L_1 (rta)"
