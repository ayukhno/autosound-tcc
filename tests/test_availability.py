"""What can run on this machine right now, and in one word why not."""
from __future__ import annotations

import threading
import time

import pytest

from autosound_tcc.core import availability
from autosound_tcc.core.model_choices import Choice


@pytest.fixture(autouse=True)
def _clean():
    availability.reset()
    yield
    availability.reset()


def _choice(harness="agy", model="gemini-3.1-pro-high", available=True):
    return Choice(harness=harness, model=model, label=model, available=available)


def _status(choice, signed_in=None, unconfirmed=False):
    return availability.status(choice, signed_in=lambda: signed_in,
                               unconfirmed=lambda _c: unconfirmed)


def test_a_model_with_nothing_against_it_is_ready():
    assert _status(_choice()) == availability.Status(True)


def test_a_route_without_its_cli_is_not_installed():
    assert _status(_choice(harness="codex", available=False)).reason == availability.NOT_INSTALLED


def test_the_claude_route_without_a_login_asks_to_sign_in():
    assert _status(_choice(harness="sdk", model="claude-opus-5"), signed_in=False).reason \
        == availability.SIGN_IN
    assert _status(_choice(harness="sdk", model="claude-opus-5"), signed_in=None).ready, \
        "None means the probe could not tell — that is not a reason to go red"


def test_a_refusal_is_red_with_its_reason_and_detail_until_it_succeeds():
    choice = _choice()
    availability.refused(choice.key, availability.LOCATION, "not supported in the selected location")

    state = _status(choice)
    assert (state.ready, state.reason) == (False, availability.LOCATION)
    assert "selected location" in state.detail

    availability.succeeded(choice.key)
    assert _status(choice).ready


def test_forgetting_refusals_is_what_the_reload_button_does():
    choice = _choice()
    availability.refused(choice.key, availability.REFUSED, "no")
    availability.forget_refusals()
    assert _status(choice).ready


def test_a_harness_still_being_read_is_not_checked():
    availability.begin_reading(["agy"])
    assert _status(_choice()).reason == availability.NOT_CHECKED
    availability.finish_reading("agy")
    assert _status(_choice()).ready


def test_an_entry_remembered_from_last_launch_is_not_checked():
    assert _status(_choice(), unconfirmed=True).reason == availability.NOT_CHECKED


def test_the_most_serious_reason_wins():
    choice = _choice(harness="codex", available=False)
    availability.refused(choice.key, availability.LOCATION, "x")
    availability.begin_reading(["codex"])
    assert _status(choice, unconfirmed=True).reason == availability.NOT_INSTALLED
    assert list(availability.PRIORITY) == [availability.NOT_INSTALLED, availability.SIGN_IN,
                                          availability.LOCATION, availability.REFUSED,
                                          availability.NOT_CHECKED]


def test_every_reason_has_a_phrase_for_the_agent():
    assert set(availability.PHRASES) == set(availability.PRIORITY)


def test_concurrent_writers_and_a_reader_do_not_trip_over_each_other():
    choice = _choice()

    def write():
        for i in range(500):
            availability.refused(f"agy:m{i}", availability.REFUSED, "x")
            availability.succeeded(f"agy:m{i}")

    threads = [threading.Thread(target=write) for _ in range(4)]
    for thread in threads:
        thread.start()
    for _ in range(500):
        _status(choice)
    for thread in threads:
        thread.join()
    assert _status(choice).ready


def _result(mode, detail=""):
    from autosound_tcc.core import critic
    return critic.CriticResult(mode, "", None, "critic", detail, 0.0, "2026-09-13T00:00:00+00:00")


def test_a_reviewer_refused_by_location_goes_red_and_an_answer_clears_it():
    from autosound_tcc.core import critic

    key = "agy:gemini-3.1-pro-high"
    availability.record_reviewer_outcome(
        key, _result(critic.MODE_CLIPBOARD, "not supported in the selected location"),
        reaches=lambda _c: True)
    assert _status(_choice()).reason == availability.LOCATION

    availability.record_reviewer_outcome(key, _result(critic.MODE_API_OR_CLI), reaches=lambda _c: True)
    assert _status(_choice()).ready


def test_clipboard_by_design_is_not_a_refusal():
    """No key and no CLI for that vendor: clipboard is the designed fallback, not a failure."""
    from autosound_tcc.core import critic

    availability.record_reviewer_outcome(
        "agy:gemini-3.1-pro-high", _result(critic.MODE_CLIPBOARD, "no transport"),
        reaches=lambda _c: False)
    assert _status(_choice()).ready


def test_a_project_that_is_not_ready_changes_nothing():
    from autosound_tcc.core import critic

    availability.record_reviewer_outcome(
        "agy:gemini-3.1-pro-high", _result(critic.MODE_NOT_READY, "context missing"),
        reaches=lambda _c: True)
    assert _status(_choice()).ready


def test_the_start_waits_for_the_reading_only_up_to_the_cap():
    release = threading.Event()
    reading = availability.StartupReading(lambda: release.wait(5)).start()

    started = time.monotonic()
    assert reading.wait(0.1) is False
    assert time.monotonic() - started < 1.0, "the cap, not the reader, decides how long the start waits"

    release.set()
    assert reading.wait(2.0) is True


def test_a_reader_that_raises_still_finishes_the_reading():
    def boom():
        raise RuntimeError("agy exploded")

    assert availability.StartupReading(boom).start().wait(2.0) is True


def test_the_default_reader_marks_harnesses_not_checked_until_it_is_done(monkeypatch):
    from autosound_tcc.core import claude_sdk, model_choices

    seen = []
    monkeypatch.setattr(model_choices, "refresh_cli_catalogue",
                        lambda **kw: seen.append(availability.status(_choice(), signed_in=lambda: None,
                                                                       unconfirmed=lambda _c: False).reason))
    monkeypatch.setattr(claude_sdk, "probe_signed_in", lambda **kw: None)

    availability.read_catalogues()

    assert seen == [availability.NOT_CHECKED]
    assert _status(_choice()).ready


def test_reset_also_clears_a_registered_startup_reading():
    availability.start_startup_reading(lambda: None)
    availability.reset()
    assert availability.startup_reading() is None
