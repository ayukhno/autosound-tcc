"""Read the skill-owned `project.json` into the shapes the left panel's sections render.

TCC is a schema *consumer* here too (same posture as `process_view.py`/`measurement_view.py`):
the skill's `rew_tool/project.py` owns `project.json` and is the only writer. This module turns
that file into flat `(label, value)` rows for two sections that used to be static placeholders
(SKILL-CHANGE-REQUESTS.md SCR-015/016):

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
`state/dsp_state.py::load_param_sections` — a brand-new project reads as "nothing yet", not an
error.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from autosound_tcc.core import config


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


def load_open_questions(project_dir_: Optional[Path] = None) -> tuple[str, ...]:
    """Unresolved intake facts (dotted paths) for onboarding TODO chips — `project.json`'s
    `_open_questions`, the same convention `dsp_profile.json` and the skill's own
    `rew_tool/project.py::open_questions` use."""
    return tuple(str(q) for q in (_load(project_dir_).get("_open_questions") or []))
