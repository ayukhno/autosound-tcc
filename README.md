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

One script installs everything, on both platforms, in one of two sizes. It is the same script for
a first install, an update and a removal.

| | what you get | roughly |
| :-- | :-- | --: |
| **Terminal** | the tuning method and the Python packages its tools need. Works on its own, in a terminal. | 30 MB |
| **Terminal + TCC** | plus this desktop app: the DSP tree, the plan, the measurement panel and the curve window | 680 MB |

TCC never works without the skill — the skill writes the project's files, TCC reads them — so
every route below installs the skill, and TCC only if you ask for it.

### macOS

Nothing to download. Open **Terminal** (⌘-Space, type "terminal", Enter) and paste one of these:

```sh
# the method only
curl -fsSL https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.sh | bash -s -- --terminal

# the method and the desktop app
curl -fsSL https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.sh | bash -s -- --tcc
```

Without a flag it asks which. It asks before anything is fetched from the network, and it says
what it is about to run.

**On a machine that has never built anything**, the first run stops and asks you to run
`xcode-select --install` — macOS puts git behind a dialog that a script cannot click. Click
Install, wait, and run the line again.

Downloading the script and double-clicking it is deliberately *not* the route here, and this is
the opposite of Windows for a reason: macOS quarantines anything a browser saved and Gatekeeper
blocks it, so on this platform the pasted line is the smoother path. On Windows the download is
the smoother one, because `cmd` cannot run a PowerShell script at all.

### Windows

1. **[Download the installer](https://github.com/ayukhno/autosound-tuning-skill/archive/refs/heads/main.zip)** — a ZIP, about 2 MB.
2. **Right-click it → Extract All.** Extracting matters: run from inside the ZIP viewer and Windows
   copies the file to a temporary folder where it cannot find its other half.
3. **Double-click `install.cmd`** in the extracted folder.

It asks which of the two sizes you want, and holds the window open at the end so you can read what
happened. To skip the question, run it from a prompt: `install.cmd -Terminal` or `install.cmd -Tcc`.

A ZIP rather than a link straight to the file, because clicking a file on GitHub shows you its
text — the raw link too. Neither downloads anything. The ZIP is the one link a browser reliably
saves, and it brings both halves of the installer with it.

<details>
<summary>Why a <code>.cmd</code>, and why not the PowerShell script directly</summary>

Two things stop a Windows user before they start, and this file removes both.

`cmd` cannot run a PowerShell script at all — a double-clicked `.ps1` opens in Notepad — and a
double-click always opens `cmd`. So `.cmd` is the one thing every Windows user can start, from
anywhere: Explorer, `cmd`, or PowerShell.

And PowerShell refuses to run a script a browser downloaded, under the default execution policy.
The `.cmd` re-launches itself through PowerShell with that policy bypassed **for that one
invocation** — nothing about your machine's settings changes.

All the work is in `install.ps1`, which the `.cmd` finds beside itself or fetches. Two files, one
of them a door: the alternative is the same logic written twice, in two languages, drifting apart.

If you are already in PowerShell and would rather paste a line:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.ps1))) -Tcc
```

The `scriptblock` wrapper is what lets a fetched script take a flag; without one, `irm … | iex`
works and asks which size.
</details>

It installs git and Python with `winget` if they are missing, and links the skill with a
**junction** rather than a symlink — junctions need neither Developer Mode nor an administrator
prompt.

> **Nothing on Windows has been run yet.** Both files mirror the macOS installer, which is tested,
> but no part of either has executed on Windows. Run it once with `-DryRun` first: it changes
> nothing and prints every step, so a first attempt shows exactly where it stops. Reports of where
> it stops are the most useful thing you can send.

### What you still have to do yourself

**Sign in to Claude.** `claude auth login`, once. Neither the skill nor TCC can do it for you:
they drive *your* authenticated session, and a product may not offer a Claude login of its own.
The installer checks and tells you if it is missing.

Nothing else needs an account. Both repositories are public, nothing is pushed anywhere, and no
GitHub login is involved at any point.

A second model as reviewer is optional but is most of the value — the method is built on one
model proposing and a different vendor's disagreeing. The installer reports whether it found
`agy`, `omp` or `gemini`; without one, reviews fall back to the clipboard, which works.

### Updating, and removing

```sh
# macOS — the same line again; a second run updates
curl -fsSL https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.sh | bash -s -- --tcc

# and to remove it
curl -fsSL https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.sh | bash -s -- --uninstall
```

On Windows, `-Tcc` again to update and `-Uninstall` to remove.

**Uninstall never touches a project folder** — not with `--yes`, not ever. Those hold measurements
that took hours in a car and cannot be reproduced. It also leaves the Python packages (shared with
everything else using that interpreter), Claude Code, and `~/.claude`.

### If you would rather do it by hand

The script does five things; each is one command.

```sh
# 1. the skill, at its newest 3.x release
git clone -b v3.0.1 https://github.com/ayukhno/autosound-tuning-skill.git ~/autosound-src
ln -s ~/autosound-src/skills/autosound-tuning ~/.claude/skills/autosound-tuning

# 2. what its tools import (numpy is not optional — five modules do not load without it)
python3 -m pip install --user -r ~/autosound-src/skills/autosound-tuning/requirements.txt

# 3. TCC, if you want the window. `--python` matters: without it uv may pick an interpreter
#    older than TCC needs, and the error reads like a broken package.
uv tool install --python 3.12 'autosound-tcc[gui,claude] @ git+https://github.com/ayukhno/autosound-tcc'

# 4. Claude Code, if it is not already there
curl -fsSL https://claude.ai/install.sh | sh

# 5. sign in
claude auth login
```

Running TCC from a checkout works too, and is what you want if you intend to change it:

```sh
git clone --recurse-submodules https://github.com/ayukhno/autosound-tcc.git
cd autosound-tcc && uv venv && uv pip install -e '.[dev]'
.venv/bin/autosound-tcc
```

### Where TCC looks for the skill

In this order, first hit wins: `$AUTOSOUND_SKILL_DIR`, the `vendor/` submodule of a checkout,
`~/.claude/skills/autosound-tuning`, then skill folders under `~/.claude/plugins/`. It checks that
what it finds is the 3.x line and says so plainly if it is not — a 2.x skill has neither
`project.json` nor the contract checker, and TCC reads through both.

### Starting

```sh
autosound-tcc --project-dir .     # the window, on a project folder
claude                            # then ask it to tune your car
```

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
