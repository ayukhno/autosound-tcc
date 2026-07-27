# Skill change requests

Asks for the `autosound-tuning-skill` submodule (`vendor/autosound-tuning-skill/`) that TCC depends on
but does not own. TCC's own code never edits the submodule directly — these are tracked here and
processed in a batched skill-side session.

Status values: `proposed` (not yet actioned) · `accepted` (skill maintainers/self have agreed to do it)
· `done` (landed in the submodule and the pin bumped).

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
