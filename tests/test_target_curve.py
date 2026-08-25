"""Finding the project's target curve, and knowing whether the tool already has it.

The bug this exists for is silent by construction: the header names a curve, the link opens the
method's visualiser, and the visualiser draws whatever it happens to ship. Nothing was wrong on
screen — there was simply a different curve there than the one named a centimetre above it.
"""

from __future__ import annotations

import sys

import pytest

from autosound_tcc.core import target_curve


@pytest.mark.parametrize("stem, expected", [
    ("SQ-Comp-Ref_0db_REW", "SQ-Comp-Ref"),
    ("EPY_0db_REW", "EPY"),
    ("EPY_0dB_rew", "EPY"),
    ("Jazzi_REW", "Jazzi"),
    ("Jazzi", "Jazzi"),
    # Not a suffix in the middle, and not a curve called "" either.
    ("_0db_REW_notes", "_0db_REW_notes"),
])
def test_the_export_detail_is_not_the_curves_identity(stem, expected):
    assert target_curve.curve_name(stem) == expected


def _curve(path, name="EPY"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {name}\n20 0.0\n1000 -3.0\n", encoding="utf-8")
    return path


def test_the_methods_own_layout_is_found_first(tmp_path):
    """One folder per curve under `rew_analitic/target-curves/`, per the method's README."""
    wanted = _curve(tmp_path / "rew_analitic" / "target-curves" / "EPY" / "EPY_0db_REW.txt")
    _curve(tmp_path / "EPY_0db_REW.txt")  # the copy that also exists in real projects
    assert target_curve.find_file(tmp_path, "EPY") == wanted


def test_a_curve_filed_at_the_project_root_is_still_found(tmp_path):
    """Refusing to look there would leave the honest answer — "it is right there" — unsaid."""
    wanted = _curve(tmp_path / "EPY_0db_REW.txt")
    assert target_curve.find_file(tmp_path, "EPY") == wanted


def test_a_lone_file_in_the_curves_own_folder_is_that_curve(tmp_path):
    """The layout is one folder per curve, so the folder settles it even when somebody exported
    the file under a name of their own."""
    wanted = _curve(tmp_path / "rew_analitic" / "target-curves" / "EPY" / "measured-2026.txt")
    assert target_curve.find_file(tmp_path, "EPY") == wanted


def test_two_files_and_no_name_match_is_not_a_guess(tmp_path):
    folder = tmp_path / "rew_analitic" / "target-curves" / "EPY"
    _curve(folder / "one.txt")
    _curve(folder / "two.txt")
    assert target_curve.find_file(tmp_path, "EPY") is None


def test_no_name_finds_nothing(tmp_path):
    _curve(tmp_path / "EPY_0db_REW.txt")
    assert target_curve.find_file(tmp_path, "") is None


def test_the_tool_is_asked_what_it_carries_rather_than_told(tmp_path):
    """A hardcoded {"SQ-Comp-Ref"} would be right until the skill ships a second curve, and then
    wrong silently — the exact failure this module is about."""
    known = target_curve.tool_curves()
    if not known:
        pytest.skip("the vendored skill is not checked out")
    assert "SQ-Comp-Ref" in known
    assert all(not name.lower().endswith("_rew") for name in known), known


def test_a_curve_the_tool_ships_needs_no_handover(tmp_path):
    if not target_curve.tool_curves():
        pytest.skip("the vendored skill is not checked out")
    target = target_curve.describe(tmp_path, "SQ-Comp-Ref")
    assert target.in_tool and not target.needs_dropping


def test_a_projects_own_curve_needs_the_file_handed_over(tmp_path):
    if not target_curve.tool_curves():
        pytest.skip("the vendored skill is not checked out")
    wanted = _curve(tmp_path / "rew_analitic" / "target-curves" / "EPY" / "EPY_0db_REW.txt")
    target = target_curve.describe(tmp_path, "EPY")
    assert not target.in_tool and target.path == wanted and target.needs_dropping


def test_a_named_curve_with_no_file_is_a_state_not_an_error(tmp_path):
    """A target can be chosen before anybody exports it. The window says so instead of pointing
    at a file that is not there."""
    target = target_curve.describe(tmp_path, "Resonalyze")
    assert target.path is None and not target.needs_dropping and target.name == "Resonalyze"


def test_no_target_at_all_says_nothing(tmp_path):
    assert target_curve.describe(tmp_path, None).name == ""


@pytest.mark.skipif(sys.platform != "darwin", reason="the macOS form")
def test_the_reveal_selects_the_file_rather_than_opening_its_folder(tmp_path):
    assert target_curve.reveal_command(tmp_path / "EPY.txt")[:2] == ["open", "-R"]


def test_the_windows_form_has_no_space_after_the_comma(monkeypatch):
    """`explorer /select, C:\\x` opens the user's Documents and reports success. The comma binds
    to the path, so this is asserted here rather than discovered on somebody's Windows machine."""
    monkeypatch.setattr(target_curve.sys, "platform", "win32")
    monkeypatch.setattr(target_curve.os, "name", "nt")
    command = target_curve.reveal_command("C:/cars/EPY.txt")
    assert command[0] == "explorer" and len(command) == 2
    assert command[1].startswith("/select,") and command[1][8] != " "
    assert command[1].endswith("EPY.txt")


def test_a_platform_with_no_select_form_opens_the_folder(monkeypatch, tmp_path):
    """Linux has no portable "select this file", and opening the folder is the best that exists —
    but it must be the FOLDER, not the .txt, which xdg-open would hand to a text editor."""
    monkeypatch.setattr(target_curve.sys, "platform", "linux")
    monkeypatch.setattr(target_curve.os, "name", "posix")
    command = target_curve.reveal_command(tmp_path / "curves" / "EPY.txt")
    assert command == ["xdg-open", str(tmp_path / "curves")]


# ------------------------------------------- the copy of the tool with the curve in it
def test_the_curve_goes_INTO_the_tool_because_beside_it_is_nowhere(tmp_path):
    """The viewer performs no network request of any kind — its one curve is a JavaScript array
    inside the HTML, and `curves/` exists so a PERSON can pick a file up and drop it. So a file
    placed next to the page changes nothing, and the curve has to go in.

    The injection uses the tool's FRONT DOOR: it builds a `File` and hands it to the page's own
    file input, which is exactly what the picker does. Verified in a real browser — the page then
    lists SQ-Comp-Ref, Flat and EPY, with no console errors.
    """
    if target_curve.viewer_source() is None:
        pytest.skip("the vendored skill is not checked out")
    curve = _curve(tmp_path / "EPY_0db_REW.txt")
    out = target_curve.build_local_viewer(curve, "EPY", tmp_path / "viewer")
    assert out is not None and out.name == "EPY.html"
    html = out.read_text(encoding="utf-8")
    assert 'id="curveFile"' in html, "the tool's own input must still be there"
    assert "20 0.0" in html and "1000 -3.0" in html, "the curve's points travel with the copy"
    assert html.count("</body>") == 1 and html.rindex("Added by TCC") < html.rindex("</body>")


def test_the_injection_refuses_rather_than_producing_a_page_that_looks_right(tmp_path):
    """An injection that silently does nothing restores the original bug in a form nobody can
    see — the page opens, plots the wrong curve, and says nothing. So a viewer whose file input
    has been renamed is a refusal, and the caller falls back to handing over the file."""
    source = tmp_path / "viewer.html"
    source.write_text("<html><body><div id='dropZone'></div></body></html>", encoding="utf-8")
    curve = _curve(tmp_path / "EPY_0db_REW.txt")

    import autosound_tcc.core.target_curve as module

    original = module.viewer_source
    try:
        module.viewer_source = lambda: source
        assert module.build_local_viewer(curve, "EPY", tmp_path / "out") is None
    finally:
        module.viewer_source = original


def test_a_curve_that_the_tool_already_has_is_not_copied(tmp_path):
    """`needs_dropping` is what gates the copy, and it is False for a curve the tool ships — the
    online page is the better answer whenever it can answer at all."""
    if not target_curve.tool_curves():
        pytest.skip("the vendored skill is not checked out")
    assert not target_curve.describe(tmp_path, "SQ-Comp-Ref").needs_dropping


def test_the_fragment_carries_the_curve_without_sending_it_anywhere(tmp_path):
    """`#curve=<name>&data=<REW text>`. The FRAGMENT and not the query, and that is the point as
    much as the mechanism: a fragment never leaves the browser, so somebody's measured curve does
    not reach a web server's logs on the way to a page that only had to draw it."""
    curve = _curve(tmp_path / "EPY_0db_REW.txt")
    fragment = target_curve.fragment_for(curve, "EPY")
    assert fragment is not None and fragment.startswith("curve=EPY&data=")
    from urllib.parse import parse_qs

    parsed = parse_qs(fragment)
    assert parsed["curve"] == ["EPY"]
    assert "20 0.0" in parsed["data"][0] and "1000 -3.0" in parsed["data"][0]


def test_a_curve_file_that_cannot_be_read_makes_no_fragment(tmp_path):
    assert target_curve.fragment_for(tmp_path / "nope.txt", "EPY") is None
