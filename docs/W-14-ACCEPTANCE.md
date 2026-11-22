# Acceptance act: TCC W-14 · v1.3.2 (PR #276)

**Candidate:** branch `wave-14` at `c97c3f71c25160c1f4f43dfb3b9102c1135fb2fd`, PR #276 (author `ayukhno`).
**Method:** `vendor/autosound-tuning-skill` at `a7966a0bc468abdfcf7a5ef907633571d35bda8d`, which is tag `v3.3.3` in the
clone. The tag's SSH signature is good: key `SHA256:nSazijzZf///QKgfVXJBRd2fl7QMd2Xu4uwjc7MGbSo`, the same key as
v3.3.0 to v3.3.2 and `beta-v3.3.0-rc1`. No principal matched: GitHub lists no SSH signing key for `ayukhno`, and the
owner's local signers file could not be read here (`logs/01-tag-verify.txt`).

This was a fresh session on 2026-11-22. Everything ran from a clean clone at
`hub/scratch/tcc/accept-w14/clone`. The wheel was installed into a sandbox HOME and every window ran offscreen. The act
reports only; it decides nothing. Logs are in `logs/`, screenshots in `logs/shots/`, scripts in `walk/`.

The PR's CI at this head is **green**: run `45007409762`, 19 jobs green and 4 skipped by design (23 in all). All issues and comments
read for this act are by `ayukhno`.

## Verdicts

**No critical finding, so the alarm (a critical found only here) is not raised.** One defect was found only here, and it
makes two asks «no»: **B1**, the «checked in the DSP» mark never appears after a real `attest --from-file`. I rate it
Important because nothing false is shown and nothing is written wrong: the mark is simply absent. The Arbiter can weigh
it differently, because the mark was an ask of this wave. There are also three minor findings (A1 to A3) and two
observations.

| area | verdict |
|---|---|
| Clean install | **Works.** The wheel was built from the clone. `uv tool install --python 3.12 --constraints constraints.txt "autosound-tcc[gui,claude] @ file://…whl"` went into a sandbox HOME. `uv tool list` shows `autosound-tcc v1.3.2`. All four entry points answer: `--help` exits 0, and `autosound-tcc --version` prints `1.3.2`. Every window ran from the tool venv's `site-packages` (`logs/11`, `logs/12`). The bare wheel installed into a light venv with no PySide6 (A3 below). |
| The seam on real output | **Works, except the mark (B1).** The button and table ran on real `.pct6` files from the car on three Passat copies, and on a real `.PR15` on a project made for the Mosconi PICO 6/8-2. «Save as a new version» banked through the method on Helix and Mosconi copies. Both stale guards refuse. The DSP files stayed byte-identical. |
| The 8 issues | 6 done. #272 has two asks «no» (mark and Mosconi mark, both B1). #273's asks are all met, with one minor edge (A1). |
| CI shape (#275, #268) | **As asked** (read only, not rerun): one process per file, the `method` jobs ran on 3 OS, and a red Linux job makes the run red. |

### Each issue's asks

Verdicts are done / no / not checked. Where an issue has a «Decided» section, it overrides the issue's first text.

| issue | ask | verdict | evidence |
|---|---|---|---|
| #265 | no remote: the button stands, off, with its tip | done | `logs/60-mosconi.out`: `Send … enabled False … tip 'Nowhere to send yet: this project has no GitHub address. Back it up to GitHub first.'` Shown greyed when the section is open (`shots/mosconi-noremote-project-section.png`). |
| #265 | nothing to send: off, with its tip; strings in 4 languages | done | `logs/61-*`: `'Nothing to send: no tuning files or commits are waiting.'` (en) and `'Нічого надсилати: немає файлів налаштувань або комітів, які очікують.'` (uk). Every new key is present in uk/pl/de with the same placeholders (`logs/64-strings.txt`). |
| #266 A1 | a file recorded twice is listed once | done | `logs/41-a1-mark.out`: v_005 carries `provenance.file` (the sentence form, `ee627ad6…`) and `source_file` (the full md5) for the same file. The hover shows one line: `2026-10-28_4F-Nov26_flat1st_v.1.0.pct6 · md5 ee627ad68f298331821071bfdf9e6be4 · recorded …`. |
| #266 A2 | looking at another slot: the mark on one line, «Show version…» whole | done | `logs/62-a2-*.out`: the mark is 13 px high (one line, 12.9 px). In en, «Back to current» is 100/100 px and «Show version…» 99/99 px. In uk they are 124/124 and 125/125 (`shots/a2-uk-strip.png`). |
| #266 A3 | Qt-free start: a sentence with the hash, not the key | done | On the light install with no PySide6, importing `tuning_session_cli` and then `link_skill_into` on a project whose link is tracked gives: «TCC took the method link .claude/skills/autosound-tuning out of git … committed that as c09b867, together with .gitignore. Nothing was pushed.» (`logs/63-a3-light.out`). |
| #266 A4 | `_show_version` reads the window's own root | done (read) | `main_window.py` `_show_version`: `root = window_folder.state_root(self)`. `dsp_check.header(…, window_folder.shown(self))`. Not run: the case needs a cancelled project switch. |
| #268 | the quarantine off, the test fixed | done | `tests/test_project_github.py` has no `xfail`. CI shard 3/4 (ubuntu): `87 passed` for the file. Locally, `test_measurement_panel.py` and the test ran in one process (the reproduction the ledger names): `145 passed` (`logs/70-test-268.txt`). |
| #271 | the pin (moved to v3.3.3 by Decision), lock, guide links, CHANGELOG, README | done | gitlink `a7966a0…`. Five guide links read `blob/v3.3.3`. `## [v1.3.2]` carries the line «Paired with method `a7966a0…` — the tag on that commit is **`v3.3.3`**». `uv.lock` and `pyproject.toml` say 1.3.2. The README installs `@v1.3.2` (`logs/71-pin.txt`). |
| #271 | the picker lists Mosconi, offscreen | done | `logs/50-mosconi-make.out`: «Audiotec-Fischer — Helix DSP Ultra S», «Mosconi — PICO 6/8-2 DSP», «Musway — M6V4 (no 512K)», «+ Add new». Picking Mosconi fills vendor and model, and Create makes the folder. |
| #271 | hub #343: no link to the deleted repo | done | hub #343 is CLOSED (ayukhno). At v3.3.3, `git grep github.com/ayukhno/autosound-measurements` finds 0. Five files still name the repo (the method's own S-134). In TCC's files, the name is only in `tests/test_guide.py`'s regex and a findings note. |
| #272 (1) | the button and the picker; the table is parameter · journal · file · result; sound rows first; `unknown` never shown as a match | done | `logs/30-after-1N-v014-uk.txt`: «v_014 проти 1N-novaFrom0_v0-1.pct6», `401 збігається · 13 відрізняється · 39 невідомо`. The counts equal the method's CLI (`logs/13-cli-compare-after-1N-v_014.json`). Headings come in the order «Звук», «Система». Non-match rows reading as a match: 0. Also checked on the `line` copy (old layout: 419/56/40), on `aya` in a German window (551/30/50) and on Mosconi (17/19/15). |
| #272 (1, placement) | its own line under the DSP header, whole at the default size, en/uk/de/pl | done | The window booted once per language at 1280×820. The button's drawn text equals its full text and it sits inside the column. `after`: 185/209 px (en), 183/207 (uk), 184/208 (de), 182/206 (pl). The same on `aya`, `line` and Mosconi (`logs/20-*`, `shots/after-window-uk.png`). |
| #272 (2) | exit codes; 3 is a refusal; nothing written beside the file | done (0, 2) / not checked (1, 3) | Exit 2: «Не порівняно: не вдалося прочитати файл (container). not a known .pct6 container (no mode yields a zlib stream)», with the warning (`logs/34-refusal-broken.out`). The CLI says the same (`logs/34-cli-broken.*`). The DSP folder was compared by name, size, mtime and md5 before and after every run: unchanged. `shasum` matches `logs/13-dsp-before.txt`. Exits 1 and 3 of `compare-file` cannot be reached through the widget; see «Not checked». |
| #272 (3) | the warning on every answer, Ukrainian in a uk window, `checked_model: false` above the table | done | The uk window shows `warning_uk` verbatim (Helix and Mosconi). The Mosconi risk line: «Метод не перевірявся на цій моделі: порівняння читається на ваш власний ризик…» (`logs/30-mosconi-v001-uk.txt`). On Helix (`checked_model: true`) there is no risk line. |
| #272 (4) | the button by capability; off with its reason for other DSPs | done | Helix and Mosconi: on. Musway: off, with the tip «The method cannot read this DSP's saved file … It reads: .pct6 (Audiotec-Fischer); .PR<n> (Mosconi).» (uk the same, `logs/56-*`). The list comes from the pin's `knowledge/dsp/readers.json`. |
| #272 (4) | **the mark reads the record `attest --from-file` writes** | **no** | **B1.** After a real `attest --from-file` on Helix (`after` v_017, from `1N-novaFrom0_v0-2.pct6`): every row is entered, the file is on record, and the window shows dot `done` with no tick (`logs/40-after-mark.out`). |
| #272 (5) + Decided | Mosconi: the table now, **the mark built now** | table done; mark **no** | **B1.** Real `attest --from-file example_pico682.PR15` on the Mosconi project (v_003): dot `done`, `rows with a tick: []` (`logs/55-mosconi-mark.out`). |
| #272 Decided | what the method reads comes from the method; advice, not a gate | done | The button, filter and tip follow `readers.json`. A `.PR15` against a Helix version is shown as the method gives it, all 135 rows «unknown», with the risk line (`logs/34-pr15-on-helix.out`). Another model of the same vendor: not checked (no such file). |
| #273 Decided | shown only when rows differ | done | v_014 against a file with 13 differing rows shows the button. v_015 (banked from that file) against the same file gives `469 match · 0 differ · 12 unknown`, and `save_button: null` (`logs/32-after-v015.out`). |
| #273 | runs `propose --from-file`; shows what it kept, did not take and took short; the window re-reads | done | Helix: «Saved as a new version, v_015…», then the method's text: «Kept as v_014 has them … (1)», «Not taken from the file (5)», «Taken short (2)». The header moved `v_014` → `v_015` with a yellow dot (`logs/31-after-save2.out`). Mosconi: v_002 banked with provenance `kind: pr15` (`logs/52-…`). |
| #273 | refused when HEAD or the file moved | done | HEAD: another writer banked v_016 after the comparison, and the click said «Nothing was saved: the file or the version on screen changed since the comparison…», with no new version (`logs/33-stale-head.out`). File: one byte appended after the comparison, same answer, nothing banked (`logs/33-stale-file.out`). |
| #273 | the journal written only by the method, the file never | done | Each bank is the method's `propose`. The DSP folder is unchanged after every save. |
| #274 | closed, no code, with proof | done (read) | CLOSED. The owner's comment of 2026-11-21 records the live chat run, ending with `dsp.settings.peak_mode … source: user` and `corner_set … source: user`. Not re-run. |
| #275 A1/H/D/G | one process per file; Linux blocking; a per-test timeout; the method job | done | See «CI shape» below. |

## Findings

### B1 (Important, found only here). The «checked in the DSP» mark never appears after a real `attest --from-file`: #272 ask 4, ask 5 and Decision 4

`ledger_line._saved_files` drops every saved-file record whose `source_file.compared` is anything other than the
string `"no difference"`. Its helper `_differs` says: *«rc1 writes the string "no difference", or a list of the
differences»*.

The method at v3.3.3 writes `"no difference"` only when every row is a match. Otherwise it writes a list whose first
item is the counts line, and unknown rows go into that list too (`rew_tool/state/from_file.py` `compared`, and
CONTRACT.md item 14: *«An unknown row is never written as no difference»*). On real files there are always unknown rows:

- **Helix:** v_017 records `['compare-file.v1: 469 match, 0 differs, 12 unknown', 'w-L hp.type unknown: …', …]`.
  `_saved_files(v_017) == ()` and `_entered(v_017) == True` (`logs/42-mark-reader.txt`).
- **Mosconi:** the input gain is always unknown (#272 ask 5). v_003 records
  `['compare-file.v1: 267 match, 0 differs, 2 unknown', 'Output 8 channel unknown: …', 'preset input_gain_db unknown: the version records no preset settings']`,
  and again `_saved_files == ()`.

So the Mosconi mark can never show, and the Helix mark shows only for a version whose comparison has no unknown row.
The tests fake `compared: "no difference"` for a `.PR15` (`tests/test_dsp_check.py` `_attested_pr15`), which the real
method does not write for that file. `test_a_mosconi_comparison_that_found_differences_or_unknowns_is_no_mark` makes
«unknowns are no mark» deliberate.

The question for the Arbiter is the rule itself: should «0 differs, N unknown» count as checked? Under today's rule the
mark built this wave is dead on real output. The old record forms still mark: v_008, v_009 and 4.F v_004 have a
`provenance.file` sentence, and a hand-filled `--source-file` with `"no difference"` gives dot `checked` and the hover
(`logs/40-after-mark.out`, `logs/41-a1-mark.out`).

### A1 (minor). «Save as a new version» is offered on a preset that is not the active slot, and the method always refuses it there

The `after` copy opens on `1.N-NOV26_from0`, while the registry's active slot is `4.F-NOV26_flat1st`. The comparison
works and the button is offered. The click gets exit 1:

> «Nothing was saved: the journal refused. error: ⛔ SLOT MISMATCH — proposing to preset '1.N-NOV26_from0' but the ACTIVE
> slot in the DSP is '4.F-NOV26_flat1st'… Either `registry set-active 1.N-NOV26_from0` … or pass allow_nonactive=True…»

(`logs/31-after-save.out`). The refusal is shown as the method gives it, nothing was written, and the window re-read. But
the button cannot work on that preset, and one of the two remedies the method names is a Python argument the person
cannot pass. After `state.py registry set-active 1.N-NOV26_from0`, the same click banked v_015.

### A2 (minor). The saved time of a method-written `source_file` is dropped from the hover

The method writes `saved` as `dd.MM.yyyy hh:mm` (CONTRACT.md item 14, e.g. `"27.10.2026 11:23"`). `ledger_line._stamp`
reads only ISO time and rc1's `DDMMYYYYHHMM`, so it returns `None` for that string (`logs/42-mark-reader.txt`). The
hover then says «recorded <the version's time>» instead of «saved <the file's time>» (`logs/41-a1-mark.out`: «recorded
22.11.2026 11:23» for a file the record says was saved on 28.10.2026). Nothing false is said; a fact is lost.

### A3 (minor, the method's text, not TCC's)

- A row's reason is in English in a Ukrainian window: «невідомо: the version does not record it». The method gives no
  Ukrainian reasons.
- After `propose --from-file` on a `.PR15`, the method's sheet is headed «## APPLY THIS in Helix PC-Tool — FULL · v_002»
  for a Mosconi (`logs/52-…`). This is for the skill.

### Observations

- **#266's two comments** (2026-11-09) are outside the four asks and not addressed: the DSP header band's height with no
  DSP known (Windows), and the plural. `gitSubHousekeeping` is still `"{n} службових файлів"`, which reads «1 службових
  файлів».
- **The left column grows in uk.** Looking at another slot in a Ukrainian window, the column widens from about 207 to
  about 275 px to hold «Назад до поточної» and «Показати версію…» whole (`shots/a2-uk-strip.png`). Both stay whole.

## CI shape (#275, #268): read, not run

- **One process per file:** shard 3/4 (ubuntu) runs
  `scripts/ci_per_file.py $files -- -q -m "not method" --timeout=120 -o timeout_func_only=true`. It reports
  `[1/39] tests/…` through `[39/39]`, a `exit 0, N s` line per file, and ends with `ci_per_file: all 39 file(s) passed`.
  Windows shard 1/4 ends with `all 35 file(s) passed`.
- **The `method` jobs ran:** the gate printed «vendor/, scripts/, a dependency, a method test or this workflow changed --
  the method job runs». `method` on ubuntu, macOS and windows: all success. On ubuntu:
  `pytest tests/ -m method -q` → `80 passed, 7512 deselected in 295.38s`. `ci.yml` has no schedule, and `TESTING.md`
  describes the job.
- **Linux blocks:** red run `45005405570` at `230ec9da` failed on one job only, `shard 3/4 (ubuntu-latest)`:
  `ci_per_file: 1 of 39 file(s) failed: tests/test_ledger_line.py (pytest exit 1)`, with the assertion «the fixture must
  cut it». That one job made the run's conclusion `failure`. `ci.yml` has no `continue-on-error: true`.
- **#268:** `tests/test_project_github.py` ran green in its own process in the green run (`87 passed`).

## Who found what

Counts come from `docs/PLAN-W-14.md`'s ledger. C/I/M means critical/important/minor.

| stage | found (C/I/M) | critical | fate |
|---|---|---|---|
| Task seats: #272, #273, with their re-reviews | 0 / 2 / 10 | 0 | the Importants fixed in a round each; Minors fixed or left as the ledger names them |
| Group seats: silent-failure and tests | 0 / 4 / 16 | 0 | one fix round; S2 (a save running at quit) left |
| #265/#266 seat (the Sonnet trial) | 0 / 2 / 2 | 0 | one fix round each |
| #275/#268 seat | 1 / 2 / 2 | 1: the 120 s timeout under two shard tests run alone | fixed (`ff311c85`) |
| Final branch review (Fable) | 0 / 0 / 3 | 0 | fixed (`6d9ae7b1`) |
| PR CI, round 1 (`230ec9da`) | 1 red Linux shard: a product defect, the button in the header cut every row | 0 | fixed (`c97c3f71`, the Arbiter's choice); green at the head |
| Acceptance (this run) | 0 / 1 (B1) / 3 (A1–A3) + 2 observations | **0, so no alarm** | reported |

## Not checked

- **Windows-only:** fonts and the button at Windows widths, `.cmd` and console paths, installers. These belong to the VM.
- **`compare-file` exits 1 and 3 live.** The widget always asks for the version on screen, and exit 3 needs a file that
  changes while it is read. Exit 1 of `propose` was seen (A1).
- **The macOS native file panel.** The harness answered Qt's own file dialog offscreen
  (`AA_DontUseNativeDialogs`). The filter it showed: «Пресет Audiotec-Fischer (*.pct6)», «Пресет Mosconi (*.PR*)».
- **«Another model of the same vendor»:** no such saved file was at hand.
- **A copy that declares no reader** (the `dspFileCheckNoReadersTip` hover): it needs a project bound to an approved
  pre-v3.3.3 copy. Covered only by the repo's tests.
- **The Mosconi project's AI intake.** The project was made through the New-project picker (offscreen) and then the
  method's own writers (`project.py`, `set-dsp-setting`, `PresetHistory`), with no AI session. #274's chat was not re-run.
- **A save running at quit** (ledger S2), the writer lock under contention, the installer path (`install.sh`), and any
  push to GitHub.
- **The full suite and the reviews:** not repeated, by the brief.

## How the run was kept clean

- **One write outside this folder, by mistake, and not undone.**
  - What happened: the first copy of `passat-b8-2026` had no `.git` of its own, because the project lives inside the
    `car` repo. So `git -C <copy> remote set-url origin …` walked up and **changed the `hub` repo's `origin`**. It was
    `https://github.com/ayukhno/autosound-hub.git` for both fetch and push. It is now
    `…/accept-w14/remotes/line.git`, a path that does not exist, so a fetch or push fails loudly.
  - Why it is not fixed: my command to restore it was refused by the permission classifier.
  - **To restore:** `git -C /Users/o.yukhno/dev/autosound/hub remote set-url origin https://github.com/ayukhno/autosound-hub.git`
  - Nothing else in the hub repo changed: HEAD is `7118787`, and the status shows only the existing `.DS_Store`.
  - After this, `GIT_CEILING_DIRECTORIES` was set for every run, and the `line` project was re-made as a copy of the
    whole `car` repo (`projects/carrepo`) with a local bare remote.
- **Real home, end against baseline** (`logs/90-real-home-check.txt` against `logs/00-real-home-baseline.txt`):
  - the three `com.autosound-tcc*.plist`: same mtime and sha1;
  - `~/Library/Application Support/autosound-tcc`: still absent;
  - `~/.claude/skills/autosound-tuning`: the same link;
  - `~/.codex/config.toml` and `auth.json`: same mtime and sha1;
  - the real `uv tool list`: still `autosound-tcc v1.3.1`, bin and receipt mtimes unchanged;
  - no `~/.claude/projects` entry for this folder;
  - no crash report since the run began.
- **Originals:** `car/passat-b8-2026` (3451 files), `_afterAYAfinal` (196) and `-aya` (365) have the same names, sizes
  and mtimes outside `.git`. `ATFsaves/*.pct6` have the same sha1. The baseline's `git status` on the originals may
  have refreshed their `.git` index; nothing else was touched.
- Two end-check listings were briefly written to `/tmp/claude-502/` and moved into `logs/`.
- Every copy pointed at a local bare remote. The only writes to bare remotes were `git clone --bare`, `fetch`, and the
  Mosconi project's upstream. Nothing was pushed anywhere. There were no GitHub writes and no CI runs.
- No process under `accept-w14` is left running. Port listeners at the end belong to other software.
- Two model-retirement boxes («sdk:claude-sonnet-5-5…», «agy:…») appear at every start in the sandbox. The harness
  answered them with Cancel.

## The Arbiter's decisions on this act (2026-11-22, added by the wave's session)

- **B1:** a comparison that found nothing different counts as checked, with the number of values the method could not
  compare on the mark's hover and the first three named; a row that differs still vetoes, and a comparison that matched
  nothing checks nothing. Fixed in the commit that carries this act; checked on this run's own records with the fixed
  reader: `after` v_017 (`469 match, 0 differs, 12 unknown`) and the Mosconi v_003 (`267, 0, 2`) now carry their file.
- **A1:** to the next wave's pool.
- **A2:** fixed with B1 (the method's `dd.MM.yyyy hh:mm` is read).
- **A3:** the method's own texts; for the skill.
- The hub repo's `origin`: the owner restores it himself (the session did not, the permission check having refused it).
