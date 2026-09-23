"""Record that a version was saved into a DSP preset under a name — through the method (hub #198).

`slots.json` has one writer, the skill's `state.py config save`, for the same reason the process
journal does: the previous configuration a save continues is computed there, from the version's
ancestry, and two writers would compute two ancestries. TCC composes the call and reports what the
method said; it never writes the file.

Exit 0 prints the record in one line; exit 3 is a refusal with its reason on stderr (the old
layout, an unknown version, a missing name). A vendored method older than `config` answers with
argparse's exit 2 — said as "update the method", not as a failure of the save.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from autosound_tcc.core import app_log, child, vendor_loader

_TIMEOUT_S = 30


@dataclass(frozen=True)
class SaveResult:
    saved: bool
    #: What the method said: the record on success, the refusal otherwise.
    said: str
    #: The vendored method does not know `config` yet.
    too_old: bool = False


def script_path() -> Path:
    return vendor_loader.REW_TOOL_DIR / "state" / "state.py"


def save(state_root: Path, version: str, name: str, *, slot: Optional[str] = None,
         dsp_preset: Optional[str] = None, purpose: Optional[str] = None) -> SaveResult:
    argv = [child.script_interpreter(), str(script_path()), "--root", str(state_root),
            "config", "save", version, name]
    if slot:
        argv += ["--slot", slot]
    if dsp_preset:
        argv += ["--dsp-preset", dsp_preset]
    if purpose:
        argv += ["--purpose", purpose]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=_TIMEOUT_S, env=vendor_loader.child_env(),
                              **child.quiet())
    except (OSError, subprocess.SubprocessError) as exc:
        return SaveResult(False, f"{type(exc).__name__}: {exc}")
    app_log.logger().info("config save %s as %r -> exit %s", version, name, proc.returncode)
    if proc.returncode == 0:
        return SaveResult(True, proc.stdout.strip())
    err = proc.stderr.strip()
    too_old = proc.returncode == 2 and "invalid choice: 'config'" in err
    return SaveResult(False, err, too_old=too_old)
