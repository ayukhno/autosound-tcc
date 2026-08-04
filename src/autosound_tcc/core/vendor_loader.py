"""Load flat modules from the vendored `rew_tool` without polluting sys.path.

`rew_tool/` is a flat script directory (no `__init__.py`), so it cannot be
imported as a normal package. The obvious fix — `sys.path.insert(0, rew_tool)`
— would put modules literally named `state`, `analysis`, etc. on the global
import path, colliding with our own `autosound_tcc.state` package. Instead we
load each vendored file by explicit path under a synthetic, namespaced module
name, keeping the vendored code physically isolated.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

# vendor_loader.py -> core -> autosound_tcc -> src -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[3]
REW_TOOL_DIR = (
    _REPO_ROOT
    / "vendor"
    / "autosound-tuning-skill"
    / "skills"
    / "autosound-tuning"
    / "rew_tool"
)

# Vendored file (relative to REW_TOOL_DIR) -> synthetic module name we import it as.
_VENDORED = {
    "rew_api.py": "autosound_tcc._vendor.rew_api",
    "state/state.py": "autosound_tcc._vendor.dsp_state",
    "state/process.py": "autosound_tcc._vendor.process",
    "naming.py": "autosound_tcc._vendor.naming",
    "dsp_profile.py": "autosound_tcc._vendor.dsp_profile",
    "project.py": "autosound_tcc._vendor.project",
}
# `contract.py` (the whole-project machine-contract checker, SKILL-SYNC-PLAN.md §2.3) is
# deliberately NOT registered here: it's shaped as a CLI (`python rew_tool/contract.py check
# <project> --json`), and a future diagnostics panel should shell out to it (`subprocess`), the
# same pattern TCC already uses for the Critic scripts, rather than import it in-process.


class VendorNotInitializedError(RuntimeError):
    """Raised when the `rew_tool` submodule has not been checked out.

    Fix: `git submodule update --init --recursive`.
    """


def is_available() -> bool:
    """True if the vendored `rew_tool` submodule is present on disk."""
    return (REW_TOOL_DIR / "rew_api.py").is_file()


def child_env(**extra: str) -> dict[str, str]:
    """Environment for a subprocess that runs the skill's own scripts.

    `PYTHONDONTWRITEBYTECODE` is the point: the skill is a git submodule, and every import of
    it drops `__pycache__/*.pyc` into someone else's working tree. That repo tracks those files,
    so running the skill from TCC shows up as uncommitted changes in a repo TCC does not own —
    noise that hides real drift and invites committing build output by accident. We are the ones
    spawning the interpreter, so we are the ones who say don't.
    """
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **extra}


def _load_file(path: Path, module_name: str) -> ModuleType:
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so any intra-module self-reference resolves.
    sys.modules[module_name] = module
    # Same reason as `child_env`, for the in-process half: exec_module caches bytecode next to
    # the source, which is inside the submodule.
    previously = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    finally:
        sys.dont_write_bytecode = previously
    return module


def load(vendored_rel: str) -> ModuleType:
    """Import one vendored file (e.g. ``"rew_api.py"``) as its namespaced module."""
    if vendored_rel not in _VENDORED:
        raise KeyError(f"unknown vendored module {vendored_rel!r}; known: {sorted(_VENDORED)}")
    if not is_available():
        raise VendorNotInitializedError(
            "rew_tool submodule not found at "
            f"{REW_TOOL_DIR}. Run: git submodule update --init --recursive"
        )
    return _load_file(REW_TOOL_DIR / vendored_rel, _VENDORED[vendored_rel])


def load_rew_api() -> ModuleType:
    """The REW HTTP-API module (`rew_api.py`)."""
    return load("rew_api.py")


def load_dsp_state() -> ModuleType:
    """The DSP-state ledger module (`state/state.py`)."""
    return load("state/state.py")


def load_process() -> ModuleType:
    """The process-state module (`state/process.py`, SCR-004) — phase, plan, journal."""
    return load("state/process.py")


def load_naming() -> ModuleType:
    """Measurement naming + the per-car glossary (`naming.py`, SCR-008)."""
    return load("naming.py")


def load_dsp_profile() -> ModuleType:
    """The DSP capability-profile module (`dsp_profile.py`)."""
    return load("dsp_profile.py")


def load_project() -> ModuleType:
    """The project-facts module (`project.py`, SCR-001/011/014/015/016/017) — car/equipment/
    glossary/hardware-control facts. Not currently called by any TCC code path (`state/
    project_view.py` reads `project.json` directly, the same degrade-gracefully-without-the-
    submodule posture as the rest of that module); registered so a future writer-side feature
    (e.g. an in-app "set channel driver" action) has a working loader already in place."""
    return load("project.py")
