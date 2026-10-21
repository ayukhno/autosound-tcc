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

import inspect
import socket
import urllib.error
from dataclasses import dataclass
from types import ModuleType
from typing import Optional

from autosound_tcc.core import app_log

#: What TCC tells of REW (#219, audit T-2/T-3): it answered; it did not answer (down, the port shut,
#: a timeout); it answered, and not with what was asked (an HTTP error, an answer that cannot be
#: read, a write it did not keep); or a failure TCC cannot place, which is said as not known and
#: logged — never as «offline», which it may not be.
ONLINE = "online"
UNAVAILABLE = "unavailable"
ANSWERED_ERROR = "error"
UNKNOWN = "unknown"
#: REW's address is no address (`REW_API_URL` mistyped, the method's `RewAddressError`): REW was
#: never asked, and nothing will be until the address is put right (the group review of #219, H).
ADDRESS = "config"

#: The method's states in which REW answered, and not with what was asked (`rew_api.py`).
_ANSWERED = frozenset({"error", "protocol", "write_mismatch"})


def method_state(exc: BaseException) -> Optional[str]:
    """The method's REW state for `exc` — `rew_state` on its class (`rew_api.rew_state`), or
    "error" for REW answering 4xx/5xx — or None when it carries none.

    Off the class, never by `isinstance` on the method's classes: TCC loads `rew_api.py` by path,
    a copy of its own, and another copy's classes are other classes. REW's error answer is the
    standard library's one `HTTPError`, which has no `rew_state`; it is the one class matched.
    A method before v3.1.2 sets no state at all — read by what the exception carries, never by the
    method's version — so the standard library's own transport errors are read too, after
    `HTTPError` (one of them): a `URLError`, a refused or dropped connection, a timeout is REW not
    answering, "unavailable", as it was before #219 (the group review, G). Anything else with no
    state is None here."""
    state = getattr(type(exc), "rew_state", None)
    if state is not None:
        return str(state)
    if isinstance(exc, urllib.error.HTTPError):
        return "error"
    if isinstance(exc, _TRANSPORT):
        return "unavailable"
    return None


#: The standard library's errors for REW not answering: what a copy with no `rew_state` raises.
_TRANSPORT = (urllib.error.URLError, ConnectionError, TimeoutError, socket.timeout)


def status_of(exc: BaseException) -> str:
    """Which of TCC's states `exc` is: `UNAVAILABLE`, `ANSWERED_ERROR`, `ADDRESS` or `UNKNOWN`. A
    missing state is unknown — never REW down, and never a measurement missing."""
    state = method_state(exc)
    if state == "unavailable":
        return UNAVAILABLE
    if state in _ANSWERED:
        return ANSWERED_ERROR
    if state == ADDRESS:
        return ADDRESS
    return UNKNOWN


@dataclass(frozen=True)
class RewProbe:
    """What TCC last learned of REW: `state`, one of the four above, and `detail`, the failure in
    its own words («RewUnavailable: REW is not answering at …»), empty when REW answered."""

    state: str
    detail: str = ""


#: The failure TCC last met asking REW, as (state, exception type), and None once REW's list
#: answered (`RewBridge.measurements`): an unknown failure is logged once per change, since the
#: ping asks every 30 s (the group review of #219, H). The type is part of it: the scan, an import
#: and a rename ask REW too, and an unknown failure of another kind after the ping's went unlogged
#: until a ping succeeded — which it does only while the window has focus (W-11's final review, M2).
_last_failure: Optional[tuple[str, str]] = None


def probe_of(exc: BaseException) -> RewProbe:
    """`exc`, met asking REW, as a `RewProbe`. One TCC cannot place goes to the log whole, with
    its traceback, when it is new — not again on every ping while the same failure stays: the dot
    says only that the state is not known."""
    global _last_failure
    state = status_of(exc)
    detail = f"{type(exc).__name__}: {exc}"
    failure = (state, type(exc).__name__)
    if state == UNKNOWN and failure != _last_failure:
        app_log.logger().warning("REW's state is not known: asking it failed with %s", detail,
                                 exc_info=exc)
    _last_failure = failure
    return RewProbe(state, detail)


def _takes_smoothing(call) -> bool:
    """Whether `call` takes `smoothing=`: a parameter of that name, or `**kwargs`.

    A reader whose signature cannot be read (a builtin, a C function) is taken to take it: asked,
    the read is either the smoothing asked for or a TypeError out loud, where the other guess reads
    REW's view and passes it off as the smoothing asked for without a word."""
    try:
        parameters = inspect.signature(call).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(p.name == "smoothing" or p.kind is p.VAR_KEYWORD for p in parameters)


class RewBridge:
    """Thin read-only facade over `rew_api`.

    The vendored module is loaded lazily on first use so importing this module
    (e.g. for type hints or tests) never requires the submodule to be present.
    """

    def __init__(self, api: ModuleType | None = None) -> None:
        self._api = api

    @property
    def api(self) -> ModuleType:
        """The module handed in, or the loader's, asked on every use rather than kept: an in-app
        update reads the method again (`vendor_loader.reload_loaded`, #126), and a bridge that kept
        its first module talked to REW through the old method until TCC restarted."""
        if self._api is not None:
            return self._api
        from autosound_tcc.core import vendor_loader

        return vendor_loader.load_rew_api()

    @property
    def base_url(self) -> str:
        return self.api.BASE_URL

    def probe(self) -> RewProbe:
        """The REW dot's probe: REW's list asked for, the answer dropped — `ONLINE`, or the state
        the failure is (`probe_of`). It said «offline» for any failure (#219): REW answering an
        error read as REW not running. Call off the GUI thread."""
        try:
            self.measurements()
        except Exception as exc:  # noqa: BLE001 — every failure is a state, said or logged
            return probe_of(exc)
        return RewProbe(ONLINE)

    # -- measurements --
    def measurements(self) -> dict:
        """All measurements, keyed by REW's (unstable) ordinal id. An answer makes REW's state
        known again, whichever reader asked — the ping or the scan — so the next unknown failure
        is logged (`probe_of`)."""
        global _last_failure
        found = self.api.get_measurements()
        _last_failure = None
        return found

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
    @property
    def FINEST_SMOOTHING(self) -> str:  # noqa: N802 — the method's own constant, under its name
        """The finest smoothing the method reads at (`rew_api.FINEST_SMOOTHING`, v3.0.54): `None`
        and `1/48` are one level for its purposes, and `None` comes back linear."""
        return str(getattr(self.api, "FINEST_SMOOTHING", "1/48"))

    def frequency_response(self, mid, smoothing=None):
        """(freqs, magnitude_db, phase_deg | None).

        `smoothing` is asked of REW on the read (`?smoothing=`, hub #155); None takes whatever the
        Arbiter's view of that measurement holds. A method before v3.0.54 cannot ask, and reads the
        view rather than failing.
        """
        return self._read(self.api.get_fr, mid, smoothing)

    def group_delay(self, mid, smoothing=None):
        """(freqs, group_delay), with `smoothing` as for `frequency_response`."""
        return self._read(self.api.get_group_delay, mid, smoothing)

    @staticmethod
    def _read(call, mid, smoothing):
        """One read, called once. Whether the reader takes `smoothing` is read off its signature
        (#170 F16-3): a retry on any TypeError took one raised INSIDE a reader that does take it
        for a method too old to — swallowed it, and read the view in place of the smoothing asked."""
        if smoothing is None:
            return call(mid)
        if _takes_smoothing(call):
            return call(mid, smoothing=smoothing)
        return call(mid)

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
