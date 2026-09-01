"""What both conversation surfaces show and take: Markdown as Qt rich text, and the box you type in.

There are two windows in TCC where a model talks to the tuner — the main dialog panel, and the
DSP-profile onboarding interview that runs while the project is still being created. They are two
windows for a reason (the interview has no project to be a panel of yet), but they were also two
IMPLEMENTATIONS, and the second one was 184 lines against 1413: it printed the model's Markdown
raw, glued the answer options of a multiple-choice question into one paragraph, and took answers
through a single-line field (`SKL-008`, from a Windows run on 2026-09-01, with the screenshot).

So the parts that decide what a conversation LOOKS like live here, and both windows import them.
Whatever is fixed in a rendering rule is fixed in both from the day it is fixed.
"""

from __future__ import annotations

import html
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPlainTextEdit


def markdown(text: str) -> str:
    """The little of Markdown a tuning answer actually uses, as Qt rich text.

    Models write `**bold**`, `### headings`, `- lists` and `` `code` `` whether or not anyone asked
    them to, and a bubble that shows the asterisks makes a correct answer look like a broken one.
    Not a full parser on purpose: this renders what turns up in practice and escapes everything
    else, so a stray `<` in a filter string can never become markup.
    """
    out = html.escape(text)
    # Leading spaces are how a pasted list shows its nesting, and HTML collapses runs of them.
    out = re.sub(r"^ +", lambda m: "&nbsp;" * len(m.group()), out, flags=re.MULTILINE)
    out = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", out)
    lines = []
    rows: list[list[str]] = []

    def flush_table() -> None:
        """Turn the pipe rows collected so far into a real table, or print them if they are not
        one. Models answer equipment questions with a Markdown table -- "| Code | Role | Driver |"
        -- and without this the transcript showed the pipes and dashes raw, which is a correct
        answer looking like a broken one."""
        if not rows:
            return
        body = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]
        if len(body) >= 1 and len(rows) >= 2:
            head, *rest = body
            cells = "".join(f"<th align='left'>{c}</th>" for c in head)
            html = [f"<tr>{cells}</tr>"]
            for row in rest:
                html.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
            lines.append("<table cellpadding='4' cellspacing='0'>" + "".join(html) + "</table>")
        else:
            lines.extend("|".join(r) for r in rows)
        rows.clear()

    for line in out.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2:
            rows.append([c.strip() for c in stripped.strip("|").split("|")])
            continue
        flush_table()
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            lines.append(f"<b>{heading.group(2)}</b>")
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet:
            lines.append(f"&nbsp;&nbsp;• {bullet.group(1)}")
            continue
        numbered = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
        if numbered:
            lines.append(f"&nbsp;&nbsp;{numbered.group(1)}. {numbered.group(2)}")
            continue
        lines.append(line)
    flush_table()
    # A table is a block, not a line: joining with <br> would put a blank row under it.
    return "<br>".join(lines).replace("<br><table", "<table").replace("</table><br>", "</table>")


class ComposerInput(QPlainTextEdit):
    """The message box. Multi-line, because what gets typed here is often pasted.

    It was a `QLineEdit`, which silently flattens a paste: an equipment list arrived as one
    run-on paragraph and the structure the model needed to read it was gone (reported with the
    before/after, 2026-08-05). Enter sends and Shift+Enter breaks a line, which is what a chat
    box does; the field grows with the text up to a few lines and then scrolls, so a long paste
    does not push the transcript off screen.
    """

    submitted = Signal()

    _MAX_LINES = 6

    def __init__(self) -> None:
        super().__init__()
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setTabChangesFocus(True)
        self.document().contentsChanged.connect(self._fit_height)
        # AND the layout's own signal, which is the one that catches a paste. `contentsChanged`
        # fires the moment the text lands, before the document has been wrapped: text with real
        # newlines already has its block count by then and grew correctly, while one long pasted
        # paragraph still measured as a single line and the field stayed one line tall (user,
        # 2026-08-21 -- reproduced offscreen at 6 wrapped lines against an unchanged 29px). The
        # wrap is computed a layout pass later, and this is the signal that says so.
        self.document().documentLayout().documentSizeChanged.connect(self._on_document_resized)
        self._fit_height()

    # `QLineEdit`'s vocabulary, so call sites read the same as before.
    def text(self) -> str:
        return self.toPlainText()

    def setText(self, value: str) -> None:  # noqa: N802 (Qt naming)
        self.setPlainText(value)

    def _on_document_resized(self, _size) -> None:
        self._fit_height()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # A narrower box wraps the same text into more lines. Without this the field kept the
        # height it was given at the width it no longer has.
        super().resizeEvent(event)
        self._fit_height()

    def _fit_height(self) -> None:
        line = self.fontMetrics().lineSpacing()
        lines = min(max(int(self.document().size().height()), 1), self._MAX_LINES)
        height = int(line * lines + 14)
        # Only when it actually changes: `setFixedHeight` resizes the widget, `resizeEvent` calls
        # back here, and a call that always sets would be that loop running forever.
        if height != self.height():
            self.setFixedHeight(height)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if enter and not event.modifiers() & (Qt.KeyboardModifier.ShiftModifier
                                              | Qt.KeyboardModifier.KeypadModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(event)
