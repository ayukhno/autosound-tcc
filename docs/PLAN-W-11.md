# PLAN W-11 · v1.2.0 — the last wave before a freeze

The milestone `W-11 · v1.2.0` (#11): 13 issues, all `ok` (the Arbiter, 2026-10-21: «усі 13»). State: `docs/TODO.md`
F-103. The wave ends with the joint minor release with the skill — TCC v1.2.0 with the method's v3.2.0 (TCC-063,
hub #296; the freeze, hub #295) — and then only fixes for what users report.

**The arm: no engine** (`hub/bin/role tcc --no-SP`, hub H-022), as in W-10: the session builds or briefs an Agent;
`Engine: none` in the PR body. One branch, `wave-11`, in the main tree; one PR; the full suite runs once, on the
PR's CI.

**The reviewer trial** (the Arbiter, 2026-10-21: «Codex як ревьюєр коду … на технічних задачах, а Джемені — на
тексти і креатив»). Codex (`codex exec -m gpt-6-astra -c model_reasoning_effort=high -s read-only --ephemeral`)
takes the review seats that `hub:seam` gives to Opus and Fable; Gemini (`agy`) reviews the text. Every finding is
checked against the code before it is acted on. On the first `Risk: high` group the Opus seats run beside Codex,
to compare.

## Order

| step | group | issues | note |
|---|---|---|---|
| 1 | Install and release — tooling | #226, #227 | cheap; #226 is what the joint release needs at the end |
| 2 | The method's seam | #218, then #219 | `Risk: high`; one at a time — both touch the writers and the capture check |
| 3 | Session | #221, #222, #223 | |
| 4 | Project folder | #224, #225 | the Sonnet trial |
| 5 | Hygiene — the suite | #229 | after the code groups: it rewrites window tests the others touch |
| 6 | The method's seam — the level base | #220 | only once the skill's half lands (its W-11 item 1); not there when 1–5 are done → #220 leaves the milestone |
| 7 | the final review, the re-pin to the skill's last candidate, the release candidate | — | Codex's final branch review; #226 carries the release on the last candidate |
| 8 | Hygiene — the guide; the walk | #230, #228 | on the candidate: the guide against the screen (Gemini reviews), then the Arbiter's install from zero on a clean Mac and a clean Windows; one fix round for what blocks an install |

Implementers run **one at a time** in the tree (W-10: a review over a half-edited `conftest.py` gave 445 setup
errors).

## Weight, models and seats

| task | implementer | task review | group |
|---|---|---|---|
| `Risk: high` — #218, #219, #220, #226, #227, #228's fixes | opus · high, test first (red before the code) | **Codex** → one fix round → Codex re-review of the fix | **Codex** group review; on the method's seam also the Opus seats (silent-failure + tests), to compare |
| ordinary — #221, #222, #223 | opus · medium; one test per behaviour the issue asks for | none | **Codex** group review |
| simple — #224, #225 | **sonnet · medium** — the Sonnet trial (`hub:seam`) | none | **Codex** group review |
| the suite — #229 | sonnet · medium, from the report on #229 | none | **Codex** review |
| text — #230 | sonnet · medium; no new tests | — | **Gemini** review of the text; language versions through the Advisor |
| the wave | — | — | one final branch review on **Codex** (in place of Fable) |

The trial's record, per review: findings, how many were real after checking the code, how many the Opus seats
found that Codex did not (the method's seam), Claude runs saved. It goes to the hub's H-019 at the review between
waves.

## The method's seam — the code maps (2026-10-21, sonnet, on `wave-11` at a668c2f)

The method pinned is v3.1.4 (`71a56cf`). What the plan's G8/G7 text says and the tree differ in places; the maps
are what the implementer reads, line numbers checked on that commit.

**#218 — already done:** exit 75 → `Busy` (`core/method_cli.py:369-373`); the lock wait per call, never in
`child_env()` (`:307-310`); one deadline over the thread lock and flock (`core/project_lock.py:124-150`, W-9 renamed
`_THREAD_LOCK` to the per-folder `_THREAD_LOCKS`); `locks_itself` written and tested but **not wired**
(`project_lock.py:65-78`); `car_library` already uses `intake.py set-car`; notes as warnings (W-10, #205).

**#218 — left:**
1. `core/method_lock.py` (S): `BUSY_EXIT`, the wait env name, `BUSY_SAID`, `locks_itself` with a (mtime, size) text
   cache; `project_lock.locks_itself` stays as a re-export — the method's own docs name it (`write_lock.py:29`,
   `CONTRACT.md:378-380`).
2. `method_cli.spawn` (M): probe the bound copy (`env[method_binding.SKILL_ROOT_ENV]`); a self-locking copy gets
   **no flock** (TCC's cross-process lock on `process/.process-write.lock`) but **keeps TCC's in-process thread lock**
   (see the decision below); the full wait in the env (the W-9 `timeout_s / 4` cap goes), and a child timeout = the
   work + the wait × the holds (`holds=3` for `close_capture`). The legacy path keeps `project_lock.hold` whole.
3. The in-process-hold guard (S–M): the thread lock is not re-entrant (`project_lock.py:137-138`), so a nested hold
   waits out its deadline today; a thread-local flag makes `spawn` refuse at once as `Busy`.
4. `Busy` kept as a type through `profile_writer`, `config_writer` (`SaveResult.busy`), `project_repo` (mapping
   only — its script never answers 75), `car_library`, MCP `_record`/`_close` (M). `profile_writer`'s callers catch
   `ProfileWriterError` (`core/agent_session.py:239`, `core/mcp_server.py:999`): its busy form is a subclass of
   `ProfileWriterError`, so their failure answers hold, and both routes get a test. The launcher matrix
   (`tests/test_method_cli.py:437`) covers these writers; what is missing is typed-`Busy` propagation — extend it.
5. `process/` (S): with change 2 the flock runs only on the legacy path, so TCC stops making `process/` ahead of the
   method — F-100's item settled by «stop making it»; `test_process_writer.py:23-60` relies on it today.
6. The round id after `capture-start` (S–M): from the verb's own stdout (`process.py:10113`), not the unlocked
   `capture_round()` read (`ui/tcc/measurement_panel.py:383-396`).
7. The capture check's result slot (M): the signal carries its `round_id` (`ui/tcc/workers.py:266,299`), and the
   verdicts are judged against that round (the `NotRun.at` rule), outside `main_window.py` (6072 of 6073 lines).
8. Tests (M, the bulk): «the other writer» becomes the method's own lock held from a subprocess (the vendored
   `write_lock.hold`, both platforms); T1–T4 of `PLAN-AUDIT` §5.4.

**#218 — the decision on TCC's own lock** (TCC's technical call, 2026-10-21, revised after Codex's plan review).
TCC keeps its **in-process thread lock** around every `process.py` child and drops only the **flock** for a
self-locking copy. Two reasons, both checked against the code:
- The round guard (`under_lock`, `process_writer.py:745-766`) protects `capture-check`, `capture-taken` and
  `capture-protective`; the method's verbs take the lock and then use whichever round is open (`process.py:2246`,
  `:2351`, `:2969`). Without TCC's lock, TCC's own capture-start between the guard and the child's lock moves a
  capture into another round — protection TCC has today between its own calls.
- On a folder where the OS lock is not available (a network share, the Mac↔VM shared folder) the method writes
  without a lock, with a `note:` (`write_lock.py:325`, `:383`); TCC's thread lock is then what keeps two MCP calls from
  overwriting each other. A test: OS lock unavailable, two concurrent writes, both in the state and the journal.

What the thread lock never covered — a session writing through the bare CLI — needs the method to check the round
under its own lock: `--round <id>` is asked (TCC-064, hub #297, a candidate for the skill's W-11); when a copy has it,
TCC passes it. The `test_process_writer.py:310` and `:368` assertions stay, their «other writer» moved to the
method's lock held from a subprocess.

**#219 — the method already has it:** REW's states as `rew_state` on the exception class (`rew_api.py:57-128`; read
`getattr(type(exc), "rew_state", None)` — TCC's copy is namespaced, `isinstance` fails), except REW answering
4xx/5xx: that is the standard library's `urllib.error.HTTPError` with no `rew_state` (`rew_api.py:168-177`) —
classified by `isinstance` first, before the «unknown» fallback; `Process.load(strict=True)`
→ `Unreadable` with `.reason`/`.repair`, or `ProcessError` for a newer schema; `set_filters` refuses before sending
and reads back. TCC reads none of it today: every REW exception is «offline» or text.

**#219 — left:**
1. Three-state REW status (M): `core/rew_bridge.py:64-71` returns a state (unavailable / answered an error /
   unknown — logged, not «offline»); the ping worker's signal carries it; the contract report's `rew.state` read
   (an `error`/`protocol` state shows green today); the decision in a Qt-free module (the ratchet); tooltips ×4.
2. The measurement panel (S–M): `rewStatusChanged` carries the state; `measReadFail` per state.
3. The capture check (S): «REW answered an error» told from a refusal only by the two full lines the method prints
   (`error: REW answered with an error: …`, `error: REW's measurement list was not read (…)`) — never by the generic
   `error:` prefix, which every refusal carries (`process.py:10584`); anything unrecognised stays the refusal, shown
   verbatim; pinned words or a code are TCC-064's ask 2. `measurement_view.absent()` reads `exists is False` first,
   the text as fallback.
4. The curve window (S): REW down or an HTTP error no longer greys a row as «not in REW».
5. MCP results (S, M of test churn): a `rew_state` field in `_record`, `check_captures`, `write_rew_filters` (plus
   «may hold the write» from `rew_unchecked`/`write_mismatch`); the `error` text unchanged.
6. K-2 on screen (M): `process_view` uses `Process.load(strict=True)` when the copy has it and carries the
   method's repair to the strip, the MCP answer and the plan panel (which says «No plan yet» over an unreadable file
   at launch today); TCC's mirror stays as the fallback.
7. Gate refusals (M): a refused MCP `enter_phase` reaches the strip; `contract_check` parses the top-level
   `unreadable` with its repair; a red gate names the file and the repair.
8. Texts ×4 languages (pl/de by the Advisor), CHANGELOG, `docs/guide/REFERENCE.md:106`.

Risks the maps name: a refusal shown wrongly blocks a working project (keep «the last plan stays, said once per
state»); older copies v3.1.0–v3.1.1 lack `rew_state`/`strict` (both came in v3.1.2) — detected by capability, not
version, and a missing state is «unknown», never «not found»;
`main_window.py` cannot grow, and new tests build no `MainWindow(`.

## Cost (estimate, 2026-10-21; the seam's share raised after the maps)

| part | machine time | Claude runs | Codex runs |
|---|---|---|---|
| Install and release tooling (#226, #227) | ~1.5–2 h | ~3 | ~4 |
| The method's seam (#218, #219) — 8 + 8 changes, the test rebuild the largest | ~7–11 h | ~8 | ~6 |
| Session (#221–#223) | ~2–3 h | ~4 | ~1 |
| Project folder (#224, #225) | ~1 h | ~3 | ~1 |
| The suite (#229) | ~1.5–2 h | ~2 | ~1 |
| The level base (#220), if the skill delivers | ~1–2 h | ~2 | ~2 |
| Final review + the PR's fix round | ~1–2 h | ~2 | ~1 |
| The guide (#230) + the walk's fixes (#228) | ~1.5–3 h | ~3 | Gemini ~1 |
| **total** | **~16–26 h** | **~27** | **~17** |

Against W-10 (24 issues, 64 Claude runs, ≈19 agent-hours): about half the issues, and the review seats move to
Codex. Wall clock: two to three days at the session's pace, plus the PR's CI (~35–40 min per run), the skill's
W-11 candidate (#220, the re-pin), and the Arbiter's walk on a clean Mac and the Windows VM.

## The implementer's brief (every spawn)

- Tree `~/dev/autosound/tcc`, branch `wave-11`. Read the issue (`gh issue view N -R ayukhno/autosound-tcc`) — it is
  the brief — and `CLAUDE.md`.
- `Risk: high`: a red test first, then the fix, then green; the report shows the red run. Ordinary: one test per
  behaviour the issue asks for. A new test must fail on the old code. Tests check what the person sees or what lands
  in a file, not timing.
- **Tests: only the changed files' tests** (`uv run python -m pytest tests/<file> -q`, at most `-n 4`). No
  `make check`, no whole suite: it runs on the PR's CI. `uvx ruff@0.12.0 check` on the changed files.
- `main_window.py` may not grow (`tests/test_structure_ratchet.py`): a change that adds lines there moves a decision
  out in the same task.
- Commit only your own files, by path (never `git add -A` / `commit -a`); the subject in English,
  `<group>: <what> (#N)`, with the session's attribution lines. No push.
- Report: what changed, the commits, the tests run and their result (the red run for `Risk: high`), anything left or
  doubtful.

## Ledger

| issue | state | implementer | commits | review | note |
|---|---|---|---|---|---|
| the plan | Codex's plan review (2026-10-21, `gpt-6-astra`, ~10 min; it could not reach GitHub, so the issues' text was not read): 7 findings, **7 real** after checking — HTTP errors carry no `rew_state`; the `error:` prefix is every refusal's; `rew_state`/`strict` came in v3.1.2; the writers have launcher tests, typed `Busy` is what is missing; `ProfileWriterError`'s catchers; dropping TCC's lock loses the round guard between TCC's own calls; and the unlockable-folder fallback — the last two changed #218's decision (keep the thread lock, drop the flock) | — | 83b5ad1 + this | Codex | a trial record: 0 false findings |
| #229 | the report on the issue (Codex, 2026-10-21): 25 findings; `GroupTable`, `git_facts`, `off_convention` spot-checked dead | — | — | — | the cleanup builds from that report |
