"""Copying what is on the screen (ui/tcc/copy_menu.py, user request 2026-08-07).

Nothing in TCC could be copied, so a model id or a delay had to be retyped from the screen — which
is how `5.38` becomes `5.83`. What is worth pinning is not that a menu exists but the three things
that would make it useless: copying the ellipsis instead of the text, copying markup instead of
words, and a right-click that also opens a detail pane.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup  # noqa: E402
from autosound_tcc.ui.tcc import copy_menu, i18n  # noqa: E402
from autosound_tcc.ui.tcc.dsp_tree import ChannelRow  # noqa: E402
from autosound_tcc.ui.tcc.labels import ElidedLabel  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_a_hint_reaches_the_clipboard_as_words_not_as_markup():
    """The hints carry what the panel could not fit and what the screen never says — whose bill a
    route is, why a reviewer is clipboard-only. They are rich text, and a regex tag-strip gets both
    halves wrong: entities survive it verbatim and a `<br>` between lines vanishes into nothing."""
    _app()

    assert copy_menu.plain("Helix &amp; MUSWAY<br>second line") == "Helix & MUSWAY\nsecond line"
    assert copy_menu.plain("") == ""


def test_copying_a_shortened_label_gives_the_whole_fact_not_the_ellipsis():
    """`ElidedLabel` rewrites its own text to fit, so `text()` on a narrow one returns "Amp
    (midbass…". Copying that is worse than offering no copy at all."""
    _app()
    label = ElidedLabel("google/deep-research-preview-04-2026", min_width=40)
    label.setFixedWidth(60)
    label._elide()

    assert "…" in label.text()  # the row really is too narrow for it
    assert copy_menu.full_text(label) == "google/deep-research-preview-04-2026"


def test_an_item_with_nothing_behind_it_is_not_offered():
    """A row with no hint should have no "copy hint" entry rather than a dead one."""
    _app()
    from PySide6.QtWidgets import QWidget

    widget = QWidget()
    copy_menu.enable_copy(widget, value="w-L", hint="")

    labels = [label for label, _ in widget.copy_items()]
    assert labels == [i18n.t("copyValue")]


def test_a_source_that_raises_costs_a_menu_item_not_the_menu():
    """Every item is resolved as the menu opens, off live widgets. One that throws must not take
    the right-click with it."""
    _app()
    from PySide6.QtWidgets import QWidget

    def boom() -> str:
        raise RuntimeError("gone")

    widget = QWidget()
    copy_menu.enable_copy(widget, value=boom, row="w-L: HP 80", hint="")

    assert [label for label, _ in widget.copy_items()] == [i18n.t("copyRow")]


def test_a_channel_row_offers_its_value_its_settings_and_its_hint():
    """The hint is the reason this row gets a menu at all: driver and Fs are in it and nowhere on
    screen. It is a `rounded_tooltip`, not a Qt one, so `toolTip()` is empty here — reading it
    means asking the tip."""
    _app()
    group = ProfileGroup(id="physical_outputs", label="Outputs",
                         fields=("hp", "gain_db"))
    row = GroupRow(
        id="w-L", name="w-L",
        raw={"hp": {"f": 80, "type": "LR", "slope": 24}, "gain_db": -2.5},
        identity={"code": "w-L", "driver": {"make": "Audiofrog", "model": "GB25"}},
    )
    channel = ChannelRow(group, row)

    items = dict(channel.copy_items())
    assert items[i18n.t("copyValue")] == "w-L"
    assert "HP: 80 LR4" in items[i18n.t("copyRow")]
    assert "Audiofrog GB25" in items[i18n.t("copyHint")]
    assert "<" not in items[i18n.t("copyHint")]  # words, not the markup the tip renders


def test_a_right_click_on_a_channel_row_does_not_also_open_the_detail_pane():
    """It fired `clicked` on any button, which nobody could see until the row grew a right-click
    menu — then one right-click both opened the pane and showed the menu."""
    _app()
    group = ProfileGroup(id="physical_outputs", label="Outputs", fields=("gain_db",))
    channel = ChannelRow(group, GroupRow(id="w-L", name="w-L", raw={"gain_db": -2.5}))
    opened: list[bool] = []
    channel.clicked.connect(lambda: opened.append(True))

    point = channel.rect().center().toPointF()
    for button in (Qt.MouseButton.RightButton, Qt.MouseButton.LeftButton):
        channel.mousePressEvent(
            QMouseEvent(QMouseEvent.Type.MouseButtonPress, point, point,
                        button, button, Qt.KeyboardModifier.NoModifier)
        )

    assert opened == [True]  # the left click, and only it


def test_a_message_copies_as_text_a_person_can_paste():
    """The bubble holds HTML and keeps a tag-stripped `_plain` for width measurement — which is the
    wrong string to put on a clipboard: it keeps `&amp;` and loses the break between paragraphs."""
    _app()
    from autosound_tcc.ui.tcc.dialog_panel import MessageBubble

    bubble = MessageBubble("agent", "CLAUDE", "Gain <b>&minus;2.5</b> dB<br>Delay 5.38 ms")

    assert bubble.plain_text() == "Gain −2.5 dB\nDelay 5.38 ms"
    # A streamed answer replaces its body as it grows; copy must follow it rather than hand back
    # the first chunk of a finished message.
    bubble.set_html("Gain &minus;2.5 dB<br>Delay 5.38 ms<br>Polarity INV")
    assert bubble.plain_text().endswith("Polarity INV")


def test_a_param_row_offers_the_value_the_whole_row_and_what_was_cut():
    """`_kv_row` is the one place the left panel's facts are built, so one call covers System
    params, Project params and every lone fact. The hint is the untruncated text `ElidedLabel`
    moved behind a hover when the panel was too narrow for it."""
    _app()
    from autosound_tcc.ui.tcc.main_window import _kv_row

    row = _kv_row("Amp (front)", "google/deep-research-preview-04-2026")
    items = dict(row.copy_items())

    assert items[i18n.t("copyValue")] == "google/deep-research-preview-04-2026"
    assert items[i18n.t("copyRow")] == "Amp (front): google/deep-research-preview-04-2026"


def test_a_flaw_row_copies_its_verdict_and_the_reason_behind_it():
    """The map exists so that "do not EQ-boost this null" outlives the session that found it — and
    the reason and the captures it was read off are on hover. A verdict that can only be hovered
    cannot be handed to anybody."""
    _app()
    from autosound_tcc.state.acoustics_view import Flaw
    from autosound_tcc.ui.tcc.main_window import MainWindow

    window = MainWindow()
    flaw = Flaw(f_hz=250, level_db=-12, kind="cabin_null", action="no_boost",
                channels=("w-R",), why="interference, not min-phase",
                evidence=("w-R_1 (sw)",))

    items = dict(window._flaw_row(flaw).copy_items())

    assert items[i18n.t("copyValue")] == "250 Hz · -12 dB"
    assert i18n.t("flawAction_no_boost") in items[i18n.t("copyRow")]
    assert items[i18n.t("copyHint")] == "interference, not min-phase\nw-R_1 (sw)"
