"""«Показати версію…» (#249): one version looked at in the DSP tree, read-only.

`window._view` stays HEAD, whatever is looked at. That is what every reader that ACTS reads — the
channel switches, the delay panel's present values, the listening and protective dialogs, «Збережено
в DSP…», the preset the measurement panel and `get_tcc_state` are told — so none of them can be handed
a version somebody is merely looking at. Only what DRAWS asks `on_screen`: the tree, the pane, the
control layout's tabs, the dots, the width floor.

A key names the version (`v_002`, or `SQ/v_004` from another slot, as compare keys do). It is kept
through a language or theme change and through control mode, and through a watcher's reload that moved
nothing (a session rewriting `project.json`); a preset switch takes it back to HEAD, and so does a
watcher's reload that found HEAD or the set of versions changed, which says so once. A version that
cannot be read or drawn goes back to HEAD too, said. Out of `main_window.py`, which may not grow.
"""

from __future__ import annotations

import functools
from typing import Callable, Optional

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QWidget

from autosound_tcc.core import app_log
from autosound_tcc.state import ledger_line
from autosound_tcc.ui.tcc import dsp_check, i18n, window_folder
from autosound_tcc.ui.tcc.detail_pane import is_other_preset


def key_of(window) -> Optional[str]:
    """The version looked at (`v_002`, `SQ/v_004`), or None for HEAD."""
    return getattr(window, "_shown_key", None)


def on_screen(window):
    """The view drawn: the looked-at version, or HEAD (`window._view`)."""
    looked_at = getattr(window, "_looked_at", None)
    return looked_at if looked_at is not None else getattr(window, "_view", None)


def _split(window, key: str) -> tuple[Optional[str], str]:
    return tuple(key.split("/", 1)) if is_other_preset(key) else (window._loaded_preset, key)


def _said(window, key: str) -> str:
    of, version = _split(window, key)
    text = ledger_line.label(window_folder.state_root(window), version)
    return f"{text} · {of}" if is_other_preset(key) else text


def read(window, load: Callable, root, profile):
    """The view to draw now. A version that cannot be read is said, and HEAD is drawn."""
    key = key_of(window)
    window._looked_at = None
    if key is not None:
        of, version = _split(window, key)
        try:
            window._looked_at = load(str(root), of, profile, version=version)
        except Exception as exc:  # noqa: BLE001 - gone or broken: a word and back to HEAD, not a crash
            app_log.logger().warning("the version looked at, %s of %s, could not be read: %s: %s",
                                     version, of, type(exc).__name__, exc, exc_info=exc)
            window._shown_key = None
            window._status_strip.notify(
                i18n.t("shownVersionUnreadable").format(version=version), level="warn",
                dismissible=True)
    return on_screen(window)


def offer_compare(window, load: Callable, root, preset: str, profile: dict,
                  current: Optional[str]) -> None:
    """«Порівняти з» for the channel tables: the other versions, newest first, each with the
    names it was saved under in the device; selected by default is the PREVIOUS one (the Arbiter,
    2026-09-23: «за замовчанням попередній»). With a version looked at, the list is that
    version's: it is what the left side of a comparison is, and its slot's list is the one offered.

    Previous is the ancestry, never the number below (hub #198): SQ-2 (v_006) is compared with SQ-1
    (v_003) even with v_004 and v_005 banked for another preset between them. The method stores that
    at save time; `ledger_line.previous_of` reads it.

    After this preset's versions come the other presets' (the Arbiter, 2026-09-25, finding 66:
    «порівнювати не тільки v_xxx в поточній конфігурації, але і з іншими конфігураціями»), keyed
    `SQ/v_004` so the loader reads each from its own preset."""
    key = key_of(window)
    looked_at = key is not None
    if looked_at:
        preset, current = _split(window, key)
    own, default, labels, others = ledger_line.compare_offer(root, preset, current)

    def read_one(key: str, _root=str(root), _preset=preset, _profile=profile, _load=load):
        of, version = key.split("/", 1) if is_other_preset(key) else (_preset, key)
        return _load(_root, of, _profile, version=version)

    # One read per version: the pane, the control layout's tabs and the dots all ask for it.
    loader = functools.lru_cache(maxsize=16)(read_one)
    # `preset`, `current`, `looked_at` and the checked marks ride along after `others` (5 to 8) so
    # `control_layout._fill_compare` can head and grey the own group the same way (tcc#103) --
    # appended, not inserted, so the existing `len(args) > 3`/`> 4` reads stay right.
    checks = dsp_check.marks(root, preset, own, others, profile)
    window._compare_args = (own, default, loader, labels, others, preset, current, looked_at, checks)
    window._compare_key = default
    window._detail.set_compare_choices(own, default, loader, labels=labels, others=others,
                                       preset=preset, current=current, looked_at=looked_at, checks=checks)
    window._sync_status_dots()


def sub(window, text: str) -> str:
    """The header names HEAD; with a version looked at, it says which one is on screen too."""
    key = key_of(window)
    return i18n.t("shownVersionSub").format(head=text, shown=_split(window, key)[1]) if key else text


def row(window) -> QWidget:
    """The strip over the tree: the picker, and — while looking — the mark and the way back."""
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(12, 2, 8, 2)
    layout.setSpacing(6)
    window._shown_mark = QLabel("")
    window._shown_mark.setProperty("class", "phead-sub open-q")
    window._shown_mark.setWordWrap(True)
    window._shown_back = QPushButton("")
    window._shown_back.setProperty("class", "link-btn")
    window._shown_back.setCursor(Qt.CursorShape.PointingHandCursor)
    window._shown_back.clicked.connect(lambda _c=False: back(window))
    window._shown_pick = QPushButton("")
    window._shown_pick.setProperty("class", "link-btn")
    window._shown_pick.setCursor(Qt.CursorShape.PointingHandCursor)
    window._shown_pick.clicked.connect(lambda _c=False: _open_picker(window))
    layout.addWidget(window._shown_mark, stretch=1)
    layout.addWidget(window._shown_back)
    layout.addWidget(window._shown_pick)
    widget.setVisible(False)
    window._shown_row = widget
    return widget


def sync(window) -> None:
    """The strip, from the key and the language of the moment."""
    if getattr(window, "_shown_row", None) is None:
        return
    window._shown_row.setVisible(bool(window._has_project and getattr(window._view, "version", None)))
    window._shown_pick.setText(i18n.t("shownVersionPick"))
    window._shown_back.setText(i18n.t("shownVersionBack"))
    key = key_of(window)
    window._shown_mark.setVisible(key is not None)
    window._shown_back.setVisible(key is not None)
    window._shown_mark.setText(i18n.t("shownVersionMark").format(version=_said(window, key))
                               if key else "")


def clear(window) -> None:
    """Nothing looked at any more, and the strip says so."""
    window._shown_key = None
    window._looked_at = None
    sync(window)


def show(window, key: str) -> None:
    window._shown_key = key
    window._shown_line = ledger_line.line_mark(window_folder.state_root(window), window._loaded_preset)
    window._safe_load_project()


def back(window) -> None:
    """The one way back to HEAD."""
    window._shown_key = None
    window._safe_load_project()


def draw_failed(window, exc: Exception) -> None:
    """A project load that could not be drawn (`_safe_load_project`). With a version looked at it is
    that version's doing: the key goes, HEAD is drawn and the strip says so — left set, every
    later load fails the same way with an empty tree. On HEAD itself the last good view stays on
    screen and what happened is said (a ledger once said `slot: 1`, and `QLabel(int)` aborted the
    process): a panel that cannot draw, not a session that ends."""
    app_log.logger().exception("the project could not be drawn from disk")
    key = key_of(window)
    if key is None:
        window._status_strip.notify(i18n.t("projectRenderFailed").format(
            error=f"{type(exc).__name__}: {str(exc)[:200]}"), level="warn")
        return
    window._shown_key = None
    window._looked_at = None
    window._status_strip.notify(i18n.t("shownVersionUnreadable").format(version=_split(window, key)[1]),
                                level="warn", dismissible=True)
    window._safe_load_project()


def say_copied(window, said: str) -> None:
    """Where a copied EQ is said. A looked-at version's EQ can legitimately be copied; the sentence
    names it, so nobody pastes it believing it is the current one."""
    key = key_of(window)
    window._status_strip.notify(i18n.t("shownVersionCopied").format(
        version=_said(window, key), said=said) if key else said)


def reload_at_head(window, load: Callable[[], None]) -> None:
    """The watcher's reload. A write that moved nothing — a session rewriting `project.json` —
    keeps the version looked at. HEAD or the set of versions changed: what is on disk has moved,
    so HEAD goes back on screen, said once. A shown version that is gone says so in `read`."""
    key = key_of(window)
    if key is None:
        load()
        return
    held = getattr(window, "_shown_line", None)
    if held is not None and not ledger_line.moved(
            held, ledger_line.line_mark(window_folder.state_root(window), window._loaded_preset)):
        load()
        return
    window._shown_key = None
    load()
    window._status_strip.notify(i18n.t("shownVersionReset").format(
        version=getattr(window._view, "version", "") or ""), level="warn", dismissible=True)


def picker_menu(window) -> QMenu:
    """«Показати версію…», from `compare_offer`: every version of every slot; the current one and
    the one already shown are greyed (the way back is the strip's button)."""
    root = window_folder.state_root(window)
    preset = window._loaded_preset
    head = getattr(window._view, "file_version", None) or window._view.version
    offer = ledger_line.compare_offer(root, preset, head)
    shown = key_of(window)
    menu = QMenu(window)

    def add(text: str, key: Optional[str]) -> None:
        action = menu.addAction(text)
        action.setEnabled(key is not None and key != shown)
        if key is not None and key != shown:
            action.triggered.connect(lambda _c=False, k=key: show(window, k))

    add(i18n.t("cmpOwnPreset").format(preset=preset), None)
    for version in offer.own:
        label = offer.labels.get(version, version)
        if version == head:
            add(i18n.t("cmpCurrentVersion").format(version=label), None)
        else:
            add(label, version)
    for other, items in offer.others:
        menu.addSeparator()
        add(i18n.t("cmpOtherPreset").format(preset=other), None)
        for key, label in items:
            add(label, key)
    return menu


def _open_picker(window) -> None:
    menu = picker_menu(window)
    button = window._shown_pick
    menu.exec(button.mapToGlobal(QPoint(0, button.height())))
    menu.deleteLater()
