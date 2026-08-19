# Changelog

What changed in Autosound TCC, the desktop app for the
[autosound-tuning](https://github.com/ayukhno/autosound-tuning-skill) method. The app is installed
from `main` by the method's own installer, so a version here marks a point worth referring back to
rather than a thing anybody downloads separately.

## [v0.1.0] — 2026-08-19 · the beta the first outside tester gets

Forty-five commits since v0.0.4, and most of them are one line of work: **the curve window stopped
being a viewer and became the place a change is decided before it is typed into the DSP.** Beside
that, the app installs and runs from scratch on a clean Mac and on Windows 11.

Still a beta, and the README says so: what it has not had is a full tune driven end to end from
the window. The method in a terminal is the proven path.

### Added

- **The predicted sum of N drivers** (`core/curve_sum.py`). The complex sum of every plotted
  measurement, with each driver's proposed delay, gain, polarity and all-pass applied — so a guess
  costs nothing and only the accepted one is typed in and re-swept. It carries its own precondition
  everywhere it is shown: all inputs must be sweeps from one DSP config version (`_N`), a mixed set
  is labelled as a sum of two different cars rather than drawn quietly, and the one assumption no
  measurement can settle — that the operator set a shared time offset that day — is printed with
  every result.
- **An all-pass per driver, APF1 and APF2** (`core/allpass.py`, SCR-050). Dialled on the driver the
  radio has chosen and applied to the measured trace: the phase rotates around `f0`, the level does
  not move, and the predicted sum answers while the number is being typed. The filter comes from
  the skill's own `dsp_math` through `vendor_loader` — never a second copy here, because two
  implementations of one filter is how a front-end and a method start disagreeing about what a
  proposal means.
- **The delay bank carries the all-pass beside the delay.** A filter dialled on one driver comes
  back with it wherever it is next plotted, is counted once per driver on the button, and leaves
  in the same sentence — with its own caveat: simulated on the sweeps in hand, never verified by a
  summation sweep.
- **As many curves as the tuner names, with the glossary's own groups** (`core/curve_groups.py`):
  the woofers, a whole side, sub+woofers. One visible selection as a chip row — the Advisor's rule,
  after two ways of choosing had come to disagree — with groups and `_N` as a fill shortcut.
- **A strip under the impulse and the phase** carrying the sum, with each driver drawn thin beneath
  it and a draggable boundary that is remembered.
- **A way to omp's own setup from the model screen**, opened in the user's terminal, with the
  catalogue re-read when they come back.

### Changed

- **Markers are a constant pair**, whatever is plotted, and read as a table: each marker's position
  and what every trace is doing there, then the deltas — with the row in the marker's colour and the
  column in the trace's.
- **Delays are proposed as differences.** A set dragged onto a common arrival used to be sent as
  +10.690 / +10.670 / +10.000; only the differences were ever measured, so the set is normalised on
  the way out and names the driver it is stated from.
- **Every route is prefixed in every picker** — SDK, AGY, CODEX, OMP — including the opening screen,
  which used to print a bare name for anything that was not the SDK.
- **A route whose CLI is missing is greyed and says what it needs**, instead of being absent: an
  option that is not in the list reads as one that does not exist.

### Fixed

- **Two pyqtgraph segfaults**, both measured rather than guessed: one at construction (an empty
  menu) and one at teardown (0 crashes in 40 runs against 4 in 40).
- **A frequency axis that ran to 10^308 Hz**, from two causes — `updateLogMode` ending in a bare
  `enableAutoRange`, and `setXLink` being two-way and aligning by screen geometry.
- **The opening screen offered the generator's list as the critic**, so the reviewer this method is
  built around — a model from a different vendor — could not be chosen on the screen that asks for
  it. It also now warms the CLI catalogue that list is built from, which on a fresh machine is
  empty until something asks.

## [v0.0.4] and earlier

Not tracked here. The window itself, the DSP tree, the plan and measurement panels, the AI dialog,
the MCP server and the two adapters were built before this file existed; `git log` is the record.
