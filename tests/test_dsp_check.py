"""«Checked in the DSP» on the «Порівняти з» rows and the header dot (#251): read as the person sees
it, over a real ledger on disk."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import pytest  # noqa: E402

from autosound_tcc.core import vendor_loader  # noqa: E402
from autosound_tcc.state import ledger_line  # noqa: E402
from autosound_tcc.ui.tcc import dsp_check, i18n, shown_version  # noqa: E402
from autosound_tcc.ui.tcc.detail_pane import DetailPane  # noqa: E402

from tests import _intake, _reads  # noqa: E402

HELIX = {"dsp_profile": {"vendor": "Audiotec-Fischer", "name": "Helix DSP Ultra S", "groups": []}}
OTHER = {"dsp_profile": {"vendor": "Musway", "name": "M6V4", "groups": []}}
PATH = "presets/2026-10-28_4F flat v.1.0.pct6 (md5 ee627ad6…) decoded read-only"
FULL_MD5 = "ee627ad6" + "0" * 24
PRESET = "1.N"


def _app():
    return QApplication.instance() or QApplication([])


def _bank(root, version, statuses=("applied", "applied"), preset=PRESET, **fields):
    folder = root / preset
    folder.mkdir(parents=True, exist_ok=True)
    channels = {f"ch-{i}": {"status": s} for i, s in enumerate(statuses)}
    path = folder / f"{version}.json"
    path.write_text(json.dumps(dict({"version": version, "preset": preset, "channels": channels,
                                     "created": "2026-10-28T11:27:00"}, **fields)),
                    encoding="utf-8")
    return path


def _with_file(file=PATH):
    return {"provenance": {"file": file}}


def _combo(root, profile=HELIX, current="v_009"):
    _app()
    i18n.set_language("en")
    pane = DetailPane()
    window = SimpleNamespace(_loaded_preset=PRESET, _detail=pane, _sync_status_dots=lambda: None,
                             _shown_key=None)
    shown_version.offer_compare(window, lambda *_a, **_k: None, root, PRESET, profile, current)
    return pane._compare_combo


def _control(root):
    """A version that does carry the mark, in the same list: what makes a «no mark» test mean it."""
    _bank(root, "v_050", provenance={"file": "presets/control.pct6 (md5 aaaaaaaa…) decoded read-only"})


def _row(combo, version):
    index = next(i for i in range(combo.count()) if combo.itemText(i).startswith(version))
    tip = combo.itemData(index, Qt.ItemDataRole.ToolTipRole)
    return (not combo.itemIcon(index).isNull()), (tip or "")


def test_a_version_with_every_row_entered_and_a_file_is_marked_and_says_the_file(tmp_path):
    _bank(tmp_path, "v_001", **_with_file())
    marked, hover = _row(_combo(tmp_path), "v_001")
    assert marked, "every channel entered and the file on record"
    assert "2026-10-28_4F flat v.1.0.pct6" in hover and "md5 ee627ad6…" in hover
    assert "28.10.2026 11:27" in hover, "the time it was recorded"
    assert "presets/" not in hover and "decoded read-only" not in hover and "{" not in hover
    assert "what the dsp holds now" in hover.lower(), "the mark is no claim about the DSP today"


def test_the_method_s_source_file_gives_the_file_its_own_time_and_no_home_path(tmp_path):
    _bank(tmp_path, "v_001", preset_settings={"input_gain_db": -1.0, "source_file": {
        "name": "5S.pct6", "path": "/Users/someone/presets/5S.pct6", "md5": FULL_MD5,
        "saved": "2026-11-02T09:15:00", "compared": "no difference"}})
    marked, hover = _row(_combo(tmp_path), "v_001")
    assert marked
    assert "5S.pct6" in hover and FULL_MD5 in hover and "saved 02.11.2026 09:15" in hover
    assert "/Users" not in hover and "someone" not in hover


def test_a_file_compared_and_found_different_is_no_mark(tmp_path):
    _bank(tmp_path, "v_001", preset_settings={"source_file": {
        "name": "5S.pct6", "md5": FULL_MD5, "compared": ["w-L gain differs"]}})
    _control(tmp_path)
    combo = _combo(tmp_path)
    assert _row(combo, "v_001") == (False, "") and _row(combo, "v_050")[0]


def test_a_partial_version_is_no_mark(tmp_path):
    _bank(tmp_path, "v_001", statuses=("applied", "proposed"), **_with_file())
    _control(tmp_path)
    combo = _combo(tmp_path)
    assert _row(combo, "v_001") == (False, "") and _row(combo, "v_050")[0]


def test_a_version_with_no_channels_is_no_mark(tmp_path):
    _bank(tmp_path, "v_001", statuses=(), **_with_file())
    _control(tmp_path)
    combo = _combo(tmp_path)
    assert _row(combo, "v_001") == (False, "") and _row(combo, "v_050")[0]


def test_a_version_with_no_file_is_no_mark(tmp_path):
    _bank(tmp_path, "v_001", provenance={"decision": "by ear"})
    _control(tmp_path)
    combo = _combo(tmp_path)
    assert _row(combo, "v_001") == (False, "") and _row(combo, "v_050")[0]


def test_the_hover_lists_every_file_with_the_same_content_and_no_other(tmp_path):
    _bank(tmp_path, "v_001", **_with_file())
    _bank(tmp_path, "v_002", preset_settings={"source_file": {
        "name": "re-saved.pct6", "md5": FULL_MD5, "saved": "2026-11-02T09:15:00"}})
    _bank(tmp_path, "v_003", **_with_file("presets/other.pct6 (md5 f367e0d1…) decoded read-only"))
    _marked, hover = _row(_combo(tmp_path), "v_001")
    assert "2026-10-28_4F flat v.1.0.pct6" in hover and "re-saved.pct6" in hover
    assert "other.pct6" not in hover, "another md5 is another content"


def test_two_records_of_different_content_on_one_version_are_no_mark(tmp_path):
    _bank(tmp_path, "v_001", provenance={"file": PATH}, preset_settings={"source_file": {
        "name": "other.pct6", "md5": "f367e0d1" + "0" * 24}})
    _control(tmp_path)
    combo = _combo(tmp_path)
    assert _row(combo, "v_001") == (False, "") and _row(combo, "v_050")[0]


def test_a_dsp_whose_file_cannot_be_read_shows_no_mark(tmp_path):
    _bank(tmp_path, "v_001", **_with_file())
    assert _row(_combo(tmp_path, profile=OTHER), "v_001") == (False, "")
    assert _row(_combo(tmp_path), "v_001")[0], "the same version on the Helix"


def test_the_row_of_the_version_on_screen_carries_the_mark_too(tmp_path):
    _bank(tmp_path, "v_001", **_with_file())
    marked, hover = _row(_combo(tmp_path, current="v_001"), "v_001")
    assert marked and "md5 ee627ad6…" in hover


def test_a_provenance_written_after_the_version_is_seen(tmp_path):
    path = _bank(tmp_path, "v_001", provenance={"decision": "by ear"})
    assert _row(_combo(tmp_path), "v_001") == (False, "")
    stat = path.stat()
    _bank(tmp_path, "v_001", **_with_file())
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert _row(_combo(tmp_path), "v_001")[0], "the cache kept the file as it was first read"


@pytest.mark.parametrize("sentence", [
    "presets/a.pct6 not found on disk",
    "could not read my.pct6 at all",
    "entered by hand from Helix v1.10 notes",
    "checked on the screens on 28.10.2026 by ear",
    "a.pct6 differs from the device (md5 ee627ad6)",
    "a.pct6 differs from b.pct6 (md5 ee627ad6)",
    "not found: presets/a.pct6",
    "presets/a.pct6 (md5 nothex)",
    "presets/a.pct6 (md5 ee627ad6…) but a word follows it",
])
def test_a_sentence_counts_only_in_the_shape_the_ledgers_write(tmp_path, sentence):
    _bank(tmp_path, "v_001", provenance={"file": sentence})
    _control(tmp_path)
    combo = _combo(tmp_path)
    assert _row(combo, "v_001") == (False, ""), sentence
    assert _row(combo, "v_050")[0]


@pytest.mark.parametrize("sentence", [
    "presets/2026-10-28_4F flat v.1.0.pct6 (md5 ee627ad6…) decoded read-only",
    "a.pct6 (md5 ee627ad6…)",
    "a.pct6 (md5 ee627ad6)",
])
def test_the_real_sentence_shapes_keep_their_mark(tmp_path, sentence):
    _bank(tmp_path, "v_001", provenance={"file": sentence})
    marked, hover = _row(_combo(tmp_path), "v_001")
    assert marked and "ee627ad6" in hover
    assert "(md5" not in hover and "decoded" not in hover


@pytest.mark.parametrize("record", [
    {"name": "a.pct6", "md5": "unknown"},
    {"name": "a.pct6", "md5": ""},
    {"name": "a.pct6"},
    {"name": "", "md5": FULL_MD5},
    {"name": "   ", "md5": FULL_MD5},
    {"md5": FULL_MD5},
    {"path": "/presets/", "md5": FULL_MD5},
])
def test_a_record_counts_only_with_a_real_md5_and_a_real_name(tmp_path, record):
    _bank(tmp_path, "v_001", preset_settings={"source_file": record})
    _control(tmp_path)
    combo = _combo(tmp_path)
    assert _row(combo, "v_001") == (False, ""), record
    assert _row(combo, "v_050")[0]


@pytest.mark.parametrize("value", [False, "false", "False", 0])
def test_verified_by_file_false_in_any_form_vetoes_the_version(tmp_path, value):
    """Even with a good record beside it: the ledger itself says this was not read back."""
    _bank(tmp_path, "v_001", provenance={"file": PATH, "verified_by_file": value},
          preset_settings={"source_file": {"name": "ok.pct6", "md5": FULL_MD5}})
    _control(tmp_path)
    combo = _combo(tmp_path)
    assert _row(combo, "v_001") == (False, ""), value
    assert _row(combo, "v_050")[0]


@pytest.mark.parametrize("compared", [["w-L gain differs"], "w-L gain differs", "differs", 0, False])
def test_a_compared_that_is_no_statement_of_no_difference_vetoes_the_version(tmp_path, compared):
    """Even with a good record beside it."""
    _bank(tmp_path, "v_001", provenance={"file": PATH},
          preset_settings={"source_file": {"name": "ok.pct6", "md5": "ee627ad6" + "0" * 24,
                                           "compared": compared}})
    _control(tmp_path)
    combo = _combo(tmp_path)
    assert _row(combo, "v_001") == (False, ""), compared
    assert _row(combo, "v_050")[0]


@pytest.mark.parametrize("compared", ["no difference", " No Difference ", [], "", None])
def test_no_difference_written_or_nothing_compared_keeps_the_mark(tmp_path, compared):
    _bank(tmp_path, "v_001", preset_settings={"source_file": {
        "name": "a.pct6", "md5": FULL_MD5, "compared": compared}})
    assert _row(_combo(tmp_path), "v_001")[0], compared


def test_the_saved_time_rc1_writes_is_read(tmp_path):
    _bank(tmp_path, "v_001", preset_settings={"source_file": {
        "name": "5S.pct6", "md5": "46f99511aa", "saved": "291020261232",
        "read_at": "2026-11-08T20:00:00", "compared": "no difference"}})
    _marked, hover = _row(_combo(tmp_path), "v_001")
    assert "saved 29.10.2026 12:32" in hover


def test_a_project_line_ledger_finds_the_same_content_files(tmp_path):
    versions = tmp_path / "versions"
    versions.mkdir()
    (tmp_path / "slots.json").write_text(json.dumps({"slots": {PRESET: {"version": "v_002"}}}), encoding="utf-8")
    channels = {"ch-0": {"status": "applied"}}
    for version, name in (("v_001", "first.pct6"), ("v_002", "re-saved.pct6")):
        (versions / f"{version}.json").write_text(json.dumps(
            {"version": version, "preset": PRESET, "channels": channels, "created": "2026-10-28T11:27:00",
             "preset_settings": {"source_file": {"name": name, "md5": FULL_MD5}}}), encoding="utf-8")
    marked, hover = _row(_combo(tmp_path, current="v_002"), "v_001")
    assert marked and "first.pct6" in hover and "re-saved.pct6" in hover


def test_a_proposed_row_on_another_tier_takes_the_mark_away(tmp_path):
    _bank(tmp_path, "v_001", virtual_channels={"v-L": {"status": "proposed"}}, **_with_file())
    _control(tmp_path)
    combo = _combo(tmp_path)
    assert _row(combo, "v_001") == (False, "") and _row(combo, "v_050")[0]


def test_measured_rows_count_as_entered(tmp_path):
    _bank(tmp_path, "v_001", statuses=("applied", "measured"), **_with_file())
    assert _row(_combo(tmp_path), "v_001")[0]


def test_keys_of_the_method_that_are_not_tiers_do_not_stop_the_mark(tmp_path):
    _bank(tmp_path, "v_001", banked_ear_verdicts={"v_000": {"status": "proposed"}},
          virtual_eq_ptr={"v-L": {"status": "proposed"}}, **_with_file())
    assert _row(_combo(tmp_path), "v_001")[0]


def test_other_slots_rows_get_their_marks_and_hovers(tmp_path):
    _bank(tmp_path, "v_001", **_with_file())
    _bank(tmp_path, "v_007", preset="SQ", provenance={"file": "presets/sq.pct6 (md5 bbbbbbbb…)"})
    marked, hover = _row(_combo(tmp_path), "v_007")
    assert marked and "sq.pct6" in hover


def test_a_helix_is_told_by_vendor_as_well_as_by_name(tmp_path):
    _bank(tmp_path, "v_001", **_with_file())
    vendor_only = {"dsp_profile": {"vendor": "Audiotec-Fischer", "name": "DSP Ultra", "groups": []}}
    assert _row(_combo(tmp_path, profile=vendor_only), "v_001")[0]


def test_a_view_with_no_preset_uses_the_loaded_slot_or_says_nothing(tmp_path):
    """An old layout's `view.preset` may be null, and `_retranslate` has no guard around this."""
    i18n.set_language("en")
    _bank(tmp_path, "v_001", **_with_file())
    nameless = _head_view(preset=None)
    assert dsp_check.header(tmp_path, nameless, HELIX, "tip") == ("done", "tip"), "no raise, no mark"
    assert dsp_check.header(tmp_path, nameless, HELIX, "tip", PRESET)[0] == "checked"


def _head_view(version="v_001", state="applied", preset=PRESET):
    return SimpleNamespace(version=version, state=state, preset=preset, status_counts=())


def test_the_header_dot_is_marked_and_its_hover_names_the_file(tmp_path):
    i18n.set_language("en")
    _bank(tmp_path, "v_001", **_with_file())
    dot, tip = dsp_check.header(tmp_path, _head_view(), HELIX, "plain tip <1>")
    assert dot == "checked"
    assert "plain tip &lt;1&gt;" in tip and "md5 ee627ad6…" in tip


def test_the_header_dot_stays_as_it_was_without_the_mark(tmp_path):
    _bank(tmp_path, "v_002", **_with_file())
    assert dsp_check.header(tmp_path, _head_view("v_002"), HELIX, "tip")[0] == "checked"
    _bank(tmp_path, "v_001", provenance={"decision": "by ear"})
    assert dsp_check.header(tmp_path, _head_view(), HELIX, "tip") == ("done", "tip")
    assert dsp_check.header(tmp_path, _head_view(state="proposed"), HELIX, "t") == ("wait", "t")
    assert dsp_check.header(tmp_path, _head_view(state=None), HELIX, "t") == (None, "t")
    _bank(tmp_path, "v_001", **_with_file())
    assert dsp_check.header(tmp_path, _head_view(), OTHER, "tip") == ("done", "tip")


# ---- «In the DSP now»: the method's `slots[slot].loaded`, a separate fact ----------------------


def _method_line(project, files=(None, None)):
    """FULL at v_003 with v_001 and v_002 behind it, one line per project, through the method's writers."""
    _intake.seed(project)
    root = project / "state"
    history = vendor_loader.load_dsp_state().PresetHistory(str(root), "FULL", project_dir=str(project))
    for file in files:
        history.snapshot({"preset": "FULL", "sample_rate": 96000, "note": "fixture",
                          "provenance": {"file": file} if file else {"decision": "by ear"},
                          "channels": {"w-L": {"hp": None, "lp": None, "gain_db": -1.5, "ta_ms": 1.5,
                                               "polarity": "NORM", "status": "applied"}}})
    return root, history


def _line_combo(root, current="v_003", profile=HELIX):
    _app()
    i18n.set_language("en")
    pane = DetailPane()
    window = SimpleNamespace(_loaded_preset="FULL", _detail=pane, _sync_status_dots=lambda: None,
                             _shown_key=None)
    shown_version.offer_compare(window, lambda *_a, **_k: None, root, "FULL", profile, current)
    return pane._compare_combo


def _text_of(combo, version):
    return next(combo.itemText(i) for i in range(combo.count()) if combo.itemText(i).startswith(version))


def test_the_green_mark_and_in_the_dsp_are_told_apart_on_a_row(tmp_path):
    """Either, or both: the tick is «checked», the words are «in the DSP», the hover says each."""
    root, history = _method_line(tmp_path, ("presets/a.pct6 (md5 ee627ad6…)", None))
    # v_002 is checked, v_003 is not; the DSP holds v_002.
    history.record_loaded("v_002", "a.pct6 read back")
    combo = _line_combo(root)
    assert _row(combo, "v_002")[0], "the tick stands: it is the version's own fact"
    assert "in the DSP" in _text_of(combo, "v_002"), "the words are the other fact"
    hover = _row(combo, "v_002")[1]
    assert "md5 ee627ad6…" in hover and "a.pct6 read back" in hover

    history.record_loaded("v_003", "loaded in the PC tool")
    combo = _line_combo(root)
    assert "in the DSP" in _text_of(combo, "v_003") and not _row(combo, "v_003")[0], "the words alone"
    assert _row(combo, "v_002")[0] and "in the DSP" not in _text_of(combo, "v_002"), "the tick alone"
    assert "md5" not in _row(combo, "v_003")[1], "a claim names no file it was not checked against"


def test_a_row_of_another_dsp_says_in_the_dsp_too(tmp_path):
    """`loaded` is the method's on any DSP; the green mark is the Helix's only."""
    root, history = _method_line(tmp_path)
    history.record_loaded("v_002", "loaded in the PC tool")
    combo = _line_combo(root, profile=OTHER)
    assert "in the DSP" in _text_of(combo, "v_002") and not _row(combo, "v_002")[0]


@pytest.mark.parametrize("loaded", [
    "v_002", None, 7, [], {},
    {"version": "v_099", "since": "2026-11-09T10:00:00", "source": "x"},  # no such version
    {"version": "nonsense", "since": "2026-11-09T10:00:00", "source": "x"},
    {"version": 2, "since": "2026-11-09T10:00:00", "source": "x"},
    {"version": "v_002", "source": "x"},
    {"version": "v_002", "since": "yesterday", "source": "x"},
    {"version": "v_002", "since": "2026-11-09T10:00:00"},
    {"version": "v_002", "since": "2026-11-09T10:00:00", "source": "  "},
    {"version": "v_002", "since": "2026-11-09T10:00:00", "source": 5},
])
def test_a_loaded_field_that_cannot_be_believed_is_no_claim_and_no_crash(tmp_path, loaded):
    root, _history = _method_line(tmp_path)
    data = json.loads((root / "slots.json").read_text(encoding="utf-8"))
    data["slots"]["FULL"]["loaded"] = loaded
    (root / "slots.json").write_text(json.dumps(data), encoding="utf-8")
    combo = _line_combo(root)
    assert all("in the DSP" not in combo.itemText(i) for i in range(combo.count())), loaded
    assert ledger_line.loaded_in_dsp(root, "FULL") is None


def test_the_slots_file_is_read_once_and_a_change_is_seen(tmp_path, monkeypatch):
    """Asked on the GUI thread at every reload, like a version file (#172)."""
    root, history = _method_line(tmp_path)
    history.record_loaded("v_002", "first")
    opened = _reads.opened_under(monkeypatch, tmp_path)
    assert ledger_line.loaded_in_dsp(root, "FULL").version == "v_002"
    assert ledger_line.loaded_in_dsp(root, "FULL").source == "first"
    assert [o for o in opened if o.endswith("slots.json")] == [str(root / "slots.json")], "read once"

    history.record_loaded("v_001", "read back from the device")
    claim = ledger_line.loaded_in_dsp(root, "FULL")
    assert (claim.version, claim.source) == ("v_001", "read back from the device")
