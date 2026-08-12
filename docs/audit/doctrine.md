# Doctrine audit — contradictions between documents, and between documents and code

> **Verification pass (Opus, same night).** Fable-5 audit; the five costliest findings were checked
> against the files and the code rather than taken on trust. **All five reproduced.**
>
> | # | claim | independently reproduced |
> |---|---|---|
> | 1 | the shipped `.critic-env.example` swaps Critic and Advisor | ✅ template pins `GEMINI_CRITIC_MODEL="Gemini 3.5 Flash (Medium)"` and `GEMINI_ADVISOR_MODEL="Gemini 3.1 Pro (High)"`; `setup-critic-channel.md:40-41` says Critic = Pro, Advisor = Flash. Copying the template gives you the rubber-stamp reviewer the doctrine warns about |
> | 2 | SKILL.md contradicts itself on where the active phase lives | ✅ line 56: process-state.json, "**not** tuning-changelog's ▶️ CONTINUE block"; line 79: "Read the top ▶️ CONTINUE block … to identify the active phase" — 23 lines apart |
> | 3 | the phase-0 gate names a command that does not exist | ✅ `process.py:124-127` tells the model to run `set-target`; the CLI dispatch at `:1105` is `elif cmd == "target"`. The refusal instructs a command that fails |
> | 4 | `contract.py check` calls an EMPTY project OK | ✅ `check_project(<empty dir>)` returns `ok=True` with every file `exists=False`. Phase −1's gate names that check as its verifier, so the gate's own tool endorses skipping the gate |
> | 5 | prose still crowns files the contract demoted | ✅ (documentary, both sides quoted in the report) |
>
> **One thing the audit did not claim, and I checked because it looked like a match:** yesterday's
> live session ran its Critic as `gemini-3.6-flash-high`, which is exactly what finding 1 produces.
> It is NOT the cause — `testTCC-5` has no `.critic-env` at all, and that substitution came from
> TCC's own model alias (fixed in `15aef41`/`7e1a97a`). Finding 1 is a loaded trap that has not
> fired yet, not the explanation for what we saw.
>
> Findings 6-14 are not re-run; treat them as the audit states them.


Read: `SKILL.md`, all 7 phase files, all 17 `references/core/` files, the 6 `references/patterns/` files plus `target-curves/`, all 8 `references/tooling/` files, `knowledge/dsp|cars`, `assets/data-contract-template.md`, and the `rew_tool/` + `scripts/` code the docs name (`state/process.py`, `state/state.py`, `state/apply.py`, `contract.py`, `project.py`, `dsp_profile.py`, `naming.py`, `rew_api.py`, `rew_tool.py`, `xover_select.py`, `dsp_math.py`, `gates/*`, `verify.py`, `spot_check.py`, `_gemini_common.sh`, `gemini_*.sh`, `autosound_ai.py`, `.critic-env.example`, `start_gemini_tuner.sh`). Fourteen findings survived verification against the code; everything below quotes both sides. All paths are relative to `vendor/autosound-tuning-skill/skills/autosound-tuning/`.

---

## 1. The shipped `.critic-env.example` pins the Critic to the model the doctrine forbids for the Critic

**Side A — the rule, stated twice in the same file:**
- `references/tooling/setup-critic-channel.md:46`: "**The Critic defaults to Pro** — a Flash critic praises and misses obvious problems (field-observed); 'don't praise' prompt text doesn't fix a too-weak model."
- `references/tooling/setup-critic-channel.md:181`: "**Both roles now default to Pro.**" (section "Which model for which role (updated 2026-08-01)")
- The code agrees: `scripts/_gemini_common.sh:75-77` ("BOTH review roles default to PRO: a Flash reviewer praises… Flash is the FALLBACK only"), and `scripts/gemini_advisor.sh` takes its primary from `gemini_default_critic_model` (Pro).

**Side B — the template the same doc tells you to copy:**
- `scripts/.critic-env.example:7-8`:
  ```
  GEMINI_CRITIC_MODEL="Gemini 3.5 Flash (Medium)"
  GEMINI_ADVISOR_MODEL="Gemini 3.1 Pro (High)"
  ```
- `references/tooling/setup-critic-channel.md:53-62` instructs `cp scripts/.critic-env.example rew_analitic/.critic-env` and shows the same swapped pair as the worked example (`:60-61`).
- The stale §2 table also still says Advisor default = Flash (`setup-critic-channel.md:41`), contradicting `:181` of its own file.

**Wrong choice invited:** the model (or user) follows the setup doc verbatim, copies the template, and every critique for the rest of the project runs on the model the doctrine documents as a rubber-stamp — the roles are inverted exactly. The env var beats the code's correct defaults, so the wrapper's Pro default never fires, and nothing warns: the failure the review loop exists to catch (a reviewer that never disagrees) is configured in by the skill's own template.

---

## 2. SKILL.md gives two different answers to "where does the active phase live" — 23 lines apart

**Side A** — `SKILL.md:56` (Pre-Session & Resume): "`process/process-state.json` for the active phase + plan … is where the phase/plan actually live now — **not** `tuning-changelog`'s ▶️ CONTINUE block, which is a human-readable cross-check, not the source." Backed by `references/core/project-intake.md:185` ("if the two ever disagree, the machine file is what resume trusts") and `references/core/data-contract-universal.md:23`.

**Side B** — `SKILL.md:79` (Phase Sliding Window): "Read the top **▶️ CONTINUE** block of `tuning-changelog` at every session start to identify the active phase." Repeated in `references/core/process-phases.md:10` ("read the top ▶️ CONTINUE block of the `tuning-changelog` to determine the user's active phase") and `references/core/happy-paths.md:25` (resume walkthrough: "Read `audit-trail.md`, the top ▶️ CONTINUE block of `tuning-changelog`, and `dsp-state-current`" — no mention of `process-state.json` or `contract.py`).

The code is on side A: `rew_tool/state/process.py:4-5,30-31` ("`tuning-changelog` … become generated views over the journal").

**Wrong choice invited:** on resume the model reads whichever instruction it hit last. Side B is the shorter, more actionable one and appears twice more than side A; a model following it identifies the phase from prose, never opens `process-state.json`, and a prose/machine divergence — the exact drift SCR-004 was built to catch — goes unflagged. This is the highest-traffic decision in the skill (every session start).

---

## 3. Three files defer the `knowledge/cars` verify-only rule to SKILL.md — where the Reference Map says the opposite

**Side A — the rule:**
- `references/core/project-intake.md:79`: "Take install/gear specifics ONLY from here (from the user) or from measurement — **NOT** from a `knowledge/cars`|`dsp` profile. … A profile = a checklist to 'verify', not facts to cite. Never 'your X = Y' without the user's words or a measurement."
- `knowledge/cars/vw-passat-b8-sedan.md:7`: "PART B … ⛔ **VERIFY ONLY. Never cite it as fact, never offer it as a starting point.**"

**Side B — the line the model actually reads when choosing:**
- `SKILL.md:95` (Reference Map row for `knowledge/`): "**A DSP, car or approach this skill already knows — LOOK HERE FIRST, before asking.** … Read the file; if it is not there, `ls knowledge/dsp/`". No scope, no verify-only caveat, and "before asking" points away from the interview.

Worse, both rule-carrying files claim the rule lives in SKILL.md — a dangling pointer: `knowledge/cars/vw-passat-b8-sedan.md:8` "Full rule → `SKILL.md → knowledge/cars`"; `references/core/project-intake.md:166` "(the full scope rule → `SKILL.md` → `knowledge/cars`)"; `references/patterns/car-eq-patterns.md:280` same. No such rule exists anywhere in `SKILL.md`.

**Wrong choice invited:** during intake the model reads SKILL.md's row, opens the car profile "before asking", and presents PART B's crossovers/gains/anomaly frequencies as this car's facts — the anchoring failure the profile's own banner calls out. Identical shape to the calibration instance (`screen-read-dsp.md` vs its Reference Map line): the rule exists, is correct, and loses because the line at the decision point says nothing.

---

## 4. Phase −1's gate cites `contract.py check` as its verifier — but `check` deliberately reports an empty project as clean

**Side A — the doc:**
- `references/phases/phase_-1_intake.md:13` (quality gate → Phase 0): "**the machine files exist and validate** — `project.json`, `dsp_profile.json`, the glossary, and a first ledger snapshot … (`python3 rew_tool/contract.py check <project>` reports clean)".
- `references/core/project-intake.md:179`: "`python3 rew_tool/contract.py check <project>` — should report every machine file present and valid before the Phase-0 gate clears."

**Side B — the code:**
- `rew_tool/contract.py:294`: `ok = all(f["valid"] is not False for f in files) …` — a missing file has `valid=None` and does not flip `ok`.
- `rew_tool/contract.py:371-373` (selftest): "an empty project: every file reports missing … Missing is not the same as INVALID (a brand-new project hasn't been intake'd yet, which is normal, not broken) — so `ok` stays True". Exit code 0, final line "**OK — nothing to fix.**" (`contract.py:328,360`).

**Wrong choice invited:** the model runs the gate's named verifier on a prose-only intake, gets exit 0 / "OK — nothing to fix", and closes the −1 gate with zero machine files — the exact watched failure the process module documents (`state/process.py:24-28`: a model "closed phases −1 to 3 … with `dsp_profile.json` alone on disk"). The per-file "missing" lines are in the human table, but the doc's word "clean" and the exit code both endorse the wrong reading. Related hole, same family: `phase_0_baseline.md:13` says "`enter-phase 1` refuses while `acoustics.flaws[]` is empty", but `state/process.py:166-167` stays silent when `project.json` is missing entirely ("no readable project.json at all is contract.py's complaint, not this one") — and per the above, contract.py doesn't complain about missing either. The two halves each delegate the missing-file case to the other.

---

## 5. Two files still crown `dsp-state-current` / `autosound_context.md` "the source of truth" the machine-file doctrine dethroned

**Side A — current doctrine (and the code):**
- `references/core/data-contract-universal.md:23`: "Єдина точка правди — машинні файли, не проза. … фактичний стан системи живе в `state/<preset>/v_NNN.json` … якщо вони розійшлися, Генератор довіряє машинним файлам."
- `SKILL.md:56`: "if prose and the machine files disagree, **the machine files win**."
- `rew_tool/state/state.py:4-5`: the Markdown settings sheet "is GENERATED from that JSON (`render`); it is never hand-edited."

**Side B — the older claims, still standing:**
- `references/core/naming-and-structure.md:35`: "**`dsp-state-current` is the source of truth for what's in the base**".
- `references/core/naming-and-structure.md:104`: "The full state of the current `vN` always lives in `dsp-state-current` (memory)"; footer `:120`: "Current applied config (vN) → `dsp-state-current`."
- `assets/data-contract-template.md:28-30` (§ titled "Single source of truth + dynamic state"): "`autosound_context.md` (system, crossovers, history, known anomalies) — into both chats at the start." This template is what the Critic is system-prompted with (`project-intake.md:190`, `scripts/_gemini_common.sh`), so the reviewer is contractually told prose is the truth.
- `references/core/knowledge-architecture.md:14`: layer 5 "Project State" = "`dsp-state` · `tuning-changelog` · `audit-trail`" — the ledger/process/project machine files absent from the table.
- Same family: `SKILL.md:66` says the DSP native rate lives in `autosound_context.md`, while `phase_1_foundation.md:9` + `state/process.py:192-195` make `dsp_profile.json`'s `sample_rate_hz` the gated record.

**Wrong choice invited:** on a prose/ledger divergence (three real cases logged in `process-control.md:56-62`), the model reconciles *toward* the prose file two documents call the source of truth — or the Critic flags the Generator's correct machine-file reading as drift, which `setup-critic-channel.md:123` records as an actual field incident ("a critic on stale context spends its round policing ghosts").

---

## 6. The data contract's own Trace-ID examples don't parse under the naming grammar the tools enforce

**Side A — the grammar:**
- `references/core/naming-and-structure.md:30-37`: name = `<code>[ modifier]_<version>` + suffix `(sw)`/`(rta)`; "`_N` … starts at `_1`, NOT 'baseline'" (also `phase_0_baseline.md:31`).
- `rew_tool/naming.py:173-238` (`generate_name`/`parse_name`): only `<body>_<version> (sw|rta)` parses; `state/process.py:312-339` (`resolves`) accepts a measurement name as step evidence **only** when it parses with a method suffix.

**Side B — the contract both AIs are prompted with:**
- `references/core/data-contract-universal.md:24`: a proposal is invalid without a Trace ID "напр. `tw-L_sw_v1` або `w-R_rta_v3`" — method embedded mid-name, `v`-prefixed version, no `(sw)`/`(rta)` suffix.
- `assets/data-contract-template.md:30`: "e.g. `m-L_split_320Hz_LR4`"; `:139`: "**The first Trace ID:** set it at the first measurement (e.g. `<channel>_baseline`)" — the exact `_baseline` form Phase 0 forbids.

**Wrong choice invited:** the Generator formats packages (or, worse, tells the user to *title REW measurements*) per the contract's examples. Titles like `tw-L_sw_v1` are invisible to `naming.expected_series`/`validate_series`, are refused as `done`-step evidence by `process.py`, and break the `_N`-matches-config-version convention every before/after comparison hangs on. The contract is loaded into both chats at session start, so its examples outrank the naming file at the moment of choice.

---

## 7. Phase 0 (and the code's own error message) name a `set-target` command the CLI does not have

**Side A — the docs and the error text:**
- `references/phases/phase_0_baseline.md:40-41`: "`python3 rew_tool/state/process.py <project>/process set-target <preset> <curve>`" (also in the quality gate at `:13`).
- `rew_tool/state/process.py:124-127` — the gate's own refusal says: "nothing has been recorded with `set-target`. … Record it: `set-target <preset> <curve>` (e.g. `set-target FULL EPY`)."

**Side B — the code:**
- `rew_tool/state/process.py:961` (usage): "`target <preset> <curve>` — set a preset's active target curve"; dispatcher `:1105-1107` handles only `cmd == "target"`. `set-target` falls through to usage, exit 2.

**Wrong choice invited:** the model follows Phase 0 (or the refusal message itself — the one string guaranteed to be on screen at the failure), runs `set-target`, gets a usage dump, and either burns a round debugging or — the SCR-036 shape — gives up and records the curve in prose, leaving `targets` empty and the phase-1 gate either blocking later or the choice lost on `/clear`. The code contradicts itself here, so even "read the source" resolves it only if you read the dispatcher, not the error string.

---

## 8. `capture-check` and `--step` exist only in code — no document ever tells the model to arm or run the capture-verification gate

**Side A — the code:**
- `rew_tool/state/process.py:548-556`: `finish_step` refuses a step bound to an open capture round with unusable captures: "Run `capture-check` (and re-take what it fails) before closing the step" (SCR-040).
- `rew_tool/state/process.py:964-966` CLI: `capture-start <version> [title ...] [--step ID]` — the gate only engages when the round is bound via `--step`; `capture-check` is the verdict command.

**Side B — the doctrine:**
- `SKILL.md:65` (always-loaded guardrail) prescribes the capture-round ritual as exactly four calls: "**every capture round → `capture-start <version> [titles...]` before measuring, `capture-taken <title>` as each one comes back, `capture-skip <title> <reason>` … `capture-close` at the end**" — no `--step`, no `capture-check`. `grep -rn "capture-check\|--step" **/*.md` over the whole skill returns nothing.

**Wrong choice invited:** a model following the guardrail to the letter opens unbound rounds and never verifies a capture; `finish_step`'s gate never fires (no `--step`), rounds close with unchecked or unusable curves, and SCR-040's protection is structurally disabled by the doc-side recipe. "I looked at the graphs and they seem fine" — the sentence the gate exists to stop — is again load-bearing.

---

## 9. Three different phase maps: 7 phases in the code, "9-stage" in SKILL.md, "−1–7 with center/rear before listening" in naming-and-structure

**Side A — current structure:**
- `references/core/process-phases.md:3`: "The tuning process consists of **seven** chronological phases" (−1..5); `rew_tool/state/process.py:50` `PHASES = ("-1", …, "5")`.
- Order: listening is Phase 4, center/rear is inside Phase 5, and `phase_3_control.md:63`: "**Center/rear (Phase 5) is optional and comes only once the front satisfies** — don't jump to it straight from the lock." `phase_4_listening.md:92`: session closes in Phase 4, "no separate wrap phase".

**Side B — the stale maps:**
- `SKILL.md:99` (Reference Map row): "core/process-phases.md | Phase transitions, the **9-stage** overview."
- `references/core/naming-and-structure.md:10`: "PHASE **−1–7** (process-phases.md): intake … → verdict → **center/rear → listening** → client voicing → **wrap-up/feedback**" — center/rear *before* listening, plus a wrap-up phase that no longer exists.
- `references/core/project-intake.md:106`: "a **Phase-6** voicing move (`voicing-by-ear.md`)" — voicing is Phase 5; `enter-phase 6` is refused by `process.py:474-475`.

**Wrong choice invited:** a model planning from naming-and-structure's hierarchy schedules center/rear integration straight after the Phase-3 lock, before the ear pass — the ordering `phase_3_control.md` explicitly forbids; or it narrates/records a "Phase 6" the writer refuses, and the step lands nowhere.

---

## 10. Phase 2's body makes two critic checkpoints unconditional; its own quality gate makes the second conditional

**Side A** — `references/phases/phase_2_eq.md:15` (quality gate → Phase 3): "**one critic checkpoint passed on the round's full package** (add a second, after 2b, **only when joint alignment was reworked**)." Consistent with `SKILL.md:134` ("Cadence: ONE reviewer call per round") and `review-loop.md:48` ("The default review is **one** stateless critique pass on the round's whole batch").

**Side B** — same file, `:60`: "🔍 **Critic checkpoint (1 of 2):** with the joints/polarity set, run a cross-vendor review round on the phase alignment **before** EQ" and `:89`: "🔍 **Critic checkpoint (2 of 2):** with the EQ done, run a cross-vendor review round … **before** the Phase-3 lock" — numbered "1 of 2" / "2 of 2", stated with no condition.

**Wrong choice invited:** the two readings differ on whether the 2b review happens on an ordinary pass. A model that reads the gate first treats the 2b checkpoint as skippable (and "joint alignment was reworked" as the only trigger); one that reads the body first spends an extra review round every phase-2 pass. Whichever side is intended, the checkpoint most likely to be silently dropped is the phase-gate-adjacent one. The gate wording is load-bearing for the cadence code path (one call per round); the body's "1 of 2" predates it.

---

## 11. setup-critic-channel §2 says `autosound_ai.py` maps display labels to API ids — the code removed that mapping on purpose

**Side A — the doc:**
- `references/tooling/setup-critic-channel.md:44`: "**`Gemini 3.5/3.1` are Antigravity's own display labels** … — the direct-API path (`autosound_ai.py`, no CLI) **maps them to `gemini-2.5-flash` / `gemini-2.5-pro`**."

**Side B — the code (and the same doc, later):**
- `scripts/autosound_ai.py:221-222`: "The model name is passed through as given. There used to be an alias table here mapping a CLI's display labels onto API ids ('Gemini 3.1 Pro (High)' -> gemini-2.5-pro); **it was wrong**".
- `references/tooling/setup-critic-channel.md:104-105`: "Same reason the display-label→API-id table is **gone**: a table of model names is a maintenance commitment."

**Wrong choice invited:** a session with an API key configured pins the `agy` display label (as §2 and the `.critic-env.example` both show) and expects the direct-API path to translate it; the label goes through verbatim, the API call fails as an opaque model-not-found, and the wrapper degrades — read as "quota dry" per the doc's troubleshooting, not as the config error it is.

---

## 12. Arrival TA: "NEVER the global peak" (Phase 1, critical rule) vs "align heavy midbasses to 100% of the amplitude peak" (car-eq-patterns)

**Side A** — `references/phases/phase_1_foundation.md:44`: "Use the **IR FIRST FRONT** (leading edge, **NOT the global peak**) of each solo channel." Stated inside a "⚠️ CRITICAL RULE" block; `rew-api-quirks.md:38` backs the onset-not-max reading for the reflection failure mode.

**Side B** — `references/patterns/car-eq-patterns.md:306`: "**Rule for heavy midbasses:** align to **100% of the amplitude peak** of the IR, not to the onset (the nose). By ear it gives punch and instrument body on the dash." (`phase_1_foundation.md:24` does link this as a "common pattern (hypothesis)".)

**Wrong choice invited:** the two files answer the same question — "which IR feature is the TA anchor for a door midbass" — oppositely, and the absolute phrasing of side A ("NEVER") gives no hint an exception exists unless the pattern file was also loaded. A model with only Phase 1 in context onsets-aligns a heavy midbass (the documented stage-collapse case); one with only the pattern in context peak-aligns everything. Side A is the one stated as law; side B is the one marked as a hypothesis — a maintainer call on which should reference the other explicitly.

---

## 13. Phase 2's entry gate is documented as unconditional on `parametric_eq`; the code only owes it when a tier declares an `eq` field

**Side A — the doc:**
- `references/phases/phase_2_eq.md:13`: "⛔ **Entry precondition:** `enter-phase 2` refuses while the profile does not describe what the EQ can actually do — `parametric_eq` … Filters are sized against those limits; inventing them is how a 30-band answer lands on a 10-band processor."

**Side B — the code:**
- `rew_tool/dsp_profile.py:418-423` (`_FACTS_BY_FIELD`): `parametric_eq` becomes a missing fact only when some group's `fields` include `"eq"`; `rew_tool/state/process.py:192-195` filters by the same list, and the selftest asserts the pass-through: `state/process.py:1035-1038` — "phase 2 asked only for what a profile declaring no EQ actually owes: **this profile declares no `eq` field, so there is nothing for it to owe**" → `enter_phase("2")` succeeds.

**Wrong choice invited:** an under-built profile (no `eq` field declared at all — precisely the "nobody described the EQ" case) sails through `enter-phase 2`; a model that trusts the doc's gate as proof the EQ limits are on record then sizes a filter bank against limits that were never written — the 30-band-on-a-10-band failure the doc names, passed by the gate the doc says prevents it.

---

## 14. process-phases' protocol names a `view_file` tool this harness does not have

**Side A** — `references/core/process-phases.md:11`: "**Load active & adjacent phases:** Use the `view_file` tool to load ONLY the active phase file…"

**Side B** — no such tool exists in the Claude Code / Agent SDK surface this skill runs on (its own docs elsewhere say "Read the file" — e.g. `SKILL.md:95`); `view_file` is another harness's tool name.

**Wrong choice invited:** small, but real for a weaker driver: it looks for a `view_file` tool, doesn't find one, and either stalls or treats the sliding-window instruction as inapplicable. The instruction's intent (read two phase files only) survives; the named mechanism doesn't.

---

## Not fully verifiable against code (kept out of the main list)

- **REW API behavior claims** (`references/tooling/rew-api-quirks.md` throughout: Pro-gated write endpoints, free measurement-processing commands, big-endian encoding, `gaindB` field, slot counts per equaliser) — consistent with what `rew_tool/rew_api.py` implements, but only a live REW instance can confirm the server side; not audited as contradictions.
- **`agy` / Antigravity CLI facts** (`setup-critic-channel.md:15-33`: brew cask name, login flow, weekly quota semantics, model-name drift) — external tooling, unverifiable here. Note only that the file itself already flags its own model-name table as unstable (`:187`).
- **Field-calibration numbers** (`eq_gate.py` Z 4.5/6.0 thresholds, `ROBUST_PERT` ±20 µs/±0.5 dB) — the numbers match between `rew-tool-docs.md:46`, `filter-types-car-audio.md:111` and the code (`dsp_math.py:139`, `xover_select.py:152-159`); their *validity* ("provisional, 7/7 on one build") is a claim about hardware history, not checkable here.
- **`rew_api.py` defines `get_distortion` twice** (`rew_api.py:159` raw-dict version shadowed by the parsed-tuple version at `:288`). The surviving definition is the one the docs describe (`rew-api-quirks.md:46`), so it is dead code rather than a doc/code contradiction; flagged here only so the maintainer knows the first definition is unreachable.
