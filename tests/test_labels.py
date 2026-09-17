"""`ElidedLabel` (ui/tcc/labels.py): a label that shortens itself only when it has to."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QSizePolicy  # noqa: E402

from autosound_tcc.ui.tcc import i18n  # noqa: E402
from autosound_tcc.ui.tcc.labels import ElidedLabel  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication([])


def test_a_label_given_the_width_it_asked_for_shows_its_whole_text():
    # The hint was measured in whole pixels and the eliding in fractions of one, so a text 177.08 px
    # wide asked for 177 and lost its last letters in exactly the room it asked for: the footer's
    # reviewer status read "Критик: ще не викликав…" with nothing beside it (TODO F-045).
    texts = sorted({
        text
        for lang in ("en", "uk")
        for text in i18n.T[lang].values()
        if 3 < len(text) <= 60 and "\n" not in text and "{" not in text
    })
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
