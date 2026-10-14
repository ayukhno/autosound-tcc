"""Which project folder a window reads, and whether a delayed re-read may still run on it.

Both project switches (a new project, Open folder) repoint the process-wide folder first and close
the old window after. With a session live, that close asks Save, Discard or Cancel, and Cancel keeps
the old window — whose agent re-read and watcher reload then read the NEW folder into it, beside a
session whose tools still write to the old one (W-8's branch-code M2, #206). A window pins its
folder when it is built; a read on a folder that is no longer it reads nothing and says, on a line
that stays up, to open TCC again (`ours`); TCC's own writes go to the folder it shows (`tcc_dir`).

Out of `main_window.py`, which may not grow (`tests/test_structure_ratchet.py`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from autosound_tcc.core import app_log, config
from autosound_tcc.ui.tcc import i18n

#: A window built without `pin` (a stand-in in a test): no folder to compare, every re-read runs.
_UNPINNED = object()


def pin() -> Optional[Path]:
    """The folder a window being built reads: the one chosen now, or None."""
    return config.chosen_project_dir()


def may_reread(window, what: str) -> bool:
    """Whether `what`, a delayed re-read of `window`'s project, may run now: not on a window that
    is closing (F-053), and only on the folder it was built on (`ours`)."""
    if getattr(window, "_closing", False):
        app_log.logger().info("%s is skipped: the window is closing", what)
        return False
    return ours(window, what)


def ours(widget, what: str) -> bool:
    """Whether `what`, a read of the project `widget`'s window shows, may run now.

    The one guard for every reader that follows the process-wide folder (the header's ↻, a preset
    pick, the agent's re-read, the watcher, the contract and intake checks, #206's group review
    I1): once the process's folder is another than the one the window was built on, that is a
    cancelled switch — the window reads nothing, and says so once on a line that stays up, naming
    both folders. A widget whose window pinned none (a stand-in in a test) reads as before."""
    window = _owner(widget)
    if window is None:
        return True
    now = config.chosen_project_dir()
    if _same(window._built_on, now):
        return True
    app_log.logger().info("%s is skipped: the project folder is now %s, this window reads %s",
                          what, now, window._built_on)
    if not getattr(window, "_told_reopen", False):
        window._told_reopen = True
        window._status_strip.notify(
            i18n.t("projectStillShows").format(old=window._built_on, new=now),
            level="warn", sticky=True)
    return False


def folder(widget) -> Optional[Path]:
    """The project folder `widget`'s window shows — after a cancelled switch the old one, where
    the session beside it writes too — or None (follow the process's) for a window that pinned
    none. What the window writes of TCC's own goes there, not to the process's (I1)."""
    window = _owner(widget)
    return None if window is None else window._built_on


def tcc_dir(widget) -> Path:
    """`folder`'s `.tcc/`."""
    return config.tcc_dir(folder(widget))


def project(widget) -> Path:
    """The project `widget`'s window works on, for what it writes and what it reads beside it.

    The process's folder while the window still shows it; after a cancelled switch the folder the
    window was built on — where the session beside it writes too. The measurement panel's import
    and Refresh went to the process's: Cancel on a new project left project A's window open, and
    ⤓ wrote A's captures into B's round store, B's ledger and B's level record (Fable's I4). A
    window built with no folder chosen worked on `config.DEFAULT_STATE_ROOT` (`config.project_dir`).
    """
    kept = _kept(widget)
    return config.project_dir() if kept is None else kept


def state_root(widget) -> Path:
    """`project`'s ledger root (`config.state_root`, `AUTOSOUND_STATE_ROOT` honoured)."""
    kept = _kept(widget)
    return config.state_root() if kept is None else config.state_root(kept)


def _kept(widget) -> Optional[Path]:
    """The folder `widget`'s window kept through a cancelled switch, or None: no switch (follow
    the process's, as everything did before), or no window that pinned one."""
    window = _owner(widget)
    if window is None or _same(window._built_on, config.chosen_project_dir()):
        return None
    return window._built_on if window._built_on is not None else config.DEFAULT_STATE_ROOT


def _owner(widget):
    """The window `widget` belongs to that pinned a folder (`pin`), or None."""
    while widget is not None:
        if getattr(widget, "_built_on", _UNPINNED) is not _UNPINNED:
            return widget
        parent = getattr(widget, "parentWidget", None)
        widget = parent() if callable(parent) else None
    return None


def _same(one: Optional[Path], other: Optional[Path]) -> bool:
    if one is None or other is None:
        return one is other
    try:
        return Path(one).resolve() == Path(other).resolve()
    except OSError:
        return Path(one) == Path(other)
