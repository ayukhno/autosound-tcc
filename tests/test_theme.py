

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


def test_the_time_on_a_message_reads_on_every_bubble():
    """tcc#100: the time beside who spoke is 10 px on a TINTED bubble. In `faint` it came to
    3.4:1 on the Arbiter's own bubble — the one he reads to time a wait — against the 4.5:1 that
    finding 51 (tcc#65) set after his eyes strained. Computed from the colours the sheet draws, for
    every kind of bubble in both themes; and it stays quieter than the message itself."""
    import re

    from autosound_tcc.ui.tcc import theme

    def drawn(sheet: str, selector: str, prop: str) -> str:
        block = sheet.split(selector + " {", 1)[1].split("}", 1)[0]
        value = re.search(prop + r":\s*([^;]+);", block).group(1).strip()
        if value.startswith("#"):
            return value
        r, g, b = (int(float(part)) for part in value[value.index("(") + 1:-1].split(",")[:3])
        return f"#{r:02x}{g:02x}{b:02x}"

    kinds = ("msg-gen", "msg-crit", "msg-user", "msg-sys", "msg-sys-warn", "msg-sys-error")
    for name in ("dark", "light"):
        palette = theme.get_theme(name)
        sheet = theme.build_qss(palette)
        stamp = drawn(sheet, 'QLabel[class~="msg-time"]', "color")
        for kind in kinds:
            ground = drawn(sheet, f'QFrame[class~="{kind}"]', "background")
            assert _contrast(stamp, ground) >= 4.5, (
                f"{name} {kind}: the time is {_contrast(stamp, ground):.2f}:1 on {ground}")
            assert _contrast(stamp, ground) < _contrast(palette.text, ground), (
                f"{name} {kind}: the time must stay quieter than the message")


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
