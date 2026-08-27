"""The DSP-profile interview agent's BOUNDARY — what it may reach, and where it runs.

F-035. This file exists because the module's docstring and its code disagreed, silently, for an
unknown length of time: the docstring said the agent had no built-in tools and named
`allowed_tools` as the reason, while `allowed_tools` only auto-approves what is already available
and `tools` — the field that decides what exists — was never set at all. Nothing failed. The one
thing refusing a `Bash` call was the SDK raising over a `can_use_tool` callback nobody passed,
which is a boundary by accident.

So the rule these tests enforce is not "the options look right today". It is that the CLAIM and
the VALUE are one thing: change either without the other and this file goes red.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from autosound_tcc.core import agent_session

#: The docstring's machine-readable line. One line, one claim, and this is the only place its
#: shape is written down — a test that accepted several shapes would drift the way the prose did.
_GRANTED = re.compile(r"^Built-in tools granted: *(.+?) *$", re.M)


def _declared_tools() -> list[str]:
    """The built-in tools the module docstring PROMISES, as a list."""
    found = _GRANTED.search(agent_session.__doc__ or "")
    assert found, (
        "the module docstring no longer carries a 'Built-in tools granted:' line — it is the "
        "claim this file checks, and removing it removes the check, not the obligation")
    said = found.group(1).strip()
    return [] if said == "NONE" else [name.strip() for name in said.split(",") if name.strip()]


def test_the_docstring_promise_is_the_value_the_options_carry():
    """The claim and the code, compared. Neither is allowed to move alone."""
    assert _declared_tools() == agent_session.BUILTIN_TOOLS


def test_granting_a_tool_in_code_alone_fails_this_file(monkeypatch):
    """The check has to be able to FAIL, or it is decoration. Widen the code, leave the sentence:
    red. That is the exact shape of what went wrong — one half moved, nobody noticed."""
    monkeypatch.setattr(agent_session, "BUILTIN_TOOLS", ["Bash"])

    assert _declared_tools() != agent_session.BUILTIN_TOOLS


def test_the_boundary_is_stated_and_not_inherited(tmp_path, monkeypatch):
    """All four fields set, on a real session's options.

    `None` on any of them is not a smaller version of the same thing — it is the CLI's default,
    which is the whole built-in tool set, TCC's own working directory, every settings file on the
    machine, and every MCP server the person has connected. The test asserts they are SET, not
    merely that they are falsy: `[]` and `None` read alike in an `if` and mean opposite things
    here.
    """
    session = _session(tmp_path, monkeypatch)
    options = session._options

    assert options.tools == [], "no built-in tools"
    assert options.setting_sources == [], "no settings files, so no hooks from whoever's machine"
    assert Path(options.cwd) == tmp_path, "the project, not wherever TCC was started"
    assert options.strict_mcp_config is True, "only our own tool server"

    for field in ("tools", "cwd", "setting_sources", "strict_mcp_config"):
        assert getattr(options, field) is not None, (
            f"{field} is None — that is the SDK default, and every default here lets the outside "
            "in (F-035)")


def test_the_users_own_mcp_servers_are_not_in_the_interview():
    """The fourth field, and the one no field name gives away: emptying `setting_sources` does NOT
    keep connected MCP servers out, because they come from the CLI's own configuration rather than
    from a settings file.

    Found by asking a live session what it could see, not by reading. With the other three set and
    this one left alone the model listed 39 tools that were not ours — `mcp__claude_ai_Gmail__*`,
    `Google_Calendar`, `Google_Drive`. With `strict_mcp_config=True`: 0
    (`spike/agent_boundary.py`, 2026-08-27, SDK 0.2.145, CLI 2.1.247).

    Asserted on the SOURCE rather than on a constructed session, so that it also fails if somebody
    removes the line while leaving a default that happens to be true in some future SDK: what is
    under test is that this app SAYS it, not that the SDK currently agrees.
    """
    source = Path(agent_session.__file__).read_text(encoding="utf-8")

    assert "strict_mcp_config=True" in source, (
        "the interview no longer says strict_mcp_config — without it the agent sees every MCP "
        "server the person connected to their own Claude Code (F-035)")


def test_tools_is_a_LIST_because_anything_else_means_every_tool(tmp_path, monkeypatch):
    """A trap worth a test of its own. The SDK reads `[]` as "disable all built-in tools" only for
    a `list`; anything else falls through to its preset branch and is sent as `--tools default`,
    which is every tool there is. So the type is not a style question here — it is the difference
    between no tools and all of them, and neither reads differently on the page.

    What this actually guards is the `list(...)` at the call site, which is the only thing that
    normalises the type. Freezing the module constant into a tuple is caught by the docstring
    comparison rather than here (measured: `[] != ()`), but a tuple built AT the call — the same
    edit one line lower — reaches the SDK untouched, and only this fails.
    """
    options = _session(tmp_path, monkeypatch)._options

    assert isinstance(options.tools, list) and not isinstance(options.tools, tuple)
    assert isinstance(options.setting_sources, list)


def test_the_session_owns_its_own_copy_of_the_boundary(tmp_path, monkeypatch):
    """A live session's reach must not be widenable through the module constant it was built
    from."""
    options = _session(tmp_path, monkeypatch)._options

    assert options.tools is not agent_session.BUILTIN_TOOLS
    assert options.setting_sources is not agent_session.SETTING_SOURCES


def test_the_five_mcp_tools_are_the_only_thing_auto_allowed(tmp_path, monkeypatch):
    """`allowed_tools` is an auto-approval list, not an availability list — the confusion this
    whole file comes from. Whatever else it is, it is only ever our own MCP tools."""
    options = _session(tmp_path, monkeypatch)._options

    assert options.allowed_tools, "the interview cannot run with nothing auto-approved"
    assert all(name.startswith("mcp__dsp_onboarding__") for name in options.allowed_tools), (
        f"something outside the interview's own tool server is auto-approved: "
        f"{options.allowed_tools}")


def test_a_project_directory_that_is_not_there_is_said_at_once(tmp_path, monkeypatch):
    """The folder is the caller's to make, and `cwd` made that load-bearing: the SDK spawns the
    CLI in it and refuses one that does not exist. A caller who forgets should hear it here, by
    name, rather than as an SDK error several awaits later on a worker thread."""
    monkeypatch.setattr(agent_session.profile_writer, "start", lambda *a, **kw: None)
    missing = tmp_path / "never_made"

    with pytest.raises(NotADirectoryError) as raised:
        agent_session.OnboardingSession(missing, "Musway", "M6V4")

    assert str(missing) in str(raised.value)


@pytest.mark.parametrize("caller", ["cli", "dialog"])
def test_both_callers_create_the_folder_before_the_session(caller):
    """The other half of the contract above, read from the callers themselves rather than trusted.

    Source order, not a run: both sites are a `mkdir` and then a construction, and what this
    guards is somebody moving the construction above the `mkdir` — which no runtime test of the
    happy path would notice.
    """
    import ast

    root = Path(agent_session.__file__).parents[3]
    if caller == "cli":
        path = root / "src" / "autosound_tcc" / "dsp_profile_interview.py"
        builds = "OnboardingSession"
    else:
        path = root / "src" / "autosound_tcc" / "ui" / "tcc" / "new_project_dialog.py"
        builds = "ProfileInterviewDialog"
    source = path.read_text(encoding="utf-8")

    mkdir_at = min(
        node.lineno for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "mkdir")
    builds_at = min(
        node.lineno for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == builds)

    assert mkdir_at < builds_at, (
        f"{path.name} builds the interview at line {builds_at}, before its mkdir at {mkdir_at} — "
        "the session now refuses a project directory that is not there")


def _session(tmp_path, monkeypatch):
    """A session with the skill's writer stubbed out: what is under test is the OPTIONS, and
    `build_tools` otherwise starts a real profile draft through the vendored method."""
    monkeypatch.setattr(agent_session.profile_writer, "start", lambda *a, **kw: None)
    monkeypatch.setattr(agent_session.profile_writer, "draft", lambda *a, **kw: {"draft": {}})
    return agent_session.OnboardingSession(tmp_path, "Musway", "M6V4")
