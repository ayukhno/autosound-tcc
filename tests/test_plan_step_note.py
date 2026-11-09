"""A plan step's note and the Arbiter's answer beside it (#248, the method's #202, hub #313).

Every plan here is the method's own: a real `Process` writes `process-state.json` in `tmp_path` and
the panel reads it the way the window does (`load_state` -> `to_plan` -> `set_plan`). A shape the
method would not write is put in the file by hand, after the method has written the rest.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QTextDocument  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from autosound_tcc.core import vendor_loader  # noqa: E402
from autosound_tcc.state import process_view  # noqa: E402
from autosound_tcc.state.models import StepNote  # noqa: E402
from autosound_tcc.ui.tcc import i18n, theme  # noqa: E402
from autosound_tcc.ui.tcc.plan_panel import _PhaseRow, _PhaseStepRow, PlanPanel  # noqa: E402
from tests import _intake  # noqa: E402

pytestmark = pytest.mark.skipif(
    not vendor_loader.is_available(), reason="rew_tool submodule not checked out"
)

NOTE = {
    "do": "Play the vocal track",
    "expect": "Voice 5-10 cm left of centre",
    "if_not": "Check the delay of tw-L",
}


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def process(project):
    """The method's own writer on a project in `tmp_path`; `v_003` so a step can close against it."""
    snapshot = project / "state" / "FULL" / "v_003.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("{}", encoding="utf-8")
    module = vendor_loader.load_process()
    _intake.seed(project)
    written = module.Process(str(process_view.process_dir(project)))
    _intake.open_phases(written)
    written.set_target("FULL", "EPY")
    written.enter_phase("2")
    return written


def _plan(project):
    return process_view.to_plan(process_view.load_state(project))


def _panel(project) -> PlanPanel:
    _app()
    panel = PlanPanel()
    panel.set_plan(_plan(project))
    return panel


def _show(panel: PlanPanel, width: int = 200, height: int = 500) -> None:
    panel.resize(width, height)
    panel.show()
    QApplication.processEvents()
    QApplication.processEvents()


def _row(panel: PlanPanel, title: str) -> _PhaseStepRow:
    found = next(row for row in panel.widget().findChildren(_PhaseStepRow)
                 if any(title in label.text() for label in row.findChildren(QLabel)))
    found.held_panel = panel  # the panel owns the row: collected, it would take the row with it
    return found


def _icons(row: QWidget) -> list:
    return [w for w in row.findChildren(QWidget) if w.property("class") == "step-note-icon"]


def _seen(markup: str) -> str:
    """What a rich-text tip or label puts in front of a person: the markup read as markup."""
    document = QTextDocument()
    document.setHtml(markup)
    return document.toPlainText()


def _tip(row: QWidget) -> str:
    return _seen(_icons(row)[0].hover_tip.text())


def _edit_note(project, step_id: str, note) -> None:
    """Put a shape in the file by hand, the way a hand edit or an older copy would have."""
    path = process_view.state_file(project)
    state = json.loads(path.read_text(encoding="utf-8"))
    entry = next(s for s in state["plan"] if s["id"] == step_id)
    if note is _ABSENT:
        entry.pop("note", None)
    else:
        entry["note"] = note
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


_ABSENT = object()


def test_a_step_with_a_note_shows_the_icon_and_its_tip_says_what_the_step_predicts(process, project):
    process.add_step("2.1", "listen to the voice", note=NOTE)
    process.add_step("2.2", "no prediction here")
    panel = _panel(project)

    row = _row(panel, "listen to the voice")
    assert len(_icons(row)) == 1
    tip = _tip(row)
    assert i18n.t("planNoteDo") in tip and NOTE["do"] in tip
    assert i18n.t("planNoteExpect") in tip and NOTE["expect"] in tip
    assert i18n.t("planNoteIfNot") in tip and NOTE["if_not"] in tip
    assert i18n.t("planNoteAnswer") not in tip, "nothing was answered yet"

    assert _icons(_row(panel, "no prediction here")) == []


def test_the_icon_is_really_drawn(process, project):
    process.add_step("2.1", "listen to the voice", note=NOTE)
    icon = _icons(_row(_panel(project), "listen to the voice"))[0]

    image = icon.grab().toImage()
    corner = image.pixelColor(0, 0).rgba()
    drawn = sum(image.pixelColor(x, y).rgba() != corner
                for x in range(image.width()) for y in range(image.height()))
    assert drawn >= 12, "an empty square is not a document icon"


def test_a_click_opens_the_note_under_the_row_and_a_second_click_closes_it(process, project):
    process.add_step("2.1", "listen to the voice", note=NOTE)
    panel = _panel(project)
    _show(panel, 300)
    windows = set(QApplication.topLevelWidgets())

    row = _row(panel, "listen to the voice")
    assert row._note_view.isHidden()

    _icons(row)[0].mousePressEvent(None)
    QApplication.processEvents()

    view = row._note_view
    assert not view.isHidden() and view.isVisible()
    assert NOTE["expect"] in _seen(view.text()) and NOTE["if_not"] in _seen(view.text())
    assert not view.isWindow() and row.isAncestorOf(view)
    assert set(QApplication.topLevelWidgets()) == windows, "a note opens no window"
    assert view.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse

    _icons(row)[0].mousePressEvent(None)
    assert row._note_view.isHidden()
    panel.close()


def test_after_the_close_the_answer_stands_beside_expect(process, project):
    process.add_step("2.1", "listen to the voice", note=NOTE)
    process.start_attempt("2.1")
    process.finish_step("2.1", ["v_003"], heard="Slightly left, as predicted")

    row = _row(_panel(project), "listen to the voice")

    for said in (_tip(row), _seen(row._note_view.text())):
        expect, answer, otherwise = (said.index(NOTE["expect"]),
                                     said.index("Slightly left, as predicted"),
                                     said.index(NOTE["if_not"]))
        assert expect < answer < otherwise, said
        assert i18n.t("planNoteAnswer") in said
        between = said[expect + len(NOTE["expect"]):answer]
        assert i18n.t("planNoteDo") not in between and i18n.t("planNoteIfNot") not in between


def test_an_answer_on_a_step_that_had_no_note_is_still_shown(process, project):
    """The method keeps it on a step with no note too: a note of `answer` alone."""
    process.add_step("2.1", "just check it")
    process.start_attempt("2.1")
    process.finish_step("2.1", ["v_003"], heard="sounded fine")

    row = _row(_panel(project), "just check it")

    assert "sounded fine" in _tip(row)
    assert i18n.t("planNoteExpect") not in _tip(row)


def test_a_redo_takes_the_answer_away_and_keeps_the_prediction(process, project):
    process.add_step("2.1", "listen to the voice", note=NOTE)
    process.start_attempt("2.1")
    process.finish_step("2.1", ["v_003"], heard="not this time")
    process.start_attempt("2.1")

    tip = _tip(_row(_panel(project), "listen to the voice"))

    assert "not this time" not in tip and NOTE["expect"] in tip


def test_a_note_is_text_and_never_markup(process, project):
    """The note is what a session wrote; a rich-text tip would otherwise run it (`<img>` reads files)."""
    hostile = {"do": "<b>bold</b> & <img src='file:///etc/hosts'>", "expect": "a < b > c",
               "if_not": "</div><i>x"}
    process.add_step("2.1", "listen to the voice", note=hostile)

    row = _row(_panel(project), "listen to the voice")

    for markup in (_icons(row)[0].hover_tip.text(), row._note_view.text()):
        assert "<img" not in markup and "<b>bold" not in markup and "<i>x" not in markup, markup
        said = _seen(markup)
        assert hostile["do"] in said and "a < b > c" in said and "</div><i>x" in said, said


def test_the_note_view_is_rich_text_on_purpose(process, project):
    """Escaped text in a label that guesses its format is one edit from being read as markup."""
    process.add_step("2.1", "listen to the voice", note=NOTE)

    row = _row(_panel(project), "listen to the voice")

    assert row._note_view.textFormat() == Qt.TextFormat.RichText


def test_line_breaks_in_a_note_are_kept(process, project):
    process.add_step("2.1", "listen to the voice",
                     note={"expect": "first line\nsecond line"})

    row = _row(_panel(project), "listen to the voice")

    for said in (_tip(row), _seen(row._note_view.text())):
        assert "first line\nsecond line" in said, said


@pytest.mark.parametrize("note", [_ABSENT, {}, None, "a string", ["a", "list"], 7, {"do": "  "},
                                  {"unknown": "text"}, {"do": 5, "expect": ["x"], "if_not": None}],
                         ids=["absent-older-project", "empty", "null", "string", "list", "number",
                              "blank", "unknown-key-only", "no-string-field"])
def test_nothing_readable_means_no_icon_and_the_plan_still_draws(process, project, note):
    process.add_step("2.1", "listen to the voice")
    _edit_note(project, "2.1", note)

    panel = _panel(project)

    row = _row(panel, "listen to the voice")
    assert _icons(row) == []
    assert getattr(row, "_note_view", None) is None


def test_a_field_that_is_not_a_string_and_an_unknown_key_are_left_out(process, project):
    process.add_step("2.1", "listen to the voice")
    _edit_note(project, "2.1", {"do": 5, "expect": "  the voice  ", "because": "UNKNOWN KEY"})

    tip = _tip(_row(_panel(project), "listen to the voice"))

    assert "the voice" in tip and "UNKNOWN KEY" not in tip
    assert i18n.t("planNoteDo") not in tip


def test_a_long_note_is_short_in_the_tip_and_whole_on_click(process, project):
    long_text = " ".join(f"word{i}" for i in range(900))
    process.add_step("2.1", "listen to the voice", note={"expect": long_text})

    row = _row(_panel(project), "listen to the voice")

    tip = _tip(row)
    assert len(tip.splitlines()) <= 12, f"{len(tip.splitlines())} lines is not a tip"
    assert "word899" not in tip
    assert i18n.t("planNoteReadAll") in tip
    assert "word899" in _seen(row._note_view.text())


def test_a_short_note_does_not_say_there_is_more(process, project):
    process.add_step("2.1", "listen to the voice", note=NOTE)

    assert i18n.t("planNoteReadAll") not in _tip(_row(_panel(project), "listen to the voice"))


def test_one_endless_word_does_not_widen_the_column(process, project):
    token = "x" * 600
    process.add_step("2.1", "listen to the voice", note={"expect": token})
    panel = _panel(project)
    _show(panel, 220)

    row = _row(panel, "listen to the voice")
    _icons(row)[0].mousePressEvent(None)
    QApplication.processEvents()
    QApplication.processEvents()

    assert panel.horizontalScrollBar().maximum() == 0
    view = row._note_view
    assert view.height() >= view.heightForWidth(view.width()), "the word is wrapped, not cut"
    assert view.heightForWidth(view.width()) > 3 * view.fontMetrics().height(), "and it did wrap"
    tip = _tip(row)
    assert max(len(line) for line in tip.splitlines()) <= 80, "the tip's label does not wrap"
    assert i18n.t("planNoteReadAll") in tip
    panel.close()


_TITLE_AND_REST = "Check the voice at the seat — a long reason the method wrote after the name"


@pytest.mark.parametrize("look", ["normal", "typewriter"])
def test_the_icon_fits_beside_the_hint_in_the_narrow_column(process, project, look):
    process.add_step("2.1", _TITLE_AND_REST, note=NOTE)
    process.add_step("2.2", _TITLE_AND_REST.replace("voice", "image"))
    panel = _panel(project)
    panel.setStyleSheet(theme.build_qss(theme.get_theme("dark"), font=look))
    _show(panel, 200)

    noted = _row(panel, "the voice")
    plain = _row(panel, "the image")
    name, hint = (noted.findChildren(QLabel)[0],
                  next(w for w in noted.findChildren(QLabel)
                       if w.property("class") == "step-title-hint"))
    icon = _icons(noted)[0]

    assert panel.horizontalScrollBar().maximum() == 0, "the row must not push the column wider"
    for part in (hint, icon):
        assert part.isVisible() and part.width() > 0
        left = part.mapTo(noted, part.rect().topLeft()).x()
        assert 0 <= left and left + part.width() <= noted.width(), "cut at the row's edge"
    assert hint.mapTo(noted, hint.rect().bottomLeft()).y() < icon.mapTo(noted, icon.rect().topLeft()).y()
    title_right = name.mapTo(noted, name.rect().topRight()).x()
    assert title_right < hint.mapTo(noted, hint.rect().topLeft()).x()
    assert title_right < icon.mapTo(noted, icon.rect().topLeft()).x()

    assert name.height() >= name.heightForWidth(name.width()), "the title is wrapped, not cut"
    plain_name = plain.findChildren(QLabel)[0]
    assert plain_name.width() - name.width() <= 4, "under the `?`, the icon costs the title almost nothing"
    panel.close()


def test_a_session_writing_refreshes_the_note_and_keeps_the_folds_and_the_scroll(process, project):
    """The window reloads the plan on every write of the state (`process_watch`)."""
    for n in range(40):
        process.add_step(f"1.{n}", f"early step number {n}", phase="1")
    process.add_step("2.1", "listen to the voice", note=NOTE)
    panel = _panel(project)
    _show(panel, 320, 240)

    earlier = next(r for r in panel.widget().findChildren(_PhaseRow)
                   if any("early step number 3" in w.text() for w in r.findChildren(QLabel)))
    assert earlier._steps_container.isHidden()
    earlier._toggle(None)
    _icons(_row(panel, "listen to the voice"))[0].mousePressEvent(None)
    QApplication.processEvents()
    QApplication.processEvents()
    bar = panel.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    assert bar.value() > 0
    where = bar.value()

    process.start_attempt("2.1")
    process.finish_step("2.1", ["v_003"], heard="left, as predicted")
    panel.set_plan(_plan(project))
    panel.set_open_questions({"project.json:a"})
    QApplication.processEvents()
    QApplication.processEvents()

    row = _row(panel, "listen to the voice")
    assert not row._note_view.isHidden(), "the note the Arbiter opened stays open"
    assert "left, as predicted" in _seen(row._note_view.text()), "and it is the new text"
    assert "left, as predicted" in _tip(row)
    earlier = next(r for r in panel.widget().findChildren(_PhaseRow)
                   if any("early step number 3" in w.text() for w in r.findChildren(QLabel)))
    assert not earlier._steps_container.isHidden(), "the phase he opened stays open"
    assert bar.value() == where, "and the plan stays where he scrolled it"
    panel.close()


def test_the_next_phase_still_opens_itself_when_the_plan_moves_on(process, project):
    """What is remembered is what he changed, not the default of the moment."""
    process.add_step("3.1", "later step", phase="3")
    panel = _panel(project)
    current = next(r for r in panel.widget().findChildren(_PhaseRow)
                   if not r._steps_container.isHidden())
    current._toggle(None)  # his fold on the current phase, kept below

    process.enter_phase("3")
    panel.set_plan(_plan(project))

    later = next(r for r in panel.widget().findChildren(_PhaseRow)
                 if any("later step" in w.text() for w in r.findChildren(QLabel)))
    assert not later._steps_container.isHidden()


def test_an_unchanged_plan_does_not_rebuild_the_rows(process, project):
    """A write that changes nothing on screen leaves the rows alone: a selection, a tip, the lot."""
    process.add_step("2.1", "listen to the voice", note=NOTE)
    panel = _panel(project)
    before = _row(panel, "listen to the voice")

    panel.set_plan(_plan(project))
    panel.set_open_questions(())

    assert _row(panel, "listen to the voice") is before


def test_another_project_does_not_inherit_what_was_opened(process, project, tmp_path, monkeypatch):
    process.add_step("2.1", "listen to the voice", note=NOTE)
    panel = _panel(project)
    _icons(_row(panel, "listen to the voice"))[0].mousePressEvent(None)
    plan = _plan(project)

    other = tmp_path / "another-project"
    other.mkdir()
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(other))
    panel.set_plan(plan[:-1] + plan[-1:])  # same steps, another folder: nothing to inherit
    panel.retranslate()

    assert _row(panel, "listen to the voice")._note_view.isHidden()


def test_a_covers_list_stays_open_through_a_reload_too(process, project):
    process.add_step("2.1", "close the fields", covers=["project.json:a"])
    panel = _panel(project)
    row = _row(panel, "close the fields")
    chip = next(w for w in row.findChildren(QLabel)
                if "step-covers-chip" in (w.property("class") or ""))
    chip.mousePressEvent(None)

    process.add_step("2.2", "one more")
    panel.set_plan(_plan(project))

    assert not _row(panel, "close the fields")._covers_list.isHidden()


def test_a_step_with_a_note_is_not_folded_into_a_run(process, project):
    """A folded row counts its steps; one prediction on it would read as all of theirs, or be lost.

    Names as an older copy wrote them, with no id in front: only those can fold, and such a step
    still gets a note when a late answer is written on it (`done --heard`).
    """
    for step_id, channel in (("2.1", "tw-L"), ("2.2", "tw-R"), ("2.3", "mid-L")):
        process.add_step(step_id, f"Baseline solo: {channel}")
    path = process_view.state_file(project)
    state = json.loads(path.read_text(encoding="utf-8"))
    for entry in state["plan"]:
        if entry["id"] in ("2.1", "2.2", "2.3"):
            entry["name"] = entry["name"].split(" ", 1)[1]
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    _edit_note(project, "2.2", {"answer": "heard it late"})
    panel = _panel(project)

    noted = _row(panel, "tw-R")

    assert "heard it late" in _tip(noted)
    assert " \u00b7 " not in noted.findChildren(QLabel)[0].text(), "not a counted row"


def test_showing_a_note_writes_nothing(process, project):
    """`process-state.json` is the method's: TCC reads it and has no key of its own in it."""
    process.add_step("2.1", "listen to the voice", note=NOTE)
    path = process_view.state_file(project)
    before = path.read_bytes()

    panel = _panel(project)
    _icons(_row(panel, "listen to the voice"))[0].mousePressEvent(None)
    panel.retranslate()

    assert path.read_bytes() == before


def test_the_note_is_read_with_the_keys_the_method_writes(process, project):
    """The seam, held from TCC's side: the method's writer against TCC's reader. The method's schema
    (`state/process-schema.md`, «A step's note») is the only description; a key renamed there goes
    red here, on the nightly against the method's newest tag too."""
    process.add_step("2.1", "listen to the voice", note=NOTE)
    process.start_attempt("2.1")
    process.finish_step("2.1", ["v_003"], heard="as predicted")

    written = next(s for s in process_view.load_state(project)["plan"] if s["id"] == "2.1")["note"]
    read = next(s for p in _plan(project) for s in p.steps if s.id == "2.1").note

    assert set(written) == set(StepNote.__dataclass_fields__)
    assert read == StepNote(answer="as predicted", **NOTE)


def test_the_labels_are_in_every_language():
    keys = ("planNoteDo", "planNoteExpect", "planNoteAnswer", "planNoteIfNot", "planNoteReadAll")
    for lang in ("en", "uk", "pl", "de"):
        assert all(i18n._CORE[lang].get(key) for key in keys), lang
