# Autosound TCC

**In one line:** a desktop app for car-audio tuning. It gives you a window onto the
[autosound-tuning](https://github.com/ayukhno/autosound-tuning-skill) method, so you can tune a car
without working in a terminal.

- **Shows the whole rig at once**: the DSP tree, crossovers, delays, gains and per-channel EQ
- **Reads REW live**: measurements come over its API — and the curve window predicts what the
  drivers do TOGETHER, so a delay or an all-pass can be tried on the measured curves before
  anything is typed into the DSP and re-swept
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
> **The app works, but it is not released yet.** It runs, reads REW and drives a tuning session,
> and its installer has run from scratch on macOS and on Windows 11. What it has not had yet is a
> full tune driven end to end from the window — the method in a terminal is the proven path.

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
- [Reporting a problem](#reporting-a-problem)
- [License](#license)

## Who it is for

- **Who:** anyone building sound in their own car who would rather work in a window than in a
  terminal. You bring the ears and the hands on the DSP.
- **Why:** the tuning method already exists and it works, but it runs as a conversation with an AI
  in a terminal. Most people who tune cars have never worked that way. TCC does not make the
  tuning decisions easier. It replaces the terminal with a window.

## What you need

**A clean machine is the expected case.** The installer brings its own: Claude Code, Python, the
tuning method, the app itself, and Google's `agy` for the Gemini reviewer. One line, and none of it
has to be there beforehand.

Three things it cannot get for you, because they are yours:

- **[REW](https://www.roomeqwizard.com/) — a beta build**, with its API switched on. This is where
  measurements come from, and TCC's own REW indicator tells you whether it is reachable. **The API
  is in the betas only**: the release version (V5.31.3, July 2024) has no *API* tab in its
  preferences at all, and that is the one a web search hands you — take the build from
  [roomeqwizard.com/beta.html](https://www.roomeqwizard.com/beta.html) instead (downloads at
  AV NIRVANA, the REW forum). Then in REW: open *Preferences → API*, tick **Start the API when REW
  starts** and press **Start server**; the panel then reads *"API server is running on port 4735"*,
  and from then on it comes up with REW. That panel is the same on macOS and Windows; on Windows the
  installer also puts a **REW (API on)** shortcut on your Desktop, which does it in one click.
- **A calibrated measurement microphone, and a DSP.** The hardware half of the job.
- **A paid Claude subscription (Pro or Max).** The skill's FAQ explains
  [the plans and what a session actually costs](https://github.com/ayukhno/autosound-tuning-skill/blob/main/FAQ.md#subscription-options-quotas--budgets-as-of-july-2026).

**A GitHub account is worth having, and it is not needed to install.** Installing asks you to log
in nowhere, and both repositories are public. The reason to have one is your own project, and it
is not the raw sweeps: those run 16 to 112 MB apiece, they stay on your disk, and if you ever
needed them again you would re-measure. What is worth keeping is everything you *concluded* — the
ledger of every crossover, delay, gain and filter, the journal of how you got there, the DSP
config backups that restore the tune, the target curves and the analysis notes. Small files, and
no amount of re-measuring brings them back. The installer asks whether you want them backed up to
a **private** GitHub repository, and if so puts GitHub's `gh` in place and signs it in; the backup
itself happens when you tell the AI to back the project up — it knows what stays out. A free
account covers it.

A second AI as reviewer is optional, but it is where most of the value comes from: the method works
by having one model propose a change and a model from a different vendor argue with it. The
installer brings `agy` for it and offers the sign-in at the end; the
[FAQ](https://github.com/ayukhno/autosound-tuning-skill/blob/main/FAQ.md) covers the rest, and it
can wait until after your first session.

## Install

One line installs, updates and removes, on macOS and on Windows. It installs everything by default
— Claude Code, the method, the app, the Gemini reviewer, and `omp`, which is what lets the app
offer models other than Claude — shows what is already on the machine, lists everything it will
download and where from, asks once, and then runs on its own for ten to twenty minutes. The one
interruption comes right after that question: on a Mac that has never been used for programming it
asks for your Mac password, once, for Apple's Command Line Tools; on
Windows it shows one permission dialog, for Git. At the end it signs you in, in your browser:
Claude first (that one is required), then the reviewer and GitHub if you want them — each on
Enter, or later.

It does not matter which folder you run it from. Everything goes to fixed places: `~/.claude/` for
the method, `~/.local/bin/` for the app and the tools; on macOS the app is also
`~/Applications/Autosound TCC.app` with a shortcut on your Desktop, on Windows a shortcut on your
Desktop and in the Start Menu.

### macOS

Nothing to download. Open Terminal (⌘-Space, type "terminal", press Enter) and paste this line:

```sh
curl -fsSL https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.sh | bash
```

### Windows

Nothing to download either. Open PowerShell (press Start, type "powershell", press Enter) and paste
this line:

```powershell
irm https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.ps1 | iex
```

Everything installs into your user profile except Git for Windows, which is machine-wide and is
the one thing Windows asks permission for.

<details>
<summary>Options, and a double-click alternative for Windows</summary>

To leave something out: `--terminal` (the method only, no app), `--no-reviewer`, `--no-github`,
`--no-omp`. On macOS they go after `bash -s --`:

```sh
curl -fsSL https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.sh | bash -s -- --terminal
```

On Windows the same four are `-Terminal`, `-NoReviewer`, `-NoGitHub`, `-NoOmp`, on this form:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.ps1))) -Terminal
```

Prefer a double-click on Windows?
[Download the repository ZIP](https://github.com/ayukhno/autosound-tuning-skill/archive/refs/heads/main.zip),
right-click it and choose *Extract All* (do not run the file from inside the ZIP), then double-click
`install.cmd`. It runs the same installer and keeps the window open at the end so you can read
what happened. `install.cmd -Terminal` and the other options work there too.
</details>

<details>
<summary>Installing by hand, six commands</summary>

Get the method, at its newest 3.x release (v3.0.4 as of August 2026 — the tags are on GitHub):

```sh
git clone -b v3.0.4 https://github.com/ayukhno/autosound-tuning-skill.git ~/autosound-src
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

On Windows the same steps use a junction instead of the symlink (`New-Item -ItemType Junction`),
`python3` from `uv python install 3.12 --default`, and `--break-system-packages` on the pip line;
the installer does all of that, which is the argument for using it.
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

**Starting the app.** Double-click **Autosound TCC** on your Desktop. It asks which folder:
*Browse…* to the car's folder — a new, empty one is right — and pick the models: Claude Opus (SDK)
as *AI main*, Gemini Pro (High) as *AI critic*. Press *Open*. Then you work in the dialog panel on
the right, in any language. Say what you want to do, for example *"let's tune this car from
scratch"*, and it takes you through the phases. On Windows, start REW from the **REW (API on)**
shortcut the installer put beside it, so its API is up.

From a terminal the same is:

```sh
autosound-tcc --project-dir ~/Autosound/my-car
```

TCC remembers the folder, so next time the app reopens the same car. To switch cars, run
`autosound-tcc --choose-project`, or start it from inside another car's folder.

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

To update, run the same install line again. It fetches the newest version of everything and leaves
the rest alone — nothing is asked twice, and the sign-ins it already has are kept.

To remove, on macOS:

```sh
curl -fsSL https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.sh | bash -s -- --uninstall
```

On Windows:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/main/install.ps1))) -Uninstall
```

> [!IMPORTANT]
> **Removing never deletes a project folder.** That folder is the tune itself: the ledger, the
> process journal, the DSP config backups and the sweeps. Nothing in this installer will touch it.
> It also leaves Claude Code, Git, the Python packages and the reviewer alone, because other things
> on your machine may use them; `--uninstall --all` / `-Uninstall -All` takes those too, and says
> what it is about to remove before it does.

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

Run the tests with `.venv/bin/python -m pytest`.

Every dependency carries an upper version bound, and a test fails if one does not. An open-ended
requirement means that whoever installs this in six months gets whatever exists on that day.

TCC finds the skill by looking, first hit wins, at `$AUTOSOUND_SKILL_DIR`, the `vendor/` submodule
of a checkout, `~/.claude/skills/autosound-tuning`, and then skill folders under
`~/.claude/plugins/`. It needs the 3.x line and says so plainly if what it finds is older: only
3.x has `project.json` and the contract checker, and TCC reads both.
</details>

## Reporting a problem

Anything that broke or was wrong: **[open an issue](https://github.com/ayukhno/autosound-tcc/issues/new/choose)**.
The app fills in the half nobody can assemble by hand — open the diagnostics window, go to
**Installation** and press **Report a problem**: the form opens with the versions, the paths and
the tool list already in it. The **Log** tab beside it has its own Copy button for the field
underneath. Problems with the tuning method itself belong
[in the skill's repository](https://github.com/ayukhno/autosound-tuning-skill/issues/new/choose).

## License

Apache-2.0, see [LICENSE](LICENSE).
