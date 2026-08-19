"""The glossary's own groups — Ws, SW+Ws, a whole side, ALL — as the titles REW actually holds.

The curve window used to be able to ask one question: "these two measurements, how far apart".
The question a tune is argued about is bigger than that (user, 2026-08-18): what do the woofers do
together, the mids, sub+woofers, a whole side, everything — **before** anything is typed into the
DSP and the car is re-measured. Those names are not free text: they are the project's glossary,
which the skill writes per car (`naming.Glossary`, SCR-008) and which already knows that this car
has no rear speakers and a disconnected centre.

So this module is a translator and nothing else. It takes a group the tuner picked and a DSP
config version, and answers with the REW titles of that group's members — plus, just as important,
the ones that are NOT there. A sum of a group with a member missing is a sum of a different thing,
and `core.curve_sum` cannot catch it: that module only ever sees what it was handed.

Two rules it follows rather than invents:

* **The grammar is the skill's.** Titles are built with `naming.generate_name` and read with
  `naming.parse_name`/`name_key`, so `w-L_2 (sw)` and `w-L_02 (sw)` are one measurement — REW
  titles are typed by hand and zero-padding is common. A second grammar here is how a front-end
  and a method start disagreeing about what a name means.
* **Only `(sw)` captures.** A sum needs phase, and an MMM/RTA capture has none (`rew-api-quirks.md`
  and `curve_sum.summability`, which refuses one by name). Asking for the sweeps is therefore not a
  filter, it is what the group MEANS here.

Degrades to nothing, deliberately and in three ways: no skill installed, no glossary in the
project, or a glossary with no groups in it. Each answers "no groups" and leaves the caller's other
selector working, because a curve window that cannot open without a project file is worse than one
that offers one control fewer.

stdlib plus the skill; no Qt, no numpy — this is read by a dialog but it is not a widget.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from autosound_tcc.core import config, vendor_loader

#: The glossary's group buckets, in the order they are offered. Pairs first because a pair is the
#: commonest question by a distance; ALL and its friends last because they are the widest.
KINDS = ("pairs", "joints", "sides", "combos")

#: The capture method a sum is built from. See the module docstring: this is not a filter over a
#: wider set, it is the only method that carries a phase.
METHOD = "sw"


@dataclass(frozen=True)
class Group:
    """One named set of channels out of the glossary: `("pairs", "Ws", ("w-L", "w-R"))`."""

    kind: str
    name: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class Resolved:
    """A group at one config version, split into what REW has and what it does not.

    `missing` holds the titles the members WOULD have had (`generate_name`), not bare codes: the
    tuner is going to go and look for them in REW, and a code is not what they will be reading
    there.
    """

    group: Group
    version: str
    titles: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing


def _version_key(version: str) -> tuple[int, int, str]:
    """Sort key for a config version: numeric order, with `final` after every number.

    `final` is a legal version in the grammar (phase 3), and comparing it as a string would file it
    between `_1` and `_2`. A version that is neither a number nor `final` sorts before everything,
    because it is not one of ours and must not win "the newest".
    """
    text = str(version)
    if text.isdigit():
        return (1, int(text), text)
    if text == "final":
        return (2, 0, text)
    return (0, 0, text)


class GlossaryGroups:
    """The project's glossary, ready to answer "which titles is this group, at this version".

    Built by `load()` rather than by hand, and safe to build when there is no skill and no project:
    `available` is then False and `groups()` is empty. Nothing here talks to REW — the caller
    passes in the titles REW reported, because this window already has that list and a module that
    opened its own HTTP connection would be a second answer to "what does REW hold".
    """

    def __init__(self, naming=None, glossary=None) -> None:
        self._naming = naming
        self._glossary = glossary

    @classmethod
    def load(cls, project_dir: Optional[Path] = None) -> "GlossaryGroups":
        """Read the glossary for `project_dir`, or come back empty-handed without complaining.

        `Glossary.for_project` already accepts both shapes the project can carry — a standalone
        `glossary.json` and the `glossary` key of `project.json` (SCR-011) — and answers with an
        empty glossary rather than raising when there is neither.
        """
        try:
            naming = vendor_loader.load_naming()
        except Exception:  # noqa: BLE001 — no skill is a state this window renders, not an error
            return cls()
        try:
            glossary = naming.Glossary.for_project(str(project_dir or config.project_dir()))
        except Exception:  # noqa: BLE001 — an unreadable project must not take the window down
            return cls()
        return cls(naming, glossary)

    @property
    def available(self) -> bool:
        """Whether there is a glossary with at least one group in it worth offering."""
        return bool(self.groups())

    def groups(self) -> tuple[Group, ...]:
        """Every group this car has, pairs first, in the glossary's own order within each kind."""
        if self._glossary is None:
            return ()
        out: list[Group] = []
        for kind in KINDS:
            for name, members in (getattr(self._glossary, kind, None) or {}).items():
                codes = tuple(str(code) for code in (members or []) if str(code))
                if name and codes:
                    out.append(Group(kind=kind, name=str(name), members=codes))
        return tuple(out)

    def facts(self, title: str) -> Optional[dict]:
        """A REW title read with the skill's grammar AND this car's codes, or None if not ours.

        The glossary is what separates the joint `L w+m` from the side `L` with a stray modifier,
        which is exactly the ambiguity a group picker would otherwise walk into.
        """
        if self._naming is None:
            return None
        try:
            return self._naming.parse_name(title, self._glossary)
        except Exception:  # noqa: BLE001 — a REW list holds imports and hand-typed names too
            return None

    def title_for(self, code: str, version: str) -> str:
        """What the sweep of `code` at `version` is called, in the skill's own words."""
        if self._naming is None:
            return f"{code}_{version} ({METHOD})"
        try:
            return str(self._naming.generate_name(code, version, METHOD))
        except Exception:  # noqa: BLE001 — a code the grammar rejects still has to be nameable
            return f"{code}_{version} ({METHOD})"

    def versions_in(self, titles: Sequence[str], codes: Sequence[str] = ()) -> tuple[str, ...]:
        """Every config version REW holds a sweep for, oldest first; `codes` narrows it to a group.

        Narrowed by code because "the newest version" is a question about the drivers being summed:
        a car whose sub was re-measured at `_04` while the tweeters stopped at `_02` has no single
        newest, and offering `_04` for a group of tweeters would offer a version none of them has.

        `_2` and `_02` come back as ONE version, spelled the way the first title that carries it
        spells it. They ARE one — that is why the skill's parser reports `version_n` at all — and
        offering both would let a tuner pick the spelling that happens not to match the sub.
        """
        wanted = {self._resolve(code) for code in codes}
        found: dict[object, str] = {}
        for title in titles:
            parsed = self.facts(title)
            if not parsed or parsed.get("method") != METHOD:
                continue
            if wanted and (parsed.get("code_current") or parsed.get("code")) not in wanted:
                continue
            version = parsed.get("version")
            if version:
                found.setdefault(self._version_n(version), str(version))
        return tuple(sorted(found.values(), key=_version_key))

    def version_of(self, titles: Sequence[str]) -> Optional[str]:
        """The one config version all of `titles` are on, or None when they disagree.

        This is the version a group picker starts from: whatever is on screen right now is the
        round the tuner is working in, and moving them to another one unasked would answer a
        different question than the one they are looking at.

        Compared on the version NUMBER, so a round captured as `w-L_2` and `w-R_02` is one round
        rather than a disagreement — which is the same reason `name_key` exists.
        """
        versions = set()
        spelling = None
        for title in titles:
            parsed = self.facts(title)
            if not parsed or not parsed.get("version"):
                return None
            versions.add(self._version_n(parsed["version"]))
            spelling = spelling or str(parsed["version"])
        if len(versions) != 1:
            return None
        return spelling

    def resolve(
        self, group: Group, version: str, available: Sequence[str]
    ) -> Resolved:
        """`group` at `version` as REW titles, in member order, plus the members REW does not have.

        Matched on the skill's `name_key` rather than on the string, so `_2` and `_02` are the same
        version and a channel renamed mid-project still matches its old captures (SCR-039). A
        capture carrying a MODIFIER (`w-L FX_2 (sw)`) is deliberately not accepted as the member's
        sweep: the modifier says the driver was measured with something else going on, and quietly
        summing it would be a sum of a car nobody configured.
        """
        by_key: dict[tuple, str] = {}
        for title in available:
            parsed = self.facts(title)
            key = self._naming.name_key(parsed) if (parsed and self._naming) else None
            if key is not None:
                # First writer wins: two REW titles with the same key are the same measurement
                # zero-padded two ways, and either one plots the same curve.
                by_key.setdefault(key, title)
        titles: list[str] = []
        missing: list[str] = []
        for code in group.members:
            key = (self._resolve(code), None, self._version_n(version), METHOD)
            found = by_key.get(key)
            if found:
                titles.append(found)
            else:
                missing.append(self.title_for(code, version))
        return Resolved(group=group, version=str(version), titles=tuple(titles),
                        missing=tuple(missing))

    # ---- internals -------------------------------------------------------

    def _resolve(self, code: str) -> str:
        """A code as the channel is named TODAY, so a rename does not hide its own captures."""
        if self._glossary is None:
            return code
        try:
            return str(self._glossary.resolve_code(code))
        except Exception:  # noqa: BLE001 — an unknown code is not ours to reinterpret
            return code

    @staticmethod
    def _version_n(version: str):
        """`name_key`'s view of a version: the number where there is one, the word otherwise."""
        text = str(version)
        return int(text) if text.isdigit() else text
