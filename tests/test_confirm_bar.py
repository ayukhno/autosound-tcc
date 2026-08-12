"""The Arbiter's gate as a widget (ui/tcc/confirm_bar.py).

Every assertion here is really about one property: an MCP tool call blocked on a confirmation must
always end up with a resolved future, whatever the user does or doesn't do.
"""

from __future__ import annotations

import os
from concurrent.futures import Future

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core.mcp_server import ConfirmRequest  # noqa: E402
from autosound_tcc.ui.tcc.confirm_bar import ConfirmBar  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication([])


def _request(tool="copy_helix_eq"):
    return ConfirmRequest(tool=tool, title=f"Allow {tool}?", detail="detail", payload={})


def test_hidden_until_something_needs_confirming():
    bar = ConfirmBar()

    assert bar.isHidden()
    assert bar.pending_count == 0


def test_allow_resolves_the_future_true():
    bar = ConfirmBar()
    future: "Future[bool]" = Future()

    bar.enqueue(_request(), future)
    assert not bar.isHidden()
    bar._allow.click()

    assert future.result(timeout=1) is True
    assert bar.isHidden()


def test_deny_resolves_the_future_false():
    bar = ConfirmBar()
    future: "Future[bool]" = Future()

    bar.enqueue(_request(), future)
    bar._deny.click()

    assert future.result(timeout=1) is False


def test_requests_queue_one_at_a_time():
    """Two prompts fighting for the same screen is how people learn to click through both."""
    bar = ConfirmBar()
    first, second = Future(), Future()

    bar.enqueue(_request("write_rew_filters"), first)
    bar.enqueue(_request("copy_helix_eq"), second)

    assert bar.pending_count == 2
    assert bar._title.text() == "Allow write_rew_filters?"
    assert not second.done()

    bar._allow.click()

    assert first.result(timeout=1) is True
    assert bar._title.text() == "Allow copy_helix_eq?"
    assert not second.done()


def test_reject_all_denies_everything_outstanding():
    """Shutdown must not leave a tool call parked until its timeout."""
    bar = ConfirmBar()
    current, queued = Future(), Future()
    bar.enqueue(_request(), current)
    bar.enqueue(_request(), queued)

    bar.reject_all()

    assert current.result(timeout=1) is False
    assert queued.result(timeout=1) is False
    assert bar.isHidden()
    assert bar.pending_count == 0


def test_a_request_whose_caller_gave_up_is_skipped():
    bar = ConfirmBar()
    abandoned: "Future[bool]" = Future()
    abandoned.set_result(False)  # the tool already timed out
    live: "Future[bool]" = Future()

    bar.enqueue(_request("abandoned"), abandoned)
    bar.enqueue(_request("still_wanted"), live)

    assert bar._title.text() == "Allow still_wanted?"


def test_resolved_signal_reports_the_verdict():
    bar = ConfirmBar()
    seen: list[tuple[str, bool]] = []
    bar.resolved.connect(lambda tool, ok: seen.append((tool, ok)))

    bar.enqueue(_request("write_rew_filters"), Future())
    bar._deny.click()

    assert seen == [("write_rew_filters", False)]


def test_ticking_always_names_the_tool_it_covers(tmp_path):
    """Claude Code's own prompt works this way, and the reason is the one measured here all day: a
    gate that fires constantly gets clicked through, so the way to keep it meaningful is to let it
    be narrowed deliberately — one tick, one kind."""
    from concurrent.futures import Future

    from autosound_tcc.core.mcp_server import ConfirmRequest
    from autosound_tcc.ui.tcc.confirm_bar import ConfirmBar

    bar = ConfirmBar()
    seen: list[str] = []
    bar.alwaysAllowed.connect(seen.append)
    bar.enqueue(ConfirmRequest(tool="Bash", title="t", detail="d"), Future())

    bar._always.setChecked(True)
    bar._answer(True)

    assert seen == ["Bash"]


def test_the_tick_does_not_carry_over_to_the_next_request(tmp_path):
    from concurrent.futures import Future

    from autosound_tcc.core.mcp_server import ConfirmRequest
    from autosound_tcc.ui.tcc.confirm_bar import ConfirmBar

    bar = ConfirmBar()
    seen: list[str] = []
    bar.alwaysAllowed.connect(seen.append)
    bar.enqueue(ConfirmRequest(tool="Bash", title="t", detail="d"), Future())
    bar._always.setChecked(True)
    bar._answer(True)
    bar.enqueue(ConfirmRequest(tool="Read", title="t", detail="d"), Future())

    bar._answer(True)

    assert seen == ["Bash"]


def test_denying_never_remembers(tmp_path):
    """A refusal is not a rule; ticking the box and then refusing must not silently allow it next
    time."""
    from concurrent.futures import Future

    from autosound_tcc.core.mcp_server import ConfirmRequest
    from autosound_tcc.ui.tcc.confirm_bar import ConfirmBar

    bar = ConfirmBar()
    seen: list[str] = []
    bar.alwaysAllowed.connect(seen.append)
    bar.enqueue(ConfirmRequest(tool="Bash", title="t", detail="d"), Future())

    bar._always.setChecked(True)
    bar._answer(False)

    assert seen == []
