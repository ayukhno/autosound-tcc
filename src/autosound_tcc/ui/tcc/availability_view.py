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


def mark_missing(combo, entries, warn: bool = False, reviewer: bool = False,
                 ok: bool = False, refused: bool = False) -> None:
    """Red when the current choice is not among `entries`, plain when it is.

    Recomputed on every selection change, not only when the list is rebuilt. It was set once at
    fill time, so a combo that had ever been red STAYED red through every later pick — the Arbiter
    chose a model that exists and the field went on claiming it did not (user, 2026-08-12).

    `warn` is the other tint — the choice exists but is not what it appears to be — and it is
    passed in rather than applied by the caller afterwards because both write the same `class`
    property: whoever wrote second used to erase the other's answer. `ok` is the green the main
    AI's check gives a pick its route lists for this login (tcc#222), never over red or a warning;
    `refused` is that check's red — a pick the login does not list, or a signed-out route.
    """
    current = str(combo.currentData() or "")
    # A route whose CLI is not installed counts as missing here, even though its row is now on the
    # list (greyed, saying what it needs). The row exists so the option is discoverable; the field
    # still has to say that what it currently holds cannot run.
    #
    # And so does a choice this launch saw REFUSED — by region, a missing sign-in, a refused call
    # (finding 20: red in the open list, plain in the closed picker that is on screen all the
    # time). "Not checked yet" is not a refusal and does not turn it red.
    def runs(choice) -> bool:
        state = availability.status(choice, reviewer=reviewer)
        return choice.available and (state.ready or state.reason == availability.NOT_CHECKED)

    missing = refused or (bool(current) and not any(
        choice.key == current and runs(choice) for choice in entries))
    classes = "mini-select" + (" is-missing" if missing else "") + (" is-warn" if warn else "")
    if ok and not (missing or warn):
        classes += " is-ok"
    combo.setProperty("class", classes)
    combo.style().unpolish(combo)
    combo.style().polish(combo)
