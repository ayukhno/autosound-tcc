# Changelog

What changed in Autosound TCC, the desktop app for the
[autosound-tuning](https://github.com/ayukhno/autosound-tuning-skill) method. The app's update
button follows the tags below, so a version here is what somebody actually receives when they press
it. A FRESH install still takes `main` — until the installer follows the same tag, the two can
differ, and the newer of them is the fresh install.

## [v0.1.19] — 2026-08-23 · the ⌂ button is the main menu now

### Changed

- **Everything the window can do is in one menu, in five sections.** "Let us make this the main
  menu and gather everything there logically" — until now the same vocabulary was spread over a
  header, a footer, a button in the left column and two popups, so somebody looking for a thing
  had four places to look and no way to know which. The menu now carries: **Project** (open, new,
  import from Resonalyze, re-read from disk) · **Session and models** (start a session, terminal,
  save what the model knows, fresh session, configure models, what to ask about) · **Appearance**
  (theme, language, text size) · **Tools** (diagnostics and updates, target-curve tool) · **Help
  and support** (write to the developer, GitHub Sponsors, the Monobank jar).

  Three controls left the chrome for it, and none of them was a thing you press ten times an
  hour: the Resonalyze import button above the DSP tree, and the coffee and feedback buttons in
  the footer. Everything you do press often — refresh, diagnostics, zoom, theme, language, preset,
  models, session, terminal — keeps its own button as well.

- The menu is **rebuilt when the language changes**, which it never was: a menu item's label is
  set once at construction, so it used to keep the language it was born in while the rest of the
  window switched around it. That also makes the language check marks show the choice just made.

## [v0.1.18] — 2026-08-23 · the second door, in the state that needs it most

### Fixed

- **"Import from Resonalyze…" is visible before there is a ledger.** It sat in the DSP section and
  appeared only when the DSP tree did — that is, only for a project with a banked ledger. But the
  moment this button exists FOR is a project seeded an hour ago, with facts and a profile and no
  tuning yet, and somebody else's plan in hand. It was hidden in exactly that state. The dialog
  needs only `project.json` and `dsp_profile.json`, and says plainly when it has neither, so the
  button no longer waits for a tree.

  Same class as v0.1.17's missing menu item, found the same way: by opening the window on a
  freshly seeded project and looking for the button instead of assuming it was there.

## [v0.1.17] — 2026-08-23 · the new-project dialog had no door

### Fixed

- **"New project…" is back in the ⌂ menu.** The dialog behind it is the only path to the
  DSP-profile interview and, since v0.1.16, to seeding a project from an existing one — and its
  button in the left column had been hidden ever since "which project" moved into that menu,
  which never gained the matching item. So half of v0.1.16 shipped with no way to reach it. Found
  by the user asking where the new features were, which is the honest way to find a missing door.

### Changed

- The bundled **Helix profile carries the union of the PC-Tool modes**, not either one of them:
  the EQ frequency step is 0.01 Hz and the Q range 0.5–50, a pair that appears on no single
  screen. The user's rule — record the full range everywhere, because it can be entered by hand.
  Which way to be wrong is the point: a profile that passes a Q of 30 sends a tuner to switch
  mode at the PC-Tool screen, and they learn something; a profile that refuses what the hardware
  accepts means a valid tune is never tried and nobody finds out why. The import window says so
  now — legs are not "accepted by this DSP", they are "refused by no stated limit", which answers
  for the hardware and not for the mode you are in.
- **A DSP tier whose controls nobody has enumerated** (`groups[].fields: null`, new in the
  method's schema) no longer crashes the project view, and is not silently read as a tier with no
  controls: the params table says "controls not enumerated yet" where a channel with nothing set
  says "—". The two are a different sentence, and the method's own to-do list is derived from
  exactly these tokens.
- Vendored method pinned to the tag **v3.0.18**.

## [v0.1.16] — 2026-08-23 · a project can start from another one, and a plan can arrive from outside

Two features that answer the same complaint from opposite sides — a project that begins as a
blank interrogation — plus the Windows icon fix from the same morning.

### Added

- **Seed a new project from an existing one.** Pick a folder that already has a `project.json`
  and the installation comes over: the car, the source, the DSP, the amps, the mic, the hardware
  controls, every channel with its driver, the naming glossary, the presets, `dsp_profile.json`,
  and both prose files marked at the top as inherited. "Each next project demands a full
  description — and that should not have to be done" — and it is worst when the tune arrives from
  outside, since whoever wrote that plan has none of your system parameters and never will.

  What does not travel is the point: the measured findings (`acoustics.flaws`, `_open_questions`)
  are offered and OFF, because their evidence names measurements that exist only in the project
  they came from; `project_rev` restarts at 1; of `paths` only `measurements_repo` follows,
  because it addresses the car rather than the tune. It is an allowlist, so a project's `state/`,
  `process/`, `journal/` and ledger snapshots are not excluded by a rule somebody has to maintain
  — they are never reached.

  Seeding from the same DSP skips the capability interview: there is nothing left to ask about a
  processor already described in the folder. Pick a different DSP and the profile stays behind
  while everything else still travels. The status line says what was inherited, and how many
  facts in the inherited profile nobody has confirmed yet.

- **Import a Resonalyze virtual-DSP session.** Somebody tunes in Resonalyze's virtual crossover,
  sends the session file, and this reads it into the ledger's own vocabulary — per channel:
  crossovers, gain, delay, polarity, PEQ — then checks every value against what your processor
  can actually be given.

  It refuses rather than rounds. The sample this was built on asks for **LR48 on four legs**; a
  Helix DSP Ultra S offers LR at 12/24/36, so those eight edges are shown refused at the value
  that was asked for. A tune that looks imported and is not the one that was sent would be the
  worst possible outcome.

  Three more things it shows rather than smooths over: a limit your DSP profile does not state is
  "not checked", never a pass, rolled up once at the bottom; a dormant crossover edge (the file
  keeps values on the edge the crossover kind does not use) is greyed and labelled, so nobody
  reads a subsonic filter that was never set; and the stereo scene offset is context, not a value
  to enter — it is already inside each leg's own gain and delay. Legs that match a channel bind
  themselves; the ones that do not get a picker rather than a guess.

  No write path. Banking rows is the method's gate, which validates against the ledger head and
  produces the settings sheet somebody enters by hand; the window offers the rows on the
  clipboard, and only when nothing is blocked.

### Fixed

- **The taskbar drew Python's icon beside our window on Windows**, and a pinned shortcut plus a
  running window made two buttons — one of which did not start the app. The window's own icon was
  right all along; what was Python's was the process's identity. A uv trampoline starts the
  interpreter as a child, so the process that owns the window is `pythonw.exe`, and Windows takes
  the application from it. The app now claims an explicit AppUserModelID before the window
  exists, and the same id is stamped into each `.lnk`, which is what makes a pinned shortcut and
  the running window one button. On Windows the window icon is now the `.ico` with its seven
  drawn sizes rather than a 1024-pixel `.png` squeezed into a title bar.

  Testing this after an update needs one extra step: an already-pinned shortcut is a separate copy
  Windows keeps outside `--install-desktop`'s reach, so unpin it, start from the Desktop icon, and
  pin it again.

### Changed

- The bundled **Helix DSP Ultra S profile** states four limits it never did: the channel-gain
  range (−30…+5 dB, and deliberately not the EQ band's −30…+12 — they are different controls),
  the 20.82 ms delay ceiling, the EQ frequency range and the crossover corner range. On a real
  session that moves 53 checks from "not checked" to checked, and refuses nothing that was
  passing. The channel-gain STEP stays an open question, because nobody has verified it and a
  guessed hardware limit is enforced code.
- The vendored method moves to **v3.0.17+**: it now carries the Resonalyze converter and the
  project seeding, both with their own CLIs, so everything this release adds through the window
  is available in a terminal too.

## [v0.1.15] — 2026-08-22 · two things Windows saw that no test could

Both found by running the method's installer test in a Windows VM — one by the plan's own opening
command, one by watching the screen.

### Fixed

- **A console window blinked in front of the app.** Three times in one session on Windows 11:
  before the main window, again after it, and once more on opening the version panel. Every
  `subprocess` call in this app already asked for no window; the ones that cannot are the
  GRANDCHILDREN — the agent CLI runs the method's own `python3` and `git`, and a console program
  started by a console-less parent is given a console of its own. So "no console window" is the
  process's default now rather than a keyword each call site has to remember, and the one caller
  whose purpose IS a visible window — the terminal launcher — asks for it out loud.
- **`--version` started the app instead of printing a version.** There was no such flag, and the
  parser that lets Qt take its own flags off the same line swallowed it in silence, so asking the
  app its version launched it, MCP server and all. It prints and exits now, before the toolkit is
  even imported. An installer asks this before deciding whether to replace us, and a bound port is
  a bad answer.

### Changed

- The vendored method moves to **v3.0.17**, and two of its contracts changed under us. Flaw-map
  rows are no longer guaranteed a frequency: a new class of finding is a property of TIME
  (`energy_lag`, `ringing`, `decay_asymmetry`) and carries `t_ms` instead of a level — those rows
  were being dropped silently, so the panel drew a map with a class missing and said nothing. And
  the REW cross-check is now the verdict of the open capture round rather than of the ledger's
  head, with two new keys: the round it is about, and duplicate measurement titles — which the
  diagnostics line now puts first, because this app addresses a measurement by its title.

## [v0.1.14] — 2026-08-22 · the method's crossover maths, and a gate that was green because it was blind

No new surface: this release is the method underneath the app being corrected, and the test that
should have caught it being made able to see.

### Changed

- **The vendored method moves to v3.0.16**, which fixes a real defect in its crossover maths. Below
  about 250 Hz, a steep BW or BE filter was drawn from a transfer function that had lost its own
  answer to floating point: BW42 at 80 Hz came out at −33.11 dB where the family defines −3.010,
  BE36 at 40 Hz at +10.15. Verified here by loading the old and the new module side by side rather
  than taken on report; worst error across the hardware grid, 30.10 dB.
  **What this does and does not mean for what you saw in TCC.** The app never draws a crossover
  curve itself — it asks the method only for all-pass responses (`apf1`/`apf2`) — so no window here
  was showing those numbers. What the defect reached is the method's own recommendations: a
  crossover chosen for a steep low joint was fitted against a curve that did not describe the
  hardware, and delays or polarities settled on such a joint are worth re-deriving. **LR is
  untouched at any order** — 0.0000 dB, because that path designs a half-order Butterworth and
  squares it, so it never reaches the conditioning cliff. A rig on LR crossovers, which is what
  this one uses, has nothing to re-derive.

### Fixed

- **The gate that runs the method's own selftests was blind to half of them.** It kept a
  hand-written list of twelve modules with a completeness test beside it — and that test matched
  the quoted string `"selftest"`, which finds the modules taking the command positionally and none
  of the thirteen taking `--selftest`. Eleven of the method's modules had never been run here while
  a green test said the list was complete, and one of them was `xover_select` — the module that
  picks the crossovers the release above got wrong. The list is discovered now, by the same rule
  the method's own runner applies: 12 modules become 25, plus the installer-consistency check. The
  completeness test is a canary holding the two properties that actually broke — discovery reaches
  the subpackages, and it sees both command styles — because either failure otherwise looks exactly
  like success.

### Also

- A fresh install now takes TCC by release tag and lets the app build its own bundle: the method
  merged both requests (SCR-054, SCR-056) the evening v0.1.13 shipped and released them as v3.0.16,
  and its installer is served from `main`, so it took effect immediately. The "Known" note under
  v0.1.13 carries the same correction.
- Two cautions that come with that, both the method's to close and neither an emergency: the
  Windows half of those installer changes has not been run yet (there is no PowerShell on the
  machine they were written on — a Parallels pass is planned), and there is no fallback for an
  installed TCC older than v0.1.13, which has no `--install-desktop` to call. Such an install keeps
  working; it just gets no new shortcut.

## [v0.1.13] — 2026-08-22 · the app can install itself, and the left column scrolls straight

### Added

- **`autosound-tcc --install-desktop`.** The app now builds its own double-clickable entry point:
  an `Autosound TCC.app` in `~/Applications` with an alias on the Desktop, or — on Windows — the
  two `Autosound TCC.lnk` shortcuts, Desktop and Start Menu. Both point at the INSTALLED launcher,
  so `uv tool upgrade` moves the shortcut with it. This existed before, in the method's installer,
  as a 138-line script that opened our package to build our bundle — and once, on a clean M1, did
  not find itself. The installer can now call one command instead of carrying a builder for
  somebody else's app; until it does, the old script stays as the fallback.

### Fixed

- **The left column scrolled past the end of itself.** At the bottom of the panel the rows looked
  sliced and the space under them scrolled into nothing — 196px of it, measured. The DSP tree was
  a scroll area with its scrolling turned off, sitting inside the column's scroll, and a widget
  like that answers its parent with a size hint instead of the height it draws — and never says
  when it changes. So folding a group did not reach the column either: 66px of room handed to a
  tree that needed 886. The tree is a plain widget now; the column scrolls exactly its rows, and
  folding a group gives the room back.
- A channel's second line (`HP 100 LR4 · LP OFF · +0.0dB`) is elided rather than wrapped, so a
  narrow panel keeps one line per channel instead of rows that double in height.

### Changed

- The vendored method moves to **v3.0.12** — `align_delay_polarity`'s near-tie rule now spans both
  polarities (an exact draw settles by convention rather than float noise), and the pin stands on a
  release tag again rather than between two. Note for anyone comparing: `v3.0.12` was force-moved
  on 2026-08-22, so the same number means different code before and after.

### Known

- A FRESH install still takes `main` rather than this tag, and still builds the bundle with the
  method's own script — both halves live in the installer, which is in the method's repository.
  Both requests are filed (SCR-054 for the tag, SCR-056 for the builder); this release is the
  precondition the second one was waiting for.
  **Resolved the same evening** (added 2026-08-22, after this release): the method merged both
  (`5216b92`), and because its installer is served from `main` it took effect immediately — a
  fresh install now asks for TCC's newest tag and calls `--install-desktop`. Left above as it was
  written rather than edited away: it was true when this shipped, and what closed it is the point.

## [v0.1.12] — 2026-08-22 · the update button follows releases

The first release that behaves the way this file now describes: what the app offers you is a
release, not whatever happened to be on `main` an hour ago.

### Fixed

- **"Update" meant "take whatever is on `main`".** Both the button and the installer asked for the
  repository with no ref, and the version in the panel was read from `pyproject.toml` AT THAT
  COMMIT — so it looked like a release and was not one. Anyone pressing update got unfinished work
  with no way to tell from the row. The button now pins the tag it offers (`git+…@vX.Y.Z`) and the
  check compares the installed version against the newest `v*` tag. A build ahead of the releases
  reads as up to date rather than being told to update backwards — somebody working on `main` is
  ahead on purpose.
- A test helper wrote a glossary into the REAL project directory when imported outside pytest —
  which is how seven test channels landed in a live project twice on 2026-08-21. The helper now
  refuses to write anywhere but a temporary folder and says why, and the fixture that substitutes
  the project directory asserts the substitution actually took. Setting a variable is not the same
  as the redirection working.

### Known

- A FRESH install still takes `main`, because the installer lives in the method's repository and
  has not moved with this. Until it does, a new install can be newer than the release this button
  offers. Named here rather than left to be discovered.

## [v0.1.11] — 2026-08-21 · the field-fix round

Two intakes in one evening of real use, twenty-two items, none of them found by a test. The app
now delivers what the Arbiter clicks, survives being quit mid-turn, and reads as one column
instead of four boxes fighting for height.

### Fixed

- **A click in the app could sit unread for seven minutes.** Signals reached the model only when it
  happened to ask for them, and asking EMPTIED the queue — read and not acted on meant gone.
  Delivery is peek + ack: every turn carries the open queue, each answered signal records what
  became of it (`applied` / `refused` / `superseded`) in `.tcc/signals.jsonl`, and a click made
  while nobody is talking now starts its own turn rather than waiting for something unrelated to be
  said. The channel row shows "waiting…" with a counter; a second click on the same target state
  refreshes that instead of queueing a duplicate.
- **Quitting while the model was working aborted the app.** Answering "save" left the window hanging
  on a turn that had three minutes to finish, and the teardown then destroyed Qt around a running
  worker — a guaranteed `qFatal`, not bad luck. An exit that cannot tidy up now leaves without
  tidying up: better an unswept process than a crash report handed to somebody whose work was
  already saved.
- **Arriving text decided where the reader was looking.** The transcript no longer jumps while
  history is being read; a "↓ New below · N" row appears instead, and clicking it goes to where the
  new messages start.
- A request typed before the session started went nowhere and the first message vanished with it.
- A command did not take effect until the Arbiter happened to write something else.
- The left column now scrolls as one canvas — the DSP section used to be squeezed into whatever
  height was left and scrolled inside itself.
- The round picker was clipped by a banner that never fit; the banner is gone for the live session
  too, and the field's width is measured from the style rather than guessed.
- The composer grows when multi-line text is pasted into it.
- The parameter table listed disabled channels, and `Channels` / `Virtual channels` were left in
  English.
- The Arbiter's colour read as an alarm; the open questions were drawn as muted grey and could not
  be copied. Both now say what they are.
- A copied message keeps its table.
- Automatic flaws appeared only after a restart; the tree came back clipped after a reload
  (a regression from the scroll fix, kept as a test).

### Added

- The curve window lists capture rounds and filters by them, so a set visible in the capture panel
  is selectable on the plot. Picking ONE of two identically named captures is still not possible —
  that is the next step, and it stays inside TCC.
- Every number that means a version now says which axis it belongs to — series/config, or pass.

## [v0.1.10] — 2026-08-19 · up to date is the answer, when it is

### Fixed

- **A row on the newest release still explained why its button was off** — "the method 3.0.8 — a
  submodule of a checkout — update it with git" — which answers "why can I not update" at a moment
  when nothing needs updating. Up to date now wins over every caveat; the caveat comes back the
  moment there IS something the app may not install itself.
- The beta-report form says out loud that a path carries your computer's user name, since the
  repository is public.

## [v0.1.9] — 2026-08-19 · what the update buttons must not touch

### Fixed

- **"Update the method" offered to move a git SUBMODULE.** A submodule is detached and clean —
  exactly what an installed release looks like — so all three existing guards passed it, and the
  button would have checked a release tag out inside somebody's working repository and left the
  parent's pin modified. Found by the question "what happens if I press this on my own machine?",
  which was a better test than the three that were written. It now refuses and names the
  repository the submodule belongs to.
- **The diagnostics gear stood a head above the reload button beside it.** A larger font grows a
  QPushButton, so the glyph and the box moved together; the box is now pinned to the neighbour's
  size in code, on every theme and zoom change, and only the glyph is larger.

### Changed

- **A newer build of the same version says WHEN**: "a newer build is out, from 2026-08-19" instead
  of a commit hash. One anonymous API call, made only when there is something newer — an up-to-date
  machine asks nothing.

## [v0.1.8] — 2026-08-19 · no hashes in a sentence meant for a person

### Fixed

- **`TCC 0.1.7 · 0ef59ea — up to date`** put a commit hash in front of somebody who has no use for
  one (user: "незрозумілі цифри та букви"). The hash exists to tell two builds of the same version
  apart, which is a bug-report job — and it is already in the installation block below. The row now
  carries version numbers only, and when the two numbers are the same it says *a newer build of the
  same version is out* in words rather than showing the hashes that differ.

## [v0.1.7] — 2026-08-19 · in the reader's language, and legible

### Fixed

- **The update rows explained themselves in English inside a Ukrainian window.** `core/updates.py`
  is Qt-free and language-free, and it was composing sentences — so "running from a source
  checkout" arrived untranslated. It now returns a reason KEY and its data (a branch name, git's
  own words); the panel writes the sentence.
- **A disabled default button kept its accent ring** — "Update TCC" sat greyed with a live-looking
  orange outline over a row that said there was nothing to update. Qt holds both states at once and
  the accent won by coming later in the sheet.
- **A source checkout reported `TCC 0.0.1`** in its title bar from a tree at 0.1.6: the metadata in
  the virtualenv is whatever was installed once, long ago. For a checkout the version now comes
  from the checkout's own `pyproject.toml`; an installed build still reports its metadata, which
  there IS the build.

### Changed

- **The title bar says when something newer exists** — asked once in the background at startup, and
  silent both when offline and when up to date. The versions are already there; this is the line a
  person reads without being asked to.
- **The diagnostics gear is twice the size** of its neighbours. It is the button you hunt for when
  something is wrong.

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
