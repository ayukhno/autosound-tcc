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
the method vendored at `vendor/autosound-tuning-skill` (v3.1.1, `e8dabf7`; v3.1.2, `d9633fa`, since Task S2).

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
- `vendor/autosound-tuning-skill/` is a submodule pinned at v3.1.2 (since Task S2) and is never edited. A test that needs another
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
- **`core/method_cli.py`** — `ProcessWriterError` moves here, with `Busy(ProcessWriterError)` and
  `Refused(ProcessWriterError)`; `process_writer` re-exports all three names, so every
  `except process_writer.ProcessWriterError` keeps working; `spawn(project_dir, script_rel, args, *, timeout_s, lock=True, lock_wait_s=None)
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
constants move; the issue's «N1 and `handoff` move into `process_writer`»: it gains
`supersede_capture(project_dir, wrong, right) -> tuple[int, str, str]` and `handoff_json(project_dir) ->
tuple[int, str, str]` — the exit code kept, since it is the answer, and `_refuse_if_too_old` applied — and
`title_fixes.supersede` and `handoff.check` call them; `LANDED_IN` gains `capture-supersede` and `handoff`, each with the first tag whose `process.py` has
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

---

## G9+G3+G4 · Bounded waits, truthful stores and updates (#172–#174)

Anchors in `map-G9-G3-G4.md`. No task here needs `main_window.py` except Task 21, which stays line-neutral.

### Task 15 · #174 F10a, T-35, F13 — the newest tag, the signature check, the pairing (three commits, one review)

Three small fixes, each its own red test and commit:

1. **F10a** — `newest_tcc_tag()` (`updates.py:536-540`) ranks with `_version_key` (`:402`), which keeps every `v*`
   name, so `v1.2.0-wip` outranks `v1.1.1` and the press refuses it as a bad signature. Rank over release-shaped
   names only (`_release_key` `:775` / `channel_key` `:411` already answer None for anything else). Red:
   `newest_tcc_tag()` over `v1.1.1, v1.2.0-wip, v1.1.1.1` (the `_git_answers` helper, `test_updates.py:19-32`) →
   `v1.1.1`. Commit `G4: the newest TCC tag is ranked over release-shaped names only (#174)`.
2. **T-35** — `_verify_tag` (`:803`, the call `:829-830`) runs `git verify-tag` without pinning `gpg.ssh.program`, so
   a signing helper in the user's git config (1Password's) refuses a good release; the classifier (`:766-772`)
   matches a bare `"-Y"`. Pin `-c gpg.ssh.program=ssh-keygen` in that argv and classify on git's own sentences.
   Red: the `_git` spy's argv carries the pin (`test_updates.py:1465-1477`); a text that merely contains `-Y` is not
   classified; the five sentences at `test_updates.py:600-643` still are. Commit `G4 T-35: verify-tag pins
   gpg.ssh.program and classifies on git's sentences (#174)`.
3. **F13** — `scripts/ship.py:297` accepts `method_sha.startswith(said) or said in method_sha`: one character
   pairs. Require a ≥7-character prefix, no substring. And every `uv run` in `.github/workflows/ci.yml`
   (`:146,189,193,255,331`) gets `--locked`; `:189` runs with `--no-project`, where the lock does not apply — the
   scan exempts a `--no-project` line, with that reason in the test. Red: `check_paired_method(…)` with `said="a"`,
   and with `said="e"` against a sha containing `e`, → `Stop` (`test_ship.py:58-66,349-354`); a line scan of
   `ci.yml` (model `test_ship.py:815-836`). Commit `G4 F13: the pairing check needs a 7-character prefix; CI runs
   uv --locked (#174)`.

- [ ] Each: red, build, green (`tests/test_updates.py tests/test_ship.py -n 4`), commit.

### Task 16 · #174 F10b N6 — every install hint is the one install command, and the README names its tag

Four hints are literals and three are wrong: `app.py:43-50` `_NO_GUI` (`[gui]` only), `claude_sdk.py:33-36`
`INSTALL_HINT` (`[claude]` only), `desktop_entry.py:146-166` `_launcher_script` (no URL, no `--python` — it would
not work), `protective.py:111-115` (`[gui]` only); `README.md:186` names no tag. All four come from
`updates.tcc_install_command("")` (`:91-104`; its text is pinned in ~25 places — it does not change). Hazards from
the map: `_NO_GUI` is `str.format`ted (`app.py:498,571`) — no braces but `{error}`; the AppleScript alert puts the
command inside a double-quoted string — escape `"`; `app.py` importing `core.updates` must keep the light install
importable with Qt blocked (`test_packaging.py:126-140`).

**Files:** `app.py`, `claude_sdk.py`, `desktop_entry.py`, `protective.py`, `README.md`; tests
`tests/test_packaging.py` (`:135` `"[gui]"` and `:436` `"[claude]"` change), `tests/test_desktop_entry.py`, a new
README test.

- [ ] **Red tests:** one test parametrised over the four hints asserts `--python 3.12`, `git+https://` and
  `[gui,claude]` (the URL part alone passes today for two); the README's install line names `@v<version>` and that
  version equals `pyproject.toml`'s (the controller's version commit then updates README too — the test is what
  makes it remembered).
- [ ] Red, build, green. Commit: `G4 F10b N6: every install hint is the install command; README names its tag (#174)`.

### Task 17 · #173 — an unreadable store is moved aside and said, never written over: the helper and `project_settings`

`project_settings.load` (`:33-43`) reads any `OSError`, bad JSON or non-dict as `{}`, and `set_value` (`:51-79`)
then rewrites the file — model choices, ticks, delays and import answers gone (F5). An ERROR line does not reach the
strip today: `app_log._notify` runs only from the two excepthooks (`app_log.py:230-267`), so the report needs its own
call.

**Files:** create `src/autosound_tcc/core/own_store.py` (light, Qt-free): `read_json(path) -> dict` — absent → `{}`;
bad JSON, bad UTF-8 or a non-dict → the file is moved to `<same folder>/<name>.corrupt-<YYYYMMDD-HHMMSS>`, reported,
and `{}` returned (the next write starts a fresh file; the original bytes are kept); any other `OSError` → reported
and `StoreUnreadable` raised from writes, `{}` from reads — never written over; `write_json(path, data)` — mkstemp
in the folder, write, `flush`, `os.fsync`, `os.replace`. A report is made once per file state, not on every read.
Modify `app_log.py` (`report(message)`: an ERROR log line and the UI sink, re-entrancy guarded — a sink that raises
is logged once and never recurses), `project_settings.py` (through the helper). Tests `tests/test_own_store.py`,
`tests/test_project_settings.py`, `tests/test_app_log.py` (model `:56-64`; patch `_log_path`, `:253`).

- [ ] **Red tests:** a trailing comma in `tcc-project.json`, then `set_value` → exactly one `*.corrupt-*` holding
  the original bytes, the new file holds only the new field, and the sink heard one message naming the file;
  `os.fsync` is called before `os.replace` (spies, model `test_mcp_server.py:1680`); an absent file → `{}`, nothing
  moved, nothing said; a reader that cannot open the file (permission) → `set_value` raises `StoreUnreadable` and the
  file is untouched. `delay_bank` callers keep working (`tests/test_curve_view.py` bank tests, `-n 4`).
- [ ] Red, build, green. Commit: `G3: an unreadable settings store is moved aside and said; writes fsync (#173)`.

### Task 18 · #173 — the import store, `sessions.json` and the signal log (one dispatch, three commits)

The same helper, same shape: `capture_import` (`_section` `:133-140` reads twice per write, `_write_store`
`:143-157`); `session_registry` (`load` `:51-59` raises `AttributeError` on a valid non-dict; `_write` `:122-128`
uses a fixed `sessions.json.tmp` that two registries share — `mcp_server.py:1822`, `tuning_session.py:213` —
mkstemp instead); `signal_bus` (ruling 10: no replace there; read with bad UTF-8 tolerated and the line skipped).
`tests/test_session_registry.py:63-70` pins the overwrite: it turns around (one `*.corrupt-*`, then the fresh phase).

- [ ] **Red tests:** for the import store and `sessions.json`, the Task 17 test shape (a damaged file, then a write
  → one aside copy with the original bytes, said once); `sessions.json` holding `[]` → aside, no `AttributeError`;
  a signal log with invalid UTF-8 → the bus constructs and restores the good lines.
- [ ] Each: red, build, green, commit `G3: <store> moves an unreadable file aside (#173)`.

### Task 19 · #173 F16-6 — `.mcp.json`: unreadable is not empty, and one instance does not remove another's entry

`write_mcp_config` (`mcp_server.py:1667`) reads any `OSError`/`ValueError`/non-dict as `{}` and replaces the file
(the user's other servers lost); `forget_mcp_config` (`:1639`) pops the key `"tcc"` whatever instance wrote it — so
instance A's quit removes instance B's live entry. W-8 left: `write_mcp_config` replaces the file on any `OSError`
while reading.

**Files:** `mcp_server.py` — through `own_store`, with the aside copy in `<project>/.tcc/` (ruling 9; it carries the
token, and `_IGNORE_LINES` `:1590` covers `.tcc/` only); `forget_mcp_config(project_dir, port=None, token=None)`
removes the entry only when it is this instance's (port and token match; the one-argument call keeps today's
meaning for the tests at `test_mcp_server.py:551-576,745`); `stop()` passes its own. Tests `tests/test_mcp_server.py`
(two real servers, model `:789-799`).

- [ ] **Red tests:** `.mcp.json` written by A, then by B; A's `stop()` → B's port is still there; a damaged
  `.mcp.json` → its bytes are under `.tcc/`, the user's other servers are in that copy, the strip is told; an
  unreadable one (permission) → not written over.
- [ ] Red, build, green. Commit: `G3 F16-6: .mcp.json is not written over when unreadable, and A does not remove B (#173)`.

### Task 20 · #172 — `osascript` is bounded, and the three history reads are remembered (one dispatch, two commits)

1. `terminal_launcher._osascript` (`:300-309`) has no timeout; the realistic hang is macOS's Automation prompt,
   which `osascript` waits on. Bound it at 30 s; `TimeoutExpired` becomes `TerminalLaunchError` with a sentence
   that names the likely cause («macOS may be asking whether TCC may control Terminal — allow it in System Settings
   → Privacy & Security → Automation, then try again»); `launch` (`:453`) maps it like the other two. Red: a fake
   `subprocess.run` that raises `TimeoutExpired` → `TerminalLaunchError` with that sentence (the `recorded`
   fixture, `test_terminal_launcher.py:19-40`, asserts `timeout=` is passed).
2. A stat-memo for the reads that grow with history — each keyed by `(path, st_mtime_ns, st_size)` of every file it
   reads, returning a copy: `critic.last_call` (`:905-919`, the whole `critic-log.jsonl`), `ledger_line._made_for`
   (`:92-99`, write-once version files), `process_view.stale_channels` (`:365-418`, the journal plus `project.json`
   and the glossary). In-house idiom: `critic.py:136-162`. Red, for each: a second call reads nothing (spy the
   read); a changed file (same size, new mtime) is read again.

- [ ] Each: red, build, green (`tests/test_terminal_launcher.py tests/test_critic.py tests/test_ledger_line.py
  tests/test_process_view.py -n 4`), commit `G9 S1: …(#172)`.

### Task 21 · #172 — a reload starts at most two git children, and the callers not about git start none

`git_status` (`project_view.py:414-464`) spawns 6–7 children per call (7 on macOS with `/usr/bin/git`), and five
callers not about git — reviewer pick, generator pick, effort, gate mode, the language switch (`main_window.py`
`_set_project_params(…)` at :4565, :5534, :5547, :5774, :6218) — pay the full probe.

**Files:** `project_view.py` — `_git_works` remembered per process, keyed on `shutil.which("git")` (so
`test_project_view.py:348-353` still sees a missing git); the redundant `rev-parse --git-dir` goes; branch, dirty
state and ahead count from one `git status --porcelain=v2 --branch`; the remotes from one `git remote -v`;
`git_status(project_dir=None, *, reuse=False)` — `reuse=True` answers the last result for that project when there is
one. `main_window.py`, line-neutral: `_show_git_state(self, reuse=False)` passes it, `_set_project_params(self, view,
reuse_git=False)` passes it, and the five callers above pass `reuse_git=True` (a reload and `_after_git` stay fresh).
Tests `tests/test_project_view.py`, `tests/test_project_repo.py:69-85` (it flips git state under a live window and
must stay green: each `_set_project_params(None)` there is a fresh read).

- [ ] **Red tests:** `git_status` on a real repo with an `origin` and an upstream (model `test_project_view.py:315-345`)
  starts at most two git children (spy `project_view.subprocess.run`) and answers the same facts as today's code on
  the same repo (branch, dirty, ahead, remote URL; also detached, no upstream, no remote); `reuse=True` starts none;
  the language switch on a live window starts no git child (extend an existing window test — no new build).
- [ ] Red, build, green; `main_window.py` line count unchanged (`tests/test_structure_ratchet.py`). Commit:
  `G9 S1: a reload starts at most two git children; callers not about git start none (#172)`.

### Task 22 · #172 — the seed preview is debounced and remembered

`_would_travel` (`new_project_dialog.py:456-494`) runs the vendored `seeder.seed(...)` in-process on the GUI thread
into a temporary folder — its last act is `project_repo.init` (6–8 git children, plus `gh api user` with a 30 s
bound when no git identity is set). The seed-source edit, the toggles and the seat and profile combos redraw at once
(`:424`, `:282`, `:290`, `:303`, `:317`); only vendor and model go through the 250 ms timer (`:193-195`), and an
identical preview after `_prefill_dsp` seeds again (`:450-453`).

**Files:** `new_project_dialog.py` — every trigger through the one timer; the last preview remembered under a key of
every input the seed reads (the dialog's fields and toggles, the profile choice, and the source folder's
`project.json`, `dsp_profile.json` and prose files by `(path, st_mtime_ns, st_size)`); `tests/conftest.py` sets
`AUTOSOUND_NO_GH=1` for every test (the real seeder must not reach `gh` from a test). Tests
`tests/test_new_project_dialog.py` (`_StubSeeder.seeded_into` `:221-256`, `_dialog_on` `:258-265`; `:363-382`
asserts a re-seed after a vendor change and must stay green).

- [ ] **Red tests:** a second identical preview runs no seed; a changed toggle runs one; five quick edits of the seed
  source run one seed after the timer, none before it.
- [ ] Red, build, green. Commit: `G9 S1: the seed preview is debounced and remembered (#172)`.

### Task 23 · #172 — two guards in `conftest`: an import on a worker thread, a modal from a callback

§5.1's two pieces of «Clean»: they enforce `install_report.py:11-16` (imports at the top; PySide6's import hook costs
per executed import) and TA-6 (modals in worker and timer slots) mechanically. Last in the group, because they can
turn other tests red.

**Files:** `tests/conftest.py` only, after the existing guards (`:374`).

- **Import guard:** wrap `builtins.__import__` (it sees every executed `import`, which `sys.meta_path` does not);
  an import executed on a thread that is not the main thread fails the test, naming the importing file and line —
  except an allowlist of today's sites, each with its file and function (the map's first hits: `app_log.py:73`,
  `critic.py:884`, `availability.py:140,145,171,213`, `model_choices.py:501,521,819,907`, `workers.py:205`,
  `reviewer_key.py:245`). The allowlist may only shrink: a test pins its length.
- **Modal guard:** the existing `_ModalLog` (`:283-374`) learns «opened while the event loop dispatches»: a depth
  counter around `QCoreApplication.processEvents` and the event-loop `exec`s; a modal `exec()` at depth > 0 fails,
  except today's sites in an allowlist pinned the same way.
- [ ] **Red tests** (a `tests/test_conftest_guards.py`): an import on a worker thread fails a test (run the inner
  test with `pytester`, or call the guard's check directly); an allowlisted site does not; a modal opened from a
  `QTimer.singleShot` slot fails; one opened directly by a test does not.
- [ ] Green on the files the allowlist names and on `tests/test_mcp_server.py tests/test_main_window.py -n 4`; the
  full suite before the PR is where a missed site shows — the fix is an allowlist line with its reason, or a hoisted
  import.
- [ ] Commit: `G9 S1: conftest fails an import on a worker thread and a modal from a callback (#172)`.

---

## G6+G7 · The method's answers on screen (#175, #176) — Fable's final review of G7's refusal paths

Anchors in `map-G6-G7.md`. Build order: Tasks 24–29.

### Task 24 · #176 F5 — a half-written plan is not an empty one, and the watcher stays armed

`process_view.load_state` (`:71-79`) returns `Process.load()`, which answers `_empty_state()` for an unparseable
file (the skill's `process.py:974-986`), so the window's guard (`main_window.py:3670-3676`, «the file is there but
did not read as state») never fires: the plan blanks to seven empty phases. The test that should catch it
(`test_main_window.py:1636-1659`) asserts only that the plan is truthy, which an empty state also is. Two hazards
the issue does not name: `mcp_server._load_process_state` (`:577-588`) has the same blind spot (a corrupt file
reads as «no active phase»); and once the guard can fire, it returns before the watcher's re-arm (`:3717-3721`),
so after an atomic replace the plan would freeze.

**Files:** `process_view.py` (one helper, `read_state_text(project_dir) -> dict | None`: the file parsed as JSON and
required to be a dict — `OSError`, `ValueError` (incl. `UnicodeDecodeError`), JSON `null` or a list → None — and
only then `Process.load()`; `load_state` and `mcp_server._load_process_state` both use it; `_load_process_state`
answers `(None, "process-state.json could not be read")`), `main_window.py` (the re-arm moves to the top of
`_refresh_process`, before any early return — a move, line-neutral), tests `tests/test_process_view.py`,
`tests/test_main_window.py:1636-1659`, `tests/test_mcp_server.py`.

- [ ] **Red tests:** the half-written test asserts the step is still there — `"xo" in [s.id for p in
  window._plan_panel.plan for s in p.steps]` (red today); `load_state` → None for `{ half`, an empty file, `null`,
  `[]` and an unreadable file (model `test_process_view.py:52-55`); `report_phase` on a corrupt file answers the
  reason, not «no active phase»; after the guard fires, the watcher still holds the path (extend the same window
  test — no new build).
- [ ] Red, build, green; `main_window.py` line count unchanged. Commit: `G7 F5: a half-written plan is not an empty
  one, and the watcher stays armed (#176)`.

### Task 25 · #176 F4 — `write_rew_filters` runs off the event loop and says what failed

`write_rew_filters` (`mcp_server.py:1213-1244`) calls `rew_api.find_measurement_id` and `set_filters` on the event
loop; `find_measurement_id` raises `KeyError` for none and for several (`rew_api.py:265-291`) — it never returns
None, so `if mid is None` (`:1241-1242`) is dead and the `KeyError` escapes as a tool error; REW down raises an
`OSError`/`URLError`. TCC does **not** check `gain`/`gaindB` itself (the skill's K-1).

**Files:** `mcp_server.py` — `vendor_loader.load_rew_api()` stays on the loop, before `_in_thread` (its `_LOCK`, and
Task 23's import guard); then one sync inner function through `_in_thread` doing the lookup and the write; `KeyError`
→ `{"applied": false, "error": exc.args[0]}` (`str(KeyError)` adds quotes — idiom `curve_dialog.py:129`);
`OSError` (incl. `URLError`/`HTTPError`) and `ValueError` → `{"applied": false, "error": "REW: <message>"}`; the
dead branch goes. Tests `tests/test_mcp_server.py` (`RecordingBridge(allow=True)`, `_server`, `_text` `:32-89`;
thread identity `:2517-2553`; REW is already dead in tests, `conftest.py:182-228`).

- [ ] **Red tests:** REW down → `applied: false` and an error; a missing title through the real
  `find_measurement_id` (patch `get_measurements` with a dict) → the same JSON shape with the method's words;
  `set_filters` records its thread → not the loop's.
- [ ] Red, build, green. Commit: `G7 F4: write_rew_filters runs off the event loop and says what failed (#176)`.

### Task 26 · #175 D-1 — the DSP profiles come from the skill's library

TCC ships its own older Helix file (`src/autosound_tcc/dsp_profiles/helix-dsp-ultra-s.json`, no schema version) and
the picker reads that folder, so the skill's richer `audiotec-fischer-helix-dsp-ultra-s.json` (schema 3) is never
offered and Musway is unreachable (F8).

**Files:** `config.py` (`bundled_profiles_dir()` → `Path(vendor_loader.load_dsp_profile().bundled_dir())` — it
returns a `str`; `DEFAULT_BUNDLED_PROFILES_DIR` goes); `new_project_dialog.py` (the picker from `list_bundled()` —
`(vendor, model, path)` triples; with the skill not loadable it offers only «Add new» and logs a warning, so the
dialog still opens, `:63-73,141-162`); delete `src/autosound_tcc/dsp_profiles/`; tests
`tests/test_packaging.py:292-303` (turned around: the package carries no `dsp_profiles/`, and the dir is the
skill's), `tests/test_resonalyze_import_dialog.py:59,252` (the skill's file by its name — re-run, it is richer),
`tests/test_new_project_dialog.py` (model `:56-81`). `test_mcp_server.py:835,858` patch
`config.bundled_profiles_dir` — the seam stays.

- [ ] **Red tests:** the turned-around packaging test; the picker lists Helix, then Musway, then «Add new»;
  `check_existing_profile("Musway", "M6V4")` finds the bundled one.
- [ ] Red, build, green. Commit: `G6 D-1: the DSP profiles come from the skill's library (#175)`.

### Task 27 · #175 F6 N2 N16 — a superseded capture is not done: the fold, `standing()` and parity

A title taken and then superseded still counts as taken in TCC: no reader knows `superseded_by` (the skill's rule
is `_is_taken`, `process.py:819-822`: `isinstance(entry, dict) and not entry.get("superseded_by")`); the fold
(`process_view.py:98-187`) has no `capture_superseded` branch, does not pop `skipped` on a take (the skill does,
`process.py:1518`; N16), and ignores the closed event's `outstanding`/`skipped`. Notes from the map: the last round
is merged from the state file and already carries `superseded_by`, so a fold test needs two rounds;
`reconcile_captures` takes and un-skips with no `capture_taken` event, so a past round's truth is its closed event;
the closed event's `taken` includes superseded titles (N17) — do not read it; a missing `outstanding` key (an older
journal) is not `[]`.

**Files:** `process_view.py` — `standing(round_) -> dict[str, dict]` mirroring `_is_taken` exactly; the fold learns
`capture_superseded`, pops `skipped` on `capture_taken`, and takes a closed round's `outstanding` and `skipped` from
its event when present; the nine raw reads outside the window go through `standing()`
(`measurement_view.py:121,340,438,453,467,651` — the verdicts are built from `standing()` only, so a same-key
supersede cannot colour the corrected row, `:465-471`; `protective_dialog.py:496`; `curve_dialog.py:1045`;
`measurement_panel.py:1333`). Fixtures from a real `Process` (T-29): a shared `tests/_rounds.py` built from
`test_measurement_view.py`'s `_round`/`_as_typed` (`:276-311`) plus `supersede_capture`; never a hand-written
journal (the existing shape tests at `test_measurement_view.py:436-468,608-621,817-829` and
`test_process_view.py:500-555` stay as shape tests).

- [ ] **Red tests (the issue's first):** a real round with `w-R_1` taken and then superseded → the panel's waiting
  rows (status wait or found, by `name_key`) equal `capture_outstanding()` — no `optional` titles in the fixture,
  which TCC does not read; a same-key supersede (`w_R_1 (sw)` → `w-R_1 (sw)`), checked on both lookups (by raw
  title and by key); an older closed round after a supersede, and after a skip-then-take (two rounds); a closed
  event's `outstanding` read, and one without the key.
- [ ] Red, build, green (`tests/test_process_view.py tests/test_measurement_view.py tests/test_measurement_panel.py
  tests/test_protective_dialog.py tests/test_curve_view.py -n 4`). Commit: `G6 F6 N16: a superseded capture is not
  done — standing() and the fold (#175)`.

### Task 28 · #175 TA-8 — «settled» is decided once

Three places decide whether a capture's verdict needs the Arbiter: the window's `settled` (`main_window.py:
4048-4056`), the text parse in `_on_capture_check_done` (`:4111-4159`, «UNUSABLE <title> — », sliced again at
`:4149` and in `_show_unusable` `:4193`), and `measurement_view.status_for` (`:496-535`, past rounds `:671-683`).
Settled is not one boolean: «absent» is waiting on the card and «check again» in the window.

**Files:** `measurement_view.py` — `verdict_state(verdict, title, as_is, window) -> str`, one of `fine` (ok, or the
check does not apply), `as_is` (answered as it is), `own_range` (held by the window — tcc#149's patch, kept in this
one place so dropping it after hub #247 is one deletion), `absent`, `bad`; the card, the window's check loop and the
strip all read it. `main_window.py` — `_on_rew_titles_changed` and `_on_capture_check_done` call it;
`_on_capture_check_done` reads the verdicts the method recorded instead of parsing the text — `bad` = asked titles
whose recorded verdict is `bad`; the strip's lines are rebuilt as `<title> — <issues joined by "; ">`; a refused
check (nothing recorded) reports nothing, never «everything is bad». The window loses lines: lower
`MAIN_WINDOW_MAX_LINES` to the measured count in this commit, and `WINDOW_BUILDS_MAX` by the builds the moved tests
free (`test_main_window.py:5774-5793,5830-5849,5887-5936,7491-7523,7526-7588`, `test_title_fixes.py:95-113`,
`test_intake_window.py:254-272` — to plain tests on `verdict_state` over a real recorded round; `Process.check_captures`
with a fake verifier records verdicts without the private `_write`), and update the ratchet's docstring list
(`test_structure_ratchet.py:10-14`).

- [ ] **Red tests:** `verdict_state` over a real recorded round, one per state; the strip after a check is built from
  the recorded verdicts (a line for each bad one, none for as-is or own-range); a refused check says nothing.
- [ ] Red, build, green; both ratchet bounds measured and lowered. Commit: `G6 TA-8: «settled» is decided once,
  from the recorded verdicts (#175)`.

### Task 29 · #175 — the last raw reads of `taken`, and a scan that keeps it so

**Files:** `main_window.py:4167,4180,4315` → `process_view.standing(round_)` (line-neutral); a source scan in
`tests/test_process_view.py` (model `tests/test_model_choices.py:661-677`): outside `process_view.standing` and the
fold, no `.get("taken")` and no `["taken"]` in `src/`.

- [ ] Red (the scan names the three), build, green. Commit: `G6: standing() is the only reader of taken (#175)`.

---

## G10 · The curve window (#177)

Anchors in `map-G10-G13.md`. No test counts writes, loads or renders today, so these are new red tests, not
rewrites; the bank tests that read the bank after `set_delay` (`test_curve_view.py:1116-1462,3761-3896`) must stay
green, and `delay_bank.put` stays (fixtures write with it). The M part (`setData`, the crash history
`curve_view.py:361-478`) is W-12's.

### Task 30 · #177 TA-4 — one bank write and one readout render per step (two commits)

1. **One write.** `CurveDialog._bank_current_delay` (`curve_dialog.py:1353-1383`) calls `delay_bank.put` once per
   trace; each `put` loads the store and `set_value` loads it again — 2N+2 loads and N writes per step. Add
   `delay_bank.put_many(readings, tcc_dir=None, session=None)` over `delay_bank.Reading(title, ms, arrival_ms=None,
   allpass=_KEEP)` items (one load, one `set_value`; the store ends exactly as N `put`s leave it — all-pass kept,
   arrival, series) and use it there; `project_settings` keeps its API (Task 17 changes its
   inside). Red: a seven-trace dialog, one `set_delay(0.26)` → `project_settings.set_value` called once (today 7) and
   `load` called the same number of times for 2 and 7 traces (spy through the module; `_dialog()` `:63-73`);
   `put_many` stores exactly what N `put`s store.
2. **One render.** `set_delay` (`curve_view.py:1414-1442`) renders the readout inside `set_traces` and again after
   it; in the dialog `_sync_channel_delay` (`curve_dialog.py:1347-1351`) renders once more per trace through
   `set_channel_delay` (`:1449-1458`) — 2+N per step; `set_allpass` (`:1609-1637`) does the same. Skip the direct
   render when `set_traces` ran; add `CurveView.set_channel_delays(values)` (one render) and use it in
   `_sync_channel_delay`; the same two changes in `set_allpass`. Red: `set_delay` on a seven-trace view →
   `_render_readout` once (today 2); in a dialog with a delays provider → once (today 2+N).

- [ ] Each: red, build, green (`tests/test_curve_view.py tests/test_delay_bank.py -n 4`), commit
  `G10 TA-4: … (#177)`.

### Task 31 · #177 TA-11 TA-7 — one render per marker move, and `tip_html` out of `curve_view` (two commits)

1. **Marker move.** In vhs mode `_sync_levels` (`:3516-3530`) moves the h-line, which fires `_on_marker_moved`
   (`:3498-3502`) again — two renders and two `markersChanged` per move; `_syncing` guards only `_sync_levels`. Return
   from `_on_marker_moved` while `_syncing`. Red: vhs, one `_markers[0].setValue(…)` → one render and one
   `markersChanged` (model `test_curve_view.py:635-649`); v, h, vh, vx, hx pinned at one.
2. **`tip_html` out.** `main_window.py:131` imports `tip_html` from `curve_view`, which imports pyqtgraph and numpy
   at module level (`curve_view.py:33-34`) — ~0.34 s at start for a function that needs neither. Move `tip_html`,
   `_wrapped` and `_TIP_FONT_PX`/`_TIP_WRAP_CHARS` into `ui/tcc/rounded_tooltip.py` (it imports only `theme`);
   `curve_view` and `curve_dialog` import them from there; `import textwrap` leaves `curve_view` (ruff F401);
   `main_window.py:127-131` shrinks to the one import (lines out — measure the ratchet); the comment at `app.py:487`
   is corrected. Red, first: a golden test of `tip_html`'s output (text, head, warn, the 72-character wrap) against
   today's function — it must pass before and after the move; then a fresh interpreter (model
   `test_main_window.py:5745-5771`: a `QApplication` first, then `import autosound_tcc.ui.tcc.main_window`) →
   `"pyqtgraph" not in sys.modules` (red today). The probe's text must not contain the literal `MainWindow(` (the
   ratchet counts it).

- [ ] Each: red, build, green, commit `G10: … (#177)`.

---

## G13 · A slice out of the window (#179) — after Task 29

### Task 32 · #179 — `capture_version` and the compare offer leave the window (two commits)

The `row_rule` precedent (`ui/tcc/row_rule.py`): the decision moves into a Qt-free module, its window tests become
plain tests and are deleted from the window file — a plain twin beside a window test saves nothing (W-8's gate and
signal-id moves left theirs, and only the menu lowered the builds). Both bounds come down in each commit, measured
from that commit's own tree.

1. **`_capture_version`** (`main_window.py:4298-4326`) never touches `self`: it becomes
   `measurement_view.capture_version(state, project_dir=None) -> int | None`, reading the round's titles through
   `process_view.standing()` (ruling 8); `import re` leaves `main_window` if nothing else uses it. Red: four plain
   tests in `tests/test_measurement_view.py` (open round, a plan step, the highest series, none) on real rounds,
   plus a fresh-interpreter Qt-free probe; then delete the four window tests (`test_main_window.py:2372-2438`) and
   re-point `:5070` at `measurement_view.capture_version`. About −31 lines and −4 builds.
2. **The compare offer** (`main_window.py:2461-2472` inside `_offer_compare`): `ledger_line.compare_offer(root,
   preset, current)` returns own, default, labels and others as plain data (it must not import `detail_pane`'s
   `is_other_preset`); `_compare_args`' seven-tuple shape is unchanged (`test_control_layout.py` builds it by hand).
   Red: a plain test on `_arbiter_example` (default `v_003`) and the untested branch — the previous version lives in
   another preset's group; then the window test `test_ledger_line.py:98-111` goes. About −10 lines and −1 build.

- [ ] Each: red, build, green (`tests/test_measurement_view.py tests/test_ledger_line.py tests/test_main_window.py
  tests/test_structure_ratchet.py -n 4`), commit `G13: <decision> leaves the window (#179)`.

---

## The skill's side (#178, #164) — the controller, when the skill's W-8 tag is out

- **#178, the re-pin:** the submodule to the skill's W-8 tag; `tests/test_rew_api_shapes.py:54-67` answers GET
  /filters with what was written (the skill's R3); the CHANGELOG's `Paired with method` line follows. If the tag is
  not out when the rest is built, #178 moves to the next wave with the Arbiter's word.
- **#164, N2:** when the skill names a candidate tag on the bus — a scratch clone under `hub/scratch/tcc/`, the
  submodule at the candidate, the boundary set at `-n 4`, the whole suite once serially with the VM suspended, the
  answer on the skill's ticket with the command and its result.

## Order and cost

- **Build order:** G5+G8 (Tasks 1–14) → G9+G3+G4 (15–23) → G6+G7 (24–29) → G10 (30–31) → G13 (32). One builder at a
  time (Opus), each task with its task review; Tasks 15, 18, 20, 30, 31 and 32 are batches of small same-shape fixes
  (one dispatch and one review, one commit per fix).
- **Reviews:** after each group, silent-failure-hunter and pr-test-analyzer on its diff (Opus) and one fix round;
  Fable's final review after G5+G8 and after G7; at the end of the branch `/pr-review-toolkit:review-pr code errors
  tests` once.
- **The controller, at release:** `CHANGELOG.md` (the `[Unreleased]` notes, the preamble's stale sentence at `:5-7`
  rewritten to what the installer does at the paired method — F10c's TCC line), the version 1.1.3 with README's tag
  (Task 16's test), `KNOWN_CONTRACT` (ruling 3); the full suite once with the VM suspended; one PR from `wave-9` with
  the full CI; `make ship`; after the merge, `method-newest.yml` dispatched once.
- **Size:** 32 dispatches (about 45 commits), five group reviews, two Fable reviews, one branch review — about 30–35
  hours of session time with subagents, which is three to four days at today's token limits. The plan's own note
  holds: if G5+G8 run long, what is left moves to the next wave with the Arbiter's word.
