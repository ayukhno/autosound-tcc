# Harness spike — reproducing the omp result on your own machine

Answers two questions with evidence rather than documentation:

1. **Does the harness reach TCC's MCP server** as it stands — streamable HTTP on
   loopback, `X-TCC-Token` header, config in the project's `.mcp.json`?
2. **Does a tool-permission request reach an external non-Node host, and does the
   agent actually block until that host answers?** This is the load-bearing one:
   it is what `TuningSession._can_use_tool` → `ConfirmRequest` → Qt dialog does
   today via the Claude Agent SDK, and nothing may regress there.

No provider credentials and no cost: a stub stands in for the model and always
replies with the same tool call.

## Setup

```
python3 -m venv /tmp/tccvenv
/tmp/tccvenv/bin/pip install mcp claude-agent-sdk uvicorn
brew install can1357/tap/omp
```

## Run

Three terminals, from the repo root.

**1 — TCC's real MCP server, headless.** Writes `.mcp.json` into the project
folder exactly as the GUI does, and wiretaps the JSON-RPC both ways.

```
mkdir -p /tmp/fx
HOLD_S=6 LIFETIME_S=180 /tmp/tccvenv/bin/python spike/serve_tcc.py /tmp/fx
```

**2 — the stub model.**

```
/tmp/tccvenv/bin/python spike/stub_llm.py
```

**3 — the host driver.** Speaks omp's `rpc-ui` protocol over stdio, which is the
seat TCC would occupy, and answers the approval frame six seconds late on purpose.

```
PROJECT_DIR=/tmp/fx WARMUP_S=12 ANSWER_DELAY=6 /tmp/tccvenv/bin/python spike/rpc_driver.py
```

## What to look for

**Question 1** — in `/tmp/spike/http.log`:

```
-> initialize            protocolVersion 2025-03-26, clientInfo "omp-coding-agent"
-> notifications/initialized
-> tools/list
<- result                get_tcc_state … TCC's tools, with descriptions
```

`token_present` must be `true` on every line and no response may be a 401.

**Question 2** — in the driver's own timeline. The shape that matters:

```
12.61s  AGENT -> UI REQUEST   method "select"  title "Allow tool: bash …"
12.61s  tool start
18.61s  HOST -> extension_ui_response  value "Approve"
18.79s  tool end
```

The gap between the request and `tool end` should equal `ANSWER_DELAY`. That gap
*is* the answer: the agent waited for a Python process to decide.

Run it again with `ANSWER=Deny` to confirm the refusal path, and with
`ANSWER_DELAY=0` to see the same flow without the artificial wait.

## Known result, and the one open item

Both questions passed for omp on 17.2.5. The open item: TCC's MCP tools arrive
over the wire but are **not** placed in the tool list the model sees. omp mounts
MCP tools as `discoverable` (reachable under `xd://`) rather than `essential`
(top-level), which is its way of keeping tool schemas out of the prompt. Check
`/tmp/spike/catalogue.json` — it holds the exact catalogue the model was offered.
Deciding how TCC's tools should be presented, and what that means for the skill's
wording, is the next question, not a blocker.

`opencode` is not covered here yet; it needs the same servers but its MCP config
goes in `opencode.json`, not `.mcp.json`.
