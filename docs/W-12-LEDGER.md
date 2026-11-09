# W-12 ledger

Filled from the first run. Two halves: the review numbers hub #333 asks for, in the form of the skill's
`docs/W-12-LEDGER.md`, and what the wave teaches for the PMO cube.

## Review numbers

Per pass: findings, real, in part, false, found only by this seat; blocker / important / minor; each checked at its main
site. Sent to the hub by ticket at the wave's end.

| when | seat | what | findings | real | in part | false | only this seat | B / I / M |
|---|---|---|---|---|---|---|---|---|
| 2026-11-09 | Opus seat (`feature-dev:code-reviewer`, opus · high), 9 min, 178K | hygiene + small fixes (#233, #252, #250, #244, #236) | 2 | 2 | 0 | 0 | 2 | 0 / 1 / 1 |

| 2026-11-09 | silent-failure seat (opus · high), 7 min, 185K | the window group (#245, #243, #237) | 7 | 6 (each by a red test) | 0 | 0 | 7 | 0 / 2 / 5 |
| 2026-11-09 | test seat (opus · high), 10 min, 163K | the window group | 16 | 12 taken and red on the seat's mutation; 1 Minor taken; 3 Minor left | 0 | 0 | 16 | 0 / 12 / 4 |

The silent-failure seat's seventh (a setting written before the restyle) was left: no raiser exists today. The window group's fix
round: opus · medium, three commits (`385b30bb`, `247d9193`, `41578365`).

The first group's Important was checked by an offscreen `grab()` with the real sheet and a red control cell: no item background paints in a
`ptable`. The check found one more, which the seat had not: `QColor(t.mix(…))` is invalid, since `mix` returns `rgb(r, g, b)`,
so the test compared two invalid colours and passed.

## The Sonnet trial (per task)

| issue | model · effort | wall clock | tokens | tool calls | commit | defects found later |
|---|---|---|---|---|---|---|
| #233 | sonnet · medium | 77 s | 83K | 16 | `f6cd1b81` | |
| #252 | sonnet · medium | 22 s | 64K | 6 | `193af6dc` | |
| #250 | sonnet · medium | 81 s | 79K | 13 | `5d0009c0` | |
| #244 | sonnet · medium | 53 s | 77K | 12 | `3142d66a` | |
| #236 | sonnet · medium | 100 s | 86K | 15 | `ad903a3f` | |
| #245 (beside the trial) | opus · medium | 217 s | 109K | 18 | `1b6a59a3` | |
| #243 (beside the trial) | opus · medium | 553 s | 142K | 27 | `61ac5c5c` | |
| #237 (beside the trial) | opus · medium | 873 s | 230K | 49 | `4cb4e1fd` | |
| the group's fix round | opus · medium | 457 s | 184K | 29 | `d889f300` `a0cef017` `3a74dac7` | the Sonnet tasks' defects the seat found: #250's background (Important), #252's flash (Minor) |

## For the PMO cube (the Arbiter's word 2026-11-09)

The practices of effective work and of steering a session, collected as they happen. At the wave's end they become issues
in `ayukhno/hub-kit`, each with its evidence. No write to hub-kit before that.

1. **Check the limits from the data, before each group.** context-bar-mod writes the 5-hour and 7-day figures to
   `~/dev/_pmo/usage/limits/claude/<UTC day>.jsonl` at most every 5 minutes, so a session can read them and name them before
   a group starts. Evidence: the session first said it could not see them and asked for `/usage`; the Arbiter pointed at the
   mod; the file answered the same 26%. A session has to be told this exists: nothing at its start says so.
2. **Walk open decisions one at a time, each with advice.** Eight decisions in eight stops, one question each, the advised
   option first. Two answers changed the design and one came back as free text no option held («Купити каву та Відгук»,
   the rule for the green mark per DSP).
3. **Read the code behind an option before offering it.** On #254 the option «a button installs a newer version» was offered
   from the plan's text. Only after he chose it did a grep show that TCC installs only a file whose sha256 is pinned in its
   source, so a newer version would rest on PyPI alone. Told, he reversed it, and that reversed #253's PATH write too. Ask
   after the check, or the person decides on half the facts and pays one more round.
4. **Say a consequence the moment it is found, even after the answer.** The same case: the choice was not recorded until the
   new fact had been put to him.
5. **Give an implementer the competing accounts, and ask it to establish which is true.** On #233 the issue said a read still
   running, the plan's map said queued reloads. The brief named both as things to check, and the code showed a third: the
   project watcher's 400 ms debounce. A brief with one diagnosis would have shipped a fix that did not hold.
6. **Re-read a plan's steps against what changed since.** The quarantine planned for #257 had become pure churn once the
   candidate carried the fix and the PR's CI runs after the pin; dropped.
7. **Check a subagent's report at the commit.** `git show --stat` and the diff before the ledger says done: the files touched
   are the claim that can be checked in seconds.
8. **A look is proved by pixels, with a control.** A UI test that reads an item's data says what was asked for, not what is
   drawn: #250's test passed on a background that never paints and a colour that never parsed. A `grab()` with the real
   stylesheet and a planted red cell settled it in one run. The first grab misled too (the current cell's tint), which the
   control exposed.
9. **Show a design consequence to the person, even mid-review.** The seat named a place the decision did not cover; asked
   once, he replaced the rule with a better one (blue stays, an orange frame for INV) before a fix round was spent on the old.
10. **A crash in a test reaches the person's screen.** During the fix round a run built a `QWidget` before the `QApplication`;
    Qt aborted and macOS put a «Python quit» dialog in front of him (10:23:07, one second after a commit; the `.ips` holds the
    time and the stack, not the command). Every committed test was clean; a draft did it. The brief now says it, drafts
    included. A session asked «is it yours?» answers from the `.ips`, not from memory.
11. **A question of look is settled on the real window, in rounds of pictures.** #237 went through five rounds of offscreen
    grabs of the actual window (a throwaway test, no window on the screen), in his language. Each round cost seconds and
    changed the design: a text list of looks had looked fine to everybody, and his final pick was a crop of one picture beside
    a crop of another.
12. **A test seat that proves each gap by a mutation.** The seat broke the product in memory and ran only the file concerned:
    «green» then means a real regression would pass. 12 Important, among them a signal nobody connected, a saved value equal
    to the default, and a look compared with itself; one live defect came out of it. Worth writing into the seat's brief.
13. **From the skill's W-12, taken here:** acceptance on the exact head after the last code change; the reviewer's brief
   (a quote at `path:line`, every site of a class, «checked → clean», what could not be checked). Their result in this wave
   goes here when the wave has one.
