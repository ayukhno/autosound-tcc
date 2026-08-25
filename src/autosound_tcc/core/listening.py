"""What to judge in a track while listening, and the words for saying it.

Phase 4 is the ear's phase: play a track, decide whether one thing about the sound is right or
wrong, write it down. The hard part is not the deciding — it is knowing what THIS track was chosen
to expose, and having words for the answer that mean the same thing tomorrow.

**The words are the method's and this module never restates them.** `rew_tool/listening.py` parses
the cheat sheet and the track index and returns the vocabulary; here it is only reshaped into what
a tree widget can show. That split was argued out with the skill session on 2026-08-25 and it has
a specific shape worth keeping in view:

* a **characteristic** owns the wording — its short label, and the two sentences for "sounds
  right" / "sounds wrong". Nothing else may carry a second copy of them. Before that rule the same
  criterion lived in three places of one file and had already drifted three ways ("holds <40 vs
  dries up" / "holds, doesn't drone or dry up" / "holds vs dries up").
* a **track** owns only what is true of the track: library, number, artist, title, version.
* a **link** owns what is specific to hearing that characteristic ON that track — where in the
  track to listen (`cue`), and a timecode when there is one. It is the link and not the track that
  carries them, because one track exposes several characteristics and usually only one of them
  happens at a stated moment.

**A track is never named by its bare number.** The method's own rule (`test-tracks.md`, "Disc
identity — the number is not the track"): compilations reuse each other's numbering, so `#3` on
somebody's disc is not `#3` on ours. `track_label` therefore always says library, number, artist
and title together.

**Translation falls back rather than blanks.** `translated=False` on an entry means the method has
no text in this language yet and the English is being shown — the panel says so instead of
displaying an empty row, because a translation and a new id arrive in different commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Optional

from autosound_tcc.core import vendor_loader

_MODULE = "listening.py"

#: The routes the cheat sheet defines, in the order a tune meets them. Named here so the panel can
#: offer them in a sensible order and translate their names; the STEPS always come from the method.
ROUTE_ORDER = ("first", "short", "full", "league")


class ListeningUnavailable(RuntimeError):
    """The method's listening vocabulary could not be read on this installation."""


@dataclass(frozen=True)
class Phrase:
    """One thing to judge on one track: the characteristic, where to hear it, and both verdicts."""

    characteristic: str
    label: str
    name: str
    good: str
    bad: str
    cue: str
    timecode: Optional[str]
    route_hint: str
    translated: bool

    def verdict_text(self, ok: bool) -> str:
        return self.good if ok else self.bad


@dataclass(frozen=True)
class Track:
    id: str
    library: str
    number: Optional[str]
    artist: Optional[str]
    title: str
    version: str
    phrases: tuple[Phrase, ...]


@dataclass(frozen=True)
class Step:
    n: int
    track: str
    characteristic: str


@dataclass(frozen=True)
class Sheet:
    lang: str
    tracks: dict[str, Track]
    routes: dict[str, tuple[Step, ...]]
    libraries: tuple[str, ...]
    problems: tuple[str, ...]

    def phrase(self, track_id: str, characteristic: str) -> Optional[Phrase]:
        track = self.tracks.get(track_id)
        if track is None:
            return None
        for phrase in track.phrases:
            if phrase.characteristic == characteristic:
                return phrase
        return None


def _module() -> ModuleType:
    try:
        return vendor_loader.load(_MODULE)
    except Exception as exc:  # noqa: BLE001 — every failure reads the same to a window
        raise ListeningUnavailable(str(exc)) from exc


def available() -> bool:
    """Whether the vocabulary can be read at all — a panel that raises is worse than one that
    explains itself, so this is asked before the button offers anything."""
    try:
        _module()
    except ListeningUnavailable:
        return False
    return True


def languages() -> tuple[str, ...]:
    """The languages the method has this text in. English is always one of them: it is the source
    the translations are checked against, and it is what a missing entry falls back to."""
    try:
        return ("en",) + tuple(_module().languages())
    except ListeningUnavailable:
        return ("en",)


def load(lang: str = "en") -> Sheet:
    """The whole vocabulary, in `lang`, reshaped as tracks each carrying what to judge on it.

    A track with no link is kept: it is in the index for a reason and a person may still want to
    say something about it — but it will have nothing to click, which reads correctly as "the
    method has not said what this one is for".
    """
    module = _module()
    # `lang` may be a language TCC's UI offers and the method does not (the two lists are allowed
    # to move apart). The parser already falls back per entry; asking it for an unknown language
    # would just mark everything untranslated, which is the honest result.
    characteristics = module.characteristics(lang)
    raw_tracks = module.tracks()
    links = module.links(lang)
    routes = module.routes()

    by_track: dict[str, list[Phrase]] = {}
    for link in links:
        char = characteristics.get(link["characteristic"])
        if char is None:
            # The method's own `check()` reports this; skipping keeps the panel usable meanwhile.
            continue
        by_track.setdefault(link["track"], []).append(Phrase(
            characteristic=char["id"],
            label=char["label"],
            name=char["name"],
            good=char["good"],
            bad=char["bad"],
            cue=link["cue"],
            timecode=link["timecode"],
            route_hint=char["route"],
            translated=bool(char["translated"]) and bool(link["translated"]),
        ))

    tracks = {
        tid: Track(
            id=tid, library=row["library"], number=row["number"], artist=row["artist"],
            title=row["title"], version=row["version"],
            phrases=tuple(by_track.get(tid, ())),
        )
        for tid, row in raw_tracks.items()
    }
    ordered_routes = {
        name: tuple(Step(s["n"], s["track"], s["characteristic"]) for s in steps)
        for name, steps in sorted(routes.items(), key=_route_sort)
    }
    libraries = tuple(dict.fromkeys(row["library"] for row in raw_tracks.values()))
    try:
        problems = tuple(module.check(lang))
    except Exception as exc:  # noqa: BLE001 — a broken checker must not take the panel with it
        problems = (str(exc),)
    return Sheet(lang=lang, tracks=tracks, routes=ordered_routes, libraries=libraries,
                 problems=problems)


def _route_sort(item) -> tuple[int, str]:
    name = item[0]
    return (ROUTE_ORDER.index(name) if name in ROUTE_ORDER else len(ROUTE_ORDER), name)


def track_label(track: Track) -> str:
    """`CarMus #07 · Melody Gardot — Over The Rainbow (Live)`.

    Library and number together, never the number alone, and the artist because the method's
    "Disc identity" rule is that a gate citing a bare number breaks silently the day the disc
    changes. A row with no number or no artist (the mono set, the user's own material) simply
    leaves that part out rather than printing an empty separator.
    """
    head = f"{track.library} #{track.number}" if track.number else track.library
    who = f"{track.artist} — {track.title}" if track.artist else track.title
    return f"{head} · {who}"


def sheet_text(lang: str = "en") -> str:
    """The cheat sheet itself, as the method wrote it, for the window that opens it whole.

    Markdown, unrendered and unedited: the panel shows the method's own page rather than a summary
    of it. Falls back to the English file when this language has no translation on disk.
    """
    module = _module()
    root = Path(module.PATTERNS)
    for name in ((f"{module.CHEAT_SHEET}.{lang}.md",) if lang and lang != "en" else ()) + (
            f"{module.CHEAT_SHEET}.md",):
        path = root / name
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise ListeningUnavailable(f"{module.CHEAT_SHEET}.md not found in {root}")
