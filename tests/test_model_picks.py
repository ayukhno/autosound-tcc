"""What the model pickers decide, without a window (`core.model_picks`): the AI-picks group, W-10
(tcc#165, #196, #182, hub #262) and its group review."""
from __future__ import annotations

import pytest

from autosound_tcc.core import availability, model_choices as mc, model_overrides, model_picks
from autosound_tcc.core.model_choices import Choice


def _sdk(model: str) -> Choice:
    return Choice(harness="sdk", model=model, label=model, provider="anthropic")


ENTRIES = [_sdk("claude-opus-5-5"), _sdk("claude-sonnet-5"), _sdk("claude-sonnet-5-5")]


@pytest.fixture(autouse=True)
def _own_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))


def test_a_row_picked_by_name_runs_itself_even_under_an_old_alias():
    """Finding 156: an alias Sonnet 5 → the running Opus 5.5 made the Sonnet pick change nothing."""
    model_overrides.set_alias("sdk:claude-sonnet-5", "sdk:claude-opus-5-5")

    picked = model_picks.chosen(ENTRIES, "sdk:claude-sonnet-5")

    assert picked.key == "sdk:claude-sonnet-5"
    assert model_picks.restart_offered("sdk:claude-opus-5-5", picked)
    assert not model_picks.restart_offered("sdk:claude-sonnet-5", picked)
    assert not model_picks.restart_offered(None, picked)


def test_the_old_dialogs_alias_for_this_projects_pick_is_honoured_once():
    """157's own machine: a project on Sonnet 5, aliased to Opus 5.5 by the old «gone» dialog, and
    Sonnet 5 offered again — it would silently run Sonnet 5 and undo the accepted switch."""
    model_overrides.set_alias("sdk:claude-sonnet-5", "sdk:claude-opus-5-5")

    plan = model_picks.plan_pickers(ENTRIES, [], "sdk:claude-sonnet-5", "")

    assert plan.honoured == ("sdk:claude-sonnet-5", "sdk:claude-opus-5-5")
    assert plan.generator_shown == "sdk:claude-opus-5-5"
    assert plan.offers == ()
    # Once: with the setting rewritten, the next fill has nothing to honour.
    assert model_picks.plan_pickers(ENTRIES, [], "sdk:claude-opus-5-5", "").honoured is None


def test_a_gone_key_with_an_alias_shows_the_model_that_runs_and_asks_nothing():
    """The `shown` branch: an alias written before the window opened, the key not offered."""
    model_overrides.set_alias("sdk:claude-opus-4-1", "sdk:claude-opus-5-5")

    plan = model_picks.plan_pickers(ENTRIES, [], "sdk:claude-opus-4-1", "")

    assert plan.generator_shown == "sdk:claude-opus-5-5"
    assert plan.honoured is None and plan.offers == ()


def test_a_gone_key_is_offered_a_replacement_but_not_while_its_list_is_read():
    """157 was likely offered from an incomplete startup list: a row missing while the route is
    still being read is «not read yet», not «gone»."""
    plan = model_picks.plan_pickers(ENTRIES, ENTRIES, "sdk:claude-opus-4-1", "sdk:claude-x")
    assert [(setting, key) for setting, key, _e in plan.offers] == [
        ("generator", "sdk:claude-opus-4-1"), ("critic", "sdk:claude-x")]

    availability.begin_reading(["sdk-cli"])
    try:
        assert model_picks.plan_pickers(ENTRIES, ENTRIES, "sdk:claude-opus-4-1",
                                        "sdk:claude-x").offers == ()
    finally:
        availability.finish_reading("sdk-cli")


def test_the_gone_check_follows_an_alias_as_the_pick_does():
    model_overrides.set_alias("sdk:claude-old", "sdk:claude-sonnet-5-5")

    assert model_picks.plan_pickers(ENTRIES, ENTRIES, "", "sdk:claude-old").offers == ()


# ---- a reviewer pick with no key here is offered the installed route (hub #262) ---------------

API_PICK = Choice(harness="api", model="gemini-3.1-pro-preview", label="gemini-3.1-pro-preview",
                  provider="google")
FLASH = Choice(harness="agy", model="gemini-3.8-flash-high", label="Gemini 3.8 Flash (High)",
               provider="google")
PRO = Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro (High)",
             provider="google")


@pytest.fixture
def agy_by_adc(monkeypatch):
    monkeypatch.setattr(mc, "_CLI_CACHE", {"agy": [PRO, FLASH]})
    monkeypatch.setattr(mc, "agy_on_adc", lambda: True)
    monkeypatch.setattr(mc, "cli_available", lambda harness: harness == "agy")
    # No key on this machine: only agy's rows reach (conftest stubs the real question).
    monkeypatch.setattr(mc, "critic_reaches", lambda choice: choice.harness == "agy")


def test_under_adc_the_methods_own_reviewer_is_offered_before_the_recommended_pro(agy_by_adc):
    assert model_picks.reviewer_on_a_signed_in_route(API_PICK) == (FLASH, False)


def test_a_row_refused_by_region_this_launch_is_not_offered(agy_by_adc, monkeypatch):
    """The group review: «signed in» was said of a row agy had just refused by region."""
    monkeypatch.setattr(mc, "agy_on_adc", lambda: False)
    availability.refused(FLASH.key, availability.LOCATION, "not supported in the selected location")

    assert model_picks.reviewer_on_a_signed_in_route(API_PICK) == (PRO, False)


def test_installed_is_said_until_the_sign_in_was_checked(agy_by_adc):
    notes, instead = model_picks.critic_notes(API_PICK.key, [API_PICK, PRO, FLASH], None)
    assert instead == FLASH
    assert any(n.tip == "criticInstalledRoute" for n in notes)

    availability.succeeded(FLASH.key)  # it answered this launch
    notes, _ = model_picks.critic_notes(API_PICK.key, [API_PICK, PRO, FLASH], None)
    assert any(n.tip == "criticSignedInRoute" and "AGY · Gemini 3.8 Flash (High)" in
               n.args["instead"] for n in notes)


def test_a_pick_that_reaches_or_has_no_other_route_is_offered_nothing(agy_by_adc):
    claude = Choice(harness="api", model="claude-opus-5", label="x", provider="anthropic")

    assert model_picks.reviewer_on_a_signed_in_route(FLASH) is None
    assert model_picks.reviewer_on_a_signed_in_route(claude) is None
