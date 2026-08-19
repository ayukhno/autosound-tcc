# What the READMEs will have to say — recorded, not written

Notes for whoever picks up `docs/readme-review` in the skill repo (and TCC's own README). **This
file changes no README.** It exists because the install flow moved a lot on 2026-08-13, during the
first from-scratch test on a second Mac, and the documentation still describes the old one.

Rule for every line below: it is written here in engineering terms and belongs in the README in
**one short, plain sentence for somebody who has never opened a terminal before**. If an item
cannot survive that compression, it does not belong in a README at all — it belongs in the FAQ or
in nothing.

Which README each item lands in is marked: **[skill]** = `README.md` + the three translations,
**[tcc]** = TCC's own README.

---

> **2026-08-17, later:** the text has now been WRITTEN — skill `README.md` + `FAQ.md` on branch
> `docs/readme-review` (rebased onto main, pushed, commit 793072e) and TCC `README.md` on main
> (c29c1a1), with the shared paragraphs (REW, GitHub, install, first project) kept identical in
> substance. The branch is still not merged: that merge is the release act, gated on the
> MacBookAir run (planned 2026-08-18) — see the gate section at the end. Still to do after the
> merge: the uk/de/pl translations (line-for-line port of the new English), GitHub Releases for the
> v3.0.x tags, and TCC's screenshot.

## 2026-08-17 — the installer was rebuilt; the 08-13 items below are superseded where they clash

The flow is now **two blocks**, and the README's getting-started should be written as exactly
that — nothing in between needs the reader:

1. **Paste the one line.** It shows what is already on the Mac, asks one optional question (*back
   projects up to a private GitHub repository?*), lists everything it will download, and asks
   *Go ahead?* once. **On a Mac without Apple's Command Line Tools it then asks for the Mac
   password — once, right there — and that is the only password in the whole install.** Homebrew
   is gone; nothing else needs an administrator. Then 10–20 minutes with nobody at the keyboard.
2. **Sign in, at the end, in the browser.** The installer runs `claude auth login` itself (Enter
   opens the browser; Authorize), then offers the Gemini reviewer's sign-in (`agy` — Google
   account; on some accounts a Project ID from `aistudio.google.com/app/apikey`) and, if asked
   for, GitHub's (`gh auth login --web`). Each is Enter = now, s = later. Then: REW → Preferences →
   API → *Start the API when REW starts*; double-click **Autosound TCC** on the Desktop.

**[skill] "It asks which of two sizes you want" is no longer true.** Everything is the default —
the method, the app, the reviewer. `--terminal` leaves the app out, `--no-reviewer` the reviewer,
`--no-github` skips the question; through the one-liner they go after `bash -s --`. The README
should say the default and name the flags in one sentence, not describe a menu.

**[skill] `omp` is NOT installed by default any more** (`--with-omp`). It is the metered route.
The 08-13 line "without it that dialog is empty" is still true and is now the intended state for a
first install: the recommended pair (Claude through the SDK, Gemini through `agy`) does not need
it.

**[skill] "Open a new terminal" disappears from the app path.** The .app finds its own tools, and
the installer runs the Claude sign-in with a full path. Only the `--terminal` path says "open a
NEW Terminal window", and that is the whole PATH story a reader needs.

**[skill] A GitHub question exists now (SCR-049 §2), and the backup itself is still unscripted
(§1).** The installer installs `gh` and signs it in when asked; the README may say that, and may say
"ask the AI to back the project up" — it must still not say the method *offers* it on its own.

**[skill] Windows has an installer that has actually run (2026-08-17, Windows 11 25H2 in a VM).**
The README's Windows path is one line in PowerShell — `irm https://raw.githubusercontent.com/
ayukhno/autosound-tuning-skill/main/install.ps1 | iex` — or a double-click on `install.cmd`;
same two blocks as the Mac. What to say that differs from the Mac: the one interruption is a
Windows permission dialog (UAC) for **Git for Windows**, not a password, and only when Git is
missing; everything else lands in the user profile; the shortcuts are on the Desktop and in the
Start Menu; the reviewer's doctor runs in **Git Bash**. Options are `-Terminal`, `-NoReviewer`,
`-NoGitHub` on the scriptblock form (`& ([scriptblock]::Create((irm …))) -Terminal`). The
interactive sign-in block has run there too (Claude in the browser, agy's TUI, gh's device code —
gh asks one extra "Authenticate Git with your GitHub credentials?", answer Yes). REW detection has
run on a PC with REW too. The installer puts a **"REW (API on)"** shortcut on the Desktop
(`roomeqwizard.exe -api`, REW's own switch) — one click that cannot be forgotten.

~~**Windows REW has no "start the API when REW starts" box.**~~ **Wrong, corrected 2026-08-19.**
It was never a platform difference: the API arrived in REW's 5.40 betas, and the release build
(V5.31.3, July 2024) — which is what a web search hands you, and what that PC had — has no *API*
tab at all. On a beta the panel is identical on macOS and Windows. Both READMEs and both installers
now say: take a beta from roomeqwizard.com/beta.html (downloads at AV NIRVANA), then tick the box.

**[skill] The app's icon needs the next tag.** `make-macos-app.sh` is fixed on `main`, but the
clone is the tag, so `v3.0.4` (or later) is what makes the icon appear on a fresh install.

## Things that were true on 2026-08-13 and are not written down anywhere

**[skill] ~~The install stops and asks for your Mac password.~~** Superseded above: the password is
asked once at the start, only when Apple's Command Line Tools are missing, and Homebrew is gone.

**[skill] The reviewer really does get installed now.** The README can stop hedging about setting
Gemini up by hand: the one-liner installs Antigravity (`agy`) — now through Google's own installer,
no Homebrew — and the installer offers the sign-in at the end. What still has to be done by hand,
once, is that sign-in (Google account; sometimes a Project ID from `aistudio.google.com/app/apikey`).

**[skill] ~~`omp` is installed too.~~** Superseded above: `--with-omp` only.

**[skill] ~~The "what to do next" list is now ordered and grouped~~** — superseded by the two-block
flow above; there is no list to mirror any more, only "sign in, then start".

**[skill] You need a Claude login and nothing can do it for you.** Already true, already written,
but it is now also enforced on screen (TCC marks the picker when the Claude route has no login),
so the README and the app finally agree. Worth one sentence, not a paragraph.

**[tcc] The app has a name and an icon.** "Autosound TCC" in the Dock and the menu bar instead of
"python3.12", its own icon, and a shortcut on the Desktop. Only relevant to the README as a
screenshot: whatever picture is eventually taken now shows the real thing.

**[tcc] The first minute on a new project.** A brand-new project folder has no contract and no
context, so the reviewer answers "nothing to read yet — start the tune". That is the normal first
state, not a fault, and a reader who meets it before the README mentions it will file a bug.
Two sentences, in the getting-started part.

**[tcc] Where the logs are.** `~/Library/Logs/autosound-tcc/tcc.log`. It now also collects the
library warnings that used to print on launch, so "the terminal is quiet" is only true because
they went somewhere — say where, in the troubleshooting section.

## Things the READMEs must NOT say yet

**The GitHub backup is not offered by the installer.** Both rewritten READMEs recommend an account
for it; the installer does not ask, and nothing in the skill or TCC scripts it — the AI can do it
when it thinks of it, and that is all. Tracked as **SCR-049**. Until that lands, the READMEs may
recommend an account, but must not describe an offer that does not exist.

## Still open from the earlier README review

Unchanged by this session, repeated here so the list is in one place: **no screenshot** of the
window in TCC's README, and **the three translations (de/pl/uk) are out of sync** with the
rewritten English — mechanical to port, but it must happen before the merge or a non-English
reader gets the old version.

## And the gate itself

Merging `docs/readme-review` is the act of making 3.x the default for everyone arriving from a web
search, because the README leads new readers through `install.sh` and that script installs the
newest `v3.*` tag. It is gated on the clean-machine test finishing — which is the work that
produced this file, and which has not yet been run once end to end with everything in place.
