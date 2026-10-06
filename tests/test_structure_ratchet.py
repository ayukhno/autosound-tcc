"""G13 step 0 (hub H-013): `main_window.py` may not grow, and each wave lowers the bound.

Progress is two numbers — the file's lines and the full windows the tests build. A decision pulled
out of the window into a Qt-free module (the `row_rule` precedent, F-091) lowers both: its window
tests become plain-function tests. A bound is lowered in the commit that shrinks the file, never
raised.

The next decisions to pull out — they live only on the window and are pinned by window tests:
`_capture_version`, `_effective_gate`, the compare default, the preset choice in `_load_project`,
the «settled» verdict parsed from text, the signal ids parsed from `unacked_brief` (pinned by
`test_the_signal_nudge_reads_every_open_signals_id_from_the_brief`), the reviewer's state, and the
delay maths mirrored in `curve_view` (`delay_bank`, `curve_sum`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
WINDOW = ROOT / "src" / "autosound_tcc" / "ui" / "tcc" / "main_window.py"

#: What a full-window build looks like in a test — spelled in two halves, so this file does not
#: count itself.
BUILD = "Main" + "Window("

#: Lowered by every wave that moves a decision out; never raised (W-8, measured 2026-10-06).
MAIN_WINDOW_MAX_LINES = 6506
#: Full-window builds in the tests, outside comments (W-8, measured 2026-10-06).
WINDOW_BUILDS_MAX = 223


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


def test_main_window_does_not_grow():
    assert over(lines_of(WINDOW), MAIN_WINDOW_MAX_LINES, "main_window.py lines") is None


def test_the_tests_build_no_more_full_windows():
    assert over(window_builds(ROOT / "tests"), WINDOW_BUILDS_MAX, "full-window builds") is None


def test_the_ratchet_goes_red_past_its_bound(tmp_path):
    """Green by design, so shown failing: a file one line over, a build in code and not in a comment."""
    (tmp_path / "w.py").write_text("a\nb\nc\n", encoding="utf-8")
    (tmp_path / "test_x.py").write_text(
        f"w = {BUILD})\n# {BUILD}) in a comment\nx = {BUILD})  # and one here\n", encoding="utf-8")

    assert over(lines_of(tmp_path / "w.py"), 2, "w") is not None
    assert over(lines_of(tmp_path / "w.py"), 3, "w") is None
    assert window_builds(tmp_path) == 2
