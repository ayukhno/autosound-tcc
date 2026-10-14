"""Availability for people: one word for a picker row, one short phrase for the footer."""
from __future__ import annotations

from autosound_tcc.core import availability, model_choices
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


def detail(state: availability.Status, choice) -> str:
    """What a tooltip says about a row that is not ready: a region refusal as a sentence naming the
    model, the route and — for agy — the rows known ready instead, with the CLI's own line under it
    (hub #262: «Selected model is not supported in the selected location» read as a failure, and
    the model that worked was found by hand). Otherwise the stored detail as it is."""
    if state.ready or state.reason != availability.LOCATION:
        return state.detail
    said = i18n.t("availRegionRefusal").format(model=choice.model, route=choice.route)
    if choice.harness == "agy":
        ready = [c.label or c.model for c in model_choices.agy_choices()
                 if c.key != choice.key and availability.status(c, reviewer=True).ready]
        if ready:
            said += " " + i18n.t("availRegionInstead").format(models=", ".join(ready))
    return f"{said}\n{state.detail}" if state.detail else said
