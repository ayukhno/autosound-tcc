"""Derive the capture task from the glossary + REW, instead of hard-coding a series (SCR-008).

SCR-004 is explicit that the measurement task is **not hand-written** — it is a function of
(phase × glossary × ledger version). This is that function on TCC's side: it asks the skill's
`naming` module what a phase expects, asks REW what it actually holds, and folds the two into the
`MeasSession` shape the panel already renders.

Why this had to wait for SCR-008: the mock series hard-coded `c_*` and `r-L/r-R_*`. The car it was
modelled on has the centre disconnected and no rear speakers at all, so a third of that checklist
was tasks nobody could carry out. A checklist with impossible rows in it stops being read.

Returns `None` when the project has no glossary — the signal to keep the mock rather than render
an empty task that looks like a completed one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from autosound_tcc.core import config, vendor_loader
from autosound_tcc.state import process_view
from autosound_tcc.ui.tcc.mock_data import MeasGroup, MeasItem, MeasSession

STATUS_DONE = "done"
STATUS_WAIT = "wait"
# The panel's own legend already calls this one "taken, unusable" -- exactly what a capture becomes
# when the hardware under it changed (SCR-014).
STATUS_STALE = "bad"
# Decided against, with a reason, and recorded as such by the skill (SCR-034). Distinct from
# waiting: before the round was recorded these were the same colour, so a capture the tuner had
# ruled out came back on the checklist every session.
STATUS_SKIPPED = "skip"


def glossary_path(project_dir: Optional[Path] = None) -> Path:
    return Path(project_dir or config.project_dir()) / "glossary.json"


def has_glossary(project_dir: Optional[Path] = None) -> bool:
    """A standalone `glossary.json`, or one embedded in `project.json` (SCR-011)."""
    project = Path(project_dir or config.project_dir())
    if (project / "glossary.json").is_file():
        return True
    try:
        import json

        return bool(json.loads((project / "project.json").read_text(encoding="utf-8")).get("glossary"))
    except (OSError, ValueError):
        return False


# REW title -> capture method, by the suffix the grammar writes (`naming-and-structure.md`).
_METHOD_BY_SUFFIX = (("(sw)", "sw"), ("(rta)", "rta"))
_METHOD_LABELS = {"sw": "sweep (sw)", "rta": "MMM RTA (rta)"}


def groups_from_titles(titles) -> list[dict]:
    """A flat list of REW titles, split into the column groups the panel renders.

    Used where there is no `expected_groups` to ask: a round the session opened itself, and every
    past round read back from the journal. Grouped by capture method and nothing else — the scopes
    the derived path knows about (pairs, sides, joints) are a property of the phase plan, and a
    round that exists outside one has no such structure to recover.
    """
    by_method: dict[str, list[str]] = {}
    for title in titles:
        text = str(title).strip()
        if not text:
            continue
        method = next(
            (m for suffix, m in _METHOD_BY_SUFFIX if text.rstrip().endswith(suffix)), "sw"
        )
        by_method.setdefault(method, []).append(text)
    return [
        {"label": _METHOD_LABELS.get(method, method), "method": method, "names": names}
        for method, names in sorted(by_method.items(), key=lambda kv: kv[0] != "sw")
    ]


def protective_phrase(legs) -> str:
    """What was in the chain, as a phrase for a row — `"HP 80 LR24 · LP 3500 LR24"`, or `""`.

    Empty for `"OFF"`, for a channel nobody listed, and for a leg with no frequency: all of them
    are the same instruction to the analysis — read the curve as measured (`core/protective.py`).
    Two states, not three, since 2026-09-06; the third one is a question standing with the method
    (hub#71), not something this renderer should invent a look for.
    """
    if not isinstance(legs, dict):
        return ""
    parts = []
    for kind, label in (("hp", "HP"), ("lp", "LP")):
        leg = legs.get(kind)
        if not isinstance(leg, dict):
            continue
        freq = leg.get("f")
        if freq in (None, "", 0):
            continue
        # `LR24`, the way the app spells it everywhere else (`protective_dialog.QUICK_LABEL`) —
        # not `LR 24`, which reads as two facts.
        shape = "".join(str(v) for v in (leg.get("type"), leg.get("slope")) if v)
        parts.append(f"{label} {freq:g}" if isinstance(freq, (int, float)) else f"{label} {freq}")
        if shape:
            parts[-1] = f"{parts[-1]} {shape}"
    return " · ".join(parts)


def build_session(
    phase: str,
    version,
    titles: list[str],
    project_dir: Optional[Path] = None,
    taken: Optional[list[str]] = None,
) -> Optional[MeasSession]:
    """One capture task: what `phase` expects at `version`, checked against `titles` from REW.

    `titles` is what REW is SHOWING; `taken` is what this project has actually taken in (the
    import store). They used to be one list, and that is what made a slot go green the moment REW
    held a title like it — the tuner opened the read window, took nothing, and the whole checklist
    was already done (user, 2026-09-06). REW's list decides what can be OFFERED; only a record of
    taking decides what is done. `taken` left out means "the same list", which is the old
    behaviour and is what the mock and the tests that predate the split rely on.

    `titles` is passed in rather than fetched here so the caller controls when REW is talked to —
    the panel already owns a worker for that, and a view module that blocks on HTTP is a view
    module that freezes the GUI.
    """
    project = Path(project_dir or config.project_dir())
    if not has_glossary(project):
        return None
    try:
        naming = vendor_loader.load_naming()
    except vendor_loader.VendorNotInitializedError:
        return None

    glossary = naming.Glossary.for_project(str(project))
    groups_spec = naming.expected_groups(phase, glossary, version)
    live_round = process_view.capture_round(project) or {}
    if not groups_spec:
        # A phase whose plan captures nothing (the skill's `_CAPTURE_PLAN["1"]` is literally `[]`
        # — phase 1 computes from what phase 0 took) still gets a task if the session OPENED one.
        # This used to return before it ever looked, so an ad-hoc round in such a phase rendered
        # as "no captures here": the panel showed the derivation and ignored the record, which is
        # the wrong way round — a round is a fact, a phase plan is a prediction about it.
        outstanding = [] if live_round.get("closed") else list(live_round.get("expected") or [])
        if not outstanding:
            return MeasSession(
                id=f"v{version}",
                version={"en": f"Phase {phase} · no capture",
                         "uk": f"Фаза {phase} · без замірів"},
                groups=(),
            )
        groups_spec = groups_from_titles(outstanding)

    # Keyed by parsed identity, not by raw title, so `c_01 (rta)` counts as `c_1 (rta)` -- REW
    # titles are hand-typed and zero-padding is common.
    parsed = {}
    for title in titles:
        entry = naming.parse_name(title, glossary)
        if entry:
            parsed[naming.name_key(entry)] = entry
    # The same reading over what the PROJECT took in, which is a different question from what REW
    # is showing (see the docstring). This is the one that colours a row.
    def _key(title: str):
        entry = naming.parse_name(str(title), glossary)
        return naming.name_key(entry) if entry else None

    taken_keys = set()
    for title in (titles if taken is None else taken):
        key = _key(title)
        if key is not None:
            taken_keys.add(key)
    # And what the ROUNDS recorded, which is the other half of "taken" and the bigger one: the ⤓
    # window writes the import store, a session writes the round, and a project driven by a model
    # has everything in the round and nothing in the store. Watched on the live project
    # (`testTCC8`, 2026-09-06): `cap_002` held fourteen captures, every one verified `ok`, and the
    # checklist above it said "waiting" for all fourteen.
    #
    # Two things are deliberate here. **Every round at this version, not only the open one** — a
    # pass that closed did not un-take its measurements, and asking for them again is the checker
    # crying wolf. And **through `name_key`**: the round records the title as typed (`tw-L_01
    # (sw)`) while the checklist derives `tw-L_1 (sw)`, and a raw-string comparison misses that —
    # which is exactly how it missed all fourteen.
    for round_at in process_view.capture_rounds(project):
        if str(round_at.get("version") or "").lstrip("v_").lstrip("0") not in (
                "", str(version).lstrip("v_").lstrip("0")):
            continue
        for title in (round_at.get("taken") or {}):
            key = _key(title)
            if key is not None:
                taken_keys.add(key)

    # SCR-014: a capture whose channel was invalidated by a `config_change` is not "done" -- the
    # graph exists and is unusable, which is a different thing from missing, and the panel has a
    # colour for exactly that. Flagging it here rather than in the panel keeps the panel a renderer.
    stale = process_view.stale_channels(project)

    # The round the skill recorded, if there is one (SCR-034). REW's open-measurement list is what
    # this panel used to be built on entirely, which meant closing REW turned a finished round back
    # into an empty checklist. What was recorded is a fact; what REW happens to have open is a
    # snapshot of another application's session.
    round_ = live_round
    recorded_taken = {str(t) for t in (round_.get("taken") or {})}
    recorded_skipped = {str(t) for t in (round_.get("skipped") or {})}
    # What the arithmetic said about each curve (SCR-040). A verdict outranks "a title exists":
    # a sweep that never finished and a muted channel both leave a title behind, and every later
    # phase used to compute on them.
    verdicts = {
        str(title): (entry or {}).get("verified") or {}
        for title, entry in (round_.get("taken") or {}).items()
    }

    def status_for(name: str) -> str:
        entry = naming.parse_name(name, glossary)
        if name in recorded_skipped:
            return STATUS_SKIPPED  # a decision, and it outranks both REW and the derivation
        verdict = verdicts.get(name)
        if verdict and not verdict.get("ok"):
            # The panel's own legend already calls this "taken, unusable" -- which is exactly what
            # a capture that came back and failed the check is.
            return STATUS_STALE
        if naming.name_key(entry) not in taken_keys and name not in recorded_taken:
            # Waiting, even when REW is showing a curve by that name: a title in another
            # application's list is not this project taking a measurement in (user, 2026-09-06).
            # The read window opens on it ticked, and the tick is what makes it done.
            return STATUS_WAIT
        # Both names a renamed channel answers to (SCR-039): a `config_change` names whichever the
        # session was using, and the capture's title carries whichever it was typed under. Either
        # side alone would leave a real invalidation looking like a clean capture.
        codes = {(entry or {}).get("code"), (entry or {}).get("code_current")} - {None}
        return STATUS_STALE if codes & set(stale) else STATUS_DONE

    def issues_for(name: str) -> Optional[str]:
        """Why a capture is unusable, in the checker's own words — the panel shows it on hover."""
        issues = (verdicts.get(name) or {}).get("issues") or []
        return "; ".join(str(i) for i in issues) or None

    protective = {str(k): v for k, v in (round_.get("protective") or {}).items()}

    def protective_for(name: str) -> str:
        """What the round says was in this channel's chain while it was measured.

        By channel, because the record is: one signal path per channel, whatever methods it was
        captured with. You cannot tell it from the curve — a protective `LR4 @100` and a designed
        one are the same filter — so the row is the only place it can be seen (tcc#15).
        """
        entry = naming.parse_name(name, glossary) or {}
        for code in (entry.get("code"), entry.get("code_current"), entry.get("channel")):
            if code and str(code) in protective:
                return protective_phrase(protective[str(code)])
        return ""

    groups = []
    for spec in groups_spec:
        items = tuple(
            MeasItem(name=name, status=status_for(name), extra=issues_for(name),
                     protective=protective_for(name))
            for name in spec["names"]
        )
        groups.append(MeasGroup(type=spec["label"], items=items, method=spec.get("method")))

    extras = _extras(naming, glossary, parsed, groups_spec, version, taken_keys)
    if extras:
        # Ours, at this version, but not on the checklist -- an experiment tag, a channel the
        # phase doesn't ask for. Shown, flagged blue, never silently dropped.
        groups.append(MeasGroup(type="additional", items=extras))

    # The round's own id when there is one: the ledger version names the config the measurements
    # were taken under and cannot tell two passes at the same config apart, which is exactly what
    # "this session's task" means (SCR-034). The two are spelled differently on purpose -- "series
    # 6" is the config, `cap_002` is the pass -- because a picker holding both used to offer `v6`
    # beside `cap_001` and say which was which nowhere (user, 2026-08-21).
    round_id = str(round_.get("id") or "") if not round_.get("closed") else ""
    return MeasSession(
        id=round_id or f"v{version}",
        version={
            "en": f"Series {version} · phase {phase}"
            + (f" · {round_id}" if round_id else ""),
            "uk": f"Серія {version} · фаза {phase}" + (f" · {round_id}" if round_id else ""),
        },
        groups=tuple(groups),
    )


def build_sessions(
    phase: str,
    version,
    titles: list[str],
    project_dir: Optional[Path] = None,
    taken: Optional[list[str]] = None,
) -> Optional[tuple[MeasSession, ...]]:
    """The live capture task, followed by every past round, newest first.

    The panel has had a session picker, a read-only history view and a plan-step link since it was
    built against the mock — and no supplier for any of it: the window only ever handed it one
    session (user, 2026-08-11: "shows v4, no history of v1"). The rounds were on disk the whole
    time, in the journal.
    """
    project = Path(project_dir or config.project_dir())
    live = build_session(phase, version, titles, project, taken)
    if live is None:
        return None
    state = process_view.load_state(project)
    past = [
        session
        for round_ in process_view.capture_rounds(project)
        if str(round_.get("id") or "") != live.id
        for session in (_session_for_round(round_, state),)
        if session is not None
    ]
    return (live, *past)


def _session_for_round(round_: dict, state: Optional[dict]) -> Optional[MeasSession]:
    """One past round as a read-only session: what it asked for, and what became of each item.

    Statuses come from the round's own record and nothing else — REW is not consulted. A series
    captured three weeks ago is history whether or not that project is still open in REW, which is
    the whole reason SCR-034 wrote the round down in the first place.
    """
    expected = [str(t) for t in (round_.get("expected") or [])]
    taken = {str(k): (v or {}) for k, v in (round_.get("taken") or {}).items()}
    skipped = {str(k) for k in (round_.get("skipped") or {})}
    if not expected and not taken:
        return None
    for title in taken:
        if title not in expected:
            expected.append(title)  # captured though nobody asked: still part of what happened

    def status_for(name: str) -> str:
        if name in skipped:
            return STATUS_SKIPPED
        entry = taken.get(name)
        if entry is None:
            return STATUS_WAIT  # asked for, never taken, and the round closed anyway
        verdict = entry.get("verified") or {}
        return STATUS_DONE if verdict.get("ok", True) else STATUS_STALE

    def issues_for(name: str) -> Optional[str]:
        # The skip reason comes first, and the order is the point: a skipped capture is ALSO
        # reported by the checker as "no measurement titled ...", which is true and useless. Why a
        # human decided not to take it outranks the arithmetic noticing it is not there.
        if name in skipped:
            return (round_.get("skipped") or {}).get(name, {}).get("reason")
        issues = ((taken.get(name) or {}).get("verified") or {}).get("issues") or []
        return "; ".join(str(i) for i in issues) or None

    protective = {str(k): v for k, v in (round_.get("protective") or {}).items()}

    def protective_for(name: str) -> str:
        """Same fact for a past round — read from the journal fold (`process_view.capture_rounds`),
        which did not carry it until 2026-09-06, so history had no marker at all."""
        from autosound_tcc.core import capture_import

        code = capture_import.channel_from_title(name)
        return protective_phrase(protective.get(code)) if code else ""

    groups = tuple(
        MeasGroup(
            type=spec["label"],
            method=spec.get("method"),
            items=tuple(
                MeasItem(name=name, status=status_for(name), extra=issues_for(name),
                         protective=protective_for(name))
                for name in spec["names"]
            ),
        )
        for spec in groups_from_titles(expected)
    )
    rid = str(round_.get("id") or "")
    ver = str(round_.get("version") or "").lstrip("v_").lstrip("0") or "?"
    phase = round_.get("phase")
    return MeasSession(
        id=rid or f"round·{ver}",
        version={
            "en": f"Series {ver} · phase {phase} · {rid}",
            "uk": f"Серія {ver} · фаза {phase} · {rid}",
        },
        groups=groups,
        used_in_steps=process_view.steps_using(state, expected),
    )


def _extras(naming, glossary, parsed: dict, groups_spec: list, version,
            taken_keys: Optional[set] = None) -> tuple[MeasItem, ...]:
    wanted = {
        naming.name_key(naming.parse_name(name, glossary))
        for spec in groups_spec
        for name in spec["names"]
    }
    try:
        version_n = int(version)
    except (TypeError, ValueError):
        version_n = version
    out = []
    for key, entry in sorted(parsed.items(), key=lambda kv: kv[1]["title"]):
        if key in wanted or (entry["version_n"] or entry["version"]) != version_n:
            continue
        out.append(
            MeasItem(
                name=entry["title"],
                # Ours, at this version, off the checklist — and green only once it was taken in.
                # A curve REW is holding is an offer, not a capture (see `build_session`).
                status=STATUS_DONE if taken_keys is None or key in taken_keys else STATUS_WAIT,
                extra=entry["modifier"],
                additional=True,
            )
        )
    return tuple(out)


def off_convention(titles: list[str], project_dir: Optional[Path] = None) -> list[str]:
    """Titles REW holds that aren't in the naming grammar at all.

    Worth surfacing separately from "not captured yet": no analysis will ever find these by name,
    so they are invisible to every later step rather than merely missing.
    """
    project = Path(project_dir or config.project_dir())
    if not has_glossary(project):
        return []
    try:
        naming = vendor_loader.load_naming()
    except vendor_loader.VendorNotInitializedError:
        return []
    glossary = naming.Glossary.for_project(str(project))
    return [t for t in titles if naming.parse_name(t, glossary) is None]
