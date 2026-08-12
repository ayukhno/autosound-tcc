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

from autosound_tcc.core import model_choices, model_overrides

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
        return Check("aliases", OK, _t("selfAliasNoneTitle"), _t("selfAliasNoneDetail"))

    known = model_choices.choices([]) + model_choices.critic_choices([])
    lines, collapsing = [], []
    for from_key, entry in sorted(aliases.items()):
        to_key = str((entry or {}).get("to") or "")
        lines.append(f"{from_key} → {to_key}" + (f"  ({entry.get('why')})" if entry.get("why") else ""))
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
    return Check(
        "aliases",
        BAD if collapsing else WARN,
        _t("selfAliasTitle").format(n=len(aliases)),
        detail,
        fix_label=_t("selfAliasFix"),
        fix=_clear_all_aliases,
    )


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


def run() -> list[Check]:
    """Every self-check, worst first. Never raises: a diagnostics panel that crashes is worse than
    one that is missing a row."""
    checks = []
    for probe in (_alias_check, _catalogue_check):
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
