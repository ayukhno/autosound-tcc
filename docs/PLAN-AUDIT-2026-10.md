# Plan — the October 2026 audit volume, TCC's side

Written 2026-10-04 for hub #253 (HUB-081). The input is five reports: TA and TB are TCC's own, S1 and S2 cover the skill,
S3 covers the user's path. The hub's routing map is `hub/docs/AUDIT-INDEX-2026-10.md`. S3 is private, so it is cited
here by ID only.

**What this file is.** This is the input to the milestone review. It is not an order. W-8 is in collection. Its milestone
opens on «збір закінчено», and nothing below is built before the user's `ok` on that task (`WAVES.md` §1). No issue
was opened and no code was changed.

**Base.** tcc `main` at `f58d208` (v1.1.1), with the method pinned at v3.1.1 (`e8dabf7`). TA and TB were written at this
same commit, so `rev-list --count f58d208..main` = 0: the code has not moved since the audit. S1 and S2 were written at
skill `7b3232b` (`rev-list --count e8dabf7..7b3232b` = 7).

**How it was made.**
- Four read-only passes (sonnet) re-checked every TCC finding and every joint item against the code.
- Grouping and wave order were done in one head, by this session.
- Ten design passes (opus) covered the four M/L groups, two or three focuses per group.
- Two test passes (sonnet) named the first red test per group.
- One coverage pass (sonnet) checked that every finding has a place.

**Notation.** Every group carries the four lines from `WAVES.md` §1:
- **Class:** defect · feature · infra · docs.
- **Model:** the model that builds it. Builders are Opus. Fable gives the final review of risky code.
- **Risk:** L · M · H.
- **Complexity:** S = hours · M = days · L = more than one wave.

## 0. In one paragraph

The reports hold up: **of ~95 TCC findings checked, none is wrong**. Some are wider than written, and some were understated:
- the lock can hold a writer for ~240 s, not 120 s;
- a curve step costs 3N+2 file operations, not 2N;
- a superseded capture is misread in two ways, not one;
- there are five broken install hints, not two.

**Twenty-one findings are new (§1).** The most important are:
- the omp route gets none of TCC's system rules;
- `gate=never` in a project folder is never vetted;
- `title_fixes` writes outside the lock;
- `car_library` writes `project.json` in-process with no lock;
- an older method silently turns unknown flags into data.

**The work falls into 14 groups.** Six meet the skill:
- G5, the contract and one method per project;
- G6, readers;
- G7, refusals and REW states, which ships in the same wave as the skill's refusals;
- G8, one lock;
- G11, what TCC tells the model;
- G9, for the seed preview only.

Everything else is TCC's own.

**Proposed order** (§3):
1. **W-8:** two small TCC-only groups — the agent↔window crossing (G2) and loud boundaries (G1). Both are user-visible, and neither touches a module a joint group will redesign.
2. **W-9:** the TCC-only parts that prepare the joint work.
3. **W-10:** the contract, the refusals and the REW states, on top of the skill's W-8 tags.
4. **W-11:** one lock for every writer, on top of the skill's W-9 lock.

The mismatches with the skill's plan were settled in one round (hub #255), §10.
5. **Later:** the deeper GUI-thread work, curve view, end-to-end tests and structure, one slice per wave.

## 1. Verification — what changed against the reports

The per-finding verdicts with file:line are in `docs/audit/AUDIT-2026-10-VERIFIED.md`; where each finding goes is §8. Corrections that change the plan:

| id | report said | at `f58d208` |
|---|---|---|
| TA-1d | `capture-check` holds the writer lock up to 120 s | The `_THREAD_LOCK` acquire has **no timeout**. The holder runs the flock wait plus the child inside it, so the worst case is ~240 s. MCP-thread writers wait too (`core/process_writer.py:50,106-159`). |
| TA-1f | the seed runs "while the user types a car's name" | It runs on the DSP fields, **un-debounced on every toggle and combo**, and also runs `gh api user` over the network (`ui/tcc/new_project_dialog.py:258-307`; vendor `project_repo.py:77`). |
| TA-3 | reloads twice | Process-state is re-read twice; the project is reloaded twice only when project files changed. `refreshRequested` also fires with no file change (`core/mcp_server.py:1487`), so a coalesced re-read must stay. |
| TA-4 | 2·N file operations per step | 3N+2 per step (`core/delay_bank.py:140-180`). |
| TA-12 | ~1 min worst case | ~28 s of waits, plus `close_session` behind the unbounded lock. Leave it as it is. |
| TB-F6 | no `capture_superseded` case | **Two** misreadings: the event is missing from the fold, **and** `taken[title].superseded_by` in the open round reads as taken (`state/process_view.py:98-187`, `state/measurement_view.py:415-441`). The skill's `Process.capture_rounds()` is narrower than TCC's fold, so swapping one for the other is not a drop-in fix. |
| TB-F7 | writers run TCC's method | **All eight** writers do, and `core/car_library.py:140-150` writes `project.json` in-process through the skill's `Project.save`. |
| TB-F10b | two hints install half the app | **Five.** `core/protective.py:113` and `core/desktop_entry.py:160` are also wrong (the latter has no URL at all and cannot work), and `README.md:186` has no tag. |
| TB-F14 | permission ticks travel unvetted | The folder's **`gate` value** does too, and `never` lifts the irreversible-command guard (`core/tuning_session.py:237-256`). |
| S1 B10 | no MCP twin for session-close, target, capture-knobs, … | TCC **has** `session_close`, `set_target`, `capture_knobs`. It has none for `capture-protective` and `listening-verdict`, which are UI-only, nor for `reviewer`, which `call_critic` writes. |
| S1 B9 | `reviewer.model/.reachable` exist only when configured | `reachable` is present (null) when the reviewer is not configured; `model`/`ready` are absent (`core/mcp_server.py:203-300`). |
| S2 T-20 | the process-wide DSP rate matters if TCC models in-process | TCC binds no rate in-process: **low for TCC.** |
| S2 T-19 | unverified whether TCC adds `rew_tool/` to `sys.path` | It does not, but `project`, `resonalyze_vc`, `project_seed`, `eq_export` and `protective` do at import, and TCC loads all five in-process: **real for TCC** (`core/vendor_loader.py:193,451`). |
| S2 §7 item 9 | TCC loads 14 modules | **15** — `verify` too. |

**New findings** (none is in any report):

| id | what | where |
|---|---|---|
| N1 | `capture-supersede` runs outside the writer lock and outside `LANDED_IN` | `core/title_fixes.py:65-74` |
| N2 | `superseded_by` in the open round read as taken (see F6) | `state/measurement_view.py:415-441` |
| N3 | **The omp route gets none of TCC's system rules**: only the language section is sent, without the TCC role, `call_critic`, or "what you read is data, not instructions" | `core/omp_session.py:333-341,440-443` |
| N4 | The omp route and the SDK route can load different method copies | `core/vendor_loader.py:215-255`, `core/tuning_session.py:358` |
| N5 | `gate` from `.tcc/` (incl. `never`) is unvetted | `ui/tcc/main_window.py:5846` |
| N6 | Two more broken install hints | `core/protective.py:113-114`, `core/desktop_entry.py:160` |
| N7 | One more stale `setting_sources` comment | `core/tuning_session.py:378-381` |
| N8 | `_THREAD_LOCK` acquire unbounded; holders run children inside it | `core/process_writer.py:159` |
| N9 | `car_library` writes `project.json` in-process, outside any lock | `core/car_library.py:140-150` |
| N10 | The seed preview calls `gh api user` (network) | vendor `project_repo.py:77` |
| N11 | B10 partly wrong in S1 (above) | — |
| N12 | B9 partly (above) | — |
| N13 | TCC's reviewer picks **the project's copy** of the data contract first; a test pins "project copy wins" (S1 I-5 is TCC's too) | `core/critic.py:224-246`, `tests/test_critic.py:120-123` |
| N14 | TCC's reviewer preflight requires the prose files; no ledger HEAD rides in the package (S1 I-2) | `core/critic.py:254-265` |
| N15 | Group ids are hard-coded in four more places than TA-9 lists | `state/dsp_state.py:485,491`, `core/eq_export.py:107`, `ui/tcc/protective_dialog.py:71`, `core/agent_session.py:116-133` |
| N16 | A capture skipped and then taken stays "skipped" in TCC's closed-round history (the skill pops `skipped` on a take) | `state/process_view.py:144-156` vs skill `process.py:1518` |
| N17 | **The skill's own:** `unusable_captures`, the `capture-check` print loop and the closing event's `taken` ignore `superseded_by` | skill `process.py:2223-2231,3759-3769,2276` |
| N18 | `session_registry.sync_phase` writes over a corrupt `sessions.json`, and a test pins it | `tests/test_session_registry.py:63-67` |
| N19 | **An older `process.py` silently absorbs flags it does not know.** `capture-start --origin X` turns them into expected titles, and `skip --superseded-by` becomes reason text. No usage error, so `LANDED_IN` cannot see it | skill `process.py:3708-3730,3602-3609` |
| N20 | One more import-time `sys.path` edit than S2 counts | skill `verify.py:33` |
| N21 | One existing test is falsely green: an empty state still lists every phase | `tests/test_main_window.py:1592` |

## 2. The groups

TCC's own: G1, G2, G10, G12, G13, G14, and the TCC halves G3 (J3) and G4 (J6), which need nothing from the skill. Joint with the skill: G5 (J1), G6 (J1/J8), G7 (J3/J4), G8 (J2), G9 (J5, for the seed preview only), G11 (J8). The J7 family waits for a walk in the car.

### G1 · Boundaries say what happened (TCC-only)
- **Findings:** F3a (omp death → the next turn hangs), F3b (SDK `is_error` read as a normal end), F3c (MCP server death unnoticed), F3e (confirm-bridge errors swallowed as "denied", three places), F16-1 (bare `subprocess.run` in `critic.run` `:574`, `critic.doctor` `:970` and `updates._run_upkeep`, which are unbounded on Windows), F16-5 (`report_from_json` and `forget_mcp_config` "never raise" but do).
- **Shared solution:** at each boundary, silence becomes a visible Notice, a log line or a refusal; children go through `child.run_bounded`.
- **Four lines:** Class defect · Model opus · Risk M (omp/SDK async paths; a wrong Notice can end a healthy turn) · Complexity S×6, ~1 day.
- **First tests:**
  - **F3a:** after the reader hits EOF, the first event of the next `_prompt` (under `wait_for`) is a Notice that is **not** the "no output" silence notice. A plain "yields a Notice" passes today.
  - **F3b:** a real `claude_agent_sdk.ResultMessage(is_error=True, errors=["x"])`, constructible with 0.2.145, → a Notice containing "x".
  - **F3c:** `_mcp_server` with `serving=False, failure=OSError("p")` → one system message naming "p".
  - **F3e:** a bridge whose `request_confirmation` raises "boom" → "boom" is logged. The same test runs for the two sessions. A timeout stays a denial.
  - **F16-1:** `tests/_hung_child.py` with `windows=True` → no `WaitedForever`, and `MODE_ERROR`.
  - **F16-5:** `.mcp.json` = `[]` → `forget_mcp_config`/`write_mcp_config` do not raise.
- **Churn:** ~13 tests in `test_critic.py` replace `subprocess.run`, and they move to `run_bounded`/`Popen`. Every bridge double returns a resolved `Future` and never raises (`test_mcp_server.py:34-40`, `test_omp_session.py:34-39`, `test_tuning_session.py:31-36`). `_send` stubbed with `list.append` never fails on a dead pipe.
- **Moved out:** F3d (the `"None"` plugin path) goes to G5, whose resolver changes the same line (`tuning_session.py:358`).

### G2 · The agent↔window crossing (TCC-only)
- **Findings:** TA-5 (the model is told a stale preset/edit mode is "on their screen" — **correctness**), TA-3 (every agent write runs the full ↻), TA-2 (every streamed delta re-renders the whole message).
- **Shared solution:** the agent→GUI path through `QtUiBridge`. The snapshot is republished wherever its fields change, from the preset `_load_project` actually chose. `refreshRequested` gets a coalesced re-read, and ↻ stays the explicit full re-check. Deltas are buffered and redrawn at 10–20 Hz.
- **Four lines:** Class defect · Model opus · Risk L · Complexity S×3, ~4 h.
- **First tests:**
  - **TA-5:** a two-preset fixture **without** `AUTOSOUND_TCC_PRESET` → `bridge.snapshot()["preset"] == combo.currentData()`. Every existing preset test sets that variable, which hides the bug. Siblings: a combo switch, and edit mode on.
  - **TA-3:** `refreshRequested.emit()` → 0 catalogue starts, 0 `forget_refusals`, 0 REW pings; five emits → at most one load.
  - **TA-2:** 600 `TextDelta`s → `set_html` at most 30 times. The first delta renders at once, and `turn_done` flushes.
- **Churn:** `test_main_window.py:5110-5128` calls `_reload_from_disk` directly. About 20 `test_dialog_live.py` tests read the bubble right after a delta, so the first delta must stay immediate.

### G3 · TCC's own stores: unreadable is not empty (J3, TCC half)
- **Findings:**
  - F5 for `.tcc/tcc-project.json` and the capture-import store: an unparseable file is read as `{}` and then rewritten, losing model choices, ticks, delays and import answers.
  - **N18:** `session_registry.sync_phase` writes over a corrupt `sessions.json` the same way, and `test_session_registry.py:63-67` pins that.
  - F16-6 (`.mcp.json`): an unparseable file is replaced, and a foreign instance's entry is removed.
- **Shared solution:** absent ≠ unreadable. On unreadable, move the file aside (`*.corrupt-<stamp>`), say so in the status strip, and never write over it. TCC's own atomic writers (`project_settings`, `session_registry`, `capture_import`, `signal_bus`) also `fsync` before `os.replace` (TB-F5's TCC half; the skill's half is T-8/T-17).
- **Independent of the skill:** these are TCC's own files, so G3 ships before G7 without splitting J3. J3's "one wave, both sides" applies to the skill's refusals and G7.
- **Four lines:** Class defect · Model opus · Risk L · Complexity S×5, ~6 h.
- **First tests:**
  - A trailing comma in `tcc-project.json`, then `set_value` → exactly one `*.corrupt-*` holding the original bytes. The window's strip says "corrupt"; this needs an ERROR-level log through `app_log.set_ui_sink`.
  - The same for the import store and for `sessions.json`.
  - `.mcp.json` written by instance A, then by B; A's `stop()` → B's port is still there.
- **Not here:** `process-state.json` is the skill's (K-2); TCC's display of that refusal is G7.

### G4 · Install and update say the truth (J6, TCC half)
- **Part 1, TCC-only:** F10a (rank stable with release-shaped names only), F10b + N6 (all four code hints built from `updates.tcc_install_command`, and the README line at `:186` given its tag), F13 (pairing check needs a ≥7-character prefix; `uv run --locked` in CI), the CHANGELOG preamble (F10c's TCC line).
- **Part 1 also takes the T-35 twin**, which the skill's plan found in TCC. `updates.py:830` runs `git verify-tag` without pinning `gpg.ssh.program`, so a signing helper in the user's git config (1Password's, say) refuses a good release. Its classifier also matches a bare `"-Y"` (`:767-773`). Fix: pin `-c gpg.ssh.program=ssh-keygen` and classify on git's own sentences. First red test: the `_git` spy's argv carries the pin.
- **Part 2a, TCC first (W-10):** F1 — `constraints.txt` exported from `uv.lock` (`uv export --extra gui --extra claude --no-hashes`) ships in every tag from W-10. A test holds it equal to the lock, and `ship.py` refuses a tag where it differs. TCC's updater passes `-c` with the file read from the signed tag's tree to disk, so whether uv takes a URL does not matter. The skill's installers take the same file in its J6c (W-11), its N7.
- **Part 2b (W-12, with G12):** the scheduled fresh-resolve job.
- **Four lines:** Class defect/infra · Model opus · Risk L (part 1), M (part 2) · Complexity S×4 (~5 h) + M.
- **First tests:**
  - `newest_tcc_tag()` over `v1.1.1, v1.2.0-wip, v1.1.1.1` (the `_git_answers` helper) → `v1.1.1`.
  - A test parametrised over `_NO_GUI`, `INSTALL_HINT` and `desktop_entry._launcher_script` asserts `--python 3.12`, `git+https://` and both extras. The URL part alone passes today for the first two.
  - `ship.check_paired_method(…, said="a")`, and a sha containing `"e"` with `said="e"` → `Stop`.
  - A test that reads `ci.yml`: every `uv run` has `--locked`.
- **Churn:**
  - `test_packaging.py:139` (`"[gui]" in stderr`) and `:436` (`"[claude]"`).
  - `test_updates.py:796-800`.
  - `test_diagnostics_panel.py:896`.

### G5 · The contract handshake and one method per project (J1, joint)
- **Findings:** F2, F7, N4, N1, F3d, F16-3, the private `PresetHistory._path`, T-19's import-time `sys.path` edits reaching TCC; and the inventory TCC sends the skill (§4).
- **First red test:** a project linked to an approved second copy → `enter_phase` starts **that** copy's `process.py`. Today `process_writer.py:92-93` starts TCC's own.
- **Four lines:** Class infra · Model opus · Risk H (every writer and both session routes pass through it) · Complexity M, ~30 h.
- **Design:** §5.2.

### G6 · Stop mirroring the method's readers (J1/J8)
- **Findings:** F6 + N2 (a superseded capture shows as done — **user-visible**), F8 (D-1: TCC's own older Helix profile overrides the skill's library; Musway unreachable), TA-8's "settled" written three ways, ~15 direct parses of the skill's files.
- **Import-store OR:** it stays. The import store is TCC's own record, consulted only where the method has no round; the open round already wins (`measurement_view.py:478-483`).
- **First red test:** a real `Process` round with `w-R_1` taken and then superseded → TCC's waiting rows equal `capture_outstanding()`. Today `w-R_1` shows as done.
- **Four lines:** Class defect · Model opus · Risk M · Complexity M (~16 h + ~5 h + ~9 h in three slices).
- **Design:** §5.3.

### G7 · Refusals and REW states reach the screen (J3 + J4, TCC half; follows the skill's half)
- **Findings:**
  - F5 for `process-state.json`: today an empty plan is shown, and the next write makes it permanent.
  - F4 `write_rew_filters`.
  - TCC's half of T-1, T-2, T-3 and T-10: one REW state where there are three, and gates that let a damaged project advance.
- **Shared solution:** the skill starts refusing with **named** errors and exit codes, and TCC shows the refusal instead of an empty plan or "missing — measure it".
- **Split by timing:**
  - **Now, TCC-only:**
    - F4's two TCC parts: `rew_api` called through `_in_thread`, and `KeyError` mapped to the JSON error (the dead `if mid is None` goes).
    - A parse check of `process-state.json` before `Process.load` is trusted, so the guard at `main_window.py:3868` can fire.
  - **With the skill's wave:**
    - the refusal from `Process.load` (K-2) is shown;
    - the gate refusals (T-10, T-11) are shown;
    - the three REW states (T-2, T-3) appear in the capture check, the measurement panel and the MCP tool results;
    - `write_rew_filters` relies on the skill's `set_filters` validation and read-back (K-1). TCC does **not** validate `gain`/`gaindB` itself.
- **Four lines:**
  - Class: defect.
  - Model: opus, with **Fable's final review** for the refusal paths.
  - Risk: H. A refusal shown wrongly blocks a working project.
  - Complexity: S×2 now, M with the skill.
- **First tests:**
  - **Strengthen the falsely green test.** `test_main_window.py:1592` (`…half_written_process_file_does_not_erase_the_plan`) passes today only because an empty state still lists every phase. Assert a real step name instead, and it goes red.
  - `load_state` on `{ half` → `None`, not an empty dict.
  - `write_rew_filters` with REW down (conftest already points REW at port 1) → `applied: false` plus an error.
  - A missing title, using the real `find_measurement_id` → the same JSON error.
  - `set_filters` records its thread id → not the event loop's thread. This is a count, not wall time.
  - "REW answered 500" vs "missing" can only be written once the skill's T-2/T-3 define the states.
- **Churn:**
  - `test_rew_bridge.py:19-34` pins "any exception = unreachable".
  - `test_main_window.py:2920-2922` pins `_set_rew_online(bool)`.
  - Only one behaviour test covers `write_rew_filters` (`test_mcp_server.py:458-479`).

### G8 · One lock for every writer (J2, joint; TCC's half follows the skill's lock)
- **Findings:** F9, N1 (lock part), N8, N9, TA-1d/e, and the skill's K-3, T-8, T-9, T-12, T-18.
- **Four lines:** Class defect · Model opus + **Fable's final review** · Risk H · Complexity M.
- **Design:** §5.4.

### G9 · Off the GUI thread
- **Findings:**
  - TA-1, rows a–n;
  - TA-6 (two-phase construction, modals in slots);
  - TA-7 M (`mcp` imported lazily);
  - J5 (the seed preview; the skill adds K-4);
  - the reads that grow with history (`stale_channels`, `ledger_line._made_for`, `critic.last_call`).
- **The seed preview is built once, in two steps:** S1 debounces and remembers it; once the pin carries the skill's K-4 dry run, a follow-up in S3's wave switches to it, found by checking `seed`'s signature. G9 builds both; the skill builds only K-4.
- **Four lines:** Class defect · Model opus · Risk M–H · Complexity M/L, in three slices (~8 h, ~20 h, ~16 h).
- **Design:** §5.1.

### G10 · The curve window
- **Findings:** TA-4 S part (one bank write per step: `delay_bank.put_many`, so 3N+2 → 2; the readout rendered once per event), TA-7 S part (`tip_html` out of `curve_view`, which saves ~0.34 s at start), TA-11 (marker drag), then TA-4 M (`setData` instead of rebuilding every item).
- **Four lines:** Class defect (perf) · Model opus · Risk L (S part), M (M part: the pyqtgraph crash history, `curve_view.py:361-478`) · Complexity S×3 (~4 h) + M.
- **First tests:**
  - **One write per step:** `set_delay` with 7 traces → `project_settings.set_value` called once; today 7. `load` calls are bounded by a constant; today 3N+2.
  - **One render per change:** `set_delay` → `_render_readout` called once; today twice.
  - **pyqtgraph stays out:** a subprocess imports `main_window` → `"pyqtgraph" not in sys.modules`. In-process cannot work, because pytest already imported it.
  - **Marker drag:** one move → one readout render.
- **The M part** (`setData`) also takes the rest of TA-11, as TA itself says: the vhs-mode `_sync_levels` re-entry, the cross-mode `ScatterPlotItem` built per move, the `AxisItem` rebuilt on linear x, and the sum computed three times on a kind change. It also takes TA-4's "opening a set" (`_on_curves` restores the banked delay trace by trace, one full rebuild each).
- **Crash rate:** it is re-measured with the module's own **manual** protocol (5/40 → 0/40) before and after; it is not a CI test.
- **Churn:** tests reading `getData()` (`test_curve_view.py:1784,2523,2628,2634,4501`) and the never-rebuilt `_sum_vb` test (`:1736`).

### G11 · What TCC tells the model (J8)
- **Findings:**
  - N3: omp gets the system rules through its system-prompt file, the same text the SDK route appends.
  - The handoff prompt names the folder for `autosound_context.md`, after the skill settles I-21.
  - N13: the critic's contract lookup follows the skill's I-5 (the skill's copy first, or a warning on a differing project copy), and `tests/test_critic.py:120` turns around.
  - N14: the preflight follows I-2: the machine files win, and the ledger HEAD rides in the package if the skill asks for it.
  - F14 + N5: `.tcc/` ticks and `gate` are listed by `project_trust` before the first session (see Q2).
  - B9: a test that `model`/`ready` are absent when the reviewer is not configured.
  - **The external terminal** gets no system prompt by design (it is the user's own CLI). It reaches TCC only through the MCP server's `instructions` (`mcp_server.py:527-533`). Those carry the same core rules as `SYSTEM_PROMPT_APPEND`, so all three routes agree, and one test compares them.
- **Four lines:** Class defect · Model opus · Risk L · Complexity S×6.
- **First tests:**
  - **N3:** the omp `--append-system-prompt` file `== tuning_session.system_prompt_append(lang)`.
  - **F14/N5:** `.tcc/tcc-project.json` = `{"gate":"never","always_allowed":"Bash"}` → `bool(project_trust.warnings(p))`.
  - **N13:** with `vendor_loader.skill_dir` patched, the skill's contract copy is returned, or `preflight` warns on a differing copy, depending on the skill's I-5 answer.
  - **B9** is a pin, not a red test; it passes today.
- **Churn:** `test_critic.py:121-123` ("project copy wins"), and `:105`/`:135`, where preflight names `autosound_context.md`.

### G12 · Tests at the seams
- **Findings:** F11 (no wheel build or install, base install never run, `_TokenGuard` untested, doubles never compared with the real classes, a docstring-satisfied test, `ANTHROPIC_API_KEY` not cleared, a real GET in `_fetch_sdk_choices`, no per-test timeout).
- **Shared solution:**
  - one end-to-end smoke job: build the wheel, then a fresh `uv tool install`, then import the CLI half, then `TccMcpServer` on a fixture project, then a real `mcp` client over HTTP — without the token (401) and with it — then `get_tcc_state` and one gated write, then the file on disk;
  - contract tests for the SDK and REW doubles;
  - `conftest` clears provider keys and stubs `_fetch_sdk_choices`;
  - the docstring stripped before the `strict_mcp_config` check;
  - `pytest-timeout`.
  - The newest-method CI job is G5's.
- **Four lines:** Class infra · Model opus · Risk L · Complexity M, ~2 days.
- **First tests:**
  - **Provider keys:** a subprocess probe with `ANTHROPIC_API_KEY=sk-x` asserts that the key is gone inside a test.
  - **No network:** a counting `urlopen` spy → 0 calls from `sdk_choices()`. The conftest stub must be removable, since `test_model_choices.py:463` needs the real function.
  - **REW double:** a `"bridge"` slot in `test_doubles.py`; `_FakeBridge.find_id(name, exact=True)` differs from the real keyword-only `exact`, so this is red.
  - **Token guard:** `_TokenGuard` called directly as ASGI with no `x-tcc-token` → 401, and the inner app is not called.
  - **Timeout:** `pytest-timeout` declared.
  - **Python 3.11:** `requires-python >=3.11` is never run. The smoke job gets a 3.11 leg, base install only.
  - **`raising=False` guards:** 112 `monkeypatch.setattr(..., raising=False)` calls. A guard test asserts that every attribute conftest patches exists, so a renamed probe cannot turn a guard into a no-op silently.
  - **`app.main`'s window path:** one offscreen test runs `app.main` on a fixture project up to the first paint, then quits.
  - **The docstring-satisfied `strict_mcp_config` test** cannot be red at `f58d208`. Its proof is a manual mutation (delete `agent_session.py:322`), and the plan says so.
- **The smoke job fits the existing CI:**
  - It runs as a separate ubuntu job, with network to PyPI and GitHub only.
  - It sets `AUTOSOUND_SKILL_DIR` to the submodule, because the skill is not in the wheel.
  - Its "gated write that lands" is `enter_phase("-1")`. `HeadlessBridge` refuses every confirmed write.

### G13 · Structure, a slice per wave
- **Findings:**
  - TA-8 / F12 (`MainWindow` 6,465 lines, 222 methods);
  - decisions that live only on the window, and the duplicates (signal ids parsed from text, delay maths mirrored, reviewer state computed twice, the private `_CRITIC_VENDOR_MARKERS`);
  - `ControlLayout` reading ~20 of the window's private attributes, and `MainWindow` calling other widgets' privates 19 times (`_dialog._add_system_message`, `_detail._build_table`, `_detail._compare_version`);
  - `branding.py`;
  - mock data that still ships;
  - TA-9 + N15: group tables and tabs come from the profile, keeping A10's two named tabs.
- **Shared solution:** the `row_rule` precedent. Pull one decision at a time into a Qt-free module, then rewrite its full-window tests as plain-function tests. Never a rewrite.
- **Step 0, for W-8:** a ratchet — `main_window.py` may not grow, and each wave lowers the bound (hub H-013).
  - The size limit is green by design, so it gets a go-red companion test, as `test_packaging.py:106` does.
  - The decisions already pinned by window tests become the rewrite targets: `_capture_version` (`test_main_window.py:2344-2393`), `_effective_gate` (`:1338-1384`), and ~10 tests in all.
  - The signal-id parsing gets a characterisation test first, with a real `SignalBus`.
- **Four lines:** Class infra · Model opus · Risk M · Complexity L, at 1–2 S extractions per wave.

### G14 · Small hygiene and docs
- **Findings:**
  - F15 + N7: stale `setting_sources` comments (`project_trust.py:3-11`, `omp_session.py:320`, `tuning_session.py:378-381`); the docstrings that say TCC never writes `process/` (`config.py:161-165`, `process_view.py:59`); `rew_bridge.py:52` naming `_RewReadWorker`; the `TESTING.md` flake table; `CLAUDE.md:32` and `pyproject.toml:113-127` citing tcc#22 (fix the text, keep the serial default); ARCHITECTURE-NOTES §8 line refs; the CHANGELOG preamble.
  - TA-10: check the Windows monospace fallback on the VM; correct the scipy comment.
  - F16-2: stop losing the skill's worded message on a failed curve read (`curve_dialog.py:428-433` keeps only the exception type).
  - F16-4: REW's wording comes from the source, not a copied string.
  - The `capture_order` QSettings key carries the project.
- **Four lines:** Class docs/defect · Model sonnet for text, opus for code · Risk L · Complexity S. Picked up when the nearby code is touched.

### J7 · The car desk (waits)
- P2 (one car sheet per visit), P5 (the two loop modes), P7 (a state check first on every visit) and P8 (a return list at session close).
- **What TCC shows today:** each is PARTLY covered. TCC has pieces (the capture grid, the compare-with-v_NNN view, the end-of-phase handoff), but no per-visit sheet, no device-against-ledger check placed first, and no return list (P8). Its in-app vs terminal split does not match P5's two modes.
- **Four lines:** Class feature · Model opus · Risk — · Complexity — : not sized, because nothing is designed until Q4.
- **The skill writes these as text first.** S3's own advice is to walk them once in the car before writing them down.
- **TCC plans its screens after that walk (Q4).** Nothing is designed here, so nothing has to be redone.

## 3. Order across waves

**Decision, the Arbiter, 2026-10-06:** the audit's changes build first; W-8's findings collection (the pool: F-094, F-095's wave part, F-096) waits until they are done. How the wave numbers map is open (the number is read from the open milestones of both repos, `WAVES.md` §1), so the table below is not renumbered yet. The skill is told in hub #256 (TCC-051).

Joint groups follow the hub's rule: the skill tags first, and TCC re-pins in its next wave. **J2 and J3 no longer need one wave on both sides** (§10, M2): the skill's half is safe for today's TCC, provided «busy» is not exit 1. TCC's half then improves the display a wave later. Every skill candidate tag that TCC users would receive is run through TCC's suite first (§10, M3).

| wave | TCC builds | the skill builds (its own plan decides) | why this order |
|---|---|---|---|
| **W-8** (open; milestone at «збір закінчено») | G2 (3 S), G1 (6 S), G13 step 0 (ratchet) | — | TCC-only and user-visible (a wrong preset told to the model; a hung turn). Touches no module that a joint group redesigns. Small, because W-8 also carries the collection's findings and is the trial of the agents. |
| **W-9** | G5 S1+S2 (one copy per project, N1, `set-car`, the flag check, stop swallowing, newest-tag workflow; the handshake ships, its constant per §4.2); G9 S1 (bound and cache, no threads; its lock deadline **is** G8 phase 0, built once); G8 phase 0 race tests (xfail); G6 slice 1 (D-1, superseded, "settled", parity); G3; G4 part 1 (+ the T-35 twin); G7's "now" part; G10 S part (~4 h); **re-pin to the skill's W-8 tag**, with `test_rew_api_shapes.py:54-67` answering GET /filters with what was written (the skill's R3) | the contract (K-6, the 15-module list, T-19, T-27, T-21, T-23 incl. N19), strict reads (T-10, K-2, T-11, T-13, T-14), REW states (T-1, T-2, T-3, K-1), S-R1/S-R2 readers, N17, T-8 unique temp names | It prepares both sides. Nothing in TCC's part waits for the skill, and nothing in it is replaced when the contract lands. ~70 h of TCC work, so the milestone may split it in two. |
| **W-10** — joint 1 | G5 S3 (contract 1); G7 (the skill's refusals and REW states shown); G6 slice 2 (only if the skill takes §4.1 #6); G11; **G4 part 2a** (`constraints.txt` with every tag, the updater's `-c`); **conftest patches the shared `rew_api`** (the skill's J1c prerequisite, §10 M4) | the skill's W-8 tags (J1a, J2a + J3a, J4a), already out | TCC's half follows the skill's in the next wave; until then the refusals reach the strip verbatim and `_write`'s guard keeps the file (§10, M2). |
| **W-11** — joint 2 | G8 phase 1 (adopt the skill's lock) + G9 S2 (one helper; **one FIFO lane for all of TCC's writes**); G6 slice 3 (one reader per skill file) | the skill's J2b lock (its W-9), already out; its J1c (`sys.path` edits out) and J6c (installers take `constraints.txt`) | TCC drops its own lock around children that lock themselves, in the re-pin commit. The lane and the lock are built together, so the lane does not bake in today's lock. Fable reviews both. |
| **W-12 →** | G9 slice 3 (two-phase constructor, lazy `mcp`), G10 M part, G12 (+ G4 part 2b, the fresh-resolve job) | K-4 seed preview (its J5, W-10), K-5 `gh` timeout | The riskiest window changes come last, on top of the helper. |
| every wave | G13: one or two extractions; G14 when nearby | — | |
| after a car walk | J7 screens | J7 text | S3's own advice. |

## 4. Dependencies between the products

The hub matches this list with the skill's own. Wave numbers are TCC's. "Joint 1" = the skill builds in its wave before
TCC's W-10 and tags first.

### 4.1 What TCC needs from the skill

| # | what | S2/S1 ids | for | wave |
|---|---|---|---|---|
| 1 | `CONTRACT_VERSION = 1`, a top-level integer literal in `rew_tool/contract.py`. TCC reads it with `ast` from disk and from tag blobs, and never imports it. **Contract 1 = the v3.1.x surface TCC uses (§9).** A bump comes only on a breaking change to a listed item, never in a patch, and only after a TCC release that accepts it is out, with a beta candidate first. | §7.1, §7.12, K-6 | G5 | joint 1 |
| 2 | The importable list = **TCC's 15 modules, including `verify`** (S2 lists 14). No `sys.path` edits at import — there are six today, `verify.py:33` included — or at call time (`project.py:1568`, `naming.py:1081`, `project_seed.py:340`, `eq_export.py:585`) **by the skill's J1c (W-11), not earlier** (§10, M4). Before that, `siblings.py` registers its modules **in `sys.modules`**, so TCC's `reload_loaded` drops them after an in-app update (`vendor_loader.py:356-401`). A by-path load probe in the skill's suite. A public `PresetHistory` path accessor to replace `_path`. | §7.9, T-19, T-27 | G5 | J1a (W-8); J1c (W-11) |
| 3 | An exit-code table: 0 yes/done · 1 no/refused · 2 usage · **an unknown flag is a usage error, never absorbed (N19)** · busy **≠ 1** (75 asked; §10, M2) · one code for "unexpected error" · one for "REW unavailable". | §7.2, T-23 | G5, G7, G8 | joint 1 |
| 4 | Strict reads. `Process.load` refuses an unreadable file with a named error. Newer schemas are refused in `Process.load`, `PresetHistory` and `load_profile`. The gates refuse a damaged project, and the contract check says `valid: false`. | K-2, T-10, T-11, T-13, T-14, T-21 | G7 | joint 1 |
| 5 | REW. `set_filters` refuses unknown keys and reads back, raising a named error. `capture-check` never creates `taken`. Named errors for unavailable, protocol error and not found (a `KeyError` subclass), with a third verdict state. | K-1, T-1, T-2, T-3 | G7 | joint 1 |
| 6 | Readers. `Process.capture_history()` returns every round in the state-slice shape, open and closed alike. `is_taken`/`outstanding` become public. The fix for N17. `capture_superseded` and the closed event's `outstanding` are documented. **Not in the skill's plan, and the hub's match has no row for it** (§10). If the skill does not take it, G6 slice 2 is dropped, and TCC's fold stays its own with parity tests (the slice-3 rule). | new (S-R1, S-R2), T-22 | G6 | its W-9 → TCC W-10 |
| 7 | The prose answers that TCC follows: the reviewer's truth model, the contract copy, one folder per prose file. | I-2, I-5, I-21 | G11 | joint 1 |
| 8 | The lock (§5.4): `rew_tool/write_lock.py` with `PROTOCOL = 1`; `<project>/.autosound/write.lock` plus a self-ignoring `.autosound/.gitignore`, and never `process/.process-write.lock`; re-entrancy owned by a thread, with one registry per process; `hold`, `held_here`, `Busy` and `Project.update`; never held across REW, git or a subprocess; `AUTOSOUND_LOCK_TIMEOUT_S`, then exit 75 with a `busy:` line. **T-8 in the same tag** (unique temp name, fsync, Windows retry). | T-18, K-3, T-8, T-9, T-12, T-17 | G8 | joint 2 (W-11) |
| 9 | A seed dry run with no git, no `gh`, no `Project.save` and no `.gitignore`, whose record carries the Fs count; lazy imports moved to the top. `describe()` does **not** cover the dialog (§10, N4). | K-4 | G9 S3 | its J5 (W-10) |
| 10 | A `gh` timeout. | K-5, T-49 | G9 | any time |
| 11 | Installers take TCC's `constraints.txt` (`-c`) from the paired TCC tag; the unsigned-`main` fallback stops (T-37, its J6a). | F1, T-37 | G4 part 2a | its J6c (W-11), after TCC's W-10 |

**TCC does not need** these, so the skill should not build them for us:
- `"contract": N` in every JSON output (one handshake per copy is enough);
- `deployment.py --json` (§7.4);
- the CLIs `naming parse`, `verify --json`, `verify_prediction`, `predict`, `timebase`, `eq_propose`, `resonalyze_vc --json` (TCC imports these);
- the verbs `session-reopen`, `capture-import`, `amp-gain`, `amp-changes`, `selftest`;
- SINCE/SURFACE tables, MIN/MAX or a binding API in the skill;
- `set-car` and `project_seed --json`, which already exist;
- a `--lock-timeout` flag (an old `process.py` would read it as usage);
- lock tokens, pids, read locks or exposed revision numbers;
- anything for T-20 (TCC binds no DSP rate).

`contract.py version --json` is optional; TCC uses it for diagnostics only.

### 4.2 What the skill needs from TCC

- **The surface TCC uses (§9).** It is the input to §7 items 2, 3 and 9, and it defines contract 1.
- **Release order for contract 1.** The handshake ships in W-9 (G5 S2). Its constant is set by one rule: **no installed TCC may see a contract number it does not know.**
  - If the skill confirms before TCC's W-9 release that contract 1 = the v3.1.x surface (§9), TCC ships `KNOWN_CONTRACT = 1` in W-9.
  - Otherwise W-9 ships it inert (`0`), and the skill's contract-1 tag waits for TCC's W-10 release through the release train (hub #246).
  - After contract 1, every bump waits for a TCC release that accepts it, with a beta candidate first.
- **Next-wave commitments** (§10, M2): TCC shows the refusals (J3) and the REW states (J4) in its wave after the skill ships them (skill W-8 → TCC W-10). It drops its own lock around self-locking children in the commit that re-pins to the skill's lock (skill W-9 → TCC W-11).
- **A candidate run before each skill tag TCC users would receive** (§10, M3).
- **The contract list itself** (§9 + §4.1) is settled between the two sessions, and the user confirms it then (`AUDIT-INDEX` §4.2). It is not a question now.
- **Every route sets `AUTOSOUND_SKILL_ROOT`** to the copy the project runs (G5), so the skill's own deployment check agrees with TCC.
- **Facts for the skill's own audit:**
  - **B9:** `reachable` is present, as null, when the reviewer is not configured; `model` and `ready` are absent.
  - **B10:** S1's row is partly wrong. TCC has `session_close`, `set_target` and `capture_knobs`. `capture-protective` and `listening-verdict` are UI-only (Q3), and `reviewer` is written by `call_critic`.
  - **T-19 is real for TCC** (six modules). **T-20 is low for TCC.**
  - **N17** (supersede ignored in three places) and **N19** (unknown flags absorbed) are bugs in the skill's code.
  - **K-4's preview** should also leave out `Project.save` and `.gitignore`.

## 5. Design choices for the M/L groups

For each group, the approaches are given with a recommendation. These are technical choices made by this session from the design passes; they are shown at the milestone for confirmation, not asked as questions (§7). Then one
plan per group follows (`writing-plans`).

### 5.1 G9 · Off the GUI thread

| approach | shape | effort |
|---|---|---|
| **Smallest** | One `call_off_thread(fn, on_done, on_failed, keep=)` helper in `ui/tcc/workers.py`, registered with `qt_shutdown`. Everything else is bounded or cached: a lock deadline, a `_osascript` timeout, a git cache, stat-memo reads, a debounced seed preview. An `INLINE` switch keeps the window builds synchronous in tests (196 in `test_main_window.py`, ~212 across the suite). | 33–40 h |
| **Clean** | `ui/tcc/offthread.py` `Lane` with three policies (QUEUE for journal writes, LATEST for previews and git, SHARE for key status and catalogues), a `CancelToken` that kills children, `ask.py` (no `exec()` anywhere — `open()` + `finished`, held until the window has started), a `core/project_lock.py` seam, `core/mcp_types.py`, and conftest guards (any import on a worker thread fails, a modal from a callback fails, children spawned on the GUI thread are counted). | ~60 h |
| **Balance** (recommended) | Three slices, each shippable alone. **S1 bound and cache** (no threads): one deadline for the writer lock, a `_osascript` timeout, git cached for callers not about git, stat-memo for the growth reads, a debounced and remembered seed preview. **S2 one helper:** a `Job`, plus one FIFO lane; G8 widens it to all of TCC's writes. It moves the journal writes (TA-1d/e), git status on reload (TA-1a), the reviewer-key read (TA-1b), the git buttons (TA-1g), `handoff.check` (TA-1h) and the feedback upload (TA-1n). **S3 two-phase construction:** modals out of the constructor and out of slots, lazy `mcp` (TA-7 M), the MCP start after the first paint (TA-1c), and the reviewer-key and model dialogs (TA-1j/k). | S1 7–9 h · S2 18–22 h · S3 14–18 h |

**Recommendation: Balance, with two pieces of Clean.**
- **Why Balance:** S1 removes the only two **unbounded** waits (the lock acquire and `osascript`) with no threading risk. It cuts git children from 7 to 2 per reload, which also means fewer console flashes on Windows. It can ship in W-9, before the skill's lock exists, and nothing in it is thrown away later.
- **Why not Smallest:** its `INLINE` test switch hides thread bugs in the 196 window tests.
- **Why not all of Clean:** three lane policies are more machinery than TCC needs today.
- **The two pieces of Clean:**
  - the **import-on-worker guard and the modal-in-callback guard** in `conftest`. These are cheap, and they enforce `install_report.py:11-16` and TA-6 mechanically;
  - the seam's name, **`project_lock.hold(project_dir, timeout_s)`**. This is the one place G8 later swaps for the skill's lock.

**The risk all three passes name first:** session ordering once `record_session` goes asynchronous. `_session_open` is set at `main_window.py:5370` and read at `:5233`. A quit between submit and done must neither skip `session_close` nor write it for a session that never started. The lane's FIFO order, with a flag the lane sets, is the guard, and this interleaving is the first test of S2.

**Test churn, sized:**
- **Most window builds are already insulated.** `conftest.py:461` sets `AUTOSOUND_TCC_MCP=0`, so the MCP start, the contract check, the CLI catalogue and the update check do not run in tests.
- **S3 therefore churns ~25 tests:**
  - 8 opt back into MCP;
  - ~6 plant `_mcp_server`;
  - 9 touch the reviewer key or probe;
  - 15 touch the catalogue.
  - `test_main_window.py:2786` pins the very constructor order S3 removes.
  - `tests/_windows.py` `quiet()` must learn the new helper.
- **S2 churns ~12 tests** that assert a `process_writer` call right after the action, for example `_record_stops`, `…answer_clicked_in_the_dialog_reaches_the_journal` and `…session_is_on_the_record_before_its_first_token`. They need a lane drain hook.
- **Rule for S3:** `_load_project`/`_load_process` stay in `__init__`. Moving them after the first paint would expose all ~212 window builds across the suite.

**An open point for the build:** the passes disagree on whether passing TCC's own bounded `runner=` to `upload_issue_asset` skips the gate's `gh` checks (vendor `side_effect.py:254,508`). Check this before T9. Until K-5 lands, moving the call off the GUI thread is enough.

### 5.2 G5 · The contract handshake and one method per project

| approach | shape | effort |
|---|---|---|
| **A — Smallest** | `vendor_loader.method_dir(project_dir)`. No link → TCC's own copy. A link to a **known** copy (TCC's own, any `_candidates()` root, or one the Arbiter approved once on this machine) → that copy. Anything else → `MethodMismatchError`. Writers and both session routes go through it. In-process reads stay on TCC's own copy, with a diagnostics row. `CONTRACT_VERSION` is read as text. Stop swallowing errors; a newest-tag CI job. | ~27 h |
| **B — Clean** | `core/method_contract.py` (MIN/MAX contract, a `SINCE` capability table replacing `LANDED_IN` and the probes, a `SURFACE` of names and keyword arguments) + `core/method_binding.py` (`Binding` state same/pinned/refused, `.can()`, `.plugin_root()`, `.session_env()`). `bind()` **activates** the pinned copy in-process too. `car_library` and the seed preview become CLIs. A blocking newest-tag job, plus a floor-version run. | ~45 h |
| **Balance** (recommended) | A's rules inside B's binding object. | ~30 h |

**The five decisions** (balance pass, recommended):

1. **In-process reads stay on TCC's own copy, and a diagnostics row names the project's copy when it differs.**
   - Modules are cached under a fixed name (`vendor_loader.py:297-299`), and five skill modules leave `rew_tool` on `sys.path` (T-19). Switching copies in-process can therefore mix two copies.
   - `main_window.py:2865-2888` opens the new window before closing the old one, so the two overlap.
   - Few projects are affected: every link TCC makes points at the one installed copy, which updates in place.
2. **Trusted links are only a known copy, or one approved once on this machine**, stored in QSettings and never in the project.
   - B's rule — "outside the project folder + passes the handshake" — checks what a copy looks like, not where it came from. A zip can carry a sibling folder plus a link to it, and HUB-050's reason is about origin.
   - Refused: a real folder inside the project, a target inside the project, a broken link, a 2.x copy, an unapproved outside path, a newer contract. A copy inside the project gets no approve button.
3. **No SINCE/SURFACE table now.**
   - Read `CONTRACT_VERSION` with `ast`, never by import. Keep `LANDED_IN`, adding `capture-supersede` and `handoff`.
   - No released copy (≤ v3.1.1) will ever carry a number, so a table keyed on it replaces nothing until contract 2.
   - **Add a flag check (N19, below).**
4. **`car_library` moves to `intake.py set-car` now.** The verb exists since v3.0.59 (`rew_tool/intake.py:1711`). This also settles N9 without waiting for J2.
   - `set-car` refuses a blank generation or body. The method's rule wins, and `save_car` already returns refusals as JSON.
   - The seed preview moves later, with J5 (K-4).
5. **The newest-tag CI job runs in its own workflow:** on push to main, nightly, and on demand.
   - It is not a required check on the wave's PR, because a skill tag that breaks TCC is not that PR's fault.
   - A red run stays red, with no `continue-on-error`.
   - It becomes a ship gate through G4/J6.

**Slices.**

| slice | what | when | effort |
|---|---|---|---|
| **S1 — writes and sessions on the project's own copy** | New `core/method_binding.py` (`Binding`; `for_project()` never raises; `require()`, `script(rel)`, `approve()`, `relink()`, `read_contract_version()`). New `core/method_cli.py`, which holds today's `_spawn` and its lock, so the G8 lock lands in one place; children get `AUTOSOUND_SKILL_ROOT` = the bound copy. All writers go through it, and N1 and `handoff` move into `process_writer`. `car_library` → `set-car`. Sessions: the SDK plugin path comes from the binding (F3d refuses with a sentence), and omp calls `require()` (N4). Diagnostics row with "approve on this machine" and "re-link to TCC's copy". The old entry moves to `.tcc/method-aside/<stamp>/`, never kept under `.claude/skills/`, where omp would still load it. **The flag check ships in the same PR.** | W-9, before the skill | ~19 h |
| **S2 — guard against a newer method** | The update press reads the tag's `contract.py` through `git show` and refuses a newer number ("update TCC first"). Stop swallowing errors: `inspect.signature` instead of the TypeError retry (F16-3); the verdict TypeError is logged and shown. `method-newest.yml`. | W-9 | ~6 h |
| **S3 — contract 1** | `KNOWN_CONTRACT = 1`, unless it already went out in W-9 (§4.2). A newer number is refused for writes, sessions and TCC's own copy at start. A floor-version CI entry. The exit-code table (T-23) separates "refused" from "crashed". | W-10, after the skill | ~5 h |

**N19 — the risk most likely to break, found by this pass.** `process.py` parses flags by hand and **silently absorbs flags it does not know**.
- In an older copy, `capture-start --origin X` turns `--origin` and `X` into expected titles (`rew_tool/state/process.py:3708-3730`), and `skip --superseded-by` becomes part of the reason text (`:3602-3609`).
- There is no usage error, so `_refuse_if_too_old` cannot see it.
- S1 exposes this for every approved older copy.
- **Guard:**
  - before spawning, check that each flag TCC sends appears in the bound copy's `process.py` text;
  - **first red test:** a fixture copy whose `process.py` lacks `--origin` → `start_capture(..., origin=...)` refuses before spawning. Today it spawns, and the flag becomes a title;
  - a pin test registers all ~17 flag literals in `process_writer.py`, on the model of `test_process_writer.py:206-219`.
- **Skill side:** unknown flags should be a usage error (exit 2). This goes with T-23.

**Two corrections to pass A:**
- "Is a link" is decided by `realpath(entry) != realpath(entry.parent)/entry.name`. `realpath != abspath` is wrong whenever a parent folder is a link: macOS `/var`, pytest temp folders, mapped drives.
- Windows junctions are proven on the Windows CI shard with a real junction. The existing test only monkeypatches.

### 5.3 G6 · Stop mirroring the method's readers

The two passes (smallest, balance) **agree** on the rule: where the method already writes the answer, TCC reads it. Where
it does not yet, TCC works it out in one place, and a parity test runs the method's own function on the same files.
Parity fixtures are written by a real `Process`/`PresetHistory`, never hand-written journals (T-29).

| slice | what | when | effort |
|---|---|---|---|
| **1 — TCC-only** | **D-1:** `config.bundled_profiles_dir()` returns the skill's `bundled_dir()`. The New-project picker uses `list_bundled()`. Delete `src/autosound_tcc/dsp_profiles/` and turn `test_packaging.py:292-303` around. **Superseded:** the fold learns `capture_superseded`. One `standing(round_)` (taken minus `superseded_by`, the rule at the skill's `process.py:819-822`) replaces 15 raw reads of `taken`; a source-scan test keeps it the only one. A past round's status comes from its closed event's `outstanding`. A take pops `skipped` (N16). **"Settled" written once:** in `measurement_view`. `_on_capture_check_done` reads the recorded verdicts instead of parsing `"UNUSABLE <title> — "`. **Parity tests** run against `capture_outstanding()` and the closed event. | next TCC wave; waits for nothing — v3.1.1 already has `bundled_dir`/`list_bundled`/`find_bundled(dir_=None)` | ~16 h |
| **2 — after the skill** | `process_view.capture_rounds()` becomes an adapter over the skill's new `Process.capture_history()`, and the fold (`process_view.py:110-185`) is deleted. `standing()` and the outstanding list call the skill's now-public `is_taken`/`outstanding`. The rounds are read once per refresh instead of ~4 times. | the wave after the skill ships S-R1/S-R2 and TCC re-pins | ~5 h |
| **3 — TCC-only, any wave after 1** | One reader per skill file. `project.json` goes through the skill's `Project.load()`, which already refuses unreadable files, and that is the seam where G7 shows the refusal. One `dsp_profile.json` reader. A guard: no raw `json.loads` of either outside `project_view.py`. Its literal scan lists 9 sites today; the wider list of parse sites is in `docs/audit/AUDIT-2026-10-VERIFIED.md` F6. **Stay TCC's own, with parity tests:** the journal tail in `control_layout` (polled every 2 s; parses only the last N lines) and `ledger_line`'s `slots.json`/`v_NNN.json` reads (the skill's equivalents raise where TCC must render). | any wave after slice 1 | ~9 h |

**Why the superseded bug is fixed now, not after the skill's reader.**
- The open-round half is permanent code.
- The past-round half is ~4–6 lines in the fold, written in the skill's own shape. Slice 2 deletes them; it does not redo them.
- The parity tests compare TCC with the method's answer, so they become slice 2's acceptance tests unchanged.
- Waiting would leave a wrong "done" on screen for one or two waves to save a few lines.

This passes the no-rework rule.

**New in this pass:**
- **N16:** a capture skipped and then taken stays "skipped" in TCC's closed-round history, because the skill pops `skipped` on a take (`process.py:1518`) and TCC's fold does not.
- **N17 (the skill's own bug, for S-c):** `unusable_captures` (`process.py:2223-2231`), the `capture-check` print loop (`:3759-3769`) and the closing event's `taken` list (`:2276`) ignore `superseded_by`.

**Risks.**
- **Most likely to break:** `measurement_view.py:465-471`. `verdicts_by_key` is built over every taken entry. An A17 title fix supersedes `w_R_1 (sw)` with `w-R_1 (sw)`, and both have the same `name_key`. The old row's "absent" verdict can then colour the corrected row. Build verdicts from `standing()` only, and test a same-key supersede.
- **Churn:** 9 tests feed checker text to `_on_capture_check_done` and move to state fixtures. A refused check, with no verdicts recorded, must report nothing rather than "everything is bad".
- **D-1:** `tests/test_resonalyze_import_dialog.py:59,252` open TCC's Helix file by path. The skill's file has a different name.
- **Slice 2 has no fallback** to the fold. An older method without S-R1 must be refused by G5's handshake, or two readers come back.

### 5.4 G8 · One lock for every writer

**Both passes agree on the shape.**
- **The lock belongs to the skill.** It lives inside every skill writer, at `<project>/.autosound/write.lock`.
- **What it covers:** it is held across load → write → append, never across REW, git or a subprocess.
- **capture-check** reads REW outside the lock and merges its verdicts under a second hold.
- **A busy CLI** waits up to `AUTOSOUND_LOCK_TIMEOUT_S`, then exits **75**: "busy, nothing written, safe to retry".
- **TCC takes no lock** around a child that locks itself. If it did, it would either deadlock on the same file or bring back today's ~240 s wait on another one.

**The balance pass corrects the smallest pass in four places** (recommended):

1. **TCC still needs one FIFO lane for *all* its short writes:** GUI writes, MCP `_record`, `close_session` and supersede.
   - The lock gives exclusion, not order. Each MCP call runs on its own thread (`mcp_server.py:107-119`), and `test_process_writer.py:51-57` already accepts "add_step lost the race and was refused".
   - capture-check stays off the lane.
   - **This widens G9's lane from "GUI-issued writes" to "all writes".** G9 slice 2 and G8 are built together in W-11 for this reason.
2. **Probe the copy the child actually runs** (`script_path().parents[1]`), not one global answer. Read a `PROTOCOL = 1` constant as text, not by import. A project pinned to an older method (G5) takes no lock, and TCC keeps its legacy lock for it.
3. **The timeout is set per writer call, never in `vendor_loader.child_env()`.** The omp session builds its environment from `child_env()` (`omp_session.py:950`), so it would inherit TCC's short wait.
4. **The child's subprocess timeout = the work budget + the lock wait.** Today both are one `timeout_s` (`process_writer.py:131,175`), so TCC kills a child that is still waiting for the lock and reports "timed out" instead of "busy".

**Legacy path:** for old or pinned methods, today's `_THREAD_LOCK` + flock stays, under one deadline. No `msvcrt` half: it would only guard TCC against a second TCC, and it would be thrown away later.

This is a clarification of the hub's agreed line («TCC deletes its own lock in the re-pin commit»), not a counter. The deletion holds for every child that locks itself. A project approved to run an older copy (G5, U10) has no skill lock, so only that path keeps the bounded legacy lock.

| phase | TCC tasks | when | effort |
|---|---|---|---|
| **0 — TCC-only, nothing thrown away** | One deadline over `_THREAD_LOCK` + flock, with a `Busy` answer; this is the same task as G9 S1 #1, built once. N1, the supersede going through `_spawn`; this is G5's task, built once. Race tests marked `xfail(not locks_itself, strict=True)`. | W-9 | ~1 day |
| **1 — the J2 wave, with the skill's lock** | `core/method_lock.py` (`BUSY_EXIT`, `locks_itself(script)`, per-call env). `_spawn` takes no lock when the child locks itself, and refuses at once inside an in-process hold (the deadlock guard). Exit 75 → `MethodBusy` in `profile_writer`, `config_writer`, `project_repo`. `car_library` → `Project.update(mutate)`, or the `intake.py set-car` CLI that v3.1.1 already has (G5). MCP `_record` and supersede go on the lane. The re-pin flips the xfails to pass. | W-11 | ~2–3 days, ~40% tests |

**Proof on Windows** (the existing `windows-latest` shard):
- **T1:** a holder process keeps the lock. TCC's write answers Busy in under 3 s, and the files are byte-identical. `git add -A` stages nothing from `.autosound/`.
- **T2:** 25 TCC writes and 25 bare-CLI writes race while a reader thread re-reads. The file always parses, and the plan and journal both hold 50.
- **T3:** a spawn inside a hold refuses at once.
- **T4:** with `locks_itself` forced False, the legacy path still passes.

**Risk most likely to break: Windows `os.replace` while TCC reads.** The lock orders writers, not readers. Python opens files without `FILE_SHARE_DELETE`, so the skill's replace gets `PermissionError`. The skill's T-8 retry must ship in the **same** tag, and T2's reader thread is there to catch it.

**Other risks:**
- Writes that used to wait now fail as busy. Lane batches get a wait of at least 60 s, and `close_session` at quit gets a short wait and a clear "not recorded" line.
- Locks may not cross a Mac↔VM shared folder; one line in the docs.
- **Fable reviews** both the lane and the lock paths before the tag.

## 6. Not worth doing — and why

| item | reason |
|---|---|
| TA-12 shorten the shutdown waits | The bounded-wait-then-detach trade of F-014/F-027, bought with two `SIGABRT`s. Listed only so nobody "fixes" it. |
| Split `core/` into subpackages (TB-F12) | No user-visible gain; a wave of merge conflicts (TB §6). |
| A big-bang `MainWindow` rewrite | The extractions that worked were incremental (TA §4, TB §6); G13 is the path. |
| Make the suite parallel because tcc#22 closed | Closed on evidence, not proof; HUB-049 still open (TB §6). Fix the documents only (G14). |
| Locks around `model_choices._CLI_CACHE` / `claude_sdk._SIGNED_IN` | Verified benign under the GIL; `None` already reads as "could not tell". |
| A high-DPI policy (TA-10) | Nothing shows a fault; A18 stays parked as recorded. |
| The Windows `msvcrt` half of TCC's **own** lock (TB-F9's TCC line) | The skill's lock (T-18) replaces TCC's lock in W-11. Building it now is the rework the user wants to avoid. |
| TCC-side validation of `gain`/`gaindB` in `write_rew_filters` | The skill's `set_filters` refuses and reads back (K-1). TCC only moves the call off the loop and maps the errors (G7). |
| Pin GitHub Actions by sha (TB-F13) | Two first-party actions; the manual bump cost outweighs the risk now. `--locked` is the part worth doing (G4). |
| macOS in the push run (TB-F13) | CI cost on every push. Which run the release gate reads is the hub's preflight (`ci-green`); TCC does not change its CI for it. |
| Patch mode tagging a commit no CI ran (TB-F13, `ship.py:637-656`) | The release gate is the hub's: its preflight already runs `ci-green` (AUDIT-INDEX §3, T-48). The suite runs locally first. During a wave the process does not change; the hub decides between waves. |
| Anything for T-20 in TCC | TCC binds no DSP rate in-process; tell the skill it is low for TCC. |
| TCC changes for S1 I-2 and B9's doc side | The prompt text and the doc are the skill's; TCC only follows (G11). |

## 7. Questions only the user can answer

Each comes with advice. Technical choices — thresholds, designs, test shapes — were researched, not asked.

1. **Q1 · How much of the audit goes on W-8's milestone, next to the collection's findings?**
   - **Advice:** G2 + G1 + the G13 ratchet only — about ten S tasks, roughly 1.5 days of build.
   - They are user-visible: a wrong preset is told to the model, a turn hangs, and a dead server goes unnoticed. They are TCC-only, and they touch nothing a joint group will redesign.
   - Everything joint waits for W-9 onwards, so W-8 stays small for its first run with the agents.
2. **Q2 · Permission ticks and `gate` stored in a project folder (F14, N5).** A project copied from someone else can arrive with `always_allowed` ticked, or with `gate=never`, which lifts the irreversible-command guard.
   - **Advice:** keep them per project, and have the trust check list them before the first session, the same way it lists `.claude/settings.json`.
   - The alternative is to move them to per-machine settings. That is simpler and safer, but loses per-project choices.
3. **Q3 · Should the model get tools for listening verdicts and protection captures (B10)?** Today they are UI-only: the Arbiter records them in TCC's dialogs.
   - **Advice:** keep them UI-only until the walk in the car (Q4) shows whether the in-car AI mode needs the model to record what the user says.
4. **Q4 · When to walk P2/P5/P7/P8 in the car.**
   - **Advice:** on the next car visit, before any car-sheet screen is designed. S3's own advice, and the J7 family waits for it.
5. **Q5 · A project linked to a method copy that is neither TCC's own nor an installed one** (a developer tree, a project from another machine).
   - **Advice:** TCC asks once per machine — "use this copy for this project?" — and remembers the answer on this machine. It never trusts a copy that sits inside the project folder.
   - **Alternatives:**
     - always refuse such copies, which is safest, but a developer tree then needs a re-link;
     - follow any link outside the folder. This is not advised: a zip can carry its own copy.

## 8. Appendix — every finding and its place

`→ Gn` = planned in that group. `drop` = not worth doing (§6). `skill` = the skill's alone, so TCC only follows.

| finding | place | finding | place |
|---|---|---|---|
| TA-1a git on reload | G9 S1 (cache) + S2 | TB-F1 constraints | G4 part 2 + G12 |
| TA-1b reviewer-key lock | G9 S2 | TB-F2 newest tag, 3-file check, swallowed renames, `_path` | G5 |
| TA-1c MCP start wait | G9 S3 | TB-F3a omp death | G1 |
| TA-1d writer lock (~240 s) | G9 S1 + G8 | TB-F3b SDK `is_error` | G1 |
| TA-1e session/protective/listening writes | G9 S2 | TB-F3c MCP death | G1 |
| TA-1f seed preview | G9 S1 (debounce) + K-4 | TB-F3d plugin `"None"` | G5 |
| TA-1g git buttons | G9 S2 | TB-F3e swallowed confirm errors | G1 |
| TA-1h handoff.check | G9 S2 | TB-F4 `write_rew_filters` | G7 (+ K-1) |
| TA-1i self_check git | leave (developer checkout only) | TB-F5 `.tcc/` stores | G3 |
| TA-1j reviewer-key dialog | G9 S3 | TB-F5 process-state | G7 (+ K-2) |
| TA-1k omp catalogue | G9 S3 | TB-F5 no fsync | skill (T-8, T-17) |
| TA-1l `_osascript` | G9 S1 | TB-F6 readers, superseded | G6 |
| TA-1m place_terminal_left | leave (bounded 5 s, macOS, after a layout switch) | TB-F7 two methods write one project | G5 |
| TA-1n `gh api` per screenshot | G9 S2 + K-5 | TB-F8 D-1 | G6 slice 1 |
| TA-2 streamed text | G2 | TB-F9 two writers, no Windows lock | G8 (its TCC `msvcrt` half: drop) |
| TA-3 full ↻ per write | G2 | TB-F10a stray tag | G4 |
| TA-4 S curve bank | G10 | TB-F10b hints (+ N6) | G4 |
| TA-4 M `setData` | G10 | TB-F10c unsigned fallback | skill (T-37), already decided by the release-safety rule (unknown = refusal); TCC's updater already refuses without a tag (`updates.py:1339`); CHANGELOG line in G14 |
| TA-5 stale snapshot | G2 | TB-F11 test seams | G12 |
| TA-6 constructor | G9 S3 | TB-F12 MainWindow, branding, mock data | G13 |
| TA-7 S `tip_html` | G10 | TB-F12 split `core/` | drop |
| TA-7 M lazy `mcp` | G9 S3 | TB-F13 Linux non-blocking | G14 doc line (after HUB-049) |
| TA-8 MainWindow extractions | G13 ("settled": G6) | TB-F13 macOS on push | drop (§6) |
| TA-9 group semantics (+ N15) | G13 | TB-F13 pairing, `--locked` | G4; patch tag: hub (§6) |
| TA-10 font, DPI, scipy comment | G14 (DPI: drop) | TB-F13 actions by sha | drop |
| TA-11 marker drag | G10 | TB-F14 ticks (+ N5) | G11 + Q2 |
| TA-12 shutdown | drop | TB-F15 docs (+ N7) | G14 |
| TA growth reads | G9 S1 | TB-F16-1 bare `subprocess.run` | G1 |
| TA caches `_CLI_CACHE`, `_SIGNED_IN` | drop | TB-F16-2 curve message | G14 |
| TA `capture_order` key | G14 | TB-F16-3 TypeError retry | G5 S2 |
| FF-01 1 | G13 | TB-F16-4 copied REW wording | G14 |
| FF-01 2, 3, 4, 7, 9 | fixed | TB-F16-5 "never raises" | G1 |
| FF-01 5 (HUB-049) | open in the hub; no TCC task | TB-F16-6 `.mcp.json` | G3 |
| FF-01 6 mock-data residue | G13 | N1 supersede outside lock | G5 S1 |
| FF-01 8 stale comments | G14 | N2 superseded in open round | G6 |
| J1 contract | G5 + §4 | N3 omp system rules | G11 |
| J2 lock | G8 | N4 two routes, two copies | G5 |
| J3 unreadable | G3 + G7 | N8 unbounded lock | G9 S1 / G8 phase 0 |
| J4 REW | G7 | N9 `car_library` in-process | G5 S1 (`set-car`) |
| J5 seed | G9 + K-4 | N10 `gh api user` in preview | K-4 |
| J6 install | G4 | N11 B10, N12 B9 | §4.2 facts; Q3 |
| J7 P2, P5, P7, P8 | waits (Q4) | N13 contract copy | G11 (+ I-5) |
| J8 opener, prompt, copies | G11 + G5 | N14 preflight prose | G11 (+ I-2) |
| S1 I-21 folders | G11 (+ skill) | N16 skipped-then-taken | G6 slice 1 |
| S2 T-20 | drop for TCC | N17 skill supersede bug | skill (§4.1 #6) |
| S2 T-19 | §4.1 #2 | N18 `sessions.json` | G3 |
| S2 T-27 | §4.1 #2 | N19 unknown flags absorbed | G5 S1 (flag check) + skill (§4.1 #3) |
| S2 T-36, T-48 | hub (AUDIT-INDEX §3) | N20 `verify.py:33` | §4.1 #2 |
| | | N21 falsely green test | G7 |

## 9. The surface TCC uses (the input to contract 1)

From a read of every call site at `f58d208`. Full detail with file:line: `docs/audit/AUDIT-2026-10-SURFACE.md`.

- **In-process, 15 modules** loaded by path through `core/vendor_loader.py` (`contract.py` deliberately not):
  - `rew_api`: reads, `set_filters`, `find_measurement_id`, `rename_measurement`, `FINEST_SMOOTHING`, `is_swept`, `duplicate_titles`;
  - `naming`: `parse_name`, `name_key`, `Glossary.for_project` and members, `generate_name`, `expected_groups`, `validate_series`, `METHODS`, `canonical_title`/`_code`, `explain_name`;
  - `state/process`: `Process.load`/`events`/`session_closed`/`protective_record`, `PHASES`, `PHASE_TITLES`, `EV_*`, plus the event names and fields of TCC's fold;
  - `state/state`: `PresetHistory.head`/`load`/`_path`, `SnapshotError`, `identity_error`, `project_channels`;
  - `project`: `Project.load`/`save`, `parse_impact`, `PROJECT_TYPES`, `project_type`;
  - `dsp_profile`: `load_profile`, `validate_profile`, `FIELD_VOCABULARY`, `CAPABILITY_CHECKLIST`, `processing_rate_hz`, `bundled_dir`, `list_bundled`;
  - `verify.verdict(name, measurements=, f_low=, f_high=)`;
  - `dsp_math.apf1_response`/`apf2_response`;
  - `resonalyze_vc.load_session`/`convert`;
  - `project_seed.seed`/`describe`/`dsp_of`;
  - `eq_export.export_eq`;
  - `protective.legs_of`/`should_de_embed`/`matters_at`/`de_embed`;
  - `listening` (characteristics, tracks, links, routes, check, `PATTERNS`, `CHEAT_SHEET`);
  - `gates/side_effect` (form constants, `form_answers`, `verify_form_reply`, `upload_issue_asset`);
  - `car_profile.find_prior_projects`/`body_slug`/`find_bundled_car`.
- **CLIs:**
  - `state/process.py`, 25 verbs (23 through `process_writer`, plus `capture-supersede` and `handoff`): `enter-phase, add-step, start, done, skip, block, reviewer, capture-protective, listening-verdict, listening-verdicts, target, decision, session-start, session-close, capture-start, capture-knobs, capture-check, capture-taken, capture-skip, capture-close, check, plan, show, capture-supersede, handoff --json`, plus the flags in `process_writer.py`;
  - `dsp_profile.py start|draft|set-field|reset-field|finalize|find-bundled`;
  - `state/state.py config save`;
  - `project_repo.py init|status --json`;
  - `contract.py check --json [--no-rew]` (keys: `ok, project_dir, files[], cross_checks{rew, continue_head, glossary_vs_ledgers, tiers_vs_profile}, inherited, sources_gone, complete`);
  - `intake.py set-car` (from G5);
  - `intake_form.py serve` (the URL line);
  - `scripts/upkeep.py --json …`;
  - `scripts/autosound_ai.py critic|advisor|ask|doctor|key …` (exit codes 0–4, the stderr markers).
- **Files TCC parses itself today** — readers that move to the skill's in G6, or are kept with a parity test:
  - `project.json`, `dsp_profile.json`, `journal.jsonl`, `slots.json`, `v_NNN.json`;
  - `references/patterns/target-curves/*`;
  - `.claude-plugin/plugin.json` `version`.

## 10. Settled with the skill — hub #255 (one round)

The hub matched the two plans (`hub/docs/AUDIT-PLANS-MATCH-2026-10.md`; skill `472318c`, tcc `c8e9e3d`). These are
TCC's answers to its rows, with evidence at `f58d208`. §1 of the match is agreed and not reopened.

### M2 · J2/J3 staging — **agree with the skill, on one condition**

Neither J2 nor J3 needs to ship in one wave on both sides. TCC withdraws «one wave», and its half follows a wave later (§3).

**J3 — what today's TCC does when the skill starts refusing:**
- Every write goes through `_run`. A non-zero exit raises `ProcessWriterError` carrying the child's own stderr (`core/process_writer.py:186-193`). So a refusal from `_write`'s guard reaches the strip and the model verbatim.
- `contract_check.py:78` renders `valid: False` entries.
- What stays wrong until G7 is only the display. The plan panel shows an empty plan, because TCC's reads use the non-strict default (`state/process_view.py:79`). `report_phase` tells the agent to `enter_phase` (`core/mcp_server.py:1483-1497`). That write is then refused by the guard, so nothing is lost.
- A strict `show` does not touch TCC: nothing in `src/` calls `process_writer.state()`.
- A strict `session-close` that refuses with exit 1 reads in TCC as "not recorded", with the skill's own text (`close_session`, `:467-471`). That is honest.

**J2 — the skill's lock inside its children is safe for today's TCC:**
- TCC's flock sits on another file (`process/.process-write.lock`, `:106-147`), so a child that locks itself never waits on its parent.
- The child's wait (10 s) is under TCC's child timeouts: 20 s, or 120 s for capture-check (`:45`, `:574`).

**The condition — evidence for M1 (the skill's row): busy must not be exit 1.** TCC reads exit 1 as an *answer* in two verbs:
- `capture-supersede`: `title_fixes.py:74` returns `returncode in (0, 1)` as "done". A busy supersede that wrote nothing would read as done, silently.
- `session-close`: exit 1 means "open work, here it is". A busy stop would show the busy line as the list of what is open.

Any code other than 0 and 1 reaches TCC as an error carrying the skill's sentence, which is right. TCC asked for 75; any free code will do.

### M3 · What makes «skill first» safe — **TCC commits to N2**

- **The risk is real.** Until G5 S2 (W-9), an installed TCC takes the newest `v3.*` method tag on install and update (TB-F2; `core/updates.py:62,532,606`). So a skill tag reaches TCC users the day it is out, and TCC's CI never saw it.
- **N2, as TCC will run it.** For every candidate tag the skill names on the bus before a tag — J1a and J4a in its W-8, and every later one users would receive:
  - The tcc session runs, in a scratch clone of tcc with the submodule at the candidate (never the main tree's pin):
    - the boundary set with `-n 4`: `test_vendor_loader`, `test_process_writer`, `test_skill_selftests`, `test_rew_api_shapes`, `test_contract_check`, `test_capture_import`, `test_dsp_state`, `test_mcp_server`, `test_process_view`, `test_measurement_view`, `test_title_fixes`, `test_handoff`, `test_rew_bridge`;
    - then the whole suite once, serially, with the VM suspended.
  - It answers on the skill's ticket: pass, or the failing tests with the reason.
  - This is a test run, not a build, so it fits W-8's collection.
- **Known in advance:**
  - for J4a, `tests/test_rew_api_shapes.py:54-67` must answer GET /filters with what was written (the skill's R3). That is a TCC test change, done in the re-pin (W-9);
  - for J1a, a shared module object changes what tests that patch module globals see (M4).
- **Residual risk:** N2 covers what TCC's tests cover. The seams G12 names (no wheel install, no MCP over HTTP, doubles never compared) stay blind until W-12.

### M4 · `sys.path` edits — **TCC moves to the skill's timing: J1c (W-11)**

**Nothing in TCC breaks between W-10 and W-11 if the edits stay.**
- G5's recommended binding keeps in-process reads on TCC's **own** copy (§5.2, decision 1). It never activates another copy in-process. Every `sys.path` edit therefore adds the same `rew_tool` that TCC already loads.
- No `rew_tool` module name matches a top-level module TCC imports, or a package in TCC's installed tool environment (checked by name, 2026-10-04). TCC catches no `NamingError` across copies (`grep NamingError src/`: none).
- TCC's earlier «by W-10» came from the clean design, which switched copies in-process. That design is not the recommended one.

**What TCC does need, and when:**
1. **In J1a (skill W-8):** `siblings.py` keeps its registry **in `sys.modules`**, under names whose `__file__` lies inside the skill folder. Otherwise TCC's `reload_loaded` (`core/vendor_loader.py:356-401`), which drops by file prefix after an in-app method update, leaves adopted copies behind, and the window would mix the old and the new method. If the registry is a private dict, it needs a `reset()` that TCC calls in `reload_loaded`.
2. **J1c's prerequisite (TCC, W-10):** `tests/conftest.py`'s `_no_live_rew` (`:183-220`) re-points `REW_API_URL`, a bare `rew_api` in `sys.modules`, and TCC's own copy. It moves to «the one shared `rew_api`»: ask `siblings` for it by real path, or patch every module whose `__file__` is the skill's `rew_api.py`. That covers the copy J1c leaves. This is a test-only change, and it is in §3's W-10 row.

### M9 · The skill's questions

- **N3 — TCC does not quote or inject any SKILL.md section.**
  - TCC loads the skill whole: as a plugin with `skills=["autosound-tuning:autosound-tuning"]` (`core/tuning_session.py:357-359`), or as the project's `.claude/skills` link for omp.
  - Its own prompt (`tuning_session.py:91-141`, `core/openers.py:35-57`) names no section. "SKILL.md" appears in `src/` only in comments.
  - S2's cut is free, with one condition: TCC depends on **paths**, so moving any of these four needs a bus ticket first:
    - `references/patterns/target-curves/target_curves_visualizer.html` (`ui/tcc/main_window.py:280-283`);
    - `references/patterns/target-curves/target_curves_guide.md` (`core/guide.py:29`);
    - `references/patterns/target-curves/*.txt|.html` (`core/target_curve.py:90,133-167`);
    - `assets/data-contract-template.md` (`core/critic.py:240`).
  - One more dependency: the read-root grant lets the agent read anything under the skill folder without a click (`tuning_session.py:143-156`). It relies on reference files staying inside that folder.
- **N4 — `describe()` does not cover the New-project dialog.**
  - The dialog moved off `describe()` on purpose. `describe()` counts what the **source** holds. The note must say what **lands**:
    - channels, which depend on the same-processor rule;
    - findings and questions when ticked;
    - the profile copy;
    - the drivers' Fs.
  - See `ui/tcc/new_project_dialog.py:418-433` (the docstring says why) and `:484-506` (`report.channels`, `amps`, `flaws`, `questions`). Fs is read off the preview's `project.json` because the report has no count (tcc#93, `:105-124`).
  - `describe()` is used only to tell a project folder from a non-project folder.
  - So the skill's J5 is needed as K-4 says: `seed(..., dry_run=True)` returning the `Seeded` record, **plus the Fs count**, writing nothing.
- **N8 — agree, nothing on TCC's side.** TCC never reads or shows `goal.design_path` (`grep design_path src/ tests/`: none). The question text lives in the skill's intake form, which TCC only serves (`core/intake_form.py`). The rewording is the skill's alone. TCC does not read the field as data either, so «TCC reads it» in the skill's S3 can go.

### M10 · Constraints order — **agree: TCC first, in W-10**

- G4 part 2 is split. **2a** (`constraints.txt` with every tag from W-10, held equal to `uv.lock`; the updater's `-c`) moves from W-12 to W-10, a wave before the skill's J6c (W-11). **2b** (the scheduled fresh-resolve job) stays in W-12 with G12.
- The installers and TCC's updater read the file from the **signed tag's tree** to disk and pass a local path. uv 0.12.3 here documents `-c` as «requirements files», so a URL is not relied on.

### Named once — not in the match's rows

- **§4.1 #6, the round reader** (`Process.capture_history()`, public `is_taken`/`outstanding`) has no group in the skill's plan and no row in the match. G6 slice 2 waits on it. If the skill does not take it, the fold stays TCC's own with parity tests, so nothing breaks.
- **The T-35 twin** the skill found in TCC (`updates.py:830`, `:767-773`) is taken into G4 part 1.
- **The legacy lock** for a project approved to run an older copy: §5.4, a clarification of §1, not a counter.
