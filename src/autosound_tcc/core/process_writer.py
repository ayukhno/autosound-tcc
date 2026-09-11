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
the script is located through `vendor_loader`, not through an address only one harness understands.

Reads stay where they were: `mcp_server._load_process_state()` imports the skill's module in-process
and calls `Process(...).load()`. Writes go out-of-process for the same reason profile writes do —
one implementation of "record a step" in the world rather than an in-process copy that drifts.
"""

from __future__ import annotations

import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from autosound_tcc.core import child
from autosound_tcc.core import vendor_loader

try:  # POSIX only; Windows falls back to the thread lock alone.
    import fcntl
except ImportError:  # pragma: no cover - not exercised on macOS/Linux
    fcntl = None  # type: ignore[assignment]

# Local file I/O and a JSON rewrite; anything near this is a hang, not slowness.
DEFAULT_TIMEOUT_S = 20.0

# One writer at a time, from this process and from any other. See `_exclusive`.
_LOCK_NAME = ".process-write.lock"
_THREAD_LOCK = threading.Lock()


class ProcessWriterError(RuntimeError):
    """The skill's writer refused or could not run. Carries its own message verbatim.

    A refusal is information, not a crash: `done` rejecting a step with no evidence is the план-факт
    gate doing its job (SCR-004), and the caller has to be told exactly that so it can supply the
    evidence rather than retry the same call.
    """


def script_path() -> Path:
    return vendor_loader.REW_TOOL_DIR / "state" / "process.py"


def is_available() -> bool:
    return script_path().is_file()


def _process_dir(project_dir: Path) -> Path:
    """The skill owns the layout; `process.py` creates the directory on first write."""
    return project_dir / "process"


@contextmanager
def _exclusive(project_dir: Path, timeout_s: float) -> Iterator[None]:
    """Hold the project's process-state lock for the length of one write.

    `process.py` is a read-modify-write over a single JSON file, and nothing was serialising it.
    That is not theoretical: omp starts tool calls concurrently, and a real run fired
    `enter_phase` and two `add_step`s before any of them returned — two came back with a traceback
    and the third with `active_phase: null`, leaving a plan with one nameless step in it. The model
    had done everything right.

    A file lock rather than a thread lock because the other front-end is a separate process: the
    user's own CLI can be driving the same project through the same skill (that is what
    `signal_bus` exists for), and a lock only TCC's threads respect would not see it. The skill's
    own CLI does not take this lock, so this narrows the window rather than closing it — closing it
    belongs in `process.py`, as a change request.
    """
    lock_path = _process_dir(project_dir)
    lock_path.mkdir(parents=True, exist_ok=True)
    # Nothing is ever written into it — the file IS the lock — but it is opened in text mode,
    # and a text handle with no encoding is the same defect as the one that emptied the DSP
    # panel on a Ukrainian Windows. One rule, no exceptions to remember.
    handle = (lock_path / _LOCK_NAME).open("a+", encoding="utf-8")
    try:
        if fcntl is None:  # no flock here; the caller is still serialised by `_THREAD_LOCK`
            yield
            return
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ProcessWriterError(
                        f"another writer held {lock_path / _LOCK_NAME} for {timeout_s:.0f}s"
                    ) from None
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _spawn(
    project_dir: Path, args: list[str], timeout_s: float = DEFAULT_TIMEOUT_S
) -> tuple[int, str, str]:
    script = script_path()
    if not script.is_file():
        raise ProcessWriterError(
            f"process.py not found at {script}. Run: git submodule update --init --recursive"
        )
    try:
        with _THREAD_LOCK, _exclusive(project_dir, timeout_s):
            proc = subprocess.run(
                # The CONSOLE interpreter, not ours. TCC is a GUI app, so `sys.executable` is
                # `pythonw.exe`, which has no console — and the git this script runs then opens
                # its own window. Every flash the user saw while saving was this line (TCC-006).
                [child.script_interpreter(), str(script), str(_process_dir(project_dir)), *args],
                capture_output=True,
                text=True,
                # NOT the locale's, which is what `text=True` alone means. The skill writes UTF-8
                # to disk on every platform and folds only what a CONSOLE cannot draw, so its
                # bytes are always UTF-8 — and decoding them with a Windows ANSI page turned a
                # listening verdict into mojibake on the way back (first Windows CI run,
                # 2026-09-07). The tuner's own words about what they heard are the one thing here
                # that has to survive the trip verbatim.
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                env=vendor_loader.child_env(),
                **child.quiet(),
            )
    except subprocess.TimeoutExpired:
        raise ProcessWriterError(f"process.py timed out after {timeout_s:.0f}s") from None
    except OSError as exc:
        raise ProcessWriterError(str(exc)) from None
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def _run(project_dir: Path, args: list[str], timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    """One call, and a non-zero exit is a failure. Every command here works that way except
    `session-close`, whose exit code is an ANSWER — see `close_session`."""
    code, out, err = _spawn(project_dir, args, timeout_s)
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


def set_protective(project_dir: Path, channel: str, legs) -> str:
    """Declare what was in the signal path for one channel of the OPEN capture round.

    `legs` is `"OFF"` -- an ANSWER, meaning this channel was swept with nothing in the chain -- or
    `{"hp": {...}, "lp": {...}}` in the ledger's crossover vocabulary. Leaving a channel out
    entirely is a THIRD thing: nobody said, and it is recorded by not calling this at all. The
    de-embed refuses that case rather than treating it as clean, which is the whole point of the
    feature.

    Nothing is validated here. The skill refuses a leg missing `f`/`type`/`slope` at write time,
    and that refusal comes back verbatim through `ProcessWriterError` for the dialog to show: a UI
    that quietly fixes what a gate would have refused trains people to trust the UI over the gate.
    """
    args = ["capture-protective", str(channel)]
    if legs == "OFF":
        args.append("OFF")
    else:
        for kind in ("hp", "lp"):
            leg = (legs or {}).get(kind)
            if leg in (None, "OFF"):
                continue
            # Only what was actually given. Padding a half-filled leg with empty strings made the
            # CLI's own parser fail on `int("")` -- a ValueError where the gate has a sentence
            # ready ("--hp needs three values: f type slope ... a leg missing any of them cannot
            # be taken back out later"). Sending three values when two were typed hides the
            # refusal that was written for exactly this.
            values = [leg.get("f"), leg.get("type"), leg.get("slope")]
            args.append(f"--{kind}")
            args += [str(value) for value in values if value not in (None, "")]
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
    """
    code, out, err = _spawn(project_dir, ["session-close"])
    _refuse_if_too_old("session-close", "3.0.47", out, err)
    if code not in (0, 1):
        raise ProcessWriterError((err or out).strip() or f"process.py exited {code}")
    return code == 0, out or err


def _refuse_if_too_old(command: str, since: str, out: str, err: str) -> None:
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
    raise ProcessWriterError(
        f"this project's method does not have `{command}` — it landed in the method at v{since}. "
        "Update the method (TCC's own update row offers it), or do this step by hand; nothing "
        "here is broken on TCC's side."
    )


def start_capture(
    project_dir: Path, version: str, expected: list[str], step: str = ""
) -> str:
    """Open a capture round: which ledger version it is taken at, and what was asked for (SCR-034).

    A round, not a version — the version names the config the measurements were taken under and
    cannot tell two passes at the same config apart.

    `step` binds the round to the plan step it satisfies (SCR-040): that is what makes a re-take
    visibly attempt N of the step that asked for it, and what lets the step's own gate read the
    verdict on those captures.
    """
    args = ["capture-start", str(version), *[str(t) for t in expected or []]]
    if step:
        args += ["--step", step]
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
