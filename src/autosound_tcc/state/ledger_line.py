"""The register's two layouts, and the configurations saved from it (hub #195, #198).

**Two layouts, chosen per project by one file** (hub #195, the skill's reader contract):

* old — a line per preset: `state/<preset>/v_NNN.json`, `state/<preset>/HEAD`, `registry.json`;
* new — ONE line per project: `state/versions/v_NNN.json`, numbered once, and `state/slots.json`,
  which says what each slot (preset) holds, which one is active, and the history of each.

`state/slots.json` present → the new layout. The skill's own `PresetHistory` and `Registry` read
both, and TCC's snapshot loading goes through them; what is here is the handful of places TCC
looked at the old tree by path — which presets exist, which files to watch, which versions to
offer for comparison.

**Configurations** (hub #198, SKL-052): a `v_NNN` is a full DSP state proposed at the desk, and it
may never be kept. What the tuner saves into a preset of the device he saves under a name of his
own — `SQ-1`, `FULL-v1`, `SQ-2` — and that name is what he talks about and compares. `slots.json`
carries them:

    "configs": {code: {version, slot, purpose, saved, previous: {code, version} | null,
                       history: [{version, saved}]}}
    "slots":   {slot: {..., "dsp_preset": <the preset's number in the device>}}

"Previous" is the ANCESTRY, never the number below: SQ-2 (v_006) continues SQ-1 (v_003), with
v_004 and v_005 banked for another preset in between. The skill computes it when the name is saved
and stores it; TCC reads it and does not walk the chain. A version that was never saved under a
name has its `parent` for a previous.

Reading `slots.json` is the contract; WRITING it is the skill's alone (`state.py config save`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

SLOTS_FILE = "slots.json"
VERSIONS_DIR = "versions"
_VER = re.compile(r"^v_(\d+)$")


def _number(version: str) -> int:
    match = _VER.match(version or "")
    return int(match.group(1)) if match else -1


def is_project_line(root) -> bool:
    """The new layout: one version line per project, `slots.json` beside it."""
    return (Path(root) / SLOTS_FILE).is_file()


def slots(root) -> dict:
    """`slots.json` as written, or `{}` — never an error: a file being rewritten reads as empty."""
    try:
        data = json.loads((Path(root) / SLOTS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def presets(root) -> list[str]:
    """The presets (slots) that hold a version, in name order — on either layout."""
    root = Path(root)
    if is_project_line(root):
        entries = slots(root).get("slots") or {}
        return sorted(p for p, e in entries.items() if isinstance(e, dict) and e.get("version"))
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and not p.name.startswith(".") and any(p.glob("v_*.json")))


def version_path(root, preset: str, version: str) -> Path:
    root = Path(root)
    base = root / VERSIONS_DIR if is_project_line(root) else root / preset
    return base / f"{version}.json"


def versions(root, preset: str) -> list[str]:
    """The versions to offer beside `preset`'s, oldest first.

    On the project line that is EVERY version: a configuration's previous may have been banked
    for another slot, and the numbers are one sequence. On the old layout, the preset's own.
    """
    root = Path(root)
    folder = root / VERSIONS_DIR if is_project_line(root) else root / preset
    names = [p.stem for p in folder.glob("v_*.json") if _VER.match(p.stem)]
    return sorted(names, key=_number)


def proposals_dir(root, preset: str) -> Path:
    """Where the change sheet beside a proposal lives (SCR-026): `state/proposals/` on the
    project line, `state/<preset>/proposals/` before it."""
    root = Path(root)
    return (root if is_project_line(root) else root / preset) / "proposals"


def watched_files(root, preset_names: list[str]) -> list[str]:
    """Files rewritten in place when the register moves — which only a file watch catches."""
    root = Path(root)
    if is_project_line(root):
        return [str(root / SLOTS_FILE)]
    return [str(root / p / "HEAD") for p in preset_names]


def watched_dirs(root, preset_names: list[str]) -> list[str]:
    """Directories a new version appears in."""
    root = Path(root)
    if is_project_line(root):
        return [str(root), str(root / VERSIONS_DIR)]
    return [str(root)] + [str(root / p) for p in preset_names]


# ── configurations (hub #198) ──────────────────────────────────────────────────────────────────


def configs(root) -> dict:
    """Every saved configuration: `{code: record}`; empty on the old layout or before any save."""
    found = slots(root).get("configs") if is_project_line(root) else None
    return {c: r for c, r in found.items() if isinstance(r, dict)} if isinstance(found, dict) else {}


def dsp_preset(root, slot: str) -> Optional[str]:
    """The preset's number in the device, as the tuner gave it when he saved."""
    entry = (slots(root).get("slots") or {}).get(slot) if is_project_line(root) else None
    value = entry.get("dsp_preset") if isinstance(entry, dict) else None
    return str(value) if value not in (None, "") else None


def config_of(root, version: str) -> Optional[tuple[str, dict]]:
    """The configuration that stands at `version` now, if one does."""
    standing = [(c, r) for c, r in configs(root).items() if r.get("version") == version]
    return max(standing, key=lambda cr: cr[1].get("saved") or "") if standing else None


def saved_names(root) -> dict[str, list[str]]:
    """`{version: [code, …]}` — every name each version was ever saved under."""
    out: dict[str, list[str]] = {}
    for code, rec in configs(root).items():
        for entry in rec.get("history") or [{"version": rec.get("version")}]:
            version = entry.get("version") if isinstance(entry, dict) else None
            if version and code not in out.setdefault(version, []):
                out[version].append(code)
    return out


def parent_of(root, preset: str, version: str) -> Optional[str]:
    try:
        data = json.loads(version_path(root, preset, version).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    parent = data.get("parent") if isinstance(data, dict) else None
    return parent if isinstance(parent, str) and _VER.match(parent) else None


def previous_of(root, preset: str, version: str) -> Optional[str]:
    """What «порівняти з попередньою» compares `version` with.

    A saved configuration: its stored `previous` (SQ-2 → SQ-1's v_003). Any other version: its
    `parent`. The old layout has neither, so there it is the number below in the same preset.
    """
    if not version:
        return None
    standing = config_of(root, version)
    if standing is not None:
        previous = standing[1].get("previous")
        found = previous.get("version") if isinstance(previous, dict) else None
        return found if isinstance(found, str) and _VER.match(found) else None
    if is_project_line(root):
        return parent_of(root, preset, version)
    below = [v for v in versions(root, preset) if 0 <= _number(v) < _number(version)]
    return below[-1] if below else None


def label(root, version: str, names: Optional[dict[str, list[str]]] = None) -> str:
    """`v_006 · SQ-2` — the number, and the names it was saved under."""
    names = saved_names(root) if names is None else names
    codes = names.get(version) or []
    return f"{version} · {', '.join(codes)}" if codes else version
