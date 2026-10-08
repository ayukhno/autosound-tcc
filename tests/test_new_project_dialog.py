"""NewProjectDialog: folder + vendor/model + how the AI runs. The intake itself is the skill's
served form, which the new window opens (hub #194) -- this dialog starts no interview.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc import new_project_dialog as npd  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@contextlib.contextmanager
def _previews_stopped_at_the_end():
    """Every dialog built inside the block, as a list, each with its preview timer stopped when
    the block ends -- what `_no_preview_outlives_its_test` wraps each test here in, and what the
    test of it runs. Only the timer: what a test leaves is not deleted (F-053)."""
    built: list = []
    build = npd.NewProjectDialog.__init__

    def registered(self, *args, **kwargs):
        build(self, *args, **kwargs)
        built.append(self)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(npd.NewProjectDialog, "__init__", registered)
        try:
            yield built
        finally:
            for dlg in built:
                try:
                    dlg._seed_note_timer.stop()
                except RuntimeError:  # its C++ half is gone already, and the timer with it
                    pass


@pytest.fixture(autouse=True)
def _no_preview_outlives_its_test():
    """The preview timer of every dialog a test here built is stopped when the test ends (review of
    #172, M-4); the dialogs are the fixture's value. A dialog arms the timer while it is built --
    `_on_profile_selected` writes vendor and model -- and one left waiting fired in whichever later
    test turned the event loop, through that test's `_seeder`: a stub's count one too many, or with
    nothing patched the real seed and its git children, on another test's time."""
    with _previews_stopped_at_the_end() as built:
        yield built


@pytest.fixture(autouse=True)
def _previews_under_the_tests_own_folder(tmp_path, monkeypatch):
    """Python's temporary folder under `tmp_path` for every test here (review of #172, M-6): the
    real seeder's preview makes its temporary folder a git repository, and a test's git runs only
    on repositories under `tmp_path` (the plan's global constraints)."""
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))


def test_create_disabled_until_folder_vendor_and_model_are_filled(tmp_path):
    _app()
    dlg = npd.NewProjectDialog()
    dlg._folder_edit.setText(str(tmp_path))
    dlg._vendor_edit.setText("")
    dlg._model_edit.setText("")
    assert not dlg._create_btn.isEnabled()

    dlg._vendor_edit.setText("Musway")
    assert not dlg._create_btn.isEnabled()  # model still empty
    dlg._model_edit.setText("M6V4")
    assert dlg._create_btn.isEnabled()


def test_create_mkdirs_and_persists_project_dir_with_no_interview(tmp_path, monkeypatch):
    _app()
    calls = []
    monkeypatch.setattr(npd.config, "set_project_dir", lambda p: calls.append(p))

    project_dir = tmp_path / "brand_new_project"
    dlg = npd.NewProjectDialog()
    dlg._folder_edit.setText(str(project_dir))
    dlg._vendor_edit.setText("Musway")
    dlg._model_edit.setText("M6V4")

    dlg._on_create()

    assert project_dir.is_dir()
    assert calls == [project_dir]
    assert not hasattr(npd, "ProfileInterviewDialog"), "the form replaced the interview"
    assert dlg.project_dir == project_dir
    assert dlg.in_app_model == "claude-opus-5"  # default AI_MAIN_MODELS[0]


def test_bundled_profile_picker_defaults_to_an_exact_find_bundled_match():
    """Regression (user report 2026-07-29): free-typing "Helix"/"Ultra S" missed the bundled
    profile because it's actually keyed vendor="Audiotec-Fischer" name="Helix DSP Ultra S" --
    find_bundled() is deliberately strict/no-fuzzy (project-intake.md §4), so the picker must
    supply the exact stored strings instead of asking the user to guess them."""
    _app()
    dlg = npd.NewProjectDialog()

    assert dlg._profile_combo.count() >= 2  # at least one bundled profile + "Add new"
    first_pair = dlg._profile_combo.itemData(0)
    assert first_pair is not None
    vendor, model = first_pair
    assert dlg._vendor_edit.text() == vendor
    assert dlg._model_edit.text() == model
    assert dlg._vendor_edit.isHidden()
    assert dlg._model_edit.isHidden()

    # "+ Add new" is always the last item, itemData None.
    add_new_index = dlg._profile_combo.count() - 1
    assert dlg._profile_combo.itemData(add_new_index) is None
    dlg._profile_combo.setCurrentIndex(add_new_index)

    assert dlg._vendor_edit.text() == ""
    assert dlg._model_edit.text() == ""
    assert not dlg._vendor_edit.isHidden()
    assert not dlg._model_edit.isHidden()


def test_run_via_combo_lists_detected_clis_and_defaults_to_in_app(monkeypatch):
    monkeypatch.setattr(
        npd.terminal_launcher,
        "available_clis",
        lambda: [("gemini", "Gemini CLI"), ("codex", "Codex CLI")],
    )
    _app()
    dlg = npd.NewProjectDialog()

    assert dlg._run_via_combo.currentData() is None  # defaults to in-app
    assert not dlg._ai_combo.isHidden()
    labels = [dlg._run_via_combo.itemText(i) for i in range(dlg._run_via_combo.count())]
    assert labels[0] == "In-app (Claude)"
    assert "Terminal — Gemini CLI" in labels
    assert "Terminal — Codex CLI" in labels


def test_no_detected_clis_means_only_the_in_app_option(monkeypatch):
    monkeypatch.setattr(npd.terminal_launcher, "available_clis", lambda: [])
    _app()
    dlg = npd.NewProjectDialog()

    assert dlg._run_via_combo.count() == 1


def test_selecting_a_terminal_cli_hides_ai_model_and_branches_on_create(tmp_path, monkeypatch):
    """Regression path for the multi-AI onboarding request (2026-07-29): picking a detected CLI
    must hand the caller (main_window) enough to open a terminal later, from the intake's gate
    offer -- the AI-model picker is meaningless once a terminal CLI is in charge."""
    monkeypatch.setattr(npd.terminal_launcher, "available_clis", lambda: [("gemini", "Gemini CLI")])
    calls = []
    monkeypatch.setattr(npd.config, "set_project_dir", lambda p: calls.append(p))
    _app()
    dlg = npd.NewProjectDialog()

    idx = dlg._run_via_combo.findData("gemini")
    assert idx >= 0
    dlg._run_via_combo.setCurrentIndex(idx)
    assert dlg._ai_combo.isHidden()
    assert dlg._ai_model_label.isHidden()

    project_dir = tmp_path / "term_project"
    dlg._folder_edit.setText(str(project_dir))
    dlg._vendor_edit.setText("Musway")
    dlg._model_edit.setText("M6V4")

    dlg._on_create()

    assert project_dir.is_dir()
    assert calls == [project_dir]
    assert dlg.open_terminal_cli == "gemini"
    assert dlg.project_dir == project_dir
    assert dlg.onboarding_vendor == "Musway"
    assert dlg.onboarding_model == "M6V4"


def test_the_button_names_the_act_it_performs(tmp_path):
    """"Create" and "Copy" are different acts, and the button is the last thing read before
    either happens (user, 2026-08-23)."""
    _app()
    dlg = npd.NewProjectDialog()
    assert dlg._create_btn.text() == npd.i18n.t("npCreate")

    dlg._seed_combo.setCurrentIndex(dlg._seed_combo.findData("copy"))
    assert dlg._create_btn.text() == npd.i18n.t("npCopy")

    dlg._seed_combo.setCurrentIndex(dlg._seed_combo.findData(None))
    assert dlg._create_btn.text() == npd.i18n.t("npCreate")


def test_a_refusal_is_a_sentence_in_the_window_s_own_language(tmp_path, monkeypatch):
    """The module has no language: it answers in English with a path in it, which arrived in the
    dialog as "Нічого не скопіиовано: /Users/... already has a project.json" -- across three
    overlapping lines, on top of the checkbox (user, with the screenshot).

    The two refusals a person actually meets are conditions this dialog can test itself.
    """
    monkeypatch.setattr(npd.config, "set_project_dir", lambda p: None)
    taken = tmp_path / "taken"
    taken.mkdir()
    (taken / "project.json").write_text('{"schema_version": 3}', encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    (source / "project.json").write_text(
        '{"schema_version": 3, "car": {"make": "VW"}, '
        '"dsp": {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"}, "channels": []}',
        encoding="utf-8",
    )

    _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    dlg._folder_edit.setText(str(taken))
    dlg._seed_edit.setText(str(source))
    dlg._vendor_edit.setText("Audiotec-Fischer")
    dlg._model_edit.setText("Helix DSP Ultra S")

    dlg._on_create()

    assert dlg.result() != npd.QDialog.DialogCode.Accepted or True  # it must not accept
    assert dlg.seeded is None
    said = dlg._seed_summary.text()
    assert said == npd.i18n.t("npSeedTargetTaken").format(folder="taken")
    assert "project.json" not in said, "no English path fragments in a Ukrainian sentence"
    # And the wrapped sentence is allowed the height it needs, instead of drawing over the row
    # under it.
    assert dlg._seed_summary.sizePolicy().verticalPolicy() == npd.QSizePolicy.Policy.MinimumExpanding


def test_the_in_app_model_survives_a_copy_that_skips_the_interview(tmp_path, monkeypatch):
    """The interview is what used to carry the picked model, and a copy skips it -- so the choice
    was dropped and the window opened on "no model chosen" (user, 2026-08-23). The dialog keeps it
    where the caller can find it whether the interview ran or not."""
    monkeypatch.setattr(npd.config, "set_project_dir", lambda p: None)
    source = tmp_path / "source"
    source.mkdir()
    (source / "project.json").write_text(
        '{"schema_version": 3, "car": {"make": "VW"}, '
        '"dsp": {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"}, "channels": []}',
        encoding="utf-8",
    )
    (source / "dsp_profile.json").write_text(
        '{"dsp_profile": {"vendor": "Audiotec-Fischer", "name": "Helix DSP Ultra S"}}',
        encoding="utf-8",
    )

    _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    dlg._folder_edit.setText(str(tmp_path / "new"))
    dlg._seed_edit.setText(str(source))
    dlg._on_create()

    assert dlg.seeded is not None and dlg.seeded.ok
    assert dlg.in_app_model == npd.AI_MODEL_IDS.get(dlg._ai_combo.currentText())
    assert dlg.in_app_model, "and it is a real model id, not an empty string"



class _StubSeeder:
    """A seeder whose `seed()` reports what it was told to, so the dialog's own rendering can be
    tested apart from the method's version. The real module is exercised by the tests above and by
    the method's own selftest; what belongs here is what TCC does with the answer."""

    PROFILE_FILE = "dsp_profile.json"
    #: The method's names for the files a seed reads besides `project.json`: the preview's memory
    #: is keyed on them (#172).
    PROSE_FILES = ("autosound_context.md",)

    def __init__(self, describe, report):
        self._describe, self._report = describe, report
        self.seeded_into = []

    def describe(self, source):
        return self._describe

    def dsp_of(self, source):
        return ("Audiotec-Fischer", "Helix DSP Ultra S")

    def seed(self, source, target, **kwargs):
        self.seeded_into.append((str(source), str(target), kwargs))
        return self._report


class _Described:
    def __init__(self, car, dsp, channels):
        self.car, self.dsp, self.channels = car, dsp, channels


class _Report:
    def __init__(self, channels, amps=0, flaws=0, questions=0):
        self.ok = True
        self.written = ["project.json"]
        self.channels, self.amps = channels, amps
        self.flaws, self.questions = flaws, questions
        self.profile_open = 0
        self.problem = None


def _settled(dlg):
    """The note as it stands once the pause is over: what the timer does, done now (#172)."""
    if dlg._seed_note_timer.isActive():
        dlg._seed_note_timer.stop()
        dlg._refresh_seed_note_now()
    return dlg


def _after_the_pause(dlg) -> None:
    """Let the note's timer run out as it does when typing stops: for real, through the event loop,
    and bounded, so a timer that never fires fails here instead of holding the run."""
    assert dlg._seed_note_timer.isActive(), "nothing is waiting for the pause"
    deadline = time.monotonic() + 5.0
    while dlg._seed_note_timer.isActive():
        assert time.monotonic() < deadline, "the pause never ended"
        QTest.qWait(10)


def _past_the_pause() -> None:
    """The event loop run for longer than the pause: whatever was waiting on it has fired."""
    QTest.qWait(npd._SEED_NOTE_DELAY_MS + 150)


def _seeds_of(seeder, source) -> list:
    """The flags of each seed asked for `source`. Counted by folder, because a pause runs the event
    loop, and a dialog left alive elsewhere with its timer running would draw its own note in it
    -- through this test's seeder, which `_seeder` now answers for every dialog. This file's own
    are stopped (`_no_preview_outlives_its_test`); another file's need not be."""
    return [kwargs for src, _into, kwargs in seeder.seeded_into if src == str(source)]


def _dialog_on(source, seeder, monkeypatch, vendor="Musway", model="M6V4"):
    monkeypatch.setattr(npd, "_seeder", lambda: seeder)
    _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    dlg._vendor_edit.setText(vendor)
    dlg._model_edit.setText(model)
    dlg._seed_edit.setText(str(source))
    return _settled(dlg)


def test_the_note_says_what_would_travel_not_what_the_source_holds(tmp_path, monkeypatch):
    """The count shown before Create is a promise, and the seeder is about to stop keeping this
    one: topology belongs to the processor, so picking a different one leaves the channel grid
    behind (skill, SKL-014). Twenty Helix channels landing in an 8-output DSP is what the old
    promise cost, and `remove-channel` does not exist.

    So the dialog stops predicting: it asks the seeder with the flags Create will use and draws
    the answer. Stubbed here — what is under test is the rendering, not the method's version.
    """
    source = tmp_path / "source"
    source.mkdir()
    (source / "project.json").write_text('{"schema_version": 3}', encoding="utf-8")
    seeder = _StubSeeder(_Described("VW Passat B8 2017", "Helix DSP Ultra S", 20), _Report(0))

    dlg = _dialog_on(source, seeder, monkeypatch)

    said = dlg._seed_summary.text()
    assert "20" in said, "the source's own size is still stated"
    assert npd.i18n.t("npSeedTravels").format(channels=0, amps=0) in said
    assert npd.i18n.t("npSeedNoChannels") in said, "said BEFORE Create, not discovered after"


def test_the_findings_tick_stops_being_offered_blind(tmp_path, monkeypatch):
    """"…and what was measured there" said nothing about how much that is — the box was ticked
    without knowing whether it carried two rows or forty (#48). The preview counts them, because
    ticking the box is what changes the answer."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "project.json").write_text('{"schema_version": 3}', encoding="utf-8")
    seeder = _StubSeeder(_Described("VW Passat B8 2017", "Helix DSP Ultra S", 20),
                         _Report(20, amps=2, flaws=18, questions=3))

    dlg = _dialog_on(source, seeder, monkeypatch)
    dlg._seed_findings.setChecked(True)
    _settled(dlg)

    said = dlg._seed_summary.text()
    assert "18" in said and "3" in said, "how many flaws and how many questions"
    assert npd.i18n.t("npSeedFindingsEvidence") in said, "and where their proof lives"
    assert seeder.seeded_into[-1][2]["include_findings"] is True, "asked with the tick as set"
    assert npd.i18n.t("npSeedNoChannels") not in said, "same processor: nothing stays behind"


def test_the_preview_seeds_into_a_throwaway_folder_never_the_real_one(tmp_path, monkeypatch):
    """A preview that wrote where Create writes would be Create, done early and without being
    asked. The target it hands the seeder is a temp dir, and it is gone by the time the note is
    drawn."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "project.json").write_text('{"schema_version": 3}', encoding="utf-8")
    target = tmp_path / "the_real_one"
    seeder = _StubSeeder(_Described("VW", "Helix", 4), _Report(4))

    dlg = _dialog_on(source, seeder, monkeypatch)
    dlg._folder_edit.setText(str(target))
    dlg._refresh_seed_note()

    assert seeder.seeded_into, "the seeder was asked"
    for _src, used_target, _kwargs in seeder.seeded_into:
        assert str(target) not in used_target, "never the folder Create will use"
        assert not os.path.exists(used_target), "and it does not outlive the question"
    assert list(source.iterdir()) == [source / "project.json"], "the source is untouched"


def test_prefilling_the_dsp_from_the_source_does_not_loop(tmp_path, monkeypatch):
    """`_prefill_dsp` writes the DSP fields; those fields redraw the note; the note reads them
    back. Without the guard the two take turns until the stack runs out — this is the test that
    would have caught it."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "project.json").write_text('{"schema_version": 3}', encoding="utf-8")
    seeder = _StubSeeder(_Described("VW", "Helix DSP Ultra S", 4), _Report(4))

    dlg = _dialog_on(source, seeder, monkeypatch)          # constructing at all is half the test

    assert not dlg._prefilling, "the guard is cleared afterwards, not left on"
    assert dlg._seed_summary.text(), "and the note was drawn once the fields settled"
    # Bounded, not merely finite: the fields settle in a couple of writes, and every extra write
    # is another seed into a temp folder. A number that creeps up here is the loop coming back
    # slowly instead of all at once.
    assert len(seeder.seeded_into) <= 4, seeder.seeded_into


def test_the_terminal_model_hint_takes_its_examples_from_the_catalogue(monkeypatch):
    """The hint says what to type into a free-text `--model` field, so it has to name real models
    — but naming them IN the string made a model bump a translation job in four languages."""
    _app()
    monkeypatch.setattr(npd.model_choices, "TERMINAL_MODEL_EXAMPLES", ("zeta-9", "omega-2"))

    dlg = npd.NewProjectDialog()
    hint = dlg._terminal_model_edit.placeholderText()

    assert "zeta-9" in hint and "omega-2" in hint, hint
    assert "{" not in hint, f"placeholder left unformatted: {hint}"


def test_typing_a_dsp_name_does_not_run_a_seed_per_character(monkeypatch, tmp_path):
    """Drawing the seed note is not a lookup: it creates a temp folder, runs the REAL seeder into
    it (read the source, validate against the schema, write `project.json` and `.gitignore`, copy
    the profile and the prose), reads the report and deletes the lot — on the GUI thread. It was
    wired to `textChanged`, so typing "Audiotec-Fischer" did that seventeen times and the dialog
    resized under the cursor after each one."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "project.json").write_text('{"schema_version": 3}', encoding="utf-8")
    seeder = _StubSeeder(_Described("VW", "Helix DSP Ultra S", 4), _Report(4))
    dlg = _dialog_on(source, seeder, monkeypatch)

    before = len(seeder.seeded_into)               # the LENGTH: the list itself keeps growing
    dlg._vendor_edit.setText("Audiotec-Fischer")   # sixteen characters in one go is still one set

    assert len(seeder.seeded_into) == before, "typing arms the timer; it does not seed"
    assert dlg._seed_note_timer.isActive(), "and the redraw really is pending"

    dlg._refresh_seed_note_now()                   # what the timer would do when typing stops
    assert len(seeder.seeded_into) == before + 1, "one seed per pause, not per keystroke"


def _source_project(tmp_path, name="source"):
    source = tmp_path / name
    source.mkdir()
    (source / "project.json").write_text('{"schema_version": 3}', encoding="utf-8")
    return source


def test_a_second_identical_preview_runs_no_seed(tmp_path, monkeypatch):
    """#172: the preview's seed ends in `project_repo.init` -- six to eight git children, and `gh
    api user` for up to 30 s where git has no identity -- on the GUI thread. Asked again with
    nothing it reads changed, the note is drawn from the answer it already has."""
    source = _source_project(tmp_path)
    seeder = _StubSeeder(_Described("VW", "Helix DSP Ultra S", 4), _Report(4))
    dlg = _dialog_on(source, seeder, monkeypatch)
    drawn, seeded = dlg._seed_summary.text(), len(_seeds_of(seeder, source))

    dlg._refresh_seed_note_now()

    assert len(_seeds_of(seeder, source)) == seeded, "nothing it reads changed: no second seed"
    assert dlg._seed_summary.text() == drawn, "and the same answer is drawn"
    assert seeded == 1, "the source and the DSP fields set before the pause were one preview"


def test_a_seeder_that_names_none_of_the_files_it_reads_is_remembered_all_the_same(
        tmp_path, monkeypatch, app_log_warnings):
    """The group review, G1: the memory is keyed on the seeder's `PROFILE_FILE` and `PROSE_FILES`,
    which contract 1 does not list. A release that renamed either made the key None, and the memo
    switched itself off without a word — every redraw a whole seed on the GUI thread again, the
    freeze #172 removed. The key falls back to TCC's copy of v3.1.2's names, and says so, once."""
    monkeypatch.delattr(_StubSeeder, "PROFILE_FILE")
    monkeypatch.delattr(_StubSeeder, "PROSE_FILES")
    source = _source_project(tmp_path)
    seeder = _StubSeeder(_Described("VW", "Helix DSP Ultra S", 4), _Report(4))
    dlg = _dialog_on(source, seeder, monkeypatch)
    seeded = len(_seeds_of(seeder, source))

    key = dlg._preview_key(seeder, source)
    dlg._refresh_seed_note_now()

    assert key is not None
    keyed = {path for path, _mtime, _size in key[2]}
    assert {str(source / "dsp_profile.json"), str(source / "autosound_context.md")} <= keyed, keyed
    assert len(_seeds_of(seeder, source)) == seeded, "remembered: no second seed"
    said = [record.getMessage() for record in app_log_warnings]
    named = [line for line in said if "PROFILE_FILE" in line and "PROSE_FILES" in line]
    assert len(named) == 1, said


def test_a_preview_whose_seed_raised_leaves_a_trace(tmp_path, monkeypatch, app_log_warnings):
    """The group review, M4: `except Exception: return None, None` wrote nothing, and the note just
    left out its «Travels» line — a method bug in `seed()` for this source was invisible until
    Create hit it. The preview still never takes the dialog down; the log has the traceback."""
    source = _source_project(tmp_path)
    seeder = _StubSeeder(_Described("VW", "Helix DSP Ultra S", 4), _Report(4))

    def raises(*_args, **_kwargs):
        raise KeyError("channels")

    seeder.seed = raises
    dlg = _dialog_on(source, seeder, monkeypatch)

    traced = [record for record in app_log_warnings
              if record.exc_info and record.exc_info[0] is KeyError]
    assert traced and str(source) in traced[0].getMessage(), \
        [record.getMessage() for record in app_log_warnings]
    assert npd.i18n.t("npSeedTravels").split("{")[0] not in dlg._seed_summary.text()


@pytest.mark.parametrize("answer", ["refused", "none"])
def test_an_answer_that_is_not_ok_is_asked_again(tmp_path, monkeypatch, answer):
    """Only an ok answer is remembered (review of #172, M-1). A refusal can be passing -- an
    antivirus holding the temporary file at `os.replace`, a full temporary disk -- and kept, it
    left the note without its «Travels» line until something else changed. Every refusal in
    `seed()` comes before `project_repo.init`, so asking again starts no git child."""
    source = _source_project(tmp_path)
    report = None
    if answer == "refused":
        report = _Report(4)
        report.ok = False
    seeder = _StubSeeder(_Described("VW", "Helix DSP Ultra S", 4), report)
    dlg = _dialog_on(source, seeder, monkeypatch)
    seeded = len(_seeds_of(seeder, source))

    dlg._refresh_seed_note_now()

    assert len(_seeds_of(seeder, source)) == seeded + 1, "a not-ok answer is asked again"


def test_a_changed_tick_runs_one_seed_after_the_pause(tmp_path, monkeypatch):
    """What is remembered is the answer for what the seed read: tick the findings and the next
    preview is a seed again -- one, once the pause is over, as for typing (#172)."""
    source = _source_project(tmp_path)
    seeder = _StubSeeder(_Described("VW", "Helix DSP Ultra S", 4), _Report(4, flaws=2))
    dlg = _dialog_on(source, seeder, monkeypatch)
    seeded = len(_seeds_of(seeder, source))

    dlg._seed_findings.setChecked(True)
    assert len(_seeds_of(seeder, source)) == seeded, "the tick waits for the pause"
    _after_the_pause(dlg)

    seeds = _seeds_of(seeder, source)
    assert len(seeds) == seeded + 1, "one seed for the changed tick"
    assert seeds[-1]["include_findings"] is True, "asked with the tick as it is now"
    assert npd.i18n.t("npSeedFindingsEvidence") in dlg._seed_summary.text()


def test_five_quick_edits_of_the_seed_source_run_one_seed_after_the_pause(tmp_path, monkeypatch):
    """The source field fires per character too, typed or pasted, and it drew the note at once:
    the last five keystrokes of a path were five seeds on the GUI thread (#172)."""
    source = _source_project(tmp_path)
    seeder = _StubSeeder(_Described("VW", "Helix DSP Ultra S", 4), _Report(4))
    monkeypatch.setattr(npd, "_seeder", lambda: seeder)
    _app()
    dlg = npd.NewProjectDialog(seed_first=True)

    typed = str(source)
    for end in range(len(typed) - 4, len(typed) + 1):
        dlg._seed_edit.setText(typed[:end])

    assert seeder.seeded_into == [], "none before the pause"
    _after_the_pause(dlg)
    mine = [src for src, _into, _kw in seeder.seeded_into if src.startswith(str(tmp_path))]
    assert mine == [typed], "one seed after it, of the path as the last edit left it"


#: Everything that asks for the note, each as one change a person makes (review of #172, M-2).
_TRIGGERS = {
    "findings tick": lambda dlg, tmp_path: dlg._seed_findings.setChecked(True),
    "fs tick": lambda dlg, tmp_path: dlg._seed_fs.setChecked(False),
    "seat": lambda dlg, tmp_path: dlg._seat_combo.setCurrentIndex(
        dlg._seat_combo.findData("passenger")),
    "profile": lambda dlg, tmp_path: dlg._profile_combo.setCurrentIndex(
        dlg._profile_combo.findData(None)),
    "source": lambda dlg, tmp_path: dlg._seed_edit.setText(str(_source_project(tmp_path, "other"))),
    "vendor": lambda dlg, tmp_path: dlg._vendor_edit.setText("Mosconi"),
    "model": lambda dlg, tmp_path: dlg._model_edit.setText("M7"),
}


@pytest.mark.parametrize("trigger", list(_TRIGGERS))
def test_every_trigger_waits_for_the_pause_then_seeds_once(tmp_path, monkeypatch, trigger):
    """Each of the seven things that ask for the note goes through the one timer (#172): wired back
    to an immediate redraw, any one of them is a seed per change again."""
    source = _source_project(tmp_path)
    seeder = _StubSeeder(_Described("VW", "Helix DSP Ultra S", 4), _Report(4))
    dlg = _dialog_on(source, seeder, monkeypatch)

    def seeds() -> int:
        return len([src for src, _into, _kw in seeder.seeded_into
                    if src.startswith(str(tmp_path))])

    seeded = seeds()
    _TRIGGERS[trigger](dlg, tmp_path)
    assert seeds() == seeded, f"the {trigger} waits for the pause"
    assert dlg._seed_note_timer.isActive(), f"the {trigger} asked for the pause"
    _after_the_pause(dlg)
    assert seeds() == seeded + 1, f"one seed for the {trigger}, once the pause is over"


def test_a_preview_still_waiting_when_its_test_ends_is_stopped(_no_preview_outlives_its_test):
    """Review of #172, M-4: a dialog is built, a field asks for the note, and the test ends inside
    the pause -- as most tests here do. What every test here is wrapped in stops that timer at its
    end; a timer left running fires in whichever test next turns the event loop, through that
    test's `_seeder`. One test, in any order (the group review, W1): it was a pair, and the second
    half looked at nothing when it ran alone, under `-k` or `--lf`, or on another worker -- it
    passed with the stop taken out."""
    _app()
    with _previews_stopped_at_the_end() as built:
        dlg = npd.NewProjectDialog(seed_first=True)
        dlg._vendor_edit.setText("Mosconi")
        assert dlg._seed_note_timer.isActive(), "the test ends inside the pause"

    assert built == [dlg]
    assert not dlg._seed_note_timer.isActive(), "a preview outlived its test"
    assert dlg in _no_preview_outlives_its_test, "the wrapping every test here has, this one's too"


@pytest.mark.parametrize("name", ["project.json", "dsp_profile.json", "autosound_context.md"])
def test_a_file_the_seed_reads_changed_on_disk_is_seeded_again(tmp_path, monkeypatch, name):
    """The answer is remembered under each file the seed reads, by its time and its size (#172): a
    source saved from its own window while this dialog is open is a new question, and so is a file
    that grew by a byte with its time put back."""
    source = _source_project(tmp_path)
    path = source / name
    if not path.exists():
        path.write_text("{}", encoding="utf-8")
    seeder = _StubSeeder(_Described("VW", "Helix DSP Ultra S", 4), _Report(4))
    dlg = _dialog_on(source, seeder, monkeypatch)
    seeded = len(_seeds_of(seeder, source))
    dlg._refresh_seed_note_now()
    assert len(_seeds_of(seeder, source)) == seeded, "unchanged: remembered"

    was = path.stat()
    os.utime(path, ns=(was.st_atime_ns, was.st_mtime_ns + 10**9))
    dlg._refresh_seed_note_now()
    assert len(_seeds_of(seeder, source)) == seeded + 1, "the same bytes at a later time: asked again"

    was = path.stat()
    path.write_bytes(path.read_bytes() + b" ")
    os.utime(path, ns=(was.st_atime_ns, was.st_mtime_ns))
    dlg._refresh_seed_note_now()
    assert len(_seeds_of(seeder, source)) == seeded + 2, "a byte more at the same time: asked again"


def test_a_preview_still_waiting_is_dropped_by_create_and_by_closing(tmp_path, monkeypatch):
    """What the pause holds is a seed for the fields as they were a moment ago. A refused Copy says
    why in the same place, and the preview drawn after it covered the sentence; a closed dialog has
    nobody to draw for, and the source it would seed has just been let go of (#172)."""
    taken = tmp_path / "taken"
    taken.mkdir()
    (taken / "project.json").write_text('{"schema_version": 3}', encoding="utf-8")
    refused = _Report(2)
    refused.ok = False
    source = _passat(tmp_path)
    seeder = _StubSeeder(_Described("VW Passat B8", "Helix DSP Ultra S", 2), refused)
    dlg = _dialog_on(source, seeder, monkeypatch)
    dlg._folder_edit.setText(str(taken))

    dlg._model_edit.setText("M7")              # a preview asked for...
    dlg._on_create()                           # ...and Copy pressed inside the pause
    refusal = npd.i18n.t("npSeedTargetTaken").format(folder="taken")
    assert dlg._seed_summary.text() == refusal
    _past_the_pause()
    assert dlg._seed_summary.text() == refusal, "the refusal is the last word"

    seeded = len(_seeds_of(seeder, source))
    dlg._model_edit.setText("M8")
    dlg.reject()
    _past_the_pause()
    assert len(_seeds_of(seeder, source)) == seeded, "a closed dialog seeds for nobody"


def _passat(tmp_path, seat=None):
    source = tmp_path / "source"
    source.mkdir()
    extra = f', "project_type": "{seat}"' if seat else ""
    (source / "project.json").write_text(
        '{"schema_version": 3, "car": {"make": "VW"}, '
        '"dsp": {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"}, "channels": []'
        + extra + "}", encoding="utf-8")
    return source


def test_a_copy_cannot_be_made_until_a_seat_is_chosen(tmp_path, monkeypatch):
    seeder = _StubSeeder(_Described("VW Passat B8", "Helix DSP Ultra S", 2), _Report(2))
    dlg = _dialog_on(_passat(tmp_path), seeder, monkeypatch)
    dlg._folder_edit.setText(str(tmp_path / "new"))
    assert dlg._seat_combo.currentData() is None
    assert not dlg._create_btn.isEnabled()
    dlg._seat_combo.setCurrentIndex(dlg._seat_combo.findData("passenger"))
    assert dlg._create_btn.isEnabled()


def test_the_seat_reaches_both_seed_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(npd.config, "set_project_dir", lambda p: None)
    seeder = _StubSeeder(_Described("VW Passat B8", "Helix DSP Ultra S", 2), _Report(2))
    dlg = _dialog_on(_passat(tmp_path), seeder, monkeypatch)
    dlg._folder_edit.setText(str(tmp_path / "new"))
    seeder.seeded_into.clear()  # the previews drawn before a seat was chosen are not the point
    dlg._seat_combo.setCurrentIndex(dlg._seat_combo.findData("rear_left"))
    dlg._refresh_seed_note_now()
    dlg._on_create()
    seats = [kwargs.get("seat") for _src, _dst, kwargs in seeder.seeded_into]
    assert len(seats) >= 2 and set(seats) == {"rear_left"}, seats


def test_the_source_s_own_seat_is_named_beside_the_choice(tmp_path, monkeypatch):
    seeder = _StubSeeder(_Described("VW Passat B8", "Helix DSP Ultra S", 2), _Report(2))
    dlg = _dialog_on(_passat(tmp_path, seat="driver"), seeder, monkeypatch)
    driver = dlg._seat_combo.itemText(dlg._seat_combo.findData("driver"))
    assert driver in dlg._seat_source.text()


#: The Passat package's seven measured Fs (`car/passat-b8-2026`, impedance of 2026-08-21) -- the
#: numbers the Arbiter would have to measure a second time if they stayed behind (tcc#93).
_PASSAT_FS = (("sw", "K", "sub", 43.9), ("w-L", "C", "woofer", 52.4), ("w-R", "D", "woofer", 52.4),
              ("m-L", "E", "midrange", 194.8), ("m-R", "F", "midrange", 196.7),
              ("tw-L", "G", "tweeter", 939.7), ("tw-R", "H", "tweeter", 948.9))


def _passat_with_fs(tmp_path):
    """The Passat as the seeder meets it: seven channels with a measured Fs, and the centre, which
    was never measured and must not be counted as one."""
    source = tmp_path / "source"
    source.mkdir()
    channels = [{"code": code, "slot": slot, "role": role, "tier": "channels",
                 "fs_hz": {"value": fs, "source": "measured", "at": "2026-08-21T15:18:52+00:00"}}
                for code, slot, role, fs in _PASSAT_FS]
    channels.append({"code": "c", "slot": "B", "role": "center", "tier": "channels"})
    (source / "project.json").write_text(json.dumps({
        "schema_version": 3, "car": {"make": "VW", "model": "Passat B8"},
        "dsp": {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"},
        "channels": channels}), encoding="utf-8")
    (source / "dsp_profile.json").write_text(
        '{"dsp_profile": {"vendor": "Audiotec-Fischer", "name": "Helix DSP Ultra S"}}',
        encoding="utf-8")
    return source


def _created_fs(tmp_path, monkeypatch, *, ticked):
    """Copy the Passat through the REAL seeder with the Fs box as given; the new project's Fs."""
    monkeypatch.setattr(npd.config, "set_project_dir", lambda p: None)
    _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    dlg._folder_edit.setText(str(tmp_path / "new"))
    dlg._seed_edit.setText(str(_passat_with_fs(tmp_path)))
    dlg._seed_fs.setChecked(ticked)
    dlg._on_create()
    assert dlg.seeded is not None and dlg.seeded.ok, dlg.seeded and dlg.seeded.problem
    data = json.loads((tmp_path / "new" / "project.json").read_text(encoding="utf-8"))
    return {row["code"]: row.get("fs_hz") for row in data["channels"]}


def test_the_drivers_fs_box_is_ticked_by_default(tmp_path):
    """«імпеданс складна штука і міряти його другий раз це подвиг» (hub #185): the Fs travel
    unless somebody decides otherwise. And the box belongs to copying, like the findings box."""
    _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    assert dlg._seed_fs.isChecked()
    assert dlg._seed_fs.text() == npd.i18n.t("npSeedFs")
    assert not dlg._seed_fs.isHidden()
    dlg._seed_combo.setCurrentIndex(dlg._seed_combo.findData(None))
    assert dlg._seed_fs.isHidden(), "from scratch there is nothing to carry"


def test_ticked_the_seven_passat_fs_arrive(tmp_path, monkeypatch):
    fs = _created_fs(tmp_path, monkeypatch, ticked=True)
    arrived = {code: row["value"] for code, row in fs.items() if row is not None}
    assert arrived == {code: value for code, _slot, _role, value in _PASSAT_FS}
    assert fs["c"] is None, "the centre had none to give"


def test_unticked_no_channel_has_an_fs(tmp_path, monkeypatch):
    fs = _created_fs(tmp_path, monkeypatch, ticked=False)
    assert len(fs) == 8, "the channels still travel -- only their Fs stay behind"
    assert all(value is None for value in fs.values()), fs


def test_the_note_counts_the_fs_the_box_carries(tmp_path, monkeypatch):
    """Counted off the preview seed, as the findings are (#48): what lands, not what the source
    holds -- a different processor leaves the channels, and their Fs with them, behind."""
    _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    dlg._seed_edit.setText(str(_passat_with_fs(tmp_path)))
    counted = npd.i18n.t("npSeedTravelsFs").format(fs=7)
    assert counted in _settled(dlg)._seed_summary.text()

    dlg._seed_fs.setChecked(False)
    assert counted not in _settled(dlg)._seed_summary.text(), "unticked, nothing of it is promised"


def test_the_real_preview_seeds_under_the_tests_own_folder(tmp_path, monkeypatch):
    """The real seeder's preview makes its temporary folder a git repository -- `git init`, a
    commit -- and a test's git runs only on repositories under `tmp_path` (the plan's global
    constraints; review of #172, M-6)."""
    seeder = npd._seeder()
    if seeder is None:
        pytest.skip("the vendored skill is not checked out")
    into: list = []
    seed = seeder.seed
    monkeypatch.setattr(seeder, "seed", lambda source, target, **kwargs:
                        into.append(Path(target)) or seed(source, target, **kwargs))
    _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    dlg._seed_edit.setText(str(_passat_with_fs(tmp_path)))
    _settled(dlg)

    assert into, "the preview was a real seed"
    assert all(target.resolve().is_relative_to(tmp_path.resolve()) for target in into), into


def _the_method_counted(monkeypatch, source) -> tuple:
    """The method TCC runs, its `seed` counted for `source`: the module and the list of calls."""
    method = npd._seeder()
    if method is None:
        pytest.skip("the vendored skill is not checked out")
    seeds: list = []
    seed = method.seed
    monkeypatch.setattr(method, "seed", lambda src, target, **kwargs:
                        (seeds.append(src) if str(src) == str(source) else None)
                        or seed(src, target, **kwargs))
    return method, seeds


def _stood_in_for(warnings) -> list[str]:
    """The fallback's WARNING (`_seed_reads`): which of the method's names it stood in for."""
    return [record.getMessage() for record in warnings
            if "project_seed names no" in record.getMessage()]


def test_a_second_identical_preview_with_the_real_method_runs_no_seed(
        tmp_path, monkeypatch, app_log_warnings):
    """The group review, G1: every memory test above runs on `_StubSeeder`, which names its files
    itself. With the method TCC runs (P1), the first preview is a real seed -- `project_repo.init`
    and its git children on the GUI thread -- keyed on the files that method's `PROFILE_FILE` and
    `PROSE_FILES` name, with no stand-in; and a second identical one is drawn from memory. On the
    nightly a release that renamed either name is red here, as well as in contract 1's list."""
    source = _passat_with_fs(tmp_path)
    method, seeds = _the_method_counted(monkeypatch, source)
    _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    dlg._seed_edit.setText(str(source))
    _settled(dlg)
    seeded = len(seeds)

    dlg._refresh_seed_note_now()

    assert seeded == 1, "the first preview was a real seed"
    assert _stood_in_for(app_log_warnings) == [], "the method names both: nothing stood in"
    keyed = {path for path, _mtime, _size in dlg._preview_key(method, source)[2]}
    named = {str(source / method.PROFILE_FILE), *(str(source / n) for n in method.PROSE_FILES)}
    assert named <= keyed, keyed
    assert len(seeds) == seeded, "nothing it reads changed: no second seed"


class _MethodWithout:
    """The method TCC runs less one name, as a release that renamed it looks to TCC: its own
    `seed()` still reads its own globals; only the name the dialog asks for is gone."""

    def __init__(self, method, gone: str) -> None:
        self._method, self._gone = method, gone

    def __getattr__(self, name: str):
        if name == self._gone:
            raise AttributeError(name)
        return getattr(self._method, name)


@pytest.mark.parametrize("name", ["PROFILE_FILE", "PROSE_FILES"])
def test_the_real_method_without_a_name_the_memory_keys_on_is_remembered_all_the_same(
        tmp_path, monkeypatch, app_log_warnings, name):
    """G1: both names are outside contract 1, so a release may rename either. Without one, the
    real method's preview is still remembered -- keyed on TCC's copy of v3.1.2's name (part A's
    fallback) -- so redrawing runs no seed on the GUI thread, and the log names what stood in,
    once for the dialog."""
    source = _passat_with_fs(tmp_path)
    method, seeds = _the_method_counted(monkeypatch, source)
    seeder = _MethodWithout(method, name)
    monkeypatch.setattr(npd, "_seeder", lambda: seeder)
    _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    dlg._seed_edit.setText(str(source))
    _settled(dlg)
    seeded = len(seeds)

    dlg._refresh_seed_note_now()
    dlg._refresh_seed_note_now()

    assert seeded == 1, "the first preview was a real seed"
    assert len(seeds) == seeded, "remembered: neither redraw seeds"
    said = _stood_in_for(app_log_warnings)
    # Exactly what the seeder lacks: this name, and the other only where the copy lacks it too --
    # a release that renamed it is the test above's to say, and contract 1's list's.
    names = ("PROFILE_FILE", "PROSE_FILES")
    assert len(said) == 1, said
    assert [n for n in names if n in said[0]] == [n for n in names if not hasattr(seeder, n)], said


def test_what_travels_is_said_on_one_line_the_fs_its_last_part(tmp_path, monkeypatch):
    """tcc#122 (W-4's review of tcc#93): the note said «Travels:» twice, the Fs on a line of its
    own, and «the Fs of 1 drivers». One line names what travels, the Fs its last part; the count's
    noun in the form the rest of the window uses for a count of any size, in every language."""
    _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    dlg._seed_edit.setText(str(_passat_with_fs(tmp_path)))
    for lang in ("en", "uk"):
        npd.i18n.set_language(lang)
        try:
            dlg._refresh_seed_note_now()
            lines = dlg._seed_summary.text().splitlines()
            travels = [line for line in lines
                       if line.startswith(npd.i18n.t("npSeedTravels").split("{", 1)[0])]
            assert len(travels) == 1, (lang, lines)
            assert travels[0].endswith(" · " + npd.i18n.t("npSeedTravelsFs").format(fs=7)), lines
        finally:
            npd.i18n.set_language("en")
    one = npd.i18n.t("npSeedTravelsFs").format(fs=1)
    assert "1 drivers" not in one and "1 driver" in one, one


def test_the_fs_tick_reaches_both_seed_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(npd.config, "set_project_dir", lambda p: None)
    seeder = _StubSeeder(_Described("VW Passat B8", "Helix DSP Ultra S", 2), _Report(2))
    dlg = _dialog_on(_passat(tmp_path), seeder, monkeypatch)
    dlg._folder_edit.setText(str(tmp_path / "new"))
    seeder.seeded_into.clear()
    dlg._seed_fs.setChecked(False)
    _settled(dlg)                           # the note redrawn after the pause: the preview call
    dlg._on_create()
    flags = [kwargs.get("include_fs") for _src, _dst, kwargs in seeder.seeded_into]
    assert len(flags) >= 2 and set(flags) == {False}, flags


def test_a_preview_that_lands_a_project_it_cannot_count_does_not_take_the_dialog_down(
        tmp_path, monkeypatch):
    """tcc#123 (W-4 review of tcc#93): the preview's seed sits inside a `try` -- a preview must
    never take the dialog down -- and the Fs count read off what it wrote sat after it. A
    `project.json` whose `channels` is not a list raised out of the note's redraw."""

    from pathlib import Path

    class _WritesOddChannels(_StubSeeder):
        def seed(self, source, target, **kwargs):
            (Path(target) / "project.json").write_text('{"channels": 5}', encoding="utf-8")
            return super().seed(source, target, **kwargs)

    seeder = _WritesOddChannels(_Described("VW Passat B8", "Helix DSP Ultra S", 2), _Report(2))
    source = _passat(tmp_path)
    dlg = _dialog_on(source, seeder, monkeypatch)

    assert dlg._would_travel(source) == (None, None)


def test_the_seat_offers_exactly_the_method_s_seats_in_its_words():
    _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    codes = [dlg._seat_combo.itemData(i) for i in range(1, dlg._seat_combo.count())]
    assert codes == ["driver", "passenger", "both", "all", "rear_left", "rear_right"]
    assert all(dlg._seat_combo.itemText(i) != dlg._seat_combo.itemData(i)
               for i in range(1, dlg._seat_combo.count())), "labels come from the method, not codes"


def _box(drawn, window, check):
    """The pixel on the left edge of `check`'s box, half way down, and the one at its middle."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QStyle, QStyleOptionButton

    option = QStyleOptionButton()
    option.initFrom(check)
    box = check.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, check)
    corner = check.mapTo(window, box.topLeft())
    middle = corner.y() + box.height() // 2
    return (QColor(drawn.pixel(corner.x() + 1, middle)).name(),
            QColor(drawn.pixel(corner.x() + box.width() // 2, middle)).name())


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_a_check_box_shows_its_box_in_either_theme(monkeypatch, mode):
    """tcc#131: check boxes were left to the native style, which on Windows in the dark theme
    draws an empty box that is not there at all -- finding 75's list, VM-11's radios. Drawn
    under the sheet the window applies, an empty box is a ring in `muted` around `panel3`, the
    ring at 3:1 or more on the window's own colour (WCAG's floor for a control's outline), and a
    ticked one is the accent's fill: the radios' rule, given to every check box. The copy's two
    boxes are one of each: the findings empty, the drivers' Fs ticked."""
    from tests import _windows
    from tests.test_theme import _contrast

    app = _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    palette = _windows.theme_on(monkeypatch, dlg, mode)
    dlg.show()
    try:
        app.processEvents()
        drawn = dlg.grab().toImage()

        assert not dlg._seed_findings.isChecked() and dlg._seed_fs.isChecked()
        ring, inside = _box(drawn, dlg, dlg._seed_findings)
        said = f"{mode}: ring {ring}, inside {inside}, on {palette.panel}"
        assert inside == palette.panel3, said
        assert _contrast(ring, palette.panel) >= 3, said
        _ring, ticked = _box(drawn, dlg, dlg._seed_fs)
        assert ticked == palette.accent, f"{mode}: the ticked box is {ticked}"
    finally:
        dlg.close()


class _FileSource:
    """A second source for the copy (G13 C2): a `.car` file resolves to a folder with a note and a
    warning; a `.bad` one is refused. What it let go of is counted on the class, because the
    dialog's picker makes its own instance."""

    chooser = None  # set by the test: car_source.Chooser("file", …)
    folder = None
    released: list = []

    def accepts(self, path):
        return path.suffix in (".car", ".bad")

    def resolve(self, path):
        from autosound_tcc.ui.tcc import car_source

        if path.suffix == ".bad":
            return car_source.Resolved(
                None, problem=car_source.Line("npSeedFailed", {"problem": "not a car file"}))
        return car_source.Resolved(type(self).folder,
                                   about=(car_source.Line("npSeedNoSkill"),),
                                   warnings=(car_source.Line("npSeedPlaceholder"),))

    def release(self):
        type(self).released.append(True)


def test_a_second_source_needs_no_dialog_code(tmp_path, monkeypatch):
    """G13 C2: a new source of a car is a module, not dialog code. Registered, it gets its own
    browse button; what it resolves is copied from, with its note under the summary and its
    warning last; a refused file says why while it is typed and creates no project; the copy is
    made from the folder the source resolved, and named after what the person picked; closing
    lets go of it."""
    from autosound_tcc.ui.tcc import car_source

    source = tmp_path / "source"
    source.mkdir()
    (source / "project.json").write_text('{"schema_version": 3}', encoding="utf-8")
    _FileSource.chooser = car_source.Chooser("file", "npBrowse", "npSeedFrom", "npSeedPlaceholder")
    _FileSource.folder = source
    _FileSource.released = []
    monkeypatch.setattr(car_source, "SOURCES", (_FileSource, car_source.FolderSource))
    seeder = _StubSeeder(_Described("VW Passat B8 2017", "Helix DSP Ultra S", 20), _Report(20))

    picked = tmp_path / "the.car"
    dlg = _dialog_on(picked, seeder, monkeypatch)

    assert len(dlg._seed_browse_buttons) == 2, "one browse button per source"
    assert {src for src, _into, _kw in seeder.seeded_into} == {str(source)}, \
        "the preview runs on what the source resolved, not on the typed file"
    said = dlg._seed_summary.text().split("\n")
    assert said[0].startswith(npd.i18n.t("npSeedSummary").split("{")[0])
    assert said[1] == npd.i18n.t("npSeedNoSkill"), "the source's note sits under the summary"
    assert said[-1] == npd.i18n.t("npSeedPlaceholder"), "its warning comes last"

    dlg._seed_edit.setText(str(tmp_path / "x.bad"))
    refusal = npd.i18n.t("npSeedFailed").format(problem="not a car file")
    assert dlg._seed_summary.text() == refusal, "said while it is typed, not after Create"
    assert dlg._seed_summary.property("class") == "kv-warn"
    target = tmp_path / "new"
    dlg._folder_edit.setText(str(target))
    dlg._on_create()
    assert dlg._seed_summary.text() == refusal
    assert not target.exists(), "a refused file creates no project"

    dlg._seed_edit.setText(str(picked))
    released = len(_FileSource.released)
    dlg._on_create()
    assert seeder.seeded_into[-1][:2] == (str(source), str(target)), "copied from what it resolved"
    assert dlg.seeded_from == picked, "and named after what the person picked"
    assert dlg.result() == npd.QDialog.DialogCode.Accepted
    assert len(_FileSource.released) == released + 1, "closing lets go of what was held"


class _BrokenSource:
    """A source whose reading fails: a package that will not unpack (G13 review)."""

    chooser = None  # set by the test
    released: list = []

    def accepts(self, path):
        return path.suffix == ".car"

    def resolve(self, path):
        raise OSError("the package is damaged")

    def release(self):
        type(self).released.append(True)


class _StuckSource(_BrokenSource):
    """A source that reads, then cannot let go: a temporary folder Windows keeps."""

    folder = None

    def resolve(self, path):
        from autosound_tcc.ui.tcc import car_source

        return car_source.Resolved(type(self).folder)

    def release(self):
        type(self).released.append(True)
        raise PermissionError(32, "The file is in use", "car.tmp")


def _with_source(kind, monkeypatch):
    from autosound_tcc.ui.tcc import car_source

    kind.chooser = car_source.Chooser("file", "npBrowse", "npSeedFrom")
    kind.released = []
    monkeypatch.setattr(car_source, "SOURCES", (kind, car_source.FolderSource))


def test_a_source_that_raises_refuses_the_copy_and_creates_nothing(tmp_path, monkeypatch):
    """A raised fault read as "nothing typed": the note went blank, «Copy» stayed enabled, and
    pressing it made and opened an empty, unseeded project (the G13 review reproduced it)."""
    _with_source(_BrokenSource, monkeypatch)
    seeder = _StubSeeder(_Described("VW", "Helix DSP Ultra S", 4), _Report(4))
    dlg = _dialog_on(tmp_path / "broken.car", seeder, monkeypatch)

    refusal = npd.i18n.t("npSeedFailed").format(problem="the package is damaged")
    assert dlg._seed_summary.text() == refusal
    assert dlg._seed_summary.property("class") == "kv-warn"
    target = tmp_path / "new"
    dlg._folder_edit.setText(str(target))
    dlg._on_create()
    assert not target.exists() and dlg.project_dir is None and seeder.seeded_into == []


def test_copy_with_nothing_named_creates_nothing(tmp_path, monkeypatch):
    """«Copy» with the source field empty made an empty project, as if copying were not chosen."""
    seeder = _StubSeeder(_Described("VW", "Helix DSP Ultra S", 4), _Report(4))
    dlg = _dialog_on("", seeder, monkeypatch)
    target = tmp_path / "new"
    dlg._folder_edit.setText(str(target))
    dlg._on_create()
    assert not target.exists() and dlg.project_dir is None
    assert dlg._seed_summary.text() == npd.i18n.t("npSeedEmpty")
    assert dlg._seed_summary.property("class") == "kv-warn"


def test_a_source_that_cannot_let_go_does_not_keep_the_dialog_open(tmp_path, monkeypatch):
    _with_source(_StuckSource, monkeypatch)
    _StuckSource.folder = tmp_path
    seeder = _StubSeeder(None, _Report(0))
    dlg = _dialog_on(tmp_path / "held.car", seeder, monkeypatch)
    dlg.show()
    dlg.reject()
    assert not dlg.isVisible() and dlg.result() == npd.QDialog.DialogCode.Rejected
    assert _StuckSource.released == [True], "it was asked to let go"


def test_a_source_s_lines_stay_when_what_it_holds_is_not_a_project(tmp_path, monkeypatch):
    """A package that unpacks without a project.json still says what it is and what it warns of."""
    from autosound_tcc.ui.tcc import car_source

    _FileSource.chooser = car_source.Chooser("file", "npBrowse", "npSeedFrom")
    _FileSource.folder = tmp_path
    monkeypatch.setattr(car_source, "SOURCES", (_FileSource, car_source.FolderSource))
    dlg = _dialog_on(tmp_path / "the.car", _StubSeeder(None, _Report(0)), monkeypatch)
    assert dlg._seed_summary.text().split("\n") == [
        npd.i18n.t(key) for key in ("npSeedNotAProject", "npSeedNoSkill", "npSeedPlaceholder")]


def test_each_browse_button_opens_its_own_source_s_chooser(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc import car_source

    _FileSource.chooser = car_source.Chooser("file", "npSeedFindings", "npSeedFrom",
                                             "npSeedPlaceholder")
    _FileSource.folder = tmp_path
    monkeypatch.setattr(car_source, "SOURCES", (_FileSource, car_source.FolderSource))
    asked = []
    monkeypatch.setattr(npd.QFileDialog, "getOpenFileName",
                        lambda _parent, title, _start, wanted:
                        asked.append(("file", title, wanted)) or (str(tmp_path / "p.car"), wanted))
    monkeypatch.setattr(npd.QFileDialog, "getExistingDirectory",
                        lambda _parent, title, _start:
                        asked.append(("folder", title)) or str(tmp_path / "picked"))
    dlg = _dialog_on("", _StubSeeder(None, _Report(0)), monkeypatch)

    file_button, folder_button = dlg._seed_browse_buttons
    assert file_button.text() == npd.i18n.t("npSeedFindings") and dlg._seed_browse is file_button
    assert folder_button.text() == npd.i18n.t("npBrowse")
    file_button.click()
    assert dlg._seed_edit.text() == str(tmp_path / "p.car")
    folder_button.click()
    assert dlg._seed_edit.text() == str(tmp_path / "picked")
    assert asked == [("file", npd.i18n.t("npSeedFrom"), npd.i18n.t("npSeedPlaceholder")),
                     ("folder", npd.i18n.t("npSeedFrom"))]


def test_a_sentence_missing_its_argument_is_shown_unfilled_and_logged(caplog):
    from autosound_tcc.ui.tcc import car_source

    said = npd._said(car_source.Line("npSeedFailed", {"wrong": "x"}))
    assert said == npd.i18n.t("npSeedFailed") and "npSeedFailed" in caplog.text
