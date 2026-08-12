"""Resolve where the DSP-state ledger and the tuning project live.

The ledger lives under `project_dir()/state/` by default (2026-07-29: scoped per-project --
previously a global path shared by every project, so a brand-new "Create new project" folder
showed whichever ledger happened to be sitting at the old default). Both the ledger root and the
preset can still be overridden by environment variables:

    AUTOSOUND_STATE_ROOT       directory holding <preset>/v_NNN.json subdirs (overrides the
                               project-scoped default -- this dev checkout's own dogfood ledger at
                               `data/private/state/` needs this set explicitly now). Same spelling
                               the skill's own `rew_tool/state/state.py` CLI uses (SCR-011 --
                               one env-var convention on both sides of the submodule boundary, no
                               `AUTOSOUND_TCC_*` variant kept).
    AUTOSOUND_TCC_PRESET       preset name (subdir); auto-detected if unset and
                               exactly one preset directory exists -- TCC-only (a multi-preset UI
                               selector), no skill-side equivalent to converge with.
    AUTOSOUND_PROJECT_DIR      the tuning project folder the AI session runs in -- also the
                               skill's own convention; no `AUTOSOUND_TCC_PROJECT_DIR` fallback.

**Project folder** (TCC-TZ.md §3): one project = one folder the user points at,
with a recent-projects list and *zero* disk scanning. That folder is the agent's
`cwd`, holds the skill's own state, and gets TCC's `.tcc/` and `.mcp.json`
written into it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# config.py -> core -> autosound_tcc -> src -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STATE_ROOT = _REPO_ROOT / "data" / "private" / "state"
# INSIDE the package, not beside it. It used to be `<repo>/data/dsp_profiles`, which exists in a
# checkout and nowhere else: a `uv tool install` produced a New Project dialog with no bundled
# profiles at all, silently, because a wheel contains only what is under `src/autosound_tcc`
# (found by installing it, 2026-08-12). One location that works in both layouts beats a build
# rule that copies it into a second one.
DEFAULT_BUNDLED_PROFILES_DIR = Path(__file__).resolve().parent.parent / "dsp_profiles"


def state_root() -> Path:
    """Where `<preset>/v_NNN.json` ledgers live for the CURRENT project.

    Scoped under `project_dir()` (2026-07-29 fix -- previously a project-independent global/env
    path, so opening a brand-new "Create new project" folder showed whichever ledger happened to
    be sitting at the old default, e.g. this dev checkout's own dogfood data). Override with
    `AUTOSOUND_STATE_ROOT` for pointing at a ledger tree that predates this per-project scoping
    (this repo's own `data/private/state/` dogfood ledger included) -- same env var the skill's
    own CLI reads (SCR-011).
    """
    env = os.environ.get("AUTOSOUND_STATE_ROOT")
    return Path(env).expanduser() if env else project_dir() / "state"


# QSettings keys for the user's project-folder choice. The chosen folder outlives a single run
# (recent-projects list, TCC-TZ.md §3) but an env var still wins, so a dogfood/CI run can point at
# a different project without touching the developer's saved preference.
_PROJECT_DIR_KEY = "project/dir"
_RECENT_PROJECTS_KEY = "project/recent"
MAX_RECENT_PROJECTS = 8


def chosen_project_dir() -> Optional[Path]:
    """The project folder the user actually chose, or None if they never chose one.

    `project_dir()` cannot answer this: it ends in `DEFAULT_STATE_ROOT` so that every caller gets
    *a* path, which means a fresh install silently opens this checkout's own dogfood folder. A
    window that must not open on a folder nobody picked needs the difference.

    Note what is NOT checked: whether the folder contains anything. An empty directory is a valid
    new project -- the intake fills it -- so "choose a folder" and "create a project" are one act,
    and judging the contents here would invent a second.
    """
    env = os.environ.get("AUTOSOUND_PROJECT_DIR")
    if env:
        return Path(env).expanduser()
    saved = _settings().value(_PROJECT_DIR_KEY, "")
    return Path(str(saved)).expanduser() if saved else None


def project_dir() -> Path:
    """The tuning project folder: agent `cwd`, skill state, `.tcc/`, `dsp_profile.json`.

    Resolution order — env override, then the user's persisted choice, then `DEFAULT_STATE_ROOT`
    as the last-resort fallback for a truly unconfigured install (this dev checkout's own
    `data/private/state/` dogfood location, kept as-is for continuity). Deliberately NOT
    `state_root()` -- that function now derives ITS default FROM `project_dir()` (2026-07-29 fix),
    so falling back to it here would recurse. `project.json` lives directly at this folder's top
    level, `state/<preset>/v_NNN.json` under it (SKILL-SYNC-PLAN.md D1) -- the skill's own layout,
    not a TCC-specific nesting.

    `AUTOSOUND_PROJECT_DIR` is the skill's own env var (SCR-011); no `AUTOSOUND_TCC_PROJECT_DIR`
    fallback is kept -- the two names were never meant to coexist long-term.
    """
    env = os.environ.get("AUTOSOUND_PROJECT_DIR")
    if env:
        return Path(env).expanduser()
    saved = _settings().value(_PROJECT_DIR_KEY, "")
    if saved:
        return Path(str(saved)).expanduser()
    return DEFAULT_STATE_ROOT


def set_project_dir(path: Path) -> None:
    """Persist the user's project choice and push it to the front of the recent list."""
    path = Path(path).expanduser()
    settings = _settings()
    settings.setValue(_PROJECT_DIR_KEY, str(path))
    recent = [str(path)] + [p for p in _recent_raw(settings) if p != str(path)]
    settings.setValue(_RECENT_PROJECTS_KEY, recent[:MAX_RECENT_PROJECTS])


def recent_projects() -> list[Path]:
    """Recently opened project folders, newest first, filtered to ones that still exist."""
    return [Path(p) for p in _recent_raw(_settings()) if Path(p).is_dir()]


def looks_like_project(path: Path) -> bool:
    """Whether `path` plausibly is a tuning project, for validating a folder the user picked.

    Deliberately loose: a project the skill has driven has `autosound_context.md`, one TCC has
    opened before has `.tcc/`, and one that has only been through DSP-profile onboarding has just
    `dsp_profile.json`. Any of those counts; an empty folder the user means to start fresh in
    doesn't, so the caller can warn rather than silently write into the wrong place.
    """
    path = Path(path)
    return any(
        (path / name).exists()
        for name in ("autosound_context.md", ".tcc", "dsp_profile.json", "rew_analitic")
    )


def tcc_dir(project_dir_: Optional[Path] = None) -> Path:
    """TCC's own per-project scratch: session registry, signal bus, UI-mode mirror.

    Deliberately NOT the skill's `process/` directory (SCR-004) — that namespace belongs to the
    skill, and squatting on it would make the eventual real `process-state.json` ambiguous.
    """
    return (project_dir_ or project_dir()) / ".tcc"


def mcp_config_path(project_dir_: Optional[Path] = None) -> Path:
    """Where TCC advertises its own MCP server so any CLI launched in the project picks it up."""
    return (project_dir_ or project_dir()) / ".mcp.json"


def _settings():
    # Imported lazily so this module stays importable (and the ledger paths stay resolvable)
    # without a Qt application object having been constructed yet.
    from autosound_tcc.ui.tcc.app_settings import get_settings

    return get_settings()


def _recent_raw(settings) -> list[str]:
    value = settings.value(_RECENT_PROJECTS_KEY, [])
    if isinstance(value, str):  # QSettings collapses a 1-element list back to a bare string
        return [value] if value else []
    return [str(v) for v in (value or [])]


def dsp_profile_path(project_dir_: Optional[Path] = None) -> Path:
    return (project_dir_ or project_dir()) / "dsp_profile.json"


def project_path(project_dir_: Optional[Path] = None) -> Path:
    """The skill-owned `project.json` -- car/equipment/glossary/hardware facts, plus the
    facts this project's left panel renders in its System/Project/Car-audio-analysis
    sections. Replaces the TCC-only `project_profile.json` (D2, SKILL-SYNC-PLAN.md §0): one file,
    written by the skill, instead of two files with an overlapping and easily-diverging job.
    Absent by default; nothing renders until intake writes it."""
    return (project_dir_ or project_dir()) / "project.json"


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
