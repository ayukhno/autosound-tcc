"""What the two model pickers decide, without a window: which row each shows, which stored key is
gone, what the reviewer pick's «!» says, and what is offered instead.

Out of `main_window` (the structure ratchet, G13): these were window methods pinned by full-window
tests, and the AI-picks group (tcc#165, #196, #182) changed every one of them. Words for people stay
in the window: a note here is an i18n KEY and its arguments, translated there.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from autosound_tcc.core import availability, claude_sdk, model_choices, model_overrides
from autosound_tcc.core.model_choices import Choice


@dataclass(frozen=True)
class Note:
    """One thing the «!» says: `note` and `tip` are i18n keys formatted with `args`; `text` is a
    ready tip (the substitution's own clause) used when `tip` is empty."""

    note: str
    tip: str = ""
    args: dict = field(default_factory=dict)
    text: str = ""
    hard: bool = False


def chosen(entries: list, key: str) -> Optional[Choice]:
    """What `key` runs: its own row when one is on offer, else what an alias sends it to.

    A row picked by name runs itself; an alias is for a key nothing offers. An old alias sent
    Sonnet's row to the model already running — no restart, nothing said (finding 156)."""
    key = str(key or "")
    return model_choices.find(entries, key) or model_choices.resolve(entries, key).choice


def restart_offered(running: Optional[str], choice: Optional[Choice]) -> bool:
    """Whether a running session should be offered a restart onto `choice`."""
    return choice is not None and running not in (None, choice.key)


def replacements_for(key: str, entries: list) -> list:
    """`entries`, ordered so the sensible stand-ins for `key` come first.

    Same vendor first (user, 2026-08-11). A replacement is meant to be the nearest thing that
    still runs, and the list is alphabetical by route otherwise — so the default selection was
    whatever happened to sort first. That is how a Gemini reviewer became a Claude one, which is
    not a replacement at all: it is the end of cross-vendor review, chosen by a combo box.
    """
    wanted = key.partition(":")[2] or key
    marker = next(
        (vendor for token, vendor in model_choices._CRITIC_VENDOR_MARKERS if token in wanted.lower()),
        "",
    )
    if not marker:
        return list(entries)
    same = [c for c in entries if model_choices.vendor_of(c) == marker]
    other = [c for c in entries if model_choices.vendor_of(c) != marker]
    return same + other


@dataclass(frozen=True)
class PickerPlan:
    """What `_reload_model_choices` does: the Generator key to show, a setting to rewrite (with the
    old and new key, said on the status line), and the stored keys to offer a replacement for."""

    generator_shown: str
    honoured: Optional[tuple[str, str]] = None
    offers: tuple = ()


def plan_pickers(generator_entries: list, critic_entries: list, generator: str,
                 critic: str) -> PickerPlan:
    """Decide the pickers' fill from the project's two settings.

    * A Generator key an alias maps elsewhere, now on offer again: the old «gone» dialog wrote that
      alias for this project's own pick, and the picker ran the target. Offered again, the row
      would silently run the gone model and undo the accepted switch (157's own machine) — so the
      setting takes the target, once, and the status line says so.
    * A Generator key nothing offers, mapped to one that is: shown as the model that runs.
    * A key that runs nothing: offered a replacement — but not while its route's list is still
      being read, when a missing row means «not read yet», not «gone» (157 was likely offered from
      an incomplete startup list)."""
    generator, critic = str(generator or ""), str(critic or "")
    shown, honoured = generator, None
    if generator and model_choices.find(generator_entries, generator) is not None:
        target, alias = model_overrides.resolve_key(generator)
        if alias is not None and target != generator and \
                model_choices.find(generator_entries, target) is not None:
            shown, honoured = target, (generator, target)
    elif generator:
        resolved = model_choices.resolve(generator_entries, generator)
        shown = resolved.choice.key if resolved.ok else generator
    offers = tuple(
        (setting, key, entries)
        for setting, key, entries in (("generator", generator, generator_entries),
                                      ("critic", critic, critic_entries))
        if key and chosen(entries, key) is None
        and not availability.being_read(key.partition(":")[0])
    )
    return PickerPlan(shown, honoured, offers)


def sdk_login_note(choice: Optional[Choice], reviewer: bool = False) -> Optional[Note]:
    """"You picked Claude and this machine has no Claude login", or None.

    Only for a `False` from `signed_in()`. `None` means the probe could not tell (no CLI to ask, a
    timeout, output we do not recognise) and must stay silent: sending somebody to redo a login
    that was fine is a worse error than saying nothing. A reviewer's `claude -p` runs without
    `ANTHROPIC_API_KEY` (tcc#127): only the login counts there."""
    if choice is None or getattr(choice, "harness", "") != "sdk":
        return None
    if claude_sdk.signed_in(reviewer=reviewer) is not False:
        return None
    return Note("sdkNoLogin", "sdkNoLoginTip", {"cmd": claude_sdk.LOGIN_HINT}, hard=True)


def reviewer_on_a_signed_in_route(choice: Choice) -> Optional[tuple[Choice, bool]]:
    """For an API reviewer pick nothing here can call, the same vendor's model on an installed CLI,
    and whether that CLI's sign-in was checked (it answered this launch); None otherwise (hub #262).

    The pick was `api:gemini-3.1-pro-preview` on a machine that reaches Gemini only through agy
    signed in by Google Cloud's ADC: TCC asked for `GEMINI_API_KEY` and never said agy answers.
    Under ADC the model is the method's own (`ADC_REVIEWER`); otherwise the recommended reviewer
    the CLI lists, else its first row. A row refused this launch — by region, by the CLI — is not
    offered: it is the one thing known not to work (the group review)."""
    if choice.harness != "api" or model_choices.critic_reaches(choice):
        return None  # the API route is the one that needs a key; the CLIs have their own sign-in
    vendor = model_choices.vendor_of(choice)
    if not vendor:
        return None
    offered = [c for c in model_choices.agy_choices() + model_choices.codex_choices()
               if c.available and c.key != choice.key and model_choices.vendor_of(c) == vendor
               and model_choices.critic_reaches(c)
               and availability.status(c, reviewer=True).reason not in (availability.LOCATION,
                                                                         availability.REFUSED)]
    pick = (next((c for c in offered if model_choices._adc_reviewer(c)), None)
            or next((c for c in offered if model_choices.recommended(c, critic=True)), None)
            or (offered[0] if offered else None))
    return (pick, availability.answered(pick.key)) if pick is not None else None


def critic_notes(key: str, entries: list, generator: Optional[Choice],
                 mismatch: Optional[tuple] = None) -> tuple[list[Note], Optional[Choice]]:
    """What is wrong with the reviewer pick `key`, and the model offered instead (or None).

    * **Substituted** — the stored key is aliased on this machine, so the model that answers is
      not the one named (it is in `get_tcc_state` as `substituted`).
    * **Answered by another model** (`mismatch`) — the only condition backed by evidence rather
      than configuration: the script fell back and another model did the reviewing (2026-08-12).
    * **No transport** — the reviewer script cannot call it; the first sign of that used to be a
      package where a critique should have been (2026-08-23). The same vendor on an installed CLI
      is named, and the «!»'s box takes it in one click (hub #262).
    * **Same vendor as the Generator** — it reviews, but cross-vendor anti-anchoring is the
      reason the reviewer is another vendor (SCR-041).
    """
    resolved = model_choices.resolve(entries, key)
    notes: list[Note] = []
    instead = None
    if resolved.note:
        notes.append(Note("criticSubstituted", text=resolved.note))
    if mismatch:
        notes.append(Note("criticAnswered", "selfReviewerDiffDetail",
                          {"model": mismatch[1], "wanted": mismatch[0], "answered": mismatch[1]}))
    picked = resolved.choice
    for_reach = picked or Choice(harness=key.partition(":")[0] or "omp",
                                 model=key.partition(":")[2] or key, label=key, provider="")
    why_not = model_choices.not_a_reviewer(for_reach, generator=generator) if key else ""
    if why_not == model_choices.NOT_A_REVIEWER_SELF:
        notes.append(Note("criticRowSelf", "criticSelfTip", hard=True))
    elif why_not == model_choices.NOT_A_REVIEWER_OMP:
        # Not "clipboard only": nothing is called at all until the method goes through omp.
        notes.append(Note("criticRowViaOmp", "criticViaOmpTip", hard=True))
    elif key and not model_choices.critic_reaches(for_reach):
        vendor = model_choices.vendor_of(for_reach)
        found = reviewer_on_a_signed_in_route(for_reach)
        if found is not None:
            instead, checked = found
            notes.append(Note("criticClipboardOnly",
                              "criticSignedInRoute" if checked else "criticInstalledRoute",
                              {"model": for_reach.model,
                               "instead": f"{instead.route} · {instead.label}"}, hard=True))
        else:
            notes.append(Note("criticClipboardOnly",
                              "criticClipboardOnlyTip" if vendor else "criticUnknownVendorTip",
                              {"model": for_reach.model, "vendor": vendor}, hard=True))
    if key and not why_not and model_choices.reviewer_caution(for_reach):
        # Picked, and it reviews: the method advises a Pro tier, the choice is the Arbiter's
        # (finding 129, tcc#118). A warning, so not `hard`; a refused pick has its refusal.
        notes.append(Note("criticRowNotRecommended", "criticNotFlashTip"))
    if picked is not None and generator is not None and why_not != model_choices.NOT_A_REVIEWER_SELF:
        # `vendor_of`, not `critic_vendor`: the latter falls back to google for a name it does not
        # recognise, which would make any two unknown models look like a matched pair.
        vendor = model_choices.vendor_of(picked)
        if vendor and vendor == model_choices.vendor_of(generator):
            notes.append(Note("criticSameVendor", "criticSameVendorTip", {"vendor": vendor}))
    login = sdk_login_note(picked, reviewer=True)
    if login is not None:
        notes.append(login)
    return notes, instead
