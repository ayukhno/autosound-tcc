"""Tcc#243: the right column's two cards fold to their header lines; one always stays open.

A real `QSplitter` with two stand-in cards: the fold knows nothing of what is in a card, and a
full window would add nothing to these. Control mode and the real cards are in
`test_control_layout.py`.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QFrame, QHBoxLayout, QLabel, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from autosound_tcc.ui.tcc import i18n  # noqa: E402
from autosound_tcc.ui.tcc.labels import ElidedLabel  # noqa: E402
from autosound_tcc.ui.tcc.panel_fold import RIGHT_SPLIT_KEY, PanelFold  # noqa: E402


class _Settings:
    def __init__(self, data: dict | None = None) -> None:
        self.data = data if data is not None else {}

    def value(self, key, default=None, **_kw):
        return self.data.get(key, default)

    def setValue(self, key, value):  # noqa: N802 (Qt's name)
        self.data[key] = value


class _Column:
    """What `_build_right` builds, without the window around it."""

    def __init__(self, settings: _Settings, height: int = 800) -> None:
        QApplication.instance() or QApplication([])
        self.split = QSplitter()
        self.split.setOrientation(_vertical())
        self.split.setChildrenCollapsible(False)
        self.fold = PanelFold(self.split, settings)
        self.plan, self.plan_head, self.plan_body = self._card()
        self.focus, self.focus_head, self.focus_body = self._card()
        self.split.addWidget(self.plan)
        self.split.addWidget(self.focus)
        self.fold.add("plan", self.plan, self.plan_head, self.plan_body)
        self.fold.add("focus", self.focus, self.focus_head, self.focus_body)
        self.split.splitterMoved.connect(self.fold.remember)  # as `_build_right` does
        self.split.resize(300, height)
        self.split.show()
        QApplication.processEvents()
        self.fold.apply()
        QApplication.processEvents()

    @staticmethod
    def _card():
        card = QFrame()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        head = QWidget()
        row = QHBoxLayout(head)
        row.addWidget(QLabel("title"))
        layout.addWidget(head)
        body = QWidget()
        body.setMinimumHeight(150)
        layout.addWidget(body, stretch=1)
        return card, head, body


def _vertical():
    from PySide6.QtCore import Qt
    return Qt.Orientation.Vertical


def _arrow(column: _Column, name: str):
    return column.fold.arrow(name)


def _press(column: _Column, name: str) -> None:
    _arrow(column, name).click()
    QApplication.processEvents()


def test_a_folded_card_is_its_header_and_the_other_takes_the_height():
    column = _Column(_Settings({RIGHT_SPLIT_KEY: json.dumps([300, 500])}))
    whole = sum(column.split.sizes())
    _press(column, "plan")
    assert not column.plan_body.isVisible()
    assert column.plan_head.isVisible()
    assert column.plan.height() <= column.plan_head.height() + 4
    assert column.focus.height() == whole - column.plan.height()


def test_unfolding_returns_the_size_it_had_and_folding_saves_no_sizes():
    settings = _Settings({RIGHT_SPLIT_KEY: json.dumps([300, 500])})
    column = _Column(settings)
    column.split.setSizes([200, 600])
    QApplication.processEvents()
    held = column.split.sizes()
    _press(column, "focus")
    assert not column.focus_body.isVisible()
    column.split.splitterMoved.emit(10, 1)  # the border pulled while a card is folded
    assert settings.data[RIGHT_SPLIT_KEY] == json.dumps([300, 500])
    _press(column, "focus")
    assert column.focus_body.isVisible()
    assert column.split.sizes() == held


def test_the_fold_survives_a_restart_and_the_saved_border_is_no_sliver():
    settings = _Settings({RIGHT_SPLIT_KEY: json.dumps([200, 600])})
    first = _Column(settings)
    _press(first, "plan")
    first.split.close()

    second = _Column(settings)
    assert not second.plan_body.isVisible()
    assert second.focus_body.isVisible()
    _press(second, "plan")
    assert second.plan_body.isVisible()
    plan, focus = second.split.sizes()
    assert abs(plan / (plan + focus) - 1 / 4) < 0.02, "the border the person set"


def test_folding_the_second_card_is_refused():
    column = _Column(_Settings())
    _press(column, "plan")
    assert not _arrow(column, "focus").isEnabled()
    _press(column, "focus")
    assert column.focus_body.isVisible(), "one card always stays open"
    # Two folds in the settings (an older save, an edited file): the first one holds.
    both = _Column(_Settings({"ui/plan_folded": True, "ui/focus_folded": True}))
    assert not both.plan_body.isVisible()
    assert both.focus_body.isVisible()


def test_a_card_refused_at_the_start_does_not_come_up_folded_later():
    settings = _Settings({"ui/plan_folded": True, "ui/focus_folded": True})
    _Column(settings)
    assert settings.data["ui/plan_folded"] is True
    assert settings.data["ui/focus_folded"] is False, "the refused card's key is cleared"


@pytest.mark.parametrize("raw", ["[Infinity, 500]", "[1e999, 500]", "[3000000000, 500]"])
def test_a_saved_border_out_of_range_is_no_saved_border(raw):
    column = _Column(_Settings({RIGHT_SPLIT_KEY: raw}))
    assert column.fold.read() == []
    plan, focus = column.split.sizes()
    assert abs(plan / (plan + focus) - 3 / 8) < 0.02, "the first-time column"


def test_on_a_real_settings_file_false_is_open_and_an_unfolded_card_stays_unfolded(tmp_path):
    """QSettings reads a saved `false` back as the word: only `type=bool` makes it false, and the
    fake above drops `type=`."""
    QApplication.instance() or QApplication([])

    def from_disk(path) -> QSettings:
        return QSettings(str(path), QSettings.Format.IniFormat)

    first = tmp_path / "first.ini"
    first.write_text("[ui]\nplan_folded=false\n", encoding="utf-8")
    settings = from_disk(first)
    column = _Column(settings)
    assert column.plan_body.isVisible(), "a saved false is open"

    _press(column, "focus")
    _press(column, "focus")
    settings.sync()
    column.split.close()
    # A second file, because Qt shares one parsed copy per path within a process: read through the
    # same path, the value is still the bool that was set and not the word a restart reads.
    restarted = tmp_path / "restarted.ini"
    restarted.write_bytes(first.read_bytes())
    assert "focus_folded=false" in restarted.read_text(encoding="utf-8")
    assert _Column(from_disk(restarted)).focus_body.isVisible(), "unfolded, and so after a restart"


def test_a_request_unfolds_only_the_folded_card_it_names():
    settings = _Settings()
    column = _Column(settings)
    told = []
    column.fold.unfolded.connect(lambda: told.append(True))

    column.fold.reveal("focus")
    assert told == [], "an open card is left alone"

    _press(column, "focus")
    called = []
    column.fold.revealing("focus", lambda *args: called.append((args, column.focus_body.isVisible())))("s1")
    QApplication.processEvents()
    assert called == [(("s1",), True)], "unfolded before the request runs"
    assert settings.data["ui/focus_folded"] is False
    assert _arrow(column, "plan").isEnabled(), "the other card can fold again"

    _press(column, "plan")
    column.fold.reveal("focus")
    QApplication.processEvents()
    assert not column.plan_body.isVisible(), "a request to the open card leaves the folded one folded"


def test_after_unfolding_the_arrows_come_back_enabled_with_the_open_glyph():
    column = _Column(_Settings())
    _press(column, "plan")
    assert _arrow(column, "plan").text() == "▸" and not _arrow(column, "focus").isEnabled()
    _press(column, "plan")
    for name in ("plan", "focus"):
        assert _arrow(column, name).isEnabled() and _arrow(column, name).text() == "▾", name


def test_the_handle_shows_no_resize_cursor_while_a_card_is_folded():
    column = _Column(_Settings())
    handle = column.split.handle(1)
    assert handle.cursor().shape() == Qt.CursorShape.SplitVCursor
    _press(column, "plan")
    assert handle.cursor().shape() == Qt.CursorShape.ArrowCursor
    _press(column, "plan")
    assert handle.cursor().shape() == Qt.CursorShape.SplitVCursor

    restored = _Column(_Settings({"ui/focus_folded": True}))
    assert restored.split.handle(1).cursor().shape() == Qt.CursorShape.ArrowCursor


def test_the_arrow_costs_the_header_row_no_width():
    from tests.test_detail_pane import _no_real_font

    QApplication.instance() or QApplication([])
    split = QSplitter()
    card, head, body = _Column._card()
    fontless = _no_real_font(head.font())
    if fontless:
        pytest.skip(f"a box's width is no font's: {fontless}")
    sub = ElidedLabel("a subtitle that elides", min_width=40, policy=QSizePolicy.Policy.Maximum)
    head.layout().addWidget(sub)
    split.addWidget(card)
    before = head.minimumSizeHint().width()
    PanelFold(split, _Settings()).add("plan", card, head, body, sub)
    assert head.minimumSizeHint().width() <= before


def test_a_body_shown_again_by_its_own_refresh_stays_folded():
    column = _Column(_Settings())
    _press(column, "plan")
    height = column.plan.height()
    column.plan_body.show()  # what a reload does to its own widgets
    QApplication.processEvents()
    assert not column.plan_body.isVisible()
    assert column.plan.height() == height


def test_the_arrow_says_what_it_does_in_the_language_and_a_switch_does_not_unfold():
    column = _Column(_Settings())
    _press(column, "plan")
    i18n.set_language("en")
    assert _arrow(column, "plan").hover_tip.text() == i18n.t("panelUnfold")
    assert _arrow(column, "focus").hover_tip.text() == i18n.t("panelFoldRefused")
    try:
        i18n.set_language("uk")
        column.fold.retranslate()
        assert _arrow(column, "plan").hover_tip.text() == i18n.t("panelUnfold")
    finally:
        i18n.set_language("en")
    assert not column.plan_body.isVisible()
