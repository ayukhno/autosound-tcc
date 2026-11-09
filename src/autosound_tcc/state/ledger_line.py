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


#: `_entry`'s answers, one slot per version file: `{path: ((path, st_mtime_ns, st_size), Entry)}`
#: (#172, #203, #251). A slot is replaced when its file changes: a version may gain its file
#: record after it was banked, so a version file is not assumed to be written once.
_ENTRIES: dict = {}


class SavedFile(NamedTuple):
    """A preset file saved from the DSP, as a version records it (#251): the file's name, its md5
    (what is recorded, short or full), when it was saved and when that was recorded, as «DD.MM.YYYY
    HH:MM». A field the record does not give is None."""

    name: str
    md5: Optional[str]
    saved: Optional[str]
    recorded: Optional[str]


class Entry(NamedTuple):
    """What a version's own file says of it: the preset it was proposed for, the day it was made,
    whether every channel row is entered, and the saved files it records."""

    preset: Optional[str] = None
    day: Optional[str] = None
    entered: bool = False
    files: tuple[SavedFile, ...] = ()


#: A status past `proposed`: the row was entered (`applied`), and may since have been measured.
_ENTERED = ("applied", "measured")
#: Top-level dicts of a version that are not channel tiers.
_NOT_TIERS = ("channels", "preset_settings", "provenance", "roles")
_MD5 = re.compile(r"^[0-9a-fA-F]{6,32}$")
_MD5_IN_TEXT = re.compile(r"\(md5\s+([0-9a-fA-F]{6,32})")
_FILE_IN_TEXT = re.compile(r"^(.*?\.[A-Za-z0-9]{2,6})(?=\s*\(md5\b|\s|$)")


def _day(created) -> Optional[str]:
    """`created` as the local day, `DD.MM` (#203); None when it is not a readable timestamp."""
    if not isinstance(created, str):
        return None
    try:
        moment = datetime.fromisoformat(created)
        if moment.tzinfo is not None:
            # `OverflowError` at the year-1/9999 edges, `OSError` on Windows before 1970: a day
            # that cannot be placed is no day, not a project that fails to load (#203).
            moment = moment.astimezone()
    except (ValueError, OverflowError, OSError):
        return None
    return moment.strftime("%d.%m")


def _stamp(value) -> Optional[str]:
    """An ISO timestamp as «DD.MM.YYYY HH:MM», local where it says its zone; None if it is none."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is not None:
            moment = moment.astimezone()
    except (ValueError, OverflowError, OSError):
        return None
    return moment.strftime("%d.%m.%Y %H:%M")


def _leaf(path: str) -> str:
    """A file's name without its folders: a hover shows no path, a home path least of all."""
    return re.split(r"[\\/]", path.strip())[-1]


def _saved_file(record, created) -> Optional[SavedFile]:
    """One saved-file record in either shape, or None where none is usable.

    `provenance.file` is a sentence on today's ledgers — `presets/a.pct6 (md5 ee627ad6…) decoded
    read-only` — and the method's `source_file` (3.3) is an object of name, path, md5, saved,
    read_at, compared. A file compared and found different is not one this version was checked
    against, and a field absent stays absent."""
    if isinstance(record, str):
        md5 = _MD5_IN_TEXT.search(record)
        cut = record[:md5.start()] if md5 else record
        found = _FILE_IN_TEXT.match(cut) if not md5 else None
        name = _leaf(found.group(1) if found else cut) if (md5 or found) else ""
        return SavedFile(name, md5.group(1).lower() if md5 else None, None,
                         _stamp(created)) if name else None
    if not isinstance(record, dict):
        return None
    compared = record.get("compared")
    if compared and compared != "no difference":
        return None
    name = record.get("name") or (_leaf(record["path"]) if isinstance(record.get("path"), str) else "")
    if not isinstance(name, str) or not name:
        return None
    md5 = record.get("md5")
    return SavedFile(_leaf(name), md5.lower() if isinstance(md5, str) and _MD5.match(md5) else None,
                     _stamp(record.get("saved")), _stamp(record.get("read_at")) or _stamp(created))


def _saved_files(data: dict) -> tuple[SavedFile, ...]:
    """The saved files a version records: `provenance.file`, and `preset_settings.source_file`."""
    created = data.get("created")
    provenance = data.get("provenance")
    settings = data.get("preset_settings")
    found = []
    if isinstance(provenance, dict) and provenance.get("verified_by_file") is not False:
        found.append(_saved_file(provenance.get("file"), created))
    if isinstance(settings, dict):
        found.append(_saved_file(settings.get("source_file"), created))
    return tuple(f for f in found if f is not None)


def _entered(data: dict) -> bool:
    """Every channel row entered; a version with no channels is not. Rows of the other tiers count
    where they state a status: `attest` flips every tier, and the schema's virtual rows carry none."""
    rows = data.get("channels")
    if not isinstance(rows, dict) or not rows:
        return False
    tiers = [t for k, t in data.items() if k not in _NOT_TIERS and isinstance(t, dict)]
    stated = [r for t in tiers for r in t.values() if isinstance(r, dict) and "status" in r]
    return all(isinstance(r, dict) and r.get("status") in _ENTERED for r in [*rows.values(), *stated])


def _entry(path: Path) -> Entry:
    """What a version's own file says of it, each field empty where the file does not say, or
    cannot be read.

    Remembered per file by its path, mtime and size (#172): every reload asks this of every
    version, on the GUI thread, and each one is a whole DSP state read for a few fields."""
    try:
        stat = path.stat()
    except OSError:
        return Entry()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    held = _ENTRIES.get(key[0])
    if held is None or held[0] != key:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Entry()
        if not isinstance(data, dict):
            data = {}
        preset = data.get("preset")
        found = Entry(preset if isinstance(preset, str) and preset else None,
                      _day(data.get("created")), _entered(data), _saved_files(data))
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


def same_content(one: Optional[str], other: Optional[str]) -> bool:
    """Two md5s of the same content: equal, or one the short form of the other (a ledger's text
    keeps eight characters of it)."""
    return bool(one) and bool(other) and (one.startswith(other) or other.startswith(one))


def all_saved_files(root, preset: str) -> list[SavedFile]:
    """Every saved file any version records, on either layout: what «the same content» is found in."""
    root = Path(root)
    if is_project_line(root):
        return [f for v in versions(root, preset) for f in _entry(version_path(root, preset, v)).files]
    return [f for p in sorted({*presets(root), preset}) for v in versions(root, p)
            for f in _entry(version_path(root, p, v)).files]


def checked_files(root, preset: str, version: str,
                  every: Optional[list[SavedFile]] = None) -> tuple[SavedFile, ...]:
    """The files that make `version` «checked in the DSP» (#251), its own first and then every
    other one recorded with the same md5; empty when it is not checked. Not checked: a row not
    entered, no file on record, or two records of different content.

    `every` is `all_saved_files`' answer, passed in as a list reads it once."""
    entry = _entry(version_path(root, preset, version))
    own = list(dict.fromkeys(entry.files))
    if not entry.entered or not own:
        return ()
    md5s = [f.md5 for f in own if f.md5]
    if not all(same_content(md5, md5s[0]) for md5 in md5s):
        return ()
    others = all_saved_files(root, preset) if every is None else every
    if not md5s:
        return tuple(own)
    held = {(f.name, f.md5) for f in own}
    for file in others:
        if same_content(file.md5, md5s[0]) and (file.name, file.md5) not in held:
            own.append(file)
            held.add((file.name, file.md5))
    return tuple(own)


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
