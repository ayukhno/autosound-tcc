"""The project's `AGENTS.md`, which Codex reads where Claude reads `CLAUDE.md` (skill #149).

From v3.1.4 the method seeds `AGENTS.md` beside `CLAUDE.md` in a new project: the skill's load line
and its feedback rule, written for Codex. A project made before that has none, and a Codex started
on it — in TCC or in a terminal — reads neither the load line nor the rule. The method's own
command writes it into an existing project: `project.py <project> agents-setup`, which never
overwrites a file that is there. TCC runs it once before a Codex start, when the file is missing,
through the copy the project is bound to (`method_cli`, #169) — never its own text.

Blocking — a child process: the in-app session calls it off the event loop, the terminal before
Codex takes the console. A refusal is said by the caller and never stops the start: Codex runs
without the file, as it did before v3.1.4.

Nothing here imports Qt.
"""

from __future__ import annotations

from pathlib import Path

import threading

from autosound_tcc.core import app_log, method_cli, method_features

#: The file Codex reads, at the project's root.
FILE = "AGENTS.md"
#: The method's command, relative to its `rew_tool/`.
_SCRIPT = "project.py"
#: A file written and a line printed: well inside this, even on a slow disk.
_TIMEOUT_S = 30.0
#: What a bound copy before v3.1.4 is told, once per project in this run (tcc#200's review, I3).
OLDER = "this project's method is older than v3.1.4 — no agents-setup, so Codex gets no AGENTS.md"
_TOLD: set[str] = set()
_LOCK = threading.Lock()


def ensure(project_dir: Path | str) -> str:
    """Give the project the `AGENTS.md` Codex reads, through the method, when it has none.

    Returns "" when there is nothing to say: the file (or anything under its name) is already
    there, so the method is not asked; the folder holds no `project.json`, so it is no project the
    method writes into; or the method wrote it. Otherwise one line saying why it was not written —
    the method's refusal in its own words, or why the run did not come back.

    A bound copy before v3.1.4 has no `agents-setup` — read from its `project.py`'s text, never
    started: its usage line would be said on every Codex start. That is said once per project in
    this run (`OLDER`), "" after. Never raises: a folder that cannot be looked into is a sentence."""
    project = Path(project_dir)
    try:
        if (project / FILE).exists() or (project / FILE).is_symlink():
            return ""
        if not (project / "project.json").is_file():
            return ""
    except OSError as exc:
        return f"{FILE} was not written: {project} could not be read ({exc.strerror or exc})"
    if not method_features.has(method_features.AGENTS_SETUP, project):
        with _LOCK:
            if str(project) in _TOLD:
                return ""
            _TOLD.add(str(project))
        app_log.logger().warning("agents-setup on %s: %s", project, OLDER)
        return OLDER
    try:
        code, out, err = method_cli.spawn(project, _SCRIPT, [str(project), "agents-setup"],
                                          timeout_s=_TIMEOUT_S, lock=False)
    except method_cli.ProcessWriterError as exc:
        app_log.logger().warning("agents-setup on %s did not run: %s", project, exc)
        return f"{FILE} was not written: {exc}"
    if code == 0:
        app_log.logger().info("agents-setup on %s: %s", project, out or err)
        return ""
    lines = [line.strip() for line in (err or out).splitlines() if line.strip()]
    said = lines[-1].removeprefix("error: ") if lines else f"{_SCRIPT} exited {code}"
    app_log.logger().warning("agents-setup on %s: exit %s: %s", project, code, said)
    return f"{FILE} was not written: {said}"
