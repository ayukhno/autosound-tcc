"""The main window's background threads — one per slow question, each off the GUI thread.

They sat in `main_window.py` among the window's helpers and depend on nothing of the window's, so
they are the first cut of that file (hub #102, HUB-051). `main_window` imports them back under the
same names: a test that reaches for `main_window._CliCatalogueWorker` still finds it.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from autosound_tcc.core import (
    app_log,
    availability,
    claude_sdk,
    contract_check,
    critic,
    model_choices,
    process_writer,
)
from autosound_tcc.core.rew_bridge import RewBridge
from autosound_tcc.ui.tcc import qt_shutdown


class _RewPingWorker(QThread):
    """Connectivity probe for the REW-online dot: one synchronous HTTP call, off the GUI thread.

    It used to run exactly once per launch, and that is what made the dot a lie for the rest of
    the session: REW started after TCC stayed red until the app was restarted, and ↻ re-read the
    disk while the diagnostics check probed REW and threw the answer away (user, 2026-09-06 —
    "тільки вихід-вхід"). It is re-run now: on ↻, on every diagnostics result, whenever the
    measurement panel talks to REW, and on a slow timer while the window has focus.
    """

    result = Signal(bool)

    def __init__(self, bridge: RewBridge) -> None:
        super().__init__()
        self._bridge = bridge
        # Say who you were if you are destroyed before you finished (finding 35): Qt's own
        # fatal line names no class, and this app has eight kinds of worker.
        qt_shutdown.watch(self)

    def run(self) -> None:
        self.result.emit(self._bridge.is_reachable())


class _ContractWorker(QThread):
    """Run the skill's whole-project contract check off the GUI thread.

    It spawns a Python subprocess and (unless REW is skipped) probes REW over HTTP, so the GUI
    thread is exactly where it must not run -- same reason `_RewPingWorker` exists just above.
    """

    result = Signal(object)  # ContractReport

    def __init__(self, project_dir) -> None:
        super().__init__()
        self._project_dir = project_dir
        self._child = None
        # Say who you were if you are destroyed before you finished (finding 35): Qt's own
        # fatal line names no class, and this app has eight kinds of worker.
        qt_shutdown.watch(self)

    def run(self) -> None:
        self.result.emit(contract_check.run(self._project_dir, register=self._took_child))

    def _took_child(self, child) -> None:
        self._child = child

    def cancel(self) -> None:
        """End the check now rather than at its 30 s timeout.

        Killing the child is the only lever that works: this thread is blocked reading the child's
        output, so it reads no interrupt flag. Waiting the full timeout instead would freeze a
        window on its way out for half a minute, and NOT waiting means Qt destroys a running
        QThread -- which is not a warning but a `qFatal`, i.e. the whole process aborts. Seen
        exactly that way, as a macOS crash report with `_ContractWorker` still in `poll`.
        """
        child = self._child
        if child is not None and child.poll() is None:
            child.kill()


class _CliCatalogueWorker(QThread):
    """Ask the local CLIs what they can run, off the GUI thread.

    `agy models` fetches over the network. The pickers are built while the window is being
    constructed, so asking there would freeze the launch — and a route that answers slowly must
    not be a route that looks absent.
    """

    done = Signal()

    def __init__(self, force: bool = False, active_omp: list | None = None,
                wait_for=None) -> None:
        super().__init__()
        # `force` reaches `refresh_cli_catalogue`: an ordinary launch leaves agy cached and unrun
        # (its window is the startup flash of TCC-006), while the ↻ button forces a re-ask.
        self._force = force
        #: Which omp models the user marked. Empty means the omp catalogue is needed for NOTHING,
        #: and asking for it is a subprocess spent labelling models nobody chose (probe30).
        self._active_omp = list(active_omp or [])
        #: The start's own reading, if there is one. Waited on instead of asked again.
        self._wait_for = wait_for
        # Say who you were if you are destroyed before you finished (finding 35): Qt's own
        # fatal line names no class, and this app has eight kinds of worker.
        qt_shutdown.watch(self)

    def run(self) -> None:
        if self._wait_for is not None:
            # The start already asked everything, forced. Wait for it, then only what it skips
            # (omp for marked models) — asking agy and claude a second time is a second window.
            # In steps, so a quit during the read is heard: an unbounded wait outlived
            # `stop_workers`, and Qt destroying a running QThread is `qFatal`.
            while not self._wait_for.done.wait(0.2):
                if self.isInterruptionRequested():
                    return
            model_choices.refresh_cli_catalogue(force=False, active_omp=self._active_omp)
            self.done.emit()
            return
        model_choices.refresh_cli_catalogue(force=self._force, active_omp=self._active_omp)
        # A forced read that came back settles what a failed start left "not checked" — without
        # this, a start whose read raised kept those rows red for the whole launch.
        if self._force:
            availability.finish_reading("agy")
        # Same thread, same reason: `claude auth status` is a subprocess, and the pickers are
        # built during construction. Asking there would put a process launch in front of the
        # first paint on every startup.
        # `force` travels here too: without it the answer is asked once per process, which is the
        # point — `claude` puts a console window on screen on Windows and upstream has closed that
        # as not planned. A press means somebody just logged in and wants it re-asked.
        claude_sdk.probe_signed_in(force=self._force)
        if self._force:
            availability.finish_reading("sdk")
        self.done.emit()

    quiet = Signal(list)  # routes that are installed and answered with nothing


#: What the probe asks. Short, so the call costs as little as a real call can.
_REVIEWER_PROBE_QUESTION = "Reply with the single word: ready."
#: How long the probe may take: past the script's own CLI timeout (120 s), so the script gives its
#: answer first, and far short of a real review's ten minutes.
_REVIEWER_PROBE_TIMEOUT_S = 180.0
#: The stub project context the probe hands the method script, so the real project's own
#: `rew_analitic/autosound_context.md` is never read (or overwritten) for a call that has
#: nothing to do with it.
_REVIEWER_PROBE_CONTEXT = "Reviewer probe: there is no project. Answer the question only.\n"


class _ReviewerProbeWorker(QThread):
    """One short `ask` to the chosen reviewer at session start, so a refusal (region, key) is red
    before the first review instead of being found by it (the Arbiter, 2026-09-13)."""

    done = Signal(str)

    def __init__(self, key: str, project_dir: Path) -> None:
        super().__init__()
        self._key = key
        self._project_dir = project_dir
        # Say who you were if you are destroyed before you finished (finding 35): Qt's own
        # fatal line names no class, and this app has eight kinds of worker.
        qt_shutdown.watch(self)

    def run(self) -> None:
        import tempfile

        mode = ""
        try:
            # The reviewer a real call reaches: an alias followed, so the probe asks the same model
            # and files its answer under the key every reader looks up.
            _, reviewer = model_choices.resolve_critic(self._key)
            if reviewer is None:
                return
            # The REAL project as cwd, and a throwaway folder for everything the script writes.
            # The cwd is the one a real review runs in: a CLI that checks folder trust against it
            # answers the probe as it answers a review, where a temp cwd would be refused on every
            # probe for somebody who trusted the project — red while reviews work (final review,
            # 2026-09-13). The writes go elsewhere through the env, applied last so it outranks
            # the mirror `project_dir` implies: the answer is filed under AUTOSOUND_PROJECT_DIR,
            # the clipboard package and the audit trail under PROJECT_MIRROR. The stub context
            # there is found before the project's own, so no project data reaches a probe; the
            # data contract comes from the skill's assets. A project not yet reviewable (no
            # context of its own) comes back not ready, and that records nothing.
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
                scratch = Path(folder)
                mirror = scratch / "rew_analitic"
                mirror.mkdir()
                (mirror / "autosound_context.md").write_text(
                    _REVIEWER_PROBE_CONTEXT, encoding="utf-8")
                package = scratch / "reviewer-probe.md"
                package.write_text(_REVIEWER_PROBE_QUESTION, encoding="utf-8")
                result = critic.run(str(package), project_dir=self._project_dir, role="ask",
                                    model=reviewer.model, harness=reviewer.harness,
                                    timeout_s=_REVIEWER_PROBE_TIMEOUT_S,
                                    extra_env={"AUTOSOUND_PROJECT_DIR": str(scratch),
                                               "PROJECT_MIRROR": str(mirror)})
            if result.mode == critic.MODE_ERROR:
                app_log.logger().warning("reviewer probe could not run: %s", result.detail)
            availability.record_reviewer_outcome(reviewer.key, result)
            mode = result.mode
        except Exception:  # noqa: BLE001 — a probe must never take the window down or go silent
            app_log.logger().exception("reviewer probe failed")
        finally:
            self.done.emit(mode)


class _CaptureCheckWorker(QThread):
    """Run the skill's capture verdict off the GUI thread (SCR-040).

    It pulls every expected measurement out of REW through the skill's own checker, so it is the
    slowest of TCC's background calls and the one that must never run inline: the window would
    freeze for seconds while somebody is sitting in a car waiting to move the mic.
    """

    result = Signal(str)  # the checker's own output, or the refusal verbatim

    def __init__(self, project_dir) -> None:
        super().__init__()
        self._project_dir = project_dir
        # Say who you were if you are destroyed before you finished (finding 35): Qt's own
        # fatal line names no class, and this app has eight kinds of worker.
        qt_shutdown.watch(self)

    def run(self) -> None:
        try:
            self.result.emit(process_writer.check_captures(self._project_dir))
        except process_writer.ProcessWriterError as exc:
            self.result.emit(str(exc))
