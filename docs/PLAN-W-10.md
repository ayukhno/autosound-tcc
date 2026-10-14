# PLAN W-10 · v1.1.4 — real use and earlier waves' leftovers

The milestone `W-10 · v1.1.4` (#10): 25 issues, all `ok` (the Arbiter, 2026-10-14). The map by group and the
ranking: `docs/W-10-POOL-RANKED.md`. State: `docs/TODO.md` F-102.

**The arm: no engine** (`hub/bin/role tcc --no-SP`, hub H-022). The method is `hub:seam` «Без двигуна»: the
session builds or briefs an Agent; the seats from «Process weight»; `Engine: none` in the PR body. One branch,
`wave-10`, in the main tree; one PR; the full suite runs once, on the PR's CI.

## Order (the Arbiter's «го», 2026-10-14)

| step | group | issues | note |
|---|---|---|---|
| 0 | the Arbiter's retest on the VM, v1.1.3 | #184, #192, #183, #165 | done 2026-10-14: #192 and #183 do not reproduce → closed; #165 reproduced on this Mac and fixed (40185b3); #184 works on the Mac, Windows checked in real work — nothing built unless it reproduces |
| 1 | Release tooling | #201, #202 | cheap; makes the release itself cheaper |
| 1‖ | a study, beside everything | #181 | a document, no code |
| 2 | Install and update | #194, #195 | #195 may need a skill ticket for the method's half |
| 3 | AI picks + what step 0 leaves | #196, #182, #165; #184, #192, #183 | |
| 4 | Rounds and the bank | #197, #198, #199, #200 | the skill's halves of #198/#199 ticketed first; #200 waits for the skill's W-10 tag; #200 also runs the method's `project.py <dir> agents-setup` before a Codex start (in-app and terminal) so a project made before skill #149 gets the `AGENTS.md` Codex reads |
| 6 | Codex (#181, the Arbiter: «в цій») | #181 | `feature-dev`: code map → questions → architects → his choice → build; after the AI picks group (shared files) |
| 5 | Window polish, Leftovers | #203, #166, #167, #204, #180; #205–#209 | the Haiku trial |
| 7 | the Windows pass, last | Codex task 10's Windows half, #184 | the Arbiter, 2026-10-14: «віндоус треба оновити щоб перевіряти. зробимо в кінці» — Windows on the VM is updated first; the VM pass runs after every group is built, before the final review. The macOS live run of task 10 stays in order |

Code implementers run **one at a time** in the tree (no parallel edits, no tests over a changing file); the study
runs beside them. Bought 2026-10-14: #194's re-review ran while the AI picks group had `tests/conftest.py` half-edited — 445 setup errors; it re-ran on a `git archive`.

## Weight and models (`hub:seam`, with the Arbiter's word of 2026-10-14 on Haiku)

| task | implementer | task review | group |
|---|---|---|---|
| `Risk: high` — #184, #194, #195, #197–#201 | opus · high, test first | opus · high → one fix round → re-review of the fix | silent-failure + test seats (opus · high) → one fix round |
| ordinary — #165, #180, #182, #183, #192, #196, #202, #204–#206, #208, #209 | opus · medium | none | the same two seats |
| mechanical — #166, #167, #203, #207 | **haiku · high** (#166, #203) / **haiku · xhigh** (#167, #207) — a trial | none | the same two seats; their findings on these four counted apart |
| the study #181 | opus · high | — | — |
| the wave | — | — | one final branch review on **Fable** (the wave holds `Risk: high` code) |

**The Haiku trial** (the Arbiter, 2026-10-14: «для механічних задач спробувати Хайку 5.5 … high чи extra high —
треба зрозуміти можливість нової моделі»). It replaces TCC's Sonnet trial for this wave. History: on 2026-10-13
Haiku 5.5 did not make a small mod edit (it stopped at a hub guard and left a plan with an error) — effort unknown
then. Measure per task: done or not, defects the Opus seats find, rework rounds, time; high against xhigh. The
result goes to the ledger below and one line to the hub's H-019.

## Cost (estimate, 2026-10-14; hub #282)

Machine time ~16–22 h — the subagents' run time over the whole wave, of which ~6 h spent by the evening of
2026-10-14 (Release tooling, Install and update, AI picks, the Codex study, spike and tasks 1–7).

| part | machine time | agent runs |
|---|---|---|
| done: three groups + #181's study and spike + Codex tasks 1–7 | ~6 h | ~60 |
| Codex tasks 8–10 + its group seats | ~3–4 h | ~10 |
| Rounds and the bank (#197–#200, Risk: high) | ~3–4 h | ~12 |
| Window polish + Leftovers (10 issues; the Haiku trial on four) | ~3–5 h | ~15 |
| the final branch review (Fable) + the PR's fix round | ~1–3 h | ~3 |
| **total** | **~16–22 h** | **~100** |

Wall clock: two to three more days at the session's pace, plus the PR's CI (~35 min per run) and the Arbiter's
live Codex run and Windows VM pass (task 10). Codex usage: the spike and task 1 spent ~356k tokens on the cheapest
model; task 10's live run is the next spend.

## The implementer's brief (every spawn)

- Tree `~/dev/autosound/tcc`, branch `wave-10`. Read the issue (`gh issue view N -R ayukhno/autosound-tcc`) — it is
  the brief — and `CLAUDE.md`.
- A red test first for a defect; then the fix; then green.
- **Tests: only the changed files' tests** (`uv run python -m pytest tests/<file> -q`, at most `-n 4`; plain `uv run pytest` fails to spawn on this Mac). No `make check`, no
  whole suite: it runs on the PR's CI, and a local one loads the Mac beside the VM. `uvx ruff@0.12.0 check` on the
  changed files.
- Commit only your own files, by path (never `git add -A` / `commit -a`); the subject in English,
  `<group>: <what> (#N)`, with the session's attribution lines. No push.
- Report: what changed, the commits, the tests run and their result, anything left or doubtful.

## Ledger

| issue | state | implementer | commits | review | note |
|---|---|---|---|---|---|
| #201 | done — re-review clean (ship as is); hub #246 told the command |  opus · high | 0a01d66, 5e24c74, 228fe1a | opus · high | ship skips the local suite on `ci-green` ok; `make ship VERSION= AT=` dry check; CHANGELOG v1.1.3 corrected; fallback cannot run today (the hub fails ci-green and windows-ran on unreadable CI) |
| #202 | built | opus · medium | 05230bb, b3f722e | — (ordinary; the group seats) | a test race with the folder watcher's reload (400 ms); `ci_shard.py` prints UTF-8 on a cp1252 pipe. Found: TCC reloads ~0.4 s and ~0.94 s after its own pick lands in `.tcc/` — a pool line (F-102) |
| Release tooling group | seats done: Important 2 (AT reads TCC's tags when the submodule is not initialised; AT's published-tag seam untested), Minor/gaps 11 — done — fixed in 6c02aed, 07522b4 (all 10); re-review: one Minor (a `-` URL reached ls-remote as an option) fixed by the session in this round's last commit | — | — | opus · high | not now: the self-triggered reload (pool), suite-wide `filterwarnings`, the «READY» wording |
| #194 | done — last re-review: no regression; uv ≥ 0.5.6 (uv #9547) confirmed; the README URL is v1.1.3's until the release bump (404 till then) | opus · high | 14b02a3, fc6cfe1, f008582, 7de4aab, cc7000b | opus · high | Windows cmd cases first run on the PR's CI; the downgrade 6.12 → 6.11.2 needs one real update on the VM after v1.1.4 |
| AI picks group (#165, #196, #182) | done — the group fix round 7f86554: the four «could not ask» paths say why; the 157 alias honoured once; no «gone» offer from a list still being read; startup asks claude/codex after agy and sdk, claude only on ↻ or a changed binary; pickers' decisions moved to `core/model_picks.py` (main_window 6225 → 6138, ratchet lowered); pl/de by the Advisor (agy gemini-3.8-flash-high) | opus · medium | 40185b3, 255c5ac, 537616f, cbfee77, 6a70992, 7f86554 | the group seats (ordinary: no re-review) | the skill's `failure_reason` → hub #281 |
| #195 | done — the last Minors in f46ebd2 (a `finally` for the shared job, only «good» kept, temp cleanup, fallback only on a filter refusal) | opus · high | cd1fdb3, c3ac6b6, f46ebd2 | opus · high | pl/de by the Advisor (agy gemini-3.8-flash-high) |
| Install and update group (#194, #195) | done — re-review: all 5 closed, no regression («ready to release»); Minor 2 fixed by the session (uv's version line silenced); Minor 1 (the developer's switch installs ≥ v1.1.4 without the `nopins` line — developers only) → the pool | — | e336c54, 582e16b + the session's | opus · high | the first update INTO v1.1.4 runs v1.1.3's code: unpinned, unsaid — the file holds from v1.1.4 → next |
| Codex task 1 (fixtures, stand-in) | done — 2 paid turns, 62.4k tokens (47.9k cached) on gpt-5.6-luna/low; 13 scenarios, a 41-method schema cut, the stand-in asserting exactly-once | opus · medium | acaf06d | — | what binds the later tasks: `docs/PLAN-W-10-codex.md` «Learned in task 1» |
| Codex task 2 (registry routes, `session_routes`) | done — review: no Critical/Important; 4 Minors fixed by the session (e89f0ca: a Codex pick reads the SDK route until task 6; stale probe comments) | opus · high | 747128a, c9a78cd, e89f0ca | opus · high | main_window 6138 → 6095 |
| Codex task 3 (`codex_rpc`) | done — 20 tests against the stand-in; the model list moved onto `ask_blocking` (paging, reasons kept) | opus · medium | cb70b5c | — (the Codex group seats) | notes for task 6 in the Codex plan |
| Codex task 4 (`codex_cli`) | done — `find`/`version`/`probe` (one app-server, paging), the picker and availability wired, the reviewer env, `codexNotYet` until task 6; checked on this Mac: the npm shim → the native binary, 0.162.1, signed in, 7 models | opus · medium | 1475e33 | — (the Codex group seats) | pl/de by the Advisor (agy gemini-3.8-flash-high) |
| Codex task 5 (`shell_gate.judge_action`) | done — the last round ba3264e: a delete/move of a path missing at check time after an earlier statement in the same line asks (a link made by python/perl/tar); `cd`/`export`/`echo` exempt (Ruling 49 kept); the junction walk without `isjunction` | opus · high | 54e6b96, 2b56a6c, 6e07979, 9bf24f8, ba3264e | opus · high | the `foreign` hole closed fully (the Arbiter); omp and the SDK route ask more — every changed row in `CHANGED_FOR_OMP` / `CHANGED_FOR_SDK` |
| Codex task 6 (`CodexSession` turns) | done — re-review: I1–I4 and the Minors closed, «task 7 can build on this file»; M1–M3 folded into task 7; the `ask` cancel hang not reproduced in ~230 tries (M4 → task 7 checks the repro) | opus · high | 1464e49, a70218e, beeac31 | opus · high | |
| Codex task 7 (approvals through the gate) | re-review of 9010b4d: C1/I1/I2/M1–M3 closed; N1 a tick outranks a foreign cwd and a dangerous line (old, all routes) → **the Arbiter: a tick never outranks «cannot be undone»** (omp, SDK, Codex); N2 a subfolder cwd judged with an absolute `cd` lets `rm -rf ../..` pass (a regression) → second fix round (f79dd15: the tick rule on all three routes, `CHANGED_FOR_OMP`/`CHANGED_FOR_SDK` rows flipped, relative `cd`, sweep of the current turn only, fired timers dropped) → **re-review clean** (946 passed; probes: ordinary lines pass with a tick, dangerous ones ask on every route incl. PowerShell spellings, symlinked cwd, quote spoof in a folder name) | opus · high | 032c28c, 9010b4d, f79dd15 | opus · high | |
| Codex task 8 + tcc #180 («Open terminal» submenu; Codex in a terminal with TCC's tools) | done — submenu Terminal/Claude/Codex/Antigravity/OMP everywhere the action is; `codex_terminal` (token only in env, `tcc_connection_args` split from the session's `tcc_tool_args`); no fallback to Claude; `main_window` 6095→6080. Codex 0.162.1 has no `-c` key for an extra skills root: a terminal Codex gets the method through the project's `AGENTS.md` + `AUTOSOUND_SKILL_ROOT` (check in task 10). For the group seats: the token reaches the terminal Codex's shells (`shell_environment_policy` left to the user's config) | opus · medium | 3427ed1 | — (group seats) | |
| Codex task 9 (install from the official wheel, sign-in button, menu lines, blockers, strings) | building — brief `hub/scratch/tcc/w10/codex/BRIEF-task9.md`; also task 8's leftovers (the «not installed» sentence names the menu line, the plain terminal's hint as an i18n key) | opus · high | | opus · high | |
| N2 for the skill's beta-v3.1.4-rc1 (hub #283) | answered on hub #283 (run 38555923376): none is the skill's; 17 TCC tests/fakes on the old method, 3 XPASS(strict) markers, 1 Windows installer check under TCC's `USERPROFILE=tmp_path`, 1 Ubuntu flake (the 4/4 re-run passes it, job 115831006652). Draft: `hub/scratch/tcc/w10/N2-283-answer.md` | — | d84a0cb | — | #200 takes every TCC row: drop the tcc#149 patch and its tests, key matching in `measurement_panel` ~1424 / `process_view.outstanding` / `measurement_view` ~858-900, the parity table rewritten, `_FAIL_ON_WINDOWS` gone, installer check with the real profile; plus SKL-073 items 1 and 5 |
| #181 spike | done — all six PASS (`spike/codex-app-server/RESULT.md`) | opus · high | 464159d | — | build L: 3–4 days macOS + ~1 day Windows; risks: app-server experimental (pin the version), the user's `~/.codex` servers/plugins/hooks switched off per process; the build: in W-10 (the Arbiter, 2026-10-14) — the Arbiter chose the blended design (`docs/PLAN-W-10-codex.md`, 10 tasks, ~5.5–6 days) |
| #181 | done — the study, `docs/STUDY-W-10-codex-primary.md` | opus · high | (this commit) | — | feasible, L (2–4 days); next: a ≤1-day spike on six points; five questions for the Arbiter (§5) |
