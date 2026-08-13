# Autosound TCC

**In one line:** a desktop app for car-audio tuning. It gives you a window onto the
[autosound-tuning](https://github.com/ayukhno/autosound-tuning-skill) method, so you can tune a car
without working in a terminal.

- **Shows the whole rig at once**: the DSP tree, crossovers, delays, gains and per-channel EQ
- **Reads REW live**: measurements come over its API, and you can drag delay markers on the curves
- **Keeps the plan in view**: the phase you are on, what is done, what is still waiting
- **Puts the AI in a panel**, instead of a terminal full of scrolling text
- **Never writes to your processor**: nothing reaches the DSP unless you put it there. EQ does
  not have to be retyped, though. REW exports a file the Helix PC-Tool imports in one go, and a
  [copy-paste helper](https://github.com/IvanBakhmutov/REW-EQ-CopyPaste-Assistant) covers
  processors without file import

> [!CAUTION]
> AI gets numbers wrong. Check crossover frequencies, slopes and EQ values in your DSP before you
> unmute, especially on tweeters, and start quiet.

> [!NOTE]
> **The app works, but it is not released yet.** It runs, reads REW and drives a tuning session.
> The Windows installer has never been run on Windows.

The method itself is documented in several languages:
[Deutsch](https://github.com/ayukhno/autosound-tuning-skill/blob/main/README.de.md) ·
[Polski](https://github.com/ayukhno/autosound-tuning-skill/blob/main/README.pl.md) ·
[Українська](https://github.com/ayukhno/autosound-tuning-skill/blob/main/README.uk.md)

## Table of contents

- [Who it is for](#who-it-is-for)
- [What you need](#what-you-need)
- [Install](#install)
- [Your first project](#your-first-project)
- [Updating and removing](#updating-and-removing)
- [What's in here](#whats-in-here)
- [License](#license)

## Who it is for

- **Who:** anyone building sound in their own car who would rather work in a window than in a
  terminal. You bring the ears and the hands on the DSP.
- **Why:** the tuning method already exists and it works, but it runs as a conversation with an AI
  in a terminal. Most people who tune cars have never worked that way. TCC does not make the
  tuning decisions easier. It replaces the terminal with a window.

## What you need

**A clean machine is the expected case.** The installer brings its own: Claude Code, Python, the
tuning method, the app itself. One command, and none of it has to be there beforehand.

Three things it cannot get for you, because they are yours:

- **[REW](https://www.roomeqwizard.com/)**, with its API switched on. Install it, open
  *Preferences → API*, and tick **Start the API when REW starts**. That is the whole setup, and it
  means the API is up every time instead of you pressing *Start server* each session. TCC's own REW
  indicator tells you whether it is reachable. This is where measurements come from.
- **A calibrated measurement microphone, and a DSP.** The hardware half of the job.
- **A paid Claude subscription.** The skill's FAQ explains
  [the plans and what a session actually costs](https://github.com/ayukhno/autosound-tuning-skill/blob/main/FAQ.md#subscription-options-quotas--budgets-as-of-july-2026).

**A GitHub account is worth having, and it is not needed to install.** Installing asks you to log
in nowhere, and both repositories are public. The reason to have one is your own project, and it
is not the raw sweeps: those run 16 to 112 MB apiece, they stay on your disk, and if you ever
needed them again you would re-measure. What the method commits is everything you *concluded* —
the ledger of every crossover, delay, gain and filter, the journal of how you got there, the DSP
config backups that restore the tune, the target curves and the analysis notes. Small files, and
no amount of re-measuring brings them back. So it sets up a git backup when you start a project
and keeps feeding it; pointing that at a **private** repository is the cheapest insurance there is
against a dead disk. A free account covers it.

A second AI as reviewer is optional, but it is where most of the value comes from: the method works
by having one model propose a change and a model from a different vendor argue with it. The
[FAQ](https://github.com/ayukhno/autosound-tuning-skill/blob/main/FAQ.md) covers how to add one,
and it can wait until after your first session.

## Install

One script installs, updates and removes, on both macOS and Windows. It offers two sizes:

| | what you get | roughly |
| :-- | :-- | --: |
| **The app** | the desktop window, plus the method it reads | 680 MB |
| **Method only** | no window; you work in a terminal | 30 MB |

It does not matter which folder you run it from. Everything goes to fixed places: `~/.claude/`
for the method and `~/.local/bin/` for the app.

### macOS

Nothing to download. Open Terminal (⌘-Space, type "terminal", press Enter) and paste this line:

```sh
curl -fsSL https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.sh | bash
```

It asks which of the two sizes you want — for this app, answer **2**. Then it lists everything it
is about to download, and where each piece comes from, and asks once before any of it happens.

On a Mac that has never been used for programming, the script stops and asks you to run
`xcode-select --install` first. macOS installs git through a dialog box, and a script cannot click
that dialog for you. Click Install, wait for it to finish, then paste the line again.

### Windows

> [!WARNING]
> **The Windows installer has never been run on Windows.** It mirrors the macOS one, which is
> tested, but no part of it has executed on Windows yet. Run it once with `-DryRun` first: that
> changes nothing and prints every step it would take. If it stops somewhere, telling us where is
> genuinely useful.

1. **[Download the installer](https://github.com/ayukhno/autosound-tuning-skill/archive/refs/heads/main.zip)**, a ZIP file of about 2 MB.
2. **Right-click the ZIP and choose Extract All.** Do not open the ZIP and run the file from
   inside it. Windows would copy that one file to a temporary folder, away from the other files it
   needs.
3. **Double-click `install.cmd`** in the folder you extracted.

It asks which of the two sizes you want, and keeps the window open at the end so you can read what
happened. To skip the question, open a command prompt and run `install.cmd -Tcc` (or
`install.cmd -Terminal`).

Installing the method itself needs no administrator rights. If git or Python are missing, it
offers to install them too, and Windows may ask for permission at that point.

<details>
<summary>Why a ZIP, when GitHub just shows you the file</summary>

Clicking a file on GitHub shows you its text, and so does the "raw" link. Neither one downloads
anything, which is where most people get stuck. A ZIP is the one link a browser reliably saves,
and it brings the whole installer with it rather than half of it.

The file you double-click is `install.cmd`, but the real work is in `install.ps1` beside it.
Windows needs both. A double-click always opens the old `cmd`, which cannot run a PowerShell
script at all, and PowerShell by default refuses to run any script that came from a browser. The
`.cmd` is a small door that gets past both, for that one run, without changing any setting on your
machine.

If you already use PowerShell, you can paste this instead:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.ps1))) -Tcc
```
</details>

<details>
<summary>Installing by hand, six commands</summary>

Get the method, at its newest 3.x release:

```sh
git clone -b v3.0.1 https://github.com/ayukhno/autosound-tuning-skill.git ~/autosound-src
```

Put it where Claude Code looks for skills. On a machine that has never run Claude Code that folder
does not exist yet, hence the `mkdir`:

```sh
mkdir -p ~/.claude/skills && ln -s ~/autosound-src/skills/autosound-tuning ~/.claude/skills/autosound-tuning
```

Install the Python packages its tools import. `numpy` is not optional: five of them will not load
without it.

```sh
python3 -m pip install --user -r ~/autosound-src/skills/autosound-tuning/requirements.txt
```

Install the app. Name the Python version explicitly: without it, `uv` may pick one older than TCC
needs, and the error message will look as if the package is broken.

```sh
uv tool install --python 3.12 'autosound-tcc[gui,claude] @ git+https://github.com/ayukhno/autosound-tcc'
```

Install Claude Code, if you do not have it:

```sh
curl -fsSL https://claude.ai/install.sh | sh
```

Sign in:

```sh
claude auth login
```
</details>

## Your first project

Make one folder per car, anywhere you keep your own files:

```sh
mkdir -p ~/Autosound/my-car
```

Keep it away from the folder you installed from, from `~/.claude`, and from any copy of the two
repositories, because those get replaced when you update. Everything about a car lives in its own
folder, so copying that folder copies the whole tune. The folder you ran the installer from holds
nothing and can be deleted.

**Starting the app.** Point it at that folder the first time:

```sh
autosound-tcc --project-dir ~/Autosound/my-car
```

On an empty folder it asks a few setup questions: the car's processor, and which AI models to use.
After that you work in the dialog panel on the right, in any language. Say what you want to do,
for example *"let's tune this car from scratch"*, and it takes you through the phases.

TCC remembers the folder, so next time `autosound-tcc` on its own reopens the same car, and so
does double-clicking the app on macOS. To switch cars, run `autosound-tcc --choose-project`.

**Starting in a terminal instead.** The same project also opens without the window:

```sh
cd ~/Autosound/my-car
```

```sh
claude
```

Then say the same thing you would have said in the panel.

The two are one project, not two. The skill writes the project's files and TCC reads them, so you
can work in the window one day and the terminal the next and find everything where you left it.

## Updating and removing

To update, run the install command again. It fetches the newest version and leaves everything else
alone.

On macOS, update:

```sh
curl -fsSL https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.sh | bash -s -- --tcc
```

On macOS, remove:

```sh
curl -fsSL https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.sh | bash -s -- --uninstall
```

On Windows, from the folder you extracted:

```bat
install.cmd -Tcc
```

```bat
install.cmd -Uninstall
```

If you already deleted that folder, which is fine, open PowerShell and paste this to update:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.ps1))) -Tcc
```

Or this to remove:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.ps1))) -Uninstall
```

> [!IMPORTANT]
> **Removing never deletes a project folder.** That folder is the tune itself: the ledger, the
> process journal, the DSP config backups and the sweeps. Nothing in this installer will touch it.
> It also leaves Claude Code and the Python packages alone, because other things on your machine
> use them.

## What's in here

The app is Python and Qt (PySide6), with `pyqtgraph` drawing the curves. The tuning method it
reads is a separate project:
[`autosound-tuning-skill`](https://github.com/ayukhno/autosound-tuning-skill).

<details>
<summary>For developers</summary>

To run TCC from a checkout:

```sh
git clone --recurse-submodules https://github.com/ayukhno/autosound-tcc.git
```

```sh
cd autosound-tcc && uv venv && uv pip install -e '.[dev]'
```

```sh
.venv/bin/autosound-tcc
```

There are 864 tests: `.venv/bin/python -m pytest`.

Every dependency carries an upper version bound, and a test fails if one does not. An open-ended
requirement means that whoever installs this in six months gets whatever exists on that day.

TCC finds the skill by looking, first hit wins, at `$AUTOSOUND_SKILL_DIR`, the `vendor/` submodule
of a checkout, `~/.claude/skills/autosound-tuning`, and then skill folders under
`~/.claude/plugins/`. It needs the 3.x line and says so plainly if what it finds is older: only
3.x has `project.json` and the contract checker, and TCC reads both.
</details>

## License

Apache-2.0, see [LICENSE](LICENSE).
