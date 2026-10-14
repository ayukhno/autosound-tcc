# Spike W-10 — `codex app-server` as TCC's primary AI backend (tcc#181)

Run 2026-10-14 on the Arbiter's Mac against the installed `codex-cli 0.162.1` (Homebrew), signed in
with the Arbiter's own ChatGPT account (plan `plus`, read through `account/read`). Throwaway code:
`client.py` (stdlib JSON-RPC client over stdio) and `serve_tcc.py` (TCC's real `TccMcpServer`
headless, real `X-TCC-Token` guard, HTTP wiretap, every confirmation denied). Wire logs land in
`work/logs/` (git-ignored); the lines quoted below are cut from them.

**Result: all six points PASS.** The study's option 1 (own app-server client, the `OmpSession`
shape) holds. Two points pass with a behaviour the build must design for (3 and 2, below).

## Setup

- **Model:** `gpt-5.6-luna`, effort `low` — the smallest, oldest "fast and efficient" row of the live
  `model/list` (7 rows: gpt-6.1-sol default, gpt-6-astra, gpt-6-sol, gpt-6-luna, gpt-5.6-sol,
  gpt-5.6-terra, gpt-5.6-luna; ids, display names, efforts and `hidden` all come from the runtime).
- **Codex's cwd:** `work/scratch/`. Thread: `sandbox: workspace-write`, turn `sandboxPolicy`
  `workspaceWrite` with `networkAccess: false`, `approvalPolicy: untrusted`, `approvalsReviewer: user`.
- **TCC's MCP server**, per process, never in `~/.codex/config.toml`:
  `-c mcp_servers.tcc.url="http://127.0.0.1:8765/mcp"`
  `-c mcp_servers.tcc.env_http_headers={"X-TCC-Token"="TCC_MCP_TOKEN"}` with the token in the
  child's env only (not in argv, not on disk).
- **The user's own Codex extras switched off per process** (`-c`): their `home-assistant` and
  `node_repl` MCP servers, `notify`, plugins, apps, browser/computer use, hooks, goals, multi-agent.
  Without this they would load into TCC's session — see risk 3.

## The six points

| # | Point | Result | Evidence | What it means for the build |
|---|---|---|---|---|
| 1 | Streaming | **PASS** | T1: 23 `item/agentMessage/delta` events for one 74-char answer: `{"method":"item/agentMessage/delta","params":{"threadId":"01a13981-…","turnId":"01a13981-bbcc-…","itemId":"msg_093b…","delta":"/"}}`, then `"delta":"Users"` … T3: 448 deltas. `item/started`/`item/completed` bracket every `reasoning`, `mcpToolCall`, `commandExecution`, `agentMessage`; `turn/completed` ends the turn. | delta → `TextDelta`; item started/completed → `ToolCall`/`ToolEnd`; `turn/completed` → `TurnEnd(threadId)`. One-to-one with the eight events. |
| 2 | Real TCC tool read | **PASS** | TCC's server saw `ua: codex-mcp-client/0.162.1`, `token_present: true` on every request; `mcpServerStatus/list` (no model cost) listed all **36** TCC tools. T1 called `get_tcc_state`: TCC log `{"method":"tools/call","params":{"_meta":{"x-codex-turn-metadata":{"thread_id":"01a13981-…",…}}…`; item `{'type':'mcpToolCall','server':'tcc','tool':'get_tcc_state','status':'completed','durationMs':10}`; answer = the real `project_dir` (`…/work/tcc-project`). **But** Codex first asked the client: `{"method":"mcpServer/elicitation/request","id":0,"params":{"serverName":"tcc","mode":"form","_meta":{"codex_approval_kind":"mcp_tool_call","persist":["session","always"],…}}}` → client `{"action":"accept","content":{}}`. Re-run with `-c mcp_servers.tcc.default_tools_approval_mode="approve"`: `get_capability_checklist` called twice, **zero** approval requests. | Wire `default_tools_approval_mode="approve"` for `tcc` (TCC's tools confirm themselves inside TCC, `mcp_server.py:605`) — the open question in the study is answered: yes, it silences Codex's own prompt. Keep an elicitation handler anyway (accept `tcc`, decline others). Codex sends `thread_id` in `_meta` of each call — TCC's server can tell which session called. Footer detection by client name already matches (`codex-mcp-client`). |
| 3 | Window signal mid-turn | **PASS** (lands at the next model boundary) | T3: at the first delta of a 120-line list, `-> {"method":"turn/steer","params":{"threadId":"01a13981-…","expectedTurnId":"01a13982-4c44-…","input":[{"type":"text","text":"[TCC window signal] The user pressed STOP-LIST. …answer only: SIGNAL RECEIVED."}]}}` → `{"turnId":"01a13982-4c44-…"}`. Timeline: steer sent 208.01 s; the list's `agentMessage` still completed in full at 210.12; steered `userMessage` item at 210.19; `agentMessage "SIGNAL RECEIVED"` at 212.92, same turn. | `turn/steer` is the channel for a signal that arrives while a turn runs: it joins the running turn, but only after the current model response ends — it does not cut a message in progress. In a tuning turn the boundaries are tool calls, so the delay is one model step. For "stop now", TCC uses interrupt (point 5). Between turns, the existing `signal_bus.with_pending_brief` on `turn/start` text works unchanged. |
| 4 | Approval allow + deny | **PASS** | T2: `<- {"method":"item/commandExecution/requestApproval","id":1,"params":{"kind":"command","command":"/bin/zsh -lc 'echo hi > note.txt'","cwd":"…/work/scratch",…}}` → `-> {"id":1,"result":{"decision":"accept"}}` → item `status: completed, exitCode: 0`, `note.txt` exists. `<- …"id":2,…"command":"/bin/zsh -lc 'touch denied.txt'"` → `-> {"id":2,"result":{"decision":"decline"}}` → item `status: "declined"`, `denied.txt` absent, stderr `exec_command failed: Rejected("rejected by user")`; the model said "`touch denied.txt` was refused and did not run." | The approval is a JSON-RPC request the client must answer; Codex blocks until it does and obeys the answer. TCC's gate (`default` / `auto` / `never` / remembered ticks) plugs in here; `acceptForSession` maps to a remembered tick. `fileChange` approvals come the same way (`item/fileChange/requestApproval`; not exercised — the client declines them). |
| 5 | Interrupt | **PASS** | T4: `-> {"method":"turn/interrupt","params":{"threadId":"01a13981-…","turnId":"01a13982-7398-…"}}` at the first delta → `{}`; `turn/completed` with `"status":"interrupted"` **0.01 s** later; `thread/read` on the same process still works. T6 (extra): interrupt while an approval was **pending** (`touch held.txt` left unanswered) → `interrupted` in 0.02 s, `serverRequest/resolved {"requestId":0}` withdrew the open approval, `held.txt` absent, stderr `exec_command failed: … "TurnAborted"`. | `interrupt()` → `turn/interrupt`. `serverRequest/resolved` is the signal to close TCC's confirm bar when the user stops mid-question (the omp path needed `QuestionWithdrawn` for the same thing). Closing stdin ended the process with exit 0 every time — clean shutdown path. |
| 6 | Resume in a new process | **PASS** | New `codex app-server` process: `thread/resume {"threadId":"01a13981-…"}` → thread with **4 turns** (items 6/6/5/2; statuses completed, completed, completed, interrupted). T5, no tools: "What project_dir did get_tcc_state return, and what did the window signal ask?" → `…/work/tcc-project; SIGNAL RECEIVED.` The thread's token total continued from 178 652 to 222 783, i.e. the history was in the model's context. The server also sent `deprecationNotice`: "Full-history hydration is deprecated for paginated threads; use `excludeTurns: true`, then page with `thread/turns/list` and `thread/items/list`." | Resume keyed by Codex `threadId`, stored with the route next to it (the registry gap in the study §2). Use `excludeTurns: true` and page the history only if the panel needs to redraw it. Threads live under `CODEX_HOME` (`~/.codex`), so resume needs the same `CODEX_HOME`. |

Also confirmed at zero model cost: `account/read` (type `chatgpt`, plan, `requiresOpenaiAuth`),
`model/list`, `mcpServerStatus/list`, `account/rateLimits/updated` (5-hour and weekly windows) — the
picker, the sign-in state and a usage line can all come from the runtime.

## Windows — what this Mac run cannot prove

Seen here and relevant:

- **Binary.** The official wheel `openai-codex-cli-bin==0.162.1` exists for `win_amd64` (151.7 MB)
  and `win_arm64` (140.6 MB); macOS arm64 124 MB, x86_64 135 MB (PyPI, read 2026-10-14). An optional
  extra is a ~150 MB download. Spawn the `.exe` with an argument list and no shell — not an npm
  `.cmd` shim, which needs `shell=True`.
- **Shell in approvals.** On macOS the approval carries the user's login shell wrapper:
  `/bin/zsh -lc '…'`. On Windows it is expected to be PowerShell. TCC's gate parses bash
  (`shell_gate.py`). Each approval also carries `commandActions` (Codex's own parse:
  read / listFiles / search / unknown), a shell-independent hint the gate could use.
- **Framing.** JSONL over stdio. Python text-mode pipes on Windows write `\r\n`; the build should
  use binary pipes or `newline="\n"`. Whether the app-server tolerates `\r` is unknown.
- **Sandbox.** The protocol has `windowsSandbox/setupStart`, `windowsSandbox/readiness`,
  `windowsSandbox/setupCompleted` and `windows/worldWritableWarning`: the first run on Windows
  likely needs a setup step TCC must drive and show.

Only a Windows run can prove: the shell and quoting in approval requests; whether the sandbox setup
needs elevation or a UI prompt; console windows (spawning `codex.exe` from the GUI needs
`CREATE_NO_WINDOW`, and the shells Codex spawns inherit it — the conhost/Windows Terminal issue
seen before in TCC); `CODEX_HOME` and thread `cwd` with backslash paths and non-ASCII user names;
that `thread/resume` works across processes there; that the loopback MCP call passes Windows
Defender/firewall without a prompt.

## The build, revised

**Size: L — 3–4 days on macOS plus about 1 day on the Windows VM** (the study guessed 2–4 days and
no Windows). The protocol side is smaller than feared — every point maps one-to-one onto the eight
events — and the work moves to the edges:

1. `core/codex_session.py`: subprocess + JSON-RPC reader thread, the event mapping above, the gate
   on command and file approvals, `serverRequest/resolved` → withdraw the confirm bar, steer for
   mid-turn signals, `default_tools_approval_mode="approve"` for `tcc`.
2. Isolation of the user's own Codex config (risk 3): read `config/read` at start and pass
   `enabled=false` for every MCP server but `tcc`, and off-switches for plugins, hooks, notify.
3. Factory branch, launch checks (binary found, `account/read` signed in, else a sentence), picker
   rows from `model/list`, registry stores route + `threadId`.
4. Method: skill via `skills/extraRoots/set` or `.agents/skills`; `developerInstructions` for
   `system_prompt_append(language)` — not exercised in the spike.
5. Optional extra with the wheel binary, version-pinned; Windows pass on the VM (shell in the gate,
   console windows, sandbox setup).

## Risks

1. **Protocol churn (top risk).** `app-server` is `[experimental]`; this one run already got a
   `deprecationNotice` for full-history resume. The build must pin the Codex version (the wheel)
   and keep the schema check (`codex app-server generate-json-schema`) in its test fixtures.
2. **Windows shell in the gate.** If approvals arrive as PowerShell, the bash-based gate needs a
   second parser or must lean on `commandActions` — unproven until the VM run.
3. **The user's own Codex config leaks in.** The app-server reads `~/.codex/config.toml`
   (`codexHome` in `initialize`): the Arbiter's Home Assistant and node_repl MCP servers, plugins,
   a notifier and hooks would join every TCC session unless TCC turns them off per process.
   A separate `CODEX_HOME` would isolate cleanly but loses the user's sign-in (copying `auth.json`
   risks refresh-token rotation logging the user out of their own Codex) — not recommended.
4. **Context cost.** Each model request carried ~20 k input tokens before the conversation (Codex's
   prompt + 36 TCC tool schemas); caching absorbed most of it (≈221 k of 292 k input cached).
   It counts against the user's own plan limits.
5. **Steer semantics.** A mid-turn signal waits for the current model response to end; a long
   prose answer is not cut by it. Acceptable for tuning turns; "stop" must stay an interrupt.

## Usage spent

7 turns on `gpt-5.6-luna` / `low` (T1–T4 one process; T5–T6 resumed process; one tool-approval
re-check on an ephemeral thread). Tokens: ≈293.7 k total, of which ≈221 k cached input, ≈1.4 k
output. The 5-hour window read 0 % used after the run, the weekly window 6 %.

## Rerun

```
.venv/bin/python spike/codex-app-server/serve_tcc.py spike/codex-app-server/work/tcc-project spike/codex-app-server/work/logs &
# export TCC_URL / TCC_MCP_TOKEN from work/logs/serve.out, then from spike/codex-app-server/:
python3 client.py probe                       # no model cost
python3 client.py run gpt-5.6-luna low        # T1–T4, prints thread_id
python3 client.py resume <thread_id> gpt-5.6-luna low   # T5–T6 in a new process
TCC_TOOLS_APPROVAL=approve python3 client.py tooltest gpt-5.6-luna low
```
