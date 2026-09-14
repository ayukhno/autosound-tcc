# Session analysis — project testTCC8, 2026-09-01 … 09-14

For the wave review: why a tuning run through TCC is long, and what would make it shorter and more
predictable. Asked by the Arbiter on 2026-09-14 ("replace the interview with a form to fill in").

**Source.** Three Claude Code transcripts from the Arbiter's Windows VM, copied from
`~\.claude\projects\C--Users-o-yukhno--autosound-testTCC8\`: `786a2715` (the tuning session, phases
−1 and 0), `1f4c97ae` (MUSWAY M6V4 DSP interview), `0434422f` (Helix DSP interview); plus
`.tcc/sessions.json`. Counts by script over the JSONL.

## 1. Numbers

| | |
|---|---|
| Tuning session span | 01.09 13:19 → 14.09 15:47, five working days |
| Arbiter's turns | 86 — by day 29 · 13 · 27 · 6 · 11 |
| Model's words | 27 640 — by day 9.4k · 5.6k · 9.5k · 0.8k · 2.4k; 116 per text block; the longest 563 |
| Bash calls | 229 — by day 96 · 51 · 67 · 3 · 12 |
| Phases | −1 closed 01.09; 0 entered 01.09 14:09, still open on 14.09 (`baseline-m6v4-real` blocked) |
| Reviewer | 6 `call_critic`, no review produced (TEST-FINDINGS 17, 21, 23, 25) |

## 2. Where the Arbiter's turns went

Read message by message:

- **About half — the product, not the car.** Empty DSP and car-analysis panels, issues to file, logs,
  flashing windows, protection status, a ledger that was not UTF-8. 02.09 entirely, most of 06.09.
- **About a quarter — intake and setup.** DSP answers, car and channels, the REW bridge from the VM
  to the Mac, the target curve. Almost all on 01.09.
- **A handful — tuning decisions.** Inputs for sweep vs RTA, the sub on two slots, whether gaps can be
  heard before a basic setup, reusing a baseline.
- **About ten — session mechanics.** Resume, close, interruptions, the answer language.

So most of the length measured here is the session diagnosing the product for the Arbiter. The
method's own length needs a run with fewer product defects in the way; the intake below is the part
that can be measured now.

## 3. The intake: what was asked, and how

**DSP, MUSWAY M6V4** — 30 minutes, 6 turns: 14 questions in 5 batches, most with enumerated options
(a / b / c), and one clarification of a free-text answer that could not be recorded as it stood
("level could gone away"). **DSP, Helix DSP Ultra S** — 1 minute, no questions: a library match
filled the profile. The DSP half is already a fixed checklist with enumerated answers — a form in all
but the widget.

**The car half was not asked until the gate refused.** The DSP interview window covered only the
equipment. At 14:09 the Phase-0 gate refused for `project.json`, the glossary and the first ledger
snapshot; the session then asked, in long free-text messages, for (1) car, body, year, stock or custom
install, (2) what sits on each of the 8 slots, (3) microphone, loopback, amplifiers — and in the end
inherited most of it from an earlier project on the same car. A session limit at 14:19 cut it in two.

**Fields the intake actually needed** (from the questions asked and the files written):

- **DSP** — vendor and model (library match first); else the capability checklist: tiers
  (virtual layer or not); number of outputs and inputs; input processing; PEQ bands, types, ranges and
  steps; crossover types, slopes, ranges; delay range and step; polarity and phase control; mute and
  EQ bypass; presets and input switching; output gain range; sample rate; EQ import from file.
- **Car** — make, model, generation, body, LHD/RHD; stock or custom install.
- **Channel map** — slot → channel name (`tw-L` … `sw`), the amplifier behind it, where the driver sits.
- **Measurement chain** — interface, microphone and calibration files, physical loopback, the input
  each method enters by (sweep vs RTA).
- **Goal** — competition (which format), personal, or both; which seats (driver, driver + passenger,
  all).
- **Target curve.**
- **REW** — where it runs, API port.

Decided in dialogue that a form would ask up front: one sub on two slots as one channel; sweeps and RTA
on different inputs and whether their levels match; the answer language.

## 4. Where predictability leaks

- **229 free Bash calls.** 96 ran method scripts directly (`contract.py` 18, `project.py` 16,
  `process.py` 16, `state.py` 14, `protective.py` 5, `project_seed.py` 4, `autosound_ai.py` 4, …), 17
  were HTTP calls to REW, 13 read or listed files, 8 were `gh` issue commands, and several read TCC's
  own source to debug it. Each is a possible permission prompt (TEST-FINDINGS 15, 16, 24) and a place
  where the session chooses the script, its arguments and the folder by itself (17, 21, 25).
- **Long diagnostic answers.** The five longest (431–563 words) are product debugging or inheritance
  tables.

## 5. Proposal for the wave review — not started

1. **One intake form in TCC, before any session.** The fields in §3: the DSP checklist as enumerated
   controls, pre-filled by a library match; car, channel map, measurement chain, goal and target on the
   same form; checked against the method's contract before "Start". The session opens at Phase 0 with
   the intake files written — no gate discovering a missing half.
   *Needs from the method:* a machine-readable list of intake fields and their enumerations (the
   capability checklist already is one) and a writer that takes the answers (`project_seed.py` and
   `save_profile_field` exist).
2. **Short answers by default in TCC sessions** — one line per step, details on request, in the
   session's system prompt.
3. **Product problems out of the tuning dialogue** — a "report a problem" path that does not need the
   tuning session (F-042, TEST-FINDINGS 19), so it does not spend half its turns on issues.
4. **Fewer free Bash calls** — the scripts run most (`contract`, `project`, `process`, `state`) as TCC
   tools with fixed arguments and no prompt.

Owners: the form and 2–4 are TCC's; the field list, the enumerations and the writer are the method's
— a ticket to the skill once the review decides.
