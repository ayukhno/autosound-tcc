"""Which model runs the tuning conversation, and which harness carries it.

The two are one choice, not two, and it is the user's to make explicitly rather than TCC's to
infer. The split behind it is fixed (`spike/HANDOFF.md` §5-ter): Claude runs through the Agent SDK
against the user's own CLI, because that is the path whose licensing is settled; everything else
runs through omp. Picking "Claude Opus 5" therefore picks the SDK, and picking a Gemini or a local
model picks omp — but the user picks a *model*, and the harness follows.

**omp's list is not TCC's to curate.** `omp models` reports several hundred, most of which nobody
has credentials for; showing all of them would make the picker useless, and picking a subset for
the user would be TCC deciding what they are allowed to run. So the user marks models active and
TCC remembers the marks. Nothing here reads or writes credentials — omp's broker owns those, and
whether a marked model actually answers is between the user and their own accounts.

`cost` comes back with the catalogue, so a free model is visibly free at the moment of choosing.
That is the axis the harness was chosen on and it belongs in front of the person paying.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from autosound_tcc.core import claude_sdk, model_overrides

# How a model is reached — and, more to the point, WHOSE BILL it lands on. This is the axis the
# picker was missing: "Gemini 3.1 Pro" through a desktop subscription and the same model through
# omp's broker are the same words and two different accounts, and the one that quietly spends API
# credit is the one nobody notices until the balance goes negative (reported 2026-08-07, on a
# Google AI Studio account, by a user who also had a subscription and free OAuth access).
Harness = Literal["sdk", "omp", "agy", "codex"]

#: Prefix shown in front of every picker entry, and what it means for billing. Every route is
#: labelled, not just the SDK: an unlabelled entry reads as "the normal one", which is exactly the
#: assumption that costs money.
ROUTES: dict[str, tuple[str, str]] = {
    "sdk": ("SDK", "your own Claude login, through the Agent SDK"),
    "agy": ("AGY", "the Antigravity CLI on this machine — its own subscription"),
    "codex": ("CODEX", "the Codex CLI on this machine — its own ChatGPT login"),
    "omp": ("OMP", "omp's broker — whichever API credentials omp holds, metered"),
}

# What TCC drives through the Agent SDK. Claude only, and deliberately not read from a catalogue:
# these are the models this front-end is tested against, and the SDK resolves credentials from the
# user's own installation.
#: When this list was last checked against what Anthropic actually serves. It is a floor for
#: installs that cannot ask (no API key), and it is expected to age — see `sdk_choices`.
SDK_MODELS_VERIFIED = "2026-08"
SDK_MODELS: tuple[tuple[str, str], ...] = (
    ("Claude Opus 5", "claude-opus-5"),
    ("Claude Sonnet 5", "claude-sonnet-5"),
    ("Claude Fable 5", "claude-fable-5"),
)

# The pair that is worth running today — named as a CLASS, not as two model names.
#
# It was `sdk:claude-opus-5` and a literal search for "gemini"+"pro", and that has a short shelf
# life: the day Gemini 3.7 ships, the recommendation stops matching anything and does so SILENTLY
# — no error, no warning, just nothing bold in a list of two hundred rows. Same failure class as
# every "declared and not enforced" rule found this week, in the one place meant to help a
# first-time Arbiter.
#
# A vendor and a tier survive a version bump, because that is what the experience is actually
# about: Opus-class generator, Pro-class reviewer, cross-vendor. Nobody ever concluded "3.1
# specifically". And when Opus and Pro themselves are gone — they will be — the recommendation
# matches nothing, `recommendation_available()` says so out loud, and the date below says how old
# the claim is. Going stale is not the failure; going stale quietly is.
RECOMMENDED_SINCE = "2026-08"
RECOMMENDED = {
    "generator": ("anthropic", "opus"),
    "critic": ("google", "pro"),
}
#: …but not a reduced-effort tier of it. `agy` publishes Pro at several efforts, and "Pro (Low)"
#: is not the reviewer the pair was judged on.
RECOMMENDED_CRITIC_EXCLUDES = ("low", "flash", "lite")

#: Model TIERS, by the marker that names them. Ordered: the first match wins, so a longer or more
#: specific token comes before one that could also appear inside it. `""` for anything
#: unrecognised — the same rule as `vendor_of`, and for the same reason: a guess here would put a
#: recommendation badge on a model nobody has judged.
_TIER_MARKERS = (
    ("opus", "opus"), ("sonnet", "sonnet"), ("haiku", "haiku"), ("fable", "fable"),
    ("pro", "pro"), ("flash", "flash"), ("lite", "lite"),
    ("codex", "codex"), ("gpt-oss", "oss"),
)


def tier_of(choice: "Choice") -> str:
    """Which class of model this is (`opus`, `pro`, `flash`…), or "" when the name does not say."""
    haystack = f"{choice.model} {choice.label}".lower()
    return next((tier for marker, tier in _TIER_MARKERS if marker in haystack), "")

# How hard the Generator is asked to think. Three levels, not the full ladder the CLIs expose:
# **below `high` is not a tuning setting** (user, 2026-08-07). A cheap pass reads as competence —
# the case this whole harness is built around is a model that closed phases -1..3 in one sitting and
# reported a finished tune, crossovers and delays and a listening verdict, on a car nobody sat in.
#
# `xhigh` is the default because it has margin; `max` exists because some steps genuinely need it
# and **nothing escalates on its own**. Claude varies its own thinking depth per turn (adaptive
# thinking), but only UNDER the level set here — a session started at `xhigh` never reaches `max`,
# however hard the work turns out to be. So `max` is a choice made when the session starts, which
# is also the only time it CAN be made: the Agent SDK takes effort at client construction, so
# changing it mid-tune means dropping the session.
#
# The same three words mean the same thing on both routes that take a flag (`ClaudeAgentOptions`
# and `omp --thinking`). `agy` is not one of them — it publishes each tier as its own model
# (`gemini-3.1-pro-high`), so there the effort IS the model name and `critic_choices` already picks
# the only sensible one. Codex is the skill's to set (`AUTOSOUND_CRITIC_EFFORT`).
EFFORT_LEVELS: tuple[str, ...] = ("high", "xhigh", "max")
EFFORT_DEFAULT = "xhigh"


def resolve_effort(value: Optional[str]) -> str:
    """One reading of a stored effort, for every consumer.

    An unset or unrecognised value reads as the default rather than being passed through: these
    strings reach a subprocess argument and a model API, and "the level I typed is not a level"
    should not be discovered there.
    """
    level = (value or "").strip().lower()
    return level if level in EFFORT_LEVELS else EFFORT_DEFAULT


CATALOGUE_TIMEOUT_S = 20.0
# Long enough for a CLI that shells out to list its own models, short enough that a hung binary
# does not hold the picker open.
CLI_TIMEOUT_S = 15.0

#: What Codex offers. Hardcoded because `codex models` needs a terminal (it answers "stdin is not
#: a terminal" when driven), unlike `agy models` which prints a plain list.
CODEX_MODELS: tuple[str, ...] = ("gpt-5.2-codex", "gpt-5.2")


@dataclass(frozen=True)
class Choice:
    """One entry in the picker: a model, and the harness that runs it."""

    harness: Harness
    model: str
    label: str
    provider: str = ""
    free: bool = False

    @property
    def key(self) -> str:
        """Stable identity for persistence — `omp:google/gemini-3.1-pro-preview`."""
        return f"{self.harness}:{self.model}"

    @property
    def route(self) -> str:
        """The prefix a reader sees: SDK / AGY / CODEX / OMP."""
        return ROUTES.get(self.harness, (self.harness.upper(), ""))[0]

    @property
    def route_note(self) -> str:
        """Whose bill this lands on, in one clause, for the tooltip."""
        return ROUTES.get(self.harness, ("", ""))[1]


class OmpCatalogueError(RuntimeError):
    """`omp models` could not be read. Carries its own message; usually omp is not installed."""


def sdk_choices() -> list[Choice]:
    """Claude models: what the Models API reported if it could be asked, then the shipped list.

    Empty when `claude-agent-sdk` is not installed — the route genuinely does not exist then.

    The shipped list is a floor, not the answer. It is dated (`SDK_MODELS_VERIFIED`) and it will
    go stale — every name in it retires eventually. Three things keep an install working past that
    without anybody shipping an update: the API refresh below when this machine has a key, the
    local overrides file, and the replacement offered when a stored choice stops resolving.
    """
    if not claude_sdk.available():
        # The SDK is an extra. Offering Claude models on an install that cannot reach them is the
        # same failure as the aliases were: a picker that says a route exists when it does not
        # (2026-08-12). Nothing here is hidden from a Claude user — for them it is installed.
        return []
    fetched = list(_CLI_CACHE.get("sdk", []))
    known = {choice.model for choice in fetched}
    for label, model in SDK_MODELS:
        if model not in known:
            fetched.append(
                Choice(harness="sdk", model=model, label=label, provider="anthropic")
            )
    return fetched


def _fetch_sdk_choices() -> list[Choice]:
    """Ask the Models API which Claude models exist — when this machine has a key.

    A **bonus layer, not the mechanism**: the SDK route deliberately runs on the user's own `claude`
    login rather than an API key (TCC authenticates to nothing — that is the licensing position),
    so most installs will not have `ANTHROPIC_API_KEY` set and this returns nothing. Those installs
    survive a retirement through the overrides file instead. Where a key does exist, this keeps the
    list current for free.

    Raw HTTP on purpose: TCC has no Anthropic SDK dependency, and taking one on for a single list
    call would be a package to maintain in exchange for a GET.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return []
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/models?limit=100",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(request, timeout=CLI_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — no key, no network, a 401: all mean "cannot refresh"
        return []
    out: list[Choice] = []
    for entry in payload.get("data") or []:
        model = str(entry.get("id") or "")
        if not model:
            continue
        out.append(
            Choice(
                harness="sdk",
                model=model,
                label=str(entry.get("display_name") or model),
                provider="anthropic",
            )
        )
    return out


def omp_available() -> bool:
    return shutil.which("omp") is not None


def cli_available(harness: str) -> bool:
    """Is this route's binary on PATH. Cheap: no subprocess, so the picker can ask per entry."""
    return shutil.which({"agy": "agy", "codex": "codex"}.get(harness, "")) is not None


#: Last good answer from each CLI that has to be asked over the network. Populated by
#: `refresh_cli_catalogue()` on a background thread; read by the picker, which must never block.
#: A failed refresh keeps the previous answer rather than emptying the list — `agy models` fetches
#: over the network, and a picker that drops a whole route because one call timed out is a picker
#: that teaches people the route does not exist.
#:
#: "Previous answer" used to mean previous IN THIS PROCESS, which is the same as no memory at all:
#: every launch started empty, the worker filled it a second or two later, and any launch where
#: the fetch was slow or came back empty ran the whole session with the route missing. What that
#: looks like from the outside is a picker with empty lists, then a recommended pair that reports
#: itself absent (user, 2026-08-11) — and worse, downstream: the stored critic key stops
#: resolving, TCC offers a replacement, and the reviewer quietly becomes the Generator's own
#: vendor. So the cache is on disk now, and a route that has ever answered never silently
#: disappears again.
_CLI_CACHE: dict[str, list[Choice]] = {}
#: Entries served from the file rather than confirmed this launch. The picker marks them: an
#: option that may not work is a different thing from one that will, and both are different from
#: an option that is not shown at all.
_UNCONFIRMED: set[str] = set()


def catalogue_cache_path() -> Path:
    """Beside `models.json` — same directory, same reason: a fact about this machine, not about
    any one project."""
    return model_overrides.config_dir() / "cli-catalogue.json"


def _load_cached_catalogue() -> None:
    """Seed `_CLI_CACHE` from disk. Called once, lazily, before the first read.

    Forgiving in the same way `model_overrides.load()` is: this file exists to keep a picker
    populated, so a malformed one must read as "no memory" rather than stop the window opening.
    """
    if _CLI_CACHE:
        return
    try:
        data = json.loads(catalogue_cache_path().read_text(encoding="utf-8"))
        routes = data["routes"] if isinstance(data, dict) else {}
    except (OSError, ValueError, KeyError, TypeError):
        return
    for route, rows in (routes or {}).items():
        entries = [
            Choice(
                harness=str(row.get("harness") or route),
                model=str(row.get("model") or ""),
                label=str(row.get("label") or ""),
                provider=str(row.get("provider") or ""),
            )
            for row in rows or []
            if isinstance(row, dict) and row.get("model")
        ]
        if entries:
            _CLI_CACHE[str(route)] = entries
            _UNCONFIRMED.update(choice.key for choice in entries)


def _save_cached_catalogue() -> None:
    path = catalogue_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "routes": {
                route: [
                    {"harness": c.harness, "model": c.model,
                     "label": c.label, "provider": c.provider}
                    for c in entries
                ]
                for route, entries in _CLI_CACHE.items()
            },
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass  # a cache that cannot be written is a slower picker, not a broken one


def unconfirmed(choice: Choice) -> bool:
    """Was this entry remembered from a previous launch rather than confirmed by the CLI now."""
    return choice.key in _UNCONFIRMED


def agy_choices() -> list[Choice]:
    """What the Antigravity CLI says it can run, from cache. Never blocks, never fetches."""
    _load_cached_catalogue()
    return list(_CLI_CACHE.get("agy", []))


def cli_routes_without_models() -> list[str]:
    """CLIs that are installed and told us nothing.

    Worth saying out loud rather than rendering as absence: `agy models` fetches over the network
    and has been seen come back empty, and a route that silently disappears is exactly how a user
    ends up believing it does not exist and paying for the metered one instead.
    """
    return [
        harness
        for harness in ("agy",)
        if cli_available(harness) and not _CLI_CACHE.get(harness)
    ]


def refresh_cli_catalogue() -> dict[str, list[Choice]]:
    """Ask every CLI that needs asking, and cache the answer. **Call this off the GUI thread.**

    `agy models` fetches over the network and has been seen take seconds; the picker is built on
    the GUI thread at window construction, so asking there would freeze the window on launch.
    """
    _load_cached_catalogue()
    for route, fetch in (("agy", _fetch_agy_choices), ("sdk", _fetch_sdk_choices)):
        fetched = fetch()
        # A failed refresh keeps the previous answer; only a first-ever failure stores the empty
        # list, and for `sdk` that is the ordinary case (no API key — see `_fetch_sdk_choices`).
        if fetched or route not in _CLI_CACHE:
            _CLI_CACHE[route] = fetched
        if fetched:
            # Confirmed by the CLI just now: these stop being "remembered from last time".
            _UNCONFIRMED.difference_update(choice.key for choice in fetched)
    _save_cached_catalogue()
    return dict(_CLI_CACHE)


def _fetch_agy_choices() -> list[Choice]:
    """Asked rather than hardcoded, because `agy models` prints its own list and a stale hardcoded
    selector is a model that fails at call time instead of being absent at pick time. An agy model
    is reached through a subscription the user already pays for, which is the whole reason it
    belongs in this picker beside omp's metered catalogue.
    """
    if not cli_available("agy"):
        return []
    # Twice, because the FIRST `agy models` in a fresh process comes back empty often enough to
    # matter (it prints "Fetching available models..." and returns 0 with nothing on either
    # stream); a second call moments later answers. Without the retry the route appeared and
    # disappeared between launches, which is indistinguishable from "not installed" and sends
    # somebody to the metered catalogue instead.
    proc = None
    for _ in range(2):
        try:
            proc = subprocess.run(
                ["agy", "models"], capture_output=True, text=True, timeout=CLI_TIMEOUT_S
            )
        except (subprocess.TimeoutExpired, OSError):
            return []
        if proc.returncode == 0 and (proc.stdout or "").strip():
            break
    if proc is None or proc.returncode != 0:
        return []
    # Both streams: with stdout on a pipe rather than a terminal, `agy` puts part of its output on
    # stderr -- including, sometimes, the catalogue itself next to its "Fetching available
    # models..." progress line. Reading stdout alone made the whole route vanish at random, which
    # looked exactly like "this CLI is not installed".
    out: list[Choice] = []
    for line in ((proc.stdout or "") + "\n" + (proc.stderr or "")).splitlines():
        # `<selector>\t<display name>` -- the display name carries agy's own wording for the
        # effort tier ("Gemini 3.1 Pro (High)"), which is what the user recognises, while the
        # selector is what the CLI is actually invoked with.
        selector, _, label = line.partition("\t")
        selector, label = selector.strip(), label.strip()
        if not selector or " " in selector:
            continue
        provider = "google" if "gemini" in selector else (
            "anthropic" if "claude" in selector else ""
        )
        out.append(
            Choice(harness="agy", model=selector, label=label or selector, provider=provider)
        )
    return out


def codex_choices() -> list[Choice]:
    """What the Codex CLI offers. Hardcoded — `codex models` refuses without a terminal."""
    if not cli_available("codex"):
        return []
    return [
        Choice(harness="codex", model=model, label=model, provider="openai")
        for model in CODEX_MODELS
    ]


def omp_catalogue() -> list[Choice]:
    """Every model omp knows about, for the "which of these do I actually use" dialog.

    Several hundred entries. This is the list to *choose from*, never the list to show in the
    picker -- see `choices`.
    """
    if not omp_available():
        raise OmpCatalogueError("omp is not installed — brew install can1357/tap/omp")
    try:
        proc = subprocess.run(
            ["omp", "models", "--json"],
            capture_output=True,
            text=True,
            timeout=CATALOGUE_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise OmpCatalogueError(str(exc)) from None
    if proc.returncode != 0:
        raise OmpCatalogueError((proc.stderr or proc.stdout or "").strip()[:300])
    try:
        models = json.loads(proc.stdout).get("models") or []
    except ValueError:
        raise OmpCatalogueError("omp models --json did not return JSON") from None

    out: list[Choice] = []
    for entry in models:
        selector = entry.get("selector") or entry.get("id")
        if not selector:
            continue
        cost = entry.get("cost") or {}
        out.append(
            Choice(
                harness="omp",
                model=str(selector),
                label=str(entry.get("name") or selector),
                provider=str(entry.get("provider") or ""),
                # Free at the point of use: either a zero-cost model or one covered by a
                # subscription the user already pays for. The catalogue only tells us the first.
                free=not (cost.get("input") or cost.get("output")),
            )
        )
    return out


def choices(active_omp: list[str]) -> list[Choice]:
    """What the picker shows: the SDK's Claude models, then the omp models the user marked.

    `active_omp` holds selectors (`google/gemini-3.1-pro-preview`). A marked model that omp no
    longer reports is still offered, labelled by its selector -- dropping it silently would make a
    picker that quietly forgets what the user chose, and the failure it prevents (a model that
    errors when used) is louder and easier to act on.
    """
    entries = sdk_choices()
    if active_omp:
        try:
            catalogue = {choice.model: choice for choice in omp_catalogue()}
        except OmpCatalogueError:
            catalogue = {}
        for selector in active_omp:
            entries.append(
                catalogue.get(selector)
                or Choice(harness="omp", model=selector, label=selector, provider="")
            )
    return _apply_overrides(entries)


def _apply_overrides(entries: list[Choice]) -> list[Choice]:
    """Fold in what this machine says: models it can run that no catalogue reports, and ones it
    should stop offering (`model_overrides`).

    Additions come last and never replace a catalogue entry of the same key — a hand-written row
    that shadowed the real one would be a silent lie about which model is being run.
    """
    data = model_overrides.load()
    hidden = model_overrides.hidden_keys(data)
    out = [choice for choice in entries if choice.key not in hidden]
    known = {choice.key for choice in out}
    for row in model_overrides.added_entries(data):
        harness = str(row.get("harness") or "omp")
        model = str(row["model"])
        key = f"{harness}:{model}"
        if key in known or key in hidden:
            continue
        out.append(
            Choice(
                harness=harness,  # type: ignore[arg-type]
                model=model,
                label=str(row.get("label") or model),
                provider=str(row.get("provider") or ""),
            )
        )
        known.add(key)
    return out


def find(entries: list[Choice], key: str) -> Choice | None:
    return next((choice for choice in entries if choice.key == key), None)


@dataclass(frozen=True)
class Resolved:
    """What a stored model key turned out to mean on THIS machine.

    Three answers, and the caller must be able to tell them apart:

    * `choice` set, `alias` None — the ordinary case.
    * `choice` set, `alias` set — the machine sends this key somewhere else. The caller should say
      so rather than quietly run a different model than the record names.
    * `choice` None — the key names nothing this install can run. Not an error to swallow: it is
      the moment to tell the user and offer a replacement, which is what fills the overrides file.
    """

    key: str
    choice: Optional[Choice] = None
    alias: "Optional[model_overrides.Alias]" = None

    @property
    def ok(self) -> bool:
        return self.choice is not None

    @property
    def note(self) -> str:
        """One clause for a record or a strip: what was asked for, and what will actually run."""
        if self.alias is None or self.choice is None:
            return ""
        return (
            f"{self.alias.from_key} → {self.choice.key}"
            + (f" ({self.alias.why})" if self.alias.why else "")
        )


def resolve(entries: list[Choice], key: str) -> Resolved:
    """Turn a stored key into something this machine can actually run — the one indirection.

    Every consumer goes through here (the pickers, session start, the Critic call, `get_tcc_state`)
    so that a model retiring is handled in ONE place. Without it, each call site reads the key its
    own way and there is nowhere to put a substitution — which is how a stored name that no longer
    exists becomes a dead button in one place and silently the first entry in another.
    """
    if not key:
        return Resolved(key="")
    resolved, alias = model_overrides.resolve_key(key)
    return Resolved(key=resolved, choice=find(entries, resolved), alias=alias)


# What the skill's reviewer script needs per vendor, mirroring its own provider table (SCR-033):
# an API key in the environment, or one of that vendor's CLIs on PATH. Kept here rather than read
# out of the script because this runs on the GUI thread while a combo box is being filled — the
# answer has to be instant, and it decides a label, not a call.
_CRITIC_TRANSPORTS = {
    "google": (("GEMINI_API_KEY",), ("agy", "gemini")),
    "anthropic": (("ANTHROPIC_API_KEY",), ("claude",)),
    "openai": (("OPENAI_API_KEY",), ("codex",)),
}
_CRITIC_VENDOR_MARKERS = (
    ("gemini", "google"), ("google", "google"),
    ("claude", "anthropic"), ("opus", "anthropic"), ("sonnet", "anthropic"),
    ("haiku", "anthropic"), ("fable", "anthropic"),
    ("gpt", "openai"), ("o1", "openai"), ("o3", "openai"), ("codex", "openai"),
)


def vendor_of(choice: Choice) -> str:
    """The vendor a model name actually names, or "" when no marker matches.

    Split out from `critic_vendor` because the two questions differ where it matters. "Which
    transport do we call?" needs an answer for every model, so it falls back. "Are these two models
    the same vendor?" must NOT: with a fallback, two unrecognised names look like a matched pair
    and the caller warns about something it does not know.
    """
    haystack = f"{choice.provider} {choice.model}".lower()
    return next((vendor for marker, vendor in _CRITIC_VENDOR_MARKERS if marker in haystack), "")


def critic_vendor(choice: Choice) -> str:
    """Which vendor's transport the reviewer script would use for this model.

    Same resolution the script does, by the same markers — an unrecognised name falls to google,
    which is what every setup predating the parameter already meant.
    """
    return vendor_of(choice) or "google"


def critic_reaches(choice: Choice) -> bool:
    """Whether the reviewer script can actually call this model, rather than fall to the clipboard.

    Since SCR-033 the script's transport is a parameter, so this is no longer "is it Gemini" — it
    is "does this machine have that vendor's key or CLI". Clipboard mode stays a designed fallback
    rather than a failure; the point is that the Arbiter learns which it will be before picking,
    not after waiting.
    """
    keys, binaries = _CRITIC_TRANSPORTS.get(critic_vendor(choice), ((), ()))
    if any(os.environ.get(name) for name in keys):
        return True
    return any(shutil.which(binary) for binary in binaries)


def critic_choices(active_omp: list[str]) -> list[Choice]:
    """The Generator's registry PLUS whatever CLI is installed on this machine.

    A different vendor from the Generator is the method's own requirement (SKILL.md, three roles),
    not something to enforce here: the Arbiter can legitimately want the same family for a
    second opinion on a narrow question, and a picker that silently omits options is harder to
    reason about than one that shows them.

    The CLI routes appear HERE and not in the Generator list because the reviewer is a one-shot
    call the skill's own script already knows how to make (`autosound_ai.py`, SCR-033), while a
    Generator has to hold a session and talk to TCC's MCP server — which `agy` and `codex` may
    well be able to do, but not by anything TCC has wired yet.
    """
    return _apply_overrides(choices(active_omp) + agy_choices() + codex_choices())


def recommended(choice: Choice, critic: bool = False) -> bool:
    """Is this model of the class the method has actually been driven with end to end.

    An Opus-class generator on the user's own login, a Pro-class reviewer from another vendor.
    Matched by vendor and tier rather than by name, so a new version of either is recommended the
    day it appears and nobody has to ship a release for it. Everything else in the picker is a
    real option and an experiment.
    """
    vendor, tier = RECOMMENDED["critic" if critic else "generator"]
    if vendor_of(choice) != vendor or tier_of(choice) != tier:
        return False
    if critic:
        name = f"{choice.model} {choice.label}".lower()
        if any(marker in name for marker in RECOMMENDED_CRITIC_EXCLUDES):
            return False
    return True


def recommendation_available(entries: list[Choice], critic: bool = False) -> bool:
    """Does the recommended CLASS match anything this machine can actually offer.

    Asked separately because the answer "no" has to be visible. A recommendation that quietly
    matches nothing is indistinguishable from having no recommendation at all — and that is the
    state this whole scheme exists to make loud, since the classes it names will retire too.
    """
    return any(recommended(choice, critic=critic) for choice in entries)
