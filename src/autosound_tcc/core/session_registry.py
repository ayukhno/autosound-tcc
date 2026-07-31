"""Which agent session belongs to which tuning phase — `<project>/.tcc/sessions.json`.

This is TCC's answer to SCR-019 ("when do we start a new Generator session vs. resume?"). The
rule the user settled on: **one phase of the skill's Phase −1..6 skeleton is roughly one AI
session.** Re-entering an unfinished phase resumes its session so the context is still there;
finishing a phase closes it so the next one starts clean instead of dragging a spent context
along.

The mechanism is cheap because the Agent SDK already persists sessions: we only store the id and
hand it back as `ClaudeAgentOptions.resume`.

Deliberately NOT `process/process-state.json` (SCR-004). That file is the skill's, describes the
*process*, and is written by the skill; this one is TCC's own bookkeeping about *sessions* and
would be noise inside the skill's schema.

**Which way the phase flows (D-6).** `current_phase` here is a MIRROR, never a source: it is set
only from a value read back out of the skill's `process-state.json`, so the two files cannot
disagree about whose answer counts. The step/status/evidence this registry used to store
alongside it are gone — that was TCC keeping its own copy of the process, which is exactly the
divergence (#10) the one-way-write rule closes. What stays is the part only TCC knows: which SDK
session id belongs to which phase, and whether that session is spent.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SessionRegistry:
    """Read/modify/write `<tcc_dir>/sessions.json`.

    Every mutation rewrites the whole (small) file. No in-memory cache: TCC's UI, the MCP server
    thread, and a headless CLI spike can all hold a registry over the same project at once, and a
    stale cache would let one of them clobber another's phase transition.
    """

    def __init__(self, tcc_dir: Path) -> None:
        self.path = Path(tcc_dir) / "sessions.json"

    # ---- reads -------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"schema_version": SCHEMA_VERSION, "current_phase": None, "phases": {}}
        data.setdefault("schema_version", SCHEMA_VERSION)
        data.setdefault("current_phase", None)
        data.setdefault("phases", {})
        return data

    def current_phase(self) -> Optional[str]:
        return self.load().get("current_phase")

    def resumable_session(self, phase: Optional[str] = None) -> Optional[str]:
        """The session id to resume for `phase`, or None if it's closed/unknown/never started.

        None is the signal to start a fresh session — the caller does not need to distinguish
        "phase finished" from "never ran", because both mean the same thing here.
        """
        data = self.load()
        phase = phase or data.get("current_phase")
        if not phase:
            return None
        entry = data["phases"].get(str(phase)) or {}
        if entry.get("closed"):
            return None
        return entry.get("session_id") or None

    # ---- writes ------------------------------------------------------------

    def sync_phase(self, phase: str) -> dict[str, Any]:
        """Point session bookkeeping at `phase`, closing the one before it.

        `phase` must be a value READ BACK from the skill's `process-state.json`, not one an agent
        claimed in a tool call (D-6): an agent that reports a phase it never actually entered would
        otherwise close a live session and orphan its context. Entering a different phase is the
        transition that ends an AI session — inferring it here means nothing has to manage session
        lifetime explicitly.

        Nothing about the process itself is stored: step, status and evidence live in the skill's
        file, and this registry deliberately keeps no second copy.
        """
        data = self.load()
        phase = str(phase)
        previous = data.get("current_phase")
        if previous and previous != phase:
            data["phases"].setdefault(previous, {})["closed"] = True
            data["phases"][previous]["updated"] = _now()
        entry = data["phases"].setdefault(phase, {"session_id": None, "closed": False})
        entry["closed"] = False
        entry["updated"] = _now()
        data["current_phase"] = phase
        self._write(data)
        return entry

    def bind_session(self, phase: str, session_id: str) -> None:
        """Attach the SDK's session id to a phase, so a later launch can resume it."""
        data = self.load()
        entry = data["phases"].setdefault(str(phase), {"closed": False})
        entry["session_id"] = session_id
        entry["updated"] = _now()
        data.setdefault("current_phase", str(phase))
        self._write(data)

    def close_phase(self, phase: str) -> None:
        data = self.load()
        entry = data["phases"].setdefault(str(phase), {})
        entry["closed"] = True
        entry["updated"] = _now()
        self._write(data)

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a crash mid-write would otherwise leave truncated JSON, and the next
        # launch would silently fall back to "no resumable session" and drop a live context.
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)
