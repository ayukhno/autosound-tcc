# Skill change requests

Asks for the `autosound-tuning-skill` submodule (`vendor/autosound-tuning-skill/`) that TCC depends on
but does not own. TCC's own code never edits the submodule directly — these are tracked here and
processed in a batched skill-side session.

Status values: `proposed` (not yet actioned) · `accepted` (skill maintainers/self have agreed to do it)
· `done` (landed in the submodule and the pin bumped) · `superseded` / `rejected` (the ask stopped
being the right one — the reason is on the entry).

**Open as of 2026-08-13: SCR-049** (the project backup nobody wrote down). SCR-041 and SCR-042 closed on 2026-08-07; SCR-043, SCR-044 and SCR-045 on 2026-08-11, SCR-046, SCR-047 and SCR-048 on 2026-08-12. The table below is kept as the record of the last open batch.

| SCR | ask | where it bites |
|-----|-----|----------------|
| 041 | README/FAQ must name the supported pair | any other model reads as equally fine, and a downgrade fails by agreeing rather than by erroring |
| 042 | a spare slot does not say which tier it is spare in | the panel meant to show the whole rig cannot show the unused slots at all |

The statuses of SCR-001…019 were written before the 3.0 format break and had not been revisited;
they were checked against the code and corrected on 2026-08-06. Most of that batch had landed.

## SCR-001 — driver make/model + Fs per output channel

**Status**: done (v3 — `project.json` `channels[]` carries `driver.make/model` and `fs_hz` as a `fact()` with its source)
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

**Status**: superseded by the 3.0 break — identity (`slot`/`order`/`descr`/`role`/`hidden`) LEFT the ledger instead of being emitted into it; `project.json` owns it and consumers join on `code` (SCR-001/017). `validate` refuses a row still carrying those, so the migration is loud rather than lossy
**Target**: the vendored skill's ledger-writing code (state writer, wherever `v_NNN.json` files are
produced)
**TCC dependency**: `state/dsp_state.py`'s `GroupRow` (slot/order/descr/tag) and the tree's `role`
passthrough all assume these fields exist per channel — currently true only because the ledgers in
this repo were hand-edited during the M7 pass, not because the skill's own writer emits them yet.

**Detail**: carried over from M7 session notes (previously memory-only, "submodule task A6" — not
done). Any ledger the skill writes going forward needs to include `slot`, `order`, `descr`, `tag`,
and `role` per channel to match what TCC now renders.

## SCR-003 — explicit `hidden`/`unused` flag on unused virtual channels

**Status**: done (`hidden` on a `project.json` channel entry — `{"code": "vrf", "slot": "F", "hidden": true}`)
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

**Status**: done — `rew_tool/state/process.py` writes `process-state.json` + `journal.jsonl`; TCC reads both (`state/process_view.py`, the plan panel)
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

**Status**: done, and gone past it: v2 landed, then the 3.0 format break. One `schema_version: 3` across every machine file, `contract.py` checks it
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

**Status**: done (`"eq": [{"type": "PK", "f": 1000, "gain_db": -9, "q": 2, "bypass": false}]` — `state/schema.md`)
**Target**: ledger writer + `schema.md` (channel `eq` field)
**TCC dependency**: `state/dsp_state.py::EqBand.from_string` regex-parses the informal string
micro-format (`"PK 1000 -9 Q2"`); the planned EQ panel (30 bands, per-band bypass, TCC-Concept §7)
needs real per-band values, not a display string. The skill's own canon is the opposite extreme —
`eq_ptr` pointing at an export file, no values in the snapshot at all.

**Detail**: store bands structured: `[{"type": "PK", "f": 1000, "gain_db": -9, "q": 2,
"bypass": false}]`. Keep `eq_ptr` alongside for traceability to the exported `.req`. String forms
(`"PK 1000 -9 Q2"`) demote to display-only, generated. TCC drops its string parser once landed.

## SCR-007 — `dsp-state-current` is always generated, never hand-written

**Status**: done — `state.py` renders the `dsp-state-current` view and says so: generated-only, never hand-edited
**Target**: `SKILL.md` guardrails + `naming-and-structure.md` + phase docs
**TCC dependency**: indirect but structural — TCC treats the JSON ledger as the single source of
truth; any workflow where `dsp-state-current` (markdown) is maintained by hand can fork from the
ledger and TCC would render stale/contradicting state.

**Detail**: today SKILL.md says "re-read `dsp-state-current` before proposing" while `schema.md` says
`render` is generated-only — the multi-slot path already generates it (`registry render`), the
single-slot path is ambiguous. Make it uniform: `dsp-state-current` = `render` output of the ledger
HEAD, full stop. Edit the JSON (via `apply.propose`), re-render the markdown.

## SCR-008 — machine-readable channel glossary + naming-grammar functions

**Status**: done — `naming.py` carries the `Glossary` plus `parse_name`/`generate_name`/`expected_series`/`expected_groups`; TCC calls them rather than re-deriving the grammar
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

**Status**: done for the pointer — `process-state.json` `targets` is `{preset: curve}` and `set-target` is the only writer (SCR-036 gates on it). NOT done for the catalogue: the curves themselves are still code (`target_curves.py`), not data
**Target**: `naming-and-structure.md §6` convention + project scaffolding (`project-intake.md §5`)
**TCC dependency**: the header's `TARGET curve: <name>` per preset (TCC-Concept §4) and SCR-004's
"active target curve per preset" field. Today the ACTIVE curve + curve↔preset mapping live in a
human-maintained `rew_analitic/target-curves/README.md`.

**Detail**: add `target-curves/registry.json` (`{"active": ..., "curves": {"<name>": {"presets":
[...], "path": ...}}}`), same pattern as the slot `registry.json`. README becomes generated from it.
The ledger's per-snapshot `target` string stays as the historical record; the registry is the live
pointer.

## SCR-010 — one canonical DSP capability profile; skill owns the field vocabulary

**Status**: done — `dsp_profile.py` + a project's `dsp_profile.json`; the skill owns the field vocabulary and TCC renders whatever tiers it declares
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

**Status**: done — `project.json` holds the machine facts, `autosound_context.md` stays the prose profile
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

**Status**: **rejected** — two repos, forever, and no third (see the repo-boundary decision in `docs/TCC-TZ.md` §7). TCC vendors the skill as a submodule and loads `rew_tool` by explicit path (`core/vendor_loader.py`); an `autosound-core` package would be a third thing to version for no gain
**Target**: repo structure — `rew_tool/` flat script dir → a proper package with semver
**TCC dependency**: `core/vendor_loader.py` exists solely because `rew_tool` is a flat, `__init__`-less
directory whose module names (`state`, `analysis`) would collide on `sys.path`; TCC loads three files
by synthetic path. Every new shared schema (SCR-004/005/008/010) makes this hack load-bearing.

**Detail**: turn the data layer (state/ledger, apply gate, registry, dsp_profile, rew_api, naming
functions, schemas) into an installable package. TCC then depends on a versioned API instead of
vendoring file paths; `vendor_loader.py` gets deleted. Scripts in the skill keep working by importing
the package. Already anticipated in TCC's brief ("later pip package `autosound-core`").

## SCR-013 — `verify_measurements` as a library function with a JSON verdict

**Status**: done (skill `7807114` — `rew_tool/verify.py`: `verdict()` / `verify()` / `summary()` return `{name, exists, valid, issues, stats}` per REW title, plus a `--json` CLI whose exit code is 0 only when every title is usable. `verify_measurements.py` stays as the one-off Passat script it says it is. Validity is FR-side (empty / flat to under a dB / silence / truncated); the impulse stats are reported and never judged — gating on `pre_ringing_dB` marked both of this project's real sweeps unusable, since on a car sweep everything before the peak includes the loopback reference.)
**Target**: `rew_tool/verify_measurements.py`
**TCC dependency**: the measurement task card must show, per expected measurement: exists / valid /
drifted (TCC-TZ §4 "валідність свіпу"). The current file is a one-off Passat session script with
`sys.path` hacks and `print`-driven output — nothing TCC can call.

**Detail**: refactor into `rew_tool` library functions returning a machine verdict per measurement
(`{"name": ..., "exists": bool, "valid": bool, "issues": [...]}`), with the drift/validity math
factored out of the script `main()`. The CLI wrapper stays for skill sessions; TCC calls the function
through the vendored/packaged module and lights the indicator.

## SCR-014 — config lifecycle: provenance, `_open_questions`, change events with `impact`

**Status**: done — `fact()` wraps a value with `source`/`at`, `_open_questions` lists what is unanswered, and `project.py record-change` writes a `config_change` event with `impact`. TCC reads the impact (`state/plan_audit.stale_channels`)
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

**Status**: done (skill `c2aeafb`, TCC `HEAD`) — System params reads `project.json`, and **Car audio analysis renders the phase-0 Acoustic Flaw Map** (user's own framing, 2026-08-07): what this cabin does to the sound, one row per finding — frequency · width · the feature's own height/depth — and, load-bearing, what may and may not be done about it. `project.py flaw` writes it into `project.json` under `acoustics.flaws[]` with closed `kind`/`action` lists, and refuses a dip recorded as notchable. TCC colours by `action`: correctable · leave alone · never boost · fixable but not with EQ.
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

**Status**: done, in a different place than the ask — the processor's identity is a System-params row, and the per-tier channel summary is the group header there (`OUTPUT 6/12`), built 2026-08-06. Project params kept its own scope (car/setup, body/chassis)
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

**Status**: done — `project.json` `hardware.controls` is the single DSP-level home; a ledger row carries only `tag`, naming WHICH control affects it, and the value is resolved on read (`GroupRow.tag_value`)
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

**Status**: done as a field — `project.json` `paths.rew_project`, filled when intake records it. Whether intake actually asks is a flow question, not a schema one
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

**Status**: answered by implementation — `core/session_registry.py` binds one session per phase and resumes it (`resumable_session`), which is the hypothesis this SCR recorded. Reopen if the phase↔session mapping turns out wrong in use
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

## SCR-026 — `apply.propose` emits the change delta, not only the snapshot

**Status**: done (skill `15ba1b1`, TCC `HEAD` — `propose` writes `<preset>/proposals/<v_NNN>.json` from the same `delta_rows` the settings sheet renders from, each row carrying the formatted value the Arbiter keys and the raw one beside it; `state/proposal_view.py` reads it and the window shows the card once per version. The strategy branch — TCC hands off to the delta file instead of prose — is NOT decided here; the skill still prints the sheet, and both now say the same numbers because both come from one structure.)
**Target**: `skills/autosound-tuning/rew_tool/state/apply.py` (`propose`), alongside the
`v_NNN.json` snapshot it already writes
**TCC dependency**: the settings-sheet card in the dialogue panel. The render spike
(`spike/render_dialog.py`, `sheet_html`) had to invent `spike/fixture/proposals/v_007.json`
because nothing on disk carries what the card needs.

**Detail**: the ledger stores a full **snapshot** per version — the state after the change. The
Arbiter's sheet is about the **change**: which channel, which parameter, what it was, what it
becomes, and whether the EQ gate passed. Today the skill computes exactly that (it has to, to
print the sheet in chat) and then throws it away, leaving the front-end to diff two snapshots and
re-derive intent it can only guess at — a `gain_db` that moved could be a level-match trim or a
banked decision, and the snapshots do not say which.

Ask: `propose` writes a sibling `presets/<preset>/proposals/<v_NNN>.json` with the delta it already
built. Minimum shape, matching what the card renders:

```jsonc
{"version": "v_007", "preset": "SQ", "at": "…", "note": "…",
 "settings": [{"tier": "channels", "channel": "c", "param": "hp.f",
               "was": "620 Hz LR36", "value": "680 Hz LR36"}],
 "eq_gate": "passed (max boost +1.8 dB <= +6 dB)", "max_boost_db": 1.8}
```

**Why this is more than a rendering convenience**: SKILL.md's Core Guardrails require actionable
params to land in chat as a legible list, which today means the model **retypes** numbers it
already computed. That is a transcription surface with no gate on it — exactly the class of error
that "gains as ABSOLUTE values only" exists to prevent. With a delta file the Arbiter reads the
values the ledger banked, not the values the model re-rendered. Structurally this is the same
argument as SCR-007 (`dsp-state-current` is generated, never hand-written), applied to the sheet.

**Consequent skill-strategy change** (needs a decision, not just code): when the front-end is TCC,
the "settings land in chat" rule should hand off to the delta file rather than prose. The terminal
front-end keeps printing the sheet as today. TCC already tells the agent where it is running
(`tuning_session.SYSTEM_PROMPT_APPEND`), so the skill can branch on that.

## SCR-027 — `critic_called` links to the critique text

**Status**: done (skill `15ba1b1`/`829a7bc`, TCC `HEAD` — `autosound_ai.py` writes every answer to `process/reviews/<ts>-<role>.md` and prints a `>> REVIEW_FILE:` marker; `critic_called` carries `review` + `mode`, TCC parses the marker and records the call itself, and the Critic bubble links the file. Clipboard mode writes the compiled package to the same place with `mode: clipboard`.)
**Target**: `skills/autosound-tuning/rew_tool/state/process.py` (`record_reviewer`, event
`critic_called`) + `scripts/autosound_ai.py` (persist its stdout instead of only returning it)
**TCC dependency**: the Advisor bubble in the dialogue panel; `core/critic.py` already parses the
`— [critic: <model>]` marker and holds the text in memory only for the duration of the call.

**Detail**: `critic_called` records `vendor`, `model`, `phase`, `step`, `outcome` — enough for a
process chip ("Gemini 3.1 Pro — revise"), nothing for the bubble that should carry *what the
reviewer actually argued*. Today that text exists only in the chat stream, so a session rendered
from disk shows that a critique happened and how it was resolved, but not the reasoning — which is
the part worth reading back a week later, and the part an audit needs.

Ask: `autosound_ai.py` writes the critique to `process/reviews/<ts>-<role>.md`, and the
`critic_called` event carries a `review` pointer to it (relative path). Clipboard mode writes the
compiled package to the same place with `"mode": "clipboard"` on the event, so the record shows a
review was requested and answered by hand rather than silently looking like no review happened.

**Related**: this closes the same gap SCR-004 closed for phase/plan — narrating in chat without
writing the matching record leaves resume and any front-end with nothing real to read.

## SCR-028 — prescribed commands must not invoke a bare `python`

**Status**: accepted — fixed in `autosound-skill-bridge` `344b57e` (branch `feat/tcc-sync-p0`,
2026-08-04), option 2 (`python3` everywhere). Not `done`: the vendored submodule is still pinned at
`7b93b75`, which does not carry it, so the pin bump is outstanding.
**Target**: **30 call sites across 8 files** (counted 2026-08-04): `rew_tool/state/schema.md` ×7,
`rew_tool/project-schema.md` ×6, `SKILL.md` ×6, `references/core/project-intake.md` ×4,
`references/tooling/helix-eq-export.md` ×3, `references/core/data-contract-universal.md` ×2,
`references/tooling/installation.md` ×1, `references/phases/phase_-1_intake.md` ×1
**TCC dependency**: none directly — this breaks the skill for every user on a stock macOS,
whatever front-end they run.

**Detail**: observed live. Running the skill under OpenCode on macOS, the agent obeyed SKILL.md and
ran `python rew_tool/contract.py check .`, which returned `zsh:1: command not found: python`. Apple
ships no `python` — only `python3` — and has not shipped one since Python 2 was removed. Under
Claude Code this has been invisible because the developer's shell happens to have a `python` on
PATH (a venv, pyenv, or Homebrew); it is not a property of the method, it is a property of one
machine.

The consequence is not cosmetic. The turn under test spent roughly ten minutes and six bash calls
failing to reach `process.py`, and wrote **nothing** to `process/journal.jsonl` — not because the
model declined to record the process, but because the prescribed path to the recorder does not
exist on the machine. Every downstream guarantee that rests on the journal (resume, evidence gates,
any front-end's plan panel) silently degrades to nothing.

Ask, in order of preference:

1. The project supplies the interpreter and the skill uses it — the installer already builds a venv
   with `numpy`/`scipy` (`INSTALLER-TZ.md` §2.2), so the honest fix is a resolved path the project
   records once, not a name the shell has to guess.
2. Failing that, `python3` everywhere. Correct on macOS and on every current Linux; the only losers
   are machines where `python3` is absent, which are not the target.

Either way the rule to state in SKILL.md is that a prescribed command names a **resolved**
interpreter, never a bare one.

> **Re-run, same conditions, fixed skill (2026-08-04)**: the fix is in, but this run did not
> exercise it. Gemini ran five bash calls and **not one of them invoked an interpreter** — the turn
> ended at the intake interview before any `process.py` call was attempted. So SCR-028 is landed and
> unfalsified, not landed and confirmed; the confirming run is one that actually reaches the
> recorder over bash. See the re-run record under SCR-031.

## SCR-029 — skill self-location must be portable, not `file:///skills/...`

**Status**: accepted — fixed in `autosound-skill-bridge` `dd7af76` (branch `feat/tcc-sync-p0`,
2026-08-04): a "Resolving paths in this skill" preamble in SKILL.md declares the skill root and
107 references were rewritten relative to it. Same outstanding pin bump as SCR-028.
**Target**: **108 links across at least 12 files** (counted 2026-08-04) of the form
`file:///skills/autosound-tuning/...` — `SKILL.md` ×47, then `phase_5_variations.md` ×7,
`core/process-phases.md` ×7, `phase_4_listening.md` ×6, `phase_1_foundation.md` ×6,
`core/preference-profile.md` ×5, `tooling/rew-tool-docs.md` ×3, `phase_3_control.md` ×3,
`phase_-1_intake.md` ×3, `patterns/target-curves/target_curves_guide.md` ×3, and the rest —
plus the implicit assumption that `rew_tool/` is reachable relative to the working directory
**TCC dependency**: `tuning_session._read_roots_for()` already has to resolve the
`.claude/skills/autosound-tuning` symlink to its real location so reads of the skill are not gated
— the same resolution the model itself cannot perform from inside the conversation.

**Detail**: `file:///skills/...` is Claude Code's own addressing. Under any other harness it names
nothing. In the observed run the agent, unable to resolve it, fell back to searching:
`find . -name "rew_tool" -type d` returned nothing, because `find` does not descend into symlinks
by default and the skill is mounted at `<project>/.claude/skills/autosound-tuning` as a link out to
the checkout. It recovered eventually — by resolving the symlink by hand — after about three minutes
of hunting.

This is the concrete, measured form of the port that `TCC-TZ.md` §4a called for in the abstract:
the skill is Claude-Code-shaped, and the shape leaks through its own cross-references.

Ask: the skill states its own absolute root once, at load, and every internal reference is relative
to that. Mechanically this can be a one-line preamble the harness fills, an env var the front-end
sets (TCC already sets several — SCR-011 converged them on `AUTOSOUND_*`), or a tiny resolver
script. What matters is that no reference in the body depends on a URL scheme only one harness
understands.

**Related, and the reason this is worth doing rather than routing around**: when TCC's MCP server
is up, the process-recording tools are available as MCP tools and the agent never needs to find
`rew_tool` at all (`report_phase` already exists on that surface). But the skill must also work
from a plain terminal with no TCC running — that is front-end B, and it is the path with no
authentication question attached. A skill that only works when TCC is running would trade one
lock-in for another.

> **Correction, from the run with TCC's MCP server up (2026-08-04)**: the parenthesis above is
> wrong on the facts. `report_phase` is not a recorder — its own docstring says "This records
> nothing"; it re-reads `process-state.json` and refreshes what the Arbiter sees. `grep journal
> core/mcp_server.py` returns nothing. There is no journal writer on the MCP surface at all, so
> the agent still reaches the recorder through `rew_tool/state/process.py`, and this SCR is load-
> bearing in every configuration, not only the no-TCC one.

> **Confirmed by the re-run (2026-08-04)**, and this one is measured. With the preamble in place the
> agent went straight to `ls -la .claude/skills/autosound-tuning/rew_tool` on its first look at the
> skill — no `find`, no `glob` scan, no symlink hunt. The pre-fix run spent two glob passes (`*`,
> then `**/*`, the second costing ~68 s) getting to the same place. Do **not** read the wall-clock
> drop (320 s → 52 s) as the size of this win: the pre-fix run's first tool call did not land until
> 198.65 s, the re-run's at 17.24 s, and that ~180 s is provider latency ahead of any skill text.
> The honest figure attributable to SCR-029 is the eliminated scan.

## SCR-030 — the Arbiter's answers are not events

**Status**: done (skill `fed5464`, TCC `HEAD` — a `user_decision` event carrying the question, the answer as given, the phase/step it was asked under and `invalidates`; a `decision` subcommand and a `record_decision` MCP tool write it, and TCC writes one itself whenever the Arbiter clicks an option, which is where the answer is machine-readable. SKILL.md: record a ruling before acting on it.)
**Target**: `rew_tool/state/process.py` + the journal vocabulary fixed in SCR-004 — one new event
type and the command that writes it; SKILL.md states when it is mandatory
**TCC dependency**: the dialog render (`spike/render_dialog.py`, headed for `ui/tcc/dialog_panel.py`)
draws Orchestrator and Advisor turns from `journal.jsonl` and has nothing to draw the Arbiter with;
`process-state.json` is what a resume reads, so a constraint the user set is invisible to the next
session unless it happens to be re-read out of prose.

**Detail**: measured, not reasoned. In the observed turn the user answered six questions across two
rounds — session language, DSP identity, reviewer channel, system goal, reference seat, and whether
to re-measure the baseline at 96 kHz. The journal grew by **eleven** events, and **not one of them
records an answer as an answer.** Two of those answers are durable engineering constraints:
*reference seat = driver's seat* binds every alignment and target-curve decision from Phase 0 on,
and *re-measure at 96 kHz* invalidates a 12 MB baseline already on disk. Both exist only as prose,
in `autosound_context.md` and in the chat text.

The vocabulary is the reason. SCR-004 fixed `phase_entered`, `step_added`, `attempt_started`,
`step_skipped`, `step_done`, `critic_called`, `config_change` — the Generator's moves and the
Critic's calls. The method has three roles; the third one leaves no trace. `config_change`
(SCR-014) is the near miss: it carries `impact`, which is exactly the shape "the 48 kHz baseline is
now superseded" needs, but a user ruling is not a config change and forcing it there would lie
about provenance.

Two further symptoms of the same hole, both visible in the same eleven events:

- the only surviving trace of an answer is a hand-typed evidence string —
  `step_done lang ["user-answer 2026-08-04: Ukrainian (session), English (skill issues)"]`. That is
  the transcription surface SCR-026 objects to, in a second place: the answer is retyped into prose
  rather than referenced;
- answers that arrive mid-step have nowhere to land at all. `interview` bundles language, goals,
  seat, car, drivers and Fs into one step that cannot close until the last fact arrives — correctly,
  the model refused to mark it done without evidence. So three answered facts sat inside an open
  `attempt_started` with no way to say which of them were in.

**What makes this cheap now**: under OpenCode the answers do not have to be parsed out of free text.
The harness has a structured question channel (`GET /question`, `POST /question/{id}/reply`, SSE
`question.asked`/`question.replied`) and the reply is a chosen option label. The machine-readable
form already exists at the moment of the answer and is currently discarded.

Ask, smallest version first:

1. A `user_decision` event: the question asked, the option chosen, the step or phase it was asked
   under, and — where it applies — `invalidates` (same field shape as `config_change.impact`, so a
   ruling that supersedes a measurement is legible to the same reader).
2. A `process.py` subcommand that writes it, so recording an answer is one prescribed call and not
   a judgement about which existing event to bend.
3. SKILL.md rule: an answer that constrains a later phase is recorded before it is acted on. Prose
   files may repeat it; they may not be the only copy — "machine files win" is already the skill's
   rule, and today the Arbiter's half of the conversation is not in one.

## SCR-031 — the recorder is prescribed as a shell call even when it is a tool

**Status**: done (skill `fed5464`, TCC `HEAD` — the prescription sites now say tool-first: where a process-recording tool is on the surface that is the call, the command lines stay exact for a plain terminal. Opening the phase became an entry condition, before the first question. TCC seeds `enter_phase(-1)` itself when a session starts against a project with no process state, and writes `session_started` on every attach.)
**Target**: every site that names the recorder as a command line — `SKILL.md` ~line 65 ("Write the
PROCESS as it happens"), `references/core/project-intake.md` ~line 137 (`enter-phase -1` at the start
of Phase −1), `references/core/process-control.md`
**TCC dependency**: `src/autosound_tcc/core/process_writer.py` + the recorder tools on the MCP
surface (`enter_phase`, `add_step`, `start_step`, `finish_step`, `skip_step`, `block_step`), landed
in `3f75dd0`. The skill has no way to know they are there, so it prescribes the CLI unconditionally
and the agent is left to notice the tool on its own.

**Detail**: SCR-028 and SCR-029 were called blocking on the theory that the empty journal was a
reachability problem — the agent could not reach the recorder, so of course it wrote nothing. Both
are fixed. The re-run says reachability was **necessary and not sufficient**.

Re-run record (2026-08-04, `spike/real_turn.py`, artifacts in that session's scratchpad as
`run2-report.txt` / `run2-gemini-notcc.jsonl`). Conditions held identical to the first of the three
runs in `spike/HANDOFF.md` §3 — `google/gemini-3.1-pro-preview`, same neutral prompt, no TCC MCP
server (`GET /mcp` → `{}`), no `mcp` block in config. Clean project directory (`testTCC-EPY-2`)
holding only `EPY_0db_REW.txt`, `baseline_phase0.mdat`, and the skill symlink; the three-run evidence
directory was left untouched. One variable: the fixed skill.

| | run 1 (§3) | re-run |
| :-- | --: | --: |
| events in `process/journal.jsonl` | 0 | **0** |
| disk search for `rew_tool` | 2× `glob` (`*`, `**/*`) | none — direct path |
| interpreter written | — | none written at all |
| wall clock | 320 s | 52 s (≈180 s of it provider latency, see SCR-029) |
| turn tokens / longest prose | 40 870 / 2088 ch | 39 570 / 1649 ch |

Six tool calls: `skill`, `ls -la`, `cat EPY_0db_REW.txt`, `ls -la .claude/skills/autosound-tuning/
rew_tool`, `cat references/phases/phase_-1_intake.md`, `cat references/core/project-intake.md`. Then
the turn ended with a correct situation report and four intake questions in prose. Nothing was
written to disk — no `process/`, no `autosound_context.md`.

The diagnosis is sharper than "the model was lazy", and it is what makes this a skill ask rather than
a note. The agent **read `project-intake.md`**, whose §files bullet says verbatim
`python3 rew_tool/state/process.py <project>/process enter-phase -1` *at the start of this very
phase*, and did not call it. Instruction delivered, path resolvable, interpreter correct, still no
event. What is missing is not information but a default: the skill describes recording as one item in
a list of things to do during the phase, and a model that decides to ask its questions first drops it
without ever disobeying a sentence.

Alongside, from the parallel run with TCC's recorder tools up (dirty project directory, so not a
clean comparison): Gemini called `tcc_enter_phase` once and wrote **one** event, then went back to
bash and prose. Presence of the tool moved 0 → 1. The grid now has one empty cell — recorder tools up
**and** a clean directory — and that number is what tells us how thin the supervisor can be.

Ask:

1. Where the skill prescribes a recorder call, state the tool-first rule: if a process-recording tool
   is on the tool surface, that is the call; the `process.py` command line is the fallback for a
   plain terminal with no front-end. Same two-path shape SCR-029 settled for references — the skill
   stays runnable with nothing else present, without pretending the CLI is the only door.
2. Make the first call of a phase an entry condition rather than a checklist item: opening the phase
   precedes asking the user anything, so an interview that runs long cannot leave the phase
   unopened. This is the one ordering the re-run actually broke.

**Parked for the TCC side** (not asks against the skill — recorded here so the re-run's conclusions
survive in one place):

- **Seed the first event from TCC.** If a session starts against a project with no `process/`, TCC
  calls `enter_phase` itself. Event one then does not depend on which model the user brought.
- **Reconcile at the turn boundary**, not in the prompt. The failure mode observed twice is a turn
  that narrates a phase or a step and records neither; comparing the two at turn end is where a
  supervisor can act, and it is `spike/HANDOFF.md` §5 item 3 with a measured shape.
- **The question channel is implicated again** (§5 item 2). This turn ended on four unanswered
  questions in prose. Gemini asks in prose, Claude asks structurally; either way a TCC window that
  does not render the ask looks like a finished turn that stopped for no reason.
- Harness note: the re-run was executed on OpenCode, which `a6690b7` rejected on the subscription
  axis. It does not weaken the finding — the defects and the compliance gap are in the skill, and
  `HANDOFF.md` already establishes that determinism is not a harness property. The numbers should be
  re-taken on omp when convenient, not treated as suspect until then.

## SCR-032 — `__pycache__` is tracked, so running the skill dirties the checkout

**Status**: done — `__pycache__/` is in the skill repo's `.gitignore` and nothing matching it is tracked
**Target**: `skills/autosound-tuning/rew_tool/__pycache__/`, `rew_tool/state/__pycache__/`,
`rew_tool/gates/__pycache__/` — **11 tracked `.pyc` files**; plus `.gitignore`, which already
carries careful rules for OS files and project data but nothing for build output
**TCC dependency**: none any more, and that is the point — TCC stopped causing it from its side
(`vendor_loader.child_env()` sets `PYTHONDONTWRITEBYTECODE` for every subprocess that runs the
skill, `sys.dont_write_bytecode` guards the in-process loads). The ask is for everyone else.

**Detail**: bytecode caches are committed to the skill repo. Any Python that imports or runs
`rew_tool` rewrites them, so the working tree reports modifications nobody made:

```
M skills/autosound-tuning/rew_tool/__pycache__/dsp_profile.cpython-312.pyc
M skills/autosound-tuning/rew_tool/__pycache__/naming.cpython-312.pyc
M skills/autosound-tuning/rew_tool/state/__pycache__/process.cpython-312.pyc
…
```

Two costs, both small and both permanent. Noise: as a submodule it shows as `m` in the parent's
`git status` forever, which is exactly where a real pin drift would show, so the signal that
matters sits under one that never means anything. And risk: the caches are version- and
platform-stamped (`cpython-312`), so a contributor on another interpreter commits a wholesale
rewrite of files that should not be in the history at all.

This lands on **front-end B** specifically — the plain terminal with no TCC running, which is the
path with no authentication question attached (SCR-029's closing note). That user gets a dirty
checkout the first time they run anything, and no `child_env()` to protect them.

Ask, both halves:

1. `git rm --cached` the 11 files and add `__pycache__/` + `*.pyc` to `.gitignore`.
2. Nothing else — no interpreter flags in prescribed commands. A repo that does not track build
   output does not care whether the caches get written.

## SCR-033 — the reviewer is Gemini-shaped; make the transport a parameter

**Status**: done (skill `7807114`, TCC `HEAD` — `autosound_ai.py` resolves the vendor from the model name and takes that vendor's API or CLI: google (`agy`/`gemini`), anthropic (`claude`), openai (`codex`), each raw-HTTP because the script must run with nothing installed. `AUTOSOUND_CRITIC_MODEL` is the vendor-neutral name; `GEMINI_CRITIC_MODEL` still works and means the same thing. `critic_reaches` stopped asking "is it Gemini" and now asks whether this machine has the chosen vendor's key or CLI.)
**Target**: `skills/autosound-tuning/scripts/autosound_ai.py` — `call_gemini_api` (the only API
function), `detect_cli` (`agy`/`gemini` only), the CLI invocation `[bin, "--model", M, "-p",
<path>]`, and `run_doctor`'s provider report
**TCC dependency**: `core/critic.py` steers the script through `GEMINI_CRITIC_MODEL` /
`GEMINI_ADVISOR_MODEL` and deliberately knows nothing about model names. TCC's Critic picker is
being converged onto the same registry as the Generator picker (`core/model_choices.py`), and the
moment those lists agree, the picker offers models the reviewer cannot reach.

**Detail**: the method is vendor-neutral by design — SKILL.md's three roles call for a *different
vendor's* model as Critic, and the whole point is that it is not the Generator. The script is not:

* one API path exists, `call_gemini_api`. There is no Anthropic call at all;
* `detect_cli` looks for `agy` and `gemini` (or a `GEMINI_BIN` override);
* the CLI is invoked as `[bin, "--model", M, "-p", <temp file path>]`. Claude Code's `-p` takes a
  **prompt string**, not a path, so `GEMINI_BIN=claude` runs and sends the model the literal
  filename — the shape of a bug that looks like a bad review rather than a broken call;
* `run_doctor` prints "▶ Режим роботи: АВТОМАТИЧНИЙ (через API Anthropic)" when it finds
  `ANTHROPIC_API_KEY`, and then no code path can use it. A false green light is worse than no
  detection: it sends someone to debug their key.

**What TCC learned doing this on the Generator side, offered rather than re-derived.** The harness
investigation (`spike/HANDOFF.md`) landed on three things that apply here unchanged:

1. **Model and transport are one choice, made explicitly.** `core/model_choices.py` carries a
   `Choice(harness, model, …)`; picking a model picks how it is reached. The reviewer needs the
   same shape — `GEMINI_CRITIC_MODEL` names a model and silently assumes a vendor.
2. **A one-shot reviewer needs no per-provider integration, because one already exists.** omp
   (`spike/HANDOFF.md` §5-ter) is a single binary with a credential broker covering Anthropic
   Pro/Max, ChatGPT/Codex, Copilot, Z.AI, local runners and the rest, and `omp -p "<prompt>"
   --model <provider/selector>` is exactly a one-shot. One transport replaces the N provider APIs
   this script would otherwise grow. Measured on this project: `omp models --json` returns
   `{provider, selector, name, contextWindow, cost}` per model, so cost is known at choosing time.
3. **The licensing line, which is the reason not to just add an Anthropic API call.** TCC's rule is
   that it never holds credentials and never steers to a third-party client for a Claude
   subscription (`spike/HANDOFF.md` §5-ter, and `a6690b7`). The reviewer should inherit it: reach
   Claude through the **user's own CLI**, never through a key the skill asks for.

Ask, smallest first:

1. `detect_cli` and the invocation stop assuming Gemini's argument shape. A CLI entry carries how
   it is called — Claude Code takes the prompt as a string, `gemini` takes `--skip-trust` and a
   path — so the per-CLI difference lives in one table rather than in `extra_args`.
2. A generic `omp` transport, tried like the others. It is the cheapest way for the reviewer to
   become vendor-neutral for real, and it is the transport a subscription can pay for.
3. `run_doctor` reports only what a run can actually use. Finding a key the script cannot call is
   worth saying — as "found, unused", never as the automatic mode.

Until at least (1), TCC's Critic picker has to mark non-Gemini choices as clipboard-mode, which is
a front-end apologising for a method-level gap.

## SCR-034 — the capture task is derived but never recorded

**Status**: done (skill `9eee08d`, TCC `HEAD` — four journal events (`capture_task_issued` / `capture_taken` / `capture_skipped` / `capture_round_closed`), four `process.py` subcommands and the matching MCP tools; the open round lives in `process-state.json` under `capture`. `measurement_view` reads it, so a finished round survives REW being closed and a skip is its own status rather than another `wait`.)
**Target**: the journal vocabulary fixed in SCR-004 (`rew_tool/state/process.py`) — new event
types and the commands that write them; `naming.expected_groups` stays as it is
**TCC dependency**: `state/measurement_view.build_session` derives the checklist today and
`ui/tcc/measurement_panel.py` renders it. Nothing here asks the skill to hand TCC a list — the
derivation is right where SCR-004 put it. What TCC cannot do is show history, because there is
none to read.

**Detail**: the derivation half is done and works. `build_session(phase, version, titles)` calls
the skill's own `naming.expected_groups(phase, glossary, version)`, matches the result against the
measurement titles REW reports, and renders three states per item: `done`, `wait`, and `stale` for
a capture whose channel a `config_change` invalidated (SCR-014) — "the graph exists and is
unusable" is already distinguished from "missing". Captures that belong to this version but are
not on the checklist get their own `additional` group rather than being dropped.

What is missing is the **record**. Every one of those statuses is recomputed, on every refresh,
from the list of titles currently open in REW. Three consequences, none of them cosmetic:

* **REW closed means the panel cannot tell taken from not-taken.** The evidence for a whole
  capture round lives in another application's session.
* **Nothing survives.** There is no history of when a round happened, how long it took, or how
  many attempts it needed — while `journal.jsonl` records exactly that shape of thing for every
  other kind of work.
* **"Deliberately skipped" is indistinguishable from "not done yet".** Both render as `wait`. A
  tuner who decided a capture was unnecessary has no way to say so, and the next session
  re-proposes it.

There is also no session identity. The task is keyed `v{version}` — the ledger HEAD, which is
correct for *naming* the measurements (`_N` is the config they were taken under,
`naming-and-structure.md` §3) but wrong for identifying the round: two capture passes at the same
config are the same key. What the Arbiter asks about is "this session's task".

Measurement names do reach the journal today, as strings inside `step_done`'s evidence. That is
the transcription surface SCR-026 and SCR-030 object to, in a third place: the fact is retyped
into a proof rather than recorded as itself, so nothing can be counted, filtered, or re-derived
from it.

Ask:

1. Capture events in the journal, against phase + ledger version + a session id the skill already
   has: the task issued, a capture taken (title, when), a capture skipped (with the reason —
   skipping is a decision, and SCR-030 makes the same point about the Arbiter's other decisions),
   an unplanned capture added.
2. `process.py` subcommands to write them, so recording a round is a prescribed call rather than a
   judgement about which existing event to bend.
3. Nothing new for the derivation. `expected_groups` stays the source of what *should* be
   captured; these events are what *happened*, and план-факт is the two read together — which is
   the whole shape TCC's plan panel is built on.

## SCR-035 — `step_done` evidence must be checkable, not just present

**Status**: done (landed as `ff58abd` — `finish_step` requires at least one evidence item that
resolves: a capture name in the grammar WITH its `(sw|rta)` method suffix, a ledger version that
exists on disk, or a project file that exists. `check` gained the second question — done steps
whose evidence resolves to nothing now. The narrower alternative at the bottom of this SCR is what
landed: prose may ride along with a resolvable item, it may not be the whole list.)
**Target**: `rew_tool/state/process.py` — the `done` command's evidence check (currently "is the
list non-empty"), and the vocabulary SKILL.md prescribes for what an evidence item may be
**TCC dependency**: TCC is building the план-факт audit that catches this from the outside
(`core/plan_audit.py`), because it can see the disk. It should not have to: a step that cannot be
proven should not close in the first place, and the skill is where closing happens.

**Detail**: observed end to end, in a real project, with a cheap model — which is the case that
matters, since the whole harness decision rests on cheap models being viable
(`spike/HANDOFF.md` §5-bis).

Gemini 3.5 Flash Lite closed phases −1 through 3 and reported the tune finished. Its final
message listed crossovers per driver, delays to 0.1 ms, gains to 0.5 dB, EQ "within ±0.5 dB in the
passband", verified phase coherence at the crossover points, and a listening verdict: *"the stage
is focused on the centre of the dashboard, vocals natural, bass tight and stitched to the front"*.

On disk at that moment: `dsp_profile.json`, and nothing else. No ledger snapshot. No REW
measurement of any kind. The Critic was never called. The capture task the skill derives
(`expected_groups`) had never been issued.

**Every one of those steps passed the evidence gate.** `done` requires a non-empty evidence list,
and the model supplied a sentence for each — "baseline measurements analysed", and so on. The gate
is doing exactly what it was written to do; what it cannot do is tell a measurement name from a
description of one. Prose satisfies it, and prose is free.

This is the same defect SCR-026, SCR-030 and SCR-034 each found in their own corner: a fact is
retyped into a proof instead of being recorded as itself. Here it is load-bearing, because
`step_done`'s evidence rule is the one place the method actually enforces план-факт.

Ask:

1. Evidence items are **typed**, not free text: a REW measurement name (parseable by the glossary),
   a ledger version (`v_NNN`), a file path relative to the project, an audit-trail entry id. Prose
   may accompany them; it may not be the whole item.
2. `done` verifies what it can before writing: a named ledger version that has no file, a
   measurement name that parses as nothing, a path that does not exist — these are refusals with
   the reason, exactly as an empty list already is.
3. What cannot be verified locally (a measurement only REW knows about) stays typed anyway, so a
   front-end that *can* check it — TCC, which talks to REW — is checking a field rather than
   grepping a sentence.

The narrower alternative, if typing every item is too big a change: a single required field naming
the artefact, with the prose beside it. The point is not the shape but that something in the
record can be resolved against the world.

## SCR-036 — the target curve is chosen in conversation and never written down

**Status**: done (landed as `d0f69a0` — `enter-phase` refuses a forward move out of phase 0 with no target, phase 0 prescribes `set-target`)
**Target**: `phase_0_baseline.md` and the phase-0 gate; `rew_tool/state/process.py set-target`
**TCC dependency**: the header's "target curve" field and `state/process_view` read the machine
files. TCC renders nothing because there is nothing to render — this is not a panel bug.

**Detail**: phase 0 is *Baseline & target selection*. In a real session the Arbiter named the
target ("EPY") in the intake answers, the model repeated it back, wrote it into
`dsp_profile.draft.json` as a free-text field, and moved on. Afterwards, on disk:

```
process/process-state.json   → "targets": {}
project.json                 → no target field at all
```

`process.py` already has `set-target`, and TCC already wraps it (`core/process_writer.set_target`).
Nothing called it. The choice exists in three places that are all prose — the transcript, the
draft profile, and the model's memory — and in none that survive a `/clear`.

This is the same shape as SCR-034 and SCR-030: a decision is *made* and then not *recorded*, so
every later phase re-derives it from a conversation that may be gone. It matters more here than
in either, because the target is what every EQ move in phases 2–3 is measured against. A session
resumed after the target was chosen and not written has no way to know whether the curve it is
matching is the one the Arbiter picked.

Ask:

1. **Phase 0 cannot be left without a target.** Closing the last phase-0 step, or entering phase 1,
   refuses while `targets` is empty — the same shape as `done` refusing an empty evidence list.
2. **One machine place.** `set-target` writes it and everything else reads it. A curve named in
   `autosound_context.md` or in a profile field is a copy, and the copies drift.
3. The target record carries what it is: a bundled curve name, or a path to an imported one, plus
   the seat it was chosen for. "EPY" alone is not resolvable a month later.

## SCR-037 — intake asks about things the front-end already knows

**Status**: done (landed as `2989e46`, completed by `a925b18` + TCC `8df639e` — intake reads
`get_tcc_state` first, treats it as answered, and **closes the step** it answers instead of leaving
it `todo` forever; `get_tcc_state` now also reports `language`, the one fact it was missing)
**Target**: `references/core/project-intake.md` §1 and the phase −1 step list
**TCC dependency**: none outstanding — `get_tcc_state` now reports the reviewer the Arbiter chose
in TCC's own UI, with `decided_by` saying it is settled rather than suggested.

**Detail**: every intake so far has opened with the same two questions — which language, and how
to set up the Reviewer (Critic-Advisor) channel. Both are already decided *in the front-end*, in
controls the Arbiter used before starting the session. In the last run the model read the reviewer
out of TCC's state and then asked the Arbiter to confirm it anyway, which is the friction the GUI
exists to remove: a window that knows something and asks anyway is a chat with more buttons.

Ask: the intake's first move is to read the front-end's state (`get_tcc_state` when a `tcc` MCP
server is present) and to treat what it finds as answered. Ask only about what is missing or what
contradicts the disk. When no front-end is present the current questions stay exactly as they are
— this is an "if you are told, do not ask" rule, not a removal.

## SCR-038 — a knowledge file the skill ships takes three minutes to find

**Status**: done (landed as `5781dcd` — `knowledge/` is in the Reference Map with its naming rule, intake §4 reads the shipped checklist first)
**Target**: `SKILL.md` (the index) and `references/tooling/rew-tool-docs.md`
**TCC dependency**: none. TCC installs the skill as a symlink into the project, which is what makes
`find` behave the way it does below, and that install method is not changing.

**Detail**: the Arbiter said "Helix DSP Ultra S". The skill ships
`knowledge/dsp/helix-dsp-ultra-s.md` — a hardware-verified capability checklist that answers most
of intake §4 on its own. Getting to it took **06:07:59 → 06:10:50**:

```
find <skill>/ -iname "*ultra*" -o -iname "*helix*"     → nothing (symlink not followed)
find <skill>/ \( -iname "*ultra*" -o -iname "*helix*" \) → nothing
ls -la <skill>/..; readlink -f <skill>                  → oh, it is a symlink
find -L <skill>/ \( ... \)                              → found it
```

SCR-029 fixed *addressing* — the skill now resolves its own root and `references/...` reads work.
What is still missing is that the knowledge base is not indexed anywhere the model looks. It knew
the file might exist and had no way to name it, so it searched.

Ask: SKILL.md names the convention outright — `knowledge/dsp/<vendor>-<model>.md`, slug-cased —
and lists what is currently in it. A model that has just been told the processor should be able to
construct the path and `Read` it, with no search at all. If the index would go stale, generate it:
a one-line `ls knowledge/dsp/` in the intake reference is worth three minutes of `find`.

## SCR-039 — a channel's id is its name, so renaming one rewrites its history

**Status**: done (skill `29d29a3`, TCC `HEAD`, 2026-08-07) — a channel has an `id` that never moves
and a `code` that is what it is called today. **The id defaults to the code**, so nothing migrated
and no format broke: the two diverge only after a rename. `rename_channel` materialises the id,
sets the new code, appends the old to `previous_names` and renames the glossary entry; snapshots
and REW titles are left alone, and `Glossary.resolve_code`/`name_key` make `m-L_2 (sw)` and
`w-L_2 (sw)` one measurement. `apply.propose` resolves too, so a delta addressed to the current
name lands on the id row instead of banking a second one. TCC shows `code`, addresses `id`.
**Target**: `rew_tool/state/schema.md` + `project.py`'s `channels[]` (`code`), `naming.py`'s
glossary, and every consumer that joins the two on `code`
**TCC dependency**: `state/dsp_state.py` joins `project.json`'s `channels[]` onto the ledger row by
`code` and renders `code` as the channel's name. TCC can follow whatever the skill decides here; it
cannot decide it, because the codes are also what REW measurement titles are built from.

**Detail**: `code` is doing three jobs at once. It is the row key in the ledger, the join key
between `project.json` and a snapshot, and the label a human reads — and it is the first half of
every measurement title the project will ever have (`tw-L_1 (sw)`).

That is fine until something is renamed, which happens for ordinary reasons: `m-L` becomes `w-L`
after the install is corrected, a "rear" pair turns out to be a centre, a project adopts clearer
codes halfway through. Renaming today means either rewriting every historical snapshot (losing the
guarantee that a snapshot is immutable) or leaving the history keyed by a name nobody uses. Both
have been done by hand in this repo's own dogfood data.

The measurement titles make it worse: they are typed into REW by a human and cannot be rewritten
retroactively at all. A renamed channel silently orphans every capture it ever had.

Ask:

1. A channel has a **stable id** that is never displayed and never changes once written, and a
   **name** (the current `code`) that is what people and REW titles use. The ledger and the
   glossary key on the id; the name is an attribute of the identity record.
2. Renaming is then an ordinary edit to one field in `project.json`, with the old name kept as a
   `previous_names` entry — which is exactly what a consumer needs to keep matching old captures
   to the channel they belong to.
3. Migration writes ids equal to today's codes, so nothing changes for an existing project until
   somebody actually renames something.

The cost is real: two keys where there is one, in a schema that has just been through a 3.0 break.
Worth raising now rather than after the next rename, but not worth a fourth format break on its
own — it should ride along with whatever the next one is.

**How it landed without one** (2026-08-07): the id is resolved, not stored — `channel_id(row)`
returns `row["id"] or row["code"]`, so every existing project already has ids and no file was
touched. `id`/`previous_names` are written by the first rename and by nothing else. What point 1
above called "never displayed" is exactly what happened: TCC renders `code`, and `id` only ever
appears as a ledger row key, where it reads as the name anyway until somebody renames something.

## SCR-040 — verification is a deterministic phase TCC runs, and "done" means "verified"

**Status**: accepted (user decision 2026-08-07; supersedes the "TCC consumes `verify.py`" follow-up
left open by SCR-013)
**Target**: `rew_tool/state/process.py` (the capture round: bind it to a plan step, record a
verdict per capture) + `rew_tool/verify.py` (already the math) + the `finish_step` gate
**TCC dependency**: TCC runs the phase — it is the party that can talk to REW, hold a loop, and
put a retake in front of the Arbiter. It writes nothing itself (D-6): the skill's writer records
the verdict, exactly as it records the round and the journal.

**Detail**: checking a curve needs no model. Does REW hold it; is it in the band asked for; is the
level a signal rather than silence or a loopback; is a THD spike real or a null artifact — all of
it is arithmetic, and the skill already owns that arithmetic (`analysis.py`, `rew_api.py`,
`eq_gate.py`, `verify.py`). A model reading FR arrays to answer it burns tokens on a job an `if`
does better, and can report a verdict it did not compute.

The panel today says "taken" when a title with the right name exists. A sweep that never finished,
a muted channel, a mic in the wrong input — all read as captured, and the analysis that follows is
computed on them.

Decided:

1. **No separate "verify curves" step.** The plan step IS the ask ("capture the baseline solo");
   verification is what makes it *done*. A step bound to a capture round cannot close while any
   expected capture is missing or unusable — the same shape as SCR-035's evidence gate and
   SCR-036's target gate: the refusal belongs to the record, not to the model's judgement.
2. **The round binds to the step** (`capture-start … --step <id>`), so the front-end can go from a
   step to the captures that satisfy it and back, and so a retake is visibly attempt N of that
   step rather than a loose measurement.
3. **A verdict is pinned to REW's `uuid`**, not to the title. REW gives every measurement a stable
   `uuid` (`9ff4deb9-…`) while its ordinal id is explicitly unstable. Without the pin, "verified"
   outlives the graph it verified: re-take `sw_1 (sw)`, same name, different data, status still
   green.
4. **The retake is proposed, not automatic.** A sweep is a physical act in a car with a person and
   drivers in it, not a write to a file. TCC surfaces "unusable: silence in band — re-take?" and
   one click runs it; an automatic loop lives behind an explicit per-project toggle, default off.
5. **No TCC, no change.** `verify.py` stays the skill's own CLI, and a session with no status file
   verifies as it does today. The statuses are an accelerator, never a prerequisite.

Ask: `capture-check` on the process writer — run the skill's own verdict over the open round's
expected titles, record `{ok, uuid, at, issues}` per capture, append a `capture_verified` event;
`capture-start --step <id>`; and `finish_step` refusing a step whose bound round is not clean.

## SCR-041 — the README and FAQ must name the pair that is actually supported

**Status**: done (skill `70c27ca`, 2026-08-07) — a named subsection heads "Recommended Models,
Modes & My Take" in all four READMEs, dated in the heading itself, stating Generator = Claude Opus
at `xhigh` and Reviewer = Gemini Pro (High), followed by the paragraph that the rest is the reader's
own experiment and the documented phases-−1..3-in-one-sitting failure. Explicitly not a requirement:
the free/clipboard/web-chat paths are named and linked in the same breath. Mode A in the options
table now IS that pair rather than a competing row, and the two "my experience" bullets that used to
undercut it (Sonnet's token thrift, Fable as an unqualified best) were reconciled instead of deleted.
FAQ gets its own dated section placed immediately *before* the cost options, since that is where the
downgrade is actually chosen, plus cross-links from Options 1 and 2. Also fixed a pre-existing dead
link to the removed `audit-fable-2026-07-11.md` in all four READMEs.
**Target**: the skill's `README.md` (and its translations) + `FAQ.md`
**TCC dependency**: none — TCC already marks the same pair in its picker
(`model_choices.RECOMMENDED_GENERATOR` / `RECOMMENDED_CRITIC_MARKERS`) and now runs it at a stated
effort. This ask is that the skill's own front door say the same thing, for the reader who never
opens TCC.

**Detail**: the skill is usable with any model the reader has, and the docs currently read that
way. That is true and, on its own, misleading: the method has been driven end to end with exactly
one combination, and the failure mode of the others is not an error message — it is a plausible,
confident, wrong tune. The documented case is a cheap model that closed phases −1..3 in one
sitting and reported crossovers, delays to 0.1 ms, EQ "within ±0.5 dB" and a listening verdict
about a car nobody had sat in.

State, as of **August 2026**:

- **Generator: Claude Opus, at `xhigh` effort.**
- **Reviewer/Advisor: Gemini Pro (High).** In `agy` the effort tier IS the model name, so `(High)`
  is the whole instruction; `(Low)` is a different reviewer.
- **Everything else is at the reader's own risk** — a different model, a different vendor, or the
  same model at a lower effort. Say it plainly rather than as a preference: a downgrade does not
  announce itself, it agrees with you.

Two things the wording has to avoid: pretending the skill only works with that pair (it does not
depend on it, and the free/clipboard paths are deliberate), and burying the recommendation in a
table of options where it reads as one row among many. It is the supported configuration; the rest
is experiment.

**Also date it.** "As of August 2026" is part of the claim — the pair is a snapshot of what has
been driven, and an undated recommendation is the thing that goes stale silently
(the same reasoning as `SDK_MODELS_VERIFIED`).

## SCR-042 — a spare slot does not say which tier it belongs to

**Status**: done (skill `bbab835`, TCC needed no change, 2026-08-07 — "there are no OFF channels
in the lists").
Both fields shipped, and verified end to end against TCC's already-built half: a fixture with
`off-out-A`/`off-out-L` on `tier: "channels"` and `off-virt-F`/`off-virt-H` on
`tier: "virtual_channels"` renders slot `F` into the virtual tier and the spare outputs into the
output tier, reading `3/12` and `3/8`; stripping both fields reproduces today's render exactly.
The trap worth knowing: `tier` is the **ledger** key, so physical outputs are `channels`, never the
profile's group id `physical_outputs` — `dsp_profile.ledger_tier()` is now the single home for that
conversion (`contract.py` was duplicating it inline), `project.validate()` refuses the group-id
spelling by name, and `contract.py` flags a `tier` no profile group declares, because a spare slot
has no ledger row to contradict a typo. `max_count` validates as a positive int or null and stays
null-until-confirmed, so `open_questions()` surfaces it. Intake §4's checklist and
`knowledge/dsp/helix-dsp-ultra-s.md` now carry the slot-count question and its Helix answer
(outputs 12/A–L, virtual 8/A–H — user-confirmed 2026-08-07).
**Target**: `project.py`'s `channels[]` (a `tier` field), and `dsp_profile.json`'s groups
(`max_count`)
**TCC dependency**: `state/dsp_state.py` `ProjectView.from_dict` now joins identity-only channels
into their tier and renders them as spare rows — **already built, and inert until this lands**:
it places a channel only when the entry names its tier, and skips it otherwise rather than
guessing. `main_window._add_channel_switches` is the panel that shows them.

**Detail**: rows are built from the ledger, and a slot with nothing wired to it has no ledger row —
there is no tuning state to record for it. `project.json` *does* carry those slots, correctly
marked (a real project: `off-out-A`, `off-out-L`, `off-virt-F`, `off-virt-H`, each `hidden: true`,
`role: "unused"`). What no entry says is which tier it is a spare slot OF, and that cannot be
inferred: **slot letters repeat across tiers.** On this Helix the virtual tier uses A–H and the
outputs use B–K, so `slot: "F"` is a legal address in both. Guessing would put a spare output among
the virtual channels — a wrong row in the one panel whose job is showing the rig as it is.

Ask:

1. **`tier` on each `channels[]` entry** — the ledger tier key the channel belongs to (`channels`,
   `virtual_channels`, `inputs`, whatever that DSP's profile declares). Cheap for the entries that
   have a ledger row (it is the key they already sit under) and load-bearing for the ones that do
   not. `role: "virtual"` is not a substitute: an unused virtual slot is written `role: "unused"`,
   which is what loses the tier in the first place.
2. **`max_count` per group in `dsp_profile.json`** — how many slots that tier physically has. The
   real profile leaves it null, so the panel can only count what it was given: a Helix Ultra S
   reads `PHYSICAL OUTPUTS 10/10` when it is a 12-output processor with two slots spare. With the
   count declared it reads 10/12, and the two spares are visible as spares whether or not (1) has
   landed.

Neither is retroactive: a project without them renders exactly as it does today.

## SCR-043 — the field vocabulary is closed, so something must close it

**Status**: done (skill `1b8a343`, 2026-08-11 — `_validate_group` enforces `FIELD_VOCABULARY`,
`FIELD_NEAR_MISSES` names the wanted spelling, three selftest fixtures corrected)
**Target**: `skills/autosound-tuning/rew_tool/dsp_profile.py`
**TCC dependency**: none new. `state/dsp_state.py::_field_label` is the consumer this protects —
it renders exactly the vocabulary's tokens and falls through to a raw `"<token>: <value>"` for
anything else, which is invisible in practice because an unknown token also never carries a value.

**Detail**: not an ask from TCC, but from the 2026-08-07 architecture review (`ARCHITECTURE-NOTES.md`
§1, hole 1) — the cheapest useful item on that list, done first for that reason.

`FIELD_VOCABULARY` had declared itself "the ONLY field-name tokens a group's `fields` may contain"
since SCR-010 and was referenced in exactly one place: the `checklist` printout. `_validate_group`
never compared anything to it. So a group declaring `delay_ms` instead of `ta_ms` validated clean,
saved clean, and rendered as nothing in every consumer — the same silent-wrong class as SCR-042,
with no error anywhere on the path.

The fix is the SCR-042 lever, not a documentation lever: an unknown token is a hard refusal, and
the message names the token that was wanted (`FIELD_NEAR_MISSES` for the synonyms `difflib` cannot
reach — `delay`, `time_alignment`, `level_db`, `invert`, `crossover` — difflib for the typos). A
non-string token is refused too: that is `maybe_decode_json`'s tool-call round-trip failure
arriving one level deeper.

Nothing on disk changed meaning: the bundled Helix profile, the live project's profile and both TCC
fixtures already used `ta_ms`. The only `delay_ms` declarations anywhere were three fixtures inside
the module's own selftest, which is how it had gone unnoticed for so long.

## SCR-044 — the flaw map is a phase-0 deliverable, so leaving phase 0 should ask for it

**Status**: done (skill `39fbd19`, 2026-08-11 — `enter-phase` refuses to leave phase 0 while
`acoustics.flaws[]` is empty; `process.py` gained the selftest it never had)
**Target**: `skills/autosound-tuning/rew_tool/state/process.py`,
`references/phases/phase_0_baseline.md`
**TCC dependency**: none new. `state/acoustics_view.py` + the "Car audio analysis" section have
rendered this since SCR-015 and were correct to show nothing — there was nothing.

**Detail**: found on the live `testTCC-5` run, 2026-08-11. The step *"Acoustic flaw map:
distortion floor + raw pair coherence"* was closed `done`; `project.json` had no `acoustics` key at
all; and the actual findings were in the journal as a `user_decision`:

> «Are the w-L 160 Hz and w-R 250-315 Hz anomalies mechanical faults or acoustic nulls? — Both are
> acoustic nulls, settled by absolute harmonic SPL, not the THD ratio…»

So the work was done and the knowledge stayed prose. SCR-015 had built both ends — the writer with
its closed `action` list and the panel — and left the middle to good intentions. Phase 2 equalises
against this map: which features may be cut, which must be left, which are not EQ problems at all.

The lever is the one that keeps working (SCR-042, SCR-043): refuse, and name the command. The gate
sits beside the target-curve one in `enter_phase` and follows the same rules — forward moves only,
re-entry and going back always allowed, and an unreadable `project.json` is `contract.py`'s
complaint rather than this gate's, so a half-built project is not blocked by it.

Two judgement calls worth keeping:

1. **Non-empty, not merely present.** `project.py`'s own template seeds `"acoustics": {"flaws": []}`,
   so requiring the key would have passed trivially on every new project.
2. **The escape is itself a record.** A car with nothing to correct still has features; the answer
   is an entry with `action=leave`, which is exactly why that value is in the closed list. "Nothing
   to record" and "nobody recorded anything" must not look the same.

Found on the way: **`process.py` was the only one of the seven modules with no selftest**, so the
module holding the most gates (evidence must exist and resolve — SCR-035; a round's captures must
be usable — SCR-040; the target curve — SCR-036) had none of them exercised since they were
written. It has one now.

## SCR-045 — an open question that is never asked again was never open

**Status**: done (skill `a71cf5a`, 2026-08-11 — `missing_facts()` in `dsp_profile.py`, and
`enter-phase` refuses a phase whose facts are not on record)
**Target**: `rew_tool/dsp_profile.py`, `rew_tool/state/process.py`,
`references/phases/phase_1_foundation.md`, `references/phases/phase_2_eq.md`
**TCC dependency**: none new — but the Diagnostics dialog's "Open questions (intake unfinished)"
list gets truthful the moment the pin is bumped, because `contract.py` renders whatever
`open_questions()` returns.

**Detail**: the second half of the decision in `ARCHITECTURE-NOTES.md` §4 — *learning instead of
softer gates*. That decision rested on a measurement: `open_questions` is deliberately not part of
`contract.py`'s `ok`, so the phase −1 gate has always wanted a **valid** profile rather than a
**complete** one, and a DSP nobody knows everything about can already start. The missing piece was
that an unanswered question never came back.

Checking that on the live project turned up something worse first. `testTCC-5`'s Helix profile:

```json
{"dsp_profile": {"name": "Helix DSP Ultra S", "vendor": "Audiotec-Fischer",
                 "groups": [...], "_open_questions": []}}
```

No `sample_rate_hz`. No `max_count`. No `parametric_eq`, no `crossover_filters`, no per-group `eq`.
And `open-questions` returned **`[]`** — because `open_questions()` walks *nulls*, and every one of
those keys was **absent**. "Unconfirmed facts are `null`, not omitted" was an invariant in the
module docstring that nothing enforced, so a question the interview never reached left nothing
behind to find. Third instance of the same class after SCR-042 and SCR-043.

`missing_facts()` fixes it without a new list to keep in sync: **what a profile must describe is
derived from what it declares.** A group's `fields` says which capabilities the DSP has, and each
capability has a block explaining how it behaves — `ta_ms` → `delay`, `phase_deg` →
`phase_control`, `eq` → `parametric_eq`, `hp`/`lp` → that group's `crossover_filters`. Plus two
unconditional ones: `sample_rate_hz`, and `max_count` per group (SCR-042). A tier that declares no
crossover legs is not missing a crossover description. This only works because `FIELD_VOCABULARY`
is now enforced (SCR-043) — deriving from a field list nobody checks would inherit its typos.

Then the return: `enter-phase` refuses a phase whose arithmetic needs a fact nobody recorded —
phase 1 (`sample_rate_hz`, `delay`, `crossover_filters`), phase 2 (`parametric_eq`, `eq`).
**Phase-scoped, not step-scoped**, for the same reason `_CAPTURE_PLAN` is: a phase's needs belong
to the method and are identical on every car, while a step's name is written per project. Same
rules as the other two gates in `enter_phase` — forward moves only, re-entry and going back free,
an unreadable profile is `contract.py`'s complaint.

The one that actually hurts is `sample_rate_hz`: phase 1 converts every delay to samples, so a
rate nobody wrote down is a rate the next session assumes. On this project the real answer is
96 kHz; at an assumed 48 kHz every sample count would have been half of what the DSP needed.

## SCR-046 — an unreadable `project.json` is not an empty one

**Status**: done (skill `94eaa62`, 2026-08-12 — `Project.load()` refuses a file it cannot read;
`contract.py` reports it as a row instead of crashing)
**Target**: `skills/autosound-tuning/rew_tool/project.py`, `rew_tool/contract.py`
**TCC dependency**: none — TCC reads `project.json` with plain `json.loads` in
`state/project_view.py`, so it never went through this path.

**Detail**: found by the 2026-08-12 audit and reproduced before fixing. `load()` answered the same
thing for two different questions:

```python
except (OSError, ValueError):
    return _empty_project()
```

"This project has no facts yet" and "this file exists and will not parse" are not the same state,
and every mutator in the module is load-modify-save. So one `set_channel` against a half-written
or badly merged file wrote the skeleton over it: the whole project replaced, `project_rev` back to
1, no error anywhere. Verified — the reproduction is now a selftest case.

**What did not help, and is worth being precise about: the atomic write.** temp-then-rename
guarantees nobody ever reads a half-written file, and it delivered exactly that here — the
replacement was atomic and complete. Atomicity protects the SHAPE of a write. It has nothing to
say about its meaning.

Two judgement calls:

1. **A missing file still reads as a skeleton**, because that is true, and a brand-new folder must
   not be an error. The distinction is `os.path.isfile`, checked before the parse rather than
   inferred from the exception — `FileNotFoundError` is not the only way to fail to read a file.
2. **`contract.py` catches and reports** rather than propagating. Diagnostics exists to say what is
   wrong with a project; a checker that dies on the worst case is a checker that is absent exactly
   when it is needed.

## SCR-047 — three gates that did not hold what they claimed

**Status**: done (skill `bb20bfc`, 2026-08-12)
**Target**: `rew_tool/dsp_profile.py`, `rew_tool/state/process.py`, `rew_tool/contract.py`,
`references/phases/phase_-1_intake.md`
**TCC dependency**: none. TCC reads `contract.py check`'s JSON and now gets two extra keys
(`complete`, `missing`) it may render later; nothing it already reads changed shape.

**Detail**: all three came out of the 2026-08-12 audit, and all three were in gates written or
leaned on within the previous 48 hours. Worth recording together for that reason — the pattern is
not "old code rots", it is "a gate is easy to build one assertion short".

1. **`sample_rate_hz` was checked for presence, not for being a rate.** SCR-045 refuses phase 1
   without it, because every delay in samples comes from it. `"96 kHz-ish"` satisfied that gate on
   the night it shipped. Now: a number, in hertz, drawn from a list of rates DSPs actually run at.
   `96` is refused as loudly as a sentence — kHz-for-Hz is the same defect in another costume — and
   an unlisted rate must be added in the same commit as the profile that needs it, so it gets a
   second reader instead of a silent pass.

2. **The phase-0 refusal named `set-target`; the CLI has `target`.** A refusal that instructs an
   invalid command costs more than the one gate: it teaches the reader that refusals are noise.

3. **`contract.py check` called an EMPTY project OK, and phase −1 named it as its verifier.** The
   verdict was right and the usage was wrong — two questions sharing one word:

   * `ok` — is anything here WRONG. A fresh folder passes, and should: intake has not run.
   * `complete` — does everything the method needs EXIST. That is the gate's question, and it is
     new.

   `--gate` exits on `complete`, the report lists what is owed, and the phase −1 doc names the flag
   and says why plain `check` is not it. The missing ledger needed separate detection:
   `check_ledgers` emits one row per preset directory, so a project with no `state/` emits none —
   absence of the row IS the missing ledger, which no name-based check can see.

## SCR-048 — the last five from the audit

**Status**: done (skill `1101c71`, 2026-08-12 — each pinned by a selftest case that reproduces it)
**Target**: `rew_tool/state/state.py`, `rew_tool/project.py`, `rew_tool/state/process.py`,
`scripts/.critic-env.example`, `SKILL.md`
**TCC dependency**: none new. TCC benefits from all five as a reader; nothing it calls changed
shape.

**Detail**: the remainder of the 2026-08-12 audit, closed together.

1. **One stray value hid a whole tier.** `tier_names` required a dict OF DICTS, so a single
   `"comment": "temp note"` sitting beside the rows demoted `virtual_channels` to unknown
   metadata — and `validate` never looks at unknown top-level keys. The snapshot validated, banked,
   and then disappeared from `validate`, `diff_states` and `render` simultaneously: the
   split-artifact failure `state/schema.md` names as the reason its invariants exist. A dict at top
   level IS a tier now, and a bad row is `validate`'s problem.
2. **`acoustics.flaws[]` was validated only by `add_flaw`.** Any other route to disk banked
   anything. `validate` runs the same checker, so the rule belongs to the file rather than to one
   function.
3. **A plan step could name a phase outside the skeleton.** Written, counted by nothing, displayed
   nowhere.
4. **`scripts/.critic-env.example` had Critic and Advisor swapped.** Copying the skill's own
   template configured the rubber-stamp Flash reviewer that `setup-critic-channel.md` warns about
   two lines below its own table. Latent — it had not fired on the live project, which has no
   `.critic-env` — but loaded.
5. **SKILL.md contradicted itself on where the active phase lives**, twenty-three lines apart.

The pattern across SCR-043…048 is worth keeping in one sentence: **every one of them was a rule
that existed and was not checked.** Not missing rules — unenforced ones. That is the class an audit
finds cheaply and a reader never does, because the rule reads as true.

## SCR-049 — the project backup is a promise nobody wrote down

**Status**: proposed (2026-08-13 — user chose to build it rather than soften the claim)
**Target**: skill — a documented backup step (where it belongs in the phase order is part of the
ask); `install.sh` in the skill repo, for the question and the CLI it needs
**TCC dependency**: none required. TCC already reads git state for the project panel
(`state/project_view.py:259`) and would show the result for free.

**Detail**: the installer's closing advice says "the skill offers to keep it in a private
repository when you start one". Grepped both repositories on 2026-08-13: there is no `git init`,
no `git remote`, no `gh repo create` anywhere in the skill or in TCC. TCC only READS git state to
display a branch and a dirty count.

The claim is not false, and that is the part worth being precise about: **the skill can do it
today because the AI can run the commands.** What does not exist is anything written down — no
step, no phase, no script, no check. So it happens when the model thinks of it and not otherwise,
which for the artefact the whole method produces (the ledger, the journal, the config backups,
weeks of decisions) is the wrong reliability.

What the ask covers:

1. **A written backup step in the skill** — when it is offered, what goes in, what stays out. The
   sweeps stay on disk; the record is what is worth keeping. Private by default, and never
   automatic: pushing somebody's car, DSP and measurements to a cloud is an outward-facing action
   and needs their word, once, explicitly.
2. **The installer asks up front** rather than advising at the end: "keep the project's record in
   a free private GitHub repository?" — and if yes, `brew install gh`, which turns account
   creation, login and repo creation into `gh auth login` + one command. Asking early matters
   because the answer decides whether anything is installed at all.
3. **The closing advice becomes a how-to** with the actual commands, for the person who said no
   at install time and changed their mind — or who wants to do it by hand.

Until this lands, the installer's line should not claim the skill "offers" anything.
