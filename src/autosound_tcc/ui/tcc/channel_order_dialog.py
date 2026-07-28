"""Drag-to-reorder dialog for the measurement-panel's "Дати найменування" (assign names) flow --
item 9, 2026-07-27: the user always captures REW measurements in the same channel order, so this
lets them declare that order once per capture method (drag-reorder to match their real capture
sequence) and reuse it to auto-name future captures.

One button drives all three capture methods (sweep / RTA / RTA-group), so the dialog itself carries
a method switcher -- picking a method is mandatory every time (there's no single implicit method to
default to), which is also why there's no "don't show this again" here (user request 2026-07-27
round 2): skipping the dialog would mean skipping the method choice too.

Channel lists come from the measurement panel's own "У фокусі зараз" data (`ui/tcc/mock_data.py`'s
`MEAS`), NOT the DSP tree -- that data is phase/step-scoped (which channels are expected THIS
step), unlike the DSP tree's fixed hardware channel list, so it's the right source for "what am I
about to capture, in what order" (user request 2026-07-27 round 2).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from autosound_tcc.ui.tcc import i18n

_ID_ROLE = Qt.ItemDataRole.UserRole

# method key -> i18n label key, in switcher order.
_METHOD_LABELS = (
    ("sw", "captureMethodSw"),
    ("rta", "captureMethodRta"),
    ("rta_group", "captureMethodRtaGroup"),
)


class ChannelOrderDialog(QDialog):
    """`methods`: method key -> `(channel_id, display_label)` pairs (already in the order to seed
    that method's list with -- a previously-saved per-method order, or the mock panel's own order
    as the first-use default). Only methods present as a non-empty key show a switcher button --
    a phase/step with no RTA-group channels, say, just won't offer that tab."""

    def __init__(
        self,
        methods: dict[str, list[tuple[str, str]]],
        initial_method: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.t("captureOrderTitle"))
        self.resize(360, 460)
        self._methods = {k: list(v) for k, v in methods.items() if v}
        # Set below via _switch_method(), once self._list exists -- setting it here too would make
        # that first _switch_method() call's _store_current_list() clobber the real seed data with
        # the still-empty QListWidget's (nonexistent) contents.
        self._method: str | None = None
        first_method = initial_method if initial_method in self._methods else next(iter(self._methods), None)

        layout = QVBoxLayout(self)
        hint = QLabel(i18n.t("captureOrderHint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        switcher_row = QHBoxLayout()
        self._method_btns: dict[str, QPushButton] = {}
        for key, label_key in _METHOD_LABELS:
            if key not in self._methods:
                continue
            btn = QPushButton(i18n.t(label_key))
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked=False, k=key: self._switch_method(k))
            switcher_row.addWidget(btn)
            self._method_btns[key] = btn
        switcher_row.addStretch(1)
        layout.addLayout(switcher_row)

        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        layout.addWidget(self._list, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if first_method is not None:
            self._switch_method(first_method)

    def _store_current_list(self) -> None:
        if self._method is None:
            return
        self._methods[self._method] = [
            (self._list.item(i).data(_ID_ROLE), self._list.item(i).text())
            for i in range(self._list.count())
        ]

    def _switch_method(self, key: str) -> None:
        self._store_current_list()
        self._method = key
        for k, btn in self._method_btns.items():
            btn.setChecked(k == key)
        self._list.clear()
        for chan_id, label in self._methods.get(key, []):
            item = QListWidgetItem(label)
            item.setData(_ID_ROLE, chan_id)
            self._list.addItem(item)

    def get_method(self) -> str | None:
        return self._method

    def get_order(self) -> list[str]:
        self._store_current_list()
        return [cid for cid, _label in self._methods.get(self._method, [])] if self._method else []
