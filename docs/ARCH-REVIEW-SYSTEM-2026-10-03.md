# Architecture review of the whole TCC application — 2026-10-03

**Base:** `main` at **`f58d20868a13d8d33d9c30170f97a72af8ff5822`** (2026-10-03 17:10 +0200, "F-093: v1.1.1's
GitHub Release published and Latest…"), which is release **v1.1.1**, paired with method **v3.1.1**
(`vendor/autosound-tuning-skill` at `e8dabf7`). This session's branch started at that commit. No code changed;
this file is the only output.

**Scope:** `src/`, `tests/`, `scripts/`, `.github/workflows/ci.yml`, `pyproject.toml`/`uv.lock`, and the parts of
the vendored method that TCC calls. Read first, as instructed: `CLAUDE.md`, `docs/ARCHITECTURE-NOTES.md`,
`docs/TCC-Concept.md`, `docs/DATA-MODEL-DECISIONS.md`, `docs/DATA-MODEL-INVENTORY.md`,
`docs/CROSS-PLATFORM-PLAN.md`, `docs/INSTALLER-TZ.md`, `docs/DECISIONS-W-2.md` (the only `DECISIONS-*.md`),
plus `docs/TESTING.md`. Recorded decisions are treated as settled. Where a finding touches one, it says so.

**How claims were checked.** Every finding gives `file:line`. Each piece of evidence carries a mark:

- ✔ — re-verified in this session by the reviewer, by reading the code, a probe script, or a targeted run;
- ◐ — verified in this session by one of four focused audit passes (grep, read, probe or run; logs in the
  session), and not re-read line by line by the reviewer;
- ✘ — could not be verified here, with the reason given.

Effort: **S** = about a day including tests; **M** = a few days, several files, or a cross-repo ticket;
**L** = incremental, over more than one wave.

---

## 1. Summary

1. **The layering holds, and a test enforces it.** `core/` and `state/` never import `ui/` (`tests/test_packaging.py:96`). The CLI half is 30 modules that load without Qt. No module imports another in a cycle at load time.
2. **The biggest risk is distribution.** What a user installs is not what CI tested. Dependencies are re-resolved at install time, so a fresh install today gets claude-agent-sdk 0.2.163 against the 0.2.145 that is locked and tested. The method is the newest `v3.*` tag, not the pinned one.
3. **Several boundaries fail silently.**
   - When omp dies, the next turn hangs.
   - An SDK error result reads as a normal end of turn.
   - `write_rew_filters` can report a flat filter as applied, and it blocks the MCP event loop while it waits for REW.
4. **TCC's own readers and stores lose data quietly.**
   - One bad byte wipes a project's TCC settings.
   - A corrupt `process-state.json` shows as an empty plan, and the next write makes that permanent.
   - A superseded capture is shown as done.
5. **D-1 is not implemented.** TCC ships its own older DSP profile folder and passes it to the skill, overriding the skill's library. As a result the Musway profile cannot be reached from TCC.
6. **The tests are strong where they look and blind at the seams.**
   - Strong: 3,805 tests; `state/` coverage 90–100%.
   - Blind: no wheel is built, the base install is never run, MCP is never exercised over HTTP with its token, and the SDK and REW test doubles are never compared with the real APIs.
7. **FF-01 (2026-09-06) re-check:** of its nine items, six are fixed (some partly), two have changed (one fixed with a new drift, one tightened but still open), and one is still present. `main_window.py` has grown to 6,465 lines.
8. **Recommended order:** first the small fixes at the boundaries, which make silent failures loud; then pin what gets installed and test the method that users actually receive.

---

## 2. Module map and layering

### 2.1 The map

```
entry points ─────────────────────────────────────────────────────────────────────────────────────
  autosound-tcc / autosound-tcc-gui → app.main (app.py:376)                       needs [gui]
  tuning-session        → tuning_session_cli (120 lines)                          base (+[claude] to talk)
  dsp-profile-interview → dsp_profile_interview (69 lines)                        needs [claude]

ui/tcc/   47 modules · 37,532 lines · PySide6, pyqtgraph, numpy
  main_window.py  6,465 lines — MainWindow (:753), 221 methods, imports 78 internal modules
  panels & dialogs (curve_view 3,588 · detail_pane 2,125 · diagnostics_panel 1,846 · dialog_panel 1,509 …)
  i18n.py 5,295 (4 languages, parity-tested) · theme.py 2,176
  qt_bridge.QtUiBridge — the ONLY place the MCP server thread reaches the GUI (signals + locked snapshot)
  workers.py — QThread workers;  mock_data.py — prototype constants still imported by 3 panels
        │  ui → core: 127 import edges · ui → state: 25
        ▼
state/    11 modules · 3,452 lines — read-only views over skill-owned files (frozen dataclasses)
  project_view, dsp_state, process_view, measurement_view, ledger_line, models, …
        │  state → core: 20 edges (config, vendor_loader, child, capture_import)
        ▼
core/     55 modules · 21,787 lines — four kinds of module in one package:
  infrastructure     config, vendor_loader, child, app_log, project_settings, signal_bus, session_registry
  agent + MCP        mcp_server (FastMCP over loopback HTTP + token), tuning_session (Claude Agent SDK),
                     agent_session (onboarding), omp_session (omp JSON-RPC), critic, shell_gate, model_choices
  skill-CLI drivers  process_writer, profile_writer, config_writer, project_repo, intake_form
  domain math        curve_sum (numpy), allpass, protective (scipy), delay_bank, target_curve, capture_import
  OS / distribution  updates, desktop_entry, windows_identity, macos_identity, install_report, self_check,
                     terminal_launcher, default_terminal
        │  importlib (15 files under autosound_tcc._vendor.*) and subprocess (8 skill CLIs)
        ▼
vendor/autosound-tuning-skill   (submodule, v3.1.1; NOT in the wheel)
  rew_tool/rew_api.py  — the REW HTTP client (urllib, 5 s timeout, no retry)
  rew_tool/state/{state,process}.py, project.py, dsp_profile.py, naming.py, contract.py, …
```

Sizes were measured with `wc -l` ✔. The import graph was built from an AST walk of every module in `src/`
(script in the session scratchpad) ✔.

### 2.2 Dependency direction

| from → to | edges | all lazy (imported inside a function)? | note |
|---|---|---|---|
| ui → core / state | 127 / 25 | no | the intended direction |
| state → core | 20 | no | `state` sits *above* core's infrastructure, *beside* its services |
| core → state | 6 | **yes** | `config.py:233` → `ledger_line`; `protective.py:129,181` → `process_view`; `title_fixes.py:79` → `measurement_view` ✔ |
| core → app, ui → app | 2, 1 | **yes** | `desktop_entry.py:93`, `windows_identity.py:251`, `main_window.py:6221`, all to reach `APP_DISPLAY_NAME` / icons in `app.py:23-32` ✔ |
| core/state → ui | **0** | — | enforced by `tests/test_packaging.py:96`, with a test proving the guard turns red (`:106`) ✔ |

**The light core** is the set of modules imported at load time by `tuning_session_cli`, `dsp_profile_interview` and `core.mcp_server`. It comes to **30 modules and 11,646 lines**, with `mcp` as its only third-party import ✔.
- `tests/test_packaging.py:118` imports it in a fresh interpreter with PySide6, pyqtgraph, shiboken6 and numpy blocked ✔.
- The CLI picks up the window's settings store through an optional side-effect import (`tuning_session_cli.py:37-40` → `app_settings.py:31` `config.use_settings`). That is deliberate (HUB-051), but it is injection by import, not by an argument ✔.

**Import cycles.** There are none at load time. Three exist through imports inside functions, and all are deliberate and commented ✔:

| cycle | edges that close it |
|---|---|
| `app` ↔ `core.desktop_entry` / `core.windows_identity` / `ui.main_window` | `app.py:19` imports `windows_identity` at load time; `windows_identity.py:67` imports `desktop_entry` at load time. Both reach back into `app` only inside functions for the branding constants (`desktop_entry.py:85-95` explains why). |
| `critic` ↔ `availability` ↔ `model_choices` ↔ `reviewer_key` | `model_choices.py:34` and `reviewer_key.py:40` import at load time; the rest happens inside functions (`availability.py:145,171,213`, `critic.py:388,863`, `model_choices.py:819,907`, `reviewer_key.py:245`). |
| `agent_session` ↔ `tuning_session` | `tuning_session.py:35` imports at load time; `agent_session.py:307` imports `DEFAULT_MODEL` inside a function. |

### 2.3 How the rest is put together (facts; the findings come in §3)

**Persistence.** A project is a folder.
- **Owned by the skill and written only through the skill's code:** `project.json`, `dsp_profile.json`, `state/…/v_NNN.json` with `slots.json`, and `process/process-state.json` with `journal.jsonl`. TCC runs the skill's CLIs as subprocesses to write them (`core/process_writer.py:150-183` ✔, `profile_writer.py`, `config_writer.py` ◐), or runs the skill's own code inside its process (`car_library.py:132-151` ◐).
- **Owned by TCC:** `.tcc/` (session registry, signal bus, settings, import store, critic log) and `.mcp.json`.
- **Atomicity and versioning:** every TCC store is written atomically (temp file plus `os.replace`) ◐. Nothing anywhere calls `fsync` ◐.
- **Refresh:** a `QFileSystemWatcher` reloads the window, coalesced at 400 ms (`main_window.py:3753-3842` ◐).
- **App-level settings:** `QSettings` in INI format, with no version key ◐.
- **D-6 ("the skill writes, TCC reads") holds for skill data,** and the MCP surface audits itself against it (`mcp_server.py:23-41` ✔).

**External boundaries.**
- **REW:** reached only through the skill's `rew_api` (`rew_bridge.py:36-44` ◐), except that `write_rew_filters` calls it directly.
- **Claude:** the optional claude-agent-sdk. Its names are bound into module globals at first use (`claude_sdk.bind`), and the names TCC uses are pinned against `SDK_NAMES` (`tests/test_packaging.py:441` ✔).
- **omp (Gemini, Codex):** a JSON-RPC subprocess, protocol v2 (`omp_session.py:131` ◐).
- **External agent CLIs:** they dial in to TCC's MCP server over loopback HTTP and present a per-session token (`mcp_server.py:1510-1550`, `:1626-1662` ✔).
- **The method:** 15 files imported under `autosound_tcc._vendor.*`, plus 8 CLIs run as subprocesses (`vendor_loader.py:141-196`, `:292-317` ◐).
- **GitHub:** bounded `git ls-remote` (`updates.py:364-401` ◐).

**Error handling.** Timeouts, cancellation and per-item isolation are careful almost everywhere.
- Of 181 handlers that catch `Exception`, 167 carry a written reason, and there is no bare `except:` ◐.
- The weak spots are the places where a change outside TCC turns into *silence*, not into an error (§3, F3–F6).

**Packaging and release.**
- **The wheel** contains only `src/autosound_tcc` (`pyproject.toml:110` ✔): 133 entries and no file from `vendor/` (◐, built with `uv build --wheel`).
- **Install and update** go through the method's `install.sh`/`install.ps1` and the in-app updater. Both run `uv tool install --python 3.12 --upgrade "autosound-tcc[gui,claude] @ git+…@<newest signed v* tag>"` (`updates.py:87-105` ✔; vendored `install.sh:1255-1292` ✔).
- **Releases** go only through `scripts/ship.py`. It calls the hub's preflight, checks the CHANGELOG, the method pin and its published tag (TCC-021), runs the full suite serially, and makes an SSH-signed tag (`ship.py:161-180`, `:234-302`, `:394-445`, `:466-542` ◐).

**Tests.**
- **Size:** 98 files and 3,805 collected tests ◐.
- **Kinds:** about 63% Qt widget tests, about 37% pure core/state/script tests, about 45 subprocess call sites, one replay test (omp), and roughly 40–50 tests that read source text ◐.
- **Isolation:** `tests/conftest.py` redirects QSettings, `HOME`, the platform folders, the project folder, the agent CLI and critic probes, update checks and REW (`conftest.py:182-228`, `:404-557` ◐).

---

## 3. Findings, ranked by impact

### F1 — What a user installs is not what CI tested: dependencies are resolved fresh at install time · **High** · Effort **S–M**

**Evidence**
- **The install command has no lock and no constraints.** The installer and the in-app updater both run `uv tool install … --upgrade "autosound-tcc[gui,claude] @ git+…@<tag>"` (`core/updates.py:87-105` ✔; `vendor/autosound-tuning-skill/install.sh:1291-1292` ✔).
- **`uv tool install` has no `--locked`/`--frozen` option, but it does take `-c/--constraints`.** Checked against uv 0.8.17's help ✔. The installer pins uv 0.12.10 (`install.sh:84` ✔); that version's flags ✘ (not installed here).
- **Locked versus fresh, today:** `uv.lock:203-204` locks claude-agent-sdk **0.2.145**, `:396-397` mcp **1.29.1**, `:1218-1219` uvicorn **0.52.4** ✔. A fresh resolve on 2026-10-03 gives **0.2.163 / 1.30.0 / 0.54.0** ◐.
- **The bound is wide on purpose:** `pyproject.toml:52` `claude-agent-sdk>=0.2,<1`, with the comment at `:50` "the whole 0.x line is the risk surface" ✔.
- **What the SDK pin actually covers:** the SDK test pins exported *names* only (`tests/test_packaging.py:441-476` ✔). Message fields are read by duck typing (`tuning_session.py:444-496` ◐), and the test doubles for SDK messages are never compared with the real classes (`tests/test_tuning_session.py:208-224`, `:491-505` ◐).

**Risk.** A 0.x SDK release changes a message field. Every fresh install and every "Update TCC" from then on gets it, and turns render empty or end early. CI stays green, because CI only ever runs the locked 0.2.145. The signed tag protects TCC's source, not its dependency set.

**Recommendation.**
- Ship a constraints file exported from `uv.lock` (for example `uv export --extra gui --extra claude --no-hashes`) with each tag, and pass `-c <it>` in `tcc_install_command` and in the method's installers.
- Add a scheduled CI job that installs the built wheel with a *fresh* resolve and runs the SDK, omp and MCP boundary tests. That job is the early warning when the bounds start to bite.
- Check first: whether uv 0.12.10 accepts a URL for `-c`, or whether the file has to be fetched to disk.

**Decision touched.** The bounds policy (`pyproject.toml:23-29`, 2026-08-12, "bounds are the next major/minor that may break us") is kept. Constraints add reproducibility *inside* the bounds; they do not narrow them.

---

### F2 — The method users run is the newest `v3.*` tag; nothing checks it is compatible beyond three files existing · **High** · Effort **M**

**Evidence**
- **Users get the newest method tag, not the pin.** The installer takes the newest `v3.*` tag (`install.sh:1017-1026` ✔), and so does the updater (`updates.py:62` `SKILL_TAG_GLOB = "v3.*"`, `newest_tag()` `:532-534` ✔).
- **"A skill" is decided by three files.** A folder counts as the method if it has `rew_api.py`, `project.py` and `contract.py` (`vendor_loader.py:65` ◐).
- **The release check proves the pin is tagged, and nothing more.** TCC-021 shows the *pinned* commit carries a published tag (`scripts/ship.py:394-445` ◐; `docs/TESTING.md:314-332` ✔). The suite only ever runs against the pin.
- **Older methods are handled; newer ones are not.**
  - Handled: `process_writer.LANDED_IN` with `_refuse_if_too_old` (`process_writer.py:51-75`, `:474-497` ✔), and `getattr` checks for newer names such as `SnapshotError` and `identity_error` (`state/dsp_state.py:651` ✔).
  - Not handled: a *newer* method that renames or re-signs a function TCC calls in-process. That surfaces as a `TypeError` at the call site, and some of those are swallowed. Example: `capture_import.py:524-529` passes `f_low`/`f_high` to `verify.verdict` and swallows any failure ◐.
  - The coupling surface is about 40 names across `naming`, `process`, `state`, `dsp_profile`, `rew_api` and friends (◐, AST inventory).
- **Private API:** TCC calls one private method of the skill, `history._path(...)` (`state/dsp_state.py:619` ✔).

**Risk.** The method ships `v3.2.0`, which changes a signature or a file field that TCC reads in-process. Every installed TCC that updates its method breaks in that spot the same day, and no TCC CI run ever saw that combination.

**Decision touched.**
- `docs/INSTALLER-TZ.md:189-204` (§4, 2026-07-30) said the submodule pin is the single source of truth and the installer takes "the latest *verified*" method. That rule was never built.
- `docs/ARCHITECTURE-NOTES.md:447-456` (§8.2, 2026-08-27) later settled that "the dependency between the app and the method is at the API level, not the sha", and it records that a sync gate on TCC's tag was rejected (hub `RELEASE-CHANNEL.md` §8.5, ✘: the hub is not on this machine).
- **This review keeps §8.2.** It recommends making that API-level contract *mechanical*, not reintroducing sha pinning.

**Recommendation.**
1. Add a CI job, run on PRs and on a schedule, that checks out the **newest published `v3.*` method tag** in place of the pin and runs the boundary and state tests. This is the method users actually receive. The skill's `scripts/installer-consistency.py` is the precedent for checking against what users get.
2. Write the tested method range down in code (a minimum and the newest minor exercised). Show "method v3.x is newer than this TCC was tested with" in the diagnostics panel, the same way the "pin behind" row works (`self_check.py:194-201` ◐).
3. Optionally, ask the method role (through the bus) for a contract-version constant that TCC can read. That turns (2) from a version comparison into a real handshake.

---

### F3 — Silent failures at the agent boundaries · **Medium-High** · Effort **S** (each part)

**(a) omp dies mid-turn, and the next message hangs.**
- **Evidence:**
  - When omp's output ends, the frame reader sets `_ended` and queues a single `None` (`omp_session.py:697-699` ✔).
  - The running turn treats that `None` as "process ended" and returns with no message (`:1096-1097` ✔).
  - `send()`/`_prompt()` never check `_ended` (`:1054-1112` ✔), and `_send` writes to the dead process's stdin (`:448-453` ✔).
  - The next turn then waits on an empty queue: one "120 s with no output" notice, then `continue` forever (`:1067-1094` ✔).
  - Only a *reader exception* posts a Notice telling the user to start a new session (`:690-696` ✔). A clean exit says nothing.
  - No test covers process death (◐). The hang was read from the code, not reproduced (✘ live).
- **Recommendation:** in `send()`, check `self._ended.is_set()` and raise or yield a Notice "omp exited — start a new session", and make the end-of-process marker sticky so it is not consumed by one turn.

**(b) SDK error results read as a normal end of turn.**
- **Evidence:**
  - `_drain` turns any `ResultMessage` into `TurnEnd` after recording the session id (`tuning_session.py:425-428`, `:498-505` ✔).
  - `is_error`, `errors`, `api_error_status` and `terminal_reason` exist on SDK 0.2.145's `ResultMessage` (◐), and grep finds none of them anywhere in `src/` ✔.
  - A stream that ends with *no* result also ends quietly (`:431-432` ✔).
- **Risk:** a rate-limit or API error mid-turn reads as "the model said nothing".
- **Recommendation:** when the result says it is an error, yield a visible Notice carrying the SDK's reason (and record it with `availability`, the way reviewer refusals already are).

**(c) The MCP server dying mid-session is not noticed.**
- **Evidence:** the server's failure is checked only while it starts (`mcp_server.py:1858-1869` ✔). `_launch_session` checks `self._mcp_server is None`, not whether the server is still serving (`main_window.py:5320-5321` ✔).
- **Recommendation:** add a liveness check (thread alive, plus the `started` flag) before launching a session and on the existing diagnostics tick.

**(d) The plugin path can be the string `"None"`.**
- **Evidence:** `tuning_session.py:358` passes `str(vendor_loader.skill_repo_root())` as the plugin path. `skill_repo_root()` returns `None` when the skill folder is neither inside a git checkout nor a plugin (`vendor_loader.py:116-119` ✔), for example a bare `$AUTOSOUND_SKILL_DIR`. The session then runs without the method, which is the failure `link_skill_into` exists to prevent. The existing test would pass with `"None"` too (`tests/test_tuning_session.py:680-690` ◐).
- **Recommendation:** refuse to start the session, with a message naming the folder.

**(e) The confirmation bridge treats any error as "denied", without logging it.**
- **Evidence:** `mcp_server.py:561-567` (`except (asyncio.TimeoutError, Exception): return False` ✔). The same pattern is at `tuning_session.py:303` and `omp_session.py:601` ◐.
- **Risk:** this is the safe direction, but a bug in the bridge reads to the model and the user as "the Arbiter denied".
- **Recommendation:** log the exception before returning `False`.

---

### F4 — `write_rew_filters` can report a flat filter as applied, and blocks the MCP server · **Medium-High** · Effort **S**

**Evidence**
- **The tool** is at `core/mcp_server.py:1191-1221` ✔. It is confirm-gated, then calls `rew_api.find_measurement_id` and `rew_api.set_filters` directly on the server's event loop. It does not use `_in_thread` (`:161-165` ✔), which 19 other call sites use (◐).
- **The skill itself calls this "the worst failure mode this API has":** an entry using `gain` instead of `gaindB` is accepted with HTTP 200 and stored at 0 dB (`rew_api.py:478-490` ✔). The tool's docstring says so too (`mcp_server.py:1198-1201` ✔), but nothing validates the entries and nothing reads them back.
- **Dead branch:** `if mid is None:` (`mcp_server.py:1218`) can never be true, because `find_measurement_id` raises `KeyError` (`rew_api.py:280-290` ✔). A missing title becomes a raw tool exception instead of the intended JSON error.
- **Tests** cover only the denied path (`tests/test_mcp_server.py:465-485` ◐).

**Risk.**
- **A flat filter reported as applied.** The model writes `{"gain": -3}`. The Arbiter approves a payload that looks right; REW stores 0 dB; the tool answers `applied: True`. The next measurement shows "no change", and the session reasons from a false premise. This is the SCR-041 class: agreement, not failure.
- **A stalled server.** A REW that is up but not answering holds the MCP loop for up to 2 × 5 s per call, stalling every tool and signal for every connected agent.

**Recommendation.** Make the wrong write loud, which is the lever `ARCHITECTURE-NOTES.md:53-59` names:
- Reject an entry that carries `gain` without `gaindB`, and say the right key.
- Read the filters back with the skill's getter and compare them with what was sent.
- Run the REW calls in `_in_thread`.
- Turn `KeyError` into the JSON error.

The same validation belongs in the skill's `set_filters`, which owns the client; send that to the bus as a ticket for the skill role.

---

### F5 — Unreadable files are treated as empty, and then written over · **Medium** · Effort **S** (TCC) + skill ticket

**Evidence**
- **TCC's per-project settings.** `core/project_settings.py:33-42`: an unparseable `.tcc/tcc-project.json` loads as `{}`. `set_value` (`:52-79`) then writes `{}` plus the one key it was asked to set ✔.
  - Probe ◐: one write after a trailing comma left `{'ui_mode': 'gui', 'schema_version': 1}`. The generator, critic, `gate`, `always_allowed` and `curve_delays` were gone.
- **TCC's import store, same shape.** `core/capture_import.py:133-139` reads an unparseable store as `{}`, and `:141-153` rewrites the whole store ✔. That erases the import history, including «Take it as it is» answers (probe ◐).
- **The skill's process state.**
  - The skill's `Process.load()` returns an *empty state*, not an error, on an unreadable file (`rew_tool/state/process.py:974-986` ✔).
  - TCC's `process_view.load_state` passes that through (`state/process_view.py:70-78` ✔), so the window's guard for "file exists but did not parse" (`main_window.py:3865-3876` ✔) never fires: `state` is never `None` here. The plan panel shows an empty plan.
  - `report_phase` then tells the agent to call `enter_phase` (`mcp_server.py:1488-1496` ◐), and the skill's next read-modify-write replaces the plan. The journal survives.
  - `project.py` already refuses this exact case (`project.py:784-790` ◐); `process.py` does not.
- **No `fsync`** anywhere in `src/` or in `rew_tool/` (◐ grep). After a power loss, some filesystems leave a renamed file empty, which leads straight into the cases above.

**Risk.** A hand edit, a sync conflict or a crash at the wrong moment silently drops a project's model choices and permission ticks, its import answers, or its plan.

**Recommendation.**
- **TCC side:** distinguish *absent* from *unreadable* in every `.tcc/` store. On unreadable, move the file aside (`*.corrupt-<timestamp>`), say so in the status strip, and never write over it.
- **For `process-state.json`:** check that it parses as an object before trusting `Process.load()`, so the existing guard can work.
- **Skill side (to the bus):** make `Process.load` refuse an unreadable or non-object file the way `project.py` does.

---

### F6 — TCC re-implements readers of skill-owned files, and one already disagrees with the skill · **Medium** · Effort **M**

**Evidence**
- **TCC's own journal fold** is `state/process_view.py:98-182` ✔. It has no `capture_superseded` case: grep finds the word nowhere in `src/` ✔. The method's v3.1.1 has the event (`process.py:104`) and leaves superseded rows out of what is taken (`process.py:820-822`) ✔.
  - Probe ◐: the method lists `w-R_1 (sw)` as outstanding, while TCC shows it as done.
  - "Taken" is also an OR of the method's round and TCC's import store (`state/measurement_view.py:419`, `:526` ◐).
- **TCC parses `project.json` directly in several places:** `state/project_view.py:83`, `:139`, `:369`; `state/dsp_state.py:562` (unguarded, so it raises); `state/acoustics_view.py:180`; `state/measurement_view.py:54` ✔.
- **TCC parses `slots.json` itself:** `state/ledger_line.py:56` ✔.
- **The ledger is read two ways.** The MCP server reads it through the skill's `PresetHistory` (`mcp_server.py:751-765` ✔), and the GUI mostly does too (`dsp_state.py:640-645` ✔). But the GUI joins in `project.json` and `process-state` by itself.
- **Already known:** DECISIONS-W-2 A18 (S22) sent the `capture-supersede` contract to the skill as hub #201 (TCC-028), with A17 to be built on top of it ✔.

**Risk.** Every time the method adds an event or a field, TCC's fold or parse silently disagrees with the method. The tuner then sees a different state from the one the model is acting on.

**Recommendation.**
- Where the skill has a reader, call it.
- Where TCC keeps its own fold for speed or shape, add a **parity test** that runs the skill's function and TCC's fold on the same recorded journal or project. `tests/test_contract_check.py` already does this by running the real checker.
- Start with the capture fold, inside the TCC-028 work.

---

### F7 — Two method versions can write to the same project · **Medium** · Effort **M**

**Evidence**
- **A project pins its method on purpose** through its `.claude/skills/autosound-tuning` link: "the session runs this one, and a project pins it on purpose" (`install_report.py:293-296`, finding 94, tcc#83 ✔).
- **The link is created once and never moved** (`vendor_loader.py:234-236` ✔).
- **The omp and external-terminal routes run the project's link** (`tuning_session.py:355-356` comment ✔).
- **The in-app Claude route runs TCC's own method as a plugin** (`tuning_session.py:357-358` ✔).
- **TCC's writers run TCC's own method too:** `process_writer.script_path()` is `vendor_loader.REW_TOOL_DIR / "state" / "process.py"` (`process_writer.py:92-93` ✔). Profile and config writes go the same way (◐).
- **The only visible signal** is a suffix in the title bar (`main_window.py:4618-4628` ✔). `Process.load()` accepts any `schema_version` (◐ probe: 1 and 99 both render).

**Risk.** A project pinned at v3.0.61 is driven from a terminal while TCC records captures with v3.1.1's `process.py` into the same `process-state.json`. Each side writes fields the other's version may not keep. The lenient readers (F5, F6) show the result without complaint.

**Recommendation.**
- When a project has a method link, run TCC's writers (`process_writer`, `profile_writer`, `config_writer`, `contract_check`) through *that* method, the same one its session runs.
- Where that is not possible, put the mismatch in the diagnostics panel as an actionable row, not only in the title.
- This keeps finding 94's decision (projects pin) and makes TCC obey it.

---

### F8 — D-1 is not implemented: TCC ships its own older DSP profiles and overrides the skill's library · **Medium** · Effort **S**

**Evidence**
- **TCC's own folder:** `core/config.py:40` sets `DEFAULT_BUNDLED_PROFILES_DIR = <package>/dsp_profiles`, and `:225-227` returns it ✔. It holds one file, `src/autosound_tcc/dsp_profiles/helix-dsp-ultra-s.json` (5.9 KB) ✔.
- **It is passed to the skill everywhere:** `ui/tcc/new_project_dialog.py:289` (the New Project list), `core/mcp_server.py:803-806` and `core/agent_session.py:219-221` (`bundled_exact_match` for onboarding) ✔.
- **The skill's own library:** `knowledge/dsp/profiles/` holds `audiotec-fischer-helix-dsp-ultra-s.json` (22.7 KB) and `musway-m6v4.json`. `dsp_profile.find_bundled(vendor, model, dir_=None)` defaults to it (`rew_tool/dsp_profile.py:488-506`) ✔.
- **Probe ✔** (`dsp_profile.py find-bundled`):
  - through TCC's folder, `Musway / M6V4 (no 512K)` gives **"no exact match"**, while the skill's default finds it;
  - Helix comes back as **7,185 bytes** instead of **22,786**;
  - TCC's copy lacks `groups_enumerated`, `dsp_processing_rate_note` and `effects_and_dynamics`, plus other fields ◐.
- **A test locks in the wrong location:** `tests/test_packaging.py:292-303` asserts the profiles live *inside TCC's package* ✔.

**Risk.** New projects are offered fewer DSPs than the method knows, and onboarding seeds an older Helix profile as the "exact match". That is the drift D-1 was written to prevent.

**Decision touched.** **D-1** (`docs/DATA-MODEL-DECISIONS.md:48-71`, 2026-07-31): "profiles belong to the skill … `DEFAULT_BUNDLED_PROFILES_DIR` moves into the submodule". This is **implementing** D-1, not reversing it.
- The 2026-08-12 move into the package (`config.py:35-39`) was right at the time: the skill shipped no profiles (`DATA-MODEL-INVENTORY.md` §1.2).
- New evidence: the skill now ships its own library, and its owner has answered for it (`dsp_profile.py:475-503`).

**Recommendation.**
- Pass `None`, or the skill's `bundled_dir()` through `vendor_loader`, at all three call sites.
- Have the New Project dialog read the skill's folder, with an empty list when there is no skill. Project seeding already behaves that way (`new_project_dialog.py:49-58` ✔).
- Delete `src/autosound_tcc/dsp_profiles/` and turn `test_packaging.py:292` around.

---

### F9 — Two writers of `process-state.json` are still not serialised, and on Windows there is no lock at all · **Medium** · Effort **M** (mostly the skill)

**Evidence**
- **TCC's lock** is a `flock` on POSIX only (`process_writer.py:38-43`, `:106-147` ✔). Its own docstring says "the skill's own CLI does not take this lock, so this narrows the window rather than closing it" (`:117-118` ✔).
- **The skill has neither a lock nor compare-and-swap:** grep finds no `flock`, `msvcrt.locking` or `expect_rev` under `rew_tool/` ✔. It writes through a fixed temp-file name (`process.py:2533` ◐).
- **This is ARCHITECTURE-NOTES §1 hole 3** (`:45-48`), with planned fix 3 "`save(data, expect_rev=N)`" (`:69-70`) still open ✔.

**Risk.** The import window records a capture (`measurement_panel.py:333` ◐) while the agent's Bash runs `process.py done`. One update to the state file is lost, while the journal keeps both.

**Recommendation.**
- **Skill side (to the bus):** the change §1 already names — a lock inside `process.py`/`state.py` and `expect_rev`.
- **TCC side:** add the Windows half of `_exclusive` with `msvcrt.locking` (S).

---

### F10 — The update and install paths have three sharp edges · **Medium** · Effort **S**

**(a) A stray `v*` tag outranks real releases on the stable channel.**
- **Evidence:**
  - `TCC_TAG_GLOB = "v*"` (`updates.py:70` ✔), and stable ranks tags with `_version_key`, which pulls every number out of the name (`:403-405`, `:537-541` ✔). The tag is then refused as "not a release tag" (`:789-792` ✔).
  - **Reproduced ✔:** `max(['v1.1.0','v1.1.1','v1.2.0-wip','v1.1.1.1'], key=_version_key)` gives `v1.2.0-wip`, while `channel_key` gives `v1.1.1`.
  - The method's installer already fixed this exact problem (`install.sh:1022`, `:1260`, skill #108 ✔).
- **Risk:** stable updates are blocked until a real release ranks above the stray tag, and published tags are never deleted here (`CLAUDE.md`, Releases). The method update shares the same ranking (`:534`, `:606` ✔).
- **Recommendation:** rank stable with a key that only accepts release-shaped names.

**(b) The fix-it hints install half the app.**
- **Evidence:** `app.py:43-50` (`_NO_GUI`) and `claude_sdk.py:31-35` (`INSTALL_HINT`) tell the user to run `uv tool install --upgrade 'autosound-tcc[gui|claude] @ git+…'` with no tag, no `--python 3.12` and **one** extra ✔.
- `updates.py:84-86` explains why `--python 3.12` is "not optional" ✔.
- With uv 0.8.17, `--upgrade` with a single extra removed the other extra's packages (◐, throwaway-package test). Under the installer's uv 0.12.10 ✘.
- **Recommendation:** build both hints from `tcc_install_command(tag)`.

**(c) The installer can fall back to `main`, unsigned.**
- **Evidence:**
  - When listing tags fails, the installer installs from the default branch, unsigned, with a warning (`install.sh:1269-1274` ✔); it does the same for the method (`:1026` ✔).
  - The README pipes the installer from the method's `main` (`README.md:112`, `:121` ✔).
  - `CHANGELOG.md:6-7` still says "a FRESH install still takes `main`". That reads stale against the v3.1.1 installer, which picks the newest signed tag ◐.
- **Recommendation:** decide whether the offline fallback should stop instead (the release-safety rule says unknown is a refusal), and update the CHANGELOG preamble.

---

### F11 — The tests are blind at the seams that matter most · **Medium** · Effort **M**

**What the suite protects well** (◐ unless marked):
- **Coverage:** `state/*` 90–100%; `mcp_server` 88%; `omp_session` 93%; `tuning_session` 81% (partial runs, so lower bounds).
- **Translations:** i18n parity across four languages (`tests/test_i18n_languages.py:26-66` ✔).
- **Layering and the light core:** `test_packaging.py:96`, `:118` ✔.
- **The method:** its own selftests are run (`tests/test_skill_selftests.py`), and the contract checker is run for real.
- **REW:** request shapes are checked at the `urlopen` layer through the real `rew_api`, with responses recorded 2026-07-28 (`tests/test_rew_api_shapes.py:12-36`).
- **omp:** a replay of real frames recorded 2026-08-05 (`tests/test_omp_replay.py:1-25`).
- **Qt-slot exceptions fail the test** (`conftest.py:33-56` ✔).

**Gaps**
- **No end-to-end path.**
  - Nothing builds a wheel or installs one (◐: no `uv build`/`pip install` in `tests/` or `ci.yml`; ✔: grep on `ci.yml`).
  - The suite runs from an editable install (◐).
  - `app.main`'s window path (`app.py:583-670`) never runs (◐).
  - Nothing connects an MCP client over HTTP: `_TokenGuard` (`mcp_server.py:1510-1535`) is referenced by no test ✔.
- **Base install never tested.** No CI job installs *without* extras; every job uses `--extra dev`, which pulls in `gui` and `claude` (◐). `requires-python = ">=3.11"` (`pyproject.toml:15` ✔) is never run; CI is 3.12 only (◐).
- **Test doubles are never compared with the real classes,** except the `bus` slot (`tests/test_doubles.py:39` ◐):
  - SDK: `_StreamEvent`, `_Block`, `_Message`, `_RecordingClient` (`tests/test_tuning_session.py:208-224`, `:491-505`), and the classes swapped into `agent_session`'s globals (`tests/test_agent_session.py:191-220`);
  - REW: `_FakeApi`/`_Api` (`tests/test_rew_bridge.py:8`, `:39`) and `_FakeBridge` (`tests/test_curve_view.py:177`) ◐.
  - There are 112 `monkeypatch.setattr(..., raising=False)` calls. A renamed production probe would turn a conftest guard into a no-op without failing anything (◐; all 17 attributes conftest patches exist today).
- **A source-text test that the docstring satisfies on its own.** `tests/test_agent_session.py:74-91` asserts `"strict_mcp_config=True" in source`, and the module docstring alone contains that text (`agent_session.py:43` ✔). The runtime check at `:69` is what actually protects the setting (◐).
- **One network call is still open on developer machines.** `ANTHROPIC_API_KEY` is not cleared by `conftest.py` (✔ grep). `model_choices._fetch_sdk_choices` sends a real GET with it (`model_choices.py:252-260` ✔), and it is reached from `ProjectGateDialog` on an unjoined daemon thread (◐). CI has no key, so CI never shows it.
- **No per-test timeout** (no `pytest-timeout` in `pyproject.toml:93` ✔). A hang costs the CI job limit of 25–60 minutes (◐).

**Recommendation.**
1. Add one end-to-end smoke job:
   - build the wheel and `uv tool install` it into a scratch folder with a fresh resolve;
   - import the CLI half;
   - start `TccMcpServer` on a fixture project;
   - connect a real `mcp` client over HTTP, once without the token (expect 401) and once with it;
   - call `get_tcc_state` and one gated write;
   - assert the file on disk.
2. Add contract tests for the doubles: the attribute set of each fake must be a subset of the real class's, for example `dataclasses.fields(ResultMessage)`.
3. Clear `ANTHROPIC_API_KEY` (and the other provider keys) in `conftest.py`.
4. Strip the docstring before the `strict_mcp_config` check, the pattern `test_windows_identity.py:113-118` already uses (◐).
5. Add `pytest-timeout` with a generous default.

---

### F12 — Structure: `MainWindow` keeps growing, and `core/` is four packages in one · **Medium (long-term)** · Effort **L** (incremental), plus one **S**

**Evidence**
- **`MainWindow`:** `ui/tcc/main_window.py` is 6,465 lines. The `MainWindow` class (`:753`) has 221 methods and imports 78 internal modules ✔. It was about 4,300 lines at FF-01 (see §4); the recommended extractions happened (`workers.py`, `state/models.py`, plus `control_layout.py`, `qt_bridge.py`) and the file still grew by 50%.
- **Churn:** in the 50 commits in this clone, `main_window.py` and `i18n.py` are the files changed most often ✔ (`git log --name-only`; a shallow clone, so only indicative).
- **`core/`** holds infrastructure, agent services, skill-CLI drivers, domain math and OS/distribution code side by side (§2.1) ✔.
- **The three function-level cycles** (§2.2) come from two small facts: branding constants live in `app.py:23-32`, and the critic/availability/model tangle ✔.
- **Mock data still ships.** `ui/tcc/mock_data.py:52-77` builds invented tuning advice (`DIALOG`). `dialog_panel.py:423-425` renders it at construction, and two call sites clear it (`main_window.py:2417`, `:3105`) ✔. Its safety depends on those calls never being skipped.

**Risk.**
- Every feature touches the same 6.5k-line class: merge conflicts, slow tests (`tests/test_main_window.py` is 7,527 lines) and teardown races (the tcc#19 class).
- A design fixture that holds fabricated advice is one missed `clear_mock()` away from a user seeing it.

**Recommendation.**
- **(S)** Move `APP_DISPLAY_NAME`/`APP_ICON*` to a leaf module (`autosound_tcc/branding.py`). That removes the `app` ↔ `core` cycle.
- **(L, only when the code is touched anyway)** Keep pulling areas out of `MainWindow` as plain `QObject` controllers, each with its own tests: project load and file watching, session lifecycle, updates and diagnostics, capture import.
- Do not split `core/` into subpackages as a project of its own (see §6).
- **(M)** Move `DIALOG`/`PLAN`/`MEAS_SESSIONS` into `tests/fixtures/` and give the panels an empty default.

---

### F13 — The CI and release signal is weaker than the policy text suggests · **Low-Medium** · Effort **S**

**Evidence**
- **Linux never blocks:** pull-request shards run `continue-on-error: ${{ matrix.os == 'ubuntu-latest' }}` (`ci.yml:166` ✔), and the push job runs `continue-on-error: true` (`:230` ✔).
- **macOS runs only as pull-request shards** (`ci.yml:170` ✔; ◐ no macOS job on push).
- **So the only *blocking* whole-suite run on the commit the release gate reads is Windows.** Which run the hub's gate reads ✘ (the hub is not here).
- **Patch mode tags a commit no CI run has seen.** `ship.py` in patch mode commits the version bump and tags that new commit at once (`:637-656` ✔), which the wave path's own comment calls "a release commit … CI never checked" (`:623-627` ✔). The suite does run locally first.
- **The pairing check is loose:** `said in method_sha` (`ship.py:297` ✔) accepts any substring of the sha.
- **CI does not use `--locked`,** and actions are pinned by tag, not by SHA (◐).

**Recommendation.**
- Finish the step `CROSS-PLATFORM-PLAN.md:342` already plans (drop `continue-on-error` on Linux) when HUB-049 closes.
- Add macOS to the push run, or say explicitly that the release gate does not need it.
- Use `uv run --locked` in CI.
- Require a full-sha prefix of at least 7 characters in the pairing check.

---

### F14 — Permission ticks travel with the project folder and are not vetted · **Low-Medium** · Effort **S**

**Evidence**
- **The ticks live in the folder.** `gate` and `always_allowed` are read from `.tcc/tcc-project.json` (`main_window.py:5487-5493` ✔) and handed to the session (`tuning_session.py:175-196` ✔).
- **They outrank the irreversible-command guard** (`tuning_session.py:247-256` ✔).
- **The trust check doesn't look at them.** `core/project_trust.py:38-62` lists what a folder's `.claude/settings.json` will apply ✔, but not TCC's own ticks.
- `.tcc/` is gitignored, so clones are safe (`mcp_server.py:1564-1597` ✔). Zips, backups and memory sticks are not.

**Risk.** A project sent for help arrives with `always_allowed` already ticked for tools the receiving Arbiter never approved.

**Recommendation.** Either list `.tcc/` ticks among what `project_trust` reports before the first session, or key the ticks per machine (`QSettings`, as `gate/machine` already is ◐).

---

### F15 — The docs have drifted from the code and from the issue tracker · **Low** · Effort **S**

**Evidence**
- **The flakiness table is out of date.** `docs/TESTING.md:278-283` lists tcc#22 and tcc#28 as open flakes. Both were **closed 2026-09-14** (GitHub ✔), #28 with its root cause found (machine dirs inside `tmp_path`; the fix is at `conftest.py:404-414` ◐). `CLAUDE.md:32` and `pyproject.toml:113-127` still cite #22 as the reason for running serially.
- **Two comments describe the opposite of the code.** `core/project_trust.py:3-11` and `core/omp_session.py:320` still say `tuning_session` passes `setting_sources=["project"]`; it passes `[]` since HUB-050 (`tuning_session.py:357` ✔).
- **Two docstrings say TCC never writes the skill's `process/` folder** (`core/config.py:161-165`, `state/process_view.py:59` ✔). It writes `process/attachments/*.png` and `process/.process-write.lock` there (`ui/tcc/attach_image.py:45-48` ◐, `process_writer.py:124-126` ✔).
- **Line references in ARCHITECTURE-NOTES §8 have moved** (for example `vendor_loader.py:64` → `:65`, `updates.py:217-231` → `:552`) ◐.
- **A docstring names a class that no longer exists:** `_RewReadWorker` (`core/rew_bridge.py:52` ✔).

**Recommendation.** Fix the text. **Do not** change the serial default because #22 closed (§6).

---

### F16 — Smaller boundary items, each Low · Effort **S**

- **Unbounded on Windows.** `critic.run` uses bare `subprocess.run(timeout=…)` (`critic.py:574-582` ✔). `child.py:327-333` explains why that can wait without bound on Windows when a grandchild holds the pipes, and `_git` was moved to `run_bounded` for exactly that reason (◐). `updates._run_upkeep` has the same pattern (`updates.py:931-934` ◐).
- **Curve-read failures lose their message.** `curve_dialog.py:428-433` keeps only the exception *type*, so the skill's worded errors never reach the user (◐).
- **The smoothing fallback catches too much.** It retries on *any* `TypeError` (`rew_bridge.py:101-108` ◐).
- **REW's own wording is copied by hand into a test.** `"No measurement titled"` (`tests/test_title_fixes.py:91` ◐; source `rew_api.py:286` ✔). A rewording would go unnoticed.
- **A function that promises "never raises" can raise.** `contract_check.report_from_json` assumes the JSON is an object (`contract_check.py:160`, `:247` ◐).
- **No single-instance guard for `.mcp.json`.** `forget_mcp_config` removes the entry whichever instance owns it, and an unparseable `.mcp.json` is replaced, not merged (`mcp_server.py:1619`, `:1642-1643` ◐).

---

## 4. FF-01 (2026-09-06, on v0.1.32), re-checked at `f58d208`

| # | FF-01 said | Status | Evidence |
|---|---|---|---|
| 1 | `main_window.py` is about 4,300 LOC; split it (workers → `ui/tcc/workers.py`, models → `state/models.py`) | **Changed: the split was done, the file grew** | `ui/tcc/workers.py` exists with five `QThread` workers (`workers.py:29`, `:52`, `:123`, `:190`, `:252`) ✔. `state/models.py` holds six domain dataclasses (`models.py:15-87`) ✔. But `main_window.py` is now **6,465 lines**, with 221 methods in `MainWindow` (`:753`) ✔. See F12. |
| 2 | Layering: `ui` imported from `core`/`state` in 4 places (`core/config.py:152`, `core/self_check.py:321`, `state/measurement_view.py:23`, `state/process_view.py:25`) | **Fixed, and guarded** | The import graph finds 0 edges from `core`/`state` to `ui` ✔. The guard is `tests/test_packaging.py:96-103`, with a test proving it turns red (`:106`) ✔. The domain types moved to `state/models.py:1-7`, and `mock_data` re-exports them (`mock_data.py:16`) ✔. Settings reach `config` by injection (`app_settings.py:31`) ✔. |
| 3 | `class Bus` stubs in `test_main_window.py` lacked `pending_count`, which `main_window` reads every 2 s; the `AttributeError` was swallowed in a Qt slot | **Fixed, and guarded (`bus` only)** | `tests/test_main_window.py:2144-2148` uses the real `SignalBus`. `tests/test_doubles.py:1-15`, `:39` derives the bus protocol from `src/` and checks every double. `conftest.py:33-56` fails a test on a Qt-slot exception ✔. Only the `bus` slot is checked this way (F11). |
| 4 | `measurement_panel.py` annotated a non-existent `_RewReadWorker` (F821); ruff total 85 (F821 37, F401 32) | **Fixed** | `uvx ruff@0.12.0 check src tests scripts --statistics` gives **0 findings**, exit 0, with `select = ["E4","E7","E9","F"]` (`pyproject.toml:136`) ✔. Ruff is in `make check` (`Makefile:35-38`) ✔ and in CI (◐). The only `_RewReadWorker` left is a docstring at `core/rew_bridge.py:52` (F15). |
| 5 | Order-dependent Qt abort (exit 134) on Linux offscreen; `shiboken6.isValid` in `i18n.set_language` was already there, so the cause is elsewhere | **Still present (unresolved, not reproduced)** | The `isValid` guard is still at `i18n.py:5291` ✔. HUB-049 is "no repro yet" (`docs/TESTING.md:282` ✔; `ci.yml:6`, `:163`, `:229` ✔). Linux runs non-blocking (`ci.yml:166`, `:230` ✔). The last five pushes to `main` were green on Linux (◐). Current status in the hub ✘. |
| 6 | Model names hardcoded in several places (`tuning_session.py`, `model_choices.py`, `mock_data.py`, `i18n.py`) | **Mostly fixed; residue in `mock_data.py`** | Ids and defaults are written once in `core/model_choices.py:60-80` (`DEFAULT_SDK_MODEL` `:65`, `DEFAULT_OMP_MODEL` `:66`, `SDK_MODELS` `:70`) ✔. `tuning_session.py:59` and `omp_session.py:80` import them ✔. A test forbids any i18n string from naming a model (`tests/test_i18n_languages.py:98-101`) ✔. Left over: `mock_data.py:29` `CURRENT_GENERATOR_MODEL = "Claude Opus 5"`, still the dialog's first label (`dialog_panel.py:305`) ✔, and `mock_data.py:31` `AI_CRITIC_MODELS`, which nothing reads ✔. |
| 7 | `terminal_launcher.py` used `shell=True` with `project_dir` inside the command string | **Fixed** | No `shell=True` call anywhere in `src/` ✔. On the `cmd` route the folder travels as `cwd`, never inside the line (`terminal_launcher.py:356-372`, HUB-053) ✔. On the `wt` route it is an argv element quoted by `list2cmdline`, with `;` escaped (`:134-144`, `:350-353`) ✔. |
| 8 | Claude SDK: `setting_sources` loads the project's hooks/permissions along with the skill; gate `auto` in `_can_use_tool` passes Bash before the allowlist check | **`setting_sources` fixed; gate tightened, but `auto` is still the default** | The session runs with `setting_sources=[]` and gets the method as a plugin (`tuning_session.py:328-358`, HUB-050) ✔; onboarding does the same, with `strict_mcp_config` (`agent_session.py:27`, `:318-322`) ✔. The default gate is still `auto` (`shell_gate.py:50`) and still lets ordinary Bash through without the allowlist, by design. But irreversible commands now go to the Arbiter first (`tuning_session.py:258-272`, HUB-028) ✔. New since FF-01: a per-project "always allowed" tick outranks that guard (`:247-256`) and lives in the folder (F14). Stale comments: `project_trust.py:3-11`, `omp_session.py:320` (F15). |
| 9 | Docs drift: test counts in `docs/TESTING.md` did not match the suite | **Fixed, and guarded; new drift of another kind** | `TESTING.md:12-16` carries no count, and `tests/test_packaging.py:661` fails if one comes back ✔. The flakiness table now lists two issues closed on 2026-09-14 (F15). |

---

## 5. Recommended changes, in order

These are the inputs to the next wave's review, not orders: per `CLAUDE.md`, "a finding waits for its wave" and the Arbiter decides. Items marked **→ bus** belong to the method's role and go as tickets (`bin/ticket open`), not as TCC changes.

| order | change | finding | effort |
|---|---|---|---|
| 1 | `write_rew_filters`: reject `gain` without `gaindB`, read back and compare, run in `_in_thread`, turn `KeyError` into the JSON error. **→ bus:** the same validation in the skill's `set_filters`. | F4 | S |
| 2 | Make the agent boundaries loud: an exited omp is checked in `send()`; SDK `is_error` becomes a Notice; MCP liveness is checked before a session; a `None` plugin path refuses to start; the confirmation bridge logs what it swallows. | F3 | S |
| 3 | `.tcc/` stores: unreadable is not empty. Move the file aside, say so, and never write over it. Check that `process-state.json` parses as an object before trusting it. **→ bus:** `Process.load` refuses unreadable input, as `project.py` does. | F5 | S |
| 4 | D-1: use the skill's profile library at all three call sites; delete `src/autosound_tcc/dsp_profiles/`; turn `test_packaging.py:292` around. | F8 | S |
| 5 | Updates: rank stable with release-shaped names only; build both fix-it hints from `tcc_install_command(tag)`; decide the unsigned-`main` fallback. | F10 | S |
| 6 | Pin the install: a constraints file from `uv.lock` with every tag, passed with `-c` by the updater and **→ bus** the installers; a scheduled CI job doing a fresh-resolve install of the built wheel. | F1 | S–M |
| 7 | A CI job against the **newest published method tag**; a tested method range in code, shown in diagnostics. **→ bus:** optionally, a contract-version constant. | F2 | M |
| 8 | TCC's writers run the project's own method link when there is one, and a mismatch becomes a diagnostics row. | F7 | M |
| 9 | Parity tests for TCC's own readers against the skill's; the `capture_superseded` fold (TCC-028). | F6 | M |
| 10 | Test seams: the end-to-end smoke job (wheel → base install → MCP over HTTP with token → write); contract tests for the doubles; clear provider API keys in `conftest`; fix the docstring-satisfied test; `pytest-timeout`. | F11 | M |
| 11 | **→ bus:** the lock and `expect_rev` in `process.py`/`state.py` (ARCHITECTURE-NOTES §1 item 3). TCC: the Windows `msvcrt.locking` half. | F9 | M |
| 12 | Report or relocate the `.tcc/` permission ticks. | F14 | S |
| 13 | Docs: the TESTING.md flakiness table, the `project_trust`/`omp_session`/`config`/`process_view` docstrings, the line refs in ARCHITECTURE-NOTES §8, the CHANGELOG preamble. | F15 | S |
| 14 | CI: `--locked`; macOS on push, or an explicit statement that the gate does not need it; Linux blocking once HUB-049 closes; a stricter pairing check. | F13 | S |
| 15 | Structure: a `branding.py` leaf module (S); `MainWindow` controllers pulled out as areas are touched (L); mock data moved to test fixtures (M). | F12 | S / L / M |
| 16 | The small items in F16. | F16 | S |

---

## 6. What should NOT change, and why

1. **D-6, "the skill writes, TCC reads"** (`DATA-MODEL-DECISIONS.md:197-233`).
   - The code holds it: every write to skill data goes through the skill's own code (§2.3), and the MCP surface audits itself (`mcp_server.py:23-41`).
   - The fixes for F5, F6 and F9 must not "help" by having TCC write `process-state.json` or `project.json` itself. They go to the skill as tickets, or into TCC's own `.tcc/`.
2. **The vendored submodule** (`ARCHITECTURE-NOTES.md` §8, removal rejected 2026-08-27).
   - It is what makes the suite reproducible: 178 failures without it (§8.3).
   - F2's job against the newest tag *adds* a second view; it does not replace the pin.
3. **No `.pkg`/`.exe`** (§9). Nothing found here changes the reason (paid signing, and an unsigned installer is worse than the script). F1's constraints keep the script path.
4. **The light core and the heavy extras, each with an upper bound and a test that enforces it** (`pyproject.toml:18-29`, ARCHITECTURE-NOTES §3).
   - Measured here: 30 modules, no Qt, base install verified (◐).
   - F1 adds constraints *within* the bounds and leaves the policy alone.
5. **Serial is the default for the suite, even though tcc#22 is closed.**
   - The decision was "it stays serial until that crash is understood" (`pyproject.toml:124`).
   - #22 was closed after 0 crashes in 15 runs and attributed to the #19 fix, which its closing comment calls *evidence, not proof* (◐). HUB-049 is still open.
   - Fix the documents (F15), keep the default. Reversing it would need a reproduction-backed explanation, which does not exist yet.
6. **The MCP server as the shared substrate on loopback HTTP with a token** (`mcp_server.py:1-21`). One implementation serves the in-app SDK, omp and any external CLI, and it sidesteps the Agent SDK's login terms. F3(c) and F11 add liveness and a test; the shape stays.
7. **The one thread crossing in `qt_bridge.py`** (signals out to the GUI; a locked, cached snapshot in). This is the reason the agent's thread never touches a widget; keep it the only crossing.
8. **HUB-050: `setting_sources=[]`, with the method loaded as a plugin** (`tuning_session.py:328-358`). It closed FF-01's item 8; any change to how the method loads should keep "nothing from the project folder".
9. **`scripts/ship.py` as the only release path, with signed tags and the hub preflight called rather than copied.** F13's points tighten it. None of them argues for a manual path or a copied preflight.
10. **Model ids written once in `core/model_choices.py`, and the i18n test that forbids model names in UI strings.** This is what fixed FF-01 item 6.
11. **Progressive gates and "one product, two switches"** (ARCHITECTURE-NOTES §3-§4). Nothing in this review touches them.
12. **No big-bang rewrite of `MainWindow` or `core/`.** The extractions that worked (workers, models, control layout, Qt bridge) were incremental and tested. A wholesale move would cost a wave of merge conflicts and Qt teardown risk (the tcc#19 class) for no user-visible gain.

---

## 7. Verification log, and what could not be verified

**Run in this session**
- **Ruff:** `uvx ruff@0.12.0 check src tests scripts --statistics` gave 0 findings, exit 0 ✔.
- **Packaging:** `QT_QPA_PLATFORM=offscreen pytest -n 4 tests/test_packaging.py` passed 37 in 12.9 s ◐.
- **Guards and loader:** `pytest -n 4 tests/test_conftest_guards.py tests/test_packaging.py tests/test_vendor_loader.py` passed 68 in 13.6 s ◐.
- **Boundaries:** eight boundary test files passed 414 ◐.
- **Sessions and selftests:** `test_skill_selftests`, `test_omp_session`, `test_mcp_server` and `test_agent_session` gave 269 passed and 1 failed. The failure is `test_the_three_installers_still_agree_with_each_other`, because this container has no `ssh-keygen`; it is environmental, not a code defect ◐.
- **Release tests:** `test_ship.py` and `test_signed_tags.py` skipped 38 of 78 (no hub, no `ssh-keygen`) ◐.
- **Coverage:** three partial passes — 607 tests in 66.7 s, 436 tests in 44.5 s, and 1,282 passed with 6 skipped in 455 s. Coverage.py does not trace `QThread` code, so these numbers are lower bounds ◐.
- **Collection:** 3,805 tests in 98 files ◐.
- **Builds and installs:** `uv build --wheel` (133 entries, no `vendor/`); a base install with no extras, on which all 8 light modules import; a fresh `uv pip compile` ◐.
- **Probes:**
  - `dsp_profile.py find-bundled` through TCC's folder versus the skill's default ✔;
  - stable-channel tag ranking ✔;
  - `project_settings` and `capture_import` corruption, the superseded capture, and the `process-state` truncation ◐.
- **Import graph:** the AST walk and the light-core closure ✔.
- **GitHub:** issue state of tcc#22 and tcc#28 ✔.

**Not verified (✘)**
- **The hub's `scripts/release-preflight.py` and `governance/*`:** the hub checkout is not on this machine. The `ship.py` dry run stops there, by design (◐).
- **HUB-049's current state,** and which CI run the release gate reads.
- **uv 0.12.10**, the installer's pinned version: whether it takes `-c` with a URL, and what `--upgrade` does with a single extra.
- **`install.ps1`/`install.cmd` on Windows:** not run here.
- **Live REW, live Claude SDK and live omp behaviour.** Their claims rest on code and on recorded fixtures. The F3(a) omp hang was read in the code, not reproduced.
- **Whether a late `ANTHROPIC_API_KEY` refresh in the tests writes to the real per-user config.**
- **Whether TCC reads any file that REW itself wrote,** besides target-curve `.txt` files.
