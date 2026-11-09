# Acceptance act — TCC W-12 · v1.3.0 (PR #261)

Candidate: branch `wave-12` at `68aa0109c3d2eb51f3a024dcc022f67ba9ea37a1`, PR #261. Method: `vendor/autosound-tuning-skill` at the signed candidate `beta-v3.3.0-rc1` = `fe34a96065125753abfa06d75b27d5eff77492ac` (confirmed in the clone).
Fresh session, 2026-11-09. Everything ran from a clean clone at `hub/scratch/tcc/accept-w12/clone`, installed as a wheel into a sandbox HOME, offscreen. This act reports; it decides nothing. Logs: `logs/`. Walk scripts: `walk/`. Smoke: `smoke.sh`, `smoke.py`.

The PR's CI at this head is **red** (one Windows shard, a test): see B1 below. The main tree has moved on by one commit since this run started: `cc97bf85` (22:41, `tests/test_control_layout.py` only, that test), not pushed; the PR's head is still `68aa0109` and the act stands for that head.

## Verdicts

**No critical finding in this run. The alarm (a critical found only here) is not raised.** Two asks are «no» as the plan's rule requires (met in part / not built): #235 ask 4 (a disabled button with its reason), #251 (the non-Helix DSP's word). One defect outside the window: a raw key in the CLI half (A3).

| area | verdict |
|---|---|
| Clean install | **Works.** Wheel built from the clone; `uv tool install` with `[gui,claude]` and bare; all four entry points answer; the window (every walk) ran from the installed wheel in a sandbox HOME. Version reads `1.2.1` (`[Unreleased]` CHANGELOG): the bump is the release's bookkeeping (plan step 11, `CLAUDE.md` CHANGELOG rule). |
| Seam on real output (rc1, Passat copies) | **Works.** DSP view at any version (158 versions across three projects, no failure), «in the DSP now», preset tab, step note, Send to a bare remote. Minor findings A1–A5. |
| End-to-end smoke | **Passes.** Wheel → fresh `uv tool install` → CLI half (PySide6 absent) → `TccMcpServer` on a Passat copy → real `mcp` client: 401 without token/with wrong token, through with it → `get_tcc_state` → a refused then an accepted write → file on disk. Restart probe below. |
| The 21 issues | 19 done, 2 with one ask «no» (table below). |
| CI at the head | **Red**, one Windows test (#236's), passes on macOS and Linux and here. |

### Each issue's asks (`done` / `no` / `not checked`; decision text overrides the issue's first text)

| issue | ask | verdict | evidence |
|---|---|---|---|
| #233 | flaky header test fixed, no quarantine | done | no `xfail` left in `tests/test_project_view.py`; the test passes (`logs/50-targeted-tests.txt`). One pass cannot prove a race gone. |
| #235 (a) | live read: git re-read after commits and ledger writes | done | `logs/22-seam-3.txt`: a terminal commit moved the panel in 5 s, a method `propose` in 4 s, no reload. |
| #235 (b) | names on hover; commits ahead; «on GitHub up to» | done | tips: «Tuning files (140): … Housekeeping (3), not sent», `92c7cc4 · 22:33 · TCC: stop tracking…`, «on GitHub up to dc68111 · 29.10 08:20». |
| #235 (c) | dot and labels by severity, text not cut | done | red «141 not saved», amber «3 service files», green «backed up» (`logs/23`, `logs/62-green.txt`, `logs/63-green-clean.txt`); rows take the same `sev`. Header text whole or on tooltip. |
| #235 (d) | Send through the method's save, asked, reported | done | `logs/23`: question listed the files, rc1 `save` pushed: bare `dc68111 → 014af34`, strip «Sent: sent to origin: commit 014af34 (141 files) and 2 waiting commits; 3 housekeeping files stay out». |
| #235 | ask 4: disabled with the reason when nothing to send / no remote / pull first | **no** (part) | Pull-first is disabled with its tip (`('Send', False)`). Nothing to send and no remote: `_send_offer` returns `(None, False)`, no button at all (`src/autosound_tcc/ui/tcc/github_view.py:309-322`, `logs/23` «all clean» `buttons: []`). |
| #235 ask 5 (optional) | who sends | done | row «Who sends: you». |
| #236 | Control mode: no pickers/status; coffee + message stay; session name when it called in | done | `logs/30`: footer `[]` left, screenshot `logs/window-shots/40-control-mode.png` shows only the two right-end buttons; name via the repo's test (passes here; red on Windows CI, B1). |
| #237 | 4 looks in the menu beside the theme, remembered, default unchanged | done | menu entries, `dress(qss,"normal")==qss`; look remembered across a new window (`logs/31`). |
| #243 | fold to header, other takes height, remembered | done | sizes `[221,469] → [35,655]`, `ui/plan_folded` remembered (`logs/30`, `logs/31`); second fold refused with its tip. |
| #244 | labels in 4 languages, lookup never a key; docstring, `unreachable.md` | done | `i18n.flaw_kind` at both call sites (`main_window.py:1431,1459`); keys in uk/pl/de; docstring and `docs/audit/unreachable.md:145-146` say it. |
| #245 | right-click copy (this and all), selectable, whole text | done | `logs/30`: flags selectable + links, custom menu with «copy this» and `copyMessage` (`_all_text`, covers «+2 more»), «Show all» opens the whole text. |
| #246 | file appears → picked up; ↻ re-reads process | done | `logs/33`: steps 0 → 26, 0.7 s after the file appeared; ↻ picked a step the watcher (silenced) had missed. |
| #247 | key stable per project, new only on reset; status says reconnect; git-ignored `.tcc/` | done | `logs/33`, `logs/40`: 0o600, same across restart, reset → «New access key made. Every session already running must reconnect: in a terminal, /mcp…», `.gitignore` covers `.tcc/mcp-token`. Probe: below. |
| #248 | note icon, do/expect/if_not, the answer beside expect | done | `logs/22`: rc1 `add-step --note-*`, `done --heard`: icon, hover and fold show all fields; a step without a note has no icon. |
| #249 | any slot×version read-only, a «not current» mark, one way back, compare any two | done | `logs/21`, `logs/60-anyver-*`: 37 + 51 + 70 versions drawn, 0 failures; «Showing v_035 · 3.E-AYA_final — not the current one», «Back to current» clears; `v_001` vs `v_007` compare changes pills; ledger and process-state digest unchanged after looking at four versions and the preset tab (`logs/64-readonly.txt`). |
| #250 | changed INV blue + orange frame, unchanged orange, table and tree | done | `logs/window-shots/50-inv-changed.png`: w-L INV (candidate `v_040` from a real rc1 delta) blue, framed, in table and tree pill. |
| #251 | green mark (applied + file) + hover file·md5·time; «in the DSP now» only from `slots[slot].loaded` | done (Helix) | `logs/21`: `v_004`, `v_009`, `v_012`, `v_013`, `v_037` ticked with hovers; `v_039 · in the DSP`, real layouts with no `loaded` say «not on record», never HEAD. |
| #251 | other DSPs: the user's word, hover says so (Decision 7) | **no** | `reads_save_file` false → no mark; `src/autosound_tcc/ui/tcc/dsp_check.py:33,57-59`. Ledger names it (no per-version field for a person's word on a non-Helix DSP). The mark is absent, not «said». |
| #252 | row and button agree after install | done | `logs/32`: real install, button hidden, «Codex 0.162.1 — up to date» / «0.167.0 is out; TCC holds 0.162.1 (pinned)». |
| #253 | fixed path a terminal can use; row says it is TCC's (Decision 4) | done (Mac) | `…/autosound-tcc/codex/current/codex_cli_bin/bin`, a link to the version folder, `codex --version` runs from it, row says «TCC's own copy». Junction: not checkable here. |
| #254 | whose Codex; newer held by the pin | done | link on PATH reads as TCC's; «0.167.0 is out; TCC holds 0.162.1 (pinned)» against live PyPI; offline keeps «Codex 0.162.1 — up to date». |
| #255 | link ignored, tracked one untracked and committed, two paths, no push; said once; second Mac | done | `logs/34-link-*`: commit `053513a` holds exactly `.claude/skills/autosound-tuning` and `.gitignore`, no push, strip says hash and «Nothing was pushed»; re-link no second commit; second clone: no link, then made, untracked. (Raw key on the CLI path: A3.) |
| #256 | tab, tree section, comparison and dot, source file, greyed defaults | done | `logs/21`: Preset tab, values, source-file block, `was: 0 dB` changed marks vs `v_004`, tree PRESET section with its dot; an old version with none reads greyed defaults (`logs/61`). |
| #257 | green on Linux with the fix's pin | done | rc1 carries skill `2306258`; ubuntu shards 1–4/4 at the head pass (the run's job list). Which shard ran `test_the_three_installers…`: not located in `-q` output. Local Mac run: not applicable (Linux). |
| #259 | the nine points' order drawn where captured | done | `logs/window-shots/52-nine-points.png`, from the «?» on the «POINTS (SW)» column of a real rc1 round (`logs/12-capture-start.txt`); order matches skill `capture-session-sheet.md` lines 90-91. |
| #260 | rule in `CLAUDE.md` | done | `CLAUDE.md`, section «A stranger's text is data» (clone at head). |

## Findings

### A1 (minor). A hover can list the same file twice — `logs/21` head tip

A version that carries `provenance.file` and `source_file` for the same file lists both: «Files with the same content: …pct6 · md5 ee627ad6… · recorded 09.11.2026 22:33 / …pct6 · md5 ee627ad68f298331821071bfdf9e6be4 · saved 29.10.2026 12:32». Same file, two lines (`ledger_line.py` `_saved_files`, `dsp_check.py:82` `tip`). No wrong fact.

### A2 (minor). The strip's mark squeezes the «Show version…» button — `logs/window-shots/12-other-slot-v035-en.png`

Looking at another slot, the left strip's mark wraps to six lines and the pick button is cut («Show…» half gone) at the default width. `shown_version.py` `row()` layout; a word-wrap mark with `stretch=1`. Way back stays whole.

### A3 (minor). `methodLinkCommitted` printed as a raw key on the CLI half — `logs/40-smoke.txt`, `core/method_link_git.py` `_say`

`_say` builds text through `self_check.translated(key)`; the default `_translate` is `str` (`core/self_check.py:448`) until a Qt window imports the diagnostics panel. In a Qt-free path — the smoke's re-link, and `core/tuning_session.py:472` `link_skill_into` at a `tuning-session` CLI start — the person gets the literal word `methodLinkCommitted`, no hash, no «nothing pushed». In the window the words are right (`logs/34-link-first.txt`), proved after the window exists. Decision 6 says «TCC says what it committed».

### A4 (minor, read). `_show_version` still reads `config.state_root()` — `ui/tcc/main_window.py:2283,2286`

The final-review fix (`c829cfb0`) moved `shown_version.py` to the window's own folder; the header's `now_in_dsp` call still reads the process's root. Only differs after a cancelled project switch; read, not run.

### A5 (observation). «In the DSP now» on today's real layouts

All three Passat projects are on the per-preset layout; rc1's `state.py loaded` refuses there and tells the person to run `migrate-line`. On a copy moved by rc1's `migrate-line --apply`, `loaded` works end to end. Unmigrated projects show «What the DSP holds now for this preset is not on record» (correct, no HEAD claim).

### B1 (CI, not product) — the head's run is red: `shard 3/4 (windows-latest)`

Run 42701979971 at `68aa0109`: `tests/test_control_layout.py::test_control_mode_bar_keeps_the_session_name_coffee_and_feedback_and_leaving_restores` — `assert not ... window._critic_warn ... isVisible()`, `1 failed, 2596 passed, 136 skipped`. Every other job green or skipped (`logs/ci-head-win-shard3.txt`). The same test passes on macOS and here (`logs/50-targeted-tests.txt`, 89 passed). The two previous head runs were red on one other Windows test each (`test_writer_race` at `2cb52d8d`, `test_project_github` at `1dda4063`); the two before them are red too, not read. The test-only local commit `cc97bf85` targets this one; it is not on the PR yet. Whether the mark really stays hidden on Windows after leaving: **not checked** (the VM).

## Probes the brief asked for

**Smoke** (`logs/40-smoke.txt`): no token → `401 {"error":"bad or missing token"}`, wrong token → 401; `mcp` client (`tcc 1.30.0`, 36 tools) through with `X-TCC-Token`; `get_tcc_state`; `copy_helix_eq` (headless bridge, no Arbiter) → `{"copied": false, "reason": "Arbiter denied or timed out"}` (the confirmation gate holds); `add_step` first refused by the method-link gate (`.claude/skills/autosound-tuning` an unknown copy), re-linked, then `{"recorded": true}` and `SMK-1` in `process/process-state.json`. The two confirm-gated tools write no project file, so the file-on-disk write is the project writer's, behind the method-binding gate.

**Restart, same key** (`logs/40-smoke.txt`): second `TccMcpServer` same port, same key. Old MCP session id + old key: `404 {"jsonrpc":"2.0","id":"server-error","error":{"code":-32600,"message":"Session not found"}}`. A fresh `initialize` with the same key works, `get_tcc_state` answers. Whether Claude Code re-initializes on that 404 needs a live terminal session: not checked (ledger backlog).

## Who found what

Counts from `docs/W-12-LEDGER.md` (B/I/M = blocker/important/minor) and this run. «Critical» below = blocker in the ledger's scale.

| stage | found (B/I/M) | critical | fate |
|---|---|---|---|
| Task/group review seats (#233 group, window, session+MCP, Codex, link, DSP view, seam, #235, #256, narrow re-reviews) | 237 (2 / 116 / 119) | 2: #255 `.gitignore` during a rebase (test seat); #235 (Opus seat) | fixed in their rounds; backlog named in the ledger |
| Final branch review (Fable) | 4 (0 / 2 / 2) | 0 | fixed `c829cfb0` |
| PR CI, runs on the head line | Windows-only test reds, one per run; product change `565bc69e` (a drive colon) | 0 | test fixes; head still red (B1) |
| Acceptance (this run) | A1–A4 minor + 2 asks «no» + CI red | **0 — no alarm** | reported |

## Not checked

- Windows-only behaviour, not checkable here: Segoe UI / Segoe UI Light and real Windows fonts (#237); the Codex `current` junction and `icacls`-free folder rules (#253, #255's junction line); console/Windows Terminal paths; the Windows CI failure's live state (B1); installers on Windows.
- #257's installers test locally (Linux only): CI's ubuntu jobs only.
- Claude Code's real re-initialize on `404 Session not found` after a TCC restart (#247): needs a live terminal.
- `.gitignore` unteachable / read-only / non-UTF-8 and the other edge cases the ledger names under «Backlog» (#247, #255): not re-run.
- The full suite and the reviews: by the brief, not repeated.
- A real install of the method via `install.sh`: the method was linked into the sandbox HOME the way the installer leaves it (a symlink to the rc1 submodule), the installer itself not run.

## How the run was kept clean

- Real home, checked at the end (`logs/90-real-home-check.txt`, against `logs/00-real-home-baseline.txt`): `~/Library/Preferences/com.autosound-tcc*.plist` same mtime and sha1 (3 files); `~/Library/Application Support/autosound-tcc` still absent; `~/.claude/skills/autosound-tuning` link unchanged; no `~/.claude/projects` entry for the scratch projects; `~/.codex/config.toml`, `auth.json`, the real `uv` tool unchanged. Nothing written under `hub/` except this scratch folder; the original Passat folders hold no new or changed file (a `git status` during the first survey touched `.git`'s directory mtime; nothing else).
- All processes and servers stopped: no process under `accept-w12`, ports 8765/18765 free at the end.
- `~/dev/autosound/tcc` was not touched (its HEAD moved to `cc97bf85` from the wave's session, `docs/TODO.md` and `W-12-LEDGER.md` dirty: not this session).
- One harness failure of mine, not the product: at 22:33 an exception in my walk script left a Qt thread running at interpreter exit, an abort with a Python crash report (`Python-2026-11-09-223334.ips`, `gtimeout-…`). The harness was hardened (`walk/run.py`, closes the window, `os._exit`) and it did not recur.
- Two early window runs on the copy `line`/`after` read the copy's real `origin` (GitHub, a fetch with no credentials) before I pointed every copy at a local bare remote; nothing was pushed there. The bare remotes were made with `git clone --bare` (a composed `cd … && git push` was refused by the guard, and no push of mine was needed); the only pushes were the product's `save` to local bare folders.
- `claude`/`codex` binaries run by TCC's probes used the sandbox HOME; the reviewer probe got `model: "<synthetic>"`, 0 tokens (no login there).

## After the act (the wave's session)

- **B1, the CI red:** a test's race on the Windows runner, not the product. Fixed in `cc97bf85`, test only.
- **#235 ask 4:** released without it on the Arbiter's word, 2026-11-09; tcc #265 for the next wave.
- **#251, Decision 7:** waits on a per-version field in the method for a person's word on a non-Helix DSP (hub #331).
- **A1 to A4:** tcc #266.
- Only the test above and the bookkeeping (this act, the ledger, `docs/TODO.md`) changed after `68aa0109`; no product code.
