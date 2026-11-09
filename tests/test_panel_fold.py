"""Tcc#243: the right column's two cards fold to their header lines; one always stays open.

A real `QSplitter` with two stand-in cards: the fold knows nothing of what is in a card, and a
full window would add nothing to these. Control mode and the real cards are in
`test_control_layout.py`.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
    settings = _Settings({RIGHT_SPLIT_KEY: json.dumps([300, 500])})
    first = _Column(settings)
    _press(first, "plan")
    first.split.close()

    second = _Column(settings)
    assert not second.plan_body.isVisible()
    assert second.focus_body.isVisible()
    _press(second, "plan")
    assert second.plan_body.isVisible()
    plan, focus = second.split.sizes()
    assert abs(plan / (plan + focus) - 3 / 8) < 0.02, "the border the person set"


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


def test_the_arrow_costs_the_header_row_no_width():
    QApplication.instance() or QApplication([])
    split = QSplitter()
    card, head, body = _Column._card()
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
