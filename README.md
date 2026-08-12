# autosound-tcc

Cross-platform (macOS + Windows) desktop app for car-audio tuning:
a **Tuning Command Center** and a **Guided Setup Wizard**.

The goal is to lower the barrier to entry for people who are not tuning
experts — show the current state of a system clearly, and guide the manual
steps — rather than to automate the DSP.

> **Status: working, not released.** The app runs, reads REW, drives a tuning
> session and has a test suite. It is not on PyPI and there are no installers
> yet, so every route below installs from source. Install instructions describe
> only what has actually been run end to end.

## Scope of the first version

- **Read-only.** The app connects to [REW](https://www.roomeqwizard.com/)
  (local API on `localhost:4735`), reads the current measurement and filter
  state, and displays crossovers, delays, gains, EQ and frequency-response
  curves.
- **No DSP writes.** The app does not change processor settings. Automated
  writing is deliberately out of scope until the safety work behind it is
  done.

## Install

There are two pieces and they are separate on purpose:

- **the skill** (`autosound-tuning`) — the tuning method itself. Plain Python.
  It works on its own, in a terminal, with no TCC at all. It needs `numpy`
  (imported at module scope by five of its tools, which do not load without
  it); `scipy` and `matplotlib` are feature dependencies, imported at the point
  of use, and their absence costs one feature rather than a session. Its
  `requirements.txt` lists all three.
- **TCC** — this app. It never works without the skill: the skill writes the
  project's files, TCC reads them.

Install the skill first.

### 1. The skill

Clone it anywhere:

```sh
git clone https://github.com/ayukhno/autosound-tuning-skill.git
```

Then tell TCC where it is, by either of these:

```sh
# a) point at the clone
export AUTOSOUND_SKILL_DIR=/path/to/autosound-tuning-skill/skills/autosound-tuning

# b) or put it where Claude Code keeps skills, and TCC finds it with no variable
ln -s /path/to/autosound-tuning-skill/skills/autosound-tuning \
      ~/.claude/skills/autosound-tuning
```

Then install what its tools need:

```sh
python3 -m pip install -r /path/to/autosound-tuning-skill/skills/autosound-tuning/requirements.txt
```

Skipping this leaves the method usable but takes crossover selection, the EQ
gate, the DSP maths and plot rendering with it — those five modules import
`numpy` at module scope and do not load without it.

TCC looks in this order, first hit wins: `$AUTOSOUND_SKILL_DIR`, the
`vendor/` submodule of a checkout, `~/.claude/skills/autosound-tuning`, then
skill folders under `~/.claude/plugins/`.

### 2. TCC

[`uv`](https://docs.astral.sh/uv/) is the recommended route because it installs
a suitable Python itself, which removes the most common failure on Windows.

Two things are extras, and both for the same reason — they are choices, and
each one is hundreds of megabytes:

- `gui` — the window. Qt is most of the download.
- `claude` — the Claude Agent SDK, needed only if a **Claude** model drives the
  session. Every other model (Gemini, Codex, …) goes through the `omp` CLI and
  needs no Python package at all.

```sh
# CLI only, driven by Gemini/Codex through omp
uv tool install 'autosound-tcc @ git+https://github.com/ayukhno/autosound-tcc'

# the window, driven by Gemini/Codex
uv tool install 'autosound-tcc[gui] @ git+https://github.com/ayukhno/autosound-tcc'

# the usual one: the window, with Claude available too
uv tool install 'autosound-tcc[gui,claude] @ git+https://github.com/ayukhno/autosound-tcc'
```

Measured on macOS/arm64: 29 MB for the base, 394 MB with the window, 678 MB
with the window and Claude. Asking for something that is not installed prints
the command that adds it — the window and the Claude route both do — rather
than a traceback about a module you have never heard of.

`pip install` works the same way if you would rather not use `uv`. So does
running from a checkout:

```sh
git clone --recurse-submodules https://github.com/ayukhno/autosound-tcc.git
cd autosound-tcc
uv venv && uv pip install -e '.[dev]'
.venv/bin/autosound-tcc
```

### What else you need

- **Python 3.11+** — or nothing, if you use `uv`, which brings its own.
- **REW** with its API enabled, for anything involving measurements.
- **A model, and a way to reach it.** For Claude: the `claude` CLI, logged in,
  plus the `claude` extra above — TCC authenticates to nothing itself, it uses
  your own login. For anything else: `omp` on your PATH and
  whichever vendor CLI it drives.
- Nothing here removes the Claude Code step for the Claude route. TCC talks to
  a locally-authenticated session; it cannot offer you a login of its own.

## Stack

Python + PySide6 (Qt), with `pyqtgraph` for curves. The tuning engine is
Python already, so the app reuses it directly rather than bridging languages.

Every dependency carries an upper version bound, and a test refuses one that
does not: an open-ended requirement means whoever installs this in six months
gets whatever exists that day, which is not a version policy.

## Related projects

- [`autosound-tuning-skill`](https://github.com/ayukhno/autosound-tuning-skill)
  — the tuning knowledge base and tooling this app builds on.

## License

Apache-2.0 — see [LICENSE](LICENSE).
