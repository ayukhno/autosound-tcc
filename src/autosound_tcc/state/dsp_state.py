"""Typed model of the DSP-state ledger, translated from its raw JSON schema.

The source of truth is the vendored `state/state.py` `PresetHistory`: one JSON
snapshot per version under ``<root>/<preset>/v_NNN.json``. `root` is the USER's
own project folder (tier-1 install-specific data, brief §3a) — never anything
inside the vendored skill repo — so the caller supplies it (e.g. from a future
settings screen).

`DspSnapshot.from_dict` works on a raw dict alone, so the UI/tests can consume a
snapshot without the submodule present; only `load_snapshot` (which reads from
disk via `PresetHistory`) needs the vendored code.

Raw per-channel schema: {helix_ch, hp, lp, gain_db, ta_ms, polarity, eq_ptr,
status}. `hp`/`lp` are crossover legs — either None / "OFF" (disabled) or
{f, type, slope}. `ta_ms` is time-alignment delay in milliseconds (canonical).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class CrossoverLeg:
    """One crossover leg (high-pass or low-pass), or disabled."""

    freq_hz: Optional[float] = None
    type: Optional[str] = None
    slope: Optional[Any] = None
    enabled: bool = True

    @classmethod
    def from_raw(cls, raw: Any) -> "CrossoverLeg":
        # A leg is null / "OFF" (disabled) or a {f, type, slope} dict.
        if raw is None or raw == "OFF":
            return cls(enabled=False)
        if not isinstance(raw, dict) or "f" not in raw:
            raise ValueError(f"crossover leg must be null/'OFF' or {{f,...}}, got {raw!r}")
        return cls(
            freq_hz=raw["f"],
            type=raw.get("type"),
            slope=raw.get("slope"),
            enabled=True,
        )


@dataclass(frozen=True)
class ChannelState:
    """One DSP output channel's settings."""

    name: str
    helix_ch: Optional[Any] = None
    hp: CrossoverLeg = field(default_factory=CrossoverLeg)
    lp: CrossoverLeg = field(default_factory=CrossoverLeg)
    gain_db: float = 0.0
    ta_ms: float = 0.0
    polarity: str = "NORM"
    eq_ptr: Optional[Any] = None
    status: str = "proposed"

    @classmethod
    def from_raw(cls, name: str, raw: dict) -> "ChannelState":
        return cls(
            name=name,
            helix_ch=raw.get("helix_ch"),
            hp=CrossoverLeg.from_raw(raw.get("hp")),
            lp=CrossoverLeg.from_raw(raw.get("lp")),
            gain_db=raw["gain_db"],
            ta_ms=raw["ta_ms"],
            polarity=raw.get("polarity", "NORM"),
            eq_ptr=raw.get("eq_ptr"),
            status=raw.get("status", "proposed"),
        )


@dataclass(frozen=True)
class DspSnapshot:
    """A whole DSP preset snapshot — the read-only view the UI displays."""

    preset: str
    sample_rate: float
    channels: dict[str, ChannelState]
    version: Optional[str] = None
    note: Optional[str] = None
    created: Optional[str] = None

    @classmethod
    def from_dict(cls, raw: dict) -> "DspSnapshot":
        chans = raw.get("channels", {})
        return cls(
            preset=raw.get("preset", ""),
            sample_rate=raw["sample_rate"],
            channels={name: ChannelState.from_raw(name, ch) for name, ch in chans.items()},
            version=raw.get("version"),
            note=raw.get("note"),
            created=raw.get("created"),
        )

    def samples_for(self, ms: float) -> int:
        """DSP samples for a delay in ms at this snapshot's sample rate.

        Derived, never stored (entering 96 kHz samples into a 48 kHz DSP would
        double the physical delay). Mirrors the vendored `state.samples_for`.
        """
        return int(round(ms * self.sample_rate / 1000.0))


def load_snapshot(root: str, preset: str, version: Optional[str] = None) -> DspSnapshot:
    """Read a snapshot from disk via the vendored `PresetHistory`.

    `version=None` loads the current HEAD. Requires the `rew_tool` submodule.
    """
    from autosound_tcc.core import vendor_loader

    vstate = vendor_loader.load_dsp_state()
    history = vstate.PresetHistory(root, preset)
    raw = history.load(version)
    return DspSnapshot.from_dict(raw)
