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

    /* .panel — the card background used by every section */
    QFrame[class~="panel"] {{
        background: {t.panel};
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
        padding: 4px 9px;
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

    /* Native tooltips are tiny and low-contrast -- theme them so channel hover-hints read well. */
    QToolTip {{
        background: {t.panel3};
        color: {t.text};
        border: 1px solid {t.border2};
        border-radius: 5px;
        padding: 6px 9px;
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
    QLabel[class~="pill-off"] {{
        color: {t.off};
        background: {t.panel3};
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
        background: {t.panel};
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
        background: {t.panel};
        color: {t.muted};
        border: none;
        border-bottom: 1px solid {t.border2};
        padding: 6px 10px;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 600;
    }}

    QLabel[class~="eq-hint"] {{
        color: {t.faint};
        font-size: 11px;
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
    QLabel[class~="stag"] {{ font-size: 10px; }}
    QLabel[class~="stag-ok"] {{ color: {t.ok}; }}
    QLabel[class~="stag-wait"] {{ color: {t.yellow}; }}

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
    QLabel[class~="mcol-h"] {{
        font-size: 9.5px;
        letter-spacing: 1px;
        text-transform: uppercase;
        color: {t.muted};
        border-bottom: 1px solid {t.border};
        padding-bottom: 3px;
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

    QPushButton[class~="edit-chip"] {{
        background: {t.panel3};
        border: 1px solid {t.border2};
        color: {t.muted};
        border-radius: 12px;
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
    QPushButton[class~="reason-btn"] {{
        background: {t.panel3};
        border: 1px solid {t.border2};
        color: {t.text};
        border-radius: 12px;
        padding: 4px 12px;
        font-size: 11.5px;
    }}
    QPushButton[class~="reason-btn"]:hover {{
        border-color: {t.info};
        color: {t.info};
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
