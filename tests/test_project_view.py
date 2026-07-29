"""Reading the skill's `project.json` into the left panel's System/Project-params shapes
(state/project_view.py, SCR-015/016). No vendored submodule needed -- this is plain JSON reading.
"""

from __future__ import annotations

import json

from autosound_tcc.state import project_view


def _write(project_dir, data):
    (project_dir / "project.json").write_text(json.dumps(data), encoding="utf-8")


def test_no_project_json_reads_as_empty_everywhere(tmp_path):
    assert project_view.has_project(tmp_path) is False
    assert project_view.load_system_params(tmp_path) == ()
    assert project_view.load_channel_summary(tmp_path) == ()
    assert project_view.load_open_questions(tmp_path) == ()


def test_system_params_only_renders_facts_actually_present(tmp_path):
    _write(tmp_path, {
        "dsp": {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"},
        "amps": [{"role": "front", "make": "Helix", "model": "P Six DSP"}, {"role": "sub"}],
        "mic": {"model": "UMIK-1"},
        "source": {},
    })
    rows = project_view.load_system_params(tmp_path)
    assert ("DSP", "Audiotec-Fischer Helix DSP Ultra S") in rows
    assert ("Amp (front)", "Helix P Six DSP") in rows
    assert ("Mic", "UMIK-1") in rows
    # an amp with no make/model, and an empty source block, contribute no row -- not blank ones.
    assert not any(label == "Amp (sub)" for label, _ in rows)
    assert not any(label == "Source" for label, _ in rows)


def test_channel_summary_renders_total_and_off(tmp_path):
    _write(tmp_path, {
        "channel_summary": {
            "virtual_channels": {"total": 8, "off": 1},
            "channels": {"total": 12, "off": 0},
        }
    })
    rows = dict(project_view.load_channel_summary(tmp_path))
    assert rows["Virtual channels"] == "8 (1 off)"
    assert rows["Channels"] == "12"  # off=0 -> no "(0 off)" noise


def test_open_questions_passthrough(tmp_path):
    _write(tmp_path, {"_open_questions": ["mic.calibration_file", "amps.0.gain_db"]})
    assert project_view.load_open_questions(tmp_path) == (
        "mic.calibration_file", "amps.0.gain_db",
    )


def test_has_project_true_once_the_file_exists(tmp_path):
    _write(tmp_path, {})
    assert project_view.has_project(tmp_path) is True
