"""Importing an outside plan: what the window must show, and what it must never smooth over.

The conversion and every "your DSP cannot enter this" verdict belong to the method
(`rew_tool/resonalyze_vc.py`) and are tested there. What is tested HERE is the rendering and the
refusal — the four things a person reading the session file by hand would get wrong, and which
the window would get wrong too if it were written from the file rather than from the converter's
answer:

* an LR48 edge is shown as refused, at its own value, never rounded to the LR36 the DSP has;
* a dormant edge is shown as not live, so nobody reads the sub's `BW 10 Hz / 24` as a subsonic
  filter that was set;
* a transparent EQ band is shown as dropped rather than as a band;
* a leg nothing matched is offered a binding rather than guessed at.

Against the skill's own fixture, deliberately — `rew_tool/testdata/virtual-dsp-session-v7.json`
is generated from the builder its selftest runs on and fails loudly there if the two drift, so a
second copy here would be the thing that goes quietly stale.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import config, vendor_loader  # noqa: E402
from autosound_tcc.ui.tcc import resonalyze_import_dialog as rid  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def session() -> Path:
    path = vendor_loader.rew_tool_dir() / "testdata" / "virtual-dsp-session-v7.json"
    if not path.is_file():
        pytest.skip(f"the skill's fixture is not in this checkout: {path}")
    return path


def _project(root: Path, codes=("sw", "w-L", "w-R")) -> Path:
    """A project with a profile to check against and channels to bind to."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.json").write_text(json.dumps({
        "schema_version": 3, "project_rev": 1,
        "car": {"make": "VW", "model": "Passat B8"},
        "dsp": {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"},
        "channels": [{"code": code, "tier": "channels"} for code in codes],
    }), encoding="utf-8")
    shutil.copy2(
        Path(config.bundled_profiles_dir()) / "helix-dsp-ultra-s.json", root / "dsp_profile.json"
    )
    return root


def _open(project: Path, session: Path) -> rid.ResonalyzeImportDialog:
    _app()
    dialog = rid.ResonalyzeImportDialog(project)
    dialog._file_edit.setText(str(session))
    dialog.reconvert()
    return dialog


def test_the_refusal_keeps_the_value_that_was_asked_for(tmp_path, session):
    """LR48 against a DSP that offers 12/24/36. The window says so and shows 48 -- rounding it to
    36 would be a tune that looks imported and is not the one that was sent."""
    dialog = _open(_project(tmp_path / "proj"), session)

    assert dialog.result is not None
    assert dialog.result["summary"]["blocked"] is True
    refusals = [c for leg in dialog.result["legs"] for c in leg["checks"]
                if c["enterable"] is False]
    assert refusals, "the fixture exists to carry a refusal"
    assert any("48" in c["wanted"] for c in refusals)

    html = rid.render_html(dialog.result)
    assert "LR48" in html
    # And the row still carries what was asked for, so nothing downstream sees a substitution.
    slopes = [leg["row"].get("lp", {}).get("slope") for leg in dialog.result["legs"]
              if isinstance(leg["row"].get("lp"), dict)]
    assert 48 in slopes


def test_one_bad_edge_does_not_condemn_the_other_side_of_the_pair(tmp_path, session):
    """The fixture's pair 1 is LR48 on the left and LR24 on the right for exactly this reason."""
    dialog = _open(_project(tmp_path / "proj"), session)

    refused = {leg["channel"] or leg["channel_hint"] for leg in dialog.result["legs"]
               if any(c["enterable"] is False for c in leg["checks"])}
    clean = {leg["channel"] or leg["channel_hint"] for leg in dialog.result["legs"]
             if leg["checks"] and not any(c["enterable"] is False for c in leg["checks"])}
    assert refused and clean and not (refused & clean)


def test_a_dormant_edge_is_shown_and_never_entered(tmp_path, session):
    """`crossoverKind` decides which edge applies; the other one still holds values. The sub's
    `BW 10 Hz / 24` is in the file and was never set -- and 10 Hz is under the Helix floor, so
    reading it as live would also invent a refusal."""
    dialog = _open(_project(tmp_path / "proj"), session)

    dormant = [leg for leg in dialog.result["legs"] if leg.get("dormant")]
    assert dormant, "the fixture carries the sub's withheld high-pass"
    for leg in dormant:
        for field in leg["dormant"]:
            assert leg["row"].get(field) is None
            assert not any(c["field"] == field for c in leg["checks"])
    assert "NOT live" in rid.render_html(dialog.result)


def test_a_transparent_band_is_dropped_not_entered(tmp_path, session):
    dialog = _open(_project(tmp_path / "proj"), session)

    dropped = [band for leg in dialog.result["legs"] for band in leg.get("dropped_eq_bands") or []]
    assert dropped and all(band["gain_db"] == 0 for band in dropped)
    assert "dropped" in rid.render_html(dialog.result)


def test_an_unbound_leg_is_offered_a_binding_rather_than_guessed(tmp_path, session):
    """`bind_channels` resolves the common case on its own; this dialog is built for the miss."""
    dialog = _open(_project(tmp_path / "proj"), session)

    assert dialog.result["summary"]["unbound"] >= 1
    assert dialog._bind_box.isVisible() or dialog._binders
    assert "nosuch" in dialog._binders, sorted(dialog._binders)

    combo = dialog._binders["nosuch"]
    assert combo.itemData(0) is None  # "leave unbound" leads, so nothing binds by accident
    combo.setCurrentIndex(combo.findData("w-L"))  # re-converts on change

    bound = [leg for leg in dialog.result["legs"] if leg.get("channel_hint") == "nosuch"]
    assert bound and bound[0]["channel"] == "w-L"
    assert bound[0]["channel_bound_by"] == "mapping"


def test_answering_a_binding_does_not_take_the_combos_apart(tmp_path, session):
    """The re-check runs from inside a combo's own signal handler, and rebuilding the row list
    there would delete the widget that is mid-emit -- the SIGSEGV shape this app has paid for
    twice. So the rows stay put, and a second change still works."""
    dialog = _open(_project(tmp_path / "proj"), session)
    combo = dialog._binders["nosuch"]

    combo.setCurrentIndex(combo.findData("w-L"))
    assert dialog._binders["nosuch"] is combo, "the same widget, not a rebuilt one"

    combo.setCurrentIndex(combo.findData("sw"))
    bound = [leg for leg in dialog.result["legs"] if leg.get("channel_hint") == "nosuch"]
    assert bound and bound[0]["channel"] == "sw"

    combo.setCurrentIndex(0)  # and back to unbound
    assert dialog.result["summary"]["unbound"] >= 1


def test_the_unchecked_limits_are_rolled_up_once(tmp_path, session):
    """53 identical shrugs on the user's real file buried the one finding that mattered. The
    roll-up says it once, in its own colour, and never as a pass."""
    dialog = _open(_project(tmp_path / "proj"), session)

    html = rid.render_html(dialog.result)
    if dialog.result["profile_gaps"]:
        assert html.count("Not checked") == 1
    unknowns = [c for leg in dialog.result["legs"] for c in leg["checks"]
                if c["enterable"] is None]
    for check in unknowns:
        assert f'✗ {check["field"]}' not in html or check["enterable"] is False


def test_a_project_with_no_profile_verifies_nothing_and_says_so(tmp_path, session):
    """Not a silent pass: a value nobody could check has not been checked."""
    project = _project(tmp_path / "proj")
    (project / "dsp_profile.json").unlink()

    dialog = _open(project, session)

    assert all(c["enterable"] is None for leg in dialog.result["legs"] for c in leg["checks"])
    assert "nothing was checked" in rid.render_html(dialog.result)


def test_a_file_that_is_not_a_session_is_a_sentence(tmp_path, session):
    """A dialog that raises into the event loop is a crash; this one reports and stays open."""
    junk = tmp_path / "junk.json"
    junk.write_text("{}", encoding="utf-8")

    dialog = _open(_project(tmp_path / "proj"), junk)

    assert dialog.result is None
    assert not dialog._copy_btn.isEnabled()
    assert dialog._verdict.text()


def test_the_rows_can_be_taken_to_the_gate_but_not_written_from_here(tmp_path, session):
    """Banking is `state/apply.py`'s job. The window's most it does is hand over the rows."""
    dialog = _open(_project(tmp_path / "proj"), session)

    assert not dialog._copy_btn.isEnabled(), "the fixture is blocked, so there is nothing to take"
    assert not hasattr(dialog, "_write_btn")
    for leg in dialog.result["legs"]:
        assert leg["row"]["status"] == "proposed"
