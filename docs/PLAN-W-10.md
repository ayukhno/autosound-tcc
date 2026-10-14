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
| 4 | Rounds and the bank | #197, #198, #199, #200 | the skill's halves of #198/#199 ticketed first; #200 waits for the skill's W-10 tag |
| 6 | Codex (#181, the Arbiter: «в цій») | #181 | `feature-dev`: code map → questions → architects → his choice → build; after the AI picks group (shared files) |
| 5 | Window polish, Leftovers | #203, #166, #167, #204, #180; #205–#209 | the Haiku trial |

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
| Codex task 5 (`shell_gate.judge_action`) | re-review of 6e07979: C1/C2/I3/I4/I5 closed; Critical — the `auto` symlink escape (`ln -s ~ h`, then `rm -rf h/`; older, in `bash_is_dangerous`, also the SDK route's) and PowerShell junctions passing `foreign`; Important — the writer's process-folder operand → third fix round | opus · high | 54e6b96, 2b56a6c, 6e07979 | opus · high | the third round also tightens the Claude route (`bash_is_dangerous`) |
| Codex task 6 (`CodexSession` turns) | review: «do not merge as is» — Important 3 (a `turn/start` timeout hangs the turn; Stop before the turn id is lost; the frame log stops at its cap) + test gaps (isolation from a real `config/read` never exercised) — fix round running | opus · high | 1464e49 | opus · high | 26 tests on the stand-in; approvals declined until task 7; `CODEX_ROUTE` on, `codexNotYet` gone |
| #181 spike | done — all six PASS (`spike/codex-app-server/RESULT.md`) | opus · high | 464159d | — | build L: 3–4 days macOS + ~1 day Windows; risks: app-server experimental (pin the version), the user's `~/.codex` servers/plugins/hooks switched off per process; the build: in W-10 (the Arbiter, 2026-10-14) — the Arbiter chose the blended design (`docs/PLAN-W-10-codex.md`, 10 tasks, ~5.5–6 days) |
| #181 | done — the study, `docs/STUDY-W-10-codex-primary.md` | opus · high | (this commit) | — | feasible, L (2–4 days); next: a ≤1-day spike on six points; five questions for the Arbiter (§5) |
