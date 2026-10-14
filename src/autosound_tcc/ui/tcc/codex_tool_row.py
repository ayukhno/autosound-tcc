"""Codex's row on the Updates tab, under «Tools the installer put in» (W-10 tcc#181, the
Arbiter's Windows pass: the list had omp, agy, gh and Claude Code, and no Codex).

TCC's own row, not the method's `upkeep`: the Codex TCC would use (`codex_cli.standing()`, read on a
plain thread — it runs `codex --version` — never on the GUI thread) and what is to be done about it:

* none found → «not installed», and «Install Codex», which is `codex_menu.install` — the same
  worker, progress and receipt as the menu line, on the main window's status strip;
* only one known too old → «0.152.0 → 0.162.1 (TCC's own copy)», the same button;
* TCC's own copy → «up to date»;
* the person's own Codex, new enough → «<version> — your own Codex», no button: their winget, npm
  or Homebrew Codex is theirs to update, and the tooltip says so.

The install needs the main window (its strip, its pickers, its one Codex job): a dialog opened
without one shows the row and offers nothing.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from autosound_tcc.core import codex_cli
from autosound_tcc.ui.tcc import codex_menu, i18n

_POLL_MS = 100


class _Check:
    """`codex_cli.standing()` on a plain thread (nothing of Qt's, so it may outlive the row);
    `result` is the `Standing`, `error` the exception's words."""

    def __init__(self) -> None:
        self.result: Optional[codex_cli.Standing] = None
        self.error = ""
        self._thread = threading.Thread(target=self._run, name="tcc-codex-row", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            codex_cli.forget()  # Re-check looks again: a Codex installed since is seen
            self.result = codex_cli.standing()
        except Exception as exc:  # noqa: BLE001 — an answer on the row, not a dead thread
            self.error = f"{type(exc).__name__}: {exc}"

    @property
    def running(self) -> bool:
        return self._thread.is_alive()


class CodexToolRow(QWidget):
    """One line and «Install Codex». `host()` is the main window, or something without its strip
    (a dialog opened alone); `changed()` is called whenever what the row offers may have moved —
    «Update all» goes by it."""

    def __init__(self, host: Callable[[], Any], changed: Callable[[], None]) -> None:
        super().__init__()
        self._host = host
        self._changed = changed
        self.standing: Optional[codex_cli.Standing] = None
        self._error = ""
        self._receipt = ""
        self._job: Optional[_Check] = None
        self._installing = False
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setProperty("class", "mn")
        line.addWidget(self.label, stretch=1)
        self.button = QPushButton(i18n.t("codexInstall"))
        self.button.setProperty("class", "reason-btn")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setToolTip(i18n.t("codexInstallTip"))
        self.button.clicked.connect(self.install)
        line.addWidget(self.button, alignment=Qt.AlignmentFlag.AlignRight)
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._draw()

    # ---- what it says ----------------------------------------------------------------------

    @property
    def checking(self) -> bool:
        return self._job is not None

    def _strip_host(self):
        host = self._host()
        return host if host is not None and hasattr(host, "_status_strip") else None

    @property
    def offered(self) -> bool:
        """TCC's install is the thing to do, and it can be started from here now."""
        host = self._strip_host()
        return (self.standing is not None and self.standing.offered and host is not None
                and not self._installing and not self.checking and not codex_menu._busy(host))

    def _text(self) -> str:
        found = self.standing
        if self._error:
            return i18n.t("updCodexUnknown").format(why=self._error)
        if found is None:
            return i18n.t("updCodexChecking")
        if found.state == codex_cli.STANDING_MISSING:
            return i18n.t("updCodexMissing")
        if found.state == codex_cli.STANDING_TOO_OLD:
            return i18n.t("updCodexTooOld").format(here=found.version, there=codex_cli.PIN)
        if found.state == codex_cli.STANDING_TCC:
            return i18n.t("updToolCurrent").format(name="Codex", here=found.version)
        return i18n.t("updCodexOwn").format(here=found.version)

    def _draw(self) -> None:
        if not self._installing:
            text = self._text()
            self.label.setText(f"{text}\n{self._receipt}" if self._receipt else text)
        own = self.standing is not None and self.standing.state == codex_cli.STANDING_OWN
        self.label.setToolTip(i18n.t("updCodexOwnTip") if own else "")
        self.button.setHidden(own)
        self.button.setEnabled(self.offered)

    def retranslate(self) -> None:
        self.button.setText(i18n.t("codexInstall"))
        self.button.setToolTip(i18n.t("codexInstallTip"))
        self._draw()

    # ---- asking -----------------------------------------------------------------------------

    def check(self) -> None:
        """Ask which Codex TCC would use — off the GUI thread; not while one is being installed
        or asked already."""
        if self._installing or self._job is not None:
            return
        self._job = _Check()
        self._error = ""
        self.standing = None
        self._draw()
        self._timer.start()

    def _poll(self) -> None:
        job = self._job
        if job is None or job.running:
            return
        self._timer.stop()
        self._job = None
        self.standing, self._error = job.result, job.error
        self._draw()
        self._changed()

    # ---- installing -------------------------------------------------------------------------

    def install(self) -> None:
        """`codex_menu.install` on the main window — the menu line's own worker and strip — with
        its progress on this row too, and the row read again when it ends."""
        host = self._strip_host()
        if not self.offered or host is None:
            return
        codex_menu.install(host)
        job = getattr(host, "_codex_job", None)
        if job is None:
            return
        self._installing = True
        self._receipt = ""
        self.label.setText(i18n.t("codexInstalling").format(percent=0, done=0, total=0))
        job.progress.connect(self._progress)
        job.done.connect(self._installed)
        self._draw()
        self._changed()

    def _progress(self, done, total) -> None:
        percent = int(done * 100 / total) if total else 0
        self.label.setText(i18n.t("codexInstalling").format(
            percent=percent, done=codex_menu._mb(done), total=codex_menu._mb(total)))

    def _installed(self, error) -> None:
        self._installing = False
        self._receipt = "" if error is None else i18n.t("updToolFailed").format(
            why=codex_menu.say_install_error(error))
        self.check()
        self._changed()
