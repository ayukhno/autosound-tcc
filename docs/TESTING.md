# Testing

## The policy

**Run everything, every time.** `python3 -m pytest tests/ -q` — 783 tests, ~30 seconds, and that
includes the skill's own ten selftests as subprocesses.

There is deliberately no fast/slow split, and it is worth writing down why, because there nearly
was one.

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
