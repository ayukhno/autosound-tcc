"""Has this CABIN been described, and have we built on it? (`core/car_library.py`, SKL-020)

The matching rule is the method's and is exercised here through it, not re-implemented: a cabin is
`make / model / generation / body`, the year takes no part, and a platform sibling is never named.
What this module owns is the half the method cannot have — which project folders to look in. The
car itself is written by the method's own `intake.py set-car` (#169, N9), and its rule wins.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autosound_tcc.core import car_library, method_cli, vendor_loader

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
    # The ANSWER carries no near miss. `searched` is deliberately excluded: it is the scope this
    # looked in (tcc#10), and the folder names on a real machine are nobody's suggestion.
    answer = {key: value for key, value in got.items() if key != "searched"}
    assert "b8" not in json.dumps(answer).lower(), "no suggestion, no did-you-mean, no fallback"


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

    # The year travels as text on the method's argv, and the method keeps what it is given.
    assert car == {"make": "VW", "model": "Passat", "generation": "B8",
                   "body": "sedan", "year": "2018"}
    after = car_library.look_up("VW", "Passat", "B8", "sedan", dirs=[folder])
    assert [m["path"] for m in after["prior_projects"]] == [str(folder)]


def test_the_car_goes_to_the_method_s_set_car_as_four_parts_and_a_year(tmp_path, monkeypatch):
    """`record` composes the call and the method writes (#169, N9): `intake.py set-car <project>
    <make> <model> <generation> <body> [--year Y]` of the copy the project is bound to. The four
    parts go as they were given — blank ones too, since refusing them is the method's — and the
    year as text, only when there is one. No lock: `project.json` is not the journal the lock
    guards, and taking it would make the lock's `process/` in a project still being described."""
    folder = _project(tmp_path, "new", {})
    calls = []

    def spawn(project_dir, script_rel, args, **kwargs):
        calls.append((Path(project_dir), script_rel, list(args), kwargs.get("lock")))
        return 0, "", ""

    monkeypatch.setattr(method_cli, "spawn", spawn)

    car_library.record(folder, "VW", "Passat", "B8", "sedan", year=2018)
    car_library.record(folder, "VW", "Passat", "B8", "")

    assert calls == [
        (folder, "intake.py",
         ["set-car", str(folder), "VW", "Passat", "B8", "sedan", "--year", "2018"], False),
        (folder, "intake.py", ["set-car", str(folder), "VW", "Passat", "B8", ""], False),
    ]


def test_a_blank_body_is_the_method_s_refusal_in_its_own_words_and_nothing_is_written(tmp_path):
    """The method's rule wins (#169, N9). TCC dropped a blank `body` and wrote the rest — a car the
    library reads as "no body recorded" for the rest of its life — where the method's `set-car`
    refuses it and writes nothing. Its sentence comes back as it is, without the class name Python
    prints in front of it, so a session reads which part to ask for; `project.json` is untouched."""
    folder = _project(tmp_path, "half", {})
    before = (folder / "project.json").read_bytes()

    with pytest.raises(car_library.CarLibraryError) as refused:
        car_library.record(folder, "VW", "Passat", "B8")

    said = str(refused.value)
    assert said.startswith("the car is four parts and body is blank"), said
    assert said.endswith("Nothing was written"), said
    assert (folder / "project.json").read_bytes() == before


def test_a_good_car_lands_in_project_json_written_by_the_method(tmp_path, monkeypatch):
    """A real child on the vendored copy writes it; TCC's own copy of `Project` only reads it back,
    so what `record` answers is the car as the method stored it."""
    folder = _project(tmp_path, "new", {})
    monkeypatch.setattr(vendor_loader.load_project().Project, "save",
                        lambda self, data: pytest.fail("TCC wrote project.json in-process"))

    car = car_library.record(folder, "VW", "Passat", "B8", "sedan", year=2018)

    saved = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    assert saved["car"] == car == {"make": "VW", "model": "Passat", "generation": "B8",
                                   "body": "sedan", "year": "2018"}
    assert saved["project_rev"] >= 1


def test_the_answer_says_where_it_looked(tmp_path):
    """An empty `prior_projects` used to be indistinguishable from "we looked nowhere". On the
    live intake it meant "none among the eight folders TCC has opened", and the build on the very
    same cabin — never opened in TCC — was folded into "none" (tcc#10)."""
    same = _project(tmp_path, "same", {"make": "VW", "model": "Passat",
                                       "generation": "B8", "body": "sedan"})

    got = car_library.look_up("VW", "Passat", "B8", "sedan", dirs=[same])

    assert str(same) in got["searched"]
    assert [entry["path"] for entry in got["prior_projects"]] == [str(same)]


def test_a_folder_inside_a_project_finds_the_project(tmp_path):
    """What TCC remembers is what was opened, and a sub-folder of a project has no `project.json`
    of its own — the method drops it from both buckets, so it does not even come back as
    `unknown`. That is how the previous build on this cabin answered "none"."""
    project = _project(tmp_path, "build-a", {"make": "VW", "model": "Passat",
                                             "generation": "B8", "body": "sedan"})
    inside = project / "rew_analitic"
    inside.mkdir()

    got = car_library.look_up("VW", "Passat", "B8", "sedan", dirs=[inside])

    assert [entry["path"] for entry in got["prior_projects"]] == [str(project)]


def test_the_open_project_is_not_reported_as_its_own_prior_build(tmp_path, monkeypatch):
    """It is prepended as a candidate on purpose — but an un-normalised path made it a DIFFERENT
    Path from the same folder in the recent list, so it arrived twice."""
    project = _project(tmp_path, "open-now", {"make": "VW", "model": "Passat",
                                              "generation": "B8", "body": "sedan"})
    monkeypatch.setattr(car_library.config, "chosen_project_dir", lambda: project)

    got = car_library.look_up("VW", "Passat", "B8", "sedan",
                              dirs=[Path(str(project) + "/.")])

    assert [entry["path"] for entry in got["prior_projects"]] == [str(project)]
