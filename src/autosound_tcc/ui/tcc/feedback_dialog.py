"""The feedback modal — ported from the prototype's `.fb-modal` (`data/private/prototype/
tcc-main.html`). A small rich-text editor (Bold / Italic / bulleted / numbered) plus a choice of
destination: a GitHub issue (for users with an account) or the Arbiter's Google Form (for everyone else).

The GitHub route hands the text to the system browser, prefilled. The form route SENDS it, from the
window, with no browser and no sign-in (TODO F-042, the Arbiter's decision of 2026-09-17): a person
without a GitHub account used to be handed a clipboard and a form to paste into, and before that
nothing at all. What goes is on screen before Send — the words, the first line that says what they
ran on, and anything the caller attaches — and "sent" is said only when the form confirmed it
(`core/form_report.py`).
"""

from __future__ import annotations

import threading
import urllib.parse

from pathlib import Path

from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap, QTextListFormat
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import form_report, issue_assets
from autosound_tcc.ui.tcc import discard, i18n
from autosound_tcc.ui.tcc.labels import ElidedLabel
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip

#: Big enough to recognise a name, a path or an installer's logo in a screenshot — which is the
#: only thing this preview is for. A thumbnail too small to read is a consent screen that shows
#: nothing (SKL-019).
THUMB_W, THUMB_H = 220, 140


def body_with_shots(body: str, urls) -> str:
    """The report's own text, then the pictures under it, as Markdown GitHub renders.

    Under, never inside: the text is what a person wrote and the images are evidence for it, and
    a body that opens with three screenshots reads as a bug report with no words in it.
    """
    if not urls:
        return body
    shots = [f"![{i18n.t('fbShotsAlt').format(n=n)}]({url})" for n, url in enumerate(urls, 1)]
    return "\n\n".join([body] + shots).strip()


class _FormSend:
    """Posts one report to the form on a plain thread, the `_UpdateProbe` shape of the diagnostics
    dialog: a slow network must not freeze the window, and nothing of Qt's is touched off it."""

    def __init__(self, text: str, url: str) -> None:
        self.result = None
        self._thread = threading.Thread(
            target=self._run, args=(text, url), name="tcc-form-report", daemon=True)
        self._thread.start()

    def _run(self, text: str, url: str) -> None:
        try:
            self.result = form_report.send(text, url=url)
        except Exception as exc:  # noqa: BLE001 — `send` never raises; a stand-in still might
            self.result = form_report.Sent(False, "network", f"{type(exc).__name__}: {exc}")

    @property
    def running(self) -> bool:
        return self._thread.is_alive()


#: What each kind is called on screen; the first line always carries the English word.
_KIND_KEYS = {"problem": "fbKindProblem", "wish": "fbKindWish", "feedback": "fbKindFeedback"}


class FeedbackDialog(QDialog):
    def __init__(self, github_url: str, form_url: str, parent=None, *, kind: str = "feedback",
                 attachment: str = "", github_link=None) -> None:
        """`form_url` empty leaves GitHub as the only route. `attachment` goes to the form under
        the words, shown before Send; `github_link(body)` builds the page the GitHub route opens,
        so a caller with its own issue template keeps it (the diagnostics dialog does)."""
        super().__init__(parent)
        self._github_url = github_url
        self._form_url = form_url
        self._attachment = attachment
        self._github_link = github_link or self._plain_issue_link
        self._sending = None
        self._send_timer = QTimer(self)
        self._send_timer.setInterval(150)
        self._send_timer.timeout.connect(self._poll_send)
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

        # ---- screenshots ---------------------------------------------------
        # Offered only where they can actually travel: the gate's uploader arrives with a method
        # newer than this checkout's pin, and a control that attaches pictures nothing can carry
        # is a promise the Send button then breaks (SKL-019; `core/issue_assets.available()`).
        self._shots: list[Path] = []
        self._shots_box = QWidget()
        shots_layout = QVBoxLayout(self._shots_box)
        shots_layout.setContentsMargins(0, 0, 0, 0)
        shots_layout.setSpacing(6)
        add_row = QHBoxLayout()
        self._shots_add = QPushButton(i18n.t("fbShotsAdd"))
        self._shots_add.setProperty("class", "fb-tool")
        self._shots_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self._shots_add.clicked.connect(self._on_add_shots)
        add_row.addWidget(self._shots_add)
        add_row.addStretch(1)
        shots_layout.addLayout(add_row)
        # The sentence that makes the pictures a decision rather than an attachment. It appears
        # WITH them, not above an empty row: a warning about nothing is read once and then never.
        self._shots_warn = QLabel(i18n.t("fbShotsWarn"))
        self._shots_warn.setWordWrap(True)
        self._shots_warn.setProperty("class", "fb-hint")
        self._shots_warn.setVisible(False)
        shots_layout.addWidget(self._shots_warn)
        self._strip = QHBoxLayout()
        self._strip.setSpacing(8)
        self._strip.addStretch(1)
        shots_layout.addLayout(self._strip)
        self._shots_problem = QLabel("")
        self._shots_problem.setWordWrap(True)
        self._shots_problem.setProperty("class", "kv-warn")
        self._shots_problem.setVisible(False)
        shots_layout.addWidget(self._shots_problem)
        outer.addWidget(self._shots_box)

        via = QLabel(i18n.t("fbVia"))
        via.setProperty("class", "fb-hint")
        outer.addWidget(via)
        self._radio_github = QRadioButton(i18n.t("fbViaGithub"))
        self._radio_form = QRadioButton(i18n.t("fbViaForm"))
        self._radio_form.setChecked(True)  # default when there IS a form: no account needed
        outer.addWidget(self._radio_form)
        outer.addWidget(self._radio_github)
        if not form_url:
            # No form configured — and this was the DEFAULT choice, so "Send" copied the text to
            # the clipboard, opened nothing, and closed the dialog as though it had gone somewhere.
            # A tester's report died there silently (found 2026-08-19, on the way into the beta).
            # One destination left, so the question goes away with it.
            via.hide()
            self._radio_form.hide()
            self._radio_github.setChecked(True)

        # ---- what the form route sends besides the words (TODO F-042) ----------------------
        # The kind, and the first line it makes, matter only where they travel: the GitHub route
        # has its own page for them, so both go away with the form radio.
        self._kind_row = QWidget()
        kind_layout = QHBoxLayout(self._kind_row)
        kind_layout.setContentsMargins(0, 0, 0, 0)
        kind_label = QLabel(i18n.t("fbKind"))
        kind_label.setProperty("class", "fb-hint")
        kind_layout.addWidget(kind_label)
        self._kind_group = QButtonGroup(self)
        self._kind_buttons: dict[str, QRadioButton] = {}
        for name in form_report.KINDS:
            button = QRadioButton(i18n.t(_KIND_KEYS[name]))
            self._kind_group.addButton(button)
            self._kind_buttons[name] = button
            kind_layout.addWidget(button)
        kind_layout.addStretch(1)
        self._kind_buttons[kind if kind in self._kind_buttons else "feedback"].setChecked(True)
        outer.addWidget(self._kind_row)
        self._goes_with_label = QLabel(i18n.t("fbGoesWith"))
        self._goes_with_label.setProperty("class", "fb-hint")
        outer.addWidget(self._goes_with_label)
        self._goes_with = QPlainTextEdit()
        self._goes_with.setReadOnly(True)
        self._goes_with.setMaximumHeight(90)
        outer.addWidget(self._goes_with)
        # Connected once the box they write to exists — the `_send` lesson below, again.
        for button in self._kind_buttons.values():
            button.toggled.connect(self._refresh_goes_with)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setProperty("class", "fb-hint")
        self._status.setVisible(False)
        outer.addWidget(self._status)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton(i18n.t("fbCancel"))
        cancel.setProperty("class", "fb-cancel")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self._cancel = cancel
        self._send = QPushButton()
        self._send.setProperty("class", "fb-send")
        self._send.clicked.connect(self._on_send)
        actions.addWidget(self._send)
        outer.addLayout(actions)
        # Connected HERE, after the button exists. It used to be wired where the radio is built,
        # and the "no form configured" branch a few lines above checks that radio on -- so
        # `toggled` reached `_sync_send_label` before `self._send` had been created and the
        # dialog died on `AttributeError` (user, 2026-08-21, with the log line). Every path that
        # sets the radio before this point is now just a state change; the label is settled once,
        # below, and kept in step from here on.
        self._radio_github.toggled.connect(self._sync_send_label)
        self._refresh_goes_with()
        self._sync_send_label()

    # ---- screenshots ------------------------------------------------------

    def _on_add_shots(self) -> None:
        pattern = " ".join(f"*{s}" for s in issue_assets.IMAGE_SUFFIXES)
        picked, _ = QFileDialog.getOpenFileNames(
            self, i18n.t("fbShotsPick"), "", f"{i18n.t('fbShotsKind')} ({pattern})"
        )
        for name in picked:
            path = Path(name)
            if path not in self._shots:
                self._shots.append(path)
        self._rebuild_strip()

    def _rebuild_strip(self) -> None:
        discard.clear(self._strip)
        unreadable = []
        for path in list(self._shots):
            card = self._shot_card(path)
            if card is None:
                # A file Qt cannot draw is a file nobody can check before it is published, so it
                # does not go: dropped here, and said, rather than travelling unseen.
                unreadable.append(path.name)
                self._shots.remove(path)
                continue
            self._strip.addWidget(card)
        self._strip.addStretch(1)
        self._shots_warn.setVisible(bool(self._shots))
        self._say_problem(i18n.t("fbShotsUnreadable").format(names=", ".join(unreadable))
                          if unreadable else "")

    def _shot_card(self, path: Path):
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return None
        card = QWidget()
        column = QVBoxLayout(card)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        shot = QLabel()
        shot.setPixmap(pixmap.scaled(THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
        shot.setCursor(Qt.CursorShape.PointingHandCursor)
        # A thumbnail is enough to notice a name in a title bar; it is not enough to read one.
        # Clicking opens the file itself, in whatever the machine views images with.
        shot.mousePressEvent = lambda _event, p=path: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(p)))
        attach_tip(shot, i18n.t("fbShotsOpen"))
        column.addWidget(shot)
        row = QHBoxLayout()
        row.setSpacing(4)
        name = ElidedLabel(path.name, min_width=60)
        name.setProperty("class", "cline2")
        row.addWidget(name, 1)
        drop = QPushButton("×")
        drop.setProperty("class", "fb-tool")
        drop.setCursor(Qt.CursorShape.PointingHandCursor)
        attach_tip(drop, i18n.t("fbShotsDrop"))
        drop.clicked.connect(lambda _checked=False, p=path: self._drop_shot(p))
        row.addWidget(drop)
        column.addLayout(row)
        return card

    def _drop_shot(self, path: Path) -> None:
        if path in self._shots:
            self._shots.remove(path)
        self._rebuild_strip()

    def _say_problem(self, text: str) -> None:
        self._shots_problem.setText(text)
        self._shots_problem.setVisible(bool(text))

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
        # A public form takes text from the clipboard and nothing else, so the pictures have
        # nowhere to go on that route. Hidden rather than explained: an offer that is withdrawn
        # at Send is worse than one never made.
        self._shots_box.setVisible(issue_assets.available() and self._radio_github.isChecked())
        on_form = not self._radio_github.isChecked()
        for widget in (self._kind_row, self._goes_with_label, self._goes_with):
            widget.setVisible(on_form)

    def _kind(self) -> str:
        return next((name for name, button in self._kind_buttons.items() if button.isChecked()),
                    "feedback")

    def _first_line(self) -> str:
        return form_report.first_line(self._kind(), i18n.current_language())

    def _refresh_goes_with(self, *_args) -> None:
        extra = [self._first_line()]
        if self._attachment.strip():
            extra.append(self._attachment.strip())
        self._goes_with.setPlainText("\n\n".join(extra))

    def _plain_issue_link(self, body: str) -> str:
        return f"{self._github_url}?body={urllib.parse.quote(body)}" if body else self._github_url

    def _say(self, text: str) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))

    def reject(self) -> None:  # noqa: D401 (Qt override)
        # Not while a report is on the way: closing would leave nobody to say whether it arrived.
        if self._sending is not None:
            return
        super().reject()

    def _send_to_form(self) -> None:
        words = self._editor.toMarkdown().strip() if self._editor.toPlainText().strip() else ""
        if not words:
            self._say(i18n.t("fbEmpty"))
            return
        self._outgoing = form_report.compose(self._first_line(), words, self._attachment)
        self._send.setEnabled(False)
        self._cancel.setEnabled(False)
        self._say(i18n.t("fbSending"))
        self._sending = _FormSend(self._outgoing, self._form_url)
        self._send_timer.start()

    def _poll_send(self) -> None:
        probe = self._sending
        if probe is None or probe.running:
            return
        self._send_timer.stop()
        self._sending = None
        self._cancel.setEnabled(True)
        result = probe.result or form_report.Sent(False, "network", "no answer")
        if result.ok:
            self._say(i18n.t("fbSent"))
            self._cancel.setText(i18n.t("fbClose"))
            self._editor.setReadOnly(True)
            return
        why = i18n.t("fbNoConfirm") if result.reason == "unconfirmed" else result.detail
        # Nothing a person wrote is lost to a network: the whole text goes to the clipboard.
        QGuiApplication.clipboard().setText(self._outgoing)
        self._say(i18n.t("fbNotSent").format(problem=why))
        self._send.setEnabled(True)

    def _on_send(self) -> None:
        if not self._radio_github.isChecked():
            self._send_to_form()
            return
        body = self._editor.toMarkdown().strip()
        if self._shots:
            # `consented=True` is EARNED here, and this is the only place in either half that
            # can earn it: these are the pictures still on screen after a person looked at
            # them and dropped the ones that should not travel.
            published = issue_assets.publish(self._shots, consented=True)
            body = body_with_shots(body, published.urls)
            if not published.ok:
                # Nothing is posted on a partial upload — but what already went up cannot be
                # taken back, so the count is said rather than swallowed.
                self._say_problem(i18n.t("fbShotsFailed").format(
                    problem=published.problem, n=len(published.urls)))
                return
        QDesktopServices.openUrl(QUrl(self._github_link(body)))
        self.accept()
