import pytest


def test_the_permission_bar_is_actually_tinted_not_just_declared_tinted():
    """It said `mix("inv", 0.18, "panel")` and rendered `rgb(255, 255, 255)`.

    `mix` takes a PERCENTAGE. `0.18` is eighteen hundredths of one percent — white on light, the
    panel colour on dark. So the attention background the Arbiter asked for was never drawn, the
    bar read as an ordinary panel, they did not see the question, and a five-minute wait looked
    like the app had hung (2026-09-11).

    The test computes the colour rather than reading the stylesheet for a token name: the old rule
    MENTIONED `inv` and was still white, so mentioning it proves nothing.
    """
    import re

    from autosound_tcc.ui.tcc import theme

    for name in ("dark", "light"):
        palette = theme.get_theme(name)
        sheet = theme.build_qss(palette)
        block = sheet.split('QWidget[class~="confirm-bar"]', 1)[1].split("}", 1)[0]
        found = re.search(r"background:\s*rgba?\(([^)]+)\)", block)
        assert found, f"{name}: the bar has no computed background at all"
        bar = [int(float(part)) for part in found.group(1).split(",")[:3]]

        panel = list(theme._to_rgb(palette.panel))
        distance = sum(abs(a - b) for a, b in zip(bar, panel))
        assert distance > 40, (
            f"{name}: the bar is {bar} and the panel behind it is {panel} — "
            f"a difference of {distance} is not a background anybody will notice")


def test_no_tint_is_written_as_a_fraction_when_mix_takes_a_percentage():
    """One wrong call was a missing colour; EIGHT of them was a missing vocabulary.

    `mix(colour, pct, other)` takes 0-100. Eight calls passed `0.10`…`0.45`, meaning a tenth of
    one percent — indistinguishable from the panel behind them. What went missing was not
    decoration: `chan-toggle-on` / `-wait` / `-late` are the CHANNEL'S STATE, and all three drew
    as a plain button. The permission bar was the one somebody noticed, because missing it looked
    like the application had hung (2026-09-11).

    Nothing legitimate asks for less than one percent of a colour, so the rule can be absolute.
    """
    import re
    from pathlib import Path

    from autosound_tcc.ui.tcc import theme

    source = Path(theme.__file__).read_text(encoding="utf-8")
    guilty = re.findall(r"mix\(\s*\"[a-z_]+\"\s*,\s*(0\.\d+)\s*[,)]", source)

    assert guilty == [], (
        f"these are fractions where a percentage is meant: {guilty}. "
        "0.18 is not 18% — it is eighteen hundredths of one percent, and it draws as nothing.")


def _contrast(a: str, b: str) -> float:
    def lum(h):
        h = h.lstrip("#")
        r, g, b_ = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b_)
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_faint_grey_reads_on_every_panel():
    """Finding 51 (tcc#65): the faint grey strained the eyes, in both themes and in many places —
    2.3 to 3.2 : 1. Now close to WCAG AA's 4.5 on a card, and still below `muted`."""
    from autosound_tcc.ui.tcc.theme import PALETTE_DARK, PALETTE_LIGHT

    for palette in (PALETTE_DARK, PALETTE_LIGHT):
        assert _contrast(palette["faint"], palette["panel"]) >= 4.5
        assert _contrast(palette["faint"], palette["panel2"]) >= 4.4
        assert _contrast(palette["faint"], palette["panel"]) < _contrast(palette["muted"],
                                                                          palette["panel"])


def test_a_plain_text_field_is_themed():
    """Finding 52: the dark theme's search field was white with pale text on Windows."""
    from autosound_tcc.ui.tcc.theme import build_qss, get_theme

    qss = build_qss(get_theme("dark"))
    assert "QLineEdit {" in qss.replace("QLineEdit {{", "QLineEdit {")


def test_the_reviewer_pickers_state_colour_holds_under_the_mouse():
    """Finding 96 (tcc#82): a green «answered» frame turned red-brown under the cursor — the
    pickers' common hover border drawn over the state colour — and read as a refusal."""
    from autosound_tcc.ui.tcc import theme

    for name in ("dark", "light"):
        palette = theme.get_theme(name)
        sheet = theme.build_qss(palette)
        common = sheet.index('QComboBox[class~="mini-select"]:hover')
        for state, colour in (("is-ok", palette.ok), ("is-missing", palette.warn)):
            rule = f'QComboBox[class~="{state}"]:hover'
            assert rule in sheet, (name, state)
            at = sheet.index(rule)
            assert at > common, "later in the sheet, so it wins over the common hover"
            assert colour in sheet[at:].split("}", 1)[0], (name, state)


def _hex(value: str) -> str:
    """`#rrggbb` or `rgb(r, g, b)` as the sheet writes a colour, as `#rrggbb`."""
    value = value.strip()
    if value.startswith("#"):
        return value
    r, g, b = (int(float(part)) for part in value[value.index("(") + 1:-1].split(",")[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def _drawn(sheet: str, selector: str, prop: str) -> str:
    """The colour `selector`'s first rule in `sheet` gives `prop`."""
    import re

    block = sheet.split(selector + " {", 1)[1].split("}", 1)[0]
    return _hex(re.search(r"(?:^|\s)" + prop + r":\s*([^;]+);", block).group(1))


_BUBBLES = ("msg-gen", "msg-crit", "msg-user", "msg-sys", "msg-sys-warn", "msg-sys-error")


def test_the_time_on_a_message_reads_on_every_bubble():
    """tcc#100: the time beside who spoke is 10 px on a TINTED bubble. In `faint` it came to
    3.4:1 on the Arbiter's own bubble — the one he reads to time a wait — against the 4.5:1 that
    finding 51 (tcc#65) set after his eyes strained. Computed from the colours the sheet draws, for
    every kind of bubble in both themes; and it stays quieter than the message itself."""
    from autosound_tcc.ui.tcc import theme

    for name in ("dark", "light"):
        palette = theme.get_theme(name)
        sheet = theme.build_qss(palette)
        stamp = _drawn(sheet, 'QLabel[class~="msg-time"]', "color")
        for kind in _BUBBLES:
            ground = _drawn(sheet, f'QFrame[class~="{kind}"]', "background")
            assert _contrast(stamp, ground) >= 4.5, (
                f"{name} {kind}: the time is {_contrast(stamp, ground):.2f}:1 on {ground}")
            assert _contrast(stamp, ground) < _contrast(palette.text, ground), (
                f"{name} {kind}: the time must stay quieter than the message")


def test_who_spoke_reads_on_every_bubble_and_never_quieter_than_the_time():
    """tcc#122 (W-4's review of tcc#100): the role is what the eye finds, the time is looked up
    when wanted — and on the Generator's bubble the time read brighter than the role beside it
    (`muted` 4.8:1 against the stamp's 5.5:1), while the light theme's Critic and System roles, in
    `info`, came to 3.2–3.5:1 against finding 51's 4.5. Each role at 4.5:1 or more and at least as
    strong as the time, on its own bubble, computed from the colours the sheet draws."""
    from autosound_tcc.ui.tcc import theme

    role = {"msg-gen": "msg-who", "msg-crit": "msg-who-crit", "msg-user": "msg-who-user",
            "msg-sys": "msg-who-sys", "msg-sys-warn": "msg-who-sys", "msg-sys-error": "msg-who-sys"}
    for name in ("dark", "light"):
        sheet = theme.build_qss(theme.get_theme(name))
        stamp = _drawn(sheet, 'QLabel[class~="msg-time"]', "color")
        for kind in _BUBBLES:
            ground = _drawn(sheet, f'QFrame[class~="{kind}"]', "background")
            who = _drawn(sheet, f'QLabel[class~="{role[kind]}"]', "color")
            said = f"{name} {kind}: the role {_contrast(who, ground):.2f}:1, the time " \
                   f"{_contrast(stamp, ground):.2f}:1 on {ground}"
            assert _contrast(who, ground) >= 4.5, said
            assert _contrast(who, ground) >= _contrast(stamp, ground), said


def test_every_label_in_the_info_blue_reads_on_what_it_sits_on():
    """tcc#122: the light theme's `info` as text came to 3.6–4.2:1 on its own panels — the status
    strip, the changed pills, the band ids, the protective marks — against finding 51's 4.5. Every
    rule of the sheet that draws text in `info` is checked on its own background where it has an
    opaque one, and on each of the panels where it does not, in both themes."""
    import re

    from autosound_tcc.ui.tcc import theme

    for name in ("dark", "light"):
        palette = theme.get_theme(name)
        sheet = theme.build_qss(palette)
        checked = 0
        for block in sheet.split("}"):
            if "{" not in block:
                continue
            selector, body = block.rsplit("{", 1)
            colour = re.search(r"(?:^|\s)color:\s*([^;]+);", body)
            if colour is None or _hex(colour.group(1)) != palette.info:
                continue
            ground = re.search(r"(?:^|\s)background:\s*([^;]+);", body)
            grounds = ([_hex(ground.group(1))] if ground and ground.group(1).startswith(("#", "rgb("))
                       else [palette.tokens[t] for t in ("ground", "panel", "panel2", "panel3")])
            for under in grounds:
                checked += 1
                assert _contrast(palette.info, under) >= 4.5, (
                    f"{name} {selector.split('*/')[-1].strip()}: "
                    f"{_contrast(palette.info, under):.2f}:1 on {under}")
        assert checked > 20, f"{name}: the sheet's info-blue labels were found ({checked})"


class _App:
    """What `apply_theme` asks of the application -- its palette and its sheet -- with the sheet
    writes counted. `setStyleSheet` on the real one re-polishes every widget of the process."""

    def __init__(self) -> None:
        from PySide6.QtGui import QPalette

        self._palette, self.sheet, self.sets = QPalette(), "", 0

    def palette(self):
        return self._palette

    def setPalette(self, palette) -> None:  # noqa: N802 (Qt's name)
        self._palette = palette

    def styleSheet(self) -> str:  # noqa: N802 (Qt's name)
        return self.sheet

    def setStyleSheet(self, sheet) -> None:  # noqa: N802 (Qt's name)
        self.sheet, self.sets = sheet, self.sets + 1


def test_a_sheet_taken_off_behind_its_back_is_put_back(monkeypatch):
    """tcc#123 (W-4 review, round 5 of the order fixes): `apply_theme` skipped the re-style when
    its own record said the sheet was on, whatever the application really had. A test that
    cleared the sheet left the record saying «applied», and the next window measured itself
    unstyled. The application's own sheet is what is compared now: the same sheet already on
    is not applied twice, and one taken off is put back."""
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc import theme

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(theme, "_CURRENT", theme._CURRENT)
    app = _App()

    theme.apply_theme(app, "dark")
    theme.apply_theme(app, "dark")
    assert app.sets == 1, "the identical sheet, already on, is not applied again"

    app.sheet = ""
    theme.apply_theme(app, "dark")
    assert app.sets == 2 and app.sheet == theme.build_qss(theme.get_theme("dark"))


def _drawn_picks(monkeypatch) -> list:
    """What every `MiniCombo` paints as its closed label, in order — the paint itself, spied, so
    what is checked is what is drawn rather than what a helper returns."""
    from autosound_tcc.ui.tcc import theme

    drawn = []

    class _Painter(theme.QStylePainter):
        def drawControl(self, element, option):  # noqa: N802 (Qt's name)
            drawn.append(option.currentText)
            super().drawControl(element, option)

    monkeypatch.setattr(theme, "QStylePainter", _Painter)
    return drawn


def _edit_field(box) -> int:
    """The style's edit field: under the app's sheet, the width the closed label is clipped to."""
    from PySide6.QtWidgets import QStyle, QStyleOptionComboBox

    option = QStyleOptionComboBox()
    box.initStyleOption(option)
    return box.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                      QStyle.SubControl.SC_ComboBoxEditField, box).width()


def _styled_mini_select(monkeypatch, stretch: int):
    """A `.mini-select` under the sheet the window applies (`_windows.theme_on`), its font
    `stretch`ed: the Mac's offscreen text, and about twice and four times as wide — the Windows
    runner's, as the compare box's tests are held."""
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc import theme
    from tests import _windows

    QApplication.instance() or QApplication([])
    combo = theme.mini_combo()
    _windows.theme_on(monkeypatch, combo, "dark")
    font = QFont(combo.font())
    font.setStretch(stretch)
    combo.setFont(font)
    return combo


@pytest.mark.parametrize("stretch", [100, 141, 200])
def test_a_mini_select_too_narrow_for_its_pick_says_so_with_an_ellipsis(monkeypatch, stretch):
    """Finding 132 (tcc#122): the footer's reviewer box read «API · gemini-3.1-pro-prev» on the
    Windows VM — cut mid-word, no «…», as though that were the model's name. The closed box draws
    its pick elided to its field, «…» where anything was cut, and whole where it fits; the open
    list keeps every row whole (`MiniCombo.showPopup`). What is checked is what the paint draws,
    against the style's edit field, under the app's stylesheet (VM-6: the first version ran
    without it, and the sheet draws the label across the whole field) — and whole the moment the
    field holds the pick's ink, since nothing short of that is clipped."""
    import math

    from PySide6.QtGui import QFontMetricsF
    from PySide6.QtWidgets import QComboBox

    drawn = _drawn_picks(monkeypatch)
    full = "API · gemini-3.1-pro-preview"
    combo = _styled_mini_select(monkeypatch, stretch)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(6)
    combo.addItem(full)
    metrics = QFontMetricsF(combo.font())
    whole = metrics.horizontalAdvance(full)
    for share in (0.35, 0.55, 0.8):
        combo.resize(int(whole * share) + combo.width() - _edit_field(combo), 26)
        combo.grab()
        shown = drawn[-1]
        assert shown.endswith("…") and full.startswith(shown[:-1]) and len(shown) > 1, (share, shown)
        assert metrics.horizontalAdvance(shown) <= _edit_field(combo), (
            share, shown, _edit_field(combo))
    ink = math.ceil(metrics.boundingRect(full).right())
    combo.resize(ink + combo.width() - _edit_field(combo), 26)
    combo.grab()
    assert drawn[-1] == full, f"whole in a field of its ink ({ink} px), which clips nothing"
    combo.resize(int(whole) + 80 + combo.width() - _edit_field(combo), 26)
    combo.grab()
    assert drawn[-1] == full, "whole where it fits"


@pytest.mark.parametrize("stretch", [100, 141, 200])
def test_a_mini_select_at_its_own_width_draws_every_row_whole(monkeypatch, stretch):
    """VM-6 (tcc#122, the Windows VM): the language box read «…» for EN and DE, and the effort box
    «x-hi…» where «x-high» fits — maximised or not, since a box sized to its rows does not grow.
    `fit_text` took the edit field less a pixel each side, the platform style's inset; the app's
    sheet draws the label across the whole field, and Qt sizes the box to its widest row's ink,
    so the widest rows lost their letters to two pixels nothing clips. Under the sheet the window
    applies, at the width each box gives itself (and its floor in the window), every row is
    drawn as it is."""
    from autosound_tcc.ui.tcc import i18n
    from autosound_tcc.core import model_choices

    drawn = _drawn_picks(monkeypatch)
    badges = [badge for _code, badge in i18n.language_badges()]
    efforts = [i18n.t(f"effort_{level}") for level in model_choices.EFFORT_LEVELS]
    for rows, floor in ((badges, 64), (efforts, 62)):  # `main_window`'s own floors for the two
        combo = _styled_mini_select(monkeypatch, stretch)
        for row in rows:
            combo.addItem(row)
        combo.setMinimumWidth(floor)
        combo.resize(combo.sizeHint().expandedTo(combo.minimumSize()))
        for index, row in enumerate(rows):
            combo.setCurrentIndex(index)
            combo.grab()
            assert drawn[-1] == row, (
                f"«{row}» drawn as «{drawn[-1]}» in a {combo.width()} px box, field "
                f"{_edit_field(combo)} px")


def test_a_hold_is_said_in_orange_that_reads_in_both_themes():
    """VM-5 (ruling 21, tcc#98): the line under omp and Claude Code while a session runs on them
    read red, like an error. The Arbiter: «не сірим - помаранчевим, бо це стопер але не помилка».
    Orange, then — and not the accent itself: as text the light accent reads 3.2–3.7:1 on these
    surfaces, under finding 51's 4.5. Computed from the colour the sheet draws, on every surface
    the line can sit on, in both themes."""
    import colorsys

    from autosound_tcc.ui.tcc import theme

    for name in ("dark", "light"):
        palette = theme.get_theme(name)
        drawn = _drawn(theme.build_qss(palette), 'QLabel[class~="kv-caution"]', "color")
        r, g, b = theme._to_rgb(drawn)
        hue = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)[0] * 360
        assert 20 <= hue <= 45, f"{name}: {drawn} is not orange (hue {hue:.0f}°)"
        assert drawn.lower() != palette.warn.lower(), f"{name}: the error's red"
        for surface in ("panel", "panel2", "panel3", "ground"):
            ground = palette.tokens[surface]
            assert _contrast(drawn, ground) >= 4.5, (
                f"{name}: {drawn} is {_contrast(drawn, ground):.2f}:1 on {surface} {ground}")
