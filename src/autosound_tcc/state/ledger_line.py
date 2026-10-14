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
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional

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


#: `_entry`'s answers, one slot per version file: `{path: ((path, st_mtime_ns, st_size),
#: (preset, day))}` (#172, #203). A slot is replaced when its file changes — and a version file is
#: written once.
_ENTRIES: dict = {}


def _day(created) -> Optional[str]:
    """`created` as the local day, `DD.MM` (#203); None when it is not a readable timestamp."""
    if not isinstance(created, str):
        return None
    try:
        moment = datetime.fromisoformat(created)
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%d.%m")


def _entry(path: Path) -> tuple[Optional[str], Optional[str]]:
    """What a version's own file says of it: the preset it was proposed for and the day it was
    made (`created`), each None where the file does not say, or cannot be read.

    Remembered per file by its path, mtime and size (#172): every reload asks this of every
    version, on the GUI thread, and each one is a whole DSP state read for two fields."""
    try:
        stat = path.stat()
    except OSError:
        return None, None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    held = _ENTRIES.get(key[0])
    if held is None or held[0] != key:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, None
        preset = data.get("preset") if isinstance(data, dict) else None
        found = (preset if isinstance(preset, str) and preset else None,
                 _day(data.get("created")) if isinstance(data, dict) else None)
        held = _ENTRIES[key[0]] = (key, found)
    return held[1]


def _made_for(root, version: str) -> Optional[str]:
    """The preset a project-line version was proposed for, as its own file says."""
    return _entry(version_path(root, "", version))[0]


def created_days(root, preset: str, versions: list[str]) -> dict[str, str]:
    """`{version: "DD.MM"}` — the day each of `versions` was made, from its own file (#203).

    A version whose file has no readable `created` is left out, and so is labelled with its number
    alone. Read through `_entry`, the same reader as the preset a version was made for."""
    days = {}
    for version in versions:
        day = _entry(version_path(root, preset, version))[1]
        if day:
            days[version] = day
    return days


def compare_groups(root, preset: str, current: Optional[str]) -> list[tuple[str, list[str]]]:
    """What «порівняти з» offers, newest first: `preset`'s own versions, then each other preset's
    (the Arbiter, 2026-09-25, finding 66: «порівнювати не тільки v_xxx в поточній конфігурації,
    але і з іншими конфігураціями»).

    `current` stays IN the own group now (tcc#103, finding 112) — it used to be filtered out here
    on the reasoning that a version is not compared with itself, which silently dropped the row
    «4.C-cut»'s versions were supposed to open on and read as "where did my versions go". Turning
    it into a disabled, greyed «v_002 — зараз» row is `detail_pane.fill_compare_combo`'s job, not
    this one's — it still needs `current` to know which row that is.

    On the project line `current`'s own file can name a DIFFERENT preset than the one it is
    current for — a configuration may continue another preset's (`previous_of`'s own docstring).
    It still goes in THIS preset's group, the only one `fill_compare_combo` greys, and in no
    other: under another preset's heading it would be a plain, selectable row with nothing
    marking it as the version already on screen, and without it this preset's heading could
    stand over an empty list.

    The old layout numbers each preset on its own, so another preset's `v_002` is a different
    state from this one's — the caller keys it with its preset — and is never `current`, so
    nothing is dropped there. The project line numbers once, and each version's file names the
    preset it was made for; one never made for any stays with this preset, where it was offered
    before.
    """
    root = Path(root)
    if is_project_line(root):
        every = list(reversed(versions(root, preset)))
        made_for = {v: _made_for(root, v) for v in every}
        groups = [(preset, [v for v in every if v == current or made_for[v] in (None, preset)])]
        # Named from the versions other than `current`, so a preset whose only version is the
        # one open now gets no heading over nothing.
        for other in sorted({made_for[v] for v in every
                             if v != current and made_for[v] not in (None, preset)}):
            groups.append((other, [v for v in every if made_for[v] == other and v != current]))
        return groups
    groups = [(preset, list(reversed(versions(root, preset))))]
    for other in presets(root):
        theirs = list(reversed(versions(root, other))) if other != preset else []
        if theirs:
            groups.append((other, theirs))
    return groups


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


def label(root, version: str, names: Optional[dict[str, list[str]]] = None,
          days: Optional[dict[str, str]] = None) -> str:
    """`v_006 · 22.09 · SQ-2` — the number, the day it was made (#203), and the names it was saved
    under. `days` is `created_days`' answer, passed in as `names` is, so a list reads each once;
    a version with no day, or no name, has none in its text."""
    names = saved_names(root) if names is None else names
    codes = names.get(version) or []
    day = (days or {}).get(version)
    return " · ".join([version] + ([day] if day else []) + ([", ".join(codes)] if codes else []))


class CompareOffer(NamedTuple):
    """What «порівняти з» offers, as plain data (#179: decided here, out of the window)."""

    own: list[str]
    default: Optional[str]
    labels: dict[str, str]
    others: list[tuple[str, list[tuple[str, str]]]]


def compare_offer(root, preset: str, current: Optional[str]) -> CompareOffer:
    """`compare_groups` named for the list: `preset`'s own versions with their `label`s, each other
    preset's as `(key, label)` keyed `SQ/v_004` (finding 66), and selected by default the PREVIOUS
    one (the Arbiter, 2026-09-23: «за замовчанням попередній») — `previous_of`, the ancestry. On
    the project line a configuration may continue another preset's, and its previous is then
    selected in that preset's group; with nothing before `current`, nothing is."""
    groups = compare_groups(root, preset, current)
    own = groups[0][1] if groups else []
    names = saved_names(root)
    own_days = created_days(root, preset, own)
    labels = {v: label(root, v, names, own_days) for v in own}
    others = []
    for p, theirs in groups[1:]:
        days = created_days(root, p, theirs)
        others.append((p, [(f"{p}/{v}", label(root, v, names, days)) for v in theirs]))
    previous = previous_of(root, preset, current)
    if previous in own:
        default = previous
    else:
        default = next((key for _p, items in others for key, _label in items
                        if previous and key.split("/", 1)[1] == previous), None)
    return CompareOffer(own, default, labels, others)
