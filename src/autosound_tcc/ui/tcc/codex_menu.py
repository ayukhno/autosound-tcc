"""«Встановити Codex» and «Увійти в Codex»: two lines under ⚙ Settings (W-10 tcc#181, task 9).

A `menu_registry` provider — the window gains no line of its own but the one call that stops the
work when it closes (`menu_registry.stop_workers`). The Arbiter (2026-10-14): a Codex already
installed is used; with none, TCC installs it from the official source; every user signs in to
their own Codex account through a TCC button that opens the browser.

* **Install** — offered while `codex_cli.usable()` is None (not found, or known too old). The
  work runs on `workers.CodexInstallWorker`, its progress on the status strip with a «Cancel»; the
  result, done or the `InstallError`'s sentence, lands there too.
* **Sign in** — offered while Codex is usable and not known to be signed in. The work runs on
  `workers.CodexSignInWorker`; the window opens the address Codex gives in the browser and says
  «finish in the browser» with a «Cancel», then the result.

The lines' states are asked when Settings opens (`MainMenu`'s `aboutToShow`), by stat calls and
cached readings only — `version()` and `probe()` run only on the workers. One job at a time per
window, held on the host as `_codex_job` until it ends.

This module imports no Qt at its top: `menu_registry.collect()` reads it, and the registry is
Qt-free. Qt comes in when a line is pressed, on the GUI thread.
"""

from __future__ import annotations

from typing import Any, Optional

from autosound_tcc.core import codex_cli, codex_install, model_choices
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.menu_registry import MenuEntry

#: How long a closing window waits for a job to cancel before handing it to `qt_shutdown`.
STOP_WAIT_MS = 8000


def menu_entries() -> list[MenuEntry]:
    return [
        MenuEntry("codex_install", "settings", label_key="codexInstall",
                  tip_key="codexInstallTip", on=install, enabled=can_install, after="models"),
        MenuEntry("codex_sign_in", "settings", label_key="codexSignIn",
                  tip_key="codexSignInTip", on=sign_in, enabled=can_sign_in,
                  after="codex_install"),
    ]


# --- state: stat calls only -----------------------------------------------------------------------

def _busy(host) -> bool:
    job = getattr(host, "_codex_job", None)
    return job is not None and not job.isFinished()


def can_install(host) -> bool:
    """No usable Codex (none found, or one known too old), and no job running."""
    return not _busy(host) and codex_cli.usable() is None


def can_sign_in(host) -> bool:
    """A usable Codex not known to be signed in, and no job running."""
    return (not _busy(host) and codex_cli.usable() is not None
            and codex_cli.signed_in() is not True)


# --- after a success, on the worker ---------------------------------------------------------------

def after_install() -> None:
    """Read the new Codex (its login, its models) and the pickers' rows from that one probe."""
    codex_cli.probe(force=True)
    model_choices.store_codex_rows()


def after_sign_in() -> None:
    """The sign-in already probed afresh; the pickers' rows from that answer."""
    model_choices.store_codex_rows()


# --- the lines ------------------------------------------------------------------------------------

def _mb(count: Any) -> str:
    return f"{(int(count or 0)) / 1_000_000:.0f}"


def _cancel_offer(job) -> tuple[str, Any]:
    return (i18n.t("codexCancel"), job.requestInterruption)


def install(host) -> None:
    """«Встановити Codex»: start the install on a worker; progress and result on the strip."""
    if _busy(host):
        return
    from autosound_tcc.ui.tcc.workers import CodexInstallWorker

    job = CodexInstallWorker(then=lambda: after_install())
    strip = host._status_strip
    shown = {"percent": -1}

    def progress(done, total) -> None:
        percent = int(done * 100 / total) if total else 0
        if percent == shown["percent"]:
            return
        shown["percent"] = percent
        strip.notify(i18n.t("codexInstalling").format(percent=percent, done=_mb(done),
                                                      total=_mb(total)),
                     action=_cancel_offer(job))

    def finished(error: Optional[codex_install.InstallError]) -> None:
        if error is None:
            strip.notify(i18n.t("codexInstalled"))
            _reload_pickers(host)
        else:
            strip.notify(say_install_error(error), level="warn")

    job.progress.connect(progress)
    job.done.connect(finished)
    host._codex_job = job
    progress(0, 0)
    job.start()


def say_install_error(error: codex_install.InstallError) -> str:
    """The install's failure in the window's language; its English sentence when the key is not
    one of the strings."""
    if error.key and error.key in i18n.T["en"]:
        try:
            return i18n.t(error.key).format(**error.fields)
        except (KeyError, IndexError):
            pass
    return str(error)


def open_browser(url: str) -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    QDesktopServices.openUrl(QUrl(url))


def sign_in(host) -> None:
    """«Увійти в Codex»: the sign-in on a worker; the browser opened here, the result on the
    strip, a «Cancel» while it waits."""
    if _busy(host):
        return
    from autosound_tcc.ui.tcc.workers import CodexSignInWorker

    job = CodexSignInWorker(then=lambda: after_sign_in())
    strip = host._status_strip

    def got_url(url: str) -> None:
        open_browser(url)
        strip.notify(i18n.t("codexFinishInBrowser"), action=_cancel_offer(job))

    def finished(outcome) -> None:
        ok, error, cancelled = outcome
        if ok:
            strip.notify(i18n.t("codexSignedIn"))
            _reload_pickers(host)
        elif cancelled:
            strip.notify(i18n.t("codexSignInCancelled"))
        else:
            strip.notify(i18n.t("codexSignInFailed").format(error=error), level="warn")

    job.url.connect(got_url)
    job.done.connect(finished)
    host._codex_job = job
    job.start()


def _reload_pickers(host) -> None:
    reload = getattr(host, "_reload_model_choices", None)
    if callable(reload):
        reload()


def stop_workers(host) -> None:
    """The window is closing: cancel a running job (the install between chunks, the sign-in in
    Codex, its child closed) and wait for it; one that will not end is handed to `qt_shutdown`
    with its signals cut, never destroyed running."""
    job = getattr(host, "_codex_job", None)
    if job is None:
        return
    from autosound_tcc.ui.tcc import qt_shutdown

    signals = [job.done, *(getattr(job, name) for name in ("progress", "url") if hasattr(job, name))]
    qt_shutdown.stop_or_detach(job, STOP_WAIT_MS, mute=signals)
