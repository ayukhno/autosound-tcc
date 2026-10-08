"""Read the skill's process state (SCR-004) into the shapes the plan panel already renders.

TCC is a schema *consumer*: the skill owns `process/process-state.json` and is the only writer in
v1. This module does the one job on the boundary — turn that file into the `PlanPhase`/`PlanStep`
tuples `ui/tcc/plan_panel.py` was built against, so the renderer needs no changes and the mock and
the real thing stay interchangeable.

The mock's own phase numbering (0..6) was illustrative; the skill's skeleton is **−1..5**
(`references/core/process-phases.md`), so a project with real state shows different phases than
the demo does. That is the mock being wrong, not the reader.

Returns `None` when the project has no process state yet, which is the signal to keep rendering
the mock rather than showing an empty plan that looks like a finished one.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from dataclasses import replace
from typing import Optional

from autosound_tcc.core import config, vendor_loader
from autosound_tcc.state import project_view
from autosound_tcc.state.models import PlanPhase, PlanStep

# process-state's step status -> the tag chip the panel already styles.
_STATUS_TAGS = {
    "done": ({"en": "ok", "uk": "ок"}, "ok"),
    "in_progress": ({"en": "in progress", "uk": "в роботі"}, "wait"),
    "blocked": ({"en": "blocked", "uk": "заблоковано"}, "wait"),
    "skipped": ("", ""),
    "todo": ("", ""),
}
# A done step whose evidence names a channel a `config_change` invalidated (SCR-014). It overrides
# the "ok" chip rather than sitting beside it: the step is not done any more in the only sense that
# matters -- what it produced can no longer be trusted.
_STALE_TAG = ({"en": "recheck", "uk": "перезняти"}, "wait")

# The skill's fixed phase skeleton, in the languages TCC speaks. Translated HERE rather than
# written translated into `process-state.json`: the phases are the method's, identical in every
# project, and a title translated at write time freezes the file into whatever language the intake
# happened to run in -- after which switching the app to EN leaves half the panel in UK. Keyed by
# the skill's own English title, so a phase whose title has been changed on purpose (or a skeleton
# this version has not seen) is left exactly as the file has it.
_PHASE_TITLES_UK = {
    "Project intake & checklist": "Прийом проєкту та чеклист",
    "Baseline & target selection": "Базовий замір і вибір цілі",
    "Crossovers, levels & delays": "Кросовери, рівні та затримки",
    "EQ & acoustic alignment": "EQ та акустичне узгодження",
    "Technical verdict & lock": "Технічний вердикт і фіксація",
    "Targeted listening → feedback → close": "Цільове прослуховування → фідбек → закриття",
    "Variations (cyclical)": "Варіації (циклічно)",
}


def process_dir(project_dir: Optional[Path] = None) -> Path:
    """`<project>/process` — the skill's namespace, which TCC reads and never writes."""
    return Path(project_dir or config.project_dir()) / "process"


def has_process_state(project_dir: Optional[Path] = None) -> bool:
    return (process_dir(project_dir) / "process-state.json").is_file()


def state_file(project_dir: Optional[Path] = None) -> Path:
    return process_dir(project_dir) / "process-state.json"


def read_state_text(project_dir: Optional[Path] = None) -> Optional[dict]:
    """`process-state.json` as the JSON object it holds, or None: no file, one that cannot be
    opened, one that is not UTF-8 or not JSON (cut off mid-write, empty), and JSON that is not an
    object (`null`, a list) (#176).

    Read before the method is asked, because the method reads each of those as the EMPTY process
    (`Process.load()`, lenient), and that is an answer: seven phases with nothing in them, «no
    active phase». `strict=True` would refuse instead, but only from the method's v3.1.2: a copy up
    to v3.1.1 has no `strict`, and every copy `method_binding` admits must read the same way. A BOM
    is read, as the method reads it: refused here, a state the method reads would freeze the plan.
    """
    try:
        with open(state_file(project_dir), "rb") as handle:
            data = json.loads(handle.read().decode("utf-8-sig"))
    except (OSError, ValueError):  # `UnicodeDecodeError` and `JSONDecodeError` are ValueErrors
        return None
    return data if isinstance(data, dict) else None


def load_state(project_dir: Optional[Path] = None) -> Optional[dict]:
    """The raw process-state dict, or None if this project has none / the skill isn't vendored /
    the file is there and does not read as a state (`read_state_text`, #176)."""
    if read_state_text(project_dir) is None:
        return None
    try:
        process = vendor_loader.load_process()
    except vendor_loader.VendorNotInitializedError:
        return None
    return process.Process(str(process_dir(project_dir))).load()


def capture_round(project_dir: Optional[Path] = None) -> Optional[dict]:
    """The capture round the skill has open, or None (SCR-034).

    Only the OPEN one is in `process-state.json`; every round that ever happened is in the journal,
    the same split the active phase uses. A closed round is returned as it stands — the panel still
    wants to show what the last pass produced, it just must not treat it as the live task.
    """
    state = load_state(project_dir)
    round_ = (state or {}).get("capture")
    return round_ if isinstance(round_, dict) else None


def journal_file(project_dir: Optional[Path] = None) -> Path:
    return process_dir(project_dir) / "journal.jsonl"


def capture_rounds(project_dir: Optional[Path] = None) -> list[dict]:
    """Every capture round this project ever ran, newest first (SCR-034).

    `process-state.json` keeps only the round that is open; the journal keeps them all, which is
    the same split the active phase uses. Nothing read this until now, so the panel's session
    picker could only ever offer the series being captured right now — the history it was built
    for (and the plan's per-step measurement icon that links into it) had no supplier at all
    (user, 2026-08-11).

    Folded back into the same shape `capture_round()` returns, so one renderer serves both.
    """
    project = Path(project_dir or config.project_dir())
    rounds: dict[str, dict] = {}
    try:
        lines = journal_file(project).read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    order: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue  # a half-written line at the tail is normal while the skill is mid-write
        rid = str(event.get("capture") or "")
        if not rid:
            continue
        round_ = rounds.get(rid)
        if round_ is None:
            round_ = rounds[rid] = {"id": rid, "expected": [], "taken": {}, "skipped": {},
                                    "protective": {}, "version_kind": None}
            order.append(rid)
        kind = event.get("type")
        if kind == "capture_task_issued":
            round_["phase"] = event.get("phase")
            round_["version"] = event.get("version")
            # WHICH counter that version is: `ledger` (`v_001`) or `series` (`_17`). They are
            # different counters and neither is derived from the other, so reading it off the
            # spelling was a guess — the method records it since TCC-022 (hub #190). `None` on a
            # journal written before that, which is every journal this pin can still produce.
            round_["version_kind"] = event.get("version_kind")
            round_["issued"] = event.get("at")
            round_["step"] = event.get("step")
            round_["expected"] = [str(t) for t in (event.get("expected") or [])]
        elif kind == "capture_taken":
            round_["taken"][str(event.get("title"))] = {
                "at": event.get("at"),
                "planned": event.get("planned"),
            }
        elif kind == "capture_skipped":
            # `planned` beside the reason, the way `capture_taken` above carries it: `expected[]`
            # is not a closed set, so a reader cannot assume everything skipped was ever asked for
            # (TCC-022). `None` — not `False` — when the method that wrote the line did not say.
            round_["skipped"][str(event.get("title"))] = {
                "reason": event.get("reason"),
                "planned": event.get("planned"),
            }
        elif kind == "capture_verified":
            # The arithmetic's own verdict per title (SCR-040), folded onto the entry the panel
            # reads. `bad` carries no issue list here — the open round in state does, and for a
            # closed one "it did not pass" is the part that still matters.
            for title in event.get("ok") or []:
                round_["taken"].setdefault(str(title), {})["verified"] = {"ok": True}
            for title in event.get("bad") or []:
                round_["taken"].setdefault(str(title), {})["verified"] = {"ok": False}
            # Since the method's v3.0.53 a capture the check does not apply to (an RTA) is listed
            # here and no longer under `bad` (hub #154 §1): taken, and not unusable.
            for title in event.get("not_applicable") or []:
                round_["taken"].setdefault(str(title), {})["verified"] = {
                    "ok": False, "applicable": False}
        elif kind == "capture_protective":
            # What was in the signal path while this pass was measured, per channel. The fold was
            # missing entirely, so a past round came back with no `protective` at all and the
            # panel could only mark the round being captured right now (tcc#15).
            round_.setdefault("protective", {})[str(event.get("channel"))] = event.get("legs")
        elif kind == "capture_round_closed":
            round_["closed"] = event.get("at") or True

    # The open round as `process-state.json` has it wins: the journal is append-only history, the
    # state file is the live record, and only it carries the full `verified` payload with issues.
    live = capture_round(project)
    if live and live.get("id"):
        rid = str(live["id"])
        if rid not in rounds:
            order.append(rid)
        rounds[rid] = {**rounds.get(rid, {}), **live}

    return [rounds[rid] for rid in reversed(order)]


def steps_using(state: Optional[dict], titles) -> tuple[str, ...]:
    """Ids of closed steps whose evidence names any of `titles`.

    The link between a capture round and the plan steps it served is not written down as a field —
    but SCR-035 forces every closed step to cite something real, and a capture is cited by its REW
    title. So the link already exists in the evidence, and this reads it rather than asking the
    skill for a new one.
    """
    wanted = {str(t) for t in titles if str(t).strip()}
    if not wanted or not state:
        return ()
    one, tags = _reading()
    if one is not None:
        wanted |= {str(one(t)) for t in wanted}  # an older round's `w_L_10 (sw)` is `w-L_10 (sw)`
    out = []
    for step in state.get("plan") or []:
        if not isinstance(step, dict):
            continue
        evidence = _evidence_text(step.get("evidence"), one)
        # Whole, as the stale check reads it (`_cites`): `w-L_10 (sw)` is in `tw-L_10 (sw)` as text.
        if any(_cites(title, evidence, tags) for title in wanted):
            out.append(str(step.get("id")))
    return tuple(out)


def load_plan(project_dir: Optional[Path] = None) -> Optional[tuple[PlanPhase, ...]]:
    """The real plan as `PlanPhase` tuples, or None when there is no process state to read."""
    state = load_state(project_dir)
    return to_plan(state) if state else None


def to_plan(state: dict, stale: Optional[dict] = None) -> tuple[PlanPhase, ...]:
    """Map one process-state dict onto the panel's dataclasses.

    Phase order comes from the skill's own tuple rather than the JSON object's key order: a phase
    the project has never entered still has to appear, in the right place, as `todo`.

    `stale` is `stale_channels()`'s result: a done step whose evidence names one of those channels
    is re-chipped "recheck", because what it produced no longer describes the car.
    """
    process = vendor_loader.load_process()
    active = state.get("active_phase")
    phases_meta = state.get("phases", {})
    steps_by_phase: dict[str, list[dict]] = {}
    for step in state.get("plan", []):
        steps_by_phase.setdefault(str(step.get("phase")), []).append(step)

    # Read once, not per step: a rename is the only thing that makes this map interesting, and it
    # is a whole-project fact either way.
    aliases = _channel_aliases() if stale else {}
    reading = _reading() if stale else (None, None)
    out: list[PlanPhase] = []
    for key in process.PHASES:
        meta = phases_meta.get(key, {})
        title = meta.get("title") or process.PHASE_TITLES.get(key, key)
        out.append(
            PlanPhase(
                status=meta.get("status", "todo"),
                current=key == active,
                name={
                    "en": f"Phase {key} · {title}",
                    "uk": f"Фаза {key} · {_PHASE_TITLES_UK.get(title, title)}",
                },
                steps=tuple(_to_step(s, stale or {}, aliases, reading)
                            for s in steps_by_phase.get(key, [])),
            )
        )
    return tuple(out)


def _to_step(step: dict, stale: Optional[dict] = None,
             aliases: Optional[dict] = None, reading: tuple = (None, None)) -> PlanStep:
    tag, tag_class = _STATUS_TAGS.get(step.get("status", "todo"), ("", ""))
    one, tags = reading
    evidence = _evidence_text(step.get("evidence"), one)
    # Any name the channel answers to (SCR-039) — the evidence is a REW title typed under whichever
    # name was current that day, which need not be the one the `config_change` used.
    if evidence and any(
        _cites(name, evidence, tags)
        for code in (stale or {})
        for name in (aliases or {}).get(code, (code,))
    ):
        tag, tag_class = _STALE_TAG
    return PlanStep(
        id=str(step.get("id", "")),
        # Real step names are plain strings from the skill; `i18n.tx` passes those through
        # unchanged, so no per-language wrapper is needed (and inventing one would imply a
        # translation that does not exist).
        name=step.get("name", ""),
        tag=tag,
        tag_class=tag_class,
        source=step.get("source", "skill"),
        skip=bool(step.get("skip")),
        attempt=int(step.get("attempt", 1) or 1),
        covers=tuple(str(c) for c in step.get("covers") or ()),
    )


def phase_finished(state: Optional[dict]) -> Optional[str]:
    """The active phase, when its plan has steps and none is left `todo` or `in_progress`.

    That is the moment the method's `handoff` answers (hub #201): at the END of a phase, right
    after the event that closed its last step. Just after `phase_entered` the new phase's steps are
    `todo`, and `handoff` refuses.
    """
    if not state:
        return None
    active = state.get("active_phase")
    steps = [s for s in state.get("plan", []) if str(s.get("phase")) == str(active)]
    if active is None or not steps:
        return None
    if any(s.get("status", "todo") in ("todo", "in_progress") for s in steps):
        return None
    return str(active)


def done_step_ids(state: dict) -> set[str]:
    """Steps the skill considers done — the panel's checkboxes should reflect these, not guess."""
    return {
        str(s.get("id"))
        for s in state.get("plan", [])
        if s.get("status") == "done"
    }


def reviewer(state: dict) -> Optional[dict]:
    """Last reviewer call recorded by the skill (vendor/model/when), or None."""
    return state.get("reviewer")


def session_closed(project_dir: Optional[Path] = None) -> Optional[bool]:
    """Is the session closed, as the journal has it? None when the journal cannot say.

    True when its last session event is `session_closed`. A close can be taken back since the
    method's v3.0.65: `session-reopen <reason>` appends `session_reopened` after it, the close
    staying in the journal (skill #107, hub #227) — and a reopening after the last close means
    the session is open again. Read through the method's own `Process.session_closed`, the one
    place it reads the close, so the rule is not kept twice. None with no journal, and with a
    method older than that reader: it has no reopening, so the journal adds nothing to what the
    caller already knows.
    """
    process = _process_module()
    if process is None or not journal_file(project_dir).is_file():
        return None
    reader = getattr(process.Process(str(process_dir(project_dir))), "session_closed", None)
    return bool(reader()) if callable(reader) else None


# ---- what a config change invalidated (SCR-014) -----------------------------


def config_changes(project_dir: Optional[Path] = None) -> tuple[dict, ...]:
    """Every `config_change` event in the journal, oldest first, with its `impact` parsed.

    The parse comes from the skill (`project.Project.parse_impact`), not from a regex here: the
    field is written by the skill and a second reading of it in a consumer is how two readings
    drift apart.
    """
    process = _process_module()
    if process is None:
        return ()
    proc = process.Process(str(process_dir(project_dir)))
    if not (process_dir(project_dir) / "journal.jsonl").is_file():
        return ()
    parse = _impact_parser()
    out = []
    for event in proc.events(kinds=[process.EV_CONFIG_CHANGE]):
        event = dict(event)
        event["impact_parsed"] = parse(event.get("impact")) if parse else {
            "kind": "other", "codes": (), "raw": event.get("impact") or ""
        }
        out.append(event)
    return tuple(out)


#: `stale_channels`' answer, one slot per project: `{root: (key, stale)}` (#172). A slot is
#: replaced when a file it was read from changes or the method is read again, so a caller on
#: another thread never finds it emptied.
_STALE: dict = {}


class JournalUnread(dict):
    """`stale_channels`' answer from a journal that has bytes and gave no events (the group review,
    M5): the method reads a file it cannot open as empty (#134, R53) — an antivirus or a sync tool
    holding it, on Windows — so what went stale is unknown, not «nothing». Empty, as `{}` is, for
    every reader that only asks which channels; `path` is the journal, for the window to name."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path


def _stamp(path: Path) -> tuple:
    """`(path, st_mtime_ns, st_size)`, what a memo here is keyed by (#172); `(path, None, None)`
    for a file that is not there."""
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def stale_channels(project_dir: Optional[Path] = None) -> dict[str, dict]:
    """`{channel_code: the change that invalidated it}` — what needs re-measuring, and why.

    SCR-014's whole point: a driver swap or a re-gain must flag *exactly* the affected captures,
    never silently. The rule is derived from the journal alone, so it needs no capture timestamps
    from REW (which does not reliably give them):

        a `config_change` invalidates its channels until a LATER `step_done` whose evidence names
        that channel.

    "Later" is journal ORDER, not the `at` stamps: the journal is append-only, so a later line is
    later by construction, while `at` is second-resolution — a change and the capture that answers
    it land in the same second often enough that comparing stamps drops a real clear (caught by the
    test, not in the field). One ordered pass, therefore, rather than two lists compared by time.

    The result reads as "the skill has not recorded a capture for this channel since the change" —
    the honest claim, and the one a tuner can act on. `full_rebaseline` invalidates every channel
    the glossary knows; an impact the parser cannot act on (`voicing`, free text) flags nothing,
    since guessing which channels a sentence meant is how a checklist starts lying.

    Every name a channel answers to counts as naming it (SCR-039): a `config_change` says whatever
    the session was calling the channel, while the evidence that clears it is a REW title typed
    under whichever name was current the day of the capture. Matching the two literally would let a
    rename either hide a real invalidation or leave one that no capture can ever clear.

    Remembered by the path, mtime and size of each file it reads — the journal, `project.json`, the
    glossary — and handed out as a copy (#172): the window asks this at least twice a refresh, on
    the GUI thread, and the journal only grows. The method it was read with is in the key too: the
    reading is the method's, and an update reads the method again (`vendor_loader.reload_loaded`).
    An answer read while a file could not be opened is not kept (the review of Task 20, M1): the
    method reads such a file as empty, and a hold or a permission lifted moves no stamp. A journal
    with bytes that gave no events answers `JournalUnread`, so that is said, not «nothing» (M5).
    """
    process = _process_module()
    if process is None:
        return {}
    root = Path(project_dir or config.project_dir())
    if not journal_file(root).is_file():
        return {}
    journal = _stamp(journal_file(root))
    key = (process, journal, _stamp(config.project_path(root)), _stamp(root / "glossary.json"))
    held = _STALE.get(str(root))
    if held is not None and held[0] == key:
        return copy.deepcopy(held[1])
    stale, events_seen, read_empty = _stale_in(root, process)
    # A journal with bytes and no events may be one the method could not open — it reads such a
    # file as none — so its answer is «unknown», never kept, and «nothing stale» from it must not
    # outlive the hold. Otherwise kept, unless something else the answer used came back empty.
    if not events_seen and journal[2]:
        return JournalUnread(journal_file(root))
    if not read_empty:
        _STALE[str(root)] = (key, stale)
    return copy.deepcopy(stale)


def _stale_in(project_dir: Path, process) -> tuple[dict[str, dict], int, set[str]]:
    """`stale_channels`, read from the files: one ordered pass over the journal.

    With it, what that reading rests on, for the memo to judge (the review of Task 20, M1): how
    many events the journal gave, and which other reading came back empty where the answer used
    it — `project.json` with no channel when a capture was matched against what went stale or a
    full rebaseline asked which channels are on, the glossary with no channel for a full
    rebaseline. The method reads a file it cannot open as empty (#134, R53), so an empty reading
    is no evidence that the file is."""
    proc = process.Process(str(process_dir(project_dir)))
    parse = _impact_parser()
    aliases = _channel_aliases(project_dir)
    one, tags = _reading()
    events = proc.events()  # oldest first
    read_empty: set[str] = set()

    stale: dict[str, dict] = {}
    for event in events:
        kind = event.get("type")
        if kind == process.EV_CONFIG_CHANGE:
            parsed = parse(event.get("impact")) if parse else {"kind": "other", "codes": ()}
            codes = parsed.get("codes") or ()
            if parsed.get("kind") == "full_rebaseline":
                codes = _known_channel_codes(project_dir)
                if not codes:
                    read_empty.add("glossary")
                # `project.json`'s rows switch each channel on or off (skill #83): read as none,
                # the glossary's own flags stand, and they can be wrong either way.
                if not aliases:
                    read_empty.add("project.json")
            for code in codes:
                stale[code] = {**event, "impact_parsed": parsed}
        elif kind == process.EV_STEP_DONE:
            if stale and not aliases:
                read_empty.add("project.json")
            # Evidence is free-form pointers (REW names, `v_003`, an audit entry), so the code is
            # looked for in the text -- as a whole code, not a substring (`_cites`).
            evidence = _evidence_text(event.get("evidence"), one)
            cleared = [
                c for c in stale
                if any(_cites(name, evidence, tags) for name in aliases.get(c, (c,)))
            ]
            for code in cleared:
                del stale[code]
    return stale, len(events), read_empty


#: The two controls `naming.generate_name` writes INTO a code with a `-` (`m-L-ctl1_49 (sw)`): the
#: channel's own capture, not a variation of it. `ctl`/`rep` go after the series (`_49rep`).
_CONTROLS_IN_CODE = ("ctl1", "ctl3")


def _cites(name: str, evidence: str, tags: Optional[tuple[str, ...]] = None) -> bool:
    """Whether `evidence` names `name` -- a channel code, or a capture title that begins with one --
    whole, not as a piece of another channel's.

    It was a substring test, and `w-L` is in `tw-L_10 (sw)`: a tweeter-only step cleared a woofer
    swap, the silence SCR-014 exists to prevent (#126's review, Important 1), and a round asking
    for `w-L_10 (sw)` was linked to the tweeter's step. A channel is `<driver type>-<its
    variation>` with any variation (`sr-LH`, `sw-r2`; the Arbiter, 2026-10-02), and `_` only begins
    the series. So no letter or digit may touch the name on either side; no `-` may come before it
    (it would be another channel's variation) nor after it, unless that `-` begins a control
    (`w-L-ctl1_3`). A `(` may come before it, as prose puts things in brackets, but a code that is
    also a method tag and is the WHOLE of a bracket is not counted: `(sw)` is the tag, not the
    channel `sw`, and the two cannot be told apart -- left stale, which says so, rather than cleared
    in silence. `(w-L)` is no tag and counts (#126's re-review, Minor B). A title carries its own
    tag and may be bracketed whole, but not follow a `+`: there it is part of a joint's title,
    another measurement (`sw+w-L_3 (sw)` is not `w-L_3 (sw)`, Minor C), while a bare code after a
    `+` is a member the joint names. What may follow: the series `_`, a space and a modifier, the
    `+` of a joint, punctuation, the end.

    `tags` is `naming.METHODS` (`_reading`); None, with no method to ask, takes every code for one.
    """
    word = re.escape(name)
    controls = "|".join(_CONTROLS_IN_CODE)
    if re.search(r"\s", name):  # a title (`w-L_10 (sw)`): bracketed whole, never after a `+`
        before = r"(?<![A-Za-z0-9\-+])"
    elif tags is None or name in tags:  # `sw`: never the whole of a bracket, where it is the tag
        before = rf"(?:(?<![A-Za-z0-9(\-])|(?<=\()(?!{word}\)))"
    else:  # any other code: a bracket around it is prose
        before = r"(?<![A-Za-z0-9\-])"
    pattern = rf"{before}{word}(?=$|[^A-Za-z0-9\-]|-(?:{controls})(?![A-Za-z0-9]))"
    return re.search(pattern, evidence) is not None


def _reading() -> tuple:
    """`(canonical_title, METHODS)` from the method's `naming`, read once per pass, not per name.

    - `canonical_title` (v3.0.65 on): a capture typed `w_L_10 (sw)` is `w-L_10 (sw)` to the
      method, which accepts it as evidence and reads it so -- asked of the method rather than
      copied, as `load_channels` does (#126's re-review, Minor A).
    - `METHODS` (`sw`, `rta`, `imp`): the tags a `(code)` cannot be told from (Minor B).

    `(None, None)` with no method to ask: titles are read as written, and every bracketed code is
    left stale rather than cleared on a guess.
    """
    try:
        naming = vendor_loader.load_naming()
    except Exception:  # noqa: BLE001 — no method to ask: the readings fall back
        return None, None
    tags = getattr(naming, "METHODS", None)
    return getattr(naming, "canonical_title", None), (tuple(map(str, tags)) if tags else None)


def _evidence_text(items, one=None) -> str:
    """A step's evidence as one text to look names up in: each item as written, and after them
    each title `one` (`canonical_title`) reads in another notation, as it reads it. An item is
    read whole and, when it is a " + " list, title by title -- the way the method's `resolves`
    takes evidence (#126's re-review, Minor D: `w_L_10 (sw) + tw_L_10 (sw)` names `tw-L` too)."""
    said = [str(item) for item in items or []]
    if one is not None:
        titles = [part for item in said for part in dict.fromkeys([item, *item.split(" + ")])]
        said += [read for read, title in ((str(one(t)), t) for t in titles) if read != title]
    return " ".join(said)


def _channel_aliases(project_dir: Optional[Path] = None) -> dict[str, tuple[str, ...]]:
    """`{any name of a channel: every name that channel answers to}` — SCR-039.

    Built from `project.json`'s `channels[]`, which is the only place that knows a rename happened.
    A project with no renames maps each code to just itself, which is what every caller assumed
    before this existed.

    Every key `load_channels` gives the channel counts, the key asked by first (#126): it also
    keys a channel by its names in the method's one notation (`w_L` answers to `w-L`), and a key
    that is none of the literal names must still be one of the names it is matched as.
    """
    channels = project_view.load_channels(project_dir)
    out: dict[str, tuple[str, ...]] = {}
    for key, entry in channels.items():
        previous = entry.get("previous_names")
        names = [key, entry.get("id"), entry.get("code")]
        names += list(previous) if isinstance(previous, list) else []
        names += [other for other, same in channels.items() if same is entry]
        out[key] = tuple(dict.fromkeys(str(n) for n in names if n))
    return out


def _known_channel_codes(project_dir: Optional[Path] = None) -> tuple[str, ...]:
    """Active channel codes from the glossary — what "everything" means for `full_rebaseline`."""
    try:
        naming = vendor_loader.load_naming()
    except vendor_loader.VendorNotInitializedError:
        return ()
    glossary = naming.Glossary.for_project(str(Path(project_dir or config.project_dir())))
    return tuple(glossary.channel_codes(active_only=True))


def _process_module():
    try:
        return vendor_loader.load_process()
    except vendor_loader.VendorNotInitializedError:
        return None


def _impact_parser():
    """`project.Project.parse_impact`, or None when the submodule isn't checked out."""
    try:
        return vendor_loader.load_project().Project.parse_impact
    except (vendor_loader.VendorNotInitializedError, AttributeError):
        return None


_UNBACKED_TAG = ({"en": "unproven", "uk": "без доказу"}, "bad")


def mark_unbacked(
    phases: tuple[PlanPhase, ...], step_ids: set[str]
) -> tuple[PlanPhase, ...]:
    """Re-tag closed steps whose evidence resolves to nothing on disk (`state.plan_audit`).

    A chip rather than an un-tick: the skill did close the step, and pretending otherwise would
    put TCC's opinion into a file it does not own. What the panel shows is the disagreement --
    which is what a panel called ПЛАН — ФАКТ is for.
    """
    if not step_ids:
        return phases
    out = []
    for phase in phases:
        steps = tuple(
            replace(step, tag=_UNBACKED_TAG[0], tag_class=_UNBACKED_TAG[1])
            if step.id in step_ids else step
            for step in phase.steps
        )
        out.append(replace(phase, steps=steps))
    return tuple(out)
