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
    """A project with an open capture round, the way the dialog expects to find one.

    Opened at its SERIES number, not at `v_001`. These fixtures have no ledger — they are the
    phase-0 baseline — and since method `v3.0.59` a `v_NNN` round whose snapshot is not on disk is
    refused (TCC-022, which TCC asked for). The refusal names this very way out. The fixtures were
    saying "taken under configuration v_001" about measurements taken before anything was banked,
    which is the thing that gate exists to stop.
    """
    from autosound_tcc.core import vendor_loader

    (tmp_path / "project.json").write_text('{"schema_version": 3, "project_rev": 1}',
                                           encoding="utf-8")
    proc = vendor_loader.load_process().Process(str(tmp_path / "process"))
    # Both channels the dialog is opened on, because since `v3.0.59` a protective record for a
    # channel the round never captured is refused (S-036, the Arbiter's rears). A fixture that
    # writes `w-L` into a pass that only took `m-L` was describing a pass that did not happen.
    proc.start_capture("0", ["m-L_0 (sw)", "w-L_0 (sw)"])
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
        id = "physical_outputs"

        def __init__(self, names):
            self._names = names

        def rows_visible(self):
            return [_Row(name) for name in self._names]

    class _View:
        groups = (_Group(["w-L", "w-R"]),)

    project = _described(tmp_path, [{"code": "m-L"}, {"code": "w-L"}])

    assert channel_codes(_View(), project) == ["w-L", "w-R", "m-L"]


def test_the_dialog_opens_on_what_the_round_already_says(tmp_path):
    """Re-opening it is a review, not a blank form.

    Two answers now, not three (user, 2026-09-06): a row with filters, and an empty row — which
    says there was no PROTECTIVE filter, i.e. read the curve as measured. `None` (nothing recorded
    yet) and `"OFF"` (recorded as none) are the same instruction downstream, so they render alike.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.core import process_writer
    from autosound_tcc.ui.tcc.protective_dialog import ProtectiveDialog

    project = _round(tmp_path)
    process_writer.set_protective(project, "m-L", {"hp": {"f": 100, "type": "LR", "slope": 24}})
    process_writer.set_protective(project, "w-L", "OFF")

    QApplication.instance() or QApplication([])
    dialog = ProtectiveDialog(project, ["m-L", "w-L", "tw-L"])

    by_code = {row.code: row for row in dialog._rows}
    assert by_code["m-L"].hp_f.text() == "100"
    assert by_code["m-L"].answer() == {"hp": {"f": 100.0, "type": "LR", "slope": 24}}
    assert by_code["w-L"].hp_f.text() == ""
    assert by_code["w-L"].answer() == "OFF"
    # Never asked about, and never asked ABOUT either: an empty row is an answer now.
    assert by_code["tw-L"].hp_f.text() == ""
    assert by_code["tw-L"].answer() == "OFF"


def test_every_channel_of_the_pass_is_written_including_the_empty_ones(tmp_path):
    """"Якщо не має захисного фільтру — то це признак БЕЗ ЗАХИСНОГО ФІЛЬТРУ, і це означає, що не
    треба його знімати математикою при аналізі" (user, 2026-09-06). So Record writes every row."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.core import protective as core
    from autosound_tcc.ui.tcc.protective_dialog import ProtectiveDialog

    project = _round(tmp_path)
    QApplication.instance() or QApplication([])
    dialog = ProtectiveDialog(project, ["m-L", "w-L"])
    dialog._rows[0].hp_quick.click()
    dialog._rows[0].hp_f.setText("100")

    dialog._on_save()

    assert dialog.written == ["m-L", "w-L"]
    record = core.record_for(project)
    assert core.legs_of(record, "m-L")["hp"] == {"f": 100.0, "type": "LR", "slope": 24}
    assert core.legs_of(record, "w-L") == {"hp": "OFF", "lp": "OFF"}


def test_the_gate_refuses_a_half_given_leg_and_the_dialog_shows_its_words(tmp_path):
    """The dialog collects and does not validate: a leg with a frequency and no type goes to the
    writer as typed, and the refusal is what the person reads. A UI that quietly fixes what a gate
    would have refused trains people to trust the UI over the gate."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.protective_dialog import ProtectiveDialog

    project = _round(tmp_path)
    QApplication.instance() or QApplication([])
    dialog = ProtectiveDialog(project, ["m-L"])
    row = dialog._rows[0]
    row.hp_f.setText("100")  # no type, no slope

    dialog._on_save()

    assert dialog.result() != dialog.DialogCode.Accepted
    assert dialog._problem.isVisibleTo(dialog)
    said = dialog._problem.text()
    assert "m-L" in said and "f type slope" in said, said
    assert "Traceback" not in said, "the gate's sentence, not the CLI's wrapper"


def test_protection_the_round_does_not_hold_after_record_is_said_next_to_the_button(
    tmp_path, monkeypatch
):
    """TODO F-049. A channel with no record on a baseline round now means, to the method, that the
    record did not come from this window -- or that the window failed to write what it thought it
    wrote. The second is TCC's defect and must not be silent: the writer returning is not the round
    holding it. Said where a refusal is said, and the dialog does not close as if it went through."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.core import process_writer
    from autosound_tcc.ui.tcc import i18n
    from autosound_tcc.ui.tcc.protective_dialog import ProtectiveDialog

    project = _round(tmp_path)
    real = process_writer.set_protective
    # `m-L` reports success and writes nothing: the defect being caught.
    monkeypatch.setattr(process_writer, "set_protective",
                        lambda d, c, legs: real(d, c, legs) if c == "w-L" else "")
    QApplication.instance() or QApplication([])
    dialog = ProtectiveDialog(project, ["m-L", "w-L"])

    dialog._on_save()

    assert dialog.result() != dialog.DialogCode.Accepted, "not closed as if it went through"
    assert dialog._problem.isVisibleTo(dialog)
    assert dialog._problem.text() == i18n.t("protNotInRecord").format(channels="m-L")
    assert dialog.written == ["w-L"], "what the round holds, and only that"


def test_one_press_makes_the_leg_the_filter_it_almost_always_is(tmp_path):
    """User, 2026-09-02: "додати маленьку кнопочку по нажаттю якої фільтр стає LR24". Two dropdowns
    are the honest surface — a protective filter can be whatever was in the chain — but nearly
    every one of them is an LR24, and choosing it twice per channel is a toll on the common path.

    It also removes a real trap: the skill's writer refuses a leg with a frequency and no type or
    slope, so "type 80 and press Record" was a refusal."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.protective_dialog import ProtectiveDialog

    project = _round(tmp_path)
    QApplication.instance() or QApplication([])
    dialog = ProtectiveDialog(project, ["m-L"])
    row = dialog._rows[0]
    assert row.answer() == "OFF", "an untouched row says there was no protective filter"

    row.hp_quick.click()

    assert (row.hp_type.currentData(), row.hp_slope.currentData()) == ("LR", 24)
    row.hp_f.setText("80")
    assert row.answer() == {"hp": {"f": 80.0, "type": "LR", "slope": 24}}


def test_every_widget_in_a_row_is_live_from_the_start(tmp_path):
    """There is nothing to switch on any more: the row is the answer, and the fields are how it is
    given. A field disabled until a dropdown said "filters" was the last trace of the flag."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.protective_dialog import ProtectiveDialog

    project = _round(tmp_path)
    QApplication.instance() or QApplication([])
    dialog = ProtectiveDialog(project, ["m-L"])
    row = dialog._rows[0]

    assert row.hp_quick.isEnabled() and row.lp_quick.isEnabled()
    assert row.hp_f.isEnabled() and row.lp_f.isEnabled()


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
    proc.start_capture("01", ["m-L_01 (sw)", "m-R_01 (sw)"])  # a baseline: series, not a ledger

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


def test_with_no_round_open_only_output_channels_are_offered(tmp_path):
    """TEST-FINDINGS 22: the dialog listed VFL…VSW before the outputs. A protective filter sits in
    an OUTPUT's signal path, the driver being measured; a virtual channel is not measured through
    one."""
    from autosound_tcc.ui.tcc.protective_dialog import channel_codes

    class _Row:
        def __init__(self, name):
            self.name = name

    class _Group:
        def __init__(self, group_id, names):
            self.id = group_id
            self._names = names

        def rows_visible(self):
            return [_Row(name) for name in self._names]

    class _View:
        groups = (_Group("virtual_channels", ["VFL", "VFR"]),
                  _Group("physical_outputs", ["w-L", "w-R"]))

    project = _described(tmp_path, [{"code": "w-L"}, {"code": "VC", "tier": "virtual_channels"},
                                    {"code": "tw-L", "tier": "channels"}])

    assert channel_codes(_View(), project) == ["w-L", "w-R", "tw-L"]


def test_the_row_form_has_the_protection_form_s_own_fields():
    """F-056, the Arbiter 2026-09-16: the import row's filters "done the way the form that sets
    filters does it". One set of fields, two places."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.protective_dialog import TYPES, ProtectiveLegsDialog

    QApplication.instance() or QApplication([])
    form = ProtectiveLegsDialog({"hp": {"f": 80.0, "type": "BW", "slope": 12}})

    freq, kind, slope, _quick = form.hp
    assert (freq.text(), kind.currentData(), slope.currentData()) == ("80", "BW", 12)
    assert [kind.itemData(i) for i in range(1, kind.count())] == list(TYPES)
    assert form.legs() == {"hp": {"f": 80.0, "type": "BW", "slope": 12}}

    form._clear()
    assert form.legs() is None, "cleared is 'read the curve as measured'"



def test_who_answered_is_recorded_with_the_protective_record(tmp_path):
    """Method `v3.0.59` (SKL-046, S-036): a protective record carries WHO answered —
    `user | front_end | default`. Ten channels marked `OFF` in one second is not a person
    answering ten times, and the method reads a front-end's blanket `OFF` as `check` rather than
    as a settled answer.

    The CLI's own default is `user`, so a caller that says nothing signs every bulk write as a
    person. TCC has both kinds in one flow and they must not be signed alike:

    * the protective dialog is a person typing legs per channel → `user`;
    * the import filling an empty cell with `OFF` because the channel came in is the FRONT END
      answering for a channel it captured → `front_end`.
    """
    from autosound_tcc.core import process_writer, vendor_loader

    (tmp_path / "project.json").write_text('{"schema_version": 3, "project_rev": 1}',
                                           encoding="utf-8")
    proc = vendor_loader.load_process().Process(str(tmp_path / "process"))
    proc.start_capture("0", ["m-L_0 (sw)", "w-L_0 (sw)"])

    process_writer.set_protective(tmp_path, "m-L", "OFF")                      # the default
    process_writer.set_protective(tmp_path, "w-L", "OFF", source="front_end")

    record = proc.load()["capture"]["protective_source"]
    assert record["m-L"] == "user", "a caller that says nothing is still a person"
    assert record["w-L"] == "front_end", "and the front end can say it was the front end"


def test_a_closed_round_is_corrected_with_a_reason_rather_than_written_into(tmp_path, monkeypatch):
    """The window half of skill `#48`. `set_protective` needs an OPEN round, and the round that
    needs correcting is the one already read — on a live project, a nine-position series filed as
    `OFF` for all ten channels while the sweeps show the roll-off.

    Opened on a closed round the dialog becomes a CORRECTION: the reason is asked for, because
    the gate requires it and because a correction with no why is indistinguishable from a second
    opinion, and the write goes to `amend_protective` with that round's id.
    """
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.core import process_writer, vendor_loader
    from autosound_tcc.ui.tcc.protective_dialog import ProtectiveDialog

    project = _described(tmp_path, [{"code": "m-L"}])
    proc = vendor_loader.load_process().Process(str(project / "process"))
    proc.start_capture("1", ["m-L_1 (sw)"])
    proc.set_protective("m-L", "OFF")
    cap_id = proc.load()["capture"]["id"]
    proc.close_capture("done")

    QApplication.instance() or QApplication([])
    dialog = ProtectiveDialog(project, ["m-L"], capture_id=cap_id)

    assert dialog._reason is not None, "a correction asks why"
    dialog._rows[0].hp_quick.click()
    dialog._rows[0].hp_f.setText("100")

    dialog._on_save()
    assert not dialog.written, "no reason, no write — the gate's rule, said before the round trip"

    dialog._reason.setText("the sweep shows the roll-off; filed OFF by mistake")
    dialog._on_save()

    assert dialog.written == ["m-L"]
    record = proc.protective_record_for("1")
    assert record["channels"]["m-L"]["hp"]["f"] == 100
    assert process_writer.amend_protective is not None  # the writer this path uses


def test_a_named_round_offers_its_own_channels_not_the_open_rounds(tmp_path):
    """`round_channel_codes` answered for the OPEN round only, which is the wrong round whenever
    the record being corrected belongs to a closed one (skill `#48`). Named, it answers for that
    one — otherwise the correction dialog would offer rows the pass never touched."""
    from autosound_tcc.core import vendor_loader
    from autosound_tcc.ui.tcc.protective_dialog import round_channel_codes

    project = _described(tmp_path, [{"code": "m-L"}, {"code": "m-R"}, {"code": "tw-L"}])
    proc = vendor_loader.load_process().Process(str(project / "process"))
    proc.start_capture("1", ["m-L_1 (sw)", "m-R_1 (sw)"])
    closed = proc.load()["capture"]["id"]
    proc.close_capture("done")
    proc.start_capture("2", ["tw-L_2 (sw)"])

    assert round_channel_codes(project) == ["tw-L"], "the open round, as before"
    assert round_channel_codes(project, closed) == ["m-L", "m-R"], "and the named one by name"


def test_with_a_round_open_only_output_channels_are_offered_too(tmp_path):
    """TEST-FINDINGS 22, the other half: the round's titles named a virtual channel and the dialog
    offered it. Filtered by the same rule — when the project says which channels are outputs."""
    from autosound_tcc.core import vendor_loader
    from autosound_tcc.ui.tcc.protective_dialog import round_channel_codes

    project = _described(tmp_path, [{"code": "m-L"}, {"code": "VFL", "tier": "virtual_channels"}])
    proc = vendor_loader.load_process().Process(str(project / "process"))
    proc.start_capture("01", ["VFL_01 (sw)", "m-L_01 (sw)"])

    assert round_channel_codes(project) == ["m-L"]
