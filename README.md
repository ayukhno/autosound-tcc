# autosound-tcc

Cross-platform (macOS + Windows) desktop app for car-audio tuning:
a **Tuning Command Center** and a **Guided Setup Wizard**.

**The barrier it lowers is the terminal, not the tuning.** The method lives in the
[`autosound-tuning`](https://github.com/ayukhno/autosound-tuning-skill) skill and it works on its
own, in a terminal, driven by an AI — which is a fluent way to work and an unfamiliar one for most
people who tune cars. TCC is the same method with a window on it: the DSP state, the plan, the
measurements and the curves visible at once, and the conversation in a panel instead of a scroll
of text. It does not make the tuning decisions easier; it makes the tool ordinary.

It does not write to the processor. Automated DSP writes stay out of scope until the safety work
behind them is done.

> **Status: working, not released.** The app runs, reads REW, drives a tuning session and carries
> 864 tests. It is not on PyPI, so every route below installs from source, and the Windows
> installer has not yet been run on Windows. Everything written here has been executed except
> where it says otherwise.

## Scope of the first version

- **Read-only against the processor.** TCC connects to
  [REW](https://www.roomeqwizard.com/) (local API on `localhost:4735`), reads the current
  measurement and filter state, and shows crossovers, delays, gains, EQ and curves. Changes to the
  DSP are typed in by a person, as they always were.
- **The project's files are the skill's.** The skill writes them, TCC reads them. That boundary is
  what lets the same project be worked on from a terminal one day and the window the next.

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

The method only:

```sh
curl -fsSL https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.sh | bash -s -- --terminal
```

The method and the desktop app:

```sh
curl -fsSL https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.sh | bash -s -- --tcc
```

Without a flag it asks which. It asks before anything is fetched from the network, and it says
what it is about to run.

It does not matter which folder you are standing in: everything goes to fixed places, never into
the current directory.

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

Updating is the same command as installing — a second run fetches the newest release and leaves
everything else alone.

macOS, update:

```sh
curl -fsSL https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.sh | bash -s -- --tcc
```

macOS, remove:

```sh
curl -fsSL https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.sh | bash -s -- --uninstall
```

Windows, update and remove, if you still have the extracted folder:

```bat
install.cmd -Tcc
```

```bat
install.cmd -Uninstall
```

If you deleted it — which is fine, it is scratch — paste this into PowerShell instead. Update:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.ps1))) -Tcc
```

Remove:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.ps1))) -Uninstall
```

**Uninstall never touches a project folder** — not with `--yes`, not ever. Those hold measurements
that took hours in a car and cannot be reproduced. It also leaves the Python packages (shared with
everything else using that interpreter), Claude Code, and `~/.claude`.

### If you would rather do it by hand

The script does six things. Each is one command, and none of them depend on the folder you
run them from.

Get the method, at its newest 3.x release:

```sh
git clone -b v3.0.1 https://github.com/ayukhno/autosound-tuning-skill.git ~/autosound-src
```

Put it where Claude Code looks. On a machine that has never run Claude Code the `skills` folder
does not exist yet, hence the `mkdir`:

```sh
mkdir -p ~/.claude/skills && ln -s ~/autosound-src/skills/autosound-tuning ~/.claude/skills/autosound-tuning
```

Install what its tools import. `numpy` is not optional — five of them do not load without it:

```sh
python3 -m pip install --user -r ~/autosound-src/skills/autosound-tuning/requirements.txt
```

Install the app, if you want the window. The `--python` matters: without it `uv` may pick an
interpreter older than TCC needs, and the error reads like a broken package:

```sh
uv tool install --python 3.12 'autosound-tcc[gui,claude] @ git+https://github.com/ayukhno/autosound-tcc'
```

Install Claude Code, if it is not already there:

```sh
curl -fsSL https://claude.ai/install.sh | sh
```

Sign in:

```sh
claude auth login
```

Running TCC from a checkout works too, and is what you want if you intend to change it:

```sh
git clone --recurse-submodules https://github.com/ayukhno/autosound-tcc.git
```

```sh
cd autosound-tcc && uv venv && uv pip install -e '.[dev]'
```

```sh
.venv/bin/autosound-tcc
```

### Where TCC looks for the skill

In this order, first hit wins: `$AUTOSOUND_SKILL_DIR`, the `vendor/` submodule of a checkout,
`~/.claude/skills/autosound-tuning`, then skill folders under `~/.claude/plugins/`. It checks that
what it finds is the 3.x line and says so plainly if it is not — a 2.x skill has neither
`project.json` nor the contract checker, and TCC reads through both.

### Three folders, and which is which

This trips people up, so plainly:

| folder | what it is | keep it? |
| :-- | :-- | :-- |
| wherever you ran the installer | nothing lands here | delete it |
| `~/.claude/skills/`, `~/.local/bin/` | the method and the app | the installer manages these |
| **your project, one per car** | your measurements and the tune | **this is the one that matters** |

The install folder is scratch. On macOS the one-liner leaves nothing behind at all; on Windows the
folder you extracted the ZIP into can go in the bin once the installer has finished.

A project is a folder you make, one per car, anywhere you keep your own files:

```sh
mkdir -p ~/Autosound/my-car
```

Do not put it inside the installer folder, inside `~/.claude`, or inside a checkout of either
repository — those get replaced on update. Keep it where your backups already reach. Everything
about a car lives in its folder, so moving or copying that one folder moves the whole tune.

### Starting, the first time

**In a terminal.** Stand in the project folder and start Claude:

```sh
cd ~/Autosound/my-car
```

```sh
claude
```

Then tell it what you are doing — "let's tune this car", in any language. On an empty folder it
runs the intake interview: the car, the processor, the channel map, the microphone. That interview
is what creates the project, so there is nothing to set up beforehand.

**In the window.** Point TCC at the same folder:

```sh
autosound-tcc --project-dir ~/Autosound/my-car
```

It remembers, so afterwards `autosound-tcc` alone reopens that car — and from the macOS app,
double-clicking does the same. To work on a different car:

```sh
autosound-tcc --choose-project
```

The two are the same project. Start in the window, continue in the terminal, come back — the files
are the shared state, and both read them fresh.

**Before the first measurement**, REW must be running with its API enabled: *Preferences → API*,
then check that `localhost:4735` answers. TCC carries a REW indicator that goes red when it cannot
reach it; the terminal route just finds no measurements, which reads like a bug and is not one.

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
