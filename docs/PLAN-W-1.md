# Plan · W-1 · v0.1.42 — what this wave builds, what it defers, and in which order

Written 2026-09-20 at the review step, after the Arbiter closed the collection (2026-09-19) and the
method opened `W-1 · v3.0.59` on its side. This is a PROPOSAL: the content of a wave is the
Arbiter's call, and nothing below starts before he says so.

The name was read, not agreed: the method's milestone is `W-1 · v3.0.59`, so ours is
`W-1 · v0.1.42` (`WAVES.md` §1; skill's `SKL-046`, hub `#188`).

## Start here — a clean session with no memory of the last one

Written for a session that begins with nothing but this repository (the Arbiter restarts fresh,
2026-09-20). Read this section first and in order; everything below it is the reasoning.

**1. Know your breed, then look at the queue.**

```bash
echo "HUB_ROLE=[$HUB_ROLE]"     # must say tcc; empty means you are the hub and this plan is not yours
bin/ticket queue                # in ../hub — the queue, the receipts, and THIS repo's issues
```

`#188` (skill → us) is already taken into work and is the other half of this wave. `#179`, `#181`,
`#182` are in work from the previous wave: the code of `#181`/`#182` is merged, and what is left of
`#181` is one check — `release-preflight.ci_verdict` on a REAL tag, which happens when `v0.1.42` is
cut. `#83` is deferred; do not count it.

**2. Know where the tree stands.**

- Branch `wave-0.1.42` is checked out and pushed, and it is AHEAD of `main` by about two dozen
  commits — not only documents. The code on it that `main` does not have: the confirmation bar's
  single scrolled question block and its attention tint (`ui/tcc/confirm_bar.py`, `ui/tcc/theme.py`),
  the quote-aware substitution check that stopped the never-ask gate firing on markdown backticks
  (`core/tuning_session.py`), and the AI-history tab (`core/session_export.py`,
  `ui/tcc/diagnostics_panel.py`, strings in four languages).
- **No pull request is open for any of it**, and no tag is cut. `CHANGELOG.md` carries the entries
  under `## [Unreleased]`.
- Continue on this branch. It is the wave's branch; do not open a second one.

**3. Do not rebuild what is already built.** Findings `15`, `16`, `24` and `27` are closed in the
branch above. `32` went to the method as hub `#187` and is W-2.

**4. Then work the packages in the order given under "Order, and why this one"**, starting with
finding `36` — not with the crash it causes.

**5. Before claiming anything is done**: targeted tests on the file you changed while hunting, the
full suite only when the change is final (and say so). `make test` is the hub's set, not ours; ours
is `uv run --extra dev --python 3.12 python -m pytest tests/... -q -p no:randomly`.

## Where the work comes from

Four sources, and nothing else was counted:

| source | what is in it |
|---|---|
| `docs/TEST-FINDINGS.md` | 21 open findings of 34. The Arbiter's testing, 2026-09-19 closed the collection |
| `docs/TODO.md` | 8 open items: `F-061`, `F-065`–`F-070` (and `F-026`, which is done and mislabelled) |
| the bus | `#188` (skill → us, this wave's half), `#179`/`#181`/`#182` in work, `#83` deferred (not counted) |
| `ayukhno/autosound-tcc` issues | `#43` — a round accepts a ledger version that does not exist (`#21` deferred, not counted) |

## The categories the work falls into

1. **The window lies or dies** — a wrong answer or a crash. Nothing else competes with this.
2. **The window gets in the way** — noise, missing affordances, a form that cannot be aimed.
3. **The method's change with a visible half here** — the five pieces of `SKL-046`. These are the
   reason `vendor/autosound-tuning-skill` moves at all, which is what makes this ONE wave over two
   products rather than two neighbouring ones.
4. **Words** — the settled vocabulary, and the header that speaks it.
5. **Machinery nobody sees** — CI economy, shard weights.
6. **New shapes** — the Layout mode, a native intake form. Whole features, not repairs.

## Proposed for W-1

### Package «neither lies nor dies» — the window's correctness (first, and nothing starts before it)

- **`35` the crash** — a curve worker destroyed while running; reproduction: in the curve window
  pick a set, then pick a group. Twice, on two sets.
- **`36` its source** — picking a set does not change the driver list, the read then fails with
  `KeyError` on the previous set's titles, and curves of one set are shown under another's name.
- **`33` the picker** — a capture SERIES and the ROUNDS of a config in one list, and an entry that
  disappears when a new round arrives. Same widget as `36`, and the vocabulary work below decides
  what the two kinds are CALLED.
- **`#43` integrity** — `start_capture` accepts a ledger version with no snapshot on disk (four
  rounds in a row), while the load form in the same state cannot be opened at all. One half lenient,
  the other strict.

### Package «out of the way» — the window's noise and missing affordances

- **`29`** the `UNUSABLE` banner: sixteen lines across the top, no way to dismiss it.
- **`28`** the REW import form: the New name column pre-filled (ours or the method's), draggable
  column widths, and a select-all / clear at the foot.
- **`31`** "In focus now": the protection button into the row with the name field, a narrower name
  field, the colour legend on one line with the wording in a tooltip, the status message above the
  row and in blue, and a **Готово** button in the header beside the REW mark, disabled until
  something is loaded. In `Terminal+GUI` it must post a bus signal rather than call the SDK — but
  that mode is W-2, so this wave gives it the signal path and no mode switch.
- **`30`** the same panel's honesty: protection shown on the rows that carry it, the cut-off RTA
  explanation removed, and the double suffix `(sw) (rta)` fixed where the additional rows are built.
- **`34`** capture order: drag a selection rather than a row, save the order deliberately, and copy
  it between RTA and SW.

### Package «the method's five» — changes whose visible half is ours (`SKL-046`)

Needs the method's `w1` branch first, then its published tag.

- **`covers` on a plan step** (S-031) — render the dotted paths a step closes instead of a count.
- **Language** (S-045) — the method stores the REPLY language; our report stays authoritative for
  the INTERFACE language; what the person TYPES switches neither.
- **Who wrote a protective record** (`#48`, S-036) — `user | front_end | default`, so ten channels
  marked `OFF` in one second is not read as an answer.
- **A closed round becomes correctable** (`#48`) — the path the window needs when a title was
  mistyped.
- **Imported measurements carry their origin** (S-048) — the project they came from and the `_N`
  they had there.

### Package «words» — the vocabulary, and the header that speaks it

- **The vocabulary**, settled by the Arbiter 2026-09-20: **варіант** (what the desk proposes in
  Phase 1) → **конфігурація = версія `v_NNN`** (what is in the processor now) → **пресет** (the slot
  a version is fixed in). A **серія `_N`** is measurements, a **фаза** is a step of the plan. This
  is a pass over the interface strings in all four languages, and it decides the wording of `33`.
- **`F-070`** — the header carries the ledger version and its state (`v_008` with a yellow/green
  dot) instead of the processor's name, which moves into the tooltip; and the DSP preset NUMBER
  beside the preset name when the project has one. Two things to establish before building: what
  the dot reads (per-channel `status`, or the attest record for the version), and whether a preset
  number exists in `project.json` at all.

## Proposed for W-2 — and why not now

| item | why it waits |
|---|---|
| `F-069` Layout `GUI only` / `Terminal+GUI` | A whole new shape, and it has an unresolved decision in it: the confirmation bar lives inside the panel that mode hides, while TCC's own tools keep raising confirmations in every mode. Building it inside a wave that is already four packages is how both get done badly. |
| `F-068` the drivers' Fs checkbox | Waits for a method flag that does not exist (hub `#185`, with skill). Not in the method's W-1 either. |
| `#187` the reviewer channel, and findings `17`, `20`, `21`, `23`, `25`, `32` | The method put `#187` in W-2 explicitly. Every one of these is the same channel; splitting them across waves would mean testing it twice. |
| the native intake form | The method deferred it (S-033, S-037) and eight of the Arbiter's points against its first page are open. Building a front end against it now is building against something that will move. |
| the registry rebuild (versions numbered per project) | The method's migration is W-2. Until then we keep reading `state/<preset>/v_NNN.json` and name a version with its slot — `SQ v_007` — so two `v_001`s are never ambiguous. |
| findings `12`, `13`, `14` — the Windows update path | They need the VM and a full update cycle to verify, which is its own testing session rather than a package inside this one. |
| `F-065`, `F-066` — suite cost, per-platform shard weights | Machinery. `F-066` is worth about a minute of CI and costs a table re-recorded on three platforms. |
| `18`, `19`, `22` | Small and real, but they are not what stops a round; they ride in W-2 unless the Arbiter pulls one forward. |

## Order, and why this one

1. **Correctness**, and its first item is `36`, not `35`: the crash grows out of the stale list, and a crash
   fixed without its cause is a crash that comes back by another path. Then `35` with its own
   measurement of the detach bookkeeping, then `33`, then `#43`.
2. **The vocabulary pass** next, because «out of the way» and «the method's five» both write
   interface strings, and renaming after them means touching the same lines twice in four languages.
3. **The method's five** as soon as its `w1` branch is installable — test against the branch
   (`install.sh --skill-ref w1`), not against a release; `fetch-binary` still takes the last tag
   (`--tag v3.0.58`), which is not a bug.
4. **Out of the way**, which is the widest package but has no order inside it.
5. **F-070** last of the wave's own work: it reads state the earlier packages may move.

## Exit criteria

- The method is tagged FIRST (`v3.0.59`); we pin that PUBLISHED tag, are tested against it, then cut
  `v0.1.42` (`WAVES.md` §1 step 4; the mechanical half is `TCC-021`, already merged).
- Green sharded run on the pull request, green full serial run on the `main` push.
- `make ship REAL=1` for `v0.1.42`, with `release-preflight.ci_verdict` checked on the real tag —
  the fourth check of `TCC-020`, which is the last thing still open from the previous wave.
- The installer path walked by hand on macOS; the Windows VM is a separate session (see W-2).

## Models, and what each is for

- **The main session — the one that talks to the Arbiter — runs Opus.** Every item in package A is judgment — a race in thread
  teardown, and two halves of a capture flow that disagree. `F-070` and the vocabulary are design
  decisions in four languages. This is not work a cheaper model finishes correctly faster.
- **Sonnet, for mechanical sweeps, and only with the Arbiter's word**: reading a source tree to
  list every place a term appears, checking the four language blocks have the same keys, running a
  suite and reporting failures. Reading and cross-checking, never deciding.
- **Fable: the main session only** — the conversation itself, never a subagent it spawns.
- At most four subagents at once, and only against a written plan with its cost named first.

## Starting the next session

```bash
hub/bin/role tcc --resume 7f1f34ff-a032-471c-a38e-6d519c231fa5        # this conversation, in its breed
```

First three things in that session, in order:

1. `bin/ticket queue` — the queue, the receipts, and this repo's own issues.
2. Read this file and the milestone `W-1 · v0.1.42` (five lines, the Arbiter's scope).
3. Branch from `main` for the wave's work; `wave-0.1.42` already exists and is merged, so the next
   branch continues it rather than starting a second one.
