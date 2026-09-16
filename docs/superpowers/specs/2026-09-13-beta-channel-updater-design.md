# Beta channel in the updater — design

Hub ticket #140 (HUB-061), ask 1 of 3. Asks 2 and 3 landed on 2026-09-13: `make ship CANDIDATE=` in
PR #30, `## [Unreleased]` and the `### Breaking` form in PR #29 and #30.

**Status:** answered by the user on 2026-09-14 (see the end). TCC's own half is built first; the
method half waits for hub #145 (TCC-011).

**Built 2026-09-16** (TCC's half, on `wave-0.1.40`): plan `docs/superpowers/plans/2026-09-16-beta-channel-updater.md`. Hub #145 is closed (skill v3.0.52); the method half is not built — the Arbiter needs only tags (`docs/TODO.md` F-058, dropped 2026-09-16).

## What is asked

> `updates.py`: a channel setting — stable (default, unchanged) and beta, which also lists
> `beta-v*` for both the method and TCC, ordered by the key in RELEASE-CHANNEL.md §11.2; the
> self-check row reads the chosen channel. Why: a candidate reaches the app of whoever tries it,
> and nobody on stable.

The contract, hub `governance/RELEASE-CHANNEL.md` §11.2:

| channel | takes | order |
|---|---|---|
| stable (default) | `vX.Y.Z` of the line | as today |
| beta | `vX.Y.Z` **and** `beta-vX.Y.Z-rcN` of the same line | release `(X,Y,Z,1,0)`, candidate `(X,Y,Z,0,N)` |

The skill already carries the same contract in its installers (HUB-060, v3.0.50):
`install.sh --channel beta`, `install.ps1 -Channel beta`, `SKILL_BETA_GLOB="beta-v3.*"`,
`TCC_BETA_GLOB="beta-v*"`, `newest_on_channel`. This design mirrors it.

## What exists

- `core/updates.py` (Qt-free, runs on a worker thread): `SKILL_TAG_GLOB = "v3.*"`,
  `TCC_TAG_GLOB = "v*"`, `_version_key` keeps every digit, `_newest_tag_in(repo, glob)` lists one
  glob with `ls-remote` and peels annotated tags. `check_skill` compares by **commit**, `check_tcc`
  by **version**. `apply_skill(tag="")` fetches `newest_tag()`.
- Callers: `ui/tcc/diagnostics_panel.py` (update row, `_UpdateProbe` → `updates.check_all()`,
  `apply_skill()`, `tcc_install_line(tag=updates.newest_tcc_tag())`) and
  `ui/tcc/main_window.py:_check_for_updates` (title note).
- `core/self_check.py:_pin_check` — for a checkout with the method as a submodule, the newest local
  `refs/tags/v3.*` against the pinned commit. Runs on the GUI thread from the diagnostics dialog.
- Settings: `QSettings` through `ui/tcc/app_settings.get_settings()`; `core/config.py` already
  reads it lazily (`_settings()`).
- The installers do not record the channel anywhere the app can read.

## A trap the ticket does not name

A candidate carries the **previous** version in `pyproject.toml`: `make ship CANDIDATE=` tags HEAD
and writes nothing (hub §11.3 — the release commit does the bookkeeping). TCC installed from
`beta-v0.2.0-rc1` therefore reports `0.1.38`. `check_tcc` compares versions, so on beta it would
offer `0.2.0-rc1` to an installation that already is `rc1`, forever. **On beta, TCC is compared by
commit**, the way the method already is.

## Design

### 1. One setting, both halves

`updates/channel` in `QSettings`, `stable` or `beta`; anything else reads as `stable`. One switch
for the method and the app, as the installers have one `--channel` for both.

`core/config.py` gains `update_channel() -> str` and `set_update_channel(value: str) -> None`,
beside the settings it already wraps.

### 2. `updates.py` stays Qt-free: the channel is a parameter

`newest_tag`, `newest_tcc_tag`, `check_skill`, `check_tcc`, `check_all` and `apply_skill` take
`channel: str = "stable"`. GUI-thread callers read `config.update_channel()` and pass the value into
the worker. With `stable` every function does exactly what it does today, glob and ordering
included.

New constants beside the old ones, same names and values as the installers:
`SKILL_BETA_GLOB = "beta-v3.*"`, `TCC_BETA_GLOB = "beta-v*"`.

### 3. Listing and order on beta

`_newest_tag_in` accepts several globs (each with its explicit `^{}` peel pattern, the rule its
docstring keeps). On beta it asks for the release glob and the beta glob in one `ls-remote`.

`channel_key(name)` implements §11.2: `vX.Y.Z` → `(X, Y, Z, 1, 0)`,
`beta-vX.Y.Z-rcN` → `(X, Y, Z, 0, N)`; a name of neither shape is dropped, as
`newest_on_channel` drops it. Used on beta only; stable keeps `_version_key` so that "unchanged"
holds to the letter.

### 4. Comparing on beta

- **Method:** `check_skill` already compares the installed commit with the tag's commit. Only the
  listing changes.
- **TCC:** installed commit (`install_report.install_source()`) equal to the channel-newest tag's
  commit → current. Otherwise, if the installed version is above the newest tag's `X.Y.Z` → current
  (a developer build ahead of the releases, the rule `check_tcc` keeps today). Otherwise → newer.
  Worked through: `rc1` installed, `rc1` newest → current; `rc2` published → newer; `v0.2.0` cut
  on `rc2`'s commit plus bookkeeping → newer, and after it the metadata says `0.2.0`; a build from
  `main` at `0.2.1` → current.
- `Status.latest` for a candidate is the tag without its `beta-v` / `v` prefix: `0.2.0-rc1`.

### 5. Applying

`apply_skill(tag="", channel=...)` fetches the channel-newest tag. The TCC button passes
`updates.newest_tcc_tag(channel)` into `tcc_install_line`, which already pins any tag name.

### 6. The self-check pin row

`_pin_check` reads `config.update_channel()`. On beta it lists
`refs/tags/v3.*` and `refs/tags/beta-v3.*` and takes the newest by `channel_key`; the texts are the
same (`selfPinAtTitle`, `selfPinBehindTitle`) with the tag name in them.

### 7. The switch in the window

A checkbox under the update row of the diagnostics dialog: "Beta channel — also offer release
candidates", in `i18n.py` for en, uk, pl and de. Toggling it writes the setting and re-runs the
update check. The title-bar check on start passes the same setting.

### 8. What a candidate installation shows

The update row and the installation block say `0.1.38` for an app built from `rc1` — true of the
metadata, false of the build. `install_report.install_source()` also reads
`vcs_info.requested_revision` from `direct_url.json`; when it is a `beta-v*` tag, the version is
shown with it: `0.1.38 (beta-v0.2.0-rc1)`. This rests on the same precondition as open question 1
(that `uv` writes `requested_revision` for a tag); if it does not, the section is dropped and the
commit on the row is what tells the builds apart.

## Errors

Nothing here raises, as today: an unreadable setting is `stable`, an `ls-remote` that fails is
"unknown" (never "up to date"), a tag of neither shape is not a candidate for anything.

## Testing

Test-first, in the existing files and seams (`_git` faked, `newest_tcc_tag` stood in for):

- `channel_key` on fixed names, the installer's own cases: `v3.1.0` above `beta-v3.1.0-rc2`,
  `rc10` above `rc2`, a candidate for `v3.1.0` above `v3.0.49`, `v3.1.1-foo` dropped.
- beta lists both globs with their peel patterns; stable still lists one — the existing tests stay
  untouched and green.
- `check_tcc` on beta by commit: the four worked cases in §4 above.
- `apply_skill` on beta fetches the candidate.
- `_pin_check` on beta, in a fixture repository with local `v3.*` and `beta-v3.*` tags.
- `config.update_channel` default and an unknown value; the checkbox writes the setting and
  re-asks.
- `requested_revision` read when present, absent without harm.

## Out of scope

- `installer-consistency.py` reading TCC's globs — the skill's call, and a ticket if wanted.
- The method's version display for a candidate (its manifest also lags); the sha is on the row.
- Changing stable's ordering.

## The method on beta: waits for the skill (added 2026-09-14)

The user's rule: a Claude session in the terminal takes a released tag of the method; a session TCC
starts with the checkbox on takes a candidate, chosen by a parameter TCC passes. The method has ONE
checkout, and the terminal and TCC both read it (`install.sh` links `~/.claude/skills/autosound-tuning`
to it; TCC finds it through that link). So §5's "`apply_skill` on beta fetches the candidate" would
put the terminal on the candidate too, and is NOT built. How a candidate reaches TCC's sessions only
is asked of the skill: hub #145 (TCC-011). Until then the method keeps following released tags on
both channels, and §6 (the pin row) stays as it is.

## Open questions for the user — answered 2026-09-14

Both recommendations taken; the checkbox is unchecked by default.

1. **Should an app installed from a `beta-v*` tag start on beta?** Recommended: yes, while the
   setting has never been set. Without it, `install.sh --channel beta` puts the app on stable at the
   first update check, and the tester is moved off the candidates without a word. Precondition,
   checked before relying on it: `uv tool install … @beta-v…` writes `requested_revision`. The one
   installation on this machine was made without a ref, so it cannot answer that.
2. **Where the switch lives.** Recommended: the checkbox under the update row of the diagnostics
   dialog, next to the thing it changes. The alternative is a menu entry beside the language.
