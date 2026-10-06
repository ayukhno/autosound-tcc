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

**G13's three seams** (#161 menu registry, #162 strings per feature, #163 car source) went through three architects
(`hub:seam`); the Arbiter chose «Balance» on 2026-10-06, and their Tasks 11–18 are the section below Task 10. N2 (#164) is a standing test run the controller does when the skill names a
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

## G13 · The three seams (#161–#163) — the Arbiter's choice «Balance»

The Arbiter, 2026-10-06, chose the «Balance» design of three (`.superpowers/sdd/PLAN-W-8/arch-balance.md`, local; the
other two beside it). Each seam gets its whole mechanism now; only what the car package will touch moves, or what
proves the mechanism. The design's own check: after it, the car package (F-096) adds 0 lines to `main_window.py`,
`new_project_dialog.py` and `i18n.py`. Built after Task 10, in this order: B1, B2, A1, A2, A3, C1, C2, B3. Re-read line
numbers when you start — Tasks 1–10 move them.

Shared rules for Tasks 11–18 (on top of the Global Constraints):
- A module said to have "no Qt" is proven by a fresh-interpreter test, as `tests/test_setting_status.py:149-160` does
  (`_fresh(...)` printing the loaded `PySide6`/`shiboken6` modules, expecting `[]`).
- A guard that is green by design gets a test that shows it failing (the `test_packaging.py:106` pattern).
- Old private names that tests use keep working until the task that rewrites those tests.
- A string a user sees: uk and en by the builder; pl and de carry the English until the Advisor.

### Task 11 · #162 B1 — `i18n.assemble`, the `strings/` package, the lookup without Qt

**Files:** Modify `src/autosound_tcc/ui/tcc/i18n.py`. Create `src/autosound_tcc/ui/tcc/strings/__init__.py`. Test:
`tests/test_i18n_features.py` (new).

**Interfaces (produces):**
```python
# ui/tcc/strings/__init__.py — no module-level imports beyond the standard library
FEATURES: tuple[str, ...] = ()            # module names under this package, in join order (B3 adds "new_project")
def tables() -> list[tuple[str, dict[str, dict[str, str]]]]   # [(f"strings.{name}", module.STRINGS), …], imported at call time
# ui/tcc/i18n.py
_CORE: dict[Lang, dict[str, str]] = {…}   # the literal that is `T` today, renamed, unchanged
def assemble(core, tables) -> dict[Lang, dict[str, str]]
T = assemble(_CORE, strings.tables())     # core first, then FEATURES in order
```
`assemble` returns a new dict-of-dicts: every language of `core`, each with core's keys, then each table's rows. A
table row is `{key: {lang: text}}`. It raises `ValueError` naming the key and both owners (`"core"` or the table's name)
when a key is defined twice, and naming the key, the table and the language when a row lacks one of core's languages
or has a language core does not. `import shiboken6` moves from the top of `i18n.py` into `set_language`, its only user.

- [ ] **Step 1: failing tests** (`tests/test_i18n_features.py`)

```python
"""G13 B1: strings per feature, joined into one table; the lookup imports no Qt."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from autosound_tcc.ui.tcc import i18n

LANGS = ("en", "uk", "pl", "de")


def _core(**keys):
    return {lang: dict(keys) for lang in LANGS}


def test_a_key_in_core_and_a_table_is_refused_naming_both():
    with pytest.raises(ValueError) as caught:
        i18n.assemble(_core(a="A"), [("strings.demo", {"a": {lang: "x" for lang in LANGS}})])
    said = str(caught.value)
    assert "'a'" in said and "core" in said and "strings.demo" in said


def test_a_key_in_two_tables_is_refused_naming_both():
    row = {lang: "x" for lang in LANGS}
    with pytest.raises(ValueError) as caught:
        i18n.assemble(_core(), [("strings.one", {"b": row}), ("strings.two", {"b": row})])
    said = str(caught.value)
    assert "'b'" in said and "strings.one" in said and "strings.two" in said


def test_a_row_without_one_of_the_languages_is_refused():
    with pytest.raises(ValueError) as caught:
        i18n.assemble(_core(), [("strings.demo", {"c": {"en": "C", "uk": "C", "pl": "C"}})])
    assert "'c'" in str(caught.value) and "de" in str(caught.value)


def test_a_table_s_rows_reach_every_language():
    out = i18n.assemble(_core(a="A"), [("strings.demo", {"d": {"en": "D", "uk": "Д", "pl": "D", "de": "D"}})])
    assert out["uk"]["d"] == "Д" and out["en"]["a"] == "A" and set(out) == set(LANGS)


def test_the_table_the_app_uses_is_the_join():
    assert i18n.T == i18n.assemble(i18n._CORE, i18n.strings.tables())


def _fresh(code: str) -> str:
    done = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output=True,
                          text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_the_lookup_imports_no_qt():
    loaded = _fresh("""
        import sys
        from autosound_tcc.ui.tcc import i18n
        i18n.t("npCancel")
        print(sorted(m for m in sys.modules if m.split(".")[0] in ("PySide6", "shiboken6")))
    """)
    assert loaded == "[]"
```

- [ ] **Step 2:** run `.venv/bin/python -m pytest tests/test_i18n_features.py -q` — FAIL (`assemble` missing; shiboken6 loaded).
- [ ] **Step 3:** implement as above (the `strings` import in `i18n.py` sits with the other imports at the top).
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_i18n_features.py tests/test_i18n_languages.py tests/test_labels.py tests/test_project_repo.py -q -n 4` — PASS.
- [ ] **Step 5:** commit — `#162 G13 B1: strings per feature join one table, and the lookup imports no Qt`

### Task 12 · #162 B2 — every literal key the UI names exists

**Files:** Create `tests/test_i18n_keys.py`. Fix any missing keys it finds (in `i18n.py`, en + uk; pl/de English).

**Interfaces (produces, in the test module):** `literal_keys(source: str) -> set[str]` — every string constant passed
as the first argument to `i18n.t(...)`, including both branches of a conditional expression there
(`i18n.t("a" if x else "b")`); a key built at run time (a variable, an f-string, `+`) is not a literal and is skipped.

- [ ] **Step 1: failing test that shows the guard can fail**

```python
"""G13 B2: a key typed wrong shows on screen as the raw key, and nothing caught it."""

from __future__ import annotations

import ast
from pathlib import Path

from autosound_tcc.ui.tcc import i18n

UI = Path(__file__).resolve().parents[1] / "src" / "autosound_tcc" / "ui"


def literal_keys(source: str) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and node.args and isinstance(node.func, ast.Attribute)
                and node.func.attr == "t" and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "i18n"):
            continue
        arg = node.args[0]
        branches = [arg.body, arg.orelse] if isinstance(arg, ast.IfExp) else [arg]
        keys |= {b.value for b in branches if isinstance(b, ast.Constant) and isinstance(b.value, str)}
    return keys


def test_the_key_guard_goes_red_on_a_typo():
    source = ('i18n.t("npCancel")\n'
              'i18n.t("noSuchKeyAnywhere")\n'
              'i18n.t("npCreate" if ok else "noSuchOtherKey")\n'
              'i18n.t(name)\n')
    assert literal_keys(source) - set(i18n.T["en"]) == {"noSuchKeyAnywhere", "noSuchOtherKey"}


def test_every_literal_key_the_ui_names_exists():
    missing = {}
    for path in sorted(UI.rglob("*.py")):
        lost = literal_keys(path.read_text(encoding="utf-8")) - set(i18n.T["en"])
        if lost:
            missing[path.relative_to(UI).as_posix()] = sorted(lost)
    assert not missing, missing
```

- [ ] **Step 2:** run it. The first test passes (it proves the checker); the second either passes or names keys that
  are raw on screen today. Each one found is a finding: fix it (a typo → the right key; a key never added → add it,
  en + uk written, pl/de the English) and name every one in the report with its file:line.
- [ ] **Step 3:** `.venv/bin/python -m pytest tests/test_i18n_keys.py tests/test_i18n_languages.py -q` — PASS.
- [ ] **Step 4:** commit — `#162 G13 B2: every key the UI names exists` (+ the keys fixed, in the body).

### Task 13 · #161 A1 — the menu as data: `menu_registry.py`

**Files:** Create `src/autosound_tcc/ui/tcc/menu_registry.py` (no Qt). Test: `tests/test_menu_registry.py` (new); extend
the existing menu test in `tests/test_main_window.py` (the one that checks headings and every key, ~:3583) first.

**Interfaces (produces):**
```python
@dataclass(frozen=True)
class MenuEntry:
    id: str; place: str                  # a SECTIONS id, or the id of a submenu entry
    label_key: str = ""; label: str = ""; tip_key: str = ""; prefix: str = ""   # prefix e.g. "⚙ ", "📖 "
    on: Callable[[Any], None] | None = None        # receives the host (the window), never Qt's `checked`
    url: Callable[[], str] | None = None           # opened in the browser instead of `on`
    enabled: Callable[[Any], bool] | None = None
    checked: Callable[[Any], bool] | None = None   # set → the line is checkable
    submenu: bool = False; bold: bool = False
    before: str = ""; after: str = ""              # an anchor: another entry's id in the same place
    alias: str = ""; alias_key: str = ""           # the window attribute tests use; a dict entry when alias_key is set
SECTIONS: tuple[tuple[str, str], ...] = (("project", "menuProject"), ("session", "menuSession"),
                                         ("tools", "menuTools"), ("help", "menuHelp"))
PROVIDERS: tuple[str, ...] = ()           # module names exposing menu_entries() -> list[MenuEntry]
SPONSORS_URL: str; MONOBANK_URL: str     # moved from main_window.py with their comments
def window_entries() -> list[MenuEntry]  # today's menu, in today's order, handlers as late-bound calls on the host
def collect() -> list[MenuEntry]         # window_entries() + every provider's, PROVIDERS read at call time
def ordered(entries, place: str) -> list[MenuEntry]   # registration order with anchors applied; an unknown anchor goes last
def problems(entries, known_keys) -> list[str]        # duplicate ids, unknown places or anchors, keys not in known_keys,
                                                      # an entry with neither on, url nor submenu
```
`window_entries()` is a transcription of `_build_main_menu`: every `addAction` / `addMenu` / heading becomes one entry in
the same order, with the same keys, prefixes, tips, checkable state and `bold`; each `triggered.connect(...)` becomes
`on=lambda w: w.<the same method>(<the same arguments>)` (late-bound, so a test that patches a window method still
wins); the gate, EQ-order and language submenus become entries with `checked`; Settings stays a bold submenu placed last
in TOOLS; the Guides submenu keeps its order and URLs. Nothing in `main_window.py` changes in this task.

- [ ] **Step 1: pin today's menu.** Extend the existing headings-and-keys menu test in `tests/test_main_window.py` so it
  walks the whole tree (sections, entries, submenus, separators) and compares it with a list of
  `(depth, kind, key-or-text, checkable, bold)` rows written out in the test. It passes on today's code and adds no
  window build. This pin is what Task 15 must keep green.
- [ ] **Step 2: failing registry tests** (`tests/test_menu_registry.py`), among them:

```python
class _Recorder:
    """A host that writes down which window method an entry calls, and with what."""
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args, **kwargs: self.calls.append((name, args, kwargs))


def _entry(entry_id):
    return next(e for e in menu_registry.window_entries() if e.id == entry_id)


def test_copy_the_car_asks_for_a_seeded_dialog():
    host = _Recorder()
    _entry("copy_car").on(host)
    _entry("new_project").on(host)
    assert host.calls == [("_open_new_project_dialog", (), {"seed": True}),
                          ("_open_new_project_dialog", (), {})]


def test_the_window_s_menu_has_no_problems():
    assert menu_registry.problems(menu_registry.collect(), set(i18n.T["en"])) == []


def test_every_entry_calls_a_method_the_window_has():
    from autosound_tcc.ui.tcc.main_window import MainWindow
    for entry in menu_registry.window_entries():
        if entry.on is not None:
            host = _Recorder()
            entry.on(host)
            assert all(hasattr(MainWindow, name) for name, _a, _k in host.calls), entry.id


def test_an_anchor_puts_an_entry_right_before_its_neighbour():
    entries = [MenuEntry("a", "project", label="A", on=print), MenuEntry("b", "project", label="B", on=print),
               MenuEntry("x", "project", label="X", on=print, before="b")]
    assert [e.id for e in menu_registry.ordered(entries, "project")] == ["a", "x", "b"]


def test_problems_name_a_duplicate_id_an_unknown_place_and_a_missing_key():
    entries = [MenuEntry("a", "project", label_key="npCancel", on=print),
               MenuEntry("a", "nowhere", label_key="noSuchKey", on=print)]
    said = " ".join(menu_registry.problems(entries, set(i18n.T["en"])))
    assert "'a'" in said and "nowhere" in said and "noSuchKey" in said
```
(Use the real entry ids your transcription gives the copy and new-project lines; `copy_car` / `new_project` if free.)
Plus a fresh-interpreter test that `menu_registry` loads no Qt.

- [ ] **Step 3:** implement; **Step 4:** run `tests/test_menu_registry.py` and the extended window menu test — PASS.
- [ ] **Step 5:** commit — `#161 G13 A1: the menu as data, today's entries transcribed and pinned`

### Task 14 · #161 A2 — one renderer: `main_menu.py`

**Files:** Create `src/autosound_tcc/ui/tcc/main_menu.py`. Test: `tests/test_main_menu.py` (new).

**Interfaces (produces):**
```python
def tip_menu(parent) -> QMenu            # today's `_tip_menu`: class "support-menu", hover tips, tip hidden on hide
def show_action_tip(action) -> None      # today's `_show_action_tip`
def add_heading(menu, text) -> None      # today's `_menu_section`: a disabled upper-case action
class MainMenu:
    def __init__(self, button: QToolButton, host, entries: Callable[[], list[MenuEntry]] | None = None)  # default collect
    def render(self) -> QMenu   # builds the tree, button.setMenu(new), old.deleteLater(), sets the aliases, then sync()
    def sync(self) -> None      # re-asks every `enabled` and `checked` predicate
    def action(self, entry_id: str) -> QAction | None
```
Every line connects `triggered` (never `toggled`) as `lambda _checked=False, e=entry: self._fire(e)`; `_fire` calls
`e.on(host)` or opens `e.url()`. Aliases: `render()` sets `host.<alias>` (or `host.<alias>[alias_key]`, the dict reset
first so its order is the render order).

- [ ] **Step 1: failing tests** on a bare `QToolButton` with a small host object (no `MainWindow`):
  `test_a_handler_never_receives_qts_checked_flag` (a checkable entry and a plain one; trigger both; the host's
  handler was called with the host only), `test_a_render_from_inside_an_entry_defers_the_old_menu` (an entry whose `on`
  calls `render()` again; trigger it; process the deferred delete; no RuntimeError; `button.menu()` is the new menu),
  `test_sync_re_asks_enabled_and_checked`, `test_headings_are_disabled_upper_case_lines`,
  `test_render_sets_the_aliases_the_tests_use`.
- [ ] **Steps 2–4:** RED, implement, GREEN (`tests/test_main_menu.py`).
- [ ] **Step 5:** commit — `#161 G13 A2: one menu renderer, handlers never see Qt's checked flag`

### Task 15 · #161 A3 — the window renders the registry

**Files:** Modify `src/autosound_tcc/ui/tcc/main_window.py` (delete `_build_main_menu`'s body, `_tip_menu`,
`_build_eq_order_menu`, `_menu_section`, `_show_action_tip`; `_sync_menu_state`'s body becomes
`self._main_menu.sync()`, its four call sites unchanged; the loop in `_set_eq_order_pref` becomes
`self._sync_menu_state()`; the footer's coffee popup uses `main_menu.tip_menu`). Modify `tests/test_main_window.py`,
`tests/test_structure_ratchet.py`.

- [ ] **Step 1: failing test** — the successor of the menu pin: a fake provider module put in `sys.modules` and named in
  `menu_registry.PROVIDERS` (monkeypatched) whose entry has `before=` the intake entry's id; the window's menu shows it
  right before Intake, and otherwise the tree equals the Task 13 pin.
- [ ] **Step 2:** switch the window to `self._main_menu = MainMenu(self._menu_btn, self)` and `render()`; delete the
  old code.
- [ ] **Step 3:** rewrite as plain or renderer tests (no `MainWindow()`): the save/fresh-disabled test (~:1408), the
  tooltip test (~:1454), the New-project label test (~:3544), the Guides test (~:3627), the menu half of the
  Copy-the-car test (~:3717; its dialog half stays, without its window build); the pin becomes a plain list over
  `window_entries()` plus the one window test from Step 1. The gate tests (~:1761, ~:1786), reload (~:3500), import
  (~:3564), language (~:3695), feedback (~:3766), EQ-order (~:6452) and `tests/test_intake_window.py:52-65` stay
  unchanged — the aliases carry them. After the rewrites the alias list is exactly `_intake_action`, `_reload_action`,
  `_import_action`, `_gate_actions`, `_eq_order_actions`; a test pins that list.
- [ ] **Step 4:** measure and lower both bounds in `tests/test_structure_ratchet.py` to the new numbers in this commit.
- [ ] **Step 5:** `.venv/bin/python -m pytest tests/test_main_window.py -k "menu or gate or reload or import or guide or copy or feedback or eq_order or tip or language" tests/test_main_menu.py tests/test_menu_registry.py tests/test_intake_window.py tests/test_structure_ratchet.py tests/test_control_layout.py -q -n 4` — PASS.
- [ ] **Step 6:** commit — `#161 G13 A3: the window renders the menu registry` (lines before → after in the body).

### Task 16 · #163 C1 — the car source as an interface: `car_source.py`

**Files:** Create `src/autosound_tcc/ui/tcc/car_source.py` (no Qt). Test: `tests/test_car_source.py` (new).

**Interfaces (produces):**
```python
@dataclass(frozen=True)
class Line:                      # an untranslated sentence: the dialog translates it
    key: str
    args: Mapping[str, object] = field(default_factory=dict)
@dataclass(frozen=True)
class Resolved:
    folder: Path | None
    problem: Line | None = None
    about: tuple[Line, ...] = ()
    warnings: tuple[Line, ...] = ()
@dataclass(frozen=True)
class Chooser:
    kind: str                    # "folder" | "file"
    label_key: str; title_key: str; filter_key: str = ""
class CarSource(Protocol):
    chooser: Chooser
    def accepts(self, path: Path) -> bool: ...
    def resolve(self, path: Path) -> Resolved: ...
    def release(self) -> None: ...
class FolderSource:              # Chooser("folder", "npBrowse", "npSeedFrom"); accepts: not path.is_file();
                                 # resolve → Resolved(path); release: nothing
SOURCES: tuple[type, ...] = (FolderSource,)   # sources take disjoint inputs; also the browse buttons' order
class Picker:
    def __init__(self, sources=None) -> None  # reads SOURCES at call time when None, so tests can monkeypatch it
    def resolve(self, text: str) -> Resolved | None   # None for blank text; memo per expanded path; resolving a new
                                                      # path releases the previous source
    def release(self) -> None
```
No source accepts the input → `Resolved(None, problem=Line("npSeedNotAProject"))`, the sentence a file gets today.

- [ ] **Step 1: failing tests:** `test_the_same_path_is_resolved_once_and_released_on_change` (a counting fake source;
  resolve the same text twice → one resolve; a new text → the first released), `test_a_folder_and_a_path_not_made_yet_are_folders`,
  `test_a_file_no_source_takes_is_refused_as_not_a_project`, `test_blank_text_resolves_to_nothing`, and a
  fresh-interpreter test that `car_source` loads no Qt.
- [ ] **Steps 2–4:** RED, implement, GREEN.
- [ ] **Step 5:** commit — `#163 G13 C1: the car source as an interface, the folder its first`

### Task 17 · #163 C2 — the new-project dialog goes through the picker

**Files:** Modify `src/autosound_tcc/ui/tcc/new_project_dialog.py`. Test: `tests/test_new_project_dialog.py`.

Changes: `self._picker = car_source.Picker()`; one Browse button per source in the seed row (`self._seed_browse` stays
the first one); `_on_browse_seed` becomes `_on_browse_source(chooser)` (a folder or a file dialog by `chooser.kind`,
titled `t(chooser.title_key)`, filtered by `t(chooser.filter_key)`); `_seed_source()` keeps returning
`Optional[Path]` (the resolved folder); `_on_seed_source` shows `problem` as the warning it shows today;
`_refresh_seed_note_now` adds `about` under the summary and `warnings` last; `_on_create` refuses while there is a
`problem`; `done()` calls `self._picker.release()`. Untouched: `npd._seeder`, the `(parent, seed_first=)` constructor,
the public attributes, every private widget the 27 tests use, `_would_travel`'s `(report, fs)`.

- [ ] **Step 1: failing test** `test_a_second_source_needs_no_dialog_code`: a fake file source monkeypatched into
  `car_source.SOURCES` (accepts files; resolves to a tmp folder with `about=(Line("npSeedTravels"),)` and
  `warnings=(Line("npSeedNoChannels"),)`; counts releases; a second fake path it refuses with
  `problem=Line("npSeedFailed")`). Assert: a second browse button exists; typing the accepted file shows the about line
  under the summary and the warning last; the refused one shows the problem and Create does not create a project;
  closing the dialog releases what was held.
- [ ] **Steps 2–4:** RED, implement, GREEN: `.venv/bin/python -m pytest tests/test_new_project_dialog.py tests/test_intake_window.py tests/test_car_source.py -q -n 4`.
- [ ] **Step 5:** commit — `#163 G13 C2: the new-project dialog copies a car through the source picker`

### Task 18 · #162 B3 — the new-project strings live beside their dialog

**Files:** Create `src/autosound_tcc/ui/tcc/strings/new_project.py`; modify `strings/__init__.py`
(`FEATURES = ("new_project",)`), `i18n.py` (the keys leave `_CORE`). Test: `tests/test_i18n_features.py`.

The 39 `np*` keys of today's table move, every language and every comment with them: all of `np*` except `npBrowse`
and `npCancel`, which six dialogs share and which stay in `_CORE`. The module is plain data that imports nothing:
`STRINGS = {"npTitle": {"en": …, "uk": …, "pl": …, "de": …}, …}`, one row per key.

- [ ] **Step 1: failing tests:** `test_the_copy_strings_live_with_their_feature` (`"npSeedSummary"` in
  `strings.new_project.STRINGS`, not in `i18n._CORE["en"]`; `"npCancel"` still in `_CORE["en"]`),
  `test_every_strings_module_is_joined` (the `.py` files of the package minus `__init__` == `FEATURES`),
  `test_a_strings_module_imports_nothing` (AST: no `Import`/`ImportFrom` in any feature module) with its go-red twin on
  a tmp file.
- [ ] **Step 2:** before moving, record `hashlib.sha256(json.dumps(i18n.T, sort_keys=True, ensure_ascii=False).encode()).hexdigest()`;
  move the keys with a script (not by hand); record the hash after. They must be equal; both go in the report.
- [ ] **Step 3:** `.venv/bin/python -m pytest tests/test_i18n_features.py tests/test_i18n_languages.py tests/test_i18n_keys.py tests/test_new_project_dialog.py tests/test_labels.py -q -n 4` — PASS.
- [ ] **Step 4:** commit — `#162 G13 B3: the new-project strings live beside their dialog` (the two hashes in the body).

**Group review after Task 18 (controller):** `pr-review-toolkit:silent-failure-hunter` and
`pr-review-toolkit:pr-test-analyzer` on the diff of Tasks 11–18; findings in one round of fixes.

## N2 · #164 — the skill's candidates through TCC's suite (the controller)

When the skill names a candidate tag on the bus (first its J1a and J4a): a scratch clone of tcc under
`hub/scratch/tcc/`, the submodule at the candidate; the boundary set with `-n 4`, then the whole suite once,
serially, the VM suspended; the answer on the skill's ticket with the command and its result. Known in advance: J4a
needs `tests/test_rew_api_shapes.py:54-67` to answer GET /filters (TCC's re-pin, W-9). No code in this wave.

## Order and cost

Tasks 1 → 18 by one builder at a time (Opus), each with its own task review; the three group reviews and the Fable
review where marked; `CHANGELOG.md` and the version (v1.1.2) by the
controller; one PR from `wave-8` with the full CI; the full suite once before the PR. About 4 hours of build and
review for Tasks 1–10, and about 19 for Tasks 11–18.
