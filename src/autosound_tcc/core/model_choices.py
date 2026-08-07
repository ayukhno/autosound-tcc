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
    """The same registry as the Generator's, so one list means one place to configure.

    A different vendor from the Generator is the method's own requirement (SKILL.md, three roles),
    not something to enforce here: the Arbiter can legitimately want the same family for a
    second opinion on a narrow question, and a picker that silently omits options is harder to
    reason about than one that shows them.
    """
    return choices(active_omp)
