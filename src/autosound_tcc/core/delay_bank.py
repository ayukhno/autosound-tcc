"""Delays the Arbiter has read off the curves, kept per measurement until they are analysed.

Aligning a car is not one pair of curves. It is a woofer against a woofer, then the pair against
a midbass, then the front against the sub — and each of those readings is worth nothing on its own
because a delay is only ever relative to everything else in the cabin. The curve window used to
lose each one the moment the next pair was loaded, which put the Arbiter in the position of
holding six numbers in their head while reading the seventh (user, 2026-08-12: "було б здорово
мати збереження затримки по кожному каналу... і потім коли ти все виставив — відправити на аналіз
ШІ").

**Not for writing.** This is a reading, not a change: nothing here goes to a DSP, and nothing here
is a delta. The whole set is handed to the model to be *looked at* — the model's job is to say
whether the picture is coherent (a sub 20 ms behind everything else is a measurement error, not a
tuning), and the Arbiter's job is to decide what to do about it. Two more gates stand between this
and any hardware, and both of them are somebody else's (see `project_tcc_safety_gates`).

Keyed by MEASUREMENT TITLE, not by channel. Those are nearly the same thing and the difference
matters: a delay read off `w-L_02` was read off that capture, at that crossover, with that gain.
Folding it onto "w-L" would silently carry a number from round 2 into round 5.

Lives in `.tcc/` with TCC's other state, never in the skill's files (D-6).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from autosound_tcc.core import config, project_settings

KEY = "curve_delays"


def load(tcc_dir: Optional[Path] = None) -> dict[str, float]:
    """`{measurement title: ms}`, worst case empty. Never raises: a hand-edited file is "nothing
    banked yet", not a dead curve window."""
    raw = project_settings.load(tcc_dir or config.tcc_dir()).get(KEY)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for title, ms in raw.items():
        try:
            value = float(ms)
        except (TypeError, ValueError):
            continue
        if value > 0:
            out[str(title)] = value
    return out


def put(title: str, ms: float, tcc_dir: Optional[Path] = None) -> dict[str, float]:
    """Bank one reading, or forget it when it goes back to zero.

    Zero is stored as absence rather than as `0.0`: "this channel needs no delay" and "I have not
    looked at this channel" are different statements, and only the second is honest about a curve
    nobody has opened.
    """
    tcc_dir = tcc_dir or config.tcc_dir()
    bank = load(tcc_dir)
    title = str(title)
    if float(ms) > 0:
        bank[title] = round(float(ms), 4)
    else:
        bank.pop(title, None)
    project_settings.set_value(tcc_dir, KEY, bank or None)
    return bank


def clear(tcc_dir: Optional[Path] = None) -> None:
    project_settings.set_value(tcc_dir or config.tcc_dir(), KEY, None)


def as_sentence(
    bank: dict[str, float], sample_rate_hz: Optional[float] = None, lang_t=None
) -> str:
    """The whole set as something a model can read, and a person can check before it is sent.

    Every line carries the sample count when a rate is on record, because the skill's own rule is
    that a delay is stated in milliseconds AND samples — and because the arithmetic between them
    is exactly where a plausible-looking set turns out to be unreachable on the hardware.
    """
    if not bank:
        return ""
    t = lang_t or (lambda key: key)
    lines = []
    for title, ms in sorted(bank.items(), key=lambda kv: (-kv[1], kv[0])):
        line = f"  {title}: +{ms:.3f} ms"
        if sample_rate_hz:
            line += f" ({int(round(ms * sample_rate_hz / 1000.0))} smp)"
        lines.append(line)
    return "\n".join([t("curveBankAsk"), *lines, t("curveBankNotForWriting")])
