"""Headless smoke tests for the AI-dialog panel and the project-param-edit flag flow."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc.dialog_panel import DialogPanel, MessageBubble  # noqa: E402
from autosound_tcc.ui.tcc.mock_data import DIALOG  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_dialog_panel_builds_one_bubble_per_mock_message():
    _app()
    panel = DialogPanel()
    bubbles = panel._chat.findChildren(MessageBubble)
    assert len(bubbles) == len(DIALOG)
    assert not panel.is_editing


def test_edit_chip_flow_adds_system_messages_and_toggles_state():
    _app()
    panel = DialogPanel()
    seen = []
    panel.editingChanged.connect(seen.append)

    panel._start_editing("manual")
    assert panel.is_editing
    assert seen == [True]
    bubbles = panel._chat.findChildren(MessageBubble)
    assert len(bubbles) == len(DIALOG) + 1
    assert bubbles[-1].property("class") == "msg msg-sys"

    panel._finish_editing()
    assert not panel.is_editing
    assert seen == [True, False]
    bubbles = panel._chat.findChildren(MessageBubble)
    assert len(bubbles) == len(DIALOG) + 2


def test_reasons_bar_toggles_on_chip_click_when_not_editing():
    _app()
    panel = DialogPanel()
    assert panel._reasons_bar.isHidden()
    panel._on_chip_clicked()
    assert not panel._reasons_bar.isHidden()
    panel._on_chip_clicked()
    assert panel._reasons_bar.isHidden()


def test_retranslate_does_not_leave_stale_bubbles_behind():
    """Regression: clearing the chat with deleteLater() alone (no setParent(None) first) leaves
    the old widgets as real children of self._chat until the next event-loop pass -- calling
    retranslate() without ever spinning the event loop (exactly what happens on a synchronous
    language switch) would double- then triple-count bubbles here without the fix."""
    _app()
    panel = DialogPanel()
    panel.retranslate()
    assert len(panel._chat.findChildren(MessageBubble)) == len(DIALOG)
    panel.retranslate()
    assert len(panel._chat.findChildren(MessageBubble)) == len(DIALOG)


def test_a_markdown_table_is_rendered_as_a_table():
    """Models answer equipment questions with one — "| Код | Роль | Драйвер |" — and the
    transcript showed the pipes and dashes raw, which makes a correct answer look broken."""
    from autosound_tcc.ui.tcc.dialog_panel import _markdown

    html = _markdown("| Код | Роль |\n|---|---|\n| tw-L/R | Твітер |")

    assert "<table" in html and "<th align='left'>Код</th>" in html
    assert "<td>tw-L/R</td>" in html
    assert "|---|" not in html  # the separator row is structure, not content


def test_text_around_a_table_keeps_its_place():
    from autosound_tcc.ui.tcc.dialog_panel import _markdown

    html = _markdown("before\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nafter")

    assert html.index("before") < html.index("<table") < html.index("after")


def test_a_stray_pipe_line_is_not_mistaken_for_a_table():
    from autosound_tcc.ui.tcc.dialog_panel import _markdown

    html = _markdown("| just one line |")

    assert "<table" not in html


def test_the_role_line_is_measured_with_its_letter_spacing():
    """`.msg-who` sets `letter-spacing: 1px`, which Qt renders but does not report through
    `fontMetrics()` — so the bubble came out a pixel per character short and "ARBITER · YOU" lost
    its U to the border."""
    from autosound_tcc.ui.tcc.dialog_panel import MessageBubble

    _app()
    role = "ARBITER · YOU"
    bubble = MessageBubble("user", role, "Hi")

    bare = bubble._who_label.fontMetrics().horizontalAdvance(role) + 28

    assert bubble.natural_width >= bare + len(role)


def test_a_long_message_keeps_the_panel_pinned_to_the_bottom():
    """A bubble's height settles over several layout passes, so a single scroll lands at whatever
    it was one pass ago — a long message ended up with only its top edge on screen."""
    from autosound_tcc.ui.tcc.dialog_panel import DialogPanel

    _app()
    panel = DialogPanel()
    panel._stick_to_bottom = True

    bar = panel._scroll.verticalScrollBar()
    bar.setRange(0, 500)  # an empty panel has no range to scroll away from

    panel._on_scroll_value_changed(0)  # scrolled up by hand
    assert panel._stick_to_bottom is False

    panel._on_scroll_value_changed(bar.maximum())  # back at the bottom
    assert panel._stick_to_bottom is True


def test_the_composer_grows_for_a_pasted_paragraph_not_only_for_newlines():
    """User, 2026-08-21: "коли в діалог вставляю текст на декілька строк - висота поля не
    збільшується".

    The growth was written and worked for text carrying real newlines, which is why it looked
    present: `contentsChanged` fires with the block count already final. A pasted paragraph is ONE
    block that wraps, and the wrap is computed a layout pass later — the field measured itself
    before that and stayed one line tall. Both shapes are asserted here, and the shrink back with
    them: a field that only ever grows is the same bug facing the other way.
    """
    app = _app()
    panel = DialogPanel()
    panel.resize(420, 700)
    panel.show()
    app.processEvents()
    field = panel._input
    one_line = field.height()

    def paste(text: str) -> int:
        data = QMimeData()
        data.setText(text)
        field.insertFromMimeData(data)
        for _ in range(3):  # the wrap lands on a later pass; that is the whole point
            app.processEvents()
        return field.height()

    wrapped = paste("слово " * 60)
    assert wrapped > one_line, "a pasted paragraph wraps, so the field has to grow with it"

    field.clear()
    app.processEvents()
    assert field.height() == one_line, "and shrinks back when the text goes"

    assert paste("\n".join(f"line {i}" for i in range(5))) > one_line

    field.clear()
    tall = paste("\n".join(f"line {i}" for i in range(40)))
    assert tall <= paste("\n".join(f"line {i}" for i in range(200))), \
        "past the cap the field stops growing and scrolls instead of eating the transcript"
