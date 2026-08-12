"""AI-driven DSP-profile onboarding interview (docs/TCC-TZ.md §4a, option B: agent inside the
app via the Claude Agent SDK).

Scoped narrowly to ONE task — building or extending a DSP capability profile — never the whole
autosound-tuning skill. The agent has no built-in Bash/Read/Write/Edit tools at all
(`ClaudeAgentOptions.allowed_tools` lists only the five tools below); its entire filesystem reach
is through them, and each is a closure hardcoded to exactly one project directory chosen by the
CALLER, never a path the model supplies.

The question bank is `project-intake.md §4`'s DSP capability checklist, verbatim — the agent asks
THOSE questions, it does not invent new ones.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from autosound_tcc.core import claude_sdk, config, profile_writer

#: Bound into this module's globals by `claude_sdk.bind()` at the point the SDK is first needed —
#: the SDK is an extra, and importing it here would stop the window opening on an install that
#: only ever talks to Gemini (see `core/claude_sdk.py`). Declared as a list so a test can check it
#: still matches what this file actually references: a name added to the code and not to this
#: tuple is a `NameError` that only the person running an onboarding interview would find.
SDK_NAMES = (
    "AssistantMessage",
    "ClaudeAgentOptions",
    "ClaudeSDKClient",
    "ResultMessage",
    "TextBlock",
    "create_sdk_mcp_server",
    "tool",
)

_SYSTEM_PROMPT = """You are the DSP-profile onboarding interviewer for the Tuning Command Center \
(TCC), a car-audio DSP tuning tool.

Your ONLY job: run the DSP capability-checklist interview and write the answers into a DSP \
profile via your tools. Ask closed questions with concrete options where you can, 2-3 questions \
per turn — never dump the whole remaining checklist into one message, even when several fields \
are still open. Never assume a fact about the DSP model that the user hasn't told you or that \
check_existing_profile hasn't confirmed — leave it null and move on rather than guessing.

## The profile schema — follow this EXACTLY, it is consumed by code, not read by a human

Top level: {{"name": str, "vendor": str, "groups": [...], "sample_rate_hz": number|null, \
"_open_questions": [...]}}. Add other descriptive top-level keys if you like (e.g. `presets`, \
`input_routing`) — those are fine as freeform nested objects, they're just not rendered per-row.

`groups` is a flat JSON array of group objects, each EXACTLY:
    {{"id": "<snake_case_id>", "label": "<Human Label>", "fields": [<tokens>]}}
`fields` MUST be a flat array of STRING TOKENS drawn ONLY from this fixed vocabulary — nothing
else, no nested objects, no invented names:
{vocabulary}
A field not in this list has no renderer — if the DSP has a capability that doesn't fit (rare),
note it in `_open_questions` instead of inventing a field name.

Example — a DSP with no virtual layer but per-input processing (this shape, not richer):
    "groups": [
      {{"id": "physical_outputs", "label": "Output channels",
        "fields": ["hp", "lp", "gain_db", "ta_ms", "polarity", "eq"]}},
      {{"id": "inputs", "label": "Inputs", "fields": ["gain_db", "eq", "ta_ms"]}}
    ]

Steps:
1. Call check_existing_profile first. If it returns a project profile or an exact bundled match,
   do not re-ask about anything it already confirmed — call get_capability_checklist and ask only
   about what's still open.
2. As the user answers, call save_profile_field immediately for each confirmed fact — one field
   per call, don't batch everything to the end. If a save produced the wrong shape (e.g. you
   meant to store a list but it came back as a string), call reset_profile_field on that exact
   path and re-save it — don't leave a corrupted field in place or give up on finalize_profile.
3. The profile's `groups` list is the load-bearing structure: figure out which tiers this DSP
   actually has (e.g. does it have a virtual/voicing layer above the per-channel one, at all? does
   it expose per-input gain/EQ/delay on things like Optic/USB/BT — that's its own group, not a
   channel) and declare each group's `id`/`label`/`fields` per the schema above. A DSP with no
   virtual layer must simply have no `virtual_channels` group — never invent one to match another
   DSP. Details that don't fit a group row (EQ band count/types, crossover filter types/orders,
   delay step/range, preset count, input routing) are genuinely useful — record them as
   descriptive top-level keys (not inside `fields`), they just won't be per-row rendered yet.
4. When the profile is complete enough to be useful, or the user says they're done, call
   finalize_profile. Do not just say you're done in text — call the tool. If it comes back
   "not written", the writer's gate refused the draft and told you why — fix that field and call
   it again; your answers are safe on disk either way.
"""


def system_prompt() -> str:
    """Built on demand, not at import: the field vocabulary it quotes comes from the skill
    (`profile_writer.field_vocabulary`), and this module must stay importable without the
    submodule checked out."""
    return _SYSTEM_PROMPT.format(
        vocabulary=json.dumps(profile_writer.field_vocabulary(), indent=2)
    )


# Matches ui/tcc/i18n.py's language codes -- kept here rather than importing that module, since
# core/ shouldn't depend on the ui/ layer. PL/DE are reserved there too (i18n.py: "disabled").
LANGUAGE_NAMES = {"en": "English", "uk": "Ukrainian"}


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


def build_tools(project_dir: Path, vendor: str, model: str):
    claude_sdk.bind(SDK_NAMES, globals())  # `@tool` below is one of them
    """One closure set per interview session — this is what keeps the agent's filesystem reach to
    exactly this project's profile file, nothing else (no path is ever taken from the model).

    Every tool that WRITES hands the value to the skill's own `dsp_profile.py` (D-6): the draft on
    disk, validation, the JSON-decoding defences and the schema stamp all live there. This module
    used to keep the draft in memory and write the finished file itself, which made TCC an author
    of project data and put a second copy of the field vocabulary in the app.

    Returns `(tool_list, draft_box)`. `draft_box["data"]` is refreshed from disk after each write,
    so a caller reading it after the session sees what is actually stored.
    """
    profile_writer.start(project_dir, vendor, model)
    draft: dict[str, Any] = {"data": profile_writer.draft(project_dir).get("draft", {})}

    def _refresh() -> dict:
        draft["data"] = profile_writer.draft(project_dir).get("draft", {})
        return draft["data"]

    @tool("get_capability_checklist",
          "Return the fixed DSP capability-checklist questions (project-intake.md §4) to ask "
          "the user about.", {})
    async def get_capability_checklist(_args: dict) -> dict:
        return {"content": [{"type": "text",
                              "text": json.dumps(profile_writer.capability_checklist())}]}

    @tool("check_existing_profile",
          "Check the project's own in-progress profile and the bundled reference library for an "
          "EXACT vendor+model match. Never treat a different model's profile as fact.", {})
    async def check_existing_profile(_args: dict) -> dict:
        current = profile_writer.draft(project_dir)
        draft["data"] = current.get("draft", {})
        out = {
            "project_profile": draft["data"],
            "open_questions": current.get("open_questions", []),
            "bundled_exact_match": profile_writer.find_bundled(
                vendor, model, config.bundled_profiles_dir()
            ),
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
        try:
            result = profile_writer.set_field(project_dir, args["path"], args["value"])
        except profile_writer.ProfileWriterError as exc:
            return {"content": [{"type": "text", "text": f"not saved: {exc}"}]}
        _refresh()
        return {"content": [{"type": "text",
                              "text": f"saved {result['set']} = {result['value']!r}"}]}

    @tool("reset_profile_field",
          "Delete a field from the draft (by dotted path) so it can be re-saved from scratch. "
          "Use this if a previous save_profile_field produced the wrong shape (e.g. a list "
          "written as a string).",
          {"type": "object",
           "properties": {"path": {"type": "string"}},
           "required": ["path"]})
    async def reset_profile_field(args: dict) -> dict:
        try:
            result = profile_writer.reset_field(project_dir, args["path"])
        except profile_writer.ProfileWriterError as exc:
            return {"content": [{"type": "text", "text": f"not reset: {exc}"}]}
        _refresh()
        if not result.get("found"):
            return {"content": [{"type": "text", "text": f"{args['path']} not found"}]}
        return {"content": [{"type": "text", "text": f"reset {args['path']}"}]}

    @tool("finalize_profile",
          "Validate and write the profile to disk. Call this when the interview is done.", {})
    async def finalize_profile(_args: dict) -> dict:
        try:
            path = profile_writer.finalize(project_dir)
        except profile_writer.ProfileWriterError as exc:
            # The skill's gate refused; the draft is still there. Hand the reason back verbatim so
            # the interviewer can fix the specific field instead of guessing or giving up.
            return {"content": [{"type": "text", "text": f"not written: {exc}"}]}
        _refresh()
        return {"content": [{"type": "text", "text": f"saved to {path}"}]}

    return [get_capability_checklist, check_existing_profile, save_profile_field,
            reset_profile_field, finalize_profile], draft


class OnboardingSession:
    """A multi-turn DSP-profile onboarding conversation. Wraps `ClaudeSDKClient` — the interview
    is inherently back-and-forth (ask, get an answer, ask a follow-up), not a one-shot `query()`.
    """

    def __init__(
        self,
        project_dir: Path,
        vendor: str,
        model: str,
        ai_model: Optional[str] = None,
        language: str = "en",
    ) -> None:
        self.project_dir = project_dir
        self.vendor = vendor
        self.model = model
        self.language = language
        tools, self._draft = build_tools(project_dir, vendor, model)
        server = create_sdk_mcp_server(name="dsp_onboarding", version="1.0.0", tools=tools)
        allowed = [f"mcp__dsp_onboarding__{t.name}" for t in tools]
        from autosound_tcc.core.tuning_session import DEFAULT_MODEL

        self._options = ClaudeAgentOptions(
            system_prompt=system_prompt(),
            mcp_servers={"dsp_onboarding": server},
            allowed_tools=allowed,
            model=ai_model or DEFAULT_MODEL,
        )
        self._client = ClaudeSDKClient(options=self._options)
        self._started = False

    @property
    def draft_profile(self) -> dict:
        """The in-progress profile draft as it stands ON DISK — refreshed after every write, so
        this reflects what the skill actually stored rather than what was asked for."""
        return self._draft["data"]

    async def start(self) -> AsyncIterator[str]:
        """Open the session with an initial prompt naming the DSP; yields text chunks."""
        await self._client.connect()
        self._started = True
        prompt = (
            f"Start the DSP capability-checklist interview for: vendor={self.vendor!r}, "
            f"model={self.model!r}. Conduct the interview in {language_name(self.language)} -- "
            f"the skill and its users are multilingual, match the interface language."
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
