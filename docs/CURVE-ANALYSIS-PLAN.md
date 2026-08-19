# Curve analysis: the predicted sum, N drivers, and an all-pass you can dial

What this is: the design note for four changes to TCC's curve window, raised by the user on
2026-08-18 while the installer work was being field-tested. They look like four features and are
mostly one: **see what the drivers will do together before typing anything into the DSP and
re-measuring.** Today the window answers "where does this driver arrive" for a pair; the ask is
"what does this group sound like summed, and what happens to that when I rotate one driver's
phase".

Written before the code so the physics that decides whether the feature tells the truth is settled
first, and so parallel work stays in disjoint files.

## The four, in the order they are being built

1. **RTA out of phase and impulse.** An MMM/RTA capture has no impulse (REW answers 400) and no
   phase (the field is null) — `rew-api-quirks.md`. `kind_for()` handles an all-RTA selection; a
   MIXED one still offers both kinds and then fails inside the worker, which reaches the Arbiter
   as a broken window. Smallest of the four, and it is a precondition for the rest: a curve that
   cannot carry phase cannot be in a sum.
2. **The predicted sum, drawn dashed.** The complex sum of the plotted drivers, with each driver's
   current delay applied, in dB. This is the payload.
3. **More than two curves.** A checkbox selector instead of two pickers, so a tuner can look at
   Ws, Ms, TWs, SW+Ws, a whole side, or everything — the groups a tune is actually argued about.
4. **An all-pass per driver.** APF1/APF2 applied to a trace, its effect visible on the phase and,
   more to the point, on the sum. Simulation only in TCC; the ask on the skill is SCR-050.
   **Landed 2026-08-19** (TCC `ab494ac`, skill `343c0f5` + `70234d2`) — see "Decisions taken
   2026-08-19" below for what was decided while building it.
   **APF1 and APF2 only — the Helix "Phase" control is deliberately out of scope** (user,
   2026-08-18): it is one vendor's second-order all-pass with its frequency taken from the
   crossover, so it takes an angle rather than an `f0`, while `APF1`/`APF2` as EQ bands are what
   every processor with a PEQ slot can accept. The maths comes from the skill
   (`dsp_math.apf2_response`), never from a second copy in TCC — which is why SCR-050 also asks
   for the missing `apf1_response` and for the all-pass branch `eq_complex` does not have.

## The precondition, and why the sum is not allowed to hide it

A complex sum of measured responses predicts the acoustic sum **only when every measurement shares
one timing reference** — a loopback or a fixed Time Offset in REW. Without that, the relative phase
between two measurements is arbitrary, and the summed curve is a confident fiction: smooth,
plausible, and about nothing. `rew-api-quirks.md` §Timing is explicit that a floating
per-measurement reference makes `startTime` jump by ~5 ms between adjacent captures, and that this
cannot be settled from the numbers alone.

So the rule for this feature: **state the assumption, show the evidence, do not invent a
detector.** The sum carries its precondition in words wherever it is shown and wherever it is
packaged for the Critic; the per-measurement timing facts travel with it. The one check that is
sound — a capture with no phase at all cannot be summed — is enforced, and it proves only that.

This matters more here than in most places, because a predicted sum is exactly the kind of artefact
that ends an argument. If it can be wrong without saying so, it will end arguments wrongly.

## Decisions taken 2026-08-18 (user)

- **On the impulse view the sum gets its own strip below the plot**, not a second Y axis: the
  impulse's X axis is time and the sum's is frequency, so they cannot share one. The point of
  putting it there at all is that the delay is dragged on the impulse — the tuner should watch the
  joint fill in while they drag, not switch views to find out.
- **The all-pass is a TCC-side simulation first**, and the skill-side ask is written up
  immediately as **SCR-050** rather than left implicit. Nothing in TCC writes an APF to the ledger:
  the skill writes the project, TCC reads it (D-6).

## Decisions taken 2026-08-18, evening (user, after using it)

- **The sum lives in the strip on the impulse AND the phase; the right-hand axis stays only on
  the FR.** In the strip every plotted trace's magnitude is drawn thin in its own colour under the
  thick dashed sum, so the joint is read against the drivers that make it. The boundary between
  plot and strip is a draggable splitter, remembered.
- **On the phase the strip is X-linked to the phase plot** (same frequency scale and position),
  with a toggle to unlink (zoom the sum alone) and to relink; on the impulse it cannot be linked
  (time above) and opens on a default band.
- **A big red X hides every guide line at once**, positions kept, the reading unchanged.
- **The two ways of choosing curves — the pair pickers and the group/choose row — confused the
  user, and the Advisor (Gemini 3.1 Pro, asked 2026-08-18) settled it: ONE visible selection, a
  chip row.** Every chosen title as a chip with an × (its own colour), "+ add ▾" for arbitrary sets,
  and `group ▾` / `_N` reduced to a FILL action that writes into the chips. The pair pickers go.
  The Advisor's rule, worth keeping verbatim: *"the tuner must always know exactly which physical
  measurements are contributing to the predicted sum on the screen … saying '(3)' while only
  listing two names, or tucking active curves inside a closed checklist, breaks trust. If a tuner
  commits a delay change based on a plotted sum, they must be 100% certain of what fed that sum."*
  Their workflow, per the Advisor: load a group as a macro, look at the sum, isolate a problem by
  removing one driver with its ×. Next round, same files.

## Decisions taken 2026-08-19 (building step 4)

- **The all-pass edits the driver the radio has chosen — the same driver the delay box edits.**
  A row of its own under the delay's (that row is full at two drivers and over at seven), but
  one editing model: "which driver am I changing" has one answer, not two. The row names the
  driver in its own colour so the answer does not need a glance upward.
- **On the impulse the drawn trace stays as captured.** An all-pass smears an impulse, and
  re-filtering the time series is a round trip through the FFT this window does not make; the
  strip's sum carries the filter, and the strip is where the joint is read anyway. On the phase
  the trace rotates around `f0`; on the frequency response it does not move — unit magnitude is
  what makes it an all-pass, and the tip says so.
- **The filter is the skill's, probed before it is kept.** `core/allpass.py` holds the parameter
  set (validated once, spelled `APF1`/`APF2` as the ledger spells them, one `label()` for the
  legend, the reading and the sum's sentence) and calls `dsp_math` through `vendor_loader`; a
  filter that cannot be computed is refused on the row rather than named in a legend the plot
  cannot show. `curve_sum` applies it on the result grid — a closed form can be stated exactly
  wherever the sum is stated — and refuses, by name, one it cannot compute.
- **Banked beside the delay, in the same entry.** The Advisor's workflow (load a group, look at
  the sum, isolate a driver with its ×) loses a filter on the first × unless the bank keeps it —
  a driver taken off the plot and put back is a new selection to the view. So `delay_bank` entries
  carry `apf`, the driver comes back with both, one clear clears both, the button counts a driver
  once whatever it carries, and the "Delays" sentence has an all-pass block with its own caveat:
  simulated on the sweeps in hand, never verified by a summation sweep. **Naming not revisited:**
  the group is still called "Затримки"/"Delays" while it now carries all-passes too — the user's
  names, left for the user to change.
- **Its own clause in the reading, its own signal in the view.** `ta_ms` and an EQ band are two
  settings typed in two places, so the reading says "all-pass, to rotate phase (proposed, not
  applied): m-L: APF2 250 Hz Q 0.71" as a clause of its own; `allpassChanged` is a signal of its
  own so the window can tell what moved.
- **What the skill does with the number afterwards is SCR-050 items 1–2, and both landed the
  same day**: `analyze-joints --apf` verifies a candidate under the joint's own trust gate, and
  the Critic's package format has an `Origin:` line. What still does not happen automatically:
  TCC does not run `--apf` itself; the Generator does, and quotes the line.

## Decisions taken 2026-08-19, second round (user, after using the APF build; six asks)

- **The markers are a constant PAIR, whatever is plotted.** One-per-curve (the step-3 build) made
  six dashed verticals over six curves and made a marker mean something it does not: a marker is a
  place the tuner is POINTING AT, a curve is what it is pointed at. Model/you when the model gave a
  reading; "1"/"2" otherwise, in the view's own two marker colours (muted / ok), never a curve's.
  On the impulse they open on the first two traces' peaks; on the FR and the phase on the geometric
  thirds of the band (200 Hz, 2 kHz) — max |y| of a response is a band edge, the one place nobody
  points. The level line of marker *i* follows trace *min(i, n−1)*, read off the DRAWN curve.
- **The reading is per marker, and the button and tip are called "Маркери"/"Markers".** Each
  marker: its position, then every trace's value there (FR/phase), or each trace's crossing of its
  level (h modes); positions only on the impulse; then a Δ block (signed, marker 2 − marker 1). The
  tip is a TABLE: the row label in the marker's colour, the column head in the trace's colour, the
  numbers in plain text; the delay and all-pass proposals follow as prose. The plain sentence that
  leaves the window is built from the same structure. Cross modes keep their one-line reading.
- **Three rows under the plot, by what they are about.** Row A: the driver radios (left) and,
  right beside "очистити:", the three counters (Σ прогноз · Маркери · Зчитані затримки (n)). Row B:
  the chosen driver's settings on one line — its name in its colour, затримка, "Затримки", all-pass
  kind/f0/Q. Row C: the axis unit, the marker modes, the × pair combos, ✕, ⇅, A D − +, "Маркери".
- **The top is ONE wrapping row**: set (`_N`) · mode · group · "Обрати… (n)" · the chips, in that
  order; few chips fit on one line, more wrap to a second. The `_N` and group combos still come and
  go with Σ (the 2026-08-18 rule stands); "заповнити:" went with the box they were in.
- **Opening from the panel plots ONE curve or the last set, never the whole round.** The first
  title for a series not opened yet, the last selection (kept in the main window, per series, for
  this sitting) afterwards — intersected with what REW holds now. The model's `show_curves` still
  gets exactly the titles it names. `available` stays the whole round, so narrowing the plot never
  narrows the choose menu.
- **The Y grid draws two tick levels, not three** (`maxTickLevel=1` on the left axes): the third,
  a tenth of the minor, was a hatch pattern behind the curves.
- **The Σ toggle is on every view, the FR included** — the user's own 2026-08-18 rule (never on
  the FR, where MMM captures are compared) reversed after a day of use: the sweeps a joint is argued
  about are compared on the FR as much as on the phase, and a toggle that exists on two views out
  of three gets hunted for.

## What each step touches

Kept explicit so two agents (or two sessions) do not land in the same file.

| Step | Files |
| :-- | :-- |
| 1 RTA | `ui/tcc/curve_dialog.py`, `ui/tcc/i18n.py`, `tests/test_curve_view.py` |
| 2 sum engine | `core/curve_sum.py` (new), `tests/test_curve_sum.py` (new) |
| 2 sum drawing | `ui/tcc/curve_view.py`, `ui/tcc/curve_dialog.py` (worker fetches magnitude AND phase) |
| 3 N curves | `ui/tcc/curve_dialog.py` (selector, bank), `ui/tcc/curve_view.py` (delay radio, markers) |
| 4 APF | `core/allpass.py` (new), `core/curve_sum.py` (apply an all-pass to an input), `core/delay_bank.py` (banked beside the delay), `ui/tcc/curve_view.py`, `ui/tcc/curve_dialog.py`, `i18n.py`; skill: `dsp_math.py`, `rew_tool.py analyze-joints --apf` |

## Consequences worth naming before they surprise someone

- **The worker fetches one of magnitude or phase today** (`values = phase if kind == "phase" else
  mag`). The sum needs both, from the same call — REW already returns them together.
- **Markers are pair-shaped.** The cross modes (`vx`, `hx`, `vhs`) answer "what do THESE TWO say at
  one x". With N curves the question changes, and the honest answer is probably: the cross modes
  stay pairwise between two chosen curves, and the per-curve markers keep working for the rest.
  Decide it when step 3 lands rather than generalising blindly.
- **The delay bank is per trace already** (`_delays`, `_channel_delays` are lists), but the dialog
  slices `[:2]` in several places. Those slices are the work, not the model.
- **A sum of drivers with different SPL calibration is a sum of nothing.** Levels have to be the
  measured ones; if a trace was captured at a different gain, that belongs in the input as a
  `gain_db` the tuner sets deliberately, not as a silent normalisation.
- **An all-pass does not fill a null** (`helix-phase-allpass.md`). A single-source magnitude dip is
  positional; only the summation of two overlapping sources can be re-tuned by rotating phase. The
  UI should make that hard to get wrong, since the whole point of showing the sum next to the APF
  is that the two are read together.
- **The timing precondition is checkable after all**, and the method already wrote the rule down:
  `phase_1_foundation.md` requires a shared Time Offset across the sweeps of a round, and
  `naming-and-structure.md` §3 makes `_N` the DSP config version a capture was taken under. So the
  enforceable rule is: every input to a sum is a `(sw)` capture carrying the same `_N`. A mixed
  `_N` is not a timing quibble — the DSP changed between those captures, so it is a sum of two
  different cars, and it has to be refused as loudly as a missing phase.

## Method

One branch per step, tests before code, `/code-review` before merge, and implementation by agents
with disjoint file scopes; the orchestrating session reviews and commits, and **agents run no git
commands** — one agent's `git add -A` would sweep up another's half-finished work. The first two
steps are built in parallel because their files do not overlap.

**Which model does which job** (decided 2026-08-18, and it is the product's own Generator ↔ Critic
rule turned on the code):

| Work | Model | Why |
| :-- | :-- | :-- |
| Changes to code | Opus 5 | the user's floor for anything that edits the app |
| Deciding what a test must ASSERT, where physics decides it | Fable 5, or the orchestrator | a weaker model writes tests that agree with the implementation instead of checking it against the physics — the same failure shape this project documents for tuning: it does not error, it concurs |
| Mechanical and line-checkable: running suites, i18n en/uk parity, porting the translated READMEs, reading transcripts | Sonnet 5 | volume work whose output can be verified line by line |
| Review | a model that did not write the code | anti-anchoring, for the same reason the method never lets one model both propose and approve |

The model is chosen per task by the orchestrating session, so no session has to be switched to
change tiers.
