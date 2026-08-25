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
from typing import Optional

# The skill's own name, and the directory both adapters expect it under inside a project.
# Duplicated from `tuning_session` on purpose: this module is imported by it, not the other way.
SKILL_NAME = "autosound-tuning"

# vendor_loader.py -> core -> autosound_tcc -> src -> <repo root>. Only meaningful in a checkout:
# from an installed wheel this points at `.../lib/python3.x`, which is how a `uv tool install`
# came out with no skill at all and said "run git submodule update" to somebody who has no repo
# (found by installing it, 2026-08-12).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SUBMODULE_DIR = _REPO_ROOT / "vendor" / "autosound-tuning-skill" / "skills" / SKILL_NAME

#: Env override, first in line. It is how a developer points TCC at a working tree of the skill,
#: and how a packaged install can be told where the skill went without guessing.
SKILL_DIR_ENV = "AUTOSOUND_SKILL_DIR"


def _candidates():
    """Where the skill may be, most specific first.

    Deliberately NOT "inside the wheel". The skill is its own repository and its own product —
    it works without TCC, TCC never works without it — and a copy shipped inside TCC would be a
    second source of truth that drifts from the one the user's Claude Code session actually runs.
    So TCC LOOKS for the installed skill instead of carrying one.
    """
    env = os.environ.get(SKILL_DIR_ENV)
    if env:
        yield Path(env).expanduser()
    yield _SUBMODULE_DIR  # a checkout: the submodule is the source of truth
    home = Path.home()
    yield home / ".claude" / "skills" / SKILL_NAME  # installed for Claude Code
    plugins = home / ".claude" / "plugins"
    if plugins.is_dir():
        # Installed as a Claude Code plugin — the front door option A recommends.
        yield from sorted(plugins.glob(f"*/skills/{SKILL_NAME}"))
        yield from sorted(plugins.glob(f"*/*/skills/{SKILL_NAME}"))


#: What makes a skill THIS TCC's skill. `rew_api.py` alone is any version back to v2.1; these two
#: arrived with the 3.0 format and are what TCC actually reads through — `project.py` for the
#: project's facts, `contract.py` for the diagnostics panel. A 2.x skill passed the old check and
#: then failed one call at a time: `load_project()` raised FileNotFoundError, diagnostics reported
#: itself unavailable, and the process writer cheerfully offered to write schema-v1 files into a
#: 3.0 project (found 2026-08-12, by pointing TCC at a v2.8.1 checkout).
_REQUIRED_FILES = ("rew_api.py", "project.py", "contract.py")


def _looks_like_the_skill(path: Path) -> bool:
    return all((path / "rew_tool" / name).is_file() for name in _REQUIRED_FILES)


def _looks_like_an_older_skill(path: Path) -> bool:
    """A real skill, of a line TCC cannot drive. Worth telling apart from "nothing here": the
    remedy is different and so is the surprise."""
    return (path / "rew_tool" / "rew_api.py").is_file() and not _looks_like_the_skill(path)


def older_skill_found() -> Optional[Path]:
    """Where a 2.x skill is sitting, when that is why nothing usable was found."""
    for candidate in _candidates():
        if _looks_like_an_older_skill(candidate):
            return candidate
    return None


def skill_dir() -> Path:
    """The skill this TCC will use. Resolved on every call, not once at import: the env override
    is the documented way to repoint it, and a value frozen at import would ignore it."""
    for candidate in _candidates():
        if _looks_like_the_skill(candidate):
            return candidate
    # Nothing found. Return the checkout path anyway so the error message names the place a
    # developer expects — the packaged case is covered by the message in `load()`.
    return _SUBMODULE_DIR


def skill_repo_root() -> Optional[Path]:
    """The repository the skill folder lives in — where `plugin.json` and `.git` are.

    `skill_dir()` returns the path TCC FOUND, which on an installed machine is a link into the
    clone: a symlink on macOS, a junction on Windows, both made by the installer. Two levels up
    from the link is `~/.claude`, which has no manifest and is not a git checkout — so the version
    came back empty and the update check said "not a git checkout" on every installed machine,
    while a developer's submodule checkout (a real path) worked and hid it (user's screenshot,
    Windows, 2026-08-19: the title bar said `(TCC 0.1.2)` with no skill beside it).

    So: follow the link first, then walk up looking for the marker rather than counting levels.
    Returns None when neither is found, which is a real answer — a skill folder unpacked on its
    own is not in a repository and cannot be updated in place.
    """
    here = skill_dir()
    try:
        here = here.resolve()
    except OSError:  # a broken link, a permission wall — the unresolved path still gets a look
        pass
    for parent in (here, *here.parents)[:4]:
        if (parent / ".claude-plugin" / "plugin.json").is_file() or (parent / ".git").exists():
            return parent
    return None


def rew_tool_dir() -> Path:
    return skill_dir() / "rew_tool"


def __getattr__(name: str):
    """`SKILL_DIR` / `REW_TOOL_DIR` as live module attributes.

    They were plain constants and are read as such all over TCC (`contract_check.script_path()`,
    `process_writer`, `critic`, the tests). Keeping the names but resolving them on access means
    the search order applies everywhere without touching each call site — and, unlike a constant,
    a skill installed after TCC started is found.
    """
    if name == "SKILL_DIR":
        return skill_dir()
    if name == "REW_TOOL_DIR":
        return rew_tool_dir()
    raise AttributeError(name)

# Vendored file (relative to REW_TOOL_DIR) -> synthetic module name we import it as.
_VENDORED = {
    "rew_api.py": "autosound_tcc._vendor.rew_api",
    "state/state.py": "autosound_tcc._vendor.dsp_state",
    "state/process.py": "autosound_tcc._vendor.process",
    "naming.py": "autosound_tcc._vendor.naming",
    "dsp_profile.py": "autosound_tcc._vendor.dsp_profile",
    "project.py": "autosound_tcc._vendor.project",
    # The filter maths (SCR-050): the curve window applies an all-pass to a measured trace and
    # takes the filter from HERE, so the front-end and the method can never disagree about what
    # `APF2 250 Hz Q 0.7` means. numpy at import, scipy only inside the crossover functions.
    "dsp_math.py": "autosound_tcc._vendor.dsp_math",
    # The Resonalyze virtual-crossover converter (2026-08-23): a session JSON becomes ledger rows
    # plus a per-field verdict against the DSP's declared capabilities. Imported rather than shelled
    # out to -- unlike `contract.py` it is a library with a thin CLI on top, and the window needs
    # the structured result, not its rendering.
    "resonalyze_vc.py": "autosound_tcc._vendor.resonalyze_vc",
    # Starting a project from an existing one (2026-08-23). It lives there and not here because
    # `project-schema.md` and `project.py` are the method's: the writer of `project.json` belongs
    # with the contract it writes, or the copy outside the schema drifts without anyone noticing.
    "project_seed.py": "autosound_tcc._vendor.project_seed",
    # One channel's EQ bank in the format its processor takes (2026-08-23, the user's call that
    # the formats belong to the method). Registered before it exists there: `core/eq_export.py`
    # asks for it and treats "not in this skill yet" as a state rather than an error, so the
    # window offers the copy the day the module lands and stays quiet until then.
    "eq_export.py": "autosound_tcc._vendor.eq_export",
    # Protective filters: what was in the signal path while measuring, and taking it back out of
    # the curve (2026-08-23). numpy at import, and scipy the moment it builds the filter -- the
    # protective response IS a crossover, and `dsp_math.xo_response` is the method's one scipy
    # caller. `core/protective.py` asks before offering the correction anywhere.
    "protective.py": "autosound_tcc._vendor.protective",
    # The listening vocabulary (2026-08-25): the characteristics a track exposes, in words, and
    # which track exposes which. A PARSER of the method's own markdown rather than a JSON copy
    # beside it -- the wording lives in one file, and a shape change fails in the SKILL's selftest
    # instead of in a widget in a car. Registered like `resonalyze_vc`: a library with a thin CLI
    # on top, and the window needs the structured result rather than its rendering.
    "listening.py": "autosound_tcc._vendor.listening",
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
    """True if a skill was found in any of the places `_candidates()` looks."""
    return _looks_like_the_skill(skill_dir())


def link_skill_into(project_dir: Path) -> Optional[Path]:
    """Make sure this project has the skill, and that it is *this* skill.

    Both adapters assume `<project>/.claude/skills/autosound-tuning` — the SDK reads it as its
    only setting source, omp as its only enabled skill — and until now nothing created it. A
    project without it does not fail: whatever happens to be in `~/.claude/skills` gets used
    instead, or nothing does, and the session improvises a tuning method of its own. That is how
    a real run came to follow a dead reference out of an old checkout, hunt the disk for three
    globs and an eight-minute `grep`, and then invent an intake.

    So TCC installs the version it ships, by symlink rather than copy: the vendored submodule is
    the single source of truth and a copy would drift from it silently. An existing entry is left
    alone whatever it points at — the user may have wired a working tree there on purpose, and
    replacing it under them would be worse than the problem this solves.

    Returns the link, or None when there is nothing to link (no submodule) or the filesystem
    refuses. Both are reported by the caller rather than raised: a session with a warning beats no
    session.
    """
    link = project_dir / ".claude" / "skills" / SKILL_NAME
    try:
        if link.exists() or link.is_symlink():
            return link
        if not is_available():
            return None
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(skill_dir().resolve(), target_is_directory=True)
        return link
    except OSError:
        return None


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
        # The message has to fit BOTH readers: a developer with a checkout who forgot the
        # submodule, and someone who installed TCC and has no repository to run git in.
        older = older_skill_found()
        if older is not None:
            raise VendorNotInitializedError(
                f"found a 2.x {SKILL_NAME} skill at {older}, and TCC needs the 3.x line — it "
                f"reads project.json and the contract checker, neither of which exists there.\n"
                f"Install the 3.0 skill (`/plugin install autosound-tuning-next`) or point "
                f"{SKILL_DIR_ENV} at a 3.x checkout.\n"
                f"Your 2.x projects are unaffected: they stay on 2.x, and the way across is "
                f"`rew_tool/state/migrate.py <old> --into <new>`."
            )
        looked = "\n  ".join(str(path) for path in _candidates())
        raise VendorNotInitializedError(
            f"the {SKILL_NAME} skill was not found. Looked in:\n  {looked}\n"
            f"In a checkout: git submodule update --init --recursive\n"
            f"Installed: install the skill for Claude Code, or set {SKILL_DIR_ENV}."
        )
    return _load_file(rew_tool_dir() / vendored_rel, _VENDORED[vendored_rel])


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


def load_dsp_math() -> ModuleType:
    """The skill's filter maths (`dsp_math.py`) — the all-pass responses, the RBJ biquads.

    Imports numpy on load, which the GUI extra has (it arrives with pyqtgraph) and a light install
    does not: called only from `core/allpass.py`, which is GUI-side for the same reason
    `core/curve_sum.py` is."""
    return load("dsp_math.py")


def load_resonalyze_vc() -> ModuleType:
    """The Resonalyze virtual-DSP-session converter (`resonalyze_vc.py`).

    It owns the conversion AND the "your DSP cannot enter this" verdict, per leg and per field --
    TCC renders that answer and refuses on it, and deliberately re-derives none of it: two
    implementations of one capability check is how the two halves start disagreeing about what a
    processor can do.

    Note for anyone debugging an import: this module puts `rew_tool/` on `sys.path` itself, at
    import time, so that its own `import project` / `import dsp_profile` resolve. That is the
    thing this loader exists to avoid doing globally -- harmless here because nothing in TCC ever
    imports a bare top-level `project`/`state`, but worth knowing before it surprises somebody.
    """
    return load("resonalyze_vc.py")


def load_project_seed() -> ModuleType:
    """Seeding a new project from an existing one (`project_seed.py`).

    TCC had this module for half a day and handed it over rather than keeping a copy: the
    classification of what travels -- the installation yes, the findings only on request, the
    other project's own write counter never -- is a statement about the project schema, and the
    schema is the method's. The window keeps the part that is genuinely its own: the folder
    picker, the translated marker the prose files get, and skipping the DSP interview when the
    profile came over.
    """
    return load("project_seed.py")


def load_project() -> ModuleType:
    """The project-facts module (`project.py`, SCR-001/011/014/015/016/017) — car/equipment/
    glossary/hardware-control facts. Not currently called by any TCC code path (`state/
    project_view.py` reads `project.json` directly, the same degrade-gracefully-without-the-
    submodule posture as the rest of that module); registered so a future writer-side feature
    (e.g. an in-app "set channel driver" action) has a working loader already in place."""
    return load("project.py")
