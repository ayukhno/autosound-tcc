"""Run the vendored skill's own `selftest` entry points, so that something does.

They are the skill's only tests, they cover the writers and the gates TCC depends on, and until
this file existed **nothing ran them but a person remembering to**. That is not a theoretical gap:
`rew_tool.py selftest` had been failing outright since the v3 identity split and nobody noticed
for weeks (2026-08-07).

Not a duplicate of the skill's own discipline — a backstop for it. They stay runnable by hand,
which is what a plain-terminal user has; this makes CI and a local `pytest` see them too.

Each is a subprocess because that is what they are: CLI entry points with their own `__main__`.
Importing them would run a different thing from what a person runs.

**The list is discovered, not written down** (F-031, 2026-08-22). It used to be twelve paths kept
by hand with a completeness test beside them, and the completeness test was blind in a way nobody
could see from reading it: it looked for the quoted string `"selftest"`, which finds the modules
that take the command positionally and none of the thirteen that take `--selftest` — a whole style
of entry point, eleven modules, never run by us while a green test said the list was complete. One
of the eleven was `xover_select`, on the evening `xo_response` turned out to draw every steep low
crossover wrong. The skill's own runner had the mirror hole, a glob that did not recurse into
`state/` and `gates/`: two partial sets, each believing it was the whole. So the rule below is the
same rule `scripts/run-selftests.sh` applies, and if the two ever disagree, that script is the
source of truth — it is what the method's own CI runs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from autosound_tcc.core import vendor_loader

pytestmark = pytest.mark.skipif(
    not vendor_loader.is_available(), reason="rew_tool submodule not checked out"
)


def _rew_tool_dir():
    return vendor_loader.REW_TOOL_DIR


def _discover() -> list[tuple[str, tuple[str, ...]]]:
    """Every `rew_tool` module with a selftest, and the argv that runs it.

    Mirrors `scripts/run-selftests.sh`: every `*.py` under the tool directory (recursively —
    `state/` and `gates/` are packages, not files), `__init__.py` skipped, the style chosen by
    whether the file mentions `--selftest`, and `naming.py` handed a project directory it ignores
    but argv must carry.
    """
    root = _rew_tool_dir()
    found = []
    for path in sorted(root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "selftest" not in text:
            continue
        rel = path.relative_to(root).as_posix()
        command = "--selftest" if "--selftest" in text else "selftest"
        argv = (".", command) if rel == "naming.py" else (command,)
        found.append((rel, argv))
    return found


_SELFTESTS = _discover() if vendor_loader.is_available() else []


@pytest.mark.parametrize(
    "module,argv", _SELFTESTS, ids=[m for m, _ in _SELFTESTS] or ["none-discovered"]
)
def test_skill_selftest_passes(module, argv):
    root = _rew_tool_dir()
    proc = subprocess.run(
        [sys.executable, str(root / module), *argv],
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


def test_discovery_sees_subpackages_and_both_command_styles():
    """The two blind spots that made F-031, pinned so neither can come back quietly.

    A discovery that stops recursing loses `state/` and `gates/` entirely; one that only knows the
    positional command loses thirteen modules including `xover_select`. Both failures look exactly
    like success — a shorter list nobody counts — so the property is asserted rather than left to
    be noticed.
    """
    modules = {module for module, _ in _SELFTESTS}
    assert modules, "no selftests discovered at all — the rule stopped matching the skill"

    packages = {module.split("/")[0] for module in modules if "/" in module}
    assert {"state", "gates"} <= packages, (
        f"discovery is not reaching the subpackages: found {sorted(packages)}"
    )

    styles = {argv[-1] for _, argv in _SELFTESTS}
    assert styles == {"selftest", "--selftest"}, (
        f"only one command style discovered ({sorted(styles)}) — the skill has two"
    )


def test_the_three_installers_still_agree_with_each_other():
    """The one check in the skill's runner that is not a `rew_tool` selftest.

    `install.sh`, `install.ps1` and `install.cmd` repeat five decisions between them — both
    repositories, the tag glob, the pinned `PS1URL`, the default mode — and until this script
    existed they were kept identical by hand (our own F-030 is the fourth copy of the tag glob,
    the one that lives here and stays ours to keep in step).
    """
    repo = vendor_loader.skill_repo_root()
    if repo is None:
        pytest.skip("the skill is not in a checkout, so its scripts are not there to run")
    script = Path(repo) / "scripts" / "installer-consistency.py"
    if not script.is_file():
        pytest.skip(f"pinned skill has no {script.name} (it arrived in v3.0.13)")
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"the installers disagree (exit {proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout[-3000:]}\n--- stderr ---\n{proc.stderr[-3000:]}"
    )
