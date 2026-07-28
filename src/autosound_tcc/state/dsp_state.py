"""Generic, profile-driven view of a project's DSP-state ledger.

The ledger's source of truth is the vendored `state/state.py` `PresetHistory`: one JSON
snapshot per version under ``<root>/<preset>/v_NNN.json``. Its schema only strictly requires
top-level `channels` (validated) — anything else, including `virtual_channels` or any other
group-shaped key, is unvalidated passthrough. This module reads that passthrough generically,
driven by a DSP capability profile (`core.dsp_profile`) rather than a fixed dataclass shape, so
the same code renders a Helix (virtual_channels + physical_outputs) and a MUSWAY (inputs +
physical_outputs, no virtual tier at all) without per-DSP code.

Ledger-key convention (by profile group id):
    * `physical_outputs` -> the ledger's required `channels` key (unchanged, existing convention).
    * any other declared group id (e.g. `virtual_channels`, `inputs`) -> a same-named top-level
      key in the ledger JSON, a dict of row-name -> field-dict. Absent = that group has no rows
      yet in this project (not an error — the group still renders, just empty).

`ProjectView.from_dict` works on a raw dict + a loaded profile alone, so the UI/tests can consume
a view without the submodule present; only `load_project_view` (which reads from disk via
`PresetHistory`) needs the vendored code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

_GAIN_RE = re.compile(r"^[+-][\d.]+$")
_Q_RE = re.compile(r"^[Qq]([\d.]+)$")
_NUM_RE = re.compile(r"^[\d.]+$")


@dataclass(frozen=True)
class EqBand:
    """One parametric-EQ band, parsed from a ledger EQ string (e.g. `"PK 1000 -9 Q2"`,
    `"LS 150 +2.5 Q0.71"`). Gain/Q are optional — an all-pass band (e.g. `"APF2 2177 Q1.5"`)
    has no gain. Any leftover token (e.g. `"(L only)"`) is kept as a free-text note rather than
    dropped or raising, since the ledger already carries these informally.
    """

    type: str
    freq_hz: float
    gain_db: Optional[float] = None
    q: Optional[float] = None
    note: Optional[str] = None

    @classmethod
    def from_string(cls, raw: str) -> "EqBand":
        tokens = raw.split()
        if not tokens:
            raise ValueError("empty EQ band string")
        band_type, rest = tokens[0], tokens[1:]
        freq_hz: Optional[float] = None
        gain_db: Optional[float] = None
        q: Optional[float] = None
        notes: list[str] = []
        for tok in rest:
            if freq_hz is None and _NUM_RE.match(tok):
                freq_hz = float(tok)
            elif _GAIN_RE.match(tok):
                gain_db = float(tok)
            elif _Q_RE.match(tok):
                q = float(_Q_RE.match(tok).group(1))
            else:
                notes.append(tok)
        if freq_hz is None:
            raise ValueError(f"could not parse a frequency from EQ band {raw!r}")
        return cls(type=band_type, freq_hz=freq_hz, gain_db=gain_db, q=q,
                   note=" ".join(notes) or None)


def parse_eq_bands(raw: Any) -> tuple[EqBand, ...]:
    """Parse a ledger `eq` field (a list of band strings) into `EqBand`s. Anything else
    (missing, None, not a list) yields an empty tuple rather than raising — EQ is optional."""
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(EqBand.from_string(s) for s in raw)


@dataclass(frozen=True)
class CrossoverLeg:
    """One crossover leg (high-pass or low-pass), or disabled."""

    freq_hz: Optional[float] = None
    type: Optional[str] = None
    slope: Optional[Any] = None
    enabled: bool = True

    @classmethod
    def from_raw(cls, raw: Any) -> "CrossoverLeg":
        if raw is None or raw == "OFF":
            return cls(enabled=False)
        if not isinstance(raw, dict) or "f" not in raw:
            raise ValueError(f"crossover leg must be null/'OFF' or {{f,...}}, got {raw!r}")
        return cls(freq_hz=raw["f"], type=raw.get("type"), slope=raw.get("slope"), enabled=True)

    @property
    def label(self) -> str:
        """Compact display string: corner freq, a space, then the filter type + its ORDER, e.g.
        "620 LR6", "88 BW6", or "OFF". The ledger stores the slope in dB/octave (LR36); we show the
        order (LR36 -> LR6, since order = slope / 6) with a space, matching how the user reads it
        off the DSP (user pref 2026-07-26, replacing the earlier space-less slope form "620LR36")."""
        if not self.enabled or self.freq_hz is None:
            return "OFF"
        freq = f"{self.freq_hz:g}"
        if self.type and self.slope is not None:
            return f"{freq} {self.type}{self._order()}"
        if self.type:
            return f"{freq} {self.type}"
        return freq

    def _order(self):
        """Filter order from the ledger's dB/octave slope (LR36 -> 6, BW24 -> 4). A non-numeric or
        non-multiple-of-6 slope falls through to the raw value so nothing is silently dropped."""
        try:
            order = float(self.slope) / 6
        except (TypeError, ValueError):
            return self.slope
        return int(order) if order == int(order) else f"{order:g}"


def _field_label(field_name: str, raw_value: Any) -> Optional[str]:
    """Render one declared field as a "label: value" chip, or None if genuinely absent.

    Generic by construction: a group declares WHICH fields matter (`profile.groups[i].fields`);
    this only decides HOW to print a value once we know it's a crossover leg vs. a plain scalar
    vs. an EQ-band list. No per-DSP special-casing.
    """
    if raw_value is None:
        return None
    if field_name in ("hp", "lp"):
        leg = CrossoverLeg.from_raw(raw_value)
        return f"{field_name.upper()}: {leg.label}"
    if field_name == "eq":
        n = len(raw_value) if isinstance(raw_value, (list, tuple)) else 0
        return f"EQ: {n} band{'s' if n != 1 else ''}" if n else None
    if field_name in ("gain_db",):
        return f"Gain: {raw_value:+.1f} dB" if isinstance(raw_value, (int, float)) else None
    if field_name in ("delay_ms", "ta_ms"):
        return f"Delay: {raw_value:g} ms" if isinstance(raw_value, (int, float)) else None
    if field_name == "phase_deg":
        return f"Phase: {raw_value:g}°" if isinstance(raw_value, (int, float)) else None
    if field_name == "polarity":
        return f"Pol: {raw_value}"
    if field_name == "mute":
        return "MUTE" if raw_value else None
    if field_name == "eq_bypass":
        return "EQ bypass" if raw_value else None
    return f"{field_name}: {raw_value}"


@dataclass(frozen=True)
class GroupRow:
    """One row (channel/input/whatever) inside a profile-declared group."""

    id: str
    name: str
    raw: dict
    order: Optional[int] = None
    slot: Optional[str] = None
    descr: Optional[str] = None

    @property
    def tag(self) -> Optional[str]:
        """Short feature-tag label shown as a chip next to the channel name (e.g. RearRC, SubRC,
        RC -- the last for VFC's RealCenter toggle, an unrelated feature that happens to share the
        "RC" abbreviation with the Remote-Control-driven RearRC/SubRC tags; see `tag_value`)."""
        return self.raw.get("tag")

    @property
    def tag_value(self) -> Optional[str]:
        """The tag's configured value for this project (e.g. "3/4" for RearRC, "-4dB" for SubRC,
        "ON"/"OFF" for VFC's RC) -- shown alongside the tag label so the chip reads as a fact,
        not just a feature name (user request 2026-07-28). None = tag shown bare, same as before
        this field existed."""
        return self.raw.get("tag_value")

    @property
    def muted(self) -> bool:
        return bool(self.raw.get("mute"))

    @property
    def off(self) -> bool:
        return bool(self.raw.get("off"))

    @property
    def hidden(self) -> bool:
        """A virtual-channel slot the skill's intake found no physical driver assigned to (e.g.
        an unused rear-fill slot) -- written by the skill, not inferred here (see
        docs/SKILL-CHANGE-REQUESTS.md SCR-003). Not retroactive: ledgers captured before that skill
        change simply have no `hidden` key and every row still renders."""
        return bool(self.raw.get("hidden"))

    def params(self, fields: tuple[str, ...]) -> list[str]:
        """Rendered "label: value" chips for exactly this group's declared fields — a field this
        row's raw dict doesn't have (or that's null) is silently skipped, never shown as an error;
        that's what lets MUSWAY's `inputs` rows (no hp/lp at all) sit next to Helix's
        `physical_outputs` rows (hp/lp/gain/delay/pol/eq) with the same rendering code."""
        out = []
        for f in fields:
            label = _field_label(f, self.raw.get(f))
            if label is not None:
                out.append(label)
        return out

    def eq_count(self) -> int:
        eq = self.raw.get("eq")
        return len(eq) if isinstance(eq, (list, tuple)) else 0

    def eq_bands(self) -> tuple[EqBand, ...]:
        return parse_eq_bands(self.raw.get("eq"))


@dataclass(frozen=True)
class ProfileGroup:
    """One DSP-profile-declared tier (e.g. virtual_channels, physical_outputs, inputs),
    populated with this project's actual rows for that tier."""

    id: str
    label: str
    fields: tuple[str, ...]
    rows: tuple[GroupRow, ...] = ()
    max_count: Optional[int] = None

    def rows_ordered(self) -> list[GroupRow]:
        return sorted(self.rows, key=lambda r: (r.order if r.order is not None else 99, r.name))


@dataclass(frozen=True)
class ParamSection:
    """One extra flat key/value collapsible section in the left panel, beyond the DSP feature-
    toggle PARAMS section -- e.g. car/setup + measurement params, car body/chassis params, future
    amp-gain/second-processor/player sections (item 2, 2026-07-27). Sourced from project-level
    config (`project_profile.json`, see core.config.project_profile_path), not the per-version
    ledger -- these facts don't change between presets/DSP-tune versions."""

    id: str
    label: str
    params: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ProjectView:
    """A whole project's DSP state, shaped by its profile — the read-only view the UI displays."""

    preset: str
    sample_rate: Optional[float]
    groups: tuple[ProfileGroup, ...]
    version: Optional[str] = None
    note: Optional[str] = None
    target: Optional[str] = None
    features: tuple[tuple[str, str], ...] = ()
    slot_label: Optional[str] = None
    save: Optional[str] = None
    param_sections: tuple[ParamSection, ...] = ()

    @classmethod
    def from_dict(
        cls, raw: dict, profile: dict, param_sections: tuple[ParamSection, ...] = ()
    ) -> "ProjectView":
        prof = profile.get("dsp_profile", profile)
        groups = []
        for g in prof.get("groups", []):
            gid = g["id"]
            # convention: physical_outputs maps to the ledger's required `channels` key;
            # every other group id maps to a same-named top-level key (absent -> no rows yet).
            row_source = raw.get("channels", {}) if gid == "physical_outputs" else raw.get(gid, {})
            rows = tuple(
                GroupRow(id=name, name=name, raw=row_raw, order=row_raw.get("order"),
                         slot=row_raw.get("slot"), descr=row_raw.get("descr"))
                for name, row_raw in (row_source or {}).items()
            )
            groups.append(ProfileGroup(id=gid, label=g.get("label", gid),
                                        fields=tuple(g.get("fields", ())), rows=rows,
                                        max_count=g.get("max_count")))
        features = tuple(
            (str(k), str(v)) for k, v in raw.get("features", []) if k is not None
        )
        return cls(
            preset=raw.get("preset", ""),
            sample_rate=raw.get("sample_rate"),
            groups=tuple(groups),
            version=raw.get("version"),
            note=raw.get("note"),
            target=raw.get("target"),
            features=features,
            slot_label=raw.get("slot_label"),
            save=raw.get("save"),
            param_sections=param_sections,
        )


def load_param_sections(project_dir_: Optional[Any] = None) -> tuple[ParamSection, ...]:
    """Read `project_profile.json` (see `core.config.project_profile_path`), if present. Absent
    file or missing `param_sections` key -> no extra sections, not an error (same convention as
    the rest of this module). `project_dir_`, if given, overrides the configured project
    directory (for tests)."""
    import json

    from autosound_tcc.core import config

    path = config.project_profile_path(project_dir_)
    if not path.is_file():
        return ()
    data = json.loads(path.read_text())
    sections = []
    for entry in data.get("param_sections", []):
        params = tuple((str(k), str(v)) for k, v in entry.get("params", []))
        sections.append(ParamSection(id=entry["id"], label=entry.get("label", entry["id"]), params=params))
    return tuple(sections)


def load_project_view(root: str, preset: str, profile: dict, version: Optional[str] = None) -> ProjectView:
    """Read a ledger snapshot from disk via the vendored `PresetHistory` and shape it per `profile`.

    `version=None` loads the current HEAD. Requires the `rew_tool` submodule.
    """
    from autosound_tcc.core import vendor_loader

    vstate = vendor_loader.load_dsp_state()
    history = vstate.PresetHistory(root, preset)
    raw = history.load(version)
    param_sections = load_param_sections()
    return ProjectView.from_dict(raw, profile, param_sections=param_sections)
