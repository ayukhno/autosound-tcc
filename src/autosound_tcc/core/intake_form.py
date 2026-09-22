"""The skill's intake form, run as a child process and opened in the system browser (hub #194).

The form is the skill's own page (`rew_tool/intake_form.py serve`): ONE form for every front end,
the Arbiter's decision 2026-09-22. TCC's part is only the process around it -- start it in the
interface language, learn the port the OS picked from the one machine line the form prints,
reopen the same URL on a second click, and stop it when the project closes. The page writes
`project.json` / `dsp_profile.json` through the method's own writers; TCC reads them back through
the file watcher it already has.

A child process rather than an import: `intake_form` rewrites `sys.path` to reach its siblings,
which is the same reason `contract.py` runs out of process (`core/contract_check.py`).
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from autosound_tcc.core import child as child_process
from autosound_tcc.core import vendor_loader

#: The machine twin of the form's translated start-up lines (skill `intake_form.serve`).
URL_PREFIX = "INTAKE_URL: "
DEFAULT_TIMEOUT_S = 10.0


class IntakeFormError(Exception):
    """Why the form is not on screen. `kind` picks the translated sentence, `detail` is the fact."""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(detail or kind)
        self.kind = kind
        self.detail = detail


def script_path() -> Path:
    return vendor_loader.rew_tool_dir() / "intake_form.py"


class IntakeForm:
    """One form process for one project; `open_url()` starts it or hands back the running one."""

    def __init__(self, project_dir, lang: str, *, popen: Callable = subprocess.Popen,
                 script: Optional[Path] = None, timeout_s: float = DEFAULT_TIMEOUT_S,
                 interpreter: Optional[str] = None) -> None:
        self._project_dir = Path(project_dir)
        self._lang = lang
        self._popen = popen
        self._script = Path(script) if script is not None else None
        self._timeout_s = timeout_s
        self._interpreter = interpreter
        self._proc = None
        self._url: Optional[str] = None
        #: True once the form has been on screen in this window: the gate offer only follows a
        #: form the Arbiter actually opened.
        self.was_opened = False

    def _script_file(self) -> Path:
        return self._script or script_path()

    def command(self) -> list[str]:
        return [self._interpreter or child_process.script_interpreter(), str(self._script_file()),
                "serve", str(self._project_dir), "--lang", self._lang, "--port", "0"]

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def open_url(self) -> str:
        if self.running() and self._url:
            return self._url
        self.stop()
        script = self._script_file()
        if not script.is_file():
            raise IntakeFormError("no_form", str(script))
        proc = self._popen(self.command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, encoding="utf-8", errors="replace",
                           env=vendor_loader.child_env(), **child_process.quiet())
        found: list[str] = []
        answered = threading.Event()
        tail: list[str] = []

        def read_out() -> None:
            # Keeps reading after the URL, so a chatty form never blocks on a full pipe.
            for line in proc.stdout:
                if not found and line.startswith(URL_PREFIX):
                    found.append(line[len(URL_PREFIX):].strip())
                    answered.set()
            answered.set()  # end of stream: the form exited

        def read_err() -> None:
            for line in proc.stderr:
                tail.append(line.rstrip())
                del tail[:-5]

        err_reader = threading.Thread(target=read_err, daemon=True)
        threading.Thread(target=read_out, daemon=True).start()
        err_reader.start()
        answered.wait(self._timeout_s)
        if not found:
            self._proc = proc
            self.stop()
            err_reader.join(timeout=1.0)
            raise IntakeFormError("failed", tail[-1] if tail else "")
        self._proc, self._url = proc, found[0]
        self.was_opened = True
        return self._url

    def stop(self) -> None:
        proc, self._proc, self._url = self._proc, None, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
