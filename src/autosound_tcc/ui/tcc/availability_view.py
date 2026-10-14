"""Availability for people: one word for a picker row, one short phrase for the footer."""
from __future__ import annotations

from autosound_tcc.core import availability, codex_cli, model_choices
from autosound_tcc.ui.tcc import i18n

_WORDS = {
    availability.NOT_INSTALLED: "availNotInstalled",
    availability.TOO_OLD: "availTooOld",
    availability.SIGN_IN: "availSignIn",
    availability.LOCATION: "availLocation",
    availability.REFUSED: "availRefused",
    availability.NOT_CHECKED: "availNotChecked",
}
_PHRASES = {
    availability.NOT_INSTALLED: "availPhraseNotInstalled",
    availability.TOO_OLD: "availPhraseTooOld",
    availability.SIGN_IN: "availPhraseSignIn",
    availability.LOCATION: "availPhraseLocation",
    availability.REFUSED: "availPhraseRefused",
    availability.NOT_CHECKED: "availPhraseNotChecked",
}


def install_codex_line() -> str:
    """The menu line that installs TCC's own Codex, from the menu's own words — the one the launch
    blocker names (`codexTooOld`, `codexMissing`)."""
    return f"☰ → ⚙ {i18n.t('menuSettings')} → {i18n.t('codexInstall')}"


def word(state: availability.Status) -> str:
    if state.ready:
        return ""
    if state.reason == availability.TOO_OLD:
        # The version, and where TCC's own copy is installed from (tcc#181).
        return i18n.t("availTooOld").format(version=state.detail, line=install_codex_line())
    return i18n.t(_WORDS[state.reason])


def phrase(state: availability.Status) -> str:
    if state.ready:
        return ""
    return i18n.t(_PHRASES[state.reason]).format(version=state.detail) \
        if state.reason == availability.TOO_OLD else i18n.t(_PHRASES[state.reason])


def detail(state: availability.Status, choice) -> str:
    """What a tooltip says about a row that is not ready: a region refusal as a sentence naming the
    model, the route and — for agy — the rows known ready instead, with the CLI's own line under it
    (hub #262: «Selected model is not supported in the selected location» read as a failure, and
    the model that worked was found by hand). Otherwise the stored detail as it is."""
    if not state.ready and choice.harness == "codex":
        # Codex's own launch blockers say it in full (`session_routes.codex_blocker`).
        if state.reason == availability.TOO_OLD:
            return i18n.t("codexTooOld").format(
                version=state.detail, min=codex_cli.version_text(codex_cli.MIN_VERSION))
        if state.reason == availability.SIGN_IN:
            return i18n.t("codexSignedOut")
    if state.ready or state.reason != availability.LOCATION:
        return state.detail
    said = i18n.t("availRegionRefusal").format(model=choice.model, route=choice.route)
    if choice.harness == "agy":
        ready = [c.label or c.model for c in model_choices.agy_choices()
                 if c.key != choice.key and availability.status(c, reviewer=True).ready]
        if ready:
            said += " " + i18n.t("availRegionInstead").format(models=", ".join(ready))
    return f"{said}\n{state.detail}" if state.detail else said
