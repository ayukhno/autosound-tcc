"""The one place TCC starts a method script (#169, #171): the project's lock, a child that comes
back, and the environment the method runs in.

`process_writer` drove `process.py` through a path like this one, but not every caller took it:
`title_fixes.supersede` and `handoff.check` started `process.py` with a bare `subprocess.run` of
their own — no lock around a write that rewrites the round, and on Windows no bound on the wait
after a timeout (tcc#132). A launcher of its own is a launcher the next fix forgets, so every one
goes through here, and a caller chooses only what really differs: whether it takes the lock, and
how long it may wait for it.

A write takes the lock (`project_lock.hold`) and, past the wait, answers `Busy` having started
nothing. A read takes none (`lock=False`): it has nothing to guard, and a read on the GUI thread
waiting behind a 120 s `capture-check` — or the lock's own `process/`, made in a project that has
none — would be the bug. `timeout_s` bounds the child alone, under `child.run_bounded`: the child's
whole tree is killed at the timeout, and the wait for its pipes after that is bounded too.

Which copy of the method runs, and in what environment, is `_resolve`'s alone: the copy the
project is bound to (`method_binding`), or `Refused` with the binding's sentence and nothing
started. Qt-free.
"""

from __future__ import annotations

import contextlib
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
    and what to do about it.

    Unlike `Busy`, the same call will NOT work in a moment: every call to this project is refused
    alike until the link is approved or re-linked. So a caller that stops after `Busy` stops after
    this too, rather than ask the rest only to be refused the same way.
    """


def _resolve(project_dir: Path, script_rel: str) -> tuple[Path, dict[str, str]]:
    """The script to run and the environment to run it in: the copy of the method the project is
    bound to (`method_binding.for_project`, asked once per spawn), and `AUTOSOUND_SKILL_ROOT` naming
    that copy's skill folder to the child.

    The one place that says which copy (#169). Every write used to run TCC's own copy whatever the
    project linked, so a session could advise from one copy while the writers wrote with another.
    A binding TCC will not run is `Refused`, with its own sentence — asked first in `spawn`, so
    before the lock and before any child. TCC's own copy is resolved on every call, so the env
    override (`AUTOSOUND_SKILL_DIR`) holds here as it does everywhere else.
    """
    binding = method_binding.for_project(project_dir)
    try:
        script = binding.script(script_rel)
    except method_binding.MethodRefused as exc:
        raise Refused(str(exc)) from exc
    return script, vendor_loader.child_env(**binding.session_env())


def _named(script: Path, args: Sequence[str], project_dir: Path) -> str:
    """What the busy line calls the run: its first argument that is not a path in the project —
    for `process.py`, the command after its `<process-dir>`. The project is named beside it."""
    words = [arg for arg in args if not Path(arg).is_relative_to(project_dir)]
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
    the lock and before any child — a read as much as a write.

    `lock` holds the project's writer lock around the child, and `lock_wait_s` is how long to wait
    for it — by default `GUI_LOCK_WAIT_S` on the main thread and `LOCK_WAIT_S` on any other, read
    now. Past it the answer is `Busy`, with nothing started. Past `timeout_s` the child's tree is
    killed and the answer is a `ProcessWriterError` saying it timed out — never `Busy`, because a
    child cut halfway may have written.
    """
    project_dir = Path(project_dir)
    args = [str(arg) for arg in args]
    script, env = _resolve(project_dir, script_rel)
    if not script.is_file():
        raise ProcessWriterError(
            f"{script.name} not found at {script}. Run: git submodule update --init --recursive"
        )
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
