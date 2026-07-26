"""The center AI-dialog panel — ported from the prototype's `renderDialog` + the project-param-
edit flag chip (`data/private/prototype/tcc-main.html`): message bubbles (Generator/Critic/
Arbiter/system), a composer, and the "✎ Project param edit" chip + reason picker that flags the
dialog as being about a ledger correction rather than routine tuning.

Mock `DIALOG` messages only (M5 scope) — this is the main tuning-dialog surface, distinct from
`profile_interview_dialog.py`'s onboarding-only chat. Wiring the composer to a real
`core.agent_session`-style backend (reusing that module's QThread+asyncio pattern) is later work.
"""

from __future__ import annotations

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


class MessageBubble(QFrame):
    def __init__(self, who: str, role: str, html: str) -> None:
        super().__init__()
        self.setProperty("class", f"msg msg-{who}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        who_label = QLabel(role)
        who_label.setProperty("class", f"msg-who msg-who-{who}")
        layout.addWidget(who_label)
        body = QLabel(html)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setProperty("class", "msg-body")
        layout.addWidget(body)


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
        self._chat_layout.setContentsMargins(14, 14, 14, 14)
        self._chat_layout.setSpacing(12)
        for message in DIALOG:
            self._add_bubble(message.who, message.role, i18n.tx(message.text))
        self._chat_layout.addStretch(1)
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
        """Re-set every static label's text, and rebuild the mock chat from DIALOG in the new
        language (simpler and just as correct as translating already-rendered bubbles in place,
        since it's mock data either way)."""
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

        while self._chat_layout.count():
            item = self._chat_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub_item = item.layout().takeAt(0)
                    sub_widget = sub_item.widget()
                    if sub_widget:
                        # setParent(None) first -- see set_view()/retranslate() elsewhere for why
                        # deleteLater() alone would leave this bubble visible one frame too long.
                        sub_widget.setParent(None)
                        sub_widget.deleteLater()
        for message in DIALOG:
            self._add_bubble(message.who, message.role, i18n.tx(message.text))
        self._chat_layout.addStretch(1)

    def _add_bubble(self, who: str, role: str, html: str) -> None:
        bubble_row = QHBoxLayout()
        bubble = MessageBubble(who, role, html)
        bubble.setMaximumWidth(int(self._chat.width() * 0.82) or 500)
        if who == "user":
            bubble_row.addStretch(1)
            bubble_row.addWidget(bubble)
        elif who == "sys":
            bubble_row.addStretch(1)
            bubble_row.addWidget(bubble)
            bubble_row.addStretch(1)
        else:
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
