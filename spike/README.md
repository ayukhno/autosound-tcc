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

---

# `agent_boundary.py` — what the DSP-interview agent can actually see

A separate question from the one above, with the same answer shape: ask a live session rather
than read the documentation.

`core/agent_session.py` fences the DSP-profile interview in with four `ClaudeAgentOptions`
fields. Three can be asserted from the options object and `tests/test_agent_session.py` does.
This script asks what the CLI on the other side actually does with them — and one of the four,
`strict_mcp_config`, exists only because it was asked.

```
uv run --extra dev --python 3.12 python spike/agent_boundary.py
```

Costs two short model turns and needs a logged-in `claude`, which is why it is here and not in
the suite. Re-run it by hand when the SDK or the CLI moves.

Measured 2026-08-27 — claude-agent-sdk 0.2.145, CLI 2.1.247, on a machine with Gmail, Calendar,
Drive and home-assistant connected:

| | BASH | READ | foreign `mcp__` tools |
|---|---|---|---|
| `strict_mcp_config` unset | no | no | **39** |
| `strict_mcp_config=True` | no | no | **0** |

Two findings. `tools=[]` takes the built-in set away and leaves our own MCP tools working — the
interview still runs. And `setting_sources=[]` does **not** cover connected MCP servers: they come
from the CLI's own configuration, not from a settings file, so without the fourth field a DSP
interview had the user's mail tools in its context. Neither is guessable from the field names.
Background: `docs/TODO.md` F-035.

---

# `submodule_absent.py` — the suite without the vendored method

The measurement behind `docs/ARCHITECTURE-NOTES.md` §8, where removing the submodule was analysed
and rejected. A pytest plugin that drops the submodule from `vendor_loader`'s candidate list
rather than from the disk, so nothing is deleted to answer a question.

```
PYTHONPATH=spike uv run --extra dev --python 3.12 python -m pytest tests/ -q -p submodule_absent
```

Measured 2026-08-27 on pin `70a4fa7`: 1438 passed as-is; 178 failed with the submodule hidden and
nothing in its place; 1438 passed again with `AUTOSOUND_SKILL_DIR` pointed at a neighbouring
checkout. Full commands and the reason the installed-skill fallback is unreachable from inside the
suite are in the file's own docstring.
