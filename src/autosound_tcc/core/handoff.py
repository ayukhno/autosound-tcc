"""Is everything the NEXT session needs on disk? — the method's `handoff`, asked (hub #201, S-044).

A session can neither restart itself nor clear, and a phase boundary is where the chat holding
the only copy of something gets thrown away. The method's `process.py <dir> handoff --json`
answers whether the next session has what it needs, and writes nothing either way:

    {ok, missing: [str], phase, resume, next_message}

`missing` names, item by item, the command that fixes it; `next_message` is what the new session
starts with («продовжуй»); `resume` says what must stay open (the REW session with the round's
captures). TCC shows the answer and starts nothing without the Arbiter's click.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from autosound_tcc.core import app_log, child, process_writer, vendor_loader

_TIMEOUT_S = 30


def check(project_dir: Path) -> Optional[dict]:
    """The method's answer, or None when the vendored method cannot give one (older than `--json`)."""
    script = process_writer.script_path()
    if not script.is_file():
        return None
    try:
        proc = subprocess.run(
            [child.script_interpreter(), str(script), str(Path(project_dir) / "process"),
             "handoff", "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_TIMEOUT_S, env=vendor_loader.child_env(), **child.quiet())
    except (OSError, subprocess.SubprocessError) as exc:
        app_log.logger().info("handoff: did not run: %s", type(exc).__name__)
        return None
    app_log.logger().info("handoff --json -> exit %s", proc.returncode)
    if proc.returncode not in (0, 1):
        return None
    try:
        answer = json.loads(proc.stdout)
    except ValueError:
        return None
    if not isinstance(answer, dict) or "ok" not in answer:
        return None
    answer["missing"] = [str(m) for m in answer.get("missing") or []]
    return answer
