"""Every language carries the same keys, with the same placeholders.

The UI ships four languages (2026-08-25) and nobody reads three of them while working. That is
exactly the condition under which a translation rots quietly, so the guarantees a person would
otherwise have to notice by eye are asserted here instead:

* a MISSING key falls back to English (`t()` does that on purpose) and looks like a translation
  nobody got to — invisible until a Polish user reads a German-shaped sentence in English;
* a missing PLACEHOLDER is worse than missing text: `t("staleStrip").format(...)` then renders a
  sentence with the number silently absent, and the reader has no way to tell;
* an EXTRA placeholder is a crash. `str.format` raises `KeyError` for a name the caller did not
  pass, in one language, on one screen, on somebody else's machine.
"""

from autosound_tcc.ui.tcc import i18n

import re

import pytest

_PLACEHOLDER = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")

_LANGS = [code for code, _key, _badge in i18n.LANGS]


def test_langs_and_tables_name_the_same_languages():
    """`LANGS` drives the window; `T` holds the words. A language in one and not the other is
    either a table nothing offers or a menu item with no strings behind it."""
    assert sorted(_LANGS) == sorted(i18n.T)


@pytest.mark.parametrize("lang", _LANGS)
def test_every_language_has_every_key(lang):
    english = set(i18n.T["en"])
    assert set(i18n.T[lang]) == english, {
        "missing": sorted(english - set(i18n.T[lang])),
        "unknown": sorted(set(i18n.T[lang]) - english),
    }


@pytest.mark.parametrize("lang", [code for code in _LANGS if code != "en"])
def test_placeholders_survive_translation(lang):
    wrong = {}
    for key, english in i18n.T["en"].items():
        want = sorted(set(_PLACEHOLDER.findall(english)))
        got = sorted(set(_PLACEHOLDER.findall(i18n.T[lang][key])))
        if want != got:
            wrong[key] = {"en": want, lang: got}
    assert not wrong, wrong


@pytest.mark.parametrize("lang", [code for code in _LANGS if code != "en"])
def test_line_breaks_survive_translation(lang):
    """Seven strings put a blank line between a question and its detail, and one puts the command
    to run on its own line. They lost their newlines on the way into this file, not in the
    translating: the splice that added Polish and German wrapped long values with `textwrap.wrap`,
    which collapses whitespace, and `\n\n` came out as two spaces. Nothing failed — the dialogs
    just quietly became one paragraph, in the two languages nobody here reads.
    """
    wrong = [key for key, english in i18n.T["en"].items()
             if ("\n" in english) != ("\n" in i18n.T[lang][key])]
    assert not wrong, wrong


@pytest.mark.parametrize("lang", [code for code in _LANGS if code != "en"])
def test_nothing_translated_to_nothing(lang):
    """An empty translation reads as a blank label, not as a fallback: `t()` returns the empty
    string it found rather than the English behind it."""
    blank = [key for key, english in i18n.T["en"].items()
             if english.strip() and not i18n.T[lang][key].strip()]
    assert not blank, blank


def test_language_choices_are_named_in_the_current_language():
    before = i18n.current_language()
    try:
        i18n.set_language("de")
        assert i18n.language_choices() == [("en", "auf Englisch"), ("uk", "auf Ukrainisch"),
                                           ("pl", "auf Polnisch"), ("de", "auf Deutsch")]
        # The one that goes into `npOnboardingHint`: "Führe das Interview auf Deutsch."
        assert i18n.language_name() == "auf Deutsch"
        assert i18n.language_name("pl") == "auf Polnisch"
    finally:
        i18n.set_language(before)


def test_language_badges_are_the_header_combos_items():
    assert i18n.language_badges() == [("en", "EN"), ("uk", "УК"), ("pl", "PL"), ("de", "DE")]


#: Model names TCC writes into ARGUMENTS, not into sentences. A UI string that spells one out is a
#: translation job every time a generation ships: `gemini-2.5-pro` stood in four languages, and
#: three of them are read by nobody working here.
_MODEL_NAMES = ("gemini-2.5-pro", "claude-opus-5", "gemini-3.1-pro-preview")


@pytest.mark.parametrize("lang", _LANGS)
def test_no_ui_string_spells_out_a_model_name(lang):
    named = {key: value for key, value in i18n.T[lang].items()
             if any(name in value for name in _MODEL_NAMES)}
    assert not named, named


def test_every_shipped_language_has_a_name_a_model_understands():
    """TCC tells the model which language to answer in, and it passes a NAME, not a code. With
    only `en` and `uk` in the table, `language_name("pl")` answered "pl" — so a Polish Arbiter got
    a session told to reply in "pl", which is not a language, from a UI that ships Polish
    (SKL-027). The break this catches is adding a fifth language to the UI and forgetting this
    table: the codes come from `i18n.LANGS`, so it fails on its own."""
    from autosound_tcc.core import agent_session

    for code in _LANGS:
        name = agent_session.language_name(code)
        assert name != code, f"{code!r} has no name — the model would be told to answer in {code!r}"
        assert name.isascii() and name[:1].isupper(), name


#: Button labels that must stay SHORT. A menu row grows to fit a sentence; a QMessageBox button
#: does not — on Windows it clips, and the person is left choosing between "on't ask at all (aut"
#: and "nly what the skill does not ow" (user's screenshot, 2026-09-09). The limit is generous:
#: German is the longest of the four and "Außerhalb des Projekts" is 22.
_BUTTON_KEYS = ("gateAskNever", "gateAskForeign", "gateAskWrites")
_BUTTON_MAX = 26


@pytest.mark.parametrize("key", _BUTTON_KEYS)
def test_a_button_label_stays_short_in_every_language(key):
    """The break this catches: somebody reuses a menu string on a button, in any of four
    languages, and it is only visible on a platform nobody develops on."""
    for code in _LANGS:
        label = i18n.T[code].get(key) or i18n.T["en"][key]
        assert len(label) <= _BUTTON_MAX, f"{code}/{key}: {label!r} is {len(label)} chars"


def test_every_language_the_window_offers_has_a_name_for_the_model():
    """`agent_session.LANGUAGE_NAMES` claims in its own comment that this test exists and fails
    when a fifth language is added to `i18n.LANGS` and forgotten there. It did not exist — found
    while giving the tuning session the same language rule the interview has (2026-09-11).

    A code is not an instruction: the table turns "uk" into "Ukrainian", and a language present in
    the switch but missing here reaches the model as two letters it cannot act on."""
    from autosound_tcc.core.agent_session import LANGUAGE_NAMES, language_name

    assert sorted(LANGUAGE_NAMES) == sorted(_LANGS)
    for code in _LANGS:
        assert language_name(code) != code, f"{code} reaches the model as a bare code"


@pytest.mark.parametrize("key", _BUTTON_KEYS)
def test_a_button_is_wide_enough_for_its_label_in_every_language(key):
    """The character guard above was satisfied and the label clipped anyway.

    `_BUTTON_MAX` is 26; "Поза проєктом" is 13 — and it rendered as "Іоза проєктом" on macOS, the
    first letter eaten (Arbiter's screenshot, 2026-09-11). The same class had already been "fixed"
    once by shortening the sentences, after Windows clipped them (2026-09-09). Counting characters
    cannot catch it: what clips is RENDERED WIDTH, which is a font, a platform and a language.

    So this measures pixels, the way the permission bar's test measures colour.
    """
    from PySide6.QtWidgets import QApplication, QPushButton

    from autosound_tcc.ui.tcc import sizing

    QApplication.instance() or QApplication([])
    for code in _LANGS:
        label = i18n.T[code].get(key) or i18n.T["en"][key]
        button = QPushButton(label)
        sizing.fit_to_text(button)

        needed = button.fontMetrics().horizontalAdvance(label)
        assert button.minimumWidth() >= needed, (
            f"{code}/{key}: {label!r} needs {needed}px and the button offers "
            f"{button.minimumWidth()}px — that is the clipping, not a style choice")
