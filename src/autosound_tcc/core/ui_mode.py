"""TCC's two operating modes (TCC-TZ.md §8) -- `<project>/.tcc/ui_mode.json`.

`view` = a read-only reader over a project the skill drives from a terminal, no AI. `control` =
the agent/MCP work: in-app session or the user's own CLI, the MCP server, the Arbiter gate.

Deliberately NOT QSettings, unlike theme/zoom/language -- §8 is explicit that mode is a property
of the *project* (a person can view one folder Monday and control another Tuesday), not a global
app preference. Same write-then-rename JSON shape as `core/session_registry.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

Mode = Literal["view", "control"]
DEFAULT_MODE: Mode = "view"


def get_mode(tcc_dir: Path) -> Mode:
    path = Path(tcc_dir) / "ui_mode.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_MODE
    mode = data.get("mode")
    return mode if mode in ("view", "control") else DEFAULT_MODE


def set_mode(tcc_dir: Path, mode: Mode) -> None:
    if mode not in ("view", "control"):
        raise ValueError(f"unknown mode: {mode!r}")
    tcc_dir = Path(tcc_dir)
    tcc_dir.mkdir(parents=True, exist_ok=True)
    path = tcc_dir / "ui_mode.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"mode": mode}, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
