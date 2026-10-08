"""Record that a version was saved into a DSP preset under a name — through the method (hub #198).

`slots.json` has one writer, the skill's `state.py config save`, for the same reason the process
journal does: the previous configuration a save continues is computed there, from the version's
ancestry, and two writers would compute two ancestries. TCC composes the call and reports what the
method said; it never writes the file.

Exit 0 prints the record in one line; exit 3 is a refusal with its reason on stderr (the old
layout, an unknown version, a missing name). A vendored method older than `config` answers with
argparse's exit 2 — said as "update the method", not as a failure of the save. The copy that runs
is the one the project is bound to (#169), started through `method_cli` as every method script is;
a copy TCC will not run is a save not made, with the binding's sentence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from autosound_tcc.core import app_log, config, method_cli, vendor_loader

_TIMEOUT_S = 30

#: The writer, relative to the method's `rew_tool/`.
_SCRIPT = "state/state.py"


@dataclass(frozen=True)
class SaveResult:
    saved: bool
    #: What the method said: the record on success, the refusal otherwise.
    said: str
    #: The vendored method does not know `config` yet.
    too_old: bool = False


def script_path() -> Path:
    """TCC's own `state.py`, for a caller with no project. A save runs the copy its project is
    bound to (`save`)."""
    return vendor_loader.REW_TOOL_DIR / "state" / "state.py"


def save(state_root: Path, version: str, name: str, *, slot: Optional[str] = None,
         dsp_preset: Optional[str] = None, purpose: Optional[str] = None,
         project_dir: Optional[Path] = None) -> SaveResult:
    """Save `version` under `name` in the ledger at `state_root`, by the method's own writer.

    `project_dir` is the project whose copy of the method runs the save (#169) — the current one
    (`config.project_dir()`) when it is not given, which is the save dialog's case: its
    `state_root` is that project's `state/`. Under `AUTOSOUND_STATE_ROOT` the ledger may lie
    elsewhere; the copy is still the current project's. No lock: `slots.json` is not the journal
    the project's lock guards.
    """
    args = ["--root", str(state_root), "config", "save", version, name]
    if slot:
        args += ["--slot", slot]
    if dsp_preset:
        args += ["--dsp-preset", dsp_preset]
    if purpose:
        args += ["--purpose", purpose]
    project = Path(project_dir) if project_dir is not None else config.project_dir()
    try:
        code, out, err = method_cli.spawn(project, _SCRIPT, args, timeout_s=_TIMEOUT_S, lock=False)
    except method_cli.ProcessWriterError as exc:
        # A copy TCC will not run (the binding's sentence, verbatim), a script not there, a timeout.
        return SaveResult(False, str(exc))
    app_log.logger().info("config save %s as %r -> exit %s", version, name, code)
    if code == 0:
        return SaveResult(True, out)
    too_old = code == 2 and "invalid choice: 'config'" in err
    return SaveResult(False, err, too_old=too_old)
