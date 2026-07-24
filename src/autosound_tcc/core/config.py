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


def state_root() -> Path:
    env = os.environ.get("AUTOSOUND_TCC_STATE_ROOT")
    return Path(env).expanduser() if env else DEFAULT_STATE_ROOT


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
