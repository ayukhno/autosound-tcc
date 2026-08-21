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


def test_opening_the_dialog_with_no_form_raises_nothing_at_all():
    """The branch that hides the form also checks the GitHub radio on, and `toggled` reached the
    label sync before the Send button it writes to had been built:
    `AttributeError: 'FeedbackDialog' object has no attribute '_send'` (user, 2026-08-21, off the
    log). This is the configuration a beta install actually ships with.

    Asserted through `sys.excepthook` rather than by expecting a raise, because that is where the
    failure surfaced: an exception inside a Qt slot does not propagate to the code that triggered
    the signal — Qt reports it and carries on, the constructor finishes, and the label gets set a
    few lines later anyway. The dialog WORKED. What the Arbiter got was a red banner over a
    window that was fine, which is its own kind of broken and invisible to a test that only looks
    at the finished widget.
    """
    import sys

    _app()
    caught: list = []
    original, sys.excepthook = sys.excepthook, lambda *exc: caught.append(exc)
    try:
        dialog = FeedbackDialog("https://github.com/example/repo/issues/new", "")
    finally:
        sys.excepthook = original

    assert caught == [], f"constructing the dialog reported {caught}"
    assert dialog._radio_github.isChecked()
    assert dialog._send.text(), "and Send says where it is going"
