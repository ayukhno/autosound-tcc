"""pytest plugin: run the suite as if the vendored submodule were not there.

Written for `docs/ARCHITECTURE-NOTES.md` §8 — the analysis of removing
`vendor/autosound-tuning-skill`, which ended in REJECTED. The numbers in that section came from
here, and a number recorded without the command that reproduces it does not cross the boundary,
so the command lives in the tree rather than in somebody's scratch directory.

**It touches no files.** Everything in the suite reaches the method through `vendor_loader`, so
dropping the submodule from its candidate list is the same thing as deleting the directory — and
it is undone by not passing `-p`. Deleting a submodule working tree to measure it would be the
kind of destructive check that is worse than the question.

    AUTOSOUND_HIDE=submodule   drop the submodule candidate only
    AUTOSOUND_HIDE=all         no method anywhere

Measured 2026-08-27, on the pin `70a4fa7` (`v3.0.36`):

    as-is                                          1438 passed,   1 skipped
    -p submodule_absent                             178 failed, 1205 passed, 25 errors
    -p submodule_absent + AUTOSOUND_SKILL_DIR=…    1438 passed,   1 skipped

Reproduce, from the repository root:

    uv run --extra dev --python 3.12 python -m pytest tests/ -q            # as-is
    PYTHONPATH=spike uv run --extra dev --python 3.12 python -m pytest tests/ -q \\
        -p submodule_absent
    PYTHONPATH=spike AUTOSOUND_SKILL_DIR=<a 3.x checkout>/skills/autosound-tuning \\
        uv run --extra dev --python 3.12 python -m pytest tests/ -q -p submodule_absent

The third line is the point of the exercise: a neighbouring checkout carries the whole suite,
installer-consistency tests included, so a replacement technically exists. §8 is about why it
costs more than it returns.

**Why the second line is not simply "the installed skill takes over".** It cannot, inside the
suite: `tests/conftest.py` swaps `HOME` for a tmp_path on every test (for QSettings), so the
`~/.claude/skills` and `~/.claude/plugins` candidates point into an empty temporary directory.
The suite depends on the submodule because of that fixture, not because the product does — the
product ships no method at all, which is the first finding in §8.
"""
import os
from pathlib import Path

#: Somewhere that cannot exist, so `_looks_like_the_skill` fails on it the way it would on a
#: repository checked out without `--recurse-submodules`.
GONE = Path("/nonexistent/no-submodule-here/skills/autosound-tuning")


def pytest_configure(config):
    from autosound_tcc.core import vendor_loader

    mode = os.environ.get("AUTOSOUND_HIDE", "submodule")
    if mode == "all":
        vendor_loader._candidates = lambda: iter(())
    vendor_loader._SUBMODULE_DIR = GONE

    print(f"\n[submodule_absent] AUTOSOUND_HIDE={mode} -> "
          f"skill_dir={vendor_loader.skill_dir()} available={vendor_loader.is_available()}")
