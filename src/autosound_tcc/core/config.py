"""Resolve where the DSP-state ledger lives.

The ledger is install-specific private data (brief §3a) — it never ships in the
repo. During development it sits under the gitignored ``data/private/state/``.
Both the root and the preset can be overridden by environment variables so a
user can point the app at their own project folder without code changes:

    AUTOSOUND_TCC_STATE_ROOT   directory holding <preset>/v_NNN.json subdirs
    AUTOSOUND_TCC_PRESET       preset name (subdir); auto-detected if unset and
                               exactly one preset directory exists
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# config.py -> core -> autosound_tcc -> src -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STATE_ROOT = _REPO_ROOT / "data" / "private" / "state"
DEFAULT_BUNDLED_PROFILES_DIR = _REPO_ROOT / "data" / "dsp_profiles"


def state_root() -> Path:
    env = os.environ.get("AUTOSOUND_TCC_STATE_ROOT")
    return Path(env).expanduser() if env else DEFAULT_STATE_ROOT


def project_dir() -> Path:
    """Directory holding this project's `dsp_profile.json`.

    Defaults to `state_root()` — the same tree also holds `<preset>/v_NNN.json` for now. Full
    `project.json` + `presets/<preset>/{target,state}` nesting (TCC-TZ.md §3) is a later storage
    migration, not required for the profile mechanism itself.
    """
    env = os.environ.get("AUTOSOUND_TCC_PROJECT_DIR")
    return Path(env).expanduser() if env else state_root()


def dsp_profile_path(project_dir_: Optional[Path] = None) -> Path:
    return (project_dir_ or project_dir()) / "dsp_profile.json"


def project_profile_path(project_dir_: Optional[Path] = None) -> Path:
    """Project-level facts that don't change between presets/versions (car setup, chassis, amp
    gains, ...) -- rendered as extra left-panel PARAMS sections (item 2, 2026-07-27). Absent by
    default; nothing renders until this file exists."""
    return (project_dir_ or project_dir()) / "project_profile.json"


def bundled_profiles_dir() -> Path:
    """Reference DSP profiles shipped with the app (public, no project data)."""
    return DEFAULT_BUNDLED_PROFILES_DIR


def _preset_dirs(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and any(p.glob("v_*.json")))


def resolve_preset(root: Optional[Path] = None) -> Optional[str]:
    """The configured preset, or the sole auto-detected one, or None."""
    root = root or state_root()
    env = os.environ.get("AUTOSOUND_TCC_PRESET")
    if env:
        return env
    presets = _preset_dirs(root)
    return presets[0] if len(presets) == 1 else None


def available_presets(root: Optional[Path] = None) -> list[str]:
    return _preset_dirs(root or state_root())
