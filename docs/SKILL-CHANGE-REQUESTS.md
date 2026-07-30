# Skill change requests

Asks for the `autosound-tuning-skill` submodule (`vendor/autosound-tuning-skill/`) that TCC depends on
but does not own. TCC's own code never edits the submodule directly — these are tracked here and
processed in a batched skill-side session.

Status values: `proposed` (not yet actioned) · `accepted` (skill maintainers/self have agreed to do it)
· `done` (landed in the submodule and the pin bumped).

---

## Status reconciliation — 2026-07-31

**This table is authoritative.** The per-entry `**Status**:` lines below were written when each ask
was raised and were never updated as work landed; where they disagree with this table, the table
wins. Verified by reading the artifacts on the skill's `feat/tcc-sync-p0` (worktree
`~/dev/Claude/autosound-skill-bridge`), not by trusting commit messages.

| SCR | Verified status | Evidence |
| :-- | :-- | :-- |
| 001 | **done, but written elsewhere than asked** — see the mismatch note below | `rew_tool/project-schema.md` — drivers carry `fs_hz` as a `fact()`; **not** on the ledger row |
| 002 | done | `state/schema.md:37-43` — `slot`, `descr`, `role`, `order`, `tag`/`tag_value` per channel |
| 003 | done | `state/schema.md:45` — `"hidden": false` alongside `mute`/`off` |
| 004 | done | `state/process-schema.md` + `state/process.py` — `process/journal.jsonl` + `process/process-state.json`. Already on `main` |
| 005 | done | `state/schema.md:27` `"schema_version": 2`; one-shot `state/migrate_v2.py` |
| 006 | done | `state/schema.md:52` — `"eq": [{"type","f","gain_db","q","bypass"}]`, plus `eq_ptr`, `status` |
| 007 | not verified | — |
| 008 | not verified | — |
| 009 | not started | no `target-curves/registry.json` |
| 010 | not verified | — |
| 011 | done | `rew_tool/project.py` + `project-schema.md` — machine facts split out of `autosound_context.md` |
| 012 | not started | `rew_tool` still runs as scripts, not an importable package |
| 013 | not started | `verify_measurements` still CLI-only |
| 014 | done | `project-schema.md` §Provenance — `fact(value, source, at)`, `_open_questions`, `config_change` events with `impact` |
| 015 | done | `project-schema.md` header names SCR-015 among its targets |
| 016 | done | `project.json` carries processor + channel summary |
| 017 | answered | `project-schema.md` §"Hardware controls vs. the ledger" — `RearRC` lives in `hardware.controls`, not per preset |
| 018 | open question | unchanged |
| 019 | open question | unchanged |
| 020 | **done** | landed on skill `main` 2026-07-31 |
| 021–023 | proposed | installer work, not started |

### Mismatch worth acting on first (SCR-001)

TCC's `dsp_tree.py` `ChannelRow._tooltip_html` reads `raw.get("driver")` / `raw.get("fs")` **off the
per-channel ledger row**. The skill now writes that information into **`project.json`** instead —
driver identity and `fs_hz` as provenance-carrying `fact()` values under the project's drivers list.

Both sides did what they were asked; they were asked for different shapes. Nothing populates the
tooltip, and no error is raised — the keys are simply absent, so the UI renders empty. This is a
concrete instance of the general symptom "the terminal session worked but TCC shows nothing".

Decide the direction before writing more bridge code:

- **TCC reads `project.json`** for driver/Fs (project-level facts are project-level — matches
  SCR-011's own framing), or
- **the ledger writer denormalizes** driver/Fs onto the channel row for consumers.

The first is more consistent with the schema split that already landed; the second is cheaper for
the UI. Either is fine — having neither is what costs.

---

## SCR-001 — driver make/model + Fs per output channel

**Status**: proposed
**Target**: skill intake flow (`skills/autosound-tuning/references/core/project-intake.md` §1.5,
`phase_-1_intake.md`)
**TCC dependency**: `src/autosound_tcc/ui/tcc/dsp_tree.py`, `ChannelRow._tooltip_html` (~line 180-186),
already reads `raw.get("driver")` / `raw.get("fs")` off the per-channel ledger dict to render the hover
tooltip (speaker make/model + resonant frequency). Both keys are dormant — absent from every ledger
today (`data/private/state/{FULL,SQ}/v_001.json`).

**Detail**: the skill already captures driver model + Fs during intake, but writes it into
`autosound_context.md` (the tuning project's own profile file), not into the TCC DSP-state ledger.
Need a bridge from that intake step into the ledger's per-channel `driver` (string) and `fs`
(numeric, Hz) keys so the already-built tooltip populates.

## SCR-002 — ledger writer must emit slot/order/descr/tag/role

**Status**: proposed
**Target**: the vendored skill's ledger-writing code (state writer, wherever `v_NNN.json` files are
produced)
**TCC dependency**: `state/dsp_state.py`'s `GroupRow` (slot/order/descr/tag) and the tree's `role`
passthrough all assume these fields exist per channel — currently true only because the ledgers in
this repo were hand-edited during the M7 pass, not because the skill's own writer emits them yet.

**Detail**: carried over from M7 session notes (previously memory-only, "submodule task A6" — not
done). Any ledger the skill writes going forward needs to include `slot`, `order`, `descr`, `tag`,
and `role` per channel to match what TCC now renders.

## SCR-003 — explicit `hidden`/`unused` flag on unused virtual channels

**Status**: proposed
**Target**: skill intake flow, same area as SCR-001 (wherever the skill decides a virtual-channel
slot has no physical driver assigned)
**TCC dependency**: `state/dsp_state.py`'s `GroupRow.hidden` property (new, added alongside this doc)
reads `raw.get("hidden")` off the ledger row; `ui/tcc/dsp_tree.py`'s `TreeGroupSection` row loop skips
rows where it's true.

**Detail**: today every key present in a ledger's `virtual_channels` dict renders unconditionally, so
an unused virtual slot (e.g. "F"/VRF with no assigned driver) still shows in the tree. No existing
ledger field reliably distinguishes "genuinely unused slot" from "used slot, just not tuned yet" or
"muted for this preset" (checked against real `FULL`/`SQ` data — the obvious heuristics don't hold).
The skill has this information at intake time (it knows whether a physical driver was assigned to a
slot) and should write an explicit `"hidden": true` (or `"unused": true`) boolean on that row so TCC
can filter reliably. Not retroactive: existing ledgers won't hide anything until re-captured with this
change.

---

SCR-004…SCR-014 come from the TCC↔skill integration audit + the storage/process design session
(both 2026-07-27). Framing principles across all of them: **the skill owns every schema and writes
all data; TCC is a schema consumer and the process front-end**, and **store facts and decisions,
derive the views; history is append-only, never rewritten** (three storage classes — mutable config
/ immutable ledger / append-only journal — see TCC-TZ.md §3). Every machine format is JSON with a
`schema_version`; prose files are either generated or purely human. Priority tiers: P1 =
SCR-004..006 (without these TCC's process UI stays mock), P2 = SCR-007..011 + SCR-014
(source-of-truth consolidation + config lifecycle), P3 = SCR-012..013 (engineering base).

## SCR-004 — machine-readable process state: `process-state.json` + `journal.jsonl`

**Status**: proposed · **Priority**: P1 — the single biggest gap
**Target**: new module alongside the ledger (`rew_tool/state/`, same design pattern as
`PresetHistory`); written by the skill after every transition
**TCC dependency**: `ui/tcc/plan_panel.py`, `ui/tcc/measurement_panel.py`, footer critic status,
header target line — all currently render `ui/tcc/mock_data.py` (`PLAN`/`MEAS`/`DIALOG`) because the
skill emits process state only as prose (`tuning-changelog` ▶️ CONTINUE block, `audit-trail.md`).
This is `docs/TCC-TZ.md §4` made concrete; TCC consumes both files via a file watcher.

**Detail**: two artifacts under `process/` in the project folder. Governing pattern is the same as
the ledger: **history is append-only; the current view is derived and rewritable.**

`process/process-state.json` — the current slice, rewritten after every transition:
- active phase + per-phase status (`done | cur | todo`). Phases themselves (−1…5) are the skill's
  fixed method skeleton — never edited per project, only status and re-entry;
- current plan steps: `id`, `name`, `status` (`todo | in_progress | done | skipped | blocked`),
  `attempt` (>1 = redone), `skip` (superseded, kept visible), `source` (`skill` = instantiated
  from the phase template on phase entry vs `project` = situational insert) — TCC's
  `PlanPhase`/`PlanStep` dataclasses in `mock_data.py` are the ready-made field spec;
- current measurement task: **not hand-written — derived** by function (phase × glossary × ledger
  `vN`) from the capture-plan table (`naming-and-structure.md §3`, code via SCR-008); only
  overrides/deviations are stored;
- last reviewer/critic call: vendor, model, timestamp, phase/step it was called on;
- active target curve per preset (pointer into SCR-009's registry).

`process/journal.jsonl` — append-only event log, one JSON object per line; the single source of
process history. Minimum event types: `phase_entered`, `step_added`, `attempt_started`,
`step_skipped`, `step_done`, `critic_called`, `config_change` (shape in SCR-014). Rules:
- plan steps are never deleted — superseded → `step_skipped` (stays visible in the plan), redo →
  `attempt_started`;
- `step_done` REQUIRES evidence links (REW measurement names, ledger `vN`, audit-trail entry) — no
  evidence, no done. This materializes план-факт and makes resume/drift-watch cheap: on every
  resume the skill reconciles the plan against disk (step done but measurement missing → flag);
- v1 writer is the skill (Generator) only; the user corrects the plan through the dialog and TCC
  renders. Direct UI plan edits come later and also land as journal events, never raw JSON edits;
- `tuning-changelog` and `audit-trail.md` become generated views over the journal (same move as
  SCR-007 makes for `dsp-state-current`), not hand-written prose.

## SCR-005 — formalize ledger schema v2 + `schema_version`

**Status**: proposed · **Priority**: P1
**Target**: `rew_tool/state/schema.md` + `state.py` `validate()` + the ledger writer
**TCC dependency**: `state/dsp_state.py` reads `slot`, `order`, `descr`, `tag`, `hidden`, `features`,
`target`, `slot_label`, `save`, and the tree passes through `role` — all of which exist only because
this repo's `FULL`/`SQ` ledgers were hand-edited during M7. `validate()` checks only `channels`;
everything else is unvalidated passthrough, so the two sides can silently diverge.

**Detail**: legalize the TCC-consumed fields in `schema.md`, teach `validate()` about them, and make
the writer emit them (this absorbs/supersedes SCR-001/002/003 field-wise). Add a top-level
`schema_version` to every snapshot — no format anywhere is versioned today, so evolution is blind.
Also reconcile the naming split: skill schema says `helix_ch`, TCC ledgers say `slot` — pick one
(recommend the DSP-agnostic `slot`) and migrate.

## SCR-006 — structured EQ bands in the snapshot

**Status**: proposed · **Priority**: P1
**Target**: ledger writer + `schema.md` (channel `eq` field)
**TCC dependency**: `state/dsp_state.py::EqBand.from_string` regex-parses the informal string
micro-format (`"PK 1000 -9 Q2"`); the planned EQ panel (30 bands, per-band bypass, TCC-Concept §7)
needs real per-band values, not a display string. The skill's own canon is the opposite extreme —
`eq_ptr` pointing at an export file, no values in the snapshot at all.

**Detail**: store bands structured: `[{"type": "PK", "f": 1000, "gain_db": -9, "q": 2,
"bypass": false}]`. Keep `eq_ptr` alongside for traceability to the exported `.req`. String forms
(`"PK 1000 -9 Q2"`) demote to display-only, generated. TCC drops its string parser once landed.

## SCR-007 — `dsp-state-current` is always generated, never hand-written

**Status**: proposed · **Priority**: P2
**Target**: `SKILL.md` guardrails + `naming-and-structure.md` + phase docs
**TCC dependency**: indirect but structural — TCC treats the JSON ledger as the single source of
truth; any workflow where `dsp-state-current` (markdown) is maintained by hand can fork from the
ledger and TCC would render stale/contradicting state.

**Detail**: today SKILL.md says "re-read `dsp-state-current` before proposing" while `schema.md` says
`render` is generated-only — the multi-slot path already generates it (`registry render`), the
single-slot path is ambiguous. Make it uniform: `dsp-state-current` = `render` output of the ledger
HEAD, full stop. Edit the JSON (via `apply.propose`), re-render the markdown.

## SCR-008 — machine-readable channel glossary + naming-grammar functions

**Status**: proposed · **Priority**: P2
**Target**: intake flow (`project-intake.md §5`) + a small `rew_tool` naming module
**TCC dependency**: the measurement panel needs to compute an expected capture series (channels,
pairs `Ws/Ms/TWs`, combos `ALL/ALL+C`, joints `SW+Ws`, types `sw`/`rta`) and validate existing REW
titles against it. Today the glossary canon is prose (`autosound_context.md §5`) and the grammar
`<ch>_<N> (sw|rta)` is prose (`naming-and-structure.md §3`); TCC's `MEAS` mock hardcodes them.

**Detail**: intake writes the agreed glossary as JSON (inside `project.json` per SCR-011, or a
standalone `glossary.json`): channel codes, pairs, combos, joints. The naming grammar becomes code in
`rew_tool` — `generate_name(ch, n, kind)`, `parse_name(title)`, `validate_series(...)` — one
implementation both the skill and TCC call, instead of two readings of the same prose.

## SCR-009 — target-curves registry (active curve + curve↔preset) as JSON

**Status**: proposed · **Priority**: P2
**Target**: `naming-and-structure.md §6` convention + project scaffolding (`project-intake.md §5`)
**TCC dependency**: the header's `TARGET curve: <name>` per preset (TCC-Concept §4) and SCR-004's
"active target curve per preset" field. Today the ACTIVE curve + curve↔preset mapping live in a
human-maintained `rew_analitic/target-curves/README.md`.

**Detail**: add `target-curves/registry.json` (`{"active": ..., "curves": {"<name>": {"presets":
[...], "path": ...}}}`), same pattern as the slot `registry.json`. README becomes generated from it.
The ledger's per-snapshot `target` string stays as the historical record; the registry is the live
pointer.

## SCR-010 — one canonical DSP capability profile; skill owns the field vocabulary

**Status**: proposed · **Priority**: P2
**Target**: `rew_tool/dsp_profile.py` + `knowledge/dsp/` templates
**TCC dependency**: TCC renders entirely from `dsp_profile.json` (`state/dsp_state.py` generic
groups), and its onboarding interviewer (`dsp_profile_interview.py`) carries its own copy of the
field-name vocabulary (`FIELD_VOCABULARY`) in a system prompt — the schema's renderer vocabulary
lives in the consumer, not the owner.

**Detail**: three moves. (1) Declare the JSON profile the single canon; `knowledge/dsp/<slug>.md`
becomes generated from it (or a thin prose wrapper referencing it) — today the same capabilities are
captured twice with zero sync. (2) Move the field vocabulary (`hp`, `lp`, `gain_db`, `ta_ms`,
`polarity`, `phase_deg`, `mute`, `eq_bypass`, `eq`) into `dsp_profile.py` as exported schema, so TCC
imports rather than duplicates it. (3) Extend the profile schema with per-vendor EQ display
conventions — band column order differs (Helix = Freq/Gain/Q, Musway = Freq/Q/Gain) and must be
captured at onboarding, not hardcoded.

## SCR-011 — split `autosound_context.md`: machine facts → `project.json`

**Status**: proposed · **Priority**: P2
**Target**: intake flow (`project-intake.md §1, §5`) + project scaffolding
**TCC dependency**: TCC-TZ §3's target layout (`project.json` + `presets/<preset>/{target,state}`)
needs a machine entry point; today equipment/routing/paths/driver-per-channel facts exist only as
markdown. SCR-001 (driver make/model + Fs per channel) is one instance of this class.

**Detail**: intake writes objective machine facts into `project.json`: car, source(s), DSP
vendor+model (→ links the capability profile), amps, per-channel driver assignments (make/model/Fs —
absorbs SCR-001), mic rig, project paths, preset list. `autosound_context.md` stays for the
human/Critic as prose — generated from `project.json` where it overlaps, free-form where it doesn't
(anomaly log, experience notes). Also unify the storage env var story: skill (`AUTOSOUND_STATE_ROOT`)
vs TCC (`AUTOSOUND_TCC_STATE_ROOT`) should converge on one convention rooted at the project folder.

## SCR-012 — package `rew_tool` as an importable library (`autosound-core`)

**Status**: proposed · **Priority**: P3
**Target**: repo structure — `rew_tool/` flat script dir → a proper package with semver
**TCC dependency**: `core/vendor_loader.py` exists solely because `rew_tool` is a flat, `__init__`-less
directory whose module names (`state`, `analysis`) would collide on `sys.path`; TCC loads three files
by synthetic path. Every new shared schema (SCR-004/005/008/010) makes this hack load-bearing.

**Detail**: turn the data layer (state/ledger, apply gate, registry, dsp_profile, rew_api, naming
functions, schemas) into an installable package. TCC then depends on a versioned API instead of
vendoring file paths; `vendor_loader.py` gets deleted. Scripts in the skill keep working by importing
the package. Already anticipated in TCC's brief ("later pip package `autosound-core`").

## SCR-013 — `verify_measurements` as a library function with a JSON verdict

**Status**: proposed · **Priority**: P3
**Target**: `rew_tool/verify_measurements.py`
**TCC dependency**: the measurement task card must show, per expected measurement: exists / valid /
drifted (TCC-TZ §4 "валідність свіпу"). The current file is a one-off Passat session script with
`sys.path` hacks and `print`-driven output — nothing TCC can call.

**Detail**: refactor into `rew_tool` library functions returning a machine verdict per measurement
(`{"name": ..., "exists": bool, "valid": bool, "issues": [...]}`), with the drift/validity math
factored out of the script `main()`. The CLI wrapper stays for skill sessions; TCC calls the function
through the vendored/packaged module and lights the indicator.

## SCR-014 — config lifecycle: provenance, `_open_questions`, change events with `impact`

**Status**: proposed · **Priority**: P2
**Target**: intake flow + every machine config file (`project.json`, `dsp_profile.json`,
`glossary.json`, `presets/*/target.json`) + the journal (SCR-004)
**TCC dependency**: TCC renders `_open_questions` as onboarding TODO chips (incremental intake right
in the UI), and must mark measurements/plan steps as *stale* — never delete — when a config change
invalidates them.

**Detail**: config is the mutable storage class (vs the immutable ledger and the append-only
journal — TCC-TZ.md §3). Its history is **git**: the project folder is already a git repo per
`naming-and-structure.md §4a`; do not build a second versioning system for rarely-changing files.
What the skill must add:

1. **Provenance per fact.** Generalize `dsp_profile.json`'s `sources` pattern: every recorded fact
   carries `source` (`user | measured | datasheet`) + date. "Where did 4 Ω come from" must always be
   answerable.
2. **`_open_questions` everywhere.** Unknowns are recorded, never guessed — extend the existing
   `dsp_profile.json` convention to `project.json` and `glossary.json`. Intake fills what it can;
   the rest is visible debt the skill retires over the project's life.
3. **Config-change events.** Every mid-project correction (driver swapped, amp gain re-staged, new
   preset, curve switch, per-vendor EQ band-order discovery) = a git commit + a journal event:
   `{"type": "config_change", "file": ..., "what": ..., "source": ..., "why": ..., "impact": ...}`.
4. **`impact` field** — the machine form of `naming-and-structure.md §2`'s "what raw data survives"
   table: `none | remeasure: [channels] | full_rebaseline`. Consequences: TCC flags affected
   measurements and plan steps as stale; the skill, on resume, sees the impact event and proposes
   re-measuring exactly the affected channels/joints (and re-entering the touched phase — phase
   gates are already re-entrant).

## SCR-015 — data-source structure for the left panel's Project / System / Car-audio-analysis sections

**Status**: proposed · **Priority**: P2
**Target**: intake flow + whatever config file(s) end up owning this (likely `project.json` per
SCR-011, or a dedicated `system_profile.json` alongside `dsp_profile.json`)
**TCC dependency**: `ui/tcc/main_window.py`/`ui/tcc/sidebar_section.py` (new 2026-07-28): the left
panel is now a 4-section top-level accordion -- **System params**, **Project params**, **Car audio
analysis**, **DSP** (in that display order). DSP is fully wired (the existing tree). Project params
reads `project_profile.json`'s `param_sections` (car/setup, body/chassis -- unchanged, just moved
out of the DSP tree into its own section, see `state/dsp_state.load_param_sections`). System params
and Car audio analysis are placeholders today: System params shows one static fact (REW's default
local port, 4735) plus a "no data yet" note; Car audio analysis shows only "no data yet".

**Detail**: need the skill to define (or point at an existing definition of) the source structure
for the fields these two placeholder sections should eventually show, so TCC can wire them up
without guessing a schema:

1. **System params** — the equipment side of the project: DSP model (already known via
   `dsp_profile.json`), amp make/model/gain-per-channel, head unit/source, mic/measurement rig,
   REW connection settings (host/port -- currently hardcoded display of the 4735 default, not read
   from or written to any config). Overlaps with SCR-011's `project.json` equipment facts and
   SCR-014's provenance-per-fact requirement (amp gain, in particular, changes mid-project and
   should carry a `config_change` event).
2. **Car audio analysis** — acoustic-analysis facts about the *installed car*, distinct from a
   per-channel measurement (which already has a home: the measurement task card / REW bridge):
   things like cabin RT60/reflections notes, install-quality observations from Phase 0 (intake +
   install), or a rollup of "what does the room do to us" that currently, if it exists at all,
   lives only as prose in `autosound_context.md`.

Until the skill (or this doc, on a follow-up pass) defines these two structures, TCC will not guess
a schema for either section -- they stay static placeholders by design, not an oversight.

## SCR-016 — Project params: processor type + channel-config summary (project data, not just knowledge base)

**Status**: proposed · **Priority**: P2
**Target**: skill intake flow, Phase −1 (intake + install) -- the same step that already resolves
the DSP model and channel layout to write `dsp_profile.json`/`knowledge/dsp/<slug>.md` (SCR-010)
**TCC dependency**: `ui/tcc/main_window.py`'s **Project params** sidebar section (SCR-015). Today it
only shows `project_profile.json`'s free-form `param_sections` (car/setup, body/chassis). User
request 2026-07-28: it should also show the DSP processor's identity and a channel-configuration
summary directly under it -- e.g., for the current real project: **Helix DSP Ultra S** — 8 virtual
channels (1 off), 12 output channels (2 off).

**Detail**: this is project-specific *summary* data -- how many channels of each tier this
particular install actually uses and how many are administratively off -- not the DSP's general
capability description (which SCR-010 already says belongs once in the shared
`knowledge/dsp/<slug>.md`, not duplicated per-project). The skill already learns the processor model
and full channel layout during Phase −1; it should write this project-scoped summary into the
project's own data structure (`project.json` per SCR-011, or a project-scoped block in
`dsp_profile.json`) rather than leave TCC to re-derive it.

Note this IS technically re-derivable today from data TCC already has -- `dsp_profile.json`'s
`groups[].max_count` plus each ledger row's `off` flag (`state/dsp_state.GroupRow.off`, read but not
rendered anywhere today, see the "OFF ... deferred to a future settings view" comment in
`ui/tcc/dsp_tree.py`'s `ChannelRow`) -- but per this doc's framing principle (the skill owns the
schema and writes the data; TCC is a consumer, not a re-deriver), TCC should render an explicit
summary fact the skill wrote, not duplicate the counting logic client-side.

## SCR-017 — open question: RearRC belongs in a DSP config file, not duplicated per preset ledger

**Status**: proposed (open question, not yet a concrete ask) · **Priority**: P3
**Target**: wherever the skill ends up putting DSP hardware-level config (new file, or a section of
`dsp_profile.json`) vs. the per-preset ledger (`state/state.py`'s `v_NNN.json`)
**TCC dependency**: `ui/tcc/dsp_tree.py`'s `tag`/`tag_value` chip (`ChannelRow`/`GroupRow.tag_value`,
added 2026-07-28 same as this doc pass) currently reads `RearRC`'s value (e.g. "3/4") straight off
each preset's own ledger row (`data/private/state/{FULL,SQ}/v_001.json`, hand-edited). **This was a
modeling mistake caught by the user (2026-07-28)**: RearRC is a physical
remote-control knob position on the Helix hardware -- it does **not** change between presets on the
same DSP, so it has no business being duplicated (and by hand, divergently -- the first pass here
briefly had it wrong for SQ) into every preset's ledger. What genuinely *is* per-preset is whether a
channel is **muted** (already correct: `mute: true` on the SQ ledger's rear channels/virtual rows,
independent of RearRC's own value, which stays "3/4" in both presets).

**Detail** — the open question for the skill: where should a DSP-hardware-level fact (RearRC/SubRC
knob position, and likely `RealCenter`'s ON/OFF too, since that's also not preset-specific) actually
live, so it's recorded ONCE per DSP rather than copy-pasted into every preset ledger where it can
drift out of sync? Candidates: a section of `dsp_profile.json` itself (it's a hardware-config file
already), or a new project-level `dsp_config.json` alongside it. Also note this entire tag
convention (RearRC/SubRC/RC) is **Helix-specific** -- a MUSWAY or other vendor profile has no
equivalent, so whatever structure the skill settles on must be optional/profile-declared, not
assumed universal. Until this is settled, TCC keeps reading `tag`/`tag_value` off the per-preset
ledger (simplest thing that works today) — moving it to a shared location is a follow-up once the
skill decides where "DSP hardware config, constant across this DSP's presets" belongs.

## SCR-018 — where does the REW project file's name + full path come from?

**Status**: proposed (open question) · **Priority**: P3
**Target**: intake flow / project config (`project.json` per SCR-011, or a dedicated field
alongside `dsp_profile.json`)
**TCC dependency**: user request 2026-07-28: show the REW project file's (`.mdat`) name and full
path as a hint somewhere in the measurement panel's header. Checked `rew_tool/rew_api.py` (the
vendored REW HTTP API wrapper) -- it has no endpoint that returns the currently-open project's file
path; REW's API surfaces measurements/curves/filters, not the host project file itself. So this
isn't a live read TCC can just add -- the fact has to come from somewhere else.

**Detail**: this is project-level config the skill would need to record at intake (or whenever the
user names/relocates their REW project file), the same class of fact as SCR-011's project.json
equipment list. Deferred rather than building a manual "type the path into a settings field"
placeholder in TCC first -- decided with the user (2026-07-28) to let the skill's own intake own
this fact if/when it's added, rather than TCC inventing a duplicate, unsynced input for it.

## SCR-019 — AI-session lifecycle: when TCC starts a new Generator session vs. resumes

**Status**: proposed (open design question, not yet answered -- user request 2026-07-28)
**Target**: TCC's live AI-dialog integration (`ui/tcc/dialog_panel.py` + a `core/agent_session.py`-
style session, once the Generator stops being `mock_data.DIALOG`) + the skill's own phase model
(`references/core/process-control.md`, the Phase −1..6 skeleton)
**TCC dependency**: this is the first thing to design before wiring a real AI dialog into the
window (see [[project_tcc_qt_port_status]] M8 follow-up, "biggest risk" per the user) -- without an
answer, every TCC launch either wastefully restarts context or silently drifts by resuming stale
state.

**Detail**: user's working hypothesis (2026-07-28), recorded as-is, not yet fully resolved:
- One **phase** (of the skill's existing Phase −1..6 method skeleton) maps to roughly one AI
  session -- not one session per app launch, not one session for the whole project.
- TCC needs explicit **semaphores** -- signals for when to start a genuinely NEW session vs.
  continue the existing one. Not yet designed: what those signals actually are.
- What's already certain: at the end of any significant chunk of work, and on app exit, enough
  context must be saved that a later launch (new session OR resume) can pick up correctly without
  re-deriving it from scratch.
- If a phase is NOT yet closed and a resumable session exists, TCC resumes it rather than starting
  fresh.

**Open questions this raises** (none answered yet):
1. What counts as "phase closed" -- the skill's own phase-gate criteria (already in
   `process-control.md`), or does TCC need its own separate closure signal?
2. Where does the resume-vs-new decision surface -- automatic on launch, or does the user get
   asked?
3. Does "save context on exit" mean SCR-004's `process-state.json`/`journal.jsonl` is already
   sufficient, or does TCC need an *additional* app-level snapshot (e.g. the live Agent SDK
   session id + last N turns) on top of what the skill already persists?

Likely the same underlying mechanism answers both "what's the current phase/step" (SCR-004's
concern) and "should the AI session resume" (this one) -- flagged as its own entry because it's
specifically about AI-session lifecycle, not just what the Plan panel displays.

**Also relevant to the wider AI-integration push** (not a separate SCR, notes from the same
conversation): the skill already has a working, non-mock Gemini "Critic"/"Advisor" channel --
`scripts/gemini_critic.sh` / `gemini_advisor.sh` (shell out to a locally installed CLI, `agy`
Antigravity or `@google/gemini-cli`, per `.critic-env`) and a fuller cross-platform
`scripts/autosound_ai.py` (same two roles, plus direct cloud-API calls and a "clipboard mode" that
copies a compiled markdown package for pasting into any web chat). TCC's Critic integration should
call/wrap these existing, already-working entry points rather than build a fresh Gemini SDK
integration from scratch. Confirmed scope for the Generator's v1 write access (user, 2026-07-28):
propose solutions + write EQ into REW's own filter/target model (not the physical DSP) + write a
Helix-format EQ string to the clipboard for the user to paste into Helix's own PC-Tool -- consistent
with the existing "no automated DSP writes" safety gate and with `autosound_ai.py`'s own clipboard-
mode precedent.

---

SCR-020…SCR-023 come from the installer design session (2026-07-30). Full design:
`docs/INSTALLER-TZ.md`. Framing principle: **the installer lives in TCC and the skill stays a clean
Claude plugin** — but a plugin has to be *runnable*, and these four items are what makes it runnable
for someone who installs the skill without TCC.

## SCR-020 — `requirements.txt` for the skill's Python code

**Status**: **done** — landed on the skill's `main` as `skills/autosound-tuning/requirements.txt` (2026-07-31)
**Target**: `skills/autosound-tuning/requirements.txt` (new file)
**TCC dependency**: the installer's `pip install` step and its hard-blocker preflight
(`python3 -c "import numpy, scipy, matplotlib"`), `docs/INSTALLER-TZ.md` §0, §2.2, §5.

**Detail**: the repo had **no `requirements.txt`, no `pyproject.toml`, and no `pip install` line
anywhere in README/FAQ** — `FAQ.md` §"First-Time Setup" only says `winget install Python.Python.3.11`.
So there was nothing to hand an installer, or a new user, that states what the environment needs.

**Correction to this entry's first draft** (which claimed a bare `ModuleNotFoundError` on the
documented install path): the skill is on a **deliberate dependency diet**, and the lazy imports are
a design choice, not an oversight. Verified in code:

| Package | How it is imported | Consequence when absent |
| :-- | :-- | :-- |
| `numpy` | **module scope** in `curve_view`, `dsp_math`, `eq_gate`, `make_plot`, `xover_select` | those modules do not import — the one hard dependency |
| `scipy` | lazy, 2 sites: `dsp_math.xo_response` (crossover design, what `xover_select.py` runs on) and `eq_gate._selftest` | `RuntimeError` naming the exact `pip install`; PEQ / all-pass / joint-phase unaffected; the EQ gate itself is scipy-free |
| `matplotlib` | module scope, `make_plot.py` only | plot rendering unavailable, nothing else |

So a missing extra costs one feature with a plain-language fix, not a session. The manifest exists so
the installer can put them in **up front**, instead of the wall arriving mid-tune.

Why it stayed invisible: the projects the skill has been exercised in carry their own scientific
stack. Measured on the author's machine 2026-07-30 — research project venv: `scipy 1.13.1`,
`matplotlib 3.9.4`; an older plain tuning project: no venv at all; system `python3` and the TCC venv:
neither scipy nor matplotlib.

Explicitly rejected alternative: declaring these deps in TCC's `pyproject.toml` instead. That does not
"keep the skill clean" — it makes **TCC mandatory for the plugin to work at all**, which is the
opposite of a self-contained plugin.

Pin policy: loose lower bounds (`numpy>=1.24` etc.), not exact pins — the skill is a library consumed
by TCC's venv, over-pinning would fight TCC's own resolver.

## SCR-021 — `opencode_critic.sh` / `opencode_advisor.sh`

**Status**: proposed
**Target**: `skills/autosound-tuning/scripts/opencode_{critic,advisor}.sh` + `_opencode_common.sh`
**TCC dependency**: `docs/INSTALLER-TZ.md` §1, §9. The installer makes OpenCode the default harness,
so the reviewer channel has to exist for it.

**Detail**: the wrapper family is `{gemini,claude,codex}_{critic,advisor}.sh` over shared
`_{gemini,claude,codex}_common.sh`. OpenCode is a fourth vendor in the same family — it belongs next
to its siblings, not in TCC, where it would be an orphan with no `_common` to source.

Why this matters beyond convenience: OpenCode can invoke a *different model in the same binary*
(`opencode run -m <other-vendor>`), which gives cross-vendor anti-anchoring from a single install, and
satisfies the skill's own "run reviewer CLIs **outside** the driver session (inside = deadlock)" rule
naturally, because it is a separate process.

Requirements carried over from the existing wrappers:

- model selectable via env var, mirroring `GEMINI_CRITIC_MODEL` / `GEMINI_ADVISOR_MODEL`, so switching
  the Critic to a paid model is one line in `.critic-env` and never a reinstall;
- `--doctor` with the same output contract (`✗ <problem>. Fix: <command>` per check, plus a live smoke);
- empty-reply detection — the free Zen tier will hit limits the same way `agy`'s weekly tier does, and
  `_gemini_common.sh:131` already documents that an empty exit-0 reply is the signature;
- `CRITIC_BIN` must stay independent of whatever drives the session (`INSTALLER-TZ.md` §9.2).

## SCR-022 — complete the Windows `.cmd` wrapper family

**Status**: proposed
**Target**: `skills/autosound-tuning/scripts/{claude,codex,opencode}_{critic,advisor}.cmd`
**TCC dependency**: `docs/INSTALLER-TZ.md` §12 R10.

**Detail**: `.cmd` wrappers exist **only for gemini** (`gemini_critic.cmd`, `gemini_advisor.cmd`).
Every other vendor is `.sh`-only, so a Windows user cannot switch reviewer vendors at all.

This is cheap now and expensive later: the scenario that forces the switch is a vendor changing its
policy (e.g. subscription auth disallowed in third-party harnesses, API-key-only left), and that
arrives without warning. A Windows user would then have no working reviewer channel and no way to
build one under time pressure.

## SCR-023 — README × 4 and FAQ must point at the installer

**Status**: proposed — **same release as SCR-020**, not backlog
**Target**: `README.md`, `README.uk.md`, `README.de.md`, `README.pl.md` ("Getting Started"),
`FAQ.md` ("First-Time Setup", "Setting up the Gemini/Antigravity Critic")

**Detail**: the documented install path becomes wrong in four languages at once the moment the
installer ships. Current text walks the user through `/plugin marketplace add` → `/plugin install`
→ `/reload-plugins`, never mentions Python dependencies, and hard-codes a two-CLI setup
(`claude` + `agy`) that the installer replaces with a single harness plus a model menu.

Minimum for this release: replace "Getting Started" in all four READMEs with a pointer to the
installer. Full FAQ rewrite and its uk/de/pl translations are backlog (`INSTALLER-TZ.md` §13) —
but the *wrong* instructions must not survive the release, because a newcomer who follows them
breaks on `numpy` (SCR-020) with no error message that explains why.

Note the direction of travel: install instructions move **out** of the skill repo and into TCC. The
skill's README should own "what this is and how to tune", not "how to get a Python environment".
