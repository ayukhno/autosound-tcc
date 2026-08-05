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
from typing import Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import signal_bus
from autosound_tcc.core.agent_events import Question, TextDelta, ToolCall
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.app_settings import get_settings
from autosound_tcc.ui.tcc.confirm_bar import ConfirmBar
from autosound_tcc.ui.tcc.mock_data import DIALOG, CURRENT_GENERATOR_MODEL, DialogMessage
from autosound_tcc.ui.tcc.theme import apply_caps

# .msg-body's base font-size in theme.py -- kept in sync with that QSS literal so the dialog's own
# A-/A+ control (below) scales from the same starting point.
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
    out = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", out)
    lines = []
    for line in out.split("\n"):
        stripped = line.strip()
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
    return "<br>".join(lines)


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
        layout.addWidget(self._body)
        # Width the bubble would want if its text sat on one line -- lets the panel size each
        # bubble to its content (dynamic, like the web) up to the max-width cap, instead of every
        # bubble being forced to the same width.
        plain = re.sub(r"<[^>]+>", "", html)
        self.natural_width = max(
            self._body.fontMetrics().horizontalAdvance(plain),
            who_label.fontMetrics().horizontalAdvance(role),
        ) + 28

    def set_html(self, html: str) -> None:
        """Replace the body text — used while a streamed answer is still growing.

        `natural_width` is recomputed so the bubble keeps hugging its content as text arrives,
        instead of freezing at the width of the first delta.
        """
        self._body.setText(html)
        plain = re.sub(r"<[^>]+>", "", html)
        self.natural_width = self._body.fontMetrics().horizontalAdvance(plain) + 28

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
        outer.addWidget(self._scroll, stretch=1)

        composer = QWidget()
        composer.setProperty("class", "composer")
        self._composer = composer
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(9, 9, 9, 9)
        composer_layout.setSpacing(8)
        self._input = QLineEdit()
        # Says "prototype — doesn't send" until an agent is attached, so the mock transcript never
        # looks like a live conversation the user can talk to.
        self._input.setPlaceholderText(i18n.t("composerMock"))
        self._input.setProperty("class", "composer-input")
        composer_layout.addWidget(self._input, stretch=1)
        self._send_btn = QPushButton(i18n.t("send"))
        self._send_btn.setProperty("class", "composer-send")
        self._send_btn.clicked.connect(self._on_send)
        self._input.returnPressed.connect(self._on_send)
        composer_layout.addWidget(self._send_btn)

        # Only meaningful while a turn is running, so it takes the send button's place rather than
        # sitting next to it greyed out.
        self._stop_btn = QPushButton(i18n.t("stop"))
        self._stop_btn.setProperty("class", "reason-btn")
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.clicked.connect(self._on_stop)
        self._stop_btn.setHidden(True)
        composer_layout.addWidget(self._stop_btn)
        outer.addWidget(composer)

    def retranslate(self) -> None:
        """Re-set the panel's own *chrome* (title, chip, composer) into the new UI language.

        The message bubbles are deliberately NOT re-translated: a dialog turn is live model /
        user output, produced in one language, not a UI string. Flipping the interface language
        must leave the actual conversation exactly as it happened (user feedback 2026-07-26)."""
        self._title_label.setText(i18n.t("dialog"))
        self._sub_label.setText(i18n.t("dialogSub"))
        self._reasons_q_label.setText(i18n.t("editReasonsQ"))
        self._reason_btns["forgot"].setText(i18n.t("reasonForgot"))
        self._reason_btns["manual"].setText(i18n.t("reasonManual"))
        self._input.setPlaceholderText(i18n.t("composer"))
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

    def _add_system_message(self, html: str) -> None:
        self._add_bubble("sys", "SYSTEM · ledger", html)
        self._scroll_to_end()

    def _scroll_to_end(self) -> None:
        # Guarded because the callers can be reached from a *queued* signal: the MCP server thread
        # emits a critique or a proposal, Qt defers the slot to the GUI thread, and by the time it
        # runs the panel may already be torn down (window closed mid-call). Touching a widget
        # whose C++ side is gone is the same class of fault as deleting a widget from inside its
        # own event handler -- see feedback_qt_qss_gotchas. Nothing to scroll is not an error.
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

    def clear_for_no_project(self) -> None:
        """Drop the mock transcript when MainWindow finds no real project on disk -- a folder
        with nothing real in it should never look like a live tuning conversation is underway."""
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
        self._input.setPlaceholderText(i18n.t("composer"))
        self.set_session_label(resumed=resumed, phase=phase)

        worker.chunk.connect(self._on_chunk)
        worker.turn_done.connect(self._on_turn_done)
        worker.failed.connect(self._on_failed)
        self._set_busy(True)
        # The first turn is slow -- the model reads the skill and the project's state before it
        # says anything, and omp additionally waits for its own tools to come up. Without a line
        # here, a session that is working looks exactly like one that did nothing.
        if model:
            self._add_system_message(i18n.t("sessionStarting").format(model=model))

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
        self._input.setEnabled(not busy)
        self._send_btn.setHidden(busy)
        self._stop_btn.setHidden(not busy)
        self._sub_label.setText(i18n.t("agentThinking") if busy else i18n.t("dialogSub"))

    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        if self._worker is None:
            # A live composer that swallows what you type is worse than a disabled one. Sending
            # the first message IS the explicit start, and the text becomes the opening prompt
            # rather than being thrown away in favour of a canned one.
            self._add_bubble("user", "Arbiter · you", text)
            self._input.clear()
            self._set_busy(True)
            self.startRequested.emit(text)
            return
        self._add_bubble("user", "Arbiter · you", text)
        self._scroll_to_end()
        self._input.clear()
        self._set_busy(True)
        self._worker.send(text)

    def _on_stop(self) -> None:
        """Interrupt the running turn. The worker owns the session, so ask it, don't reach in."""
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
        elif isinstance(item, Question):
            self._add_question(item)

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
        """A structured question from the agent, and the turn is parked until it is answered.

        Rendered rather than dropped even though nothing can answer it yet: the session that
        raises these is the omp adapter, and its reply path lands with it. What must not happen in
        the meantime is a blocked turn that looks like a finished one -- that is exactly how an
        unanswered question read during the spike, as a window that had hung.
        """
        lines = [question.question]
        lines += [
            f"· {option.label}" + (f" — {option.description}" if option.description else "")
            for option in question.options
        ]
        self._add_bubble("sys", question.header or "QUESTION", "<br>".join(lines))
        self._live_bubble = None
        self._live_text = ""
        self._scroll_to_end()

    def _add_chip(self, tool_name: str) -> None:
        """A tool call as a one-line process event ("· get_tcc_state").

        Both spellings of the prefix, because the two harnesses disagree: the Agent SDK names
        TCC's tools `mcp__tcc__get_tcc_state` and omp names them `mcp__tcc_get_tcc_state`. Showing
        the raw name leaks which harness is running into every line of the transcript.
        """
        pretty = tool_name.replace("mcp__tcc__", "").replace("mcp__tcc_", "")
        self._add_bubble("sys", "TOOL", f"· {pretty}")
        self._live_bubble = None  # text after a tool call starts a new bubble
        self._live_text = ""
        self._scroll_to_end()

    def _on_turn_done(self) -> None:
        self._live_bubble = None
        self._live_text = ""
        self._set_busy(False)
        self._input.setFocus()

    def _on_failed(self, message: str) -> None:
        self._add_bubble("sys", i18n.t("agentFailed"), f"⚠️ {message}")
        self._set_busy(False)

    def add_critique(self, critique: dict) -> None:
        """Render a reviewer reply as a Critic bubble — or say plainly that there isn't one yet.

        `clipboard` is the zero-cost path, not a failure: no API or CLI was reachable, so the
        package is on the clipboard for the Arbiter to paste into any free web chat. Showing it as
        an empty critique would be the one genuinely harmful rendering, because the loop's whole
        value is that somebody actually pushed back.
        """
        mode = critique.get("mode")
        model = critique.get("model") or "?"
        if mode == "answered":
            self._add_bubble("crit", f"Critic · {model}", critique.get("text", ""))
        elif mode == "clipboard":
            self._add_system_message(i18n.t("criticClipboard"))
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
