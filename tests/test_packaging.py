"""The light half stays light, and the heavy half fails in a sentence.

`autosound-tcc` ships in two sizes: the base install is `claude-agent-sdk` and nothing else, the
window is an extra because PySide6 + pyqtgraph is hundreds of megabytes. That split is only real
while the CLI entry points import no Qt — and adding one import to a `core/` module breaks it
invisibly, because every developer machine has the GUI installed. Hence a test.

Decision and reasoning: `docs/ARCHITECTURE-NOTES.md` §3 (2026-08-12).
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Everything a light install must be able to run. The MCP server is on the list because TCC's
#: whole non-GUI story is "the model talks to the project through it".
LIGHT_MODULES = (
    "autosound_tcc.tuning_session_cli",
    "autosound_tcc.dsp_profile_interview",
    "autosound_tcc.core.mcp_server",
    "autosound_tcc.core.app_log",
    "autosound_tcc.core.config",
    "autosound_tcc.core.delay_bank",
    "autosound_tcc.core.project_settings",
    "autosound_tcc.core.contract_check",
)

#: Blocked as a group: shiboken6 is PySide6's own runtime, and numpy arrives with pyqtgraph.
_HEAVY = ("PySide6", "pyqtgraph", "shiboken6", "numpy")

_BLOCKER = f'''
import sys

_HEAVY = {_HEAVY!r}


class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in _HEAVY:
            raise ImportError("not installed in a light install: " + name)
        return None


sys.meta_path.insert(0, _Block())
'''


def _run(body: str) -> subprocess.CompletedProcess:
    """A fresh interpreter, because the import blocker has to be in place before anything else.

    A subprocess and not `monkeypatch`: pytest itself has already imported Qt by the time any test
    runs, so an in-process check would be testing a cache rather than an install.
    """
    return subprocess.run(
        [sys.executable, "-c", _BLOCKER + body],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )


@pytest.mark.parametrize("module", LIGHT_MODULES)
def test_the_cli_half_imports_with_no_gui_installed(module):
    proc = _run(f"import {module}")
    assert proc.returncode == 0, (
        f"{module} needs the GUI extra, so a light install cannot run it\n"
        f"--- stderr ---\n{proc.stderr[-3000:]}"
    )


def test_asking_for_the_window_without_it_prints_what_to_type():
    """A traceback about `PySide6.QtWidgets` tells the reader nothing they can act on."""
    proc = _run(
        "import sys; sys.argv = ['autosound-tcc']\n"
        "from autosound_tcc.app import main\n"
        "raise SystemExit(main())"
    )

    assert proc.returncode == 2, "a refusal, not a crash and not a success"
    assert "uv tool install" in proc.stderr and "[gui]" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_the_two_sizes_are_declared_the_way_the_split_assumes():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    base = data["project"]["dependencies"]
    extras = data["project"]["optional-dependencies"]

    assert not [d for d in base if d.split(">")[0].strip().lower() in ("pyside6", "pyqtgraph")], (
        "the base install must not carry the toolkit; that is what the `gui` extra is for"
    )
    assert any("PySide6" in d for d in extras["gui"])
    # The suite is mostly Qt, run offscreen — `dev` has to pull the window in.
    assert any("gui" in d for d in extras["dev"])


def test_every_console_script_points_at_something_that_exists():
    """A dangling entry point is only discovered by the person who typed the command."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    for name, target in data["project"]["scripts"].items():
        module, _, func = target.partition(":")
        path = ROOT / "src" / Path(module.replace(".", "/") + ".py")
        assert path.exists(), f"{name} -> {module} has no module"
        assert f"def {func}(" in path.read_text(encoding="utf-8"), f"{name} -> {target} missing"
