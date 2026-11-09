"""The window's font looks, picked in ☰ ⚙ Settings beside the theme switch (tcc#237).

A `menu_registry` provider, and the decision of what each look does to the sheet: `dress` takes the
theme's finished stylesheet and returns the one for a look, so the theme keeps its one source and the
zoom, applied last, scales a look's own sizes too. The default look returns the sheet untouched.

The looks, as the Arbiter chose them on real screenshots (2026-11-09):

* **normal** — today's look.
* **light** — the system font in a light weight (Segoe UI Light on Windows, weight 300 on macOS).
* **rounded** — the general text in Trebuchet MS.
* **typewriter** — the section headings in Courier New, normal weight, at 14 px; the reading text a
  step calmer (600 and 700 go to 500).

The mono classes (`"SF Mono", Menlo, monospace`: values, numbers, the tree's second line) stay as
they are in every look. A family this machine does not have is simply not named: the widget keeps
the system font, where Qt left to fall back alone may land on anything, a serif included.

This module imports no Qt at its top: `menu_registry.collect()` reads it, and the registry is Qt-free.
"""

from __future__ import annotations

import re
import sys
from typing import Any

#: The look's word in QSettings; the window's other `ui/…` keys sit beside it.
KEY = "ui/font"

DEFAULT = "normal"
LIGHT = "light"
ROUNDED = "rounded"
TYPEWRITER = "typewriter"

#: (look, the i18n key of its line), in the order of the menu.
LOOKS: tuple[tuple[str, str], ...] = (
    (DEFAULT, "fontLookNormal"),
    (LIGHT, "fontLookLight"),
    (ROUNDED, "fontLookRounded"),
    (TYPEWRITER, "fontLookTypewriter"),
)

_ROUNDED_FAMILY = "Trebuchet MS"
_HEADING_FAMILY = "Courier New"
#: What marks a mono rule of the theme's sheet: its first family.
_MONO = '"SF Mono"'
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_HEAVY = re.compile(r"font-weight:\s*(?:600|700)\b")
_CLASS = re.compile(r'class~="([^"]+)"')


def sane(value: Any) -> str:
    """The look a stored value names; anything else — old, foreign, missing — is the default."""
    return value if value in {look for look, _key in LOOKS} else DEFAULT


def saved(settings) -> str:
    """The look this machine last chose."""
    return sane(settings.value(KEY, DEFAULT))


def _has_family(name: str) -> bool:
    """Whether this machine can draw `name`. Without an application the font database aborts the
    process, so a sheet built before one simply names no optional family."""
    from PySide6.QtGui import QFontDatabase, QGuiApplication

    return QGuiApplication.instance() is not None and QFontDatabase.hasFamily(name)


def _segoe_has_light() -> bool:
    from PySide6.QtGui import QFontDatabase, QGuiApplication

    return QGuiApplication.instance() is not None and "Light" in QFontDatabase.styles("Segoe UI")


def _light_family() -> str:
    """The family of the light look; "" keeps the system font, at weight 300 (macOS).

    On Windows the Light face is either a style of Segoe UI or, in the older font database, a family
    of its own. As a style it is the better of the two: the theme's bold elements then get Segoe's
    real Semibold rather than a Light face thickened by the renderer."""
    if sys.platform != "win32":
        return ""
    if _segoe_has_light():
        return "Segoe UI"
    return "Segoe UI Light" if _has_family("Segoe UI Light") else ""


def _general(family: str, weight: int = 0) -> str:
    """A rule for the general text. It goes FIRST in the sheet: every rule of the theme then
    outranks it, a mono class's family and a bold class's weight included."""
    body = (f'font-family: "{family}"; ' if family else "") + (f"font-weight: {weight};" if weight else "")
    return f"\n    QWidget {{ {body} }}\n" if body else ""


def _headings() -> str:
    """The section titles (`sec-title`) of the typewriter look. Last in the sheet; the second
    selector matches the weight of the theme's `.ghead QLabel`. The letter-spacing is the labels'
    own `QFont` (`theme.apply_caps`) and stays."""
    family = f'font-family: "{_HEADING_FAMILY}"; ' if _has_family(_HEADING_FAMILY) else ""
    return (f'\n    QLabel[class~="sec-title"], QWidget[class~="ghead"] QLabel[class~="sec-title"] '
            f"{{ {family}font-size: 14px; font-weight: 400; }}\n")


def _calmer(qss: str) -> str:
    """600 and 700 down to 500, everywhere but the mono rules and the rules on a mono class."""
    mono = {name for selector, body in _RULE.findall(qss) if _MONO in body
            for name in _CLASS.findall(selector)}

    def rule(match: re.Match) -> str:
        selector, body = match.group(1), match.group(2)
        if _MONO in body or mono & set(_CLASS.findall(selector)):
            return match.group(0)
        return f"{selector}{{{_HEAVY.sub('font-weight: 500', body)}}}"

    return _RULE.sub(rule, qss)


def dress(qss: str, look: Any) -> str:
    """The theme's finished sheet for `look`, before the zoom scales it."""
    look = sane(look)
    if look == LIGHT:
        return _general(_light_family(), 300) + qss
    if look == ROUNDED:
        return _general(_ROUNDED_FAMILY if _has_family(_ROUNDED_FAMILY) else "") + qss
    if look == TYPEWRITER:
        return _calmer(qss) + _headings()
    return qss


def head_floor(window) -> int:
    """What the focus card's head row needs in the typewriter look, whole; 0 in the other looks,
    whose column stays as it was. Its wider 14-px heading no longer fits the right column beside
    «Готово» and the REW mark at the window's normal size, and a plain label there is cut, so the
    column follows the row (`_fit_right_floor`), the way it follows the measurement panel."""
    if saved(window._settings) != TYPEWRITER:
        return 0
    card = window._meas_card
    return window._meas_title.parentWidget().minimumSizeHint().width() + card.width() - card.contentsRect().width()


def left_floor(window) -> int:
    """The left column's floor in the typewriter look: the widest section title, whole, beside
    its dot and the sub at its floor; 0 in the other looks. The window's normal 258 px cuts
    ПАРАМЕТРИ ПРОЄКТУ at 14 px with the sub beside it."""
    if saved(window._settings) != TYPEWRITER:
        return 0
    from autosound_tcc.ui.tcc.sidebar_section import SidebarSection

    left = window._left
    return (max((s.head_need() for s in left.findChildren(SidebarSection)), default=0)
            + left.width() - left.contentsRect().width())  # the card's own border


def pick(window, look: str) -> None:
    """A line of the menu pressed: remembered, then the window redrawn in it, under the theme
    switch's guard (a restyle is as slow as a theme change, VM-12)."""

    def change() -> None:
        window._settings.setValue(KEY, sane(look))
        window._restyle()

    window._switch(window._theme_btn, change)


def menu_entries() -> list:
    from autosound_tcc.ui.tcc.menu_registry import MenuEntry

    return [
        MenuEntry("font_look", "settings", label_key="menuFontLook", submenu=True, before="language"),
        *[MenuEntry(f"font_{look}", "font_look", label_key=key,
                    on=lambda w, chosen=look: pick(w, chosen),
                    checked=lambda w, chosen=look: saved(w._settings) == chosen)
          for look, key in LOOKS],
    ]
