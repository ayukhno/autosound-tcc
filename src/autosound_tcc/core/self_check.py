"""What TCC can tell the Arbiter about TCC's own setup — and which of it TCC may repair.

Diagnostics used to render one thing: `contract.py check`, the skill's verdict on the PROJECT's
machine files. That left a whole class of problem with nowhere to appear. A model alias written
weeks ago silently redirects every reviewer call; an installed CLI whose catalogue came back empty
takes a whole route out of the pickers. Both are TCC's own state, neither is wrong with the
project, and the only place either surfaced was in a file the Arbiter has no reason to open
(found by audit, 2026-08-12: three aliases pointing every Gemini reviewer at the Generator's own
model, written by a dialog that has no undo).

**What may carry a Fix button, and what may not.** The rule is D-6, unchanged: the skill writes the
project, TCC reads it. So a check may repair only what TCC itself owns — its config directory, its
caches, its settings. For anything under the project, diagnostics NAMES THE COMMAND and stops; the
skill's own refusals already work that way, and a button here that edited `project.json` would make
two writers of a file with one owner.

The second rule is narrower and comes from the same place: a fix must be *deterministic*. "Remove
this alias" is one outcome. "Repair the ledger" is a judgement, and a judgement behind a button is
a judgement nobody made.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from autosound_tcc.core import config, critic, model_choices, model_overrides, project_settings

#: Severity, in the same vocabulary the traffic lights already use.
BAD = "bad"
WARN = "wait"
OK = "done"


@dataclass(frozen=True)
class Check:
    """One thing TCC knows about its own setup.

    `fix` is present only when the repair is TCC's to make and has exactly one outcome. `detail`
    is what the Arbiter needs in order to decide, not a restatement of the title.
    """

    id: str
    status: str
    title: str
    detail: str = ""
    fix_label: str = ""
    fix: Optional[Callable[[], str]] = field(default=None, compare=False)

    @property
    def fixable(self) -> bool:
        return self.fix is not None


def _alias_check() -> Check:
    """Every model alias in force, and an offer to drop them.

    An alias is written by the "model gone" dialog and applied by `resolve()` unconditionally and
    forever. That is right while the model really is gone and wrong the moment it comes back — and
    nothing noticed the difference, because the only record is a JSON file nobody opens. Aliases
    that point a reviewer at the Generator's own vendor are called out separately: that is not a
    substitution, it is the end of cross-vendor review.
    """
    aliases = model_overrides.load().get("aliases") or {}
    if not aliases:
        # Says only what it knows. It used to say "every picker runs what it says", which a live
        # session disproved the same night (2026-08-12): the reviewer script ALSO substitutes, one
        # layer below TCC — Gemini API answered 404 and it fell back to the local `agy` CLI, which
        # runs whatever model `agy` is currently set to. No alias was involved, and nothing in
        # TCC's config could have shown it. An assurance that reaches further than the evidence is
        # worse than no assurance: it is the one a reader stops checking.
        return Check("aliases", OK, _t("selfAliasNoneTitle"), _t("selfAliasNoneDetail"))

    known = model_choices.choices([]) + model_choices.critic_choices([])
    lines, collapsing, spelling = [], [], []
    for from_key, entry in sorted(aliases.items()):
        to_key = str((entry or {}).get("to") or "")
        lines.append(f"{from_key} → {to_key}" + (f"  ({entry.get('why')})" if entry.get("why") else ""))
        if _harness_only(from_key, to_key):
            # `claude-opus-5 → sdk:claude-opus-5`: one model, written twice. Reading that as a
            # vendor collapse is what the check used to do -- a bare key has no harness, so the
            # fallback Choice below gave it an empty provider, which differs from every real one.
            # It painted the app's own red dot over a correction (user, 2026-08-23: "what is
            # that, and is it worth removing?").
            spelling.append(from_key)
            continue
        source = model_choices.find(known, from_key) or model_choices.Choice(
            harness=from_key.partition(":")[0], model=from_key.partition(":")[2], label=from_key,
            provider="",
        )
        target = model_choices.find(known, to_key)
        if target is not None and model_choices.vendor_of(source) != model_choices.vendor_of(target):
            collapsing.append(from_key)

    detail = "\n".join(lines)
    if collapsing:
        detail += "\n\n" + _t("selfAliasCrossVendor").format(keys=", ".join(collapsing))
    if spelling:
        detail += "\n\n" + _t("selfAliasSameModel").format(keys=", ".join(spelling))
    return Check(
        "aliases",
        BAD if collapsing else WARN,
        _t("selfAliasTitle").format(n=len(aliases)),
        detail,
        fix_label=_t("selfAliasFix"),
        fix=_clear_all_aliases,
    )


def _harness_only(from_key: str, to_key: str) -> bool:
    """Do these two keys name the same MODEL, differing only in the harness that runs it?

    `claude-opus-5` and `sdk:claude-opus-5` are one model said two ways -- the second says which
    harness starts it. An alias between them substitutes nothing; it repairs a name that was
    written without its prefix. Worth listing, because an indirection is a fact about the record,
    and not worth the sentence about cross-vendor review, which is about a different thing
    entirely.

    Not called `_same_model`: there is one of those already, further down, comparing a picker key
    against a name a reviewer script recorded, loosely, on letters and digits. Two functions of
    that name in one module is a bug waiting for whoever adds the third caller.
    """
    def model(key: str) -> str:
        return key.split(":", 1)[1] if ":" in key else key

    return bool(from_key) and bool(to_key) and model(from_key) == model(to_key)


def _clear_all_aliases() -> str:
    data = model_overrides.load()
    removed = sorted(data.get("aliases") or {})
    for key in removed:
        model_overrides.clear_alias(key)
    return _t("selfAliasFixed").format(n=len(removed))


def _catalogue_check() -> Check:
    """A CLI that is installed and told us nothing.

    Worth a row of its own because the consequence is invisible: the route simply is not in the
    picker, which reads exactly like "not installed" — and that is what wrote the aliases above.
    """
    silent = model_choices.cli_routes_without_models()
    if not silent:
        return Check("catalogue", OK, _t("selfCatalogueOkTitle"))
    return Check(
        "catalogue",
        WARN,
        _t("selfCatalogueTitle").format(clis=", ".join(silent)),
        _t("selfCatalogueDetail"),
        fix_label=_t("selfCatalogueFix"),
        fix=_refresh_catalogue,
    )


def _refresh_catalogue() -> str:
    """Ask the CLIs again. Slow (it fetches over the network), which is why it is a button and not
    something diagnostics does while you are reading it."""
    fetched = model_choices.refresh_cli_catalogue()
    total = sum(len(entries) for entries in fetched.values())
    return _t("selfCatalogueFixed").format(n=total)


def _pin_check() -> Check:
    """The vendored method sitting on an older release than the newest tag we know of (F-029).

    The pin itself is right and stays: a live link to the method's `main` would hand the app a
    deliberately unstable line, make a red suite unattributable (ours or theirs?), and break
    reproducibility for anyone cloning this public repo. What was missing is that **nobody says
    the pin has fallen behind** — it sat on v3.0.11 while the method already had v3.0.12 with a
    changed `align_delay_polarity` contract, and that was noticed only by bumping it by hand. The
    cockpit has been running this check for us every day since.

    **Two deliberate departures from how F-029 was written on 2026-08-22, both because the rule
    changed under it.** It said "N commits behind `main`" with `git submodule update --remote`.
    Since then the pin follows TAGS, so:

    * behind `main` is the NORMAL state between releases — a row that is always on is not a
      warning, it is furniture. The question worth asking is whether a released TAG went by.
    * `--remote` moves to the branch tip, which is exactly what we do not want. The command named
      here checks out the tag.

    No network, ever: it reads the tags this checkout already has. That makes an OK answer a
    LOCAL one, and the title says so rather than implying the internet was asked — the honest
    version of a check that cannot see everything. F-029's own rule, kept: never BAD, never
    blocking, and silence when there is nothing to compare.

    Only for a checkout with the submodule. An installed skill is the update row's business
    (`updates.check_skill`), and two rows saying the same thing in different words is worse than
    one.
    """
    from autosound_tcc.core import updates, vendor_loader

    repo = vendor_loader.skill_repo_root()
    if repo is None:
        return Check("pin", OK, _t("selfPinOkTitle"))
    inside, parent = updates._git("rev-parse", "--show-superproject-working-tree", cwd=repo)
    if not (inside and parent):
        # Not our submodule: an installed skill, or somebody's own checkout. Not this row's job.
        return Check("pin", OK, _t("selfPinOkTitle"))
    ok, head = updates._git("rev-parse", "HEAD", cwd=repo)
    if not ok or not head:
        return Check("pin", OK, _t("selfPinOkTitle"))
    listed, tags = updates._git(
        "for-each-ref", "--sort=-v:refname", "--format=%(refname:short)",
        f"refs/tags/{updates.SKILL_TAG_GLOB}", cwd=repo)
    newest = tags.splitlines()[0].strip() if listed and tags.strip() else ""
    if not newest:
        return Check("pin", OK, _t("selfPinOkTitle"))
    resolved, tag_sha = updates._git("rev-parse", f"{newest}^{{commit}}", cwd=repo)
    if not resolved or tag_sha == head:
        return Check("pin", OK, _t("selfPinAtTitle").format(tag=newest))
    counted, behind = updates._git("rev-list", "--count", f"HEAD..{newest}", cwd=repo)
    if not counted or not behind.isdigit() or int(behind) == 0:
        # Ahead of the newest tag, or unrelated history: a developer running in front of the
        # releases is not out of date, and telling them to check out backwards would be wrong.
        return Check("pin", OK, _t("selfPinAtTitle").format(tag=newest))
    return Check(
        "pin",
        WARN,
        _t("selfPinBehindTitle").format(tag=newest, n=behind),
        _t("selfPinBehindDetail").format(tag=newest),
    )


def _reviewer_actual_check() -> Check:
    """Who answered last, against who was asked for.

    The one comparison that survives the layer below. `reviewer.substituted` was empty and
    `reviewer.model` said `gemini-3.1-pro-high` while `gemini-3.6-flash-high` was doing the
    reviewing — because the substitution happened inside the reviewer script's own API→CLI
    fallback, which no flag in TCC records. Both halves of this comparison are already on disk;
    nothing compared them (live session, 2026-08-12: "the only reliable check is to make a call").
    """
    entry = critic.last_call() or {}
    answered = str(entry.get("model") or "").strip()
    if not answered or entry.get("mode") != "answered":
        return Check("reviewer_actual", OK, _t("selfReviewerNeverTitle"), _t("selfReviewerNeverDetail"))
    wanted_key = project_settings.get(config.tcc_dir(), "critic", "") or ""
    wanted = wanted_key.partition(":")[2] or wanted_key
    if not wanted or _same_model(wanted, answered):
        return Check("reviewer_actual", OK, _t("selfReviewerOkTitle").format(model=answered))
    return Check(
        "reviewer_actual",
        BAD,
        _t("selfReviewerDiffTitle"),
        _t("selfReviewerDiffDetail").format(wanted=wanted or "?", answered=answered),
    )


def reviewer_mismatch() -> Optional[tuple[str, str]]:
    """`(asked_for, answered)` when the last review came back from another model, else None.

    Exposed on its own because the footer needs the same fact the diagnostics row states, and two
    implementations of "did the reviewer change" would eventually disagree about it.
    """
    check = _reviewer_actual_check()
    if check.status == OK:
        return None
    entry = critic.last_call() or {}
    wanted_key = project_settings.get(config.tcc_dir(), "critic", "") or ""
    return (wanted_key.partition(":")[2] or wanted_key, str(entry.get("model") or "?"))


def _same_model(wanted: str, answered: str) -> bool:
    """Loose on purpose: the picker's key and the script's recorded name are two spellings of one
    model (`gemini-3.1-pro-high` vs `Gemini 3.1 Pro (High)`). Compare on the letters and digits."""
    strip = lambda text: "".join(ch for ch in text.lower() if ch.isalnum())  # noqa: E731
    a, b = strip(wanted), strip(answered)
    return a in b or b in a


def _recommendation_check() -> Check:
    """Does the recommended pair still name anything this machine can run.

    The recommendation is a CLASS now — Opus-class generator, Pro-class reviewer — so it survives
    a version bump on its own. It will not survive the classes themselves retiring, and that day
    has to be loud: a recommendation matching nothing looks exactly like no recommendation, which
    is the failure the class scheme was adopted to prevent rather than to postpone.
    """
    entries = model_choices.choices([]) + model_choices.critic_choices([])
    missing = [
        role for role, critic in (("generator", False), ("critic", True))
        if not model_choices.recommendation_available(entries, critic=critic)
    ]
    if not missing:
        return Check("recommendation", OK, _t("selfRecommendOkTitle"))
    pairs = ", ".join(
        f"{vendor} {tier}" for role, (vendor, tier) in model_choices.RECOMMENDED.items()
        if role in missing
    )
    return Check(
        "recommendation",
        WARN,
        _t("selfRecommendTitle").format(roles=", ".join(missing)),
        _t("selfRecommendDetail").format(pairs=pairs, since=model_choices.RECOMMENDED_SINCE),
    )


def run() -> list[Check]:
    """Every self-check, worst first. Never raises: a diagnostics panel that crashes is worse than
    one that is missing a row."""
    checks = []
    for probe in (_alias_check, _catalogue_check, _pin_check, _reviewer_actual_check,
                  _recommendation_check):
        try:
            checks.append(probe())
        except Exception as exc:  # noqa: BLE001 — a broken probe is a row, not a dead dialog
            checks.append(Check(probe.__name__, WARN, _t("selfCheckFailed"), str(exc)))
    order = {BAD: 0, WARN: 1, OK: 2}
    return sorted(checks, key=lambda c: order.get(c.status, 1))


def _t(key: str) -> str:
    """i18n, imported late. This module is core, not ui, and is imported by tests that never build
    a QApplication — but the strings belong in one table with the rest of the app's."""
    from autosound_tcc.ui.tcc import i18n

    return i18n.t(key)
