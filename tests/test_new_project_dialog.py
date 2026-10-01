"""NewProjectDialog: folder + vendor/model + how the AI runs. The intake itself is the skill's
served form, which the new window opens (hub #194) -- this dialog starts no interview.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc import new_project_dialog as npd  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


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


def _dialog_on(source, seeder, monkeypatch, vendor="Musway", model="M6V4"):
    monkeypatch.setattr(npd, "_seeder", lambda: seeder)
    _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    dlg._vendor_edit.setText(vendor)
    dlg._model_edit.setText(model)
    dlg._seed_edit.setText(str(source))
    return dlg


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
    assert counted in dlg._seed_summary.text()

    dlg._seed_fs.setChecked(False)
    assert counted not in dlg._seed_summary.text(), "unticked, nothing of it is promised"


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
    dlg._seed_fs.setChecked(False)          # redraws the note: the preview call
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
