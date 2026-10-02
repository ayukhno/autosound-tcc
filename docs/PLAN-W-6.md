# Plan · W-6 · v1.1.0 — what this wave builds, and in which order

Written 2026-10-02, when the Arbiter closed the collection («збір закінчено») and gave every issue its `ok`.
Nine issues on the milestone `W-6 · v1.1.0` (#6): #134–#138, #140, #141, #94, #21 (#139 withdrawn). The pool and
its decisions are `docs/TODO.md` F-092; the findings are `docs/TEST-FINDINGS.md` 137–142.

**One wave with the skill's `W-6 · v3.1.0`** (the Arbiter). The skill is tagged first, TCC pins that published tag
(#134), then TCC's own tag. Two issues wait for the skill: #134 (its tag) and #135 (the carrier for
`AGY_ADC_AUTH`, hub HUB-071). The skill says hub #233 and #236 are built on its wave branch.

**v1.1.0 is a minor jump from v0.1.46.** The hub's release rule refuses it from the `tcc` role: the tag is cut by
the `release` role (`hub/bin/role release ../tcc`), measured 2026-10-02 with `make ship VERSION=v1.1.0` (dry).
`pool-closed` will also ask F-023 (deferred, names #94) to close with the release.

**How it is built.** One branch, `wave-6`, in the main tree (the board reads it). One commit per issue or per
reviewed round, its number in the message. Targeted tests on the changed files, at most `-n 4`; the full suite
once, before the PR, with the VM suspended. Builders are Opus; reviews Opus; Fable for the final review. One
committer at a time. Strings in four languages: uk and en by the builder, pl and de through the Advisor
(`autosound_ai.py ask`, now on the claude CLI: codex is out of quota until 2026-10-20 and Gemini has no key here).

## Global Constraints

- Repo `/Users/o.yukhno/dev/autosound/tcc`, branch `wave-6`; no worktree, no new branch, no push by a builder.
- Tests targeted only, at most `-n 4`; never the whole suite while building. Qt offscreen (`tests/conftest.py`).
- Every user-facing string through `src/autosound_tcc/ui/tcc/i18n.py`: uk (the Arbiter's language, plain words) and
  en; pl and de carry the English until the Advisor.
- A test fails before its fix, and the builder saw it fail.
- Text measured in a test goes through `theme.drawn_width` (the Windows CI runner has no fonts).
- An API key never on argv or in a log; never the real `key` commands or real API calls in tests.
- `vendor/` moves only in #134 (the pointer); `docs/TODO.md`, `docs/TEST-FINDINGS.md`, this plan and `CHANGELOG.md`
  are the controller's.
- Commits in English (the hook refuses Cyrillic), the issue number in them.

## 1 · Small, no dependency — first

**#136** the reviewer-key window keeps its rows' height, and names places with «and» (findings 137, 138). *~1 h*
- Files: `src/autosound_tcc/ui/tcc/reviewer_key_dialog.py` (the grid ~113; the joins at ~368, ~421, ~448, ~451,
  ~489), `i18n.py`.
- Change: when the copy line and its buttons appear, the window grows to its content (or the rows keep a minimum
  height) so «Delete the key» is never squeezed; one helper joins places — two with «and» («і»), three with commas
  and «and» — used at every join.
- Test: `tests/test_reviewer_key*.py` — after a save that leaves a copy, every row button's height is at least its
  size hint; the question and the done line for two and for three places read with «and», four languages.

**#138** the Updates tab remembers what an update learned (finding 140). *~1 h*
- Files: `src/autosound_tcc/ui/tcc/diagnostics_panel.py` (`_tool_done_line` ~218, the rows ~1119, Re-check),
  `i18n.py` (`updToolUnknown`, `updToolSame`).
- Change: a version an update just reported as newest stays «already the newest» across Re-check until the tool's
  version changes; an «unknown» row says its newest cannot be known without installing and does not read as an
  invitation (its button stays, the words change — the Arbiter's look decides the exact wording).
- Test: `tests/test_diagnostics_panel.py` — Update → Re-check keeps «already the newest» for the same version; a
  newer installed version drops it.

**#140** a new reviewer pick shows a spinner while its check runs (finding 142). *~1 h*
- Files: `src/autosound_tcc/ui/tcc/main_window.py` (`_probe_reviewer` ~5217, `_critic_status` ~1494, the
  `criticCheckAnswered` line ~4857), `workers.py` (`_ReviewerProbeWorker` ~157).
- Change: from the pick until the probe answers, a spinner in place of (or beside) the «!», and the status says
  the new pick is being checked — no line from the old pick.
- Test: `tests/test_main_window.py` — a pick with a probe that does not answer shows the spinner and no old model's
  name; the answer stops the spinner.

**#94** two captures with one title: warn the tuner. *~1 h*
- Files: `src/autosound_tcc/core/capture_import.py` (beside `duplicate_targets` ~585), the import dialog and the
  measurement view; the method's `rew_api.duplicate_titles`.
- Change: when REW holds two measurements under one title that TCC reads, a warning names the title and says the
  curves and the method may pick either; nothing more (no uuid addressing — «не стабільно», the Arbiter).
- Test: `tests/test_capture_import*.py` / `tests/test_measurement_view.py` — two rows with one title raise the
  warning naming it; distinct titles raise none.

**#141** the serial suite's flaky six. *~1–1.5 h*
- Files: `src/autosound_tcc/core/mcp_server.py` (`_DaemonCalls` ~98, `_in_thread` ~124), `tests/conftest.py`
  (`_fresh_availability`), the six tests named in the issue.
- Change: find what reaches `availability` after its test (a daemon MCP call outliving `asyncio.run`, or a
  startup reading); the tests drain or join their calls, or the leak is fixed in the code if it is real at runtime.
- Test: a test that runs a call which outlives its `asyncio.run` and proves the next test's availability is fresh;
  the six, in the order of the failing run, pass three times serially.

**#137** hover follows the mouse after an app switch (finding 139). *~1.5 h + the Arbiter's look on the VM*
- Files: `src/autosound_tcc/app.py` (the app's event filters ~249), a small app-wide filter.
- Change: on the window's deactivation the hovered widget gets its leave; on activation what is under the cursor is
  read again — every window, not only diagnostics.
- Test: offscreen, a widget under a synthetic hover loses its hover state on `WindowDeactivate` and a widget under
  the cursor regains it on `WindowActivate`.

## 2 · Larger — with a design pass first

**#21** capture quality at import, while the microphone is in hand. *design ~30 min with the Arbiter, then ~5–6 h*
- The Arbiter's rule (2026-10-02): for a sweep the check finds unusable, TCC recommends a re-take, or the tuner
  confirms the capture as it is and it is taken — import is never blocked.
- Design first (`superpowers:brainstorming`, with the Arbiter): the row's look for «unusable», where the reasons
  show, the re-take / confirm choice and what the checklist counts, whether a confirmed verdict is remembered (by
  the capture's uuid, as `verify` returns `stats.uuid`, SCR-040).
- Then build: the method's `rew_tool/verify.py` (`verdict` ~59, `verify` ~169) on the SELECTED sweeps only
  (`capture_import.is_swept` ~205), on a worker like `_RewScanWorker`; the row's traffic light gains «taken,
  unusable», the issues list on hover; the choice per row. Split into its own tasks after the design.

## 3 · Waiting for the skill

**#134** the method at v3.1.0. *~1.5 h after the tag* — vendor the signed tag (the 2ec40ed habit); hub #233: TCC's
`w_L` ↔ `w-L` binding (`f8ded2d`) checked against the method's, one rule, the `sw-f` answer; hub #236: the method's
route variable set for the sessions TCC starts (`core/session` env), and the v0.1.46 CHANGELOG gap closes.

**#135** agy through ADC. *~2 h after the skill's carrier* — the ONE carrier HUB-071 names, used for TCC's own
`agy models` (`model_choices.py` ~505) and every reviewer run; the Critic recommendation from agy's ADC model list;
the sign-in agy has shown in the self-check and setup.

## Order

1. **Small** (1): #136, #138, #140, #94, #141, #137.
2. **#21**: the design with the Arbiter as soon as he is free, its tasks after section 1.
3. **The skill's two** (3), as its tag and carrier land: #135, then #134 last, since it pins the published tag.
4. **Release**: the Advisor for pl/de, the final review (Fable), the Arbiter's VM look (#136, #137, #138, #140,
   #21), the full suite with the VM suspended, the version and CHANGELOG on the branch, one PR, CI, `--ff-only`,
   the tag v1.1.0 through the `release` role.

## What it costs

About **6.5–7 hours** of build for section 1, **~6 hours** for #21 with its design, **~3.5 hours** for section 3
once the skill's tag and carrier exist, **~2 hours** for the release (the Advisor, the final review, the PR).
One VM session needs the Arbiter (about 15 minutes).

Built with subagents, one committer at a time (as W-5): an Opus implementer per issue, an Opus reviewer after each,
verify-only re-reviews, Fable for the final review.

## Exit criteria

`WAVES.md` §3.1: a green PR run, the full serial run on `main`, v1.1.0 tagged by the `release` role and pinned to
the skill's published v3.1.0 (skill first), `git verify-tag v1.1.0` → Good signature, the update path walked on
the Windows VM from v0.1.46. The tag closes hub #233, #235, #236 on TCC's side, and F-023 and F-092.
