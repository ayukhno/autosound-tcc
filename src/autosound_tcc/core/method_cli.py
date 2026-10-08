"""The one place that says which script of the method's `rew_tool/` runs, and in what environment
(#169, #171) — and where all but two of them are started: as a child that comes back, under the
project's lock when the caller asks for it.

`process_writer` drove `process.py` through a path like this one, but not every caller took it:
`title_fixes.supersede` and `handoff.check` started `process.py` with a bare `subprocess.run` of
their own — no lock around a write that rewrites the round, and on Windows no bound on the wait
after a timeout (tcc#132) — and `profile_writer`, `config_writer`, `project_repo`, `contract_check`
and `intake_form` started scripts of TCC's own copy, whatever the project linked. A launcher of its
own is a launcher the next fix forgets, so every one goes through here, and a caller chooses only
what really differs: whether it takes the lock, and how long it may wait for it.

Every launcher but two runs its child through `spawn`. The two cannot be a bounded run:
`contract_check.run` hands its child to a caller that may end it early (`register`), and
`intake_form` is a server that runs until the project closes. They take the script and the
environment from `resolve` — the answer `spawn` itself runs, refused and logged the same way — and
keep a `Popen` of their own. Outside `rew_tool/`, two scripts run TCC's own copy by design and are
started where they are: the reviewer's `scripts/autosound_ai.py` (`critic`, `reviewer_key`), and an
update's `scripts/upkeep.py`, taken from the tag being applied (`updates`).

A write to the process journal takes the lock (`project_lock.hold`) and, past the wait, answers
`Busy` having started nothing. A read takes none (`lock=False`): it has nothing to guard, and a read
on the GUI thread waiting behind a 120 s `capture-check` — or the lock's own `process/`, made in a
project that has none — would be the bug. Nor does a write the lock does not guard: the profile
draft, `slots.json`, a folder being made a repository. `timeout_s` bounds the child alone, under
`child.run_bounded`: the child's whole tree is killed at the timeout, and the wait for its pipes
after that is bounded too.

Which copy of the method runs, and in what environment, is `resolve`'s alone: the copy the
project is bound to (`method_binding`), or `Refused` with the binding's sentence and nothing
started. Nor is that copy's `process.py` started with a flag its text does not hold: its parser
takes one it does not know for data (N19), so that is `UnknownFlag`, a `Refused` too, before the
lock. Qt-free.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import threading
from pathlib import Path
from typing import Optional, Sequence

from autosound_tcc.core import app_log, child, method_binding, project_lock, vendor_loader

#: How long a write waits for the project's lock (`project_lock.hold`) before answering `Busy`
#: (#171), read when the call runs. The main thread is the window, and a window frozen behind a
#: 120 s `capture-check` — or a quit behind a queue of them — is the bug. Any other thread (an MCP
#: call, a QThread worker) freezes nobody's window, so it can afford to queue. `timeout_s` still
#: bounds the child alone.
GUI_LOCK_WAIT_S = 5.0
LOCK_WAIT_S = 60.0

#: The method's journal writer, relative to its `rew_tool/`: the one script whose flags are checked
#: against its text before it starts (#169, N19).
PROCESS_SCRIPT = "state/process.py"

#: A flag: the part of a word before any `=`, when it is `--` and a lowercase name whole. So a
#: reason, a note or a title that happens to start with `--` (`-- not needed`) is a value.
_FLAG = re.compile(r"--[a-z][a-z0-9-]*")

#: path -> (st_mtime_ns, st_size, the flags its text holds): one entry per `process.py`, read again
#: when it changes. Every call that sends a flag asks — a write, or a read such as `handoff --json`
#: — and the file is 240 KB.
_FLAGS_CACHE: dict[str, tuple[int, int, frozenset[str]]] = {}


class ProcessWriterError(RuntimeError):
    """The skill's writer refused or could not run. Carries its own message verbatim.

    A refusal is information, not a crash: `done` rejecting a step with no evidence is the план-факт
    gate doing its job (SCR-004), and the caller has to be told exactly that so it can supply the
    evidence rather than retry the same call.
    """


class Busy(ProcessWriterError):
    """Another write to this project held the lock past the wait, so this one never started.

    The one failure that means "nothing happened, and the same call will work in a moment" — and a
    `ProcessWriterError`, so every caller that already shows a refusal shows this one too.
    """


class Refused(ProcessWriterError):
    """The project's copy of the method is not one TCC will run (`method_binding`), so nothing was
    started: no lock taken, no child. Carries the binding's sentence verbatim — it names the entry
    and what to do about it. `UnknownFlag` is a `Refused` too: a copy TCC does run, which does not
    know a flag of this call.

    Unlike `Busy`, the same call will NOT work in a moment: it is refused alike until the copy is
    approved, updated or re-linked. For a refused binding every call to this project is, so a caller
    that stops after `Busy` stops after this too, rather than ask the rest only to be refused the
    same way. Not so for an `UnknownFlag`: it refuses the calls that send its flag, and the same
    call without the flag may go through — a round opened without `--plan` (`measurement_panel`).
    """


class UnknownFlag(Refused):
    """The project's copy of the method does not know a flag this call sends to its `process.py`
    (#169, N19), so nothing was started. `flag` is that flag, cut at its `=`, and the sentence names
    it. A `Refused`, so a caller that shows a refusal shows this one; a caller that can do without
    the flag catches it by name and asks again without it."""

    def __init__(self, flag: str) -> None:
        super().__init__(f"this project's method does not know {flag}; update it, or re-link the "
                         "project to TCC's copy")
        self.flag = flag


class ScriptMissing(ProcessWriterError):
    """The copy of the method the project runs has no such script, so nothing was started: a
    method older than the command, or a copy with files missing. A class of its own so that a
    launcher whose answer to that is «update the method» (`project_repo`) can tell it from a run
    that failed; every other caller reads it as the `ProcessWriterError` it is."""


def resolve(
    project_dir: Path | str, script_rel: str, args: Sequence[str] = ()
) -> tuple[Path, dict[str, str]]:
    """`rew_tool/<script_rel>` of the copy of the method the project is bound to, and the
    environment to run it in: `vendor_loader.child_env`, with `AUTOSOUND_SKILL_ROOT` naming that
    copy's skill folder to the child. `method_binding.for_project` is asked once per call.

    The one place that says which copy (#169). Every launcher used to run TCC's own copy whatever
    the project linked, so a session could advise from one copy while the writers wrote with
    another. `spawn` asks here, and so do the two launchers that keep a `Popen` of their own
    (`contract_check`, `intake_form`), so no launcher can name another copy than `spawn` would.

    A binding TCC will not run is `Refused`, with its own sentence, before anything is started —
    and said in the log here, once, in the one refused line every launcher leaves (`_say_refused`).
    `args` are what would follow the script, and are read only to name the run in that line.
    Whether the script is there is the caller's to ask. TCC's own copy is resolved on every call,
    so the env override (`AUTOSOUND_SKILL_DIR`) holds here as it does everywhere else.
    """
    project_dir = Path(project_dir)
    binding = method_binding.for_project(project_dir)
    try:
        script = binding.script(script_rel)
    except method_binding.MethodRefused as exc:
        refused = Refused(str(exc))
        _say_refused(script_rel, args, project_dir, refused)
        raise refused from exc
    return script, vendor_loader.child_env(**binding.session_env())


def _say_refused(script_rel: str, args: Sequence[str], project_dir: Path, exc: Refused) -> None:
    """Into the log, as a busy answer goes and for the same reason: the caller may have nobody left
    to tell — `close_session` at quit posts to a closing window, and `mcp_server` drops
    `record_reviewer`'s error on purpose. A refused binding and a flag the copy does not know
    alike, once each."""
    app_log.logger().warning("refused: `%s` on %s was not run: %s",
                             _named(Path(script_rel), [str(arg) for arg in args], project_dir),
                             project_dir, exc)


def _flags_known_to(script: Path) -> frozenset[str]:
    """The flags `script`'s text holds, each as a whole word: `--level-read-as` does not make
    `--level` known. Read once per path, mtime and size (`_FLAGS_CACHE`)."""
    path = str(script)
    info = script.stat()
    key = (info.st_mtime_ns, info.st_size)
    cached = _FLAGS_CACHE.get(path)
    if cached is not None and cached[:2] == key:
        return cached[2]
    known = frozenset(_FLAG.findall(script.read_text(encoding="utf-8", errors="replace")))
    _FLAGS_CACHE[path] = (*key, known)
    return known


def _refuse_a_flag_it_does_not_know(script: Path, args: Sequence[str]) -> None:
    """`UnknownFlag` for the first flag in `args` that `script` — the bound copy's `process.py` —
    does not hold in its text (#169, N19). A flag is cut at its `=`: `--review=<x>` is `--review`.

    `process.py` parses its flags by hand and takes one it does not know for data: an older copy
    reads `capture-start 49 … --origin X` as two more expected titles and `skip 2.3 --superseded-by
    2.4` as a reason, and prints no usage text that `process_writer._refuse_if_too_old` could read.

    A text check, and so a heuristic: a flag the copy names only in a message passes — `--hp` and
    `--lp`, which v3.1.1 parses with `lstrip("-")` and names in its messages."""
    flags = [word for word in (arg.split("=", 1)[0] for arg in args) if _FLAG.fullmatch(word)]
    if not flags:
        return
    try:
        known = _flags_known_to(script)
    except OSError as exc:
        raise ProcessWriterError(str(exc)) from None
    for flag in flags:
        if flag not in known:
            raise UnknownFlag(flag)


def _named(script: Path, args: Sequence[str], project_dir: Path) -> str:
    """What the busy and refused lines call the run: its first argument that is neither a flag nor
    a path in the project — for `process.py`, the command after its `<process-dir>`; for `state.py`,
    the command after `--root <ledger>`. The project is named beside it."""
    words = [arg for arg in args if not _FLAG.fullmatch(arg.split("=", 1)[0])
             and not Path(arg).is_relative_to(project_dir)]
    return words[0] if words else script.name


def spawn(
    project_dir: Path | str,
    script_rel: str,
    args: Sequence[str],
    *,
    timeout_s: float,
    lock: bool = True,
    lock_wait_s: Optional[float] = None,
) -> tuple[int, str, str]:
    """Run `rew_tool/<script_rel> *args` of the project's bound copy and return `(exit code,
    stdout, stderr)`, both stripped.

    The exit code is handed back, not judged: for most commands non-zero is a refusal, for some it
    is the answer (`session-close`, `capture-supersede`, `handoff --json`), and only the caller
    knows which.

    A project whose copy TCC will not run answers `Refused`, with the binding's sentence, before
    the lock and before any child — a read as much as a write — and says so in the log once
    (`resolve`). So does a `process.py` call with a flag that copy's text does not hold:
    `UnknownFlag`, naming the flag (N19). A script that copy does not have is `ScriptMissing`.

    `lock` holds the project's writer lock around the child, and `lock_wait_s` is how long to wait
    for it — by default `GUI_LOCK_WAIT_S` on the main thread and `LOCK_WAIT_S` on any other, read
    now. Past it the answer is `Busy`, with nothing started. Past `timeout_s` the child's tree is
    killed and the answer is a `ProcessWriterError` saying it timed out — never `Busy`, because a
    child cut halfway may have written.
    """
    project_dir = Path(project_dir)
    args = [str(arg) for arg in args]
    script, env = resolve(project_dir, script_rel, args)
    if not script.is_file():
        raise ScriptMissing(
            f"{script.name} not found at {script}. Run: git submodule update --init --recursive"
        )
    # `process.py`'s alone (#169, N19): its parser takes a flag it does not know for data.
    if script_rel == PROCESS_SCRIPT:
        try:
            _refuse_a_flag_it_does_not_know(script, args)
        except Refused as exc:
            _say_refused(script_rel, args, project_dir, exc)
            raise
    # One writer at a time, from this process and from any other (`project_lock`). How long to
    # wait for it is the calling THREAD's question, asked here and not bound at import.
    if lock_wait_s is None:
        on_gui_thread = threading.current_thread() is threading.main_thread()
        lock_wait_s = GUI_LOCK_WAIT_S if on_gui_thread else LOCK_WAIT_S
    held = project_lock.hold(project_dir, lock_wait_s) if lock else contextlib.nullcontext()
    try:
        with held:
            proc = child.run_bounded(
                # The CONSOLE interpreter, not ours. TCC is a GUI app, so `sys.executable` is
                # `pythonw.exe`, which has no console — and the git this script runs then opens
                # its own window. Every flash the user saw while saving was this line (TCC-006).
                [child.script_interpreter(), str(script), *args],
                timeout=timeout_s,
                text=True,
                # NOT the locale's, which is what `text=True` alone means. The skill writes UTF-8
                # to disk on every platform and folds only what a CONSOLE cannot draw, so its
                # bytes are always UTF-8 — and decoding them with a Windows ANSI page turned a
                # listening verdict into mojibake on the way back (first Windows CI run,
                # 2026-09-07). The tuner's own words about what they heard are the one thing here
                # that has to survive the trip verbatim.
                encoding="utf-8",
                errors="replace",
                env=env,
                **child.quiet(),
            )
    except project_lock.LockTimeout as exc:
        # Into the log too: the caller may have nobody left to tell — `close_session` at quit
        # posts its refusal to a window that is closing, and the write would go without a trace.
        app_log.logger().warning(
            "busy: `%s` on %s was not run: %s", _named(script, args, project_dir), project_dir, exc
        )
        raise Busy(
            "busy: another write to this project is still running — nothing was written, try again"
        ) from exc
    except subprocess.TimeoutExpired:
        raise ProcessWriterError(f"{script.name} timed out after {timeout_s:g}s") from None
    except OSError as exc:
        raise ProcessWriterError(str(exc)) from None
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
