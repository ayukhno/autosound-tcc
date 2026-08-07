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
from dataclasses import dataclass
from typing import Literal

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
SDK_MODELS: tuple[tuple[str, str], ...] = (
    ("Claude Opus 5", "claude-opus-5"),
    ("Claude Sonnet 5", "claude-sonnet-5"),
    ("Claude Fable 5", "claude-fable-5"),
)

# The pair that is worth running today. Everything else in the picker is a real option and an
# experiment; this is the one combination the method has been driven with end to end, and it is
# marked so a first-time Arbiter does not have to infer it from a list of two hundred models.
RECOMMENDED_GENERATOR = "sdk:claude-opus-5"
RECOMMENDED_CRITIC_MARKERS = ("gemini", "pro")
#: …but not a reduced-effort tier of it. `agy` publishes Pro at several efforts, and "Pro (Low)"
#: is not the reviewer the pair was judged on.
RECOMMENDED_CRITIC_EXCLUDES = ("low", "flash", "lite")

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
    return [
        Choice(harness="sdk", model=model, label=label, provider="anthropic")
        for label, model in SDK_MODELS
    ]


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
_CLI_CACHE: dict[str, list[Choice]] = {}


def agy_choices() -> list[Choice]:
    """What the Antigravity CLI says it can run, from cache. Never blocks, never fetches."""
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
    fetched = _fetch_agy_choices()
    if fetched or "agy" not in _CLI_CACHE:
        _CLI_CACHE["agy"] = fetched
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
    if not active_omp:
        return entries
    try:
        catalogue = {choice.model: choice for choice in omp_catalogue()}
    except OmpCatalogueError:
        catalogue = {}
    for selector in active_omp:
        entries.append(
            catalogue.get(selector)
            or Choice(harness="omp", model=selector, label=selector, provider="")
        )
    return entries


def find(entries: list[Choice], key: str) -> Choice | None:
    return next((choice for choice in entries if choice.key == key), None)


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


def critic_vendor(choice: Choice) -> str:
    """Which vendor's transport the reviewer script would use for this model.

    Same resolution the script does, by the same markers — an unrecognised name falls to google,
    which is what every setup predating the parameter already meant.
    """
    haystack = f"{choice.provider} {choice.model}".lower()
    for marker, vendor in _CRITIC_VENDOR_MARKERS:
        if marker in haystack:
            return vendor
    return "google"


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
    return choices(active_omp) + agy_choices() + codex_choices()


def recommended(choice: Choice, critic: bool = False) -> bool:
    """Is this the combination the method has actually been driven with end to end.

    Claude Opus through the user's own login as Generator, a Gemini Pro through a subscription CLI
    as Critic. Everything else in the picker is a real option and an experiment — worth offering,
    not worth a first-time Arbiter having to infer the answer from two hundred rows.
    """
    if not critic:
        return choice.key == RECOMMENDED_GENERATOR
    if choice.harness not in ("agy", "omp"):
        return False
    name = f"{choice.model} {choice.label}".lower()
    if any(marker in name for marker in RECOMMENDED_CRITIC_EXCLUDES):
        return False
    return all(marker in name for marker in RECOMMENDED_CRITIC_MARKERS)
