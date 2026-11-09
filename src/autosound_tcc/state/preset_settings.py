"""A version's `preset_settings` (#256, hub #324): the method's shape, read for TCC. Qt-free.

`FIELDS` is the method's `_PRESET_FIELDS` (`rew_tool/state/state.py`): the path, its kind, and what a
missing value reads as. A test compares the two, path by path, so the second copy cannot drift.
Only the words are TCC's (`ui/tcc/preset_tab.py`).

A field reads one of five ways: `stated`, the ledger says it; `default`, nothing said and the method
reads it as 0 dB or off; `unknown`, nothing said and no default exists (Dynamic Bass, SubXpander);
`dash`, nothing said of a field with no default (BT source, RTC curve, Conductor lamps); `unread`, a
value the method would refuse. A greyed default is the method's reading of silence, never a measured
fact, and the panel draws it so.

Two versions are compared by the same `FIELDS` defaults, as the method's `preset_settings_changes`
does, with one difference that the method's diff has no way to say: `unknown` against `off` moved
no fact (nobody knows the unknown one was on), so it is not «changed». `unknown` against `on` is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from autosound_tcc.core import app_log
from autosound_tcc.state import ledger_line

STATED, DEFAULT, UNKNOWN, DASH, UNREAD = "stated", "default", "unknown", "dash", "unread"

#: Path -> (kind, what a missing value reads as). The method's `_PRESET_FIELDS`, minus its English
#: label, which TCC says in the window's language.
FIELDS: dict[str, tuple[str, Any]] = {
    "input_gain_db": ("db", 0.0),
    "sources.main": ("db", 0.0),
    "sources.hec": ("db", 0.0),
    "sources.digital": ("db", 0.0),
    "fx.realcenter": ("switch", False),
    "fx.dynamic_bass": ("switch", None),
    "fx.subxpander": ("switch", None),
    "rtc.on": ("switch", False),
    "rtc.curve": ("curve", None),
    "bt.source": ("text", None),
    "bt.auto_switch": ("switch", False),
    "conductor.sub_lamps": ("count", None),
}
#: The only one a DSP that is not an Audiotec Fischer can have (the Arbiter, 2026-11-08).
_EVERY_DSP = ("input_gain_db",)
#: A status of the method's (`state.STATUSES`) that has not been entered in the DSP.
_STATUSES = ("candidate", "proposed", "applied", "measured")


def is_audiotec(vendor, name) -> bool:
    """A Helix-family DSP, told by vendor and name together: a profile may say only the vendor."""
    said = f"{vendor or ''} {name or ''}".lower()
    return "audiotec" in said or "helix" in said


def _number(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # an int too big for a float: JSON has no bound on one
        return False


def _valid(kind: str, value) -> bool:
    if kind == "db":
        return _number(value)
    if kind == "switch":
        return isinstance(value, bool)
    if kind == "text":
        return isinstance(value, str)
    if kind == "count":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    return isinstance(value, dict) and all(_number(v) for v in value.values())


@dataclass(frozen=True)
class Setting:
    path: str
    kind: str
    reading: str
    #: The value the panel says: stated, or the default; None for unknown, a dash, or unread.
    value: Any = None
    #: What the ledger holds where it could not be read, for the hover.
    held: str = ""

    @property
    def at_default(self) -> bool:
        return self.reading != STATED or self.value == FIELDS[self.path][1] or self.value == {}

    def changes_from(self, was: "Setting") -> bool:
        """This value differs from `was`, read by the defaults as the method's diff reads them."""
        return _changed(self, was)

    def unknown_against_off(self, was: "Setting") -> bool:
        """One side unknown, the other off: said on hover, marked as nothing. A value that could
        not be read is neither: its None is no reading of the switch."""
        return (self.kind == "switch" and UNREAD not in (self.reading, was.reading)
                and {self.value, was.value} == {None, False})


def _unread(path: str, kind: str, held) -> Setting:
    return Setting(path, kind, UNREAD, held=repr(held)[:200])


def _warn(path: str, value) -> None:
    app_log.logger().warning("preset_settings.%s is not what the method writes: %r", path, value)


def _read_one(path: str, kind: str, raw: dict) -> Setting:
    default = FIELDS[path][1]
    head, _, leg = path.partition(".")
    group = raw.get(head) if leg else raw
    if leg and group is not None and not isinstance(group, dict):
        _warn(head, group)
        return _unread(path, kind, group)
    value = group.get(leg or head) if isinstance(group, dict) else None
    if value is not None and not _valid(kind, value):
        _warn(path, value)
        return _unread(path, kind, value)
    if value in (None, "", {}):
        reading = DEFAULT if default is not None else (UNKNOWN if kind == "switch" else DASH)
        return Setting(path, kind, reading, value=default)
    return Setting(path, kind, STATED, value=value)


def _changed(now: Setting, was: Setting) -> bool:
    """`now` differs from `was`, read by the defaults as the method's diff reads them."""
    if UNREAD in (now.reading, was.reading):
        return False
    if now.value == was.value:
        return False
    if now.kind == "switch" and {now.value, was.value} == {None, False}:
        return False  # unknown against off moved no fact
    return True


@dataclass(frozen=True)
class PresetSettings:
    """What a version's `preset_settings` says, over the fields this DSP can have."""

    settings: tuple[Setting, ...]
    status: Optional[str] = None
    source: Optional[ledger_line.SourceFile] = None
    #: `source_file` was there and could not be read: not the same as «not read from a file».
    source_unread: bool = False
    audiotec: bool = False

    @property
    def any_stated(self) -> bool:
        """Something really set: a field at its default, or not stated, is no setting. A value the
        ledger holds and TCC cannot read is one: «nothing is set here» would be a claim about it."""
        return any(s.reading == UNREAD or (s.reading == STATED and not s.at_default) for s in self.settings)

    @property
    def waiting(self) -> bool:
        """The method's own status says these settings are not entered in the DSP yet."""
        return ledger_line.preset_waiting(self.status)

    @property
    def any_recorded(self) -> bool:
        """The ledger says anything at all here: a stated field, a value it could not read, a file."""
        return (any(s.reading in (STATED, UNREAD) for s in self.settings)
                or self.source is not None or self.source_unread)

    def by_path(self, path: str) -> Optional[Setting]:
        return next((s for s in self.settings if s.path == path), None)

    def changes_against(self, other: Optional["PresetSettings"]) -> dict[str, bool]:
        """`{path: differs}`, every field of ours, read against `other`; no `other` reads as none."""
        was = other if other is not None else read(None, self.audiotec)
        return {s.path: _changed(s, was.by_path(s.path) or _read_one(s.path, s.kind, {}))
                for s in self.settings}


def read(raw, audiotec: bool) -> PresetSettings:
    """`raw` is the ledger's `preset_settings`, or None. A value the method would refuse is `unread`,
    and a word in the log: never a crash. Every field of ours is on the answer."""
    whole_bad = raw is not None and not isinstance(raw, dict)
    if whole_bad:
        app_log.logger().warning("preset_settings is not an object: %r", raw)
    settings = tuple(_unread(path, kind, raw) if whole_bad else _read_one(path, kind, raw or {})
                     for path, (kind, _default) in FIELDS.items()
                     if audiotec or path in _EVERY_DSP)
    held = raw if isinstance(raw, dict) else {}
    status = held.get("status")
    if status is not None and status not in _STATUSES:
        _warn("status", status)
        status = None
    record = held.get("source_file")
    source = ledger_line.source_file(record)
    malformed = record is not None and (source is None or source.malformed)
    if malformed:
        _warn("source_file", record)
    return PresetSettings(settings, status=status, source=source, source_unread=record is not None and source is None,
                          audiotec=audiotec)
