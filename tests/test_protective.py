"""Taking a protective filter back out of a measured curve — TCC's half of it.

The maths is the method's (`rew_tool/protective.py`) and is tested there. What is tested here is
the seam: whether this installation can run the correction at all, the conversion between what REW
gives (dB and degrees) and what the maths takes (a complex response), and the one distinction the
whole feature turns on — a channel nobody recorded is not a channel recorded as clean.
"""

from __future__ import annotations

import numpy as np
import pytest

from autosound_tcc.core import protective


def test_this_installation_can_say_why_it_cannot_correct(monkeypatch):
    """A toggle that raises is worse than one that is not offered, and the two ways it cannot run
    need different sentences: an old pin has no module, and a light install has no scipy."""
    assert protective.reason() == "", "the dev environment has both halves"
    assert protective.available() is True

    monkeypatch.setattr(protective, "_module", lambda: (_ for _ in ()).throw(
        protective.ProtectiveUnavailable("no such module")))
    said = protective.reason()
    assert "not in this checkout" in said and not protective.available()


def test_a_protective_high_pass_comes_back_out():
    """The method's own numbers, through this module's dB/degree conversion: an LR4 at 100 Hz
    leaves about 52 degrees at 320 Hz, and taking it out returns them."""
    legs = {"hp": {"f": 100, "type": "LR", "slope": 24}, "lp": "OFF"}
    freqs = np.array([50.0, 100.0, 320.0, 1000.0])
    flat_db, flat_deg = np.zeros(4), np.zeros(4)

    corrected = protective.de_embed(freqs, flat_db, flat_deg, legs)

    assert corrected.applied == ("hp",)
    assert corrected.changed
    # Below the corner the filter cut; undoing it lifts. At the corner an LR4 is -6 dB.
    assert corrected.magnitude_db[0] > 20
    assert corrected.magnitude_db[1] == pytest.approx(6.0, abs=0.1)
    assert corrected.magnitude_db[3] == pytest.approx(0.0, abs=0.1)
    # And the phase the filter was carrying: ~52 degrees three-ish times above the corner.
    assert corrected.phase_deg[2] == pytest.approx(-52, abs=2)


def test_a_record_that_says_nothing_was_in_the_chain_changes_nothing():
    """`"OFF"` is an answer. The curve comes back as it was, and `changed` says so — which is not
    the same as the correction having failed."""
    legs = {"hp": "OFF", "lp": "OFF"}
    freqs = np.array([50.0, 200.0, 1000.0])
    mag, phase = np.array([1.0, 2.0, 3.0]), np.array([10.0, 20.0, 30.0])

    corrected = protective.de_embed(freqs, mag, phase, legs)

    assert not corrected.changed and corrected.applied == ()
    assert corrected.magnitude_db == pytest.approx(mag, abs=1e-6)
    assert corrected.phase_deg == pytest.approx(phase, abs=1e-6)
    assert corrected.note, "and it says why nothing happened"


def test_nobody_said_is_refused_rather_than_treated_as_clean():
    """The failure this whole design exists to prevent: a correction over an unknown chain
    produces data that LOOKS corrected. The method raises; this module lets that through rather
    than turning it into an empty result."""
    freqs = np.array([100.0, 1000.0])

    with pytest.raises(Exception) as caught:
        protective.de_embed(freqs, np.zeros(2), np.zeros(2), None)

    assert "LOOKS corrected" in str(caught.value)
    assert not isinstance(caught.value, protective.ProtectiveUnavailable), (
        "a missing RECORD is not a missing INSTALL — the caller has to tell them apart"
    )


def test_legs_of_keeps_the_two_answers_apart():
    record = {"series": "3", "channels": {"m-L": {"hp": {"f": 100, "type": "LR", "slope": 24}},
                                          "w-L": "OFF"}}

    assert protective.legs_of(record, "m-L")["hp"]["f"] == 100
    assert protective.legs_of(record, "m-L")["lp"] == "OFF", "an unstated leg in a stated channel"
    assert protective.legs_of(record, "w-L") == {"hp": "OFF", "lp": "OFF"}
    assert protective.legs_of(record, "tw-L") is None, "nobody said, and that is not OFF"
    assert protective.legs_of(None, "m-L") is None


def test_the_capped_region_is_reported_because_the_phase_there_is_not_the_driver_s():
    """Below a protective corner the filter's response goes to zero and dividing by it lifts the
    noise floor with the signal. The method caps at 40 dB; a plot has to mark where, or it draws
    invented phase as if it were measured."""
    legs = {"hp": {"f": 100, "type": "LR", "slope": 48}, "lp": "OFF"}
    freqs = np.array([5.0, 10.0, 20.0, 100.0, 1000.0])

    corrected = protective.de_embed(freqs, np.zeros(5), np.zeros(5), legs)

    assert corrected.capped_bins > 0
    assert corrected.capped_below_hz is not None
    assert corrected.magnitude_db[0] <= 40.0 + 1e-6, "the cap is what stops it inventing signal"


def test_the_round_decides_whether_the_plot_opens_corrected():
    """Readable, not inferred. A round carries the phase it belongs to and the ledger version it
    was taken against, so "is this a driver read or a verification" is a fact rather than a guess
    at a measurement title."""
    assert protective.default_corrected({"phase": "0"}) is True
    assert protective.default_corrected({"phase": "1"}) is True
    assert protective.default_corrected({"phase": "-1"}) is True, "intake reads are reads too"
    assert protective.default_corrected({"phase": "3"}) is False, (
        "verifying a tune that is supposed to have those filters in it"
    )
    # Nobody said. Not a default in either direction -- the caller asks.
    assert protective.default_corrected({"phase": ""}) is None
    assert protective.default_corrected(None) is None
    assert protective.default_corrected({}) is None


def test_no_round_reads_as_no_answer_rather_than_as_a_clean_chain(tmp_path):
    """`protective_record()` is None with no round open, and the method's docstring is explicit
    that a caller must not read that as "there was no protection". A project with no process at
    all lands in the same place."""
    assert protective.record_for(tmp_path) is None
    assert protective.default_corrected(protective.record_for(tmp_path)) is None


def _round(tmp_path):
    """A project with an open capture round, the way the dialog expects to find one."""
    from autosound_tcc.core import vendor_loader

    (tmp_path / "project.json").write_text('{"schema_version": 3, "project_rev": 1}',
                                           encoding="utf-8")
    proc = vendor_loader.load_process().Process(str(tmp_path / "process"))
    proc.start_capture("v_001", ["m-L_0 (sw)"])
    return tmp_path


def _described(tmp_path, channels):
    """A project that names channels and has NO ledger — phase 0, the first sweeps."""
    from autosound_tcc.core import vendor_loader

    project = vendor_loader.load_project()
    vendor_loader.load_project()
    proj = project.Project(str(tmp_path))
    proj.save({
        "schema_version": project.SCHEMA_VERSION,
        "channels": channels,
        "glossary": {"schema_version": 1,
                     "channels": [{"code": c["code"], "active": True} for c in channels]},
    })
    return tmp_path


def test_the_channels_come_from_the_project_before_any_ledger_exists(tmp_path):
    """F-041, reported as "нажимаю «Захист» ... і нічого не відбувається" (Windows, 2026-09-01).

    The list came from the loaded ledger view alone, and this button exists for the state BEFORE
    a ledger: raw sweeps, phase 0. `main_window` only draws a rig without a snapshot when
    `project.json` gives a channel a `tier`, which today it does for spare slots alone — so
    `_view` is None, the list was empty, and `open_for` returned None. What the presser saw was
    nothing at all, because the refusal went to the status strip at the top of the window while
    the button is at the bottom of the right column.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.protective_dialog import channel_codes, open_for

    project = _described(tmp_path, [{"code": "m-L"}, {"code": "m-R"}, {"code": "tw-L"}])

    assert channel_codes(None, project) == ["m-L", "m-R", "tw-L"]
    QApplication.instance() or QApplication([])
    assert open_for(project, None) is not None, "the dialog opens on raw measurements"


def test_a_slot_with_no_driver_is_not_offered(tmp_path):
    """`hidden` is a slot nobody assigned a driver to (SCR-003): there was no chain, so there is
    nothing to say about what was in it."""
    from autosound_tcc.ui.tcc.protective_dialog import channel_codes

    project = _described(tmp_path, [{"code": "m-L"}, {"code": "spare-1", "hidden": True}])

    assert channel_codes(None, project) == ["m-L"]


def test_the_view_leads_and_the_project_fills_in_what_it_left_out(tmp_path):
    """The view carries the order the panels show and knows which channels are switched off, so
    it stays first. It is not, however, complete: a channel `project.json` names and no ledger row
    has met yet was silently missing from a dialog that asks about the MEASURING RIG."""
    from autosound_tcc.ui.tcc.protective_dialog import channel_codes

    class _Row:
        def __init__(self, name):
            self.name = name

    class _Group:
        def __init__(self, names):
            self._names = names

        def rows_visible(self):
            return [_Row(name) for name in self._names]

    class _View:
        groups = (_Group(["w-L", "w-R"]),)

    project = _described(tmp_path, [{"code": "m-L"}, {"code": "w-L"}])

    assert channel_codes(_View(), project) == ["w-L", "w-R", "m-L"]


def test_the_dialog_opens_on_what_the_round_already_says(tmp_path):
    """Re-opening it is a review, not a blank form — and the three answers stay three."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.core import process_writer
    from autosound_tcc.ui.tcc.protective_dialog import STATE_FILTER, STATE_OFF, STATE_UNSET
    from autosound_tcc.ui.tcc.protective_dialog import ProtectiveDialog

    project = _round(tmp_path)
    process_writer.set_protective(project, "m-L", {"hp": {"f": 100, "type": "LR", "slope": 24}})
    process_writer.set_protective(project, "w-L", "OFF")

    QApplication.instance() or QApplication([])
    dialog = ProtectiveDialog(project, ["m-L", "w-L", "tw-L"])

    by_code = {row.code: row for row in dialog._rows}
    assert by_code["m-L"].state.currentData() == STATE_FILTER
    assert by_code["m-L"].answer() == {"hp": {"f": 100.0, "type": "LR", "slope": 24}}
    assert by_code["w-L"].state.currentData() == STATE_OFF
    assert by_code["w-L"].answer() == "OFF"
    # Nobody said, and closing the dialog must not turn that into OFF.
    assert by_code["tw-L"].state.currentData() == STATE_UNSET
    assert by_code["tw-L"].answer() is None


def test_the_gate_refuses_a_half_given_leg_and_the_dialog_shows_its_words(tmp_path):
    """The dialog collects and does not validate: a leg with a frequency and no type goes to the
    writer as typed, and the refusal is what the person reads. A UI that quietly fixes what a gate
    would have refused trains people to trust the UI over the gate."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.protective_dialog import STATE_FILTER, ProtectiveDialog

    project = _round(tmp_path)
    QApplication.instance() or QApplication([])
    dialog = ProtectiveDialog(project, ["m-L"])
    row = dialog._rows[0]
    row.state.setCurrentIndex(row.state.findData(STATE_FILTER))
    row.hp_f.setText("100")  # no type, no slope

    dialog._on_save()

    assert dialog.result() != dialog.DialogCode.Accepted
    assert dialog._problem.isVisibleTo(dialog)
    said = dialog._problem.text()
    assert "m-L" in said and "f type slope" in said, said
    assert "Traceback" not in said, "the gate's sentence, not the CLI's wrapper"


def test_one_press_makes_the_leg_the_filter_it_almost_always_is(tmp_path):
    """User, 2026-09-02: "додати маленьку кнопочку по нажаттю якої фільтр стає LR24". Two dropdowns
    are the honest surface — a protective filter can be whatever was in the chain — but nearly
    every one of them is an LR24, and choosing it twice per channel is a toll on the common path.

    It also removes a real trap: the skill's writer refuses a leg with a frequency and no type or
    slope, so "type 80 and press Record" was a refusal."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.protective_dialog import STATE_FILTER, STATE_UNSET, ProtectiveDialog

    project = _round(tmp_path)
    QApplication.instance() or QApplication([])
    dialog = ProtectiveDialog(project, ["m-L"])
    row = dialog._rows[0]
    assert row.state.currentData() == STATE_UNSET

    row.hp_quick.click()

    assert row.state.currentData() == STATE_FILTER, "a press is the statement that there was one"
    assert (row.hp_type.currentData(), row.hp_slope.currentData()) == ("LR", 24)
    row.hp_f.setText("80")
    assert row.answer() == {"hp": {"f": 80.0, "type": "LR", "slope": 24}}


def test_the_quick_button_works_before_the_row_has_been_switched_on(tmp_path):
    """A button that only works once you have already said "filters" is a button for a thing you
    no longer need."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.protective_dialog import ProtectiveDialog

    project = _round(tmp_path)
    QApplication.instance() or QApplication([])
    dialog = ProtectiveDialog(project, ["m-L"])
    row = dialog._rows[0]

    assert row.hp_quick.isEnabled() and row.lp_quick.isEnabled()
    assert not row.hp_f.isEnabled(), "the fields themselves are still off until it is pressed"


def test_the_method_decides_whether_to_de_embed_and_its_default_is_no(tmp_path):
    """Corrected 2026-09-02. TCC used to read "no record" as an unanswered question and refuse.
    That was our reading: the record is an INSTRUCTION to the analysis, not a description of the
    chain — there is nearly always something in the chain, the DSP's own working crossovers, and
    they belong there. The method's own default says so."""
    from autosound_tcc.core import protective as core

    assert core.should_de_embed(None, "m-L")[0] == "no"
    assert core.should_de_embed({"channels": {}}, "m-L")[0] == "no"


def test_a_baseline_capture_with_no_record_is_the_one_case_worth_asking_about(tmp_path):
    """Filters in force during a baseline sweep — taken before any crossover was designed — are
    protection almost by definition, and that is the single place a forgotten flag is recoverable."""
    from autosound_tcc.core import protective as core

    action, detail = core.should_de_embed({"channels": {}}, "m-L", baseline=True)

    assert action == "check"
    assert "m-L" in detail


def test_the_button_opens_on_the_round_being_reviewed_not_on_the_whole_rig(tmp_path):
    """Now that a protective filter is ENTERED in the import table, this dialog is where one is
    reviewed and corrected — and the record belongs to a round. Offering the whole rig here would
    put rows in front of the tuner for channels this pass never touched."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.core import vendor_loader
    from autosound_tcc.ui.tcc.protective_dialog import open_for, round_channel_codes

    project = _described(tmp_path, [{"code": "m-L"}, {"code": "m-R"}, {"code": "tw-L"}])
    proc = vendor_loader.load_process().Process(str(project / "process"))
    proc.start_capture("v_001", ["m-L_01 (sw)", "m-R_01 (sw)"])

    assert round_channel_codes(project) == ["m-L", "m-R"]

    QApplication.instance() or QApplication([])
    dialog = open_for(project, None)
    assert [row.code for row in dialog._rows] == ["m-L", "m-R"], "tw-L was not in this pass"


def test_with_no_round_open_it_still_shows_the_rig_to_read(tmp_path):
    """A project with no round open is exactly where somebody goes to READ what a past pass
    recorded. Answering a press with nothing there is the F-041 symptom again."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.protective_dialog import open_for, round_channel_codes

    project = _described(tmp_path, [{"code": "m-L"}, {"code": "m-R"}])

    assert round_channel_codes(project) == []
    QApplication.instance() or QApplication([])
    assert [row.code for row in open_for(project, None)._rows] == ["m-L", "m-R"]
