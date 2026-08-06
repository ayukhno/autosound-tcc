"""Read the change the skill banked, instead of the change a model retyped (SCR-026).

`apply.propose` writes `<state-root>/<preset>/proposals/<v_NNN>.json` beside the snapshot: the
rows of the settings sheet, each with the value as the Arbiter keys it and the raw value beside it.
Before that file existed a front-end had to diff two snapshots and guess at intent — a `gain_db`
that moved could be a level-match trim or a banked decision — or trust the model to retype numbers
it had already computed, which is a transcription surface with no gate on it.

TCC is a consumer here, as everywhere: the skill writes this, TCC renders it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from autosound_tcc.core import config


def delta_path(version: str, preset: str, project_dir: Optional[Path] = None) -> Path:
    root = config.state_root() if project_dir is None else Path(project_dir) / "state"
    return Path(root) / preset / "proposals" / f"{version}.json"


def load_delta(version: str, preset: str, project_dir: Optional[Path] = None) -> Optional[dict]:
    """The banked delta for one version, or None.

    None is the ordinary case for any snapshot that was not made by `apply.propose` — a seeded
    baseline, a hand-written ledger, a project from before this existed. Absence is not an error.
    """
    if not version or not preset:
        return None
    try:
        data = json.loads(delta_path(version, preset, project_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("settings") is not None else None


def to_html(delta: dict) -> str:
    """The delta as the card the Arbiter keys from — one row per changed parameter.

    Deliberately the values the skill banked, verbatim: `was`/`value` were rendered by the skill's
    own formatter, the same one that prints the sheet in a terminal. Reformatting them here would
    reintroduce the second renderer this file exists to remove.
    """
    rows = []
    for row in delta.get("settings") or []:
        channel = str(row.get("channel", "?"))
        if row.get("added"):
            rows.append(f"<tr><td><b>{channel}</b></td><td>—</td><td>➕ new row</td></tr>")
            continue
        if row.get("removed"):
            rows.append(f"<tr><td><b>{channel}</b></td><td>—</td><td>➖ removed</td></tr>")
            continue
        rows.append(
            f"<tr><td><b>{channel}</b></td><td>{row.get('param', '?')}</td>"
            f"<td>{row.get('was', '—')} → <b>{row.get('value', '—')}</b></td></tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='3'><i>no hard-param changes</i></td></tr>")
    advisories = "".join(f"<br>⚠️ {item}" for item in delta.get("advisories") or [])
    head = f"<b>{delta.get('preset', '?')} · {delta.get('version', '?')}</b>"
    if delta.get("note"):
        head += f" — {delta['note']}"
    return (
        head
        + "<table cellpadding='4' cellspacing='0'>"
        + "<tr><th align='left'>Channel</th><th align='left'>Param</th>"
        + "<th align='left'>Old → New</th></tr>"
        + "".join(rows)
        + "</table>"
        + advisories
    )
