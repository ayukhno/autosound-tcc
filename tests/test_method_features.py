"""What the copy a project is BOUND to can do, read from its text (`core/method_features.py`).

tcc#200's review, I2/I3: TCC reads with its own copy (v3.1.4: titles by the series key, a sweep over
its own range, `agents-setup`), while a project may be bound to an older copy (#169 allows v3.1.0 to
v3.1.3), whose close and gate match raw titles. Each project is read by its own copy's rule, and an
older one is told once, with the way out.
"""

from __future__ import annotations

import pytest

from autosound_tcc.core import app_log, method_features
from autosound_tcc.state import process_view
from tests._method_copies import copy_of_the_method, linked_and_approved

#: What v3.1.4 added, taken out of a copy's text: a copy as v3.1.3 shipped it, for these readers.
OLDER = {
    "rew_tool/state/process.py": lambda text: text.replace("def title_key(", "def _no_key_("),
    "rew_tool/verify.py": lambda text: text.replace("band_source", "band_src"),
    "rew_tool/project.py": lambda text: text.replace("agents-setup", "agents-gone"),
}


@pytest.fixture
def older_project(tmp_path, tmp_path_factory):
    """A project bound (linked and approved) to a copy older than v3.1.4."""
    older = copy_of_the_method(tmp_path_factory.mktemp("older"), changes=OLDER)
    project = tmp_path / "car"
    project.mkdir()
    linked_and_approved(project, older)
    return project


@pytest.fixture
def told(monkeypatch):
    """What reached the strip as a warning, in the window's words (`diagnostics_panel` hands
    `self_check` the window's translator when the window loads)."""
    from autosound_tcc.core import self_check
    from autosound_tcc.ui.tcc import i18n

    said = []
    monkeypatch.setattr(app_log, "warn", said.append)
    monkeypatch.setattr(self_check, "_translate", i18n.t)
    return said


def test_tcc_s_own_copy_has_what_v3_1_4_brought(tmp_path, own_copy_is_the_submodule, told):
    for feature in (method_features.TITLE_KEY, method_features.OWN_RANGE,
                    method_features.AGENTS_SETUP):
        assert method_features.has(feature, tmp_path), feature
    assert method_features.say_if_older(tmp_path) is False and told == []
    key = process_view.title_key(tmp_path)
    assert key("w-R_01 (sw)") == key("w-R_1 (sw)"), "the series key"


def test_an_older_bound_copy_is_read_raw_and_said_once(older_project, told):
    assert not method_features.has(method_features.TITLE_KEY, older_project)
    assert not method_features.has(method_features.AGENTS_SETUP, older_project)
    assert method_features.older_than_v314(older_project)

    key = process_view.title_key(older_project)
    assert key("w-R_01 (sw)") != key("w-R_1 (sw)"), "raw titles, as that copy's close matches"
    round_ = {"expected": ["w-R_1 (sw)"], "taken": {"w-R_01 (sw)": {"at": "t"}}}
    assert process_view.outstanding(round_, older_project) == ["w-R_1 (sw)"]

    assert method_features.say_if_older(older_project) is True
    assert method_features.say_if_older(older_project) is True
    assert len(told) == 1, told
    assert "v3.1.4" in told[0] and "TCC" in told[0], told
