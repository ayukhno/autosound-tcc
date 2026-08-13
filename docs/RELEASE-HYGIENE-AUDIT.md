# Release hygiene — the 3.x line as a stranger meets it

A user audit of the skill repository, done 2026-08-13 before that day's installer work, and
re-verified against the repository at the end of it. **Nothing in it had been fixed, two items had
got worse, and one of them now blocks verifying our own work.** Kept here rather than in the skill
repo because this is planning, and TCC's `docs/` is where cross-repo planning already lives (see
`SKILL-CHANGE-REQUESTS.md`, `README-PENDING.md`).

Verified state below is as of 2026-08-13 22:30, skill repo `main` at `8a01e69`.

---

## The one that breaks silently, for the user, immediately

**1. The 3.x instructions do not work if followed literally — in all four languages.**
The section gives exactly three commands:

```
git clone -b v3.0.1 …  →  pip install --user -r …/requirements.txt  →  /plugin marketplace add ~/autosound-3x
```

and stops. **`/plugin install autosound-tuning` is missing**, so the marketplace is registered and
the skill is not installed. The 2.x section immediately below it does give that command
(`README.md:99` and `:169` against `:136`), which is what makes the omission invisible to anyone
reading their own file. The same section warns about a collision "after removing the
marketplace-installed skill" without ever giving `/plugin uninstall autosound-tuning` — the step
whose omission causes the collision it warns about.

Verified still true in `README.md`, `README.uk.md`, `README.de.md`, `README.pl.md`.

## The one that now blocks us

**2. The newest tag is behind `main`, and the gap is exactly this session's fixes.**
`v3.0.2` was tagged 2026-08-13 at `cd25657`; `main` is **7 commits ahead**, and six of those are
the clean-machine installer fixes (Homebrew through `/dev/tty`, the PATH messages, the ordered
next-steps, omp, the repo links) plus the app-icon support in `make-macos-app.sh`.

**Why this bites now.** The one-liner *executes* `install.sh` from `raw.githubusercontent…/main`,
but the skill it *clones* is the newest `v3.*` **tag**. The two halves come from different places.
So on the test machine the running installer already had this session's fixes, while
`$SKILL_SRC/scripts/make-macos-app.sh` — the app builder, taken from the clone — is the v3.0.2
copy, which has no icon support. **The icon cannot appear on the test machine until a new tag
exists**, however many times the installer is re-run.

The README also still says `git clone -b v3.0.1`, now two tags behind.

## The rest, all still true

**3. `install.ps1` is 313 lines that say "NOT YET RUN ON WINDOWS" in their own header** — and
`install.cmd` fetches it from `raw.githubusercontent…/main/install.ps1`, a moving HEAD rather than
a tag. Both files sit in the repository root where they are visible and double-clickable, so a
Windows user can run an unverified installer straight from HEAD.

**4. The installers are documented nowhere.** Zero mentions of `install.sh`, `install.ps1` or
`install.cmd` across all four READMEs (grep: 0/0/0/0). The FAQ's `install.sh` mention is Claude
Code's own installer, not this one. They exist as a conspicuous lure with no instructions —
which is also why §1 above is the documented path and stays broken.

**5. No GitHub releases for the 3.x tags.** Twelve releases exist; `latest` is still **v2.8.1**
(2026-08-12). v3.0.0, v3.0.1 and v3.0.2 are tags with CHANGELOG entries and no release, so the
releases page shows a 2.x line to anyone who looks there first.

**6. The CHANGELOG stops at v3.0.1.** No entry for v3.0.2, no `Unreleased` section for the seven
commits after it, and the installers are described nowhere in it.

**7. The upgrade path for anyone installed before the pin was never reproduced directly.** Left
as accepted risk: the marketplace catalogue carries no 3.x entry at all, so even a wrong
resolution yields the pin or an error, not 3.0.

---

## Order to do them in

1. **Tag** — nothing else can be verified until the clone carries this session's work (§2). A
   `v3.0.3` with the seven commits, and the CHANGELOG entry that §6 wants, are the same task.
2. **Fix §1 in all four READMEs** — one missing line each, and the one item that breaks a real
   person quietly.
3. **Decide about Windows (§3)** — either the `.cmd` pins a tag instead of `main`, or both files
   leave the repository root until someone has run them on Windows once.
4. **§5 releases and §4 documenting the installers** — both are "the project looks abandoned at
   3.x to anyone arriving from outside", and both are cheap once §1 and §2 are done.

`README-PENDING.md` in this directory holds what the READMEs must SAY once they are being edited;
this file holds what is structurally wrong around them.
