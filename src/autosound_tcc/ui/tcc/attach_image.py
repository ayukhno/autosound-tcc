"""Put a screenshot from the clipboard into the project, and hand the model its path.

Why a file and not an inline image. TCC talks to three front-ends — the in-app SDK session, omp,
and the Arbiter's own terminal — and only one of them has anywhere to put an image in a message.
A file works for all three: every agent CLI here can read one. It also survives the conversation,
which is the point that matters more: a screenshot of a REW window is evidence, it can be named in
a step's `evidence` list, and the next session can go and look at it. An inline image lives in one
context and dies with it (`process/` is the project's own namespace for exactly this kind of
record).

Why it is downscaled. A tool result carrying an image is base64 on one line, and the SDK refuses a
line over its buffer limit — a live tune ended on exactly that (2026-08-11, see
`tuning_session.max_buffer_size`). Raising the limit stops the crash; it does not make a 4 MB
Retina capture a sensible thing to push through a model's context. A REW window at 1400 px is
still readable to the pixel that matters — the cursor, the grid, the trace.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from autosound_tcc.ui.tcc import i18n

# Wide enough that a REW trace, its grid and the cursor readout stay legible; small enough that the
# base64 of it is not a meaningful fraction of a context window.
MAX_WIDTH_PX = 1400
ATTACHMENTS_DIRNAME = "attachments"


def attachments_dir(project_dir: Path) -> Path:
    """`<project>/process/attachments` — inside `process/`, because this is part of the record of
    what happened, not a scratch folder."""
    return Path(project_dir) / "process" / ATTACHMENTS_DIRNAME


def slugify(caption: str) -> str:
    """A caption as a filename fragment. Latin-transliterating is deliberately NOT done: the
    Arbiter writes in Ukrainian, and `w-l-imnpuls` helps nobody. Unsafe characters go, the rest
    stays as typed."""
    text = unicodedata.normalize("NFC", (caption or "").strip().lower())
    text = re.sub(r"[^\w\-]+", "-", text, flags=re.UNICODE).strip("-")
    return text[:48] or "screenshot"


def scaled(image: QImage, max_width: int = MAX_WIDTH_PX) -> QImage:
    if image.isNull() or image.width() <= max_width:
        return image
    return image.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)


def save(image: QImage, caption: str, project_dir: Path) -> Path:
    """Write the image under `process/attachments/` and return its path.

    The name is `<timestamp>-<caption>.png`: sortable first, so a folder of them reads as a
    sequence, and captioned second, so a name says which problem it belonged to.
    """
    directory = attachments_dir(project_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    path = directory / f"{stamp}-{slugify(caption)}.png"
    scaled(image).save(str(path), "PNG")
    return path


def message_line(path: Path, caption: str, project_dir: Path) -> str:
    """What goes into the composer: the caption, then a path relative to the project.

    Relative, because that is how every other reference in this project is written — a step's
    evidence, the reviewer's saved text — and because an absolute path from one machine is noise
    in a record another machine will read.
    """
    try:
        shown = path.relative_to(Path(project_dir))
    except ValueError:
        shown = path
    caption = (caption or "").strip()
    return f"{caption} — {shown}" if caption else str(shown)


def clipboard_image() -> Optional[QImage]:
    """Whatever picture the clipboard is holding, or None. Never raises: an empty clipboard is the
    normal state, not an error."""
    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        return None
    image = clipboard.image()
    return None if image.isNull() else image


class AttachImageDialog(QDialog):
    """Paste a screenshot, name it, and get back a line to send.

    Reads the clipboard on open (the usual flow: ⌘⇧4, then this button) and takes ⌘V as well, so a
    capture made after the window opened does not require closing it.
    """

    def __init__(self, project_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self._project_dir = Path(project_dir)
        self._image: Optional[QImage] = None
        self.saved_path: Optional[Path] = None

        self.setWindowTitle(i18n.t("attachTitle"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        self._preview = QLabel(i18n.t("attachEmpty"))
        self._preview.setProperty("class", "phead-sub")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumSize(420, 240)
        self._preview.setWordWrap(True)
        layout.addWidget(self._preview)

        self._caption = QLineEdit()
        self._caption.setPlaceholderText(i18n.t("attachCaption"))
        layout.addWidget(self._caption)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        QShortcut(QKeySequence.StandardKey.Paste, self, self.take_from_clipboard)
        self.take_from_clipboard()

    def take_from_clipboard(self) -> bool:
        image = clipboard_image()
        if image is None:
            self._set_ok_enabled(False)
            return False
        self._image = image
        preview = QPixmap.fromImage(scaled(image, 520))
        self._preview.setPixmap(preview)
        self._set_ok_enabled(True)
        return True

    def _set_ok_enabled(self, enabled: bool) -> None:
        button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if button is not None:
            button.setEnabled(enabled)

    def caption(self) -> str:
        return self._caption.text().strip()

    def accept(self) -> None:  # noqa: D102 — Qt's own vocabulary
        if self._image is None:
            return  # nothing pasted: the button is disabled, this is the keyboard route
        self.saved_path = save(self._image, self.caption(), self._project_dir)
        super().accept()

    def line(self) -> str:
        """The composer line for what was saved, or "" if nothing was."""
        if self.saved_path is None:
            return ""
        return message_line(self.saved_path, self.caption(), self._project_dir)
