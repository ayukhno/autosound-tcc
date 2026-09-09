"""The first thing TCC says to a model, and what happens when the Arbiter speaks first.

README and the installer both tell a new user to type "tune a new car from scratch". In TCC that
message REPLACED the opener (`opener = prompt or ...`) — and the opener is the only thing that
says "read state from disk, call get_tcc_state first". So the one path a first-time user is told
to take was the one path where nobody told the model to look at the project (SKL-027).
"""

from __future__ import annotations

from autosound_tcc.core import openers


def test_the_arbiters_first_words_are_kept_whole():
    said = openers.opening_prompt(resumed=False, typed="tune a new car from scratch")

    assert "tune a new car from scratch" in said


def test_typing_first_does_not_lose_the_instruction_to_read_state():
    """The break this catches is `prompt or <canonical>` — one word, and the model starts a car
    tune without ever calling `get_tcc_state`."""
    said = openers.opening_prompt(resumed=False, typed="tune a new car from scratch")

    assert "get_tcc_state" in said


def test_the_canonical_opener_stands_alone_when_nobody_typed_anything():
    said = openers.opening_prompt(resumed=False)

    assert "get_tcc_state" in said
    assert said == openers.opening_prompt(resumed=False, typed="")


def test_resuming_asks_for_the_pending_signals_too():
    """A resumed session has a queue behind it; a fresh one does not. That difference is the whole
    reason there are two openers rather than one."""
    assert "get_pending_signals" in openers.opening_prompt(resumed=True)
    assert "get_pending_signals" not in openers.opening_prompt(resumed=False)


def test_both_harnesses_open_with_the_same_words():
    """Two harnesses, one first contact. The texts used to be copied into `tuning_session` and
    `omp_session` separately, which is a drift waiting to happen: fix the opener in one and the
    other keeps its own. The break this catches is exactly that divergence."""
    from autosound_tcc.core import omp_session, tuning_session

    session = omp_session.OmpSession.__new__(omp_session.OmpSession)
    session.resume = True

    assert session._opening() == openers.opening_prompt(resumed=True)
    assert tuning_session.TuningSession._opener(resumed=True, prompt="") == (
        openers.opening_prompt(resumed=True)
    )


def test_the_opener_says_which_language_to_answer_in():
    """Decision, 2026-09-09 (user): TCC's own instructions are always English — a system command
    must never be mistakable for the Arbiter's own words — and the model answers the person in the
    project's language. English text with nothing said about it is how a Ukrainian Arbiter gets
    answered in English, which is the half of the decision that has to be written down where the
    model reads it, not in a comment."""
    for resumed in (True, False):
        said = openers.opening_prompt(resumed=resumed)
        assert "language" in said.lower()
        assert "get_tcc_state" in said
