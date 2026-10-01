"""The center detail pane — ported from the prototype's `.detail` (Table/EQ/⇄L+R tabs + close,
opening in the top half above the AI dialog): `openTable`/`openEq`/`bandHtml`/`siblingName`
(`data/private/prototype/tcc-main.html`).

Two views share one pane:
  * Table  — every row in a group, one column per declared field (HP/LP/Gain/Delay/Pol/Phase/EQ),
    driven entirely by `group.fields` — a group with fewer/different fields just gets fewer/
    different columns, no per-DSP code.
  * EQ     — band cards for one row (Type/Freq/Q/Gain), or two stacked rows (⇄ L+R) with shared-
    frequency color-coding when a sibling channel is found.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QFontMetricsF,
    QGuiApplication,
    QIcon,
    QPainter,
    QPalette,
    QPixmap,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyleOption,
    QStyleOptionComboBox,
    QStyleOptionToolButton,
    QStyleOptionViewItem,
    QStylePainter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import eq_export
from autosound_tcc.state.dsp_state import (UNREAD_LEG, CrossoverLeg, EqBand, GroupRow,
                                           ProfileGroup, leg_label)
from autosound_tcc.state.eq_diff import BandDiff, compare_bands
from autosound_tcc.ui.tcc import copy_menu, i18n, rounded_tooltip
from autosound_tcc.ui.tcc.labels import ElidedButton
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.setting_status import field_status, tip_for
from autosound_tcc.ui.tcc.theme import apply_caps, current_theme

# field token -> (column header, cell-renderer). Order here is the fallback display order when a
# group declares a field not already covered by a fixed prototype-matching order below.
_FIELD_COLUMNS: dict[str, str] = {
    "hp": "HPF", "lp": "LPF", "gain_db": "Gain dB", "ta_ms": "Delay ms",
    "polarity": "Pol", "phase_deg": "Phase", "mute": "Mute", "off": "Off",
    "eq_bypass": "EQ Byp", "eq": "EQ",
}

#: The controls worth looking at across the whole rig at once, and what each tab is called.
#: Values are callables so the label is read in the CURRENT language every time, not frozen at
#: import; the fields themselves are the ledger's own names.
_PARAM_TABS: dict[str, "object"] = {
    "gain_db": lambda: i18n.t("tabGain"),
    "ta_ms": lambda: i18n.t("tabDelay"),
    "phase_deg": lambda: i18n.t("tabPhase"),
}

_MATCH_PALETTE = ["#5aa9e6", "#4bbf87", "#e8973c", "#c98fe0", "#e8c34a", "#e05c5c"]
#: The compared pairs' colours: not the marks' green and red, which say new and removed (the
#: Arbiter, 2026-09-26: «кольори, відмінні від зеленого і червоного, як у точок — синій ок»).
_CMP_PALETTE = ["#5aa9e6", "#e8973c", "#c98fe0", "#e8c34a", "#f28cc8", "#c9a27e"]


def _bank_sentence(channel: str, bank) -> str:
    """What was copied, in what, and what did not make it — in that order.

    The count and the bank size travel together because a fixed-size bank is a FORM: pasting it
    writes its empty rows over whatever those slots held. "8 bands of 30" says that; "copied" does
    not. And a band left out is said with the method's own reason, because "it did not fit" and
    "this format has no room for an all-pass" send a person to different places.
    """
    said = i18n.t("copyEqDone").format(channel=channel, format=bank.format_name)
    if bank.bank_size:
        said = f"{said} {i18n.t('copyEqCount').format(written=bank.written, size=bank.bank_size)}"
    elif bank.written:
        said = f"{said} {i18n.t('copyEqWritten').format(written=bank.written)}"
    if bank.crossovers:
        said = f"{said} {i18n.t('copyEqCrossovers').format(n=bank.crossovers)}"
    for note in bank.notes:
        said = f"{said} {note}"
    if bank.left_out:
        said = f"{said} {i18n.t('copyEqLeftOut').format(what='; '.join(bank.left_out))}"
    return said


def _sibling_name(name: str) -> Optional[str]:
    """Best-effort L<->R sibling lookup across the naming conventions seen in real ledgers:
    "L"/"R" as a standalone word (`Front L Full`, the prototype's own convention) OR as a bare
    trailing suffix with no delimiter at all (`FrontL`/`FrontR`, `w_L`/`w_R`) — the real virtual-
    channel ledger uses the latter. Generic string swap, not tied to any DSP-specific channel
    list; suffix form is tried last since it's the loosest pattern.
    """
    if re.search(r"\bL\b", name):
        return re.sub(r"\bL\b", "R", name, count=1)
    if re.search(r"\bR\b", name):
        return re.sub(r"\bR\b", "L", name, count=1)
    if re.search(r"L$", name):
        return re.sub(r"L$", "R", name)
    if re.search(r"R$", name):
        return re.sub(r"R$", "L", name)
    return None


def _is_left(name: str) -> bool:
    return bool(re.search(r"(\bL\b|L$)", name))


class _FitLabel(QLabel):
    """A head label that shortens itself to «…» instead of running past its row and getting
    clipped mid-word (tcc#96, finding 105: «⇅ П», «Копі», the Arbiter's screenshot).

    Drawn elided, never `setText`-ed (the same reasoning as `labels.ElidedButton`): `.text()`
    always stays the real, full string, and only `paintEvent` substitutes a shorter one, measured
    against whatever room THIS paint actually has. `labels.ElidedLabel` was tried first and
    reverted -- it elides eagerly, inside `setText` and on every `resizeEvent`, and a great many
    of this file's own tests build a bare, unshown `DetailPane` (no `show()`/resize at all) and
    read a tab's `.text()` straight back; on such a pane `showEvent`/layout activation can still
    fire once, handing every child SOME provisional width that has nothing to do with an actual
    window's — eliding against it cut tabs that never had a real narrow row at all.

    Its floor decides WHEN it gives way (fix round 5 -- the Arbiter on the Windows VM: the full
    window's head read «Табл…», an empty «EQ», «Рів…», «Затри…», «Ф…» and «закрит…» with the
    pane 840 px wide, «порівняти з», the box and «інша конфігурація» whole beside them; measured
    here with the Mac's font and a 1400-px window, the pane 821 px for a head asking 891). A box
    layout splits what it is short of EQUALLY among the items that can shrink, and the first
    pass's 24-px floor made the tabs the only ones: the whole deficit went to them, down to a
    4-px content rect and nothing to draw. The label meets a short row one of three ways, and
    the head's own fit (`DetailPane._fit_head`) picks it by the room the row has:

    - `"holds"`: its floor is its text, as a plain `QLabel`'s was before the wave. The layout
      takes the room from whatever else can give, and only a row below its own minimum -- where
      Qt trims the widest items to one width -- cuts into it, elided instead of clipped.
    - `"gives"`: its floor is its first glyph and «…» (or the glyph alone, `floor="glyph"`),
      never nothing. It shares the shortfall with every other item that gives.
    - `"floor"`: it asks for no more than that floor. It has given all it had, and the ones
      still holding give next -- a box layout has no order of its own, only "equally from all
      that can shrink", so an order is made by holding the rest and pinning the ones that went
      first (the re-review of fix round 5: below the head's minimum the title bounced back to
      «Output chan…» while the tabs went to «Табл…»).
    - `"hidden"`: not shown at all, whole or nothing -- «порівняти з» and the tag at their glyph
      («п…», «ін…») said nothing and still cost 64 px of a head short of 130 (the review of the
      follow-up: the EQ view's head at the full window's floor emptied the box, finding 105's
      second screenshot exactly). The owner's own `setVisible` is kept apart (`wanted`), so the
      head's asks count what the owner shows and not what the fit hid: a threshold that moved
      with its own outcome would flicker.

    Whole pixels are not enough to judge a fit: `elidedText` measures in fractions, and a text
    79.11 px wide given the 79 it asked for lost its last letters (`labels.ElidedLabel`, F-045;
    the final review saw «Control mo…» at 1600 px on Windows fonts). The hint is rounded up, the
    fit is judged in fractions, and the elision is done in fractions too."""

    def __init__(self, text: str = "", holds: bool = True, floor: str = "…") -> None:
        super().__init__(text)
        self._full = text
        self._way = "holds" if holds else "gives"
        #: What it comes down to: its first glyph and «…», or the glyph alone (`"glyph"`) for a
        #: chip whose glyph says it -- «⇄ L + R», «⇅ Порівняти», «← Таблиця-О» -- and its hover
        #: says the rest (the review of the follow-up, way (b): the EQ view's head has to fit
        #: the centre's floor, and three chips at «⇄…» were 24 px of the shortfall).
        self._floor = floor
        #: Whether the owner wants it shown -- `setVisible` as the pane calls it.
        self._wanted = True
        # The OWNER's hint (`_sync_tabs`'s tcc#54 tooltips, e.g. `_cmp_btn`'s "pick a version
        # first" / "compare with {version}"), separate from the fallback this widget sets for
        # ITSELF when elided with nothing else to say. `None` -- never set -- is not the same as
        # `""` -- set, deliberately, to nothing: only the former falls back (finding IMPORTANT 2,
        # the reviewer's pass: painting used to call `setToolTip` on every paint, unconditionally,
        # overwriting whichever of the two came first).
        self._owner_tip: Optional[str] = None
        # Qt draws this label's own QSS box (`.d-tab`'s border-radius and padding, `.d-tab.on`'s
        # fill, `.cmp-other`'s border) through the style before `paintEvent`, which draws only
        # the text: `paintEvent` never calls the native `QLabel.paintEvent`.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

    def set_way(self, way: str) -> None:
        """How it meets a short row: `"holds"`, `"gives"`, `"floor"` or `"hidden"` (the class
        docstring)."""
        if way != self._way:
            self._way = way
            super().setVisible(self._wanted and way != "hidden")
            self.updateGeometry()

    def way(self) -> str:
        return self._way

    def setVisible(self, visible: bool) -> None:  # noqa: N802 (Qt override)
        """The owner's wish; shown only while the fit has not hidden the label itself."""
        self._wanted = visible
        super().setVisible(visible and self._way != "hidden")

    def wanted(self) -> bool:
        """Whether the owner shows this label -- what the head's asks are counted from, whether
        or not the fit has hidden it for now."""
        return self._wanted

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self._full = text
        super().setText(text)
        self.updateGeometry()
        self._sync_tip()

    def setToolTip(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self._owner_tip = text
        super().setToolTip(text)

    def _width(self, text: str) -> float:
        return QFontMetricsF(self.font()).horizontalAdvance(text)

    def _chrome(self) -> int:
        """What the label spends beyond its text: the contents margins the style sheet's border
        and padding become for a label, and QLabel's own margin each side -- the same number
        `_text_rect` takes off the width. Not QLabel's size hint less the text: that hint adds a
        full «x» of indent where its paint takes half, and the chips asked 4-5 px more than the
        paint needed (the re-review of fix round 2)."""
        margins = self.contentsMargins()
        return margins.left() + margins.right() + 2 * self.margin()

    def whole_width(self) -> int:
        """The width that shows the text whole, whatever way the label is set to now -- within
        the widths the style sheet fixes («?» is 16 px, min and max, whatever its glyph asks),
        which the layout holds to whatever the hint says."""
        wide = math.ceil(self._width(self._full)) + self._chrome()
        return max(self.minimumWidth(), min(self.maximumWidth(), wide))

    def _text_rect(self) -> QRect:
        """Where the text is drawn, whole or elided: the contents rect (the style sheet's border
        and padding ARE contents margins for a label), less QLabel's margin -- and not QLabel's
        half-«x» indent for a framed label: the chips' padding is that already, and the indent
        left the fit's room, the paint's and the hint's three different numbers. The re-review
        of fix round 1 found the paint rect built from the contents rect less the chrome again
        (width - 46 for a d-tab), so an elided tab drew nothing; the re-review of round 2 found
        the English chips at the half elided for a sub-pixel while asking 4-5 px more than the
        paint needed. One rule now: the room, the rect and the hint's chrome are this."""
        rect = self.contentsRect()
        margin = self.margin()
        rect.adjust(margin, margin, -margin, -margin)
        return rect

    def floor_width(self) -> int:
        """The least it can be drawn in: its first glyph and «…» -- or the glyph alone, for a chip
        whose glyph says it -- never nothing."""
        least = self._full[:1] if self._floor == "glyph" else self._full[:1] + "…"
        return min(self.whole_width(),
                   max(self.minimumWidth(), math.ceil(self._width(least)) + self._chrome()))

    def sizeHint(self):  # noqa: N802 (Qt override)
        hint = super().sizeHint()
        hint.setWidth(self.floor_width() if self._way == "floor" else self.whole_width())
        return hint

    def minimumSizeHint(self):  # noqa: N802 (Qt override)
        hint = super().minimumSizeHint()
        hint.setWidth(self.whole_width() if self._way == "holds" else self.floor_width())
        return hint

    def fit_text(self) -> str:
        """This label's text right now: the full string, or elided with «…» to what its row
        actually has (tcc#96, finding 105) -- what `paintEvent` draws, without having to paint to
        find out."""
        metrics = QFontMetricsF(self.font())
        # The room the native paint has (`_text_rect`), neither the whole contents rect (a tab
        # given 70 px read «Таблиця» whole for its 73 while the paint clipped it) nor the width
        # less the chrome (3 px stricter than the paint: chips whole took the elided path).
        room = max(0, self._text_rect().width())
        # A glyph clipped by less than a pixel is invisible: «⇄ L + R» at 41.75 px in a 41-px
        # room is whole, where a strict fit elided it (the re-review of fix round 2).
        if metrics.horizontalAdvance(self._full) < room + 1:
            return self._full
        shown = metrics.elidedText(self._full, Qt.TextElideMode.ElideRight, room)
        # At its floor the label shows its floor text -- the glyph, or the glyph and «…» -- by
        # this label's own measure: Qt's elision is a few tenths of a pixel off either way, and
        # given the room «Р…» was measured for it drew «…» alone.
        # -- and never nothing, whatever the room: the Windows runner's fontless text handed
        # back «» for a chip given room for three of its glyphs (CI at 467c655), and a floor
        # glyph clipped beats a chip with no ink.
        least = self._full[:1] if self._floor == "glyph" else self._full[:1] + "…"
        if shown in ("", "…"):
            shown = least
        return shown

    def _sync_tip(self) -> None:
        """The owner's tooltip if it ever set one -- even an empty one, deliberately; otherwise
        the text elision took away, so nothing is silently lost. Called from `resizeEvent` and
        `setText`, never from `paintEvent`: painting must stay free of side effects (finding
        IMPORTANT 2)."""
        if self._owner_tip is not None:
            return
        super().setToolTip(self._full if self.fit_text() != self._full else "")

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._sync_tip()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        """Drawn by this label whole and elided alike, in `_text_rect`, the way QLabel draws its
        own text: through `drawItemText` with the option's palette, so a disabled chip's colour
        is the sheet's. One paint for both, so the fit and the paint cannot disagree by an indent
        again. The style's box is not drawn here: `WA_StyledBackground` has Qt draw it before
        this runs, and a second `PE_Widget` doubled every "on" chip's translucent accent («Таблиця»
        0x28231c -> 0x3e3120, the re-review of the CI fix)."""
        option = QStyleOption()
        option.initFrom(self)
        painter = QStylePainter(self)
        painter.setFont(self.font())
        painter.drawItemText(self._text_rect(), int(self.alignment()), option.palette,
                             self.isEnabled(), self.fit_text(), self.foregroundRole())


class _DTab(_FitLabel):
    """A head tab/chip («EQ», «⇅ Порівняти», «Копіювати EQ …»): a `_FitLabel` that is clicked.
    In the full window it holds its text while the row has the room -- the tabs ARE the
    navigation -- and gives way last (`DetailPane._fit_head`); inside a control-mode tab it
    always gives way, as the chips there must (finding 105)."""

    clicked = Signal()

    def __init__(self, text: str, floor: str = "…") -> None:
        super().__init__(text, floor=floor)
        self.setProperty("class", "d-tab")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        event.accept()
        self.clicked.emit()

    def set_on(self, on: bool) -> None:
        cls = "d-tab on" if on else "d-tab"
        self.setProperty("class", cls)
        self.style().unpolish(self)
        self.style().polish(self)


class _TierPickButton(QToolButton):
    """A tier picker's chip («Output: c», `_fill_pickers`): as wide as the longest thing it could
    say, so switching between channels never moves the row (finding 71, 6) — but able to give
    ground when the ROW itself has no room, eliding instead of running past the head's edge and
    getting clipped there, which is what «Output: c» cut to («tcc#96, finding 105) actually was: a
    fixed-width button the layout could not shrink at all, not its own text failing to fit itself.

    A `QToolButton` on purpose, not `labels.ElidedButton` (`QPushButton`): the theme's QSS keys
    `.tier-pick`'s colours, hover and hidden menu-indicator off the `QToolButton` type itself
    (`theme.py`), and a `QPushButton` would silently stop matching it.
    """

    def __init__(self) -> None:
        super().__init__()
        self._full = ""
        self._preferred_width = 0
        # `Maximum`, not `Preferred`: `Preferred` also carries the GROW flag, and with the row's
        # old hard `setFixedWidth` gone this widget would happily take any leftover space in the
        # row instead of stopping at its own preferred width (caught by
        # `test_the_tiers_are_pickers_in_the_eq_header`'s "nothing jumps" -- it jumped to 640 px).
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self._full = text
        super().setText(text)
        self.updateGeometry()

    def set_preferred_width(self, width: int) -> None:
        """The row's STABLE width, off the tier's longest possible label (`width_for`) — not
        whatever text happens to be picked right now, which `sizeHint` would otherwise track on
        its own and move the row every time the pick changed (the property `setFixedWidth` used to
        give it, before it also had to be able to shrink)."""
        self._preferred_width = width
        self.updateGeometry()

    def width_for(self, text: str) -> int:
        """The width at which this chip shows `text` whole: its chrome, measured, and the text's
        width rounded UP from its fractions -- `fit_text` judges the fit in fractions, and a
        whole-pixel width one fraction short elides the last letters (F-045)."""
        return self._chrome() + math.ceil(QFontMetricsF(self.font()).horizontalAdvance(text))

    def _chrome(self) -> int:
        """What the button spends beyond its text: the dot, the gap after it, the two spaces Qt
        pads a tool button's text with, and the theme's padding -- Qt's own size of the button
        (the base `sizeHint`, not this class's) less Qt's own measure of the text in it, so the
        QSS carries into this number instead of being guessed.

        Against Qt's measure of the text, not `horizontalAdvance`: the two round differently, and
        the difference made the chrome, and the row, a pixel wider for «m-L» than for «m-L/m-R»
        on a wide font -- the row jumped on the pair toggle."""
        text = self.fontMetrics().size(Qt.TextFlag.TextShowMnemonic, self._full).width()
        return max(0, super().sizeHint().width() - text)

    def sizeHint(self):  # noqa: N802 (Qt override)
        hint = super().sizeHint()
        # Never narrower than its own text whole, whatever it was told (CI at f9d3a9e: on the
        # Windows runner's fontless text the chip's chrome outgrew a guessed allowance, and at its
        # own preferred width it read «Output: m-Left-Tweeter-Fro…»).
        hint.setWidth(max(self._preferred_width, self.width_for(self._full)))
        return hint

    def minimumSizeHint(self):  # noqa: N802 (Qt override)
        hint = super().minimumSizeHint()
        # Room for the chrome and a single elided character -- the floor that lets a squeezed row
        # actually shrink this button instead of leaving it fixed and clipped past its own edge.
        hint.setWidth(self._chrome() + self.fontMetrics().horizontalAdvance("…"))
        return hint

    def fit_text(self) -> str:
        """This chip's text right now: the full string, or elided with «…» to what it was
        actually given (tcc#96, finding 105) -- what `paintEvent` draws, without having to paint
        to find out."""
        room = max(0, self.width() - self._chrome())
        # Judged in fractions, as `_FitLabel` does: a whole-pixel room one fraction short of the
        # text would elide it with its own width to spare (F-045).
        if QFontMetricsF(self.font()).horizontalAdvance(self._full) <= room:
            return self._full
        return self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, room)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        shown = self.fit_text()
        if shown == self._full:
            super().paintEvent(event)
            return
        # Drawn elided, never `setText`-ed: changing the real text would change `minimumSizeHint`
        # too (it reads `self._full`), and the two would chase each other (`labels.ElidedButton`'s
        # same reasoning).
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.text = shown
        QStylePainter(self).drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)


#: The head's gap between its items, and the gap once the tabs are giving way: with eight chips
#: at their floors in the EQ view, nine gaps of 6 px were the 27 px that kept the head from the
#: centre's floor on a 1512-px screen at the zoom's first steps (stretch 106: 605 against 589).
_HEAD_SPACING = 6
_HEAD_SPACING_TIGHT = 3


class _HeadBox(QComboBox):
    """The full head's «порівняти з» list. It asks for what it always did -- six letters' room,
    `AdjustToMinimumContentsLengthWithIcon`, whatever is picked, so a pick never moves the
    window's floor (tcc#107's rule for control mode's box) -- but its floor is «v_NNN», its real
    shortest content, and not the six letters: 121 px of floor against a head 130 px short is
    what emptied the box in the EQ view at the full window's floor (the review of the follow-up,
    finding 105's second screenshot). Whatever it shows is drawn elided to its field, never
    clipped mid-glyph. It meets a short row the way a `_FitLabel` does (`set_way`)."""

    def __init__(self) -> None:
        super().__init__()
        self._way = "holds"

    def set_way(self, way: str) -> None:
        if way != self._way:
            self._way = way
            self.updateGeometry()

    def way(self) -> str:
        return self._way

    def _room(self, size=None) -> int:
        """The width the text has: the style's edit field, less the pixel each side of it."""
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        if size is not None:
            option.rect = QRect(QPoint(0, 0), size)
        field = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                            QStyle.SubControl.SC_ComboBoxEditField, self)
        return max(0, field.width() - 2)

    def whole_width(self) -> int:
        return super().sizeHint().width()

    def floor_width(self) -> int:
        """«v_NNN» whole with the «…» that says a saved name follows: measured on «v_000» alone,
        «v_001 · P3» read «v_0…» at the floor (the re-review of fix round 1). Or with the sign a
        refused version comes down to, `UNREAD_SIGN`, where that is the wider -- whatever is
        picked: a pick never moves the window's floor (tcc#122, Ruling 26)."""
        hint = super().sizeHint()
        chrome = hint.width() - self._room(hint)
        metrics = QFontMetricsF(self.font())
        least = max(metrics.horizontalAdvance("v_000…"),
                    metrics.horizontalAdvance("v_000" + UNREAD_SIGN))
        return min(hint.width(), chrome + math.ceil(least))

    @staticmethod
    def _version_head(text: str) -> str:
        """«v_NNN» at the start of a row's text, or nothing."""
        return text[:5] if text[:2] == "v_" and text[2:5].isdigit() else ""

    def sizeHint(self):  # noqa: N802 (Qt override)
        hint = super().sizeHint()
        hint.setWidth(self.floor_width() if self._way == "floor" else self.whole_width())
        return hint

    def minimumSizeHint(self):  # noqa: N802 (Qt override)
        hint = super().minimumSizeHint()
        hint.setWidth(self.whole_width() if self._way == "holds" else self.floor_width())
        return hint

    def fit_text(self) -> str:
        """What the closed box draws: the current text, elided to the room it has now -- the
        version whole and «…» after it where the saved names do not fit; a row marked
        «не читається» gives way after its names and before its version (`with_unread_mark`)."""
        split = unread_mark(self)
        version = self._version_head(split[0] if split else self.currentText())
        return with_unread_mark(self, self._room(), self._fit, version)

    def _fit(self, text: str, room: int) -> str:
        metrics = QFontMetricsF(self.font())
        if metrics.horizontalAdvance(text) <= room:
            return text
        shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, room)
        head = self._version_head(text)
        if head and not shown.startswith(head) and metrics.horizontalAdvance(head + "…") <= room:
            shown = head + "…"
        return shown

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        paint_compare_box(self, self.fit_text())


def cell_width(table: QTableWidget, text: str, font: QFont) -> int:
    """The width a cell of `table` needs to show `text` whole in `font`, its padding included --
    measured by the table's own style, which is what `sizeHintForColumn` asks for a cell."""
    option = QStyleOptionViewItem()
    option.initFrom(table)
    option.font = font
    option.fontMetrics = QFontMetrics(font)
    option.text = text
    option.features = QStyleOptionViewItem.ViewItemFeature.HasDisplay
    return table.style().sizeFromContents(QStyle.ContentsType.CT_ItemViewItem, option, QSize(),
                                          table).width()


class _ContentTable(QTableWidget):
    """The pane's table, each column as wide as its heading and its widest value -- measured by
    Qt in the table's own font, a changed cell's bold one included -- and the rest of a wide
    pane shared out among the columns after the ID, so the table still fills it (the user's
    «table on full width»).

    Every column but the ID used to stretch to one equal share (tcc#106 and tcc#107 both named
    it): the share had to be the widest column's, «3500 LR4» in bold, so the full window's floor
    asked ~1254 px of the Arbiter's rig for a table whose content needs ~1115, and control
    mode's ~854 for ~761. Short of its content -- under the half-screen and two-thirds caps --
    every column gives in proportion, and the cells elide as they did everywhere before."""

    def __init__(self, rows: int, columns: int) -> None:
        super().__init__(rows, columns)
        # `Fixed`: the widths are set here, on every resize of the viewport (a vertical scroll bar
        # coming or going changes its width, not the table's), and the header leaves them be.
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.viewport().installEventFilter(self)

    def column_needs(self) -> list:
        """Each column's width whole: its heading's, or its widest cell's, by Qt's own measure --
        every cell measured BOLD, the widest it can be drawn (a compared change,
        `DetailPane._styled_cell`), so a compare pick never moves the columns: measured by the
        review of the follow-up, «3500 LR4» bold or plain shifted every column 1-3 px at panes of
        760-1060 px."""
        header = self.horizontalHeader()
        bold = QFont(self.font())
        bold.setBold(True)
        needs = []
        for column in range(self.columnCount()):
            need = header.sectionSizeHint(column)
            for row in range(self.rowCount()):
                item = self.item(row, column)
                if item is not None and item.text():
                    need = max(need, cell_width(self, item.text(), bold))
            needs.append(need)
        return needs

    def fit_columns(self) -> None:
        needs = self.column_needs()
        if not needs:
            return
        room, whole = self.viewport().width(), sum(needs)
        if room >= whole:
            # The ID column keeps to its content; the others share what is left, the odd pixels
            # to the first of them.
            sharing = max(1, len(needs) - 1)
            share, odd = divmod(room - whole, sharing)
            widths = [needs[0]] + [need + share + (1 if i < odd else 0)
                                   for i, need in enumerate(needs[1:])]
            if len(needs) == 1:
                widths = [room]
        else:
            widths = [need * room // whole for need in needs]
            for i in range(room - sum(widths)):
                widths[i % len(widths)] += 1
        for column, width in enumerate(widths):
            if self.columnWidth(column) != width:
                self.setColumnWidth(column, width)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt override)
        if watched is self.viewport() and event.type() == QEvent.Type.Resize:
            self.fit_columns()
        return super().eventFilter(watched, event)


#: Freq first, then Q and Gain in the order the processor's own software shows them (finding 68,
#: the Arbiter, 2026-09-25): PC-Tool (Helix, Audiotec-Fischer) reads Freq · Gain · Q; a MUSWAY
#: reads Freq · Q · Gain. The profile does not state it, so the vendor decides.
_ORDER_DEFAULT = ("freq", "q", "gain")
_ORDER_GAIN_FIRST = ("freq", "gain", "q")


def eq_field_order(vendor: Optional[str], name: Optional[str] = "") -> tuple:
    said = f"{vendor or ''} {name or ''}".lower()
    return _ORDER_GAIN_FIRST if ("audiotec" in said or "helix" in said) else _ORDER_DEFAULT


def _band_kind(kind: Optional[str]) -> str:
    """The filter type's family, for its colour (finding 69): shelf · pk · apf · other."""
    k = (kind or "").upper()
    if k in ("LSH", "HSH", "LS", "HS", "LSF", "HSF") or "SHELF" in k:
        return "shelf"
    if k in ("PK", "PEQ", "PEAK", "BELL"):
        return "pk"
    if k in ("APF", "AP", "ALLPASS") or k.startswith("AP"):
        return "apf"
    return "other"


def _band_empty(band: EqBand) -> bool:
    """A slot with nothing in it: not drawn (PAS-011) — the gap shows in the band numbers. PC-Tool's
    white slot is one: a frequency and no gain, no Q (finding 71, 5); a BYPASSED band with its
    settings is a band, and is drawn."""
    return ((band.type or "").upper() in ("", "OFF", "NONE") or not band.freq_hz
            or (band.gain_db is None and band.q is None))


def band_count(bands) -> str:
    """«(8/12)»: active of configured, the empty slots not counted (finding 71, 3 and 5)."""
    configured = [b for b in bands if not _band_empty(b)]
    if not configured:
        return ""
    return f"({sum(not b.bypass for b in configured)}/{len(configured)})"


#: A band against the compared version (tcc#54): green new, blue changed — the window's colour for
#: a change, as the changed cells and dots — red removed. The theme's token, read when drawn.
_MARK_TOKEN = {"new": "ok", "chg": "info", "removed": "warn"}
_MARK_WORD = {"new": "bandNew", "chg": "bandChg", "removed": "bandGone"}


def _band_value(name: str, band: EqBand) -> str:
    if name == "freq":
        return f"{band.freq_hz:g} Hz"
    if name == "gain":
        return f"{band.gain_db:+.1f} dB" if band.gain_db is not None else "—"
    if name == "q":
        return f"{band.q:.2f}" if band.q is not None else "—"
    if name == "bypass":
        return "● ByPass" if band.bypass else "○ ByPass"
    return band.type or "—"


def _mark_tip(diff: BandDiff, version: str) -> str:
    """What the mark means for THIS band: new against which version, what moved and from what."""
    word = i18n.t(_MARK_WORD[diff.status])
    if diff.status == "new":
        return f"{word}: {i18n.t('bandNewTip').format(version=version)}"
    if diff.status == "removed":
        return f"{word}: {i18n.t('bandGoneTip')}"
    moved = [f"{_band_value(f, diff.other)} → {_band_value(f, diff.band)}"
             for f in ("type", "freq", "gain", "q", "bypass") if f in diff.fields]
    return f"{word}: {' · '.join(moved)}"


def mark_colour(status: str) -> str:
    """The mark's colour in the theme on now: green new, blue changed, red removed."""
    return getattr(current_theme(), _MARK_TOKEN[status])


def band_changes(row: GroupRow, old_row: Optional[GroupRow]) -> dict:
    """`{"new": n, "chg": n, "removed": n}`: `row`'s bands against the same channel in the
    compared version, by the EQ view's own match; `old_row` None — that version lacks the channel,
    and every band is new (finding 74)."""
    now_side, was_side = compare_bands(_shown(row.eq_bands()),
                                       _shown(old_row.eq_bands()) if old_row is not None else [])
    return {"new": sum(d.status == "new" for d in now_side),
            "chg": sum(d.status == "chg" for d in now_side),
            "removed": sum(d.status == "removed" for d in was_side)}


def table_fields(group: ProfileGroup) -> list:
    """The controls a tier's table draws as columns, in the tier's own order."""
    return [f for f in group.known_fields if f in _FIELD_COLUMNS]


def column_title(field: str) -> str:
    """A control's name as the table's column heads it («Pol», «EQ Byp»)."""
    return _FIELD_COLUMNS.get(field, field)


def cell_text(field: str, row: GroupRow) -> str:
    """A value as the table reads it — and as it is compared (`field_changed`)."""
    raw = row.raw
    if field in ("hp", "lp"):
        return leg_label(raw.get(field))
    if field == "gain_db":
        v = raw.get("gain_db")
        return f"{v:+.1f}" if isinstance(v, (int, float)) else "—"
    if field == "ta_ms":
        v = raw.get("ta_ms")
        return f"{v:g}" if isinstance(v, (int, float)) else "—"
    if field == "phase_deg":
        v = raw.get("phase_deg")
        return f"{v:g}°" if isinstance(v, (int, float)) else "—"
    if field == "polarity":
        return raw.get("polarity") or "—"
    if field == "mute":
        return "MUTE" if raw.get("mute") else "—"
    if field == "off":
        return "OFF" if raw.get("off") else "—"
    if field == "eq_bypass":
        return "Y" if raw.get("eq_bypass") else "—"
    if field == "eq":
        # «(active/configured)», as the pickers say it: «15 bands» counted the empty slots.
        count = band_count(row.eq_bands())
        return f"{count} ▸" if count else "—"
    return "—"


def unread_leg_tip(field: str, row: GroupRow) -> str:
    """The hover of a crossover leg the table reads as «?» — what the ledger holds, as it holds
    it (tcc#123) — or "" for every other cell."""
    if field not in ("hp", "lp") or cell_text(field, row) != UNREAD_LEG:
        return ""
    value = json.dumps(row.raw.get(field), ensure_ascii=False, default=str)
    return i18n.t("xoverUnread").format(value=value)


def field_changed(field: str, row: GroupRow, old_row: Optional[GroupRow]) -> bool:
    """Whether this value differs from the same channel in the compared version: the ONE rule for
    the table's changed cells and the DSP tree's marks, so the two never disagree (tcc#104,
    finding 113 — the table marked sw's HPF, the tree only its EQ). `old_row` None: that version
    lacks the channel, and every value is new."""
    if old_row is None:
        return True
    # «7 bands ▸» reads the same with a band moved; the bands are what changed.
    bands_moved = field == "eq" and old_row.raw.get("eq") != row.raw.get("eq")
    return cell_text(field, old_row) != cell_text(field, row) or bands_moved


def changed_fields(group: ProfileGroup, row: GroupRow, old_row: Optional[GroupRow]) -> frozenset:
    """Every column of `group`'s table that `field_changed` marks for this channel."""
    return frozenset(f for f in table_fields(group) if field_changed(f, row, old_row))


def _pair_colours(now_side: list) -> dict:
    """Each changed band and its compared self in one colour of the pair palette, keyed by the
    band object: «кольорово однаковими "змінені", як у нас правий-лівий» (the Arbiter,
    2026-09-26). By the current row's order, as the cards stand."""
    colours = {}
    for k, d in enumerate(d for d in now_side if d.status == "chg"):
        colour = _CMP_PALETTE[k % len(_CMP_PALETTE)]
        colours[id(d.band)] = colours[id(d.other)] = colour
    return colours


def _freq_said(d: BandDiff) -> str:
    return (f"{d.other.freq_hz:g}→{d.band.freq_hz:g}" if "freq" in d.fields and d.other
            else f"{d.band.freq_hz:g}")


def _compare_legend(now_side: list, was_side: list, colours: Optional[dict] = None) -> QWidget:
    """«однакові (7) ● нова (1): 1250 Hz ● змінена (2): 250 · 1000→1120 Hz ● видалена (0)»: all
    three colours always, the same bands by count only, the rest with their frequencies (the
    Arbiter, 2026-09-26). With `colours` (the compared row on) each changed one is a chip in its
    pair colour, «⬤ 1000→1120 Hz», as the pair mode's «спільні» are."""
    legend = QWidget()
    legend_layout = QHBoxLayout(legend)
    legend_layout.setContentsMargins(0, 0, 0, 0)
    legend_layout.setSpacing(12)
    same = QLabel(f"{i18n.t('bandSame')} ({sum(d.status == 'same' for d in now_side)})")
    same.setProperty("class", "eq-rowlab")
    legend_layout.addWidget(same)
    t = current_theme()
    for status, side in (("new", now_side), ("chg", now_side), ("removed", was_side)):
        entries = sorted((d for d in side if d.status == status), key=lambda d: d.band.freq_hz)
        said = f"● {i18n.t(_MARK_WORD[status])} ({len(entries)})"
        paired = status == "chg" and colours and entries
        if entries and not paired:
            said += ": " + " · ".join(_freq_said(d) for d in entries) + " Hz"
        chip = QLabel(said + (":" if paired else ""))
        chip.setStyleSheet(f"color: {getattr(t, _MARK_TOKEN[status])};")
        legend_layout.addWidget(chip)
        for d in entries if paired else ():
            pair = QLabel(f"⬤ {_freq_said(d)} Hz")
            pair.setStyleSheet(f"color: {colours.get(id(d.band), t.info)};")
            legend_layout.addWidget(pair)
    legend_layout.addStretch(1)
    return legend


class EqBandCard(QFrame):
    """One EQ band card: «Type (band)» + Freq/Q/Gain in the processor's order + the band's own
    bypass. `match_color`, when given, draws the colored top border used to flag a shared frequency
    between paired L/R channels.

    Against a compared version (tcc#54): `mark` — "new" · "chg" · "removed" — puts a coloured dot
    in the heading, `mark_tip` says what it means; `changed` names the values drawn in the change
    colour, and `was` the band they were, for «було: …» on hover."""

    def __init__(
        self, band: EqBand, match_color: Optional[str] = None, gain_mismatch: bool = False,
        order: tuple = _ORDER_DEFAULT, mark: Optional[str] = None, mark_tip: str = "",
        changed: frozenset = frozenset(), was: Optional[EqBand] = None,
    ) -> None:
        super().__init__()
        self.setProperty("class", "band")
        self.mark = mark
        self.match_color = match_color
        self.setFixedWidth(112)
        if match_color:
            # A bare (selector-less) setStyleSheet() rule is implicitly "*" and cascades to every
            # descendant widget, not just this QFrame -- without the type-selector scope, this
            # border-top would also apply to each Freq/Q/Gain row inside, producing a colored bar
            # under every row (a "zebra stripe") instead of a single accent line at the card top.
            self.setStyleSheet(f"EqBandCard {{ border-top: 3px solid {match_color}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The DSP's own band number in brackets (hub #211 PAS-011, finding 69): PC-Tool names a band
        # by it, and the check «band N in the DSP = card N here» was done by eye.
        title = f"{band.type} ({band.index})" if band.index is not None else band.type
        self._title = QLabel(title)
        self._title.setProperty("class", f"band-id band-{_band_kind(band.type)}")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if mark in _MARK_TOKEN:
            colour = getattr(current_theme(), _MARK_TOKEN[mark])
            self._title.setTextFormat(Qt.TextFormat.RichText)
            self._title.setText(f'<span style="color:{colour}">●</span>&nbsp;{title}')
            self._title.setToolTip(mark_tip)
        layout.addWidget(self._title)

        values = {key: (name, _band_value(key, band))
                  for key, name in (("freq", "Freq"), ("q", "Q"), ("gain", "Gain"))}
        self._field_names = [values[key][0] for key in order]
        self._changed_labels: list = []
        for key, (label, value) in ((key, values[key]) for key in order):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 3, 8, 3)
            fk = QLabel(label)
            fk.setProperty("class", "band-fk")
            fv = QLabel(value)
            # A shared frequency (same top-border match_color) whose L/R gain still differs looked
            # identical to a same-freq/same-gain match -- flag the Gain value specifically so the
            # asymmetry is visible at a glance (user request 2026-07-27).
            fv.setProperty("class", "band-fv-mismatch" if (label == "Gain" and gain_mismatch) else "band-fv")
            if key in changed:
                # What changed against the compared version, not what is the same (tcc#54).
                fv.setProperty("class", "band-fv-chg")
                if was is not None:
                    fv.setToolTip(i18n.t("cmpWas").format(value=_band_value(key, was)))
                self._changed_labels.append(label)
            row_layout.addWidget(fk)
            row_layout.addStretch(1)
            row_layout.addWidget(fv)
            layout.addWidget(row)

        # The band's own bypass (hub #209 PAS-009): the same grey «○ ByPass» stood on every band,
        # and a band switched off in the DSP could not be told from one that was on. A band with
        # no `bypass` (older files) is on — the ledger's own reading.
        self._byp = QLabel(("● " if band.bypass else "○ ") + "ByPass")
        self._byp.setProperty("class", ("band-byp on" if band.bypass else "band-byp")
                              + (" chg" if "bypass" in changed else ""))
        apply_caps(self._byp, spacing_px=0.8)
        self._byp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._byp)

    def field_names(self) -> list:
        return list(self._field_names)

    def changed_fields(self) -> list:
        """The value rows drawn as changed, by their names («Gain», «Q»)."""
        return list(self._changed_labels)


def _shown(bands) -> list:
    """By the DSP's band number, as PC-Tool lists them; an empty slot draws nothing (PAS-011)."""
    return sorted((b for b in bands if not _band_empty(b)),
                  key=lambda b: (b.index is None, b.index or 0))


def _band_flow(
    bands: tuple[EqBand, ...],
    match_map: Optional[dict[float, str]] = None,
    gain_mismatch_freqs: Optional[set] = None,
    order: tuple = _ORDER_DEFAULT,
    diff: Optional[list] = None,
    marks: tuple = (),
    paint: bool = False,
    version: str = "",
    pair_colours: Optional[dict] = None,
    mark_tops: bool = False,
) -> QWidget:
    """One row of cards. With `diff` (the row's `BandDiff`s, in `_shown` order) the bands come
    from it: the statuses in `marks` get their dot, and `paint` draws the changed values, with
    «було: …» on hover.
    `pair_colours` (`_pair_colours`) tops a changed band with its pair's colour; `mark_tops` a new
    or removed one with its mark's green or red («щоб краще було видно»). Not in pair mode, where
    the top already says «shared frequency»."""
    container = QWidget()
    # One row and the pane's scroll, not a wrap (the Arbiter, finding 71, 2).
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for entry in diff if diff is not None else (BandDiff(b, "same") for b in _shown(bands)):
        band = entry.band
        color = (pair_colours or {}).get(id(band)) or (match_map or {}).get(band.freq_hz)
        mismatch = band.freq_hz in (gain_mismatch_freqs or ())
        mark = entry.status if entry.status in marks else None
        if mark_tops and mark in ("new", "removed"):
            color = getattr(current_theme(), _MARK_TOKEN[mark])
        layout.addWidget(EqBandCard(
            band, color, mismatch, order, mark=mark,
            mark_tip=_mark_tip(entry, version) if mark else "",
            changed=entry.fields if paint else frozenset(),
            was=entry.other))
    layout.addStretch(1)
    return container


#: A tier's name on its picker, written out as the Arbiter asked: «Virtual: / Output: / Input:».
_TIER_NAME = {"virtual_channels": "Virtual", "physical_outputs": "Output", "inputs": "Input"}


def _dot_icon(colour: QColor) -> QIcon:
    """A tier's status dot, drawn inside its picker (not beside it, where it floated)."""
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    painter.drawEllipse(0, 0, 16, 16)
    painter.end()
    return QIcon(pixmap)


#: Marks a cell whose value differs from the compared version (the Arbiter, 2026-09-23).
CHANGED_ROLE = Qt.ItemDataRole.UserRole + 7


def fill_compare_combo(combo: QComboBox, versions: list, labels: Optional[dict] = None,
                       others: Optional[list] = None, preset: Optional[str] = None,
                       current: Optional[str] = None) -> None:
    """«Порівняти з»: «—», this preset's versions under its own heading, then each other preset's
    under its.

    `preset` heads the first group the same way `others` heads the rest (tcc#103, finding 112):
    the open configuration's own versions used to be drawn bare, right under «—», with no way to
    tell them apart from a flat list. `current`, if it is among `versions`, gets a disabled,
    greyed row of its own — «v_002 — зараз» — instead of being silently absent: a version is never
    something to compare with itself, but dropping it read as "where did my versions go".

    `others` is `[(preset, [(key, label), …]), …]` (finding 66). The key of another preset's
    version carries that preset (`SQ/v_004`) because on the old layout each preset numbers its
    own, and the loader has to know where to read it from."""
    combo.clear()
    combo.addItem("—", None)
    if preset is not None:
        combo.addItem(i18n.t("cmpOwnPreset").format(preset=preset), None)
        combo.model().item(combo.count() - 1).setEnabled(False)
    for version in versions:
        label = str((labels or {}).get(version, version))
        if version == current:
            combo.addItem(i18n.t("cmpCurrentVersion").format(version=label), None)
            combo.model().item(combo.count() - 1).setEnabled(False)
        else:
            combo.addItem(label, str(version))
    for other, items in others or ():
        combo.insertSeparator(combo.count())
        combo.addItem(i18n.t("cmpOtherPreset").format(preset=other), None)
        combo.model().item(combo.count() - 1).setEnabled(False)
        for key, label in items:
            combo.addItem(str(label), str(key))
    # The open list as wide as its longest line: it wrapped «2.S-shelf — інший пресет» (67, 2).
    view = combo.view()
    view.setMinimumWidth(view.sizeHintForColumn(0) + 24)


#: A row's own label, kept by `mark_unreadable` beside the text that says «не читається» on it: a
#: closed box elides the label and keeps the mark whole (`with_unread_mark`).
UNREAD_LABEL_ROLE = Qt.ItemDataRole.UserRole + 8


def mark_unreadable(combo: QComboBox, key: Optional[str]) -> None:
    """`key`'s row says «не читається» and is greyed, as the current version's is: the loader
    could not read it — the method refuses a file whose `version` names another — and picked it
    compared with nothing and said nothing, as though nothing had changed (tcc#122, W-4's review
    of #89). Marked when it is first loaded, since reading every version to fill the list would
    be a read per version on every reload; the list is filled afresh on the next one."""
    index = combo.findData(key) if key else -1
    item = combo.model().item(index) if index >= 0 else None
    if item is None or not item.isEnabled():
        return
    label = combo.itemText(index)
    combo.setItemData(index, label, UNREAD_LABEL_ROLE)
    combo.setItemText(index, i18n.t("cmpUnreadable").format(version=label))
    item.setEnabled(False)


def unread_mark(combo: QComboBox) -> Optional[tuple[str, str, str]]:
    """`(the picked row's own label, what its «не читається» says before it, after it)` while the
    picked row is marked, else None. A translation may put the words on either side."""
    label = combo.currentData(UNREAD_LABEL_ROLE)
    text = combo.currentText()
    at = text.find(label) if isinstance(label, str) and label else -1
    if at < 0:
        return None
    return label, text[:at], text[at + len(label):]


def unread_mark_width(combo: QComboBox) -> int:
    """The room the picked row's «не читається» takes in the box's font; 0 on an unmarked row."""
    split = unread_mark(combo)
    if split is None:
        return 0
    return math.ceil(QFontMetricsF(combo.font()).horizontalAdvance(split[1] + split[2]))


#: What «не читається» comes down to where its words do not fit beside the version: the sign the
#: tables already give a value TCC cannot read (`UNREAD_LEG`, tcc#123). With the box greyed it
#: says "refused"; the hover says it in words (tcc#122, the controller's Ruling 26).
UNREAD_SIGN = UNREAD_LEG


def with_unread_mark(combo: QComboBox, room: int, fit, version: str = "") -> str:
    """What a closed box draws: `fit(text, room)` of the picked row. On a row marked
    «не читається» the parts give way in the controller's order (Ruling 26, tcc#122): the saved
    names, then the preset (`fit`, in what the whole mark leaves), then the mark's words — cut
    with «…», down to `UNREAD_SIGN` — and never `version`; the whole elided to `room`, never
    clipped. The mark asks no room of its own: made uncuttable it took the version at W-4's
    widths and moved the window's floor (the re-review of fix round 1)."""
    split = unread_mark(combo)
    if split is None:
        return fit(combo.currentText(), room)
    label, before, after = split
    metrics = QFontMetricsF(combo.font())

    def width(text: str) -> int:
        return math.ceil(metrics.horizontalAdvance(text))

    def held(text: str) -> str:
        return (text if width(text) <= room
                else metrics.elidedText(text, Qt.TextElideMode.ElideRight, room))

    shown = fit(label, room - width(before + after))
    if not version or version in shown:
        return held(before + shown + after)
    rest = room - width(version)
    said = after or before
    words = metrics.elidedText(said, Qt.TextElideMode.ElideRight, rest) if rest > 0 else ""
    if not any(ch.isalpha() for ch in words):  # not a letter of the words left: the sign,
        # apart from the version where there is the room
        words = next((sign for sign in (f" {UNREAD_SIGN}", UNREAD_SIGN) if width(sign) <= rest), "")
    return held(version + words if after or not before else words + version)


def paint_compare_box(box: QComboBox, text: str) -> None:
    """A «порівняти з» box closed, `text` its label — greyed while the picked row is disabled, as
    the open list draws it (`.cmp-box:disabled`): a refused version read in the ordinary colour."""
    painter = QStylePainter(box)
    painter.setPen(box.palette().color(QPalette.ColorRole.Text))
    option = QStyleOptionComboBox()
    box.initStyleOption(option)
    painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
    option.currentText = text
    item = box.model().item(box.currentIndex()) if box.currentIndex() >= 0 else None
    if item is not None and not item.isEnabled():
        option.state &= ~QStyle.StateFlag.State_Enabled
    painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)


def is_other_preset(key: Optional[str]) -> bool:
    """A compare key of another preset's version (`SQ/v_004`)."""
    return bool(key) and "/" in key


class DetailPane(QFrame):
    """The whole `.detail` panel: tabs, title, close, and a body that shows either a table or an
    EQ view. Hidden by default (`.detail` starts at max-height 0 in the prototype)."""

    closed = Signal()
    tableRowActivated = Signal(str, str)
    #: What was copied and in what format, for the window's status line.
    bankCopied = Signal(str)  # group_id, row_id -> caller opens EQ for it
    eqRequested = Signal(str, str)
    #: The compare key the Arbiter picked here (None = «—»), for the window to follow.
    compareChanged = Signal(object)
    #: What is on screen, for the tree to light: `(group id, "params" | row id)`, or `(None, None)`.
    focusChanged = Signal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("class", "panel")
        self.setVisible(False)
        self._mode: Optional[str] = None  # "table" | "eq" | "param"
        self._group: Optional[ProfileGroup] = None
        self._row: Optional[GroupRow] = None
        self._sib_row: Optional[GroupRow] = None
        self._pair_mode = False
        #: The compared version's EQ row under the current one (tcc#54): the Arbiter's, like the
        #: pair mode — it stays on from channel to channel.
        self._cmp_rows = False
        #: Inside a tab of «Режим контролю»: the tabs above are the navigation, so the pane carries
        #: no menu of its own, and a row asks for the EQ tab instead of turning into it (finding 47).
        self._embedded = False
        #: Where «← …» returns from an EQ: `(label, callback)`, or None.
        self._back: Optional[tuple] = None
        self._eq_chips: dict = {}
        self._compare_version: Optional[str] = None
        self._compare_text = ""
        self._selected: Optional[str] = None
        self._eq_order: tuple = _ORDER_DEFAULT
        #: Each tier's own pick, kept while another tier is on screen (finding 71, 6).
        self._tier_choice: dict = {}
        self._tier_pickers: dict = {}
        self._tier_status: dict = {}
        #: The whole project view, for the one-parameter tabs: gain, delay and phase are asked
        #: about ACROSS the rig ("show the table for all channels, physical and virtual" -- user,
        #: 2026-08-23), and a single group cannot answer that.
        self._view = None
        self._param: Optional[str] = None
        #: The version the tables are compared with, and how to load one (set by the window).
        self._compare_view = None
        self._compare_loader = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QWidget()
        head.setProperty("class", "phead")
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(12, 6, 12, 6)
        head_layout.setSpacing(_HEAD_SPACING)
        self._head = head

        # «← Таблиця-О» (the Arbiter, 2026-09-25: «ось це супер»): in a control-mode tab an EQ
        # opened from a table names the way back to it. The full window needs none: «Таблиця»
        # stands right beside it, and the head has no room for the same way twice.
        self._back_btn = _DTab("←", floor="glyph")
        self._back_btn.setProperty("class", "d-tab on")
        self._back_btn.clicked.connect(self._on_back)
        self._back_btn.setVisible(False)
        head_layout.addWidget(self._back_btn)

        self._tab_table = _DTab(i18n.t("tabTable"))
        self._tab_table.clicked.connect(self._on_tab_table)
        head_layout.addWidget(self._tab_table)
        self._tab_eq = _DTab("EQ")
        self._tab_eq.clicked.connect(self._on_tab_eq)
        head_layout.addWidget(self._tab_eq)
        # The EQ's actions come down to their glyph in a tight row (`_FitLabel`, `floor="glyph"`).
        self._pair_btn = _DTab("⇄ L + R", floor="glyph")
        self._pair_btn.clicked.connect(self._on_pair_toggle)
        self._pair_btn.setVisible(False)
        head_layout.addWidget(self._pair_btn)
        # A `_FitLabel` for its `set_way("hidden")` only: it never elides, it goes when tight.
        self._eq_help = _FitLabel("?")
        self._eq_help.setProperty("class", "eq-help")
        self._eq_help.setCursor(Qt.CursorShape.WhatsThisCursor)
        self._eq_help.setVisible(False)
        self._eq_help_tip = attach_tip(self._eq_help)
        head_layout.addWidget(self._eq_help)

        # The compared version's EQ under this one (tcc#54, finding 73): left of the copy, passive
        # with no version chosen, gone in pair mode — two channels leave no room for a third row.
        self._cmp_btn = _DTab(i18n.t("cmpRowBtn"), floor="glyph")
        self._cmp_btn.clicked.connect(self._on_cmp_rows_toggle)
        self._cmp_btn.setVisible(False)
        head_layout.addWidget(self._cmp_btn)

        # The bank of the channel on screen, in the format its processor takes -- named after the
        # channel, because in the single-channel view that is what "copy EQ" means. Hidden unless
        # the method can produce one for this DSP: a copy button that yields nothing, or
        # something nobody can identify, is worse than no button (user, 2026-08-23).
        # Its floor is «К…», not «К»: the copy has no glyph of its own, and a lone letter reads
        # as a word cut with nothing to say so (the re-review of fix round 1).
        self._eq_copy = _DTab(i18n.t("copyEqBank"))
        self._eq_copy.setProperty("class", "d-tab d-copy")
        self._eq_copy.clicked.connect(self._on_copy_eq_bank)
        self._eq_copy.setVisible(False)
        head_layout.addWidget(self._eq_copy)
        # In a control-mode tab the tier pickers sit here, in the header row (finding 71, 6); the
        # full window's head is full already, so there they open the EQ's body instead.
        self._pick_holder = QWidget()
        self._pick_layout = QHBoxLayout(self._pick_holder)
        self._pick_layout.setContentsMargins(6, 0, 0, 0)
        self._pick_layout.setSpacing(4)
        self._pick_holder.setVisible(False)
        head_layout.addWidget(self._pick_holder)

        # At the END of the left cluster, after the buttons that belong to what is on screen
        # (user, 2026-08-23: "the new buttons at the end of the left set, not in the middle").
        # One parameter, every channel, both tiers -- the same kind of thing as "Table" and "EQ",
        # a way of looking at the rig, but a wider one: the question they answer is a comparison,
        # which a per-group table cannot show while it is one group at a time.
        self._param_tabs: dict[str, _DTab] = {}
        for field, label in _PARAM_TABS.items():
            tab = _DTab(label())
            tab.clicked.connect(lambda _checked=False, f=field: self.open_param(f))
            head_layout.addWidget(tab)
            self._param_tabs[field] = tab
        # The first thing in this row to give way (fix round 5): what it says, the table below
        # says too. Who gives next, and who never does, is `_fit_head`'s.
        self._title = _FitLabel("", holds=False)
        self._title.setProperty("class", "phead-sub")
        head_layout.addWidget(self._title)
        head_layout.addStretch(1)

        # «Порівняти з» (the Arbiter, 2026-09-23): what changed since another version of this preset
        # — the previous one by default — is marked in the tables, with what it was on hover.
        self._compare_label = _FitLabel(i18n.t("cmpWith"))
        self._compare_label.setProperty("class", "phead-sub")
        head_layout.addWidget(self._compare_label)
        self._compare_combo = _HeadBox()
        # `cmp-box`: a refused pick's closed box greyed (`paint_compare_box`, tcc#122).
        self._compare_combo.setProperty("class", "mini-select cmp-box")
        # As wide as a version's name, not as the longest line in its list: the head is full.
        self._compare_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._compare_combo.setMinimumContentsLength(6)
        self._compare_combo.currentIndexChanged.connect(self._on_compare_changed)
        head_layout.addWidget(self._compare_combo)
        # Said beside the list when the version picked is another preset's (finding 66).
        self._compare_other = _FitLabel(i18n.t("cmpOtherTag"))
        self._compare_other.setProperty("class", "cmp-other")
        head_layout.addWidget(self._compare_other)
        self._compare_label.setVisible(False)
        self._compare_combo.setVisible(False)
        self._compare_other.setVisible(False)

        # Shortened from its end when the row is short, not cut on both sides («(риті», the
        # Arbiter, 2026-09-25). It holds its text (fix round 5): the layout takes a small
        # shortfall equally from every item that can shrink, and this one shrank beside a title
        # with room to give -- «закрит…» on the Windows VM with the pane 840 px wide. The head's
        # minimum keeps it whole (`_fit_head`); only a row below that trims it, elided.
        self._close_btn = ElidedButton(i18n.t("close"), holds=True)
        self._close_btn.setProperty("class", "d-close")
        self._close_btn.clicked.connect(self.close_pane)
        head_layout.addWidget(self._close_btn)
        # The EQ's actions after «Фази», right before «порівняти з», copy before the pair toggle:
        # between «EQ» and «Рівень» they made the tabs jump as they came and went, and with copy
        # after the toggle the toggle moved when copy went (the Arbiter, 2026-09-25). Past the
        # stretch, so nothing on either side moves when copy goes.
        eq_actions = (self._cmp_btn, self._eq_copy, self._pair_btn, self._eq_help)
        for widget in eq_actions:
            head_layout.removeWidget(widget)
        at = head_layout.indexOf(self._compare_label)
        for offset, widget in enumerate(eq_actions):
            head_layout.insertWidget(at + offset, widget)
        # Who gives way in a short row is decided from the room the row has (`_fit_head`), so it
        # is decided again whenever the row is resized, shown, or laid out afresh -- a tab shown
        # or hidden, a language, a zoom.
        head.installEventFilter(self)
        outer.addWidget(head)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(self._scroll, stretch=1)
        # Sized by the parent QSplitter now (main_window._build_center), which gives the user a
        # drag handle between this pane and the AI dialog below it -- no fixed cap here anymore.

        i18n.on_language_changed(self.retranslate)

    def retranslate(self) -> None:
        """The head is set once at construction; the body is rebuilt from the open group.

        Its four labels were English literals while both translations already sat in the table
        (found 2026-08-12) — the pane simply never registered, so switching to Ukrainian left
        "Table", "close ✕", "Channel" and "shared frequencies:" behind in an otherwise translated
        window.
        """
        self._compare_label.setText(i18n.t("cmpWith"))
        self._compare_other.setText(i18n.t("cmpOtherTag"))
        self._tab_table.setText(i18n.t("tabTable"))
        for field, tab in getattr(self, "_param_tabs", {}).items():
            tab.setText(_PARAM_TABS[field]())
        self._close_btn.setText(i18n.t("close"))
        # With a group open, `refresh_with` rewrites this button (and the per-row ones) anyway.
        # With the pane closed it does not run, and the button kept the language the pane was
        # built in until it was next opened — invisible, and wrong the moment it appeared (F-033).
        self._eq_copy.setText(i18n.t("copyEqBank"))
        self._cmp_btn.setText(i18n.t("cmpRowBtn"))
        if self._group is not None:
            self.refresh_with(self._group)

    # ---- public API ----------------------------------------------------

    def set_embedded(self, on: bool) -> None:
        """Inside a tab of «Режим контролю»: no menu of its own, no «Закрити ✕», no «порівняти з»
        (one sits by the tabs and drives them all), and a row asks for the EQ tab (`eqRequested`)
        instead of turning this table into an EQ with no way back (finding 47)."""
        self._embedded = on
        self._compare_label.setVisible(False)
        self._compare_combo.setVisible(False)
        # The full window's tabs hold their text while the row has the room; a control-mode
        # tab's chips give way, down to a glyph and «…» (finding 105; fix round 5) -- `_fit_head`
        # reads `_embedded`, and `_sync_tabs` below runs it.
        if on:
            # The row reads: the way back, the channels, then the actions at its end (the
            # Arbiter, 2026-09-25: «ось це в кінець строчки»).
            head = self._head.layout()
            head.removeWidget(self._pick_holder)
            head.insertWidget(head.indexOf(self._back_btn) + 1, self._pick_holder)
        self._sync_tabs()

    def set_eq_order(self, order: tuple) -> None:
        """Freq · Q · Gain or Freq · Gain · Q — the processor's own order (finding 68)."""
        self._eq_order = tuple(order)
        if self._mode == "eq" and self._group is not None and self._row is not None:
            self.open_eq(self._group, self._row)

    def set_back(self, label: Optional[str], callback=None) -> None:
        """Name the way back from the EQ on screen, or say there is none."""
        self._back = (label, callback) if label and callback is not None else None
        self._sync_tabs()

    def _on_back(self) -> None:
        back, self._back = self._back, None
        if back is not None:
            back[1]()
        self._sync_tabs()

    def close_pane(self) -> None:
        self.setVisible(False)
        # Clear what's "open" along with visibility -- otherwise `current_group_id()`/
        # `refresh_with()` would keep reporting the just-closed group as open (`_group` isn't
        # otherwise touched by closing), and a later reload would silently re-open a pane the user
        # explicitly closed.
        self._group, self._row, self._mode = None, None, None
        self._back = None
        self.closed.emit()
        self.focusChanged.emit(None, None)

    def focus(self) -> tuple:
        """`(group id, "params" | row id)` of what is on screen, or `(None, None)`."""
        if self._mode == "eq" and self._group is not None and self._row is not None:
            return self._group.id, self._row.id
        if self._mode == "table" and self._group is not None:
            return self._group.id, self._selected or "params"
        return None, None

    def open_table(self, group: ProfileGroup, select_row_id: Optional[str] = None) -> None:
        self._group, self._row, self._mode = group, None, "table"
        self._back = None
        self._selected = select_row_id
        # `rows_visible()` and not `rows`: an off channel is not part of the rig being tuned, and
        # counting it here said "· 8" over six rows (user, 2026-08-21).
        self._title.setText(f"{group.label} · {len(group.rows_visible())}")
        table = self._build_table(group)
        self._scroll.setWidget(table)
        if select_row_id is not None:
            for r, row in enumerate(group.rows_visible()):
                if row.id == select_row_id:
                    table.selectRow(r)
                    break
        self._sync_tabs()
        self.setVisible(True)
        self.focusChanged.emit(*self.focus())

    def set_view(self, view) -> None:
        """The project view behind the panel, refreshed on every load.

        Held rather than passed per call because the parameter tabs are pressed from inside this
        widget, long after whoever opened it has gone; and re-rendered from here so a preset
        switch does not leave a table of the previous preset's delays on screen.
        """
        self._view = view
        self._sync_param_tabs()
        if self._mode == "param" and self._param:
            self.open_param(self._param)

    def set_compare_choices(self, versions: list, default: Optional[str], loader,
                            labels: Optional[dict] = None, others: Optional[list] = None,
                            preset: Optional[str] = None, current: Optional[str] = None) -> None:
        """Offer these versions to compare with; `loader(key)` returns that version's view.

        `default` is the one selected (the previous configuration, by the window's choice); None,
        or nothing to actually pick, compares with nothing and hides the control. `labels` names a
        version the way the list shows it — `v_003 · SQ-1`, with the names it was saved under in
        the device (hub #198). `others` are the other presets' versions, after this one's
        (`fill_compare_combo`, finding 66); `preset` and `current` head and grey out this preset's
        own group the same way (tcc#103) — `current` may be IN `versions` now, so it is not what
        decides whether the control has anything to offer."""
        self._compare_loader = loader
        blocked = self._compare_combo.blockSignals(True)
        fill_compare_combo(self._compare_combo, versions, labels, others, preset, current)
        index = self._compare_combo.findData(default) if default else 0
        self._compare_combo.setCurrentIndex(max(index, 0))
        self._compare_combo.blockSignals(blocked)
        selectable = [v for v in versions if v != current]
        shown = bool(selectable or others) and not self._embedded
        self._compare_label.setVisible(shown)
        self._compare_combo.setVisible(shown)
        self._load_compare()
        self._sync_tabs()

    def select_compare(self, key: Optional[str]) -> None:
        """Pick `key` as the window picked it elsewhere — the same list, no echo back."""
        index = self._compare_combo.findData(key) if key else 0
        blocked = self._compare_combo.blockSignals(True)
        self._compare_combo.setCurrentIndex(max(index, 0))
        self._compare_combo.blockSignals(blocked)
        self._load_compare()
        self._rerender()

    def use_compare(self, key: Optional[str], view, text: str = "") -> None:
        """Compare with a version somebody else already loaded: the control layout's one list
        drives every tab (finding 47, 4), and reading the same file seven times is not a feature."""
        self._compare_version = key
        self._compare_text = text or (key or "")
        self._compare_view = view if key else None
        self._rerender()

    def _load_compare(self) -> None:
        version = self._compare_combo.currentData()
        self._compare_version = version
        self._compare_text = self._compare_combo.currentText() if version else ""
        self._compare_view = None
        if version and self._compare_loader is not None:
            try:
                self._compare_view = self._compare_loader(version)
            except Exception:  # noqa: BLE001 — a version that cannot be read compares with nothing
                self._compare_view = None
                # ...and says so on its row (tcc#122).
                mark_unreadable(self._compare_combo, version)
                self._compare_text = self._compare_combo.currentText()
        self._sync_box_tip()

    def _rerender(self) -> None:
        if self._mode == "param" and self._param:
            self.open_param(self._param)
        elif self._mode == "table" and self._group is not None:
            self.open_table(self._group)
        elif self._mode == "eq" and self._group is not None and self._row is not None:
            # The band marks follow the version chosen (tcc#54).
            self.open_eq(self._group, self._row)
        else:
            self._sync_tabs()

    def _on_compare_changed(self, _index: int) -> None:
        self._load_compare()
        self._rerender()
        self.compareChanged.emit(self._compare_version)

    def _compared_row(self, group_id: Optional[str], row: GroupRow) -> tuple[bool, Optional[GroupRow]]:
        """`(compared, the same channel in the compared version or None)`."""
        view = self._compare_view
        if view is None or group_id is None:
            return False, None
        group = next((g for g in getattr(view, "groups", ()) or () if g.id == group_id), None)
        if group is None:
            return True, None
        return True, next((r for r in group.rows if r.id == row.id), None)

    def _param_groups(self, field: str) -> list:
        """Every tier that declares this control and has channels to show, in the view's order."""
        groups = getattr(self._view, "groups", ()) or ()
        return [g for g in groups if field in g.known_fields and g.rows_visible()]

    def _sync_param_tabs(self) -> None:
        """A control no tier declares is not offered -- a processor without phase does not get a
        Phase tab that opens an empty table."""
        for field, tab in self._param_tabs.items():
            tab.setVisible(not self._embedded and bool(self._param_groups(field)))
            tab.set_on(self._mode == "param" and self._param == field)

    def open_param(self, field: str) -> None:
        """One control, every channel, both tiers, in one table.

        The per-group table answers "what is this tier set to"; this answers "how do these compare
        across the rig", which is the question somebody actually has about a gain or a delay --
        and it is the one shape the panel could not make before, because it only ever held one
        group at a time.
        """
        groups = self._param_groups(field)
        if not groups:
            return
        self._mode, self._param, self._row = "param", field, None
        self._back = None
        # The tab's own word, not the column header's: the header is the DSP's vocabulary
        # ("Delay ms", as PC-Tool spells it) and the title is the window's.
        self._title.setText(i18n.t("paramAllChannels").format(param=_PARAM_TABS[field]()))
        self._scroll.setWidget(self._build_param_table(field, groups))
        self._sync_tabs()
        self.setVisible(True)
        self.focusChanged.emit(None, None)

    def open_eq(self, group: ProfileGroup, row: GroupRow) -> None:
        self._group, self._row, self._mode = group, row, "eq"
        sib_name = _sibling_name(row.name)
        sib_row = next((r for r in group.rows if r.name == sib_name), None) if sib_name else None
        # Pair mode is the Arbiter's, not the channel's: a channel with no pair shows alone and
        # leaves the mode on for the next pair (2026-09-25: «повертаючись до парного — знову бачу
        # пару — це супер (було не так — скидувалось)»).
        self._sib_row = sib_row
        self._render_eq(group, row, sib_row)
        self._sync_tabs()
        self.setVisible(True)
        self.focusChanged.emit(group.id, row.id)

    def current_group_id(self) -> Optional[str]:
        """The id of the group currently shown (table or EQ), or None if nothing's open --
        lets a caller re-fetch the up-to-date `ProfileGroup` after a project reload without this
        module knowing anything about where groups come from."""
        return self._group.id if self._group is not None else None

    def refresh_with(self, group: ProfileGroup) -> None:
        """Re-render whatever's currently open (table or EQ) using a freshly loaded `group` with
        the same id. `ProfileGroup`/`GroupRow` are immutable snapshots -- without this, a table or
        EQ view left open across a preset switch keeps showing the OLD preset's frozen values
        (mute state and everything else) since nothing tells it a new version was loaded (user
        report 2026-07-28). No-op if the pane isn't currently open.

        Checks `self._group` rather than `self.isVisible()` -- the latter also depends on every
        ancestor being shown, which is false in headless tests (and would make this a silent
        no-op there) even though the pane's own open/closed state is unambiguous."""
        if self._mode == "param" and self._param:
            # Its rows come from the whole view, which `set_view` has already replaced.
            self.open_param(self._param)
            return
        if self._group is None:
            return
        if self._mode == "eq" and self._row is not None:
            row = next((r for r in group.rows if r.id == self._row.id), None)
            if row is not None:
                self.open_eq(group, row)
                return
        self.open_table(group)

    # ---- tabs -----------------------------------------------------------

    def _sync_tabs(self) -> None:
        eq_on = self._mode == "eq"
        paired = eq_on and self._pair_mode and self._sib_row is not None
        self._tab_table.set_on(self._mode == "table")
        self._tab_eq.set_on(eq_on)
        # The tab says WHOSE bank is on screen. With one channel showing, nothing else on the
        # left of the header did: the only name was on the copy button, and the title that
        # carries it sits greyed at the far end of the row (user, 2026-08-23). In pair mode it
        # stays plain -- each heading names its own channel there.
        single = eq_on and self._row is not None and not paired
        self._tab_eq.setText(f"EQ {self._row.name}" if single else "EQ")
        self._sync_param_tabs()
        self._pair_btn.set_on(self._pair_mode)
        self._pair_btn.setVisible(eq_on and self._sib_row is not None)
        comparing = self._compare_view is not None
        self._cmp_btn.setVisible(eq_on and not paired)
        self._cmp_btn.setEnabled(comparing)
        self._cmp_btn.set_on(comparing and self._cmp_rows)
        self._cmp_btn.setToolTip(i18n.t("cmpRowTip").format(version=self._compare_text)
                                 if comparing else i18n.t("cmpRowOff"))
        self._eq_help.setVisible(eq_on)
        self._eq_copy.setText(f'{i18n.t("copyEqBank")} {self._row.name}' if single
                              else i18n.t("copyEqBank"))
        # Gone in pair mode: with two channels on screen it would name one of them, each heading
        # carries its own, and a passive grey one only doubled them (the Arbiter, 2026-09-25:
        # «дублює сірим»).
        self._eq_copy.setVisible(
            eq_on
            and not paired
            and self._row is not None
            and bool(self._row.raw.get("eq"))
            and eq_export.available()
        )
        self._back_btn.setVisible(eq_on and self._back is not None)
        if self._back is not None:
            self._back_btn.setText(self._back[0])
        menu = not self._embedded
        for widget in (self._tab_table, self._tab_eq, self._close_btn):
            widget.setVisible(menu)
        self._compare_other.setVisible(menu and self._compare_combo.isVisibleTo(self)
                                       and is_other_preset(self._compare_version))
        # Inside a control-mode tab the head is only for the EQ: its way back, its pair, its copy.
        # No grey «EQ · m-L» over an EQ in either mode: the lit picker, or the «EQ m-L» tab, says
        # which one it is, and in the full window the head needed the room for the copy.
        self._head.setVisible(menu or eq_on)
        self._title.setVisible(menu and not eq_on)
        self._pick_holder.setVisible(self._embedded and eq_on)
        self._fit_head()

    # ---- the head in a short row (tcc#96, finding 119) -------------------------------------

    def _head_stages(self) -> list:
        """The head's items in the order they give way when the row is short (finding 119, the
        re-review of fix round 5), each stage with what its items come down to: the title first,
        to its floor -- what it says, the table below says too; then «порівняти з», the «інша
        конфігурація» tag and the EQ's «?», whole or hidden -- the list beside them names the
        version, and «п…» said nothing for 64 px (the review of the follow-up); then the tabs
        and the list, to their floors -- a tab to a glyph and «…», an EQ action to its glyph,
        the list to «v_NNN», never to nothing. «закрити ✕» keeps its floor throughout. What is
        left when all three have given is the head's own minimum, and it has to sit inside the
        centre's floor (tcc#106's two thirds of the screen, less the sides), or Qt trims the
        widest items below their floors: the list showed «v_», then nothing."""
        return [([self._title], "floor"),
                ([self._compare_label, self._compare_other, self._eq_help], "hidden"),
                ([*self._head.findChildren(_DTab), self._compare_combo], "floor")]

    def _head_shows(self, widget: QWidget) -> bool:
        """Whether the owner shows this item -- the fit's own hiding does not count."""
        return widget.wanted() if isinstance(widget, _FitLabel) else widget.isVisibleTo(self._head)

    @staticmethod
    def _whole_of(widget: QWidget) -> int:
        return widget.whole_width() if hasattr(widget, "whole_width") else widget.sizeHint().width()

    @staticmethod
    def _floor_of(widget: QWidget) -> int:
        return (widget.floor_width() if hasattr(widget, "floor_width")
                else widget.minimumSizeHint().width())

    def head_asks(self) -> list:
        """The widths the head asks for: `[0]` with everything whole, then with each stage of
        `_head_stages` given in turn -- `[1]` the title at its floor and the rest whole, `[2]`
        the labels and the «?» hidden too, `[3]` the tabs and the list at their floors too, which
        is the head's own minimum. Counted from the items' whole and floor widths (a hidden one
        takes its spacing with it), not from what they ask for right now, so the numbers do not
        move with the way `_fit_head` last set them."""
        layout = self._head.layout()
        shown = [w for w in (layout.itemAt(i).widget() for i in range(layout.count()))
                 if w is not None and self._head_shows(w)]
        margins, spacing, gaps = layout.contentsMargins(), _HEAD_SPACING, len(shown) - 1
        width = margins.left() + margins.right() + spacing * gaps
        width += sum(self._whole_of(w) for w in shown)
        asks = [width]
        stages = self._head_stages()
        for widgets, target in stages:
            for widget in widgets:
                if not self._head_shows(widget):
                    continue
                if target == "hidden":
                    width -= self._whole_of(widget) + spacing
                    gaps -= 1
                else:
                    width -= self._whole_of(widget) - self._floor_of(widget)
            asks.append(width)
        # The last stage tightens the gaps too.
        asks[-1] -= max(0, gaps) * (_HEAD_SPACING - _HEAD_SPACING_TIGHT)
        return asks

    def head_need(self) -> int:
        """The width at which the head reads whole but for the title -- the tabs, «закрити ✕»,
        the compare label, list and tag -- for those of them the head shows now. What the full
        window's floor holds (tcc#106, `MainWindow._head_need`)."""
        return self.head_asks()[1]

    def _fit_head(self) -> None:
        """Sets each stage's way by the room the head has now: the first stage that still fits
        with everything after it whole gives (a whole-or-hidden stage hides: it has no between);
        the stages before it have given all -- at their floors, or hidden; the ones after it
        hold. In a control-mode tab every chip gives (finding 105). A head not shown yet has no
        width to judge by: the defaults, until its first show or resize."""
        stages = self._head_stages()
        giving = 1
        if self._embedded:
            ways = ["gives"] * len(stages)
        elif not self._head.isVisible():
            ways = ["gives"] + ["holds"] * (len(stages) - 1)
        else:
            asks, width = self.head_asks(), self._head.width()
            giving = next((i for i in range(1, len(asks)) if width >= asks[i]), len(stages))
            ways = []
            for i, (_widgets, target) in enumerate(stages, start=1):
                if i < giving:
                    ways.append(target)
                elif i == giving:
                    ways.append("gives" if target == "floor" else target)
                else:
                    ways.append("holds")
        for (widgets, _target), way in zip(stages, ways):
            for widget in widgets:
                widget.set_way(way)
        # The gaps tighten with the last stage, the tabs giving (`_HEAD_SPACING_TIGHT`).
        spacing = _HEAD_SPACING_TIGHT if giving == len(stages) else _HEAD_SPACING
        if self._head.layout().spacing() != spacing:
            self._head.layout().setSpacing(spacing)
        self._sync_box_tip()

    def _sync_box_tip(self) -> None:
        """What a hidden label said goes into the list's hover, as control mode's corner does
        (the re-review of fix round 1: at two thirds of the screen the tag hid over the table
        too, and another configuration's «v_002» read as this configuration's own)."""
        said = []
        if self._compare_label.way() == "hidden":
            said.append(i18n.t("cmpWith"))
        if self._compare_other.way() == "hidden" and is_other_preset(self._compare_version):
            preset = self._compare_version.split("/", 1)[0]
            said.append(i18n.t("cmpOtherTip").format(
                version=f"{preset} · {self._compare_combo.currentText()}"))
        elif unread_mark(self._compare_combo) is not None:
            # The box says «не читається» as far as its room goes, down to a sign: the hover says
            # it whole (tcc#122, Ruling 26).
            said.append(self._compare_combo.currentText())
        tip = "\n".join(said)
        if self._compare_combo.toolTip() != tip:
            self._compare_combo.setToolTip(tip)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt override)
        if watched is self._head and event.type() in (
                QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest):
            self._fit_head()
        return super().eventFilter(watched, event)

    def _on_tab_table(self) -> None:
        if self._group is not None:
            self.open_table(self._group)

    def _on_tab_eq(self) -> None:
        if self._row is not None:
            self.open_eq(self._group, self._row)
        elif self._group is not None and self._group.rows_visible():
            self.open_eq(self._group, self._group.rows_visible()[0])

    def _on_copy_eq_bank(self) -> None:
        """The header's copy: the channel this view was opened on."""
        if self._row is not None and self._group is not None:
            self._copy_bank_of(self._group, self._row)

    def _copy_bank_of(self, group: ProfileGroup, row: GroupRow) -> None:
        """One channel's whole bank, ready to paste into the DSP's own software.

        The window formats nothing: it asks the method, puts what came back on the clipboard, and
        says WHICH format that was -- plus anything the format could not carry, because a band
        quietly dropped on the way to a processor is the kind of loss nobody notices until the
        tune sounds wrong.
        """
        raw = row.raw
        bank = eq_export.format_bank(
            raw.get("eq"),
            crossovers={"hp": raw.get("hp"), "lp": raw.get("lp")},
            group_id=group.id,
            channel=row.name,
        )
        if bank is None:
            self.bankCopied.emit(i18n.t("copyEqNoFormat"))
            return
        QGuiApplication.clipboard().setText(bank.text)
        self.bankCopied.emit(_bank_sentence(row.name, bank))

    def _on_cmp_rows_toggle(self) -> None:
        if self._compare_view is None:
            return
        self._cmp_rows = not self._cmp_rows
        if self._row is not None:
            self.open_eq(self._group, self._row)

    def _on_pair_toggle(self) -> None:
        self._pair_mode = not self._pair_mode
        if self._row is not None:
            self.open_eq(self._group, self._row)

    # ---- table view -------------------------------------------------------

    def _build_table(self, group: ProfileGroup) -> QTableWidget:
        columns = table_fields(group)
        headers = ["ID", i18n.t("colChan")] + [_FIELD_COLUMNS[f] for f in columns]
        rows = group.rows_visible()
        # Each column to its content, the rest of the pane's width shared (`_ContentTable`): the
        # user's "table on full width", without nine equal columns as wide as the widest.
        table = _ContentTable(len(rows), len(headers))
        table.setProperty("class", "ptable")
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        header = table.horizontalHeader()
        apply_caps(header, spacing_px=0.7)  # QSS text-transform/letter-spacing don't apply to th

        t = current_theme()
        for r, row in enumerate(rows):
            id_item = QTableWidgetItem(row.slot or row.id)
            id_item.setForeground(QColor(t.accent))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            table.setItem(r, 0, id_item)
            name_item = QTableWidgetItem(row.name)
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            table.setItem(r, 1, name_item)
            for c, field in enumerate(columns, start=2):
                table.setItem(r, c, self._styled_cell(field, row, t, group.id))
            table.setRowHeight(r, 26)

        def _activate(r: int, _c: int) -> None:
            row_obj = rows[r]
            self.tableRowActivated.emit(group.id, row_obj.id)
            # cellClicked fires from inside QTableWidget's own mouseReleaseEvent; open_eq()
            # replaces this table's widget in self._scroll (QScrollArea.setWidget deletes the
            # old widget synchronously), which would destroy `table` while it is still executing
            # its own C++ event handler -- a use-after-free that crashes with SIGSEGV. Deferring
            # to the next event-loop tick lets mouseReleaseEvent return first.
            self._open_eq_from_here(group, row_obj)

        table.cellClicked.connect(_activate)
        self._copy_on_right_click(table)
        return table

    def _build_param_table(self, field: str, groups: list) -> QWidget:
        """One column per tier, side by side -- virtual channels next to the outputs.

        Stacked, the two tiers were a scroll: eight outputs below six virtual channels, with the
        heading of the second block off screen by the time you reached it (user, 2026-08-23:
        "make it two columns, virtual beside output"). Side by side they fit, and the comparison
        that the whole view exists for -- how these numbers sit against each other -- is one
        glance instead of two.
        """
        holder = QWidget()
        columns = QHBoxLayout(holder)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(12)
        for group in groups:
            columns.addWidget(self._param_column(field, group), stretch=1)
        return holder

    def _param_column(self, field: str, group: ProfileGroup) -> QWidget:
        """One tier: its name, then `ID · channel · value` for every channel in it."""
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The tier's name in the panel's language. `group.label` is the PROFILE's word for it
        # ("Output channels"), which is English in a file written once, and reads as a foreign
        # line among Ukrainian rows -- the same fix the project-params rows got.
        said = i18n.t(f"chanSum_{group.id}")
        title = QLabel(said if said != f"chanSum_{group.id}" else group.label)
        title.setProperty("class", "kv-lbl")
        title.setContentsMargins(8, 6, 8, 2)
        layout.addWidget(title)

        rows = group.rows_visible()
        table = QTableWidget(len(rows), 3)
        table.setProperty("class", "ptable")
        table.setHorizontalHeaderLabels(["ID", i18n.t("colChan"), _FIELD_COLUMNS[field]])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        apply_caps(header, spacing_px=0.7)

        t = current_theme()
        for r, row in enumerate(rows):
            id_item = QTableWidgetItem(row.slot or row.id)
            id_item.setForeground(QColor(t.accent))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            table.setItem(r, 0, id_item)
            name_item = QTableWidgetItem(row.name)
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            table.setItem(r, 1, name_item)
            table.setItem(r, 2, self._styled_cell(field, row, t, group.id))
            table.setRowHeight(r, 26)

        def _activate(clicked: int, _c: int) -> None:
            row_obj = rows[clicked]
            self.tableRowActivated.emit(group.id, row_obj.id)
            # Deferred for the same reason as the group table's: this runs inside the table's own
            # mouse handler, and opening the EQ replaces (and destroys) the widget under it.
            self._open_eq_from_here(group, row_obj)

        table.cellClicked.connect(_activate)
        self._copy_on_right_click(table)
        layout.addWidget(table)
        return block

    def _open_eq_from_here(self, group: ProfileGroup, row: GroupRow) -> None:
        """A row was clicked: its EQ, with the way back to what was on screen.

        Embedded, the table stays a table and the control layout opens the EQ tab (finding 47, 5:
        the table tab turned into the EQ, and there was no way back without leaving the mode)."""
        if self._embedded:
            self.eqRequested.emit(group.id, row.id)
            return
        QTimer.singleShot(0, lambda: self.open_eq(group, row))

    def _copy_on_right_click(self, table: QTableWidget) -> None:
        """Right-click a cell and its value is on the clipboard, with a tip saying which.

        No menu: "copy the value" was the only item a table cell could offer, and a one-item menu
        is a question with one answer (user, 2026-08-23). The tip is the receipt -- a copy with no
        feedback leaves you pressing again to be sure, which is how the number you wanted gets
        replaced by the one under it.
        """
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        def _copy(pos) -> None:
            item = table.itemAt(pos)
            if item is None:
                return
            # The cell's own pasteable value when it has one, its text otherwise (an ID, a name).
            text = (item.data(Qt.ItemDataRole.UserRole) or item.text() or "").strip()
            if not text:
                return
            copy_menu.copy_text(text)
            said = i18n.t("copiedValue").format(value=text)
            tip = rounded_tooltip.RoundedTooltip.instance()
            tip.show_at(table.viewport().mapToGlobal(pos) + QPoint(14, 14), said)
            # Hidden on a timer, and only if it is still OUR tip: another one may have taken the
            # singleton over in the meantime, and hiding somebody else's would be a flicker
            # nobody could explain.
            QTimer.singleShot(1500, lambda: tip.hide_tip() if tip.text() == said else None)

        table.customContextMenuRequested.connect(_copy)

    def _styled_cell(self, field: str, row: GroupRow, t,
                     group_id: Optional[str] = None) -> QTableWidgetItem:
        """A value cell with prototype-style alignment + colour: numbers right-aligned, gain
        green/orange by sign, INV highlighted, the EQ count an accent link. Mirrors the web
        `.ptable` cell classes (`.gpos/.gneg/.tinv/.eqcell`)."""
        item = QTableWidgetItem(self._cell_text(field, row))
        # The pasteable form rides along with the cell, so the copy does not have to work out
        # afterwards what kind of number it is looking at.
        item.setData(Qt.ItemDataRole.UserRole, self._copy_value(field, row))
        if field in ("hp", "lp", "gain_db", "ta_ms", "phase_deg", "eq"):
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        elif field in ("polarity", "mute", "off", "eq_bypass"):
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        color = None
        if field in ("gain_db", "ta_ms", "phase_deg"):
            # Zero is not a setting, it is the absence of one, and it was reading as a boost:
            # a column of green `+0.0` next to the two channels that actually carry gain (user,
            # 2026-08-23: "colours — nought in grey"). Only a real value gets a colour, and gain
            # keeps its sign meaning: up is the app's green, down is its accent.
            v = row.raw.get(field)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if not v:
                    color = t.faint
                elif field == "gain_db":
                    color = t.ok if v > 0 else t.accent
        elif field == "polarity":
            color = t.inv if row.raw.get("polarity") == "INV" else t.muted
        elif field == "eq":
            color = t.accent if row.eq_count() > 0 else t.faint
        elif field == "off":
            color = t.off if row.raw.get("off") else None
        elif field in ("hp", "lp") and self._cell_text(field, row) == "OFF":
            color = t.faint
        if color:
            item.setForeground(QColor(color))
        compared, old = self._compared_row(group_id, row)
        if compared and field_changed(field, row, old):
            before = self._cell_text(field, old) if old is not None else None
            item.setData(CHANGED_ROLE, True)
            # Blue and bold: the table's stylesheet paints over an item's background, and the
            # change has to read at a glance — blue is the window's "new" (in REW, import it).
            item.setForeground(QColor(t.info))
            item.setBackground(QColor(t.mix("info", 14, "panel")))
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            if before is None:
                item.setToolTip(i18n.t("cmpNew"))
            elif before == self._cell_text(field, row):
                item.setToolTip(i18n.t("cmpEqChanged"))
            else:
                item.setToolTip(i18n.t("cmpWas").format(value=before))
        unread = unread_leg_tip(field, row)
        if unread:
            item.setToolTip("\n".join(filter(None, (item.toolTip(), unread))))
        return item

    @staticmethod
    def _copy_value(field: str, row: GroupRow) -> str:
        """What a right-click puts on the clipboard: what you would TYPE, not what you read.

        A crossover cell reads `350 LR6` and only the 350 can be pasted -- the type is a dropdown
        in the DSP's software, not a number field (user, 2026-08-23). The same rule settles the
        rest: no leading `+` on a gain, no degree sign on a phase, no unit anywhere. The screen
        keeps the reading; the clipboard carries the value.
        """
        raw = row.raw
        if field in ("hp", "lp"):
            if cell_text(field, row) == UNREAD_LEG:
                return ""  # nothing a DSP would take (tcc#123)
            leg = CrossoverLeg.from_raw(raw.get(field))
            return f"{leg.freq_hz:g}" if leg.enabled and leg.freq_hz is not None else ""
        if field in ("gain_db", "ta_ms", "phase_deg"):
            v = raw.get(field)
            return f"{v:g}" if isinstance(v, (int, float)) and not isinstance(v, bool) else ""
        return ""

    _cell_text = staticmethod(cell_text)

    # ---- EQ view ----------------------------------------------------------

    def _fill_pickers(self, layout, group: ProfileGroup, row: GroupRow,
                      sib_row: Optional[GroupRow]) -> None:
        """«Virtual: VFL/VFR   Output: tw-L/tw-R   Input: -/-»: one picker per tier with channels,
        the tier on screen lit, its status dot inside, a click dropping down the tier's channels
        with their «(active/configured)» (finding 71, 6, and the Arbiter's look at it: full names,
        a width that does not jump, one name and one mark in single mode)."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
                item.widget().deleteLater()
        self._tier_pickers, self._tier_status = {}, {}
        self._tier_choice[group.id] = row.id
        paired = self._pair_mode
        shown = {row.id} | ({sib_row.id} if paired and sib_row is not None else set())
        old = getattr(self._compare_view, "groups", ()) or ()
        compared = self._compare_view is not None
        colours = current_theme()
        for tier in (g for g in (getattr(self._view, "groups", ()) or ()) if g.rows_visible()):
            rows = tier.rows_visible()
            by_name = {r.name: r for r in rows}
            if tier.id == group.id:
                pick, partner = row, sib_row
            else:
                chosen = self._tier_choice.get(tier.id)
                pick = (next((r for r in rows if r.id == chosen), None)
                        or next((r for r in rows if r.eq_count() > 0), None))
                partner = by_name.get(_sibling_name(pick.name) or "") if pick is not None else None
            name = _TIER_NAME.get(tier.id, tier.label or "?")
            button = _TierPickButton()
            button.setText(f"{name}: {self._pair_text(pick, partner, paired)}")
            button.setProperty("class", "tier-pick on" if tier.id == group.id else "tier-pick")
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            status = field_status([tier], "eq", old, compared)
            button.setIcon(_dot_icon(QColor({"none": colours.off, "set": colours.ok,
                                             "chg": colours.info}[status])))
            button.setIconSize(QSize(8, 8))
            # With an icon a tool button shows ONLY the icon unless told otherwise.
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setToolTip(tip_for(status, self._compare_text))
            # As wide as the longest thing it can say, so switching never moves the row -- the
            # PREFERRED width, not a fixed one: a squeezed head still has to be able to shrink it
            # (tcc#96, finding 105), which is what elides its text instead of clipping the whole
            # button past the row's edge.
            button.ensurePolished()
            labels = [f"{name}: {self._pair_text(r, by_name.get(_sibling_name(r.name) or ''), p)}"
                      for r in rows for p in (False, True)] or [f"{name}: -/-"]
            # Measured, chrome and all: a guessed 40 px of chrome held the longest label on the
            # Mac and not on the Windows runner's fontless text (CI at f9d3a9e).
            button.set_preferred_width(max(button.width_for(label) for label in labels))
            menu = QMenu(button)
            for r in rows:
                count = band_count(r.eq_bands())
                action = menu.addAction(f"{r.name} {count}" if count else f"{r.name} —")
                action.setCheckable(True)
                action.setChecked(tier.id == group.id and r.id in shown)
                # Deferred: the menu belongs to the picker this call replaces.
                action.triggered.connect(lambda _c=False, g=tier, rr=r:
                                         QTimer.singleShot(0, lambda: self.open_eq(g, rr)))
            button.setMenu(menu)
            layout.addWidget(button)
            self._tier_pickers[tier.id] = button
            self._tier_status[tier.id] = status

    @staticmethod
    def _pair_text(pick: Optional[GroupRow], partner: Optional[GroupRow], paired: bool) -> str:
        """`m-L`, or `m-L/m-R` in pair mode — L first whichever was picked; `-` / `-/-` for none."""
        if pick is None:
            return "-/-" if paired else "-"
        if not paired or partner is None:
            return pick.name
        left, right = (pick, partner) if _is_left(pick.name) else (partner, pick)
        return f"{left.name}/{right.name}"

    def _band_diff(self, group: ProfileGroup, row: GroupRow) -> tuple:
        """`(current side, compared side, the compared channel)`; `(None, None, None)` with no
        version chosen. A channel the compared version lacks: every band of it is new."""
        compared, old_row = self._compared_row(group.id, row)
        if not compared:
            return None, None, None
        old = _shown(old_row.eq_bands()) if old_row is not None else []
        now_side, was_side = compare_bands(_shown(row.eq_bands()), old)
        return now_side, was_side, old_row

    def _single_rows(self, layout, group: ProfileGroup, row: GroupRow) -> None:
        """One channel's bands, marked against the version chosen; with «⇅ Порівняти» on, that
        version's bands under them, named, each changed pair in one colour and the values to enter
        in red (tcc#54, finding 73)."""
        now_side, was_side, old_row = self._band_diff(group, row)
        rows_on = self._cmp_rows and now_side is not None
        colours = _pair_colours(now_side) if rows_on else None
        if now_side is not None:
            layout.addWidget(_compare_legend(now_side, was_side, colours))
        layout.addWidget(_band_flow(row.eq_bands(), order=self._eq_order, diff=now_side,
                                    marks=("new", "chg"), paint=rows_on,
                                    version=self._compare_text, pair_colours=colours,
                                    mark_tops=True))
        if not rows_on:
            return
        if old_row is None:
            said = QLabel(f"{self._compare_text} · {i18n.t('cmpNew')}")
            said.setProperty("class", "eq-rowlab")
            layout.addWidget(said)
            return
        heading = QLabel(f"{self._compare_text} · {old_row.name} {band_count(old_row.eq_bands())}")
        heading.setProperty("class", "eq-rowlab")
        layout.addWidget(heading)
        # Its values plain: red is for what is to be entered, the row above (the Arbiter,
        # 2026-09-26); the pair colour on top says which band above it was.
        layout.addWidget(_band_flow(old_row.eq_bands(), order=self._eq_order, diff=was_side,
                                    marks=("removed",), pair_colours=colours, mark_tops=True))

    def _render_eq(self, group: ProfileGroup, row: GroupRow, sib_row: Optional[GroupRow]) -> None:
        self._eq_help_tip.set_text(i18n.t("eqHint"))

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)
        if self._embedded:
            self._fill_pickers(self._pick_layout, group, row, sib_row)
        else:
            row_of_pickers = QWidget()
            self._fill_pickers(QHBoxLayout(row_of_pickers), group, row, sib_row)
            row_of_pickers.layout().setContentsMargins(0, 0, 0, 0)
            row_of_pickers.layout().addStretch(1)
            layout.addWidget(row_of_pickers)

        if self._pair_mode and sib_row:
            l_row, r_row = (row, sib_row) if _is_left(row.name) else (sib_row, row)
            l_bands, r_bands = l_row.eq_bands(), r_row.eq_bands()
            shared = sorted({b.freq_hz for b in l_bands} & {b.freq_hz for b in r_bands})
            match_map = {f: _MATCH_PALETTE[i % len(_MATCH_PALETTE)] for i, f in enumerate(shared)}
            l_gain_by_freq = {b.freq_hz: b.gain_db for b in l_bands}
            r_gain_by_freq = {b.freq_hz: b.gain_db for b in r_bands}
            gain_mismatch = {f for f in shared if l_gain_by_freq.get(f) != r_gain_by_freq.get(f)}

            if shared:
                legend = QWidget()
                legend_layout = QHBoxLayout(legend)
                legend_layout.setContentsMargins(0, 0, 0, 0)
                legend_layout.addWidget(QLabel(i18n.t("shared")))
                for f in shared:
                    chip = QLabel(f"⬤ {f:g} Hz")
                    chip.setStyleSheet(f"color: {match_map[f]};")
                    legend_layout.addWidget(chip)
                legend_layout.addStretch(1)
                layout.addWidget(legend)
            else:
                # The key existed and the string was hardcoded past it: an English line among
                # Ukrainian ones, in the view that compares two channels.
                layout.addWidget(QLabel(i18n.t("noShared")))

            for label, r in (("L", l_row), ("R", r_row)):
                # The heading carries its own copy: with two channels on screen, one button in
                # the header says "copy EQ" and means only one of them (user, 2026-08-23). Beside
                # the name there is no ambiguity about whose bank it is.
                heading = QWidget()
                heading_row = QHBoxLayout(heading)
                heading_row.setContentsMargins(0, 0, 0, 0)
                heading_row.setSpacing(8)
                row_label = QLabel(f"{label} · {r.name} {band_count(r.eq_bands())}")
                row_label.setProperty("class", "eq-rowlab")
                heading_row.addWidget(row_label)
                if eq_export.available() and r.raw.get("eq"):
                    copy_btn = _DTab(i18n.t("copyEqBank"))
                    copy_btn.setProperty("class", "d-tab d-copy")
                    copy_btn.clicked.connect(
                        lambda _checked=False, target=r: self._copy_bank_of(group, target)
                    )
                    heading_row.addWidget(copy_btn)
                heading_row.addStretch(1)
                layout.addWidget(heading)
                layout.addWidget(_band_flow(r.eq_bands(), match_map, gain_mismatch,
                                            self._eq_order, diff=self._band_diff(group, r)[0],
                                            marks=("new", "chg"), version=self._compare_text))
        else:
            self._single_rows(layout, group, row)

        layout.addStretch(1)
        self._scroll.setWidget(container)
        # `id` and `name` are the same string until a channel is renamed (SCR-039), and repeating
        # it reads as a bug in the header rather than as two facts.
        self._title.setText(f"EQ · {row.name}" if row.id == row.name
                            else f"EQ · {row.name} ({row.id})")
