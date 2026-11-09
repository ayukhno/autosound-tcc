"""Both layouts of the register (hub #195), and saved configurations (hub #198, SKL-052)."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import config_writer, method_binding, method_cli, vendor_loader  # noqa: E402
from autosound_tcc.state import ledger_line  # noqa: E402

from tests import _reads  # noqa: E402


def _new_window():
    """The one full-window build in this file (the ratchet counts it once)."""
    from autosound_tcc.ui.tcc.main_window import MainWindow

    QApplication.instance() or QApplication([])
    return MainWindow()


def _arbiter_example(root):
    """The Arbiter's own example (2026-09-23): v_003 saved into preset 1 as SQ-1; FULL-1 into
    preset 2 as v_004, its rear changed into v_005; back on SQ-1, refined into SQ-2 = v_006."""
    versions = root / "versions"
    versions.mkdir(parents=True)
    parents = {"v_001": None, "v_002": "v_001", "v_003": "v_002", "v_004": "v_003",
               "v_005": "v_004", "v_006": "v_003"}
    presets = {"v_004": "FULL", "v_005": "FULL"}
    for version, parent in parents.items():
        (versions / f"{version}.json").write_text(json.dumps(
            {"version": version, "preset": presets.get(version, "SQ"), "parent": parent}),
            encoding="utf-8")
    (root / "slots.json").write_text(json.dumps({
        "active": "SQ", "layout": "project-numbered",
        "slots": {"SQ": {"version": "v_006", "dsp_preset": 1},
                  "FULL": {"version": "v_005", "dsp_preset": 2}},
        "configs": {
            "SQ-1": {"version": "v_003", "slot": "SQ", "saved": "2026-09-20T10:00:00",
                     "previous": None, "history": [{"version": "v_003", "saved": "2026-09-20"}]},
            "FULL-1": {"version": "v_004", "slot": "FULL", "saved": "2026-09-21T10:00:00",
                       "purpose": "the whole car", "previous": {"code": "SQ-1", "version": "v_003"},
                       "history": [{"version": "v_004", "saved": "2026-09-21"}]},
            "SQ-2": {"version": "v_006", "slot": "SQ", "saved": "2026-09-22T10:00:00",
                     "purpose": "sound quality", "previous": {"code": "SQ-1", "version": "v_003"},
                     "history": [{"version": "v_006", "saved": "2026-09-22"}]},
        },
    }), encoding="utf-8")


def _old_layout(root):
    for preset, numbers in (("SQ", (1, 2, 3)), ("FULL", (1, 2))):
        folder = root / preset
        folder.mkdir(parents=True)
        for n in numbers:
            (folder / f"v_{n:03d}.json").write_text("{}", encoding="utf-8")
        (folder / "HEAD").write_text(f"v_{numbers[-1]:03d}\n", encoding="utf-8")


def test_the_previous_configuration_is_its_ancestry_not_the_number_below(tmp_path):
    """«Показ порівняння з попереднім має брати v_003, а не v_005» (the Arbiter, 2026-09-23)."""
    _arbiter_example(tmp_path)
    assert ledger_line.previous_of(tmp_path, "SQ", "v_006") == "v_003"


def test_a_version_never_saved_is_compared_with_its_parent(tmp_path):
    _arbiter_example(tmp_path)
    assert ledger_line.previous_of(tmp_path, "FULL", "v_005") == "v_004"


def test_the_old_layout_keeps_the_number_below_in_its_own_preset(tmp_path):
    _old_layout(tmp_path)
    assert not ledger_line.is_project_line(tmp_path)
    assert ledger_line.previous_of(tmp_path, "SQ", "v_003") == "v_002"
    assert ledger_line.previous_of(tmp_path, "SQ", "v_001") is None
    assert ledger_line.configs(tmp_path) == {}


def test_presets_watches_and_proposals_follow_the_layout(tmp_path):
    new, old = tmp_path / "new", tmp_path / "old"
    _arbiter_example(new)
    _old_layout(old)
    assert ledger_line.presets(new) == ["FULL", "SQ"]
    assert ledger_line.presets(old) == ["FULL", "SQ"]
    assert ledger_line.watched_files(new, ["SQ"]) == [str(new / "slots.json")]
    assert ledger_line.watched_files(old, ["SQ"]) == [str(old / "SQ" / "HEAD")]
    assert str(new / "versions") in ledger_line.watched_dirs(new, ["SQ"])
    assert ledger_line.proposals_dir(new, "SQ") == new / "proposals"
    assert ledger_line.proposals_dir(old, "SQ") == old / "SQ" / "proposals"
    assert ledger_line.versions(new, "SQ") == [f"v_{n:03d}" for n in range(1, 7)], \
        "on the project line every version is offered: a previous may be another slot's"


def test_a_version_is_named_by_what_it_was_saved_under(tmp_path):
    _arbiter_example(tmp_path)
    assert ledger_line.label(tmp_path, "v_003") == "v_003 · SQ-1"
    assert ledger_line.label(tmp_path, "v_005") == "v_005"
    code, rec = ledger_line.config_of(tmp_path, "v_006")
    assert code == "SQ-2" and rec["purpose"] == "sound quality"
    assert ledger_line.dsp_preset(tmp_path, "SQ") == "1"


def test_a_version_is_named_with_the_day_it_was_made_beside_its_names(tmp_path):
    """#203: `v_007 · 05.10 · SQ-2` — the day comes in as `days`, the names as `names`, as the
    names already do, and each is left out where there is none."""
    names = {"v_007": ["SQ-2"]}
    days = {"v_007": "05.10"}
    assert ledger_line.label(tmp_path, "v_007", names, days) == "v_007 · 05.10 · SQ-2"
    assert ledger_line.label(tmp_path, "v_007", {}, days) == "v_007 · 05.10"
    assert ledger_line.label(tmp_path, "v_007", names, {}) == "v_007 · SQ-2"
    assert ledger_line.label(tmp_path, "v_007", {}, {}) == "v_007"


def _made_on(root, stamps: dict) -> None:
    """Gives each version file of the project line its `created`, as the method writes it (#203)."""
    for version, stamp in stamps.items():
        path = root / "versions" / f"{version}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["created"] = stamp
        path.write_text(json.dumps(data), encoding="utf-8")


def test_compare_offers_name_each_version_with_the_day_it_was_made(tmp_path, monkeypatch):
    """#203: the day comes from each version's own `created`, for this preset's versions and for
    the other preset's alike; a version with no `created` keeps its number alone. The day is read
    once per version: a second offer opens none of the version files it has already read."""
    _arbiter_example(tmp_path)
    _made_on(tmp_path, {"v_002": "2026-09-19T09:00:00", "v_003": "2026-09-20T10:00:00",
                        "v_004": "2026-09-21T10:00:00", "v_005": "2026-09-23T08:00:00",
                        "v_006": "2026-09-22T10:00:00"})
    offer = ledger_line.compare_offer(tmp_path, "SQ", "v_006")
    assert offer.labels == {"v_006": "v_006 · 22.09 · SQ-2", "v_003": "v_003 · 20.09 · SQ-1",
                            "v_002": "v_002 · 19.09", "v_001": "v_001"}
    assert offer.others == [("FULL", [("FULL/v_005", "v_005 · 23.09"),
                                      ("FULL/v_004", "v_004 · 21.09 · FULL-1")])]

    opened = _reads.opened_under(monkeypatch, tmp_path)
    ledger_line.compare_offer(tmp_path, "SQ", "v_006")
    assert [p for p in opened if "/versions/" in p and not p.endswith("v_006.json")] == [], \
        "the days are remembered per file: only the open version's own file is read again"


def test_a_tz_aware_created_is_read_as_the_local_day():
    """#203: a `created` with its offset is the day it was where this machine is."""
    from datetime import datetime

    stamp = "2026-09-20T23:30:00+00:00"
    assert ledger_line._day(stamp) == datetime.fromisoformat(stamp).astimezone().strftime("%d.%m")


@pytest.mark.parametrize("stamp", ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00",
                                   "not a time", "", 20260920])
def test_a_created_that_cannot_be_a_local_day_is_no_day(stamp):
    """#203: `astimezone()` raises `OverflowError` at the year-1/9999 edges, and on Windows
    `OSError` before 1970; either made `compare_offer` raise and the project load fail."""
    assert ledger_line._day(stamp) is None


def test_a_created_windows_cannot_place_is_no_day(monkeypatch):
    """#203: Windows' `astimezone()` raises `OSError` for a time before 1970."""
    from datetime import datetime as real

    class _Moment(real):
        def astimezone(self, tz=None):
            raise OSError(22, "Invalid argument")

    class _Clock:
        @staticmethod
        def fromisoformat(text):
            moment = real.fromisoformat(text)
            return _Moment(moment.year, moment.month, moment.day, tzinfo=moment.tzinfo)

    monkeypatch.setattr(ledger_line, "datetime", _Clock)
    assert ledger_line._day("1969-07-20T20:17:00+00:00") is None


def test_compare_offer_survives_a_created_it_cannot_place(tmp_path):
    """#203: one version's `created` at the edge of the calendar costs that version its day, not
    the offer."""
    _arbiter_example(tmp_path)
    _made_on(tmp_path, {"v_003": "0001-01-01T00:00:00+14:00", "v_002": "2026-09-19T09:00:00"})
    offer = ledger_line.compare_offer(tmp_path, "SQ", "v_006")
    assert offer.labels["v_003"] == "v_003 · SQ-1"
    assert offer.labels["v_002"] == "v_002 · 19.09"


def test_compare_offers_the_previous_configuration_by_default(tmp_path):
    """«Порівняти з» for SQ-2 (v_006): its own versions with the names they were saved under, then
    FULL's, keyed by their preset; selected by default the PREVIOUS configuration — SQ-1's v_003,
    not v_005 (the Arbiter, 2026-09-23: «за замовчанням попередній»)."""
    _arbiter_example(tmp_path)
    offer = ledger_line.compare_offer(tmp_path, "SQ", "v_006")
    assert offer.own == ["v_006", "v_003", "v_002", "v_001"]
    assert offer.default == "v_003", "SQ-2 continues SQ-1, not v_005"
    assert offer.labels["v_003"] == "v_003 · SQ-1"
    assert offer.others == [("FULL", [("FULL/v_005", "v_005"), ("FULL/v_004", "v_004 · FULL-1")])]


def test_a_previous_made_for_another_preset_is_selected_in_that_preset_s_group(tmp_path):
    """The project line: a configuration may continue another preset's. FULL-1 (v_004) continues
    SQ-1 (v_003), made for SQ and so not in FULL's own group: the default is SQ's row, keyed
    `SQ/v_003` as the loader reads it from its own preset. With nothing before the version open
    now, nothing is selected."""
    line, old = tmp_path / "line", tmp_path / "old"
    _arbiter_example(line)
    offer = ledger_line.compare_offer(line, "FULL", "v_004")
    assert "v_003" not in offer.own
    assert offer.default == "SQ/v_003"
    assert ("SQ/v_003", "v_003 · SQ-1") in dict(offer.others)["SQ"]

    _old_layout(old)
    assert ledger_line.compare_offer(old, "SQ", "v_001").default is None


def _the_method_answers(monkeypatch, code: int, out: str = "", err: str = "") -> list:
    """The method's `state.py` answering `(code, out, err)` at the one door a method script is
    started by (`method_cli`, #169), and what it was started with, one argv per run. The script is
    the copy the current project runs — TCC's own, for a project with no entry."""
    if not config_writer.script_path().is_file():
        pytest.skip("skill submodule not checked out")
    seen = []

    def run(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, code, out, err)

    monkeypatch.setattr(method_cli.child, "run_bounded", run)
    return seen


def test_a_save_goes_through_the_method_with_its_arguments(tmp_path, monkeypatch):
    seen = _the_method_answers(monkeypatch, 0, "SQ-2 = v_006 in slot SQ (DSP preset 1)\n")
    result = config_writer.save(tmp_path, "v_006", "SQ-2", slot="SQ", dsp_preset="1",
                                purpose="sound quality")
    assert result.saved and result.said.startswith("SQ-2 = v_006")
    argv = seen[0]
    assert argv[argv.index("--root") + 1] == str(tmp_path)
    assert argv[argv.index("config"):argv.index("config") + 4] == ["config", "save", "v_006", "SQ-2"]
    assert argv[argv.index("--dsp-preset") + 1] == "1"


def test_a_method_without_config_is_said_as_too_old(tmp_path, monkeypatch):
    _the_method_answers(monkeypatch, 2, "",
                        "state.py: error: argument cmd: invalid choice: 'config' (choose from ...)")
    result = config_writer.save(tmp_path, "v_006", "SQ-2")
    assert not result.saved and result.too_old


def test_a_save_runs_the_copy_of_the_project_it_is_given(tmp_path, monkeypatch):
    """R-h (#169): `project_dir=` is the project whose copy of the method runs the save, the current
    one when it is not given — the dialog's case, whose `state_root` is that project's `state/`.
    Here the named project's copy is refused while the current one's is not, and the save says the
    named one's sentence, having started nothing."""
    seen = _the_method_answers(monkeypatch, 0, "saved")
    other = tmp_path / "other-car"
    (other / ".claude" / "skills" / vendor_loader.SKILL_NAME).mkdir(parents=True)

    result = config_writer.save(other / "state", "v_006", "SQ-2", project_dir=other)

    assert (result.saved, result.said) == (False, method_binding.for_project(other).reason)
    assert seen == []
    assert config_writer.save(other / "state", "v_006", "SQ-2").saved, "the current project's runs"


def test_the_form_offers_the_device_preset_it_was_last_saved_to(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc.save_config_dialog import SaveConfigDialog

    QApplication.instance() or QApplication([])
    _arbiter_example(tmp_path)
    calls = []
    monkeypatch.setattr(config_writer, "save", lambda *a, **k: calls.append((a, k)) or
                        config_writer.SaveResult(True, "SQ-2 = v_006 in slot SQ"))
    dialog = SaveConfigDialog(tmp_path, "v_006", "SQ", ["FULL", "SQ"])
    assert dialog._name.text() == "SQ-2", "a version already saved opens with its name"
    assert dialog._dsp_preset.text() == "1"
    dialog._on_save()
    assert calls and calls[0][1]["slot"] == "SQ" and calls[0][1]["dsp_preset"] == "1"
    assert dialog.said == "SQ-2 = v_006 in slot SQ"


def test_a_save_another_write_held_is_said_as_busy_and_the_form_stays(tmp_path, monkeypatch):
    """The method's exit 75 (#218): another write held the project past the wait, nothing was
    recorded, and the same save will work in a moment. The save says so — `busy`, not the method's
    technical line about its lock file — and the form stays open for the retry."""
    from autosound_tcc.ui.tcc import i18n
    from autosound_tcc.ui.tcc.save_config_dialog import SaveConfigDialog

    QApplication.instance() or QApplication([])
    _arbiter_example(tmp_path)
    line = ("busy: /car/.autosound/write.lock is held by another writer -- nothing was written, "
            "safe to retry")
    _the_method_answers(monkeypatch, method_cli.EXIT_BUSY, "", line)
    assert config_writer.save(tmp_path, "v_006", "SQ-2") == config_writer.SaveResult(
        False, line, busy=True)

    dialog = SaveConfigDialog(tmp_path, "v_006", "SQ", ["FULL", "SQ"])
    dialog._on_save()

    assert dialog._result.text() == i18n.t("cfgBusy")
    assert dialog.said is None, "the dialog closed as saved"


def test_the_slot_list_holds_a_long_slot_name_whole(tmp_path, monkeypatch):
    """tcc#145's review, I1: every combo's list has `.mini-select`'s room for the check mark, and
    a plain box's list is only as wide as the box. A slot name longer than anything else in the
    form sizes the box to itself, and its row came back cut."""
    from autosound_tcc.ui.tcc.save_config_dialog import SaveConfigDialog
    from tests import _windows

    QApplication.instance() or QApplication([])
    _arbiter_example(tmp_path)
    dialog = SaveConfigDialog(tmp_path, "v_006", "SQ",
                              ["FULL", "SQ", "Daily drive with the rear fill switched off"])
    _windows.theme_on(monkeypatch, dialog, "dark")
    dialog.show()
    try:
        assert _windows.cut_rows(dialog._slot) == []
    finally:
        dialog.close()


def test_the_dsp_header_names_the_configuration_in_the_processor(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from autosound_tcc.core import config

    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    root = tmp_path / "ledger"
    _arbiter_example(root)
    monkeypatch.setattr(config, "state_root", lambda *_a, **_k: root)
    window = _new_window()
    view = SimpleNamespace(version="v_006", state="applied", status_counts=(), preset="SQ")
    window._show_version(view, {"dsp_profile": {"vendor": "Audiotec", "name": "Helix"}})
    assert window._dsp_section.sub_text() == "SQ-2 · v_006"
    assert not window._cfg_btn.isHidden(), "the save is offered on the per-project line"
    # The window hands `compare_offer`'s labels to the pane (Task 32's review, Minor 1): the one
    # window build of a project with saved names, so the pin rides here.
    window._offer_compare(root, "SQ", {}, "v_006")
    assert "SQ-1" in window._detail._compare_combo.currentText(), "the saved name reaches the list"
    # #251: the window's header reads a file recorded after the version was first read.
    stat = (root / "versions" / "v_006.json").stat()
    (root / "versions" / "v_006.json").write_text(json.dumps(
        {"version": "v_006", "preset": "SQ", "channels": {"w-L": {"status": "applied"}},
         "provenance": {"file": "presets/a.pct6 (md5 ee627ad6…) decoded read-only"}}), encoding="utf-8")
    os.utime(root / "versions" / "v_006.json", ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    window._show_version(view, {"dsp_profile": {"vendor": "Audiotec", "name": "Helix"}})
    assert window._dsp_section.dot_status() == "checked"
    assert "md5 ee627ad6…" in window._dsp_section._dot.toolTip()


def test_compare_offers_this_preset_first_then_the_others_on_the_old_layout(tmp_path):
    """«Треба мати можливість порівнювати не тільки v_xxx в поточній конфігурації, але і з іншими
    конфігураціями» (the Arbiter, 2026-09-25, finding 66). The old layout numbers each preset on
    its own, so the other presets' versions are a second list, not more of the same one.

    `current` (v_003) stays in its own group, first (tcc#103, finding 112) -- greying it out and
    marking it «зараз» is `fill_compare_combo`'s job, not this function's."""
    _old_layout(tmp_path)
    assert ledger_line.compare_groups(tmp_path, "SQ", "v_003") == [
        ("SQ", ["v_003", "v_002", "v_001"]), ("FULL", ["v_002", "v_001"])]


def test_compare_groups_the_project_line_by_the_preset_each_version_was_made_for(tmp_path):
    _arbiter_example(tmp_path)
    assert ledger_line.compare_groups(tmp_path, "SQ", "v_006") == [
        ("SQ", ["v_006", "v_003", "v_002", "v_001"]), ("FULL", ["v_005", "v_004"])]


def test_the_preset_a_version_was_made_for_is_read_once_per_file(tmp_path, monkeypatch):
    """#172: every reload offers «порівняти з», and that asks each version which preset it was
    made for — a whole DSP state read for one field, on the GUI thread. The answer is remembered
    per file by its path, mtime and size: the groups read a second time open no version, and a
    version rewritten to the same size under a new mtime is read again."""
    _arbiter_example(tmp_path)
    groups = ledger_line.compare_groups(tmp_path, "SQ", "v_006")
    opened = _reads.opened_under(monkeypatch, tmp_path)

    assert ledger_line.compare_groups(tmp_path, "SQ", "v_006") == groups
    assert opened == []

    v_004 = tmp_path / "versions" / "v_004.json"
    was = v_004.stat()
    v_004.write_text(json.dumps({"version": "v_004", "preset": "LOUD", "parent": "v_003"}),
                     encoding="utf-8")
    os.utime(v_004, ns=(was.st_atime_ns, was.st_mtime_ns + 1_000_000_000))
    assert v_004.stat().st_size == was.st_size
    assert ledger_line.compare_groups(tmp_path, "SQ", "v_006") == [
        ("SQ", ["v_006", "v_003", "v_002", "v_001"]), ("FULL", ["v_005"]), ("LOUD", ["v_004"])]
    assert opened == [str(v_004)]


def test_compare_groups_keeps_the_current_version_even_with_nothing_else_to_offer(tmp_path):
    """A preset with a single version used to come back empty (silently dropped, tcc#103, finding
    112); now its own version -- the one open now -- is still there for the heading and the greyed
    row to stand on."""
    versions = tmp_path / "versions"
    versions.mkdir(parents=True)
    (versions / "v_001.json").write_text('{"version": "v_001", "preset": "SQ", "parent": null}',
                                         encoding="utf-8")
    (tmp_path / "slots.json").write_text(
        '{"active": "SQ", "layout": "project-numbered", '
        '"slots": {"SQ": {"version": "v_001", "dsp_preset": 1}}, "configs": {}}', encoding="utf-8")
    assert ledger_line.compare_groups(tmp_path, "SQ", "v_001") == [("SQ", ["v_001"])]


def test_current_is_dropped_from_every_group_it_does_not_head(tmp_path):
    """The GAP the controller caught in review (an opus reviewer's pass on the first fix):
    `current` stays IN its own group now (tcc#103), but must stay OUT of every OTHER one --
    before this change it was dropped from every group; a version's own file can name a preset
    different from the one it is CURRENT for (SQ is applying v_006, but v_006 itself says it was
    proposed for FULL), and nothing marks it there as the version already open.

    It still stands in the OPEN preset's group, whatever its file names: #103 wants the current
    version shown there, greyed -- not a heading over an empty list."""
    versions = tmp_path / "versions"
    versions.mkdir(parents=True)
    (versions / "v_004.json").write_text(
        '{"version": "v_004", "preset": "FULL", "parent": null}', encoding="utf-8")
    (versions / "v_006.json").write_text(
        '{"version": "v_006", "preset": "FULL", "parent": null}', encoding="utf-8")
    (tmp_path / "slots.json").write_text(
        '{"active": "SQ", "layout": "project-numbered", '
        '"slots": {"SQ": {"version": "v_006", "dsp_preset": 1}, '
        '"FULL": {"version": "v_004", "dsp_preset": 2}}, "configs": {}}', encoding="utf-8")
    groups = ledger_line.compare_groups(tmp_path, "SQ", "v_006")
    assert dict(groups).get("FULL", []) == ["v_004"], \
        "current does not reappear, selectable, under the preset its own file names"
    assert groups == [("SQ", ["v_006"]), ("FULL", ["v_004"])], \
        "the open preset's heading stands over its current version, not over nothing"

    (versions / "v_004.json").unlink()
    assert ledger_line.compare_groups(tmp_path, "SQ", "v_006") == [("SQ", ["v_006"])], \
        "nor does FULL's heading, once the version open now was its only one"


def test_another_preset_keeps_its_own_v_002_on_the_old_layout(tmp_path):
    """The old layout numbers each preset on its own: FULL's `v_002` is a different state from
    SQ's `v_002` -- keyed `FULL/v_002` and read from FULL's own folder -- never the version open
    now, so nothing of FULL's is dropped because SQ's current is also called `v_002`."""
    _old_layout(tmp_path)
    groups = ledger_line.compare_groups(tmp_path, "SQ", "v_002")
    assert dict(groups)["FULL"] == ["v_002", "v_001"], \
        "FULL's own current version stays on offer beside its older one"


def test_the_arbiter_s_project_offers_every_other_preset_s_both_versions(tmp_path):
    """The shape of `passat-b8-2026-aya` (tcc#103, finding 112): `3.S-shelf`…`7.E-epy` each hold
    `v_001` and `v_002`, `HEAD` = `v_002`; `4.C-cut` is open at its `v_002`. Its own group keeps
    that version (greyed by the combo), and every other configuration offers both of its own --
    its current one included (finding 66)."""
    names = ("3.S-shelf", "4.C-cut", "5.B-bass", "6.W-wide", "7.E-epy")
    for name in names:
        folder = tmp_path / name
        folder.mkdir()
        for n in (1, 2):
            (folder / f"v_{n:03d}.json").write_text("{}", encoding="utf-8")
        (folder / "HEAD").write_text("v_002\n", encoding="utf-8")
    groups = ledger_line.compare_groups(tmp_path, "4.C-cut", "v_002")
    assert groups[0] == ("4.C-cut", ["v_002", "v_001"])
    assert groups[1:] == [(n, ["v_002", "v_001"]) for n in names if n != "4.C-cut"]


def test_the_window_offers_other_presets_versions_after_its_own(tmp_path, monkeypatch):
    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc import main_window

    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    loaded = []
    monkeypatch.setattr(main_window, "load_project_view",
                        lambda root, preset, profile, version=None: loaded.append((preset, version)))
    root = tmp_path / "ledger"
    _old_layout(root)
    window = _new_window()
    window._offer_compare(root, "SQ", {}, "v_003")
    combo = window._detail._compare_combo
    keys = [combo.itemData(i) for i in range(combo.count())]
    # "—", the own-preset heading, v_003 (the current one) greyed out (tcc#103), then its
    # selectable versions -- still first, as before.
    assert keys[:5] == [None, None, None, "v_002", "v_001"], \
        "this preset's own group comes first, headed and with its current version greyed"
    assert keys.index("FULL/v_002") > keys.index("v_001")
    assert combo.currentData() == "v_002", "`compare_offer`'s default is the one selected"
    header = next(i for i in range(combo.count())
                  if combo.itemData(i) is None and "FULL" in combo.itemText(i))
    assert not combo.model().item(header).isEnabled(), "the preset's name heads its versions"

    combo.setCurrentIndex(combo.findData("FULL/v_002"))
    assert loaded[-1] == ("FULL", "v_002"), "another preset's version is read from that preset"
    assert window._detail._compare_other.isVisibleTo(window._detail)


# ---- «Показати версію…» (#249): one version looked at in the DSP tree, read-only ---------------


def _project_with_versions(tmp_path, monkeypatch):
    """FULL at v_003 with v_001 and v_002 behind it, SQ at v_004 (one line per project), through
    the skill's writers."""
    from tests import _intake

    _intake.seed(tmp_path)
    state = vendor_loader.load_dsp_state()
    full = state.PresetHistory(str(tmp_path / "state"), "FULL", project_dir=str(tmp_path))

    def snap(history, preset, gain, **row):
        history.snapshot({"preset": preset, "sample_rate": 96000,
                          "channels": {"w-L": {"hp": None, "lp": None, "gain_db": gain, "ta_ms": -gain,
                                               "polarity": "NORM", **row}}}, note="fixture")

    snap(full, "FULL", -1.5, off=True)  # v_002: its only channel switched off
    snap(full, "FULL", -4.5, status="applied")
    sq = state.PresetHistory(str(tmp_path / "state"), "SQ", project_dir=str(tmp_path))
    snap(sq, "SQ", -7.5, status="proposed")
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path / "state"))
    window = _new_window()
    assert window._loaded_preset == "FULL" and window._view.version == "v_003", "the fixture opens"
    return window


def _table_text(pane) -> str:
    from PySide6.QtWidgets import QTableWidget

    tables = [t for t in pane.findChildren(QTableWidget) if not t.isHidden()]
    return " ".join(t.item(r, c).text() for t in tables for r in range(t.rowCount())
                    for c in range(t.columnCount()) if t.item(r, c) is not None)


def _shown_text(window) -> str:
    """What the person reads in the channel table, opened as the tree's «params» opens it."""
    window._on_table_requested("physical_outputs")
    return _table_text(window._detail)


def _dot_of(window):
    return window._dsp_section._dot.property("class")


def _tree_text(window) -> str:
    """Every word on the DSP tree, as drawn."""
    from PySide6.QtWidgets import QLabel

    return " ".join(label.text() for label in window._tree.findChildren(QLabel))


def _pick(window, text_start):
    """Press the row of «Показати версію…» that reads `text_start`."""
    from autosound_tcc.ui.tcc import shown_version

    menu = shown_version.picker_menu(window)
    action = next(a for a in menu.actions() if a.text().startswith(text_start))
    assert action.isEnabled(), f"{action.text()!r} can be picked"
    action.trigger()


def test_any_version_can_be_shown_read_only_with_a_mark_and_one_way_back(tmp_path, monkeypatch):
    window = _project_with_versions(tmp_path, monkeypatch)
    assert window._shown_mark.isHidden() and window._shown_back.isHidden(), "HEAD carries no mark"
    assert "-4.5" in _shown_text(window)

    _pick(window, "v_001")

    assert "0" in _shown_text(window) and "-4.5" not in _shown_text(window), "the tree shows v_001"
    assert not window._shown_mark.isHidden() and "v_001" in window._shown_mark.text()
    assert "not the current" in window._shown_mark.text()
    # The header's dot and version say what is in the processor, HEAD, and name what is looked at.
    assert window._dsp_section.sub_text().startswith("v_003") and "v_001" in window._dsp_section.sub_text()

    window._shown_back.click()
    assert window._shown_mark.isHidden() and "-4.5" in _shown_text(window), "one way back to HEAD"


def test_nothing_acts_on_a_looked_at_version_as_head(tmp_path, monkeypatch):
    """The listening and protective dialogs, «Saved in the DSP», the delay panel's present values,
    the measurement panel's preset and what is published to a session all stay on HEAD."""
    from types import SimpleNamespace

    from autosound_tcc.ui.tcc import i18n, listening_dialog, protective_dialog

    i18n.set_language("en")
    window = _project_with_versions(tmp_path, monkeypatch)
    monkeypatch.setattr(ledger_line, "is_project_line", lambda _root: True)  # «Збережено в DSP…» lives there
    published = {}
    window._bridge = type("B", (), {"set_snapshot": lambda _s, **f: published.update(f)})()
    head_dot = _dot_of(window)
    _pick(window, "v_004")  # SQ's: another slot, so a reader of what is drawn would say SQ

    assert window._shown_mark.text().startswith("Showing v_004") and "SQ" in window._shown_mark.text()
    assert window._view.version == "v_003", "the actors' view is HEAD"
    assert _dot_of(window) == head_dot and head_dot == "tl tl-done", "the header's dot is HEAD's"
    window._open_curves(["w-L_01 (sw)"])
    assert window._curve_dialog._delays_provider() == {"w-L": 4.5}, "the delay panel reads HEAD"
    window._curve_dialog.close()
    assert window._cfg_btn.isHidden(), "«Збережено в DSP…» is not offered over an old version"
    assert published["preset"] == "FULL", "the session is told what HEAD is"
    window._publish_snapshot()
    assert published["preset"] == "FULL"
    assert window._meas_panel._preset_provider() == "FULL"
    sent = []
    monkeypatch.setattr(listening_dialog, "open_for", lambda _p, view, *a, **k: sent.append(view.version)
                        or (None, "x"))
    monkeypatch.setattr(protective_dialog, "open_for", lambda _p, view, *a, **k: sent.append(view.version)
                        or SimpleNamespace(exec=lambda: 0, written=[]))
    window._open_listening()
    window._open_protective()
    assert sent == ["v_003", "v_003"], "a verdict or protection is never stamped on the shown one"


def test_the_channel_switches_stay_on_head_while_another_version_is_looked_at(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc import i18n

    i18n.set_language("en")
    window = _project_with_versions(tmp_path, monkeypatch)
    _pick(window, "v_002")  # its channel is switched off; HEAD's is not
    window._rebuild_system_params()  # as a language switch does: a reader of what is drawn shows here

    assert window._toggle_buttons[("physical_outputs", "w-L")].text() == i18n.t("chanTurnOff")


def test_a_shown_version_gone_says_so_and_goes_back_to_head(tmp_path, monkeypatch):
    window = _project_with_versions(tmp_path, monkeypatch)
    said = []
    monkeypatch.setattr(window._status_strip, "notify", lambda text, **_k: said.append(text))
    _pick(window, "v_001")
    (tmp_path / "state" / "versions" / "v_001.json").unlink()

    window._reload_from_disk()

    assert any("v_001" in line and "could not be read" in line for line in said), said
    assert window._shown_mark.isHidden() and "-4.5" in _shown_text(window), "back on HEAD, no crash"


def test_a_write_that_moves_nothing_keeps_the_version_looked_at(tmp_path, monkeypatch):
    """A live session rewriting `project.json` is no reason to throw the person off an old version."""
    window = _project_with_versions(tmp_path, monkeypatch)
    said = []
    monkeypatch.setattr(window._status_strip, "notify", lambda text, **_k: said.append(text))
    _pick(window, "v_001")
    project_json = tmp_path / "project.json"
    project_json.write_text(project_json.read_text(encoding="utf-8"), encoding="utf-8")

    window._reload_project_files()

    assert not window._shown_mark.isHidden() and "v_001" in window._shown_mark.text(), said
    assert "-4.5" not in _shown_text(window) and not [line for line in said if "current version" in line]


def _bank_a_new_head(tmp_path) -> None:
    state = vendor_loader.load_dsp_state()
    full = state.PresetHistory(str(tmp_path / "state"), "FULL", project_dir=str(tmp_path))
    full.snapshot({"preset": "FULL", "sample_rate": 96000,
                   "channels": {"w-L": {"hp": None, "lp": None, "gain_db": -9.5, "ta_ms": 0.0,
                                        "polarity": "NORM"}}}, note="a session wrote")


def test_a_session_banking_a_version_while_one_is_shown_resets_and_says_once(tmp_path, monkeypatch):
    window = _project_with_versions(tmp_path, monkeypatch)
    said = []
    monkeypatch.setattr(window._status_strip, "notify", lambda text, **_k: said.append(text))
    _pick(window, "v_001")
    _bank_a_new_head(tmp_path)

    window._reload_project_files()
    window._reload_project_files()

    told = [line for line in said if "current version" in line]
    assert len(told) == 1 and "v_005" in told[0], said
    assert window._shown_mark.isHidden() and "-9.5" in _shown_text(window)


def test_a_new_version_on_the_line_resets_even_when_head_did_not_move(tmp_path, monkeypatch):
    window = _project_with_versions(tmp_path, monkeypatch)
    _pick(window, "v_001")
    versions = tmp_path / "state" / "versions"
    (versions / "v_009.json").write_text((versions / "v_002.json").read_text(encoding="utf-8"),
                                         encoding="utf-8")

    window._reload_project_files()

    assert window._shown_mark.isHidden(), "the set of versions changed: back on HEAD"


def test_a_version_that_loads_but_cannot_be_drawn_goes_back_to_head_and_says_so(tmp_path, monkeypatch):
    """`role: 5` loads and then fails inside the tree: the strip said the last good view stays,
    with the key still set, and every later load failed the same way."""
    window = _project_with_versions(tmp_path, monkeypatch)
    said = []
    monkeypatch.setattr(window._status_strip, "notify", lambda text, **_k: said.append(text))
    path = tmp_path / "state" / "versions" / "v_001.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["channels"]["w-L"]["role"] = 5
    path.write_text(json.dumps(data), encoding="utf-8")

    _pick(window, "v_001")

    assert window._shown_mark.isHidden() and "-4.5" in _shown_text(window), "back on HEAD"
    assert "w-L" in _tree_text(window), "the tree is drawn again, not left empty"
    assert any("v_001" in line and "current one is shown" in line for line in said), said
    assert not [line for line in said if "last good view" in line], said


def test_a_control_mode_tab_that_cannot_draw_the_shown_version_goes_back_to_head(tmp_path, monkeypatch):
    """The control tabs are redrawn from a timer: a raise there is outside every guard."""
    from autosound_tcc.ui.tcc import control_layout

    window = _project_with_versions(tmp_path, monkeypatch)
    said = []
    monkeypatch.setattr(window._status_strip, "notify", lambda text, **_k: said.append(text))
    monkeypatch.setattr(control_layout, "place_terminal_left", lambda *a, **k: None)
    monkeypatch.setattr(control_layout.MonitorFeed, "refresh", lambda self: None)
    real = control_layout._table_tab

    def fussy(win, view, group_id, empty_key):
        if view.version == "v_001":
            raise ValueError("a tab that cannot draw this version")
        return real(win, view, group_id, empty_key)

    monkeypatch.setattr(control_layout, "_table_tab", fussy)
    layout = window._control_layout
    layout.enter()
    try:
        _pick(window, "v_001")  # the tree and the pane draw it; only a tab cannot
        layout.refresh()

        assert window._shown_mark.isHidden(), "the key is cleared, not left to fail every redraw"
        assert any("v_001" in line and "current one is shown" in line for line in said), said
        tab = layout.tabs.widget(layout._index["physical_outputs"])
        assert "-4.5" in _table_text(tab), "the tabs are drawn again, from HEAD"
    finally:
        layout.leave()


def test_a_version_that_cannot_be_read_says_why_in_the_log(tmp_path, monkeypatch, caplog):
    """The strip says it was unreadable; the log has to carry why, or nobody can find out."""
    import logging

    window = _project_with_versions(tmp_path, monkeypatch)
    _pick(window, "v_001")
    (tmp_path / "state" / "versions" / "v_001.json").write_text("{ not json", encoding="utf-8")
    logger = logging.getLogger("autosound_tcc")
    logger.addHandler(caplog.handler)
    try:
        window._reload_from_disk()
    finally:
        logger.removeHandler(caplog.handler)

    records = [r for r in caplog.records if "v_001" in r.getMessage()]
    assert records, caplog.text
    assert records[0].exc_info is not None or "Error" in records[0].getMessage(), "the cause is in it"


def _copy_said(monkeypatch, window, pane) -> list:
    """Press «copy EQ» on `pane` over a channel; what the strip then says."""
    from autosound_tcc.core import eq_export

    said = []
    monkeypatch.setattr(window._status_strip, "notify", lambda text, **_k: said.append(text))
    monkeypatch.setattr(eq_export, "format_bank", lambda rows, **kw: eq_export.Bank(
        text="BANK", format_name="X", written=1, bank_size=0, crossovers=0, notes=(), left_out=()))
    group = window._find_group("physical_outputs")
    pane._group, pane._row = group, group.rows[0]
    pane._on_copy_eq_bank()
    return said


def test_a_copied_eq_names_the_version_only_while_one_is_looked_at(tmp_path, monkeypatch):
    window = _project_with_versions(tmp_path, monkeypatch)

    said = _copy_said(monkeypatch, window, window._detail)
    assert len(said) == 1 and "v_00" not in said[0], said

    _pick(window, "v_004")
    said = _copy_said(monkeypatch, window, window._detail)
    assert len(said) == 1 and "v_004" in said[0] and "SQ" in said[0], said
    assert "not the current" in said[0], said


def test_a_copy_from_a_control_mode_tab_is_said_and_names_the_version(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc import control_layout

    window = _project_with_versions(tmp_path, monkeypatch)
    monkeypatch.setattr(control_layout, "place_terminal_left", lambda *a, **k: None)
    monkeypatch.setattr(control_layout.MonitorFeed, "refresh", lambda self: None)
    _pick(window, "v_001")
    layout = window._control_layout
    layout.enter()
    try:
        tab = layout.tabs.widget(layout._index["eq"])
        said = _copy_said(monkeypatch, window, tab)
        assert len(said) == 1 and "v_001" in said[0], said
    finally:
        layout.leave()


def test_the_tree_itself_shows_the_looked_at_version_also_after_a_language_change(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc import i18n

    window = _project_with_versions(tmp_path, monkeypatch)
    assert "-4.5dB" in _tree_text(window), "the fixture's HEAD"

    _pick(window, "v_001")
    assert "+0.0dB" in _tree_text(window) and "-4.5dB" not in _tree_text(window), "the tree, not just the table"

    before = i18n.current_language()
    i18n.set_language("en" if before == "uk" else "uk")
    window._retranslate()
    assert "+0.0dB" in _tree_text(window) and "-4.5dB" not in _tree_text(window), "after a language change too"
    i18n.set_language(before)
    window._retranslate()


def test_control_mode_opens_the_looked_at_values_and_its_list_says_so(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc import control_layout

    window = _project_with_versions(tmp_path, monkeypatch)
    monkeypatch.setattr(control_layout, "place_terminal_left", lambda *a, **k: None)
    monkeypatch.setattr(control_layout.MonitorFeed, "refresh", lambda self: None)
    _pick(window, "v_001")
    layout = window._control_layout
    layout.enter()
    try:
        row = window._find_group("physical_outputs").rows[0]
        window._on_channel_clicked("physical_outputs", row.id)  # the tree's click

        tab = layout.tabs.widget(layout._index["physical_outputs"])
        assert layout.tabs.currentWidget() is tab
        text = _table_text(tab)
        assert "+0.0" in text and "-4.5" not in text, "the table opened on what is looked at"
        combo = layout.compare_combo
        shown = [combo.itemText(i) for i in range(combo.count()) if combo.itemText(i).startswith("v_001")]
        assert shown and shown[0].endswith("shown"), "the mode's own list says it is looking"
    finally:
        layout.leave()


def test_a_preset_switch_goes_back_to_head(tmp_path, monkeypatch):
    window = _project_with_versions(tmp_path, monkeypatch)
    _pick(window, "v_001")

    window._preset_combo.setCurrentIndex(window._preset_combo.findData("SQ"))

    assert window._shown_mark.isHidden()
    assert window._view.preset == "SQ" and "-7.5" in _shown_text(window)


def test_a_version_of_another_slot_is_named_and_compared_from_that_slot(tmp_path, monkeypatch):
    window = _project_with_versions(tmp_path, monkeypatch)

    _pick(window, "v_001")
    window._shown_back.click()
    menu_row = "SQ/v_004"
    from autosound_tcc.ui.tcc import shown_version

    shown_version.show(window, menu_row)

    assert "-7.5" in _shown_text(window), "the other slot's values are on screen"
    assert "SQ" in window._shown_mark.text() and "not the current" in window._shown_mark.text()
    assert window._loaded_preset == "FULL" and window._view.version == "v_003", "HEAD did not move"
    args = window._compare_args
    assert args[5] == "SQ" and args[6] == "v_004", "the compare list is the shown slot's"


def test_compare_has_the_shown_view_on_the_left_and_never_itself(tmp_path, monkeypatch):
    window = _project_with_versions(tmp_path, monkeypatch)
    _pick(window, "v_002")

    combo = window._detail._compare_combo
    row = next(i for i in range(combo.count()) if combo.itemText(i).startswith("v_002"))
    assert not combo.model().item(row).isEnabled(), "a version is not compared with itself"
    assert combo.itemText(row).endswith("shown"), "greyed as what is shown, not as the current one"
    assert window._compare_key == "v_001", "the previous of the SHOWN one is the default"
    assert window._detail._compare_view is not None and window._detail._view.version == "v_002"
    # HEAD can be chosen against the shown version: the row of v_003 is an ordinary one.
    assert combo.findData("v_003") > 0


def test_control_mode_language_and_theme_keep_the_shown_version(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc import control_layout, i18n

    window = _project_with_versions(tmp_path, monkeypatch)
    monkeypatch.setattr(control_layout, "place_terminal_left", lambda *a, **k: None)
    monkeypatch.setattr(control_layout.MonitorFeed, "refresh", lambda self: None)
    _pick(window, "v_001")

    layout = window._control_layout
    layout.enter()
    try:
        tab = layout.tabs.widget(layout._index["physical_outputs"])
        assert "-4.5" not in _table_text(tab), "the tabs draw the shown version, too"
        assert not window._shown_mark.isHidden(), "the mark stays in control mode"
    finally:
        layout.leave()
    before = i18n.current_language()
    i18n.set_language("en" if before == "uk" else "uk")
    window._retranslate()
    window._apply_theme("light")
    i18n.set_language(before)
    window._retranslate()
    assert not window._shown_mark.isHidden(), "language and theme changes keep the shown version"
    assert "-4.5" not in _shown_text(window)
