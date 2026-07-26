"""Headless smoke tests for the AI-dialog panel and the project-param-edit flag flow."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
