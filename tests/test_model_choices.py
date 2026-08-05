"""Which model runs the conversation, and which harness carries it.

`omp models --json` is stubbed: the shape here is the one omp actually returns (captured
2026-08-05), and the point of these tests is the curation rules, not the subprocess.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from autosound_tcc.core import model_choices
from autosound_tcc.core.model_choices import Choice, OmpCatalogueError

CATALOGUE = {
    "models": [
        {
            "provider": "google",
            "id": "gemini-3.1-pro-preview",
            "selector": "google/gemini-3.1-pro-preview",
            "name": "Gemini 3.1 Pro",
            "cost": {"input": 1.25, "output": 10.0},
        },
        {
            "provider": "opencode",
            "id": "nemotron-3-ultra-free",
            "selector": "opencode/nemotron-3-ultra-free",
            "name": "Nemotron 3 Ultra (free)",
            "cost": {"input": 0, "output": 0},
        },
    ]
}


@pytest.fixture
def catalogue(monkeypatch):
    monkeypatch.setattr(model_choices, "omp_available", lambda: True)
    monkeypatch.setattr(
        model_choices.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(CATALOGUE), ""),
    )


def test_claude_models_run_through_the_sdk(tmp_path):
    """Not a preference — the SDK against the user's own CLI is the path whose licensing is
    settled, so picking a Claude model picks that harness."""
    assert all(choice.harness == "sdk" for choice in model_choices.sdk_choices())
    assert "claude-opus-5" in [choice.model for choice in model_choices.sdk_choices()]


def test_the_picker_shows_only_the_omp_models_the_user_marked(catalogue):
    entries = model_choices.choices(["google/gemini-3.1-pro-preview"])

    omp = [choice for choice in entries if choice.harness == "omp"]
    assert [choice.model for choice in omp] == ["google/gemini-3.1-pro-preview"]
    assert omp[0].label == "Gemini 3.1 Pro"


def test_with_nothing_marked_the_picker_is_the_sdk_alone(catalogue):
    assert [choice.harness for choice in model_choices.choices([])] == ["sdk", "sdk", "sdk"]


def test_a_free_model_is_visibly_free_at_the_moment_of_choosing(catalogue):
    """The axis the harness was chosen on; it belongs in front of the person paying."""
    entries = model_choices.omp_catalogue()

    by_model = {choice.model: choice for choice in entries}
    assert by_model["opencode/nemotron-3-ultra-free"].free is True
    assert by_model["google/gemini-3.1-pro-preview"].free is False


def test_a_marked_model_omp_no_longer_reports_is_still_offered(catalogue):
    """Dropping it silently makes a picker that forgets what the user chose. A model that errors
    when used says so loudly, which is the better failure."""
    entries = model_choices.choices(["some/retired-model"])

    assert [choice.model for choice in entries if choice.harness == "omp"] == ["some/retired-model"]


def test_the_picker_survives_omp_being_absent(monkeypatch):
    """A marked model must still be selectable on a machine where omp is not installed — the
    resulting error belongs at the moment of running, not at the moment of drawing a combo box."""
    monkeypatch.setattr(model_choices, "omp_available", lambda: False)

    entries = model_choices.choices(["google/gemini-3.1-pro-preview"])

    assert [choice.model for choice in entries if choice.harness == "omp"] == [
        "google/gemini-3.1-pro-preview"
    ]


def test_reading_the_catalogue_without_omp_is_an_error_with_the_fix_in_it(monkeypatch):
    monkeypatch.setattr(model_choices, "omp_available", lambda: False)

    with pytest.raises(OmpCatalogueError) as exc:
        model_choices.omp_catalogue()

    assert "brew install" in str(exc.value)


def test_a_choice_key_survives_a_restart():
    """Persisted selection is by key, so it has to name both halves of the choice."""
    assert Choice(harness="omp", model="google/gemini-3.1-pro-preview", label="x").key == (
        "omp:google/gemini-3.1-pro-preview"
    )
    assert model_choices.find(model_choices.sdk_choices(), "sdk:claude-opus-5").label == "Claude Opus 5"
