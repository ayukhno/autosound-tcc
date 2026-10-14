# Study W-10 — Codex as a primary in-app AI (tcc#181)

Feasibility study only (the Arbiter, 2026-10-14). No code changed. Read on branch `wave-10`,
2026-10-14; Codex facts are from the installed `codex-cli 0.162.1` (Homebrew) and the sources in §3.

## 1. Question and answer

**Question.** Can Codex run TCC's tuning conversation in the window the way Claude (Agent SDK) and
omp do, through Codex's own official interface and without omp?

1. **Feasible: yes.** `codex app-server` (stdio JSON-RPC) covers the whole seam in §2: streaming,
   threads with resume, interrupt, approval requests, `model/list`, account state and TCC's MCP
   server over streamable HTTP with its own header. Nothing in TCC's MCP server has to change.
2. **Size: L** (2–4 days, a guess) for a third adapter beside `OmpSession`, the picker, the resume
   registry and an optional install. The risk is maturity and terms, not missing pieces: OpenAI marks
   the app-server experimental, and its terms for app-server sign-in (§3, §5) need the Arbiter's reading.
3. **Next step:** a spike (M, ≤1 day), throwaway like omp's `spike/` driver, with the six checks
   from the issue: stream · real TCC MCP read · GUI user signal · approval · interrupt · resume.
   Build only if all six pass.

## 2. How TCC's sessions work today — the seam

**The contract.** One Protocol, `AgentSession` (`core/agent_events.py:147-171`): `start(prompt)` and
`send(text)` are async generators of eight events (`agent_events.py:37-143`: `TextDelta`,
`ToolCall`, `ToolEnd`, `Question`, `QuestionWithdrawn`, `Notice`, `Unasked`, `TurnEnd(session_id)`),
plus `answer(question_id, value)`, `interrupt()`, `close()`. The panel renders events, not vendor
objects. `AgentWorker` (`ui/tcc/agent_worker.py:34`) runs the session on its own thread and asyncio
loop; `interrupt` and shutdown go through it (`agent_worker.py:83-126`).

**Two backends today.**

| | Claude — `TuningSession` (`core/tuning_session.py:235`) | omp — `OmpSession` (`core/omp_session.py:350`) |
|---|---|---|
| transport | Agent SDK `ClaudeSDKClient` in-process (`:468-470`) | subprocess `omp --mode rpc-ui`, JSON frames on stdio (`:423-428`, `:977-983`) |
| TCC tools | MCP `{"type":"http", url, headers:{X-TCC-Token}}` passed in (`:271-277`) | reads the project's `.mcp.json` (`main_window.py:5032-5033`) |
| method | skill as a plugin, no project settings (`:426-428`) | `.claude/skills` link (`vendor_loader.py:223`, `omp_session.py:929`) |
| gate | `can_use_tool` callback (`:294-362`) | permission frames → `_gate` (`:580`) |
| questions | none — `answer` is a no-op (`:492-496`) | `ask` frames → `Question` (`:537`) |
| interrupt | `client.interrupt()` (`:498-500`) | `abort` frame (`:1193-1196`) |
| resume | session id bound to the phase (`:591-598`) | omp's own "last session in this folder" (`:451-458`) |

**The factory.** `MainWindow._session_factory` (`ui/tcc/main_window.py:5022-5054`) branches on
`choice.harness`: `"omp"` → `OmpSession`, anything else → `TuningSession`. `_launch_session`
(`:5056-5098`) checks the MCP server is up, checks omp is installed and `.mcp.json` written
(`:5075-5081`), reads resume from the registry through a cheap `TuningSession` probe (`:5082`),
then builds the worker (`:5091`).

**The picker.** `Harness` already includes `"codex"` (`core/model_choices.py:41`) with a billing label
(`:49`). But the Generator list is SDK + omp only (`choices()`, `:662-680`); Codex rows appear only in
the reviewer list (`critic_choices`, `:925-938`), from a hardcoded `CODEX_MODELS` (`:159-161`)
because `codex models` needs a terminal.

**What any backend must provide** (from the two above):

1. **Streaming** prose and tool activity as the eight events; a turn ends with `TurnEnd`.
2. **TCC's tools over MCP**: streamable HTTP on loopback, `http://127.0.0.1:<port>/mcp`
   (`core/mcp_server.py:14-16`, `:1707`), every request carrying header `X-TCC-Token`; any other
   request gets 401 (`_TokenGuard`, `:1596-1622`; header name `:93`).
3. **Confirmations.** TCC's own write tools confirm themselves inside the server through the
   window (`_confirm` → `await_confirmation`, `mcp_server.py:605-606`, `:518`), whatever the harness.
   The backend must not ask about `mcp__tcc*` again (`tuning_session.py:304-305`) and must route its
   *own* shell/file actions through the gate dials: default, `auto`, `never`, remembered ticks
   (`:307-362`; `bash_is_dangerous`, `bash_is_read_only` — `core/shell_gate.py:482`, `:2099`).
4. **User signals** ride into every turn: `signal_bus.with_pending_brief` on each prompt
   (`tuning_session.py:473`, `:488`; `omp_session.py:1130`), and `restore_delivered` when a turn ends
   (`tuning_session.py:531`).
5. **Language and method**: `system_prompt_append(language)` (`tuning_session.py:172`), the bound
   skill copy (`method_binding`), and its env (`critic.session_env`, `binding.session_env`, `:391`).
6. **Stop / restart / resume** without reseeding DSP state; resume keyed by phase.
7. **Model list** for the picker, and **errors said in words** (`Notice`, `tuning_session.py:509-520`).

**Two gaps a third backend hits at once:**

- The resume registry stores a bare `session_id` per phase, with no route (`core/session_registry.py:102-116`,
  `:144-151`). A Codex thread id and a Claude session id would be indistinguishable after a model switch.
- The factory's `else` is "Claude": a new harness must be a new branch, and the availability checks
  in `_launch_session` are written per harness.

Also seen: TCC already knows Codex as an MCP *client* by name — `codex-mcp-client` in
`_CLIENT_NAMES` (`main_window.py:184-186`) — from the external-terminal route. And skill#149 reports
that Codex in a terminal did **not** pick up TCC's tools from `.mcp.json`
([autosound-tuning-skill#149](https://github.com/ayukhno/autosound-tuning-skill/issues/149)):
Codex reads its own `config.toml`, so the omp shortcut does not carry over.

## 3. Codex's surfaces

Read 2026-10-14. Latest stable Codex: `rust-v0.162.1`, 2026-10-09
([release](https://github.com/openai/codex/releases/tag/rust-v0.162.1)); this Mac runs the same
version. "Local schema" means `codex app-server generate-json-schema` run on that binary.

**A. `codex app-server`** — the interface OpenAI documents for embedding Codex in a product
([docs](https://learn.chatgpt.com/docs/app-server),
[README](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)).

- *Gives:* JSONL JSON-RPC on stdio (`initialize` handshake). `thread/start` takes `model`, `cwd`,
  `approvalPolicy`, `sandbox`, `developerInstructions`, `baseInstructions` and a free-form `config`
  override; `thread/resume {threadId}`; `turn/start` (with `effort`); `turn/interrupt`; `turn/steer`.
  Streamed `item/agentMessage/delta`, `item/started`/`item/completed` (items `mcpToolCall`,
  `commandExecution`, `fileChange`), `turn/completed`, `error`. Server→client requests:
  `item/commandExecution/requestApproval`, `item/fileChange/requestApproval`,
  `item/permissions/requestApproval`, `mcpServer/elicitation/request`, `item/tool/requestUserInput`.
  `model/list` gives id, display name, `supportedReasoningEfforts`, `defaultReasoningEffort`, `hidden`.
  `account/read`, `account/login/start` (ChatGPT browser, device code, API key), `account/rateLimits/read`.
  `skills/list`, `skills/extraRoots/set`. All method names confirmed in the local schema.
- *Mapping onto §2:* delta → `TextDelta`; item started/completed → `ToolCall`/`ToolEnd` (the SDK
  path still lacks `ToolEnd`); `turn/completed` → `TurnEnd(threadId)`; `error`/failed turn → `Notice`;
  command and file approvals → TCC's gate and `await_confirmation`, `Unasked` under `never`;
  `turn/interrupt` → `interrupt()`; `thread/resume` → resume; `model/list` replaces `CODEX_MODELS`
  (and the "needs a terminal" problem, `model_choices.py:159-161`); `developerInstructions` carries
  `system_prompt_append(language)`.
- *Lacks / to prove:* a question channel in normal mode — `requestUserInput` is "EXPERIMENTAL" in
  the local schema and the `default_mode_request_user_input` feature is "under development", off
  (`codex features list`); the SDK path has none either, so this is parity, not a loss. TCC's tools
  over MCP are approved by Codex itself: "destructive tool annotations always trigger approval"
  ([MCP docs](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)), arriving as an elicitation;
  TCC must answer it as "allowed" (its tools confirm themselves, `mcp_server.py:605`) or set
  `default_tools_approval_mode = "approve"` for the `tcc` server — whether that silences every
  prompt is unconfirmed. Whether `thread/start.config` takes a nested `mcp_servers` map is
  unconfirmed; `--config` flags on the process are the sure route.
- *MCP wiring:* `[mcp_servers.tcc]` with `url` and `env_http_headers = {"X-TCC-Token" = "<env var>"}`
  ([MCP docs](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)) — the existing `X-TCC-Token`
  works as is, and the token stays out of argv and files. Not `.mcp.json` (skill#149).
- *Method:* Codex skills live in `.agents/skills` or `~/.agents/skills`, or an extra root set per
  process ([skills docs](https://learn.chatgpt.com/docs/build-skills)); `AGENTS.md` in the cwd is
  read too ([AGENTS.md docs](https://learn.chatgpt.com/docs/agent-configuration/agents-md)). This
  overlaps skill#149.
- *Auth:* reuses the user's `codex login` (`~/.codex/auth.json`); ChatGPT plan or API key
  ([auth docs](https://learn.chatgpt.com/docs/auth)). The app-server page says app-server
  authentication "has never been permitted for commercial or hosted services", while "a local or
  open-source application ... can continue using it"; OpenAI points such apps to "Sign in with
  ChatGPT", which needs a client ID ([SIWC](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server)).
- *Platforms:* macOS; native Windows with its own sandbox, Windows 11 as baseline, Windows 10 "best
  effort" ([Windows docs](https://learn.chatgpt.com/docs/windows/windows-sandbox)).
- *Maturity:* `codex --help` lists `app-server` as `[experimental]`; the docs say the app-server and
  WebSocket "are experimental and aren't supported for production workloads". Releases come several
  times a week (0.163 alphas daily), so the protocol must be pinned.

**B. Codex Python SDK `openai-codex`** — the same app-server, wrapped
([source](https://github.com/openai/codex/tree/main/sdk/python), [docs](https://learn.chatgpt.com/docs/codex-sdk),
[PyPI](https://pypi.org/project/openai-codex/)).

- *Gives:* 0.162.1 (2026-10-09), "stable", Python ≥3.10 (TCC needs ≥3.11, `pyproject.toml:15`).
  `AsyncCodex`, `thread_start`/`thread_resume`, turn `stream()`/`interrupt()`, `models()`,
  `account()`, `login_chatgpt()`. **Bundles the binary** via `openai-codex-cli-bin` wheels for
  macOS (x86_64, arm64) and Windows (amd64, arm64): no npm or Homebrew for the user.
- *Lacks:* an approval callback. `approval_mode` has only `auto_review` (Codex's own AI reviewer
  decides) and `deny_all`; the lower `CodexClient(approval_handler=...)` is not exported, and its
  default accepts every command and file change (`_approval_mode.py`, `client.py`). Under the
  public API the Arbiter's gate cannot be honoured — the one hard mismatch with §2.

**C. `codex exec --json`** ([docs](https://learn.chatgpt.com/docs/non-interactive-mode)) — one process per
turn, JSONL events, `codex exec resume <id>`. No approval round-trip (non-interactive), interrupt
only by killing, no model list. Not enough for the seam; fine for the reviewer, where it is used now.

**D. `codex mcp-server`** — removed: "The `codex mcp-server` command and standalone
`codex-mcp-server` binary have been removed" ([docs](https://learn.chatgpt.com/docs/codex-sdk));
absent from `codex --help` here.

## 4. Options

| | What | Size | Risk | What breaks or must change |
|---|---|---|---|---|
| **1. Own app-server client** | `core/codex_session.py`: asyncio subprocess `codex app-server`, JSON-RPC by hand — the pattern `OmpSession` already uses for omp's rpc frames | L (2–4 days, guess) | medium: experimental protocol, pin the version; approvals map onto the gate | factory branch (`main_window.py:5022`), launch checks (`:5075-5081`), `choices()` gets Codex rows from `model/list` (`model_choices.py:662`), registry tags the route (`session_registry.py:144`), skill link for `.agents/skills`, optional extra for the binary |
| **2. Python SDK `openai-codex`** | the same adapter on top of `AsyncCodex` | L (a little less protocol code) | high: no public approval hook — either `auto_review`/`deny_all` (the gate is lost) or the private `CodexClient` (breaks on any SDK release) | same as 1, plus a pydantic ≥2.12 dependency and an exact pin to the runtime |
| **3. `codex exec` per turn** | spawn per message, resume by id | M | high: no approvals, no clean interrupt | only safe with a read-only sandbox, which stops the skill's own writers — not the tuning conversation the issue asks for |

**Recommendation: option 1, after the spike.** It keeps TCC's gate — the one thing the SDK can't
give without private API — and it is the same shape as omp, so the panel, worker and signal code
do not move. Take the **binary** from the official `openai-codex-cli-bin` wheel as an optional
extra (`pip install autosound-tcc[codex]`), falling back to a `codex` on PATH: it is the one
supported way to put Codex on Windows and macOS without npm. Resume also needs the route stored
next to the session id, or a model switch hands a Claude id to Codex.

**What the spike must answer** (the open "unconfirmed" items): `thread/start.config` with
`mcp_servers.tcc` + `env_http_headers` reaches TCC (MCP client name shows in the footer,
`main_window.py:184-186`); TCC tool calls go through without a Codex prompt; a command approval
reaches the confirm bar and a refusal is respected; `turn/interrupt` stops a running tool;
`thread/resume` after restarting TCC continues without reseeding; an unsigned machine gives a
sentence, not a crash. On Windows: whether the commands Codex asks about are PowerShell rather
than bash — TCC's gate parses bash (`shell_gate.py:482`, `:2099`); a guess, to check.

## 5. Questions only the Arbiter can answer

1. **Terms.** OpenAI allows app-server sign-in for "local or open-source" apps, not "commercial or
   hosted" ones (§3 A). TCC uses the user's own login on the user's machine. Is TCC, as you plan
   to distribute it, local/open-source in that sense — and if it may ever be sold, do we stop at
   API keys or apply for "Sign in with ChatGPT"?
2. **Who it is for.** Only you, or every TCC user? For everyone, Codex ships as an optional
   download in the installer; for you alone, the `codex` already on your machine is enough.
3. **Windows.** Needed in the first build, or macOS first? Windows 10 is "best effort" for Codex.
4. **Codex's own reviewer.** Codex can let an AI reviewer approve its commands (`auto_review`).
   Is that acceptable in place of asking you, or must every non-read command come to you as today?
5. **When.** Spike in W-10 and build in a later wave, or both in W-10?

### The Arbiter's answers (2026-10-14)

1. **Terms — yes:** TCC is local and open-source in that sense.
2. **For every user, under each user's own licence:** each signs in to Codex with their own account; TCC
   brings the engine integration and the logic, not the access.
3. **Windows — from the first build.**
4. **Approvals follow TCC's own setting** when Codex runs inside TCC (the same gate as the other backends);
   in a terminal, Codex's own configuration applies.
5. **The spike is in W-10.** The build is decided on the spike's result (all six points pass).
