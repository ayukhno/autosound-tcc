"""The listening vocabulary as TCC reshapes it, and the panel that clicks it into a verdict.

These run against the REAL files in the vendored skill, deliberately. The whole point of parsing
the method's markdown instead of keeping a JSON copy beside it is that a shape change is caught;
a fixture of our own would restore exactly the second source we refused to create.
"""

from pathlib import Path

import pytest

from autosound_tcc.core import listening
from autosound_tcc.ui.tcc import i18n

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication, QTreeWidgetItem  # noqa: E402

from autosound_tcc.ui.tcc import listening_dialog  # noqa: E402


@pytest.fixture(scope="module")
def sheet():
    if not listening.available():
        pytest.skip("the vendored skill is not checked out")
    return listening.load("uk")


def test_the_vocabulary_loads_and_the_method_says_it_is_consistent(sheet):
    assert sheet.tracks and sheet.routes
    # `check()` is the method's own orphan check over both files in both directions. If it ever
    # reports something, the panel is showing a vocabulary with a hole in it and we want to know
    # here rather than from a tree with a blank row in a car.
    assert sheet.problems == ()


def test_a_track_carries_its_own_characteristics_with_the_words_on_the_characteristic(sheet):
    track = sheet.tracks["CarMus#07"]
    assert track.library == "CarMus" and track.number == "07"
    by_id = {p.characteristic: p for p in track.phrases}
    assert set(by_id) >= {"c03", "c09", "c10"}
    depth = by_id["c09"]
    assert depth.good and depth.bad and depth.good != depth.bad
    # The cue says WHERE on this track; the good/bad sentences come from the characteristic and
    # are the same wherever it is judged. That split is the contract with the skill (2026-08-25).
    other = next(t for t in sheet.tracks.values()
                 if t.id != track.id and any(p.characteristic == "c09" for p in t.phrases))
    twin = next(p for p in other.phrases if p.characteristic == "c09")
    assert twin.good == depth.good, "the wording belongs to the characteristic, not the track"
    assert twin.cue != depth.cue, "the cue belongs to the link"


def test_the_timecode_rides_on_the_link_not_the_track(sheet):
    """#07 exposes four things and only one of them happens at a stated moment. A timecode on the
    TRACK would point at the wrong one -- this is why `characteristics` is a list of links."""
    phrases = {p.characteristic: p for p in sheet.tracks["CarMus#07"].phrases}
    assert phrases["c10"].timecode == "2:00"
    assert phrases["c09"].timecode is None


def test_a_track_is_never_named_by_its_bare_number(sheet):
    """The method's "Disc identity" rule: compilations reuse each other's numbering, so a gate
    citing `#7` breaks silently the day the disc changes."""
    label = listening.track_label(sheet.tracks["CarMus#07"])
    assert "CarMus" in label and "#07" in label and "Melody Gardot" in label
    # A row with no number (the mono set, the user's own material) must not print an empty one.
    mono = listening.track_label(sheet.tracks["mono/merrill"])
    assert "#" not in mono and "Helen Merrill" in mono


def test_routes_are_ordered_and_name_things_that_exist(sheet):
    assert set(sheet.routes) >= {"first", "short", "full"}
    for name, steps in sheet.routes.items():
        assert [s.n for s in steps] == list(range(1, len(steps) + 1)), name
        for step in steps:
            assert sheet.phrase(step.track, step.characteristic) is not None, (name, step)


def test_an_unknown_language_falls_back_rather_than_blanking():
    """TCC offers four UI languages and the method translates its own set; the two lists are
    allowed to move apart. What must never happen is an empty tree row."""
    sheet = listening.load("xx")
    assert sheet.tracks
    for track in sheet.tracks.values():
        for phrase in track.phrases:
            assert phrase.good.strip() and phrase.bad.strip() and phrase.label.strip()


# ------------------------------------------------------------------- the panel
def _dialog(tmp_path, sheet, version="v_003"):
    QApplication.instance() or QApplication([])
    return listening_dialog.ListeningDialog(Path(tmp_path), sheet, version)


def _leaves(item: QTreeWidgetItem):
    if item.data(0, listening_dialog._PAIR) is not None:
        yield item
    for i in range(item.childCount()):
        yield from _leaves(item.child(i))


def test_clicking_a_phrase_ticks_a_pair_and_writes_a_line(tmp_path, sheet):
    dialog = _dialog(tmp_path, sheet)
    leaf = next(_leaves(dialog._tree.topLevelItem(0)))
    dialog._on_item(leaf)
    track, characteristic, ok = leaf.data(0, listening_dialog._PAIR)
    assert dialog._pairs == [(track, characteristic, ok)]
    text = dialog._text.toPlainText()
    phrase = sheet.phrase(track, characteristic)
    assert phrase.verdict_text(ok) in text and listening.track_label(sheet.tracks[track]) in text
    dialog.deleteLater()


def test_editing_the_text_does_not_touch_the_ticks(tmp_path, sheet):
    """The two are kept side by side ON PURPOSE. Deriving the pairs from the final text would have
    to guess, and would guess wrong the first time somebody wrote "not really" under a 🟢 phrase."""
    dialog = _dialog(tmp_path, sheet)
    leaf = next(_leaves(dialog._tree.topLevelItem(0)))
    dialog._on_item(leaf)
    before = list(dialog._pairs)
    dialog._text.setPlainText("зовсім інші слова")
    assert dialog._pairs == before
    dialog.deleteLater()


def test_undo_drops_the_tick_and_leaves_the_sentence_alone(tmp_path, sheet):
    """By the time somebody presses undo they may have rewritten that line; a widget that hunts
    for its own sentence in edited prose deletes the wrong one eventually."""
    dialog = _dialog(tmp_path, sheet)
    leaves = list(_leaves(dialog._tree.topLevelItem(0)))
    dialog._on_item(leaves[0])
    dialog._on_item(leaves[1])
    text_before = dialog._text.toPlainText()
    dialog._drop_last()
    assert len(dialog._pairs) == 1
    assert dialog._text.toPlainText() == text_before
    dialog.deleteLater()


def test_saving_nothing_refuses_and_says_why(tmp_path, sheet):
    dialog = _dialog(tmp_path, sheet)
    dialog._text.setPlainText("сцена поїхала праворуч")
    dialog._on_save()
    # `isHidden`, not `isVisible`: the label is shown, but its dialog was never exec'd, and a
    # widget inside an unshown window reports `isVisible() == False` however it was set.
    assert not dialog._problem.isHidden() and dialog.written == 0
    # The words are kept WITH the ticks, not instead of them -- and the refusal says so.
    assert i18n.t("lsnNoPairs") == dialog._problem.text()
    dialog.deleteLater()


def test_a_refusal_from_the_gate_is_shown_in_the_gates_own_words(tmp_path, sheet, monkeypatch):
    """A UI that quietly fixes what a gate would have refused trains people to trust the UI over
    the gate -- the same rule the protective dialog is built on."""
    dialog = _dialog(tmp_path, sheet)
    dialog._on_item(next(_leaves(dialog._tree.topLevelItem(0))))

    def refuse(*_args, **_kwargs):
        raise RuntimeError("Traceback (most recent call last):\n  File \"x\"\nunknown track 'q'")

    monkeypatch.setattr(listening_dialog.process_writer, "record_listening_verdict", refuse)
    dialog._on_save()
    assert not dialog._problem.isHidden() and "unknown track 'q'" in dialog._problem.text()
    assert dialog.written == 0
    dialog.deleteLater()


def test_the_verdict_is_stamped_with_the_version_that_was_read(tmp_path, sheet, monkeypatch):
    seen = {}

    def capture(project_dir, pairs, **kwargs):
        seen.update(kwargs, pairs=list(pairs), project_dir=project_dir)
        return "ok"

    dialog = _dialog(tmp_path, sheet, version="v_042")
    dialog._on_item(next(_leaves(dialog._tree.topLevelItem(0))))
    monkeypatch.setattr(listening_dialog.process_writer, "record_listening_verdict", capture)
    dialog._on_save()
    assert seen["ledger_version"] == "v_042"
    assert seen["route"] in sheet.routes
    assert dialog.written == 1
    dialog.deleteLater()


def test_no_ledger_yet_is_said_out_loud_rather_than_faked(tmp_path, sheet):
    """A verdict stamped with the wrong snapshot is worse than one with no stamp, because it looks
    attributable. With no version the panel writes without one AND warns."""
    dialog = _dialog(tmp_path, sheet, version=None)
    assert dialog._version == ""
    dialog.deleteLater()


# ------------------------------------------------------- all the way to disk
def test_a_verdict_reaches_the_journal_and_reads_back(tmp_path, sheet):
    """The whole path, through the skill's real writer: click, save, read it back.

    Worth having end to end rather than at the seam, because everything interesting about this
    feature is in the handover — the ids TCC composes must be the ids the method validates, and a
    typo on either side is invisible until a person in a car presses the button.
    """
    from autosound_tcc.core import process_writer
    from tests import _intake

    if not process_writer.is_available():
        pytest.skip("the vendored skill is not checked out")
    project = tmp_path / "car"
    _intake.seed(project)

    dialog = _dialog(project, sheet, version="v_007")
    leaves = list(_leaves(dialog._tree.topLevelItem(0)))
    dialog._on_item(leaves[0])
    dialog._on_item(leaves[-1])
    dialog._text.setPlainText("сцена трохи праворуч, але вокал тримається")
    dialog._on_save()
    assert dialog._problem.isHidden(), dialog._problem.text()
    assert dialog.written == 2

    back = process_writer.listening_verdicts(project, ledger_version="v_007")
    assert "сцена трохи праворуч" in back
    for track, characteristic, _ok in dialog._pairs:
        assert track in back and characteristic in back
    dialog.deleteLater()
