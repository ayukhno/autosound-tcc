"""G13 step 0 (hub H-013): `main_window.py` may not grow, and each wave lowers the bound.

Progress is two numbers — the file's lines and the full windows the tests build. A decision pulled
out of the window into a Qt-free module (the `row_rule` precedent, F-091) lowers both: its window
tests become plain-function tests. A bound is lowered in the commit that shrinks the file, never
raised -- and a measure that sits more than its slack under the bound fails too, so the room a
change frees is not spent by the next one. A build inside a helper counts once however many tests
call it: moving builds into a helper is not a way to lower the bound (the G13 review).

The next decisions to pull out — they live only on the window and are pinned by window tests:
`_capture_version`, the compare default, the preset choice in `_load_project`, the «settled»
verdict parsed from text, the reviewer's state, and the delay maths mirrored in `curve_view`
(`delay_bank`, `curve_sum`). Out already: the menu (`menu_registry`), the gate's three layers
(`shell_gate.effective_gate`), the open signals' ids (`SignalBus.open_ids`) — W-8.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
WINDOW = ROOT / "src" / "autosound_tcc" / "ui" / "tcc" / "main_window.py"

#: What a full-window build looks like in a test — spelled in two halves, so this file does not
#: count itself.
BUILD = "Main" + "Window("

#: Lowered by every wave that moves a decision out; never raised (W-8: 6506 on 2026-10-06, 6270
#: after the menu moved into its registry, #161).
MAIN_WINDOW_MAX_LINES = 6270
#: Full-window builds in the tests, outside comments (W-8: 223 on 2026-10-06, 218 after the menu
#: tests became renderer tests, #161).
WINDOW_BUILDS_MAX = 218
#: How far under its bound a measure may sit before the bound must come down with it.
SLACK_LINES = 20
SLACK_BUILDS = 2


def lines_of(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def window_builds(folder: Path) -> int:
    count = 0
    for path in sorted(folder.glob("test_*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            count += line.split("#", 1)[0].count(BUILD)
    return count


def over(measured: int, bound: int, what: str) -> Optional[str]:
    if measured <= bound:
        return None
    return (f"{what}: {measured} > {bound}. Move a decision out of the window (the row_rule "
            "precedent) instead of adding to it; the bound is lowered, never raised.")


def slack(measured: int, bound: int, allowed: int, what: str) -> Optional[str]:
    if bound - measured <= allowed:
        return None
    return (f"{what}: {measured} is {bound - measured} under its bound {bound}. Lower the bound to "
            f"{measured} in this commit, so the room is not spent by the next change.")


def test_main_window_does_not_grow():
    measured = lines_of(WINDOW)
    assert over(measured, MAIN_WINDOW_MAX_LINES, "main_window.py lines") is None
    assert slack(measured, MAIN_WINDOW_MAX_LINES, SLACK_LINES, "main_window.py lines") is None


def test_the_tests_build_no_more_full_windows():
    measured = window_builds(ROOT / "tests")
    assert measured > 0, "the walk found no test files: a moved folder would pass this"
    assert over(measured, WINDOW_BUILDS_MAX, "full-window builds") is None
    assert slack(measured, WINDOW_BUILDS_MAX, SLACK_BUILDS, "full-window builds") is None


def test_the_ratchet_goes_red_past_its_bound(tmp_path):
    """Green by design, so shown failing: a file one line over, a build in code and not in a comment."""
    (tmp_path / "w.py").write_text("a\nb\nc\n", encoding="utf-8")
    (tmp_path / "test_x.py").write_text(
        f"w = {BUILD})\n# {BUILD}) in a comment\nx = {BUILD})  # and one here\n", encoding="utf-8")

    assert over(lines_of(tmp_path / "w.py"), 2, "w") is not None
    assert over(lines_of(tmp_path / "w.py"), 3, "w") is None
    assert window_builds(tmp_path) == 2
    assert slack(3, 24, 20, "w") is not None and slack(3, 23, 20, "w") is None
