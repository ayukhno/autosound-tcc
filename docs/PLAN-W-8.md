# Plan · W-8 · v1.1.2 — the audit's first wave

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the agent↔window crossing tells the model what is on screen and costs the GUI thread less (G2), every
boundary that went silent says what happened (G1), and `main_window.py` stops growing (G13 step 0).

**Architecture:** small, local changes in the files that own each behaviour — no new layer. One shared helper
(`mcp_server.await_confirmation`) replaces three copies of the same swallow. `TccMcpServer` gains a truthful
liveness answer (`stopped_reason`). A test module holds the size ratchet.

**Tech Stack:** Python 3.11+, PySide6 (Qt offscreen in tests), asyncio, claude-agent-sdk 0.2.145, uvicorn 0.52.4,
pytest.

**Spec:** `docs/PLAN-AUDIT-2026-10.md` §2 G1, G2, G13 (the four lines and the first tests of each finding);
`docs/audit/AUDIT-2026-10-VERIFIED.md` (file:line of each finding). Milestone `W-8 · v1.1.2` (#8), all issues `ok`
by the Arbiter 2026-10-06. Pool `docs/TODO.md` F-097.

**Not in this plan yet:** G13's three seams (#161 menu registry, #162 strings per feature, #163 car source). They go
through the group's architects first (`hub:seam`); the Arbiter picks the approach, and then their tasks are added
here as a section of their own. N2 (#164) is a standing test run the controller does when the skill names a
candidate (§ N2 below), not a build.

## Global Constraints

- Repo `/Users/o.yukhno/dev/autosound/tcc`, branch `wave-8`; no worktree, no new branch, no push by a builder.
- Tests targeted only, at most `-n 4`; never the whole suite while building. Qt offscreen (`tests/conftest.py`).
  Run tests with `.venv/bin/python -m pytest …`.
- A test fails before its fix, and the builder saw it fail.
- Every user-facing string in `ui/` through `src/autosound_tcc/ui/tcc/i18n.py` (uk + en; pl and de carry the
  English until the Advisor). `core/` must not import the ui (`tests/test_packaging.py`), so a `Notice` written in
  `core/` is English, as every existing one there is.
- Text measured in a test goes through `theme.drawn_width` (the Windows CI runner has no fonts).
- An API key never on argv or in a log; no real API calls, no live REW, GitHub or `gh` in tests.
- `docs/TODO.md`, `docs/TEST-FINDINGS.md`, this plan and `CHANGELOG.md` are the controller's.
- Commits in English (the hook refuses Cyrillic), the issue number in the subject, ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit after reading the test result, never chained
  after the test command in one line.
- `src/autosound_tcc/ui/tcc/main_window.py` may grow by the few lines Tasks 1, 2 and 4 need; Task 10 then sets the
  bound at the size it finds. After Task 10 the file may not grow.

---

## G2 · The agent↔window crossing (#151–#153)

### Task 1 · #151 TA-5 — the agent is told the preset and edit mode that are on screen

`_publish_snapshot` reports `self._preset_override or config.resolve_preset()`. `resolve_preset` is None for two or
more presets, while `_load_project` falls back to `available[0]`; an override left by another project is reported
as is, while the load ignores it. The snapshot is republished only at MCP start and on a language switch, so a
preset switch or edit mode never reaches the model. Every existing preset test sets `AUTOSOUND_TCC_PRESET`, which
hides it.

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/main_window.py` — `__init__` (~832, beside `_preset_override`),
  `_load_project` (~2406), `_on_dialog_editing_changed` (~3558), `_publish_snapshot` (~4713).
- Test: `tests/test_main_window.py`.

**Interfaces:**
- Produces: `MainWindow._loaded_preset: str | None` — the preset the last `_load_project` chose (None when it chose
  none). `_publish_snapshot()` is safe to call before the bridge exists.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_main_window.py`)

```python
def _two_presets(tmp_path, monkeypatch):
    """A seeded project with two presets and no AUTOSOUND_TCC_PRESET — the case every preset test
    hid by setting it (TA-5)."""
    from autosound_tcc.core import vendor_loader

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("AUTOSOUND_STATE_ROOT", raising=False)
    monkeypatch.delenv("AUTOSOUND_TCC_PRESET", raising=False)
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    _intake.seed(tmp_path)
    vendor_loader.load_dsp_state().PresetHistory(
        str(tmp_path / "state"), "SECOND", project_dir=str(tmp_path)).snapshot({
            "preset": "SECOND", "sample_rate": 96000,
            "channels": {"w-L": {"hp": None, "lp": None, "gain_db": 0.0, "ta_ms": 0.0,
                                 "polarity": "NORM"}},
        }, note="fixture: a second preset")
    assert config.available_presets() == ["FULL", "SECOND"], "the situation this is about"
    assert config.resolve_preset() is None


def test_the_agent_is_told_the_preset_on_screen_when_there_are_two(tmp_path, monkeypatch):
    """TA-5: with two presets `resolve_preset` is None while the window shows the first, so the
    model was told no preset at all about a screen that had one."""
    _two_presets(tmp_path, monkeypatch)
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)

    assert window._preset_combo.currentData() == "FULL"
    assert window._bridge.snapshot()["preset"] == window._preset_combo.currentData()


def test_a_preset_switch_reaches_the_agent(tmp_path, monkeypatch):
    _two_presets(tmp_path, monkeypatch)
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)

    window._preset_combo.setCurrentIndex(window._preset_combo.findData("SECOND"))

    assert window._bridge.snapshot()["preset"] == "SECOND"


def test_a_preset_left_by_another_project_is_not_reported(tmp_path, monkeypatch):
    """`ui/preset` is global; the load ignores a name this project does not have, and the
    snapshot reported it anyway."""
    _two_presets(tmp_path, monkeypatch)
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)

    window._preset_override = "GONE"
    window._load_project()

    assert window._bridge.snapshot()["preset"] == "FULL"


def test_edit_mode_reaches_the_agent(tmp_path, monkeypatch):
    _two_presets(tmp_path, monkeypatch)
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)

    window._dialog._start_editing("manual")
    assert window._bridge.snapshot()["param_edit_mode"] is True
    window._dialog._finish_editing()
    assert window._bridge.snapshot()["param_edit_mode"] is False
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/test_main_window.py -k "preset_on_screen or preset_switch_reaches or left_by_another_project or edit_mode_reaches" -q`
Expected: 4 FAIL (`None != 'FULL'`, the stale `'GONE'`, the edit flag never republished).

- [ ] **Step 3: Implement**

In `__init__`, beside `self._preset_override` (~832):

```python
        #: The preset the last `_load_project` chose — what the agent is told is on screen (TA-5).
        self._loaded_preset: str | None = None
```

Rename the body of `_load_project` to `_load_project_inner` (same code, unchanged, docstring moves with it) and
give `_load_project` this wrapper, so every early return publishes too:

```python
    def _load_project(self) -> None:
        """Load the project, then tell the agent what is now on screen (TA-5)."""
        self._loaded_preset = None
        try:
            self._load_project_inner()
        finally:
            self._publish_snapshot()
```

In `_load_project_inner`, right after the preset is chosen (`preset = config.resolve_preset(root) or (available[0]
if available else None)`, ~2446):

```python
        self._loaded_preset = preset
```

`_publish_snapshot` (~4713): guard the bridge and report the loaded preset:

```python
    def _publish_snapshot(self) -> None:
        """Mirror what's on screen into the bridge, for `get_tcc_state` to read off-thread."""
        bridge = getattr(self, "_bridge", None)
        if bridge is None:  # the first load runs before the MCP server's bridge exists
            return
        bridge.set_snapshot(
            # The preset the load chose, not `resolve_preset`: that is None for two or more
            # presets, and an override from another project is not what is on screen (TA-5).
            preset=self._loaded_preset,
            project_dir=str(config.project_dir()),
            ...  # the other fields exactly as they are
        )
```

`_on_dialog_editing_changed` (~3558): add `self._publish_snapshot()` as its last line.

- [ ] **Step 4: Run the four tests, then the neighbours**

Run: `.venv/bin/python -m pytest tests/test_main_window.py -k "preset or snapshot or editing" -q -n 4` and
`.venv/bin/python -m pytest tests/test_dialog_live.py -k snapshot -q`
Expected: PASS. A test that patched `MainWindow._load_project` keeps working (the wrapper is the same name).

- [ ] **Step 5: Commit** — `#151 TA-5: the agent is told the preset and edit mode on screen`

### Task 2 · #152 TA-3 — an agent write re-reads the project once, not the whole ↻

`report_phase` lands on `refreshRequested → _reload_from_disk`, the header's ↻: the project, the contract check,
a REW ping, `availability.forget_refusals()` and a forced model catalogue — per write. ↻ stays exactly that; the
agent's signal gets a coalesced re-read of the project and the contract.

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/main_window.py` — a module constant near the other `_…_MS` constants;
  `_start_mcp_server` (~4554, the `refreshRequested` connection); two new methods beside `_reload_from_disk` (~1970).
- Modify: `tests/test_main_window.py` ~3529 (`test_the_header_reload_asks_again_for_the_title` calls
  `_reload_from_disk` as «what the session's report_phase lands on» — it lands elsewhere now).
- Test: `tests/test_main_window.py`.

**Interfaces:**
- Produces: `main_window._AGENT_REFRESH_MS = 300`; `MainWindow._on_agent_refresh()` (the slot);
  `MainWindow._reread_after_agent()` (what the timer runs); `MainWindow._agent_refresh_timer: QTimer`.

- [ ] **Step 1: Write the failing test**

```python
def test_an_agent_write_rereads_the_project_without_the_full_recheck(monkeypatch):
    """TA-3: every `report_phase` ran the header's ↻ — REW, the models, the refusals — and a
    session that wrote five files ran it five times. The agent's signal re-reads the project and
    the contract once the writes settle; ↻ stays the explicit full re-check."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    loads, checks, pings, catalogues, forgets = [], [], [], [], []
    monkeypatch.setattr(MainWindow, "_safe_load_project", lambda self: loads.append(1))
    monkeypatch.setattr(MainWindow, "_start_contract_check", lambda self: checks.append(1))
    monkeypatch.setattr(MainWindow, "_ping_rew", lambda self: pings.append(1))
    monkeypatch.setattr(MainWindow, "_refresh_cli_catalogue",
                        lambda self, force=False: catalogues.append(force))
    monkeypatch.setattr(main_window.availability, "forget_refusals", lambda: forgets.append(1))

    for _ in range(5):
        window._bridge.refresh_from_disk()

    assert _pump_until(lambda: bool(loads), seconds=5), "the re-read comes once the writes settle"
    _pump_until(lambda: False, seconds=0.6)  # and no second one after it
    assert loads == [1] and checks == [1]
    assert pings == [] and catalogues == [] and forgets == []
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_main_window.py -k agent_write_rereads -q`
Expected: FAIL — five loads, five pings, five forced catalogues.

- [ ] **Step 3: Implement**

Constant:

```python
#: An agent write is answered with ONE re-read once the writes settle (TA-3): `report_phase` fires
#: per write, and each used to run the whole ↻.
_AGENT_REFRESH_MS = 300
```

In `_start_mcp_server`, replace `self._bridge.refreshRequested.connect(self._reload_from_disk)` with:

```python
        self._agent_refresh_timer = QTimer(self)
        self._agent_refresh_timer.setSingleShot(True)
        self._agent_refresh_timer.setInterval(_AGENT_REFRESH_MS)
        self._agent_refresh_timer.timeout.connect(self._reread_after_agent)
        self._bridge.refreshRequested.connect(self._on_agent_refresh)
```

(keep the comment above the old line; it still says why this signal exists).

Beside `_reload_from_disk`:

```python
    def _on_agent_refresh(self) -> None:
        """The session's `report_phase`: the skill wrote something. A burst of writes is one re-read
        (the timer restarts), and it is not ↻: REW, the models and the refusals did not change
        because a file did (TA-3)."""
        self._agent_refresh_timer.start()

    def _reread_after_agent(self) -> None:
        self._safe_load_project()
        self._start_contract_check()
```

In `test_the_header_reload_asks_again_for_the_title` (~3529) replace `window._reload_from_disk()  # what the
session's report_phase lands on` with `window._bridge.refresh_from_disk()  # what the session's report_phase sends`
and keep its `QTest.qWait(50)` and the assertion `asked == []`.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_main_window.py -k "agent_write or reload or refresh" -q -n 4` — PASS.

- [ ] **Step 5: Commit** — `#152 TA-3: an agent write re-reads the project once, not the whole reload`

### Task 3 · #153 TA-2 — a streamed answer is redrawn at ~15 Hz, not per delta

`DialogPanel._append_live_text` runs markdown, `setText` and the fit over the whole message on every delta. The first
delta stays immediate (about 20 `tests/test_dialog_live.py` tests read the bubble right after one); the rest are
drawn by a single-shot timer; anything that ends the live bubble draws what is waiting first.

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/dialog_panel.py` — a constant; `__init__` (create the timer BEFORE anything in
  `__init__` that can add or clear bubbles — the mock transcript); `_append_live_text` (~1135); the places that end
  the live bubble: `_on_chunk`'s Notice and Unasked branches (~1123, ~1131), `_add_question` (~1205), `_add_chip`
  (~1287), `_on_turn_done` (~1307); `clear` (~950, ~972).
- Test: `tests/test_dialog_live.py`.

**Interfaces:**
- Produces: `dialog_panel._LIVE_REDRAW_MS = 66`; `DialogPanel._draw_live_text()`; `DialogPanel._end_live_bubble()`;
  `DialogPanel._live_timer: QTimer`; `DialogPanel._live_drawn: str`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_long_stream_is_drawn_at_a_bounded_rate_and_whole_at_the_end(tmp_path, monkeypatch):
    """TA-2: every delta re-rendered the whole message — markdown, setText and the fit — so a long
    answer cost the GUI thread O(n²). The first delta is drawn at once, the rest at most ~15 times
    a second, and the end of the turn draws whatever is still waiting."""
    panel, worker, _ = _attached(tmp_path)
    drawn = []
    real = MessageBubble.set_html

    def counting(self, html, source=""):
        drawn.append(source)
        return real(self, html, source)

    monkeypatch.setattr(MessageBubble, "set_html", counting)

    worker.chunk.emit(TextDelta("first "))
    assert len(panel._bubbles) == 1
    assert "first" in panel._bubbles[0]._plain, "the first delta is on screen at once"

    words = [f"w{i} " for i in range(599)]
    for word in words:
        worker.chunk.emit(TextDelta(word))
    worker.turn_done.emit()

    assert len(drawn) <= 30, f"{len(drawn)} redraws for 600 deltas"
    assert panel._bubbles[0]._source == "first " + "".join(words), "the end draws the rest"


def test_a_stream_is_drawn_while_it_streams(tmp_path):
    from PySide6.QtTest import QTest

    panel, worker, _ = _attached(tmp_path)
    worker.chunk.emit(TextDelta("one "))
    worker.chunk.emit(TextDelta("two"))

    for _ in range(40):
        if panel._bubbles[0]._source == "one two":
            break
        QTest.qWait(25)
    assert panel._bubbles[0]._source == "one two", "the timer draws without waiting for the end"


def test_text_waiting_to_be_drawn_is_drawn_before_a_tool_call(tmp_path):
    panel, worker, _ = _attached(tmp_path)
    worker.chunk.emit(TextDelta("a"))
    worker.chunk.emit(TextDelta("b"))

    worker.chunk.emit(ToolCall(name="mcp__tcc__get_tcc_state"))

    assert panel._bubbles[0]._source == "ab"
```

(If `MessageBubble.__init__` does not set `_plain`, assert on `panel._bubbles[0]._source` in the first test instead.)

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/test_dialog_live.py -k "bounded_rate or while_it_streams or before_a_tool_call" -q`
Expected: the first FAILS with 599 redraws; the other two pass today and must stay green.

- [ ] **Step 3: Implement**

```python
#: A streamed answer is redrawn at ~15 Hz, not per delta (TA-2).
_LIVE_REDRAW_MS = 66
```

In `__init__`, before the first bubble is added or cleared:

```python
        # Every delta re-ran the markdown and the fit over the whole message (TA-2); the timer
        # draws what has arrived at most once per tick, and the first delta is still immediate.
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(_LIVE_REDRAW_MS)
        self._live_timer.timeout.connect(self._draw_live_text)
        self._live_drawn = ""
```

```python
    def _append_live_text(self, text: str) -> None:
        if not text:
            return
        self._live_text += text
        if self._live_bubble is None:
            self._add_bubble("gen", f"Generator · {self._model_label}",
                             _markdown(self._live_text), self._live_text)
            self._live_bubble = self._bubbles[-1]
            self._live_drawn = self._live_text
            self._scroll_to_end()
        elif not self._live_timer.isActive():
            self._live_timer.start()

    def _draw_live_text(self) -> None:
        """Bring the live bubble up to the text received so far — at most once per tick."""
        self._live_timer.stop()
        if self._live_bubble is None or self._live_text == self._live_drawn:
            return
        self._live_bubble.set_html(_markdown(self._live_text), self._live_text)
        self._fit(self._live_bubble)
        self._live_drawn = self._live_text
        self._scroll_to_end()

    def _end_live_bubble(self) -> None:
        """The live answer is over — a tool call, a notice, a question, the turn's end: draw what is
        still waiting, then let the next text start a new bubble."""
        self._draw_live_text()
        self._live_bubble = None
        self._live_text = ""
        self._live_drawn = ""
```

Replace the pair `self._live_bubble = None` / `self._live_text = ""` with `self._end_live_bubble()` in the Notice
and Unasked branches of `_on_chunk`, in `_add_question`, in `_add_chip` and in `_on_turn_done` (there, after the
`turn_ended_in_a_dropped_connection(self._live_text)` check, which reads the text). In `clear` (both resets) add
`self._live_timer.stop()` and `self._live_drawn = ""` — a clear discards, it does not draw.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_dialog_live.py -q -n 4` — PASS. A test that fed two
deltas and read the RENDERED body without ending the turn gets `panel._draw_live_text()` before its read; one that
reads `_live_text` needs nothing.

- [ ] **Step 5: Commit** — `#153 TA-2: a streamed answer is redrawn at a bounded rate, not per delta`

**Group review after Task 3 (controller):** `pr-review-toolkit:silent-failure-hunter` and
`pr-review-toolkit:pr-test-analyzer` on the diff of Tasks 1–3; findings in one round of fixes.

---

## G1 · Boundaries say what happened (#154–#159)

### Task 4 · #156 F3c — a dead MCP server is told, not handed to the next session

uvicorn sets `Server.started` once and never clears it (checked in 0.52.4), so `TccMcpServer.serving` read True for
a server whose thread had died, and `_launch_session` checked only `self._mcp_server is None`.

**Files:**
- Modify: `src/autosound_tcc/core/mcp_server.py` — `TccMcpServer.serving` (~1872) and a new `stopped_reason`.
- Modify: `src/autosound_tcc/ui/tcc/main_window.py` — `_launch_session` (~5320).
- Test: `tests/test_mcp_server.py`, `tests/test_main_window.py`.

**Interfaces:**
- Produces: `TccMcpServer.stopped_reason -> Optional[str]` — None while it starts or serves; `"<Type>: <message>"`
  when `failure` is set; `"the MCP server's thread ended"` when the thread is dead without one.
  `TccMcpServer.serving` is `started and stopped_reason is None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_mcp_server.py`:

```python
def test_a_server_whose_thread_died_is_not_serving_and_says_why(tmp_path):
    """F3c: uvicorn's `started` is set once and never cleared, so `serving` read True for a server
    whose thread had died."""
    import threading
    from types import SimpleNamespace

    from autosound_tcc.core.mcp_server import TccMcpServer

    server = TccMcpServer(project_dir=tmp_path)
    assert server.stopped_reason is None and not server.serving, "never started: nothing to say"

    server._server = SimpleNamespace(started=True)  # uvicorn got up once
    server._thread = threading.Thread(target=lambda: None)
    server._thread.start()
    server._thread.join()
    assert not server.serving
    assert server.stopped_reason == "the MCP server's thread ended"

    server.failure = OSError("p")
    assert server.stopped_reason == "OSError: p"
```

`tests/test_main_window.py`:

```python
def test_a_session_is_not_started_on_a_server_that_died(tmp_path, monkeypatch):
    """F3c: the window held a server whose thread had died and handed its URL to the next session;
    it now says why the server is down, once, as it does for one that never started."""
    from types import SimpleNamespace

    from autosound_tcc.core.mcp_server import TccMcpServer

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    dead = TccMcpServer(project_dir=tmp_path)
    dead._server = SimpleNamespace(started=True)
    dead.failure = OSError("p")
    said = []
    monkeypatch.setattr(window._dialog, "_add_system_message",
                        lambda text, *_a, **_k: said.append(text))
    window._mcp_server = dead
    try:
        window._launch_session()
    finally:
        window._mcp_server = None

    assert len(said) == 1
    assert i18n.t("mcpDown") in said[0] and "OSError: p" in said[0]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/test_mcp_server.py tests/test_main_window.py -k "thread_died or server_that_died" -q`
Expected: FAIL — `stopped_reason` does not exist; the window goes on to build a session.

- [ ] **Step 3: Implement**

`mcp_server.py`, in `TccMcpServer`:

```python
    @property
    def stopped_reason(self) -> Optional[str]:
        """Why a server that was started is not up any more — None while it starts or serves.

        `serving` could not say it alone (F3c): uvicorn sets `started` once and never clears it,
        so a server whose thread had died still read as up, and the next session was handed a URL
        nothing answered on."""
        if self.failure is not None:
            return f"{type(self.failure).__name__}: {self.failure}"
        if self._thread is not None and not self._thread.is_alive():
            return "the MCP server's thread ended"
        return None

    @property
    def serving(self) -> bool:
        """Whether uvicorn is actually up — not merely whether a thread was created, and not after
        it died."""
        return bool(getattr(self._server, "started", False)) and self.stopped_reason is None
```

`main_window.py`, the top of `_launch_session`:

```python
        server = self._mcp_server
        reason = (getattr(self, "_mcp_error", "") if server is None
                  else getattr(server, "stopped_reason", None))
        if server is None or reason:
            # WITH the reason. … (the existing comment, unchanged)
            where = app_log.log_path()
            self._dialog._add_system_message(
                "⚠️ " + i18n.t("mcpDown")
                + (f" {reason}" if reason else "")
                + (f"\n{i18n.t('mcpDownLog')} {where}" if where else "")
            )
            return
```

(the later `server = self._mcp_server` line stays or goes — `server` is already bound).

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_mcp_server.py tests/test_main_window.py -k "serving or server or launch or install_facts" -q -n 4` — PASS.

- [ ] **Step 5: Commit** — `#156 F3c: a dead MCP server says why instead of being handed to a session`

### Task 5 · #157 F3e — a failed confirmation is logged, and stays a denial

Three places wrap `bridge.request_confirmation` in `except Exception: denied` with nothing written:
`mcp_server.build_server._confirm` (~560), `tuning_session.TuningSession._ask` (~294),
`omp_session.OmpSession._gate` (~596). One helper replaces all three.

**Files:**
- Modify: `src/autosound_tcc/core/mcp_server.py` — new module function `await_confirmation` beside
  `CONFIRM_TIMEOUT_S` (~94); `_confirm` uses it.
- Modify: `src/autosound_tcc/core/tuning_session.py` (`_ask`), `src/autosound_tcc/core/omp_session.py` (`_gate`) —
  import and use it.
- Test: `tests/test_mcp_server.py`, `tests/test_tuning_session.py`, `tests/test_omp_session.py`.

**Interfaces:**
- Produces: `async def await_confirmation(bridge, request: ConfirmRequest, timeout_s: float) -> bool` in
  `autosound_tcc.core.mcp_server`. True only on the Arbiter's yes; a timeout is False, silent; any other exception is
  False and one WARNING on `app_log.logger()` naming the request's tool, the exception type and its message.

- [ ] **Step 1: Write the failing tests**

`tests/test_mcp_server.py`:

```python
class _BrokenBar:
    """A confirmation bar that fails instead of answering."""

    def request_confirmation(self, request):
        raise RuntimeError("boom")


class _SilentBar:
    """A confirmation bar nobody answers."""

    def request_confirmation(self, request):
        from concurrent.futures import Future
        return Future()


def test_a_failed_confirmation_is_logged_and_denied(caplog):
    """F3e: the failure read as the Arbiter's «no», with nothing in the log."""
    import asyncio
    import logging

    from autosound_tcc.core import app_log
    from autosound_tcc.core.mcp_server import ConfirmRequest, await_confirmation

    request = ConfirmRequest(tool="bash", title="Allow bash?", detail="rm x", payload={})
    with caplog.at_level(logging.WARNING, logger=app_log.LOGGER_NAME):
        allowed = asyncio.run(await_confirmation(_BrokenBar(), request, timeout_s=1.0))

    assert allowed is False
    assert any("boom" in r.getMessage() and "bash" in r.getMessage() for r in caplog.records)


def test_an_unanswered_confirmation_is_a_quiet_denial(caplog):
    import asyncio
    import logging

    from autosound_tcc.core import app_log
    from autosound_tcc.core.mcp_server import ConfirmRequest, await_confirmation

    request = ConfirmRequest(tool="bash", title="Allow bash?", detail="rm x", payload={})
    with caplog.at_level(logging.WARNING, logger=app_log.LOGGER_NAME):
        allowed = asyncio.run(await_confirmation(_SilentBar(), request, timeout_s=0.05))

    assert allowed is False
    assert not caplog.records, "nobody answering is not a failure"
```

(Check `ConfirmRequest`'s required fields in `mcp_server.py` and fill them as the existing tests do.)

`tests/test_tuning_session.py`:

```python
def test_a_failed_confirmation_in_the_sdk_session_is_logged(tmp_path, caplog):
    import logging

    from autosound_tcc.core import app_log

    session, arbiter = _session(tmp_path, allow=True)

    def broken(request):
        raise RuntimeError("boom")

    arbiter.request_confirmation = broken
    with caplog.at_level(logging.WARNING, logger=app_log.LOGGER_NAME):
        behavior = _decide(session, "Bash", {"command": "touch x"})

    assert behavior == "deny"
    assert any("boom" in r.getMessage() for r in caplog.records)
```

`tests/test_omp_session.py`:

```python
def test_a_failed_confirmation_in_the_omp_session_is_logged_and_denies(tmp_path, caplog):
    import logging

    from autosound_tcc.core import app_log

    session = _session(tmp_path, allow=True)

    def broken(request):
        raise RuntimeError("boom")

    session.bridge.request_confirmation = broken
    with caplog.at_level(logging.WARNING, logger=app_log.LOGGER_NAME):
        asyncio.run(session._gate(PERMISSION_FRAME))

    assert session.sent == [{"type": "extension_ui_response", "id": "f1", "value": "Deny"}]
    assert any("boom" in r.getMessage() for r in caplog.records)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/test_mcp_server.py tests/test_tuning_session.py tests/test_omp_session.py -k "failed_confirmation or unanswered_confirmation" -q`
Expected: FAIL — `await_confirmation` does not exist; the two sessions deny with nothing logged. If `_decide`'s
command reaches the allowlist instead of `_ask`, pick a command the allowlist refuses (see the parametrized cases
at the top of the file).

- [ ] **Step 3: Implement**

`mcp_server.py`, beside `CONFIRM_TIMEOUT_S`:

```python
async def await_confirmation(bridge: "UiBridge", request: ConfirmRequest, timeout_s: float) -> bool:
    """The Arbiter's answer to `request`, False when there is none.

    A timeout is a denial: nobody answered. A failure is a denial too — the gate stays shut — but it
    is logged with what failed (F3e): three places asked this way and swallowed the failure as a plain
    «no», so a broken confirmation bar read as the Arbiter refusing everything."""
    try:
        return bool(await asyncio.wait_for(
            asyncio.wrap_future(bridge.request_confirmation(request)), timeout=timeout_s))
    except asyncio.TimeoutError:
        return False
    except Exception as exc:  # noqa: BLE001 — any failure is a denial, said in the log
        app_log.logger().warning("confirmation for %s failed, read as a denial: %s: %s",
                                 request.tool, type(exc).__name__, exc)
        return False
```

(`UiBridge` is defined later in the module: the quoted annotation is enough; import `asyncio` at the top if it is
not.) `_confirm` becomes `return await await_confirmation(bridge, request, CONFIRM_TIMEOUT_S)`.

`tuning_session.py`: import `await_confirmation` in the existing `from autosound_tcc.core.mcp_server import …` line;
in `_ask` replace the `try/except` with `allowed = await await_confirmation(self.bridge, request, timeout_s=600.0)`.

`omp_session.py`: the same import; in `_gate` replace the `try/except` with
`allowed = await await_confirmation(self.bridge, request, CONFIRM_TIMEOUT_S)`.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_mcp_server.py tests/test_tuning_session.py tests/test_omp_session.py -q -n 4` — PASS.

- [ ] **Step 5: Commit** — `#157 F3e: a failed confirmation is logged and stays a denial, in one helper`

### Task 6 · #154 F3a — the turn after omp died says so instead of waiting forever

The reader puts `None` and sets `_ended` at EOF. The turn running then returns silently; the next `_prompt` writes
to the dead process and waits on a queue nothing fills, saying only «…s with no output» every two minutes. A close
cancels the reader, so `None` and `_ended` come only from a real EOF — a notice on them is never a false alarm.

**Files:**
- Modify: `src/autosound_tcc/core/omp_session.py` — `_prompt` (~1054), a new `_ended_notice`.
- Test: `tests/test_omp_session.py`.

**Interfaces:**
- Produces: `OmpSession._ended_notice() -> Notice` whose text contains «omp has stopped» and omp's stderr tail
  (`_why`).

- [ ] **Step 1: Write the failing tests**

```python
def test_the_turn_after_omp_died_says_so_instead_of_waiting(tmp_path):
    """F3a: the reader saw EOF, and the next prompt went to the dead process and waited on a queue
    nothing would fill, saying only «no output» every two minutes."""
    from types import SimpleNamespace

    from autosound_tcc.core.agent_events import Notice

    session = _session(tmp_path)

    async def run():
        reader = asyncio.StreamReader()
        reader.feed_eof()  # omp is gone
        session._proc = SimpleNamespace(stdout=reader, stdin=None)
        await session._read_frames()
        while not session._events.empty():  # the turn that was running took its None
            session._events.get_nowait()
        turn = session._prompt("next?")
        return await asyncio.wait_for(turn.__anext__(), timeout=2.0)

    first = asyncio.run(run())
    assert isinstance(first, Notice)
    assert "no output" not in first.text, "the silence notice is not the answer"
    assert "omp has stopped" in first.text
    assert session.sent == [], "nothing is written to a process that is gone"


def test_omp_ending_mid_turn_ends_the_turn_out_loud(tmp_path):
    from autosound_tcc.core.agent_events import Notice

    session = _session(tmp_path)

    async def run():
        turn = session._prompt("go")
        session._events.put_nowait(None)  # the reader's EOF, mid-turn
        return await asyncio.wait_for(_collect(turn), timeout=2.0)

    async def _collect(turn):
        return [event async for event in turn]

    events = asyncio.run(run())
    assert isinstance(events[-1], Notice) and "omp has stopped" in events[-1].text
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/test_omp_session.py -k "omp_died or ending_mid_turn" -q`
Expected: the first FAILS on `asyncio.TimeoutError` (it waits), the second with an empty event list.

- [ ] **Step 3: Implement**

```python
    def _ended_notice(self) -> Notice:
        """What a turn says when omp is gone (F3a): the next prompt went to the dead process and
        waited on a queue nothing would fill, saying only «no output» every two minutes."""
        return Notice(self._why("omp has stopped, so this session cannot go on. Start a new session."))
```

In `_prompt`, before `self._send(...)` (after the three resets at the top):

```python
        if self._ended.is_set():
            yield self._ended_notice()
            return
```

and in the loop replace `if event is None:  # process ended mid-turn` / `return` with:

```python
                if event is None:  # process ended mid-turn
                    yield self._ended_notice()
                    return
```

(`Notice` is already imported in `omp_session.py`; check.)

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_omp_session.py -q -n 4` — PASS.

- [ ] **Step 5: Commit** — `#154 F3a: the turn after omp stopped says so instead of waiting forever`

### Task 7 · #155 F3b — an SDK result that ended in error is said

`TuningSession._drain` reads every `ResultMessage` as a normal end, `is_error=True` included.

**Files:**
- Modify: `src/autosound_tcc/core/tuning_session.py` — add `Notice` to the `agent_events` import (~27); a module
  function `_result_error_text`; `_drain` (~425).
- Test: `tests/test_tuning_session.py`.

**Interfaces:**
- Produces: `tuning_session._result_error_text(result) -> str` — «The session reported an error: …» with the
  result's `errors` joined by «; », else its `result` text, else its `subtype`.

- [ ] **Step 1: Write the failing test**

```python
def test_an_sdk_result_that_ended_in_error_is_said(tmp_path):
    """F3b: a ResultMessage with is_error=True was read as a normal end, so a turn the SDK failed
    looked finished and said nothing. A real SDK type, so the field names are the SDK's."""
    from claude_agent_sdk import ResultMessage

    from autosound_tcc.core import claude_sdk
    from autosound_tcc.core import tuning_session as ts
    from autosound_tcc.core.agent_events import Notice, TurnEnd

    claude_sdk.bind(ts.SDK_NAMES, vars(ts))
    failed = ResultMessage(subtype="error_during_execution", duration_ms=1, duration_api_ms=1,
                           is_error=True, num_turns=1, session_id="s-1", errors=["x"])

    class _Failing(_RecordingClient):
        async def receive_response(self):
            yield failed

    session = _live_session(tmp_path)
    session._client = _Failing()

    events = _run_turn(session, "go")

    assert isinstance(events[-2], Notice) and "x" in events[-2].text
    assert isinstance(events[-1], TurnEnd) and events[-1].session_id == "s-1"
```

- [ ] **Step 2: Run it and watch it fail** — `.venv/bin/python -m pytest tests/test_tuning_session.py -k ended_in_error -q`; expected FAIL: the last-but-one event is not a Notice.

- [ ] **Step 3: Implement**

```python
def _result_error_text(result: Any) -> str:
    """What an SDK result that ended in error says (F3b)."""
    said = [str(e) for e in (getattr(result, "errors", None) or []) if str(e).strip()]
    if not said and getattr(result, "result", None):
        said = [str(result.result)]
    detail = "; ".join(said) or str(getattr(result, "subtype", "") or "no reason given")
    return f"The session reported an error: {detail}"
```

In `_drain`:

```python
                if isinstance(message, ResultMessage):
                    self._remember_session(message)
                    if getattr(message, "is_error", False):
                        yield Notice(_result_error_text(message))
                    yield TurnEnd(session_id=message.session_id)
                    return
```

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_tuning_session.py -q -n 4` — PASS.

- [ ] **Step 5: Commit** — `#155 F3b: an SDK result that ended in error is said, not read as a normal end`

### Task 8 · #158 F16-1 — the critic and the updater's children are bounded on Windows

`critic.run` (~574), `critic.doctor` (~970) and `updates._run_upkeep` (~931) call `subprocess.run`. On Windows,
at the timeout, that kills the one process and then waits in `communicate()` with no bound for pipes a grandchild
holds (tcc#132). `child.run_bounded` is the fix the rest of TCC already uses.

**Files:**
- Modify: `src/autosound_tcc/core/critic.py`, `src/autosound_tcc/core/updates.py`.
- Modify: `tests/test_critic.py` — the ~10 tests that patch `critic.subprocess.run` patch `critic.child.run_bounded`
  instead (same `capture(_argv, **kwargs)` signature; `env`, `cwd` and `timeout` keep their names).
- Test: `tests/test_critic.py`, `tests/test_updates.py`.

**Interfaces:**
- Consumes: `child.run_bounded(args, *, timeout, input=None, register=None, **popen_kwargs) -> CompletedProcess` —
  output always captured; no `capture_output=` or `check=`; raises `subprocess.TimeoutExpired` as `run` does.

- [ ] **Step 1: Write the failing tests**

`tests/test_critic.py`:

```python
def _reviewer_ready(monkeypatch, tmp_path):
    from autosound_tcc.core import critic

    monkeypatch.setattr(critic, "is_available", lambda: True)
    monkeypatch.setattr(critic, "preflight", lambda _p=None: [])
    monkeypatch.setattr(critic, "script_path", lambda: tmp_path / "autosound_ai.py")
    monkeypatch.setattr(critic.shutil, "which", lambda name: f"/usr/bin/{name}")
    return critic


def test_a_reviewer_that_never_answers_is_killed_on_windows(tmp_path, monkeypatch):
    """F16-1: the reviewer's call was one of three left on `subprocess.run`, which on Windows waits
    with no bound for pipes a grandchild holds (tcc#132)."""
    from tests import _hung_child

    critic = _reviewer_ready(monkeypatch, tmp_path)
    spawns = _hung_child.install(monkeypatch)

    result = critic.run("a package", project_dir=tmp_path, role="ask", harness="agy", timeout_s=1)

    assert result.mode == critic.MODE_ERROR and "timed out" in result.detail
    assert spawns.hung and all(child.killed for child in spawns.hung)


def test_the_reviewer_doctor_is_bounded_on_windows(tmp_path, monkeypatch):
    from tests import _hung_child

    critic = _reviewer_ready(monkeypatch, tmp_path)
    spawns = _hung_child.install(monkeypatch)

    said = critic.doctor(tmp_path, python_executable="python")

    assert said.startswith("doctor failed")
    assert spawns.hung and all(child.killed for child in spawns.hung)
```

`tests/test_updates.py` (beside the other `_hung_child` tests, ~1950):

```python
def test_an_upkeep_run_that_never_answers_is_bounded_on_windows(monkeypatch):
    spawns = _hung_child.install(monkeypatch)

    code, out, err = updates._run_upkeep(["python", "upkeep.py", "--json", "libs"], timeout=1)

    assert code == -1 and out == "" and err.startswith("TimeoutExpired")
    assert spawns.hung and all(child.killed for child in spawns.hung)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/test_critic.py tests/test_updates.py -k "reviewer_that_never_answers or doctor_is_bounded or upkeep_run_that_never" -q`
Expected: ERROR `WaitedForever` in all three (it is a `BaseException`, nothing swallows it).

- [ ] **Step 3: Implement**

`critic.run`:

```python
        proc = child.run_bounded(
            argv, timeout=timeout_s, cwd=str(project_dir), env=env,
            text=True, encoding="utf-8", errors="replace", **child.quiet())
```

`critic.doctor`:

```python
        proc = child.run_bounded(
            [python_executable, str(script_path()), "doctor"], timeout=60,
            cwd=str(project_dir), text=True, encoding="utf-8", errors="replace",
            env=vendor_loader.child_env(**critic_bin_override()),  # TCC-002, as above
            **child.quiet(),
        )
```

`updates._run_upkeep`:

```python
        done = child.run_bounded(
            argv, timeout=timeout, text=True, encoding="utf-8", errors="replace",
            env=vendor_loader.child_env(**_NO_PROMPTING), **child.quiet())
```

The `except` clauses stay as they are. Then move the `critic.subprocess.run` patches in `tests/test_critic.py` to
`critic.child.run_bounded`.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_critic.py tests/test_updates.py tests/test_child.py -q -n 4` — PASS.

- [ ] **Step 5: Commit** — `#158 F16-1: the critic and the updater's children are bounded on Windows`

### Task 9 · #159 F16-5 — the helpers that «never raise» do not raise on a file of the wrong shape

`contract_check.report_from_json` is the last call of `run`, which «never raises», and it calls `.get` on whatever
`json.loads` gave. `mcp_server.forget_mcp_config` («never raises — this runs on the way out») and
`write_mcp_config` call `.get` / `.setdefault` on `.mcp.json`'s content; `write_mcp_config` is wrapped in
`except OSError` inside `start()`, so an `AttributeError` there takes the MCP server down — the 2026-09-06 class.

**Files:**
- Modify: `src/autosound_tcc/core/contract_check.py` (`report_from_json`, ~245),
  `src/autosound_tcc/core/mcp_server.py` (`forget_mcp_config` ~1600, `write_mcp_config` ~1626).
- Test: `tests/test_contract_check.py`, `tests/test_mcp_server.py`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("report", [[], None, "x", 3])
def test_a_report_that_is_not_an_object_is_no_report(report):
    """F16-5: `run` never raises, and this is the last thing it calls."""
    from autosound_tcc.core import contract_check

    out = contract_check.report_from_json(report, "/p", "now", 0.1)

    assert not out.ok and out.error and out.files == ()


def test_a_report_field_of_the_wrong_shape_is_read_as_empty():
    from autosound_tcc.core import contract_check

    out = contract_check.report_from_json(
        {"ok": True, "files": 3, "inherited": 5, "cross_checks": [], "sources_gone": 7},
        "/p", "now", 0.1)

    assert out.ok and out.error == ""
    assert out.files == () and out.inherited == () and out.cross_checks == {}
    assert out.sources_gone == ()
```

`tests/test_mcp_server.py`:

```python
@pytest.mark.parametrize("text", ["[]", "null", "3", '{"mcpServers": []}'])
def test_an_mcp_json_of_the_wrong_shape_neither_raises_nor_stops_the_server(tmp_path, text):
    """F16-5: `forget_mcp_config` never raises; `write_mcp_config` raising anything but OSError
    escaped `start()` and took the server down with it."""
    path = config.mcp_config_path(tmp_path)
    path.write_text(text, encoding="utf-8")

    mcp_server.forget_mcp_config(tmp_path)
    write_mcp_config(tmp_path, 8765, "tok")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"][mcp_server.SERVER_NAME]["url"] == "http://127.0.0.1:8765/mcp"
```

(use the module's existing imports of `config`, `json`, `mcp_server`, `write_mcp_config`; add what is missing.)

- [ ] **Step 2: Run them and watch them fail** — `AttributeError` / `TypeError` in every case.

- [ ] **Step 3: Implement**

`report_from_json`:

```python
def report_from_json(report: Any, project_dir, checked_at: str, duration_s: float) -> ContractReport:
    """`contract.py check --json`'s answer as a `ContractReport`. Never raises (F16-5): an answer
    that is not an object is a run that produced no report, and a field of the wrong shape reads as
    empty — `run` promises never to raise, and this is the last thing it calls."""
    if not isinstance(report, dict):
        return ContractReport(
            ok=False, project_dir=str(project_dir), checked_at=checked_at, duration_s=duration_s,
            error=f"contract.py answered with a JSON {type(report).__name__}, not an object")

    def rows(key: str) -> tuple:
        value = report.get(key)
        return tuple(row for row in value if isinstance(row, dict)) if isinstance(value, list) else ()

    cross, gone = report.get("cross_checks"), report.get("sources_gone")
    return ContractReport(
        ok=bool(report.get("ok")),
        project_dir=str(report.get("project_dir") or project_dir),
        files=rows("files"),
        cross_checks=cross if isinstance(cross, dict) else {},
        checked_at=checked_at,
        duration_s=duration_s,
        inherited=rows("inherited"),
        sources_gone=tuple(str(path) for path in gone) if isinstance(gone, list) else (),
        complete=bool(report.get("complete")),
    )
```

(import `Any` from `typing` if the module does not.)

`forget_mcp_config`, after the `json.loads` block: `if not isinstance(data, dict): return`.

`write_mcp_config`, after its `json.loads` block:

```python
    if not isinstance(data, dict):
        app_log.logger().warning("%s is not a JSON object; written anew with TCC's entry", path)
        data = {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        if servers is not None:
            app_log.logger().warning("%s: mcpServers is not an object; replaced", path)
        servers = data["mcpServers"] = {}
```

(this replaces `servers = data.setdefault("mcpServers", {})`).

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_contract_check.py tests/test_mcp_server.py -q -n 4` — PASS.

- [ ] **Step 5: Commit** — `#159 F16-5: report_from_json and the .mcp.json helpers do not raise on the wrong shape`

**Group review after Task 9 (controller):** `pr-review-toolkit:silent-failure-hunter` and
`pr-review-toolkit:pr-test-analyzer` on the diff of Tasks 4–9, then a final review on Fable (the omp/SDK async
paths and the confirmation gate are risky code); findings in one round of fixes.

---

## G13 · Step 0 (#160)

### Task 10 · #160 — a ratchet on `main_window.py`, and the signal-id parsing pinned

**Files:**
- Create: `tests/test_structure_ratchet.py`.
- Test: `tests/test_main_window.py` (the characterisation test).

- [ ] **Step 1: Measure** — after Tasks 1–9 are committed:

```bash
wc -l src/autosound_tcc/ui/tcc/main_window.py
grep -h -v '^\s*#' tests/test_*.py | grep -o 'MainWindow(' | wc -l
```

Write the two numbers into the constants below. (The second count is approximate on purpose — a comment at the end
of a line still counts; the module's own counter is the definition.)

- [ ] **Step 2: Write the ratchet**

```python
"""G13 step 0 (hub H-013): `main_window.py` may not grow, and each wave lowers the bound.

Progress is two numbers — the file's lines and the full windows the tests build. A decision pulled
out of the window into a Qt-free module (the `row_rule` precedent, F-091) lowers both: its window
tests become plain-function tests. A bound is lowered in the commit that shrinks the file, never
raised.

The next decisions to pull out — they live only on the window and are pinned by window tests:
`_capture_version` (tests ~2344-2393), `_effective_gate` (~1338-1384), the compare default, the
preset choice in `_load_project`, the «settled» verdict parsed from text, the signal ids parsed
from `unacked_brief` (pinned by `test_the_signal_nudge_reads_every_open_signals_id_from_the_brief`),
the reviewer's state, and the delay maths mirrored in `curve_view` (`delay_bank`, `curve_sum`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
WINDOW = ROOT / "src" / "autosound_tcc" / "ui" / "tcc" / "main_window.py"

#: Lowered by every wave that moves a decision out; never raised (W-8).
MAIN_WINDOW_MAX_LINES = 0  # ← the number measured in Step 1
#: `MainWindow(` in the tests, outside comments (W-8).
WINDOW_BUILDS_MAX = 0  # ← the number measured in Step 1


def lines_of(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def window_builds(folder: Path) -> int:
    count = 0
    for path in sorted(folder.glob("test_*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            count += line.split("#", 1)[0].count("MainWindow(")
    return count


def over(measured: int, bound: int, what: str) -> Optional[str]:
    if measured <= bound:
        return None
    return (f"{what}: {measured} > {bound}. Move a decision out of the window (the row_rule "
            "precedent) instead of adding to it; the bound is lowered, never raised.")


def test_main_window_does_not_grow():
    assert over(lines_of(WINDOW), MAIN_WINDOW_MAX_LINES, "main_window.py lines") is None


def test_the_tests_build_no_more_full_windows():
    assert over(window_builds(ROOT / "tests"), WINDOW_BUILDS_MAX, "full-window builds") is None


def test_the_ratchet_goes_red_past_its_bound(tmp_path):
    """Green by design, so shown failing: a file one line over, a build in code and not in a comment."""
    (tmp_path / "w.py").write_text("a\nb\nc\n", encoding="utf-8")
    (tmp_path / "test_x.py").write_text(
        "w = MainWindow()\n# MainWindow() in a comment\nx = MainWindow()  # and one here\n",
        encoding="utf-8")

    assert over(lines_of(tmp_path / "w.py"), 2, "w") is not None
    assert over(lines_of(tmp_path / "w.py"), 3, "w") is None
    assert window_builds(tmp_path) == 2
```

- [ ] **Step 3: Write the characterisation test** (`tests/test_main_window.py`)

```python
def test_the_signal_nudge_reads_every_open_signals_id_from_the_brief(tmp_path, monkeypatch):
    """Characterisation before the parsing leaves the window (G13 step 0, TA-8): the ids are read
    back out of `unacked_brief`'s text with `rsplit("id ")`. Pinned with a real bus and a payload
    that has «id » in it, so the extraction keeps exactly this behaviour."""
    from types import SimpleNamespace

    from autosound_tcc.core.signal_bus import CHANNEL_TOGGLE, SignalBus

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    bus = SignalBus(tmp_path)
    one = bus.push(CHANNEL_TOGGLE, group="rear", channel="r-L", on=False)
    two = bus.push(CHANNEL_TOGGLE, group="rear", channel="r-R", on=False, note="said id x")
    asked = []
    monkeypatch.setattr(window._dialog, "nudge_for_signals",
                        lambda count, prompt: asked.append(count) or True)
    window._mcp_server = SimpleNamespace(bus=bus)
    try:
        window._nudge_for_open_signals()
        assert asked == [2]
        assert window._nudged_signal_ids == {one.id, two.id}
        window._nudge_for_open_signals()
        assert asked == [2], "a signal already handed a turn gets no second one"
    finally:
        window._mcp_server = None
```

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_structure_ratchet.py tests/test_main_window.py -k "ratchet or full_windows or does_not_grow or signal_nudge" -q`
Expected: PASS (characterisation and ratchet are green by design; the go-red test proves the checker).
Then make it red once by hand — set `MAIN_WINDOW_MAX_LINES` one below the measure, see the failure message, put it
back — and say so in the report.

- [ ] **Step 5: Commit** — `#160 G13 step 0: a ratchet on main_window.py, and the signal-id parsing pinned`

---

## N2 · #164 — the skill's candidates through TCC's suite (the controller)

When the skill names a candidate tag on the bus (first its J1a and J4a): a scratch clone of tcc under
`hub/scratch/tcc/`, the submodule at the candidate; the boundary set with `-n 4`, then the whole suite once,
serially, the VM suspended; the answer on the skill's ticket with the command and its result. Known in advance: J4a
needs `tests/test_rew_api_shapes.py:54-67` to answer GET /filters (TCC's re-pin, W-9). No code in this wave.

## Order and cost

Tasks 1 → 10 by one builder at a time (Opus), each with its own task review; the two group reviews and the Fable
review where marked; then G13's seams on the Arbiter's choice; `CHANGELOG.md` and the version (v1.1.2) by the
controller; one PR from `wave-8` with the full CI; the full suite once before the PR. About 4 hours of build and
review for Tasks 1–10.
