"""Run the vendored skill's own `selftest` entry points, so that something does.

They are the skill's only tests, they cover the writers and the gates TCC depends on, and until
now **nothing ran them but a person remembering to**. That is not a theoretical gap: `rew_tool.py
selftest` had been failing outright since the v3 identity split and nobody noticed for weeks
(2026-08-07), and three of the eight grew new cases this week only because a defect sent someone
to look.

Not a duplicate of the skill's own discipline — a backstop for it. They stay runnable by hand,
which is what a plain-terminal user has; this makes CI and a local `pytest` see them too.

Each is a subprocess because that is what they are: CLI entry points with their own `__main__`.
Importing them would run a different thing from what a person runs.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from autosound_tcc.core import vendor_loader

#: (module path relative to `rew_tool/`, extra argv before `selftest`).
#: `naming.py` takes a project directory first; the rest take none.
#: TEN, not the eight anybody could name. `curve_view.py` and `state/migrate.py` were found by
#: the completeness test below on its first run — both have a working `selftest` and neither was
#: on the list a person keeps in their head, which is the whole argument for having the list
#: checked by a test instead of by memory (2026-08-12).
SELFTESTS = (
    ("project.py", ()),
    ("dsp_profile.py", ()),
    ("contract.py", ()),
    ("naming.py", (".",)),
    ("state/state.py", ()),
    ("state/apply.py", ()),
    ("state/process.py", ()),
    ("rew_tool.py", ()),
    ("curve_view.py", ()),
    ("state/migrate.py", ()),
)

pytestmark = pytest.mark.skipif(
    not vendor_loader.is_available(), reason="rew_tool submodule not checked out"
)


def _rew_tool_dir():
    return vendor_loader.REW_TOOL_DIR


@pytest.mark.parametrize("module,args", SELFTESTS, ids=[m for m, _ in SELFTESTS])
def test_skill_selftest_passes(module, args):
    root = _rew_tool_dir()
    proc = subprocess.run(
        [sys.executable, str(root / module), *args, "selftest"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=180,
    )
    # Both streams: some of them print their summary on stdout and their failures on stderr, and a
    # bare "exit 1" tells whoever reads CI nothing they can act on.
    assert proc.returncode == 0, (
        f"{module} selftest failed (exit {proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout[-3000:]}\n--- stderr ---\n{proc.stderr[-3000:]}"
    )


def test_every_selftest_in_the_skill_is_listed_here():
    """The list above is hand-written, so it can fall behind the skill it is meant to cover.

    A module that grows a `selftest` and is not added here is a module nobody runs — which is the
    exact state all eight were in before this file existed.
    """
    root = _rew_tool_dir()
    found = {
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if '"selftest"' in path.read_text(encoding="utf-8", errors="ignore")
        and "__main__" in path.read_text(encoding="utf-8", errors="ignore")
    }
    listed = {module for module, _ in SELFTESTS}
    missing = {
        name for name in found - listed
        # `verify.py` and friends compare against `sys.argv` for other commands; only count a
        # module that actually dispatches a `selftest` command of its own.
        if "selftest" in (root / name).read_text(encoding="utf-8", errors="ignore").split(
            "def main", 1
        )[-1]
    }
    assert not missing, f"skill modules with a selftest that nothing runs: {sorted(missing)}"
