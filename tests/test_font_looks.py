"""Font looks in the ☰ menu (tcc#237): four of them, the default untouched, picked and remembered.

What is drawn is read off the widgets: a heading and a value of a real window, through the sheet the
window was given, as `QFont`, the way the person sees them.
"""

from __future__ import annotations

import logging
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc import i18n, menu_registry, theme  # noqa: E402
from tests import _windows  # noqa: E402
from tests.test_control_layout import _window  # noqa: E402

MONO = "SF Mono"
ALL_LOOKS = ("normal", "light", "rounded", "typewriter")


def _looks():
    from autosound_tcc.ui.tcc import font_looks

    return font_looks


def _themed_window(tmp_path, monkeypatch, *, families=True):
    window = _window(tmp_path, monkeypatch)
    _windows.theme_on_the_window(monkeypatch, window)
    monkeypatch.setattr(_looks(), "_has_family", lambda _name: families)
    return window


def _pick(window, look) -> None:
    action = window._main_menu.action(f"font_{look}")
    assert action is not None, "no such line in the menu"
    action.trigger()
    QApplication.processEvents()


def _font(label):
    label.ensurePolished()
    return label.font()


def _heading_and_value(window):
    return window._plan_title, window._slot_label


def test_the_menu_offers_the_four_looks_and_ticks_the_current_one(tmp_path, monkeypatch):
    window = _themed_window(tmp_path, monkeypatch)
    lines = menu_registry.ordered(menu_registry.collect(), "font_look")
    assert [line.id for line in lines] == [f"font_{look}" for look in ALL_LOOKS]
    assert [line.text() for line in lines] == [
        i18n.t(key) for key in ("fontLookNormal", "fontLookLight", "fontLookRounded",
                                "fontLookTypewriter")]
    settings_lines = [e.id for e in menu_registry.ordered(menu_registry.collect(), "settings")]
    assert settings_lines.index("font_look") == settings_lines.index("theme") + 1

    window._main_menu.sync()
    ticked = [look for look in ALL_LOOKS if window._main_menu.action(f"font_{look}").isChecked()]
    assert ticked == ["normal"]
    _pick(window, "rounded")
    window._main_menu.sync()
    ticked = [look for look in ALL_LOOKS if window._main_menu.action(f"font_{look}").isChecked()]
    assert ticked == ["rounded"]


def test_picking_a_look_applies_it_and_it_is_remembered(tmp_path, monkeypatch):
    window = _themed_window(tmp_path, monkeypatch)
    heading, value = _heading_and_value(window)

    _pick(window, "typewriter")

    font = _font(heading)
    assert font.family() == "Courier New"
    assert font.pixelSize() == 14 and font.weight() == 400
    assert MONO in _font(value).families()
    assert window._settings.value("ui/font") == "typewriter"

    # The next start reads the same word.
    assert _looks().saved(window._settings) == "typewriter"


def test_the_default_look_s_sheet_is_the_sheet_without_a_look():
    for mode in ("dark", "light"):
        palette = theme.get_theme(mode)
        plain = theme.build_qss(palette)
        assert "Courier New" not in plain and "Trebuchet" not in plain
        assert "sec-title" not in plain
    sheet = 'QLabel[class~="kv-val"] { font-weight: 600; font-size: 12px; }\n'
    assert _looks().dress(sheet, "normal") == sheet


def test_a_look_survives_a_theme_switch_and_a_zoom(tmp_path, monkeypatch):
    window = _themed_window(tmp_path, monkeypatch)
    heading, value = _heading_and_value(window)
    _pick(window, "typewriter")

    window._apply_theme("light" if window._mode == "dark" else "dark")
    assert _font(heading).family() == "Courier New"

    window._set_zoom(1.2)
    font = _font(heading)
    assert font.family() == "Courier New"
    assert font.pixelSize() in (16, 17)  # 14 px × 1.2, the zoom scales the look's own size too
    assert MONO in _font(value).families()


def test_an_unknown_or_old_saved_value_is_the_default_look(tmp_path, monkeypatch):
    looks = _looks()
    for value in ("bogus", "", None, 3, ["a", "b"]):
        assert looks.sane(value) == looks.DEFAULT
    palette = theme.get_theme("dark")
    assert theme.build_qss(palette, font="bogus") == theme.build_qss(palette)

    window = _themed_window(tmp_path, monkeypatch)
    window._settings.setValue("ui/font", "fancy-2019")
    window._set_zoom(1.0)
    heading, _value = _heading_and_value(window)
    assert _font(heading).family() != "Courier New"


@pytest.mark.parametrize("look", ("light", "rounded", "typewriter"))
def test_the_mono_values_keep_their_face_and_their_weight(tmp_path, monkeypatch, look):
    window = _themed_window(tmp_path, monkeypatch)
    _heading, value = _heading_and_value(window)
    before = _font(value).weight()
    _pick(window, look)
    font = _font(value)
    assert MONO in font.families()
    assert font.weight() == before  # slot-val is 600: the mono classes stay as they are


def test_the_light_look_is_light_and_leaves_the_theme_s_bold_alone(tmp_path, monkeypatch):
    window = _themed_window(tmp_path, monkeypatch)
    _pick(window, "light")
    plain = window._preset_field_lbl  # a class with no weight of its own
    assert _font(plain).weight() == 300
    assert _font(window._plan_title).weight() == 600  # `.phead-title` sets it


def test_the_rounded_look_reaches_the_general_text(tmp_path, monkeypatch):
    window = _themed_window(tmp_path, monkeypatch)
    _pick(window, "rounded")
    assert _font(window._preset_field_lbl).family() == "Trebuchet MS"
    assert MONO in _font(window._slot_label).families()


def test_the_typewriter_look_is_calmer_in_the_reading_text(tmp_path, monkeypatch):
    window = _themed_window(tmp_path, monkeypatch)
    _pick(window, "typewriter")
    # `.kv-val` is 600 in the theme, and reading text in this look.
    assert _font(window._project_label).weight() == 500
    # The other headings: the header's, and the left panel's.
    preset = _font(window._preset_field_lbl)
    assert preset.family() == "Courier New" and preset.weight() == 400


def test_a_family_the_machine_lacks_leaves_the_system_font(tmp_path, monkeypatch):
    window = _themed_window(tmp_path, monkeypatch, families=False)
    system = _font(window._preset_field_lbl).family()

    _pick(window, "rounded")
    assert _font(window._preset_field_lbl).family() == system
    assert "Trebuchet" not in theme.build_qss(theme.get_theme("dark"), font="rounded")

    _pick(window, "typewriter")
    assert _font(window._plan_title).family() == system
    assert "Courier New" not in theme.build_qss(theme.get_theme("dark"), font="typewriter")


@pytest.mark.parametrize("look", ALL_LOOKS)
def test_no_heading_is_cut_at_the_normal_size_in_ukrainian(tmp_path, monkeypatch, look):
    """The window's headings in Ukrainian, the language it is mostly used in. Polish's longest
    title is wider: the test after this one."""
    window = _themed_window(tmp_path, monkeypatch)
    window._on_language_selected("uk")
    window.resize(1500, 900)
    window.show()
    QApplication.processEvents()
    _pick(window, look)
    for _ in range(4):
        QApplication.processEvents()

    for title in (window._plan_title, window._meas_title, window._preset_field_lbl):
        assert title.width() >= title.fontMetrics().horizontalAdvance(title.text()) - 1, title.text()
    for section in (window._project_section, window._system_section, window._audio_section):
        assert section._title_label.text() == section._title_label._full
    window.hide()


def test_the_left_column_follows_a_new_language_in_the_typewriter_look(tmp_path, monkeypatch):
    """Polish's section title needs more than the Ukrainian one the floor was read for, and the
    floor was re-read only by a restyle: «Parametry projek…»."""
    window = _themed_window(tmp_path, monkeypatch)
    window._on_language_selected("uk")
    window.resize(1500, 900)
    window.show()
    QApplication.processEvents()
    _pick(window, "typewriter")
    try:
        window._on_language_selected("pl")
        assert window._left.minimumWidth() >= _looks().left_floor(window) > 0
        for _ in range(4):
            QApplication.processEvents()
        title = window._project_section._title_label
        assert title.text() == title._full, title.text()
    finally:
        window._on_language_selected("en")
        window.hide()


def _on_windows(monkeypatch, *, style: bool, family: bool) -> None:
    looks = _looks()
    monkeypatch.setattr(looks, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(looks, "_segoe_has_light", lambda: style)
    monkeypatch.setattr(looks, "_has_family", lambda name: family and name == "Segoe UI Light")


@pytest.mark.parametrize("style, family, expected", [
    (True, True, "Segoe UI"),  # the style is the better of the two
    (False, True, "Segoe UI Light"),
    (False, False, ""),
])
def test_the_light_family_on_windows(monkeypatch, style, family, expected):
    QApplication.instance() or QApplication([])
    _on_windows(monkeypatch, style=style, family=family)
    assert _looks()._light_family() == expected


def test_the_light_family_elsewhere_is_the_system_font(monkeypatch):
    looks = _looks()
    monkeypatch.setattr(looks, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(looks, "_segoe_has_light", lambda: True)
    assert looks._light_family() == ""


def test_a_look_whose_font_is_absent_leaves_one_log_line_each(app_log_heard, monkeypatch):
    QApplication.instance() or QApplication([])
    looks = _looks()
    heard = app_log_heard(logging.INFO)
    monkeypatch.setattr(looks, "_told", set(), raising=False)
    _on_windows(monkeypatch, style=False, family=False)

    for look in ("rounded", "rounded", "typewriter", "light", "typewriter"):
        looks.dress("", look)

    lines = sorted(record.getMessage() for record in heard)
    assert len(lines) == 3, lines
    for line, look, family in zip(lines, ("light", "rounded", "typewriter"),
                                  ("Segoe UI Light", "Trebuchet MS", "Courier New")):
        assert look in line and family in line, line
    assert {record.levelno for record in heard} == {logging.INFO}, "not a warning: nothing to show"


def test_a_remembered_look_is_on_at_the_next_start(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc import main_window

    seen = []
    monkeypatch.setattr(main_window, "apply_theme",
                        lambda _app, mode, scale=1.0, font="normal": seen.append(font))
    main_window.get_settings().setValue(_looks().KEY, "typewriter")
    _window(tmp_path, monkeypatch)
    assert seen and seen[0] == "typewriter"
