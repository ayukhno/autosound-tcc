"""The feedback modal — where a tester's words actually go.

The one behaviour worth a test here is the destination, not the rich-text editor: a modal that
looks like it sent something and did not is worse than no modal.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc.feedback_dialog import FeedbackDialog  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])
def test_with_no_form_configured_the_only_destination_is_github(monkeypatch):
    """The form radio was the DEFAULT and its URL is empty, so Send copied the text, opened
    nothing, and closed as though it had been sent. A beta report died there in silence."""
    from PySide6.QtGui import QDesktopServices

    _app()
    dialog = FeedbackDialog("https://github.com/ayukhno/autosound-tcc/issues/new", "")
    dialog._editor.setPlainText("the window would not open")
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))

    assert dialog._radio_github.isChecked()
    assert dialog._radio_form.isHidden() or not dialog._radio_form.isVisible()

    dialog._on_send()

    assert len(opened) == 1 and "issues/new" in opened[0]
