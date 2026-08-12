# Audit: built and not reachable

> **Verification pass (Opus, same night).** Fable-5 audit; all three findings were re-checked
> against the code. **All three reproduced**, and the second one turned out to have already fired
> on this machine.
>
> | # | claim | independently reproduced |
> |---|---|---|
> | 1 | `SELECTION` / `NOTE` signal kinds have no producer | ✅ the only `push()` calls in the tree are `CHANNEL_TOGGLE` ×1, `NOT_VISIBLE` ×1, `PARAM_EDIT_MODE` ×2 — while `get_pending_signals`' docstring (`mcp_server.py:329-330`) promises the model "moving attention to another channel" |
> | 2 | `clear_alias` is unreachable | ✅ zero callers in `src/` or `tests/` |
> | 3 | finished uk strings that can never render | ✅ `detail_pane.py:185,206,307,427` and `measurement_panel._LEGEND` hard-code English while `tabTable`/`close`/`colChan`/`shared`/`noShared`/`band`/`legWait`/`legDone`/`legBad` all exist in **both** language tables |
>
> **Finding 2 is live on this machine, and it explains the rest of the reviewer story.**
> `~/.config/autosound-tcc/models.json` currently holds three aliases, all written by the
> "model gone" dialog, all pointing at the Generator's own model:
>
> ```
> agy:gemini-3.1-pro-high   → sdk:claude-opus-5   (2026-08-07)
> agy:gemini-3.1-pro-low    → sdk:claude-opus-5   (2026-08-07)
> agy:gemini-3.5-flash-high → sdk:claude-opus-5   (2026-08-11)
> ```
>
> The cause of their creation is fixed — the agy catalogue used to vanish on a slow launch, which
> made those stored keys unresolvable and raised the dialog (`7e1a97a`). The DAMAGE is not: picking
> any of those three reviewers still silently runs Claude, the footer's new "!" says so, and there
> is no control anywhere in the app that removes an alias. `clear_alias()` was written for exactly
> this and never wired to anything.
>
> Until it is, the remedy is manual: edit `~/.config/autosound-tcc/models.json` and delete the
> `aliases` entries.
>
> The report's own "verified dead, no symptom" section is worth reading rather than skipping:
> `ui/tcc/group_table.py` is a whole widget module with no importer — the same shape as the curve
> panel that sat unreachable for a day.


Scope: every Python module in `src/autosound_tcc/` + `tests/`, and the skill at
`vendor/autosound-tuning-skill/skills/autosound-tuning` (`rew_tool/`, `references/`, `SKILL.md`) —
signals vs connect/emit, i18n keys vs `t()`/`tx()` call sites, public defs vs call sites, dataclass
fields vs reads, MCP tools vs documentation, CLI subcommands vs docs, pyproject deps vs imports,
widget construction vs layout insertion. **3 findings carry a user- or agent-visible symptom;
everything else verified dead lands in the explicitly-labelled no-symptom and unverified sections
below.** The four previously known instances are all fixed (curve button:
`src/autosound_tcc/ui/tcc/measurement_panel.py:364`; injected `sessions_for`:
`src/autosound_tcc/ui/tcc/plan_panel.py:355`; `known_titles` exists:
`src/autosound_tcc/ui/tcc/measurement_panel.py:651`; `pyqtgraph` imported:
`src/autosound_tcc/ui/tcc/curve_view.py:27`).

---

## 1. The `selection` and `note` signal kinds have no producer — the agent is promised signals that can never arrive

- `src/autosound_tcc/core/signal_bus.py:37` (`SELECTION = "selection"`) and `:39` (`NOTE = "note"`)
  are defined, documented in the module ("user moved attention: channel / preset / measurement
  session", "free-text aside typed into the panel"), and consumed by the drain/wait machinery.
- The **only** `bus.push(...)` calls in the entire app are:
  - `src/autosound_tcc/ui/tcc/main_window.py:1842` — `CHANNEL_TOGGLE`
  - `src/autosound_tcc/ui/tcc/dialog_panel.py:1117` — `NOT_VISIBLE`
  - `src/autosound_tcc/ui/tcc/dialog_panel.py:1139` and `:1145` — `PARAM_EDIT_MODE`

  No code path anywhere pushes `SELECTION` or `NOTE`. Clicking a channel, switching a preset, or
  selecting a measurement session goes to the detail pane / measurement panel and never touches
  the bus.
- The model is explicitly told otherwise: the `get_pending_signals` tool docstring
  (`src/autosound_tcc/core/mcp_server.py:328`) says signals include "**moving attention to another
  channel**", and `wait_for_signal` (`mcp_server.py:356`) tells it to "park until the Arbiter does
  something in the UI".

**Observable symptom:** an agent that follows its own tool documentation — "hand the Arbiter a task,
then `wait_for_signal`" — parks for up to the full 900 s timeout while the Arbiter is actively
clicking channels and sessions in the window, because none of that activity produces a signal. To
the user it looks like the session went dead right after they did what was asked. The "type a note
to the model" affordance the bus documents does not exist in the UI at all.

## 2. `clear_alias` is unreachable — a model substitution, once accepted, is permanent

- `src/autosound_tcc/core/model_overrides.py:101` — `clear_alias(from_key)` is defined and called by
  nothing (no src, no tests, no CLI, no dynamic access).
- Aliases ARE created from the UI: the "model gone" replacement dialog writes one at
  `src/autosound_tcc/ui/tcc/main_window.py:2462`. And they are applied unconditionally on every
  resolution: `src/autosound_tcc/core/model_choices.py:529` (`resolve()`) follows the alias chain
  with no check that the original model is still absent.

**Observable symptom:** the Arbiter accepts "Opus 5 is gone, run X instead" once; from then on every
session, Critic call, and `get_tcc_state` report silently runs X **forever** — including after the
original model comes back (CLI reinstalled, catalogue refreshed). The app shows the `modelAliased`
notice but offers no control to undo what it announces; the only way out is hand-editing the
overrides JSON. The undo half of the feature was built and cannot be reached.

## 3. Translated strings that can never render — detail pane and capture legend hard-code English

Both language tables carry finished translations (parity is exact: 317 keys en, 317 uk) for strings
whose widgets never call `t()`:

- **Detail pane** (`src/autosound_tcc/ui/tcc/detail_pane.py`) hard-codes:
  - `:185` `_DTab("Table")` — key `tabTable` («Таблиця») at `i18n.py:145`/`:509`
  - `:206` `QPushButton("close ✕")` — key `close` («закрити ✕») at `i18n.py:146`/`:510`
  - `:307` header `"Channel"` — key `colChan` («Канал») at `i18n.py:149`/`:513`
  - `:427` `"shared frequencies:"` — key `shared` at `i18n.py:153`/`:517`
  - `:435` `"no shared frequencies"` — key `noShared` at `i18n.py:154`/`:518`
  - `:401` `f"{n} band{'s'...}"` — key `band` («банд») at `i18n.py:155`/`:519`
- **Measurement legend** (`src/autosound_tcc/ui/tcc/measurement_panel.py:86`) hard-codes
  `"waiting"`, `"done"`, `"taken, unusable"` — keys `legWait`/`legDone`/`legBad`
  (`i18n.py:156-158`/`:520-522`) exist in both languages and are referenced by nothing. (The fourth
  entry, `"skipped"`, never got a key at all.)

**Observable symptom:** with the UI language set to Ukrainian, the detail pane's tabs, close button,
table header, EQ pair legend, and the measurement panel's status legend stay English — and
`set_language()`'s full-UI repaint (the module's own stated contract, `i18n.py:5-7`) skips them,
because a string that never goes through `t()` also never re-translates. The translation work is
done, shipped in both tables, and unreachable.

---

## Verified dead — no user-visible symptom today

Confirmed unreachable by reading the code (not just grep), but nothing a user or caller can
currently observe goes wrong because of it. Listed so it stops being found by accident.

- **`GroupTable` — an entire widget module with zero importers.**
  `src/autosound_tcc/ui/tcc/group_table.py` (the generic profile-driven table from commit
  `7511a02`) is imported by nothing in src or tests. Superseded by `DetailPane._build_table`
  (`detail_pane.py:305`). No data is currently lost by the supersession: DetailPane's
  `_FIELD_COLUMNS` covers all 9 tokens of the skill's `FIELD_VOCABULARY`
  (`vendor/.../rew_tool/dsp_profile.py:185`) plus `off`, and the validator refuses profiles with
  unknown fields — but the day the vocabulary grows a token, the table that would have rendered it
  is this one, and it cannot be reached.
- **`quiet = Signal(list)`** — `src/autosound_tcc/ui/tcc/main_window.py:429`, declared (after
  `run()`, on `_CliCatalogueWorker`), never emitted, never connected. The feature its comment
  promises (report routes that answered with nothing) is implemented independently at
  `main_window.py:1898-1901` via `model_choices.cli_routes_without_models()`.
- **`DetailPane` dead signal surface** (`src/autosound_tcc/ui/tcc/detail_pane.py`):
  - `:164` `eqRequested` — declared, never emitted, never connected.
  - `:163` `tableRowActivated` — emitted at `:337`, connected by nothing; its comment ("caller
    opens EQ for it") is stale — the pane opens the EQ itself at `:343`, so row-click works.
  - `:162` `closed` — emitted at `:228`, connected by nothing in src (one test connects a
    same-named signal on `agent_worker`, not this one).
- **`_AgentWorker.closed`** — `src/autosound_tcc/ui/tcc/agent_worker.py:38`, emitted at `:151`,
  connected only by `tests/test_dialog_live.py:338`; app shutdown uses `stop_workers()`/`wait()`
  (`main_window.py:2762`), not this signal.
- **`CurveView.markersChanged`** — `src/autosound_tcc/ui/tcc/curve_view.py:137`, emitted at `:646`,
  connected only by `tests/test_curve_view.py:64`. The dialog reads markers via `on_send`/
  `reading()`, and the view paints its own readout, so nothing visible is missing.
- **`RewBridge` facade methods with no caller** — `src/autosound_tcc/core/rew_bridge.py:102-116`:
  `equalisers()`, `crossover_types()`, `slopes()`, `target_settings()`, `target_response()`.
- **Orphaned public functions/methods** (zero references in src, tests, docs, or via
  getattr/strings):
  - `OnboardingSession.draft_profile` — `src/autosound_tcc/core/agent_session.py:227`
  - `DialogPanel.set_composer_visible` — `src/autosound_tcc/ui/tcc/dialog_panel.py:642` (built for
    the view/control mode that is a deliberately open decision; nothing calls it yet, and today's
    no-worker composer path handles its own case at `:796-804`, so no live symptom)
  - `measurement_view.glossary_path` — `src/autosound_tcc/state/measurement_view.py:36`
    (`has_glossary` right below re-derives both paths inline)
  - `_PlanProgress.is_done` — `src/autosound_tcc/ui/tcc/plan_panel.py:63`
- **Dataclass fields:**
  - `Question.multi` — `src/autosound_tcc/core/agent_events.py:91`: never written by either adapter
    (the only `Question(...)` constructor is `omp_session.py:478`, which doesn't pass it — the omp
    select frame carries no multi flag), never read by the panel. Dead in both directions.
  - `Unbacked.phase` — `src/autosound_tcc/state/plan_audit.py:46`: written by the audit, read by
    nothing — the `supervisorUnbacked` warning (`main_window.py:1991`) names steps but can never
    say which phase they sit in.
- **i18n keys whose widget no longer exists** (in both language tables, referenced by no code):
  - `outTitle`/`virtTitle` (`i18n.py:147-148`) — section titles now come from profile group labels.
  - `pillOff` (`i18n.py:189`) — the OFF pill was deliberately removed from the tree
    (`dsp_tree.py:144-149`, user request 2026-07-27); the key stayed.
  - `startSessionReady`/`startSessionRunning` (`i18n.py:305-306`) — the session button was
    redesigned to a restart-only control (`main_window.py:2569-2575`); these tooltips have no
    button state left to appear on.
- **Skill (stdlib repo) orphans** — no callers, no doc mentions:
  - `HouseCurve.from_file` — `vendor/.../rew_tool/target_bands.py:77`; every `HouseCurve` instance
    is built from inline literals (`:182`, `:232`), so the file-loading path is dead.
  - `dsp_math.complex_interp` — `vendor/.../rew_tool/dsp_math.py:304`.
  - `dsp_math.load_ntt_txt` — `vendor/.../rew_tool/dsp_math.py:318`; NTT files are read by
    `nono_curves.parse_nono_curve` instead.

## Checked and clean

- **Signal wiring**: every other `Signal` in src is both emitted and connected, including the
  chains that go through `.emit` passed as a callable (`plan_panel.py:391`
  `sessionRequested.emit`; the `dsp_tree` re-emit ladders at `dsp_tree.py:436-439`, `:495-498`).
- **i18n direction 2**: no `t("key")`/`tx("key")` call names a key missing from the tables; en/uk
  parity is exact. Dynamic families (`curveKind_*`, `curveAxes_*`, `effort_*`, `effortTip_*`,
  `flawAction_*`, `flawKind_*` including `non_min_phase`/`thd_spike`/`pair_suckout` — all legal
  `kind`s per `vendor/.../rew_tool/project.py:214`, `curveZoom*` via `t(key + "Short")` at
  `curve_view.py:692`, `attachEmpty*` via `capture_hint_key`) are all reachable.
- **pyproject**: all three dependencies are imported (`PySide6` everywhere, `pyqtgraph` at
  `curve_view.py:27`, `claude-agent-sdk` in `agent_session.py`/`tuning_session.py`). All three
  `[project.scripts]` entry points resolve.
- **MCP tools**: all 27 `@mcp.tool` registrations in `core/mcp_server.py` are advertised to the
  model at runtime through the MCP listing, so "not mentioned in `references/`" is not
  unreachability. 14 of 27 have no mention in the skill's references or TCC docs
  (`wait_for_signal`, `get_ledger`, `get_capability_checklist`, `check_existing_profile`,
  `save_profile_field`, `reset_profile_field`, `finalize_profile`, `check_captures`,
  `propose_change`, `write_rew_filters`, `copy_helix_eq`, `show_curves`, `call_critic`,
  `get_pending_signals` docs-only) — the only one whose *documentation promises the impossible* is
  the signal pair, which is Finding 1.
- **Skill CLI subcommands**: every subcommand of `rew_tool.py`, `state/state.py` (incl. `log`,
  documented at `rew_tool/state/schema.md:150`), `dsp_profile.py` (all 11 driven by TCC's
  `core/profile_writer.py`), `state/process.py`, and both `gates/` modules is documented or called.
- **Widgets never added to a layout**: none found — all candidates were factory functions whose
  return value the caller inserts.
- **Deliberate, not defects**: `ui/tcc/mock_data.py` is a design fixture used on purpose by the
  tests and the no-project design surface. The terminal front-end button is intentionally hidden
  (`main_window.py:826`, comment states the product decision), not orphaned.

## Unverified

- **MCP reachability under non-SDK harnesses**: that omp/Codex sessions actually surface the tcc
  HTTP server's tool list to their model (via the written `.mcp.json`) was not exercised live; the
  "advertised at runtime" claim above is verified for the FastMCP/SDK path only.
- **Intent behind the detail-pane i18n keys** (Finding 3): the tables were ported wholesale from
  the web prototype "so later milestones can copy more entries in verbatim" (`i18n.py:1-3`), so
  some of those keys may be pre-staged rather than regressions — the symptom (mixed-language UI in
  uk mode) is real either way, but whether it is a P1 or a known v1 gap is a product call I cannot
  verify from code.
- **Reflection in tests**: I checked `getattr` call sites in src (all are guards on known
  attributes), but I cannot categorically rule out reachability through test-only reflection for
  the items in the no-symptom list; none was found where I looked.
