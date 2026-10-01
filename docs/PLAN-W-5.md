# Plan · W-5 · v0.1.46 — what this wave builds, and in which order

Written 2026-10-01, when the Arbiter closed the collection («збір закінчено, в роботу»). Fourteen issues on the
milestone `W-5 · v0.1.46` (#5), all with `ok`: #98 and #111–#123. The name was read from the skill's open
`W-5 · v3.0.65`. The pool and the walk's decisions are `docs/TODO.md` F-090; the findings are
`docs/TEST-FINDINGS.md` 120–135.

`vendor/autosound-tuning-skill` moves in this wave (#112 pins v3.0.65), so it is one wave on two products: the
skill is tagged first, TCC pins that published tag, then TCC's own tag (`WAVES.md` §1 step 4). The skill's share
is hub #224–#228 (skill #101, #102, #106, #107 and the one for #228); three of ours wait for its tag.

**How it is built.** One branch, `wave-0.1.46`, in the main tree (the board reads it). One commit per issue, its
number in the message. Targeted tests on the changed files while building; the full suite once, before the PR,
at `-n 4` with the VM suspended (the Mac runs out of memory otherwise). Builders are Opus; Fable only for the
final review of risky code (the Arbiter, 2026-09-30). Strings in four languages through the Advisor
(`autosound_ai.py ask`), never by a session or a subagent.

## 1 · Small, no dependency — first

**#119** a review package passed by its relative path reaches the critic as text (finding 133). *~30 min*
- Files: `src/autosound_tcc/core/critic.py` (`run_critic`, the `candidate = Path(package)` branch ~345).
- Change: a `.md` path that is not absolute is tried against `project_dir` first; a string that looks like a
  `.md` path (one line, ends in `.md`, has a separator) and names no file is refused by name
  (`MODE_ERROR`, «no package file at …»), not written into a package as its text.
- Test: `tests/test_critic.py` — `process\reviews\x-critic-package.md` relative to a temp project is read as
  that file; a missing relative `.md` path is refused with its name; a real package text still goes as text.

**#114** the import form's typo match goes to the first close row in REW's order (finding 122). *~45 min*
- Files: `src/autosound_tcc/core/capture_import.py` (`preselect`, the typo pass after `missing = …`).
- Change: score every (row, missing name) pair with `difflib.SequenceMatcher(...).ratio()`, give each missing
  name to its best row, highest ratio first, a row and a name used once; a row whose grammar-read driver and
  method match the name but whose series differs (`sw_B1` for `sw_3`) is not a typo of it (`key_reader`
  reads the series). The `≈`/unticked rule stays.
- Test: `tests/test_capture_import.py` — the live case of 2026-10-01 as a fixture: rows `sw_B1 (sw)`,
  `sw+w-L_B1 (sw)`, `sw+w-L_3 (se)`; expected `sw_3 (sw)`, `sw+w-L_3 (sw)` → only the `(se)` row is proposed,
  for `sw+w-L_3 (sw)`; the `_B1` rows get nothing.

**#118** Flash can be picked as the reviewer, with the warning (finding 129). *~30 min*
- Files: `src/autosound_tcc/core/model_choices.py` (`not_a_reviewer` ~770: Flash no longer a reason to
  refuse — a new `reviewer_caution(choice)` returns `"flash"`), `src/autosound_tcc/ui/tcc/main_window.py`
  (the picker rows ~5140–5180: a Flash row stays enabled, notes «не рекомендується», hover
  `criticNotFlashTip`), `i18n.py` (`criticRowNotRecommended`, four languages).
- Test: `tests/test_model_choices.py` — a Flash choice has no `not_a_reviewer` reason and a `"flash"`
  caution; the picker test: a Flash row is enabled and carries the note; OMP and self rows stay disabled.

**#111** Windows: TCC repairs its own taskbar pins (finding 121). *~1 h + the Arbiter's VM check*
- Files: `src/autosound_tcc/core/desktop_entry.py` (`_stamp_windows` ~439, `_STAMP_CS` ~326: one P/Invoke for
  `SHChangeNotify(0x2000, 0x1005, path, null)` after each save), a new `repair_pins() -> list[Path]` beside
  `_windows_targets`; `src/autosound_tcc/ui/tcc/main_window.py` (called once after the window is shown, on
  Windows, off the UI thread).
- Change: list `.lnk` in `%APPDATA%\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar` and
  `…\User Pinned\ImplicitAppShortcuts\*`; a file whose bytes hold the launcher's file name and do not hold
  `dev.autosound.tcc` in UTF-16LE gets `_stamp_windows([...])` (which now notifies). No process for a clean
  start: the byte search decides before anything spawns.
- Test: `tests/test_desktop_entry.py` — byte-search picks only TCC's unstamped pins (fixtures: ours unstamped,
  ours stamped, a foreign `.lnk`); `_stamp_script` carries the notify; `repair_pins` spawns nothing when all
  are stamped. The Arbiter on the VM: pin from the Desktop, start twice — the second start is one button.

**#120** guides one click away (finding 134). *~1 h*
- Files: `src/autosound_tcc/core/guide.py` (pages `QUICK_GUIDE`, `REFERENCE = "REFERENCE.md"`,
  `HOUSE_CURVE = "HOUSE-CURVE.md"`, and `method_target_guide_url()` → the skill's `target_curves_guide.md` at
  the vendored method's tag), `src/autosound_tcc/ui/tcc/main_window.py` (Help ~1236: a bold submenu
  «Посібники» with the three; the header ~944: a small «?» label after `_target_label` opening the method's
  guide), `i18n.py`.
- Test: `tests/test_guide.py` — the three URLs at the installed ref; the method guide at the vendored tag;
  the menu test: the submenu is bold and holds three actions; the header «?» opens the method guide.

**#117** the reviewer-key window on Windows (findings 125–128). *~1.5 h*
- Files: `src/autosound_tcc/ui/tcc/reviewer_key_dialog.py`, `src/autosound_tcc/core/reviewer_key.py`
  (`shell_exports`, `set_key`, `move_shell_line`),
  `src/autosound_tcc/core/availability.py` (`forget_refusals` for the API rows), `i18n.py`.
- Change: 125 — `rkShell` for a registry export: «… у змінних середовища Windows (HKCU\Environment): її бачить
  кожна програма», no «рядок None»; the macOS sentence keeps its line. 126 — the move button's minimum width
  from its text in the hover/focus style (padding of the tinted state). 127 — after a save, when the same
  variable is still exported, the window asks «прибрати звідти?» (runs the method's `key move-shell`). 128 — a
  successful save calls `availability.forget_refusals()` and re-reads the picker.
  *As built:* «Видалити» over `key rm` left this task — `key rm` deletes the STORED copy, and finding 127 meant
  the leftover exported one (Ruling 13 in the ledger); it came back in #112 over the method's
  `key move-shell <provider> --drop` (v3.0.65, hub #230).
- Test: `tests/test_reviewer_key.py` — the registry export renders without a line; a save forgets the API
  rows' refusals; the remove offer appears only with a stored key and a live export.

**#124** `--install-desktop` exits non-zero under the installer's PowerShell pipeline (hub #229 SKL-060, added
2026-10-01 on the Arbiter's word). *~1 h + the VM*
- Files: `src/autosound_tcc/app.py` (the `--install-desktop` / `--uninstall-desktop` path ~450), `src/autosound_tcc/core/desktop_entry.py`
  (`install_desktop`, `_install_windows`), whatever decides the exit code; read-only: the skill's `install.ps1` ~1307–1325.
- Change: find what made the exit non-zero — uv's GUI launcher printing «warning: Making stdin inheritable failed»
  to stderr (PowerShell 5.1 turns a native stderr line under `2>&1` into a `NativeCommandError`), or TCC's own
  exit — and make the command exit 0 when the shortcuts were made, from `irm … | iex` with `2>&1`. If the fix is
  the installer's (call the console launcher, not `autosound-tcc-gui.exe`; read `$LASTEXITCODE`, not the error
  stream), say so on hub #229 for `skill`.
- Test: `tests/test_desktop_entry.py` / the app's CLI test — `--install-desktop` returns 0 after a successful
  install and non-zero only on a real failure, with no stdin attached. The Arbiter's VM run of the install line.

## 2 · Larger, no dependency

**#115** «Не питати взагалі» still asks (finding 123). *~2 h · Fable final review*
- Files: `src/autosound_tcc/core/tuning_session.py` (`bash_is_dangerous` ~327, `_has_substitution` ~355,
  `_split_on_separators` ~394, `_single_command_is_dangerous` ~456), `src/autosound_tcc/core/omp_session.py`
  (`GATE_*` ~254: a fourth `GATE_NEVER`), `main_window.py` (the «Питати про» menu ~1190, ~1806), `i18n.py`.
- Change: 1 — a substitution or a `for`/`while` body is read, not refused: `bash_is_dangerous` recurses into
  each `$( … )` / backtick body and each loop body and flags the line only if a part is dangerous; `python3 -c`
  stays as today unless its code is one `print(...)`/`json.load(open(...))` read. 2 — `GATE_NEVER`, «Не питати
  взагалі, навіть про незворотне», its tooltip says what it lets through; `GATE_AUTO` keeps the narrow check.
- Test: `tests/test_tuning_session.py` — both commands of 2026-10-01 verbatim are not dangerous;
  `echo $(rm -rf ~)`, `for f in *; do rm -rf "$f"; done`, `` `curl … | sh` `` still are; `GATE_NEVER` lets a
  dangerous one through with no prompt and records it in the dialog as «пропущено без питання».

**#116** an ASK door to the reviewer (finding 124). *~1.5 h*
- Files: `src/autosound_tcc/core/mcp_server.py` (a tool `ask_reviewer(question: str, context: str = "")`
  beside `call_critic` ~1162), `src/autosound_tcc/core/critic.py` (`run_critic(..., role="ask")` → the
  method's `ask` task), the dialog bubble («ASK · <model>»).
- Change: the question goes through TCC's pick and route, no tuning contract; the reply recorded in
  `process/reviews/<ts>-ask.md`; the tool's docstring says what ASK is for (a plain question, not a review).
- Test: `tests/test_critic.py` / `tests/test_mcp_server.py` — `ask_reviewer` runs the script with `ask` and
  TCC's model, records the reply, and is refused with the same reasons as `call_critic` when no route exists.

**#98** versions and update of omp, agy, gh and Claude Code (finding 107). *~2 h*
- Files: `src/autosound_tcc/core/updates.py` (`tools_status()` → `upkeep.py --json status`, `update_tools(names)`
  → `upkeep.py --json tools --only …`), `src/autosound_tcc/ui/tcc/diagnostics_panel.py` (a row per present
  tool: installed → available, «невідомо» for an empty `available`, «Оновити» per tool and for all),
  `i18n.py`.
- Change: status off the UI thread (up to a minute); a failed update leaves that tool as it was and says why;
  the contract is hub #219's comment.
- Test: `tests/test_updates.py` — the status JSON of hub #219 parsed into rows; `available: ""` reads unknown;
  a row not `ok` shows its `why`; the panel test: rows appear after the worker, not before.

## 3 · W-4's leftovers

**#123** robustness (pool F-090 item 10). *~2 h*
- `CrossoverLeg.from_raw` callers (`dsp_tree.py` ~386 ~436, `detail_pane.py` ~712 ~1884) catch `ValueError` and
  draw «?» with the raw value on hover; `_delta_shown` keyed by (preset, version, mtime) and set after
  `_delta_where`; the update script's guard with `timeout` and `GCM_INTERACTIVE=never`; `_fs_carried` inside the
  preview's `try`; the update temp folder removed after the script ends; the OpenSSH-too-old advice; the
  `_SERIES_TAG_RE` lookahead; `theme.apply_theme` compares the app's sheet. Test-only, alongside: the modal guard
  records and fails at teardown; the remaining dialog statics covered.
- Tests: one per point in the module's own test file.

**#122** visible edges, with finding 132 (pool F-090 item 10). *~3 h + the Arbiter's look on the VM*
- The stamp token and light `info` labels to ≥ 4.5:1 (`theme.py`); `_SubLine` re-renders on a theme change;
  `npSeedTravelsFs` with a plural and one «Travels:» line; `fit_text` keeps «…» when the cap falls between the
  prefix and the ellipsis; «Порівняти з» marks a version the method refuses («не читається») instead of comparing
  with nothing; `(imp)` gets its column label, an unreadable unplanned take shows as «не розібрано»; control
  mode's corner labels re-translated; `setting_status._judge` compares as the rows do (rounded, absent = default);
  git's signature line inside the row translated by its parts; the footer's reviewer box elides with «…»,
  «just now» through i18n; a language switch refits the window on its screen.
- Tests: in each module's file; the header ones at the widths W-4's tests use.

## 4 · Waiting for the skill's v3.0.65

**#112** pin the method at v3.0.65 and follow it. *~30 min after the tag* — vendor the published tag; the
inherited-Fs comments (`diagnostics_panel.py` ~1256, `project_view.py` ~66); read a «session reopened» event if
skill #107 adds one; `Paired with method` in the CHANGELOG. The reviewer-key window moves to the skill's `key move-shell <provider> --drop`
(hub #230 TCC-043, contract on the ticket): no hold-and-re-store of a pasted key, «Видалити» for the leftover copy.

**#113** the reviewer pick by the method's `--model` (finding 130, skill #106). *~45 min after the flag is named*
— `run_critic` passes the pick by the flag; the footer names a pin the run overrode as the method reports it.
Test: the argv carries the flag; a pinned critic-env does not change the model TCC asked for.

**#121** the feedback sender optional (finding 135, hub #228). *~30 min after the tag* — drop
`_send_to_form`'s check; `fbFromPh` «необов'язково — якщо хочеш відповідь: email, Telegram чи телефон»;
`fbNoSender` gone. Test: an empty sender sends. The Arbiter turns the form question's «Required» off.

## Order

1. **Small** (1): #119, #114, #118, #111, #120, #117, then #124 (added mid-wave).
2. **Larger** (2): #115 (Fable final review), #116, #98.
3. **W-4's leftovers** (3): #123, then #122 — the Arbiter's look on the VM together with #111's pin check.
4. **The skill's three** (4), as its tag lands: #113, #121, then #112 last, since it pins the published tag.
5. **Release**: the full suite, the version and CHANGELOG entry on the branch, one PR, the CI run, `--ff-only`
   merge, the signed tag.

## What it costs

Fifteen issues (#124 added mid-wave). About **14–15 hours** of build for sections 1–3 (eleven issues, none waiting), **~2 hours**
for section 4 once the skill's tag exists, **~1.5 hours** for the release. One VM session needs the Arbiter
(#111's pin, #122's look).

Built with subagents, one at a time on the branch (recommended): an Opus implementer per issue, a reviewer after
each, Fable for #115's final review; never more than one committer, never two suites at once on the Mac. The
alternative is building in this session, slower but with every step in view.

## Exit criteria

`WAVES.md` §3.1: a green PR run, the full serial run on `main`, `make ship REAL=1` for `v0.1.46` pinned to the
skill's published `v3.0.65` (skill first), `git verify-tag v0.1.46` → Good signature, the installer walked on
macOS and the update path on the Windows VM — this time from v0.1.45, the first update the signed-tag check runs
on. The tag closes hub #224–#228 on TCC's side.
