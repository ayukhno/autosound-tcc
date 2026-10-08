"""Drive the skill's process writer (`rew_tool/state/process.py`) — TCC never writes the journal.

Same boundary as `core/profile_writer.py`, for the same reason, and closing the same kind of hole.
`dsp_profile.json` used to be written by TCC because the skill had no writer; `process/journal.jsonl`
has had a writer all along, and the hole was on this side: the MCP surface offered the model
`report_phase`, which *reads* the process and refreshes what the Arbiter sees, and nothing at all
that records a move. So an agent that wanted to record one had to find `state/process.py` on disk
and run it through a shell, which is exactly where the measured runs came apart — one model resolved
the path and the interpreter by itself and recorded eleven events, another used the same tools and
recorded none (`spike/HANDOFF.md` §3).

What crosses this boundary is an INTENT ("the `lang` step is done, here is the evidence"), never a
finished file. The gates stay on the skill's side, where the schema is owned: `done` without
evidence is refused there, and the refusal comes back verbatim through `ProcessWriterError` — the
interviewer needs to hear what the gate said, not a generic failure.

Two things this fixes for free, both measured skill defects (SCR-028, SCR-029): the interpreter is
our own venv's, never a bare `python` the shell has to guess — `child.script_interpreter()`, which
is that venv's CONSOLE binary rather than the windowed `pythonw.exe` TCC itself runs under, because
a script with no console hands none down and the git it calls then opens a window (TCC-006) — and
the script is the one of the copy the project is bound to (`method_binding`), not an address only
one harness understands. Both happen in `method_cli`, the one place that says which script of the
method's `rew_tool/` runs and in what environment, and where all but two of them are started: the
two whose child cannot be its bounded run (the contract check a caller cancels, the intake form's
server) take its `resolve` and keep a `Popen` of their own. A binding TCC will not run answers
`Refused` there, with its own sentence.

Reads stay where they were: `mcp_server._load_process_state()` imports the skill's module in-process
and calls `Process(...).load()`. Writes go out-of-process for the same reason profile writes do —
one implementation of "record a step" in the world rather than an in-process copy that drifts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from autosound_tcc.core import app_log, method_binding, method_cli

# Local file I/O and a JSON rewrite; anything near this is a hang, not slowness.
DEFAULT_TIMEOUT_S = 20.0

#: The first line Python prints for an exception nothing caught. The interpreter then exits 1, as
#: `process.py`'s `_main` does for its own refusal — so the exit code alone cannot tell the method's
#: answer from a crash, where the code is the answer (`close_session`, `capture-supersede`). The
#: stderr can (#169 review I1).
_TRACEBACK = "Traceback (most recent call last):"
#: How `_main` says a refusal (a `ProcessError`, an `IndexError`): this, then its sentence.
_REFUSAL = "error: "

#: The writer, relative to the method's `rew_tool/`: `method_cli`'s name for it, so the script
#: whose flags `spawn` checks is the one these writers run (#169, N19).
_SCRIPT = method_cli.PROCESS_SCRIPT

#: Every command TCC sends, and the first method tag whose `process.py` has it — read from the
#: skill's history (2026-09-14), never guessed. `2.8.0` is the oldest tag with the file at this
#: path, so for those it means "by then", not "since then". An old method answers an unknown command
#: with its usage text; `_refuse_if_too_old` turns that into this version (tcc#26).
#: `capture-supersede` and `handoff` were read on 2026-10-07 as the first release tag whose
#: `process.py` dispatches the command (`git show <tag>:…/state/process.py`, tags in version order):
#: the submodule is a shallow clone, and `git log -S` names its cut-off commit as the one that added
#: any command older than the cut — `session-close` came out as 3.0.52 that way.
LANDED_IN = {
    "add-step": "2.8.0",
    "block": "2.8.0",
    "capture-check": "3.0.0",
    "capture-close": "3.0.0",
    "capture-knobs": "3.0.47",
    "capture-protective": "3.0.20",
    "capture-skip": "3.0.0",
    "capture-start": "3.0.0",
    "capture-supersede": "3.0.60",
    "capture-taken": "3.0.0",
    "check": "2.8.0",
    "decision": "3.0.0",
    "done": "2.8.0",
    "enter-phase": "2.8.0",
    "handoff": "3.0.60",
    "listening-verdict": "3.0.29",
    "listening-verdicts": "3.0.29",
    "plan": "2.8.0",
    "reviewer": "2.8.0",
    "session-close": "3.0.43",
    "session-start": "3.0.0",
    "show": "2.8.0",
    "skip": "2.8.0",
    "start": "2.8.0",
    "target": "2.8.0",
}


#: `method_cli`'s, under the names every caller already catches — the same classes, not copies, so
#: an `except process_writer.ProcessWriterError` (or `.Busy`, `.Refused`, `.UnknownFlag`) catches
#: what `method_cli` raises.
ProcessWriterError = method_cli.ProcessWriterError
Busy = method_cli.Busy
Refused = method_cli.Refused
UnknownFlag = method_cli.UnknownFlag


class TooOld(ProcessWriterError):
    """The project's copy of the method answered a command with its usage text: it is older than
    the command (`LANDED_IN`), which `_refuse_if_too_old` says. A class of its own so a caller
    whose answer to that alone is «update the method» (`handoff`) can tell it from a run that got
    no answer — a crash, a timeout — where updating mends nothing (#169 review I4)."""


def script_path() -> Path:
    """TCC's own `process.py`, for a caller with no project: `is_available`, a bare CLI run beside
    TCC (`test_writer_race.py`). A write runs the PROJECT's bound copy (`method_cli.spawn`); this is
    the copy a project with no entry is bound to, taken from the binding's own answer
    (`method_binding.own_copy`) so the two cannot drift apart."""
    return method_binding.own_copy() / "rew_tool" / _SCRIPT


def is_available() -> bool:
    """Whether TCC's own copy has its writer. A project bound to another copy is answered for by
    that copy when it writes — `Refused`, or the script not found there."""
    return script_path().is_file()


def _process_dir(project_dir: Path) -> Path:
    """The skill owns the layout; `process.py` creates the directory on first write."""
    return project_dir / "process"


def _spawn(
    project_dir: Path, args: list[str], timeout_s: float = DEFAULT_TIMEOUT_S, **kw
) -> tuple[int, str, str]:
    """`process.py <process-dir> <command> …` through `method_cli.spawn`, which holds the lock,
    bounds the child and gives it its environment. `kw` is spawn's own: `lock=`, `lock_wait_s=`."""
    return method_cli.spawn(
        project_dir, _SCRIPT, [str(_process_dir(project_dir)), *args], timeout_s=timeout_s, **kw
    )


def _run(project_dir: Path, args: list[str], timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    """One call, and a non-zero exit is a failure. Every command here works that way except
    `session-close`, whose exit code is an ANSWER — see `close_session`."""
    code, out, err = _spawn(project_dir, args, timeout_s)
    _refuse_if_too_old(args[0], out, err)
    if code != 0:
        raise ProcessWriterError((err or out).strip() or f"process.py exited {code}")
    return out


def enter_phase(project_dir: Path, phase: str) -> str:
    """Make a phase current. Phases are the skill's fixed skeleton (−1…5), never invented."""
    return _run(project_dir, ["enter-phase", str(phase)])


def add_step(project_dir: Path, step_id: str, name: str, situational: bool = False) -> str:
    """Add a plan step. `situational=True` marks it `source: project` — an insert this car needed,
    as opposed to one instantiated from the phase template."""
    args = ["add-step", step_id, name]
    if situational:
        args.append("--project")
    return _run(project_dir, args)


def start_step(project_dir: Path, step_id: str) -> str:
    """Begin, or re-begin, a step. A re-begin is attempt N+1 — a redo is recorded, never erased."""
    return _run(project_dir, ["start", step_id])


def finish_step(project_dir: Path, step_id: str, evidence: list[str]) -> str:
    """Mark a step done. Evidence is required by the skill and this does not soften that.

    Passing an empty list reaches the same refusal the CLI gives, just without spending a
    subprocess on it.
    """
    if not evidence:
        raise ProcessWriterError(
            f"step {step_id!r} cannot be done without evidence "
            "(measurement names, ledger vNNN, or an audit entry)"
        )
    return _run(project_dir, ["done", step_id, *[str(e) for e in evidence]])


def skip_step(
    project_dir: Path, step_id: str, reason: str = "", superseded_by: str = ""
) -> str:
    """Supersede a step. It stays visible in the plan — steps are never deleted (SCR-004).

    One of the two is REQUIRED (SKL-029, skill v3.0.47): the step that replaces this one, or a
    sentence saying why it is not being done. A skip with neither cannot be told from a step
    forgotten, and the next session proposes it again — which is what the skill's own live journal
    showed, nine skips out of nine.

    `superseded_by` travels as `--superseded-by`, never positionally. The CLI reads every bare word
    after the id as the reason, so the id used to land as a reason whose text happened to be "2.4",
    with the link written nowhere — and no test saw it, because every other test drives `Process`
    in-process, where a keyword stays a keyword.
    """
    if not superseded_by and not reason.strip():
        raise ProcessWriterError(
            f"step {step_id!r} cannot be skipped without a reason "
            "(the step that supersedes it, or a sentence saying why it is not being done)"
        )
    args = ["skip", step_id]
    if reason.strip():
        args.append(reason.strip())
    if superseded_by:
        args += ["--superseded-by", superseded_by]
    return _run(project_dir, args)


def block_step(project_dir: Path, step_id: str, reason: str) -> str:
    """Mark a step blocked, with the reason that blocks it."""
    return _run(project_dir, ["block", step_id, reason])


def record_reviewer(
    project_dir: Path,
    vendor: str,
    model: str,
    step: str = "",
    review: str = "",
    mode: str = "",
) -> str:
    """Record a reviewer/critic call against the step it was called on.

    `review` is the project-relative path to the critique's own text, which the skill's reviewer
    script writes (SCR-027) — the record used to say a review happened and lose what it argued.
    `mode` separates a channel that ran from one the Arbiter worked by hand (`clipboard`), because
    a review answered by paste must not read as no review at all.
    """
    args = ["reviewer", vendor, model]
    if step:
        args.append(step)
    if review:
        args.append(f"--review={review}")
    if mode:
        args.append(f"--mode={mode}")
    return _run(project_dir, args)


def _protective_legs(channel: str, legs) -> list[str]:
    """`<channel> OFF` or `<channel> --hp f type slope --lp …`, as the CLI takes them.

    Shared by `set_protective` and `amend_protective` so the two cannot spell a leg differently —
    a correction that reached the journal in another shape than the record it corrects would be
    the one thing worse than no correction.

    Only what was actually given. Padding a half-filled leg with empty strings made the CLI's own
    parser fail on `int("")` — a ValueError where the gate has a sentence ready ("--hp needs three
    values: f type slope … a leg missing any of them cannot be taken back out later"). Sending
    three values when two were typed hides the refusal written for exactly this.
    """
    out = [str(channel)]
    if legs == "OFF":
        return out + ["OFF"]
    for kind in ("hp", "lp"):
        leg = (legs or {}).get(kind)
        if leg in (None, "OFF"):
            continue
        values = [leg.get("f"), leg.get("type"), leg.get("slope")]
        out.append(f"--{kind}")
        out += [str(value) for value in values if value not in (None, "")]
    return out


def set_protective(project_dir: Path, channel: str, legs, source: str = "user") -> str:
    """Declare what was in the signal path for one channel of the OPEN capture round.

    `legs` is `"OFF"` -- an ANSWER, meaning this channel was swept with nothing in the chain -- or
    `{"hp": {...}, "lp": {...}}` in the ledger's crossover vocabulary. Leaving a channel out
    entirely is a THIRD thing: nobody said, and it is recorded by not calling this at all. The
    de-embed refuses that case rather than treating it as clean, which is the whole point of the
    feature.

    `source` says WHO answered — `user`, `front_end` or `default` (method `v3.0.59`, S-036). The
    CLI's own default is `user`, so a caller that says nothing signs its write as a person, and a
    bulk import doing that for ten channels in one second is the exact claim the field was added
    to stop: the method reads a front-end's blanket `OFF` as `check` rather than as an answer.
    The default is kept at `user` deliberately — the dialog IS a person, and the one caller that
    is not says so.

    Nothing is validated here. The skill refuses a leg missing `f`/`type`/`slope` at write time,
    and that refusal comes back verbatim through `ProcessWriterError` for the dialog to show: a UI
    that quietly fixes what a gate would have refused trains people to trust the UI over the gate.
    """
    args = ["capture-protective", *_protective_legs(channel, legs)]
    if source and source != "user":
        # Only when it differs: `--source` landed in `v3.0.59`, and an older method answers an
        # unknown flag with its usage text (`_refuse_if_too_old` reads that per COMMAND, not per
        # flag). Sending it only where it changes the meaning keeps the ordinary path working
        # against the method this build is paired with and against the one before it.
        args += ["--source", str(source)]
    return _run(project_dir, args)


def amend_protective(project_dir: Path, capture_id: str, channel: str, legs,
                     reason: str, source: str = "user") -> str:
    """Correct a CLOSED round's protective record, visibly as a correction (skill `#48`).

    `set_protective` needs an OPEN round, and the round most likely to need a correction is the
    one somebody has already read. The live case: a nine-position series captured with 100 Hz LR24
    on the mids and 1 kHz LR24 on the tweeters, filed as `OFF` for all ten channels. The only way
    to say so was to open a NEW round on the same version and close it with a reason saying
    nothing was measured in it — which makes "capture round" mean two things at once.

    `reason` is required BY THE GATE, and this does not soften that: a correction with no why is
    indistinguishable from a second opinion, and the refusal says exactly that. The empty string
    is passed through rather than caught here, for the same reason no other writer in this file
    validates — one implementation of the rule, on the side that owns it.

    Writes no state: a closed round is not in the slice. The correction is a journal event
    carrying the round's id, which `protective_record_for` replays as the last word on that
    channel, plus `amends` and the reason so a reader sees a correction rather than a record that
    was always this way.
    """
    args = ["capture-protective", "--amend", str(capture_id), "--reason", str(reason or "")]
    args += _protective_legs(channel, legs)
    if source and source != "user":
        args += ["--source", str(source)]
    return _run(project_dir, args)


def record_listening_verdict(
    project_dir: Path,
    pairs,
    text: str = "",
    route: str = "",
    ledger_version: str = "",
    note: str = "",
) -> str:
    """What the Arbiter heard: the pairs they ticked AND their own words, in one journal entry.

    `pairs` is `[(track_id, characteristic_id, ok)]`. Both go in and NEITHER stands for the other:
    the ticks carry structure a filter can read back, the text carries what the person meant after
    editing it. Claiming the text equals the ticks is the thing this shape exists to avoid — they
    click a phrase, then rewrite the sentence, and the two legitimately stop matching.

    `ledger_version` is the state they were listening to, and the caller must pass what it READ
    (the loaded view's version), never a remembered one: a verdict stamped with the wrong snapshot
    is worse than one with no stamp, because it looks attributable.

    Nothing is validated here. The skill checks every id against its own vocabulary and refuses an
    unknown one; that refusal comes back verbatim for the dialog to show, for the same reason the
    protective record does not pre-validate either.
    """
    args = ["listening-verdict"]
    for track, characteristic, ok in pairs:
        args += ["--pair", f"{track}:{characteristic}:{'ok' if ok else 'bad'}"]
    for flag, value in (("--text", text), ("--route", route),
                        ("--ledger-version", ledger_version), ("--note", note)):
        if value:
            args += [flag, str(value)]
    return _run(project_dir, args)


def listening_verdicts(
    project_dir: Path,
    track: str = "",
    characteristic: str = "",
    ledger_version: str = "",
) -> str:
    """Look back at what was heard, filtered. Reading, so it takes the same route as the writes
    rather than parsing the journal here — the shape of an event is the skill's business."""
    args = ["listening-verdicts"]
    for flag, value in (("--track", track), ("--characteristic", characteristic),
                        ("--ledger-version", ledger_version)):
        if value:
            args += [flag, str(value)]
    return _run(project_dir, args)


def set_target(project_dir: Path, preset: str, curve: str) -> str:
    """Point a preset at its active target curve."""
    return _run(project_dir, ["target", preset, curve])


def record_decision(
    project_dir: Path, question: str, answer: str, step: str = "", invalidates: str = ""
) -> str:
    """What the Arbiter ruled, as the answer rather than as prose about it (SCR-030).

    TCC has the machine-readable form at the moment it happens — an option the Arbiter clicked, a
    confirmation they allowed or denied — and used to discard it. The skill's own writer is still
    the only writer.
    """
    args = ["decision", question, answer]
    if step:
        args.append(step)
    if invalidates:
        args.append(f"--invalidates={invalidates}")
    return _run(project_dir, args)


def record_session(project_dir: Path, harness: str, model: str, resumed: bool = False) -> str:
    """A working session was attached — the one journal event TCC writes on its own behalf.

    Everything else here is the model recording its own work. This one it cannot record: only the
    front-end knows a session started, and without it a journal that begins at some `step_done`
    cannot tell a session that recorded nothing from a session that never happened.
    """
    args = ["session-start", harness or "?", model or "?"]
    if resumed:
        args.append("resumed")
    return _run(project_dir, args)


def close_session(project_dir: Path) -> tuple[bool, str]:
    """Stopping, said out loud. Returns (recorded, report).

    A session that ended in order used to leave no trace at all, so it read exactly like a process
    that was killed — the journal ran out of events either way (SKL-029). `session-close` fixes
    that from the skill's side; calling it is TCC's half, and there is nobody else to call it: the
    model is gone by then.

    **The exit code is an ANSWER here, not a failure.** `session-close` exits non-zero while a
    capture round or a step is still open, precisely so "we stopped" cannot be said over open
    work, and it prints what is open instead. Passing that through `_run` would turn a report into
    an exception and lose it. `recorded` is False in that case and `report` holds the skill's own
    text; nothing is written to the journal, which is the honest record.

    Exit 1 is that report only when it is one: the method's report on stdout, with no traceback.
    Its own refusal (`error: …`) is raised in its words, as `_run` raises every other; a crash —
    Python's traceback, exit 1 too — is raised in its last line and logged (`no_answer`). Handed
    back as the report, a traceback sent the model after open work that does not exist (#169
    review I1).
    """
    code, out, err = _spawn(project_dir, ["session-close"])
    _refuse_if_too_old("session-close", out, err)
    if code == 0:
        return True, out or err
    said = refusal(code, err)
    if said:
        raise ProcessWriterError(said)
    if code == 1 and out and not crashed(err):
        return False, out
    raise no_answer("session-close", code, out, err)


def refusal(code: int, err: str) -> str:
    """The method's own refusal — its stderr from the `error: ` line on — or "" when exit `code`
    with `err` is none: another exit, or exit 1 with Python's traceback, or with no such line at
    all, which is a run that crashed rather than refused (#169 review I1)."""
    if code != 1 or crashed(err):
        return ""
    lines = err.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(_REFUSAL):
            return "\n".join(lines[index:]).strip()
    return ""


def no_answer(command: str, code: int, out: str, err: str) -> ProcessWriterError:
    """The failure of a `command` whose exit code is its answer, and which gave none: a crash, or
    an exit with neither its answer nor the method's refusal. Said in one line — the last it
    printed, for a crash the exception's own — and logged at WARNING with its stderr's tail, as a
    busy answer is: the caller may have nobody left to tell (`close_session` at quit). Returned,
    for the caller to raise or to say."""
    sentence = (f"`{command}` {'crashed' if crashed(err) else 'gave no answer'} in the method: "
                f"{last_words(code, out, err)}")
    app_log.logger().warning("%s (exit %s)%s", sentence, code,
                             f"; its stderr ends:\n{method_cli.tail(err)}" if err else "")
    return ProcessWriterError(sentence)


def crashed(err: str) -> bool:
    """Whether a run's stderr holds Python's traceback: an exception nothing in the method caught."""
    return _TRACEBACK in err


def last_words(code: int, out: str, err: str) -> str:
    """The last line a run printed — stderr's first, where a traceback ends in its exception — or
    `process.py exited N` when it printed nothing."""
    lines = [line.strip() for line in (err or out).splitlines() if line.strip()]
    return lines[-1] if lines else f"process.py exited {code}"


#: The reason a title fix gives the round for superseding a row (A17).
SUPERSEDE_REASON = "renamed in REW by TCC (A17)"


def supersede_capture(project_dir: Path, wrong: str, right: str) -> tuple[int, str, str]:
    """The open round took a capture as `wrong`, and it is `right` (A17): `capture-supersede`.
    Returns `(exit code, stdout, stderr)`.

    **The exit code is an answer**, as in `close_session`: 1 with the method's refusal (`refusal`)
    — no round open, or the round never took `wrong` — which `title_fixes.supersede` reads as
    nothing left to correct; 1 with a traceback is a crash, which it does not. A write like any
    other, so it holds the lock: on the GUI thread, the short wait and then `Busy`.
    """
    args = ["capture-supersede", str(wrong), str(right), SUPERSEDE_REASON]
    code, out, err = _spawn(project_dir, args, timeout_s=30.0)
    _refuse_if_too_old("capture-supersede", out, err)
    return code, out, err


def handoff_json(project_dir: Path) -> tuple[int, str, str]:
    """Is everything the next session needs on disk (hub #201): `handoff --json`. Returns
    `(exit code, stdout, stderr)` — 0 ready, 1 not, and the JSON on stdout either way, which
    `handoff.ask` reads.

    A READ: the command writes nothing, so it takes no lock. On the GUI thread a wait behind a
    120 s `capture-check` would be the bug, and so would the lock's own `process/`, made in a
    project that has none.
    """
    code, out, err = _spawn(project_dir, ["handoff", "--json"], timeout_s=30.0, lock=False)
    _refuse_if_too_old("handoff", out, err)
    return code, out, err


def _refuse_if_too_old(command: str, out: str, err: str) -> None:
    """Turn "process.py printed its usage" into a sentence about the machine.

    An unknown command makes `process.py` dump its usage text, and that text travels back to the
    model as the error. Measured on the user's Windows VM (2026-09-09): the installed method was
    **3.0.8**, `session_close` answered with `usage: process.py <process-dir> <command>`, and the
    model read the stopping ritual as broken — then started deriving work to close that nobody had
    opened. A tool that needs a newer method is fine; one that fails without saying so is not.

    Deliberately keyed on the usage text rather than on a version comparison. The version is
    knowable (`install_report.skill_version`), but the ANSWER is not: a method can be new enough
    by number and still be a checkout without that command, and the usage dump is the thing that
    actually happened.
    """
    said = f"{out}\n{err}"
    if "usage: process.py" not in said:
        return
    since = LANDED_IN.get(command)
    has_it = f" — the method has it by v{since}" if since else ""
    raise TooOld(
        f"this project's method does not have `{command}`{has_it}. "
        "Update the method (TCC's own update row offers it), or do this step by hand; nothing "
        "here is broken on TCC's side."
    )


def start_capture(
    project_dir: Path, version: str, expected: list[str], step: str = "", origin: str = "",
    plan: bool = False, optional=(), start_method: str = "",
) -> str:
    """Open a capture round: which ledger version it is taken at, and what was asked for (SCR-034).

    A round, not a version — the version names the config the measurements were taken under and
    cannot tell two passes at the same config apart.

    `step` binds the round to the plan step it satisfies (SCR-040): that is what makes a re-take
    visibly attempt N of the step that asked for it, and what lets the step's own gate read the
    verdict on those captures.

    `origin` is `"<project>:<their _N>"` and says these measurements were taken SOMEWHERE ELSE
    (S-048, method `v3.0.59`). `_N` numbers one project's series, so a foreign number is refused
    without it — two projects both have a `_49` and they mean different DSP states on different
    days. Not an edge case: a second tune of the same car starts from the first one's
    measurements, which the Arbiter called the base case rather than a rarity (2026-09-20).
    Whether a number IS foreign is the method's judgement, not ours — TCC carries the answer, it
    does not re-derive the gate.

    `plan` asks the METHOD for the list (`--plan`, the Arbiter's round rule, skill #77 / SKL-054):
    what this phase measures at series `version`, for the project's channels, `optional` captures
    on it and ordered by setup from `start_method` (`sw` / `rta`). What it prints is the list the
    person reads — returned here as it is.
    """
    args = ["capture-start", str(version), *[str(t) for t in expected or []]]
    if plan:
        args.append("--plan")
    for title in optional or ():
        args += ["--optional", str(title)]
    if start_method:
        args += ["--start", str(start_method)]
    if step:
        args += ["--step", step]
    if origin:
        args += ["--origin", str(origin)]
    return _run(project_dir, args)


def capture_knobs(project_dir: Path, positions: dict) -> str:
    """The hardware controls as they stood for THIS round — `SubRC=4/4`, `RealCenter=ON`.

    A fact about the SERIES, not about one measurement: two passes taken at different knob
    positions can be told apart instead of the difference landing in a calibration offset. Not
    optional either — `verify_prediction --project` refuses with exit 4 while the open round has
    no knobs recorded (RES-007).
    """
    if not positions:
        raise ProcessWriterError("capture-knobs needs at least one NAME=POSITION")
    return _run(
        project_dir,
        ["capture-knobs", *[f"{name}={value}" for name, value in positions.items()]],
    )


def check_captures(
    project_dir: Path, titles: list[str] | None = None, session: bool = False
) -> str:
    """Run the skill's verdict over the open round and record it (SCR-040).

    TCC runs this phase because TCC is what can reach REW and hold a loop — but the arithmetic is
    the skill's, and so is the writing. Nothing here decides whether a curve is usable; it asks.

    `session=True` adds the whole-session probe — every level side by side, loudest and quietest,
    ctl1→ctl3 drift — which is step 0.6 of the virtual-first path and reads the shoot as one thing
    rather than measurement by measurement.

    Slower than the other writes: it pulls every expected measurement out of REW. Call it off the
    GUI thread.
    """
    args = ["capture-check", *[str(t) for t in titles or []]]
    if session:
        args.append("--session")
    return _run(project_dir, args, timeout_s=max(DEFAULT_TIMEOUT_S, 120.0))


def record_capture(project_dir: Path, title: str) -> str:
    """A measurement came back. One that was not on the round's list is recorded as unplanned
    rather than rejected — the derivation can only say what should have been taken."""
    return _run(project_dir, ["capture-taken", title])


def skip_capture(project_dir: Path, title: str, reason: str) -> str:
    """A capture deliberately not taken. The skill requires the reason and this does not soften
    that: skipped and not-yet-taken looked identical until the decision was recorded."""
    if not (reason or "").strip():
        raise ProcessWriterError(
            f"skipping {title!r} needs a reason -- it is a decision, not a gap"
        )
    return _run(project_dir, ["capture-skip", title, reason])


def close_capture(project_dir: Path, reason: str = "") -> str:
    """Close the open round. What is neither taken nor skipped is named as outstanding."""
    args = ["capture-close"]
    if reason:
        args.append(reason)
    return _run(project_dir, args)


def check(project_dir: Path) -> str:
    """List done steps that carry no evidence — the skill's own план-факт reconciliation."""
    return _run(project_dir, ["check"])


def plan(project_dir: Path, phase: Optional[str] = None) -> str:
    """The plan for a phase (default: the active one), as the skill prints it."""
    args = ["plan"]
    if phase is not None:
        args.append(str(phase))
    return _run(project_dir, args)


def state(project_dir: Path) -> Any:
    """The current state as the CLI reports it.

    Prefer `mcp_server._load_process_state()` in-process for reads; this exists so a caller that
    already has this module does not need a second import path for a one-off.
    """
    import json

    out = _run(project_dir, ["show"])
    try:
        return json.loads(out)
    except ValueError:
        raise ProcessWriterError(f"expected JSON from process.py show, got: {out[:200]}") from None
