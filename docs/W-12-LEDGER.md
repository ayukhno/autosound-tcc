# W-12 ledger

Filled from the first run. Two halves: the review numbers hub #333 asks for, in the form of the skill's
`docs/W-12-LEDGER.md`, and what the wave teaches for the PMO cube.

## Review numbers

Per pass: findings, real, in part, false, found only by this seat; blocker / important / minor; each checked at its main
site. Sent to the hub by ticket at the wave's end.

| when | seat | what | findings | real | in part | false | only this seat | B / I / M |
|---|---|---|---|---|---|---|---|---|

## The Sonnet trial (per task)

| issue | model · effort | wall clock | tokens | tool calls | commit | defects found later |
|---|---|---|---|---|---|---|
| #233 | sonnet · medium | 77 s | 83K | 16 | `f6cd1b81` | |
| #252 | sonnet · medium | 22 s | 64K | 6 | `193af6dc` | |
| #250 | sonnet · medium | 81 s | 79K | 13 | `5d0009c0` | |
| #244 | sonnet · medium | 53 s | 77K | 12 | `3142d66a` | |

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
8. **From the skill's W-12, taken here:** acceptance on the exact head after the last code change; the reviewer's brief
   (a quote at `path:line`, every site of a class, «checked → clean», what could not be checked). Their result in this wave
   goes here when the wave has one.
