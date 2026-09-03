"""Has this CABIN been described, and have we built on it? (`core/car_library.py`, SKL-020)

The matching rule is the method's and is exercised here through it, not re-implemented: a cabin is
`make / model / generation / body`, the year takes no part, and a platform sibling is never named.
What this module owns is the half the method cannot have — which project folders to look in.
"""

from __future__ import annotations

import json

import pytest

from autosound_tcc.core import car_library

pytestmark = pytest.mark.skipif(
    not car_library.available(), reason="the car library arrived with method v3.0.40"
)


def _project(root, name, car):
    """A project folder whose `project.json` says (or does not say) what car it is."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    body = {"schema_version": 3, "car": car}
    if car:
        body["acoustics"] = {"flaws": [
            {"f_hz": 160, "level_db": -12, "kind": "sbir", "action": "geometry",
             "evidence": ["m-FL_01 (sw)"]},
        ]}
    (folder / "project.json").write_text(json.dumps(body), encoding="utf-8")
    return folder


def test_the_library_answers_for_exactly_this_cabin(tmp_path):
    got = car_library.look_up("VW", "Passat", "B8", "sedan", dirs=[])

    assert got["slug"] == "vw-passat-b8-sedan"
    assert got["bundled_exact_match"]["slug"] == "vw-passat-b8-sedan"
    assert got["bundled_exact_match"]["path"].endswith("vw-passat-b8-sedan.md")


def test_a_near_miss_is_not_named_at_all(tmp_path):
    """The damage is not a wrong file being read — it is a wrong file being MENTIONED. "We have
    something for the Passat B7, want it?" is already the harm, because the answer will be yes:
    the same shell can carry different doors, glass and floor, and the numbers do not transfer."""
    got = car_library.look_up("VW", "Passat", "B7", "sedan", dirs=[])

    assert got["bundled_exact_match"] is None
    assert "b8" not in json.dumps(got).lower(), "no suggestion, no did-you-mean, no fallback"


def test_a_body_that_was_never_recorded_is_its_own_answer(tmp_path):
    """Three answers, and the third is the point. A project that cannot say what body it is is NOT
    a project on another body — folding it into "none" is how the material went missing for two
    days on the live intake (public `skill#19`), one floor down."""
    same = _project(tmp_path, "same", {"make": "VW", "model": "Passat",
                                       "generation": "B8", "body": "sedan"})
    other = _project(tmp_path, "wagon", {"make": "VW", "model": "Passat",
                                         "generation": "B8", "body": "wagon"})
    silent = _project(tmp_path, "silent", {"make": "VW", "model": "Passat B8", "year": 2018})

    got = car_library.look_up("VW", "Passat", "B8", "sedan", dirs=[same, other, silent])

    assert [m["path"] for m in got["prior_projects"]] == [str(same)]
    assert [u["path"] for u in got["unknown"]] == [str(silent)]
    assert "no body recorded" in got["unknown"][0]["why"]
    # And what is on offer, because that is the question the person answers: those captures live
    # in THAT project, so anything carried travels as a hypothesis.
    assert got["prior_projects"][0]["flaws"] == 1
    assert got["prior_projects"][0]["evidence"] == ["m-FL_01 (sw)"]


def test_the_year_describes_the_car_and_classifies_nothing(tmp_path):
    """A generation is already the span of years whose acoustics count as the same, so two builds
    of one generation and body are one cabin whether 2017 or 2018 (owner, 2026-09-03)."""
    older = _project(tmp_path, "2017", {"make": "VW", "model": "Passat", "generation": "B8",
                                        "body": "sedan", "year": 2017})
    newer = _project(tmp_path, "2018", {"make": "VW", "model": "Passat", "generation": "B8",
                                        "body": "sedan", "year": 2018})

    got = car_library.look_up("VW", "Passat", "B8", "sedan", dirs=[older, newer])

    assert len(got["prior_projects"]) == 2, "the year does not split one cabin into two"


def test_recording_a_car_is_what_makes_the_next_project_findable(tmp_path):
    """The round trip, and the reason the writer exists at all: the in-app interview has no Bash
    (`agent_session.BUILTIN_TOOLS` is empty), so without a tool a TCC-made project could never
    record a body — and would answer "no body recorded" for the rest of its life."""
    folder = _project(tmp_path, "new", {})

    before = car_library.look_up("VW", "Passat", "B8", "sedan", dirs=[folder])
    assert before["prior_projects"] == []

    car = car_library.record(folder, "VW", "Passat", "B8", "sedan", year=2018)

    assert car == {"make": "VW", "model": "Passat", "generation": "B8",
                   "body": "sedan", "year": 2018}
    after = car_library.look_up("VW", "Passat", "B8", "sedan", dirs=[folder])
    assert [m["path"] for m in after["prior_projects"]] == [str(folder)]


def test_an_empty_part_is_absent_rather_than_blank(tmp_path):
    """A blank `body` is the state the library calls "no body recorded"; storing `""` would make
    it read as a body named nothing, which is the kind of value that looks settled."""
    folder = _project(tmp_path, "half", {})

    car = car_library.record(folder, "VW", "Passat", "B8")

    assert "body" not in car and car["generation"] == "B8"
    saved = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    assert saved["car"] == car and saved["project_rev"] >= 1, "written through the method's writer"
