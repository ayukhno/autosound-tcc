# Why the suite breaks without product defects and why CI keeps getting slower (2026-11-10)

Scope: `ayukhno/autosound-tcc` at `c94a0467`; 268 `checks` runs since 09-15; 39 non-product
breakage episodes since 09-07 (hub `scratch/tcc/ci-analysis/3-fix-timeline.md`, R1..R39). Read-only;
nothing was run. Every claim below was checked at its source (`path:line`, commit, run id).

## 1. The answer in five lines

1. **Nothing is ever destroyed, so every test pays for every test before it.** Windows are kept alive by
   design (F-053); app-wide operations (stylesheet, font, language, GC) are O(alive widgets). The
   serial run costs 1.6–2x the sum of its files run alone, the weights table is wrong by up to 10x, and
   a test that takes 2 s in a shard takes 54 s on `main`. This is the first cost and the precondition for #2.
2. **Tests drive a real `MainWindow` whose own timers, watchers, threads and git children keep running,
   and wait with fixed event passes or wall-clock deadlines.** Fast process: the test ends before the
   product moves. Slow process (main serial, Windows, late shard): the product repaints over the test,
   or the deadline is overrun. 10 TIME episodes, #268, and both 11-10 failures are this one mechanism.
3. **Process-wide state has no per-test reset** (`qt_shutdown._LIVE/_DETACHED`, the app's sheet, font,
   palette, language, 17 product module caches). Any change in which files share a process — new
   shards, a re-weighted table, serial vs sharded — moves the red. 6 ORDER episodes.
4. **CI runs two different environments and trusts the wrong signals**: PR = 12 serial shards, `main` =
   one serial process (a third environment); Linux is `continue-on-error` and the gate reads the run's
   conclusion, so the Linux suite was red for three weeks while every run said green; limits were raised
   (30→45→60 min) instead of the cost being cut; every prose push to `main` costs ~100 runner-minutes.
5. **The suite's composition and the process multiply all of the above**: the method's self-tests,
   installer checks, a 10-writer race and real-`uv` packaging run in every shard of every run (~25% of
   the time, 3 ENV episodes); the suite grew 2104→7456 tests in eight weeks under "run everything,
   every time"; the only place a test meets Windows/Linux is the full ~20-min PR run; quarantine =
   `xfail(strict=False)` hides the result instead of reporting it.

## 2. The root causes

### RC1 — accumulation: alive widgets make cost superlinear and make the weights lie

**Mechanism.** `tests/_windows.py:1-14` and `tests/conftest.py:573-597`: a test's windows are never
deleted (deleting them crashed Qt at exit; `qt_shutdown.py:20-36`); one full run leaves 16,631 top-level
widgets, 87 `MainWindow`s (`qt_shutdown.py:13-15`). `QApplication.setStyleSheet` re-polishes every widget
in the process (`theme.py:2219-2227`), `i18n.set_language` retranslates every registered pane, and a
full `gc.collect` walks every object. So the N-th test's cost depends on N, not on the test.

**Evidence.**
- Commit `990ea0c7` (09-30, F-065) measured it: 2733 s vs 945 s for the same suite; 834 s in 23
  `setStyleSheet` calls, 827 s in 415 `set_language` calls, 437 s in GC. It cut the then-existing call
  sites by routing them through `tests/_windows.theme_on` and freezing the heap. `docs/TODO.md:1884`
  marks F-065 done: "main 5 min Linux / 12 min Windows" on 10-01.
- Today: Linux main 31.0–41.0 min, Windows 55 min / cancelled at 60 (runs 42724107999, 42766261211).
  Sum of the files run alone: 1154 s = 19 min on a Mac (`tests/shard-weights.json`, 11-09). The top-10
  single tests are 51.7% of the Linux run, and every one of them does an app-wide restyle, retranslate
  or zoom: `test_edit_mode_reaches_the_agent` 214 s (`test_main_window.py:8412-8415`, two real
  `_apply_theme`), `test_a_folded_panel_holds_through_the_mode_a_language_and_a_theme` 108 s
  (`test_control_layout.py:1746-1751`, two themes + two zooms), `test_a_changed_value_follows_a_theme_switch`
  83 s (`test_dsp_tree_compare.py:390-398`, `theme.apply_theme(app, …)` twice),
  `test_the_status_is_whole_at_the_narrowest_column_in_every_language` 117 s (`test_project_github.py:611`,
  `_restyle` + 4 languages × polish/unpolish). `main_window._restyle()` → `apply_theme(QApplication.instance(), …)`
  (`main_window.py:3222-3224`).
- **Why it regrew after `990ea0c7`:** the fix was a convention (`theme_on`), not a guard. 48 app-wide
  restyle call sites exist today across 12 test files (`grep` of `_apply_theme(|_set_zoom(|_restyle(|apply_theme(app|app.setStyleSheet(|app.setFont(`);
  5 of the 6 slowest tests were written on 10-01..11-09, after the fix. Each new wave adds tests that
  pay the tax, and the tax grows with the suite (2104 tests on 09-17 → 7456 on 11-09).
- **The weights table is wrong by construction** for the environment it packs: `record_shard_weights.py:10-27`
  records each file alone precisely to avoid the penalty, but a shard of 25–43 files pays it too.
  Table vs in-suite seconds: `test_ledger_line` 18 vs 175, `test_project_github` 82 vs 283,
  `test_main_window` 153 vs 389 (Linux, 42766261211). Shards packed to 289/288/289/289 s ran
  7.2/6.2/8.0/4.3 min on Linux and 14.6/10.7/11.2/14.2 on Windows (42722089408).

**Episodes explained:** R12, R13 (limits raised), R14 and R33's shard-2 overrun (one restyle per test ×
alive windows), the 11-09 shard cancellations at 25 min (42677312857), the 60-min Windows cancel
(42766261211), and — through RC2 — both 11-10 failures. **Why fixes did not hold:** every fix removed
one call site or raised one limit; nothing stops the next test from restyling the app, and nothing caps
the number of alive windows except the window-build ratchet (`test_structure_ratchet.py:56`, 196).

### RC2 — the product's asynchronous machinery runs during the test, and tests wait by the clock

**Mechanism.** A `MainWindow` built in a test keeps its real timers (`_RELOAD_COALESCE_MS` 400,
`_AGENT_REFRESH_MS` 300, `_pending_timer` 1000, `_nudge_timer` 2000, `main_window.py:557-697`), its
`QFileSystemWatcher`, its `QThread` workers and their git children. `_quiet_windows_left_behind`
(`conftest.py:401-425`) silences them only *after* the test. Tests then "settle" with two or five or eight
`processEvents()` passes (`test_ledger_line.py:598-605`, `test_control_layout.py:1381`,
`test_dialog_live.py:1090`) or poll with a deadline (`_until` 20 s, `test_project_github.py:138-145`;
5 s in `test_new_project_dialog.py:419-427`). In a 2-second test no 400-ms timer fires. In a 54-second
test (RC1) all of them do.

**Evidence.**
- 11-10, run 42766261211, `test_ledger_line.py:714`: the test called `set_sub(long_text)` and
  `set_sub_tip(...)`, then read the tooltip — and got the window's *own* DSP claim, dated
  "10.11.2026 06:15", i.e. the window's deferred reload repainted the section during the two event
  passes. The test took 54.2 s on main; it passed in the PR shard of the same tree.
- 11-10, same run, `test_new_project_dialog.py:425`: "the pause never ended", overshoot
  `1139.52 < 1138.84` → the last `QTest.qWait(10)` took ≥ 0.68 s; a 5-s budget on a real event loop in a
  process holding ~16k widgets. Same test failed on the macOS whole-suite nightly 39218070627 (10-19).
- #268 (`test_project_github.py:925`): waits for `qt_shutdown.live()` — the *process's* registry —
  to be empty; the `host` teardown waits `worker.wait(20000)` on every worker in the process
  (`:124-125`). Red on main at `c5b56ae4` (L+W), green on the PR of the same sha.
- R24 (watcher reload asks git 400 ms later), R28 (git answers "" within 3 s on a busy runner), R29
  (window resized before `floorChanged`, "four blind event passes"), R30/#233 (spy saw an earlier
  `git status`; fixed by blocking the watcher and stopping the timer), R36 ("window's own checks
  answered late", "read answered mid-loop and wrote its status over the sub under test") — each
  commit message names this mechanism, each fix is local to one test.

**Why fixes did not hold:** each fix taught one test to stop one timer or wait for one condition; the
window still starts everything for the next test. The "flaky-same-day" rule turns the next instance into
`xfail(strict=False)`, which stops reporting it (section 4).

### RC3 — process-wide state with no per-test reset

**Mechanism.** `conftest.py` resets a long list of product state per test (`:171-181`, `:673`,
`:1192`), but not: `qt_shutdown._LIVE/_DETACHED` (`qt_shutdown.py:61,71`; nothing in `tests/` clears it),
the application's stylesheet/palette/font (`app_ground` exists but is used in 2 files), `i18n`'s current
language (151 `set_language` calls, restored only by individual `finally` blocks), and 17 product
module-level caches never mentioned in `tests/` (`curve_view._KEPT_CTRL_FORMS`, `method_lock._CACHE`,
`critic._*_CACHE`, …). What a test sees therefore depends on which files ran before it in this process.

**Evidence.** R9, R33, R39/#268: three generations of the same assertion on the shared registry
(`settled` fixture, `test_project_github.py:129-135`: "«empty» depended on the shard's order"). R14,
R17, the card-fits test (`docs/TESTING.md:228-233`: "the font an earlier test had left was different").
R33 appeared "once the shards changed" (`1dda4063`): re-recording the weights (`98505f33`) re-cut the
shards, and the tests that read process state moved from green to red without a code change.

**Why fixes did not hold:** each fix made one test read its own delta (`settled`) instead of adding the
reset to conftest; the fourth test (#268) kept the old wait, and the next file that asserts on the app's
font will do the same.

### RC4 — CI shape: three environments, blind signals, limits instead of cost

- **PR ≠ main.** PR = 12 shards of 25–43 files each; main = one process of 150 files (`ci.yml:158-194`,
  `:221-258`). Same sha, different process history → RC1–RC3 give different answers: main-red/PR-green
  pairs at 681d535e, 8dc1087b, c5b56ae4 (and R6, R24, R28). The main run exists to "catch what fewer tests
  per process can hide — HUB-049 and #19" (`ci.yml:26-29`). #19 was fixed 09-12; HUB-049 closed 09-14 with no
  recurrence. Since 10-02 the main run found 0 product defects and produced 7 test-only reds.
- **Linux red is invisible.** `continue-on-error: true` on the main Linux job (`ci.yml:231`) and on Linux
  PR shards (`:166`); `release-preflight` votes per workflow run (`docs/TESTING.md:161-170`). Verified: run
  40835448465 — job `linux (run 1)` failure, run success. The installers test was red on every finished
  Linux main run from 10-21 to 11-09 (11 runs) and the gate passed releases over it. PR 40196496923 is
  green with Linux shard 1/4 red.
- **Cancellation, not completion.** `cancel-in-progress: true` (`ci.yml:80-84`): 82 of 136 push runs
  cancelled; on 10-01 twenty-five runs in 85 minutes. Nobody reads main ("nobody waits for it
  interactively", `ci.yml:29`), so a three-week red goes unnoticed.
- **Limits raised four times** (R13, R25, R36; 30→45→60 min; 120→360 s; `joint_search` 600 s) — each
  time "slow, not hung" — and the limit was hit again within weeks (42766261211).
- **Every push runs the whole suite, prose included** (`ci.yml:11-12`): a tag-ledger or SESSION-STATE
  commit costs ~40 Linux + ~60 Windows runner-minutes and a fresh chance for RC2 to go red on main.

### RC5 — composition and growth

- `test_skill_selftests.py` runs the vendored method's own self-tests as subprocesses: 268–373 s on
  Linux main (14%), ~339 s on Windows, `joint_search.py` alone 93–147 s; `installer-consistency.py`
  90–107 s on Windows (`:148-152`) and red for three weeks on Linux for the pinned skill's own reason
  (R31). `test_writer_race.py` 62–81 s, `test_packaging.py` real `uv`. These are tests of other
  systems and of the runner's shell, run in every shard of every PR and push.
- Width/elision tests measure pixels under whatever font the runner has; windows-latest offscreen has a
  box font (`tests/test_detail_pane.py:1957-1972`). 4 FONT episodes, 17 skip sites, #264 open.
- Growth: 2104 → 7456 tests (3.5x) between 09-17 and 11-09; 108K lines of tests vs 86K of product;
  hub `SKILL.md:124-125` already records 3.4 test lines per code line in W-10. `docs/TESTING.md:5-22`
  says "run everything, every time" and "deliberately no fast/slow split". With RC1 the cost of
  "everything" is superlinear in "everything".

## 3. CI duration

**Where the time goes (Linux main 42766261211, 1862 s pytest):** top-10 tests 51.7% (all app-wide
restyle/retranslate, RC1); `test_skill_selftests` 268 s; `test_project_github` 283 s (84 tests: real git
repos, `_until` polls, `worker.wait(20000)` on the process's workers); `test_writer_race` 62 s. Windows
is 1.3–2.2x Linux and the Windows log is `-q`, so per-test Windows times do not exist.

**Why it regrew after `990ea0c7`:** (a) 48 new/remaining app-wide restyle sites (RC1), each costing
seconds × alive windows; (b) 3.5x more tests, so more alive windows per restyle; (c) two new heavy files
on 11-09 (`test_project_github.py`, `test_ledger_line.py`: 6809 → 7456 tests, Linux main 20.8 → 31–41
min). The fix of 09-30 cleaned the tests of that day; it installed no guard.

**Realistic target.** With accumulation removed (one process per file, option A1) the serial cost is the
solo sum: ~19 min Linux / ~30 Windows (still too long for main); a 4-way split is ~5 min Linux, ~8–10
Windows; moving the method's self-tests and installer check out of the shards (G) takes ~4.5 min off
every Windows shard; 6 Windows shards then land at **≈ 5 min wall for a PR on every OS, ≈ 6 min for
main** if main uses the same shards (I). Without A1 nothing else gets below ~10 min on Windows.

**As designed:**
- *Weights table* — right idea, wrong model: solo seconds packed into a shard that accumulates. Correct
  only if shards stop accumulating (A1) or if recorded from the shard logs per platform.
- *Sharding by file* — right (module-scoped `QApplication`, module state).
- *Serial main run* — its stated purpose (HUB-049, #19) has been met since 09-14; since then it has cost
  40–60 min per push and found only test-timing reds. Not right any more.
- *`continue-on-error` on Linux* — wrong since hub#100 closed: it hides real failures and the gate reads
  the run. *Time limits* — the 25-min shard limit is right as a hang guard; 45/60 on main are limits that
  follow the cost; a per-test timeout (D) is the missing one: today a hang gives "cancelled, test unknown".

## 4. Process flaws

- **A test meets Windows and Linux only on the full PR run.** Locally only the changed files' tests run
  (`WAVES.md` §1 step 3), on a Mac with real fonts, `sh`, `flock`. So PATH (5), FONT (4) and ENV (3)
  classes can only appear at the PR, and each round costs the whole 12-shard run: W-12 = 5 runs ×
  ~20 min for 19 red tests, 1 product defect; the fix of `e8c07f90` "cured nothing on Windows and broke
  Linux" and only the next full run said so. #263 (fast named-test run) names the gap; it is not built.
- **The main run is a second, different exam that nobody watches**, taken after the merge, with its own
  reds (RC4). The wave process says the PR's green run *is* the release's test run (`WAVES.md` §1 step 4),
  yet the suite still runs whole on every push, and every bookkeeping push to `main` restarts RC2's lottery.
- **Quarantine hides.** `xfail(strict=False)` never reports XPASS and never fails; the mark's reason
  records no mechanism class (ORDER vs TIME need different fixes). Three quarantines, one lifted. The rule
  "a mark that stood a whole wave comes up at the next milestone: fix or delete" (hub `SKILL.md:126-131`)
  has no budget and no owner; `docs/TESTING.md` "Known flakiness" lists three items, none from R30–R39.
- **Linux red reports green** (RC4) — and the rule "one green CI per commit" (hub `88db093`) is satisfied
  by a run whose Linux job failed.
- **Rules that are wrong or missing:** "run everything, every time / no fast-slow split" (TESTING.md) is
  wrong under superlinear cost; "tests by risk" and "behaviour, not timing" (hub `SKILL.md`) exist but no
  mechanism enforces "not timing" (no lint on fixed `processEvents` loops, no per-test timeout); there is
  no rule that a test may not restyle the application, no reset rule for process-wide state, no suite
  cost budget per wave (the only ratchet is window builds, 196), and no rule that a quarantine must name
  its class and its reproduction.

## 5. Fixes, as options

Advised first: **A1 + G + H + D + K** (all S), in one infra wave, because together they remove the
accumulation tax and the invisible reds without touching a single test, and they make every later
option measurable. The decisions marked (owner) change a recorded policy.

### Suite architecture

| id | change | size | risk | removes | verify |
|---|---|---|---|---|---|
| **A1** | One pytest process per test file in CI shards (and on main): `for f in $files; do pytest $f; done`, exit code aggregated, `--junitxml` per file | S (ci.yml only) | low–medium: 150× the exit-time `destroy_application`; +1–2 min startup per shard | RC1 across files, RC3 across files (R9, R33, R39, R17, card-fits); makes the weights table exact by construction | shard minutes vs the table within 20%; a 10× `linux_runs`/`windows_runs` series with 0 exit-139 |
| A2 | Same per-file loop locally (`make test`) | S | none | the Mac OOM of a whole run (memory is per process) | one local full run finishes beside the VM |
| B | Destroy windows per test (F-053 "first way") | L | high: measured crashes with pyqtgraph (`qt_shutdown.py:20-36`) | RC1 within a file | not advised |
| **C** | conftest guard: snapshot/restore the app's sheet, palette, font and language per test; fail a test that calls `QApplication.setStyleSheet`/`setFont` unless marked `restyles_app`; a ratchet on the count (like `WINDOW_BUILDS_MAX`) | M (one fixture + ~48 marks or conversions to `theme_on`) | low | RC1 regrowth, R14, R17; the 51% of main time in the top-10 tests shrinks to their solo cost | `--durations=20` on main: no test > 10 s |
| **E** | A window built in a test starts quiet: conftest wraps `MainWindow.__init__` to stop its timers and empty its watcher after construction; a `live_window` fixture for the tests that are about the timers (owner: changes what "a real window" means in a test) | M | medium: some tests rely on a timer firing | RC2: 11-10 ledger_line, R24, R28, R29, R30, R36 class | the same tests green on a 3× slowed run (`taskset`/`nice` or Windows) |
| F | One wait helper (`tests/_wait.py`): condition + deadline, raises with the predicate's last value; a lint that forbids bare `for _ in range(n): processEvents()` and `qWait(const)` | M | low | R6, R29, the 5-s pause class; makes a hang name itself | lint green; no fixed-count loops left |
| **G** | Move `test_skill_selftests.py`, installer consistency, `test_writer_race.py`, real-`uv` packaging into a `method` job that runs when `vendor/` or `scripts/` change and nightly; keep the discovery test in the suite (owner: TESTING.md says the self-tests ride in the suite since 08-07) | S | low | R31, R25's and R36's bound-raising; ~270 s Linux / ~340 s Windows from every shard and main run | shard makespan drops by that; the `method` job still runs on a pin change |
| J | Bundle one TTF in `tests/` and set it as the application font in conftest for all width tests (owner: width tests then measure a test font, not Segoe UI) | S–M | low | FONT class R15, R16, R26, R32, 17 skip sites, #264 | the skips removed; Windows shard green |
| N | Per-test reset of `qt_shutdown._LIVE/_DETACHED` snapshot (fail the test that leaves a running worker, like `_no_mcp_call_outlives_its_test`) and of the 17 module caches | S | low | RC3's remaining instances; #268 | #268's mark removed and green on main 5× |

### CI

| id | change | size | risk | removes | verify |
|---|---|---|---|---|---|
| **H** | Drop `continue-on-error` on Linux (PR and main); keep `PYTHONFAULTHANDLER` | S | low: a real exit-134 would block — it has not appeared since 09-14 | the invisible red (3 weeks), gate blindness | a failing Linux job fails the run |
| **D** | `pytest-timeout` with `timeout = 120`, `timeout_func_only = true` | S | low; on Windows the thread method ends the process, which still names the test | "cancelled at the limit, test unknown" (42677312857, 42766261211, 6 nightly cancels) | a deliberate `sleep(200)` test is named in the log |
| **I** | `main` runs the same 12 shards as the PR (owner: retires the serial whole-suite argument of `ci.yml:26-29`); the serial whole suite stays available as a dispatch series and a weekly job | S | low | the "main red / PR green" class by construction; 40–60 min per push → ~6 | main and PR on one sha agree 10 runs in a row |
| I2 | Skip the run on pushes that touch only `docs/`, `CHANGELOG`, `.pending` *unless* it is the release commit — or let the release gate accept the PR run on the same sha (it already does, `TESTING.md:166-169`) | S | the HUB-058 argument (`ci.yml:9-12`); owner's | ~100 runner-minutes per prose push | push count vs run count |
| **K** | `workflow_dispatch` input `tests` → a job that runs those node ids on all three OS (#263) | S | none | the 20-min round for a test-only fix; PATH/FONT fixes checked in ~2 min | a named test's three results in < 3 min |
| L | Record weights per platform from the shard job's own `--durations` (only if A1 is not taken) | M | low | shard imbalance (4.3 vs 8.0, 10.7 vs 14.6) | makespan within 15% of the mean |
| M | `-v` or `--durations=50` on the Windows jobs | S | log size | the blind spot in section 6 | per-test Windows times exist |

### Process

| id | change | size | owner's? | removes |
|---|---|---|---|---|
| P1 | A quarantine names its class (ORDER/TIME/FONT/PATH/ENV) and the reproduction that would close it; `xfail` replaced by a marker that still records pass/fail in the job summary; cap of 3 open quarantines, each with a milestone | S | yes | hidden results; "or delete" as the default |
| P2 | Before the PR, the wave runs K on the tests it added or changed — a rule, not a habit | S | yes | first-contact PATH/FONT rounds |
| P3 | A suite cost budget per wave: sum of solo weights may not grow more than X% without an `infra` issue; `/test-audit` with a delete quota | S | yes | the 3.5x growth drift |
| P4 | `docs/TESTING.md` rewritten: "run everything" → "every test runs once per PR, in a shard, in its own process"; the parallel/`-n` section retired once A1 holds | S | yes | a policy that contradicts the mechanism |
| P5 | The gate reads jobs, not the run (or H) | S | no | gate blindness |

## 6. What could not be established, and the cheapest way

- **The exact slot that ate ≥ 0.68 s per `qWait(10)` in `test_a_changed_tick_runs_one_seed_after_the_pause`**
  (a leftover window's slot vs the event backlog). Cheapest: run `tests/test_main_window.py
  tests/test_new_project_dialog.py` in one process locally with `--durations=0` and a `QTimer`
  spy; two runs settle it.
- **Per-test Windows times and which test hangs in a cancelled shard** — logs are `-q`. Cheapest: M.
- **Whether `host`'s `worker.wait(20000)` on process-wide workers is what makes `test_project_github`
  283 s Linux / ~640 s Windows** (84 tests). Cheapest: `--durations=20` on one main run (M).
- **Whether per-file processes reintroduce the exit-139/134 crash** (A1's risk). Cheapest: the existing
  `linux_runs: 10` / `windows_runs: 10` dispatch on a branch with A1.
- **Whether `QT_QPA_FONTDIR` works on windows-latest** (#264) vs bundling a font (J). Cheapest: one K run.
- **Whether the 29% `-n auto` worker crash is the same fault as R22/R27 (widget before QApplication).**
  Moot if A1 is taken; otherwise a 10× local series with `faulthandler` and `-p no:cacheprovider`.
- **Windows "slow stretches"** (10-minute gaps in `test_project_github`, `test_mcp_key`, `test_critic`):
  not attributable without M.
