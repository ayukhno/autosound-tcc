

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
