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
import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

Harness = Literal["sdk", "omp"]

# What TCC drives through the Agent SDK. Claude only, and deliberately not read from a catalogue:
# these are the models this front-end is tested against, and the SDK resolves credentials from the
# user's own installation.
SDK_MODELS: tuple[tuple[str, str], ...] = (
    ("Claude Opus 5", "claude-opus-5"),
    ("Claude Sonnet 5", "claude-sonnet-5"),
    ("Claude Fable 5", "claude-fable-5"),
)

CATALOGUE_TIMEOUT_S = 20.0


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


class OmpCatalogueError(RuntimeError):
    """`omp models` could not be read. Carries its own message; usually omp is not installed."""


def sdk_choices() -> list[Choice]:
    return [
        Choice(harness="sdk", model=model, label=label, provider="anthropic")
        for label, model in SDK_MODELS
    ]


def omp_available() -> bool:
    return shutil.which("omp") is not None


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


def critic_reaches(choice: Choice) -> bool:
    """Whether the reviewer script can actually call this model, rather than fall to the clipboard.

    The Critic runs through the skill's `scripts/autosound_ai.py`, which is Gemini-shaped: one API
    function (`call_gemini_api`), and a CLI mode that looks for `agy`/`gemini` and invokes them
    with Gemini's argument shape. Everything else lands in clipboard mode — a designed fallback,
    not a failure, but the user should learn that before picking rather than after waiting.

    Raised as SCR-033. This function is the front-end apologising for it and should be deleted the
    day the reviewer's transport becomes a parameter.
    """
    haystack = f"{choice.provider} {choice.model}".lower()
    return "gemini" in haystack or "google" in haystack


def critic_choices(active_omp: list[str]) -> list[Choice]:
    """The same registry as the Generator's, so one list means one place to configure.

    A different vendor from the Generator is the method's own requirement (SKILL.md, three roles),
    not something to enforce here: the Arbiter can legitimately want the same family for a
    second opinion on a narrow question, and a picker that silently omits options is harder to
    reason about than one that shows them.
    """
    return choices(active_omp)
