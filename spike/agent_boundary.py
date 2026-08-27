"""What the DSP-interview agent can actually see — asked of a live session, not of the docs.

F-035. `core/agent_session.py` sets four fields to fence the interview in. Three of them can be
asserted from the options object, and `tests/test_agent_session.py` does. What no unit test can
answer is what the CLI on the other side of those options DOES with them — and one of the four,
`strict_mcp_config`, was only found because this script asked.

Two questions, and the second is the one that pays:

1. Does `tools=[]` take the built-in set away without taking our own MCP tools with it? If it
   took both, the interview would not run at all.
2. With `setting_sources=[]` already set, can the agent still see the MCP servers the person
   connected to their own Claude Code?

Measured 2026-08-27 — claude-agent-sdk 0.2.145, CLI 2.1.247, on a machine with Gmail, Calendar,
Drive and home-assistant connected:

    strict_mcp_config unset   BASH: no   READ: no   foreign mcp__ tools: 39
    strict_mcp_config=True    BASH: no   READ: no   foreign mcp__ tools: 0

So `tools=[]` does its half, and `setting_sources=[]` does NOT cover connected MCP servers:
they come from the CLI's own configuration, not from a settings file. That is not guessable from
the field names, which is why this file exists.

COSTS MONEY and needs a logged-in `claude` — two short model turns. Not a test for that reason;
re-run it by hand when the SDK or the CLI moves under us.

    uv run --extra dev --python 3.12 python spike/agent_boundary.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import anyio
from claude_agent_sdk import (
    AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, TextBlock,
    create_sdk_mcp_server, tool,
)

QUESTION = (
    "Answer with three lines and nothing else:\n"
    "BASH: yes or no — do you have a Bash tool?\n"
    "READ: yes or no — do you have a Read tool?\n"
    "FOREIGN: the number of tools you have whose name starts with mcp__ but NOT with "
    "mcp__probe__, then a few of their names."
)

CALLED: list[str] = []


@tool("ping", "Return the secret word for this probe. Call it when asked for the secret word.", {})
async def ping(args):
    CALLED.append("ping")
    return {"content": [{"type": "text", "text": "the secret word is BOUNDARY-OK"}]}


async def ask(prompt: str, cwd: Path, strict: bool) -> str:
    """One session, shaped exactly like `agent_session.OnboardingSession`'s."""
    server = create_sdk_mcp_server(name="probe", version="1.0.0", tools=[ping])
    kwargs = dict(
        system_prompt="You are a probe. Answer exactly in the format asked.",
        mcp_servers={"probe": server},
        allowed_tools=["mcp__probe__ping"],
        model="claude-sonnet-5",
        tools=[],
        cwd=cwd,
        setting_sources=[],
    )
    if strict:
        kwargs["strict_mcp_config"] = True
    client = ClaudeSDKClient(options=ClaudeAgentOptions(**kwargs))
    await client.connect()
    said: list[str] = []
    try:
        await client.query(prompt)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        said.append(block.text)
    finally:
        await client.disconnect()
    return "\n".join(said).strip()


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-boundary-") as tmp:
        cwd = Path(tmp)

        print("=== 1. do our own MCP tools survive tools=[] ? ===")
        said = await ask("Call your ping tool and tell me the secret word it returns.", cwd, True)
        print("model:", said[:200])
        print("TOOL ACTUALLY RAN:", bool(CALLED))
        if not CALLED:
            print("!! the interview would not run — tools=[] took the MCP server with it")

        for strict in (False, True):
            print()
            print(f"=== 2. what else is in context — strict_mcp_config={strict} ===")
            print(await ask(QUESTION, cwd, strict)[:800] if False else
                  (await ask(QUESTION, cwd, strict))[:800])


if __name__ == "__main__":
    sys.exit(anyio.run(main))
