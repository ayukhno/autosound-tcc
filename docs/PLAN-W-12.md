# PLAN W-12 · v1.3.0 — the joint minor with the method's v3.3.0

The milestone `W-12 · v1.3.0` (#12): 19 issues with `ok` (the Arbiter, 2026-10-30; state `docs/TODO.md` F-107). A
shared wave (his word: «скіл налаштован на мінорний реліз — синхронізуйтесь», hub #327 TCC-069): the skill's v3.3.0 is
cut first, TCC pins the published tag, then TCC's v1.3.0 (`WAVES.md` §1 step 4, §3.1). The Claude API key group
(#238–#242) is not in this wave (his word: «все окрім ключів»).

**The arm: no engine** (`hub/bin/role tcc`, `двигун: НЕМА`), as in W-10 and W-11: the session builds or briefs an
Agent; `Engine: none` in the PR body. One branch, `wave-12`, in the main tree; one PR; the full suite runs once, on
the PR's CI.

**Planned in a new session** (the Arbiter: «план збережи і будемо робити в новій сесії»). The code maps below were
read on `main` at `fdb45747` (three Sonnet readers, 2026-10-30); line numbers drift, so the implementer re-reads.

## Order

| step | group | issues | note |
|---|---|---|---|
| 1 | Hygiene | #233, #257 | #257 quarantined on Linux now; the re-pin to v3.3.0 (step 9) carries the skill's fix (2306258, untagged today) and lifts it |
| 2 | Small fixes — the Sonnet trial | #252, #250, #244, #236 | ordinary, XS–S, each a short brief |
| 3 | The window | #245, #243, #237 | #237 needs his pick of the looks first (Decisions, 3) |
| 4 | Session and MCP | #246, then #247 | #247 `Risk: high`: a secret on disk |
| 5 | Codex | #254, then #253 | #253 `Risk: high`: it touches what a terminal finds |
| 6 | Project on GitHub — the link | #255 | `Risk: high`: it changes the user's git index |
| 7 | DSP view | #249, #251 (green mark + hover) | #249 changes what `window._view` means: one at a time |
| 8 | The method's seam | #248, #251's «in the DSP now», #235, #256 | only once the skill's candidate carries hub #313, #325, #326 and skill #200; a part whose shape has not come when 1–7 are done leaves the milestone |
| 9 | The re-pin, the final review, the release | — | re-pin to the skill's v3.3.0 candidate; version 1.3.0, `## [v1.3.0]` with its Paired line; strings uk/pl/de through the Advisor; the final branch review; PR; the train |

Implementers run **one at a time** in the tree (W-10: a review over a half-edited file gave 445 setup errors).

## Weight, models and seats (`hub:seam`)

| task | implementer | task review | group |
|---|---|---|---|
| `Risk: high` — #247, #253, #255, #248, #235, #256 | opus · high, a red test first | one seat → one fix round → re-review of the fix | silent-failure + tests seats |
| ordinary code — #246, #249, #251, #254, #245, #243, #237 | opus · medium; one test per behaviour asked | none | the group's seats, one fix round |
| simple — #252, #250, #244, #236, #233, #257 | **sonnet · medium** (the trial: W-11 gave it 4 tasks, one Critical caught) | none | one seat for the group |
| strings | the Advisor (`autosound_ai.py ask`) | — | the session checks placeholders by script |
| the wave | — | — | one final branch review |

**The seats:** Opus 5.5 (`hub:seam`'s own) — W-11 moved off Codex at its usage limit and off Gemini for code (invented
quotes); Codex (`gpt-6-astra`) for the plan review before «го», and beside Opus on the first `Risk: high` group if it
has quota. Gemini only for user-facing text.

## Decisions the plan makes — the Arbiter's word before «го»

1. **#236:** the whole bottom bar hides in Control mode, the thanks and feedback buttons with it (they live in it).
   Alternative: keep those two in the header. Advice: hide the bar — Control mode is the terminal's.
2. **#250:** «changed» becomes background + bold in the outputs table, the font colour stays the value's (orange INV);
   on the tree pill a frame + background. A real frame in a table cell needs a custom delegate (+S). Advice: background
   + bold in the table, frame on the pill.
3. **#237:** which 2–3 looks. A light weight shows only if the family ships one on both systems. Advice: «Звичайний»
   (today), «Легкий» (the system font, light weight: SF Pro on macOS, Segoe UI Light on Windows), «Округлий» (one more
   family present on both) — shown on a screenshot first, his pick, then built.
4. **#253:** TCC does not edit a PATH or put files in `~/.local/bin`. It keeps a fixed folder
   `…/autosound-tcc/codex/current` (a link, a junction on Windows) refreshed on install, and the row says that path and
   that the copy is TCC's. Advice: this; a PATH write is the user's.
5. **#254:** a link to TCC's copy counts as TCC's (realpath under TCC's `codex/`); the row reads PyPI's latest on the
   worker and says «0.165.0 is out; TCC holds 0.162.1 (pinned)»; offline keeps today's text. Updating the pin itself
   is a release's job, not the button's.
6. **#255:** TCC adds the link to `.gitignore` and takes an already tracked one out of the index (`git rm --cached`),
   once, and says «commit this once»; TCC does not commit. The second Mac still needs «Перепривʼязати» once.
7. **#251:** «checked in the DSP» = every channel row `applied` and `provenance.file` present; the mark and hover go on
   the «Порівняти з» rows and the header dot (there is no separate list widget). «In the DSP now» only from hub #325's
   field.
8. **#235** is an epic: split into (a) a live read — re-read on `.git/HEAD`/refs change and after every ledger write;
   (b) names on hover — files by kind, commits ahead, «на GitHub до <hash> · <time>»; (c) the dot and labels by
   severity, the label not cut; (d) «Відправити» through the method's save verb (hub #326), on a worker, asked once.
   (a)–(c) need the method's `status --json` fields; all four wait for hub #326.

## The code maps (2026-10-30, `main` at `fdb45747`)

`S` = `src/autosound_tcc`, `W` = `S/ui/tcc/main_window.py`.

**#233** — `tests/test_project_view.py:613-647`. The spy `_children` (:387-401) records every `subprocess.run`; the
two calls are queued `QTimer.singleShot(0, …)` reloads (`W` :4425, :5333, :5346 call `_set_project_params(reuse_git=True)`)
that fire on the first event-loop turn. Fix: drain events (`QApplication.processEvents()`) before the spy goes in,
drop the xfail. XS.

**#257** — `tests/test_skill_selftests.py:123-148` runs the skill's `scripts/installer-consistency.py`; the fix is
skill `2306258` (S-112), 6 commits after v3.2.0, in no tag. Now: `xfail(strict=False, reason="flaky: #257")` on
Linux only; the re-pin lifts it. XS.

**#252** — `S/ui/tcc/codex_tool_row.py:117-124` `_draw` hides the button only for `STANDING_OWN`; after an install
the state is `STANDING_TCC`, the button disabled but shown. Hide it for TCC too. Flip
`tests/test_codex_updates_row.py:193-202` to `isHidden()`. XS.

**#250** — the pill: `S/ui/tcc/dsp_tree.py:389` adds `chg` to `pill-inv`; QSS `S/ui/tcc/theme.py:1230-1235` gives `chg`
a colour that wins. The table: `S/ui/tcc/detail_pane.py:1895-1904` overrides the foreground with `t.info`. Drop the
colour from `chg` (keep frame + background), keep the value's foreground. Rewrite
`tests/test_dsp_tree_compare.py:282-294` (pins the blue). Check light and dark. XS–S.

**#244** — `flawKind_*` for 10 kinds in each language (`S/ui/tcc/i18n.py` en :376-385, uk :1815-1824, pl :3181-3190,
de :4601-4610); `W` :1478 and ~:1503 print `i18n.t('flawKind_' + kind)`. Three keys × 4 languages and a helper
`i18n.flaw_kind(kind)` that falls back to `kind.replace("_", " ")`; a test that every method `FLAW_KINDS` kind has a
label. `S/core/rew_bridge.py:1-4` docstring narrowed; `docs/audit/unreachable.md:144-145` gets group delay, IR,
distortion and fixed line refs. XS.

**#236** — `W._build_footer` (:1100-~1330), added at :842 outside `_main_splitter`; `S/ui/tcc/control_layout.py`
`enter` (:599-651) hides only the splitter (:646), `leave` (:664). Keep a reference, hide in `enter`, show in `leave`.
Watch `_footer_room` (:1148) and `tests/test_main_window.py:4433` (Control mode's minimum width). New test beside
`tests/test_control_layout.py:192`. XS.

**#245** — `S/ui/tcc/status_strip.py` (264 lines): a `QLabel` (:57) in a `QScrollArea`, `_MAX_LINES = 3` (:33),
`_fit_height` (:101), «+N more» is a separate label (:79). Add `TextSelectableByMouse | LinksAccessibleByMouse`
(keep the action link working, `tests/test_status_strip.py:120`), `copy_menu.enable_copy(...)` with «copy all» (a new
key, 4 languages), and the whole text on demand (a popover) rather than a taller strip. Extend
`tests/test_status_strip.py:157`. S.

**#243** — `W._build_right` (:3285-3366): a vertical `QSplitter` `_right_split` (:3297), `setChildrenCollapsible(False)`,
sizes kept under `ui/right_split` (:186, :3254-3276). A ▾/▸ in each `_phead` row folds the body and caps the card at
its header; two new keys; a rule for «both folded» (the second is refused). The focus head keeps Ready and the REW
dot; `floorChanged` → `_fit_right_floor` (:3364); Control mode reparents `w._right`. New splitter test. S–M.

**#237** — the theme entry `S/ui/tcc/menu_registry.py:233-234`, `_toggle_theme` (`W` :3441) → `_apply_theme`
(:3370-3393) → `theme.apply_theme(app, mode, scale=zoom)`; kept under `ui/theme` (:149, :698, :3376); zoom
(`_ZOOM_KEY`, `_set_zoom` :3446) is the pattern. No global family today (per-class sizes, ~20 mono classes,
`theme.py:1079-1549`). A `font` argument to `apply_theme`, a key `ui/font`, a submenu like the language one
(:235-236), the re-measure `_set_zoom` does (`_repolish_all`, `_fit_*`). M.

**#246** — `W._load_process` (:3465-3503) arms files only; `_refresh_process` (:3589-3600) re-arms only an existing
file; `_watched_project_dirs` (:3520-3551) never watches `process/`; «Оновити» → `_reload_from_disk` (:1690-1705)
never calls `_refresh_process`. Fix: call it there; watch `process/` (or the project folder until `process/` appears)
through the `_process_reload` coalescing timer, never the project reload (#225: a folder watch wiped the capture grid,
:3544). Extend `tests/test_main_window.py:5115`. S.

**#247** — `S/core/mcp_server.py:2089` `self.token = secrets.token_urlsafe(24)` per instance; `_TokenGuard`
(:1718-1745); `write_mcp_config` (:1930-1960), 0o600; `forget_mcp_config` (:1878-1925) matches port and token. Keep
the token in `.tcc/mcp-token` (0o600, `S/core/own_store.py`), `.tcc/` ignored before it is written, a «reset key»
action, a status-strip line when it changed. Tests: stable across two instances on one folder, reset changes it, an
HTTP test of `_TokenGuard` (none today); `tests/test_mcp_server.py:3767-3803` (withdrawal by port and token — two TCCs
on one folder now share the token: decide). S–M, high.

**#254** — `S/core/codex_cli.py` `find()` (:215-255) walks PATH and dock folders, TCC's copy last; `_usable_in`
(:182-211) returns the path as given, no realpath; `standing()` (:481-493) classifies by `found.source`. In
`standing()` (worker only) a realpath under TCC's `codex/` (`normcase`) → `STANDING_TCC`; a PyPI latest query
(`https://pypi.org/pypi/openai-codex-cli-bin/json`, `info.version`) in `_Check._run` (`codex_tool_row.py:42-47`), a
`Standing` field, a key «held by the pin». `Found` is frozen and cached by path — do not change `Found.path`. S + S.

**#253** — `tcc_copy_path` (:105-119) is versioned; `_sweep` removes other versions (`codex_install.py:327`,
:369-382). A `codex/current` link (junction on Windows, `vendor_loader.py:259-267` is the pattern; a junction is a
folder link, so it points at the version folder) refreshed after `install()` (:466); the row shows that path. Tests in
`tests/test_codex_install.py`, `tests/test_codex_cli.py:136-152`. S–M, high.

**#255** — `S/core/vendor_loader.py:223-269` `link_skill_into` makes an absolute link and leaves any entry alone
(:252); `_IGNORE_LINES` (`mcp_server.py:1776`), `_teach_git_to_ignore` (:1779-1809) run only at server start; relink
`S/core/method_binding.py:453-496`. Add `.claude/skills/autosound-tuning` (no trailing slash: a `/` pattern does not
match a symlink); a small helper with a timeout for `git ls-files --error-unmatch` + `git rm --cached`, keyed to the
link, not to the `.gitignore` write; nothing without `.git`; a Windows junction is a folder to git — test it. Tests
with a real git repo, beside `tests/test_mcp_server.py:966-1010`. S–M, high.

**#249** — `W._load_project` (:2131-2298) loads HEAD (`load_project_view` with no `version`,
`S/state/dsp_state.py:630-690`); `_offer_compare` (:2371-2406) already has a cached loader by `v_NNN` / `SLOT/v_NNN`;
`S/state/ledger_line.py` `versions`, `compare_offer` (:303-324). A «shown version» key (None = HEAD) passed to
`_load_project`; a picker from `compare_offer`; a «not the current one» header mark and one way back; compare's left
side becomes the shown view. Decide what a watcher reload and a preset switch do to the key (advice: reset).
`_show_version`'s dot today means HEAD. Extend `tests/test_ledger_line.py`, `tests/test_detail_pane.py:1445+`. M.

**#251** — no list with a tick: the «Порівняти з» combo (`detail_pane.py:886-921`, `control_layout.py:850`) and the
header dot (`W._show_version` :2308-2344). `provenance` is read nowhere; `status` per channel
(`dsp_state.py:489`, `status_counts` :437). Extend `ledger_line._entry` (:114, mtime cache `_ENTRIES` ~:96 — the cache
must see a provenance written after the version) with status and provenance (file, md5, time; all files with one
md5); icon + tooltip in the combo rows. Check `provenance.file`'s shape in the skill's `rew_tool/state/schema.md`
first. S–M.

**#248** — `S/ui/tcc/plan_panel.py` `_PhaseStepRow` (:178-340, the `?` hint :247-251 via `attach_tip`);
`S/state/process_view.py` `_to_step` (:610-635) → `PlanStep` (`S/state/models.py:15-27`). Once hub #313 names the
fields: `PlanStep.note`, read with guards (dict of strings, escaped), a document icon with the note and the answer.
M, high (the seam).

**#235, #256** — no map until their shapes come (hub #326; skill #200). #235's current code: `S/state/project_view.py`
`git_status` (:453-471), `_read_git` (:474-524, 2 s bound, counts only), the only consumer `W._show_git_state`
(:2828-2873), buttons `_git_button` (:2875-2888), `_on_git_backup` (:2918) the confirm pattern.

## Cost (estimate, 2026-10-30)

| part | machine time | Claude runs |
|---|---|---|
| Hygiene + the small fixes (steps 1–2), Sonnet | ~1.5–2 h | ~5 |
| The window (#245, #243, #237) | ~3–4 h | ~4 |
| Session and MCP (#246, #247) | ~2.5–3.5 h | ~4 |
| Codex (#254, #253) | ~2.5–3.5 h | ~4 |
| The link (#255) | ~1.5–2 h | ~3 |
| DSP view (#249, #251) | ~3–4 h | ~3 |
| The seam (#248, #251's half, #235, #256), when the shapes come | ~6–9 h | ~8 |
| Re-pin, strings, final review, the PR's fix round | ~2–3 h | ~4 |
| **total** | **~22–31 h** | **~35** |

Against W-11 (14 issues, ~27 Claude runs, ~16–26 h): more issues, but most are small. Wall clock: three to four days
at the session's pace, plus the PR's CI (~35–40 min per run) and the skill's v3.3.0 candidate (step 8 waits on it).

## The implementer's brief (every spawn)

- Tree `~/dev/autosound/tcc`, branch `wave-12`. Read the issue (`gh issue view N -R ayukhno/autosound-tcc`) — it is
  the brief — its map above, and `CLAUDE.md`.
- `Risk: high`: a red test first, then the fix, then green; the report shows the red run. Ordinary: one test per
  behaviour the issue asks for. A new test must fail on the old code. Tests check what the person sees or what lands
  in a file, not timing.
- **Tests: only the changed files' tests** (`uv run python -m pytest tests/<file> -q`, at most `-n 4`). No
  `make check`, no whole suite: it runs on the PR's CI. `uvx ruff@0.12.0 check` on the changed files.
- `main_window.py` may not grow (`tests/test_structure_ratchet.py`): a change that adds lines there moves a decision
  out in the same task.
- New strings: English in all four tables, marked for the Advisor; the session translates them at step 9.
- Commit only your own files, by path (never `git add -A` / `commit -a`); the subject in English,
  `<group>: <what> (#N)`, with the session's attribution lines. No push.
- Report: what changed, the commits, the tests run and their result (the red run for `Risk: high`), anything left or
  doubtful.

## Ledger

| issue | state | implementer | commits | review | note |
|---|---|---|---|---|---|
| the plan | written 2026-10-30; waits for the plan review (Codex, if it has quota) and the Arbiter's word on «Decisions» and «го» | — | this | — | — |
