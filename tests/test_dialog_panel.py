"""Headless smoke tests for the AI-dialog panel and the project-param-edit flag flow."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from autosound_tcc.ui.tcc.dialog_panel import DialogPanel, MessageBubble  # noqa: E402
from autosound_tcc.ui.tcc.mock_data import DIALOG  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_dialog_panel_builds_one_bubble_per_mock_message():
    _app()
    panel = DialogPanel()
    bubbles = panel._chat.findChildren(MessageBubble)
    assert len(bubbles) == len(DIALOG)
    assert not panel.is_editing


def test_edit_chip_flow_adds_system_messages_and_toggles_state():
    _app()
    panel = DialogPanel()
    seen = []
    panel.editingChanged.connect(seen.append)

    panel._start_editing("manual")
    assert panel.is_editing
    assert seen == [True]
    bubbles = panel._chat.findChildren(MessageBubble)
    assert len(bubbles) == len(DIALOG) + 1
    assert bubbles[-1].property("class") == "msg msg-sys"

    panel._finish_editing()
    assert not panel.is_editing
    assert seen == [True, False]
    bubbles = panel._chat.findChildren(MessageBubble)
    assert len(bubbles) == len(DIALOG) + 2


def test_reasons_bar_toggles_on_chip_click_when_not_editing():
    _app()
    panel = DialogPanel()
    assert panel._reasons_bar.isHidden()
    panel._on_chip_clicked()
    assert not panel._reasons_bar.isHidden()
    panel._on_chip_clicked()
    assert panel._reasons_bar.isHidden()


def test_retranslate_does_not_leave_stale_bubbles_behind():
    """Regression: clearing the chat with deleteLater() alone (no setParent(None) first) leaves
    the old widgets as real children of self._chat until the next event-loop pass -- calling
    retranslate() without ever spinning the event loop (exactly what happens on a synchronous
    language switch) would double- then triple-count bubbles here without the fix."""
    _app()
    panel = DialogPanel()
    panel.retranslate()
    assert len(panel._chat.findChildren(MessageBubble)) == len(DIALOG)
    panel.retranslate()
    assert len(panel._chat.findChildren(MessageBubble)) == len(DIALOG)


def test_a_markdown_table_is_rendered_as_a_table():
    """Models answer equipment questions with one — "| Код | Роль | Драйвер |" — and the
    transcript showed the pipes and dashes raw, which makes a correct answer look broken."""
    from autosound_tcc.ui.tcc.dialog_panel import _markdown

    html = _markdown("| Код | Роль |\n|---|---|\n| tw-L/R | Твітер |")

    assert "<table" in html and "<th align='left'>Код</th>" in html
    assert "<td>tw-L/R</td>" in html
    assert "|---|" not in html  # the separator row is structure, not content


def test_text_around_a_table_keeps_its_place():
    from autosound_tcc.ui.tcc.dialog_panel import _markdown

    html = _markdown("before\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nafter")

    assert html.index("before") < html.index("<table") < html.index("after")


def test_a_stray_pipe_line_is_not_mistaken_for_a_table():
    from autosound_tcc.ui.tcc.dialog_panel import _markdown

    html = _markdown("| just one line |")

    assert "<table" not in html


def test_the_role_line_is_measured_with_its_letter_spacing():
    """`.msg-who` sets `letter-spacing: 1px`, which Qt renders but does not report through
    `fontMetrics()` — so the bubble came out a pixel per character short and "ARBITER · YOU" lost
    its U to the border."""
    from autosound_tcc.ui.tcc.dialog_panel import MessageBubble

    _app()
    role = "ARBITER · YOU"
    bubble = MessageBubble("user", role, "Hi")

    bare = bubble._who_label.fontMetrics().horizontalAdvance(role) + 28

    assert bubble.natural_width >= bare + len(role)


def test_a_long_message_keeps_the_panel_pinned_to_the_bottom():
    """A bubble's height settles over several layout passes, so a single scroll lands at whatever
    it was one pass ago — a long message ended up with only its top edge on screen."""
    from autosound_tcc.ui.tcc.dialog_panel import DialogPanel

    _app()
    panel = DialogPanel()
    panel._stick_to_bottom = True

    bar = panel._scroll.verticalScrollBar()
    bar.setRange(0, 500)  # an empty panel has no range to scroll away from

    panel._on_scroll_value_changed(0)  # scrolled up by hand
    assert panel._stick_to_bottom is False

    panel._on_scroll_value_changed(bar.maximum())  # back at the bottom
    assert panel._stick_to_bottom is True


def test_the_composer_grows_for_a_pasted_paragraph_not_only_for_newlines():
    """User, 2026-08-21: "коли в діалог вставляю текст на декілька строк - висота поля не
    збільшується".

    The growth was written and worked for text carrying real newlines, which is why it looked
    present: `contentsChanged` fires with the block count already final. A pasted paragraph is ONE
    block that wraps, and the wrap is computed a layout pass later — the field measured itself
    before that and stayed one line tall. Both shapes are asserted here, and the shrink back with
    them: a field that only ever grows is the same bug facing the other way.
    """
    app = _app()
    panel = DialogPanel()
    panel.resize(420, 700)
    panel.show()
    app.processEvents()
    field = panel._input
    one_line = field.height()

    def paste(text: str) -> int:
        data = QMimeData()
        data.setText(text)
        field.insertFromMimeData(data)
        for _ in range(3):  # the wrap lands on a later pass; that is the whole point
            app.processEvents()
        return field.height()

    wrapped = paste("слово " * 60)
    assert wrapped > one_line, "a pasted paragraph wraps, so the field has to grow with it"

    field.clear()
    app.processEvents()
    assert field.height() == one_line, "and shrinks back when the text goes"

    assert paste("\n".join(f"line {i}" for i in range(5))) > one_line

    field.clear()
    tall = paste("\n".join(f"line {i}" for i in range(40)))
    assert tall <= paste("\n".join(f"line {i}" for i in range(200))), \
        "past the cap the field stops growing and scrolls instead of eating the transcript"


def test_being_asked_which_model_is_not_rendered_as_a_failure():
    """SKL-023: the reviewer exits 3 with the key's OWN list of callable models. Rendering that as
    "the Critic failed" hides the one thing that fixes it — and sends the Arbiter to the clipboard
    for a channel that works and is simply missing a name."""
    from PySide6.QtWidgets import QLabel

    _app()
    panel = DialogPanel()
    before = len(panel._bubbles)

    panel.add_critique({
        "mode": "choose_model",
        "models": ["gemini-pro-latest", "gemini-flash-latest"],
        "detail": ">> Модель рецензента не задано.",
    })

    said = " ".join(
        label.text()
        for bubble in panel._bubbles[before:]
        for label in bubble.findChildren(QLabel)
    )
    assert "gemini-pro-latest" in said
    assert "gemini-flash-latest" in said
    assert "critic-env" in said, "the answer has to say WHERE the choice is pinned"


def test_a_bubble_measures_its_text_once_not_once_per_resize_pixel():
    """`natural_width` shapes the WHOLE message as one line, and `resizeEvent` asks every bubble
    for it — so dragging the splitter one pixel re-shaped the entire transcript, and it got worse
    the longer the session ran.

    The cache must not freeze, though: the fonts really do change under it twice (stylesheet
    polish, and A-/A+), and a frozen pre-stylesheet measurement is the bug the on-demand
    measurement was introduced to fix in the first place.
    """
    _app()
    bubble = MessageBubble("Arbiter", "ARBITER · YOU", "<p>" + "word " * 400 + "</p>")

    calls: list = []
    real = bubble._body.fontMetrics
    bubble._body.fontMetrics = lambda: (calls.append(1), real())[1]

    first = bubble.natural_width
    for _ in range(50):  # fifty resize events, as one splitter drag
        assert bubble.natural_width == first
    assert len(calls) == 1, "measured once, then remembered"

    bubble.set_html("<p>" + "word " * 800 + "</p>")
    assert bubble.natural_width != first, "a streamed answer must not keep its first width"


def test_a_turn_that_ends_in_a_dropped_connection_says_what_to_do():
    """The failure arrives as ordinary assistant TEXT, so nothing upstream marks the turn as
    failed: the session sits there looking ready, the next message goes nowhere, and the app
    reads as hung. The Arbiter hit this twice and found the way out by quitting TCC entirely —
    nothing on screen said so (2026-09-11)."""
    from autosound_tcc.ui.tcc.dialog_panel import turn_ended_in_a_dropped_connection as dropped

    assert dropped("API Error: The response stopped arriving. The response above may be incomplete.")
    assert dropped("Failed to authenticate: OAuth session expired and could not be refreshed")

    # And an answer that merely TALKS about errors is still an answer.
    assert not dropped("Я перевірив лог — там немає жодної помилки, канал справний.")
    assert not dropped("")


def test_the_panel_names_the_way_out_rather_than_only_the_failure():
    from autosound_tcc.ui.tcc import i18n

    _app()
    panel = DialogPanel()
    before = len(panel._chat.findChildren(MessageBubble))

    panel._live_text = "API Error: The response stopped arriving."
    panel._on_turn_done()

    bubbles = panel._chat.findChildren(MessageBubble)
    assert len(bubbles) == before + 1, "the panel said something"
    said = bubbles[-1]._plain
    assert i18n.t("sessionNew").lower() in said.lower(), (
        f"it must name the control that fixes it, not just report the failure: {said!r}")


def test_right_clicking_a_bubbles_text_opens_our_copy_menu_not_qts():
    """The Arbiter, 2026-09-13, with a screenshot: right-clicking the text of a message showed Qt's
    own "Copy / Select All". The bubble's menu hung on the frame, and the selectable label on top of
    it answered the click first — so "copy the whole message" was one menu nobody could reach.

    Wanted, in their words: one line that copies everything, and "copy selected" when something is
    selected."""
    from PySide6.QtCore import Qt

    from autosound_tcc.ui.tcc import i18n

    _app()
    bubble = MessageBubble("Agent", "AGENT", "<p>alpha beta gamma</p>")

    assert bubble._body.contextMenuPolicy() == Qt.ContextMenuPolicy.NoContextMenu, \
        "the text hands the right-click to the bubble"
    assert [label for label, _ in bubble.copy_items()] == [i18n.t("copyMessage")], \
        "nothing selected: one line, copy everything"

    bubble._body.setSelection(0, 5)
    items = bubble.copy_items()
    assert [label for label, _ in items] == [i18n.t("copySelection"), i18n.t("copyMessage")]
    assert items[0][1] == "alpha"
    assert i18n.T["en"]["copyMessage"] == "Copy all"
    assert i18n.T["en"]["copySelection"] == "Copy selected"


def test_a_refused_review_says_why_and_where_the_package_is():
    """hub #154 §5: no answer is not "the Critic failed" with a package tail — it is the reasons,
    and the package the clipboard step takes."""
    from PySide6.QtWidgets import QLabel

    _app()
    panel = DialogPanel()
    before = len(panel._bubbles)

    panel.add_critique({
        "mode": "refused",
        "detail": "· CLI 'agy': quota exhausted",
        "package": "process/reviews/x-critic-package.md",
    })

    said = " ".join(
        label.text()
        for bubble in panel._bubbles[before:]
        for label in bubble.findChildren(QLabel)
    )
    assert "quota exhausted" in said
    assert "process/reviews/x-critic-package.md" in said



def test_a_proposal_is_the_generator_s_not_a_ledger_record():
    """tcc#59, finding 63: the Generator's `propose_change` arrived as the blue «SYSTEM · ledger»
    bubble, so its own proposal read as something already recorded."""
    from autosound_tcc.ui.tcc.dialog_panel import DialogPanel

    _app()
    panel = DialogPanel()
    panel.add_proposal("<b>m-L</b> · EQ: — → <b>PK 2251 Hz</b>")
    bubble = panel._bubbles[-1]
    assert bubble.property("class") == "msg msg-gen"
    assert "SYSTEM" not in bubble.findChildren(QLabel)[0].text()


def test_tccs_own_lines_are_signed_tcc_and_only_a_record_says_ledger():
    """Finding 93 (tcc#80): «Рецензент тепер …», «TCC почав хід …» came as SYSTEM · LEDGER — TCC
    talking about itself, labelled as something recorded. TCC is the default now; a line that IS a
    record (a banked change, the journal's closing report) says ledger."""
    from autosound_tcc.ui.tcc import dialog_panel

    _app()
    panel = DialogPanel()
    panel._add_system_message("the reviewer is now X")
    assert panel._bubbles[-1]._who_label.text() == "SYSTEM · TCC"
    panel._add_system_message("v_007 banked", role=dialog_panel.SYS_ROLE_LEDGER)
    assert panel._bubbles[-1]._who_label.text() == "SYSTEM · ledger"


def _hms(at: float) -> str:
    import time

    return time.strftime("%H:%M:%S", time.localtime(at))


def test_a_new_bubble_says_when_beside_who_said_it(monkeypatch):
    """tcc#100, finding 110: the Arbiter waited on a slow first turn and could not read how long it
    took — the bubbles said who spoke, not when («може додати тайм-маркери для повідомлень?»)."""
    import time

    app = _app()
    panel = DialogPanel()
    monkeypatch.setattr(time, "time", lambda: 1_790_000_000.0)
    panel._add_system_message("the reviewer is now X")
    bubble = panel._bubbles[-1]

    assert bubble._time_label.text() == _hms(1_790_000_000.0)
    assert bubble._who_label.text() == "SYSTEM · TCC", "the role keeps its own words"

    panel.resize(700, 500)
    panel.show()
    app.processEvents()
    who, when = bubble._who_label.geometry(), bubble._time_label.geometry()
    assert not bubble._time_label.isHidden()
    assert abs(who.center().y() - when.center().y()) <= 2, "on the role line, not under it"
    assert when.left() >= who.right(), "beside who spoke"


def test_the_role_line_is_measured_with_its_time():
    """The width `natural_width` gives a bubble has to hold the whole role line — a stamp left out
    of it is the lost U of "ARBITER · YOU" again, this time with the seconds cut off."""
    app = _app()
    role = "ARBITER · YOU"
    bubble = MessageBubble("user", role, "Hi", at=1_790_000_000.0)
    stamp = bubble._time_label.text()

    bare = (bubble._who_label.fontMetrics().horizontalAdvance(role) + len(role)
            + bubble._time_label.fontMetrics().horizontalAdvance(stamp) + 28)
    assert bubble.natural_width >= bare
    assert bubble.natural_width > MessageBubble("user", role, "Hi").natural_width

    bubble.setFixedWidth(bubble.natural_width)
    bubble.show()
    app.processEvents()
    assert bubble._time_label.width() >= bubble._time_label.sizeHint().width(), "not squeezed"
    assert bubble._time_label.geometry().right() <= bubble.contentsRect().right()


def test_the_opening_line_keeps_its_own_time_when_the_session_puts_it_back(monkeypatch, tmp_path):
    """The one bubble the panel rebuilds: the Arbiter's first line, held across `attach_agent`'s
    clear. It comes back with the moment it was said, not the moment it was put back (tcc#100)."""
    import time

    from PySide6.QtCore import QObject, Signal

    from autosound_tcc.core.signal_bus import SignalBus

    class _Worker(QObject):
        chunk = Signal(object)
        turn_done = Signal()
        failed = Signal(str)

    _app()
    panel = DialogPanel()
    said = 1_790_000_000.0
    monkeypatch.setattr(time, "time", lambda: said)
    panel._input.setText("Привіт")
    panel._on_send()

    monkeypatch.setattr(time, "time", lambda: said + 3_725)  # an hour, two minutes, five seconds on
    panel.attach_agent(_Worker(), SignalBus(tmp_path))

    first = panel._bubbles[0]
    assert "Привіт" in first.plain_text()
    assert first._time_label.text() == _hms(said)


def test_a_message_with_no_time_of_its_own_shows_none():
    """The dialog keeps no history with times in it, and the demo transcript was never said by
    anyone. Neither gets the moment it was drawn — a wrong time reads as a right one (tcc#100)."""
    _app()
    panel = DialogPanel()
    assert panel._bubbles, "the demo transcript is up"
    for bubble in panel._bubbles:
        assert bubble._time_label.isHidden() and not bubble._time_label.text()

    bare = MessageBubble("gen", "GENERATOR · X", "Hi")
    assert bare._time_label.isHidden() and not bare._time_label.text()


def test_an_answer_to_a_plain_question_is_labelled_ask_not_critic():
    """tcc#116: a question to the reviewer is not a review, and its answer must not read as one."""
    _app()
    panel = DialogPanel()

    panel.add_critique({"mode": "answered", "role": "ask", "text": "pong",
                        "model": "gemini-3.1-pro-high"})
    assert panel._bubbles[-1]._role == "ASK · gemini-3.1-pro-high"

    panel.add_critique({"mode": "answered", "role": "critic", "text": "too hot",
                        "model": "gemini-3.1-pro-high"})
    assert panel._bubbles[-1]._role == "Critic · gemini-3.1-pro-high"
