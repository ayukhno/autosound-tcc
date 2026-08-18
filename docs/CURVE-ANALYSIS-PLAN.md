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

## What each step touches

Kept explicit so two agents (or two sessions) do not land in the same file.

| Step | Files |
| :-- | :-- |
| 1 RTA | `ui/tcc/curve_dialog.py`, `ui/tcc/i18n.py`, `tests/test_curve_view.py` |
| 2 sum engine | `core/curve_sum.py` (new), `tests/test_curve_sum.py` (new) |
| 2 sum drawing | `ui/tcc/curve_view.py`, `ui/tcc/curve_dialog.py` (worker fetches magnitude AND phase) |
| 3 N curves | `ui/tcc/curve_dialog.py` (selector, bank), `ui/tcc/curve_view.py` (delay radio, markers) |
| 4 APF | `core/curve_sum.py` (apply an all-pass to an input), `ui/tcc/curve_view.py`, `i18n.py` |

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

## Method

One branch per step, tests before code, `/code-review` before merge, and implementation by Opus-5
agents with disjoint file scopes; the orchestrating session reviews and commits, and agents run no
git commands. The first two steps are being built in parallel because their files do not overlap.
