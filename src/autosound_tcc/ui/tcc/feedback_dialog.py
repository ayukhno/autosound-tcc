"""The feedback modal — ported from the prototype's `.fb-modal` (`data/private/prototype/
tcc-main.html`). A small rich-text editor (Bold / Italic / bulleted / numbered) plus a choice of
destination: a GitHub issue (for users with an account) or a Google Form (for everyone else).

No network calls of our own: "send" hands the composed text off to the chosen destination via the
system browser (GitHub issue prefilled with the text as Markdown; the Google Form opened with the
text placed on the clipboard to paste, since a public form has no trusted server-side prefill we
can rely on here). The point is to lower the barrier for non-developer testers, exactly like the
prototype's two-way modal.
"""

from __future__ import annotations

import urllib.parse

from PySide6.QtGui import QDesktopServices, QGuiApplication, QTextCursor, QTextListFormat
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
)

from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip


class FeedbackDialog(QDialog):
    def __init__(self, github_url: str, form_url: str, parent=None) -> None:
        super().__init__(parent)
        self._github_url = github_url
        self._form_url = form_url
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setProperty("class", "fb-card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 20)
        outer.setSpacing(10)

        head = QLabel(i18n.t("fbHead"))
        head.setProperty("class", "fb-head")
        outer.addWidget(head)
        hint = QLabel(i18n.t("fbHint"))
        hint.setWordWrap(True)
        hint.setProperty("class", "fb-hint")
        outer.addWidget(hint)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        for text, handler, tip in (
            ("B", self._toggle_bold, "bold"),
            ("I", self._toggle_italic, "italic"),
            ("• ≡", lambda: self._make_list(QTextListFormat.Style.ListDisc), "bulleted"),
            ("1. ≡", lambda: self._make_list(QTextListFormat.Style.ListDecimal), "numbered"),
        ):
            btn = QPushButton(text)
            btn.setProperty("class", "fb-tool")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            attach_tip(btn, tip)
            btn.clicked.connect(handler)
            toolbar.addWidget(btn)
        toolbar.addStretch(1)
        outer.addLayout(toolbar)

        self._editor = QTextEdit()
        self._editor.setAcceptRichText(True)
        self._editor.setPlaceholderText(i18n.t("fbPh"))
        self._editor.setProperty("class", "fb-rte")
        self._editor.setMinimumHeight(120)
        outer.addWidget(self._editor)

        via = QLabel(i18n.t("fbVia"))
        via.setProperty("class", "fb-hint")
        outer.addWidget(via)
        self._radio_github = QRadioButton(i18n.t("fbViaGithub"))
        self._radio_form = QRadioButton(i18n.t("fbViaForm"))
        self._radio_form.setChecked(True)  # default: no account needed
        self._radio_github.toggled.connect(self._sync_send_label)
        outer.addWidget(self._radio_form)
        outer.addWidget(self._radio_github)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton(i18n.t("fbCancel"))
        cancel.setProperty("class", "fb-cancel")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self._send = QPushButton()
        self._send.setProperty("class", "fb-send")
        self._send.clicked.connect(self._on_send)
        actions.addWidget(self._send)
        outer.addLayout(actions)
        self._sync_send_label()

    # ---- toolbar ----------------------------------------------------------

    def _toggle_bold(self) -> None:
        from PySide6.QtGui import QFont

        weight = QFont.Weight.Normal if self._editor.fontWeight() > QFont.Weight.Normal else QFont.Weight.Bold
        self._editor.setFontWeight(weight)
        self._editor.setFocus()

    def _toggle_italic(self) -> None:
        self._editor.setFontItalic(not self._editor.fontItalic())
        self._editor.setFocus()

    def _make_list(self, style: QTextListFormat.Style) -> None:
        cursor = self._editor.textCursor()
        fmt = QTextListFormat()
        fmt.setStyle(style)
        cursor.createList(fmt)
        self._editor.setFocus()

    # ---- send -------------------------------------------------------------

    def _sync_send_label(self) -> None:
        self._send.setText(
            i18n.t("fbSendGithub") if self._radio_github.isChecked() else i18n.t("fbSendForm")
        )

    def _on_send(self) -> None:
        if self._radio_github.isChecked():
            body = self._editor.toMarkdown().strip()
            url = self._github_url
            if body:
                url = f"{self._github_url}?body={urllib.parse.quote(body)}"
            QDesktopServices.openUrl(QUrl(url))
        else:
            # No reliable prefill for a public form: put the text on the clipboard so the tester
            # can paste it, then open the form.
            QGuiApplication.clipboard().setText(self._editor.toPlainText().strip())
            if self._form_url:
                QDesktopServices.openUrl(QUrl(self._form_url))
        self.accept()
