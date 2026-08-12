# Audit: declared and not enforced (2026-08-12)

> **Verification pass (Opus, same night).** This report is a Fable-5 audit; nothing in it was taken
> on trust. Seven of the nine findings were re-run independently against the real validators —
> loading the actual modules by path and executing them on hand-built files — and **all seven
> reproduced exactly as described**:
>
> | # | claim | independently reproduced |
> |---|---|---|
> | 1 | one non-dict value demotes a whole tier | ✅ `validate()` passes, `tier_names()` returns `['channels']` only |
> | 2 | a dip marked `notch`, no `why`, no `evidence`, survives `save()` | ✅ `save()` accepts it; `validate_flaw` refuses the same dict |
> | 3 | `project_rev` stamped, compared nowhere | ✅ no reader in either repo compares it; TCC's comment at `state/dsp_state.py:469` still says SCR-024 has not landed, while the stamp has been written since |
> | 4 | `schema_version: 99` reports valid; `registry.json` has no check row | ✅ `check_project` returns `valid=True, issues=none`, and no registry row exists |
> | 5 | a corrupt `project.json` reads as an empty skeleton | ✅ and one `set_channel` afterwards **replaced the whole project**, rev back to 1 |
> | 6 | a plan step in phase `"6"` is accepted | ✅ accepted; `PHASES` is `-1..5` |
> | 7 | `sample_rate_hz: "96 kHz-ish"` passes | ✅ passes `validate_profile`, and `missing_facts` does not report it — so the SCR-045 gate built for exactly this incident lets it through |
>
> Findings 8 and 9 were not re-run; treat them as the audit states them until they are.
>
> **Worst of the nine is #5, and it is not a validation gap — it is data loss.** A `project.json`
> that fails to parse (a half-written file, a bad merge) reads as an empty skeleton, and the next
> write persists that skeleton over the real one. Nothing to decide about severity there; the only
> question is the fix.

Nine new instances of the defect class were found and verified by executing the actual validators
against hand-built files: in every case below the quoted rule is stated in a schema document,
docstring or constant, the shown JSON passes every check on its path to disk, and the wrong value
then does something silent downstream. The two known-open items (ledger-row fields vs. profile
fields; no compare-and-swap on `project_rev`) are both CONFIRMED, with line references, in their own
section and are not counted among the nine.

All paths below are relative to
`vendor/autosound-tuning-skill/skills/autosound-tuning/` (skill) and
`src/autosound_tcc/` (TCC). Every "passes" claim was run, not inferred.

---

## 1. One malformed row makes a whole tier invisible to validate, diff AND render

**Rule stated:** `rew_tool/state/schema.md:89-90` — "a tier is any top-level key holding a dict of
row-dicts"; `schema.md:135-137` (Invariants) — "**Every tier is covered** —
`validate`/`diff_states`/`render` all walk `tier_names(state)` … A virtual-tier change used to be
invisible to all three; that was the split-artifact bug this file exists to prevent."

**Where it should be enforced:** `rew_tool/state/state.py:102-113` (`tier_names`) /
`state.py:300-337` (`validate`). `tier_names` requires `all(isinstance(row, dict) …)`, so a single
non-dict value demotes the whole key from "tier" to "unknown metadata" — and `validate` never looks
at unknown top-level keys, so nothing refuses the shape.

**Concrete bad file that passes** (`state/<preset>/v_00N.json`; also passes `snapshot()`):

```json
{
  "preset": "SQ", "sample_rate": 96000, "project_rev": 1, "schema_version": 3,
  "channels": { "w-L": {"hp": {"f": 70}, "lp": {"f": 270}, "gain_db": -7.8,
                 "ta_ms": 5.38, "polarity": "NORM"} },
  "virtual_channels": {
    "VFL": {"gain_db": 0.0, "ta_ms": 0.0, "polarity": "NORM"},
    "comment": "temp note"
  }
}
```

Verified: `validate()` passes; `tier_names()` returns `['channels']` only; a subsequent VFL gain
change produces a diff with **no** `virtual_channels` key; `render_state()` emits no
`virtual_channels` section; `apply.propose({"virtual_channels": …})` would no longer read the delta
as tier-keyed. TCC is unaffected only because it walks the profile's groups instead — so the two
readers now disagree about whether the tier exists.

**Symptom:** the exact split-artifact failure the module exists to kill, re-armed by one stray key:
virtual-tier rows keep being banked and silently vanish from every diff, sheet and advisory. No
error anywhere, ever.

---

## 2. `acoustics.flaws[]` is only validated by `add_flaw` — `validate()`/`save()` bank anything

**Rule stated:** `rew_tool/project-schema.md:118-123` — "Both lists are closed … **`level_db < 0`
with `action: "notch"` is refused** — … That refusal is the map's whole reason for existing in code
rather than in a paragraph." The refusal exists (`rew_tool/project.py:222-265`, `validate_flaw`)
but is called only from `add_flaw` (`project.py:458`).

**Where it should be enforced:** `rew_tool/project.py:129-207` (`validate`) — it checks channels,
tiers, glossary type, and never touches `acoustics`. Every other write path (`set_channel`,
`set_hardware_control`, `rename_channel`, any load-modify-`save()`) re-validates and re-writes the
whole file, flaws included, without ever checking them.

**Concrete bad file that passes** (verified: `Project.save()` accepted it):

```json
{ "schema_version": 3, "project_rev": 4,
  "acoustics": { "flaws": [
    {"f_hz": 250, "level_db": -12, "kind": "cabin_null", "action": "notch",
     "channels": ["w-R"]}
  ]}}
```

No `why`, no `evidence`, a dip marked notchable — three separate `validate_flaw` refusals, all
bypassed. (A model editing `project.json` directly, a merge, or any tool that goes through
`save()` instead of `add_flaw` produces exactly this.)

**Symptom:** TCC's `state/acoustics_view.py:27-34` colours `notch` as `"done"` ("correctable, and
the map says so"), so the panel presents *EQ-boost-this-null bait as a recorded verdict* — the
precise mistake the map exists to prevent. `process.py:158-180`'s SCR-044 gate counts any
non-empty list as a map, so the bad entry also opens phase 1. Nothing raises anywhere.

---

## 3. `project_rev` stale-join detection is declared on both sides and performed on neither

**Rule stated:** `rew_tool/state/schema.md:20-22` — "**Every snapshot stamps `project_rev`**
(SCR-024) — the revision of `project.json` in force when the values were banked, **so joining an
old snapshot to today's facts is detectable instead of silently relabelling history** when a driver
is replaced." Same claim at `rew_tool/state/state.py:34-36` and `rew_tool/project.py:114-116`.

**Where it should be enforced:** any reader that performs the join — `rew_tool/state/state.py:455-462`
(`PresetHistory.render`, joins today's `project_channels` onto any historical version),
`rew_tool/contract.py:274-296` (`check_project` has no rev cross-check), and TCC
`state/dsp_state.py:452-475` (`load_project_view`). The TCC comment at `dsp_state.py:469-472` still
reads "Fixing that needs the snapshot to say which project revision it was taken under (SCR-024,
raised for exactly this)" — SCR-024 landed, the stamp is written and shape-validated
(`state.py:321-325`), and **no code anywhere reads the stamp back to compare it with the current
`project.json` rev** (verified by grep across both repos: writers and selftests only).

**Concrete bad pair that passes:** `project.json` at `project_rev: 9` after a driver swap
(`channels[]` now says `"driver": {"make": "Scan-Speak"}`), plus a historical snapshot:

```json
{ "preset": "SQ", "version": "v_003", "project_rev": 3, "sample_rate": 96000,
  "schema_version": 3, "channels": { "w-L": { "hp": {"f": 70}, "lp": {"f": 270},
  "gain_db": -7.8, "ta_ms": 5.38, "polarity": "NORM" } } }
```

Both files are individually valid; every reader renders `v_003` with the Scan-Speak identity.

**Symptom:** exactly the "silently relabelling history" the field was added to make detectable —
old snapshots, settings sheets and TCC channel rows all report post-swap identity for pre-swap
values, with the detection data present in the file and ignored.

---

## 4. `contract.py`'s CONTRACT expected-version column is decorative, and `registry.json` is never checked at all

**Rule stated:** `rew_tool/contract.py:41-58` — the `CONTRACT` table pairs each file with an
"expected schema_version" and the header comment promises "`contract.py` can reject a whole tree in
one comparison" (`project.py:38-42`; also `contract.py:44-46` "one comparison rather than a
matrix"). Row `contract.py:57` lists `state/registry.json` as a contract file.

**Where it should be enforced:** `contract.py:274-296` (`check_project`). The 4th tuple element of
`CONTRACT` is read **only** by the `table` CLI printer (`contract.py:346-347`). `check_dsp_profile`
(`:106-122`) reports whatever `schema_version` it finds without comparing it to `FORMAT_VERSION`;
`check_ledgers` (`:158-191`) likewise (and `state.validate` at `state.py:313-316` only requires
"int if present"). No `check_registry` function exists; `check_project` never mentions the file.

**Concrete bad files that pass** (verified: report `ok: true`, registry absent from `files`):

```json
// dsp_profile.json
{ "schema_version": 99, "dsp_profile": { "name": "X", "vendor": "Y", "groups": [
  {"id": "physical_outputs", "label": "Out", "fields": ["hp","lp","gain_db","ta_ms","polarity"]}]}}
```
```json
// state/registry.json — active slot points at a preset with no history
{ "active": "Ghost", "slots": {} }
```

Report: `('dsp_profile.json', 99, valid=True)`, overall `ok=True`; the registry — the anti-
cross-slot-anchoring pointer of issue #5 — appears nowhere in the diagnostics TCC's
`core/contract_check.py` renders.

**Symptom:** the one command whose job is "which format is this project in, and is it consistent"
answers "fine" for a wrong-format file, and a broken/stale active-slot pointer (which will make
`apply.propose` refuse every change, or stamp the wrong slot) is invisible to the diagnostics panel
built for exactly this.

---

## 5. `Project.load()` never validates: 2.x and corrupt files read silently, and one write then destroys the project

**Rule stated:** `rew_tool/project.py:41-42` — "2.x files are read by `state/migrate.py`, not by
this"; `project.py:138-143` — unsupported `schema_version` is a `ProjectError`;
`project.py:311-312` — "a brand-new project folder reads as 'nothing known', not an error" (said of
a *missing* file).

**Where it should be enforced:** `rew_tool/project.py:310-320` (`load`) — it catches
`(OSError, ValueError)` into an empty skeleton and never calls `validate`, so the schema_version
refusal only ever fires on the *write* path (`save`, `:334`).

**Concrete bad files that pass:**

```json
{ "schema_version": 2, "project_rev": 5, "channels": [{"code": "w-L", "slot": "C"}] }
```
Verified: `load()` returns it unvalidated (v2 read by the very module that says it never reads v2);
`check_project_json` in contract.py then reports it invalid, but every direct consumer
(`open-questions`, `resolve_channel`, `project_channels`, TCC's `project_view._load`) consumes it.

Worse, a torn/corrupt file — `{"schema_version": 3, "project_rev": 9, "channels": [{"code":` —
loads as the **empty skeleton at rev 0**, and the next `set_channel()` (verified) writes a fresh
skeleton containing only that one channel: the project's entire fact base — car, amps, glossary,
flaw map — replaced without any error, `project_rev` restarted at 1 so even the rev no longer says
anything moved backwards.

**Symptom:** a half-written or hand-mangled `project.json` reads as "brand-new project"; the first
routine write after that silently discards every recorded fact. (The atomic-write discipline
protects against the skill's own torn writes, but not against any other producer, merge conflict or
disk fault — and `load()` is the only line of defence, and it defends nothing.)

---

## 6. A plan step's `phase` is never checked against `PHASES` — the step vanishes from every plan view

**Rule stated:** `rew_tool/state/process.py:48-50` — "The method's fixed skeleton … Phases are the
skill's, not the project's"; `PHASES = ("-1", "0", …, "5")`; `rew_tool/state/process-schema.md:38`
documents `"phase": "2"` on a step.

**Where it should be enforced:** `rew_tool/state/process.py:370-393` (`validate` checks only
`active_phase` against `PHASES`, `:379-380`) and `process.py:489-507` (`add_step` stores any
`phase=` argument uninspected; with no active phase it stores `null`).

**Concrete bad file that passes** (verified: `validate()` clean; also produced live via
`add_step("x1", …, phase="6")`):

```json
{ "schema_version": 3, "active_phase": "0",
  "phases": {"0": {"status": "cur", "title": "Baseline & target selection"}},
  "plan": [
    {"id": "x1", "name": "orphan", "status": "done", "phase": "6", "evidence": ["v_001"]},
    {"id": "x2", "name": "no-phase", "status": "todo", "phase": null}
  ], "targets": {} }
```

**Symptom:** verified — TCC's `state/process_view.py:207-229` (`to_plan`) buckets steps by phase
and iterates `process.PHASES`, so both steps render in **no** phase of the plan panel; the skill's
own `plan_for()` (`process.py:882-886`) equally never returns them for any real phase. A done step
that exists, counts for `done_step_ids`, and is displayed nowhere is a plan that quietly rewrites
itself — the failure mode the module's docstring promises is impossible.

---

## 7. `sample_rate_hz` (and every capability block) is unvalidated — junk satisfies the SCR-045 phase gate

**Rule stated:** `rew_tool/dsp_profile.py:413-416` (`_FACTS_ALWAYS`) — "the DSP's native rate —
every delay in samples is computed from it, so **a wrong or missing rate makes every alignment
number wrong**"; `process.py:216-222` — "Refuse to enter a phase whose arithmetic needs a fact the
profile has never recorded. The one that hurts is `sample_rate_hz`."

**Where it should be enforced:** `rew_tool/dsp_profile.py:101-120` (`validate_profile` checks
name/vendor/groups/fields/max_count and nothing else — no type check on `sample_rate_hz`, no shape
check on `delay`/`crossover_filters`/`parametric_eq`/`phase_control`), and
`process.py:216-253` / `dsp_profile.py:432-456` (`missing_facts` tests **key presence only**).

**Concrete bad file that passes** (verified: `validate_profile` clean, `sample_rate_hz` absent
from `missing_facts`, so the phase-1 gate opens):

```json
{ "dsp_profile": { "name": "Helix DSP Ultra S", "vendor": "Audiotec-Fischer",
  "groups": [{"id": "physical_outputs", "label": "Out",
              "fields": ["hp","lp","gain_db","ta_ms","polarity"],
              "crossover_filters": "yes, LR and BW", "max_count": 12}],
  "sample_rate_hz": "96 kHz-ish", "delay": "0.01ms steps" }}
```

**Symptom:** the gate built after the 2026-08-11 incident ("a rate nobody wrote down is a rate
somebody assumes") is satisfied by a value no arithmetic can use; phase 1 proceeds and the
ms→samples conversion is done off whatever the model assumes — the identical failure the gate was
written to stop, now with a green light on it. `finalize()` happily promotes the same draft.

---

## 8. `channel_summary` — a "skill-written fact" with no writer, no validator, and no cross-check

**Rule stated:** `rew_tool/project-schema.md:81-84` — "`channel_summary` … project-scoped tier
counts (SCR-016)"; TCC `state/project_view.py:133-137` — "Not re-derived from the ledger
client-side — **the skill already counts this at intake and writes it here**."

**Where it should be enforced:** `rew_tool/project.py` has no `set_channel_summary`, no mention
outside the empty skeleton (`:121`); `validate` (`:129-207`) never looks at it;
`contract.py`'s cross-checks (`:194-251`) never compare it against `channels[]` rows or the
profile's `max_count` — the two files that can contradict it.

**Concrete bad file that passes:** a `project.json` carrying
`"channel_summary": {"channels": {"total": 8, "off": 0}}` alongside twelve `channels[]` rows and a
profile `max_count: 12` validates everywhere, and `contract.py check` reports `ok`.

**Symptom:** TCC's Project-params panel renders "Channels 8" verbatim over a 12-slot rig — a
counting fact with no producer keeping it true and no checker allowed to notice; it is stale from
the first channel added after intake.

---

## 9. `phase_deg` and `tag` are exempt from the "only type-checked when present" promise

**Rule stated:** `rew_tool/state/schema.md:100-101` — "`tag`/`mute`/`off`/`phase_deg`/`eq` are all
OPTIONAL on every tier's rows — **only type-checked when present** (the booleans must be bool)";
`schema.md:76` — `phase_deg` is "all-pass/phase angle", a number; `FIELD_VOCABULARY` in
`dsp_profile.py:191` — "continuous phase/all-pass angle in degrees, a number".

**Where it should be enforced:** `rew_tool/state/state.py:265-297` (`_validate_row`) — it
type-checks `gain_db`, `ta_ms`, `polarity`, `status`, `mute`, `off`, `eq` and skips `phase_deg` and
`tag` entirely.

**Concrete bad file that passes** (verified): a `channels` row with
`"phase_deg": "ninety", "tag": 123` validates and snapshots clean.

**Symptom:** verified on the reader — TCC's `dsp_state._field_label` (`dsp_state.py:139-140`)
returns `None` for a non-numeric `phase_deg`, so the chip silently disappears from the channel row
(an all-pass someone dialled in reads as "no phase control set"), while the skill's own settings
sheet prints the string via `_fmt_opt`. Two readers, two different wrong answers, no error. Same
class, smaller blast radius: `hp`/`lp` legs only need `f` (`state.py:163-170`) — `type`/`slope`
are documented (`schema.md:71`) and unchecked, rendering as `70 ? ?` on the sheet the Arbiter keys
in.

---

## Crash-class (accepted by the writer, raises in a reader — louder, so ranked last)

* **`eq_ptr` as a string.** Shape documented at `schema.md:78`
  (`{"output": …, "virtual": …}`); `_validate_row` never checks it. Verified:
  `"eq_ptr": "exports/sub.req"` validates and snapshots, then `render_state`
  (`state.py:561-563`) crashes with `AttributeError: 'str' object has no attribute 'get'` — so
  `state.py render`, `PresetHistory.render`, and every `apply.propose` (which calls
  `history.render(version)` at `apply.py:328`) fail *after* the snapshot is banked.
* **`dsp`/`source`/`mic`/`car` as non-dicts.** `project.validate` (`project.py:147-149`) checks
  list-ness for five keys and dict-ness only for `hardware`/`glossary`; `{"dsp": "Helix Ultra S"}`
  validates and `Project.save()` writes it. Verified: TCC's
  `state/project_view.py:79-80` (`load_system_params`) then raises `AttributeError` — a reader
  assuming an object shape the writer never guarantees.

---

## Known-open items — CONFIRMED (not counted above)

1. **Ledger row fields are never checked against the profile's `fields` for that tier — CONFIRMED.**
   `state.validate` is profile-agnostic (`state.py:300-337`: `channels` has a fixed required list,
   every other tier "lenient"); `contract.py`'s `cross_check_tiers_vs_profile` (`:221-250`)
   compares **tier names only**. Verified: a `virtual_channels` row carrying
   `"hp": {"f": 100, "type": "BW", "slope": 12}` against a profile whose virtual group declares
   only `["gain_db"]` validates, snapshots, and produces zero cross-check issues — and TCC's
   `GroupRow.params()` (`dsp_state.py:260-270`) renders *only declared fields*, so the banked `hp`
   is invisible in the app forever (the `delay_ms` failure shape, one level down).
2. **`Project.save()` has no compare-and-swap on `project_rev` — CONFIRMED.**
   `project.py:322-340`: the new rev is computed from the rev inside the *caller's copy of the
   data* (`data.get("project_rev") … + 1`); the file's current rev is never re-read or compared.
   Two writers that both loaded rev N each write rev N+1; the second silently discards the first's
   facts and the rev sequence shows nothing. (Finding 5 compounds this: the loser can also be a
   reader that got the empty skeleton from a mid-write read.)

---

## Unverified guesses (plausible, not demonstrated end-to-end)

* **`Registry.load()` parses `registry.json` with no error handling** (`state.py:661-666`): a
  corrupt registry likely crashes `get_active()` and with it every `apply.propose(registry=…)` —
  loud, but in the wrong place, and `contract.py` would not have warned first (finding 4).
* **`glossary` sub-shape** (`glossary.channels[]` entries, `pairs`/`combos`/`joints`/`sides`) is
  only checked to be a dict (`project.py:205-206`); `naming.Glossary.for_project` consumers were
  not traced in this pass — malformed entries may drop channels from naming checks silently.
* **`reviewer.mode` closed list** — `process-schema.md:44` declares `api | cli | clipboard`;
  `record_reviewer` (`process.py:597-623`) accepts any string ("telepathy" verified to validate).
  Believed display-only in TCC; downstream effect not traced.
* **`ProjectView.from_dict` `features`** (`dsp_state.py:419-421`) unpacks `raw.get("features")` as
  pairs; a ledger carrying a non-pair list would raise during view construction. `features` appears
  in `_NON_TIER_KEYS` but in no schema document, so there may be no writer at all.
* **`_flaw_map_entries` reads `data.get("project", data)`** (`process.py:150-155`) — tolerates a
  `{"project": {…}}` wrapper no schema documents; if any producer ever writes that wrapper, every
  *other* reader of `project.json` would silently see an empty file while this gate sees content.
