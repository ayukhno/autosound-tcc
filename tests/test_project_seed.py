"""Seeding a new project from an existing one: what travels, and what must not.

"Each next project demands a full description — and that should not have to be done" (the user,
via the cockpit, 2026-08-23). The car has not changed between projects; the tune has. So these
tests are mostly about the SECOND half of that: a seeded project must arrive with the
installation and without one line of the other project's tuning.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from autosound_tcc.core import project_seed


def _source(root: Path, **overrides) -> Path:
    """A project on disk with facts, prose, and a tune around them to leave behind."""
    root.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 3,
        "project_rev": 95,
        "sources": ["user, confirmed at intake 2026-07-20"],
        "car": {"make": "VW", "model": "Passat B8", "year": 2019},
        "source": {"head_unit": "OEM"},
        "dsp": {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"},
        "amps": [{"role": "front", "make": "Helix", "model": "P Six DSP"}],
        "mic": {"model": "UMIK-1"},
        "hardware": {"controls": {"RTC": {"value": "off", "source": "measured"}}},
        "glossary": {"w": "woofer"},
        "channel_summary": {"channels": {"off": 2, "total": 12}},
        "presets": ["FULL"],
        "channels": [
            {"code": "w-L", "slot": "C", "role": "woofer", "tier": "channels"},
            {"code": "sw", "slot": "A", "role": "sub", "tier": "channels"},
        ],
        "paths": {
            "measurements_repo": "/corpus/vw-passat-b8",
            "rew_project": "new-logic-EPY.mdat",
            "baseline_set": "2026-08-20_front-set-02",
        },
        "acoustics": {"flaws": [{
            "kind": "cabin_null", "channels": ["sw"], "f_hz": 32.0, "level_db": -4.1,
            "q": None, "bw_oct": None, "action": "leave", "at": "2026-08-21T16:45:21+00:00",
            "why": "measured in MMM", "evidence": ["sw_01 (rta)"],
        }]},
        "_open_questions": ["amp gains are not written down as numbers"],
    }
    data.update(overrides)
    (root / "project.json").write_text(json.dumps(data), encoding="utf-8")
    (root / "dsp_profile.json").write_text(
        json.dumps({"dsp_profile": {"vendor": "Audiotec-Fischer", "name": "Helix DSP Ultra S"}}),
        encoding="utf-8",
    )
    (root / "autosound_context.md").write_text(
        "# Профіль системи\n\nПасат, три підсилювачі.\n", encoding="utf-8"
    )
    (root / "preference-profile.md").write_text("# Смаки\n\nБас.\n", encoding="utf-8")
    # The tune. None of this is a fact about the car.
    (root / "state" / "FULL").mkdir(parents=True)
    (root / "state" / "FULL" / "v_001.json").write_text("{}", encoding="utf-8")
    (root / "process").mkdir()
    (root / "process" / "process-state.json").write_text("{}", encoding="utf-8")
    (root / "journal").mkdir()
    (root / "rew_analitic").mkdir()
    (root / ".tcc").mkdir()
    (root / ".tcc" / "tcc-project.json").write_text("{}", encoding="utf-8")
    return root


def test_the_installation_travels_and_the_tune_stays_behind(tmp_path):
    source, target = _source(tmp_path / "old"), tmp_path / "new"

    report = project_seed.seed(source, target, today=date(2026, 8, 23))

    assert report.ok, report.problem
    assert report.channels == 2 and report.amps == 1
    assert report.written == [
        "project.json", "dsp_profile.json", "autosound_context.md", "preference-profile.md",
    ]
    seeded = json.loads((target / "project.json").read_text(encoding="utf-8"))
    for key in ("car", "dsp", "amps", "mic", "hardware", "channels", "glossary", "presets"):
        assert seeded[key] == json.loads((source / "project.json").read_text())[key]
    # Not by an exclusion list -- these are simply never reached, which is why a file class the
    # method adds tomorrow also stays behind.
    for left in ("state", "process", "journal", "rew_analitic", ".tcc"):
        assert not (target / left).exists()


def test_the_new_project_counts_its_own_writes(tmp_path):
    """`project_rev` counts writes to THIS file. Inheriting 95 would have the new project claim a
    history of changes it was not part of, and every ledger snapshot joins on that number."""
    source, target = _source(tmp_path / "old"), tmp_path / "new"

    project_seed.seed(source, target)

    assert json.loads((target / "project.json").read_text(encoding="utf-8"))["project_rev"] == 1


def test_the_facts_keep_their_provenance_and_say_they_were_inherited(tmp_path):
    """Dropping `sources` would leave the new project asserting a driver's Fs with no record of
    where the number came from -- worse than saying it was inherited."""
    source, target = _source(tmp_path / "old"), tmp_path / "new"

    project_seed.seed(source, target, today=date(2026, 8, 23))

    sources = json.loads((target / "project.json").read_text(encoding="utf-8"))["sources"]
    assert sources[0] == "user, confirmed at intake 2026-07-20"
    assert "seeded from project 'old' on 2026-08-23" in sources[-1]
    assert "not re-measured" in sources[-1]


def test_only_the_path_that_addresses_the_car_travels(tmp_path):
    """`measurements_repo` is the corpus for this vehicle; `rew_project` and `baseline_set` name
    a file and a capture belonging to the project that was left behind."""
    source, target = _source(tmp_path / "old"), tmp_path / "new"

    project_seed.seed(source, target)

    paths = json.loads((target / "project.json").read_text(encoding="utf-8"))["paths"]
    assert paths == {"measurements_repo": "/corpus/vw-passat-b8"}


def test_findings_are_offered_and_off(tmp_path):
    """The 32 Hz null is a fact about the cabin, and the entry recording it cites `sw_01 (rta)` --
    a measurement that does not exist in the new project. So: never by default, never silently."""
    source = _source(tmp_path / "old")

    without = project_seed.seed(source, tmp_path / "a")
    with_them = project_seed.seed(source, tmp_path / "b", include_findings=True)

    quiet = json.loads((tmp_path / "a" / "project.json").read_text(encoding="utf-8"))
    assert "acoustics" not in quiet and "_open_questions" not in quiet
    assert without.flaws == 0 and without.questions == 0

    loud = json.loads((tmp_path / "b" / "project.json").read_text(encoding="utf-8"))
    assert loud["acoustics"]["flaws"][0]["f_hz"] == 32.0
    assert with_them.flaws == 1 and with_them.questions == 1


def test_a_different_dsp_leaves_its_capabilities_behind(tmp_path):
    """Same doors, same drivers, new processor: everything about the car still travels, but a
    `dsp_profile.json` describing the OLD processor would be a lie the gates then enforce."""
    source, target = _source(tmp_path / "old"), tmp_path / "new"

    report = project_seed.seed(source, target, copy_profile=False)

    assert report.ok
    assert "dsp_profile.json" not in report.written
    assert not (target / "dsp_profile.json").exists()
    assert json.loads((target / "project.json").read_text(encoding="utf-8"))["channels"]


def test_the_prose_says_it_was_inherited_without_losing_its_title(tmp_path):
    source, target = _source(tmp_path / "old"), tmp_path / "new"

    project_seed.seed(source, target, today=date(2026, 8, 23))

    lines = (target / "autosound_context.md").read_text(encoding="utf-8").split("\n")
    assert lines[0] == "# Профіль системи"
    assert lines[2].startswith("> ") and "`old`" in lines[2] and "2026-08-23" in lines[2]
    assert "Пасат, три підсилювачі." in "\n".join(lines)


def test_it_refuses_a_folder_that_is_already_a_project(tmp_path):
    """Seeding is the first act of a new project. Overwriting facts somebody already confirmed
    is the one outcome nobody could want, so it stops rather than merges."""
    source, target = _source(tmp_path / "old"), tmp_path / "new"
    target.mkdir()
    (target / "project.json").write_text('{"schema_version": 3, "mine": true}', encoding="utf-8")

    report = project_seed.seed(source, target)

    assert not report.ok and "already has a project.json" in (report.problem or "")
    assert json.loads((target / "project.json").read_text(encoding="utf-8"))["mine"] is True


def test_seeding_a_folder_from_itself_is_refused(tmp_path):
    source = _source(tmp_path / "old")

    report = project_seed.seed(source, source)

    assert not report.ok
    assert json.loads((source / "project.json").read_text(encoding="utf-8"))["project_rev"] == 95


def test_a_folder_that_is_not_a_project_answers_before_anything_is_copied(tmp_path):
    """The picker asks this while the person is still typing the path, so it must be a plain
    "no" -- not an exception in a dialog."""
    empty = tmp_path / "not-a-project"
    empty.mkdir()
    (empty / "project.json").write_text("{ this is not json", encoding="utf-8")

    assert project_seed.describe(tmp_path / "nowhere") is None
    assert project_seed.describe(empty) is None
    assert project_seed.dsp_of(empty) is None
    assert not project_seed.seed(empty, tmp_path / "new").ok


def test_describe_and_dsp_of_read_the_project_a_picker_shows(tmp_path):
    source = _source(tmp_path / "old")

    summary = project_seed.describe(source)

    assert summary is not None
    assert summary.car == "VW Passat B8 2019"
    assert summary.dsp == "Audiotec-Fischer Helix DSP Ultra S"
    assert summary.channels == 2
    # The exact pair the bundled-profile match is made on, no fuzzy matching anywhere.
    assert project_seed.dsp_of(source) == ("Audiotec-Fischer", "Helix DSP Ultra S")
