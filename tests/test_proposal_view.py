"""Reading the change the skill banked (state/proposal_view.py, SCR-026).

The ledger stores the state AFTER a change; the settings card is about the change itself. Before
`apply.propose` wrote the delta, a front-end had to diff two snapshots and guess at intent, or
trust the model to retype numbers it had already computed.
"""

from __future__ import annotations

import json

import pytest

from autosound_tcc.state import proposal_view

DELTA = {
    "schema_version": 3,
    "version": "v_002",
    "from": "v_001",
    "preset": "FULL",
    "note": "centre trim",
    "settings": [
        {"tier": "channels", "channel": "c", "param": "HP", "field": "hp",
         "was": "620 Hz LR36", "value": "680 Hz LR36"},
        {"tier": "channels", "channel": "c", "param": "Gain", "field": "gain_db",
         "was": "-2 dB", "value": "-1 dB", "was_raw": -2.0, "value_raw": -1.0},
    ],
    "advisories": [],
}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path / "state"))
    path = tmp_path / "state" / "FULL" / "proposals" / "v_002.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(DELTA), encoding="utf-8")
    return tmp_path


def test_a_banked_delta_is_read_back_whole(project):
    delta = proposal_view.load_delta("v_002", "FULL")

    assert delta is not None
    assert [row["param"] for row in delta["settings"]] == ["HP", "Gain"]


def test_a_version_with_no_delta_is_not_an_error(project):
    """The ordinary case: a seeded baseline, a hand-written ledger, a project older than this."""
    assert proposal_view.load_delta("v_001", "FULL") is None
    assert proposal_view.load_delta("", "FULL") is None


def test_the_card_shows_the_values_the_skill_banked_verbatim(project):
    """Reformatting here would reintroduce the second renderer this module exists to remove: the
    `was`/`value` strings came from the skill's own formatter, the one that prints the sheet."""
    html = proposal_view.to_html(proposal_view.load_delta("v_002", "FULL"))

    assert "620 Hz LR36" in html and "680 Hz LR36" in html
    assert "-2 dB" in html and "-1 dB" in html
    assert "centre trim" in html  # why the change was made, as banked


def test_an_added_row_reads_as_added_rather_than_as_a_value_change(project, tmp_path):
    delta = dict(DELTA, settings=[{"tier": "channels", "channel": "r-L", "added": True}])
    (tmp_path / "state" / "FULL" / "proposals" / "v_003.json").write_text(
        json.dumps(delta), encoding="utf-8"
    )

    html = proposal_view.to_html(proposal_view.load_delta("v_003", "FULL"))

    assert "new row" in html
