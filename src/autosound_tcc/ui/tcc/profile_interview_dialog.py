"""Chat-style dialog for the DSP-profile onboarding interview.

Scoped to exactly this one interview (docs/TCC-TZ.md §4a's first concrete slice of the "AI
dialog" — the larger Generator/Critic/Arbiter tuning dialog from the prototype is a separate,
bigger initiative, not built here). Runs `core.agent_session.OnboardingSession` on a background
thread with its own asyncio loop (Qt's event loop isn't asyncio-compatible) and talks to it only
through Qt signals — the GUI thread never touches the SDK client directly.

## Why this is a second window and not `DialogPanel` (asked in SKL-008, answered here)

Because it runs BEFORE there is a project to be a panel of. `new_project_dialog` collects vendor,
model and folder, creates the folder, and opens this window on top of itself; the main window
behind it is still on whatever project was open before — or on none. `DialogPanel` is bound to
`config.project_dir()` and to a session the main window owns, and moving the interview into it
would mean either switching the whole application to a project that does not exist yet, or
teaching the panel a second, projectless mode. Neither is a rendering fix.

**What was actually wrong is that it was a second IMPLEMENTATION.** 184 lines against the panel's
1413, and poorer by exactly that difference: the model's Markdown was printed raw, so
`**Питання 1 — рівні (tiers):**` reached the tuner with its asterisks; a question's answer options
arrived glued into one paragraph, because `QTextEdit.append` was handed HTML and newlines are not
line breaks in HTML; and answers were typed into a `QLineEdit`, which flattens a paste. That is
`SKL-008`, from a Windows run on 2026-09-01, with the screenshot.

So the window stays and the duplication goes: rendering and input come from `chat_text`, which the
main panel uses too, and a fix to either is a fix in both. Since 2026-09-06 the THREAD comes from
`ui/tcc/agent_worker.py` as well — that module's docstring had claimed since the day it was written
that it was generalised from here, while this window still ran its own copy without the parts that
matter when a session dies (`closed`, `CancelledError`, an escalating `shutdown`).

## And it showed nothing until a turn was over (SKL-009)

`_on_chunk` used to only accumulate, and `_append_bubble` was called from `_on_turn_done` alone.
A turn whose stream never finished therefore left NO trace — the window looked exactly as it does
while thinking. On 2026-09-01 that swallowed a completed interview: profile written 15:17:36,
closing summary produced 15:17:59, never rendered; at 15:19:28 the tuner opened another window to
ask whether a profile existed at all. The text is streamed into the transcript as it arrives now,
and `finalize_profile` says so in the transcript rather than only in the status line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from autosound_tcc.core import app_log
from autosound_tcc.core.agent_session import OnboardingSession
from autosound_tcc.ui.tcc import chat_text, i18n, sizing
from autosound_tcc.ui.tcc.agent_worker import AgentWorker
from autosound_tcc.ui.tcc.app_settings import get_settings
from autosound_tcc.ui.tcc.chat_text import ComposerInput
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip

#: The same Lucide set the main panel's composer uses (NOTICE.md).
_ICONS_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"


class ProfileInterviewDialog(QDialog):
    """Chat panel: message list + composer, streaming the onboarding agent's turns from a
    background thread — rendered and typed with the same code as the main dialog."""

    # Re-emitted (not just shown in `self._status`) so a caller -- e.g. the "Create new project"
    # flow in main_window.py -- can react to a finished onboarding without reaching into this
    # dialog's own worker.
    profile_saved = Signal(str)

    def __init__(
        self,
        project_dir: Path,
        vendor: str,
        model: str,
        ai_model: Optional[str] = None,
        language: str = "en",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._project_dir = Path(project_dir)
        self.setWindowTitle(i18n.t("interviewTitle").format(vendor=vendor, model=model))
        # Measured against the window it opened from, like the read table, instead of the 560x640
        # it used to state in pixels (`ui/tcc/sizing.py` for why none of these ever looked).
        sizing.fit_to_parent(self, 0.7)

        self._transcript = QTextEdit()
        self._transcript.setReadOnly(True)
        # The same setting the main dialog's bubbles honour (`dialog_panel.apply_font_scale`).
        # This window read it nowhere at all, so A−/A+ in the app moved every surface except the
        # one a new owner meets first (tcc#8).
        scale = float(get_settings().value("ui/dialog_font_scale", 1.0))
        self._transcript.setStyleSheet(f"QTextEdit {{ font-size: {13.0 * scale:.1f}px; }}")
        self._composer = ComposerInput()
        self._composer.setPlaceholderText(i18n.t("interviewPlaceholder"))

        # A screenshot goes to the model as a FILE in the project, exactly as it does in the main
        # panel (`attach_image.py` for why). The interview is where a photo of the DSP's own
        # screen answers three questions at once, and it was the one surface without the button.
        self._attach_btn = QPushButton()
        self._attach_btn.setIcon(QIcon(str(_ICONS_DIR / "image.svg")))
        self._attach_btn.setIconSize(QSize(16, 16))
        self._attach_btn.setProperty("class", "reason-btn")
        self._attach_btn.setFixedWidth(30)
        self._attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        attach_tip(self._attach_btn, i18n.t("attachTip"))
        self._attach_btn.clicked.connect(self._on_attach_image)

        self._send_btn = QPushButton(i18n.t("send"))
        self._send_btn.setProperty("class", "composer-send")
        self._status = QLabel(i18n.t("interviewConnecting"))
        self._status.setProperty("class", "phead-sub")

        composer_row = QHBoxLayout()
        composer_row.addWidget(self._composer, stretch=1)
        composer_row.addWidget(self._attach_btn)
        composer_row.addWidget(self._send_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._transcript, stretch=1)
        layout.addLayout(composer_row)
        layout.addWidget(self._status)

        #: The turn being streamed, and where in the document it starts. `None` means no turn is
        #: on screen — the next chunk opens a new bubble instead of rewriting the last one.
        self._pending_line = ""
        self._live_start: Optional[int] = None
        self._send_btn.clicked.connect(self._on_send)
        self._composer.submitted.connect(self._on_send)
        self._set_input_enabled(False)

        app_log.logger().info("onboarding window opened: %s %s, project=%s",
                              vendor, model, self._project_dir)
        #: The written profile is announced ONCE. The worker used to stat `dsp_profile.json` after
        #: every turn and re-emit, so any turn after `finalize_profile` appended a second
        #: "profile written" bubble — masked in the real flow only because the caller closes the
        #: window on the first one.
        self._said_saved = False
        # The shared worker (`ui/tcc/agent_worker.py`), not a private copy. That module's own
        # docstring says it was generalised from this window, and until now that was not true:
        # this one had no `closed` signal, no `CancelledError` branch and no `finally`, so a
        # session that died outside `except Exception` left the window sitting on "thinking"
        # with the input disabled and nothing in the log (tcc#9).
        self._worker = AgentWorker(
            lambda: OnboardingSession(Path(project_dir), vendor, model, ai_model, language),
            parent=self,
        )
        self._worker.chunk.connect(self._on_chunk)
        self._worker.turn_done.connect(self._on_turn_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.closed.connect(self._on_closed)
        self._worker.start()

    def _set_input_enabled(self, enabled: bool) -> None:
        self._composer.setEnabled(enabled)
        self._send_btn.setEnabled(enabled)
        self._attach_btn.setEnabled(enabled)

    # ---- what the transcript shows -------------------------------------------------------

    @staticmethod
    def _bubble(who: str, body_html: str) -> str:
        return f"<b>{who}</b><br>{body_html}<br>"

    def _append_bubble(self, who: str, text: str) -> None:
        """A finished message. `text` is Markdown from a model or plain text from a person, and
        `chat_text.markdown` escapes both — nothing reaches the document as markup by accident.

        Always scrolled to: this is either what the tuner just typed or something said TO them
        about the run, and neither is "more of the stream they scrolled away from".
        """
        self._transcript.append(self._bubble(who, chat_text.markdown(text)))
        self._scroll_to_end(force=True)

    def _on_chunk(self, text: str) -> None:
        """One piece of the turn being spoken, on screen as it arrives.

        Re-rendered rather than appended, because Markdown does not survive being cut into
        chunks: `**bold**` arrives as `**bo` + `ld**`, and a renderer fed the halves would print
        the asterisks. The whole turn so far is re-rendered in place — the same bargain the main
        panel makes in `_append_live_text`.
        """
        if not text:
            return
        self._pending_line += text
        cursor = QTextCursor(self._transcript.document())
        if self._live_start is None:
            # An empty paragraph first, so the live block starts where a bubble would and does not
            # run into the end of the previous one.
            self._transcript.append("")
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._live_start = cursor.position()
        else:
            cursor.setPosition(self._live_start)
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        cursor.insertHtml(self._bubble(i18n.t("generator"),
                                       chat_text.markdown(self._pending_line)))
        self._scroll_to_end()

    def _on_turn_done(self) -> None:
        """The turn is over. What is on screen stays there; only the live anchor is released."""
        app_log.logger().info("onboarding turn delivered: %d chars", len(self._pending_line))
        self._pending_line = ""
        self._live_start = None
        self._status.setText(i18n.t("interviewYourTurn"))
        self._set_input_enabled(True)
        self._composer.setFocus()
        self._check_profile_written()

    def _check_profile_written(self) -> None:
        """Did this turn end with a profile on disk? Asked here, on the GUI thread, and answered
        at most once — a stat of one file is cheaper than a signal nobody can de-duplicate."""
        if self._said_saved:
            return
        path = self._project_dir / "dsp_profile.json"
        if not path.is_file():
            return
        self._said_saved = True
        self._on_profile_saved(str(path))

    def _on_closed(self) -> None:
        """The worker's thread ended. Whatever the reason, the window stops looking busy.

        This is the signal the private worker never had: a session that died outside
        `except Exception` left "thinking" on screen forever, which is indistinguishable from a
        model that is still working (tcc#9).
        """
        app_log.logger().info("onboarding worker finished")
        if self._said_saved:
            return
        self._set_input_enabled(False)
        self._status.setText(i18n.t("interviewEnded"))

    #: How far from the bottom still counts as "at the bottom", in pixels. A couple of lines:
    #: the bar moves under a stream, and an exact comparison would call every reader a scroller.
    _AT_BOTTOM_PX = 40

    def _scroll_to_end(self, force: bool = False) -> None:
        """Follow the stream — unless the reader has scrolled up to look at something.

        It used to slam the bar to `maximum()` on every chunk, so reading an earlier question
        while the model was still speaking was impossible: the view was yanked back within
        milliseconds. Same rule as the main panel's `_stick_to_bottom`.
        """
        bar = self._transcript.verticalScrollBar()
        if force or bar.value() >= bar.maximum() - self._AT_BOTTOM_PX:
            bar.setValue(bar.maximum())

    # ---- what the tuner does -------------------------------------------------------------

    def _on_send(self) -> None:
        text = self._composer.text().strip()
        if not text:
            return
        self._append_bubble(i18n.t("interviewYou"), text)
        self._composer.setText("")
        self._set_input_enabled(False)
        self._status.setText(i18n.t("interviewThinking"))
        self._worker.send(text)

    def _on_attach_image(self) -> None:
        """Paste a screenshot; TCC saves it in the project and writes the path into the composer.

        The interview's own project folder, not `config.project_dir()`: the application may still
        be showing another project — or none — while this window runs.
        """
        from autosound_tcc.ui.tcc.attach_image import AttachImageDialog

        dialog = AttachImageDialog(self._project_dir, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        line = dialog.line()
        if not line:
            return
        existing = self._composer.text().rstrip()
        self._composer.setText(f"{existing}\n{line}" if existing else line)
        self._composer.setFocus()

    def _on_profile_saved(self, path: str) -> None:
        """A written profile is an EVENT in the conversation, not a line in the status bar.

        It used to be the status label alone, which is the one part of the window a tuner reading
        the transcript is not looking at (SKL-009: the profile was written at 15:17:36 and at
        15:19:28 the tuner was in another window asking whether one existed).
        """
        app_log.logger().info("onboarding profile written: %s", path)
        self._append_bubble(i18n.t("interviewSystem"),
                            i18n.t("interviewSaved").format(path=path) + "\n\n"
                            + i18n.t("interviewDone"))
        self._status.setText(i18n.t("interviewSaved").format(path=path))
        self.profile_saved.emit(path)

    def _on_failed(self, message: str) -> None:
        app_log.logger().error("onboarding session failed: %s", message)
        self._append_bubble(i18n.t("interviewSystem"), f"⚠️ {message}")
        self._status.setText(i18n.t("interviewError"))
        self._set_input_enabled(False)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """`shutdown()`, not `stop()` + `wait()`: the sentinel is only read BETWEEN turns, so a
        window closed mid-turn used to expire the wait and let Qt destroy a running QThread. The
        shared worker escalates — interrupt, sentinel, cancel — and says whether it worked."""
        app_log.logger().info("onboarding window closed")
        if not self._worker.shutdown(5000):
            app_log.logger().warning("onboarding worker did not stop in time")
        super().closeEvent(event)
