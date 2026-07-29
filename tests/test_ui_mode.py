"""ui_mode: per-project view/control persistence (core/ui_mode.py, TCC-TZ.md §8)."""

from __future__ import annotations

import json

from autosound_tcc.core import ui_mode


def test_missing_file_defaults_to_view(tmp_path):
    assert ui_mode.get_mode(tmp_path) == "view"


def test_set_then_get_round_trips(tmp_path):
    ui_mode.set_mode(tmp_path, "control")
    assert ui_mode.get_mode(tmp_path) == "control"

    ui_mode.set_mode(tmp_path, "view")
    assert ui_mode.get_mode(tmp_path) == "view"


def test_set_mode_rejects_unknown_value(tmp_path):
    try:
        ui_mode.set_mode(tmp_path, "trc")  # type: ignore[arg-type]
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an unknown mode")


def test_writes_are_atomic_and_leave_no_temp_file(tmp_path):
    ui_mode.set_mode(tmp_path, "control")

    assert json.loads((tmp_path / "ui_mode.json").read_text(encoding="utf-8"))["mode"] == "control"
    assert not (tmp_path / "ui_mode.json.tmp").exists()


def test_corrupt_file_degrades_to_default_rather_than_raising(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "ui_mode.json").write_text("{ truncated", encoding="utf-8")

    assert ui_mode.get_mode(tmp_path) == "view"


def test_unknown_value_on_disk_degrades_to_default(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "ui_mode.json").write_text(json.dumps({"mode": "trc"}), encoding="utf-8")

    assert ui_mode.get_mode(tmp_path) == "view"
