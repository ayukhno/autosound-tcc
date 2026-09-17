"""The feedback modal — where a tester's words actually go.

The one behaviour worth a test here is the destination, not the rich-text editor: a modal that
looks like it sent something and did not is worse than no modal.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc.feedback_dialog import FeedbackDialog  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])
def test_with_no_form_configured_the_only_destination_is_github(monkeypatch):
    """The form radio was the DEFAULT and its URL is empty, so Send copied the text, opened
    nothing, and closed as though it had been sent. A beta report died there in silence."""
    from PySide6.QtGui import QDesktopServices

    _app()
    dialog = FeedbackDialog("https://github.com/ayukhno/autosound-tcc/issues/new", "")
    dialog._editor.setPlainText("the window would not open")
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))

    assert dialog._radio_github.isChecked()
    assert dialog._radio_form.isHidden() or not dialog._radio_form.isVisible()

    dialog._on_send()

    assert len(opened) == 1 and "issues/new" in opened[0]


def test_opening_the_dialog_with_no_form_raises_nothing_at_all():
    """The branch that hides the form also checks the GitHub radio on, and `toggled` reached the
    label sync before the Send button it writes to had been built:
    `AttributeError: 'FeedbackDialog' object has no attribute '_send'` (user, 2026-08-21, off the
    log). This is the configuration a beta install actually ships with.

    Asserted through `sys.excepthook` rather than by expecting a raise, because that is where the
    failure surfaced: an exception inside a Qt slot does not propagate to the code that triggered
    the signal — Qt reports it and carries on, the constructor finishes, and the label gets set a
    few lines later anyway. The dialog WORKED. What the Arbiter got was a red banner over a
    window that was fine, which is its own kind of broken and invisible to a test that only looks
    at the finished widget.
    """
    import sys

    _app()
    caught: list = []
    original, sys.excepthook = sys.excepthook, lambda *exc: caught.append(exc)
    try:
        dialog = FeedbackDialog("https://github.com/example/repo/issues/new", "")
    finally:
        sys.excepthook = original

    assert caught == [], f"constructing the dialog reported {caught}"
    assert dialog._radio_github.isChecked()
    assert dialog._send.text(), "and Send says where it is going"


# ---- screenshots (SKL-019) -----------------------------------------------------------------
#
# The half that belongs to the window is not the upload — it is showing a person what they are
# about to publish. A screenshot of a DSP window carries a file path with somebody's name in it,
# the car, the installer's branding, and a public repository does not un-publish.


def _png(path, colour="#3b6ea5"):
    """A real image file, because the strip refuses what Qt cannot draw."""
    from PySide6.QtGui import QColor, QPixmap

    pixmap = QPixmap(40, 30)
    pixmap.fill(QColor(colour))
    pixmap.save(str(path), "PNG")
    return path


def _dialog_with_shots(monkeypatch, tmp_path, shots, publish=None):
    from autosound_tcc.ui.tcc import feedback_dialog as fd

    monkeypatch.setattr(fd.issue_assets, "available", lambda: True)
    if publish is not None:
        monkeypatch.setattr(fd.issue_assets, "publish", publish)
    _app()
    dialog = FeedbackDialog("https://github.com/ayukhno/autosound-tcc/issues/new", "")
    dialog._shots = [_png(tmp_path / name) for name in shots]
    dialog._rebuild_strip()
    return dialog


def test_the_control_is_hidden_where_nothing_could_carry_the_pictures(monkeypatch):
    """The gate's uploader arrives with a method newer than this pin (#60). A control that
    attaches images nothing can publish is a promise the Send button then breaks — the same
    posture `eq_export` keeps for a format the method does not have yet."""
    from autosound_tcc.ui.tcc import feedback_dialog as fd

    monkeypatch.setattr(fd.issue_assets, "available", lambda: False)
    _app()
    dialog = FeedbackDialog("https://github.com/ayukhno/autosound-tcc/issues/new", "")

    assert not dialog._shots_box.isVisibleTo(dialog)


def test_every_picture_is_shown_with_a_way_to_drop_it(monkeypatch, tmp_path):
    """This is the consent step, and it is the ONLY thing in either half that ever sees what is in
    the frame. So: a thumbnail big enough to recognise a name, and an × on each one."""
    dialog = _dialog_with_shots(monkeypatch, tmp_path, ["one.png", "two.png"])

    cards = [dialog._strip.itemAt(i).widget() for i in range(dialog._strip.count())]
    cards = [c for c in cards if c is not None]
    assert len(cards) == 2
    from PySide6.QtWidgets import QLabel, QPushButton

    for card in cards:
        shot = card.findChild(QLabel)
        assert shot.pixmap() is not None and not shot.pixmap().isNull()
        assert card.findChildren(QPushButton), "each picture can be dropped on its own"
    assert dialog._shots_warn.isVisibleTo(dialog), "the warning comes WITH the pictures"


def test_a_picture_dropped_is_a_picture_not_sent(monkeypatch, tmp_path):
    """`consented=True` means "these ones", and this is what makes that true rather than asserted:
    what is sent is what was left on screen."""
    sent = {}

    def publish(paths, *, consented, **kwargs):
        from autosound_tcc.core.issue_assets import Published

        sent["paths"], sent["consented"] = list(paths), consented
        return Published(urls=tuple(f"https://raw/{p.name}" for p in paths))

    dialog = _dialog_with_shots(monkeypatch, tmp_path, ["keep.png", "private.png"], publish)
    dialog._drop_shot(tmp_path / "private.png")

    from PySide6.QtGui import QDesktopServices

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    dialog._editor.setPlainText("the window would not open")
    dialog._on_send()

    assert [p.name for p in sent["paths"]] == ["keep.png"]
    assert sent["consented"] is True
    assert len(opened) == 1 and "keep.png" in opened[0], "the surviving picture is in the body"
    assert "private.png" not in opened[0]


def test_a_partial_upload_posts_nothing_and_says_what_is_already_public(monkeypatch, tmp_path):
    """Two of three uploaded and the third failed means two pictures ARE public. Reporting only
    the failure would leave a person believing nothing was sent."""

    def publish(paths, *, consented, **kwargs):
        from autosound_tcc.core.issue_assets import Published

        return Published(urls=("https://raw/a", "https://raw/b"), problem="gh: rate limited")

    dialog = _dialog_with_shots(monkeypatch, tmp_path, ["a.png", "b.png", "c.png"], publish)

    from PySide6.QtGui import QDesktopServices

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    dialog._on_send()

    assert opened == [], "nothing is posted when the pictures did not all get there"
    said = dialog._shots_problem.text()
    assert "rate limited" in said and "2" in said
    assert dialog._shots_problem.isVisibleTo(dialog)


def test_a_file_qt_cannot_draw_does_not_travel_unseen(monkeypatch, tmp_path):
    """If it cannot be shown it cannot be checked, and this whole step exists to check."""
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a png at all")
    dialog = _dialog_with_shots(monkeypatch, tmp_path, ["fine.png"])
    dialog._shots.append(broken)
    dialog._rebuild_strip()

    assert [p.name for p in dialog._shots] == ["fine.png"]
    assert "broken.png" in dialog._shots_problem.text()


def test_the_form_route_does_not_offer_pictures(monkeypatch, tmp_path):
    """A public form takes text off the clipboard and nothing else. Withdrawing the offer at Send
    would be worse than never making it."""
    from autosound_tcc.ui.tcc import feedback_dialog as fd

    monkeypatch.setattr(fd.issue_assets, "available", lambda: True)
    _app()
    dialog = FeedbackDialog("https://github.com/x/y/issues/new", "https://forms.example/x")

    dialog._radio_form.setChecked(True)
    assert not dialog._shots_box.isVisibleTo(dialog)
    dialog._radio_github.setChecked(True)
    assert dialog._shots_box.isVisibleTo(dialog)


def test_the_body_puts_the_words_first_and_the_pictures_under_them():
    """A report that opens with three screenshots is a bug report with no words in it."""
    from autosound_tcc.ui.tcc.feedback_dialog import body_with_shots

    assert body_with_shots("it would not open", ()) == "it would not open"
    got = body_with_shots("it would not open", ("https://raw/1.png", "https://raw/2.png"))
    assert got.startswith("it would not open")
    assert got.count("![") == 2 and got.index("https://raw/1.png") < got.index("https://raw/2.png")


def test_the_control_appears_exactly_when_this_build_can_publish(monkeypatch):
    """Tied to the capability rather than to a version: the control showed up on its own the day
    the pin reached the method that has the uploader, and it would go away again on its own if a
    build ever shipped without one. Nothing here needs editing when either happens."""
    from autosound_tcc.core import issue_assets
    from autosound_tcc.ui.tcc import feedback_dialog as fd

    _app()
    dialog = fd.FeedbackDialog("https://github.com/x/y/issues/new", "")

    assert dialog._shots_box.isVisibleTo(dialog) is issue_assets.available()


# ---- the form: a report without GitHub (TODO F-042) ----------------------------------------
#
# The Arbiter's decisions of 2026-09-17: text only, straight from the window, into his form, with
# who wrote it, what kind it is and — for a problem — how far it stops the tuning, each its own
# question. What a person must be able to trust is the word "sent": it is said only when the form
# confirmed.

_GITHUB = "https://github.com/x/y/issues/new"
_FORM = "https://forms.example/post"


def _form_dialog(monkeypatch, send=None, **kwargs):
    from autosound_tcc.core import form_report
    from autosound_tcc.ui.tcc import feedback_dialog as fd

    monkeypatch.setattr(fd.form_report, "versions_line", lambda lang: f"TCC 9 · lang={lang}")
    if send is None:
        def send(report, url):
            return form_report.Sent(True)
    calls = []

    def recording(report, url):
        calls.append((report, url))
        return send(report, url)

    monkeypatch.setattr(fd.form_report, "send", recording)
    _app()
    dialog = FeedbackDialog(_GITHUB, _FORM, **kwargs)
    dialog._radio_form.setChecked(True)
    return dialog, calls


def _wait_for_send(dialog):
    probe = dialog._sending
    assert probe is not None, "Send started nothing"
    probe._thread.join(5)
    dialog._poll_send()


def _ready(dialog, kind="wish", words="a darker theme, please", sender="Олег, @oleg"):
    dialog._sender.setText(sender)
    dialog._kind_buttons[kind].setChecked(True)
    dialog._editor.setPlainText(words)


def test_the_form_route_sends_each_answer_and_says_sent(monkeypatch):
    from autosound_tcc.ui.tcc import i18n

    dialog, calls = _form_dialog(monkeypatch)
    _ready(dialog)

    dialog._on_send()
    _wait_for_send(dialog)

    assert len(calls) == 1
    report, url = calls[0]
    assert url == _FORM
    assert (report.sender, report.kind, report.impact) == ("Олег, @oleg", "wish", "")
    assert "a darker theme, please" in report.message
    assert report.versions.startswith("TCC 9 · lang=")
    assert dialog._status.text() == i18n.t("fbSent")
    assert not dialog._send.isEnabled(), "one report is one row: Send does not stay armed"


def test_who_wrote_is_remembered_for_the_next_report(monkeypatch):
    dialog, _calls = _form_dialog(monkeypatch)
    _ready(dialog, sender="Олег, @oleg")

    dialog._on_send()
    _wait_for_send(dialog)
    again, _calls = _form_dialog(monkeypatch)

    assert again._sender.text() == "Олег, @oleg"


def test_a_report_that_does_not_say_who_wrote_it_is_not_sent(monkeypatch):
    from autosound_tcc.ui.tcc import i18n

    dialog, calls = _form_dialog(monkeypatch)
    _ready(dialog, sender="  ")

    dialog._on_send()

    assert calls == [] and dialog._sending is None
    assert dialog._status.text() == i18n.t("fbNoSender")


def test_a_problem_asks_how_far_it_stops_the_tuning(monkeypatch):
    from autosound_tcc.ui.tcc import i18n

    dialog, calls = _form_dialog(monkeypatch)
    _ready(dialog, kind="problem", words="the window froze")
    assert dialog._impact_row.isVisibleTo(dialog)

    dialog._on_send()
    assert calls == [] and dialog._status.text() == i18n.t("fbNoImpact")

    dialog._impact_buttons["stops"].setChecked(True)
    dialog._on_send()
    _wait_for_send(dialog)
    assert calls[0][0].impact == "stops"


def test_a_wish_is_not_asked_how_far_it_stops_anything(monkeypatch):
    dialog, _calls = _form_dialog(monkeypatch)
    _ready(dialog, kind="wish")

    assert not dialog._impact_row.isVisibleTo(dialog)


def test_what_goes_with_the_words_is_on_screen_before_send(monkeypatch):
    dialog, _calls = _form_dialog(
        monkeypatch, kind="problem", attachment="[Autosound TCC]\n  version 9")

    shown = dialog._goes_with.toPlainText()
    assert "TCC 9 · lang=" in shown and "[Autosound TCC]" in shown


def test_the_attachment_travels_under_the_words(monkeypatch):
    dialog, calls = _form_dialog(monkeypatch, kind="problem", attachment="[Autosound TCC]\n  version 9")
    _ready(dialog, kind="problem", words="the window froze")
    dialog._impact_buttons["workaround"].setChecked(True)

    dialog._on_send()
    _wait_for_send(dialog)

    message = calls[0][0].message
    assert message.index("the window froze") < message.index("[Autosound TCC]")


def test_a_send_the_form_did_not_confirm_is_not_called_sent_and_the_report_is_kept(monkeypatch):
    from PySide6.QtGui import QGuiApplication

    from autosound_tcc.core import form_report
    from autosound_tcc.ui.tcc import i18n

    dialog, _calls = _form_dialog(
        monkeypatch, send=lambda report, url: form_report.Sent(False, "unconfirmed", "HTTP 200"))
    _ready(dialog, words="the window froze")

    dialog._on_send()
    _wait_for_send(dialog)

    assert i18n.t("fbNoConfirm") in dialog._status.text()
    kept = QGuiApplication.clipboard().text()
    assert "the window froze" in kept and "Олег, @oleg" in kept, "nothing a person wrote is lost"
    assert dialog._send.isEnabled(), "and it can be tried again"


def test_a_network_failure_is_said_in_its_own_words(monkeypatch):
    from autosound_tcc.core import form_report

    dialog, _calls = _form_dialog(
        monkeypatch, send=lambda report, url: form_report.Sent(False, "network", "no route to host"))
    _ready(dialog)

    dialog._on_send()
    _wait_for_send(dialog)

    assert "no route to host" in dialog._status.text()


def test_an_empty_report_is_not_sent(monkeypatch):
    from autosound_tcc.ui.tcc import i18n

    dialog, calls = _form_dialog(monkeypatch)
    _ready(dialog, words="   ")

    dialog._on_send()

    assert calls == [] and dialog._sending is None
    assert dialog._status.text() == i18n.t("fbEmpty")


def test_the_dialog_stays_open_while_its_report_is_on_the_way(monkeypatch):
    import threading

    from autosound_tcc.core import form_report

    gate = threading.Event()

    def slow(report, url):
        gate.wait(5)
        return form_report.Sent(True)

    dialog, _calls = _form_dialog(monkeypatch, send=slow)
    _ready(dialog)
    dialog.show()

    dialog._on_send()
    dialog.reject()
    assert dialog.isVisible(), "closing mid-send would leave nobody to say whether it arrived"

    gate.set()
    _wait_for_send(dialog)
    dialog.reject()
    assert not dialog.isVisible()


def test_the_form_questions_are_asked_only_on_the_route_that_carries_them(monkeypatch):
    dialog, _calls = _form_dialog(monkeypatch)
    rows = lambda: (dialog._sender_row, dialog._kind_row, dialog._goes_with)  # noqa: E731

    assert all(row.isVisibleTo(dialog) for row in rows())
    dialog._radio_github.setChecked(True)
    assert not any(row.isVisibleTo(dialog) for row in rows())


def test_the_github_route_opens_the_link_its_caller_builds(monkeypatch):
    from PySide6.QtGui import QDesktopServices

    dialog, _calls = _form_dialog(monkeypatch, github_link=lambda body: f"{_GITHUB}?what={body}")
    dialog._radio_github.setChecked(True)
    dialog._editor.setPlainText("froze")
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))

    dialog._on_send()

    assert opened == [f"{_GITHUB}?what=froze"]
