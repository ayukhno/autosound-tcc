"""What the new-project dialog assumes about seeding — checked against the method's own module.

The seeding itself is `rew_tool/project_seed.py` and is tested there, with a `--selftest` and a
CLI, because the classification of what travels is a statement about the project schema and the
schema is the method's. This file is deliberately NOT a second copy of that suite. It is the
short list of promises the WINDOW is built on, exercised through `vendor_loader` — the seam a pin
bump moves under us:

* the installation travels and the tune does not (`new_project_dialog` offers no way to filter it);
* the findings are off unless the checkbox is ticked;
* `PROFILE_FILE in written` is what the dialog reads to decide whether the DSP interview still has
  anything to ask;
* a refusal comes back as a `problem` sentence, because the dialog prints it and stops;
* `describe()` / `dsp_of()` answer for a folder while somebody is still typing its path;
* `profile_open` is a number the status line can say out loud.

If a future skill version changes any of those, this repository goes red rather than the window
going quietly wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autosound_tcc.core import vendor_loader


@pytest.fixture
def seeder():
    try:
        return vendor_loader.load_project_seed()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"the skill's project_seed is not in this checkout: {exc}")


def _source(root: Path) -> Path:
    """A project on disk with facts, prose, and a tune around them to leave behind."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.json").write_text(json.dumps({
        "schema_version": 3,
        "project_rev": 95,
        "sources": ["user, confirmed at intake 2026-07-20"],
        "car": {"make": "VW", "model": "Passat B8", "year": 2019},
        "dsp": {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"},
        "amps": [{"role": "front", "make": "Helix", "model": "P Six DSP"}],
        "mic": {"model": "UMIK-1"},
        "glossary": {"w": "woofer"},
        "presets": ["FULL"],
        "channels": [
            {"code": "w-L", "slot": "C", "role": "woofer", "tier": "channels"},
            {"code": "sw", "slot": "A", "role": "sub", "tier": "channels"},
        ],
        "paths": {"measurements_repo": "/corpus/vw-passat-b8",
                  "rew_project": "new-logic-EPY.mdat"},
        "acoustics": {"flaws": [{
            "kind": "cabin_null", "channels": ["sw"], "f_hz": 32.0, "level_db": -4.1,
            "q": None, "bw_oct": None, "action": "leave", "at": "2026-08-21T16:45:21+00:00",
            "why": "measured in MMM", "evidence": ["sw_01 (rta)"],
        }]},
        "_open_questions": ["amp gains are not written down as numbers"],
    }), encoding="utf-8")
    (root / "dsp_profile.json").write_text(json.dumps({"dsp_profile": {
        "vendor": "Audiotec-Fischer", "name": "Helix DSP Ultra S",
        "_open_questions": ["the channel-gain step is not verified"],
    }}), encoding="utf-8")
    (root / "autosound_context.md").write_text("# Профіль системи\n\nПасат.\n", encoding="utf-8")
    (root / "preference-profile.md").write_text("# Смаки\n\nБас.\n", encoding="utf-8")
    (root / "state" / "FULL").mkdir(parents=True)
    (root / "state" / "FULL" / "v_001.json").write_text("{}", encoding="utf-8")
    (root / "process").mkdir()
    (root / ".tcc").mkdir()
    return root


def test_the_installation_travels_and_the_tune_stays_behind(seeder, tmp_path):
    source, target = _source(tmp_path / "old"), tmp_path / "new"

    report = seeder.seed(source, target)

    assert report.ok, report.problem
    assert report.channels == 2 and report.amps == 1
    assert report.written == [
        "project.json", "dsp_profile.json", "autosound_context.md", "preference-profile.md",
    ]
    seeded = json.loads((target / "project.json").read_text(encoding="utf-8"))
    original = json.loads((source / "project.json").read_text(encoding="utf-8"))
    for key in ("car", "dsp", "amps", "mic", "channels", "glossary", "presets"):
        assert seeded[key] == original[key]
    # The new project counts its own writes, and takes only the path that addresses the car.
    assert seeded["project_rev"] == 1
    assert seeded["paths"] == {"measurements_repo": "/corpus/vw-passat-b8"}
    for left in ("state", "process", ".tcc"):
        assert not (target / left).exists()


def test_findings_are_offered_and_off(seeder, tmp_path):
    """The dialog's one checkbox. These were measured in the OTHER project and cite evidence that
    exists only there, so a default-on would build a project citing what it cannot show."""
    source = _source(tmp_path / "old")

    without = seeder.seed(source, tmp_path / "a")
    with_them = seeder.seed(source, tmp_path / "b", include_findings=True)

    quiet = json.loads((tmp_path / "a" / "project.json").read_text(encoding="utf-8"))
    assert "acoustics" not in quiet and "_open_questions" not in quiet
    assert without.flaws == 0 and without.questions == 0
    loud = json.loads((tmp_path / "b" / "project.json").read_text(encoding="utf-8"))
    assert loud["acoustics"]["flaws"][0]["f_hz"] == 32.0
    assert with_them.flaws == 1 and with_them.questions == 1


def test_the_profile_travels_only_when_it_is_the_same_dsp(seeder, tmp_path):
    """`PROFILE_FILE in written` is exactly what the dialog reads to decide whether the capability
    interview still has anything to ask. Same processor: nothing to ask. Different one: its
    capabilities are a question, not a file to inherit."""
    source = _source(tmp_path / "old")

    same = seeder.seed(source, tmp_path / "same")
    other = seeder.seed(source, tmp_path / "other", copy_profile=False)

    assert seeder.PROFILE_FILE in same.written
    assert (tmp_path / "same" / seeder.PROFILE_FILE).is_file()
    assert seeder.PROFILE_FILE not in other.written
    assert not (tmp_path / "other" / seeder.PROFILE_FILE).exists()
    assert json.loads((tmp_path / "other" / "project.json").read_text(encoding="utf-8"))["channels"]


def test_an_inherited_profile_says_how_much_of_it_is_still_open(seeder, tmp_path):
    """A profile can be inherited AND incomplete, and a `null` that looks settled is the failure
    mode. The count is of the COPY, so `--no-profile` reports none rather than a remembered number.
    """
    source = _source(tmp_path / "old")

    same = seeder.seed(source, tmp_path / "same")
    other = seeder.seed(source, tmp_path / "other", copy_profile=False)

    # Not an exact number: what counts as an open fact is `dsp_profile.open_questions()`'s to
    # decide, and it counts the stated ones AND the limits a profile leaves unsaid. What the
    # status line needs is only that an inherited profile can report some, and that a project
    # which inherited none reports none.
    assert same.profile_open >= 1
    assert other.profile_open == 0


def test_a_refusal_comes_back_as_a_sentence_the_dialog_can_print(seeder, tmp_path):
    """Seeding is the first act of a new project. Overwriting facts somebody already confirmed is
    the one outcome nobody could want, so it stops -- and says why, in one line."""
    source, target = _source(tmp_path / "old"), tmp_path / "new"
    target.mkdir()
    (target / "project.json").write_text('{"schema_version": 3, "mine": true}', encoding="utf-8")

    report = seeder.seed(source, target)

    assert not report.ok and report.problem
    assert json.loads((target / "project.json").read_text(encoding="utf-8"))["mine"] is True


def test_the_picker_can_ask_a_folder_what_it_is_before_anything_is_copied(seeder, tmp_path):
    """Answered while the path is still being typed, so it must be a plain "no" for a folder that
    is not a project -- never an exception inside a dialog."""
    source = _source(tmp_path / "old")
    empty = tmp_path / "not-a-project"
    empty.mkdir()
    (empty / "project.json").write_text("{ this is not json", encoding="utf-8")

    summary = seeder.describe(source)
    assert summary.car == "VW Passat B8 2019"
    assert summary.dsp == "Audiotec-Fischer Helix DSP Ultra S"
    assert summary.channels == 2
    # The exact pair the bundled-profile match is made on, no fuzzy matching anywhere.
    assert seeder.dsp_of(source) == ("Audiotec-Fischer", "Helix DSP Ultra S")

    assert seeder.describe(tmp_path / "nowhere") is None
    assert seeder.describe(empty) is None
    assert seeder.dsp_of(empty) is None
