# W-10 — the pool outside the audit, ranked (2026-10-14)

Asked by the Arbiter on 2026-10-14: every task **outside the audit** (`docs/PLAN-AUDIT-2026-10.md`) and every task
**left by earlier waves**, ranked and assessed. Collection is still open, and this list is the input to the
milestone review. Nothing here is built without `ok`.

**The order, as it stands (2026-10-14).** The Arbiter's order of 2026-10-06 (`PLAN-AUDIT` §3, *all of the audit's
tasks build first*) is superseded: hub #273's amendment (2026-10-13) closes the audit at its minimum (TCC's G8 phase 1
and G7) a wave later and sends the rest to the pool, TCC's call; the Arbiter, 2026-10-14: W-10 takes everything outside
the audit from real use, plus what earlier waves left. So finding 158 (G4 2a) and the curve window's minors (G10 M) are
this pool's now.

**On the milestone `W-10 · v1.1.4`** (opened 2026-10-14, review mode, no `ok` yet), by group:

| group | issues (rank) |
|---|---|
| Capture after update | #184 (1), #192, #183 (2) — each starts with «retest on v1.1.3» |
| Install and update | #194 (158), #195 (7) |
| AI picks | #165 (3), #196 (5: 157, 156, hub #262), #182 (5) |
| Rounds and the bank | #197 (4), #198 (10, hub #268), #199 (11, hub #260), #200 (the re-pin to the skill's W-10 tag) |
| Release tooling | #201 (8: hub #277 ask 1, hub #246), #202 (9) |
| Window polish | #203 (12, hub #257), #166, #167 (14), #204 (15), #180 (19) |
| Leftovers | #205 (6), #206 (16), #207 (17), #208 (18), #209 (the curve window's minors, F-100) |

**Not on it yet** — the Arbiter's word first: #13 hub #264, #20 tcc #181, #21 F-096. **Dropped:** F-098's
`write_mcp_config` on `OSError` — closed in W-9 (#173, Task 19: `own_store`, the aside copy).

**Scale.**
- Size: **S** ≤ 2 h · **M** ≤ 1 day · **L** > 1 day.
- Risk: **high** = data writes, locks, signatures, installers, the method/TCC seam; anything else is **ordinary**.
- Model: from `hub-seam` «Models by role».

## Covered by the audit on 2026-10-06 — where each went is in «On the milestone» above

| item | the audit's place |
|---|---|
| finding 158: the update installs deps newer than `uv.lock` (PySide6 6.12.0 against 6.11.2) | G4 part 2a, **W-10**: `constraints.txt` = `uv.lock`, the updater's `-c` |
| F-100: TCC's lock makes `process/` on POSIX, not on Windows; the bare CLI takes no project lock; the round slot read without the lock | G8 phase 1, W-11 |
| F-100: the curve window's minors (hx `apply_theme`, N-B1, «different set», Fable m2/m3) | G10 M part, W-12 |
| F-098: `write_mcp_config` replaces the file on any `OSError` | G3, built in W-9 (`PLAN-W-9.md:514`). **Check it closed**, then drop it. |

## Tier 1 — measurements lost or a route that does not start

| # | task | source | class | risk | size | model | note |
|---|---|---|---|---|---|---|---|
| 1 | **Done in the capture panel freezes it; the last two measurements are lost** (also gone from REW, after a force-quit, live in a session) | tcc #184 (canonical), #189, #191 | bug | high | M | opus · high | No log, no version. **Retest on v1.1.3 first**: W-9's G9 S1 bounded the GUI thread's waits, and the re-pin put capture-close under 120 s. Still there → reproduce it, then a test. |
| 2 | **The measurement window does not open after an update; the curves window crashes on open** (v1.1.1) | tcc #192 (canonical), #185–#188, #190; #183 | bug | ordinary | S–M | opus · medium | Six reports with no version and no log. **Retest on v1.1.3**. A lead to check, not a diagnosis: F-100's M3 says nothing tells the user how to install when `pyqtgraph` is missing (`MainWindow._open_curves`). |
| 3 | **The omp session crashes before ready**: `Unknown tool in --tools: inspect_image` | tcc #165 (+ its comment of 13.10) | bug | ordinary | S | opus · medium | Has the traceback; the body names the cause and a fix (`omp_session._ENABLED_TOOLS`, the refusal regex). Right now omp does not start at all. |
| 4 | **The delay bank keeps one entry per title, not per series**: after a series switch, the old series' drivers read 0 and the next step loses the reading | F-100 O4 | bug | high | M | opus · high | `core/delay_bank.py:17-22` says per series (the Arbiter's rule of 2026-08-12). Start with a strict xfail. |

## Tier 2 — the screen says something false

| # | task | source | class | risk | size | model | note |
|---|---|---|---|---|---|---|---|
| 5 | **Model and reviewer picks tell the truth** — one group: TCC offers Opus 5.5 for a gone Sonnet 5, the user accepts, and the selector still says Sonnet 5, with no Sonnet 5.5 in the list (157); Sonnet shows no restart button (156); Codex Critic has a hard-coded list and both entries are refused, with the real error hidden (#182); an API pick on an agy-only machine asks for a key, and a region refusal is unreadable (hub #262) | 157, 156, tcc #182, hub #262 | bug | ordinary | M | opus · medium | One theme: the lists are hard-coded and the refusals are not said. The Critic's check at start works (157), so it is the model to follow. |
| 6 | **A method note on the strip reads as an error** («Something went wrong: note: … cannot be locked» over a write that landed) | F-100 (Fable's M3) | bug | ordinary | S | opus · medium | A warning path in `app_log` and the window's sink. |
| 7 | **The signature check is never shown**, and a «security checked» mark beside each version on the Updates tab | 159 + the Arbiter's proposal | feature | high | S | opus · high | Shows what `prepare_tcc_update` / `upkeep.py` already check. The method's half runs the skill's `upkeep.py`, so it may need a ticket to the skill. |
| 8 | **`ship.py` skips its local suite when `ci-green` holds**, plus #246's dry `VERSION … AT=` check | hub #277 ask 1, hub #246, F-100 | process | high | S | opus · high | v1.1.3's serial suite took 15 min, while the Mac is at risk beside the VM. #277 ask 2 (main's red run) is already in F-100. Read its «CHANGELOG correction». |
| 9 | **The flaky Windows test**: `test_picking_a_reviewer_puts_it_in_the_project_params_at_once`, red on `main`'s run and green on the PR's run of the same commit | F-100 | bug (test) | ordinary | S | opus · medium | A `UnicodeDecodeError` on `0x97` in the same log. |

## Tier 3 — the car desk asks (passat)

| # | task | source | class | risk | size | model | note |
|---|---|---|---|---|---|---|---|
| 10 | **Rounds on one base**: REW's `splOffsetdB` jumped 103.35 → 120.0 (beta 134 → 135) and shifted a round by 16.65 dB, and the round check said nothing | hub #268 | feature | high | M–L | opus · high | Joint: the math may belong to the skill (`verify.py`). It decides whether rounds can be compared at all. |
| 11 | **`under` and `level` set through TCC's `start_capture`**; a verdict for unplanned takes | hub #260 | feature | high | M | opus · high | Joint with the skill's `process.py`. Its «legs OFF» note is probably hub #259 (the letter series). |
| 12 | **A date beside each version** in «Порівняти з» (`v_007 · 05.10`) | hub #257 | feature | ordinary | S | sonnet · medium (trial) | Mechanical: `ledger_line.label()` reads `created`. A good Sonnet-trial task. |
| 13 | **«Описати зміни» in Compare**: the musical changes between two versions, and «Обговорити з ШІ» | hub #264 | feature | ordinary | L | opus · medium | The skill's static data does not cover delay, polarity or crossover. Needs a design pass and probably a skill ticket. |

## Tier 4 — polish and what earlier reviews left

| # | task | source | class | risk | size | model | note |
|---|---|---|---|---|---|---|---|
| 14 | **Plan panel**: a done step's checkbox is a solid orange square (#166); long step text becomes a «?» hint (#167) | tcc #166, #167 | bug + feature | ordinary | S | sonnet · medium (trial) | `theme.py:851-854`, `PlanPanel`. |
| 15 | **The import window**: its row too short at zoom 1.3–1.5 (151); the cell frame beside TAKE (152); a way to say no to the «≈» proposal (154); a «Refresh» button that marks the rows REW holds (155) | F-094 | bug + feature | ordinary | M | opus · medium | One group, one window. |
| 16 | **W-8's leftovers**: a typed confirmation failure («not the Arbiter's answer»); uvicorn's lines into `tcc.log`; a restart onto omp checks `.mcp.json` before the handoff; Cancel on a project switch re-reads into the old window; the tests named in F-098 | F-098 | bug | ordinary | M | opus · medium | The agent-contract part (`refresh_requested`, `view_shown`) is a ticket to the skill first. |
| 17 | **W-7's leftovers**: `check_sweeps` reuses `answer`; the as-is line names REW's title; a colour test that proves nothing; `.mini-select` repeats rules; drop the card patch's band half at the re-pin that carries hub #247 | F-094 | bug + docs | ordinary | S | sonnet · medium (trial) | Small, scattered. |
| 18 | **W-9's small leftovers**: on screen, a driver whose own entry cannot be parsed is banked from the view (M2); the cards' padded list shows two rows; «unasked extra» differs live vs history; the curve window after a gate pick has no set-aside line; the gate memo misses a store written, broken and set aside between two looks | F-100 | bug | ordinary | M | opus · medium | Several sit beside G10 / G3 and can ride with them. |
| 19 | **«Open terminal in this project…» becomes a submenu**: Terminal, Claude, Codex, agy, OMP | tcc #180 | feature | ordinary | S–M | opus · medium | `terminal_launcher.py`, `_open_terminal`. |

## Tier 5 — large features

| # | task | source | class | risk | size | model | note |
|---|---|---|---|---|---|---|---|
| 20 | **Codex as a primary in-app AI** through its SDK or app-server | tcc #181 | feature | high | L | opus · high | A feasibility study first (brainstorming → architects). It touches the session factory. |
| 21 | **The car package into the product**: «Save the car to a file…», and the copy picker takes it | F-096 | feature | high | L | opus · high | The Arbiter: after the audit, as the timed pilot on G13's seams. Read the 2026-09-18 branch first (656 commits behind). |

## Bookkeeping, not tasks

- **hub #242** (cut `beta-v1.1.0-rc1`): v1.1.0 shipped on 2026-10-03 from rc2, so the ticket is superseded. Close it with that evidence.
- **hub #277** asks 3–4 (answer the skill's next candidate with the re-pin PR; process weight from `Risk`): standing practice, not a task.
- **F-095** (N2 on every skill candidate) is standing. **F-101** is this session's to-do.

## Advice

- **Rank 1–3**: the Arbiter retests on v1.1.3 first, on the VM where 1.1.3 is now installed. It takes five minutes and tells whether W-9 already fixed them.
- **Whatever still fails**: take it into W-10 beside the audit, which needs the Arbiter's word over the 2026-10-06 order. Measurements lost in a live session cost more than the audit's order protects.
- **The rest**: waits for its turn after the audit, as decided.
