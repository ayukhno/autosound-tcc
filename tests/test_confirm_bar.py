"""The Arbiter's gate as a widget (ui/tcc/confirm_bar.py).

Every assertion here is really about one property: an MCP tool call blocked on a confirmation must
always end up with a resolved future, whatever the user does or doesn't do.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import Future

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from autosound_tcc.ui.tcc import theme  # noqa: E402

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


def test_a_long_command_does_not_push_the_answer_off_the_window():
    """TEST-FINDINGS 24: a `gh issue create … --body "$(cat <<'EOF' …` with the whole body inline
    grew the block until Allow and Deny were below the window, and the turn waited forever. The
    command scrolls inside a bounded height; the answer stays on screen, and nothing is cut."""
    bar = ConfirmBar()
    bar.resize(600, 400)
    command = "\n".join(f"line {n}: gh issue create --body with a long inline heredoc" for n in range(200))

    bar.enqueue(ConfirmRequest(tool="Bash", title="Allow Bash?", detail=command, payload={}),
                Future())

    line = bar.fontMetrics().lineSpacing()
    assert bar.sizeHint().height() < 30 * line, "the block's height is bounded, whatever the command"
    assert bar._detail.text() == command, "and the whole command is still there to read"


def test_a_short_command_keeps_a_short_block():
    """The bound is a ceiling, not a floor: a one-line command is not framed in twelve lines."""
    bar = ConfirmBar()
    bar.resize(600, 400)

    bar.enqueue(ConfirmRequest(tool="Bash", title="Allow Bash?", detail="ls -la", payload={}),
                Future())

    assert bar.sizeHint().height() < 8 * bar.fontMetrics().lineSpacing()



def test_a_long_title_does_not_grow_the_bar_either():
    """The user, 2026-09-19: with a long request the buttons hid past the window.

    The command was bounded (TEST-FINDINGS 24) and the TITLE was not, so a title that wrapped over
    ten lines moved Allow down by exactly those ten lines. Both scroll together in one block now,
    and the bar's height stops depending on how much there is to read."""
    command = "\n".join(f"line {n}: gh issue create --body with a long inline heredoc"
                        for n in range(200))
    short, long_title = "Allow Bash?", "Дозволити Bash: " + " ".join(f"крок-{n}" for n in range(200))

    plain = ConfirmBar()
    plain.resize(600, 400)
    plain.enqueue(ConfirmRequest(tool="Bash", title=short, detail=command, payload={}), Future())

    wordy = ConfirmBar()
    wordy.resize(600, 400)
    wordy.enqueue(ConfirmRequest(tool="Bash", title=long_title, detail=command, payload={}),
                  Future())

    assert wordy.sizeHint().height() == plain.sizeHint().height()
    assert wordy._title.text() == long_title, "and the whole title is still there to read"


def test_the_whole_question_sits_on_the_attention_background():
    """The user, 2026-09-19, with the screenshot: the orange field goes under the WHOLE question.

    Two things had to be true and neither was. Qt paints a stylesheet background on a plain
    `QWidget` subclass only when asked, except on a top-level window — so the bar drew the tint in
    a test and nothing in the app, where it is a child of the dialog panel. And the scrolled block
    painted its own panel colour on top, which left the request itself off the tint.

    Grabbed from the PARENT for that reason: grabbing the bar alone renders it as its own window
    and shows a background the app never draws."""
    from PySide6.QtGui import QPalette

    app = QApplication.instance()
    # The sheet, the palette and the current theme are the whole application's: all go back as
    # they were. (A record of the applied sheet went too, once, and clearing the sheet alone left
    # it saying «on» -- four head tests after this one failed at 942dd61; `apply_theme` compares
    # the application's own sheet since tcc#123.)
    was = (app.styleSheet(), QPalette(app.palette()), theme._CURRENT)
    active = theme.apply_theme(app, "dark")
    try:
        panel = QWidget()
        panel.resize(600, 320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = ConfirmBar()
        layout.addWidget(bar)
        bar.enqueue(ConfirmRequest(tool="Bash", title="Allow Bash?",
                                   detail="\n".join(f"line {n}" for n in range(60)), payload={}),
                    Future())
        panel.show()
        app.processEvents()
        image = panel.grab().toImage()

        # `mix` answers in CSS `rgb(r, g, b)`; a grabbed pixel answers in `#rrggbb`.
        tint = QColor(*(int(n) for n in re.findall(r"\d+", active.mix("inv", 22, "panel")))).name()
        rect = bar._question_scroll.geometry().translated(bar.pos())
        sampled = [image.pixelColor(x, y).name()
                   for y in range(rect.top() + 2, rect.bottom() - 2, 4)
                   for x in (rect.right() - 6, rect.right() - 14)]
        on_tint = sum(1 for name in sampled if name.lower() == tint.lower())

        assert sampled, "the question block has a height to sample"
        assert on_tint > len(sampled) * 0.8, (
            f"the question block is not on the attention colour: {on_tint}/{len(sampled)} "
            f"pixels are {tint}"
        )
    finally:
        app.setStyleSheet(was[0])
        app.setPalette(was[1])
        theme._CURRENT = was[2]


def test_a_request_with_a_reason_says_it_before_the_command():
    """«Команда, яку не відкотити» was a Ukrainian literal on the Claude side and missing on omp
    (review of #115). The reason travels as an i18n key, so core stays language-free and both
    adapters' questions read the same in the Arbiter's language."""
    from autosound_tcc.ui.tcc import i18n

    bar = ConfirmBar()
    bar.enqueue(ConfirmRequest(tool="Bash", title="Allow Bash?", detail="rm -rf ~/",
                               reason="gateIrreversible"), Future())

    assert bar._detail.text() == f"{i18n.t('gateIrreversible')}: rm -rf ~/"


def test_a_request_without_a_reason_shows_its_detail_as_it_was():
    bar = ConfirmBar()
    bar.enqueue(_request(), Future())

    assert bar._detail.text() == "detail"


def test_a_request_that_timed_out_on_screen_is_withdrawn_and_said_not_recorded():
    """The tool gave up after its 10 minutes (the future cancelled) while the question was still
    up, and a later Allow was recorded as «Arbiter allowed write_rew_filters» for a write REW
    never got (the G1 review). Withdrawn now, and said as what it was."""
    bar = ConfirmBar()
    resolved, expired = [], []
    bar.resolved.connect(lambda tool, ok: resolved.append((tool, ok)))
    bar.expired.connect(expired.append)
    timed_out, following = Future(), Future()
    bar.enqueue(_request("write_rew_filters"), timed_out)
    bar.enqueue(_request("copy_helix_eq"), following)

    timed_out.cancel()  # what `await_confirmation`'s clock does

    assert expired == ["write_rew_filters"] and resolved == []
    assert bar._title.text() == "Allow copy_helix_eq?", "the next one is up"
    bar._allow.click()
    assert resolved == [("copy_helix_eq", True)] and following.result(timeout=1) is True


def test_a_click_that_beats_the_withdrawal_is_said_as_expired_once():
    """The withdrawal comes queued from the session's thread, so a click can land first."""
    import threading

    bar = ConfirmBar()
    resolved, expired = [], []
    bar.resolved.connect(lambda tool, ok: resolved.append((tool, ok)))
    bar.expired.connect(expired.append)
    future = Future()
    bar.enqueue(_request("write_rew_filters"), future)

    canceller = threading.Thread(target=future.cancel)
    canceller.start()
    canceller.join()
    bar._allow.click()  # before the queued withdrawal is delivered
    QApplication.processEvents()

    assert resolved == [] and expired == ["write_rew_filters"]
    assert bar.isHidden()
