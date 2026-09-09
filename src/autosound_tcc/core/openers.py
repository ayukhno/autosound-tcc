"""The first thing TCC says to a model — one text, two harnesses.

The opener carries the only instruction that makes a session start from the project rather than
from the model's imagination: read state from disk, call `get_tcc_state`, then say where we are.
Everything else in a tuning session follows from that call.

It used to be dropped exactly where it mattered most. `opener = prompt or <canonical>` meant that
the moment the Arbiter typed the first message — and README and the installer both tell a new
user to type "tune a new car from scratch" — the instruction went away with it. The documented
first contact was the one path where nobody told the model to look at the project (SKL-027).

Both texts also lived twice, copied into `tuning_session` and `omp_session`. Two copies of one
sentence is a drift with a date on it: fix one and the other keeps its own wording. One home,
and a test that both harnesses still read from it.
"""

from __future__ import annotations

_FRESH = (
    "Start a tuning session for this project. Read state from disk, call get_tcc_state, then "
    "tell me where we are and what the next step is."
)
_RESUMED = (
    "Resume this tuning project. Read state from disk first, call get_tcc_state and "
    "get_pending_signals, then tell me where we are and what the next step is."
)


def opening_prompt(resumed: bool, typed: str = "") -> str:
    """What to send as the session's first turn.

    `typed` is whatever the Arbiter wrote in the composer before any session existed — sending it
    IS how a session starts, so it is never thrown away. It goes AFTER the instruction rather than
    instead of it: the model reads what to do first, then what the person actually asked for,
    which is also the order it would have got them in had they typed a second message.
    """
    canonical = _RESUMED if resumed else _FRESH
    said = typed.strip()
    if not said:
        return canonical
    return f"{canonical}\n\nThen: {said}"
