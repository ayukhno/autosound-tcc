"""What the strip and the log say about a `process-state.json` that is there and does not read as
a state (#176; Task 24's review, M2). Plain Python, no Qt: the decision the window's
`_refresh_process` made inline — stop, and keep the plan on screen — with what it did not do, say
so; the window holds one `Unread` and asks it on every process refresh.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from autosound_tcc.core import app_log
from autosound_tcc.state import process_view
from autosound_tcc.ui.tcc import i18n


class Unread:
    """The guard on the plan. A file that is there and does not read as a state stops the refresh,
    and the plan on screen stays the last thing known to be true: blanking it turned half a second
    of somebody's writing into «the phases disappeared» — reported exactly that way, with them
    coming back on the next turn.

    It was silent. A file that STAYS unreadable — a hand edit gone wrong, a Windows program holding
    it — froze the plan with nothing in the log and nothing on screen, and a report that «the plan
    stopped updating» could not be read from either. Now each state of the file — why it does not
    read (`process_view.unreadable`, the read's own words), its size and time — is logged once at
    WARNING and said once on the strip, not on every refresh; and the line is taken back once the
    file reads again. The file is only read, never written or moved aside (R-bw): the method's to
    mend, and its own read names how."""

    def __init__(self) -> None:
        self._seen: Optional[tuple] = None
        self._line: Optional[str] = None

    def stops(self, strip, state: Optional[dict], project_dir: Optional[Path] = None) -> bool:
        """Whether the refresh stops here: `state` (`process_view.load_state()`) is None and the
        file is there. Says why on `strip` and in the log, once per state of the file; takes the
        line back from `strip` when the file reads or is gone."""
        there = state is None and process_view.has_process_state(project_dir)
        # None when it reads after all: the method did not load, or the write ended in between.
        why = process_view.unreadable(project_dir) if there else None
        if why is None:
            strip.withdraw(self._line)
            self._seen = self._line = None
            return there
        path = process_view.state_file(project_dir)
        try:
            info = path.stat()
            seen = (why, info.st_size, info.st_mtime_ns)
        except OSError:
            seen = (why, None, None)
        if seen != self._seen:
            self._seen = seen
            app_log.logger().warning("process-state.json at %s does not read, so the plan shown is "
                                     "the last one read: %s", path, why)
            strip.withdraw(self._line)
            self._line = i18n.t("processStateUnread").format(why=why)
            strip.notify(self._line, level="warn")
        return True
