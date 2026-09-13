# Release candidates in `make ship`

Date: 2026-09-13 · Status: design approved by the Arbiter · Tickets: hub #140 (HUB-061), part 1 of 2, and hub #136 (HUB-058)

## Problem

- **`scripts/ship.py` cuts patches only.** The hub has decided on release candidates
  (`governance/RELEASE-CHANNEL.md` §11):
  - `beta-vX.Y.Z-rcN` is tried before a release;
  - a minor or major must promote its newest candidate (§11.3);
  - a `### Breaking` entry refuses a patch (§11.4);
  - `## [Unreleased]` sits on top of the CHANGELOG between tags (§11.5).
- **ship's CHANGELOG checks assume a versioned top entry.**
  - `check_changelog` takes the first `## [vX.Y.Z]` heading in the file.
  - `check_paired_method` reads the first `## [` block.
  - With `## [Unreleased]` on top, the first check skips over it, and the second reads the wrong section.
- **The commit a release starts from gets no CI run.** CI ignores `docs/**` and `**.md`, so a
  CHANGELOG-only commit is never checked. The hub preflight refuses a tag without green CI on HEAD
  (HUB-057), so the next `make ship` could never pass (#136).

## Decisions (the Arbiter, 2026-09-13)

1. **The same model as the skill.** The skill's commits 9d3b36c and 70133aa and its
   `scripts/tag-check.sh` set the pattern:
   - a candidate writes nothing;
   - a release is one bookkeeping commit;
   - only the CHANGELOG text is written by hand (by the session): the notes under `## [Unreleased]`
     as work lands, and at release the rename to `## [vX.Y.Z] — date · title` with its
     `Paired with method` line.
2. **One script, three modes:** patch, candidate, and an explicit version.
3. **The role comes from `HUB_ROLE`**, so the `release` role can cut a minor. The hub's tag rule
   decides who may cut what; ship restates none of it.
4. **The updater's beta channel is part 2**, with its own design: the version order (a release above
   its candidates) and the self-check row.

## Design

### Modes

| command | tag | what it writes | what ship checks (besides the hub preflight) |
|---|---|---|---|
| `make ship [REAL=1]` | the next patch (preflight `want_next`) | pyproject + `uv.lock` bump, suite, commit, tag, push | CHANGELOG release form (below), method pin, Paired line |
| `make ship CANDIDATE=vX.Y.Z [REAL=1]` | preflight `candidate=` → `beta-vX.Y.Z-rcN` | nothing — the tag on HEAD and its push by name | CHANGELOG candidate form (below), method pin |
| `make ship VERSION=vX.Y.Z [REAL=1]` | preflight `tag=` | the same as a patch | the same as a patch; the hub's `rule` and `promotes` checks decide whether it may be cut |

- **Role:** `os.environ["HUB_ROLE"]` when it is set, else `tcc`. Passed to the preflight.
- **Arguments:** `CANDIDATE` and `VERSION` exclude each other, and only a value given on the
  command line counts. A malformed value is refused by the carrier's own `tag` check: ship keeps no
  copy of the version pattern (HUB-003).
- **Commands:** in every mode the three lines are the carrier's own: `git tag <tag>`,
  `git push origin main`, `git push origin <tag>`. For a candidate, `push origin main` changes
  nothing, because the hub already refuses an unpublished HEAD. The tag is pushed by name, never
  with `--tags` (unchanged).
- **A candidate runs no local suite.** Nothing is written, so there is no new tree to test. The
  tree being tagged is HEAD, and the hub's CI check on HEAD (three platforms) gates it.
- **Dry run by default in every mode; `REAL=1` writes.** The summary line names the mode and the
  tag: `patch v0.1.39`, `candidate beta-v0.2.0-rc1`, `version v0.2.0`.
- **Breaking** is the hub's `check_breaking`; ship adds nothing.

### CHANGELOG checks

- **Release form** (patch and `VERSION`):
  - refused while a `## [Unreleased]` heading exists: "rename it to [vX.Y.Z] first";
  - the top versioned heading must be the tag (unchanged);
  - its section must have at least 3 non-empty lines.
- **Candidate form:**
  - the section `## [vX.Y.Z]`, or else `## [Unreleased]`, must exist and have at least 1 non-empty line;
  - a missing section is refused: "nothing says what the candidate carries";
  - an empty section is refused: "an empty note is a forgotten note".
- **`check_paired_method`** reads the section headed by the tag, not the first `## [` block.
  It runs for releases only, because a candidate's notes are not yet a release entry.
- **`CHANGELOG.md`'s preamble** gets one short paragraph:
  - `## [Unreleased]` collects what is between tags and is renamed at release;
  - `### Breaking` marks a change the user must act on, and such a change is not a patch;
  - a candidate `beta-vX.Y.Z-rcN` is cut from the Unreleased notes, and only a beta channel sees it.

### CI (#136)

- Drop `paths-ignore` from `on.push` in `.github/workflows/ci.yml`.
- Rewrite the "NOT a release gate (HUB-045)" paragraph: CI is read by the hub preflight since HUB-057.

## Error handling

- **Every refusal happens before anything is written** (the existing rule), and one run names every
  refusal (the existing test pattern). The new checks follow both.
- **A missing hub carrier is a refusal** (unchanged).

## Testing

In `tests/test_ship.py`, with its existing fake repository and stand-in carrier:

- **Candidate, dry run:** prints the `beta-` tag and writes nothing.
- **Candidate, `REAL`:**
  - tags HEAD and pushes that tag by name;
  - no commit, `pyproject.toml` and `uv.lock` unchanged, no suite run.
- **Candidate CHANGELOG:** `## [Unreleased]` with notes is accepted; an empty Unreleased is refused;
  neither heading is refused.
- **A patch with a `## [Unreleased]` heading present** is refused before anything is written.
- **Arguments reach the carrier:**
  - `VERSION` passes `tag=` and `CANDIDATE` passes `candidate=`, each with the role from `HUB_ROLE`;
  - no `HUB_ROLE` means `tcc`;
  - both flags together are a usage error.
- **The Paired line** is read from the tag's own section, even when another section sits above it.
- **The stand-in carrier's shape test** covers `tag=` and `candidate=`.
- **The Makefile** passes `CANDIDATE` and `VERSION` through.
- **`ci.yml`** has no `paths-ignore` under `on.push`.

## Out of scope

- **Part 2:**
  - the updater's beta channel (a setting, `beta-v*` for the method and TCC);
  - the version order from §11.2;
  - the self-check row.
- **Stable users** need nothing: TCC's updater takes `v*` and the skill's installers take `v3.*`,
  so a `beta-v*` tag is invisible to both.
