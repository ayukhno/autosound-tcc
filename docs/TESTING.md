# Testing

## The policy

**Run everything, every time.** `make test` — 1722 tests, ~65 seconds, and that includes the
skill's own selftests as subprocesses.

There is deliberately no fast/slow split, and it is worth writing down why, because there nearly
was one. What there IS, since 2026-09-09, is a parallel run — which is not a split: every test
still runs, every time.

## Parallel by default; a release is serial (2026-09-09)

The suite had grown to 1722 tests and 498 s. The 2026-08-12 question was asked again first — is
this a leak or is it volume? — and answered by measurement, not by reaching for a policy:

| probe | number |
|---|---|
| 25 `MainWindow` builds in one process | window 5 = 0.1146 s, window 25 = 0.1163 s (**1.01x**) |
| non-Qt tests | 53 tests / 2.22 s = **0.042 s each** — the 2026-08-12 baseline, unchanged |
| `test_main_window.py` alone | 0.350 s/test against 0.104 s then — the WINDOW grew, not the loop |

No leak. All three 2026-08-12 fixes are still in place (`WeakSet` + a module-level `aboutToQuit`
handler, memoized `setStyleSheet`, `WeakMethod` i18n listeners). It is volume, so the answer is
workers rather than a hunt:

```
498 s serial  ->  65.7 s and 64.2 s on two consecutive runs   (-n auto --dist loadfile, 8-core M1 Pro)
```

Three things about that, all of them load-bearing:

* **The flags live in `pyproject.toml`'s `addopts`, not in the Makefile.** Four things run this
  suite — `make test`, `scripts/ship.py`, and three CI jobs. Flags kept in one caller are exactly
  how "green locally" and "green in CI" drift apart, and a test (`test_ship.py`) now fails if any
  caller grows its own `-n`.
* **`--dist loadfile`, never the default `load`.** Session-scoped `QApplication` and module-level
  state: a whole file pinned to one worker is what keeps that safe. The cost is a tail — the two
  biggest files each sit on one worker, so the run stops improving past about four of them.
  Splitting `test_curve_view.py` (216 tests) and `test_main_window.py` (138) is the next win.
* **A release runs serially.** `scripts/ship.py` passes `-n 0`. Everyday runs are fast because
  eight minutes of waiting changes what a person is willing to check; a release is the one moment
  where that trade goes the other way — one process, one order, the shape this suite's whole
  history was measured in, for eight minutes once, on the day something is published and can
  never be unpublished.

`PYTEST_ADDOPTS='-n 0' make test` is the same switch by hand: use it to debug one test, to read
output in order, or under a debugger.

## The tiered policy that was designed and then not needed (2026-08-12)

The suite really was lopsided:

```
everything except tests/test_main_window.py   676 tests   ~15 s
tests/test_main_window.py                      91 tests   ~4 min 35 s
```

95% of the wall clock in 12% of the tests. A tiered run policy was drafted around that — touched
files while working, the fast set before a commit, the window file before a push, everything plus
the skill's selftests nightly — and it was a sensible response to the measurement.

It was also a workaround. Profiling first turned up something better:

| what | why it cost | fix |
|---|---|---|
| every `MainWindow` handed `self.stop_workers` to `QApplication.aboutToQuit` | a bound method in a Qt signal is a **strong reference held for the life of the process**, so every window ever built stayed alive. `_live_windows` is a `WeakSet` precisely to avoid that, and this one line defeated it | connect the module-level `_stop_all_workers`, which walks the WeakSet and holds nothing |
| `apply_theme` called `setStyleSheet` on every window construction | Qt re-polishes **every widget in the process** on an app-level stylesheet — and with N windows alive that is N windows' worth, every time. Quadratic: window #1 took 0.26 s, #25 took 1.81 s | skip the call when the (mode, scale, qss) is identical to the one already applied |
| `i18n.on_language_changed` kept bound methods in a plain list | the same leak in a second place: a list of bound methods is a list of the widgets they belong to, and it never shrank | hold them with `weakref.WeakMethod`; drop dead ones on the next switch |

```
tests/test_main_window.py:  4 min 38 s  →  9.5 s      (29×)
whole suite:                4 min 53 s  →  30 s
```

**The slow set stopped existing, so it stopped needing a policy.** The tiers were correct about the
symptom and would have institutionalised the cause — every future reader would have learned "the
window tests are slow, that is how it is" instead of "a window leaks itself into the QApplication".
That is the general form worth keeping: when a run policy is being designed around a number,
profile the number first.

## The skill's selftests

`tests/test_skill_selftests.py` runs the vendored skill's `selftest` entry points as subprocesses —
subprocesses because that is what they are, CLI entry points with their own `__main__`, and
importing them would exercise something other than what a person runs by hand.

They are the skill's only tests and nothing ran them: `rew_tool.py selftest` had been failing since
the v3 identity split and went unnoticed for weeks (2026-08-07).

The file also asserts that its own list is complete, by scanning the skill for modules that
dispatch a `selftest` command. On its first run that found **two nobody had ever named** —
`curve_view.py` and `state/migrate.py`, both working, both unrun. The list is checked by a test
rather than by memory for exactly that reason.

## Conventions

* `QT_QPA_PLATFORM=offscreen` is set by `tests/conftest.py`; no display is needed anywhere.
* **Never fake input events.** No `CGEvent`, no synthetic mouse moves — drive the widget's own API
  and assert on its state. Synthetic events have produced false results here before.
* `conftest.py` isolates, in three layers, everything that would otherwise make a result depend on
  whose machine it runs on: QSettings, the project directory, and the machine-level config
  (`~/.config/autosound-tcc`) plus the "which agent CLIs are installed" probe. Two tests were
  reading the developer's real model aliases before that last one existed.
* A test that needs a CLI to be present monkeypatches `model_choices.cli_available` itself; its
  patch runs after the fixture's and wins.

## A fixture takes the AWKWARD shape by default (2026-09-06)

A fixture is written by the same head as the code, so it carries the same assumptions — and a
test built on it cannot see the one thing it most needs to: that the author assumed wrong. Ours
did exactly that. Every capture-round fixture wrote titles in the checklist's own spelling
(`sw_1 (sw)`) and left the round open, so nothing in the suite could tell whether the code
compared identities or strings. It compared strings. A real project — a copy of a working one,
taken from the Windows VM the day before a tag — holds titles as a person types them in REW
(`sw_01 (sw)`) and passes that were closed hours ago. On it, a closed pass with fourteen verified
captures read as fourteen rows still waiting, and the whole suite was green.

So, for anything shaped like a record somebody else writes:

* **titles go in as typed**, zero-padded, while assertions use the derived name (`_as_typed` in
  `tests/test_measurement_view.py`);
* **the pass is closed** unless the test is about an open one;
* **the writer is the other one** — what a session records through the skill, not what the window
  records through its own store.

`pad=False` and friends exist for the tidy case, and a tidy fixture must say why it is tidy.

The rule pays immediately: making the shape awkward turned up a second instance of the same fault
in the same function — a skip and a verdict were also matched as raw strings, so a capture ruled
out by a person and one the arithmetic called unusable were both lost to a zero.

**Not a substitute for real data, and not a dependence on it either.** A copy of a live project is
worth running when one happens to be at hand; it must never become a gate, because the supply of
live projects shrinks as the app stops being tested and starts being used.

## A green run could hide an exception, and did (2026-09-07)

An exception raised inside a Qt slot cannot travel back into C++. PySide6 hands it to
`sys.excepthook`, which prints it to stderr and lets the program carry on — and pytest captures
stderr on a passing test. So the traceback was not merely easy to miss: on `pytest` it was never
printed at all. `pytest -s` showed three of them in `test_main_window.py` while the file reported
"134 passed" (HUB-046).

What they were hiding:

* two hand-written `class Bus` doubles that stopped short of the protocol. `SignalBus` grew
  `pending_count`, `main_window` began reading it from a two-second timer, the doubles never
  followed. The tests were exercising an object the production code could no longer use.
* an actual defect in the window: `_on_effort_changed` read `self._agent_worker` while the model
  combos were still being filled, before anything had set it. Every start of the app raised there.

Two mechanisms came out of it, and both are cheap to keep:

* **`tests/conftest.py` fails the test when a slot raises.** Read the frames, not the heading:
  timers belong to windows earlier tests left alive, so they fire during whoever is running.
* **`tests/test_doubles.py` checks that anything standing in the `bus` slot answers every name the
  production code asks of a bus** — the protocol is read out of `src/` rather than listed, and the
  file carries its own red case so a broken scan cannot pass quietly.

The rule under both: **prefer the real object to a double when the real one is cheap.** `SignalBus`
needs a directory and starts no threads, so both tests now use it — a real bus with nothing acked
IS "the model has not answered yet", and it cannot fall behind itself.

## After a defect: the two questions, out loud

1. **Does this get a regression test?** Not automatically — a test that pins a typo is noise. It
   gets one when the defect was an assumption rather than a slip: something the code believed
   about its data, its platform or its caller.
2. **On which specimen?** **By default, the latest one** — the shape the most recent real
   occurrence had, not the smallest one that reproduces. The smallest case is the author's model of
   the bug; the real one is the bug.
