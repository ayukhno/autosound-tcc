"""The contract-check subprocess wrapper — runs the real vendored checker, no mocking.

Mocking `subprocess.run` here would test nothing that matters: the whole point of this module is
that the checker's CLI and its JSON shape are what we think they are, which only a real run can
say. Skips cleanly when the submodule isn't checked out.
"""

from __future__ import annotations

import pytest

from autosound_tcc.core import contract_check, method_binding

pytestmark = pytest.mark.skipif(
    not contract_check.is_available(),
    reason="rew_tool submodule not initialized (git submodule update --init)",
)


def test_empty_project_reports_missing_files_and_stays_ok(tmp_path):
    """Missing != invalid: a project that hasn't been intake'd yet is normal, not broken."""
    report = contract_check.run(tmp_path, skip_rew=True)

    assert report.available, report.error
    assert report.ok
    assert "project.json" in report.missing()
    # "missing -- run intake" is a note about how far intake got, not a defect: counting it as one
    # would show a brand-new project as several problems deep while the checker's own `ok` says fine.
    assert report.issues() == ()
    assert any("project.json" in note for note in report.notes())


def test_checking_a_project_does_not_create_anything_in_it(tmp_path):
    """The audit must not invent what it audits.

    `Process`/`PresetHistory` used to `makedirs` in their constructors, so merely running this
    check created `<project>/process/` — in whatever folder the user happened to open, since the
    window runs this on launch.
    """
    before = set(tmp_path.iterdir())

    contract_check.run(tmp_path, skip_rew=True)

    assert set(tmp_path.iterdir()) == before


def test_invalid_project_json_flips_ok_false(tmp_path):
    # Two channels with the same code -- a shape error the skill's own validator rejects (a merely
    # UNFILLED fact is deliberately not one; that's an open question, see the last test).
    (tmp_path / "project.json").write_text(
        '{"schema_version": 3, "project_rev": 1, '
        '"channels": [{"code": "w-L"}, {"code": "w-L"}]}',
        encoding="utf-8",
    )

    report = contract_check.run(tmp_path, skip_rew=True)

    assert report.available, report.error
    assert not report.ok
    entry = next(f for f in report.files if f["file"] == "project.json")
    assert entry["exists"] and entry["valid"] is False
    assert entry["issues"]
    assert any("duplicate channel code" in issue for issue in report.issues())


def test_skip_rew_is_reported_as_skipped_not_attempted(tmp_path):
    report = contract_check.run(tmp_path, skip_rew=True)

    assert report.rew() == {"reachable": False, "note": "skipped (--no-rew)"}


def _own_checker(tmp_path, monkeypatch, text=None) -> None:
    """TCC's own copy — the one a project with no entry runs (`method_binding.own_copy`) — as a
    folder whose `rew_tool/contract.py` is `text`, or that has none. `run` checks a project with the
    copy that project is bound to (#169), so this is where a fake checker goes."""
    own = tmp_path / "tccs-own"
    if text is not None:
        script = own / "rew_tool" / "contract.py"
        script.parent.mkdir(parents=True)
        script.write_text(text, encoding="utf-8")
    monkeypatch.setattr(method_binding, "own_copy", lambda: own)


def test_a_missing_checker_is_an_error_not_an_exception(tmp_path, monkeypatch):
    _own_checker(tmp_path, monkeypatch)

    report = contract_check.run(tmp_path)

    assert not report.available
    assert not report.ok
    assert "contract.py not found" in report.error
    assert report.files == ()


def test_a_checker_that_prints_nothing_is_an_error(tmp_path, monkeypatch):
    """Exit code alone can't be trusted (1 means "issues found", which IS a report) — an empty
    stdout is what actually means "no answer"."""
    _own_checker(tmp_path, monkeypatch, "import sys\nsys.stderr.write('boom\\n')\nsys.exit(3)\n")

    report = contract_check.run(tmp_path)

    assert not report.available
    assert "boom" in report.error


def test_timeout_is_reported_not_raised(tmp_path, monkeypatch):
    _own_checker(tmp_path, monkeypatch, "import time\ntime.sleep(30)\n")

    report = contract_check.run(tmp_path, timeout_s=0.5)

    assert not report.available
    assert "timed out" in report.error


def test_a_caller_can_end_the_check_early(tmp_path, monkeypatch):
    """Waiting out the 30 s timeout is not an option for a window on its way out, and returning
    without waiting means Qt destroys a running QThread — a `qFatal`, i.e. the process aborts."""
    _own_checker(tmp_path, monkeypatch, "import time\ntime.sleep(30)\n")

    report = contract_check.run(tmp_path, register=lambda child: child.kill())

    assert not report.available
    assert "cancelled" in report.error


def test_open_questions_are_surfaced_but_are_not_issues(tmp_path):
    """An unanswered intake fact is work the skill hasn't finished, not a broken file."""
    project = vendored_project()
    proj = project.Project(str(tmp_path))
    data = proj.load()
    data["car"] = {"make": None}
    proj.save(data)

    report = contract_check.run(tmp_path, skip_rew=True)

    assert report.open_questions()
    assert not any("car.make" in issue for issue in report.issues())


def vendored_project():
    from autosound_tcc.core import vendor_loader

    return vendor_loader.load_project()


def test_a_2x_project_is_reported_as_the_wrong_format(tmp_path):
    """3.0 is a break: a project that was never migrated must say so in the panel, in the skill's
    own words, rather than rendering as a project with mysteriously broken files."""
    (tmp_path / "project.json").write_text(
        '{"schema_version": 1, "sources": [], "channels": []}', encoding="utf-8"
    )

    report = contract_check.run(tmp_path, skip_rew=True)

    assert not report.ok
    assert any("migrate.py" in issue for issue in report.issues()), report.issues()


def test_a_stale_continue_block_is_carried_and_counted_nowhere(tmp_path):
    """#126: the method's `continue_head` (S-084, hub #227) -- a ▶️ CONTINUE block naming a HEAD
    the ledger is not at. A warning: not an issue and not in `ok`, as the checker has it."""
    from tests import _intake

    _intake.seed(tmp_path)
    plain = contract_check.run(tmp_path, skip_rew=True)
    (tmp_path / "tuning-changelog.md").write_text(
        "# Tuning changelog\n\n## ▶️ CONTINUE\n- HEAD: v_009 (FULL)\n", encoding="utf-8")

    report = contract_check.run(tmp_path, skip_rew=True)

    assert plain.continue_head() is None, "no changelog is no opinion"
    drift = report.continue_head()
    assert drift["stale"] == ["v_009"] and drift["heads"] == {"FULL": "v_001"}, drift
    assert "v_009" in drift["warning"]
    assert (report.ok, report.issues()) == (plain.ok, plain.issues())


def test_the_report_carries_inherited_facts_and_gone_sources():
    """hub #154 §3: top-level `inherited` and `sources_gone` since the method's v3.0.53."""
    report = contract_check.report_from_json({
        "ok": True, "project_dir": "/p", "files": [], "cross_checks": {},
        "inherited": [{"path": "car.body", "value": "sedan", "from": "/old", "from_exists": False}],
        "sources_gone": ["/old"],
    }, "/p", "2026-09-17T00:00:00+00:00", 0.5)

    assert report.inherited == ({"path": "car.body", "value": "sedan", "from": "/old",
                                 "from_exists": False},)
    assert report.sources_gone == ("/old",)



def test_complete_is_the_gate_verdict_the_report_already_carries():
    from autosound_tcc.core.contract_check import report_from_json

    done = report_from_json({"ok": True, "complete": True, "files": []}, "/p", "t", 0.1)
    open_ = report_from_json({"ok": True, "complete": False, "files": []}, "/p", "t", 0.1)
    older = report_from_json({"ok": True, "files": []}, "/p", "t", 0.1)
    assert done.complete is True
    assert open_.complete is False
    assert older.complete is False, "a method that does not say is not a green gate"


@pytest.mark.parametrize("report", [[], None, "x", 3])
def test_a_report_that_is_not_an_object_is_no_report(report):
    """F16-5: `run` never raises, and this is the last thing it calls."""
    out = contract_check.report_from_json(report, "/p", "now", 0.1)

    assert not out.ok and out.error and out.files == ()


def test_a_report_field_of_the_wrong_shape_is_said_not_read_as_green(caplog):
    """F16-5 kept it from raising; read as empty it also kept `ok`, so a report TCC could not read
    showed «OK — nothing to fix», and a `complete` one offered to start the session (the G1
    review). A newer method that changes the schema is the likely way here."""
    out = contract_check.report_from_json(
        {"ok": True, "complete": True, "files": 3, "inherited": 5, "cross_checks": [],
         "sources_gone": 7}, "/p", "now", 0.1)

    assert not out.ok and not out.complete
    assert "files" in out.error and "int" in out.error
    assert out.files == () and out.inherited == () and out.cross_checks == {}
    assert out.sources_gone == ()
    assert "files" in caplog.text


@pytest.mark.parametrize("report", [{"ok": "false", "complete": "yes"}, {"ok": 1, "complete": {}}])
def test_ok_and_complete_are_true_only_when_they_say_true(report):
    """`bool("false")` is True: a wrong-shaped verdict was a green gate."""
    out = contract_check.report_from_json(report, "/p", "now", 0.1)

    assert out.ok is False and out.complete is False and "ok" in out.error


def test_a_well_formed_report_reads_as_it_says():
    out = contract_check.report_from_json(
        {"ok": True, "complete": False, "files": [{"file": "project.json"}], "project_dir": None},
        "/p", "now", 0.1)

    assert out.ok and not out.complete and out.error == "" and len(out.files) == 1
