# Plan · W-4 · v0.1.45 — what this wave builds, and in which order

Written 2026-09-29, when the Arbiter closed the collection («закриваємо збір, складай план»). All twelve
issues on the milestone `W-4 · v0.1.45` (#4) carry `ok`; nothing else is on it. The name was read from the
skill's `W-4 · v3.0.64`. The skill is building its half now («скіл вже працює»), and three of ours wait
for it.

`vendor/autosound-tuning-skill` moves in this wave (#95), so it is one wave on two products: the skill is
tagged first, TCC pins that published tag, then TCC's own tag (`WAVES.md` §1 step 4). The version stays
`0.1.45`: the minor rule (hub #220 SKL-058) is built between waves, after W-4's test.

**How it is built.** One branch, `wave-0.1.45`, in the main tree (the board reads it). One commit per issue,
its number in the message. Targeted tests on the changed files while building; the full suite once, before
the PR, at `-n 4` with the VM suspended (the Mac runs out of memory otherwise).

## Already built

| issue | what | proof |
|---|---|---|
| #97 | an omp session hangs after the tools retry: an empty queue for the retry, omp's reason read past its stack (findings 106, 109) | `e465846`; live on the second Mac with omp 18, generator and reviewer, 2026-09-27 |

## 1 · Small defects — no dependency, first

**#101** «In focus now»: an RTA capture listed under SWEEP (finding 111). *sonnet · ~20 min*
- Files: `src/autosound_tcc/state/measurement_view.py` (`groups_from_titles`, `_canonical`).
- Change: sort by the method `parse_name` returns; the title's suffix only for a title the grammar
  does not read.
- Test: `tests/test_measurement_view.py` — `L m+tw_55 (rta) inv` goes under `rta`; a title the grammar
  does not read still sorts by its suffix.

**#103 + #96** the compare box and control mode's header (findings 112, 105). *sonnet · ~1.5 h*
One piece, because both touch the same box.
- Files: `src/autosound_tcc/ui/tcc/detail_pane.py` (`fill_compare_combo`),
  `src/autosound_tcc/state/ledger_line.py` (`compare_groups`), `src/autosound_tcc/ui/tcc/control_layout.py`
  (`_fill_compare`, `_compact`), `i18n.py` (four languages).
- #103: a heading over the open configuration's own group («4.C-cut — цей пресет»); its current version
  shown greyed and not selectable, «v_002 — зараз».
- #96: in a small window the tab labels and chips keep their words (elide or wrap, never cut
  mid-word), and the compare box keeps a minimum width so it is never empty while it has versions.
- Tests: `tests/test_ledger_line.py`, `tests/test_detail_pane.py` (the heading and the greyed current
  row), `tests/test_control_layout.py` (the header at a narrow width: no label cut, the box not empty).
- The Arbiter looks at it on the Mac in a small window before the commit.

**#99** the omp models dialog before omp is set up (finding 108). *sonnet · ~30 min*
- Files: `src/autosound_tcc/ui/tcc/model_config_dialog.py`, `i18n.py`.
- Change: a line the Arbiter can act on — omp is not set up yet or could not list its models, press
  «Налаштувати omp…»; omp's own text kept behind a «details» toggle for a report.
- Test: `tests/test_model_config_dialog.py` — an empty list with omp's error shows the plain line first
  and omp's text only behind the toggle.

**#100** time on the dialog's messages (finding 110). *sonnet · ~45 min*
- Files: `src/autosound_tcc/ui/tcc/dialog_panel.py` (the bubble's role line), the theme if the stamp
  needs its own faint style.
- Change: each bubble shows `HH:MM:SS` beside who spoke; a message restored from history keeps its own
  time, not the time of the restore.
- Test: `tests/test_dialog_panel.py` — the stamp is on the role line; a restored message keeps its time.

## 2 · New project from a seed

**#93** the drivers' Fs behind its own checkbox, ticked by default (F-068). *sonnet · ~45 min*
- Files: `src/autosound_tcc/ui/tcc/new_project_dialog.py` (beside `npSeedFindings`; both `seed()` calls,
  the preview and Create), `i18n.py` (four languages).
- Test: `tests/test_new_project_dialog.py` — unticked: no `fs_hz` on any channel in `project.json`;
  ticked: the seven arrive (the Passat package); the seed note counts them.

## 3 · The DSP tree's marks

**#104** every field that differs from the compared version marked in the tree: HP, LP, gain, delay,
polarity, on every tier (finding 113). *sonnet · ~2 h*
- Files: `src/autosound_tcc/ui/tcc/dsp_tree.py`; the diff the tables already use (`detail_pane.py`).
- Change: the tree reads the same diff as the output table, not an EQ-only count; the output line
  shows the delay when it differs.
- Test: `tests/test_dsp_tree_compare.py` — sw's HPF changed → its line marked; `6.R-right` against
  `v_006` → m-R and tw-R marked for delay and polarity.

## 4 · Windows — one VM session

**#92** a taskbar pin made from the desktop shortcut is a second button (F-087). *opus · ~1–2 h, research*
- Files: `src/autosound_tcc/core/windows_identity.py`, `src/autosound_tcc/core/desktop_entry.py`.
- First find where Windows 11 keeps a pin's identity, and whether TCC can stamp the id before the pin is
  made. The pin itself is the Arbiter's click on the VM.
- Done when: a pin from the desktop shortcut is one button with the running window; or, if Windows
  leaves no way, the issue closes with the proof and the hint that ships already stays.
- Test: `tests/test_windows_identity.py` for whatever TCC writes.
- The same session checks #96's header on Windows (finding 60 / tcc#66 showed «…» there).

## 5 · Waiting for the skill

**#91** the skill clone has local changes: a way out in the updater (hub #217 SKL-056). *opus · ~2 h*
- Waits for: the skill's S-064 command (skill#91), its name and output given on hub #217.
- Files: `src/autosound_tcc/core/updates.py` (the `status --porcelain` check, `updWhy_dirty`), the update
  window, `i18n.py`.
- Change: in place of the grey button, the changed files named and one action — keep the patch beside
  the clone, ask whether to send it to the skill as an issue (only on the user's OK), reset, update.
- Test: `tests/test_updates.py` — a dirty clone: the patch is on disk before any reset; a declined send
  still updates.

**#102** TCC's tags signed, and the updater verifies both tags before installing (hub #83 HUB-032).
*opus · ~3 h · high risk*
- Waits for: skill#99 (the key, the `allowed_signers` form, the skill's first signed tag).
- Files: `scripts/ship.py` (`git tag -s`, refuse without `gpg.format` / `user.signingkey`),
  `allowed_signers` in the repo, `src/autosound_tcc/core/updates.py` (`verify-tag` before the method's
  checkout and before `uv tool install`).
- Tests: `tests/test_ship.py`, `tests/test_updates.py` — unsigned or foreign-signed → refused with a
  reason key; signed → passes; a tag from before the signing date → its own branch with a visible line.
- Closed by: `git verify-tag v0.1.45` → Good signature; a line of the update log with the check's result.

**#95** the vendor pin to the skill's W-4 tag, and TCC's halves of the skill's W-4. *sonnet · ~1–2 h*
- Waits for: the skill's published W-4 tag.
- The halves the skill's milestone already names for TCC: skill#92 (after TCC's skill update the clone
  carries no tag, so `describe` fails — S-065) and skill#94 (TCC's update window on the Mac prints the
  whole command — S-068). Built when they arrive as tickets `to:tcc`.
- `Paired with method` in the CHANGELOG.

## Order

1. **Small defects** (1): #101, #103 + #96, #99, #100.
2. **Seed** (2) #93, then **the tree** (3) #104.
3. **Windows** (4) #92 — one VM session, with the Arbiter.
4. **The skill's three** (5), in the order the skill lands them: #91, #102, then #95 last, since it pins
   the published tag.
5. **Release**: the full suite, the version and CHANGELOG entry on the branch, one PR, the CI run,
   `--ff-only` merge, the tag.

## What it costs

Twelve issues, one built. About **7–8 hours** of session work for sections 1–4 (eight issues, none
waiting). About **6–7 more** for section 5 and the release, spread over whenever the skill lands its
part. One VM session needs the Arbiter (#92's pin, #96 on Windows).

Built in this session, one issue at a time (recommended): the UI issues want the Arbiter's look between
rounds, and subagents in one tree would each run tests, and two suites at once is too much for the Mac.

## Exit criteria

`WAVES.md` §3.1: a green PR run, the full serial run on `main`, `make ship REAL=1` for `v0.1.45` pinned to
the skill's published W-4 tag (skill first), `git verify-tag v0.1.45` → Good signature (#102), the
installer walked on macOS and the update path on the Windows VM. The tag closes hub #83 and hub #217.
