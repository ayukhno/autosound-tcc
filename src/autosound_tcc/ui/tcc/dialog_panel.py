"""The center AI-dialog panel — ported from the prototype's `renderDialog` + the project-param-
edit flag chip (`data/private/prototype/tcc-main.html`): message bubbles (Generator/Critic/
Arbiter/system), a composer, and the "✎ Project param edit" chip + reason picker that flags the
dialog as being about a ledger correction rather than routine tuning.

Two modes, one widget. With no agent attached it renders the mock `DIALOG` exactly as before —
that is what the design was built against and what most tests exercise. Call `attach_agent()` and
it becomes the live surface: streamed Generator text, tool calls as process chips, the Arbiter's
confirmation bar, and a composer wired to a real session.

Signals *out* of the panel go through the MCP signal bus rather than straight to the session, so
they reach whichever front-end is driving — the in-app agent or the user's own CLI in a terminal.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QSize, QTimer, Qt, Signal
from PySide6.QtGui import QIcon, QTextDocumentFragment
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import signal_bus
from autosound_tcc.core.agent_events import (
    Notice,
    Question,
    QuestionWithdrawn,
    TextDelta,
    ToolCall,
    ToolEnd,
)
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.app_settings import get_settings
from autosound_tcc.ui.tcc import copy_menu
from autosound_tcc.ui.tcc.confirm_bar import ConfirmBar
from autosound_tcc.ui.tcc.mock_data import DIALOG, CURRENT_GENERATOR_MODEL, DialogMessage
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.theme import apply_caps

# Same Lucide set the measurement panel uses (NOTICE.md).
_ICONS_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"

# .msg-body's base font-size in theme.py -- kept in sync with that QSS literal so the dialog's own
# A-/A+ control (below) scales from the same starting point.
# Who a system bubble is from. The ledger records what happened to the project; TCC's own lines
# about the harness are not that, and labelling them the same made a status read as a record.
_SYS_ROLE_TCC = "SYSTEM · TCC"
_MSG_BODY_BASE_PX = 13.0
_DIALOG_FONT_KEY = "ui/dialog_font_scale"
_DIALOG_FONT_MIN, _DIALOG_FONT_MAX, _DIALOG_FONT_STEP = 0.8, 1.6, 0.1


def _markdown(text: str) -> str:
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
        self._fit_height()

    # `QLineEdit`'s vocabulary, so call sites read the same as before.
    def text(self) -> str:
        return self.toPlainText()

    def setText(self, value: str) -> None:  # noqa: N802 (Qt naming)
        self.setPlainText(value)

    def _fit_height(self) -> None:
        line = self.fontMetrics().lineSpacing()
        lines = min(max(int(self.document().size().height()), 1), self._MAX_LINES)
        self.setFixedHeight(int(line * lines + 14))

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if enter and not event.modifiers() & (Qt.KeyboardModifier.ShiftModifier
                                              | Qt.KeyboardModifier.KeypadModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class MessageBubble(QFrame):
    def __init__(self, who: str, role: str, html: str) -> None:
        super().__init__()
        self.setProperty("class", f"msg msg-{who}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 8)
        layout.setSpacing(3)
        who_label = QLabel(role)
        who_label.setProperty("class", f"msg-who msg-who-{who}")
        layout.addWidget(who_label)
        self._body = QLabel(html)
        self._body.setTextFormat(Qt.TextFormat.RichText)
        self._body.setWordWrap(True)
        self._body.setProperty("class", "msg-body")
        # Selectable here and nowhere in the panels: a selectable QLabel captures mouse events, and
        # a bubble has nothing under it to capture them from. On a channel row it would eat the
        # click that opens the detail pane.
        self._body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._body)
        self._html = html
        # Width the bubble would want if its text sat on one line -- lets the panel size each
        # bubble to its content (dynamic, like the web) up to the max-width cap, instead of every
        # bubble being forced to the same width.
        self._who_label = who_label
        self._role = role
        self._plain = re.sub(r"<[^>]+>", "", html)
        copy_menu.enable_copy(
            self,
            # Selection first: it is the more specific of the two, and it only appears when there
            # is one — right-clicking a bubble you have not selected in offers just the message.
            extra=[("copySelection", self._body.selectedText),
                   ("copyMessage", self.plain_text)],
            hint="",  # a bubble has no tooltip, and its own text is not a hint about itself
        )

    def plain_text(self) -> str:
        """The message as text a person can paste — not the markup, and not `_plain`.

        `_plain` is a tag strip kept for width measurement, where the whole message on one line is
        the point. It is the wrong thing to put on a clipboard twice over: `&amp;` and `&nbsp;`
        survive it verbatim, and `<br>` between two paragraphs comes out as a missing space.
        Qt's own converter answers both, and it is the same engine that rendered the bubble.
        """
        return QTextDocumentFragment.fromHtml(self._html).toPlainText().strip()

    @property
    def natural_width(self) -> int:
        """Width this bubble would want on one line, measured with the fonts it *currently* has.

        Computed on demand rather than stored at construction: the stylesheet has not been applied
        yet when a widget is built, so `.msg-who`'s `letter-spacing: 1px` was missing from the
        measurement and the role line came out ~13px short -- "ARBITER · YOU" rendered with the U
        cut off. Measuring later, and again after a font-scale change, costs one text advance.
        """
        # The role line is measured with an allowance for `.msg-who`'s `letter-spacing: 1px`,
        # which Qt renders but does not report through `fontMetrics()` -- so the measurement came
        # out about one pixel per character short and "ARBITER · YOU" lost its U to the border.
        role_width = self._who_label.fontMetrics().horizontalAdvance(self._role) + len(self._role)
        return max(self._body.fontMetrics().horizontalAdvance(self._plain), role_width) + 28

    def set_html(self, html: str) -> None:
        """Replace the body text — used while a streamed answer is still growing."""
        self._body.setText(html)
        self._plain = re.sub(r"<[^>]+>", "", html)
        # Copy reads this, and a streamed answer replaces its body on every delta: without this
        # line the clipboard would hand back the first chunk of a finished message.
        self._html = html

    def apply_font_scale(self, scale: float) -> None:
        # A widget's own stylesheet wins over the app-wide one for the same selector, so this
        # overrides .msg-body's QSS without fighting the global A-/A+ zoom's stylesheet regex
        # (theme.py::_scale_font_sizes), which only ever touches the app-wide stylesheet string.
        self._body.setStyleSheet(f"QLabel {{ font-size: {_MSG_BODY_BASE_PX * scale:.1f}px; }}")


class DialogPanel(QWidget):
    """The whole center dialog: message list, composer, and the project-param-edit chip. The
    surrounding `.panel` frame's "editing" border highlight is applied by the caller
    (main_window.py) via `editingChanged`, same split as the measurement card's yellow border.
    """

    editingChanged = Signal(bool)
    # A turn ended. The window reconciles the plan against the disk here rather than only on the
    # file watcher: a turn that wrote nothing fires no watcher, and "the model talked and recorded
    # nothing" is exactly what the supervisor is for.
    turnFinished = Signal()
    # (question, answer) -- the Arbiter ruled on something. The window writes it to the journal
    # (SCR-030); the panel does not touch disk itself.
    arbiterAnswered = Signal(str, str)
    # Typing into the composer with no session running is a request to start one -- see `_on_send`.
    startRequested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._editing = False
        self._reason: str | None = None
        self._bubbles: list[MessageBubble] = []
        self._settings = get_settings()
        self._font_scale = float(self._settings.value(_DIALOG_FONT_KEY, 1.0))
        # Live-agent state. All None/False until attach_agent() is called, which is what keeps the
        # mock rendering path byte-identical for the design and for existing tests.
        self._worker: Optional[Any] = None
        self._bus: Optional[signal_bus.SignalBus] = None
        self._live_bubble: Optional[MessageBubble] = None
        self._live_text = ""
        # The run of identical tool calls currently on the activity line -- see `_add_chip`.
        self._chip_tool = ""
        self._chip_count = 0
        self._activity_label = ""
        # The question the turn is currently parked on, and the option buttons offering it.
        self._pending_question: Optional[str] = None
        self._question_widgets: Optional[QWidget] = None
        # Typed while the agent was mid-turn, waiting for a turn boundary to be sent. The field is
        # never switched off, so a thought that arrives while the model is working is not lost to
        # a disabled widget -- see `_on_send`.
        self._queued: list[str] = []
        self._busy = False
        # Whatever is actually answering. The mock transcript's Claude label was still on live
        # bubbles produced by a Gemini model, which is a caption that contradicts the footer.
        self._model_label = CURRENT_GENERATOR_MODEL

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QWidget()
        head.setProperty("class", "phead")
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(12, 8, 12, 8)
        head_layout.setSpacing(8)
        self._title_label = QLabel(i18n.t("dialog"))
        self._title_label.setProperty("class", "phead-title")
        apply_caps(self._title_label, spacing_px=1.4)
        head_layout.addWidget(self._title_label)
        self._sub_label = QLabel(i18n.t("dialogSub"))
        self._sub_label.setProperty("class", "phead-sub")
        head_layout.addWidget(self._sub_label)

        # Which AI session this conversation is: phase, and whether it was resumed or started
        # fresh. Blank until an agent is attached -- see `set_session_label`.
        self._session_chip = QLabel("")
        self._session_chip.setProperty("class", "pill")
        self._session_chip.setHidden(True)
        head_layout.addWidget(self._session_chip)

        head_layout.addStretch(1)

        # Dialog-only font-size control, independent of the header's app-wide A-/A+ zoom -- reuses
        # that control's QSS classes so it reads as consistent, but only ever touches bubble text
        # (MessageBubble.apply_font_scale), never the rest of the app's stylesheet.
        font_group = QFrame()
        font_group.setProperty("class", "zoomgroup")
        fg_layout = QHBoxLayout(font_group)
        fg_layout.setContentsMargins(0, 0, 0, 0)
        fg_layout.setSpacing(0)
        font_out = QPushButton("A−")
        font_out.setProperty("class", "zoomgroup-btn")
        font_out.setCursor(Qt.CursorShape.PointingHandCursor)
        font_out.clicked.connect(self._font_out)
        fg_layout.addWidget(font_out)
        div = QFrame()
        div.setProperty("class", "zoomgroup-div")
        div.setFixedWidth(1)
        fg_layout.addWidget(div)
        self._font_label = QLabel(f"{round(self._font_scale * 100)}%")
        self._font_label.setProperty("class", "zoomgroup-label")
        self._font_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fg_layout.addWidget(self._font_label)
        div2 = QFrame()
        div2.setProperty("class", "zoomgroup-div")
        div2.setFixedWidth(1)
        fg_layout.addWidget(div2)
        font_in = QPushButton("A+")
        font_in.setProperty("class", "zoomgroup-btn")
        font_in.setCursor(Qt.CursorShape.PointingHandCursor)
        font_in.clicked.connect(self._font_in)
        fg_layout.addWidget(font_in)
        head_layout.addWidget(font_group)

        # "I don't see this in the UI" — the Arbiter's way of telling the agent that something it
        # claimed to have changed did not land. Raises a `not_visible` signal, which the skill is
        # instructed to treat as "re-verify against disk", not "restate the claim".
        self._not_visible_btn = QPushButton("👁 " + i18n.t("notVisible"))
        self._not_visible_btn.setProperty("class", "edit-chip")
        self._not_visible_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._not_visible_btn.setToolTip(i18n.t("notVisibleHint"))
        self._not_visible_btn.clicked.connect(self._on_not_visible)
        self._not_visible_btn.setHidden(True)  # pointless without an agent listening
        head_layout.addWidget(self._not_visible_btn)

        self._edit_chip = QPushButton("✎ " + i18n.t("editChipLabel"))
        self._edit_chip.setProperty("class", "edit-chip")
        self._edit_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_chip.clicked.connect(self._on_chip_clicked)
        head_layout.addWidget(self._edit_chip)
        outer.addWidget(head)

        self._reasons_bar = QWidget()
        self._reasons_bar.setProperty("class", "edit-reasons")
        reasons_layout = QHBoxLayout(self._reasons_bar)
        reasons_layout.setContentsMargins(12, 8, 12, 8)
        reasons_layout.setSpacing(8)
        self._reasons_q_label = QLabel(i18n.t("editReasonsQ"))
        reasons_layout.addWidget(self._reasons_q_label)
        self._reason_btns: dict[str, QPushButton] = {}
        for reason_key, label_key in (("forgot", "reasonForgot"), ("manual", "reasonManual")):
            btn = QPushButton(i18n.t(label_key))
            btn.setProperty("class", "reason-btn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, r=reason_key: self._start_editing(r))
            reasons_layout.addWidget(btn)
            self._reason_btns[reason_key] = btn
        reasons_layout.addStretch(1)
        self._reasons_bar.setHidden(True)
        outer.addWidget(self._reasons_bar)

        # The Arbiter's gate. Sits directly above the transcript so the thing being approved is
        # next to the reasoning that led to it.
        self.confirm_bar = ConfirmBar()
        self.confirm_bar.resolved.connect(self._on_confirmation_resolved)
        outer.addWidget(self.confirm_bar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._chat = QWidget()
        self._chat_layout = QVBoxLayout(self._chat)
        self._chat_layout.setContentsMargins(14, 12, 14, 12)
        self._chat_layout.setSpacing(8)
        # Trailing stretch must exist BEFORE the bubbles are added: _add_bubble inserts each row at
        # count()-1 (just before the stretch), so without it the -1 index folds messages back to
        # the front and scrambles their order (the dialog rendered crit→user→gen→gen otherwise).
        self._chat_layout.addStretch(1)
        for message in DIALOG:
            self._add_bubble(message.who, message.role, i18n.tx(message.text))
        self._scroll.setWidget(self._chat)
        # Stick to the bottom, the way a chat window does, instead of scrolling once and hoping.
        # A bubble's height settles over several layout passes -- the label wraps, the font scale
        # applies, the rich text re-flows -- so a single scroll lands at whatever the height was
        # one pass ago. A long message ended up with only its top edge on screen; a short one was
        # fine, which is exactly the shape of "scrolled too early".
        self._stick_to_bottom = True
        bar = self._scroll.verticalScrollBar()
        bar.rangeChanged.connect(self._on_scroll_range_changed)
        bar.valueChanged.connect(self._on_scroll_value_changed)
        outer.addWidget(self._scroll, stretch=1)

        # Tool calls live here, not in the transcript. Their whole value is "the thing is still
        # working" -- one line of that is worth as much as eight rows of it, and eight rows was
        # most of a screen. The process record is `process/journal.jsonl`; this is a pulse.
        self._activity = QLabel("")
        self._activity.setProperty("class", "activity")
        self._activity.setHidden(True)
        outer.addWidget(self._activity)
        # The dots are the point: a static line says "a tool ran", a moving one says "it is still
        # running", and telling those apart is the only reason this line exists.
        self._activity_phase = 0
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(450)
        self._activity_timer.timeout.connect(self._tick_activity)

        # What is waiting to be sent, and the way out of waiting. Not a transcript entry: a queued
        # message was first announced as a SYSTEM · ledger bubble, which reads as something that
        # happened rather than something that is still pending -- and it said "it goes out when
        # this turn ends" under a turn that had produced nothing for two minutes, which is a
        # promise the panel cannot keep on its own. So it lives here, stays until it is kept, and
        # carries the button that keeps it.
        self._queue_row = QWidget()
        self._queue_row.setHidden(True)
        queue_layout = QHBoxLayout(self._queue_row)
        queue_layout.setContentsMargins(12, 0, 12, 0)
        queue_layout.setSpacing(8)
        self._queue_label = QLabel("")
        self._queue_label.setProperty("class", "activity")
        queue_layout.addWidget(self._queue_label)
        self._queue_now_btn = QPushButton(i18n.t("queueSendNow"))
        self._queue_now_btn.setProperty("class", "reason-btn")
        self._queue_now_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._queue_now_btn.clicked.connect(self._on_send_queued_now)
        queue_layout.addWidget(self._queue_now_btn)
        queue_layout.addStretch(1)
        outer.addWidget(self._queue_row)

        composer = QWidget()
        composer.setProperty("class", "composer")
        self._composer = composer
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(9, 9, 9, 9)
        composer_layout.setSpacing(8)
        self._input = ComposerInput()
        self._input.setPlaceholderText(i18n.t("composer"))
        self._input.setProperty("class", "composer-input")
        composer_layout.addWidget(self._input, stretch=1)
        # A screenshot goes to the model as a FILE in the project, not as an inline image — see
        # `attach_image.py` for why (three front-ends, only one of which could carry one; and a
        # capture of a REW window is evidence that should outlive the conversation).
        self._attach_btn = QPushButton()
        self._attach_btn.setIcon(QIcon(str(_ICONS_DIR / "image.svg")))
        self._attach_btn.setIconSize(QSize(16, 16))
        self._attach_btn.setProperty("class", "reason-btn")
        self._attach_btn.setFixedWidth(30)
        self._attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._attach_tip = attach_tip(self._attach_btn, i18n.t("attachTip"))
        self._attach_btn.clicked.connect(self._on_attach_image)
        composer_layout.addWidget(self._attach_btn)

        self._send_btn = QPushButton(i18n.t("send"))
        self._send_btn.setProperty("class", "composer-send")
        self._send_btn.clicked.connect(self._on_send)
        self._input.submitted.connect(self._on_send)
        composer_layout.addWidget(self._send_btn)

        # Only meaningful while a turn is running, so it appears beside Send rather than being
        # there greyed out. Send stays: while the turn runs it queues instead of sending, which is
        # still the button you press.
        self._stop_btn = QPushButton(i18n.t("stop"))
        self._stop_btn.setProperty("class", "reason-btn")
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.clicked.connect(self._on_stop)
        self._stop_btn.setHidden(True)
        composer_layout.addWidget(self._stop_btn)
        outer.addWidget(composer)

    def _on_attach_image(self) -> None:
        """Paste a screenshot; TCC saves it in the project and writes the path into the composer.

        The path is appended to whatever is already typed rather than replacing it: the sentence
        that says WHY the picture matters is usually already half-written when the Arbiter reaches
        for this button.
        """
        from autosound_tcc.core import config
        from autosound_tcc.ui.tcc.attach_image import AttachImageDialog

        dialog = AttachImageDialog(config.project_dir(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        line = dialog.line()
        if not line:
            return
        existing = self._input.text().rstrip()
        self._input.setText(f"{existing}\n{line}" if existing else line)
        self._input.setFocus()

    def retranslate(self) -> None:
        """Re-set the panel's own *chrome* (title, chip, composer) into the new UI language.

        The message bubbles are deliberately NOT re-translated: a dialog turn is live model /
        user output, produced in one language, not a UI string. Flipping the interface language
        must leave the actual conversation exactly as it happened (user feedback 2026-07-26)."""
        self._title_label.setText(i18n.t("dialog"))
        self._attach_tip.set_text(i18n.t("attachTip"))
        self._sub_label.setText(i18n.t("dialogSub"))
        self._reasons_q_label.setText(i18n.t("editReasonsQ"))
        self._reason_btns["forgot"].setText(i18n.t("reasonForgot"))
        self._reason_btns["manual"].setText(i18n.t("reasonManual"))
        self._refresh_placeholder()
        self._queue_now_btn.setText(i18n.t("queueSendNow"))
        self._show_queue_row()
        self._send_btn.setText(i18n.t("send"))
        self._stop_btn.setText(i18n.t("stop"))
        self._not_visible_btn.setText("👁 " + i18n.t("notVisible"))
        self._not_visible_btn.setToolTip(i18n.t("notVisibleHint"))
        if self._editing and self._reason:
            label = i18n.t("reasonForgot" if self._reason == "forgot" else "reasonManual")
            self._edit_chip.setText(f"✎ {label} ✕")
        else:
            self._edit_chip.setText("✎ " + i18n.t("editChipLabel"))

    def _bubble_max_width(self) -> int:
        width = self._chat.width()
        return int(width * 0.9) if width > 0 else 600

    def _fit(self, bubble: MessageBubble) -> None:
        """Size a bubble to its content up to the max-width cap: short messages hug their text,
        long ones wrap at the cap. A fixed width is needed because a wrapped QLabel's own sizeHint
        collapses far narrower than the space available."""
        bubble.setFixedWidth(min(bubble.natural_width, self._bubble_max_width()))

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        # Bubble widths are computed from the panel width, which is Qt's un-shown default until the
        # panel is actually laid out -- refit on every resize so they track the real width.
        for bubble in self._bubbles:
            self._fit(bubble)

    def _add_bubble(self, who: str, role: str, html: str) -> None:
        bubble_row = QHBoxLayout()
        bubble = MessageBubble(who, role, html)
        bubble.apply_font_scale(self._font_scale)
        self._bubbles.append(bubble)
        self._fit(bubble)
        if who == "user":
            bubble_row.addStretch(1)  # right-aligned
            bubble_row.addWidget(bubble)
        else:
            # Generator / Critic / system(ledger): left-aligned. System messages used to be
            # centered, which read as them "jumping to the middle" during a param-edit flow.
            bubble_row.addWidget(bubble)
            bubble_row.addStretch(1)
        self._chat_layout.insertLayout(self._chat_layout.count() - 1, bubble_row)

    # ---- dialog-only font size ---------------------------------------------

    def _set_font_scale(self, scale: float) -> None:
        self._font_scale = round(min(_DIALOG_FONT_MAX, max(_DIALOG_FONT_MIN, scale)), 2)
        self._settings.setValue(_DIALOG_FONT_KEY, self._font_scale)
        self._font_label.setText(f"{round(self._font_scale * 100)}%")
        for bubble in self._bubbles:
            bubble.apply_font_scale(self._font_scale)

    def _font_out(self) -> None:
        self._set_font_scale(self._font_scale - _DIALOG_FONT_STEP)

    def _font_in(self) -> None:
        self._set_font_scale(self._font_scale + _DIALOG_FONT_STEP)

    def _add_system_message(self, html: str, role: str = "SYSTEM · ledger") -> None:
        """A line from TCC rather than from anyone in the conversation.

        `role` because not all of them are ledger events: "omp has said nothing" and "starting
        <model>" are TCC talking about the machinery, and filing those under the ledger makes a
        status line look like something that was recorded.
        """
        self._add_bubble("sys", role, html)
        self._scroll_to_end()

    def _scroll_to_end(self) -> None:
        # Guarded because the callers can be reached from a *queued* signal: the MCP server thread
        # emits a critique or a proposal, Qt defers the slot to the GUI thread, and by the time it
        # runs the panel may already be torn down (window closed mid-call). Touching a widget
        # whose C++ side is gone is the same class of fault as deleting a widget from inside its
        # own event handler -- see feedback_qt_qss_gotchas. Nothing to scroll is not an error.
        # A deferred call was not enough either: a bubble's height settles after its label wraps
        # and its `_fit` runs, which can be a second layout pass later, so `maximum()` was still
        # short. Arm the scrollbar's own `rangeChanged` instead -- it fires exactly when the thing
        # we are waiting for happens -- and disarm after one shot so scrolling back stays sticky.
        self._stick_to_bottom = True
        QTimer.singleShot(0, self._scroll_now)
        self._scroll_now()

    def _on_scroll_range_changed(self, _min: int, _max: int) -> None:
        if getattr(self, "_stick_to_bottom", True):
            self._scroll_now()

    def _on_scroll_value_changed(self, value: int) -> None:
        """Scrolling up by hand means "I am reading something", and the panel stops chasing.

        Coming back to the bottom re-arms it. The tolerance is a few pixels because a wheel notch
        rarely lands exactly on the maximum.
        """
        try:
            bar = self._scroll.verticalScrollBar()
        except (AttributeError, RuntimeError):
            return
        self._stick_to_bottom = value >= bar.maximum() - 8

    def _scroll_now(self) -> None:
        try:
            bar = self._scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
        except (AttributeError, RuntimeError):
            # The guard has to cover the *use*, not just the lookup: `self._scroll` still resolves
            # after teardown and hands back a wrapper whose C++ side is gone, so the failure lands
            # on setValue rather than on the attribute.
            return

    def set_composer_visible(self, visible: bool) -> None:
        """Hide the composer in `view` mode (TCC-TZ.md §8: "no AI at all") -- `_on_send` already
        no-ops with no worker attached, so this is about not showing a live-looking input box
        that quietly goes nowhere, not about preventing a send that couldn't happen anyway."""
        self._composer.setVisible(visible)

    def clear_mock(self) -> None:
        """Drop the demo transcript. Safe to call whenever; a no-op once a session is attached.

        The mock exists for the design surface, and it is invented tuning advice -- "PK 1120 -2.5
        Q2.2", a Critic verdict, an Arbiter reply. Sitting in a window that has a real project open
        it is indistinguishable from history, and acting on a number nobody measured is the one
        failure this whole application is built to prevent. So it survives exactly as long as there
        is nothing real to be confused with.
        """
        self.clear_for_no_project()

    def clear_for_no_project(self) -> None:
        """Drop the mock transcript when MainWindow finds no real project on disk -- a folder
        with nothing real in it should never look like a live tuning conversation is underway.

        Never while a session is attached. This runs whenever the project is re-read, and a live
        session re-reads it constantly -- `enter_phase` writes to disk, the bridge asks the window
        to reload, and a project whose profile does not exist yet takes the "no project" branch.
        Wiping a running conversation there is wrong twice over: the transcript is real, and the
        deleted bubbles left `_live_bubble` pointing at a destroyed C++ object, so the next
        streamed chunk raised inside the slot and the turn froze mid-answer. Reported as "it wrote
        the text and everything hangs, Stop does not help".
        """
        if self._worker is not None:
            return
        self._clear_bubbles()

    # ---- live agent --------------------------------------------------------

    def attach_agent(
        self,
        worker: Any,
        bus: signal_bus.SignalBus,
        resumed: bool = False,
        phase: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        """Switch the panel from the mock transcript to a live session.

        The mock bubbles are cleared rather than kept: leaving demo content above real output is
        how a tuner ends up acting on a number that was never measured.
        """
        self._worker = worker
        self._bus = bus
        self._model_label = model or i18n.t("generator")
        self._clear_bubbles()
        self._not_visible_btn.setHidden(False)
        self._refresh_placeholder()
        self.set_session_label(resumed=resumed, phase=phase)

        worker.chunk.connect(self._on_chunk)
        worker.turn_done.connect(self._on_turn_done)
        worker.failed.connect(self._on_failed)
        self._set_busy(True)
        # The first turn is slow -- the model reads the skill and the project's state before it
        # says anything, and omp additionally waits for its own tools to come up. Without a line
        # here, a session that is working looks exactly like one that did nothing.
        if model:
            self._add_system_message(i18n.t("sessionStarting").format(model=model),
                                     role=_SYS_ROLE_TCC)

    def set_idle_label(self, model: Optional[str]) -> None:
        """Say what will run and that it has not started, before anyone clicks anything.

        Starting a session costs a turn -- roughly 30-40k input tokens of the model reading the
        skill and the project's state -- so TCC never starts one on its own. That is only a
        defensible default if "chosen but not running" is visible rather than inferred, which is
        what this chip is for.
        """
        self._session_chip.setText(
            i18n.t("dialogIdle").format(model=model) if model else i18n.t("dialogNoModel")
        )
        self._session_chip.setHidden(False)

    def set_session_label(self, resumed: bool, phase: Optional[str]) -> None:
        state = i18n.t("sessionResumed") if resumed else i18n.t("sessionNew")
        label = f"{phase} · {state}" if phase else state
        self._session_chip.setText(label)
        self._session_chip.setHidden(False)

    def _clear_bubbles(self) -> None:
        """Drop every bubble, keeping the trailing stretch `_add_bubble`'s insert index needs.

        Rows are nested layouts, and an earlier version called `deleteLater()` on those. That is
        the same `setParent(None)`+`deleteLater()` pattern used for widgets elsewhere, but a
        *layout* deleted that way is disposed of on a later event-loop pass while its widgets are
        already gone — which left this panel's own scroll area with stale children and made
        `verticalScrollBar()` hand back a dead wrapper (intermittent, only once other tests spun
        an event loop). Widgets get the established treatment; the emptied layout is simply
        dropped and collected, with nothing queued.
        """
        # Anything pointing into the bubbles goes with them -- a dangling reference to a deleted
        # widget is a crash in whichever slot touches it next, not a visual glitch.
        self._live_bubble = None
        self._live_text = ""
        if self._question_widgets is not None:
            self._question_widgets.setParent(None)
            self._question_widgets.deleteLater()
            self._question_widgets = None
        for bubble in self._bubbles:
            bubble.setParent(None)
            bubble.deleteLater()
        self._bubbles.clear()
        self._live_bubble = None
        self._live_text = ""
        while self._chat_layout.count() > 1:
            item = self._chat_layout.takeAt(0)
            row = item.layout()
            if row is not None:
                while row.count():
                    child = row.takeAt(0)
                    widget = child.widget()
                    if widget is not None:
                        widget.setParent(None)
                        widget.deleteLater()

    def _set_busy(self, busy: bool) -> None:
        # The field is never switched off. A turn is minutes long and the agent asks for things in
        # prose as often as it asks through `ask` -- "share your preferences and system details"
        # arrives as a paragraph, not a question frame -- so a composer that greys out for the
        # length of the turn is off exactly when there is something to say. Typing is always
        # allowed; `_on_send` decides whether it goes now or at the turn boundary.
        self._busy = busy
        self._input.setEnabled(True)
        self._stop_btn.setHidden(not busy)
        self._refresh_placeholder()
        if self._pending_question is None:
            self._sub_label.setText(i18n.t("agentThinking") if busy else i18n.t("dialogSub"))

    def _refresh_placeholder(self) -> None:
        """What the field is for right now: answering a parked question, queueing, or talking."""
        if self._pending_question is not None:
            self._input.setPlaceholderText(i18n.t("composerAnswer"))
        elif self._busy:
            self._input.setPlaceholderText(i18n.t("composerQueue"))
        else:
            self._input.setPlaceholderText(i18n.t("composer"))

    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        if self._pending_question is not None:
            # The turn is parked on a question; typing is the "Other (type your own)" answer both
            # harnesses offer, not a new message queued behind a session that cannot read it.
            self._input.clear()
            self._answer_question(text)
            return
        if self._worker is None:
            # A live composer that swallows what you type is worse than a disabled one. Sending
            # the first message IS the explicit start, and the text becomes the opening prompt
            # rather than being thrown away in favour of a canned one.
            self._add_bubble("user", "Arbiter · you", _markdown(text))
            self._input.clear()
            self._set_busy(True)
            self.startRequested.emit(text)
            return
        self._add_bubble("user", "Arbiter · you", _markdown(text))
        self._input.clear()
        if self._busy:
            # Mid-turn. The harness takes one prompt at a time, so this waits for the boundary
            # instead of being refused -- and it says so in a row that stays up until it is sent,
            # because a message that sits there silently is the same complaint as a field that
            # will not take one.
            self._queued.append(text)
            self._show_queue_row()
            self._scroll_to_end()
            return
        self._scroll_to_end()
        self._set_busy(True)
        self._worker.send(text)

    def _on_stop(self) -> None:
        """Interrupt the running turn. The worker owns the session, so ask it, don't reach in.

        A parked question is interrupted by withdrawing the question: the harness is blocked
        inside `ask` and `abort` does not reach it, so Stop did nothing at all -- reported that
        way. Answering "cancelled" is what unblocks it.
        """
        if self._pending_question is not None:
            question_id, self._pending_question = self._pending_question, None
            if self._question_widgets is not None:
                self._question_widgets.setParent(None)
                self._question_widgets.deleteLater()
                self._question_widgets = None
            self._refresh_placeholder()
            self._add_system_message(i18n.t("questionCancelled"))
            if self._worker is not None and hasattr(self._worker, "cancel_question"):
                self._worker.cancel_question(question_id)
            return
        if self._worker is not None and hasattr(self._worker, "interrupt"):
            self._worker.interrupt()

    def _on_chunk(self, item: Any) -> None:
        """Render one event from the session.

        The panel speaks `core.agent_events` and nothing else: which harness produced the turn --
        the Agent SDK for Claude, omp for everything else -- is not visible from here, and adding
        a harness must not mean touching this method.
        """
        if isinstance(item, TextDelta):
            self._append_live_text(item.text)
        elif isinstance(item, ToolCall):
            self._add_chip(item.name)
        elif isinstance(item, ToolEnd):
            self._end_chip()
        elif isinstance(item, Question):
            self._add_question(item)
        elif isinstance(item, QuestionWithdrawn):
            self._withdraw_question(item.id)
        elif isinstance(item, Notice):
            # The adapter talking about the harness. Under the model's byline it read as the model
            # saying "omp has said nothing", which is a sentence no model would write.
            self._live_bubble = None
            self._live_text = ""
            self._add_system_message(f"⚠️ {item.text}", role=_SYS_ROLE_TCC)

    def _append_live_text(self, text: str) -> None:
        if not text:
            return
        self._live_text += text
        if self._live_bubble is None:
            self._add_bubble("gen", f"Generator · {self._model_label}", _markdown(self._live_text))
            self._live_bubble = self._bubbles[-1]
        else:
            self._live_bubble.set_html(_markdown(self._live_text))
            self._fit(self._live_bubble)
        self._scroll_to_end()

    def _add_question(self, question: Question) -> None:
        """A structured question from the agent. The turn is parked inside the harness until it is
        answered, so this is not a message to reply to later -- it is the only thing that will
        move the session forward, and it says so by being the only thing that can be clicked.

        Free text stays available: the composer answers the pending question instead of sending a
        new message, which is the "Other (type your own)" both harnesses offer.
        """
        # The buttons below carry the labels, so listing them here too is the same words twice --
        # which is what omp's questions look like, since its frame has no descriptions. When an
        # option does explain itself (the SDK side, and omp's own `ask` when the model writes one),
        # that explanation is worth its line and the buttons cannot hold it.
        lines = [question.question]
        lines += [
            f"· <b>{option.label}</b> — {option.description}"
            for option in question.options
            if option.description
        ]
        if not question.options:
            # No options means no buttons, and without them the card is a grey bubble like any
            # other -- the one that hung a live session for eight minutes was exactly this. The
            # placeholder in the composer said so, and a placeholder is not where anyone looks.
            lines.append(f"<i>{i18n.t('questionFreeText')}</i>")
        self._add_bubble("sys", question.header or i18n.t("questionRole"), "<br>".join(lines))
        # Kept so the answer can be recorded against the question as PUT, not against its id: an
        # id means nothing to the next session reading the journal.
        self._pending_question_text = question.question

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for option in question.options:
            button = QPushButton(option.label)
            button.setProperty("class", "reason-btn")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, label=option.label: self._answer_question(label)
            )
            row.addWidget(button)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, holder)

        # A second question replaces the first: its buttons answer a frame omp has moved past.
        if self._question_widgets is not None:
            self._question_widgets.setParent(None)
            self._question_widgets.deleteLater()
        self._pending_question = question.id
        self._question_widgets = holder
        self._input.setEnabled(True)
        self._input.setFocus()
        self._refresh_placeholder()
        # "Working…" while the harness is blocked waiting for the human is the window blaming the
        # model for its own silence. Say who is being waited on.
        self._sub_label.setText(i18n.t("questionWaiting"))
        self._live_bubble = None
        self._live_text = ""
        self._scroll_to_end()

    def _withdraw_question(self, question_id: str) -> None:
        """The harness took the question back, so the card must go with it.

        Buttons that answer a frame omp has moved past are worse than no buttons: the answer is
        accepted, discarded, and the turn goes on looking like it ignored the Arbiter.
        """
        if self._pending_question != question_id:
            return
        self._pending_question = None
        if self._question_widgets is not None:
            self._question_widgets.setParent(None)
            self._question_widgets.deleteLater()
            self._question_widgets = None
        self._refresh_placeholder()
        self._sub_label.setText(i18n.t("agentThinking"))
        self._add_system_message(i18n.t("questionWithdrawn"))

    def _tick_activity(self) -> None:
        self._activity_phase = (self._activity_phase + 1) % 4
        dots = "." * self._activity_phase
        self._activity.setText(f"⟳ {self._activity_label}{dots}")

    def _end_chip(self) -> None:
        """That tool returned, so the line stops claiming it is running.

        The dots were the whole point of the line and nothing ever stopped them: `tool_execution_end`
        arrived on the wire and was dropped, so the last tool of a turn kept spinning for as long as
        the window stayed open. A stalled turn then looked exactly like a busy one -- which is how
        "⟳ omp:autoresearch…" came to read as "it is off doing something".
        """
        self._activity_timer.stop()
        if self._activity_label:
            self._activity.setText(f"· {self._activity_label}")

    def _answer_question(self, value: str) -> None:
        """Send the Arbiter's choice back through the channel the question came from."""
        question_id, self._pending_question = self._pending_question, None
        if question_id is None:
            return
        if self._question_widgets is not None:
            self._question_widgets.setParent(None)
            self._question_widgets.deleteLater()
            self._question_widgets = None
        self._refresh_placeholder()
        self._sub_label.setText(i18n.t("agentThinking"))  # the turn is ours to wait on again
        self._add_bubble("user", "Arbiter · you", _markdown(value))
        self._scroll_to_end()
        if self._worker is not None and hasattr(self._worker, "answer"):
            self._worker.answer(question_id, value)
        # The machine-readable form of the answer exists exactly here and was thrown away
        # (SCR-030): the option the Arbiter clicked, against the question as put.
        asked = getattr(self, "_pending_question_text", "") or i18n.t("questionRole")
        self._pending_question_text = ""
        self.arbiterAnswered.emit(asked, value)

    def _add_chip(self, tool_name: str) -> None:
        """A tool call as a one-line process event ("· get_tcc_state").

        Both spellings of the prefix, because the two harnesses disagree: the Agent SDK names
        TCC's tools `mcp__tcc__get_tcc_state` and omp names them `mcp__tcc_get_tcc_state`. Showing
        the raw name leaks which harness is running into every line of the transcript.

        A run of the same tool collapses into one row with a count. A model working out where it
        is calls `glob` six times in a row, and six identical full-width rows is most of a screen
        spent saying one thing -- the transcript is meant to show the shape of the work, not
        every call. The role caption goes too: the leading dot already says what kind of row this
        is, and "TOOL" on eight consecutive rows is the same word eight times.
        """
        pretty = tool_name.replace("mcp__tcc__", "").replace("mcp__tcc_", "")
        self._chip_count = self._chip_count + 1 if self._chip_tool == pretty else 1
        self._chip_tool = pretty
        self._activity_label = pretty + (f" ×{self._chip_count}" if self._chip_count > 1 else "")
        self._activity.setHidden(False)
        self._tick_activity()
        if not self._activity_timer.isActive():
            self._activity_timer.start()
        self._live_bubble = None  # text after a tool call starts a new bubble
        self._live_text = ""

    def _on_turn_done(self) -> None:
        self._activity_timer.stop()
        self._activity.setHidden(True)
        self._activity.setText("")
        self._chip_tool = ""
        self._chip_count = 0
        self._activity_label = ""
        # The question the turn is currently parked on, and the option buttons offering it.
        self._pending_question: Optional[str] = None
        self._question_widgets: Optional[QWidget] = None
        self._live_bubble = None
        self._live_text = ""
        self._set_busy(False)
        self._input.setFocus()
        self._flush_queued()
        self.turnFinished.emit()

    def _show_queue_row(self) -> None:
        """Say what is waiting, and keep saying it until it is not."""
        self._queue_label.setText(i18n.t("queueWaiting").format(count=len(self._queued)))
        self._queue_row.setHidden(not self._queued)

    def _flush_queued(self) -> None:
        """Send what was typed mid-turn, now that the turn boundary is here.

        Joined into one prompt rather than sent one after another: the second would land on a
        harness already busy with the first and queue again behind it, which is the same wait with
        more steps.
        """
        if not self._queued or self._worker is None:
            return
        text, self._queued = "\n\n".join(self._queued), []
        self._show_queue_row()
        self._set_busy(True)
        self._worker.send(text)

    def _on_send_queued_now(self) -> None:
        """Stop waiting for the turn to end and make it end.

        The queue's promise depends on a turn boundary arriving, and a turn that has gone quiet
        for minutes may not produce one -- that is exactly the state this button was added under.
        Interrupting produces the boundary, and `_on_turn_done` then sends what is waiting; the
        alternative, pushing a second prompt into a running harness, is not a thing omp accepts.
        """
        if self._worker is None or not self._queued:
            return
        if self._pending_question is not None:
            # A parked question blocks the harness inside `ask`, where `abort` does not reach.
            # Withdrawing it is what unblocks the turn, which is what ends it.
            self._on_stop()
            return
        if hasattr(self._worker, "interrupt"):
            self._worker.interrupt()

    def _on_failed(self, message: str) -> None:
        self._add_bubble("sys", i18n.t("agentFailed"), f"⚠️ {message}")
        self._set_busy(False)
        if self._queued:
            # There is no turn boundary coming. Put the words back where they can be re-sent
            # rather than dropping them into a session that has stopped.
            self._input.setText("\n\n".join(self._queued))
            self._queued = []
            self._show_queue_row()
            self._add_system_message(i18n.t("messageNotSent"))

    def add_critique(self, critique: dict) -> None:
        """Render a reviewer reply as a Critic bubble — or say plainly that there isn't one yet.

        `clipboard` is the zero-cost path, not a failure: no API or CLI was reachable, so the
        package is on the clipboard for the Arbiter to paste into any free web chat. Showing it as
        an empty critique would be the one genuinely harmful rendering, because the loop's whole
        value is that somebody actually pushed back.
        """
        mode = critique.get("mode")
        model = critique.get("model") or "?"
        # Where the text itself was written (SCR-027). Said in the bubble because the bubble is not
        # the copy of record any more: the file is, and a session read back from disk next week is
        # reading that file rather than this window.
        review = critique.get("review")
        note = f"<br><i>{i18n.t('criticSaved').format(path=review)}</i>" if review else ""
        if mode == "answered":
            # Through `_markdown`, like every other bubble. It was the one call site passing raw
            # model output in as rich text: asterisks and hashes showed literally, every newline
            # collapsed, so a three-page structured critique arrived as one flat paragraph (user,
            # 2026-08-11) — and an unescaped `<` in it would have been markup, not text.
            self._add_bubble("crit", f"Critic · {model}", _markdown(critique.get("text", "")) + note)
        elif mode == "clipboard":
            self._add_system_message(i18n.t("criticClipboard") + note)
        else:
            self._add_system_message(
                i18n.t("criticFailed").format(detail=critique.get("detail", "?"))
            )
        self._scroll_to_end()

    def _on_confirmation_resolved(self, tool: str, allowed: bool) -> None:
        key = "confirmAllowed" if allowed else "confirmDenied"
        self._add_system_message(i18n.t(key).format(tool=tool))

    def _on_not_visible(self) -> None:
        if self._bus is None:
            return
        self._bus.push(signal_bus.NOT_VISIBLE, note=self._input.text().strip() or None)
        self._add_system_message(i18n.t("notVisibleSent"))

    # ---- project-param-edit flag flow -------------------------------------

    def _on_chip_clicked(self) -> None:
        if self._editing:
            self._finish_editing()
            return
        self._reasons_bar.setHidden(not self._reasons_bar.isHidden())

    def _start_editing(self, reason: str) -> None:
        self._reason = reason
        self._editing = True
        self._reasons_bar.setHidden(True)
        self._edit_chip.setProperty("class", "edit-chip on")
        self._edit_chip.setText("✎ " + i18n.t("reasonForgot" if reason == "forgot" else "reasonManual") + " ✕")
        self._restyle_chip()
        self._add_system_message(i18n.t("editStartForgot" if reason == "forgot" else "editStartManual"))
        # Goes through the bus, not the session: the agent may be the in-app one or the user's own
        # CLI in a terminal, and param-edit mode has to reach whichever is actually listening.
        if self._bus is not None:
            self._bus.push(signal_bus.PARAM_EDIT_MODE, on=True, reason=reason)
        self.editingChanged.emit(True)

    def _finish_editing(self) -> None:
        self._add_system_message(i18n.t("editDoneForgot" if self._reason == "forgot" else "editDoneManual"))
        if self._bus is not None:
            self._bus.push(signal_bus.PARAM_EDIT_MODE, on=False, reason=self._reason)
        self._editing = False
        self._reason = None
        self._edit_chip.setProperty("class", "edit-chip")
        self._edit_chip.setText("✎ " + i18n.t("editChipLabel"))
        self._restyle_chip()
        self.editingChanged.emit(False)

    def _restyle_chip(self) -> None:
        self._edit_chip.style().unpolish(self._edit_chip)
        self._edit_chip.style().polish(self._edit_chip)

    @property
    def is_editing(self) -> bool:
        return self._editing
