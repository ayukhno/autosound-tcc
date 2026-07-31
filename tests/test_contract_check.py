"""The contract-check subprocess wrapper — runs the real vendored checker, no mocking.

Mocking `subprocess.run` here would test nothing that matters: the whole point of this module is
that the checker's CLI and its JSON shape are what we think they are, which only a real run can
say. Skips cleanly when the submodule isn't checked out.
"""

from __future__ import annotations

import pytest

from autosound_tcc.core import contract_check

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
        '{"schema_version": 1, "channels": [{"code": "w-L"}, {"code": "w-L"}]}',
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


def test_a_missing_checker_is_an_error_not_an_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(contract_check, "script_path", lambda: tmp_path / "nope" / "contract.py")

    report = contract_check.run(tmp_path)

    assert not report.available
    assert not report.ok
    assert "contract.py not found" in report.error
    assert report.files == ()


def test_a_checker_that_prints_nothing_is_an_error(tmp_path, monkeypatch):
    """Exit code alone can't be trusted (1 means "issues found", which IS a report) — an empty
    stdout is what actually means "no answer"."""
    fake = tmp_path / "fake_contract.py"
    fake.write_text("import sys\nsys.stderr.write('boom\\n')\nsys.exit(3)\n", encoding="utf-8")
    monkeypatch.setattr(contract_check, "script_path", lambda: fake)

    report = contract_check.run(tmp_path)

    assert not report.available
    assert "boom" in report.error


def test_timeout_is_reported_not_raised(tmp_path, monkeypatch):
    fake = tmp_path / "slow_contract.py"
    fake.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    monkeypatch.setattr(contract_check, "script_path", lambda: fake)

    report = contract_check.run(tmp_path, timeout_s=0.5)

    assert not report.available
    assert "timed out" in report.error


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
