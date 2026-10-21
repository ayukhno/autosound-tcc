"""What the copy of the method a project is BOUND to can do, read from its text (#169, tcc#200).

TCC reads with its own copy and writes, checks and runs sessions with the copy the project is bound
to (`method_binding`). A bound copy older than v3.1.4 — v3.1.0 to v3.1.3 stay allowed — matches a
round's titles as typed and judges a sweep over the band asked for; TCC's own copy, from v3.1.4,
matches by the series key and judges a sweep over its own range. Read with TCC's rule, such a
project's cards would disagree with its own close and step gate (the G6+G7 fix-B split), so TCC
reads each project by the rule of the copy it is bound to.

Found by the text, never by import — as `method_cli` finds a copy's flags: importing a copy TCC has
not decided to trust would run it. A heuristic, and a narrow one: each feature is one definition or
one word its release added. A copy that cannot be read is read as one without the feature: the rule
TCC had before it.

Nothing here imports Qt.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Optional

from autosound_tcc.core import app_log, config, method_binding

#: `(script under rew_tool/, what its text holds)` for each feature, all from v3.1.4.
TITLE_KEY = ("state/process.py", "def title_key(")       # #153: a round's titles by the series key
OWN_RANGE = ("verify.py", "band_source")                  # #154: a sweep judged over its own range
AGENTS_SETUP = ("project.py", "agents-setup")             # #149: the AGENTS.md Codex reads
#: From v3.2.0 (the skill's #176, tcc#220): `capture-check` writes `capture.level_base`, the round on
#: the project's level base. Not one of v3.1.4's: a copy without it is not «older», it keeps W-10's
#: reading of REW's listing (`level_calibration`), and nothing is said of it.
LEVEL_BASE = ("state/process.py", "def _level_base_of(")
#: From v3.2.0 (the skill's #191, 22d8988; tcc#220's task review, I2): an optional capture not taken
#: is no gap — `unusable_captures`, the exit code and the step's gate skip it (`_no_gap`). A copy
#: without it (v3.1.0 to v3.1.4) counts one as a gap, so the live card waits on it as before. Not
#: one of v3.1.4's either: no «older» warning for it.
NO_GAP = ("state/process.py", "def _no_gap(")

#: path -> (st_mtime_ns, st_size, text): one read per file until it changes.
_TEXT: dict[str, tuple[int, int, str]] = {}
_LOCK = threading.Lock()
#: The projects already told their copy is older than v3.1.4, in this run.
_TOLD: set[str] = set()


def _text(script: Path) -> Optional[str]:
    try:
        info = script.stat()
        key = (info.st_mtime_ns, info.st_size)
        with _LOCK:
            cached = _TEXT.get(str(script))
        if cached is not None and cached[:2] == key:
            return cached[2]
        text = script.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    with _LOCK:
        _TEXT[str(script)] = (*key, text)
    return text


def _script(feature: tuple[str, str], project_dir: Optional[Path | str]) -> Path:
    """The script `feature` is read from, in the copy `project_dir` is bound to. A copy TCC
    refuses runs nothing, so TCC's own copy answers for it."""
    binding = method_binding.for_project(Path(project_dir or config.project_dir()))
    if binding.state == method_binding.REFUSED or binding.skill_dir is None:
        return method_binding.own_copy() / "rew_tool" / feature[0]
    return binding.script(feature[0])


def has(feature: tuple[str, str], project_dir: Optional[Path | str] = None) -> bool:
    """Whether the copy `project_dir` is bound to holds `feature` in its text; a copy that cannot
    be read holds nothing."""
    text = _text(_script(feature, project_dir))
    return text is not None and feature[1] in text


def stated_number(script: Path, name: str) -> Optional[int]:
    """The integer a script's text assigns to the module constant `name` (`PROBE_WAIT_S = 60`), or
    None: a copy that does not state it, or cannot be read (#232).

    The whole statement or nothing: an optional type hint, digits with `_` between them, an optional
    trailing comment. `10 * 60` or `600.5` is a number this cannot read, not the 10 or 600 it starts
    with -- read so, `CLI_WAIT_MIN_S = 10 * 60` gave a review 185 s against the method's 600."""
    text = _text(script)
    found = re.search(rf"^{re.escape(name)}[ \t]*(?::[^=\n]*)?=[ \t]*([0-9](?:_?[0-9])*)[ \t]*(?:#.*)?$",
                      text or "", re.MULTILINE)
    return int(found.group(1)) if found else None


def unreadable(project_dir: Optional[Path | str] = None) -> Optional[Path]:
    """The first script of the v3.1.4 features the bound copy holds that TCC cannot read, or None:
    such a copy is read as one without them, and is said as unreadable, not as older."""
    for feature in (TITLE_KEY, OWN_RANGE):
        script = _script(feature, project_dir)
        if _text(script) is None:
            return script
    return None


def older_than_v314(project_dir: Optional[Path | str] = None) -> bool:
    """Whether the bound copy lacks what v3.1.4 brought to capture rounds: the series key or a
    sweep's own range."""
    return not (has(TITLE_KEY, project_dir) and has(OWN_RANGE, project_dir))


def say_if_older(project_dir: Optional[Path | str] = None) -> bool:
    """Tell the person once per project in this run, on the strip as a warning, that its copy is
    older than v3.1.4 and what that means on the card — and the way out; or, for a copy whose
    scripts cannot be read, that. True when it is read as older."""
    project = Path(project_dir or config.project_dir())
    if not older_than_v314(project):
        return False
    with _LOCK:
        if str(project) in _TOLD:
            return True
        _TOLD.add(str(project))
    from autosound_tcc.core import self_check  # its translator is the window's (`use_translator`)

    binding = method_binding.for_project(project)
    script = unreadable(project)
    if script is not None:  # not known to be older: it could not be read (the Rounds review)
        app_log.warn(self_check.translated("methodCopyUnreadable").format(
            path=script, entry=binding.entry))
        return True
    app_log.warn(self_check.translated("methodOlderThan314").format(
        path=binding.skill_dir or binding.entry, entry=binding.entry))
    return True

