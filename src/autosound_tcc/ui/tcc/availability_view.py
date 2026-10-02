"""Availability for people: one word for a picker row, one short phrase for the footer."""
from __future__ import annotations

from autosound_tcc.core import availability
from autosound_tcc.ui.tcc import i18n

_WORDS = {
    availability.NOT_INSTALLED: "availNotInstalled",
    availability.SIGN_IN: "availSignIn",
    availability.LOCATION: "availLocation",
    availability.REFUSED: "availRefused",
    availability.NOT_CHECKED: "availNotChecked",
}
_PHRASES = {
    availability.NOT_INSTALLED: "availPhraseNotInstalled",
    availability.SIGN_IN: "availPhraseSignIn",
    availability.LOCATION: "availPhraseLocation",
    availability.REFUSED: "availPhraseRefused",
    availability.NOT_CHECKED: "availPhraseNotChecked",
}


def word(state: availability.Status) -> str:
    return "" if state.ready else i18n.t(_WORDS[state.reason])


def phrase(state: availability.Status) -> str:
    return "" if state.ready else i18n.t(_PHRASES[state.reason])
