"""The project's `AGENTS.md` for Codex, through the method's `agents-setup` (`core/agents_md.py`).

Skill #149 (v3.1.4): a project made before the method seeded `AGENTS.md` has none, and Codex reads
neither the method's load line nor its feedback rule. TCC asks the method, through the copy the
project is bound to, once before a Codex start — never over a file that is there, never in a folder
that is no project — and a refusal is one line, never a raise.
"""

from __future__ import annotations

import json

import pytest

from autosound_tcc.core import agents_md, method_cli, vendor_loader

needs_the_method = pytest.mark.skipif(
    not vendor_loader.is_available(), reason="rew_tool submodule not checked out")


def _project(folder):
    folder.mkdir(exist_ok=True)
    (folder / "project.json").write_text(json.dumps({"schema_version": 3, "project_rev": 1}),
                                         encoding="utf-8")
    return folder


@needs_the_method
def test_a_project_without_it_gets_the_method_s_own_text(tmp_path):
    project = _project(tmp_path / "passat")

    assert agents_md.ensure(project) == ""

    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "autosound-tuning" in text, text[:300]


def test_a_file_that_is_there_or_a_folder_that_is_no_project_asks_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(method_cli, "spawn",
                        lambda *a, **k: pytest.fail(f"the method was asked: {a}"))
    there = _project(tmp_path / "there")
    (there / "AGENTS.md").write_text("the person's own\n", encoding="utf-8")
    bare = tmp_path / "bare"
    bare.mkdir()

    assert agents_md.ensure(there) == agents_md.ensure(bare) == ""
    assert (there / "AGENTS.md").read_text(encoding="utf-8") == "the person's own\n"
    assert not (bare / "AGENTS.md").exists()


def test_a_refusal_is_one_line_in_the_method_s_words_and_never_raises(tmp_path, monkeypatch):
    project = _project(tmp_path / "car")
    monkeypatch.setattr(method_cli, "spawn", lambda *a, **k: (
        1, "", "error: /car/AGENTS.md cannot be written: Permission denied; nothing was written"))
    assert agents_md.ensure(project) == (
        "AGENTS.md was not written: /car/AGENTS.md cannot be written: Permission denied; "
        "nothing was written")

    def refused(*_a, **_k):
        raise method_cli.Refused("this project's copy of the method is not one TCC runs")

    monkeypatch.setattr(method_cli, "spawn", refused)
    assert agents_md.ensure(project) == (
        "AGENTS.md was not written: this project's copy of the method is not one TCC runs")


def test_it_runs_the_bound_copy_s_project_py_without_the_lock(tmp_path, monkeypatch):
    project = _project(tmp_path / "car")
    asked = []
    monkeypatch.setattr(method_cli, "spawn", lambda project_dir, script, args, **kw: asked.append(
        (project_dir, script, list(args), kw.get("lock"))) or (0, "wrote AGENTS.md", ""))

    assert agents_md.ensure(project) == ""
    assert asked == [(project, "project.py", [str(project), "agents-setup"], False)]


def test_a_copy_before_v314_is_told_once_and_never_started(tmp_path, tmp_path_factory, monkeypatch):
    """tcc#200's review, I3: an older bound `project.py` has no `agents-setup`; started, it printed
    its usage and that line was said on every Codex start. Read from its text: said once per
    project in this run, and nothing started."""
    from tests._method_copies import copy_of_the_method, linked_and_approved
    from tests.test_method_features import OLDER

    project = _project(tmp_path / "car")
    linked_and_approved(project, copy_of_the_method(tmp_path_factory.mktemp("older"), changes=OLDER))
    monkeypatch.setattr(method_cli, "spawn",
                        lambda *a, **k: pytest.fail(f"the method was started: {a}"))

    assert agents_md.ensure(project) == agents_md.OLDER
    assert agents_md.ensure(project) == ""
    assert not (project / "AGENTS.md").exists()


def test_a_folder_that_cannot_be_looked_into_is_a_sentence(tmp_path, monkeypatch):
    """tcc#200's review, M4: «never raises» — `exists()` raises on a folder this user may not read,
    and in the terminal that was a traceback and no Codex."""
    from pathlib import Path

    def denied(self, *_a, **_k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "exists", denied)
    said = agents_md.ensure(tmp_path)
    assert said.startswith("AGENTS.md was not written:") and "Permission denied" in said, said
