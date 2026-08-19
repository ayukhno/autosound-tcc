# Changelog

What changed in Autosound TCC, the desktop app for the
[autosound-tuning](https://github.com/ayukhno/autosound-tuning-skill) method. The app is installed
from `main` by the method's own installer, so a version here marks a point worth referring back to
rather than a thing anybody downloads separately.

## [v0.1.6] — 2026-08-19 · the update row compares like with like

### Fixed

- **"TCC 0.1.4 — a newer one is out: 64c72c43eccd"** put a version number on one side and a commit
  hash on the other, which is two different kinds of thing in one sentence (user's screenshot).
  Both sides now name both: `0.1.4 · 489b1be` against `0.1.5 · 64c72c4`. The remote version is read
  from `pyproject.toml` **at that commit**, not from the branch, so the number and the hash beside
  it describe the same build. When it cannot be read the commit alone still says it.

### Changed

- **"Report a problem" moved to the dialog's bottom row**, visible from any tab, and composes the
  report on the spot when the Installation tab was never opened.
- **The diagnostics button is a gear in the app's accent orange**, not `⚕` — it is the button
  somebody goes looking for when something is wrong.

### Verified, not assumed

- `uv tool install --upgrade` on a git URL **does** pick up new commits when the version number has
  not changed — measured here by pushing a commit without a bump and watching the upgrade go
  `0.1.5 (7900359) → 0.1.5 (64c72c4)`. So the installer's line is right as it stands, and the
  update row is correct to compare commits rather than versions.

## [v0.1.5] — 2026-08-19 · one inbox for the beta

### Added

- **"Report a problem", beside Copy in the Installation tab.** It opens the repository's beta-report
  form with the installation block already in its field — versions, where each piece came from,
  which tools answer. That is the half of a bug report nobody can assemble by hand, and the half
  that decides whether the report can be answered at all. The log is not sent this way (four
  hundred lines do not fit in a URL): its tab has a Copy button and the form has a field waiting.
- **A beta-report issue form** in both repositories, with a config that points each kind of problem
  at the right one — the window here, the method there.

### Fixed

- **The feedback modal could swallow a report in silence.** Its default destination was the Google
  Form, whose URL has been empty for some time: pressing Send copied the text to the clipboard,
  opened nothing, and closed the dialog as though it had been sent. With no form configured there
  is now one destination and no question — GitHub.

## [v0.1.4] — 2026-08-19 · the update waits for the app to close

### Fixed

- **"Update TCC" left the install unable to start.** The button opened a terminal and told the
  person to close TCC first; the command ran immediately anyway. `uv` replaced the package, then
  failed to clear the old `Scripts` directory — Windows will not delete a running executable —
  and ended in `Access is denied (os error 5)` after reporting the new version as installed. What
  was left did not start (user, Windows 11). The window now WAITS for TCC's own process to
  disappear (`Wait-Process` on Windows, `kill -0` elsewhere) and runs `uv` after it, so the swap
  happens on a machine where nothing holds the files. Recovery from the half-swapped state is
  `uv tool uninstall autosound-tcc` followed by a plain install.
- **"Re-check" now re-asks about updates too**, and does so even while the slower tool probes are
  still running — the rows go back to "checking" and their buttons off, rather than a stale offer
  standing over an open question. After a successful method update the row keeps what it just
  said, because that sentence is the receipt for the press.

## [v0.1.3] — 2026-08-19 · the method's version, on the machines that have one

### Fixed

- **The skill's version was missing everywhere it was promised** — the title bar said `(TCC 0.1.2)`
  with nothing beside it, the Installation tab said `The method ? — not a git checkout`, and the
  update row could not offer anything (user's screenshot, Windows 11). On an INSTALLED machine the
  skill is reached through a link the installer made — a symlink on macOS, a junction on Windows —
  and the manifest was looked for two levels up from the link, which is `~/.claude`: no manifest,
  no git. A developer's checkout is a real path, so it worked here and hid the bug on every machine
  that matters. `vendor_loader.skill_repo_root()` now follows the link and then looks for the
  marker instead of counting levels, and both readers go through it.

## [v0.1.2] — 2026-08-19 · updating from inside the window

### Added

- **"Update TCC" and "Update the method", in the Installation tab** (`core/updates.py`), with the
  answer to "is there a newer one" beside each. The two halves install differently, so they update
  differently. The method is a shallow checkout parked on a release tag: TCC fetches the newest
  `v3.*` and checks it out itself, the way the installer does, in about a second — and refuses on
  any checkout that is on a branch or has uncommitted changes, because that is somebody's own work,
  not an installed release. TCC's own update is handed to a terminal the person can watch: it
  cannot replace the files of the process doing the asking — on Windows the running `.exe` and its
  loaded DLLs are locked and `uv` would fail halfway — so the window says the one thing that
  matters, close TCC first. TCC is compared by **commit**, not version: it installs from the
  default branch, so a build three days of fixes behind still calls itself 0.1.1.
- "Could not ask GitHub" is a state of its own, and never reads as "up to date".

### Fixed

- **Buttons nobody had given a class to came out grey-on-grey in the dark theme** and read as
  disabled — the omp catalogue dialog's Ok/Cancel/"Configure omp…" (a QDialogButtonBox, so the
  message-box rule never reached it) and the `models…` button in the model strip (user's
  screenshot). The platform draws a light button while this sheet has already told its children to
  use light text. There is now a base rule for the type, so the next unclassed button is right by
  default instead of by being noticed.

## [v0.1.1] — 2026-08-19 · what the first Windows tester found

A day of the beta being used on a machine we cannot see. Every item here is something that made
the app harder to report on, or a claim of ours that turned out to be wrong.

### Fixed

- **A terminal window jumped in front of the app at every AI session** (Windows). It is the Agent
  SDK's own `claude` process: it is started through `anyio.open_process` with no creation flags, so
  Windows gives a console program started by a windowed app a console — piping its input and output
  does not prevent that, only `CREATE_NO_WINDOW` does. TCC does not own that call, so the default is
  moved underneath it once at startup (`core/child.py`). Two more children had been missed: the omp
  session, which is driven through its own stdin, and the project panel's `git`. `subprocess` itself
  is deliberately untouched — the terminal launcher opens a window because somebody asked for one.
- **The REW indicator now says which REW has an API.** The one thing on screen at the moment it
  fails: the API is in REW's beta builds only, and the release version (V5.31.3) has no API tab at
  all — which is what a web search hands you.

### Added

- **Both versions in the title bar** — `(TCC 0.1.1 · skill 3.0.7)`, from the same reader the
  Installation tab uses. The title bar is in every screenshot anybody sends.
- **A Logs tab in the repair window, with a copy button.** The end of the log file and the path it
  came from, re-read every time the tab is opened, and the path travels with the copied text — a log
  with no filename is one nobody can ask about again.

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
