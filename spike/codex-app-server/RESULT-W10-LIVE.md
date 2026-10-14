# W-10 Codex task 10, macOS half: TCC's own Codex code, live (tcc#181)

Run on 2026-10-14 on the Arbiter's Mac, branch `wave-10` at 2a37046, against `codex-cli 0.162.1`. `codex_cli.find()`
resolved the Homebrew npm shim to its native binary. The Arbiter's own ChatGPT sign-in was used (plan `plus`).
Driver: `live_w10.py`, the recipe for this evidence. Logs are in `work/logs/w10live/` (git-ignored).

What ran is the wave's code, not spike code. The session was built by `session_routes.factory` for a Codex pick:
`CodexSession` → `codex_rpc.AppServer`, `codex_cli.isolation_args` / `tcc_tool_args`, and
`shell_gate.judge_action` through `_on_request`. TCC's real `TccMcpServer` ran in the driver's process, with
a wiretap on its HTTP layer as in `serve_tcc.py`. `session.bus` was the server's bus, as `AgentWorker`
hands it. The confirmation bar was a stub bridge that accepted, declined or never answered, depending on
the scenario. The scratch project was made the way TCC makes one: an empty folder outside any git repo, with
the method linked by `vendor_loader.link_skill_into`.

Model `gpt-5.6-luna` (the oldest "fast and efficient" row of the live `model/list`, 7 rows), effort `low`.

**Driver-only deviations.**
- (a) The effort word was forced to `low` after `_clamp_effort` ran (it clamped TCC's default to `xhigh`).
  TCC never sends anything below `high`, and the brief caps the run's cost.
- (b) The phase was seeded with `SessionRegistry.sync_phase("intake")` so the thread binds. TCC does this
  from the method's process state.
- (c) The brief's example `rm -rf ~/x-nonexistent` is not flagged by the gate: a recursive delete is judged
  by what it reaches, and a missing target reaches nothing. Under `auto` it would pass. The dangerous line
  used instead is `dd if=/dev/zero of=/dev/null count=0`, which the gate flags as `gateIrreversible`
  (it overwrites a device) and which is harmless if it ever ran.

## The points

| # | Point | Result | Wire evidence (cut from the frame log `<project>/.tcc/codex-frames.jsonl`, the wiretap, the driver's reports) |
|---|---|---|---|
| 1 | Streaming → events, one `TurnEnd` | **PASS** | T2: 35 `TextDelta`, 5 `ToolCall`/5 `ToolEnd`, 1 `TurnEnd` as the generator's last event. T3: 13/3/3/1. T7 (resumed): 10 `TextDelta`/1 `TurnEnd`. Every turn of both processes: `turnend_count` 1, `last_is_turnend` true. In T1 the model's final `agentMessage` was empty (`"text": "", "phase": "final_answer"`). That is a model answer, not a mapping loss. Minor, see F2: in T6 the held command's `ToolCall("Bash")` has no `ToolEnd`. |
| 2 | Real TCC tool read, no prompts, token hidden | **PASS** | `item/completed {"type":"mcpToolCall","server":"tcc","tool":"get_tcc_state","status":"completed"}`. `mcpServer/elicitation/request` arrived 0 times, so `default_tools_approval_mode` works. Wiretap: 29 HTTP requests over both processes, `token_present` true on all, `ua: codex-mcp-client/0.162.1`. `ps` of every descendant every 0.3 s: 306 + 15 argv samples, token in 0. The argv starts `codex app-server -c …`, and the token is not in the frame log, the HTTP log or any report. |
| 3 | Window signal rides the next `turn/start` | **PASS** | `bus.push("button", label="PROBE-SIGNAL")` between T1 and T2. The out frame `turn/start … "text": "[TCC] 1 un-acknowledged signal(s) from the Arbiter -- direct requests from the human. …"` was on turn 2 of 5 and no other. `turn/steer` out: 0. The model called `ack_signals` (first call failed on a missing `outcome`, then completed) and answered `signal kind: button`. |
| 4 | Approvals through TCC's gate | **PASS** | `writes`: `REQ 0 /bin/zsh -lc 'echo hi > note.txt'` → bar asked `detail: echo hi > note.txt` → `ANS 0 {"decision":"accept"}` → `completed`, note.txt exists. `REQ 1 … 'touch denied.txt'` → asked → `{"decision":"decline"}` → `declined`, denied.txt absent. `auto`, no tick: `REQ 2 … python3 -c "…random…"` → `accept`, bar not asked, printed `888465394`. `auto` + tick `Bash` (set after that item completed): `REQ 3 … 'dd if=/dev/zero of=/dev/null count=0'` → bar asked, `reason: gateIrreversible` → declined. `auto`: `REQ 4 item/fileChange/requestApproval` → bar asked `delete: …/note.txt`, `reason: gateIrreversible` → declined, note.txt still there. |
| 5 | Interrupt | **PASS** | Mid-stream (T5): `turn/interrupt` at the first delta (t 500.102) → `turn/completed "interrupted"` (500.107). From interrupt to `TurnEnd` took 0.006 s. Pending (T6): `REQ 5 … 'touch held.txt'` asked, and the stub never answered. `turn/interrupt` (504.487) → `interrupted` (504.495) → `serverRequest/resolved {"requestId":5}` (504.496). The stub's future was **cancelled** (504.495). Request 5 was never answered, held.txt is absent, and every other request was answered exactly once (`answered_twice: []`, no "second answer" note). |
| 6 | Resume in a new process | **PASS** | Second driver process, `factory(resumed=True)`. `registry.resumable_session(route="codex")` = `01a13a6a-f479-…`. Out frame `thread/resume {"threadId":"01a13a6a-f479-…","excludeTurns":true}` (no `deprecationNotice`), `resumed: true`, same thread id. T7 asked, before any tool: "what number did the python3 random command print?" The answer was `888465394`, which exists only in the previous process's history. It said `project_dir: not returned` (T1's empty answer, see point 1). |
| 7 | The user's extras OFF | **PASS** | `config/read` raw vs. with `isolation_args` (38 argv items). MCP servers `home-assistant: true, node_repl: true, computer-use: false` → all `false`. Features on: `remote_plugin`, `tool_suggest` + the three harmless → only `api_key_model_discovery, auth_elicitation, mentions_v2`. `notify` [the computer-use client] → `[]`. `project_doc_max_bytes` 32768 → 0. `skills.bundled.enabled` false. `shell_environment_policy.exclude` `["TCC_MCP_TOKEN"]`. `unknown_enabled_features` empty in both. Live `mcpServerStatus/list`: tcc 36 tools; home-assistant, node_repl and computer-use 0 tools. |
| 8 | Terminal | **(a) needs a decision · (b) not seen** | `codex_terminal.connection()` read the url and token from `.mcp.json`, and `codex_terminal.command()` built the argv, run as `codex exec … --json`. The token was in env only: in 108 argv samples it appeared 0 times. TCC's server saw `initialize`, `tools/list` with `token_present` true. **(a)** With the terminal's exact pieces, the item ended `get_tcc_state status: failed, "MCP tool call requires approval, but approval policy is never"`: non-interactive `exec` cannot ask. Rerun with the session's one key `mcp_servers.tcc.default_tools_approval_mode="approve"` added: `completed`, and it returned the real `project_dir`. **(b)** Both runs: "No autosound-tuning skill … is listed". The vendored `rew_tool/project.py` has no `agents-setup` command (waits for the re-pin, tcc #200), so no `AGENTS.md` was written and nothing was re-asked. |
| 9 | Close | **PASS** | Session and resume processes: `close()` → app-server `returncode 0` after stdin closed. `pgrep -P <driver pid>` (by PID) empty after close. The same was true after both `exec` runs (exit 0). |

## Findings for the round after (no `src/` was touched)

- **F1, start path (FAIL of the method check, not of the nine points).** Codex lists the linked method as
  `autosound-tuning:autosound-tuning`, scope `user`, path `vendor/autosound-tuning-skill/skills/autosound-tuning/SKILL.md`.
  Codex namespaces it because the vendored repo has `.claude-plugin/plugin.json`. `CodexSession._load_skill`
  matches by the bare name (`skill.get("name") != SKILL_NAME → continue`). Two consequences:
  - Every Codex session start says "Codex did not load the tuning method … do not trust anything it says"
    (seen in T1 and T7), although the method is loaded from the bound copy.
  - The second-copy refusal never looks at a namespaced name, so another copy would pass unnoticed.

  Task 1 recorded `skills/list` with a bare `SKILL.md` copy and no plugin around it. The fixture therefore
  carries the bare name, and the tests could not see this.
- **F2, minor.** When an approval is interrupted while pending, Codex sends no `item/completed` for that
  command. The turn's `finally` clears `_running` without a `ToolEnd`, so the panel gets `ToolCall("Bash")`
  and then `TurnEnd` directly.
- **F3, Arbiter's decision.** In a terminal, Codex's own approval settings rule (the Arbiter, 2026-10-14):
  interactively, it asks the person on every TCC tool call, and in `exec` it refuses them. Adding
  `default_tools_approval_mode="approve"` for `tcc` to `tcc_connection_args` would match the in-app session,
  where TCC's tools confirm themselves inside TCC.
- **F4, waits for #200.** The terminal Codex does not see the method. `AGENTS.md` cannot be written by the
  vendored copy until the re-pin.

## Usage

7 app-server turns in 16 model requests, plus 2 `codex exec` runs. **≈361 k tokens in total**
(app-server 191 064, of which 144 128 cached input; terminal 170 061, of which 126 976 cached). The two
terminal runs cost about as much as five session turns, because the user's own Codex config is not isolated
there: its MCP servers load.

## Rerun

```
P=<an empty folder outside any git repo>
uv run python spike/codex-app-server/live_w10.py config   $P
uv run python spike/codex-app-server/live_w10.py session  $P gpt-5.6-luna
uv run python spike/codex-app-server/live_w10.py resume   $P gpt-5.6-luna
uv run python spike/codex-app-server/live_w10.py terminal $P gpt-5.6-luna
W10_TERMINAL_APPROVE=1 uv run python spike/codex-app-server/live_w10.py terminal $P gpt-5.6-luna
uv run python spike/codex-app-server/live_w10.py tokens   $P
```
