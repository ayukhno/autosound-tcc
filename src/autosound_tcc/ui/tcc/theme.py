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
from PySide6.QtWidgets import QWidget

Mode = Literal["dark", "light"]


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
}

PALETTE_LIGHT: dict[str, str] = {
    "ground": "#eef1f5", "panel": "#ffffff", "panel2": "#f4f6f9", "panel3": "#e9edf2",
    "border": "#d7dee6", "border2": "#c4cdd8",
    "text": "#1b2430", "muted": "#5c6875", "faint": "#93a0ad",
    "accent": "#c56f18", "accent_dim": "#a95f14",
    "ok": "#1f9c63", "inv": "#c56f18", "off": "#8492a0", "warn": "#c0392b",
    "info": "#2f7fc4", "yellow": "#c99a12",
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
        background: {t.mix('accent', 16, 'panel2')};
        border: 1px solid {t.mix('accent', 30, 'border')};
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
    QLabel[class~="msg-who-user"] {{ color: {t.accent}; }}
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

    /* The "still working" line under the transcript -- system-grey, so it reads as chrome
       rather than as something the model said. */
    QLabel[class~="activity"] {{
        color: {t.muted};
        font-size: 11px;
        padding: 2px 12px 0 12px;
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
    app.setStyleSheet(build_qss(theme, scale=scale))
    return theme
