"""Mostly-read-only wrapper over the vendored REW HTTP API (`rew_api.py`).

Exposes the reading half of `rew_api`: measurements, curves (FR, group delay,
impulse response, distortion), and REW's own internal filter / equaliser /
target-response model. The write-capable functions (`set_filters`,
`set_equaliser`, `measurement_command`, and the phase/smoothing commands that
create derived measurements) are deliberately NOT surfaced here, so the
read-only guarantee is structural rather than a convention someone must
remember. See the project brief §11 (safety gates).

ONE narrow, user-approved exception: `rename_measurement` (2026-07-27, item 9 --
the capture-order auto-naming feature). Renaming a measurement's title doesn't
touch DSP state or REW's filter/target model, only REW's own measurement list,
so it was judged a much smaller blast radius than the write methods above --
still, don't add more write methods here without the same explicit sign-off.

REW must be running locally; `rew_api` talks to http://localhost:4735.
"""

from __future__ import annotations

from types import ModuleType


class RewBridge:
    """Thin read-only facade over `rew_api`.

    The vendored module is loaded lazily on first use so importing this module
    (e.g. for type hints or tests) never requires the submodule to be present.
    """

    def __init__(self, api: ModuleType | None = None) -> None:
        self._api = api

    @property
    def api(self) -> ModuleType:
        if self._api is None:
            from autosound_tcc.core import vendor_loader

            self._api = vendor_loader.load_rew_api()
        return self._api

    @property
    def base_url(self) -> str:
        return self.api.BASE_URL

    def is_reachable(self) -> bool:
        """Cheap connectivity probe for the System-params REW-online dot -- same call
        `_RewReadWorker` already makes, just discarding the result. Call off the GUI thread."""
        try:
            self.measurements()
        except Exception:  # noqa: BLE001 — any failure (REW closed, wrong port, ...) means offline
            return False
        return True

    # -- measurements --
    def measurements(self) -> dict:
        """All measurements, keyed by REW's (unstable) ordinal id."""
        return self.api.get_measurements()

    def measurement(self, mid) -> dict:
        return self.api.get_measurement(mid)

    def find_id(self, name: str, *, exact: bool = True):
        """Resolve a measurement's current ordinal id by title. Raises if
        missing/ambiguous — never resolve via a cached index (REW reshuffles)."""
        return self.api.find_measurement_id(name, exact=exact)

    def by_name(self, name: str, *, exact: bool = True):
        """(id, measurement_dict) resolved by title right now."""
        return self.api.get_measurement_by_name(name, exact=exact)

    def rename_measurement(self, mid, title: str) -> dict:
        """The one write exception -- see module docstring. UNVERIFIED against a live REW
        instance; see `rew_api.rename_measurement`'s docstring for the caveat and fallback."""
        return self.api.rename_measurement(mid, title)

    # -- curves --
    def frequency_response(self, mid):
        """(freqs, magnitude_db, phase_deg | None)."""
        return self.api.get_fr(mid)

    def group_delay(self, mid):
        """(freqs, group_delay)."""
        return self.api.get_group_delay(mid)

    def impulse_response(self, mid):
        """(times, samples)."""
        return self.api.get_impulse_response(mid)

    def distortion(self, mid):
        """Distortion data, or None if REW has none for this measurement."""
        return self.api.get_distortion(mid)

    # -- REW's own (virtual) filter / target model, not the physical DSP --
    def filters(self, mid):
        return self.api.get_filters(mid)

    def equaliser(self, mid):
        return self.api.get_equaliser(mid)

    def equalisers(self):
        return self.api.get_equalisers()

    def crossover_types(self):
        return self.api.get_crossover_types()

    def slopes(self):
        return self.api.get_slopes()

    def target_settings(self, mid):
        return self.api.get_target_settings(mid)

    def target_response(self, mid):
        """(freqs, magnitude_db) of the loaded target curve."""
        return self.api.get_target_response(mid)
