"""Which project folder a window reads, and whether a delayed re-read may still run on it.

Both project switches (a new project, Open folder) repoint the process-wide folder first and close
the old window after. With a session live, that close asks Save, Discard or Cancel, and Cancel keeps
the old window — whose agent re-read and watcher reload then read the NEW folder into it, beside a
session whose tools still write to the old one (W-8's branch-code M2, #206). A window pins its
folder when it is built; a re-read on a folder that is no longer it reads nothing and says, once, to
open TCC again.

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
    """Whether `what`, a delayed re-read of `window`'s project, may run now.

    Not on a window that is closing (F-053) — and not once the process's folder is another than
    the one the window was built on (`window._built_on`): that is a cancelled switch, and the
    window says once to open TCC again."""
    if getattr(window, "_closing", False):
        app_log.logger().info("%s is skipped: the window is closing", what)
        return False
    built_on = getattr(window, "_built_on", _UNPINNED)
    if built_on is _UNPINNED:
        return True
    now = config.chosen_project_dir()
    if _same(built_on, now):
        return True
    app_log.logger().info("%s is skipped: the project folder is now %s, this window reads %s",
                          what, now, built_on)
    if not getattr(window, "_told_reopen", False):
        window._told_reopen = True
        window._status_strip.notify(i18n.t("projectReopen"), level="warn")
    return False


def _same(one: Optional[Path], other: Optional[Path]) -> bool:
    if one is None or other is None:
        return one is other
    try:
        return Path(one).resolve() == Path(other).resolve()
    except OSError:
        return Path(one) == Path(other)
