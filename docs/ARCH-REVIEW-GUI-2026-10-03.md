# Architecture review — the GUI layer (PySide6 + pyqtgraph), 2026-10-03

A read-only review of `src/autosound_tcc/ui/tcc/` and of the parts of `core/` and `state/` the window
drives, at `f58d208` (v1.1.1). No code was changed; this file is the only output.

**Read first:** `CLAUDE.md`, `docs/ARCHITECTURE-NOTES.md`, `docs/TCC-Concept.md`,
`docs/CROSS-PLATFORM-PLAN.md`, `docs/DECISIONS-W-2.md` (the only `DECISIONS-*.md`), plus
`docs/DATA-MODEL-DECISIONS.md` (D-6) and `docs/TESTING.md`, because both carry decisions this
layer depends on. Recorded decisions are treated as settled. **No recommendation below reverses
one**; where a recommendation touches a decision, the decision is named beside it.

**How each claim was checked.** Every finding carries `path:line`. Paths under `ui/`, `core/` and
`state/` are relative to `src/autosound_tcc/`. Each claim is tagged with how it was checked:

- *read* — read in the code;
- *measured* — timed with a scratch probe, offscreen (the probes are not in the repo; the
  appendix says what each one did);
- *test* — a targeted pytest run;
- *not verified* — said where it applies, with the reason.

Every number comes from **a Linux container**: 4 vCPU, Python 3.12, PySide6 6.11.2, pyqtgraph
0.13.7, numpy 2.5.2, `QT_QPA_PLATFORM=offscreen`, warm caches. They are not macOS or Windows
numbers. The *shape* of a cost carries over (quadratic stays quadratic, N file writes stay N);
the absolute values do not. Starting a process costs much more on Windows, and none of that was
measured here.

---

## Summary

1. **The seams that broke before are sound.** Data flows one way (D-6). The MCP-to-Qt crossing goes through one locked bridge. Workers are `QThread`s registered for a safe shutdown, and the file watchers are coalesced. REW HTTP and the Agent SDK never run on the GUI thread.
2. **The main risk is the GUI thread itself.** Slots and constructors run subprocesses and wait on locks synchronously: `git` on every project reload, the reviewer-key probe (bounded at 20 s) while the window is built, the method's CLI writes behind a lock a capture check holds for up to 120 s, and a real seed with `git init` and a commit after every typing pause in "New project".
3. **Two hot paths were measured.** A streamed answer re-renders its whole message on every delta: 43 ms per delta by 8 kB, growing quadratically. One delay step in the curve window rebuilds every trace (about 180 ms with 7 impulses) and does 2·N file operations.
4. **Every agent write runs the full ↻ path** instead of a re-read: a contract check, a REW ping, a forced CLI re-probe, and all refusals forgotten.
5. **The model can be shown the wrong screen state.** `get_tcc_state` tells the model its `ui` block is "what is on their screen right now", but that snapshot is not republished when the preset, the edit mode or the theme changes.
6. **Startup is about 1.1–1.5 s offscreen; about 0.8 s of it is two imports.** `mcp` costs 0.46 s. pyqtgraph plus numpy cost 0.34 s, and they are pulled in at startup only for a tooltip helper.
7. **`MainWindow` carries most of the GUI.** It is 6,465 lines with 221 methods and about 168 attributes, and it does all the wiring. Decisions that live in it can only be tested by building a whole window, which its test file does 196 times.
8. **Recommended order:** five small, isolated fixes first. Then one helper for moving work off the GUI thread, used to migrate the blocking calls. Then an incremental redraw for the curve view, a slimmer constructor, and gradual extraction of the domain logic.
9. **No recorded decision needs reversing.** Where a fix touches one (D-6, A10, A21, S20, the delay bank's write-on-every-change), the finding names it.

---

## 1. Current architecture map

### 1.1 Start sequence (`app.py:main`)

| step | where | what it costs / why it is there |
|---|---|---|
| log + start line | `app.py:381-385` | before anything can fail (macOS full-screen focus, `core/app_log.py`) |
| model reading starts (thread) | `app.py:399`, `core/availability.py:245` | Windows waits for it inside the startup console, capped at 8 s (`app.py:421`, `availability.py:200`): the Arbiter's call (`core/child.py:243-244`) |
| one hidden app console (Windows) | `app.py:412-416`, `core/child.py:179-235`, `:644-708` | children inherit it instead of flashing their own (TCC-006) |
| answer-and-leave flags | `app.py:429-483` | `--version` etc. never import Qt |
| PySide6 imported lazily | `app.py:490-499` | the light install prints a usable sentence (`_NO_GUI`) |
| identity before `QApplication` | `app.py:515`, `:520` | Dock name on macOS, taskbar identity on Windows |
| splash + `_say` pumping | `app.py:551-563`, `:310-327` | covers the expensive import below |
| **`main_window` import** | `app.py:566` | **0.74–1.0 s measured** — §2, finding 7 |
| project gate | `app.py:583` | `ProjectGateDialog` before any window |
| **`MainWindow()`** | `app.py:586` | 0.21–0.38 s measured, with no ledger loaded — §2, findings 1, 6 |
| paint wait, then splash hand-over | `app.py:600-631` | no blank frame on Windows (video, 2026-09-09) |
| `app.exec()`; `qt_shutdown.destroy_application()` | `app.py:647-666` | refuses to delete Qt while a thread is alive (F-014) |

### 1.2 Window composition

```
MainWindow (ui/tcc/main_window.py:753)          one per project; a project switch relaunches
├─ header            _build_header :968         ☰ menu · preset · target curve · zoom · theme · layout · ↻ · diagnostics
├─ StatusStrip       status_strip.py            "what TCC found" — every outcome is said here
├─ QSplitter (H)     :869-905
│  ├─ left           _build_left :2260          SidebarSection ×3: Project params (+ git state) · System params
│  │                                            (car, acoustics, flaws, channel switches) · DSP (DspTreeWidget)
│  ├─ centre         _build_center :3500        QSplitter (V): DetailPane (tables / EQ cards)  /  DialogPanel
│  │                                            (AI dialog, bubbles, ConfirmBar, composer)
│  └─ right          _build_right :3563         QSplitter (V): PlanPanel (phases/steps)  /  MeasurementPanel
│                                               ("in focus now": capture round, REW import, «Готово»)
└─ footer            _build_footer :1377        AI main · effort · reviewer · reviewer status · Start session · Terminal

ControlLayout (control_layout.py:555)  F-069 / A9-A13 / S23: moves the SAME panels into
   tabs [Monitoring · Table-V · Table-O · EQ · params] over a left|right split, and back.
```

The secondary windows are all `QDialog`s:

- **`CurveDialog`** (`curve_dialog.py`): not modal, `Qt.Tool`, and only ever one instance, which is re-pointed rather than rebuilt (`main_window.py:2173-2219`).
- **Dialogs opened from MainWindow:** `DiagnosticsDialog`, `ProtectiveDialog` / `ProtectiveLegsDialog`, `ListeningDialog`, `ResonalyzeImportDialog`, `FeedbackDialog`, `ModelConfigDialog`, `ReviewerKeyDialog`, `SaveConfigDialog`.
- **`NewProjectDialog`.** "Create" builds a whole new `MainWindow()` inside the slot (`main_window.py:2865`).
- **Opened from MeasurementPanel:** `CaptureImportDialog` and `ChannelOrderDialog`.
- **Other:** `ProjectGateDialog` (shown before any window exists) and `AttachImageDialog`.

### 1.3 Where state lives

| state | store | written by | read by |
|---|---|---|---|
| project data: `project.json`, `dsp_profile.json`, `state/<preset>/v_NNN.json`, `process/process-state.json`, journal | the project folder | **the skill only** (D-6). TCC writes only through the method's own CLIs: `core/process_writer.py`, `profile_writer.py`, `config_writer.py`, `title_fixes.py` | `state/*` loaders |
| view models | `state/dsp_state.py:423` `ProjectView` and the other frozen dataclasses; `process_view` / `measurement_view` return dicts | rebuilt on each reload (`_load_project` `main_window.py:2406`, `_refresh_process` `:3865`) | widgets |
| TCC's own per-project choices | `<project>/.tcc/tcc-project.json` (`core/project_settings.py:51-76`) | MainWindow, `delay_bank`, the project gate | `mcp_server`, `critic`, `self_check` |
| per-machine preferences | QSettings ini (`ui/tcc/app_settings.py:23-24`) | about 10 ui modules (theme, zoom, splits, language, gate) | the same modules |
| in-memory UI state | ~168 `self._*` attributes on `MainWindow`; 99 reads go through `getattr(self, "_…", default)` | MainWindow | MainWindow, ControlLayout |
| what the model is told is on screen | `QtUiBridge._snapshot` (`qt_bridge.py:51-64`) | `_publish_snapshot` (`main_window.py:4713`) | `get_tcc_state` (`core/mcp_server.py:608`) |
| the Arbiter's requests to the session | `core/signal_bus.py` | MainWindow, DialogPanel | MCP `get_pending_signals` |

### 1.4 Wiring

**MainWindow is the only hub.**
- It has 116 `.connect(` lines.
- `ui/tcc` declares 82 `Signal`s across 33 classes.
- Only one connection goes directly from one child to another: `plan_panel.sessionRequested` → `meas_panel.show_session`, made in `_build_right`.
- There is no mediator inside the UI.

**How background work reaches the GUI.**
- **QThread workers emit signals.** Results arrive as queued slots on the GUI thread. These workers are `workers.py:29/52/123/190/252`, `agent_worker.py:34`, `curve_dialog.py:322`, the three in `measurement_panel.py:151/184/254`, and `capture_import_dialog.py:71`.
- **Plain threads are polled by `QTimer`s** that read a shared attribute:
  - the title's update check (`main_window.py:4665-4682`, every 500 ms);
  - the diagnostics probes (`diagnostics_panel.py:361/389/417`, every 250 ms);
  - feedback sending (`feedback_dialog.py:142-177`, every 150 ms);
  - the project gate (`project_gate_dialog.py:156-161`).
- **The MCP thread uses `QtUiBridge`.**
  - From the agent to the GUI, it emits signals (`qt_bridge.py:66-96`).
  - From the GUI to the agent, it uses a locked dict and a `Future`.
  - No widget is touched from any thread (*read*: a sweep of every thread body and thread target found none).
- **Watchers and timers.**
  - Two `QFileSystemWatcher`s are coalesced to 400 ms (`main_window.py:3753-3781`).
  - Polling timers: pending toggles every 1 s (`:796`), the signal nudge every 2 s (`:808`), and the REW ping every 30 s while the window is active (`:928`).

---

## 2. Findings, ranked by impact

Impact means how often a person meets it, times how bad it is when they do. Effort is S (hours),
M (a few days) or L (a wave).

### 1. The GUI thread runs subprocesses and lock waits in everyday paths — High · M

**Evidence.** A *read* survey; every row below was opened and checked.

| path | GUI-thread chain | bound |
|---|---|---|
| every project reload, plus every model or effort pick | `_set_project_params` → `_show_git_state` (`main_window.py:3253`) → `project_view.git_status` → 6 `git` children on a repository with a remote (*measured*: 6 children, about 16 ms on Linux) | 2 s each (`state/project_view.py:45`, `:434-491`). Callers: `main_window.py:2502, 2548, 4755, 5710, 5723, 5966, 6413` |
| window construction | `reviewer_key.prefetch()` (`:867`) starts a thread that holds `_LOCK` while it runs `key status --json`. Forty lines later the footer (`:907` → `:1481` → `_fill_combo` → `model_choices.py:920` → `reviewer_key.py:131` → `:107`) waits on the same lock. *Measured:* 0.10–0.15 s of `MainWindow()` | 20 s (`reviewer_key.py:45`) |
| window construction | `TccMcpServer.start()` (`main_window.py:4568`) → `_ready.wait(5)` plus a sleep-poll until uvicorn reports it has started (`mcp_server.py:1825-1828`, `:1858-1869`). *Measured:* about 0.11 s of tool registration alone | 5 s + 5 s |
| answering the model in the dialog | `arbiterAnswered` → `_record_decision` → `process_writer.record_decision` (`main_window.py:4411`). Every `process_writer` call takes a module-wide `_THREAD_LOCK` (`process_writer.py:50`, `:159`), and `capture-check`, run from `_CaptureCheckWorker` each time REW's titles change, holds that lock for up to 120 s (`process_writer.py:574`) | 20 s + however long the current holder of the lock takes |
| starting a session; protective and listening saves | `process_writer.record_session` / `enter_phase` (`main_window.py:5365-5376`); one call per channel in `protective_dialog.py:314-319` | the same lock |
| "New project", while the user types | a 250 ms debounce (`new_project_dialog.py:154`, `:471`) → `_would_travel` → `seeder.seed` into a temp dir (`:436-450`) → the method's `project_repo.init` → `git init`, `config` ×2, `add`, `diff`, `commit` (`vendor/…/rew_tool/project_seed.py:521-528`, `project_repo.py:40-42`, `:98-111`) | 60 s per `git` call |
| git backup buttons | `_on_git_init` → `project_repo.init` (`main_window.py:3192`); `_on_git_backup` → `gh repo create`. The code says so itself: "this runs on the GUI thread" (`core/project_repo.py:85-86`) | 600 s (`project_repo.py:25`) |
| hand-off | `_on_handoff` → `handoff.check` (`main_window.py:4065`, `core/handoff.py:25`, `:34-38`) | 30 s |
| diagnostics | `_render` → `self_check.run()` (`diagnostics_panel.py:1711`) → local `git` calls (`self_check.py:197-217`) | 12 s each (`updates.py:81`) |
| reviewer-key window | `status(refresh=True)` in the constructor (`reviewer_key_dialog.py:229`) and on save / drop / remove | 20 s each. Already in the backlog: `docs/TODO.md:2110` |
| model configuration | `omp_catalogue()` while populating (`model_config_dialog.py:155`) | 20 s |
| macOS terminal | `terminal_launcher._osascript` (`core/terminal_launcher.py:300-304`) | **no timeout** |
| macOS terminal placement | `place_terminal_left` (`control_layout.py:259`) | 5 s |
| GitHub feedback route | `gh api`, once per screenshot (`vendor/…/gates/side_effect.py:93-95`) | **no timeout** (in the method's code) |

**Risk.** Each bound is a guarantee only against a hang. On a normal day the cost is a freeze of
one spawn time per child. On Windows, a `git` spawn is tens of milliseconds and a Python child is
hundreds (*not verified here*; Linux numbers only). The worst rows are the ones a person
triggers while doing something else:

- **Typing a car's name** runs `git init` and a commit on every pause.
- **Answering the model** waits behind a 120 s capture check.
- **Changing the reviewer** runs six `git` calls before the combo box closes.

A macOS Automation-permission prompt in front of an `osascript` call with no timeout is a frozen
window until somebody answers it. That is *suspected, not verified*: there is no macOS here.

**Effort: M.** The fix is one small helper rather than a rewrite: run a callable off the GUI
thread, deliver the result by signal, and register the thread with `qt_shutdown`. The callers then
move to it one at a time (§3, step 6). Today every worker is a bespoke `QThread` subclass, and
four modules poll plain threads with timers. Nothing in the code uses `QThreadPool` or
`invokeMethod` (*read*).

### 2. A streamed answer re-renders the whole message on every delta — High · S

**Evidence.**
- *Read:* the SDK streams partial messages (`core/tuning_session.py:364`), so there is one `TextDelta` per `content_block_delta` (`:455-459`).
- Each delta reaches `_append_live_text` (`dialog_panel.py:1137-1148`). That method re-runs `markdown()` over all the text so far, calls `set_html` on the bubble's `QLabel`, re-measures `natural_width` over the whole plain text (`:166-197`), and scrolls.
- *Measured,* feeding 12-character deltas into a `DialogPanel`:

| answer | deltas | total GUI time | per delta at the end |
|---|---|---|---|
| 2 kB | 167 | 1.1 s | 11.5 ms |
| 8 kB | 667 | 14.9 s | 42.8 ms |
| 20 kB | 1,667 | 87.9 s | 102.6 ms |

- *Profiled:* 94% of that time is Qt relaying out the growing rich-text label inside `processEvents`. Markdown and measuring together are under 5%.

**Risk.** The dialog is the main workspace (`TCC-Concept.md` §2.1). Once deltas arrive faster
than they are drawn, the queued `chunk` signals pile up with no back-pressure
(`agent_worker.py:187`, `:199`). The window then falls behind the model and stops responding to
input for the rest of a long answer.

**Effort: S.** Buffer the deltas and redraw on a single-shot timer at about 10–20 Hz. Flush on
`ToolCall`, `turn_done` and `failed`. The per-redraw cost still grows with the message length,
but redraws now happen a bounded number of times per second. A later step could keep the closed
paragraphs as fixed blocks and re-render only the open one.

### 3. Every agent write runs the full ↻ path, not a re-read — Medium-High · S

**Evidence** (*read*).
- In `core/mcp_server.py:960-965`, `_record` calls `bridge.refresh_from_disk()` after every write the method records. About 16 MCP tools go through it (`:979-1160`), among them `record_capture`, `start_step`, `record_decision` and `check`. `:1081` and `:1487` call it too.
- The signal is connected to `_reload_from_disk` (`main_window.py:4554`). That is the header's ↻ (`:1970-1987`), and it does four more things after reloading the project:
  - it restarts the contract check, which is a child process;
  - it pings REW;
  - it calls `availability.forget_refusals()`;
  - it calls `_refresh_cli_catalogue(force=True)`. `force=True` skips the quiet period that exists "to stop window switching from spawning probes" (`:1983-1985`, `:4175-4186`), so `agy` and `claude auth` are probed again.

**Risk.**
- **Child processes on every write.** During a capture round the session records constantly, so each write costs a burst of children. On Windows each child is a potential flash, and the whole TCC-006 effort exists to prevent exactly that.
- **The picker forgets its warnings.** `forget_refusals()` clears what S20 colours red ("the closed picker turns red for anything this launch saw refused"). After each agent write the picker forgets until the next probe answers.
- **Reloads twice.** The project watcher already reloads on the same writes (`:3769-3781`), so they happen twice.

**Effort: S.** Connect `refreshRequested` to the coalesced re-read: `_project_reload.start()` and
`_process_reload.start()`. Keep ↻ as the explicit full re-check. This is D-6's own wording: the
MCP signal means "re-read the state", it carries no data, and it asks for no re-probe
(`DATA-MODEL-DECISIONS.md` D-6).

### 4. One curve-window step rebuilds every trace and does 2·N file operations — Medium-High · S + M

**Evidence.**
- **What a step does** (*read*):
  - `set_delay` → `set_traces` (`curve_view.py:1414-1442`). `set_traces` calls `self._plot.clear()` and re-creates every `PlotDataItem` (`:1784-1842`). `setData` is not used anywhere in the module.
  - It then recomputes the sum (`:1853`) and renders the readout. The readout is rendered again by `set_delay` itself (`:1441`), and each render builds the marker tables twice (`:3546` and `:3554`).
- **What it costs** (*measured*):
  - Each impulse trace is 262,144 points (the code's own figure, `curve_view.py:641-643`, `curve_dialog.py:393-395`).
  - One delay step costs about **53 ms with 2 traces and 180 ms with 7**, offscreen.
- **The bank** (*read*): the dialog banks on every step (`curve_dialog.py:596-600`). `_bank_current_delay` calls `delay_bank.put` once per trace (`:1374-1381`). Each call reads `.tcc/tcc-project.json` and atomically rewrites it (`delay_bank.py:179` → `project_settings.py:65-76`). `_render_bank` then reads the file twice more (`curve_dialog.py:1394-1395`), and for an impulse an `argmax` over 262k points runs for every trace.
- **Opening a set** (*read*): `_on_curves` restores the banked delay and all-pass trace by trace (`curve_dialog.py:1714`, `:1720`), and each restore is another full rebuild.

**Risk.**
- **The alignment pass stutters.** That is the workflow this window exists for. Arrow and wheel steps redraw once per step, and the all-pass f0 and Q boxes are accelerated on top of that (`curve_view.py:918`, `:940`).
- **Windows makes the writes worse.** Opening and replacing a file costs more there, and antivirus scanning applies to the temp files (*not verified*).

**Effort.**
- **S:** one `put_many` that does one read and one write per step. That keeps the docstring's promise, "written on every change rather than on close" (`curve_dialog.py:1354-1358`). Also: compute the readout once per event.
- **M:** update the existing items with `setData` and change only the legend text. Recreating fewer objects also means less of the churn behind the crashes recorded in this module's comments (`curve_view.py:361-478`). Re-measure that crash rate with the module's own protocol (5/40 → 0/40) before and after.

### 5. The MCP snapshot goes stale while the model is told it is the screen — Medium · S

**Evidence.**
- *Read:* `_publish_snapshot` (`main_window.py:4713-4725`) writes `preset`, `param_edit_mode` and `theme`. It is called only when the MCP server starts (`:4558`) and on a language change (`:6373`).
  - A preset switch goes `_on_preset_index` (`:3053-3059`) → `_load_project`, with no republish.
  - `_on_dialog_editing_changed` (`:3558-3561`) and `_apply_theme` do not republish either.
- `get_tcc_state` returns that `ui` block and says "what the Arbiter configured in the UI and what is on their screen right now. Act on it." (`core/mcp_server.py:608-640`).
- *Measured:* on a two-preset rig the combo showed `FULL` and the snapshot said `None`. After switching the combo to `SQ`, the snapshot still said `None`. The reason is that the snapshot uses `config.resolve_preset()` (`:4716`), while `_load_project` falls back to the first preset it finds (`:2437-2446`).

**Risk.** The model acts on a preset or edit mode the Arbiter has left. The method can then
write a proposal against the wrong slot. It is a correctness fault, not a performance one.

**Effort: S.** Republish from `_load_project`, `_on_dialog_editing_changed` and `_apply_theme`,
using the preset `_load_project` actually chose. Add a test that switches the combo and reads
`bridge.snapshot()`.

### 6. The constructor does too much, including a nested event loop — Medium · M

**Evidence** (*read*).
- **A modal question inside the constructor.** `MainWindow.__init__` (`main_window.py:759-964`) builds the footer, and filling the pickers can run `_offer_replacement`, which calls `box.exec()` (`:5578`). That is a nested event loop inside a half-built window. Timers fire inside it.
- **This has already broken once.** Commit `afc0106` (this wave, CI) patched one instance: the 2 s nudge ran before `_mcp_server` existed (`:803-807`).
- **Other modal questions inside slots:**
  - from worker-signal slots: `_on_cli_catalogue_ready` (`:4209`) and `_on_reviewer_probed` (`:5439`);
  - from a QTimer slot: `diagnostics_panel._poll_skill_job` → `box.exec()` (`diagnostics_panel.py:901`).
- **The constructor also blocks** on the MCP server start and the reviewer-key lock (finding 1), and runs the git chain while loading the project.
- **The rest of the class follows the same pattern.** Only 36 of its ~168 attributes are set in `__init__`, and 99 reads go through `getattr(self, "_…", default)` because methods run before the attribute they read exists. `main_window.py:779-784` records the same class of fault (HUB-046).

**Risk.**
- More `afc0106`-shaped faults: a slot runs against a window that is not finished.
- A first paint that waits for child processes.

**Effort: M.** Split construction in two:
- **Build widgets only** in `__init__`.
- **Run everything else from `QTimer.singleShot(0, self._after_first_paint)`:** the MCP start, the reviewer-key read, any replacement question, the contract check, and the update check.

The comment at `main_window.py:2862-2864` relies on `.mcp.json` existing before `.show()`; the
new-project path then has to await the server explicitly.

### 7. Startup imports: about 0.8 s of 1.1–1.5 s — Medium · S + M

**Evidence** (*measured*).
- **Phases,** from three warm runs of a probe that mirrors `app.main`:

| phase | time |
|---|---|
| PySide6 (QtCore / QtGui / QtWidgets) | 78–82 ms |
| `import main_window` | 736–1005 ms |
| `MainWindow()` with MCP off | 209–320 ms |
| `MainWindow()` with MCP on | 314–376 ms |
| show + paint | 37–72 ms |

- **What `import main_window` contains** (`-X importtime`): 1.14 s cumulative, of which:
  - **`mcp` 462 ms:** `main_window.py:91` → `core/mcp_server.py:70`; also reached through `core/omp_session.py:66` and `ui/tcc/qt_bridge.py:25`, which need only `ConfirmRequest` / `UiBridge` / `HeadlessBridge`;
  - **`curve_view` 337 ms, which includes pyqtgraph 234 ms and numpy 92 ms:** `main_window.py:132` imports it **only for `tip_html`**, a 17-line HTML formatter (`curve_view.py:331-347`) used once (`main_window.py:1794`). `CurveDialog` is already imported lazily (`:2164`);
  - **`main_window`'s own module body:** 41–53 ms.
- **Not imported at startup:** scipy, `claude_agent_sdk`, `curve_dialog`.

**Risk.** The start is about a third slower than it needs to be, every launch. A cold first run
after an update makes it worse, because everything is byte-compiled again (`app.py:57-61`).

**Effort.**
- **S:** move `tip_html` to a light module, `rounded_tooltip` or a new one. That saves about 0.34 s.
- **M:** split the protocol types out of `core/mcp_server.py` into a light module, so `mcp` / FastMCP / uvicorn are imported by `_start_mcp_server` after the first paint (finding 6). That saves about 0.46 s before the first pixel.
- **Constraint:** any deferred import must happen **on the GUI thread**, never on a worker. `core/install_report.py:11-16` records that PySide6's import hook makes imports on a worker thread crawl. I could not reproduce that difference here (an SDK import took 462–751 ms on either thread). The rule stays: it was measured on the development machine (2026-08-19, a report that never finished inside the dialog's thread).

### 8. `MainWindow` is the whole application, and its decisions need a window to test — Medium · L

This is the cost of every future change. It does not freeze anything today.

**Evidence** (*read*).
- **Size.** `main_window.py` has 6,465 lines and 221 methods. It sets ~168 private attributes and is the only connection hub (116 `connect` lines).
- **`ControlLayout` reaches into the window's private state.**
  - It reads about 20 distinct `MainWindow` private attributes, about 50 times in all (`control_layout.py`: `w._preset_combo` ×11, `w._main_splitter` ×6, `window._compare_view_now`, …).
  - It moves live widgets between layouts. That is the operation behind the native crash `tcc#19` (`docs/TESTING.md`, "Known flakiness"; fixed in `discard.drop`, `ui/tcc/discard.py:36`).
- **MainWindow calls other widgets' privates** 19 times (e.g. `self._dialog._add_system_message`), plus `_detail._build_table` and `_detail._compare_version`.
- **Domain logic that lives in widgets, or is written twice:**
  - **"Is this capture settled":** `main_window.py:4248-4256`, and again as `answered` at `:4334-4339`, beside `state/measurement_view.py:496-518`, `:662-669`. The second copy parses the checker's text (`"UNUSABLE <title> — "`).
  - **Signal ids** are parsed back out of the human-readable `bus.unacked_brief()` (`main_window.py:4038-4040`). `core/signal_bus.py` has no API that returns open ids.
  - **Delay maths** in `curve_view.proposed_delays` (`:1460-1497`) mirrors `core/delay_bank.py:254-256`. The phase ramp in `_shifted` (`:1742`) mirrors `core/curve_sum.py:362`.
  - **The reviewer's state:** `_critic_notes` / `_fill_combo` / `_tint_critic_combo` (`main_window.py:4787-4897`, `:5589-5644`) work out the reviewer's state beside `core/mcp_server.py:203-265`.
  - **Private access across layers:** `main_window.py:635` reads the private `model_choices._CRITIC_VENDOR_MARKERS` to re-derive `vendor_of`.
  - **Decisions that exist only on the window:** `_capture_version` (`:4498-4526`), `_effective_gate` (`:5838-5849`), the default compare version (`:2641-2664`), and the preset choice (`:2437-2446`).
- **The tests show the cost.**
  - `tests/test_main_window.py` is 7,527 lines with 270 tests and builds `MainWindow()` 196 times.
  - Examples that build a full window only to check a pure function: `:1322` (`_effective_gate`), `:2327` / `:2381` (`_capture_version`), `:6675` (`_critic_notes`), and `:5713` (the `settled` check).
  - `docs/TESTING.md` measured this one file at 53 s alone and 302 s inside the suite.

**Risk.**
- Every change to a decision pays for building a window, in time and in exposure to the
  native-teardown flakiness the suite already carries (`tcc#22`, `tcc#28`).
- Copies that are written twice drift apart. "Settled" is already written three ways.

**Effort: L in total, S per extraction.** The precedent exists: F-091 moved
`table_fields` / `cell_text` / `field_changed` into the Qt-free `ui/tcc/row_rule.py`, and
`setting_status.py:24` now imports it. That makes `docs/TODO.md:2108` already done.

### 9. Group semantics are still hard-coded in the UI — Low-Medium · M

**Evidence** (*read*).
- `ARCHITECTURE-NOTES.md` §1, hole 4, and its own work order, item 4 ("move the group mapping out of `dsp_tree.py` into the profile's data"), have been open since 2026-08-07.
- The ids now appear in four modules:
  - `dsp_tree.py:55-56`, `:87-91`;
  - `detail_pane.py:870`;
  - `control_layout.py:227`, `:713-715`, `:976`, `:1002`.

**Risk.** A processor with a third tier gets no table and no tab. This is the class of fault D-0
and D-4 were written against.

**Effort: M.** Build the tables and tabs from the groups the profile declares. **Keep A10's two
named tabs** (Table-V and Table-O) for the two known ids, and add a generic fallback for any
other declared group, so A10 is not reversed.

### 10. Cross-platform gaps that remain — Low · S

- **Windows monospace font (*not verified*).** Every monospace rule names `"SF Mono", Menlo, monospace` (`theme.py:1077` and 16 more rules), and Windows has neither. Whether Qt maps the generic `monospace` to a fixed-pitch face on Windows, rather than the UI font, was not checked; there is no Windows machine here. Check it on the VM, and if it falls back to the UI font, add `Consolas, "Cascadia Mono"`.
- **DPI.**
  - Font sizes are `px` in QSS, scaled by the zoom with a regex (`theme.py:339-347`). The bad stored zoom values seen on Windows are now clamped (`main_window.py:767-774`).
  - No high-DPI policy is set, so Qt 6's default pass-through applies.
  - Nothing here showed a fault (*read only*). Finding 18 (`DECISIONS-W-2.md` A18) stays parked as recorded.
- **macOS:** the `osascript` calls (finding 1). `TSMSendMessageToUIServer` noise stays: `ARCHITECTURE-NOTES.md` §6, and §9 (no `.app` / `.pkg`) is the decision that keeps it.
- **Windows console:** the handling is deliberate, measured on the affected machine, and guarded by tests (§4). Findings 1 and 3 are where its cost actually comes from: every child the window spawns is a candidate flash.
- **Disk weight of the gui extra (*measured*).** On Linux, scipy plus its libraries are **111 MB** against PySide6's 233 MB. scipy is not imported at startup. `pyproject.toml`'s "tens of megabytes … noise" understates it. That is a comment to correct, not a dependency to drop: `core/protective.py` needs it.

### 11. Smaller curve-view costs on a marker drag — Low · S

These were read in the code, not measured.

- **Each move** of a marker runs `_render_readout`, which builds the tables twice (`curve_view.py:3546`, `:3554`).
- **In `vhs` mode,** `_sync_levels` moves the h-markers (`:3528`), and each move re-emits `sigPositionChanged`. That re-enters the handler: about 1 + (number of h-markers) renders per mouse move.
- **Cross mode** builds a new `ScatterPlotItem` on every move (`:3023-3045`).
- **A switch to linear x** builds a new `pg.AxisItem` (`:2702`).
- **Changing the kind** computes the sum three times (`:2718`, `:2731`, `:2798`).

Fold these into finding 4's M step.

### 12. A long but bounded shutdown — Low · leave

`closeEvent` (`main_window.py:6210`) and `stop_workers` (`:6133-6191`) wait a bounded time at each
step: 2, 3, 3, 5 and 5 s per worker, 5 s to join the MCP server, and 3 s per thread left over
(`qt_shutdown.py:55`). In the worst case that sums to about a minute. That total is added up from
the constants in the code, not measured.

This is the deliberate trade made in F-014 and F-027: bounded waits, then detach rather than
abort. It is listed so that nobody "fixes" it by removing a wait.

---

## 3. Recommended changes, in order

The order is by value over risk. Steps 1–5 are independent, small, and each fits in one commit
with a red-first test, as `CLAUDE.md` asks.

1. **Coalesce streamed text** (finding 2). Use a single-shot timer in `DialogPanel` and flush it on `ToolCall`, `turn_done` and `failed`.
   - Test: feed 600 deltas and assert that the label was set at most about 30 times. That counts calls, not wall time, so CI cannot flake on it.
2. **Republish the MCP snapshot** wherever its fields change, from the preset `_load_project` chose (finding 5).
   - Test: switch the combo and read `bridge.snapshot()["preset"]`.
3. **Re-wire `refreshRequested`** to the coalesced disk re-read, and keep ↻ as the full re-check (finding 3).
   - Test: a `_record` call must start no `_CliCatalogueWorker` and leave the refusals as they were.
4. **Bank all traces with one write per step** (`delay_bank.put_many`), and render the readout once per event (findings 4 and 11, the S parts).
5. **Move `tip_html` out of `curve_view`** (finding 7, the S part).
   - Test: `test_packaging.py` already runs imports in a subprocess. Add one asserting that importing `main_window` does not import `pyqtgraph`.
6. **Add one off-thread helper** (finding 1). It runs a callable on a `QThread`, delivers the result by signal, and registers with `qt_shutdown.watch`. Then migrate in this order:
   1. `git_status` (paint "checking…" until it answers). A21 / F-079 stays as decided: the Project
      params header still says whether git runs, whether there is a repository and whether it is
      backed up. Only *when* that is computed changes;
   2. the reviewer-key read in the constructor;
   3. the `process_writer` calls made from the GUI (decision, session, phase, protective, listening);
   4. the seed preview;
   5. the git init and backup buttons;
   6. `handoff.check`;
   7. diagnostics `self_check`;
   8. the reviewer-key and model-config dialogs.

   Alongside:
   - Give `terminal_launcher._osascript` a timeout.
   - Open bus tickets for the parts that are the method's:
     - a seed preview that makes no repository (`project_seed.py:521-528`);
     - a timeout on `gh api` (`side_effect.py:93-95`).

     Per `CLAUDE.md`, a change in `vendor/` goes to the `skill` role as a ticket, never as an edit here.
7. **Incremental redraw for `CurveView`** with `setData` (finding 4, the M part). Re-measure the crash rate with the module's own protocol first and after.
8. **Two-phase `MainWindow` construction** (finding 6), then the lazy `mcp` import that depends on it (finding 7, the M part).
9. **Extract decisions from `MainWindow`, one at a time** (finding 8), following the `row_rule` precedent:
   - one "settled" verdict in `state/measurement_view`;
   - an open-ids API on `signal_bus`;
   - the reviewer's state, shared with `mcp_server`;
   - `_effective_gate`, `_capture_version` and the compare default as pure functions.

   Each extraction then lets one or more full-window tests be rewritten as plain-function tests. Give `ControlLayout` a narrow interface to the window instead of its private attributes.
10. **Derive the group tables and tabs from the profile** (finding 9), keeping A10's two tabs.
11. **Check the Windows monospace fallback** on the VM, and correct the scipy comment in `pyproject.toml` (finding 10).

---

## 4. What should NOT change, and why

- **D-6: data flows one way.** The skill writes; TCC reads and sends intents.
  - `_on_channel_toggle` puts a signal on the bus instead of writing (`main_window.py:3921-3958`), and every write goes through the method's CLI (`core/process_writer.py`).
  - Finding 3's fix narrows the MCP path *towards* D-6; it does not move away from it.
- **The `QtUiBridge` crossing** (`qt_bridge.py:1-15`). Signals carry the agent-to-GUI direction, and a locked dict plus a `Future` carry the GUI-to-agent direction. The code builds the snapshot on the GUI thread rather than walking the widget tree from the server thread. That shape closed a use-after-free class of fault, and nothing in this review found a widget touched from another thread.
- **`QThread` workers with queued signals, and the shutdown registry.** This covers `qt_shutdown.watch/detach/stop_or_detach` (`qt_shutdown.py:74-218`) and `destroy_application` refusing to destroy Qt around a live thread (`app.py:654-666`). F-014 and F-027 bought it with two `SIGABRT`s. The helper in §3 step 6 must **use** it, not replace it.
- **REW and the Agent SDK stay off the GUI thread.**
  - REW calls run inside worker `run()` methods (`curve_dialog.py:361-442`, `workers.py:48`, `measurement_panel.py:179`).
  - The Agent SDK session is built on the worker (`agent_worker.py:172`).
- **Coalesced file watchers that re-arm themselves** (`main_window.py:3753-3847`). Atomic writes replace inodes, and the `autosound-tcc#3` lesson about watching a `state/` folder that does not exist yet is written into `_watched_project_dirs`.
- **The leak fixes of 2026-08-12** (`docs/TESTING.md`): the `WeakSet` of windows with a module-level quit hook (`main_window.py:952-964`), the memoised app stylesheet, and `WeakMethod` i18n listeners. A theme toggle measures about 200 ms and a language switch about 30 ms; leave them as they are.
- **The pyqtgraph choices and workarounds:**
  - peak auto-downsampling with clip-to-view and antialias off (`curve_view.py:641-645`, `:685-686`);
  - a single `CurveDialog`, re-pointed rather than rebuilt (`main_window.py:2207-2211`);
  - the ctrl-menu and form workarounds (`curve_view.py:361-478`), backed by measured crash rates;
  - the tight `pyqtgraph<0.14` bound (`pyproject.toml`), because the code touches its internals.
- **The extras split and the layering guards.** The base install has no Qt, and the window and Claude are extras (`ARCHITECTURE-NOTES.md` §3, decision 2026-08-12). `core` and `state` never import `ui`, and the light half never imports Qt or numpy (`tests/test_packaging.py:96-124`; *test:* 260 passed in the guard set below). These keep the cleanup in finding 8 honest.
- **The Windows console strategy** (`core/child.py`): one app console, inherited by every child; `CREATE_NO_WINDOW` as the process default; and the keeper. These are the Arbiter's calls, measured on the machine that had the problem (TCC-006). The anyio private-module patch is guarded by `tests/test_child.py:27-57`, so a move in anyio fails loudly.
- **The splash and the paint wait** (`app.py:53-109`, `:600-631`). Both are answers to a recorded video of a blank window.
- **Per-machine vs per-project settings** (S23): splitter borders are stored per machine, the layout mode per project.
- **No `.app`, `.pkg` or `.exe`** (`ARCHITECTURE-NOTES.md` §9). The macOS TSM noise in §6 is the accepted price.
- **Imports at module top in the core modules that workers call** (`core/install_report.py:11-16`, `core/updates.py:31-32`). It did not reproduce here, but it was measured on the development machine (2026-08-19), and it is why §3's lazy imports must happen on the GUI thread.
- **Serial test runs as the default, and `--dist loadfile`** (`docs/TESTING.md`). Nothing in this review argues for changing either. The `-n 4` runs below were for evidence, never for a verdict.

---

## Appendix — what was run, and what was not verified

**Tests** (offscreen, `-n 4 --dist loadfile`, relevant files only):

| files | result |
|---|---|
| `test_packaging`, `test_qt_shutdown`, `test_splash_timing`, `test_startup_console`, `test_slot_errors`, `test_doubles`, `test_conftest_guards`, `test_reviewer_key`, `test_child`, `test_theme` | **260 passed** in 7.8 s |
| `test_curve_view`, `test_dialog_panel`, `test_curve_sum`, `test_control_layout`, `test_qt_shutdown`, `test_dialog_live` | **458 passed, 2 skipped** in 52 s |

**Scratch probes.** They lived in the session's scratchpad and are not committed. Each is described
well enough to rebuild:

| probe | what it did |
|---|---|
| import time | `python -X importtime -c "import autosound_tcc.ui.tcc.main_window"` ×3, aggregated by top-level package and by first importer |
| startup | mirrors `app.main`: a tmp `HOME`, a 10-channel Helix profile in a tmp project, phases timed with `perf_counter`, `MainWindow()` profiled with `cProfile`, run with `AUTOSOUND_TCC_MCP` set to 0 and to 1. Its ledger sat outside `state/`, so the window drew the rig with no configuration loaded: building a full ledger's tables is **not** in these numbers |
| git | counted the `subprocess.run` calls in `project_view.git_status` on this repository and on a folder that is not a repository |
| streaming | `DialogPanel._on_chunk(TextDelta(...))` with 12-character deltas of Markdown-ish text, followed by `processEvents()` each time; then `cProfile` on the 8 kB case |
| curve step | `CurveView` with 2 or 7 traces of 262,144 points, `set_traces`, then ten `set_delay` steps |
| theme / language / reload | `_toggle_theme`, `_change_language`, `_reload_project_files` on a built window |
| snapshot | a two-preset rig with `AUTOSOUND_STATE_ROOT` set; the combo switched, then `bridge.snapshot()["preset"]` read |
| worker-thread import | `import claude_agent_sdk` with a `QApplication` alive, on the main thread and on a `threading.Thread` |

**Not verified:**

- **Timing on macOS and Windows.** Nothing was timed on either; Windows process-spawn costs especially.
- **The Windows monospace fallback** (finding 10).
- **`osascript` blocking behind a macOS Automation prompt** (finding 1).
- **Contention in practice.** That `process_writer`'s lock makes the GUI wait was read in the code, not reproduced.
- **The seed preview's wall time.** No seed-source fixture was built, so only the number of `git` calls was established.
- **The shutdown worst case** of about a minute, which was summed from constants (finding 12).
- **The PySide6 import-hook penalty on worker threads.** It did not reproduce here, and is kept as recorded.
- **Items the code sweep flagged as suspected and that were not chased:**
  - unlocked module caches written by workers (`model_choices._CLI_CACHE`, `claude_sdk._SIGNED_IN`);
  - `ui/capture_order/<preset>` QSettings keys colliding across projects that share a preset name;
  - GUI-thread reads that grow with project history (`process_view.stale_channels`, `ledger_line.py:129`, `critic.last_call`).

---

## Appendix B — FF-01 status

FF-01 is the external audit of 2026-09-06, run on v0.1.32. Each of its seven items is checked
here at `f58d208`; this branch adds only this document on top of that commit. The audit's own
figures are taken as stated and not re-derived.

The guards named below were run offscreen with `-n 4`: `test_terminal_launcher`,
`test_model_choices`, `test_doubles` and `test_packaging` gave **151 passed, 2 skipped**. The five
named guard tests also passed when run alone, and `ruff@0.12.0 check src tests scripts` gave
"All checks passed!".

1. **`main_window.py` at about 4,300 lines; split it, moving the workers to `ui/tcc/workers.py` and the models to `state/models.py` — changed.**
   - The split was done. The five workers are imported from `ui/tcc/workers.py` (`main_window.py:144-152`; the module is 281 lines), and the domain types live in `state/models.py` (101 lines; HUB-051, `state/models.py:1-7`).
   - But `main_window.py` has since grown to **6,465 lines**, with 221 methods. It is still the problem described in this review's finding 8.
2. **`core/` and `state/` importing from `ui/` in four places — fixed.**
   - None of the four cited lines is an import any more: `core/config.py:152` is a docstring, `core/self_check.py:321` is blank, and `state/measurement_view.py:23` and `state/process_view.py:25` import from `state/`.
   - The two core modules now take what they need through a hook. `config.use_settings` (`core/config.py:193-196`) is set by `ui/tcc/app_settings.py:31`, and `self_check.use_translator` (`core/self_check.py:371-373`) is set by `ui/tcc/diagnostics_panel.py:64`.
   - The dataclasses come from `state/models.py` (`state/measurement_view.py:24`, `state/process_view.py:26`). `mock_data.py` only re-exports them (`ui/tcc/mock_data.py:15-16`).
   - `grep` finds no `autosound_tcc.ui` import under `core/` or `state/`. `tests/test_packaging.py:95-103` enforces that, and `:106-115` shows the guard going red.
3. **The `class Bus` stubs had no `pending_count`, which the 2 s timer reads — fixed.**
   - `tests/test_main_window.py` has no `class Bus` any more; it uses the real `signal_bus.SignalBus` (`:2150`, `:2202`, `:6289`). The timer's read is at `main_window.py:4035`.
   - `tests/test_doubles.py:121` checks that every double answers the whole bus protocol, and `:141` shows that check going red.
   - `tests/conftest.py:33` fails any test in which a Qt slot raised (HUB-046).
4. **`measurement_panel.py` annotates a non-existent `_RewReadWorker` (ruff F821) — fixed.**
   - The name is gone from `measurement_panel.py`. Its workers are `_RewScanWorker` (`:151`), `_RewRenameWorker` (`:184`) and `_LedgerWriteWorker` (`:254`).
   - ruff, whose selection includes `F`, passes on the whole tree.
   - One stale mention remains in a docstring, not in code: `core/rew_bridge.py:52`.
5. **An order-dependent Qt abort (exit 134) on Linux offscreen — still present.**
   - The repository's own record keeps it open and unexplained. `docs/TESTING.md:282` says "no repro yet", under hub HUB-049.
   - `.github/workflows/ci.yml:6` still describes it, and the Linux jobs carry `continue-on-error` "until HUB-049 is closed" (`:166`, `:227-230`).
   - The `shiboken6.isValid` guard in `i18n.set_language` is still in place (`ui/tcc/i18n.py:5291`).
   - **Not verified:** the full Linux suite was not run in this session. The targeted runs did not abort, but they are too small to say anything about a flake of this kind.
6. **Model names hard-coded in `mock_data.py` and `i18n.py`, beside `tuning_session.py` and `model_choices.py` — changed.**
   - The identifiers now live only in `core/model_choices.py`:
     - `tests/test_model_choices.py:673` asserts it for each id at `:658`;
     - `core/tuning_session.py:59` takes `DEFAULT_SDK_MODEL` from there;
     - the picker's list is derived from `model_choices.SDK_MODELS` (`ui/tcc/mock_data.py:30`).
   - `i18n.py` carries no model name except in a comment (`:1225`).
   - Two **display names** are still hard-coded in `mock_data.py`:
     - `CURRENT_GENERATOR_MODEL = "Claude Opus 5"` (`:29`), which labels the dialog until a session attaches (`dialog_panel.py:305`, replaced at `:891`);
     - `AI_CRITIC_MODELS` (`:31`), which nothing imports.
7. **`terminal_launcher.py` used `shell=True` with `project_dir` inside the command string — fixed.**
   - No `shell=True` is left anywhere in `src/`.
   - In the `cmd` fallback the folder is passed as `cwd`, never put in the command line, and the comment says why (`core/terminal_launcher.py:356-372`, HUB-053).
   - On the `wt` path the folder is an argument of its own, with `;` escaped (`:143-144`, `:350-354`).
   - Tests cover paths with `&` and `"` (`tests/test_terminal_launcher.py:317`, `:344`) and one console instead of two (`:368`).

**Of the 7: 4 fixed (2, 3, 4, 7), 1 still present (5), 2 changed (1, 6).**
