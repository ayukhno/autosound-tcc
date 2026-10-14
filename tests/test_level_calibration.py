"""`core.level_calibration` — REW's level calibration named between rounds, never corrected (tcc#198).

Hub #268 (PAS-015): REW 5.40 beta 135 reset its SPL calibration between `cap_003` and `cap_004`,
every capture's `splOffsetdB` 103.35 → 120.0, and the round check said nothing. The rounds here are
written by the method's own writer (`tests/_rounds.py`); REW's listing is a dict as `rew_api` returns
it.
"""

from __future__ import annotations

import json

import pytest

from autosound_tcc.core import app_log, level_calibration as lc, vendor_loader

from tests import _rounds

pytestmark = pytest.mark.skipif(
    not vendor_loader.is_available(), reason="rew_tool submodule not checked out"
)

GLOSSARY = {
    "schema_version": 1,
    "channels": [{"code": "sw", "active": True}, {"code": "w-L", "active": True},
                 {"code": "w-R", "active": True}],
}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    (tmp_path / "glossary.json").write_text(json.dumps(GLOSSARY), encoding="utf-8")
    return tmp_path


def _listing(*captures) -> dict:
    """REW's `/measurements`: `(title, uuid, splOffsetdB or None)` each, by ordinal. None leaves the
    field out, as an older REW lists it."""
    out = {}
    for ordinal, (title, uuid, offset) in enumerate(captures, start=1):
        record = {"title": title, "uuid": uuid, "rewVersion": "5.40 beta 135"}
        if offset is not None:
            record["splOffsetdB"] = offset
        out[str(ordinal)] = record
    return out


def _said(notes) -> list[tuple[str, dict]]:
    return [(note.key, note.values) for note in notes]


def _two_rounds(project, before, after, pad=False):
    """`cap_001` at series 3 took `w-L_3`, `w-R_3`; `cap_002` at series 4 took `w-L_4`, `w-R_4`.
    REW lists all four, round 3's at `before`, round 4's at `after`. `pad`: titles as a person
    types them in REW (`w-L_03`), the fixtures' default."""
    typed = _rounds.as_typed if pad else str
    _rounds.write_round(project, version=3, expected=["w-L_3 (sw)", "w-R_3 (sw)"],
                        taken=["w-L_3 (sw)", "w-R_3 (sw)"], pad=pad)
    _rounds.write_round(project, version=4, expected=["w-L_4 (sw)", "w-R_4 (sw)"],
                        taken=["w-L_4 (sw)", "w-R_4 (sw)"], pad=pad)
    return _listing((typed("w-L_3 (sw)"), "u-l3", before), (typed("w-R_3 (sw)"), "u-r3", before),
                    (typed("w-L_4 (sw)"), "u-l4", after), (typed("w-R_4 (sw)"), "u-r4", after))


@pytest.mark.parametrize("before, after, delta, pad", [
    (103.35, 120.0, "+16.65", False),
    (120.0, 103.35, "-16.65", False),
    (103.35, 120.0, "+16.65", True),
])
def test_a_jump_between_rounds_is_named_with_its_sign_and_value(project, before, after, delta,
                                                                pad):
    """PAS-015's case: the round reads 16.65 dB above the last as REW shows it, and says so — with
    the titles as typed in REW too (`pad`)."""
    listing = _two_rounds(project, before, after, pad=pad)

    assert _said(lc.notes(project, listing)) == [(lc.JUMP, {
        "delta": delta, "before": lc._db(before), "after": lc._db(after)})]
    assert lc.notes(project, listing)[0].round_id == "cap_002"


def test_the_sentence_reads_as_the_issue_wrote_it(project):
    from autosound_tcc.ui.tcc import i18n

    note, = lc.notes(project, _two_rounds(project, 103.35, 120.0))
    assert i18n.t(note.key).format(**note.values) == (
        "REW's level calibration changed since the last round: +16.65 dB (103.35 → 120.0) — "
        "levels of this round are not comparable with the last one as REW shows them.")


def test_equal_offsets_say_nothing(project):
    assert lc.notes(project, _two_rounds(project, 103.35, 103.35)) == []


def test_a_first_round_says_nothing(project):
    _rounds.write_round(project, version=3, expected=["w-L_3 (sw)"], taken=["w-L_3 (sw)"],
                        pad=False)

    assert lc.notes(project, _listing(("w-L_3 (sw)", "u-l3", 120.0))) == []


def test_mixed_offsets_inside_one_round_are_named(project):
    """REW reset between two takes of one round: its levels are not comparable inside it, and no
    jump against the last round is claimed from either value."""
    _rounds.write_round(project, version=3, expected=["w-L_3 (sw)"], taken=["w-L_3 (sw)"],
                        pad=False)
    _rounds.write_round(project, version=4, expected=["w-L_4 (sw)", "w-R_4 (sw)"],
                        taken=["w-L_4 (sw)", "w-R_4 (sw)"], pad=False)
    listing = _listing(("w-L_3 (sw)", "u-l3", 103.35), ("w-L_4 (sw)", "u-l4", 103.35),
                       ("w-R_4 (sw)", "u-r4", 120.0))

    assert _said(lc.notes(project, listing)) == [(lc.MIXED, {"values": "103.35, 120.0"})]


def test_a_rew_that_lists_no_offset_says_nothing(project):
    """An older REW lists no `splOffsetdB`: no offset, nothing said — not a jump from nothing."""
    assert lc.notes(project, _two_rounds(project, None, None)) == []
    assert lc.notes(project, _listing()) == []


def test_the_last_rounds_offset_is_kept_when_rew_no_longer_lists_it(project):
    """TCC's own record in `.tcc/`, per round, while REW's listing names its captures: the next
    round is compared with it after REW dropped the old captures (or was restarted on a new file)."""
    _rounds.write_round(project, version=3, expected=["w-L_3 (sw)"], taken=["w-L_3 (sw)"],
                        pad=False)
    assert lc.notes(project, _listing(("w-L_3 (sw)", "u-l3", 103.35))) == []
    assert lc.recorded(project) == {"cap_001": {"w-L_3 (sw)": 103.35}}
    assert (project / ".tcc" / lc.FILENAME).is_file()
    assert not (project / "process" / lc.FILENAME).exists(), "never in the method's files (D-6)"

    _rounds.write_round(project, version=4, expected=["w-L_4 (sw)"], taken=["w-L_4 (sw)"],
                        pad=False)
    listing = _listing(("w-L_4 (sw)", "u-l4", 120.0))  # REW holds round 4 only

    assert _said(lc.notes(project, listing)) == [(lc.JUMP, {
        "delta": "+16.65", "before": "103.35", "after": "120.0"})]


def test_a_retake_under_the_same_title_is_not_read_as_the_last_rounds(project):
    """Two rounds at one series take the same title. REW lists one capture under it — the new
    one — and that is no reading of the last round's offset: nothing is claimed."""
    _rounds.write_round(project, version=3, expected=["w-L_3 (sw)"], taken=["w-L_3 (sw)"],
                        pad=False)
    _rounds.write_round(project, version=3, expected=["w-L_3 (sw)"], taken=["w-L_3 (sw)"],
                        pad=False)

    assert lc.notes(project, _listing(("w-L_3 (sw)", "u-new", 120.0))) == []


def test_the_strip_is_told_once(project, monkeypatch):
    told = []
    monkeypatch.setattr(app_log, "warn", told.append)
    listing = _two_rounds(project, 103.35, 120.0)

    for _ in range(2):
        lc.tell(project, lc.notes(project, listing), lambda note: f"{note.key} {note.values}")

    assert len(told) == 1 and told[0].startswith(lc.JUMP), told


def _record_round_three(project, offset=103.35):
    """Round 3 open, read while REW lists its two takes at `offset`: TCC's record of it."""
    _rounds.write_round(project, version=3, expected=["w-L_3 (sw)", "w-R_3 (sw)"],
                        taken=["w-L_3 (sw)", "w-R_3 (sw)"], pad=False)
    assert lc.notes(project, _listing(("w-L_3 (sw)", "u-l3", offset),
                                      ("w-R_3 (sw)", "u-r3", offset))) == []


@pytest.mark.parametrize("listing_of_round_three", [
    pytest.param((("w-L_3 (sw)", "u-l3", 120.0), ("w-R_3 (sw)", "u-r3", 120.0)),
                 id="its-own-captures-listed-at-the-new-offset"),
    pytest.param((("w-L_3 (sw)", "u-l3-retake", 120.0),), id="a-new-capture-under-its-title"),
])
def test_the_last_rounds_record_is_not_rewritten_from_todays_listing(project,
                                                                     listing_of_round_three):
    """The Rounds group's review, I1: the record exists to outlast REW. Written over from today's
    listing, the jump was said once and gone on the next Refresh. A closed round's record is never
    written again; the same listing gives the same answer twice."""
    _record_round_three(project)
    _rounds.write_round(project, version=4, expected=["w-L_4 (sw)"], taken=["w-L_4 (sw)"],
                        pad=False)
    listing = _listing(*listing_of_round_three, ("w-L_4 (sw)", "u-l4", 120.0))
    jump = [(lc.JUMP, {"delta": "+16.65", "before": "103.35", "after": "120.0"})]

    assert _said(lc.notes(project, listing)) == jump
    assert _said(lc.notes(project, listing)) == jump
    assert lc.recorded(project)["cap_001"] == {"w-L_3 (sw)": 103.35, "w-R_3 (sw)": 103.35}


def test_an_empty_round_between_does_not_hide_the_jump(project):
    """I2: round 4 took nothing; round 5 is compared with round 3, the newest that has offsets."""
    _record_round_three(project)
    _rounds.write_round(project, version=4, expected=["w-L_4 (sw)"], pad=False)
    _rounds.write_round(project, version=5, expected=["w-L_5 (sw)"], taken=["w-L_5 (sw)"],
                        pad=False)

    assert _said(lc.notes(project, _listing(("w-L_5 (sw)", "u-l5", 120.0)))) == [
        (lc.JUMP, {"delta": "+16.65", "before": "103.35", "after": "120.0"})]


def test_the_newest_earlier_round_is_compared_not_the_oldest(project):
    _record_round_three(project, offset=100.0)
    _rounds.write_round(project, version=4, expected=["w-L_4 (sw)"], taken=["w-L_4 (sw)"],
                        pad=False)
    assert _said(lc.notes(project, _listing(("w-L_4 (sw)", "u-l4", 103.35))))[0][1]["before"] \
        == "100.0"
    _rounds.write_round(project, version=5, expected=["w-L_5 (sw)"], taken=["w-L_5 (sw)"],
                        pad=False)

    assert _said(lc.notes(project, _listing(("w-L_5 (sw)", "u-l5", 120.0)))) == [
        (lc.JUMP, {"delta": "+16.65", "before": "103.35", "after": "120.0"})]


def test_a_record_set_aside_as_broken_says_the_comparison_is_gone_once(project, monkeypatch):
    """The review: a broken record is set aside (`own_store`), and the earlier rounds' offsets go
    with it. Said once — a change against them cannot be named — rather than silence."""
    from autosound_tcc.core import self_check
    from autosound_tcc.ui.tcc import i18n

    told = []
    monkeypatch.setattr(app_log, "warn", told.append)
    monkeypatch.setattr(self_check, "_translate", i18n.t)
    _record_round_three(project)
    lc.store_path(project).write_text("{broken", encoding="utf-8")
    _rounds.write_round(project, version=4, expected=["w-L_4 (sw)"], taken=["w-L_4 (sw)"],
                        pad=False)

    for _ in range(2):
        assert lc.notes(project, _listing(("w-L_4 (sw)", "u-l4", 120.0))) == []
    assert told == [i18n.t(lc.RECORD_LOST)], told


def test_a_listing_entry_that_is_no_record_is_passed_over(project):
    """The review: `offset_of` guarded what it read, its index did not — a non-object in REW's
    answer raised out of the panel's read."""
    _rounds.write_round(project, version=3, expected=["w-L_3 (sw)"], taken=["w-L_3 (sw)"],
                        pad=False)

    assert lc.notes(project, {"1": "oops", "2": None, "3": {"title": "w-L_3 (sw)",
                                                            "uuid": "u", "splOffsetdB": 1}}) == []


def test_the_journal_is_read_again_only_when_it_changed(project, monkeypatch):
    """The review: `notes` runs on the GUI thread on every Refresh; the journal is folded once per
    state of it, not once per read of REW."""
    from autosound_tcc.state import process_view

    listing = _two_rounds(project, 103.35, 120.0)
    folds = []
    real = process_view.capture_rounds
    monkeypatch.setattr(process_view, "capture_rounds",
                        lambda *a, **kw: folds.append(1) or real(*a, **kw))

    first = lc.notes(project, listing)
    assert lc.notes(project, listing) == first and len(folds) <= 1, folds
    _rounds.write_round(project, version=5, expected=["w-L_5 (sw)"], pad=False)
    lc.notes(project, listing)
    assert len(folds) == 2, "a changed journal is read again"
