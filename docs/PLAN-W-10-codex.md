# PLAN W-10 · Codex as TCC's primary AI (tcc #181)

The Arbiter's choice, 2026-10-14: **the blended design** — minimal's shape (an omp-like session, routing as
functions, menu lines), clean's shared JSON-RPC client, its sandbox choice and its first step (record real answers).
~5.5–6 days. Inputs: `docs/STUDY-W-10-codex-primary.md` (§5 and both «Arbiter's answers» sections),
`spike/codex-app-server/RESULT.md`, the code map `hub/scratch/tcc/w10/codex/MAP.md`. Wave plan: `docs/PLAN-W-10.md`.

**The Arbiter's decisions.** Every user, own Codex account. Windows from the first build. Approvals follow TCC's gate
inside TCC. A Codex already installed is used; none — TCC installs it from the official source. Sign-in by a TCC
button (browser). The user's own Codex extras OFF in TCC's sessions. «Open terminal» → Codex with TCC's tools,
otherwise its own config.

## Shape

New, Qt-free (`src/autosound_tcc/core/`):

- **`codex_rpc.py`** — the one JSON-RPC client over stdio, shared by the session, the model list and sign-in.
  `AppServer(argv, *, cwd, env, spawn_kwargs, log, on_request)`: `open()` (initialize with `experimentalApi`, then
  `initialized`), `request(method, params, timeout) -> dict` (raises `RpcError` / `ConnectionLost`), `notify()`,
  `respond(rid, result=None, error=None) -> bool` — the ONLY writer of replies, refuses a second answer —
  `resolved(rid)`, `notifications: asyncio.Queue` (None = ended), `stderr_tail`, `close(grace=5)` (close stdin, wait,
  terminate, `child.kill_tree`). Binary pipes, `json.dumps(...).encode() + b"\n"`, a large line `limit`.
  `ask(binary, calls, ...)` / `ask_blocking(...)` for one-shot exchanges from worker threads. The model list's
  current reader (`_app_server_exchange`, rebuilt by the AI picks group: stdin kept open, `nextCursor`, reasons kept)
  moves onto it **with its behaviours and tests**.
- **`codex_cli.py`** — finding, version, probe, sign-in, argv pieces. `MIN_VERSION = (0, 162, 0)`.
  `find() -> Found(path, source) | None`: stat calls only, cached, ↻ clears — PATH; then the places a Dock-started app
  misses (`/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin`, `~/.npm-global/bin`, `%APPDATA%\npm`); on Windows
  only a `.exe` counts — an npm `.cmd`/`.ps1` shim (and on macOS a node-script shim) resolves to the bundled native
  binary under `node_modules/@openai/codex*/**`; then TCC's own copy. `version(found)` (`codex --version`, once per
  path+mtime, worker thread only); older than `MIN_VERSION` → not usable, the blocker offers TCC's copy.
  `probe()` — one app-server: `account/read` + `model/list` → rows + signed-in state. `SignIn`: `begin() -> authUrl`
  (`account/login/start {"type":"chatgpt"}`), `wait(timeout=600)` (`account/login/completed`), `cancel()`
  (`account/login/cancel`). Pure: `tcc_tool_args(url)`, `isolation_args(config, ...)`.
- **`codex_install.py`** — the official wheel `openai-codex-cli-bin==0.162.1` (OpenAI's, from openai/codex CI; one
  source for macOS x86_64/arm64 and Windows amd64/arm64; a native `.exe`; no Node, Homebrew or admin). PyPI JSON →
  the platform's file, sha256 checked, one member unzipped with chmod +x, into
  `~/Library/Application Support/autosound-tcc/codex/<PIN>/` / `%LOCALAPPDATA%\autosound-tcc\codex\<PIN>\` (outside
  the uv tool env: a TCC update does not wipe it, users with their own Codex download nothing). `install(progress,
  cancelled, opener=urlopen)`, `InstallError(sentence)`; a sha mismatch leaves nothing behind.
- **`codex_session.py`** — `CodexSession`, the `OmpSession` shape (tables below).
- **`session_routes.py`** — routing out of the window: `factory(choice, ...)` (the `_session_factory` branches),
  `resume_route(harness)` (sdk→"sdk", codex→"codex", omp→None = any, as today), `blocker(choice, server) -> sentence |
  None` (omp's checks and Codex's: not found / too old / signed out — each naming the menu line),
  `terminal_invocation(choice, project_dir)` (fixes «a Codex pick opens Claude»).
- **`codex_terminal.py`** — `python -m autosound_tcc.core.codex_terminal <project> [--model M]`: reads url and token
  from the project's `.mcp.json` (already written for terminal CLIs), puts the token in `TCC_MCP_TOKEN`, execs codex
  with `tcc_tool_args` only — the rest is the user's own config. The token is never in argv, the line or a new file.

Changed: `session_registry.py` (`bind_session(..., route="sdk")`, `resumable_session(..., route=...)`; an entry with no
route reads «sdk»; `SCHEMA_VERSION` stays 1) and `tuning_session.py` passes "sdk"; `shell_gate.py` gains
`judge_action(tool, detail, gate, always_allowed, read_roots)` — `OmpSession._auto_allowed`'s body with
`_touches_only_skill_files` and `effect_of`, omp delegates (one gate, not three copies); `model_choices.py`
(`choices()` adds Codex rows, `critic_choices` dedupes by key, `cli_available("codex")` → `codex_cli.find()`,
`codex_effort(level, supported)`: high→high, xhigh→xhigh else high, max→highest of max/xhigh/high);
`availability.py` (SIGN_IN for codex from `codex_cli`); `child.py` (`"codex"` in `AGENT_COMMANDS`); `critic.py`
(Codex found through `codex_cli.find()`, TCC's copy's folder on the session PATH); `install_report.py` (the Codex
row: «session and reviewer»); `main_window.py` — one-line calls only, **net smaller**; the ratchet lowered in the
same commit. UI: `ui/tcc/codex_menu.py` (`menu_entries()` «Встановити Codex», «Увійти в Codex» in a `menu_registry`
provider, work on threads, results on the status strip); `ui/tcc/strings/codex.py` (a feature table; pl/de through
the Advisor).

## The session

**Start:** `binding.require()` → a short probe for `config/read` (the isolation list) → spawn
`[codex, "app-server", *isolation, *tcc_tool_args]` with env `vendor_loader.child_env(**critic.session_env,
**binding.session_env(), TCC_MCP_TOKEN=token)` and the agent-console treatment (Codex starts a shell per command) →
`initialize` → `skills/extraRoots/set` to the project's linked skill (checked with `skills/list`; an
`autosound-tuning` from elsewhere refuses the start with the binding's sentence) → `model/list` (effort clamp) →
`thread/start {cwd, model, approvalPolicy:"untrusted", approvalsReviewer:"user", sandbox:"danger-full-access",
developerInstructions: system_prompt_append(language)}` or `thread/resume {threadId, excludeTurns:true, ...}`
(failure → a Notice and a fresh thread) → bind `(phase, threadId, route="codex")` at once.

**Sandbox: `danger-full-access`, TCC's gate is the guard** — as on the Claude and omp routes. Why: with the sandbox's
network off, Seatbelt blocks loopback too, so the method's scripts cannot reach REW on 127.0.0.1:4735; with it on,
the reviewer CLIs the method calls still need to write `~/.codex` and `~/.claude`, and Windows needs a sandbox setup
that may ask for elevation.

**Turn:** `turn/start {threadId, input:[text(with_pending_brief(bus, text))], model, effort}`; `bus.restore_delivered()`
in `finally`; a 120 s silence Notice naming the running item; the generator returns only after `turn/completed` or
EOF (`turn_done` stays honest). No `turn/steer` in this build — window signals ride the next turn, as on the others.

| Codex sends | the panel gets |
|---|---|
| `item/agentMessage/delta` | `TextDelta` |
| `item/completed` agentMessage with nothing streamed | one `TextDelta(text)` |
| `item/started` mcpToolCall | `ToolCall(f"mcp__{server}__{tool}", args)` (the gate's `mcp__tcc` prefix holds) |
| `item/started` commandExecution / fileChange | `ToolCall("Bash", {command})` / `ToolCall("Edit", {paths})`, paths kept by `itemId` |
| `item/completed` of a tool | `ToolEnd` |
| `turn/completed` completed / interrupted | `TurnEnd(threadId)`, return |
| `turn/completed` failed | `Notice(error)`, `TurnEnd`, return |
| `error` (`willRetry` false, or once per retry storm) | `Notice` |
| EOF | `Notice(why + stderr tail)`, return |
| `deprecationNotice`, `configWarning`, token usage, rate limits | frame log only (`.tcc/codex-frames.jsonl`, omp's cap; never the token) |

| Codex asks | TCC does | reply |
|---|---|---|
| `item/commandExecution/requestApproval` | `judge_action("Bash", inner command)` (the `/bin/zsh -lc '…'` wrapper stripped; PowerShell lines whole; `commandActions` only as a display hint) → else `await_confirmation`; under `never` a dangerous command passes with `Unasked` | `{"decision":"accept"\|"decline"}` — never `acceptForSession` (TCC's ticks are the only memory, read per request) |
| `item/fileChange/requestApproval` | `"Edit"` as omp's `edit` (asks under `writes`/`foreign`, passes under `auto`/`never`) — **except a change that deletes a file asks under `auto` too** (irreversible; decided 2026-10-14 after task 5's review, I1); paths + reason | same |
| `mcpServer/elicitation/request` | `tcc` → accept `{}`; any other server → decline | |
| `permissions`, `requestUserInput`, anything unknown | JSON-RPC error, answered once, logged | |
| `serverRequest/resolved {requestId}` | `rpc.resolved(id)`, cancel that gate task → the future is cancelled and `ConfirmBar._on_gave_up` takes the bar down (no new UI) | nothing sent |

Every request id is in exactly one of answered / gating / resolved; `turn/completed` sweeps the turn's leftovers.
`interrupt()` → `turn/interrupt {threadId, turnId}`; `answer`/`cancel_question` no-ops (no question channel, as the
SDK route); `close()` idempotent, safe mid-turn and with no process.

**Isolation (`-c`, the session only):** TCC in — `mcp_servers.tcc.url`, `mcp_servers.tcc.env_http_headers=
{"X-TCC-Token"="TCC_MCP_TOKEN"}`, `mcp_servers.tcc.default_tools_approval_mode="approve"`,
`mcp_servers.tcc.tool_timeout_sec` above `CONFIRM_TIMEOUT_S` and the reviewer's timeout (Codex's ~60 s default would
cut a confirmation or a review — omp's `OMP_TOOL_TIMEOUT_MS` for the same reason). The user's extras out —
`mcp_servers.<every name in config/read but tcc>.enabled=false` (a name outside `[A-Za-z0-9_-]+` → a Notice),
`notify=[]`, `features.{plugins,apps,hooks,browser_use,computer_use,in_app_browser,image_generation,multi_agent,goals,
tool_suggest,memories}=false`, `project_doc_max_bytes=0` (no AGENTS.md — the SDK route's HUB-050 rule), the user's
skills off by the key task 1 confirms. Env: `shell_environment_policy.exclude=["TCC_MCP_TOKEN"]` — the token reaches
no shell. A test fails when a recorded `config/read` shows an enabled feature on neither list. Same `CODEX_HOME` as
the user's own Codex (a separate one would lose the sign-in).

## Build sequence

Each `Risk: high` task: implementer opus · high, test first → task review opus · high → one fix round → re-review of
the fix. The group seats at the end; the wave's final review on Fable. Targeted tests only; no real model turns in
tests (recorded fixtures + the stand-in).

| # | task | size | risk |
|---|---|---|---|
| 1 | **Fixtures and stand-in.** One paid recording on the cheapest model/effort for what the spike left out: a fileChange approval, `config/read`, `skills/list` with `extraRoots`, resume with `excludeTurns`, login start and cancel, the wheel's member path; `codex app-server generate-json-schema` cut to the methods used (`tests/fixtures/codex-schema-0.162.1/`); `tests/fakes/fake_codex_app_server.py` (a POSIX replay that asserts every server request is answered once); the skill's `session-start` accepts a codex route | M | — |
| 2 | **Registry routes + `session_routes`** — factory, blocker, terminal and resume out of the window, no behaviour change; the ratchet lowered | M | high |
| 3 | **`codex_rpc`**, the model list moved onto it (its AI picks tests kept) | S–M | — |
| 4 | **`codex_cli`** — find (shim→exe, Dock PATH, min version), probe, picker rows, availability, `child`, `critic` | M | — |
| 5 | **`shell_gate.judge_action`** lifted from omp; omp's gate tests unchanged + a table test | S | high |
| 6 | **`CodexSession` turns** — start, send, mapping, interrupt, resume and its fallback, close; replay against the stand-in: `TurnEnd` only at return, EOF mid-turn, no token in argv | M | high |
| 7 | **`CodexSession` approvals** — gate, elicitation, resolved, exactly-once; `never` → `Unasked`; a narrowed gate takes effect mid-session | M | high |
| 8 | **`codex_terminal`** + the terminal invocation (coordinate with #180's submenu) | S | — |
| 9 | **Install, sign-in, menu lines, strings** — a fake wheel through `opener`, a sha mismatch leaves nothing, sign-in against the stand-in | M | high |
| 10 | **Acceptance** — a live macOS run inside TCC over the spike's six points, then the Windows VM pass (below) | M | high |

## Only the Windows VM can prove

npm `.cmd` → `.exe` and the PATH a launched app sees; no console window for app-server or per PowerShell command
(conhost and Windows Terminal); the PowerShell shape of approvals and that `bash_is_dangerous` reads it; binary pipes
with non-ASCII paths and `CODEX_HOME`; the sign-in's localhost callback without a Defender prompt; loopback to TCC's
MCP server and REW from PowerShell; resume across processes; `kill_tree` leaves no orphan shells; the unpacked `.exe`
without SmartScreen.

## Risks

1. **Protocol churn on an installed Codex** — the Arbiter's «use the installed one» meets versions TCC never tested:
   the minimum version, unknown notifications ignored, unknown requests answered with an error, the schema fixture,
   TCC's copy offered when a session fails at the protocol level.
2. **The Windows gate** — under `auto` the PowerShell parse is the only guard against an irreversible command.
3. **Extras leaking** through a new default-on Codex feature — the off-list is by name; the `config/read` test
   catches it when the fixtures are re-recorded.

Found while designing (for the pool, not this build): «Fresh» still resumes on the Claude route —
`main_window.py:5107` passes `resumed=False`, but `TuningSession.__init__` reads the registry itself and `_options`
resumes anyway.

## Learned in task 1 (acaf06d, 2026-10-14) — binding on the later tasks

- **Task 9: the wheel is a folder, not one file.** Unpack all of `codex_cli_bin/` (macOS: `bin/codex`,
  `codex-package.json`, `codex-path/rg`, `codex-resources/zsh`; Windows adds `codex-command-runner.exe` and
  `codex-windows-sandbox-setup.exe`). Member paths in `tests/fixtures/codex/wheel-0.162.1.json`.
- **Isolation can kill the start:** `-c mcp_servers.<name>.enabled=false` for a server NOT in the user's config makes
  app-server exit 1 («invalid transport»). The off-list is built only from `config/read`; the client fails cleanly on
  EOF before `initialize`.
- **Skills off:** `features.skip_host_skill_discovery` does nothing; `-c skills.bundled.enabled=false` leaves only the
  extra-root skill. User/repo skills untested (none on this Mac).
- **Features `config/read` still lists as enabled** with the spike's off-switches: decided (the session, 2026-10-14) —
  `remote_plugin` goes on the OFF list (it is the user's extras); `api_key_model_discovery`, `auth_elicitation`,
  `mentions_v2` go on a KNOWN-HARMLESS list. The test: any enabled feature on neither list fails.
- **`serverRequest/resolved` also arrives for requests already answered** — a withdrawal only while the request is
  still pending.
- **Command approvals** list `accept`, `acceptWithExecpolicyAmendment`, `cancel` as decisions; `decline` works too —
  TCC sends `accept` / `decline`.
- **Sign-in** uses a fixed callback port, `127.0.0.1:1455` (Windows: Defender/firewall on the VM pass).
- **`codex_rpc` as built (cb70b5c, task 3)** — for task 6: the reader handles `serverRequest/resolved` the moment it
  arrives (a gate finishing later cannot answer a withdrawn request); the notification is still queued; read
  `server.withdrawn(rid)` (True = it was still pending) to decide whether to drop the bar. `on_request(msg)` runs in
  the reader: return an awaitable and it runs as its own task; a raise answers the request with an error; no handler
  → -32601. On Windows `close()` goes to `child.kill_tree` after the grace (holds the loop up to 5 s). Pass
  `secret_env=("TCC_MCP_TOKEN",)` with `env` to keep the token out of the frame log.
- **`codex_cli` as built (1475e33, task 4)** — `find()` (stat-only; PATH → Homebrew/`~/.local/bin`/`~/.npm-global/bin`
  /`%APPDATA%\npm` → TCC's copy; shims resolve to the native binary under `node_modules/@openai/codex*/**`),
  `tcc_copy_path()`, `version()`/`too_old()`/`usable()`, `probe(force) -> Probe(signed_in, models, why, asked)` on ONE
  app-server (`account/read`, then `model/list` paging) — not `ask_blocking`; `supported_efforts(model)`;
  `tcc_tool_args`, `isolation_args`, `unsafe_server_names` (→ a Notice in task 6), `unknown_enabled_features`.
  For task 6: spawn `find().path` (never a shim; the npm shim's `CODEX_MANAGED_*` env is skipped — unverified);
  `codex_effort(level, codex_cli.supported_efforts(model))`; remove the `codexNotYet` refusal in `blocker` (its test
  `test_a_codex_pick_is_refused_until_codex_has_its_session`) together with `factory`'s Codex branch and `CODEX_ROUTE`.
  For tasks 8/9: Codex's blockers (not found, too old, signed out) in `blocker` — `too_old()` is known after
  `version()` ran on a worker (`probe()` runs it); task 9 unpacks to exactly `tcc_copy_path()`, then `forget()`.
- **The shared gate (54e6b96, task 5) — for task 7:** pass the inner command as `detail` (strip `/bin/zsh -lc '…'`),
  `command=None`; on Windows `shell="powershell"`; tool names `"Bash"`/`"Edit"` (`TOOL_NAMES`). Task 5's fix round
  (the Arbiter, 2026-10-14: «виправити повністю») closes the `foreign` hole — danger first, owned paths anchored
  (relative, an owned prefix, no `..`) — and makes an unknown tool name ask under `auto`.
- **`CodexSession` as built (1464e49, task 6) — for task 7:** the decision sits in `CodexSession._on_request` (runs in
  the reader; return an awaitable to gate asynchronously); read `self.gate`, `self.always_allowed`, `self._read_roots`
  per request; file-change paths in `self._paths[itemId]` (cleared in the turn's `finally`); `inner_command()` for the
  gate's detail; no `turn/completed` sweep of leftover requests yet; `serverRequest/resolved` handled only by
  `codex_rpc`; a refused `turn/start` → Notice + `TurnEnd`. The `codexNotYet` i18n key is now unused (drop it).
- **A «don't ask again» tick never outranks «cannot be undone»** (the Arbiter, 2026-10-14) — a dangerous line, a Codex `cwd` outside the project, a `writeStdin`/empty command ask with the tick or without; only `never` lets them through, with `Unasked`. omp, the SDK route and Codex alike.
- **The gate is synchronous and now touches the disk** (realpath, globs, a walk of up to 5000 entries for a recursive PowerShell delete — task 5's third round): task 7 calls `judge_action` through `asyncio.to_thread` so a network or iCloud drive does not hold the session's loop.
- **Task 6 turned `CODEX_ROUTE` on** in `session_routes.resume_route` together with `factory`'s Codex branch (e89f0ca: until then a Codex pick reads the SDK's route — one without the other told the chat «fresh» over a resumed session).
- The method's `session-start` takes any harness string (`rew_tool/state/process.py:9259-9261`): `codex` journals as
  `"harness": "codex"`.
- The stand-in: `tests/fakes/fake_codex_app_server.py` (`--scenario` / `FAKE_CODEX_*`; exit 3 with `ASSERT` on an
  unanswered / twice-answered / answered-after-resolved request, 4 on a silent client); 13 scenarios in
  `tests/fixtures/codex/`; re-record with `spike/codex-app-server/record_w10.py` + `cut_fixtures.py`.
