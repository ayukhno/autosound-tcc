"""AI-driven DSP-profile onboarding interview (docs/TCC-TZ.md §4a, option B: agent inside the
app via the Claude Agent SDK).

Scoped narrowly to ONE task — building or extending a DSP capability profile — never the whole
autosound-tuning skill. The agent has no built-in Bash/Read/Write/Edit tools at all
(`ClaudeAgentOptions.allowed_tools` lists only the four tools below); its entire filesystem reach
is through them, and each is a closure hardcoded to exactly one project directory chosen by the
CALLER, never a path the model supplies.

The question bank is `project-intake.md §4`'s DSP capability checklist, verbatim — the agent asks
THOSE questions, it does not invent new ones.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    create_sdk_mcp_server,
    tool,
)

from autosound_tcc.core import config, vendor_loader

# Verbatim from skills/autosound-tuning/references/core/project-intake.md §4 ("DSP capability
# checklist"). Do not add or reword questions here — extend that doc first if the checklist itself
# needs to change, then mirror it.
CAPABILITY_CHECKLIST = [
    "Is there a virtual/group layer above the per-channel one?",
    "EQ: bands per channel, types (PK/shelf/all-pass), file import + format",
    "Crossovers: types (LR/BW/BE), orders, independent HP/LP",
    "Delays: step and limits; polarity per-channel; a phase control (all-pass)",
    "Presets: how many; what resets on a switch (the input!)",
    "Input routing: a separate input for the measurement signal?",
]

SYSTEM_PROMPT = """You are the DSP-profile onboarding interviewer for the Tuning Command Center \
(TCC), a car-audio DSP tuning tool.

Your ONLY job: run the DSP capability-checklist interview and write the answers into a DSP \
profile via your tools. Ask closed questions with concrete options where you can; a handful of \
questions per turn, not a wall of text. Never assume a fact about the DSP model that the user \
hasn't told you or that check_existing_profile hasn't confirmed — leave it null and move on \
rather than guessing.

Steps:
1. Call check_existing_profile first. If it returns a project profile or an exact bundled match,
   do not re-ask about anything it already confirmed — call get_capability_checklist and ask only
   about what's still open.
2. As the user answers, call save_profile_field immediately for each confirmed fact — one field
   per call, don't batch everything to the end.
3. The profile's `groups` list is the load-bearing structure: figure out which tiers this DSP
   actually has (e.g. does it have a virtual/voicing layer above the per-channel one, at all? does
   it expose per-input gain/EQ/delay on things like Optic/USB/BT — that's its own group, not a
   channel) and declare each group's `id`/`label`/`fields` accordingly. A DSP with no virtual
   layer must simply have no `virtual_channels` group — never invent one to match another DSP.
4. When the profile is complete enough to be useful, or the user says they're done, call
   finalize_profile. Do not just say you're done in text — call the tool.
"""


def _load_dsp_profile_module():
    return vendor_loader.load_dsp_profile()


def _empty_draft(vendor: str, model: str) -> dict:
    return {"dsp_profile": {"name": model, "vendor": vendor, "groups": [], "_open_questions": []}}


def _set_dotted(root: dict, dotted_path: str, value: Any) -> None:
    """Set `value` at a dotted path from the profile root, creating intermediate dicts/lists as
    needed. List indices in the path are plain integers, e.g. 'groups.0.fields'."""
    parts = dotted_path.split(".")
    node = root
    for i, part in enumerate(parts[:-1]):
        key: Any = int(part) if part.isdigit() else part
        nxt_part = parts[i + 1]
        nxt_is_index = nxt_part.isdigit()
        if isinstance(node, list):
            while len(node) <= key:
                node.append([] if nxt_is_index else {})
        elif key not in node:
            node[key] = [] if nxt_is_index else {}
        node = node[key]
    last: Any = int(parts[-1]) if parts[-1].isdigit() else parts[-1]
    if isinstance(node, list):
        while len(node) <= last:
            node.append(None)
    node[last] = value


def build_tools(project_dir: Path, vendor: str, model: str):
    """One closure set per interview session — this is what keeps the agent's filesystem reach to
    exactly this project's profile file, nothing else (no path is ever taken from the model).

    Returns (tool_list, draft_box). `draft_box["data"]` is mutated in place by the tools and is
    also what the caller reads after the session ends, in case the model forgot to call
    finalize_profile (the caller can finalize on its own as a safety net).
    """
    dsp_profile = _load_dsp_profile_module()
    profile_path = config.dsp_profile_path(project_dir)
    if profile_path.is_file():
        starting = dsp_profile.load_profile(str(profile_path))
    else:
        starting = _empty_draft(vendor, model)
    draft: dict[str, Any] = {"data": starting}

    @tool("get_capability_checklist",
          "Return the fixed DSP capability-checklist questions (project-intake.md §4) to ask "
          "the user about.", {})
    async def get_capability_checklist(_args: dict) -> dict:
        return {"content": [{"type": "text", "text": json.dumps(CAPABILITY_CHECKLIST)}]}

    @tool("check_existing_profile",
          "Check the project's own in-progress profile and the bundled reference library for an "
          "EXACT vendor+model match. Never treat a different model's profile as fact.", {})
    async def check_existing_profile(_args: dict) -> dict:
        bundled = dsp_profile.find_bundled(vendor, model, str(config.bundled_profiles_dir()))
        out = {
            "project_profile": draft["data"],
            "open_questions": dsp_profile.open_questions(draft["data"]),
            "bundled_exact_match": bundled,
        }
        return {"content": [{"type": "text", "text": json.dumps(out)}]}

    @tool("save_profile_field",
          "Save one confirmed field into the in-progress profile draft.",
          {"type": "object",
           "properties": {
               "path": {"type": "string",
                         "description": "Dotted path from the profile root, e.g. "
                                        "'sample_rate_hz' or 'groups.0.fields'."},
               "value": {"description": "The confirmed value (any JSON type)."},
           },
           "required": ["path", "value"]})
    async def save_profile_field(args: dict) -> dict:
        _set_dotted(draft["data"].setdefault("dsp_profile", {}), args["path"], args["value"])
        return {"content": [{"type": "text", "text": f"saved {args['path']} = {args['value']!r}"}]}

    @tool("finalize_profile",
          "Validate and write the profile to disk. Call this when the interview is done.", {})
    async def finalize_profile(_args: dict) -> dict:
        dsp_profile.validate_profile(draft["data"])
        dsp_profile.save_profile(str(profile_path), draft["data"])
        return {"content": [{"type": "text", "text": f"saved to {profile_path}"}]}

    return [get_capability_checklist, check_existing_profile, save_profile_field,
            finalize_profile], draft


class OnboardingSession:
    """A multi-turn DSP-profile onboarding conversation. Wraps `ClaudeSDKClient` — the interview
    is inherently back-and-forth (ask, get an answer, ask a follow-up), not a one-shot `query()`.
    """

    def __init__(self, project_dir: Path, vendor: str, model: str) -> None:
        self.project_dir = project_dir
        self.vendor = vendor
        self.model = model
        tools, self._draft = build_tools(project_dir, vendor, model)
        server = create_sdk_mcp_server(name="dsp_onboarding", version="1.0.0", tools=tools)
        allowed = [f"mcp__dsp_onboarding__{t.name}" for t in tools]
        self._options = ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={"dsp_onboarding": server},
            allowed_tools=allowed,
        )
        self._client = ClaudeSDKClient(options=self._options)
        self._started = False

    @property
    def draft_profile(self) -> dict:
        """The in-progress profile draft, live — reflects every save_profile_field call so far,
        whether or not finalize_profile has run yet."""
        return self._draft["data"]

    async def start(self) -> AsyncIterator[str]:
        """Open the session with an initial prompt naming the DSP; yields text chunks."""
        await self._client.connect()
        self._started = True
        prompt = (
            f"Start the DSP capability-checklist interview for: vendor={self.vendor!r}, "
            f"model={self.model!r}."
        )
        await self._client.query(prompt)
        async for chunk in self._drain():
            yield chunk

    async def send(self, user_text: str) -> AsyncIterator[str]:
        """Send the user's next answer; yields the agent's text chunks in response."""
        if not self._started:
            raise RuntimeError("call start() before send()")
        await self._client.query(user_text)
        async for chunk in self._drain():
            yield chunk

    async def _drain(self) -> AsyncIterator[str]:
        async for message in self._client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        yield block.text
            elif isinstance(message, ResultMessage):
                return

    async def close(self) -> None:
        if self._started:
            await self._client.disconnect()
