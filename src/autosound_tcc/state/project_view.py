"""Read the skill-owned `project.json` into the shapes the left panel's sections render.

TCC is a schema *consumer* here too (same posture as `process_view.py`/`measurement_view.py`):
the skill's `rew_tool/project.py` owns `project.json` and is the only writer. This module turns
that file into flat `(label, value)` rows for two sections that used to be static placeholders
(SKILL-CHANGE-REQUESTS.md SCR-015/016). Rows are built from the FACTS in that file — a
`param_sections` key used to ship ready-made label/value rows for these same panels, and was
dropped in skill schema v3 because it restated values already stored as fields here:

* **System params** — the equipment side of the project: DSP model, amps, mic, source (SCR-015
  point 1).
* **Project params' channel-tier summary** — "8 virtual channels (1 off), 12 output channels
  (2 off)" (SCR-016): a project-scoped FACT the skill already knows at intake, not re-derived
  client-side from the ledger + profile (that re-derivation is possible but deliberately avoided —
  the skill owns the schema and writes the data, TCC renders it).
* **`_open_questions`** as onboarding TODO chips, so unresolved intake facts are visible in the UI,
  not only on disk.

**Car audio analysis stays a placeholder** (SCR-015 point 2) — `project.json` has no schema for
acoustic-analysis facts (cabin RT60, install-quality notes) yet, and this module does not invent
one; a loader here is a small addition once the skill defines it.

Returns empty tuples when `project.json` doesn't exist yet, same convention as
`state/dsp_state.py::load_hardware_controls` — a brand-new project reads as "nothing yet", not an
error.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

from autosound_tcc.core import config

# A panel row is not worth a stall: a slow mount answers "say nothing".
_GIT_TIMEOUT_S = 2.0


def fact_value(x: Any) -> Any:
    """Unwrap a `fact(value, source, at)` object, or pass a bare value through.

    Mirrors `rew_tool/project.py::fact_value`, deliberately rather than importing it: this is two
    lines of FORMAT reading (documented in `project-schema.md`'s Provenance section), and every
    other loader in this module works without the submodule being checked out. Reading a fact is
    not the same as owning one — the values themselves still come only from the skill's file.

    A reader never needs to know which fields are wrapped, which is the point: `fs_hz` is, `role`
    is not, and both go through here.
    """
    return x.get("value") if isinstance(x, dict) and "value" in x else x


def has_project(project_dir_: Optional[Path] = None) -> bool:
    return config.project_path(project_dir_).is_file()


def _load(project_dir_: Optional[Path] = None) -> dict:
    path = config.project_path(project_dir_)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_system_params(project_dir_: Optional[Path] = None) -> tuple[tuple[str, str], ...]:
    """`(label, value)` rows for the System params section: DSP model, amps, mic, source.

    Only facts actually present render — an intake that hasn't reached a given block yet simply
    omits that row, not an empty value (same "lenient on absent facts" convention as the rest of
    the machine-file family: `state.py`/`process.py`/`project.py`).
    """
    data = _load(project_dir_)
    rows: list[tuple[str, str]] = []

    dsp = data.get("dsp") or {}
    dsp_name = " ".join(filter(None, (dsp.get("vendor"), dsp.get("model"))))
    if not dsp_name:
        # `project.json` arrives late: the intake asks about the car, the drivers and their Fs
        # before it is written, and a session can legitimately spend a whole conversation short of
        # that. `dsp_profile.json` arrives early -- it is finalised as soon as the DSP is named --
        # so it is the first real fact a session produces, and a panel that shows nothing while it
        # sits on disk reads as a session that did nothing.
        dsp_name = dsp_from_profile(project_dir_) or ""
    if dsp_name:
        rows.append(("DSP", dsp_name))

    for amp in data.get("amps") or []:
        if not isinstance(amp, dict):
            continue
        name = " ".join(filter(None, (amp.get("make"), amp.get("model"))))
        if not name:
            continue
        label = f"Amp ({amp['role']})" if amp.get("role") else "Amp"
        rows.append((label, name))

    mic = (data.get("mic") or {}).get("model")
    if mic:
        rows.append(("Mic", str(mic)))

    source = (data.get("source") or {}).get("head_unit")
    if source:
        rows.append(("Source", str(source)))

    return tuple(rows)


def dsp_from_profile(project_dir_: Optional[Path] = None) -> Optional[str]:
    """`vendor model` out of `dsp_profile.json`, or None.

    Read as plain JSON rather than through the skill's loader: this is one label for a sidebar
    row, and going through `vendor_loader` would make a missing submodule turn an empty panel
    into an exception.
    """
    path = config.dsp_profile_path(project_dir_)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    profile = data.get("dsp_profile") if isinstance(data, dict) else None
    if not isinstance(profile, dict):
        return None
    name = " ".join(
        str(part) for part in (profile.get("vendor"), profile.get("name") or profile.get("model"))
        if part and str(part).lower() != "unknown"
    ).strip()
    return name or None


def load_channel_summary(project_dir_: Optional[Path] = None) -> tuple[tuple[str, str], ...]:
    """`(label, value)` rows for the project-scoped channel-tier summary (SCR-016), e.g.
    `("Virtual channels", "8 (1 off)")`. Not re-derived from the ledger client-side — the skill
    already counts this at intake and writes it here."""
    summary = _load(project_dir_).get("channel_summary") or {}
    if not isinstance(summary, dict):
        return ()
    rows = []
    for tier_id, counts in summary.items():
        if not isinstance(counts, dict):
            continue
        total = counts.get("total")
        if total is None:
            continue
        off = counts.get("off") or 0
        label = str(tier_id).replace("_", " ").capitalize()
        value = f"{total}" + (f" ({off} off)" if off else "")
        rows.append((label, value))
    return tuple(rows)


def channel_name(entry: dict) -> Optional[str]:
    """The name a channel goes by today — its `code` (SCR-039).

    A ledger row's key is the channel's *id*, so the key is not the label: after a rename they are
    the old name and the new one. Every renderer asks here rather than showing the key, which is
    what makes a rename visible in the app without rewriting a single snapshot.
    """
    code = fact_value((entry or {}).get("code"))
    return str(code) if code else None


def load_channels(project_dir_: Optional[Path] = None) -> dict[str, dict]:
    """`project.json`'s `channels[]`, keyed by every name a ledger row might use.

    SCR-001, resolved 2026-07-31: **`project.json` owns channel identity, the ledger owns tunable
    state, consumers join on `code`.** The mechanical test for which side a field belongs to is
    "does it change from snapshot to snapshot?" — `driver`, `fs_hz`, `slot`, `descr`, `role`,
    `order`, `hidden` do not; gain, delay, crossover and EQ do.

    Skill schema v3 removed those fields from the ledger row outright, so a migrated project has
    exactly one home for each. `state/dsp_state.py` still falls back to a ledger row's copy, which
    is a 2.x reader and nothing more.

    Rows without a `code` are skipped rather than guessed at — an entry with no join key cannot be
    matched to anything, and inventing one would attach a driver to the wrong channel.

    **The ledger's row key is the channel's `id`, not its name** (SCR-039). The id defaults to the
    code, so for a project that has never renamed a channel this map is exactly what it always was:
    one key per channel. After a rename the same entry answers to three — the id every snapshot was
    written with, the name it goes by now, and each name it went by before — because a snapshot is
    immutable and an old REW title cannot be edited at all. A live code always wins over another
    channel's history, so a name handed on resolves to whoever holds it now rather than to whoever
    happens to come first in the file.
    """
    channels = _load(project_dir_).get("channels") or []
    if not isinstance(channels, list):
        return {}
    out: dict[str, dict] = {}
    for entry in channels:
        if not isinstance(entry, dict) or not entry.get("code"):
            continue
        previous = entry.get("previous_names")
        keys = [entry.get("id"), entry.get("code")]
        keys += list(previous) if isinstance(previous, list) else []
        for key in keys:
            if key and (str(key) not in out or key == entry.get("code")):
                out[str(key)] = entry
    return out


def driver_label(entry: dict) -> Optional[str]:
    """`{"make": "Audiofrog", "model": "GB25"}` -> `"Audiofrog GB25"`.

    Tolerates the bare string an older file (or a ledger row) might carry, and returns None when
    there is no driver assigned — an unassigned slot renders without the line, not with an empty one.
    """
    driver = fact_value((entry or {}).get("driver"))
    if isinstance(driver, str):
        return driver or None
    if not isinstance(driver, dict):
        return None
    name = " ".join(
        str(part) for part in (driver.get("make"), driver.get("model")) if part
    )
    return name or None


def load_open_questions(project_dir_: Optional[Path] = None) -> tuple[str, ...]:
    """Unresolved intake facts (dotted paths) for onboarding TODO chips — `project.json`'s
    `_open_questions`, the same convention `dsp_profile.json` and the skill's own
    `rew_tool/project.py::open_questions` use."""
    return tuple(str(q) for q in (_load(project_dir_).get("_open_questions") or []))


def git_facts(project_dir_: Optional[Path] = None) -> tuple[tuple[str, str], ...]:
    """Branch and working-tree state of the project folder, when it is a git repo.

    The skill makes a new project a git repo on purpose -- the tune's history is the point, and
    `naming-and-structure.md §4a` says which files are tracked. TCC showed none of it, so "am I on
    the branch I think, and is anything unsaved?" meant leaving the app. Two rows, read-only, and
    silent when the folder is not a repo: not every project is one, and saying "not a git repo"
    would be noise on the ones that are not.

    Never raises and never blocks for long: a missing `git`, a repo mid-rebase or a folder on a
    slow mount all resolve to "say nothing" rather than to a spinner in a panel.
    """
    project = Path(project_dir_ or config.project_dir())
    if not (project / ".git").exists():
        return ()
    rows: list[tuple[str, str]] = []
    # `rev-parse HEAD` fails on a repo with no commits yet -- which a project is for its whole
    # first session -- so the branch comes from the ref itself, with rev-parse as the fallback for
    # a detached head.
    branch = _git(project, "symbolic-ref", "--short", "HEAD") or _git(
        project, "rev-parse", "--short", "HEAD"
    )
    if branch:
        rows.append(("Git", branch))
    status = _git(project, "status", "--porcelain")
    if status is not None:
        changed = len([line for line in status.splitlines() if line.strip()])
        rows.append(("Git changes", str(changed) if changed else "clean"))
    return tuple(rows)


def _git(project: Path, *args: str) -> Optional[str]:
    try:
        done = subprocess.run(
            ["git", "-C", str(project), *args],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None
