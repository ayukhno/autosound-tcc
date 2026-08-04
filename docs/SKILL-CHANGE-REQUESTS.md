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

## SCR-026 — `apply.propose` emits the change delta, not only the snapshot

**Status**: proposed (raised 2026-08-04 while building `spike/render_dialog.py`)
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

**Status**: proposed (raised 2026-08-04, same spike)
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

**Status**: proposed (found in the Claude run with TCC's MCP server up, 2026-08-04)
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

**Status**: proposed (found in the SCR-028/029 verification re-run, 2026-08-04)
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

**Status**: proposed (found while cleaning the submodule after the recorder work, 2026-08-04)
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
