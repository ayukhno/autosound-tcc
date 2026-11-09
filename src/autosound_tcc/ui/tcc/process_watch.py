"""What the plan's watcher holds, and which of its events are worth a redraw (#246).

A file watch cannot catch a file that is not there yet, so a `process-state.json` that appeared
after the project opened left Plan and Captures empty until a reopen. The watcher therefore also
holds a folder: `process/`, or the project folder until `process/` exists.

This is `_process_watcher`, never the project's: a project reload re-renders from disk and wipes
the capture grid (#225). And a folder event redraws only when the state file came or went, since
a redraw rebuilds that grid too and the skill writes `journal.jsonl` beside the state on every
step. A write to the state itself is the file watch's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QFileSystemWatcher

from autosound_tcc.core import app_log, config
from autosound_tcc.state import process_view


def _folder_to_watch(state_file: Path) -> set[str]:
    """Where the state file will show up. Nothing for a project nobody chose: `project_dir()` then
    ends in a fallback folder, and the file there is all that was ever watched."""
    if config.chosen_project_dir() is None:
        return set()
    process = state_file.parent
    folder = process if process.is_dir() else process.parent
    return {str(folder)} if folder.is_dir() else set()


def add(watcher: QFileSystemWatcher, paths: list[str]) -> None:
    """`addPaths`, whose answer is what it could not hold: a watch limit, or a path gone since it
    was looked at. One log line; there is nothing on the screen a person could do about it."""
    if refused := watcher.addPaths(paths):
        app_log.logger().warning("the file watcher could not hold: %s", ", ".join(refused))


class StateWatch:
    """Connects `watcher` and keeps it on exactly the paths the current project needs."""

    def __init__(self, watcher: QFileSystemWatcher, redraw: Callable[[], None]) -> None:
        self._watcher = watcher
        self._redraw = redraw
        self._there = False
        watcher.fileChanged.connect(lambda *_args: redraw())
        watcher.directoryChanged.connect(self._on_folder)

    def arm(self) -> None:
        """Hold what is wanted now and let go of the rest: a folder that went, the last project's
        paths. The folder first, then the look at the file: a file made between the two is then
        an event on the folder rather than a gap. Called before every read of the state."""
        state_file = process_view.state_file()
        self._hold(self._watcher.directories(), _folder_to_watch(state_file))
        self._there = state_file.is_file()
        self._hold(self._watcher.files(), {str(state_file)} if self._there else set())

    def _hold(self, held: list[str], wanted: set[str]) -> None:
        if gone := set(held) - wanted:
            self._watcher.removePaths(sorted(gone))
        if new := wanted - set(held):
            add(self._watcher, sorted(new))

    def _on_folder(self, *_args) -> None:
        was_there = self._there
        self.arm()  # now, not after the timer: a `process/` just made is to be held at once
        if self._there != was_there:
            self._redraw()
