# Plan · W-9 · v1.1.3 — the audit's second wave

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** every write and both session routes run the method copy the project is bound to, and refuse one TCC
cannot trust (G5); TCC's own writer lock waits with a deadline (G8 phase 0); no wait on the GUI thread is
unbounded, and git and history reads are cached (G9 S1); TCC's own stores never write over a file they could not
read (G3); install and update say the truth (G4 part 1); a superseded capture is not shown as done, and the
profiles come from the skill (G6 slice 1); `write_rew_filters` says what failed, and a half-written plan is not an
empty one (G7 now); the curve window writes and draws once per step (G10 S); one or two decisions leave the window
(G13).

**Architecture:** two new Qt-free modules carry G5 and G8 — `core/method_binding.py` (which copy a project runs:
same, approved or refused) and `core/method_cli.py` (today's `_spawn` and its lock, with one deadline behind
`project_lock.hold`) — and every writer and both session routes go through them. Everything else is a local change
in the file that owns the behaviour; no new layer, no threads (G9's helper is W-11's).

**Tech Stack:** Python ≥3.11, PySide6 (Qt offscreen in tests), claude-agent-sdk 0.2.145, uvicorn 0.52.4, pytest;
the method vendored at `vendor/autosound-tuning-skill` (v3.1.1, `e8dabf7`).

**Spec:** `docs/PLAN-AUDIT-2026-10.md` §2 G3–G10 and G13, §4 (what each product needs from the other), §5.1–§5.4
(the designs: three approaches each, «Balance» named in every issue the Arbiter OK'd on 2026-10-07);
`docs/audit/AUDIT-2026-10-VERIFIED.md` (file:line at `f58d208`). The issues on milestone `W-9 · v1.1.3` (#9). Pool
`docs/TODO.md` F-099. The code maps at HEAD `80519f1`, which re-find every anchor W-8 moved:
`.superpowers/sdd/PLAN-W-9/map-*.md`.

## Global Constraints

- Repo `/Users/o.yukhno/dev/autosound/tcc`, branch `wave-9`; no worktree, no new branch, no push by a builder.
- Tests targeted only, at most `-n 4`; never the whole suite while building. Qt offscreen (`tests/conftest.py`).
  Run tests with `.venv/bin/python -m pytest …`.
- A test fails before its fix, and the builder saw it fail.
- Every user-facing string in `ui/` through `src/autosound_tcc/ui/tcc/i18n.py` (uk + en; pl and de carry the
  English until the Advisor). `core/` must not import the ui (`tests/test_packaging.py`), so a `Notice` or a
  refusal sentence written in `core/` is English, as every existing one there is.
- Text measured in a test goes through `theme.drawn_width` (the Windows CI runner has no fonts).
- An API key never on argv or in a log; no real API calls, no live REW, GitHub, `gh` or network in tests; git only
  on repositories made under `tmp_path`.
- `vendor/autosound-tuning-skill/` is a submodule pinned at v3.1.1 and is never edited. A test that needs another
  copy of the method builds one under `tmp_path` (a copy of the vendored tree, then the one file it changes).
- `docs/TODO.md`, `docs/TEST-FINDINGS.md`, this plan and `CHANGELOG.md` are the controller's.
- Commits in English (the hook refuses Cyrillic), the issue number in the subject, ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit after reading the test result, never chained
  after the test command in one line.
- **The ratchet** (`tests/test_structure_ratchet.py`): `main_window.py` ≤ 6270 lines, ≤ 218 window builds
  (`MainWindow(` in tests). A task that adds lines to `main_window.py` takes them out in the same commit by moving a
  decision into a Qt-free module; no new `MainWindow(` in a test — extend an existing window test, or test the
  moved function plainly. G13's task lowers both bounds.
- `uvx ruff check` clean (the repo selects E4/E7/E9/F).

---

## Rulings made while planning

Each is `what — why — the cost if wrong`; the ledger repeats them.

1. **No architects again** — the audit's design passes (§5) are the three approaches, and every issue the Arbiter OK'd
   names «Balance»; the four code maps replace the explorer — a design that the code no longer fits shows up in a
   task review, not before.
2. **`method-newest.yml` runs nightly and on demand, not on `push`** — hub `scripts/release-preflight.py:349-377`
   counts every workflow run on `push` for the sha, so a push trigger would make it a release gate, which #170 says
   it must not be until G4/J6 — a breaking skill tag is seen up to a day later.
3. **`KNOWN_CONTRACT = 0` in the build** — §4.2: 1 only if the skill confirms contract 1 = the v3.1.x surface before
   the release; the controller checks the bus at release — none (no released copy carries a number).
4. **GUI-thread writes wait 5 s for the lock, other threads 60 s** — the GUI must not freeze behind a 120 s
   `capture-check`; MCP calls run on their own threads — a GUI write during a long check is refused as busy and
   retried by hand.
5. **Only `process.py` writes take TCC's lock** — it guards `process-state.json` alone today; the other launchers
   get the bound copy and the bounded run, not the lock (G8 phase 1 brings the skill's lock to all of them) — none
   beyond today's.
6. **A link made on another machine (Mac↔VM) is refused with «re-link to TCC's copy»** — decision 2 refuses a broken
   link; the project's own copy is the authority, so TCC does not switch it silently — one click per machine switch
   on a shared project.
7. **#177's target is its own red tests** (one `set_value`, loads constant in N), not the audit's «2 file ops» — the
   map counted 2N+2 loads plus N writes; `put_many` alone gives a constant — none.
8. **#179 moves `_capture_version` and the compare default** (the map's best two by lines and builds per hour), and
   only after #175, so `capture_version` reads `standing()` — the preset choice and the reviewer's state wait.
9. **The aside copy of `.mcp.json` goes into `.tcc/`** — it carries the old `X-TCC-Token`, and `.tcc/` is
   git-ignored — none.
10. **`signal_bus` gets UTF-8 tolerance, not fsync** — it is append-only (no `os.replace`) and a torn last line is
    already skipped — a power cut can lose the last signal.
11. **`model_overrides` and `model_choices` keep their writers** — same bug class as G3, not on #173; a line in the
    pool — a corrupt machine `models.json` still reads as empty until a later wave.

---

## G5+G8 · One method per project (#169–#171) — Fable's final review

Design: §5.2 «Balance» (S1, S2) and §5.4 phase 0, as the issues state them; anchors in `map-G5-G8.md`. The shapes
below are fixed here so the tasks agree; a builder who must change one says why in the report.

- **`core/project_lock.py`** — `hold(project_dir, timeout_s)`: a context manager; the project's thread lock (one
  per resolved project path), then on POSIX the flock on `process/.process-write.lock`, both under ONE deadline;
  `LockTimeout(RuntimeError)` past it; it creates `process/` only when it takes the flock. `locks_itself(skill_dir)
  -> bool`: True only when `<skill_dir>/rew_tool/write_lock.py` exists and its text holds `PROTOCOL = 1` (False for
  every copy up to v3.1.1). After Task 1 no other module imports `fcntl` or holds a writer lock.
- **`core/method_binding.py`** — `KNOWN_CONTRACT = 0`; `contract_number(text) -> int | None` (a top-level
  `CONTRACT_VERSION = <int>` found with `ast`, never by import); `read_contract_version(skill_dir) -> int | None`
  (cached by path, `st_mtime_ns`, `st_size`); `MethodRefused(RuntimeError)`; a frozen `Binding(project_dir, state,
  skill_dir, entry, reason, can_approve)` with `state` ∈ `same` / `known` / `approved` / `refused`, and
  `require() -> Path` (the skill folder, or `MethodRefused(reason)`), `script(rel) -> Path`
  (`require() / "rew_tool" / rel`), `plugin_root() -> Path | None` (the bound copy's repo root, found the way
  `vendor_loader.skill_repo_root` walks up), `session_env() -> dict` (`{"AUTOSOUND_SKILL_ROOT": str(skill folder)}`,
  empty when refused); `for_project(project_dir) -> Binding` (never raises); `approve(binding) -> Binding`;
  `relink(binding) -> Binding`. Qt-free, light (`tests/test_packaging.py` `LIGHT_MODULES`).
- **`core/method_cli.py`** — `ProcessWriterError` moves here (`process_writer` re-exports the name, so every
  `except process_writer.ProcessWriterError` keeps working), `Busy(ProcessWriterError)`,
  `Refused(ProcessWriterError)`; `spawn(project_dir, script_rel, args, *, timeout_s, lock=True, lock_wait_s=None)
  -> tuple[int, str, str]`. `lock_wait_s` defaults to `GUI_LOCK_WAIT_S = 5.0` on the main thread and
  `LOCK_WAIT_S = 60.0` on any other; `timeout_s` bounds the child alone. Env:
  `vendor_loader.child_env(**binding.session_env())`. The child runs under `child.run_bounded` where its contract
  fits (Windows reaps the child after a timeout).
- **`process_writer._spawn(project_dir, args, timeout_s=DEFAULT_TIMEOUT_S, **kw)` and `_run` keep their names and
  arguments** — tests patch both (`test_process_writer.py:124,174,196,298`, `test_mcp_server.py:1277,1311,1329,1863`).

### Task 1 · #171 — the writer lock waits with a deadline and answers «busy»

`_THREAD_LOCK.acquire()` is unbounded (`process_writer.py:159`), so a write queued behind a 120 s `capture-check` —
or `close_session` at quit behind a queue of them — waits for all of it; the flock's deadline is the child's own
`timeout_s`. F9, N8, N9, TA-1d/e.

**Files:** create `src/autosound_tcc/core/project_lock.py`; modify `src/autosound_tcc/core/process_writer.py`
(`_THREAD_LOCK`, `_LOCK_NAME`, `_exclusive` :105-147 move out; `_spawn` :150-183 holds `project_lock.hold`; dead
imports go — ruff F401); create `tests/test_project_lock.py`; modify `tests/test_process_writer.py`.

- [ ] **Red tests** (`tests/test_project_lock.py`; the project fixture is the skill's own writers, model
  `test_process_writer.py:65-87`):

```python
def test_a_held_lock_answers_busy_within_the_deadline_and_writes_nothing(project, monkeypatch):
    monkeypatch.setattr(process_writer, "GUI_LOCK_WAIT_S", 0.3)   # method_cli's from Task 2
    before = _bytes_of(project / "process")          # {relative path: bytes}
    held, release = threading.Event(), threading.Event()

    def holder():
        with project_lock.hold(project, timeout_s=5):
            held.set()
            release.wait(5)

    threading.Thread(target=holder, daemon=True).start()
    assert held.wait(5)
    started = time.monotonic()
    with pytest.raises(process_writer.Busy, match="nothing was written"):
        process_writer.enter_phase(project, "1")
    release.set()
    assert time.monotonic() - started < 2.0
    assert _bytes_of(project / "process") == before
```

  Also: a free lock is taken at once; `hold` past its deadline raises `LockTimeout` and leaves no flock held (a
  second `hold` succeeds); on a project with no `process/`, a `LockTimeout` creates nothing; the deadline covers
  the thread lock AND the flock (a POSIX-only twin with a holder **process**: `multiprocessing` or a child python
  holding the flock, `skipif(sys.platform == "win32")`).
- [ ] Run them: red (no module / the write waits).
- [ ] **Build:** `project_lock.hold` as fixed above. `method_cli` does not exist yet, so in this task `_spawn`
  maps `LockTimeout` to `process_writer.Busy` itself with the sentence «busy: another write to this project is still
  running — nothing was written, try again»; Task 2 moves that mapping into `method_cli` unchanged.
  `GUI_LOCK_WAIT_S`/`LOCK_WAIT_S` live where the mapping is (here `process_writer`, then `method_cli`; the test's
  `monkeypatch` target moves with them).
- [ ] Green: `tests/test_project_lock.py tests/test_process_writer.py -n 4`.
- [ ] Commit: `G8 phase 0: the writer lock waits with one deadline and answers busy (#171)`.

### Task 2 · #169 #171 N1 — `method_cli` owns the spawn; supersede and handoff go through it

`title_fixes.supersede` (`:61-74`) and `handoff.check` (`:28-54`) start `process.py` with a bare `subprocess.run`:
no lock, no bound copy (after Task 5), unbounded on Windows after a timeout. Their exit codes are answers (supersede
0/1 = done, `handoff --json` 0/1 = a verdict), so they go through `spawn`, not `_run`.

**Files:** create `src/autosound_tcc/core/method_cli.py`; modify `process_writer.py` (`_spawn` calls
`method_cli.spawn(project_dir, "state/process.py", args, timeout_s=…)`; `ProcessWriterError`, `Busy`, the two wait
constants move; `LANDED_IN` gains `capture-supersede` and `handoff`, each with the first tag whose `process.py` has
it — found in the submodule's history, e.g. `git -C vendor/autosound-tuning-skill log --format=%H -S'"handoff"'
-- skills/autosound-tuning/rew_tool/state/process.py` then `git tag --contains`, never guessed; the comment at :52
says how), `title_fixes.py`, `handoff.py` (public signatures unchanged: `supersede(project_dir, wrong, right) ->
tuple[bool, str]`, `check(project_dir) -> Optional[dict]`); create `tests/test_method_cli.py`; modify
`tests/test_title_fixes.py:33-46`, `tests/test_handoff.py:30-46,123-130` (they patch `subprocess.run` in the old
modules: re-point at `method_cli`'s runner).

- [ ] **Red tests:** supersede while a holder thread keeps the lock → `(False, <the busy sentence>)` within the GUI
  wait, and `process/` byte-identical (today it runs unlocked and answers done); `handoff.check` on a project with
  no `process/` creates no `process/` and returns at once while a holder keeps the lock (`lock=False`); the
  `LANDED_IN` scan (`test_process_writer.py:206-219`) covers both new commands; a fake `process.py` that sleeps past
  `timeout_s` is cut and answered «timed out», not «busy».
- [ ] Red, build, green (`tests/test_method_cli.py tests/test_title_fixes.py tests/test_handoff.py
  tests/test_process_writer.py -n 4`).
- [ ] Commit: `G5/G8: method_cli owns the spawn; supersede and handoff go through it (#169, #171)`.

### Task 3 · #171 — the race between TCC and a bare CLI write, expected to fail until the method locks itself

The lock orders TCC's writers only; the skill's own CLI does not take it (`_exclusive`'s docstring says so). The
race is real today and stays until the skill's lock (W-11), so the tests are `xfail(strict=True)`: the day a
re-pin brings a copy that locks itself, they pass, strict turns that into a failure, and the xfail comes off in
that commit.

**Files:** create `tests/test_writer_race.py` (and a fixture helper beside it if needed).

- [ ] **The interleaving must be deterministic** — the existing race test flaked ~1 in 12
  (`test_process_writer.py:51-55`), and a probabilistic race under `strict=True` fails whenever it happens not to
  lose. Make the bare write slow on purpose: run the bound `process.py` through a small wrapper (`python -c`, or a
  helper script under `tmp_path`) that wraps `Process.load` to sleep 0.5 s after loading, then runs the CLI as
  `__main__`; while it sleeps, TCC's `add_step` lands; the bare write then saves its stale state. No file of the
  vendored tree is edited.
- [ ] Tests, each `@pytest.mark.xfail(not project_lock.locks_itself(vendor_loader.skill_dir()), strict=True,
  reason="TCC's lock does not bind the skill's own CLI until the skill locks itself (G8 phase 1, W-11)")`: both
  steps are in the plan; the journal holds both events. Plus one plain test that `locks_itself` is False for the
  vendored v3.1.1 and True for a `tmp_path` copy with `rew_tool/write_lock.py` holding `PROTOCOL = 1`.
- [ ] They report `xfail` (not error) under `-n 4`.
- [ ] Commit: `G8 phase 0: the TCC-vs-CLI race pinned as an expected failure until the method locks itself (#171)`.

### Task 4 · #169 — `method_binding`: which copy a project runs, trusted or refused

Today every writer starts TCC's own `process.py` whatever the project links (`process_writer.py:92-93`), and an
existing link is «left alone whatever it points at» (`vendor_loader.py:236-237`). Decision 2: trusted links are a
known copy or one approved once on this machine; HUB-050's reason is origin, not shape.

**Files:** create `src/autosound_tcc/core/method_binding.py`; modify `src/autosound_tcc/core/config.py`
(`approved_methods() -> tuple[str, ...]`, `approve_method(path) -> bool` — QSettings key `method/approved`, a list
of realpaths; it reads the value back and answers False when the provider dropped it, `_NoSettings`
`config.py:175-182`); create `tests/test_method_binding.py`. Not wired to any caller in this task.

`for_project(project_dir)`, with `entry = project_dir / ".claude" / "skills" / "autosound-tuning"`:

| the entry | state | `can_approve` | the copy |
|---|---|---|---|
| absent (`os.path.lexists` false) | `same` | — | `vendor_loader.skill_dir()` |
| a link whose realpath is TCC's own copy's realpath | `same` | — | TCC's |
| a link to another `_candidates()` root that looks like the skill (realpaths compared) | `known` | — | that copy |
| a link to a realpath in `config.approved_methods()` | `approved` | — | that copy |
| a link to any other folder outside the project that looks like the skill | `refused` | yes | — |
| a broken link (target missing) | `refused` | no | — «points at X, which is not on this machine» |
| a link whose target is inside the project | `refused` | no | — |
| a real folder, not a link | `refused` | no | — «a copy inside the project cannot be trusted» |
| a target that is not a 3.x skill (`vendor_loader._looks_like_the_skill` false; a 2.x copy says so) | `refused` | no | — |
| `read_contract_version(target) > KNOWN_CONTRACT` (not checked for TCC's own copy — that is S3, W-10) | `refused` | no | — «newer than this TCC — update TCC first» |

«Is a link» is `os.path.realpath(entry) != os.path.join(os.path.realpath(entry.parent), entry.name)` — never
`realpath != abspath`, which is wrong whenever a parent folder is a link (macOS `/var`, pytest's temp folders, a
mapped drive); `os.path.lexists`, because a broken junction answers False to both `exists()` and `is_symlink()`.
Every `reason` is one English sentence naming the entry and what to do. `approve()` works only when `can_approve`,
stores the target's realpath, and raises `MethodRefused` when the value does not read back. `relink()` moves the
entry — a link is moved as a link, never followed — to `<project>/.tcc/method-aside/<YYYYMMDD-HHMMSS>/autosound-tuning`
(never left under `.claude/skills/`, where omp would still load it), calls `vendor_loader.link_skill_into(project)`,
and returns `for_project()` again.

- [ ] **Red tests**, on real folders under `tmp_path` (a copy of the vendored skill tree where a second copy is
  needed): one per table row; the parent-is-a-link case (the project reached through a symlinked parent with no
  entry, and with a link to TCC's copy, both read `same`); `contract_number` on a `contract.py` that raises on import
  still finds its number, and on v3.1.1's text answers None; `for_project` on an unreadable entry returns `refused`
  and never raises; `approve` with a settings provider that drops writes raises; `relink` leaves the old entry under
  `.tcc/method-aside/` and a link to TCC's copy in its place. Windows: the junction rows with a real
  `_winapi.CreateJunction`, `skipif(sys.platform != "win32")` — they go green on the Windows CI shard; their POSIX
  symlink twins go red first here.
- [ ] Red, build, green (`tests/test_method_binding.py tests/test_vendor_loader.py -n 4`).
- [ ] Commit: `G5 S1: method_binding — which copy a project runs, trusted or refused (#169)`.

### Task 5 · #169 — every `process.py` write runs the project's bound copy

**Files:** modify `method_cli.py` (`spawn` resolves `binding = method_binding.for_project(project_dir)`, the script
as `binding.script(script_rel)` — a `MethodRefused` becomes `Refused` with the same sentence — and the env as
`child_env(**binding.session_env())`); `process_writer.py` (`script_path()` and `is_available()` keep meaning TCC's
own copy for the zero-argument callers); tests `tests/test_method_cli.py`, `tests/test_process_writer.py`.

- [ ] **Red tests (the issue's first):** a project linked to an approved second copy (a `tmp_path` copy of the
  vendored tree whose `process.py` also appends one marker line to a file) → `enter_phase` runs **that** copy, and
  the child's env carries `AUTOSOUND_SKILL_ROOT` = its skill folder; a refused binding → `process_writer.Refused`
  with the binding's sentence and no child started (spy the runner); an absent entry → TCC's own copy as before.
- [ ] Red, build, green (`tests/test_method_cli.py tests/test_process_writer.py tests/test_mcp_server.py -n 4`).
- [ ] Commit: `G5 S1: process.py writes run the project's bound copy (#169)`.

### Task 6 · #169 N19 — a flag the bound copy does not know is refused before spawning

`process.py` parses flags by hand and absorbs the ones it does not know: in an older copy `capture-start --origin X`
turns `--origin` and `X` into expected titles (`process.py:3708-3711`), `skip --superseded-by` joins the reason
(`:3602-3610`). No usage error, so `_refuse_if_too_old` cannot see it. Ships in the same PR as Task 5.

**Files:** `method_cli.py` (for `state/process.py` only: every argument starting with `--`, cut at `=`, must occur
in the bound `process.py`'s text — read once per (path, mtime_ns, size) — else `Refused`: «this project's method
does not know <flag>; update it, or re-link the project to TCC's copy»); `tests/test_method_cli.py`,
`tests/test_process_writer.py`.

- [ ] **Red tests:** a `tmp_path` copy whose `process.py` has every `--origin` removed → `start_capture(...,
  origin="import")` raises `Refused` naming `--origin`, and no child starts (today it spawns and the flag becomes a
  title); the **behaviour pin** — call every writer in `process_writer` with every optional argument set, spy the
  argv, and assert the set of flags sent equals the 23 the map lists (`--project`, `--superseded-by`, `--review`,
  `--mode`, `--hp`, `--lp`, `--source`, `--amend`, `--reason`, `--pair`, `--text`, `--route`, `--ledger-version`,
  `--note`, `--track`, `--characteristic`, `--invalidates`, `--plan`, `--optional`, `--start`, `--step`, `--origin`,
  `--session`); a regex over the source cannot see the five assembled ones. The vendored v3.1.1 passes the check for
  all 23.
- [ ] Red, build, green.
- [ ] Commit: `G5 S1 N19: a flag the bound process.py does not know is refused before spawning (#169)`.

### Task 7 · #169 — the other method launchers run the bound copy

`profile_writer` (`:50-73`), `config_writer` (`:38-59`, no project argument today; its caller
`ui/tcc/save_config_dialog.py:99`), `project_repo` (`:43-92`), `contract_check` (`:207`) and `intake_form` (`:77`)
each start a script of TCC's own copy with a bare `subprocess.run`. They go through `method_cli.spawn(…, lock=False)`
for the bound script, the env and the bounded run; each keeps its own error type (a `Refused` becomes it, same
sentence) and its public signature — `contract_check.script_path()`/`is_available()` keep their zero-argument
meaning for TCC's own copy. Unchanged, TCC's own copy by design: `critic`, `reviewer_key`, `updates`' upkeep.

- [ ] **Red tests**, parametrised over the five: a project linked to an approved second copy → each runs the
  script from that copy (argv spy); a refused binding → each answers with the refusal and starts nothing. Re-point
  the patches at `tests/test_project_repo.py:19-31` and `tests/test_ledger_line.py:121,132`.
- [ ] Red, build, green (the five modules' test files, `-n 4`).
- [ ] Commit: `G5 S1: the other method launchers run the bound copy (#169)`.

### Task 8 · #169 N9 — the car is written by the method's `intake.py set-car`

`car_library.record` (`:124-151`) loads and saves `project.json` in-process with TCC's copy of `Project`; the verb
exists since v3.0.59 (`intake.py:1711-1717`, `save_car` `:1519-1543`). The method's rule wins: `set-car` refuses a
blank generation or body (MCP `save_car` defaults both to `""`, `mcp_server.py:876-897`), a body outside `BODIES`
(`intake.py:87`), and its refusal is an uncaught `IntakeError` — exit 1, the sentence on the last stderr line.

**Files:** `car_library.py` (`record` → `method_cli.spawn(project_dir, "intake.py", ["set-car", …], lock=False)`;
the year as text), `mcp_server.py` (the tool returns the method's sentence as its JSON error); tests
`tests/test_car_library.py:100-117`, `tests/test_mcp_server.py:1642-1663`.

- [ ] **Red tests:** argv spy — `record` sends `set-car` with the four parts and `--year`; a blank body → the
  method's sentence comes back and `project.json` is byte-identical; a good car lands in `project.json` written by
  the method.
- [ ] Red, build, green. Commit: `G5 S1 N9: the car is written by the method's set-car (#169)`.

### Task 9 · #169 F3d — the SDK session loads the bound copy, or says why it cannot

`plugins=[{"type": "local", "path": str(vendor_loader.skill_repo_root())}]` (`tuning_session.py:383`) sends the
string `"None"` when there is no repo root; the read roots (`_read_roots_for` `:176-194`) and the env (`:348`) name
TCC's copy whatever the project links.

**Files:** `tuning_session.py` (`start` takes `binding = method_binding.for_project(project_dir)`; `binding.require()`
first — a `MethodRefused` ends `start` with its sentence, which `AgentWorker` already shows as a failed bubble,
`dialog_panel.py:915,1409`; `plugins` from `binding.plugin_root()`, refused with «this method copy has no plugin
manifest» when None; the read roots from the bound copy; `AUTOSOUND_SKILL_ROOT` merged into the env at `:348`, NOT
into `critic.session_env` — six exact-dict pins in `test_critic.py`). `TuningSession.__init__` stays cheap and never
refuses (the probe at `main_window.py:5164` builds one only to read the registry). Tests
`tests/test_tuning_session.py:680-702`.

- [ ] **Red tests:** a project linked to an approved copy → `options.plugins` names that copy's repo root and the
  env carries its `AUTOSOUND_SKILL_ROOT`; a copy with no manifest → the sentence, never `"None"`; a refused binding →
  `start` raises with the binding's sentence; no link → today's options unchanged.
- [ ] Red, build, green. Commit: `G5 S1 F3d: the SDK session loads the bound copy or says why not (#169)`.

### Task 10 · #169 N4 — omp and the terminal route run the bound copy

omp loads the project's link (`omp_session.py:898-915`, `includeSkills` `:328`) while the writers ran TCC's copy;
the terminal route (`main_window.py:2644,5908` → `terminal_launcher.launch` `:400-452`) passes only
`critic.session_env`.

**Files:** `omp_session.py` (`start` calls `binding.require()` before spawning; `AUTOSOUND_SKILL_ROOT` merged at
`:963`); `terminal_launcher.py` (`launch` already has `project_dir`: it merges `binding.session_env()` itself, so
`main_window.py` is untouched); tests `tests/test_omp_session.py:999-1018` (`seen["env"]`), `:620-626` (an empty
`autosound-tuning` folder now refuses — the test changes to say so), `tests/test_terminal_launcher.py`.

- [ ] **Red tests:** omp's spawn env carries the bound `AUTOSOUND_SKILL_ROOT`; an unapproved link → omp refuses with
  the sentence and spawns nothing; the terminal launch's env carries it too.
- [ ] Red, build, green. Commit: `G5 S1 N4: omp and the terminal route run the bound copy (#169)`.

### Task 11 · #169 — a diagnostics row names the project's copy and offers the two fixes

Decision 1: in-process reads stay on TCC's copy, so the Arbiter must be able to see when the project runs another
one. A row in the self-check block (`self_check.py:349-362`, rows `diagnostics_panel.py:1688-1777`):
same → no row; known/approved → «this project runs the method at <path>, not TCC's own»; refused → its reason, with
«approve on this machine» (only when `can_approve`) and «re-link to TCC's copy». `_CheckRow` carries one fix button
today (`:280-320`): give the check a tuple of actions, both only on refused. The D-6 pin
(`test_self_check.py:76-84`, fixes may only touch aliases and the catalogue) widens to these two, each by the
Arbiter's click and never automatic, with that reason in the test. `self_check.run()` runs on the GUI thread, so
the contract number is read through the cache. Strings through `i18n.py` (uk, en; pl and de the English).

- [ ] **Red tests:** one row per state; «approve» calls `method_binding.approve` and the row then says approved;
  «re-link» leaves the old entry under `.tcc/method-aside/` and the row disappears; refused for a real folder → no
  approve button.
- [ ] Red, build, green (`tests/test_self_check.py tests/test_diagnostics_panel.py -n 4`). Commit:
  `G5 S1: diagnostics names the project's method copy and offers approve and re-link (#169)`.

### Task 12 · #170 — the update press refuses a method newer than this TCC

**Files:** `updates.py` — inside `_extract_upkeep` (`:869-901`), after the tag is verified (`:885`) and before the
`_UPKEEP_FILES` loop (`:889`): `method_binding.contract_number(_git_blob(clone, tag, <skill>/rew_tool/contract.py))`;
a number above `KNOWN_CONTRACT` refuses with reason `newer_contract`, so `local_changes` and `apply_skill` both
refuse before keep-local; `i18n.py` `updWhy_newer_contract` («this method is newer than this TCC — update TCC
first»; uk and en, pl and de the English). Tests `tests/test_updates.py` on real git (`_skill_repos`, `_add_upkeep`,
`_runs`, `:441-549`); `_fake_upkeep` (`:212-237`) replaces `_upkeep_from_tag`, so the new test uses the real one.

- [ ] **Red test (the issue's first):** a tag whose `contract.py` says `CONTRACT_VERSION = 2` → `local_changes` and
  `apply_skill` refuse with `newer_contract`, `_runs(log) == []`, the temp folder is empty and the clone's HEAD is
  unchanged; a tag with no number installs as today; the diagnostics row shows the sentence
  (`test_diagnostics_panel.py:1445-1480`).
- [ ] Red, build, green. Commit: `G5 S2: the update press refuses a method newer than this TCC (#170)`.

### Task 13 · #170 F16-3 — a TypeError inside the method is not taken for an old signature

`rew_bridge.py:101-108` calls with `smoothing=` and retries without it on any `TypeError` — so a `TypeError` raised
inside a method that does take `smoothing` is swallowed and the call repeated; `capture_import.py:526-531` drops a
verdict's `TypeError` with `continue`, logging nothing.

**Files:** `rew_bridge.py` (`inspect.signature` decides whether to pass `smoothing`; no retry), `capture_import.py`
(the exception is logged with its traceback and the row says «could not judge: <error>» instead of vanishing);
tests `tests/test_rew_bridge.py`, `tests/test_capture_import.py`.

- [ ] **Red tests:** a reader that takes `smoothing` and raises `TypeError` inside → the error propagates, called
  once; a reader without `smoothing` → called once without it; a verdict that raises → logged, and the row carries
  the «could not judge» verdict.
- [ ] Red, build, green. Commit: `G5 S2 F16-3: a TypeError inside the method is not mistaken for an old signature (#170)`.

### Task 14 · #170 — `method-newest.yml`: TCC's suite against the newest method tag

Ruling 2: `schedule` (nightly) and `workflow_dispatch`, no `push`. One macOS job (the Linux whole-suite run aborts
about half the time, HUB-049, `ci.yml:224-230`): checkout with submodules; the tag `updates.newest_tag()` picks
(what the app offers); the submodule checked out at it; `AUTOSOUND_SKILL_DIR=<submodule>/skills/autosound-tuning`
(conftest moves HOME); the suite through `uv run --locked`; no `continue-on-error`. It runs the skill's own
selftests too, so a red run can be the skill's — the run's title names the tag.

**Files:** create `.github/workflows/method-newest.yml`; a CI-file test in `tests/test_ship.py` (model `:839-902`).

- [ ] **Red test:** the workflow's triggers are exactly `schedule` and `workflow_dispatch`; no job has
  `continue-on-error`; the tag comes from `updates.newest_tag`; every `uv run` has `--locked`.
- [ ] Red, build, green. Commit: `G5 S2: method-newest.yml runs TCC's suite against the newest method tag (#170)`.
- [ ] After the PR merges, the controller dispatches it once and reads the result.
