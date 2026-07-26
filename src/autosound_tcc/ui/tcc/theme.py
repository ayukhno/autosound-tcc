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

from dataclasses import dataclass, field
from typing import Literal

Mode = Literal["dark", "light"]

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


def build_qss(theme: Theme) -> str:
    """The application-wide stylesheet. Widgets opt into a "class" via the Qt dynamic-property
    trick (`widget.setProperty("class", "panel")`) since QSS object names must be unique but
    many widgets share the same look — mirrors the prototype's CSS classes.
    """
    t = theme
    return f"""
    QMainWindow, QWidget#AppRoot {{
        background: {t.ground};
    }}
    QWidget {{
        color: {t.text};
        font-size: 13px;
    }}
    QLabel {{
        background: transparent;
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

    QSplitter::handle {{
        background: transparent;
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
    """


def apply_theme(app, mode: Mode) -> Theme:
    """Swap the whole application's stylesheet — the Qt equivalent of the prototype's
    `document.documentElement.dataset.theme = mode`."""
    theme = get_theme(mode)
    app.setStyleSheet(build_qss(theme))
    return theme
