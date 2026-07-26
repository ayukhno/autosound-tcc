"""The center AI-dialog panel — ported from the prototype's `renderDialog` + the project-param-
edit flag chip (`data/private/prototype/tcc-main.html`): message bubbles (Generator/Critic/
Arbiter/system), a composer, and the "✎ Project param edit" chip + reason picker that flags the
dialog as being about a ledger correction rather than routine tuning.

Mock `DIALOG` messages only (M5 scope) — this is the main tuning-dialog surface, distinct from
`profile_interview_dialog.py`'s onboarding-only chat. Wiring the composer to a real
`core.agent_session`-style backend (reusing that module's QThread+asyncio pattern) is later work.
"""

from __future__ import annotations

import re

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

from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.mock_data import DIALOG, DialogMessage
from autosound_tcc.ui.tcc.theme import apply_caps


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
        body = QLabel(html)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setProperty("class", "msg-body")
        layout.addWidget(body)
        # Width the bubble would want if its text sat on one line -- lets the panel size each
        # bubble to its content (dynamic, like the web) up to the max-width cap, instead of every
        # bubble being forced to the same width.
        plain = re.sub(r"<[^>]+>", "", html)
        self.natural_width = max(
            body.fontMetrics().horizontalAdvance(plain),
            who_label.fontMetrics().horizontalAdvance(role),
        ) + 28


class DialogPanel(QWidget):
    """The whole center dialog: message list, composer, and the project-param-edit chip. The
    surrounding `.panel` frame's "editing" border highlight is applied by the caller
    (main_window.py) via `editingChanged`, same split as the measurement card's yellow border.
    """

    editingChanged = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._editing = False
        self._reason: str | None = None
        self._bubbles: list[MessageBubble] = []

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
        head_layout.addStretch(1)

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
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(9, 9, 9, 9)
        composer_layout.setSpacing(8)
        self._input = QLineEdit()
        self._input.setPlaceholderText(i18n.t("composer"))
        self._input.setProperty("class", "composer-input")
        composer_layout.addWidget(self._input, stretch=1)
        self._send_btn = QPushButton(i18n.t("send"))
        self._send_btn.setProperty("class", "composer-send")
        composer_layout.addWidget(self._send_btn)
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

    def _add_system_message(self, html: str) -> None:
        self._add_bubble("sys", "SYSTEM · ledger", html)
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())

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
        self.editingChanged.emit(True)

    def _finish_editing(self) -> None:
        self._add_system_message(i18n.t("editDoneForgot" if self._reason == "forgot" else "editDoneManual"))
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
