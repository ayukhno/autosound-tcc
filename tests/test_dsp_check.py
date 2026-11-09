"""«Checked in the DSP» on the «Порівняти з» rows and the header dot (#251): read as the person sees
it, over a real ledger on disk."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc import dsp_check, i18n, shown_version  # noqa: E402
from autosound_tcc.ui.tcc.detail_pane import DetailPane  # noqa: E402

HELIX = {"dsp_profile": {"vendor": "Audiotec-Fischer", "name": "Helix DSP Ultra S", "groups": []}}
OTHER = {"dsp_profile": {"vendor": "Musway", "name": "M6V4", "groups": []}}
PATH = "presets/2026-10-28_4F flat v.1.0.pct6 (md5 ee627ad6…) decoded read-only"
FULL_MD5 = "ee627ad6" + "0" * 24
PRESET = "1.N"


def _app():
    return QApplication.instance() or QApplication([])


def _bank(root, version, statuses=("applied", "applied"), **fields):
    folder = root / PRESET
    folder.mkdir(parents=True, exist_ok=True)
    channels = {f"ch-{i}": {"status": s} for i, s in enumerate(statuses)}
    path = folder / f"{version}.json"
    path.write_text(json.dumps(dict({"version": version, "preset": PRESET, "channels": channels,
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


def _head_view(version="v_001", state="applied"):
    return SimpleNamespace(version=version, state=state, preset=PRESET, status_counts=())


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
