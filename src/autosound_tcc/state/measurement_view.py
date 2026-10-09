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

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from autosound_tcc.core import config, vendor_loader
from autosound_tcc.state import process_view
from autosound_tcc.state.models import MeasGroup, MeasItem, MeasSession

STATUS_DONE = "done"
STATUS_WAIT = "wait"
# The panel's own legend already calls this one "taken, unusable" -- exactly what a capture becomes
# when the hardware under it changed (SCR-014).
STATUS_STALE = "bad"
# Decided against, with a reason, and recorded as such by the skill (SCR-034). Distinct from
# waiting: before the round was recorded these were the same colour, so a capture the tuner had
# ruled out came back on the checklist every session.
STATUS_SKIPPED = "skip"
#: In REW under the name the checklist asks for, and not taken in yet (F-056, the Arbiter
#: 2026-09-16): "not everything green before the import, even when the measurements were found —
#: blue for 'it is there, but has to be loaded explicitly'". Yellow stays for what REW does not
#: hold either.
STATUS_FOUND = "found"


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


# A title the grammar refuses, read for its method tag where the grammar places one (tcc#109): glued
# to the series number, `_7 (rta)`, with free text after it (`naming.py` `_NAME_RE`/`_TAGGED_RE`) --
# the last such, as the grammar's greedy body takes it; else the first tag, as `(imp)` with no `_N`
# is placed (`_UNVERSIONED_RE`: its body holds no bracket). Case-blind, as the grammar is. A tag
# ends where a word could: `x_8 (sw)y` is no tag to the grammar, and was one here (tcc#123).
_SERIES_TAG_RE = re.compile(r"_(?:\d+|final)(?:ctl|rep)?\s*\(([A-Za-z]+)\)(?=\s|$)")
_TAG_RE = re.compile(r"\(([A-Za-z]+)\)")
# `naming.METHODS`, for a machine with no method to ask.
_METHODS = ("sw", "rta", "imp")
# Every method `naming.METHODS` knows: `imp` had none, and its column was headed «imp» (tcc#122).
_METHOD_LABELS = {"sw": "sweep (sw)", "rta": "MMM RTA (rta)", "imp": "impedance (imp)"}


def _method_by_tag(text: str, methods) -> Optional[str]:
    glued = [m.lower() for m in _SERIES_TAG_RE.findall(text) if m.lower() in methods]
    if glued:
        return glued[-1]
    loose = [m.lower() for m in _TAG_RE.findall(text) if m.lower() in methods]
    return loose[0] if loose else None


def _series_reader(project_dir: Optional[Path] = None):
    """`title -> _N or None`, through the method's grammar with this project's glossary.

    Built once per question: reading the glossary per title is a file read per title, and a
    project has rounds of sixteen. No method on the machine answers None for every title.
    """
    project = Path(project_dir or config.project_dir())
    try:
        naming = vendor_loader.load_naming()
        glossary = naming.Glossary.for_project(str(project)) if has_glossary(project) else None
    except Exception:  # noqa: BLE001 — no method, no glossary: nothing here can read a title
        return lambda _title: None

    def read(title) -> Optional[int]:
        entry = naming.parse_name(str(title).strip(), glossary)
        value = entry.get("version_n") if entry else None
        return value if isinstance(value, int) else None

    return read


def series_of(titles, project_dir: Optional[Path] = None) -> Optional[int]:
    """The `_N` of the first of `titles` the method's grammar reads with one, or None (hub #153 A).

    Through `naming.parse_name` and nothing of our own: a second reader of the grammar is the defect
    the method's #34 was.
    """
    read = _series_reader(project_dir)
    for title in titles:
        found = read(title)
        if found is not None:
            return found
    return None


def highest_series(project_dir: Optional[Path] = None) -> Optional[int]:
    """The highest `_N` among every round's titles, or None when no round names one."""
    read = _series_reader(project_dir)
    found = [
        read(title)
        for round_ in process_view.capture_rounds(project_dir)
        for title in list(round_.get("expected") or []) + list(process_view.standing(round_))
    ]
    found = [n for n in found if n is not None]
    return max(found) if found else None


def capture_version(state: Optional[dict] = None) -> Optional[int]:
    """The series `_N` the current captures are named with, or None when nothing says (hub #153 A).

    `_N` is the DSP state the measurements were taken on. The ledger's `v_NNN` is a different
    counter — it also moves for changes that are not DSP changes, and a project can start with
    the two apart (`v_001` measured as `_49`) — so the ledger is not read here. In order:

    1. the open round: its titles are the pass being taken now;
    2. the active phase's plan steps ("Baseline solo: tw-L_1 (sw) + tw-L_1 (rta)"), each piece
       read by the method's grammar;
    3. the highest `_N` among all rounds (the Arbiter, 2026-09-16);
    4. None: the checklist says the series is not known yet, and an import with no round open
       asks for it.

    Out of the window, where it was `_capture_version` (W-9, the ratchet's next decision)."""
    round_ = process_view.capture_round() or {}
    if round_ and not round_.get("closed"):
        found = series_of(list(round_.get("expected") or []) + list(process_view.standing(round_)))
        if found is not None:
            return found
    for step in (state or {}).get("plan") or []:
        if not isinstance(step, dict) or str(step.get("phase")) != str(
            (state or {}).get("active_phase")
        ):
            continue
        found = series_of(re.split(r"[+,;:]", str(step.get("name") or "")))
        if found is not None:
            return found
    return highest_series()

def groups_from_titles(titles) -> list[dict]:
    """A flat list of REW titles, split into the column groups the panel renders.

    Used where there is no `expected_groups` to ask: a round the session opened itself, and every
    past round read back from the journal. Grouped by capture method and nothing else — the scopes
    the derived path knows about (pairs, sides, joints) are a property of the phase plan, and a
    round that exists outside one has no such structure to recover.

    Sorted by the method `parse_name` reads off the title, not by how the title ends (tcc#101,
    finding 111): `L m+tw_55 (rta) inv` ends with `inv`, the clarification after the method, and
    landed under SW when the last word decided it.

    A title the grammar refuses is read for its method tag where the grammar would find it, not by
    its last word (tcc#109, finding 117): `D_L w+m_9 (rta) inv` and `D_L_7 (rta) m-L: lev=-4.5,
    PK=-2` carry the note the grammar welcomes and are refused only for the `D_` before the code
    (S-042) -- by the suffix they went under SW. The method's v3.0.65 read them as a channel `D-L`;
    v3.0.66 refuses them again and names the `D_` an old configuration prefix (hub #232 TCC-044).
    A title with no tag at all stays under SW.
    """
    try:
        naming = vendor_loader.load_naming()
    except Exception:  # noqa: BLE001 — no method on the machine: every title falls to its tag
        naming = None
    methods = naming.METHODS if naming else _METHODS
    by_method: dict[str, list[str]] = {}
    for title in titles:
        text = str(title).strip()
        if not text:
            continue
        entry = naming.parse_name(text) if naming else None
        method = (entry.get("method") if entry else None) or _method_by_tag(text, methods) or "sw"
        by_method.setdefault(method, []).append(text)
    return [
        {"label": _METHOD_LABELS.get(method, method), "method": method, "names": names}
        for method, names in sorted(by_method.items(), key=lambda kv: kv[0] != "sw")
    ]


def _canonical(naming, glossary, title: str) -> str:
    """A round's title in the derived spelling — `sw_01 (sw)` as `sw_1 (sw)` — the way the plan
    and every other row spell it. As typed when it is not in the grammar."""
    entry = naming.parse_name(str(title), glossary)
    if not entry:
        return str(title)
    version = "final" if entry.get("version") == "final" else entry.get("version_n")
    try:
        return naming.generate_name(entry["code"], version, entry.get("method"),
                                    modifier=entry.get("modifier"), position=entry.get("position"),
                                    control=entry.get("control"), params=entry.get("params"))
    except Exception:  # noqa: BLE001 — a title the writer will not rebuild is shown as typed
        return str(title)


def _round_groups(round_: dict, naming, glossary) -> list[dict]:
    """An open round's columns: the ones it carries (skill #83), else its list by method."""
    carried = [
        {"label": str(g.get("label") or g.get("method") or ""), "method": g.get("method"),
         "names": [_canonical(naming, glossary, n) for n in g.get("names") or []]}
        for g in round_.get("groups") or [] if isinstance(g, dict) and g.get("names")
    ]
    return carried or groups_from_titles(
        [_canonical(naming, glossary, t) for t in round_.get("expected") or []])


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


def applicable(verdict: dict) -> bool:
    """Whether the capture check says anything about this capture (hub #154 §1).

    False for a capture the check does not apply to — an RTA, which has no impulse. Since the
    method's v3.0.53 its verdict keeps `applicable: false` next to `ok: false`, and reading `ok`
    alone put every RTA of a phase-0 round in "taken, unusable". Absent means it applies, as every
    verdict written before did.
    """
    return (verdict or {}).get("applicable", True) is not False


def absent(verdict: dict) -> bool:
    """The check found NO curve under that title — an absent capture, not a bad one.

    The Arbiter, 2026-09-23: red is for a curve that is there and fails (retake it); a curve that
    is not there is yellow, waiting to be taken. The method's check reports both as `ok: false`,
    the absent one with REW's own «No measurement titled …» — sixteen of those once painted a
    whole round red while nothing had been measured badly at all.
    """
    return any("no measurement titled" in str(issue).lower()
               for issue in (verdict or {}).get("issues") or [])


def taken_as_is(project_dir: Optional[Path] = None) -> dict[str, str]:
    """`uuid -> title` of the captures the tuner took «as it is» in the import window (tcc#21).

    The method's verdict on such a capture stays its own — unusable, and its step gate counts it
    so (the Arbiter accepted that). The card is TCC's checklist of what the tuner did, and he took
    it: green, with the reason on the row (finding 147).
    """
    from autosound_tcc.core import capture_import

    return {uuid: str(entry.get("title") or "")
            for uuid, entry in capture_import.load_imported(project_dir).items()
            if entry.get("as_is")}


# ---- tcc#149: the card agrees with the import window on a sweep's own range ------------------
# A patch until the method's own check reads a sweep's range (hub #247, TCC-049). At the re-pin
# that carries it, drop this block and its uses (`window_checked`, `held_by_the_window`,
# `flagged_by_the_window` below, and the `own_range` state of `verdict_state` with its `window`),
# `MeasItem.own_range`, `measOwnRange*`, and `Candidate.checked` with what writes it.
# The clash half (`flagged_by_the_window`, `CLASHES`, the clash names in `checked`) is not about the
# band: keep it at that re-pin unless the method's check also reads titles by then.


def window_checked(project_dir: Optional[Path] = None) -> dict[str, str]:
    """`uuid -> what the import window's check said` (`capture_import.window_verdicts`)."""
    from autosound_tcc.core import capture_import

    return capture_import.window_verdicts(project_dir)


def held_by_the_window(verdict: dict, checked: dict) -> bool:
    """Whether a failing verdict of the method's is its «covers … — truncated» alone, on a capture
    the import window found usable over its own range — by the uuid the verdict pins, never by
    title, so a re-take under the same name is judged on its own. The method asks over 20-20000 Hz
    and every band-limited sweep reads truncated there (finding 146); the window asked over the
    sweep's own range. The verdict itself stays the method's, and so does its step gate."""
    from autosound_tcc.core import capture_import

    if not verdict or verdict.get("ok") or not applicable(verdict) or absent(verdict):
        return False
    uuid = str(verdict.get("uuid") or "")
    return (bool(uuid) and checked.get(uuid) == capture_import.CHECKED_USABLE
            and capture_import.only_truncated(verdict.get("issues")))


def flagged_by_the_window(verdict: dict, checked: dict, marked: dict) -> bool:
    """Whether the import window said this capture's title contradicts its data — the wrong kind (a
    sweep titled `(rta)`, an RTA titled `(sw)`) or another driver (a tweeter peaking in a sub's
    range, the review's m4) — and the tuner took it as it is there. The method reads no titles, so
    its verdict is a plain pass or no judgement at all; the card says what the window said. By the
    uuid the verdict pins."""
    from autosound_tcc.core import capture_import

    uuid = str((verdict or {}).get("uuid") or "")
    return bool(uuid) and uuid in marked and checked.get(uuid) in capture_import.CLASHES


def _answered_as_is(verdict: dict, title: str, marked: dict, keys: set, key) -> bool:
    """Whether a failing verdict is about a capture taken as it is. By the uuid the verdict pins:
    a re-take under the same title is another capture and is judged on its own. By the title only
    when the verdict pins no uuid at all — and never for an AMBIGUOUS one, which pins none because
    REW holds more than one curve under the title: by the method (v3.1.2, H I-8) it is unusable
    until renamed, and the «as it is» answered for one of those curves is no answer for the title
    (the re-review of #175 TA-8)."""
    if not verdict or verdict.get("ok") or not applicable(verdict) or absent(verdict):
        return False
    uuid = str(verdict.get("uuid") or "")
    if uuid:
        return uuid in marked
    if verdict.get("ambiguous"):
        return False
    return title in marked.values() or (key is not None and key in keys)


def _row(name: str, status: str, issues: Optional[str], as_is: bool, own_range: bool = False,
         **fields) -> MeasItem:
    """One checklist row. «Taken as it is» explains a GREEN row — the tuner's answer, in place of
    the method's reasons; on a row a skip or a change turned another colour, that row's own
    reason stands (review of finding 147, M3). So does «usable over its own range» (tcc#149)."""
    said = as_is and status == STATUS_DONE
    own = own_range and status == STATUS_DONE and not said
    return MeasItem(name=name, status=status, extra=None if said or own else issues, as_is=said,
                    own_range=own, **fields)


#: What a capture's recorded verdict means to the Arbiter — `verdict_state`'s five answers.
VERDICT_FINE = "fine"
VERDICT_AS_IS = "as_is"
VERDICT_OWN_RANGE = "own_range"
VERDICT_ABSENT = "absent"
VERDICT_BAD = "bad"


def verdict_state(verdict: dict, title: str, as_is: dict, window: dict, *, key=None,
                  keys=frozenset()) -> str:
    """Whether a capture's verdict needs the Arbiter, decided once (#175, TA-8). The card, the
    window's check loop (`to_check`) and the strip after a check (`unusable_lines`) all read it;
    three places decided it before, and a text parse of the check's output was one of them.

    `verdict` is the method's own, as it recorded it (`taken[title]["verified"]`), and `title` the
    capture's; `as_is` is `taken_as_is()`, `window` `window_checked()`. The answer is one of:

    * `fine` — ok, or the check does not apply (an RTA: `applicable: false`, hub #154 §1);
    * `as_is` — failing, and the tuner took it as it is (finding 147);
    * `own_range` — failing «truncated» alone, on a sweep the import window passed over its own
      range (tcc#149): kept in this one place, so dropping it after hub #247 is one deletion;
    * `absent` — no curve under that title (the Arbiter, 2026-09-23: waiting, not bad);
    * `bad` — a curve that is there and fails: a retake to decide on. So is a capture never
      checked (`{}`), as the method's own gate counts it (`unusable_captures`).

    Each reader maps the answer its own way, and that is why it is not one boolean: `absent` is
    waiting on the card and «check again» in the window. The verdict stays the method's, and so
    does its step gate. As-is is by the uuid the verdict pins; with none, by `title` — or by `key`
    among `keys`, the card's name keys of the titles taken as is (its rows are derived names)."""
    verdict = verdict or {}
    if verdict.get("ok") or not applicable(verdict):
        return VERDICT_FINE
    if absent(verdict):
        return VERDICT_ABSENT
    if _answered_as_is(verdict, title, as_is, keys, key):
        return VERDICT_AS_IS
    if held_by_the_window(verdict, window):
        return VERDICT_OWN_RANGE
    return VERDICT_BAD


def to_check(round_: dict, rew_titles, project_dir: Optional[Path] = None) -> list[str]:
    """What the window's capture check asks the method about (SCR-040): each title the round
    expects that REW holds and the round TOOK, whose verdict is not settled — `bad` or `absent`.

    Only what the round took (tcc#21): checking whatever REW showed made a dud left for a re-take
    «брак — знятий» and a good sweep nobody ticked green, and a title in REW's list is not this
    project taking it in (the Arbiter, 2026-09-06). What still stands (#175): a superseded row is
    a typo's trace. Settled is `fine`, `as_is` and `own_range`: none of those verdicts will change,
    and each check is a pull from REW and a journal event — an RTA's, read as unchecked, started
    one on every scan of REW (hub #154 §1). An absent one is asked again: the curve may be there
    now."""
    held = {str(title) for title in rew_titles}
    taken = process_view.standing(round_)
    as_is, window = taken_as_is(project_dir), window_checked(project_dir)
    return [str(title) for title in round_.get("expected") or []
            if str(title) in held and str(title) in taken
            and verdict_state(taken[str(title)].get("verified"), str(title), as_is, window)
            in (VERDICT_ABSENT, VERDICT_BAD)]


@dataclass(frozen=True)
class NotRun:
    """A strip line about a capture check that did not run (R-ax), held until its cause ends — a
    warning has no clock, and one that outlives its cause teaches people to ignore the strip (the
    G6+G7 review's I1). The line was taken back only in the result of a check of TCC's, and two
    ordinary ends of a round run none: the session's own `check_captures` recording every title
    asked (nothing left to check), and the session closing the round.

    `line` is what the strip said; `round_id` the round it was about; `asked` the titles the
    check was handed; `since` when it did not run, as the method stamps a verdict (`at`, UTC to
    the second) — or "" for any verdict at all."""

    line: str
    round_id: Optional[str]
    asked: tuple[str, ...]
    since: str = ""

    @classmethod
    def at(cls, line: str, asked) -> "NotRun":
        """The line, said now, about the round as it stands now (`process_view.capture_round`)."""
        return cls(line, (process_view.capture_round() or {}).get("id"),
                   tuple(str(t) for t in asked or ()),
                   datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def ended(self, round_: Optional[dict], rew_titles, project_dir: Optional[Path] = None) -> bool:
        """Whether the cause has ended, in `round_` (`process_view.capture_round()`): it closed,
        or another round is open; or each title asked has a verdict recorded since — anybody's
        check, the session's own, fine or bad — or is no longer one `to_check` asks about. Never
        while the round cannot be read (None): nothing is known then. A check handed no titles
        ends only with its round. The same second counts as since: a check busy behind the
        session's gives up while that one is still writing."""
        if round_ is None:
            return False
        if round_.get("closed") or (self.round_id is not None
                                    and round_.get("id") != self.round_id):
            return True
        if not self.asked:
            return False
        pending = set(to_check(round_, rew_titles, project_dir))
        taken = process_view.standing(round_)

        def recorded_since(title: str) -> bool:
            verdict = (taken.get(title) or {}).get("verified") or {}
            return bool(verdict) and str(verdict.get("at") or "")[:19] >= self.since[:19]

        return all(title not in pending or recorded_since(title) for title in self.asked)


def unusable_lines(round_: dict, asked, project_dir: Optional[Path] = None) -> list[str]:
    """What the strip says after a check that ran: `<title> — <issues joined by "; ">`, in the
    checker's own words, for each title of `asked` — what the check was handed — whose verdict the
    method RECORDED reads `bad`, in the order asked (#175, TA-8).

    Read from the record, not the check's text: that text has a line for every expected title, one
    not handed as `UNUSABLE … не перевірено` (tcc#21, review I5), and it was parsed in two places.
    No line for `as_is` (its row is green «taken as it is», review of finding 147 I1), `own_range`
    (tcc#149) or `absent` (waiting, not unusable). None for a title with no verdict recorded
    either: never «everything is bad» — a check that did not run says so itself (R-ax)."""
    taken = process_view.standing(round_)
    as_is, window = taken_as_is(project_dir), window_checked(project_dir)
    lines = []
    for title in asked or ():
        verdict = (taken.get(str(title)) or {}).get("verified")
        if verdict and verdict_state(verdict, str(title), as_is, window) == VERDICT_BAD:
            lines.append(f"{title} — {'; '.join(str(i) for i in verdict.get('issues') or [])}")
    return lines


def _round_is_at(round_: dict, version, naming, glossary) -> bool:
    """Whether a round was captured at series `version`: by its own `version`, or by the `_N` its
    titles carry (hub #153 C).

    The two can differ. A round opened with the ledger version (`capture-start v_001`) holding
    `_49` titles is at 49: the ledger's `v_NNN` and the DSP state `_N` are different counters (the
    method's naming-and-structure §3, §5), and its own `protective_record_for` finds a round by
    either.
    """
    wanted = str(version).lstrip("v_").lstrip("0")
    if str(round_.get("version") or "").lstrip("v_").lstrip("0") in ("", wanted):
        return True
    for title in list(round_.get("expected") or []) + list(process_view.standing(round_)):
        entry = naming.parse_name(str(title), glossary)
        if entry and str(entry.get("version_n")) == wanted:
            return True
    return False


def build_session(
    phase: str,
    version,
    titles: list[str],
    project_dir: Optional[Path] = None,
    taken: Optional[list[str]] = None,
    retake: Optional[list[str]] = None,
) -> Optional[MeasSession]:
    """One capture task: what `phase` expects at `version`, checked against `titles` from REW.

    `retake` names the titles whose curve in REW the tuner left on «Re-take» in the import window:
    yellow, waiting for a new sweep, rather than blue, offered for import (finding 147).

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
    live_round = process_view.capture_round(project) or {}
    round_open = bool(live_round) and not live_round.get("closed")
    # An OPEN round is the task, whatever the phase plan predicts (finding 64, tcc#60): round
    # `cap_016` was issued with six positions and the panel showed phase 2's 24, in five columns,
    # because the plan was read first and the round only when the plan was empty. A round is a
    # fact, a phase plan is a prediction about it. Its own `groups` when it carries them (skill
    # #83: label, method, names beside `expected`), else its list grouped by method.
    groups_spec = _round_groups(live_round, naming, glossary) if round_open else []
    if not groups_spec:
        groups_spec = naming.expected_groups(phase, glossary, version)
    if not groups_spec:
        # A phase whose plan captures nothing (the skill's `_CAPTURE_PLAN["1"]` is literally `[]`
        # — phase 1 computes from what phase 0 took) and no round open: nothing asked for.
        return MeasSession(
            id=f"v{version}",
            series=str(version),
            version={"en": f"Phase {phase} · no capture",
                     "uk": f"Фаза {phase} · без замірів"},
            groups=(),
        )
    # With no round open the live task is the NEXT round, a new pass (finding 57): the closed
    # pass's takes credited it, and «next round ●» listed every capture green before anything was
    # captured. Those takes stay on that round's own entry in the picker. A project that has
    # never run a round keeps the checklist it had, credited from the import store.
    next_round = not round_open and bool(process_view.capture_rounds(project))

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
        if not _round_is_at(round_at, version, naming, glossary):
            continue
        for title in process_view.standing(round_at):
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
    round_ = live_round if round_open or not next_round else {}
    # What the round took that still STANDS (#175): a superseded row is a typo's trace — taken
    # under the wrong title and corrected — and every read below asks the method's rule of it.
    recorded_taken = {str(t) for t in process_view.standing(round_)}
    # A skip and a verdict are keyed the same way "taken" is — BY KEY, not by the string. The
    # round records the title as somebody typed it in REW (`sw_01 (sw)`); the checklist derives
    # `sw_1 (sw)`. The taken half was corrected on the live project; these two are the same fault
    # in the same function, found by making the fixtures write titles the way a person does.
    # A decision ruled out and a verdict of "unusable" are exactly the facts that must not be lost
    # to a zero.
    recorded_skipped = {str(t) for t in (round_.get("skipped") or {})}
    skipped_keys = {_key(t) for t in recorded_skipped} - {None}
    # What the arithmetic said about each curve (SCR-040). A verdict outranks "a title exists":
    # a sweep that never finished and a muted channel both leave a title behind, and every later
    # phase used to compute on them. Over the standing rows only (#175): `verdicts_by_key` is the
    # last row of a key, and a superseded `w_R_1 (sw)` under the key of the `w-R_1 (sw)` that
    # corrected it lent the corrected row its verdict.
    verdicts = {
        str(title): entry.get("verified") or {}
        for title, entry in process_view.standing(round_).items()
    }
    verdicts_by_key = {
        _key(title): verdict for title, verdict in verdicts.items() if _key(title) is not None
    }
    # What an OPEN round asks for, it asks for again (tcc#38, #39). The rounds loop above credits
    # every pass at this version, and that is right for a checklist nobody re-opened — but a new
    # round that expects `tw-L_1 (sw)` is a new pass at it, and crediting the old take read an empty
    # round as finished: the import window expected nothing and offered no names, and the round
    # list painted it green (live project, 2026-09-14). For those names only a take recorded in
    # THIS round answers; the import store is history here too, so it does not either.
    asked_again = set()
    if next_round:
        asked_again = {_key(n) for spec in groups_spec for n in spec["names"]} - {None}
    elif not round_.get("closed"):
        asked_again = {_key(t) for t in (round_.get("expected") or [])} - {None}
    taken_here = {_key(t) for t in recorded_taken} - {None}
    retake_keys = {_key(t) for t in retake or ()} - {None}
    as_is_marked = taken_as_is(project)
    as_is_keys = {_key(t) for t in as_is_marked.values()} - {None}
    window = window_checked(project)  # tcc#149, until hub #247

    def not_taken(key) -> str:
        """Blue while REW holds it under this name, yellow while it does not (F-056) — or while
        what it holds is the curve left for a re-take (finding 147)."""
        if key is not None and key in parsed and key not in retake_keys:
            return STATUS_FOUND
        return STATUS_WAIT

    def verdict_for(name: str):
        """The row's verdict and what it means (`verdict_state`); `(None, None)` for a capture
        never checked, whose row is what was taken."""
        entry = naming.parse_name(name, glossary)
        key = naming.name_key(entry) if entry else None
        verdict = verdicts.get(name) or verdicts_by_key.get(key)
        if not verdict:
            return None, None
        return verdict, verdict_state(verdict, name, as_is_marked, window, key=key,
                                      keys=as_is_keys)

    def as_is_for(name: str) -> bool:
        verdict, state = verdict_for(name)
        return state == VERDICT_AS_IS or flagged_by_the_window(verdict, window, as_is_marked)

    def own_range_for(name: str) -> bool:
        return verdict_for(name)[1] == VERDICT_OWN_RANGE

    def status_for(name: str) -> str:
        entry = naming.parse_name(name, glossary)
        key = naming.name_key(entry) if entry else None
        if name in recorded_skipped or (key is not None and key in skipped_keys):
            return STATUS_SKIPPED  # a decision, and it outranks both REW and the derivation
        state = verdict_for(name)[1]
        if state == VERDICT_ABSENT:
            return not_taken(key)  # not there: yellow, waiting — not a bad curve
        if state == VERDICT_BAD:
            # The panel's own legend already calls this "taken, unusable" -- which is exactly what
            # a capture that came back and failed the check is. Unless the tuner took it as it is:
            # then it is taken like any other, below (finding 147).
            return STATUS_STALE
        if key is not None and key in asked_again:
            if key not in taken_here and name not in recorded_taken:
                return not_taken(key)  # asked for again by the open round, not taken in it yet
        elif key not in taken_keys and name not in recorded_taken:
            # Not done, even when REW is showing a curve by that name: a title in another
            # application's list is not this project taking a measurement in (user, 2026-09-06).
            # It is blue, though — there to be taken (F-056) — and the tick is what makes it done.
            return not_taken(key)
        # Both names a renamed channel answers to (SCR-039): a `config_change` names whichever the
        # session was using, and the capture's title carries whichever it was typed under. Either
        # side alone would leave a real invalidation looking like a clean capture.
        codes = {(entry or {}).get("code"), (entry or {}).get("code_current")} - {None}
        return STATUS_STALE if codes & set(stale) else STATUS_DONE

    def issues_for(name: str) -> Optional[str]:
        """Why a capture is unusable, in the checker's own words — the panel shows it on hover.

        Nothing for a capture the check does not apply to (an RTA): "this check does not apply"
        trailed every RTA row, cut off, and said nothing anyone needed (finding 30). A green row
        taken as it is says that instead (`_row`, finding 147)."""
        verdict = verdicts.get(name) or {}
        if not applicable(verdict):
            return None
        issues = verdict.get("issues") or []
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
            _row(name, status_for(name), issues_for(name), as_is_for(name), own_range_for(name),
                 protective=protective_for(name))
            for name in spec["names"]
        )
        groups.append(MeasGroup(type=spec["label"], items=items, method=spec.get("method")))

    extras = _extras(naming, glossary, parsed, groups_spec, version, taken_keys, retake_keys)
    if round_open:
        # Captured in this round though nobody asked, under a title the grammar cannot read --
        # `D_L w+m_7 (rta) inv`, the `D_` refused (S-042; read for one release, v3.0.65, and
        # refused again since v3.0.66, hub #232). On neither list above, it never showed until
        # the round closed (tcc#122, W-4's review of #109). As typed, marked for the panel.
        listed = {n for spec in groups_spec for n in spec["names"]}
        listed |= {str(t) for t in round_.get("expected") or []}
        extras += tuple(
            _row(title, status_for(title), issues_for(title), as_is_for(title),
                 own_range_for(title), additional=True, unread=True)
            for title in sorted(recorded_taken - listed) if _key(title) is None
        )
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
        series=str(version),
        round_id=round_id,
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
    retake: Optional[list[str]] = None,
) -> Optional[tuple[MeasSession, ...]]:
    """The live capture task, followed by every past round, newest first.

    The panel has had a session picker, a read-only history view and a plan-step link since it was
    built against the mock — and no supplier for any of it: the window only ever handed it one
    session (user, 2026-08-11: "shows v4, no history of v1"). The rounds were on disk the whole
    time, in the journal.
    """
    project = Path(project_dir or config.project_dir())
    live = build_session(phase, version, titles, project, taken, retake)
    if live is None:
        return None
    state = process_view.load_state(project)
    marked = taken_as_is(project)
    window = window_checked(project)  # tcc#149, until hub #247
    past = [
        session
        for round_ in process_view.capture_rounds(project)
        if str(round_.get("id") or "") != live.id
        for session in (_session_for_round(round_, state, marked, window),)
        if session is not None
    ]
    return (live, *past)


def _session_for_round(round_: dict, state: Optional[dict], as_is: Optional[dict] = None,
                       checked: Optional[dict] = None) -> Optional[MeasSession]:
    """One past round as a read-only session: what it asked for, and what became of each item.

    Statuses come from the round's own record and nothing else — REW is not consulted. A series
    captured three weeks ago is history whether or not that project is still open in REW, which is
    the whole reason SCR-034 wrote the round down in the first place.
    """
    expected = [str(t) for t in (round_.get("expected") or [])]
    taken = {str(k): v for k, v in process_view.standing(round_).items()}
    skipped = {str(k) for k in (round_.get("skipped") or {})}
    if not expected and not taken:
        return None
    for title in taken:
        if title not in expected:
            expected.append(title)  # captured though nobody asked: still part of what happened

    marked = dict(as_is or {})
    window = dict(checked or {})  # tcc#149, until hub #247

    def state_for(name: str) -> Optional[str]:
        """What the row's verdict means (`verdict_state`); None for one never checked."""
        verdict = (taken.get(name) or {}).get("verified")
        return verdict_state(verdict, name, marked, window) if verdict else None

    def as_is_for(name: str) -> bool:
        """Taken as it is, as on the live card (finding 147): history does not turn it red."""
        return (state_for(name) == VERDICT_AS_IS or flagged_by_the_window(
            (taken.get(name) or {}).get("verified") or {}, window, marked))

    def own_range_for(name: str) -> bool:
        return state_for(name) == VERDICT_OWN_RANGE

    def status_for(name: str) -> str:
        if name in skipped:
            return STATUS_SKIPPED
        if name not in taken:
            return STATUS_WAIT  # asked for, never taken, and the round closed anyway
        state = state_for(name)
        if state == VERDICT_ABSENT:
            return STATUS_WAIT
        return STATUS_STALE if state == VERDICT_BAD else STATUS_DONE

    def issues_for(name: str) -> Optional[str]:
        # The skip reason comes first, and the order is the point: a skipped capture is ALSO
        # reported by the checker as "no measurement titled ...", which is true and useless. Why a
        # human decided not to take it outranks the arithmetic noticing it is not there.
        if name in skipped:
            return (round_.get("skipped") or {}).get(name, {}).get("reason")
        verdict = (taken.get(name) or {}).get("verified") or {}
        if not applicable(verdict):
            return None  # an RTA: the check has nothing to say about it (finding 30)
        issues = verdict.get("issues") or []
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
                _row(name, status_for(name), issues_for(name), as_is_for(name),
                     own_range_for(name), protective=protective_for(name))
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
        series="" if ver == "?" else ver,
        round_id=rid,
        version={
            "en": f"Series {ver} · phase {phase} · {rid}",
            "uk": f"Серія {ver} · фаза {phase} · {rid}",
        },
        groups=groups,
        used_in_steps=process_view.steps_using(state, expected),
    )


def _extras(naming, glossary, parsed: dict, groups_spec: list, version,
            taken_keys: Optional[set] = None,
            retake_keys: Optional[set] = None) -> tuple[MeasItem, ...]:
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
        if key in wanted:
            continue
        # An impedance sweep has no `_N` (the method's v3.0.53) and sits with whatever series is on
        # screen — which one does not matter (the Arbiter, 2026-09-17). Every other extra is ours
        # only at this series.
        if entry.get("method") != "imp" and (entry["version_n"] or entry["version"]) != version_n:
            continue
        if taken_keys is None or key in taken_keys:
            status = STATUS_DONE
        elif key in (retake_keys or ()):
            status = STATUS_WAIT  # the curve REW holds was left for a re-take (finding 147)
        else:
            status = STATUS_FOUND
        out.append(
            MeasItem(
                name=entry["title"],
                # Ours, at this version, off the checklist — and green only once it was taken in.
                # A curve REW is holding is an offer, not a capture: blue (see `build_session`).
                status=status,
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
