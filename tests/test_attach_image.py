"""A screenshot becomes a file in the project, and the model is handed its path.

Inline images were not an option worth having: of TCC's three front-ends only the SDK one could
carry one, and an image that lives in a context dies with it. A capture of a REW window is
evidence — it belongs on disk, where a step can cite it and the next session can look at it.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc import attach_image, i18n  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _image(width: int, height: int = 400) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("steelblue"))
    return image


def test_a_wide_capture_is_downscaled_before_it_is_saved(tmp_path):
    """A Retina REW window is 3-4 MB, and a tool result carrying an image is base64 on ONE line —
    which is what killed a live session (see tuning_session.max_buffer_size). Raising that limit
    stops the crash; it does not make a 4 MB capture a sensible thing to push through a context."""
    _app()

    path = attach_image.save(_image(3600), "w-L impulse", tmp_path)

    assert QImage(str(path)).width() == attach_image.MAX_WIDTH_PX
    assert path.stat().st_size < 400_000


def test_a_capture_that_is_already_small_is_left_alone(tmp_path):
    _app()

    path = attach_image.save(_image(900), "phase at the joint", tmp_path)

    assert QImage(str(path)).width() == 900


def test_it_lands_in_the_projects_own_record_not_a_scratch_folder(tmp_path):
    _app()

    path = attach_image.save(_image(600), "sub IR", tmp_path)

    assert path.parent == tmp_path / "process" / "attachments"
    # Sortable first, captioned second: a folder of these reads as a sequence, and each name says
    # which problem it belonged to.
    assert path.name.endswith("-sub-ir.png")
    assert path.name[:4].isdigit()


def test_a_ukrainian_caption_survives_into_the_filename(tmp_path):
    """The Arbiter writes in Ukrainian. Transliterating would produce names that help nobody."""
    _app()

    path = attach_image.save(_image(600), "імпульсна w-L", tmp_path)

    assert "імпульсна-w-l" in path.name


def test_a_caption_that_is_all_punctuation_still_produces_a_name(tmp_path):
    _app()

    path = attach_image.save(_image(600), "???", tmp_path)

    assert path.name.endswith("-screenshot.png")


def test_the_composer_line_is_relative_to_the_project(tmp_path):
    """Absolute paths from one machine are noise in a record another machine reads — and every
    other reference in the project (step evidence, saved reviews) is relative."""
    _app()
    path = attach_image.save(_image(600), "w-R 250 Hz", tmp_path)

    line = attach_image.message_line(path, "w-R 250 Hz", tmp_path)

    assert line.startswith("w-R 250 Hz — process/attachments/")
    assert str(tmp_path) not in line


def test_the_line_is_just_the_path_when_no_caption_was_given(tmp_path):
    _app()
    path = attach_image.save(_image(600), "", tmp_path)

    assert attach_image.message_line(path, "", tmp_path).startswith("process/attachments/")


def test_an_empty_clipboard_leaves_the_dialog_unable_to_accept(tmp_path):
    """"Nothing pasted yet" is the normal state on opening, not an error."""
    app = _app()
    app.clipboard().clear()

    dialog = attach_image.AttachImageDialog(tmp_path)

    assert dialog.take_from_clipboard() is False
    dialog.accept()  # the keyboard route past a disabled button must still write nothing
    assert dialog.saved_path is None
    assert dialog.line() == ""


def test_pasting_then_accepting_writes_the_file_and_returns_its_line(tmp_path):
    app = _app()
    app.clipboard().setImage(_image(2000))

    dialog = attach_image.AttachImageDialog(tmp_path)
    dialog._caption.setText("імпульсна w-L, перший пік")
    dialog.accept()

    assert dialog.saved_path is not None and dialog.saved_path.is_file()
    assert QImage(str(dialog.saved_path)).width() == attach_image.MAX_WIDTH_PX
    assert dialog.line().startswith("імпульсна w-L, перший пік — process/attachments/")


def test_pasting_while_the_caption_has_focus_still_reaches_the_preview(tmp_path):
    """⌘V went to the QLineEdit, which pastes TEXT — and an image clipboard has none, so the
    keystroke did nothing and the picture only turned up the next time the window was opened
    (user, 2026-08-11)."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    app = _app()
    app.clipboard().clear()
    dialog = attach_image.AttachImageDialog(tmp_path)
    assert dialog._image is None

    app.clipboard().setImage(_image(800))
    paste = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier, "v"
    )
    handled = dialog.eventFilter(dialog._caption, paste)

    assert handled is True, "the line edit must not swallow a picture"
    assert dialog._image is not None


def test_a_capture_taken_while_the_window_waits_appears_on_its_own(tmp_path):
    """The screenshot tool has focus at the moment the clipboard changes, so the window has to
    look again when it comes back rather than wait for a keystroke."""
    app = _app()
    app.clipboard().clear()
    dialog = attach_image.AttachImageDialog(tmp_path)

    app.clipboard().setImage(_image(700))
    dialog._on_clipboard_changed()

    assert dialog._image is not None
    assert dialog._buttons.button(dialog._buttons.StandardButton.Ok).isEnabled()


def test_the_hint_names_the_shortcut_this_platform_actually_uses(monkeypatch):
    """On macOS ⌘⇧4 writes a FILE to the desktop; ⌘⌃⇧4 is the one that copies. Telling somebody
    the wrong one leaves them pasting nothing and wondering what broke."""
    _app()
    monkeypatch.setattr(attach_image.sys, "platform", "darwin")
    assert "⌘⌃⇧4" in i18n.t(attach_image.capture_hint_key())

    monkeypatch.setattr(attach_image.sys, "platform", "win32")
    assert "Win+Shift+S" in i18n.t(attach_image.capture_hint_key())

    monkeypatch.setattr(attach_image.sys, "platform", "linux")
    assert "Ctrl+V" in i18n.t(attach_image.capture_hint_key())


def test_clearing_drops_the_wrong_capture_without_closing_the_window(tmp_path):
    """Pasting the wrong screenshot is the ordinary mistake; the only way back was Cancel and
    reopen (user, 2026-08-11)."""
    app = _app()
    app.clipboard().setImage(_image(900))
    dialog = attach_image.AttachImageDialog(tmp_path)
    dialog._caption.setText("w-L impulse")
    assert dialog._image is not None

    dialog.clear()

    assert dialog._image is None
    assert not dialog._buttons.button(dialog._buttons.StandardButton.Ok).isEnabled()
    # The caption survives: it is usually still right for the shot that was meant.
    assert dialog._caption.text() == "w-L impulse"
    dialog.accept()
    assert dialog.saved_path is None
