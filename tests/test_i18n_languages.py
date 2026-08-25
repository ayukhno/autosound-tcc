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
