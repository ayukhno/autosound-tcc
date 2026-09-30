"""`ElidedLabel` and `ElidedButton` (ui/tcc/labels.py): a label and a button that shorten
themselves only when they have to."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QSizePolicy  # noqa: E402

from autosound_tcc.ui.tcc import i18n  # noqa: E402
from autosound_tcc.ui.tcc.labels import ElidedButton, ElidedLabel  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication([])


def _ui_texts(longest: int = 60) -> list:
    return sorted({
        text
        for lang in ("en", "uk")
        for text in i18n.T[lang].values()
        if 3 < len(text) <= longest and "\n" not in text and "{" not in text
    })


def test_a_label_given_the_width_it_asked_for_shows_its_whole_text():
    # The hint was measured in whole pixels and the eliding in fractions of one, so a text 177.08 px
    # wide asked for 177 and lost its last letters in exactly the room it asked for: the footer's
    # reviewer status read "Критик: ще не викликав…" with nothing beside it (TODO F-045).
    texts = _ui_texts()
    label = ElidedLabel(min_width=10, policy=QSizePolicy.Policy.Maximum)
    label.show()
    cut = []
    try:
        for text in texts:
            label.setText(text)
            label.resize(label.sizeHint().width(), label.sizeHint().height())
            if label.text() != text:
                cut.append(f"{text!r} -> {label.text()!r}")
    finally:
        label.close()
    assert not cut, f"{len(cut)} of {len(texts)} cut in their own width, e.g. " + "; ".join(cut[:3])


def test_a_button_given_the_width_it_asked_for_shows_its_whole_text():
    """The same F-045 on `ElidedButton` (tcc#96, fix round 5): its hint is rounded UP from the
    text's fractional width and the fit is judged in fractions, or a whole-pixel hint one
    fraction short read «Control mo…» on the mode button with the whole window to spare (the
    final review of W-4, Windows fonts). Every UI string, at exactly the width it asked for:
    whole. About half of them have a fraction the whole-pixel measure rounds away."""
    texts = _ui_texts()
    button = ElidedButton()
    button.show()
    cut = []
    try:
        for text in texts:
            button.setText(text)
            button.resize(button.sizeHint().width(), 22)
            if button.fit_text() != text:
                cut.append(f"{text!r} -> {button.fit_text()!r}")
    finally:
        button.close()
    assert not cut, f"{len(cut)} of {len(texts)} cut in their own width, e.g. " + "; ".join(cut[:3])


def test_a_button_never_draws_a_word_wider_than_its_room():
    """Finding 119, the re-review of fix round 5: «закрити ✕» in the pane's head (`holds=True`)
    read «закрит» at a 1100-px window and «закри» at the window's floor -- its leading word,
    drawn into less room than the word takes, clipped at the edge. The word is the fallback
    only where it fits; narrower, what is drawn is the text elided to the room, so nothing drawn
    is ever wider than the room -- by Qt's whole-pixel measure, the one its elision keeps to (in
    fractions it hands a room of 30 px a «зак…» of 30.09). A button that does not hold (the
    footer's) keeps its word at its own floor, which is the word's width."""
    i18n.set_language("uk")
    try:
        for holds in (True, False):
            button = ElidedButton(i18n.t("close"), holds=holds)
            button.setProperty("class", "d-close")
            button.show()
            try:
                full, word = button.text(), button.text().split(" ")[0]
                chrome, metrics = button._chrome(), button.fontMetrics()
                assert word != full and metrics.horizontalAdvance(word) > 0
                wide = []
                for width in range(button.sizeHint().width(), chrome - 1, -1):
                    button.resize(width, 22)
                    shown, room = button.fit_text(), width - chrome
                    if metrics.horizontalAdvance(shown) > room:
                        wide.append((width, shown))
                    assert shown in (full, word) or shown.endswith("…") or shown == "", shown
                assert not wide, f"holds={holds}: drawn wider than the room at {wide[:4]}"
                if not holds:
                    button.resize(button.minimumSizeHint().width(), 22)
                    assert button.fit_text() == word, "at its floor, the leading word whole"
            finally:
                button.close()
    finally:
        i18n.set_language("en")
