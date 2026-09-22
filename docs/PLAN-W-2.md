# Plan · W-2 · v0.1.43 — what this wave builds, what it leaves, and in which order

Written 2026-09-22 at the review step. This is a PROPOSAL: the content of a wave is the Arbiter's
call (`WAVES.md` §1 step 2), and nothing below starts before he says so. His instruction for this
review: include as much as possible of what is not deferred; whatever stays out gets a reason and
is deferred.

The name was read, not agreed: no `W-…` milestone was open in either repo, the highest closed one
is `W-1` on both, so this is `W-2`. Milestone `W-2 · v0.1.43` is open in `ayukhno/autosound-tcc`
(#2); the skill reads its number from it.

## Where the work comes from

Everything open in four places was read, 2026-09-22:

| source | open | of which proposed |
|---|---|---|
| `docs/TEST-FINDINGS.md` | 20 of 40 findings | 19 — finding `19` is done by `F-042` |
| `docs/TODO.md` | 19 items with a non-closed status | 12 — `F-068` is left out, `F-023`/`F-055`/`F-057` are deferred, `F-026`/`F-037`/`F-058` are done or dropped under a stale status |
| the bus, `to:tcc` | `#193`, `#194`, `#83` | `#193`, `#194` (`#83` deferred — not touched, the Arbiter's word) |
| `ayukhno/autosound-tcc` issues | `#45`, `#21` | `#45` (`#21` deferred) |

Plus what the method put off to W-2 in `SKL-046` and what its branch `wave-2026-09-20` now carries.

## Proposed for W-2 — eight packages

### 1 · Words — first, because every other package writes strings

- **The vocabulary pass**, settled 2026-09-20: **варіант** (a Phase-1 proposal) → **конфігурація =
  версія `v_NNN`** (what is in the processor) → **пресет** (the slot a version is fixed in); a
  **серія `_N`** is measurements, a **фаза** is a step of the plan. All four languages.
- **`F-070`** — the header shows the ledger version and its state instead of the processor's name,
  and the preset number when the project has one.

Planned for W-1, not built: the wave was cut after the crashes (35–39).

### 2 · The capture panel — the round is run from here

Planned for W-1, not built.

- **`33`** the picker mixes a series with the rounds of a config, and one entry vanishes when a new
  round arrives. Its wording comes from package 1.
- **`29`** the `UNUSABLE` banner: sixteen lines, half the window, no way to dismiss.
- **`28`** the REW import form: the New name pre-filled (the method's `renames` from skill `#47`
  is exactly that column), draggable widths, select-all / clear at the foot. Closes `F-056`
  (import from REW, waiting for its test since v0.1.40).
- **`30`** protection shown on the rows that carry it, the cut RTA explanation gone, the double
  `(sw) (rta)` suffix fixed where the rows are built.
- **`31`** "In focus now" tidied (protection into the name row, legend on one line, status above
  in blue) and a **Готово** button that hands the capture to the AI.
- **`34`** capture order: drag a selection, save the order on purpose, copy it RTA ↔ SW.

### 3 · The reviewer channel — our half of `#187`

The method put `#187` in W-2. Every item is the same channel, so they are tested once.

- **`32`** `child_env` hands the whole environment to the child: a `GEMINI_API_KEY` in the shell
  silently moves the reviewer to the API, where the configured model is a 404.
- **`#45`** a TCC-launched session has no shell the reviewer CLI can run from — TCC runs the
  reviewer itself outside the agent session, or offers a clean shell; and the configured model
  reaches a direct call.
- **`17`, `21`** the session goes around TCC to the reviewer, and the model is not inherited
  (same fix as `#45` point 3).
- **`20`** the closed picker and the footer say nothing when the reviewer is refused by region.
- **`23`, `25`** the advice for agy's `read_file` refusal follows whatever the method settles.

Blocked in part: the method's half is `#187` and skill `#54`.

### 4 · The skill's W-2 halves — after its tag

Skill branch `wave-2026-09-20` carries them; not tagged yet.

- **`#194` SKL-049** an «Інтейк» button that starts the skill's served form, one process per
  project, stopped on close; TCC reloads from disk after Save. Replaces `F-055`.
- **`#193` SKL-048** the seat chosen when a project is copied.
- **S-044** the «start the phase in a clean session» offer — the method's handoff that refuses is
  on the branch (`5851b3a`).

### 5 · The Windows update path — one session on the VM

- **`12`** the update window says "Done" after a failed fetch.
- **`13` / `F-043`** a second, empty console during the update.
- **`14`** a terminal blinks behind "Reading models" on the first start after an update.
- **`F-039`, `F-044`** the first start from the desktop shortcut, and a pin that does not merge
  with the live window — both waiting for the Arbiter's test since v0.1.40.

### 6 · Small

- **`1`** the "Agent commands" dialog: four sentences, the question in the middle — reworded with
  the Advisor, as the Arbiter asked.
- **`5`** long pauses with no sign of life: show that work goes on (no measurement needed), then
  measure whether TCC itself adds time.
- **`18`** the gap between the AI dialog and the right column.
- **`22`** protection asked for virtual channels — fixed with no round open (`4c11825`); check with
  a round open.
- **`F-061`** the clipboard's column names exist twice; read the method's `FORM_LABELS`.

### 7 · Layout `GUI only` / `Terminal+GUI` (`F-069`)

A whole new shape, deferred from W-1. One decision comes before any code: the confirmation bar
lives in the panel this mode hides, and TCC's own tools raise confirmations in every mode.

### 8 · Machinery

- **`F-071`** a test crashes its worker under `-n 4`.
- **`F-065`** the suite costs three times more in one process than the same files apart.
- **`F-066`** shard weights are macOS seconds; Windows is uneven.
- **`F-073`** the six commits after `v0.1.42` go into this CHANGELOG entry.
- **`F-074`** check the project's GitHub backup after the broken-git spell.

## Not included, and why

| item | why |
|---|---|
| `F-068` the drivers' Fs checkbox | The method's flag does not exist (hub `#185`, with skill) and is not on its wave branch. |
| per-project version numbering | The method has not built its migration, and nothing carried it — filed as hub `#195` (TCC-025, 2026-09-22). It joins the wave when the skill takes it; until then we keep `state/<preset>/v_NNN.json` and name a version with its slot (`SQ v_007`). |
| `F-055` a separate session towards an intake form | Superseded by `#194`: one form for every front end, the skill's page (the Arbiter, 2026-09-22). |
| hub `#83`, `#21`, `F-023`, `F-057` | Already deferred; not touched. |
| finding `19` | Done by `F-042` (2026-09-17): the report has a path without GitHub. |

## Order

1. **Words** (1) — every package after it writes strings.
2. **The capture panel** (2), starting with `33`.
3. **The reviewer channel** (3) — our half; the method's half is its own.
4. **Small** (6) and **machinery** (8) — no order inside.
5. **Layout** (7) — after its decision.
6. **The skill's halves** (4) — built against the branch while it is untagged
   (`install.sh --skill-ref wave-2026-09-20`), pinned to its published tag before ours.
7. **The Windows update path** (5) — the VM session, together with walking the installer.

## Exit criteria

`WAVES.md` §3.1: green PR run, full serial run on `main`, `make ship REAL=1` for `v0.1.43` pinned to
the skill's PUBLISHED tag (skill first), the installer walked by hand on macOS and the update path
on the Windows VM.

## Decisions the review owes

- Whether `F-069` (Layout) is in this wave or the next.
- What the milestone carries (hub `#191`, open): only `#45` is an issue today; the rest lives here
  and in the milestone's five lines.
