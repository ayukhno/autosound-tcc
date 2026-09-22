# The intake form in TCC — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TCC starts the skill's served intake form, opens it in the system browser, offers the tuning session once the Phase-0 gate is green, and chooses the seat when a project is copied (hub `#194` SKL-049, `#193` SKL-048).

**Architecture:** A small `core/intake_form.py` owns the child process (`intake_form.py serve … --port 0`) and the URL it prints. `MainWindow` owns one instance, opens the URL with `QDesktopServices`, and after each reload of the project files asks `contract.py` (already run by `core/contract_check.py`) whether the gate is `complete`; green shows a one-click offer in the status strip. The new-project flow drops the conversational DSP-profile interview and opens the form instead; the copy mode gains a seat picker.

**Tech Stack:** Python 3.12, PySide6-Essentials (no WebEngine), pytest; the skill vendored at `vendor/autosound-tuning-skill`.

**Spec:** `docs/superpowers/specs/2026-09-22-intake-form-design.md`

## Global Constraints

- Work on branch `wave-0.1.43` in the main tree `~/dev/autosound/tcc` — no worktree (hub `hub:seam` line 6).
- Targeted tests only while building: `uv run --extra dev --python 3.12 python -m pytest <files> -q -p no:randomly`. The full suite runs once, in Task 9, with the VM suspended and `-n 4`.
- Every string the Arbiter reads exists in all four languages `en`, `uk`, `pl`, `de` in `src/autosound_tcc/ui/tcc/i18n.py`; `tests/test_i18n_languages.py` enforces parity — run it in every task that adds a key.
- Commit messages, code comments and docs in English; each commit ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- The form's process binds 127.0.0.1 and holds no state; TCC never parses the page, only the `INTAKE_URL: ` line.
- The start of a session is always the Arbiter's click; nothing starts it automatically.

---

### Task 1: Pin the method at the skill's wave branch

**Files:**
- Modify: `vendor/autosound-tuning-skill` (submodule pointer)

**Interfaces:**
- Produces: `vendor/autosound-tuning-skill/skills/autosound-tuning/rew_tool/intake_form.py` and `project_seed.seed(..., seat=)`, which Tasks 2 and 8 use.

- [ ] **Step 1: Move the submodule to the branch's sha**

```bash
cd ~/dev/autosound/tcc
git -C vendor/autosound-tuning-skill fetch origin wave-2026-09-20
git -C vendor/autosound-tuning-skill checkout c27cd7a3a52ed7dd0bc081861e5a984a13938af1
test -f vendor/autosound-tuning-skill/skills/autosound-tuning/rew_tool/intake_form.py && echo form-present
```
Expected: `form-present`.

- [ ] **Step 2: Run the tests that touch the method's seed and contract**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_project_seed.py tests/test_contract_check.py tests/test_new_project_dialog.py -q -p no:randomly`
Expected: PASS. A failure here is the method's newer gate refusing a fixture — read the refusal, fix the FIXTURE (as `f6297fc` did for v3.0.59), never the gate.

- [ ] **Step 3: Commit**

```bash
git add vendor/autosound-tuning-skill
git commit -m "Pin the method at skill wave-2026-09-20 (c27cd7a) while the intake form is built

The form and seed(seat=) exist only on that branch. The release pins the skill's published tag
instead (WAVES.md §1 step 4); make ship refuses an untagged pin.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `core/intake_form.py` — the form's process

**Files:**
- Create: `src/autosound_tcc/core/intake_form.py`
- Test: `tests/test_intake_form.py`

**Interfaces:**
- Consumes: `child.script_interpreter()`, `child.quiet()`, `vendor_loader.child_env()`, `vendor_loader.rew_tool_dir()`.
- Produces:
  - `class IntakeFormError(Exception)` with `.kind: str` (`"no_form"` | `"failed"`) and `.detail: str`
  - `def script_path() -> Path`
  - `class IntakeForm(project_dir, lang, *, popen=subprocess.Popen, script=None, timeout_s=10.0, interpreter=None)` with `open_url() -> str`, `running() -> bool`, `stop() -> None`, `command() -> list[str]`, attribute `was_opened: bool`

- [ ] **Step 1: Write the failing tests**

```python
"""The intake form's child process: started once, its URL read from one line, stopped on demand."""

from __future__ import annotations

import sys
import time

import pytest

from autosound_tcc.core import intake_form

_SERVES = """\
import sys, time
print("  intake form: http://127.0.0.1:45678/ (human line, translated)", flush=True)
print("INTAKE_URL: http://127.0.0.1:45678/", flush=True)
time.sleep(60)
"""

_SILENT = """\
import sys, time
print("boom: no url today", file=sys.stderr, flush=True)
time.sleep(60)
"""

_EXITS = """\
import sys
print("intake: no such project directory", file=sys.stderr, flush=True)
sys.exit(1)
"""


def _script(tmp_path, body):
    path = tmp_path / "intake_form.py"
    path.write_text(body, encoding="utf-8")
    return path


def _form(tmp_path, body, **kw):
    spawned = []

    def popen(*args, **kwargs):
        import subprocess
        proc = subprocess.Popen(*args, **kwargs)
        spawned.append(proc)
        return proc

    form = intake_form.IntakeForm(tmp_path, "uk", popen=popen, script=_script(tmp_path, body),
                                  interpreter=sys.executable, **kw)
    return form, spawned


def test_open_url_returns_the_url_the_form_printed(tmp_path):
    form, spawned = _form(tmp_path, _SERVES)
    try:
        assert form.open_url() == "http://127.0.0.1:45678/"
        assert form.running() and form.was_opened
    finally:
        form.stop()


def test_a_second_open_reuses_the_running_form(tmp_path):
    form, spawned = _form(tmp_path, _SERVES)
    try:
        first = form.open_url()
        assert form.open_url() == first
        assert len(spawned) == 1, "one form process per project"
    finally:
        form.stop()


def test_stop_ends_the_process_and_is_idempotent(tmp_path):
    form, spawned = _form(tmp_path, _SERVES)
    form.open_url()
    form.stop()
    assert spawned[0].poll() is not None
    assert not form.running()
    form.stop()  # a second stop is a no-op, not an error


def test_a_form_that_prints_no_url_is_stopped_and_named(tmp_path):
    form, spawned = _form(tmp_path, _SILENT, timeout_s=1.0)
    with pytest.raises(intake_form.IntakeFormError) as caught:
        form.open_url()
    assert caught.value.kind == "failed"
    assert "boom" in caught.value.detail
    assert spawned[0].poll() is not None, "a form that never answered is not left running"
    assert not form.was_opened


def test_a_form_that_exits_says_why_without_waiting_out_the_timeout(tmp_path):
    form, _ = _form(tmp_path, _EXITS, timeout_s=8.0)
    started = time.monotonic()
    with pytest.raises(intake_form.IntakeFormError) as caught:
        form.open_url()
    assert time.monotonic() - started < 5.0
    assert "no such project directory" in caught.value.detail


def test_a_method_without_the_form_is_no_form_and_starts_nothing(tmp_path):
    spawned = []
    form = intake_form.IntakeForm(tmp_path, "uk", popen=lambda *a, **k: spawned.append(a),
                                  script=tmp_path / "absent.py", interpreter=sys.executable)
    with pytest.raises(intake_form.IntakeFormError) as caught:
        form.open_url()
    assert caught.value.kind == "no_form"
    assert spawned == []


def test_the_command_carries_the_interface_language_and_port_zero(tmp_path):
    form = intake_form.IntakeForm(tmp_path, "de", script=tmp_path / "intake_form.py",
                                  interpreter="py")
    assert form.command() == ["py", str(tmp_path / "intake_form.py"), "serve", str(tmp_path),
                              "--lang", "de", "--port", "0"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_intake_form.py -q -p no:randomly`
Expected: FAIL — `ModuleNotFoundError: No module named 'autosound_tcc.core.intake_form'`.

- [ ] **Step 3: Write the module**

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_intake_form.py -q -p no:randomly`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/core/intake_form.py tests/test_intake_form.py
git commit -m "The intake form's process: started once, its URL read from one line, stopped on demand (hub #194)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `ContractReport.complete` — the gate's verdict from the report TCC already reads

**Files:**
- Modify: `src/autosound_tcc/core/contract_check.py` (the `ContractReport` fields; `report_from_json`)
- Modify: `src/autosound_tcc/ui/tcc/workers.py` (`_ContractWorker.__init__`, `run`)
- Test: `tests/test_contract_check.py`

**Interfaces:**
- Produces: `ContractReport.complete: bool` (default `False`); `_ContractWorker(project_dir, skip_rew: bool = False)`.

`contract.py check --json` already carries top-level `complete` — the same verdict `--gate` exits on — so no new flag is passed.

- [ ] **Step 1: Write the failing test** (append to `tests/test_contract_check.py`)

```python
def test_complete_is_the_gate_verdict_the_report_already_carries():
    from autosound_tcc.core.contract_check import report_from_json

    done = report_from_json({"ok": True, "complete": True, "files": []}, "/p", "t", 0.1)
    open_ = report_from_json({"ok": True, "complete": False, "files": []}, "/p", "t", 0.1)
    older = report_from_json({"ok": True, "files": []}, "/p", "t", 0.1)
    assert done.complete is True
    assert open_.complete is False
    assert older.complete is False, "a method that does not say is not a green gate"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_contract_check.py -q -p no:randomly -k complete`
Expected: FAIL — `AttributeError: 'ContractReport' object has no attribute 'complete'`.

- [ ] **Step 3: Implement**

In `ContractReport`, after `sources_gone`:

```python
    #: The phase −1 gate: intake left everything phase 0 needs (`contract.py`'s own `complete`,
    #: what `--gate` exits on). False when the method does not say -- not a green gate.
    complete: bool = False
```

In `report_from_json`, inside the `ContractReport(...)` call:

```python
        complete=bool(report.get("complete")),
```

In `workers.py`, `_ContractWorker`:

```python
    def __init__(self, project_dir, skip_rew: bool = False) -> None:
        super().__init__()
        self._project_dir = project_dir
        self._skip_rew = skip_rew
        self._child = None
        # Say who you were if you are destroyed before you finished (finding 35): Qt's own
        # fatal line names no class, and this app has eight kinds of worker.
        qt_shutdown.watch(self)

    def run(self) -> None:
        self.result.emit(contract_check.run(self._project_dir, skip_rew=self._skip_rew,
                                            register=self._took_child))
```

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_contract_check.py -q -p no:randomly`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/core/contract_check.py src/autosound_tcc/ui/tcc/workers.py tests/test_contract_check.py
git commit -m "The contract report carries the gate's own verdict, and the worker can skip REW

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The status strip can carry one action

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/status_strip.py`
- Test: `tests/test_status_strip.py`

**Interfaces:**
- Produces: `StatusStrip.notify(text, level="info", action: tuple[str, Callable[[], None]] | None = None)`.

The strip is a `QLabel`, so the action is a link at the end of the line (`linkActivated`), not a separate button. A message with an action is not on the 30-second clock.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_status_strip.py`)

```python
def test_an_action_is_a_link_that_runs_once_and_clears_the_line():
    _app()
    strip = StatusStrip()
    calls = []
    strip.notify("Intake ready", action=("Start the session", lambda: calls.append(1)))
    assert "Start the session" in strip.text() and "<a " in strip.text()
    assert not strip.timer_is_running(), "an offer waits for the click, it does not expire"
    strip.linkActivated.emit("action")
    assert calls == [1]
    assert not strip.isVisible()
    strip.linkActivated.emit("action")
    assert calls == [1], "a cleared offer cannot be taken twice"


def test_a_plain_message_after_an_offer_has_no_link():
    _app()
    strip = StatusStrip()
    strip.notify("Intake ready", action=("Start", lambda: None))
    strip.notify("a <b>fact</b> & nothing else")
    assert "<a " not in strip.text()
    assert strip.timer_is_running()
```

(`_app` and `StatusStrip` are already imported at the top of that file; if `_app` is not, add
`from PySide6.QtWidgets import QApplication` and `def _app(): return QApplication.instance() or QApplication([])`.)

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_status_strip.py -q -p no:randomly`
Expected: FAIL — `TypeError: notify() got an unexpected keyword argument 'action'`.

- [ ] **Step 3: Implement**

Imports: `import html`, `from typing import Callable, Literal, Optional`, `from PySide6.QtCore import Qt, QTimer`.

In `__init__`, after the timer:

```python
        self._action: Optional[Callable[[], None]] = None
        self.setOpenExternalLinks(False)
        self.linkActivated.connect(self._on_link)
```

Replace `notify`'s signature and body (keep its docstring, add one paragraph about the action):

```python
    def notify(self, text: str, level: Level = "info",
               action: Optional[tuple[str, Callable[[], None]]] = None) -> None:
        """...existing docstring...

        An `action` is an OFFER -- one link at the end of the line, taken with one click. It is
        not on the clock either: an offer that expires while the Arbiter reads the form it
        follows was never made.
        """
        self._timer.stop()
        self._action = action[1] if action else None
        if level != "warn" and action is None:
            self._timer.start(_INFO_SECONDS * 1000)
        if action is None:
            self.setTextFormat(Qt.TextFormat.AutoText)
            self.setText(text)
        else:
            self.setTextFormat(Qt.TextFormat.RichText)
            self.setText(f'{html.escape(text)} &nbsp;<a href="action">{html.escape(action[0])}</a>')
        self.setProperty("class", f"status-strip status-{level}" if level == "warn" else "status-strip")
        self.style().unpolish(self)
        self.style().polish(self)
        self.setVisible(True)
```

In `clear`, add `self._action = None` before `self.setText("")`, and add:

```python
    def _on_link(self, _href: str) -> None:
        callback = self._action
        self.clear()
        if callback is not None:
            callback()
```

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_status_strip.py -q -p no:randomly`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/ui/tcc/status_strip.py tests/test_status_strip.py
git commit -m "The status strip can carry one offer: a link, taken once, not on the clock

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: «Інтейк» in the project menu, and the form's lifetime follows the window

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/main_window.py` (menu near `menuCopyCar`, ~line 999; new `_open_intake_form`; `closeEvent`, after `self.stop_workers()`)
- Modify: `src/autosound_tcc/ui/tcc/i18n.py` (four languages)
- Test: `tests/test_intake_window.py` (new)

**Interfaces:**
- Consumes: `intake_form.IntakeForm`, `intake_form.IntakeFormError` (Task 2).
- Produces: `MainWindow._open_intake_form() -> None`; attribute `MainWindow._intake_form: IntakeForm | None`.

- [ ] **Step 1: Write the failing tests**

```python
"""The window's side of the intake form: the menu line, one form per window, stopped on close."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import config, intake_form  # noqa: E402
from autosound_tcc.ui.tcc import i18n, main_window  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


class _FakeForm:
    made = []

    def __init__(self, project_dir, lang, **_kw):
        self.project_dir, self.lang = project_dir, lang
        self.opens, self.stopped, self.was_opened = 0, 0, False
        self.error = None
        _FakeForm.made.append(self)

    def open_url(self):
        if self.error:
            raise self.error
        self.opens += 1
        self.was_opened = True
        return "http://127.0.0.1:45678/"

    def stop(self):
        self.stopped += 1


def _window(tmp_path, monkeypatch):
    _app()
    _FakeForm.made = []
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    monkeypatch.setattr(intake_form, "IntakeForm", _FakeForm)
    opened = []
    monkeypatch.setattr(main_window.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toString()) or True))
    return main_window.MainWindow(), opened


def test_the_menu_line_opens_the_form_in_the_interface_language(tmp_path, monkeypatch):
    window, opened = _window(tmp_path, monkeypatch)
    window._intake_action.trigger()
    assert opened == ["http://127.0.0.1:45678/"]
    form = _FakeForm.made[0]
    assert form.project_dir == tmp_path and form.lang == i18n.current_language()


def test_a_second_click_reuses_the_same_form(tmp_path, monkeypatch):
    window, opened = _window(tmp_path, monkeypatch)
    window._intake_action.trigger()
    window._intake_action.trigger()
    assert len(_FakeForm.made) == 1 and _FakeForm.made[0].opens == 2


def test_a_method_without_the_form_says_so_in_the_strip(tmp_path, monkeypatch):
    window, opened = _window(tmp_path, monkeypatch)
    said = []
    monkeypatch.setattr(window._status_strip, "notify",
                        lambda text, level="info", action=None: said.append((text, level)))
    window._open_intake_form()
    _FakeForm.made[0].error = intake_form.IntakeFormError("no_form", "/x/intake_form.py")
    window._open_intake_form()
    assert said[-1] == (i18n.t("intakeNoForm"), "warn")


def test_closing_the_window_stops_the_form(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    window._open_intake_form()
    window.close()
    assert _FakeForm.made[0].stopped >= 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_intake_window.py -q -p no:randomly`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_intake_action'`.

- [ ] **Step 3: Add the strings** — in `i18n.py`, beside `menuCopyCar` in each language block:

```python
# en
        "menuIntake": "Intake…",
        "menuIntakeTip": "The project's intake as a form in your browser: the car, the equipment, the DSP and its channel map, the goal. The skill serves the page; Save writes the project files, and TCC reads them back.",
        "intakeNoForm": "This version of the method has no intake form yet — it arrives with the skill's next release.",
        "intakeFailed": "The intake form did not start: {detail}",
        "intakeOpenByHand": "Could not open the browser — open this address yourself: {url}",
        "intakeNoProject": "Open or create a project first — the form fills a project folder.",
# uk
        "menuIntake": "Інтейк…",
        "menuIntakeTip": "Інтейк проєкту формою в браузері: авто, обладнання, DSP і його карта каналів, мета. Сторінку віддає скіл; «Зберегти» пише файли проєкту, а TCC їх перечитує.",
        "intakeNoForm": "У цій версії методу ще немає форми інтейку — вона прийде з наступним релізом скіла.",
        "intakeFailed": "Форма інтейку не запустилась: {detail}",
        "intakeOpenByHand": "Не вдалося відкрити браузер — відкрийте цю адресу самі: {url}",
        "intakeNoProject": "Спершу відкрийте або створіть проєкт — форма заповнює теку проєкту.",
# pl
        "menuIntake": "Intake…",
        "menuIntakeTip": "Intake projektu jako formularz w przeglądarce: auto, sprzęt, DSP i jego mapa kanałów, cel. Stronę udostępnia skill; „Zapisz” zapisuje pliki projektu, a TCC je odczytuje.",
        "intakeNoForm": "Ta wersja metody nie ma jeszcze formularza intake — pojawi się w następnym wydaniu skilla.",
        "intakeFailed": "Formularz intake się nie uruchomił: {detail}",
        "intakeOpenByHand": "Nie udało się otworzyć przeglądarki — otwórz ten adres samodzielnie: {url}",
        "intakeNoProject": "Najpierw otwórz lub utwórz projekt — formularz wypełnia folder projektu.",
# de
        "menuIntake": "Intake…",
        "menuIntakeTip": "Das Intake des Projekts als Formular im Browser: Fahrzeug, Ausstattung, DSP mit Kanalbelegung, Ziel. Die Seite liefert der Skill; „Speichern“ schreibt die Projektdateien, TCC liest sie neu ein.",
        "intakeNoForm": "Diese Version der Methode hat noch kein Intake-Formular — es kommt mit dem nächsten Release des Skills.",
        "intakeFailed": "Das Intake-Formular ist nicht gestartet: {detail}",
        "intakeOpenByHand": "Der Browser ließ sich nicht öffnen — öffne diese Adresse selbst: {url}",
        "intakeNoProject": "Öffne oder erstelle zuerst ein Projekt — das Formular füllt einen Projektordner.",
```

- [ ] **Step 4: Implement in `main_window.py`**

Import beside the other core imports: `from autosound_tcc.core import intake_form`.

In the project menu, directly after the `self._copy_car_action` block:

```python
        # The intake is the skill's own form, served and opened in the browser (hub #194): one
        # form for every front end, so TCC starts it and never draws its own copy of it.
        self._intake_action = menu.addAction(i18n.t("menuIntake"))
        self._intake_action.setToolTip(i18n.t("menuIntakeTip"))
        self._intake_action.triggered.connect(lambda _checked=False: self._open_intake_form())
```

New method (next to `_open_new_project_dialog`):

```python
    def _open_intake_form(self) -> None:
        """Start the skill's intake form for this project, or reopen the one already running.

        Blocks for as long as the form takes to print its address -- well under a second when it
        starts, at most `intake_form.DEFAULT_TIMEOUT_S` when it does not, and then it says so.
        """
        project_dir = config.chosen_project_dir()
        if project_dir is None:
            self._status_strip.notify(i18n.t("intakeNoProject"), level="warn")
            return
        form = getattr(self, "_intake_form", None)
        if form is None:
            form = self._intake_form = intake_form.IntakeForm(project_dir,
                                                              i18n.current_language())
        try:
            url = form.open_url()
        except intake_form.IntakeFormError as exc:
            key = "intakeNoForm" if exc.kind == "no_form" else "intakeFailed"
            self._status_strip.notify(i18n.t(key).format(detail=exc.detail), level="warn")
            return
        if not QDesktopServices.openUrl(QUrl(url)):
            self._status_strip.notify(i18n.t("intakeOpenByHand").format(url=url), level="warn")
```

In `closeEvent`, directly after `self.stop_workers()`:

```python
        # The form serves THIS project; a process left behind holds a port for nobody.
        form = getattr(self, "_intake_form", None)
        if form is not None:
            form.stop()
```

- [ ] **Step 5: Run the tests**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_intake_window.py tests/test_i18n_languages.py -q -p no:randomly`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/autosound_tcc/ui/tcc/main_window.py src/autosound_tcc/ui/tcc/i18n.py tests/test_intake_window.py
git commit -m "Intake… in the project menu: the skill's form, one per window, stopped on close (hub #194)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: After the form, the gate — and one offer to start the session

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/main_window.py` (`_reload_project_files`; new `_check_intake_gate`, `_on_gate_result`, `_start_after_intake`; `stop_workers`)
- Modify: `src/autosound_tcc/ui/tcc/i18n.py`
- Test: `tests/test_intake_window.py`

**Interfaces:**
- Consumes: `ContractReport.complete`, `_ContractWorker(project_dir, skip_rew=True)` (Task 3); `StatusStrip.notify(..., action=)` (Task 4); `MainWindow._intake_form` (Task 5).
- Produces: `MainWindow._on_gate_result(report) -> None`, `MainWindow._start_after_intake() -> None`; attributes `_intake_terminal_cli: str | None`, `_intake_terminal_model: str | None` (set by Task 7).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_intake_window.py`)

```python
from autosound_tcc.core.contract_check import ContractReport  # noqa: E402


def _report(complete=True):
    return ContractReport(ok=True, project_dir="/p", complete=complete)


def _offers(window, monkeypatch):
    said = []
    monkeypatch.setattr(window._status_strip, "notify",
                        lambda text, level="info", action=None: said.append((text, action)))
    return said


def test_a_green_gate_offers_the_session_once(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    said = _offers(window, monkeypatch)
    window._on_gate_result(_report())
    window._on_gate_result(_report())
    offers = [s for s in said if s[1] is not None]
    assert len(offers) == 1 and offers[0][0] == i18n.t("intakeReady")


def test_the_offer_returns_after_the_gate_went_red_and_green_again(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    said = _offers(window, monkeypatch)
    window._on_gate_result(_report())
    window._on_gate_result(_report(complete=False))
    window._on_gate_result(_report())
    assert len([s for s in said if s[1] is not None]) == 2


def test_no_offer_while_a_session_runs(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    said = _offers(window, monkeypatch)
    window._agent_worker = object()
    try:
        window._on_gate_result(_report())
    finally:
        window._agent_worker = None
    assert said == []


def test_no_gate_check_for_a_form_never_opened(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    built = []
    monkeypatch.setattr(main_window, "_ContractWorker", lambda *a, **k: built.append(a))
    window._check_intake_gate()
    assert built == []


def test_the_offer_starts_the_in_app_session(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    started = []
    monkeypatch.setattr(window, "_start_tuning_session", lambda *a, **k: started.append(1))
    window._intake_terminal_cli = None
    window._start_after_intake()
    assert started == [1]


def test_the_offer_starts_the_terminal_the_project_was_created_with(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    launched = []
    monkeypatch.setattr(main_window.terminal_launcher, "launch",
                        lambda project_dir, cli, hint, model=None: launched.append((cli, hint, model)))
    window._intake_terminal_cli, window._intake_terminal_model = "claude", "opus"
    window._start_after_intake()
    cli, hint, model = launched[0]
    assert (cli, model) == ("claude", "opus")
    assert i18n.language_name() in hint
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_intake_window.py -q -p no:randomly`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_on_gate_result'`.

- [ ] **Step 3: Add the strings** (four languages, beside the Task 5 keys)

```python
# en
        "intakeReady": "The intake is complete — phase 0 has everything it needs.",
        "intakeStartSession": "Start the session",
# uk
        "intakeReady": "Інтейк заповнено — для фази 0 є все потрібне.",
        "intakeStartSession": "Стартувати сесію",
# pl
        "intakeReady": "Intake jest kompletny — faza 0 ma wszystko, czego potrzebuje.",
        "intakeStartSession": "Rozpocznij sesję",
# de
        "intakeReady": "Das Intake ist vollständig — Phase 0 hat alles, was sie braucht.",
        "intakeStartSession": "Sitzung starten",
```

- [ ] **Step 4: Implement in `main_window.py`**

At the end of `_reload_project_files`, after `self._safe_load_project()`:

```python
        self._check_intake_gate()
```

New methods (next to `_open_intake_form`):

```python
    def _check_intake_gate(self) -> None:
        """After the form wrote the project files: is phase 0's gate green now?

        Only for a form opened in this window and with no session running -- the offer is the
        hand-off from the form to the AI, and neither a session already talking nor a project
        nobody opened the form on needs it. REW is skipped: the gate is about the files.
        """
        form = getattr(self, "_intake_form", None)
        if form is None or not form.was_opened or getattr(self, "_agent_worker", None) is not None:
            return
        worker = getattr(self, "_gate_worker", None)
        if worker is not None and worker.isRunning():
            return
        self._gate_worker = _ContractWorker(config.project_dir(), skip_rew=True)
        self._gate_worker.result.connect(self._on_gate_result)
        self._gate_worker.start()

    def _on_gate_result(self, report) -> None:
        """Offer the session once per green; a red gate re-arms the offer. Red says nothing here:
        the page itself shows what is missing."""
        if not report.available or not report.complete:
            self._gate_offered = False
            return
        if getattr(self, "_gate_offered", False) or getattr(self, "_agent_worker", None) is not None:
            return
        self._gate_offered = True
        self._status_strip.notify(i18n.t("intakeReady"),
                                  action=(i18n.t("intakeStartSession"), self._start_after_intake))

    def _start_after_intake(self) -> None:
        """The route the project was created with: a terminal CLI when the new-project dialog chose
        one in this window, the in-app session otherwise."""
        cli = getattr(self, "_intake_terminal_cli", None)
        if cli is None:
            self._start_tuning_session()
            return
        hint = i18n.t("npOnboardingHint").format(language=i18n.language_name())
        try:
            terminal_launcher.launch(config.project_dir(), cli=cli, hint=hint,
                                     model=getattr(self, "_intake_terminal_model", None))
        except terminal_launcher.TerminalLaunchError as exc:
            self._status_strip.notify(str(exc), level="warn")
```

`npOnboardingHint` takes only `{language}` from Task 7 on; Task 7 rewrites it in all four languages. Until Task 7 lands, `.format(language=...)` on the old text raises `KeyError` for `vendor` — so run Task 7 before relying on the terminal path by hand; the test above uses the Task 7 text.

In `stop_workers`, directly after the contract worker's three lines:

```python
        gate = getattr(self, "_gate_worker", None)
        if gate is not None and gate.isRunning():
            gate.cancel()
        qt_shutdown.stop_or_detach(gate, 3000)
```

- [ ] **Step 5: Run the tests** — the terminal test passes only after Task 7's hint; run everything except it now:

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_intake_window.py tests/test_i18n_languages.py -q -p no:randomly -k "not terminal_the_project"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/autosound_tcc/ui/tcc/main_window.py src/autosound_tcc/ui/tcc/i18n.py tests/test_intake_window.py
git commit -m "After the form, the gate: a green phase-0 gate offers the session once (hub #194)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The new-project flow opens the form instead of the interview

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/new_project_dialog.py` (module docstring; drop `ProfileInterviewDialog`, `interview_dialog`, `interview_needed`, `_seed_no_interview`)
- Modify: `src/autosound_tcc/ui/tcc/main_window.py` (`_open_new_project_dialog`)
- Modify: `src/autosound_tcc/ui/tcc/i18n.py` (`npOnboardingHint` rewritten; `npSeedNoInterview` removed; `npSeedHint` removed if unused)
- Delete: `src/autosound_tcc/ui/tcc/profile_interview_dialog.py`, `tests/test_profile_interview_dialog.py`
- Modify: `tests/shard-weights.json` (drop the deleted test file's entry)
- Test: `tests/test_new_project_dialog.py`, `tests/test_intake_window.py`

**Interfaces:**
- Consumes: `MainWindow._open_intake_form()` (Task 5), `_start_after_intake` (Task 6).
- Produces: after «Створити» the new window has `_intake_terminal_cli`, `_intake_terminal_model` set and the form open.

- [ ] **Step 1: Write the failing tests**

In `tests/test_new_project_dialog.py`: delete `_FakeInterviewDialog` and every `monkeypatch.setattr(npd, "ProfileInterviewDialog", …)` line; rename `test_create_mkdirs_persists_project_dir_and_builds_the_interview` to `test_create_mkdirs_and_persists_project_dir_with_no_interview` and replace its interview assertions with:

```python
    assert not hasattr(npd, "ProfileInterviewDialog"), "the form replaced the interview"
    assert dlg.project_dir == tmp_path / "new-project"   # keep the test's own folder name
    assert dlg.in_app_model == npd.AI_MODEL_IDS.get(dlg._ai_combo.currentText())
```

In `test_the_in_app_model_survives_a_copy_that_skips_the_interview`, delete the line
`assert dlg.interview_dialog is None, …`.

Append to `tests/test_intake_window.py`:

```python
class _Dialog:
    def __init__(self, project_dir, cli=None):
        from PySide6.QtWidgets import QDialog
        self._accepted = QDialog.DialogCode.Accepted
        self.project_dir = project_dir
        self.open_terminal_cli, self.onboarding_ai_model = cli, ("opus" if cli else None)
        self.in_app_model, self.seeded, self.seeded_from = None, None, None

    def exec(self):
        return self._accepted


class _NewWindow:
    made = []

    def __init__(self):
        self.calls = []
        _NewWindow.made.append(self)
        self._status_strip = type("S", (), {"notify": lambda *a, **k: None})()

    def show(self):
        self.calls.append("show")

    def _adopt_choices_from_new_project(self, dialog):
        self.calls.append("adopt")

    def _open_intake_form(self):
        self.calls.append("intake")


def test_create_opens_the_new_window_on_the_form(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    _NewWindow.made = []
    monkeypatch.setattr(main_window, "NewProjectDialog",
                        lambda parent, seed_first=False: _Dialog(tmp_path / "n", cli="claude"))
    monkeypatch.setattr(main_window, "MainWindow", _NewWindow)
    monkeypatch.setattr(main_window, "_force_project_dir_env", lambda p: None)
    launched = []
    monkeypatch.setattr(main_window.terminal_launcher, "launch",
                        lambda *a, **k: launched.append(a))
    monkeypatch.setattr(window, "close", lambda: True)
    window._open_new_project_dialog()
    new = _NewWindow.made[0]
    assert new.calls == ["show", "adopt", "intake"]
    assert (new._intake_terminal_cli, new._intake_terminal_model) == ("claude", "opus")
    assert launched == [], "the terminal waits for the gate, it does not start at Create"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_new_project_dialog.py tests/test_intake_window.py -q -p no:randomly`
Expected: FAIL — `ProfileInterviewDialog` still importable from `npd`; `new.calls` lacks `"intake"`; `launched` is not empty.

- [ ] **Step 3: Implement `new_project_dialog.py`**

- Module docstring, first paragraph: replace with
  `""""Create new project" entry point (docs/TCC-TZ.md): folder + DSP vendor/model + how the AI runs. The intake itself is the skill's served form, which the new window opens (hub #194); this dialog no longer starts a conversational interview.`
  and in the list below it replace the second bullet with
  `* if the DSP is the same one, its profile travels with the copy; change the DSP and it does not, and the form's /new-dsp page asks for the new one.`
- Delete the import `from autosound_tcc.ui.tcc.profile_interview_dialog import ProfileInterviewDialog`.
- Class docstring: `"""Collects folder + vendor + model + how the AI runs, creates the project, and hands the caller (`main_window._open_new_project_dialog`) what it needs to open the new window on the intake form."""`
- Delete `self.interview_dialog: Optional[ProfileInterviewDialog] = None`.
- Delete the `_seed_no_interview` label block (lines ~200–210), its entry in `_on_seed_mode`'s loop and the line `self._seed_no_interview.setVisible(False)` after it, both `self._seed_no_interview.setVisible(False)` lines in `_on_seed_source`, and `self._seed_no_interview.setVisible(pair is not None)` in `_prefill_dsp`.
- In `_on_create`, replace everything from `# A project that arrived with its `dsp_profile.json`…` to the end of the method with:

```python
        cli = self._run_via_combo.currentData()
        if cli is None:
            self.in_app_model = AI_MODEL_IDS.get(self._ai_combo.currentText())
        else:
            self.open_terminal_cli = cli
            self.onboarding_vendor = vendor
            self.onboarding_model = model
            self.onboarding_ai_model = self._terminal_model_edit.text().strip() or None
        self.accept()
```

- [ ] **Step 4: Implement `main_window._open_new_project_dialog`**

Delete the whole `if dialog.interview_dialog is not None:` block. After `new_window.show()`, replace the rest of the method (the seeded-notice block stays, the terminal launch goes) with:

```python
        # Every path now: the interview used to carry the model choice, and there is no
        # interview any more (hub #194).
        new_window._adopt_choices_from_new_project(dialog)
        if dialog.seeded is not None and dialog.seeded_from is not None:
            said = i18n.t("npSeedDone").format(
                source=dialog.seeded_from.name, files=", ".join(dialog.seeded.written)
            )
            still_open = getattr(dialog.seeded, "profile_open", 0)
            if still_open:
                said = f"{said} {i18n.t('npSeedOpen').format(open=still_open)}"
            new_window._status_strip.notify(said)
        # The intake is the skill's form, opened straight away. A terminal CLI chosen in the
        # dialog is remembered and started from the gate offer, once the form has done its work.
        new_window._intake_terminal_cli = dialog.open_terminal_cli
        new_window._intake_terminal_model = dialog.onboarding_ai_model
        new_window._open_intake_form()
        self.close()
```

Keep the two existing comments above the seeded block (why the notice is shown) — move them with it.

- [ ] **Step 5: Rewrite `npOnboardingHint`; remove the dead keys**

Replace `npOnboardingHint` in the four languages (only `{language}` now):

```python
# en
        "npOnboardingHint": "Use the autosound-tuning skill. This project's intake was filled on the form, so read the project files first and continue from what the method still reports missing (contract.py check). Connect to this project's 'tcc' MCP server (see .mcp.json). Please work in {language}.",
# uk
        "npOnboardingHint": "Скористайся скілом autosound-tuning. Інтейк цього проєкту заповнено у формі, тож спершу прочитай файли проєкту й продовжуй із того, чого метод ще не має (contract.py check). Підключись до MCP-сервера 'tcc' цього проєкту (див. .mcp.json). Працюй {language}.",
# pl
        "npOnboardingHint": "Skorzystaj ze skilla autosound-tuning. Intake tego projektu wypełniono w formularzu, więc najpierw przeczytaj pliki projektu i kontynuuj od tego, czego metoda jeszcze nie ma (contract.py check). Połącz się z serwerem MCP 'tcc' tego projektu (zob. .mcp.json). Pracuj {language}.",
# de
        "npOnboardingHint": "Nutze den Skill autosound-tuning. Das Intake dieses Projekts wurde im Formular ausgefüllt; lies zuerst die Projektdateien und mach dort weiter, wo die Methode noch etwas vermisst (contract.py check). Verbinde dich mit dem MCP-Server 'tcc' dieses Projekts (siehe .mcp.json). Arbeite {language}.",
```

Delete `npSeedNoInterview` in all four languages. Then:

```bash
grep -rn "npSeedHint\|npSeedNoInterview\|ProfileInterviewDialog\|profile_interview_dialog" src tests
```
Expected: only `npSeedHint` definitions in `i18n.py` (delete them in all four languages) — nothing else.

- [ ] **Step 6: Delete the interview window and its test**

```bash
git rm src/autosound_tcc/ui/tcc/profile_interview_dialog.py tests/test_profile_interview_dialog.py
grep -n "test_profile_interview_dialog" tests/shard-weights.json
```
Remove that entry from `tests/shard-weights.json` (keep the JSON valid: no trailing comma).

- [ ] **Step 7: Run the tests**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_new_project_dialog.py tests/test_intake_window.py tests/test_i18n_languages.py tests/test_main_window.py -q -p no:randomly`
Expected: PASS, including `test_the_offer_starts_the_terminal_the_project_was_created_with`.

- [ ] **Step 8: Commit**

```bash
git add -A src/autosound_tcc tests
git commit -m "New project opens the intake form; the conversational DSP-profile interview is gone (hub #194)

A terminal CLI chosen in the dialog now starts from the gate offer, told the intake was filled on
the form. dsp_profile_interview.py (the CLI interviewer) stays.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The seat is chosen at the copy (`#193`)

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/new_project_dialog.py` (seed section; `_on_seed_mode`; `_on_seed_source`; `_would_travel`; `_sync_create_enabled`; `_on_create`)
- Modify: `src/autosound_tcc/ui/tcc/i18n.py`
- Test: `tests/test_new_project_dialog.py`

**Interfaces:**
- Consumes: `vendor_loader.load_project()` → `PROJECT_TYPES`, `project_type(data)`; `project_seed.seed(..., seat=)` (Task 1). The seat's words come from the method's own translations, `rew_tool/intake_i18n/<lang>.json` → `fields.goal.reference_seat.enum.<seat>` — the form and the dialog must name a seat the same way.
- Produces: `NewProjectDialog._seat_combo` (`currentData()` = seat code or `None`), `NewProjectDialog._seat_source` (`QLabel`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_new_project_dialog.py`)

```python
def _passat(tmp_path, seat=None):
    source = tmp_path / "source"
    source.mkdir()
    extra = f', "project_type": "{seat}"' if seat else ""
    (source / "project.json").write_text(
        '{"schema_version": 3, "car": {"make": "VW"}, '
        '"dsp": {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"}, "channels": []'
        + extra + "}", encoding="utf-8")
    return source


def test_a_copy_cannot_be_made_until_a_seat_is_chosen(tmp_path, monkeypatch):
    seeder = _StubSeeder(_Described("VW Passat B8", "Helix DSP Ultra S", 2), _Report(2))
    dlg = _dialog_on(_passat(tmp_path), seeder, monkeypatch)
    dlg._folder_edit.setText(str(tmp_path / "new"))
    assert dlg._seat_combo.currentData() is None
    assert not dlg._create_btn.isEnabled()
    dlg._seat_combo.setCurrentIndex(dlg._seat_combo.findData("passenger"))
    assert dlg._create_btn.isEnabled()


def test_the_seat_reaches_both_seed_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(npd.config, "set_project_dir", lambda p: None)
    seeder = _StubSeeder(_Described("VW Passat B8", "Helix DSP Ultra S", 2), _Report(2))
    dlg = _dialog_on(_passat(tmp_path), seeder, monkeypatch)
    dlg._folder_edit.setText(str(tmp_path / "new"))
    dlg._seat_combo.setCurrentIndex(dlg._seat_combo.findData("rear_left"))
    dlg._refresh_seed_note_now()
    dlg._on_create()
    seats = [kwargs.get("seat") for _src, _dst, kwargs in seeder.seeded_into]
    assert len(seats) >= 2 and set(seats) == {"rear_left"}, seats


def test_the_source_s_own_seat_is_named_beside_the_choice(tmp_path, monkeypatch):
    seeder = _StubSeeder(_Described("VW Passat B8", "Helix DSP Ultra S", 2), _Report(2))
    dlg = _dialog_on(_passat(tmp_path, seat="driver"), seeder, monkeypatch)
    driver = dlg._seat_combo.itemText(dlg._seat_combo.findData("driver"))
    assert driver in dlg._seat_source.text()


def test_the_seat_offers_exactly_the_method_s_seats_in_its_words():
    _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    codes = [dlg._seat_combo.itemData(i) for i in range(1, dlg._seat_combo.count())]
    assert codes == ["driver", "passenger", "both", "all", "rear_left", "rear_right"]
    assert all(dlg._seat_combo.itemText(i) != dlg._seat_combo.itemData(i)
               for i in range(1, dlg._seat_combo.count())), "labels come from the method, not codes"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_new_project_dialog.py -q -p no:randomly -k seat`
Expected: FAIL — `AttributeError: 'NewProjectDialog' object has no attribute '_seat_combo'`.

- [ ] **Step 3: Add the strings** (four languages, beside `npSeedFindings`)

```python
# en
        "npSeat": "Seat — who the copy is tuned for",
        "npSeatPick": "— choose the seat —",
        "npSeatSource": "In the source: {seat}. A different seat is exactly why a copy exists.",
        "npSeatUnset": "not set",
# uk
        "npSeat": "Місце — для кого налаштовуємо копію",
        "npSeatPick": "— оберіть місце —",
        "npSeatSource": "У джерелі: {seat}. Інше місце — саме те, для чого робиться копія.",
        "npSeatUnset": "не задано",
# pl
        "npSeat": "Miejsce — dla kogo stroimy kopię",
        "npSeatPick": "— wybierz miejsce —",
        "npSeatSource": "W źródle: {seat}. Inne miejsce to właśnie powód, dla którego robi się kopię.",
        "npSeatUnset": "nie ustawiono",
# de
        "npSeat": "Hörplatz — für wen die Kopie abgestimmt wird",
        "npSeatPick": "— Hörplatz wählen —",
        "npSeatSource": "In der Quelle: {seat}. Ein anderer Hörplatz ist genau der Grund für eine Kopie.",
        "npSeatUnset": "nicht festgelegt",
```

- [ ] **Step 4: Implement**

Module-level helpers (after `_seeder`):

```python
#: The method's seats, in its order, when the skill cannot be loaded (the dialog must still open).
_SEATS_FALLBACK = ("driver", "passenger", "both", "all", "rear_left", "rear_right")


def _seats() -> tuple[str, ...]:
    try:
        return tuple(vendor_loader.load_project().PROJECT_TYPES)
    except Exception:  # noqa: BLE001 — no skill: offer the seats the method is known to have
        return _SEATS_FALLBACK


def _seat_label(seat: str) -> str:
    """The seat in the method's own words (its form's translations), so the form and this dialog
    name a seat the same way; the code itself when no translation says otherwise."""
    import json

    for lang in (i18n.current_language(), "en"):
        path = vendor_loader.rew_tool_dir() / "intake_i18n" / f"{lang}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        label = (((data.get("fields") or {}).get("goal.reference_seat") or {})
                 .get("enum") or {}).get(seat)
        if label:
            return str(label)
    return seat


def _source_seat(source: Path) -> Optional[str]:
    import json

    try:
        data = json.loads((source / "project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        return vendor_loader.load_project().project_type(data)
    except Exception:  # noqa: BLE001 — an older method: read the field itself
        return data.get("project_type")
```

The translation keys are flat dotted ids (`d["fields"]["goal.reference_seat"]["enum"]`), checked on `c27cd7a`.

In `__init__`, directly after `layout.addWidget(self._seed_findings)`:

```python
        # The seat never travels: another seat is why a copy exists (hub #193, SKL-048). So it
        # is chosen HERE, with no default, and the source's own seat is said beside the choice.
        self._seat_label = _field_label(i18n.t("npSeat"))
        layout.addWidget(self._seat_label)
        self._seat_combo = QComboBox()
        self._seat_combo.setProperty("class", "mini-select")
        self._seat_combo.addItem(i18n.t("npSeatPick"), None)
        for seat in _seats():
            self._seat_combo.addItem(_seat_label(seat), seat)
        self._seat_combo.currentIndexChanged.connect(self._sync_create_enabled)
        self._seat_combo.currentIndexChanged.connect(self._refresh_seed_note_now)
        layout.addWidget(self._seat_combo)
        self._seat_source = QLabel("")
        self._seat_source.setWordWrap(True)
        self._seat_source.setProperty("class", "kv-lbl")
        layout.addWidget(self._seat_source)
```

In `_on_seed_mode`, add `self._seat_label, self._seat_combo, self._seat_source` to the tuple of widgets whose visibility follows `copying`.

In `_on_seed_source`, directly after `self._seed_describes = summary`:

```python
        seat = _source_seat(source) if (source is not None and summary is not None) else None
        self._seat_source.setText(i18n.t("npSeatSource").format(
            seat=_seat_label(seat) if seat else i18n.t("npSeatUnset")) if summary else "")
```

In `_would_travel` and in `_on_create`, add to each `seeder.seed(...)` call:

```python
                    seat=self._seat_combo.currentData(),
```

In `_sync_create_enabled`, replace the `setEnabled(...)` expression with:

```python
        copying = self._seed_combo.currentData() == "copy"
        seat_combo = getattr(self, "_seat_combo", None)  # built after the seed picker
        self._create_btn.setEnabled(
            bool(self._folder_edit.text().strip())
            and bool(self._vendor_edit.text().strip())
            and bool(self._model_edit.text().strip())
            and (not copying or (seat_combo is not None and seat_combo.currentData() is not None))
        )
```

(`_sync_create_enabled` runs from `_on_seed_mode` before the vendor fields exist too; if it raises
`AttributeError` on `_vendor_edit` in the new order, guard it the same way with `getattr`.)

- [ ] **Step 5: Run the tests**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_new_project_dialog.py tests/test_i18n_languages.py -q -p no:randomly`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/autosound_tcc/ui/tcc/new_project_dialog.py src/autosound_tcc/ui/tcc/i18n.py tests/test_new_project_dialog.py
git commit -m "Copying a project chooses the seat, in the method's words, with the source's seat named (hub #193)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: CHANGELOG, the whole suite, and the walk by hand

**Files:**
- Modify: `CHANGELOG.md` (`## [Unreleased]`)
- Modify: `docs/TODO.md` (F-055 → superseded)

- [ ] **Step 1: CHANGELOG entry** under `## [Unreleased]` (create the heading at the top if absent):

```markdown
### Added

- **The intake is a form.** Project menu → «Інтейк…» opens the method's own intake page in your
  browser, in the interface language; a new project opens on it straight away. Save writes the
  project files and the window follows. When phase 0 has everything it needs, the status line
  offers to start the session — one click, never automatic (hub `#194`).
- **Copying a project asks for the seat.** Driver, passenger, both, all, rear left or right — no
  default, with the source's own seat named beside it, because another seat is why a copy exists
  (hub `#193`).

### Removed

- **The conversational DSP-profile interview at "New project".** The form asks it, and for a
  processor the method has no profile for, the form's own page does.
```

- [ ] **Step 2: Mark F-055 superseded in `docs/TODO.md`**

Replace its `**Статус**:` line with:
`**Статус**: superseded 2026-09-22 · by hub #194 — one intake form for every front end, the skill's page (the Arbiter); built on wave-0.1.43`

- [ ] **Step 3: The whole suite, once** — VM suspended first (the Mac OOMs otherwise).

Run: `uv run --extra dev --python 3.12 python -m pytest tests -q -p no:randomly -n 4`
Expected: all pass. A failure in a file this plan did not touch is recorded, not fixed here.

- [ ] **Step 4: Walk it by hand** on the branch pin (`make run` or `uv run autosound-tcc`):
  1. Menu → «Інтейк…» on an existing project → the form opens in the browser, in the interface language.
  2. Click it again → the same address, no second process (`ps aux | grep intake_form`).
  3. Save a change on the form → the left column shows it within a second.
  4. Menu → «Скопіювати авто…» → «Скопіювати» stays grey until a seat is chosen; the source's seat is named; the copy's `project.json` has `project_type` = the choice.
  5. New project → the new window opens and the form with it; fill it until the gate is green → «Інтейк заповнено… Стартувати сесію» → click → the session starts.
  6. Quit TCC → `ps aux | grep intake_form` shows nothing.

- [ ] **Step 5: Commit and push**

```bash
git add CHANGELOG.md docs/TODO.md
git commit -m "CHANGELOG: the intake form and the seat at the copy; F-055 superseded by hub #194

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push
```
