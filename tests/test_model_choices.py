"""Which model runs the conversation, and which harness carries it.

`omp models --json` is stubbed: the shape here is the one omp actually returns (captured
2026-08-05), and the point of these tests is the curation rules, not the subprocess.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from autosound_tcc.core import model_choices
from autosound_tcc.core import model_choices as mc
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


def test_the_reviewer_list_is_the_generator_list_plus_the_local_clis(catalogue, monkeypatch):
    """One registry, and then the routes only a reviewer can use.

    A CLI route appears for the Critic and not for the Generator because the reviewer is a
    one-shot call the skill's own script already knows how to make, while a Generator has to hold
    a session and talk to TCC's MCP server — which nothing has wired for `agy`/`codex` yet.
    """
    from autosound_tcc.core import model_choices as mc

    active = ["google/gemini-3.1-pro-preview"]
    monkeypatch.setattr(mc, "_CLI_CACHE", {"agy": [
        mc.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro (High)",
                  provider="google")
    ]})
    monkeypatch.setattr(mc, "cli_available", lambda harness: harness == "codex")

    generator = model_choices.choices(active)
    reviewer = model_choices.critic_choices(active)

    assert reviewer[: len(generator)] == generator
    routes = {c.harness for c in reviewer[len(generator):]}
    assert routes == {"agy", "codex"}
    assert all(c.harness in ("sdk", "omp") for c in generator)


def test_every_route_is_labelled_and_says_whose_bill_it_is(catalogue):
    """The same model reached two ways is two different accounts. An unlabelled entry reads as
    "the normal one", which is the assumption that quietly spends money."""
    from autosound_tcc.core import model_choices as mc

    sdk = mc.Choice(harness="sdk", model="claude-opus-5", label="Claude Opus 5")
    omp = mc.Choice(harness="omp", model="google/gemini-3.1-pro-preview", label="Gemini")
    agy = mc.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro (High)")

    assert (sdk.route, omp.route, agy.route) == ("SDK", "OMP", "AGY")
    assert "metered" in omp.route_note  # the one that spends without being noticed
    assert "subscription" in agy.route_note


def test_the_recommended_pair_is_marked_on_both_sides(catalogue):
    """Claude Opus as Generator, a Gemini Pro through a subscription as Critic — the one
    combination the method has been driven with end to end."""
    from autosound_tcc.core import model_choices as mc

    opus = mc.Choice(harness="sdk", model="claude-opus-5", label="Claude Opus 5")
    sonnet = mc.Choice(harness="sdk", model="claude-sonnet-5", label="Claude Sonnet 5")
    gemini_pro = mc.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro (High)")
    gemini_flash = mc.Choice(harness="agy", model="gemini-3.6-flash-low", label="Gemini 3.6 Flash (Low)")

    assert mc.recommended(opus) and not mc.recommended(sonnet)
    assert mc.recommended(gemini_pro, critic=True)
    assert not mc.recommended(gemini_flash, critic=True)
    assert not mc.recommended(opus, critic=True)  # the Critic must not be the Generator's vendor


def test_the_reviewer_vendor_is_read_off_the_model_name():
    """Same resolution the skill's script does, by the same markers — the front-end must not
    disagree with it about whose transport a model belongs to (SCR-033)."""
    gemini = Choice(harness="omp", model="google/gemini-3.1-pro-preview", label="x",
                    provider="google")
    claude = Choice(harness="sdk", model="claude-opus-5", label="x", provider="anthropic")
    gpt = Choice(harness="omp", model="openai/gpt-5.2", label="x", provider="openai")
    unknown = Choice(harness="omp", model="some/local-model", label="x", provider="")

    assert model_choices.critic_vendor(gemini) == "google"
    assert model_choices.critic_vendor(claude) == "anthropic"
    assert model_choices.critic_vendor(gpt) == "openai"
    # What every setup predating the parameter already meant.
    assert model_choices.critic_vendor(unknown) == "google"


def test_reachability_is_the_vendors_key_or_cli_not_the_vendors_name(monkeypatch):
    """Before SCR-033 this answered "is it Gemini" and marked everything else clipboard-only.
    Now the reviewer script speaks three transports, so the question is whether THIS machine has
    the one the chosen model needs."""
    from autosound_tcc.core import model_choices as mc

    claude = Choice(harness="sdk", model="claude-opus-5", label="x", provider="anthropic")
    monkeypatch.setattr(mc.shutil, "which", lambda _binary: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert mc.critic_reaches(claude) is False

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert mc.critic_reaches(claude) is True

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        mc.shutil, "which", lambda binary: "/usr/bin/claude" if binary == "claude" else None
    )
    assert mc.critic_reaches(claude) is True  # the CLI is a transport too


def test_the_agy_catalogue_is_retried_and_read_off_both_streams(monkeypatch):
    """`agy models` fetches over the network: the first call in a fresh process comes back empty
    often enough to matter, and part of its output can land on stderr. Read one stream, ask once,
    and the whole route disappears between launches — indistinguishable from "not installed"."""
    from autosound_tcc.core import model_choices as mc

    calls: list = []

    class _Proc:
        def __init__(self, out: str, err: str = "") -> None:
            self.returncode, self.stdout, self.stderr = 0, out, err

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        if len(calls) == 1:
            return _Proc("")  # the cold call, exit 0 and nothing to show for it
        return _Proc("", "Fetching available models...\ngemini-3.1-pro-high\tGemini 3.1 Pro (High)")

    monkeypatch.setattr(mc, "cli_available", lambda harness: harness == "agy")
    monkeypatch.setattr(mc.subprocess, "run", fake_run)

    rows = mc._fetch_agy_choices()

    assert len(calls) == 2  # asked again rather than believing the empty answer
    assert [(c.model, c.label) for c in rows] == [
        ("gemini-3.1-pro-high", "Gemini 3.1 Pro (High)")
    ]


def test_a_cli_that_answers_with_nothing_keeps_its_last_good_list(monkeypatch):
    """A network hiccup must not empty the picker: the route the user configured is still there,
    and re-rendering it as absent is what teaches people to reach for the metered one."""
    from autosound_tcc.core import model_choices as mc

    good = [mc.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro (High)")]
    monkeypatch.setattr(mc, "_CLI_CACHE", {"agy": list(good)})
    monkeypatch.setattr(mc, "_fetch_agy_choices", lambda: [])
    monkeypatch.setattr(mc, "cli_available", lambda harness: harness == "agy")

    mc.refresh_cli_catalogue()

    assert mc.agy_choices() == good
    assert mc.cli_routes_without_models() == []  # it did answer, once; nothing to warn about


def test_an_installed_cli_that_never_answered_is_named_rather_than_hidden(monkeypatch):
    from autosound_tcc.core import model_choices as mc

    monkeypatch.setattr(mc, "_CLI_CACHE", {})
    monkeypatch.setattr(mc, "_fetch_agy_choices", lambda: [])
    monkeypatch.setattr(mc, "cli_available", lambda harness: harness == "agy")

    mc.refresh_cli_catalogue()

    assert mc.agy_choices() == []
    assert mc.cli_routes_without_models() == ["agy"]


def test_a_retired_key_resolves_through_the_local_alias(tmp_path, monkeypatch):
    """The name in a project's settings outlives the model. One indirection reaches every place
    that name was written down — other projects, journal entries, whatever the skill prescribed."""
    from autosound_tcc.core import model_choices as mc, model_overrides as mo

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path))
    entries = mc.sdk_choices()

    gone = mc.resolve(entries, "sdk:claude-opus-4-1")
    assert not gone.ok and gone.note == ""  # named, not swallowed

    mo.set_alias("sdk:claude-opus-4-1", "sdk:claude-opus-5", why="no longer offered")
    now = mc.resolve(entries, "sdk:claude-opus-4-1")

    assert now.ok and now.choice.model == "claude-opus-5"
    # The record must be able to say what actually ran, not just what was asked for.
    assert "sdk:claude-opus-4-1 → sdk:claude-opus-5" in now.note
    assert "no longer offered" in now.note


def test_an_alias_cycle_does_not_hang_the_picker(tmp_path, monkeypatch):
    """A hand-edited file can say `a -> b -> a`, and a resolver that loops is a window that never
    opens."""
    from autosound_tcc.core import model_choices as mc, model_overrides as mo

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path))
    mo.set_alias("sdk:a", "sdk:b")
    mo.set_alias("sdk:b", "sdk:a")

    assert mc.resolve(mc.sdk_choices(), "sdk:a").ok is False


def test_this_machine_can_add_and_hide_models(tmp_path, monkeypatch):
    """A model no catalogue reports (a private deployment, a preview) and one this machine should
    stop offering — the other half of surviving a generation nobody shipped an update for."""
    import json

    from autosound_tcc.core import model_choices as mc

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path))
    (tmp_path / "models.json").write_text(json.dumps({
        "schema_version": 1,
        "hidden": ["sdk:claude-fable-5"],
        "added": [{"harness": "sdk", "model": "claude-opus-6", "label": "Claude Opus 6"}],
    }), encoding="utf-8")

    keys = [c.key for c in mc.choices([])]

    assert "sdk:claude-fable-5" not in keys
    assert "sdk:claude-opus-6" in keys


def test_an_addition_never_shadows_a_real_catalogue_entry(tmp_path, monkeypatch):
    """A hand-written row that replaced the real one would be a silent lie about which model runs."""
    import json

    from autosound_tcc.core import model_choices as mc

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path))
    (tmp_path / "models.json").write_text(json.dumps({
        "schema_version": 1,
        "added": [{"harness": "sdk", "model": "claude-opus-5", "label": "NOT the real one"}],
    }), encoding="utf-8")

    labels = [c.label for c in mc.choices([]) if c.model == "claude-opus-5"]

    assert labels == ["Claude Opus 5"]


def test_a_malformed_overrides_file_does_not_stop_the_app(tmp_path, monkeypatch):
    """This is the file that keeps a machine working when a model retires; a typo in it must not
    be the thing that stops the app from opening."""
    from autosound_tcc.core import model_choices as mc, model_overrides as mo

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path))
    (tmp_path / "models.json").write_text("{ not json", encoding="utf-8")

    assert mo.load()["aliases"] == {}
    assert [c.key for c in mc.sdk_choices()]  # and the ordinary list still builds


def test_the_models_api_refreshes_the_claude_list_when_a_key_exists(tmp_path, monkeypatch):
    """The shipped list is a floor that ages. Where the machine has a key, the list is asked
    rather than believed — the same pattern as `agy models`, for the route where it is possible."""
    import io
    import json

    from autosound_tcc.core import model_choices as mc

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(mc, "_CLI_CACHE", {})
    payload = json.dumps({"data": [
        {"id": "claude-opus-6", "display_name": "Claude Opus 6"},
        {"id": "claude-opus-5", "display_name": "Claude Opus 5"},
    ]}).encode()

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(mc.urllib.request, "urlopen", lambda *a, **k: _Response(payload))
    monkeypatch.setattr(mc, "_fetch_agy_choices", lambda: [])

    mc.refresh_cli_catalogue()
    models = [c.model for c in mc.sdk_choices()]

    assert models[0] == "claude-opus-6"  # a model nobody shipped an update for
    # The shipped names stay available too: they are a floor, not a competing answer.
    assert "claude-sonnet-5" in models
    assert models.count("claude-opus-5") == 1  # and are not duplicated by the refresh


def test_without_a_key_the_shipped_list_is_what_there_is(tmp_path, monkeypatch):
    """Most SDK installs run on the user's own `claude` login and have no API key — those survive
    a retirement through the overrides file, not through this."""
    from autosound_tcc.core import model_choices as mc

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert mc._fetch_sdk_choices() == []
    assert [c.model for c in mc.sdk_choices()] == [m for _, m in mc.SDK_MODELS]


# ---- effort (2026-08-07) ----------------------------------------------------


def test_below_high_is_not_offered_because_it_is_not_a_tuning_setting():
    """The Arbiter's rule: a cheap pass reads as competence. The case the harness exists for is a
    model that closed four phases in one sitting and reported a finished tune on a car nobody sat
    in — which is what a model that agrees too easily looks like from the outside."""
    assert model_choices.EFFORT_LEVELS == ("high", "xhigh", "max")
    assert model_choices.EFFORT_DEFAULT == "xhigh"


def test_an_unknown_or_unset_effort_reads_as_the_default_not_as_itself():
    """These strings become a subprocess argument and a model API field. "The level I typed is not
    a level" must not be discovered there — and `auto`, which omp offers, is deliberately not one
    of ours: letting a metered route decide how much to spend is the setting to never leave on."""
    assert model_choices.resolve_effort(None) == "xhigh"
    assert model_choices.resolve_effort("") == "xhigh"
    assert model_choices.resolve_effort("low") == "xhigh"
    assert model_choices.resolve_effort("auto") == "xhigh"
    assert model_choices.resolve_effort("  MAX ") == "max"
    assert model_choices.resolve_effort("high") == "high"


# ---- a route that answered once must not silently disappear (user, 2026-08-11) ----------------


def test_the_catalogue_survives_a_launch_where_the_cli_says_nothing(tmp_path, monkeypatch):
    """`_CLI_CACHE` was per-process, which is the same as no memory: every launch started empty,
    and a launch where `agy models` was slow or came back blank ran the whole session with the
    route missing. From the outside that is empty pickers and a recommended pair reporting itself
    absent — and downstream, a stored critic key that stops resolving and gets aliased onto the
    Generator's own vendor."""
    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(mc, "_CLI_CACHE", {})
    monkeypatch.setattr(mc, "_UNCONFIRMED", set())
    real = [mc.Choice(harness="agy", model="gemini-3.1-pro-high",
                      label="Gemini 3.1 Pro (High)", provider="google")]
    monkeypatch.setattr(mc, "_fetch_agy_choices", lambda: real)
    monkeypatch.setattr(mc, "_fetch_sdk_choices", lambda: [])

    mc.refresh_cli_catalogue()
    assert mc.catalogue_cache_path().is_file()
    assert not mc.unconfirmed(real[0]), "confirmed just now"

    # Next launch: nothing in memory, and the CLI answers nothing at all.
    monkeypatch.setattr(mc, "_CLI_CACHE", {})
    monkeypatch.setattr(mc, "_UNCONFIRMED", set())
    monkeypatch.setattr(mc, "_fetch_agy_choices", lambda: [])

    offered = mc.agy_choices()

    assert [c.key for c in offered] == ["agy:gemini-3.1-pro-high"]
    assert mc.unconfirmed(offered[0]), "shown, and marked as remembered rather than confirmed"


def test_a_malformed_cache_reads_as_no_memory(tmp_path, monkeypatch):
    """This file exists to keep a picker populated; a typo in it must not stop the window."""
    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(mc, "_CLI_CACHE", {})
    monkeypatch.setattr(mc, "_UNCONFIRMED", set())
    mc.catalogue_cache_path().parent.mkdir(parents=True, exist_ok=True)
    mc.catalogue_cache_path().write_text("{not json", encoding="utf-8")

    assert mc.agy_choices() == []


# ---- the recommendation is a class, not a name (user, 2026-08-12) -----------------------------


def _c(harness, model, label, provider):
    return Choice(harness=harness, model=model, label=label, provider=provider)


def test_a_new_version_of_the_recommended_class_is_recommended_with_no_release():
    """It matched `sdk:claude-opus-5` literally, so the day Opus 6 shipped the badge would have
    stopped appearing — silently, in the one place meant to help a first-time Arbiter."""
    assert mc.recommended(_c("sdk", "claude-opus-6", "Claude Opus 6", "anthropic"))
    assert mc.recommended(_c("agy", "gemini-3.5-pro-high", "Gemini 3.5 Pro (High)", "google"),
                          critic=True)


def test_the_class_is_vendor_and_tier_together():
    """Cross-vendor is half the point of the pair, so an Opus-class reviewer is not the reviewer."""
    opus = _c("sdk", "claude-opus-5", "Claude Opus 5", "anthropic")

    assert mc.recommended(opus) and not mc.recommended(opus, critic=True)
    assert not mc.recommended(_c("sdk", "claude-sonnet-5", "Sonnet 5", "anthropic"))


def test_a_reduced_effort_tier_of_the_right_class_is_still_not_it():
    assert not mc.recommended(
        _c("agy", "gemini-3.1-pro-low", "Gemini 3.1 Pro (Low)", "google"), critic=True
    )


def test_an_unrecognised_name_gets_no_badge_rather_than_a_guess():
    unknown = _c("omp", "mistral-large", "Mistral Large", "mistral")

    assert mc.tier_of(unknown) == ""
    assert not mc.recommended(unknown) and not mc.recommended(unknown, critic=True)


def test_a_recommendation_that_matches_nothing_can_be_asked_about():
    """It will outlive Opus and Pro too. Going stale is not the failure; going stale quietly is."""
    only_unknown = [_c("omp", "mistral-large", "Mistral", "mistral")]

    assert not mc.recommendation_available(only_unknown)
    assert not mc.recommendation_available(only_unknown, critic=True)
    assert mc.recommendation_available(
        [_c("sdk", "claude-opus-9", "Opus 9", "anthropic")], critic=False
    )


# ---- a route this machine could have and does not (user, 2026-08-19) ---------------------------


def test_codex_is_listed_even_without_the_cli_marked_unavailable(monkeypatch):
    """Absence reads as "this does not exist". The user went looking for Codex in the picker, found
    no trace of it anywhere, and concluded the app could not do it — when what was missing was one
    CLI. So the rows stay, marked, and the picker greys them and says what they need."""
    # `cli_available`, not `shutil.which`: conftest already pins it to False for the whole suite,
    # so that no test reads whether this developer happens to have a CLI installed.
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: False)

    rows = model_choices.codex_choices()

    assert [c.model for c in rows] == list(model_choices.CODEX_MODELS)
    assert all(c.available is False for c in rows)
    assert all(c.route == "CODEX" for c in rows), "its own route, not omp's"


def test_with_the_cli_there_the_same_rows_are_usable(monkeypatch):
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "codex")

    rows = model_choices.codex_choices()

    assert rows and all(c.available is True for c in rows)


def test_an_unavailable_route_is_never_the_recommended_one(monkeypatch):
    """A greyed row must not make a recommendation look satisfied — that check exists to be loud
    when nothing matches."""
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: False)

    assert not any(
        model_choices.recommended(choice, critic=True)
        for choice in model_choices.codex_choices()
    )
