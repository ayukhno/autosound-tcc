"""Dark/light palette + QSS builder — ported from the web prototype's `:root` custom
properties (`data/private/prototype/tcc-main.html`).

QSS has neither CSS custom properties nor `color-mix()`, so both are reproduced here in Python:
`PALETTE_DARK`/`PALETTE_LIGHT` are the base tokens (exact hex values copied from the prototype's
`:root[data-theme="dark"]` / `:root[data-theme="light"]` blocks), and `mix()` reimplements the
CSS Color 4 `color-mix(in srgb, A P%, B)` algorithm used throughout the prototype for hover
states, subtle backgrounds, and shadows. Every widget's style should go through `build_qss()` —
never a per-widget inline `setStyleSheet()` — so both themes stay in sync automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QComboBox, QWidget

Mode = Literal["dark", "light"]


#: What a `.mini-select` popup spends on something other than the label: 28 px of left padding
#: reserving the check mark, 14 px on the right, the view's own 3 px either side, and room for a
#: scrollbar when the list is long. Measured off the stylesheet in this file rather than guessed —
#: if those numbers change, this one follows them.
_POPUP_CHROME_PX = 28 + 14 + 6 + 18


class MiniCombo(QComboBox):
    """A `.mini-select` whose DROP-DOWN is as wide as its widest row, whatever the box's width.

    Qt sizes a popup to the closed box unless told otherwise. These combos are narrow on purpose —
    they sit in tight rows — and `AdjustToContents` only grows the box when the layout lets it, so
    on a platform where the UI font is wider the rows came back elided: `AGY · Gem...sh (High)`,
    `x...h`, and in the narrowest one nothing but `...` (user, on Windows 11, 2026-08-19). The
    label is the whole point of the list; the closed box may elide, the list may not.

    Done at `showPopup` rather than after filling: the contents change (a catalogue arrives, a
    language switches, a project is loaded) and a width computed once goes stale without anybody
    noticing. Here it is right every time it is opened, and costs one pass over the rows.
    """

    def showPopup(self) -> None:  # noqa: N802 (Qt override)
        view = self.view()
        if view is not None and self.count():
            metrics = self.fontMetrics()
            widest = max(metrics.horizontalAdvance(self.itemText(i)) for i in range(self.count()))
            view.setMinimumWidth(widest + _POPUP_CHROME_PX)
        super().showPopup()


def mini_combo() -> MiniCombo:
    """A themed `.mini-select` that grows to fit its content — and whose popup always does."""
    combo = MiniCombo()
    combo.setProperty("class", "mini-select")
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    return combo


def apply_caps(widget: QWidget, spacing_px: float = 1.0, upper: bool = True) -> None:
    """Apply small-caps tracking to a widget's font. Qt Style Sheets silently ignore both
    `text-transform` and `letter-spacing`, so the prototype's uppercase, spaced-out section
    labels have to be reproduced through the widget's QFont instead of QSS."""
    f = widget.font()
    if upper:
        f.setCapitalization(QFont.Capitalization.AllUppercase)
    if spacing_px:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing_px)
    widget.setFont(f)

# Exact copies of the prototype's :root[data-theme="..."] tokens.
PALETTE_DARK: dict[str, str] = {
    "ground": "#0f1318", "panel": "#161b22", "panel2": "#1c232c", "panel3": "#222b36",
    "border": "#263040", "border2": "#33404f",
    "text": "#dfe6ee", "muted": "#8b97a6", "faint": "#5f6b7a",
    "accent": "#e8973c", "accent_dim": "#b3712c",
    "ok": "#4bbf87", "inv": "#e8973c", "off": "#6a7686", "warn": "#e05c5c",
    "info": "#5aa9e6", "yellow": "#e8c34a",
    # The Arbiter's own blue, and its own token on purpose. It was `accent`, and an
    # orange message bubble reads as an alarm rather than as "you said this" (user,
    # 2026-08-21). Not `info` either: that already colours the Critic's bubble, the
    # system bubble and Send, so borrowing it would leave three of the four voices in
    # the conversation the same colour. A periwinkle, far enough from the azure to be
    # told apart at the width of a border.
    "arbiter": "#8f9bf5",
}

PALETTE_LIGHT: dict[str, str] = {
    "ground": "#eef1f5", "panel": "#ffffff", "panel2": "#f4f6f9", "panel3": "#e9edf2",
    "border": "#d7dee6", "border2": "#c4cdd8",
    "text": "#1b2430", "muted": "#5c6875", "faint": "#93a0ad",
    "accent": "#c56f18", "accent_dim": "#a95f14",
    "ok": "#1f9c63", "inv": "#c56f18", "off": "#8492a0", "warn": "#c0392b",
    "info": "#2f7fc4", "yellow": "#c99a12",
    "arbiter": "#4453c4",
}


def _to_rgb(hex_or_token: str) -> tuple[int, int, int]:
    h = hex_or_token.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(color_a: str, pct: float, color_b: str = "transparent") -> str:
    """Reimplements CSS `color-mix(in srgb, color_a pct%, color_b)`.

    `color_b="transparent"` (the common case in the prototype — hover backgrounds, shadow
    glows) yields a translucent color: `rgba(A.r, A.g, A.b, pct%)` — per the CSS Color 4 spec,
    mixing with fully-transparent black in premultiplied space and un-premultiplying leaves the
    first color's own RGB with the interpolated alpha. Two opaque colors blend per-channel
    linearly (an ordinary sRGB lerp, which is what `in srgb` — non-linear-light — means).
    """
    ar, ag, ab = _to_rgb(color_a)
    t = pct / 100.0
    if color_b == "transparent":
        return f"rgba({ar}, {ag}, {ab}, {t:.3f})"
    br, bg, bb = _to_rgb(color_b)
    r = round(ar * t + br * (1 - t))
    g = round(ag * t + bg * (1 - t))
    b = round(ab * t + bb * (1 - t))
    return f"rgb({r}, {g}, {b})"


@dataclass(frozen=True)
class Theme:
    mode: Mode
    tokens: dict[str, str] = field(default_factory=dict)

    def __getattr__(self, name: str) -> str:
        try:
            return self.tokens[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def mix(self, token_a: str, pct: float, token_b: str = "transparent") -> str:
        """Like `mix()`, but takes palette TOKEN NAMES (e.g. "accent") instead of raw hex."""
        a = self.tokens[token_a]
        b = self.tokens[token_b] if token_b != "transparent" else "transparent"
        return mix(a, pct, b)


def get_theme(mode: Mode) -> Theme:
    return Theme(mode=mode, tokens=dict(PALETTE_DARK if mode == "dark" else PALETTE_LIGHT))


_FONT_SIZE_RE = re.compile(r"font-size:\s*([\d.]+)px")


def _scale_font_sizes(qss: str, scale: float) -> str:
    """Post-process every literal `font-size: Npx` in the generated stylesheet by `scale` — the
    "Qt font-scale" zoom (plan M6), a deliberately simpler stand-in for the prototype's CSS
    `zoom` (which also scales padding/spacing, not just text). Done as a single regex pass over
    the finished string rather than threading a scale arg through every f-string line below.
    """
    if scale == 1.0:
        return qss
    return _FONT_SIZE_RE.sub(lambda m: f"font-size: {float(m.group(1)) * scale:.1f}px", qss)


def build_qss(theme: Theme, scale: float = 1.0) -> str:
    """The application-wide stylesheet. Widgets opt into a "class" via the Qt dynamic-property
    trick (`widget.setProperty("class", "panel")`) since QSS object names must be unique but
    many widgets share the same look — mirrors the prototype's CSS classes.
    """
    t = theme
    qss = f"""
    QMainWindow, QWidget#AppRoot {{
        background: {t.ground};
    }}
    QWidget {{
        color: {t.text};
        font-size: 13px;
    }}
    QLabel {{
        background: transparent;
        color: {t.text};
    }}

    /* .panel — the card background used by every section. Uses `ground` (the page background),
    not the `panel` token despite the class name -- cards used to render pure white against the
    gray page, while content *inside* them (DSP-tree rows, table sheets, ...) mixed white and gray
    inconsistently depending on which sub-widget happened to inherit which ancestor. One flat gray
    everywhere, delineated only by the border below, reads as one coherent surface in both themes
    (user request 2026-07-28). `panel`/`panel2`/`panel3` stay reserved for genuinely floating
    surfaces (dropdown popups, tooltips, the feedback dialog) that should still stand apart. */
    QFrame[class~="panel"] {{
        background: {t.ground};
        border: 1px solid {t.border};
        border-radius: 7px;
    }}

    /* .phead — the small-caps section header row (matches .phead in the prototype) */
    QWidget[class~="phead"] {{
        border-bottom: 1px solid {t.border};
        background: transparent;
    }}
    QLabel[class~="phead-title"] {{
        color: {t.muted};
        font-size: 10px;
        letter-spacing: 2px;
        font-weight: 600;
    }}
    QLabel[class~="phead-sub"] {{
        color: {t.faint};
        font-size: 11px;
    }}

    /* .status-strip — "what TCC found on disk" (MCP up/down, terminal-launch result), read-only
    and shown in both view/control modes -- deliberately NOT a dialog bubble, see TCC-TZ.md §8.
    One line, hidden when there's nothing to say; `status-warn` recolors it for an error. */
    QLabel[class~="status-strip"] {{
        background: {t.panel2};
        border-bottom: 1px solid {t.border};
        color: {t.info};
        font-size: 11px;
        padding: 5px 14px;
    }}
    QLabel[class~="status-strip status-warn"] {{
        color: {t.warn};
    }}

    /* .sidebar-head — the left panel's top-level accordion header bar (System params / Project
    params / Car audio analysis / DSP) -- the only rows in the app deliberately shaded darker than
    the now-uniform `.panel` gray, so the top-level accordion still reads as a distinct landmark
    even though every surface shares one background (user request 2026-07-28). Hover sits exactly
    between the header's own shade and the general background, per the same request. Nested
    headers one level down (DSP tree's `.ghead` groups, `ParamsSection`'s own header) are left
    alone -- only the top level gets this treatment. */
    QWidget[class~="sidebar-head"] {{
        background: {t.border};
    }}
    QWidget[class~="sidebar-head"]:hover {{
        background: {t.mix('border', 50, 'ground')};
    }}
    QLabel[class~="sidebar-title"] {{
        color: {t.text};
        font-size: 11px;
        font-weight: 700;
    }}

    QPushButton[class~="theme-btn"] {{
        background: {t.panel3};
        border: 1px solid {t.border2};
        color: {t.muted};
        border-radius: 5px;
        padding: 5px 11px;
        font-size: 12px;
    }}
    QPushButton[class~="theme-btn"]:hover {{
        color: {t.text};
    }}

    QPushButton[class~="feedback-btn"] {{
        background: {t.accent};
        border: 1px solid {t.accent_dim};
        color: #1a1206;
        border-radius: 5px;
        padding: 5px 11px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton[class~="feedback-btn"]:hover {{
        background: {t.mix('accent', 88, 'panel')};
    }}

    /* .coffee-btn — the footer's support button (user request 2026-07-28), same color as the AI
    dialog's "Send" button (`.composer-send`) so it doesn't compete visually with the accent-
    colored "Give feedback" button right next to it. */
    QPushButton[class~="coffee-btn"] {{
        background: {t.info};
        color: #ffffff;
        border: none;
        border-radius: 5px;
        padding: 5px 11px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton[class~="coffee-btn"]:hover {{
        background: {t.mix('info', 88, 'panel')};
    }}
    /* .support-menu — the coffee button's 2-item popup (GitHub Sponsors / Monobank jar). */
    QMenu[class~="support-menu"] {{
        background: {t.panel3};
        border: 1px solid {t.border2};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu[class~="support-menu"]::item {{
        padding: 7px 14px;
        border-radius: 5px;
        color: {t.text};
    }}
    QMenu[class~="support-menu"]::item:selected {{
        background: {t.mix('info', 20)};
    }}
    /* The main menu's section headings are DISABLED items -- `QMenu::addSection` draws its text
    nowhere once a stylesheet is in play (measured: five headings, none visible). They are muted
    like any disabled item, and it is the UPPER CASE and the rule above them that make them read
    as headings; a smaller font here would have been better still, but it cannot be: an action
    disabled because it is unavailable right now ("save what the model knows", with no session
    running) hits the same selector, and a heading and an unavailable item must not look alike. */
    QMenu[class~="support-menu"]::item:disabled {{
        color: {t.faint};
    }}
    QMenu[class~="support-menu"]::separator {{
        height: 1px;
        background: {t.border};
        margin: 4px 8px 0 8px;
    }}

    /* .icon-btn — a single-glyph header button that stands ON ITS OWN. `.zoomgroup-btn` is
    deliberately transparent and borderless because it sits INSIDE the zoom group's frame, which
    supplies the border; the header's refresh and diagnostics buttons had borrowed that class and
    so rendered as bare glyphs next to buttons that all have a body (user, 2026-08-07). Same shell
    as `.theme-btn`, squared up for one character. */
    QPushButton[class~="icon-btn"] {{
        background: {t.panel3};
        border: 1px solid {t.border2};
        color: {t.muted};
        border-radius: 5px;
        padding: 4px 9px;
        font-size: 13px;
    }}
    QPushButton[class~="icon-btn"]:hover {{
        color: {t.text};
        border-color: {t.accent};
    }}
    /* The one icon button that is looked FOR rather than come across: diagnostics. Twice the
    glyph size of its neighbours (user, 2026-08-19) — it is the one you hunt for when something is
    wrong, and ⚙ at 13px reads as a speck. */
    QPushButton[class~="diag-btn"] {{
        color: {t.accent};
        border-color: {t.accent_dim};
        /* Bigger GLYPH, same BOX: the button is pinned to its neighbour's size in code
           (`_match_icon_buttons`), because a font-size alone grew the whole control and it stood
           a head above the reload button beside it (user, on Windows and on macOS, 2026-08-19).
           17px is as large as the glyph goes before it touches that box on either platform. */
        font-size: 17px;
        padding: 0px;
    }}
    QPushButton[class~="diag-btn"]:hover {{
        color: {t.accent};
        background: {t.mix('accent', 14, 'panel3')};
        border-color: {t.accent};
    }}

    /* .zoomgroup — A-/percent/A+ as one bordered block with divider lines, ported from the
    prototype's disconnected three-pill look at the user's request (2026-07-26 feedback). */
    QFrame[class~="zoomgroup"] {{
        background: {t.panel3};
        border: 1px solid {t.border2};
        border-radius: 5px;
    }}
    QPushButton[class~="zoomgroup-btn"] {{
        background: transparent;
        border: none;
        color: {t.muted};
        padding: 5px 11px;
        font-size: 12px;
    }}
    QPushButton[class~="zoomgroup-btn"]:hover {{
        color: {t.text};
        background: {t.mix('accent', 10)};
    }}
    QLabel[class~="zoomgroup-label"] {{
        color: {t.faint};
        font-size: 12px;
        padding: 0 8px;
    }}
    QFrame[class~="zoomgroup-div"] {{
        background: {t.border2};
        border: none;
    }}

    /* .mini-select — themed QComboBox (preset / language / AI-model pickers). Without this the
    combos render in the native platform style, which reads as an unstyled, wrong-font intrusion
    against the rest of the flat dark UI. */
    QComboBox[class~="mini-select"] {{
        background: {t.panel3};
        color: {t.text};
        border: 1px solid {t.border2};
        border-radius: 5px;
        /* right padding reserves room for the 18px ::drop-down arrow zone below -- symmetric
        padding here squeezed the closed box's own text against the arrow */
        padding: 4px 22px 4px 9px;
        font-size: 12px;
    }}
    QComboBox[class~="mini-select"]:hover {{
        border-color: {t.accent_dim};
    }}
    /* .is-warn — the picker whose current choice is not what it appears to be (substituted, or
    the reviewer sharing the Generator's vendor). Tinted rather than only marked beside: a warning
    sign next to a normal-looking field leaves you hunting for what it refers to. */
    QComboBox[class~="is-warn"] {{
        background: {t.mix('warn', 14, 'panel3')};
        border-color: {t.warn};
    }}
    /* .zoom-btn — the curve panel's A / D / − / + . Narrow enough that four of them fit beside
    the readout, and padded so the glyph is not clipped by the ordinary button padding. */
    QPushButton[class~="zoom-btn"] {{
        background: {t.panel3};
        color: {t.text};
        border: 1px solid {t.border2};
        border-radius: 5px;
        padding: 2px 0;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton[class~="zoom-btn"]:hover {{
        border-color: {t.accent_dim};
    }}
    /* `Choose…` is the one .zoom-btn carrying a menu, and an unstyled indicator is drawn by the
    native style rather than by the box above it: on macOS that is a second little bezel sitting
    on the button's right border, which reads as two controls overlapping (user, 2026-08-21, with
    the screenshot). Pinned inside the padding box, the same fix .project-btn already carries. */
    QPushButton[class~="zoom-btn"]::menu-indicator {{
        subcontrol-origin: padding;
        subcontrol-position: right center;
        width: 10px;
        right: 8px;
    }}
    /* .guides-btn — the ✕ beside the mode buttons that takes every guide off the picture at once.

    Its own class rather than a `.zoom-btn` with an inline stylesheet, for two reasons that were
    both watched happening (user, 2026-08-18, with the screenshot). A QSS `font-size` from THIS
    sheet beats a QFont set in code, so the 1.35× font the widget was given never reached the
    screen while `.zoom-btn {{ font-size: 12px }}` matched it — the "big X" that was asked for was
    never big. And an inline sheet is only written when something calls the updater, which nothing
    did at construction, so the button opened grey and identical to the zoom buttons beside it.

    Red in both states, because the button says what it DOES; FILLED while the guides are hidden,
    because that is a state the tuner has to be able to read from across a car seat. `:checked`
    carries that here, so nothing has to write a colour by hand at all. */
    QPushButton[class~="guides-btn"] {{
        background: {t.panel3};
        color: {t.warn};
        border: 1px solid {t.warn};
        border-radius: 5px;
        padding: 0;
        font-size: 17px;
        font-weight: 700;
    }}
    QPushButton[class~="guides-btn"]:hover {{
        background: {t.mix('warn', 16, 'panel3')};
    }}
    QPushButton[class~="guides-btn"]:checked {{
        background: {t.warn};
        color: {t.ground};
    }}
    /* .link-btn — the "⇅" that ties the sum's strip to the plot's frequency scale.

    An orange ring, always (user, 2026-08-18: "ободок помаранчевого кольору, щоб на неї звертали
    увагу"). It is the only control in that row that changes the RELATIONSHIP between two plots
    rather than the view of one, and a grey 1px `.zoom-btn` border said nothing about that.

    `accent` and not `warn` or `yellow`, chosen rather than reached for: `accent` IS this palette's
    orange (#e8973c dark, #c56f18 light) and carries no verdict; `warn` is red-leaning and means
    "wrong", which a healthy, useful control must never borrow; `yellow` is the predicted sum's own
    colour on every drawing surface in this window, and a button wearing it would claim to be the
    sum rather than to frame it. 2px rather than 1 is the part that makes it announce itself.

    The two states are told apart by the FILL, not by whether the ring is there: the ring is the
    "look at me", so it has to be present linked and free alike. */
    QPushButton[class~="link-btn"] {{
        background: {t.panel3};
        color: {t.muted};
        border: 2px solid {t.accent};
        border-radius: 5px;
        padding: 0;
        font-size: 12px;
        font-weight: 700;
    }}
    QPushButton[class~="link-btn"]:hover {{
        background: {t.mix('accent', 14, 'panel3')};
    }}
    QPushButton[class~="link-btn"]:checked {{
        background: {t.mix('accent', 26, 'panel3')};
        color: {t.accent};
    }}
    /* .delay-radio — the curve window's "which driver is being delayed" radios, one per trace.

    An unstyled radio indicator is drawn by the native style: a dark circle on this dark ground,
    which is why a row of THREE read as one bright control and two smudges and the user counted two
    (2026-08-18: "сорі, я не побачив що їх вже три"). The unselected state gets a ring in `muted`
    — the same token the axis labels use, so it is legible in both palettes without being loud —
    and the selected one keeps the accent FILL, so "here are your curves" and "this is the one you
    are editing" stay two different statements.

    The label is normal control type rather than the faint 11 px `.phead-sub` it wore; its COLOUR
    is written per widget from the trace's own pen (`curve_view.set_traces`), which is why no
    `color` is set here. */
    QRadioButton[class~="delay-radio"] {{
        font-size: 12px;
        font-weight: 600;
        spacing: 5px;
        padding: 0 3px;
        background: transparent;
    }}
    QRadioButton[class~="delay-radio"]::indicator {{
        width: 11px;
        height: 11px;
        /* Under half the rendered 15px (11 + 2px border either side), or Qt treats the radius as
        invalid and draws a square — the same rule `.edit-chip` records. */
        border-radius: 7px;
        border: 2px solid {t.muted};
        background: {t.panel3};
    }}
    QRadioButton[class~="delay-radio"]::indicator:hover {{
        border-color: {t.accent_dim};
    }}
    QRadioButton[class~="delay-radio"]::indicator:checked {{
        border: 2px solid {t.accent};
        background: {t.accent};
    }}
    /* .curve-chip — one chosen measurement in the curve window's selection row, with the × that
    takes it off the plot. The frame is shared; the BORDER and the name are coloured per chip, from
    the pen its own trace is drawn with (`curve_view.trace_colour`), so the row reads as a legend of
    the plot rather than as a list of strings. Neither colour is set here for that reason.

    Same radius rule as `.edit-chip`: stay under half the rendered height or Qt treats the radius as
    invalid and draws a square corner. */
    QFrame[class~="curve-chip"] {{
        background: {t.panel3};
        border: 1px solid {t.border2};
        border-radius: 9px;
    }}
    QLabel[class~="curve-chip-name"] {{
        background: transparent;
        font-size: 11.5px;
        font-weight: 600;
    }}
    /* The × is a target, not a decoration: it is the one gesture that takes a driver out of the
    predicted sum, so it gets a hit area of its own rather than a glyph squeezed against the name.
    Disabled on the last chip left — a window plotting nothing has nothing to say. */
    QPushButton[class~="curve-chip-x"] {{
        background: transparent;
        border: none;
        color: {t.muted};
        font-size: 12px;
        font-weight: 700;
        padding: 0;
        min-width: 16px;
        max-width: 16px;
        min-height: 16px;
        max-height: 16px;
    }}
    QPushButton[class~="curve-chip-x"]:hover {{
        color: {t.warn};
    }}
    QPushButton[class~="curve-chip-x"]:disabled {{
        color: {t.faint};
    }}
    /* .is-missing — the picker's current choice is not on offer on this machine. Red text, not a
    red background: the model is still SELECTED and still what the project asks for, which is a
    different statement from "this setting is wrong". */
    QComboBox[class~="is-missing"] {{
        color: {t.warn};
        border-color: {t.warn};
    }}
    /* .warn-mark — the "!" that stands in for a sentence there is no room for. Round, red, and
    clickable; hover says what, click says why. */
    QPushButton[class~="warn-mark"] {{
        background: {t.mix('warn', 16, 'panel')};
        color: {t.warn};
        border: 1px solid {t.warn};
        border-radius: 9px;
        font-weight: 700;
        font-size: 11px;
        padding: 0;
    }}
    QPushButton[class~="warn-mark"]:hover {{
        background: {t.mix('warn', 30, 'panel')};
    }}
    QComboBox[class~="mini-select"]::drop-down {{
        border: none;
        width: 18px;
    }}
    QComboBox[class~="mini-select"] QAbstractItemView {{
        background: {t.panel};
        color: {t.text};
        border: 1px solid {t.border2};
        selection-background-color: {t.mix('accent', 22)};
        selection-color: {t.text};
        outline: none;
        padding: 3px;
    }}
    QComboBox[class~="mini-select"] QAbstractItemView::item {{
        /* left padding reserves room for the current-item check mark so labels aren't clipped
        down to their first letter (the "E / U" language-picker bug) */
        padding: 5px 14px 5px 28px;
        min-height: 22px;
    }}
    /* .mini-select on a SPIN BOX — the curve window's delay field, which wears the same class as
    the combos it stands between and rendered white with light text on it in the dark theme (user,
    2026-08-18, with the picture). Every rule above is `QComboBox[...]`, so not one of them ever
    reached a QDoubleSpinBox, and the palette does not cover for that: `apply_theme` sets Window,
    Base and Text but never `Button`, and the macOS style paints a spin box's field from its own
    native drawing rather than from the palette at all. A rule that matches is the only thing that
    reaches it -- and because it lives in the application sheet, a live theme switch re-polishes
    it along with everything else, which a per-widget stylesheet would not have done.
    `QAbstractSpinBox` rather than `QDoubleSpinBox` so an integer one added later is not a second
    white box nobody notices.

    The up/down steppers are deliberately NOT given rules of their own. A rule on `::up-button`
    makes QStyleSheetStyle take the sub-control over, and with no `image:` to draw there is then
    no arrow at all -- rendered and looked at, both themes, 2026-08-18. Left alone, the base style
    draws its own steppers over our frame and they read correctly in both. Those arrows are how
    the delay is stepped by exactly what the DSP accepts (`CurveView.set_resolution`). */
    QAbstractSpinBox[class~="mini-select"] {{
        background: {t.panel3};
        color: {t.text};
        border: 1px solid {t.border2};
        border-radius: 5px;
        padding: 4px 4px 4px 9px;
        font-size: 12px;
        selection-background-color: {t.mix('accent', 22)};
        selection-color: {t.text};
    }}
    QAbstractSpinBox[class~="mini-select"]:hover {{
        border-color: {t.accent_dim};
    }}
    QAbstractSpinBox[class~="mini-select"]:focus {{
        border-color: {t.accent};
    }}
    /* The editable half is a QLineEdit child of the spin box, and it is drawn with its own
    palette. Transparent so the box's one background shows through it rather than a second,
    slightly different rectangle inside the frame. */
    QAbstractSpinBox[class~="mini-select"] QLineEdit {{
        background: transparent;
        color: {t.text};
        border: none;
        selection-background-color: {t.mix('accent', 22)};
        selection-color: {t.text};
    }}

    /* Fallback styling for native tooltips -- every widget in this app's own code now uses
    `.rounded-tip`/`rounded_tooltip.attach()` instead (native QToolTip's window frame ignores its
    own border-radius on macOS, user request 2026-07-28), but this still themes any tooltip Qt
    shows on its own (e.g. a QAbstractButton's auto-elided-text tooltip). */
    QToolTip {{
        background: {t.panel3};
        color: {t.text};
        border: 1px solid {t.border2};
        border-radius: 5px;
        padding: 6px 9px;
        font-size: 12px;
    }}
    /* .rounded-tip — the channel-hint popup (rounded_tooltip.py, user request 2026-07-28): a
    frameless/translucent widget so the rounded rect is the real window shape, not a QSS radius
    clipped by a square native frame. Background/border are painted manually in `paintEvent`
    (a WA_TranslucentBackground top-level widget's QSS background isn't reliably composited by
    the style engine -- verified: it silently didn't paint at all) -- only text styling belongs
    here; padding comes from `setContentsMargins` in code, not this rule, for the same reason. */
    QLabel[class~="rounded-tip"] {{
        color: {t.text};
        font-size: 12px;
    }}

    /* .kv-lbl — the small uppercase field labels in the header/footer (Preset / Target / AI...) */
    QLabel[class~="kv-lbl"] {{
        color: {t.muted};
        font-size: 10px;
    }}
    QLabel[class~="kv-val"] {{
        color: {t.text};
        font-weight: 600;
    }}
    /* .kv-warn — a footer value that is a warning rather than a fact (the reviewer being
    substituted or sharing the Generator's vendor). Its own class rather than inline HTML,
    because the label has to be an `ElidedLabel` and that one measures plain text. */
    QLabel[class~="kv-warn"] {{
        color: {t.warn};
        font-weight: 600;
    }}
    /* .kv-val-link — the header's "Target curve" value, clickable through to the skill's online
    target-curve tool (user request 2026-07-28). Looks like a link even before hovering (an
    accent color + the ↗ suffix main_window.py appends to the text) always, not just on hover --
    a hover-only cue is invisible until the user already happens to be pointing at it (user
    request 2026-07-28). The underline itself is set via `QFont.setUnderline()` in code, not
    `text-decoration` here -- QSS silently ignores that property on QLabel (same reason
    `.substep-name-done`'s strike-through is code-side, see `plan_panel.py`). */
    QLabel[class~="kv-val-link"] {{
        color: {t.accent};
    }}
    QLabel[class~="slot-val"] {{
        color: {t.accent};
        font-weight: 600;
        font-family: "SF Mono", Menlo, monospace;
    }}

    /* ---- DSP tree (.ghead / .chan / .pill / .eq-chip / .prow-params / .cline2) ---- */
    QWidget[class~="ghead"] {{
        background: transparent;
    }}
    QWidget[class~="ghead"] QLabel {{
        color: {t.muted};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 1px;
        text-transform: uppercase;
    }}
    QLabel[class~="tw"] {{
        color: {t.faint};
        font-family: "SF Mono", Menlo, monospace;
        font-size: 10px;
        min-width: 12px;
    }}
    QLabel[class~="cnt"] {{
        color: {t.faint};
        font-family: "SF Mono", Menlo, monospace;
        text-transform: none;
        font-weight: 400;
    }}
    QWidget[class~="prow-params"] {{
        color: {t.muted};
        font-size: 12px;
    }}
    QWidget[class~="prow-params"]:hover {{
        background: {t.panel2};
    }}
    QLabel[class~="prow-params-ic"] {{
        color: {t.accent};
    }}
    QWidget[class~="chan"] {{
        background: transparent;
        border-radius: 5px;
    }}
    QWidget[class~="chan"]:hover {{
        background: {t.panel2};
    }}
    QWidget[class~="chan-dim"] {{
        color: {t.faint};
    }}
    /* chan-dim's own color only reaches children with no more-specific rule of their own -- cid/
    cline2/eq-chip/ctype all have explicit colors that otherwise stay full-brightness on a muted
    row, so they need their own descendant overrides here. */
    QWidget[class~="chan-dim"] QLabel[class~="cid"] {{
        color: {t.faint};
    }}
    QWidget[class~="chan-dim"] QLabel[class~="cline2"] {{
        color: {t.faint};
    }}
    QWidget[class~="chan-dim"] QLabel[class~="eq-chip"] {{
        color: {t.faint};
        border-color: {t.border2};
    }}
    QWidget[class~="chan-dim"] QLabel[class~="ctype"] {{
        color: {t.faint};
    }}
    QLabel[class~="cid"] {{
        font-family: "SF Mono", Menlo, monospace;
        font-size: 10px;
        font-weight: 700;
        color: {t.accent};
        background: {t.panel3};
        border-radius: 3px;
        padding: 0 4px;
    }}
    QLabel[class~="cn"] {{
        font-weight: 600;
    }}
    QLabel[class~="cline2"] {{
        font-family: "SF Mono", Menlo, monospace;
        font-size: 10.5px;
        color: {t.muted};
    }}
    /* .ctype — the muted speaker-type label (woofer/mid/tweeter/...) on output rows */
    QLabel[class~="ctype"] {{
        color: {t.faint};
        font-size: 10px;
    }}
    /* .ctag2 — the small feature tag (RearATT/SubRC) next to a virtual channel's name */
    QLabel[class~="ctag2"] {{
        color: {t.info};
        background: {t.mix('info', 15)};
        border-radius: 3px;
        padding: 0 5px;
        font-size: 9px;
    }}
    /* .phead-badge — a flat ParamsSection's own title, styled like the left-panel's top "DSP"
    badge (`.phead-title`) instead of the DSP-tree's bolder/brighter group-header look -- these are
    project-config sections (car/setup, body/chassis, ...), visually lighter-weight than actual DSP
    channel groups (user request 2026-07-27). Needs the `.ghead QLabel` ancestor prefix to win
    specificity over that shared descendant rule (see feedback_qt_qss_gotchas.md). */
    QWidget[class~="ghead"] QLabel[class~="phead-badge"] {{
        color: {t.muted};
        font-size: 10px;
        letter-spacing: 2px;
        font-weight: 600;
        text-transform: none;
    }}

    /* .paramrow — key/value feature rows inside the top PARAMS section */
    QWidget[class~="paramrow"] {{
        font-size: 11px;
    }}
    QLabel[class~="pk"] {{
        color: {t.muted};
    }}
    QLabel[class~="pv"] {{
        color: {t.text};
        font-family: "SF Mono", Menlo, monospace;
    }}
    QLabel[class~="pill"] {{
        font-size: 9.5px;
        letter-spacing: 1px;
        text-transform: uppercase;
        font-weight: 700;
        padding: 1px 6px;
        border-radius: 8px;
    }}
    QLabel[class~="pill-inv"] {{
        color: {t.inv};
        background: {t.mix('inv', 16)};
    }}
    QLabel[class~="pill-norm"] {{
        color: {t.muted};
        background: {t.panel3};
    }}
    QLabel[class~="pill-mute"] {{
        color: {t.muted};
        background: {t.panel3};
    }}
    /* .pill-off — a real "off" flag (hardware output physically disabled at the DSP level) uses
    the palette's dedicated `off` token, distinct from a plain mute (logically silenced but still
    wired, which just reads muted-gray). */
    QLabel[class~="pill-off"] {{
        color: {t.off};
        background: {t.mix('off', 16)};
    }}
    QLabel[class~="eq-chip"] {{
        font-family: "SF Mono", Menlo, monospace;
        font-size: 10px;
        color: {t.accent};
        border: 1px solid {t.mix('accent', 40)};
        border-radius: 4px;
        padding: 0 6px;
    }}
    QLabel[class~="eq-chip"][class~="muted"] {{
        color: {t.faint};
        border-color: {t.border2};
    }}

    /* ---- detail pane: tabs / close / table / EQ bands ---- */
    QLabel[class~="d-tab"] {{
        color: {t.muted};
        border: 1px solid transparent;
        border-radius: 5px;
        padding: 2px 9px;
        font-size: 11px;
    }}
    QLabel[class~="d-tab"][class~="on"] {{
        color: {t.accent};
        border-color: {t.accent_dim};
        background: {t.mix('accent', 12)};
    }}
    QPushButton[class~="d-close"] {{
        background: transparent;
        border: 1px solid {t.border2};
        color: {t.muted};
        border-radius: 5px;
        padding: 2px 9px;
        font-size: 11px;
    }}
    QPushButton[class~="d-close"]:hover {{
        color: {t.text};
    }}

    QTableWidget[class~="ptable"] {{
        background: {t.ground};
        gridline-color: transparent;
        border: none;
        font-size: 12px;
    }}
    QTableWidget[class~="ptable"]::item {{
        padding: 4px 10px;
        border-bottom: 1px solid {t.mix('border', 60)};
    }}
    QTableWidget[class~="ptable"]::item:selected {{
        background: {t.mix('accent', 18)};
    }}
    QHeaderView::section {{
        background: {t.ground};
        color: {t.muted};
        border: none;
        border-bottom: 1px solid {t.border2};
        padding: 6px 10px;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 600;
    }}

    /* .eq-help — the "?" icon that replaced the always-on EQ hint paragraph (user request
    2026-07-28: it ate vertical space every time the EQ view was open; a hover tooltip is the
    better-practice spot for one-time explanatory text). */
    QLabel[class~="eq-help"] {{
        color: {t.muted};
        border: 1px solid {t.border2};
        border-radius: 8px;
        min-width: 14px;
        max-width: 14px;
        min-height: 14px;
        max-height: 14px;
        font-size: 10px;
        font-weight: 700;
        qproperty-alignment: AlignCenter;
    }}
    QLabel[class~="eq-rowlab"] {{
        color: {t.muted};
        font-size: 11px;
        font-weight: 600;
    }}
    QFrame[class~="band"] {{
        background: {t.panel2};
        border: 1px solid {t.border};
        border-radius: 6px;
    }}
    QLabel[class~="band-id"] {{
        font-family: "SF Mono", Menlo, monospace;
        font-size: 11px;
        color: {t.info};
        background: {t.panel3};
        padding: 3px 0;
        border-bottom: 1px solid {t.border};
    }}
    QLabel[class~="band-fk"] {{
        color: {t.muted};
        font-size: 11px;
    }}
    QLabel[class~="band-fv"] {{
        font-family: "SF Mono", Menlo, monospace;
        font-size: 11px;
    }}
    /* .band-fv-mismatch — a shared-frequency band whose L/R gain DIFFERS (the frequency itself
    still gets the usual match-color top border, but same-freq same-gain and same-freq different-
    gain otherwise looked identical -- user request 2026-07-27). */
    QLabel[class~="band-fv-mismatch"] {{
        font-family: "SF Mono", Menlo, monospace;
        font-size: 11px;
        color: {t.warn};
        font-weight: 700;
    }}
    QLabel[class~="band-byp"] {{
        color: {t.faint};
        font-size: 9.5px;
        letter-spacing: 1px;
        text-transform: uppercase;
        padding: 4px 0 7px;
    }}

    /* ---- Plan-Fact panel ---- */
    QWidget[class~="prow"] {{ border-radius: 5px; }}
    QWidget[class~="prow"]:hover {{ background: {t.panel2}; }}
    QWidget[class~="prow-current"] {{ background: {t.mix('accent', 10)}; border-radius: 5px; }}
    QLabel[class~="pcaret"] {{
        color: {t.faint};
        font-family: "SF Mono", Menlo, monospace;
        font-size: 10px;
    }}
    QLabel[class~="pcnt"] {{
        font-family: "SF Mono", Menlo, monospace;
        font-size: 10px;
        color: {t.faint};
    }}
    QLabel[class~="pname"] {{ font-weight: 600; }}
    QLabel[class~="pname-current"] {{ font-weight: 600; color: {t.accent}; }}
    QLabel[class~="st"] {{
        border-radius: 7px;
        font-size: 10px;
        font-weight: 700;
    }}
    QLabel[class~="st-done"] {{ background: {t.ok}; color: #04160d; }}
    QLabel[class~="st-cur"] {{ background: {t.accent}; color: #1a1206; }}
    QLabel[class~="st-todo"] {{ background: {t.panel3}; color: {t.faint}; }}
    QLabel[class~="substep-name"] {{ color: {t.muted}; font-size: 12px; }}
    /* .substep-name-project — situational/project-inserted steps (not from the skill's base
    structure) render in the palette's blue token, per user request 2026-07-27 item 8. */
    QLabel[class~="substep-name-project"] {{ color: {t.info}; font-size: 12px; }}
    /* .substep-name-done — QSS has no text-decoration (silently ignored), so the strike-through
    itself is applied via QFont.setStrikeOut() in code (_PhaseStepRow); this class only sets the
    dimmed color. */
    QLabel[class~="substep-name-done"] {{ color: {t.faint}; font-size: 12px; }}
    QLabel[class~="stag"] {{ font-size: 10px; }}
    QLabel[class~="stag-ok"] {{ color: {t.ok}; }}
    QLabel[class~="stag-wait"] {{ color: {t.yellow}; }}
    QLabel[class~="stag-attempt"] {{ color: {t.info}; }}
    /* .step-meas-icon — the per-step measurement-history icon (user request 2026-07-28): hover
    lists the capture series used for this step, click opens one in the measurement panel below. */
    QLabel[class~="step-meas-icon"] {{
        color: {t.muted};
        font-size: 12px;
    }}
    QLabel[class~="step-meas-icon"]:hover {{ color: {t.info}; }}
    /* .step-skip — a superseded/skipped step stays visible (attempt history matters) but dims,
    same descendant-override idiom as .chan-dim in the DSP tree. */
    QWidget[class~="step-skip"] QLabel[class~="substep-name"] {{ color: {t.faint}; }}
    QWidget[class~="step-skip"] QLabel[class~="substep-name-project"] {{ color: {t.faint}; }}
    QPushButton[class~="add-step-btn"] {{
        background: transparent;
        border: none;
        color: {t.faint};
        font-size: 11px;
        padding: 3px 26px;
        text-align: left;
    }}
    QPushButton[class~="add-step-btn"]:hover {{ color: {t.accent}; }}

    /* ---- Measurement-task card (yellow accent) ---- */
    QWidget[class~="meas-card"] {{
        border: 1px solid {t.mix('yellow', 45, 'border')};
        border-radius: 7px;
    }}
    QLabel[class~="meas-head"] {{
        font-family: "SF Mono", Menlo, monospace;
        font-size: 13px;
        font-weight: 600;
        padding: 5px 9px;
        border-radius: 5px;
        color: {t.mix('yellow', 82, 'text')};
        background: {t.mix('yellow', 20)};
        border: 1px solid {t.mix('yellow', 42)};
    }}
    QLabel[class~="meas-legend-label"] {{ color: {t.muted}; font-size: 10px; }}
    QLabel[class~="tl"] {{ border-radius: 4px; }}
    QLabel[class~="tl-wait"] {{ background: {t.yellow}; }}
    QLabel[class~="tl-done"] {{ background: {t.ok}; }}
    QLabel[class~="tl-bad"] {{ background: {t.warn}; }}
    /* A capture somebody decided against (SCR-034). Grey, not yellow: waiting is work outstanding,
       this is work that will not happen -- and until the skill recorded the decision the two were
       the same colour, so the next session proposed it again. */
    QLabel[class~="tl-skip"] {{ background: {t.off}; }}
    /* The flaw map's verdicts (SCR-015). Two answers matter more than six colours: `done` = this
       one you may correct, `bad` = the boost this map exists to forbid, `off` = a fact of the car,
       `info` = the fix exists but is not EQ. */
    QLabel[class~="tl-off"] {{ background: {t.off}; }}
    QLabel[class~="tl-info"] {{ background: {t.info}; }}
    QLabel[class~="mcol-h"] {{
        font-size: 9.5px;
        letter-spacing: 1px;
        text-transform: uppercase;
        color: {t.muted};
        background: {t.panel2};
        border-bottom: 1px solid {t.border};
        padding: 3px 6px;
    }}
    QLabel[class~="mn"] {{
        font-family: "SF Mono", Menlo, monospace;
        font-size: 10.5px;
    }}
    /* .open-q -- the intake's unanswered questions. Every other `.phead-sub` is a quiet aside
    and these are the one kind that wants something from the reader, so they carry the accent
    rather than the muted grey they used to share with placeholder text (user, 2026-08-21). */
    QLabel[class~="open-q"] {{ color: {t.accent}; }}
    QLabel[class~="mn-bad"] {{ color: {t.warn}; }}
    QLabel[class~="mn-wait"] {{ color: {t.muted}; }}
    QLabel[class~="mn-done"] {{ color: {t.text}; }}

    /* ---- AI dialog: bubbles / composer / edit-chip ---- */
    QFrame[class~="msg"] {{
        border-radius: 10px;
    }}
    QFrame[class~="msg-gen"] {{
        background: {t.panel3};
        border: 1px solid {t.border2};
    }}
    QFrame[class~="msg-crit"] {{
        background: {t.mix('info', 12, 'panel2')};
        border: 1px solid {t.mix('info', 30, 'border')};
    }}
    QFrame[class~="msg-user"] {{
        background: {t.mix('arbiter', 16, 'panel2')};
        border: 1px solid {t.mix('arbiter', 30, 'border')};
    }}
    QFrame[class~="msg-sys"] {{
        background: {t.mix('info', 10, 'panel2')};
        border: 1px dashed {t.mix('info', 45, 'border')};
    }}
    QLabel[class~="msg-who"] {{
        font-size: 10px;
        letter-spacing: 1px;
        text-transform: uppercase;
        color: {t.muted};
    }}
    QLabel[class~="msg-who-crit"] {{ color: {t.info}; }}
    QLabel[class~="msg-who-user"] {{ color: {t.arbiter}; }}
    QLabel[class~="msg-who-sys"] {{ color: {t.info}; }}
    QLabel[class~="msg-body"] {{
        font-size: 13px;
    }}

    QWidget[class~="composer"] {{
        border-top: 1px solid {t.border};
    }}
    QLineEdit[class~="composer-input"] {{
        background: {t.panel2};
        border: 1px solid {t.border2};
        border-radius: 6px;
        color: {t.text};
        padding: 8px 11px;
    }}
    QPushButton[class~="composer-send"] {{
        background: {t.info};
        color: #ffffff;
        border: none;
        border-radius: 6px;
        padding: 0 16px;
        font-weight: 700;
        min-height: 32px;
    }}
    /* .composer-send-ok — `.composer-send` in the app's own green. One place uses it: the import
    window's "send this to be banked", which is available only when the whole plan checked out
    against the processor. The colour IS the verdict -- grey while anything is refused or unbound,
    green the moment there is something worth handing over (user, 2026-08-23). */
    QPushButton[class~="composer-send-ok"] {{
        background: {t.ok};
        color: #ffffff;
        border: none;
        border-radius: 6px;
        padding: 0 16px;
        font-weight: 700;
        min-height: 32px;
    }}
    QPushButton[class~="composer-send-ok"]:hover {{
        background: {t.mix("ok", 85, "panel")};
    }}
    QPushButton[class~="composer-send-ok"]:disabled {{
        background: {t.panel3};
        color: {t.faint};
    }}
    /* .action-2nd — the same shape as `.composer-send`, without the claim to being THE action.
    Two solid blue buttons side by side is two primaries, which is none: the curve window's "this
    is my reading" is the act, and "analyse the set" is a second thing you may also do. */
    QPushButton[class~="action-2nd"] {{
        background: {t.panel3};
        color: {t.text};
        border: 1px solid {t.border2};
        border-radius: 6px;
        padding: 0 14px;
        font-weight: 600;
        min-height: 32px;
    }}
    QPushButton[class~="action-2nd"]:hover {{
        border-color: {t.accent_dim};
        color: {t.accent};
    }}
    QPushButton[class~="action-2nd"]:disabled {{
        color: {t.faint};
        border-color: {t.border};
    }}
    /* .clear-btn — the same family, low. These undo; they are not offers, and at full button
    height they carried the weight of the two actions above them (user, 2026-08-12). */
    QPushButton[class~="clear-btn"] {{
        background: {t.panel3};
        color: {t.muted};
        border: 1px solid {t.border2};
        border-radius: 5px;
        padding: 0 10px;
        font-size: 11px;
        font-weight: 600;
        min-height: 20px;
        max-height: 20px;
    }}
    QPushButton[class~="clear-btn"]:hover {{
        border-color: {t.accent_dim};
        color: {t.accent};
    }}
    QPushButton[class~="clear-btn"]:disabled {{
        color: {t.faint};
        border-color: {t.border};
    }}

    /* The "still working" line under the transcript -- system-grey, so it reads as chrome
       rather than as something the model said. */
    QLabel[class~="activity"] {{
        color: {t.muted};
        font-size: 11px;
        padding: 2px 12px 0 12px;
    }}
    /* .new-below -- the "there is new text below" marker (F-008). A full-width row under the
       transcript rather than a floating pill over it, so it can never cover a message; accented
       because unlike `.activity` it is asking to be clicked, not just pulsing. */
    QPushButton[class~="new-below"] {{
        background: {t.mix("accent", 0.10, "panel")};
        border: none;
        border-top: 1px solid {t.accent_dim};
        color: {t.accent};
        font-size: 11px;
        font-weight: 600;
        padding: 3px 12px;
    }}
    QPushButton[class~="new-below"]:hover {{
        background: {t.mix("accent", 0.18, "panel")};
    }}
    QPushButton[class~="edit-chip"] {{
        background: {t.panel3};
        border: 1px solid {t.border2};
        color: {t.muted};
        /* Under half the rendered height (22px): Qt treats a larger radius as invalid and draws
           a square corner instead -- measured, which is why these chips looked sharp while every
           other rounded thing in the app looked right. */
        border-radius: 10px;
        padding: 4px 11px;
        font-size: 11px;
    }}
    QPushButton[class~="edit-chip"]:hover {{ color: {t.text}; }}
    QPushButton[class~="edit-chip"][class~="on"] {{
        background: {t.mix('accent', 16, 'panel2')};
        border-color: {t.accent};
        color: {t.accent};
        font-weight: 600;
    }}
    QWidget[class~="edit-reasons"] {{
        background: {t.panel2};
        border-bottom: 1px solid {t.border};
    }}
    /* The confirmation is the one thing in this window that is waiting on a person, and it used
       to look like every other panel: same background, same border, a hairline apart from the
       transcript. Reported as easy to miss. It gets the accent, a real border and its own tint. */
    QWidget[class~="confirm-bar"] {{
        background: {t.mix("accent", 0.10, "panel")};
        border: 2px solid {t.accent};
        border-radius: 10px;
    }}
    QWidget[class~="confirm-bar"] QLabel[class~="phead-title"] {{
        color: {t.accent};
    }}
    QPushButton[class~="reason-btn"] {{
        background: {t.panel3};
        border: 1px solid {t.border2};
        color: {t.text};
        /* Same rule as `edit-chip`: stay under half the rendered height (22px), or Qt treats the
           radius as invalid and draws a square corner. */
        border-radius: 10px;
        padding: 4px 12px;
        font-size: 11.5px;
    }}
    /* .project-btn — the header's project picker. It is a **QToolButton** with an instant popup,
    which is the whole reason the first attempt at this did nothing: the rules said QPushButton and
    matched no widget, so macOS kept drawing its native pale pill with pale text on a dark header,
    unreadable. Both types are named now, every state is covered, theme tokens only. */
    QToolButton[class~="project-btn"], QPushButton[class~="project-btn"] {{
        background: {t.panel3};
        border: 1px solid {t.border2};
        border-radius: 8px;
        color: {t.text};
        padding: 4px 12px;
        font-size: 11.5px;
        text-align: left;
    }}
    QToolButton[class~="project-btn"]:hover, QPushButton[class~="project-btn"]:hover {{
        border-color: {t.accent};
        color: {t.accent};
    }}
    QToolButton[class~="project-btn"]:pressed, QToolButton[class~="project-btn"]:checked,
    QPushButton[class~="project-btn"]:pressed, QPushButton[class~="project-btn"]:checked {{
        background: {t.mix("accent", 0.14, "panel")};
        border-color: {t.accent};
        color: {t.text};
    }}
    QToolButton[class~="project-btn"]::menu-indicator,
    QPushButton[class~="project-btn"]::menu-indicator {{
        subcontrol-origin: padding;
        subcontrol-position: right center;
        width: 10px;
    }}
    /* .chan-toggle — the per-channel switch. It reads as the ACTION it performs, so the colour
    previews the result rather than reporting the present state: `-on` (accented) is offered on a
    channel that is currently off, `-off` (quiet) on one that is live. The state itself is the
    row's own name, dimmed when the channel is not in play. */
    QPushButton[class~="chan-toggle"] {{
        border: 1px solid {t.border2};
        border-radius: 4px;
        padding: 0px 6px;
        font-size: 9.5px;
        font-weight: 700;
    }}
    QPushButton[class~="chan-toggle-on"] {{
        background: {t.mix("ok", 0.16, "panel")};
        border-color: {t.ok};
        color: {t.ok};
    }}
    QPushButton[class~="chan-toggle-off"] {{
        background: transparent;
        color: {t.faint};
    }}
    /* Between the click and the model's answer. Neither `-on` nor `-off`: the button no longer
    offers an action, it reports a request nobody has answered yet, so it reads as a state and not
    as something to press. `-late` is the same state past a minute, which is a different fact. */
    QPushButton[class~="chan-toggle-wait"] {{
        background: {t.mix("info", 0.12, "panel")};
        border-color: {t.mix("info", 0.45, "border")};
        color: {t.info};
    }}
    QPushButton[class~="chan-toggle-late"] {{
        background: {t.mix("warn", 0.14, "panel")};
        border-color: {t.warn};
        color: {t.warn};
    }}
    QPushButton[class~="chan-toggle"]:hover {{
        border-color: {t.accent};
        color: {t.accent};
    }}
    QPushButton[class~="reason-btn"]:hover {{
        border-color: {t.info};
        color: {t.info};
    }}
    /* .meas-icon-btn — compact icon-only buttons for the measurement panel's Read/Assign-names
    actions (full-text buttons ate too much of the header row next to the version banner, user
    request 2026-07-27). Full label lives in the tooltip, not on the button face. */
    QPushButton[class~="meas-icon-btn"] {{
        background: {t.panel3};
        border: 1px solid {t.border2};
        color: {t.muted};
        border-radius: 6px;
        font-size: 14px;
        padding: 0;
    }}
    QPushButton[class~="meas-icon-btn"]:hover {{
        border-color: {t.info};
        color: {t.info};
    }}
    /* .meas-icon-btn-read — soft/gentle green (user's own wording: "салатним ніжним"), a lighter
    tint than the strong `t.ok` used for "done" status elsewhere, so it reads as inviting rather
    than a status indicator. */
    QPushButton[class~="meas-icon-btn-read"] {{
        background: {t.mix('ok', 16)};
        border: 1px solid {t.mix('ok', 45, 'border')};
        color: {t.ok};
    }}
    QPushButton[class~="meas-icon-btn-read"]:hover {{
        border-color: {t.ok};
        color: {t.ok};
        background: {t.mix('ok', 26)};
    }}
    /* param-edit mode: a bright ORANGE (accent) border, distinct + more visible than the old
    thin blue one -- the user reads blue as the feedback/send colour. */
    QFrame[class~="dialog-editing"] {{
        border: 2px solid {t.accent};
    }}

    QSplitter::handle {{
        background: {t.border};
    }}
    QSplitter::handle:hover {{
        background: {t.accent};
    }}
    QSplitter::handle:horizontal {{
        width: 2px;
    }}
    QSplitter::handle:vertical {{
        height: 2px;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {t.border2};
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}

    /* ---- tabs: the header carries the outline, the body carries none ----

    Asked for by the user (2026-08-19) when the diagnostics window grew a second tab: the tabs
    themselves were flat text on a flat ground, and the only line on screen was a box drawn around
    the CONTENT, which is the part that needs no frame. So: no pane border at all, and the selected
    tab gets a BLUE outline and underline (`info`, the palette's blue, asked for by name: "може
    синім, щоб і в темній темі було добре"). Blue rather than the accent for a reason worth
    keeping: this window's accent-orange is the colour of a WARNING everywhere else in the app —
    the guides button, the tinted picker, the below-zero total — and a selected tab is not a
    warning. `info` is defined in both palettes, so it stays legible on white and on the dark
    panel alike. */
    QTabWidget::pane {{
        border: none;
        top: -1px;
    }}
    QTabBar::tab {{
        background: {t.panel3};
        color: {t.muted};
        border: 1px solid {t.border2};
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        padding: 6px 16px;
        margin-right: 4px;
        font-size: 13px;
    }}
    QTabBar::tab:hover {{
        color: {t.text};
        border-color: {t.info};
    }}
    QTabBar::tab:selected {{
        background: {t.mix('info', 14, 'panel3')};
        color: {t.text};
        border: 1px solid {t.info};
        border-bottom: 2px solid {t.info};
        font-weight: 600;
    }}

    /* ---- every button nobody gave a class to ----

    The floor, not a style: a plain `QPushButton` is drawn by the platform, and the platform draws
    a LIGHT button — while this sheet has already told its children to use light text. Grey on grey,
    which reads as disabled. Found twice on Windows in the dark theme: the quit dialog's Save/Discard
    (2026-08-19) and then the omp catalogue dialog's own Ok/Cancel/"Configure omp…", which is a
    QDialog with a QDialogButtonBox and so was never a message box at all (user's screenshot, same
    day). Fixing it per dialog is how the second one happened, so this is the base rule for the
    type: anything with a `class` overrides it, since an attribute selector outranks a bare one. */
    QPushButton, QDialogButtonBox QPushButton {{
        background: {t.panel3};
        color: {t.text};
        border: 1px solid {t.border2};
        border-radius: 6px;
        padding: 5px 14px;
    }}
    QPushButton:hover, QDialogButtonBox QPushButton:hover {{
        border-color: {t.accent_dim};
        background: {t.mix('accent', 10, 'panel3')};
    }}
    QPushButton:pressed, QDialogButtonBox QPushButton:pressed {{
        background: {t.mix('accent', 30, 'panel3')};
    }}
    QPushButton:disabled, QDialogButtonBox QPushButton:disabled {{
        color: {t.faint};
        border-color: {t.border};
        background: {t.panel2};
    }}
    /* The answer the dialog expects, visible before it is read. */
    QPushButton:default, QDialogButtonBox QPushButton:default {{
        border: 1px solid {t.accent};
        background: {t.mix('accent', 20, 'panel3')};
        font-weight: 600;
    }}
    /* ...but a DISABLED default button is not an offer. Qt keeps both states at once, and the
    accent ring outranked the grey by coming later — so "Update TCC" sat greyed with a live-looking
    orange outline over a row that said there was nothing to update (user's screenshot). */
    QPushButton:default:disabled, QDialogButtonBox QPushButton:default:disabled {{
        border: 1px solid {t.border};
        background: {t.panel2};
        color: {t.faint};
        font-weight: 400;
    }}

    /* ---- a standard message box, which is otherwise drawn by the platform ----

    Inherits the button rules above; what is its own here is the width, so three short answers do
    not come out as three different sizes. */
    QMessageBox {{
        background: {t.panel};
    }}
    QMessageBox QLabel {{
        color: {t.text};
    }}
    QMessageBox QPushButton {{
        padding: 6px 18px;
        font-size: 13px;
        min-width: 84px;
    }}

    /* ---- feedback modal (.fb-*) ---- */
    QDialog {{
        background: {t.panel};
    }}
    QLabel[class~="fb-head"] {{
        font-size: 15px;
        font-weight: 700;
    }}
    QLabel[class~="fb-hint"] {{
        color: {t.muted};
        font-size: 12px;
    }}
    QPushButton[class~="fb-tool"] {{
        background: {t.panel3};
        border: 1px solid {t.border2};
        color: {t.text};
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 13px;
        min-width: 26px;
    }}
    QPushButton[class~="fb-tool"]:hover {{ border-color: {t.accent_dim}; }}
    QTextEdit[class~="fb-rte"] {{
        background: {t.panel2};
        border: 1px solid {t.border2};
        border-radius: 8px;
        color: {t.text};
        padding: 8px 10px;
    }}
    QPushButton[class~="fb-cancel"] {{
        background: {t.panel3};
        border: 1px solid {t.border2};
        color: {t.muted};
        border-radius: 7px;
        padding: 8px 14px;
    }}
    QPushButton[class~="fb-cancel"]:hover {{ color: {t.text}; }}
    QPushButton[class~="fb-send"] {{
        background: {t.accent};
        color: #1a1206;
        border: none;
        border-radius: 7px;
        padding: 8px 16px;
        font-weight: 700;
    }}
    QPushButton[class~="fb-send"]:hover {{ background: {t.mix('accent', 88, 'panel')}; }}
    QRadioButton {{
        color: {t.text};
        font-size: 12.5px;
        spacing: 7px;
    }}
    """
    return _scale_font_sizes(qss, scale)


_CURRENT: "Theme | None" = None


def current_theme() -> "Theme":
    """The palette last applied via `apply_theme` — lets a widget that paints its own colors
    (e.g. table-cell foregrounds) pick theme-correct hex without threading the mode through."""
    return _CURRENT if _CURRENT is not None else get_theme("dark")


#: The (mode, scale, qss) last handed to `setStyleSheet`, so an identical one is not re-applied.
_APPLIED: "tuple[str, float, str] | None" = None


def apply_theme(app, mode: Mode, scale: float = 1.0) -> Theme:
    """Swap the whole application's stylesheet — the Qt equivalent of the prototype's
    `document.documentElement.dataset.theme = mode`. `scale` reapplies the current zoom level
    (build_qss default is 1.0, i.e. no-op) so a theme toggle doesn't reset zoom."""
    global _CURRENT
    theme = get_theme(mode)
    _CURRENT = theme
    # Set the base palette too, not just QSS: a QSS `color` on `QWidget{}` does NOT reliably
    # reach a QLabel that also matches a more-specific class rule (Qt resolves color from the
    # widget's palette then, which defaulted to black -> invisible names in dark mode). The
    # palette is the dependable source for any text/base color not set by an explicit QSS rule.
    from PySide6.QtGui import QColor, QPalette

    pal = app.palette()
    text = QColor(theme.text)
    base = QColor(theme.panel)
    ground = QColor(theme.ground)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.Window, ground)
    pal.setColor(QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.faint))
    app.setPalette(pal)
    # Skip the re-style when nothing about it changed. `setStyleSheet` on the QApplication makes Qt
    # re-polish every widget in the process — 0.19 s with one window, more with each one after —
    # and building a second window re-applied an identical sheet for no reason at all.
    global _APPLIED
    qss = build_qss(theme, scale=scale)
    if _APPLIED != (mode, scale, qss):
        app.setStyleSheet(qss)
        _APPLIED = (mode, scale, qss)
    return theme
