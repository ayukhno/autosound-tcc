# PLAN W-14 · v1.3.2: TCC on the method's v3.3.2 (Mosconi, the DSP's saved file), and CI that goes red only on defects

The milestone `W-14 · v1.3.2` (#13) holds 8 issues, all with `ok` (the Arbiter, 2026-11-22). State: `docs/TODO.md` F-111. The
map is in `docs/TEST-FINDINGS.md`, «W-14 — the milestone». The method's v3.3.2 is released (`aaa3cec`, signed). Its v3.3.3
patch changes nothing for TCC (his word), so v3.3.2 is the base. Not in this wave: the Claude API key group, Windows CI
work (#262–#264), and hub #264 PAS-014.

**The arm: no engine** (`двигун: НЕМА`). The session builds, or briefs an Agent; the PR body carries `Engine: none`. One
branch, `wave-14`, in the main tree, and one PR. The full suite runs once, on the PR's CI. Every CI run, the PR's
included, waits for the Arbiter's OK.

## Order

| step | group | issues | who | note |
|---|---|---|---|---|
| 1 | Mosconi and Helix: the pin | #271 (carries hub #343) | the session | the gitlink to v3.3.2, the guide's links (`HOUSE-CURVE.md`, `REFERENCE.md`), check Mosconi in the picker offscreen. The version bump, README, lock and CHANGELOG wait for step 9 |
| 2 | Mosconi and Helix: the check | #274 | the session | read the method's `predict` path for an unset Mosconi setting; one live check on a copy of a project. If the chat asks and records, close with the proof |
| 3 | Mosconi and Helix: the button | #272 | opus · high | `Risk: high`: a red test first. A new module (`ui/tcc/dsp_file_check.py`); `main_window.py` only wires it (the ratchet). `method_cli.spawn(…, "state/apply.py", ["compare-file", v, FILE, "--json"], lock=False)` in a `QThread` worker (`workers.py` pattern). The mark's rule by capability, `dsp_check.reads_save_file` |
| 4 | Mosconi and Helix: a version from the file | #273 | opus · high | `Risk: high`: writes the journal through the method, under its lock. On step 3's module |
| 5 | Mosconi and Helix: the group seats | — | opus · high ×2 | silent-failure + tests, one fix round |
| 6 | Small fixes | #265, #266 | sonnet · medium | one seat for the two |
| 7 | CI | #275, #268 | opus · medium | A1, H, D (+ G by Decision 1); #268 by option N (a per-test reset of `qt_shutdown`). Proven only by the PR's CI |
| 8 | Strings | — | the Advisor (`autosound_ai.py ask`) | uk/pl/de; the session checks the placeholders by script |
| 9 | The final review and the PR | — | fable (the wave holds `Risk: high` code) | version 1.3.2, `## [v1.3.2]` with its `Paired with method v3.3.2` line, README, lock; the PR; its CI on his OK |
| 10 | Acceptance | — | a fresh session on the PR's exact head | as W-12's (`docs/PLAN-W-12.md`, «Acceptance»), on a copy of a real project: a Helix `.pct6` and a Mosconi `.PR15` through the button |
| 11 | The release | — | this session cuts the candidate (`CLAUDE.md`); `release` tags and publishes | the patch `v1.3.2` |

Implementers run **one at a time** in the tree.

**No `/test-audit` this wave** (the Arbiter, 2026-11-22): the suite was analysed on 2026-11-10
(`docs/CI-ROOT-CAUSE-2026-11-10.md`), and since then only three commits touched `tests/` (`c94a0467`, `e8e3a7cd`, `d6bab6b4`).

## Decisions — all four taken with the Arbiter, 2026-11-22

1. **#275, option G: yes.** The method's self-tests, the installers check, the writer-race test and real-`uv` packaging
   move out of every shard into one job. It runs when `vendor/` or `scripts/` change, with no schedule.
2. **#273: in the comparison's result, Mosconi too.** «Зберегти як нову версію» shows when rows differ, runs
   `propose --from-file` and shows the fields it kept. Mosconi's half is asked of the skill as hub #349 (TCC-072).
3. **What the method reads comes from the method.** hub #350 (TCC-073) asks the skill to declare each saved-file reader:
   its family, file pattern, verbs and checked models. TCC reads that declaration when the pin carries it. On v3.3.2 it
   falls back to its own two-row table, and a test checks the table against contract item 13. **The declaration is
   advice, not a gate** (his word): on another model of the same vendor the button stays on and shows the risk warning,
   and a refusal from the method is shown as the method gives it.
4. **Mosconi's mark is built now** («роби зразу, скіл вже робить»), against hub #348 (TCC-071). The tests fake the
   method's answer until the pin carries it.

**The pin moves** (from 3 and 4). Steps 1–8 run on v3.3.2. Before step 9, the pin moves to the skill release that
carries hub #348, #349 and #350, and the tests that faked those answers are run once against the real method. If that
release is late, the PR waits for it; that is the milestone's Blocker line.

## The code map (2026-11-22, `main` at `395ce72b`; a Sonnet reader, line numbers drift)

- **The method's CLI.** The one launcher is `core/method_cli.py` `spawn()` (~l.258). It returns `(code, stdout, stderr)`
  and raises `Refused` / `Busy` / `TimedOut`. `src/` has **no call to `state/apply.py` yet**. `--json` parsing in the
  style of `core/handoff.py:52-80`. A slow call goes in a `QThread` with `Signal(object)` (`ui/tcc/workers.py`) and
  `qt_shutdown.watch`.
- **The mark.** `ui/tcc/dsp_check.py`: `reads_save_file` (l.33), `_mark_icon` (l.100), `mark_row` (l.123),
  `header` (~l.145). The rows are filled in `detail_pane.py:926-949`, the header dot in `main_window._show_version`
  (l.2267-2305). `is_helix` → `preset_settings.is_audiotec` (l.51). The callers are `dsp_check.py:36`,
  `detail_pane.py:622` (`_ORDER_GAIN_FIRST`) and `state/dsp_state.py:549`.
- **The button.** In the DSP `SidebarSection` header beside `_cfg_btn` (`main_window.py` ~l.1992-2008), with
  `add_header_widget` (`sidebar_section.py:154`). Its visibility goes in `_show_version`, its retranslation at
  ~l.5837. `main_window.py` may not grow (`tests/test_structure_ratchet.py`).
- **The pin.** The gitlink `vendor/autosound-tuning-skill`, `ship.py` `check_method_pin` (l.559),
  `check_coming_method` (l.364-431), `published_method_tags` (l.606). The tests: `test_readme.py`, `test_guide.py`
  (the guide's links equal the vendored tag), `test_ship.py`. v3.3.1's pin touched `CHANGELOG.md`, `README.md`,
  `pyproject.toml`, `uv.lock`, the gitlink, `docs/guide/HOUSE-CURVE.md` and `REFERENCE.md`.
- **The picker.** `new_project_dialog._bundled_profiles` reads the method's `knowledge/dsp/profiles/*.json`, so Mosconi
  shows with no code. Nothing there names a vendor.
- **Strings.** `ui/tcc/strings/<feature>.py` `STRINGS`, registered in `strings/__init__.py` `FEATURES`.
- **Tests to extend.** `test_dsp_check.py`, `test_ledger_line.py`, `test_preset_settings.py`, `test_method_cli.py` and
  `test_main_window.py` (~l.7195). There is no fake `apply.py`. Use `tests/_method_copies.py::copy_of_the_method(…,
  changes={"rew_tool/state/apply.py": …})`, or monkeypatch `method_cli.spawn`.

## Weight, models and seats (`hub:seam`)

| task | implementer | task review | group |
|---|---|---|---|
| `Risk: high`: #272, #273 | opus · high, a red test first | one seat (opus · high) → one fix round → re-review of the fix | silent-failure + tests (opus · high), one fix round |
| #271 (`Risk: high`, mechanical) | the session | — | the group's seats |
| #274 | the session | — | — |
| ordinary: #275, #268 | opus · medium, one test per behaviour asked | none | one seat |
| simple: #265, #266 | sonnet · medium | none | one seat for the two |
| strings | the Advisor | — | the session checks placeholders |
| the wave | — | — | one final branch review, fable |

The reviewer's brief is W-12's (`docs/PLAN-W-12.md`): every finding cites a `path:line` and quotes it, gives an inventory
of the class's sites and a severity, a «checked → clean» row per category, and what could not be checked.

## Cost (estimate, 2026-11-22)

| part | machine time | Claude runs |
|---|---|---|
| steps 1–2, the session | ~1–1.5 h | 0 |
| #272 with its review loop | ~4–6 h | ~4 |
| #273 with its review loop | ~2–3 h | ~3 |
| the group's seats and fix round | ~1.5 h | ~3 |
| #265, #266 and a seat | ~1.5 h | ~3 |
| #275, #268 and a seat | ~2–3 h | ~3 |
| strings, the final review (Fable), the PR's fix round | ~2 h | ~2 |
| acceptance | ~1–2 h | ~1–2 |
| **total** | **~15–20 h** | **~19–20** |

Plus the PR's CI, ~25–40 min a run, and one to three runs, each on his OK. Wall clock is two to three days at the
session's pace.

## The implementer's brief (every spawn)

W-12's brief (`docs/PLAN-W-12.md`, «The implementer's brief») with `wave-14` for `wave-12`: the issue is the brief,
plus this map and `CLAUDE.md`. For `Risk: high`, a red test first. Only the changed files' tests run, with
`uvx ruff@0.12.0 check`. `main_window.py` may not grow. The `QApplication` is created first. New strings go in English
in all four tables. Commit by path, with no push. The report says what changed, which commits and tests, the red run,
and what is left. Added for this wave: **TCC decodes no DSP file**. Every read goes through `state/apply.py`, and the
DSP file is never written.

## Ledger

| issue | state | implementer | commits | review | note |
|---|---|---|---|---|---|
| the plan | written 2026-11-22; the four decisions taken the same day; his «го» the same day; 2026-11-22 night: «Як не буде помилок - запускай PR, CI» (the PR and its CI on a clean wave, no separate ask) | — | this | — | hub #348, #349, #350 to skill |
| #271 | done on the branch: the gitlink at v3.3.2 (`aaa3cec`), the guide's method links at the tag; the picker lists Mosconi offscreen; version, README, lock, CHANGELOG wait for step 9 | the session | `5c821c09` | the group's seats | hub #343 closed: 0 links at v3.3.2 (v3.3.1: 3), none in TCC's own files |
| #274 | closed: no screen needed. A live run with `tuning_session`'s options: the chat asks the peak mode and the corner set at intake and records both through `set-dsp-setting`, `source: user` | the session | — | — | ~$1 of Opus, two turns; the proof is on the issue |
| #272 | built: `core/dsp_file.py` (the readers: `readers.json` when the pin has it, else the two-row fallback), `ui/tcc/dsp_file_check.py` (the button, the worker, the dialog), the mark by `attest --from-file` in the family's verbs; real `compare-file` on the method's AYA.pct6 and example_pico682.PR15 | opus · high, 20 min, 98 tools | `c25db512` | task review next | red run: ImportError/AttributeError (no module before); `main_window.py` and the window-build count at their bounds, #273 moves something out first; two segfaults in early runs (.ips 005616, 005621), fixed by holding the worker |
