"""EN/UK strings — ported from the web prototype's `T = {en, uk}` table
(`data/private/prototype/tcc-main.html`). Keys are kept identical to the prototype's so later
milestones can copy more entries in verbatim instead of re-naming anything.

Every user-facing string in the app should go through `t()`/`tx()`, and every widget that
displays translated text registers a retranslate callback via `on_language_changed()` so
`set_language()` can repaint the whole UI in place — mirrors the prototype's `setLang()`.
"""

from __future__ import annotations

from typing import Callable

Lang = str  # "en" | "uk"

T: dict[Lang, dict[str, str]] = {
    "en": {
        "theme": "theme",
        "dspPanel": "DSP",
        "dialog": "AI dialog",
        "dialogSub": "Generator ↔ Critic ↔ Arbiter",
        "planTitle": "Plan — Fact",
        "planSub": "phases + steps",
        "focus": "◆ IN FOCUS NOW",
        "measSub": "measurement task",
    },
    "uk": {
        "theme": "тема",
        "dspPanel": "DSP",
        "dialog": "Діалог з ШІ",
        "dialogSub": "Generator ↔ Critic ↔ Arbiter",
        "planTitle": "План — Факт",
        "planSub": "фази + кроки",
        "focus": "◆ У ФОКУСІ ЗАРАЗ",
        "measSub": "задача на замір",
    },
}

_lang: Lang = "en"
_listeners: list[Callable[[], None]] = []


def current_language() -> Lang:
    return _lang


def t(key: str) -> str:
    """Plain string lookup, falling back to English, then the key itself."""
    return T.get(_lang, {}).get(key, T["en"].get(key, key))


def tx(obj) -> str:
    """Per-language object picker: `{"en": "...", "uk": "..."}` -> the current language's value.
    Passing a plain string returns it unchanged (mirrors the prototype's `tx()`)."""
    if isinstance(obj, dict):
        return obj.get(_lang, obj.get("en", ""))
    return obj


def on_language_changed(callback: Callable[[], None]) -> None:
    """Register a no-arg callback to run every time the language changes (a widget's own
    "retranslate myself" method). Mirrors the prototype re-rendering `[data-i]` elements."""
    _listeners.append(callback)


def set_language(lang: Lang) -> None:
    global _lang
    if lang not in T:
        raise ValueError(f"unknown language {lang!r}, known: {sorted(T)}")
    _lang = lang
    for callback in list(_listeners):
        callback()
