"""The Updates tab says, beside each version, whether the installed release's signature was
checked and good — or why not (#195, finding 159). The answers are `updates.Seal`s, faked here:
`test_installed_signature.py` covers how TCC reaches them."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import updates  # noqa: E402
from autosound_tcc.ui.tcc import i18n  # noqa: E402
from autosound_tcc.ui.tcc.diagnostics_panel import DiagnosticsDialog  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _seals(monkeypatch, tcc: updates.Seal, skill: updates.Seal) -> list:
    asked = []
    monkeypatch.setattr(updates, "tcc_seal", lambda: asked.append("tcc") or tcc)
    monkeypatch.setattr(updates, "skill_seal", lambda: asked.append("skill") or skill)
    monkeypatch.setattr(updates, "check_all", lambda channel="stable": (
        updates.Status("tcc", "1.1.3", "1.1.3", False),
        updates.Status("skill", "3.1.3", "3.1.3", False)))
    monkeypatch.setattr(updates, "tools_status", lambda: updates.ToolsStatus(True, ()))
    return asked


def _finish_seals(dialog) -> None:
    for job in list(dialog._seal_jobs.values()):
        job.join(timeout=10)
    dialog._poll_seals()
    assert not dialog._seal_jobs, "the seal checks never settled"


def _opened(monkeypatch, tcc, skill):
    asked = _seals(monkeypatch, tcc, skill)
    _app()
    dialog = DiagnosticsDialog()
    dialog._tabs.setCurrentWidget(dialog._updates_tab)
    _finish_seals(dialog)
    return dialog, asked


def test_each_version_has_its_signature_mark_on_the_updates_tab(monkeypatch):
    dialog, asked = _opened(monkeypatch,
                            updates.Seal("good", "v1.1.3", principal="ayukhno"),
                            updates.Seal("good", "v3.1.3", principal="ayukhno"))

    assert sorted(asked) == ["skill", "tcc"], "opening the tab asks both"
    for name, tag in (("tcc", "v1.1.3"), ("skill", "v3.1.3")):
        mark = dialog._seal_labels[name]
        assert dialog._updates_tab.isAncestorOf(mark) and not mark.isHidden(), name
        assert mark.text() == i18n.t("updSealGood").format(tag=tag, principal="ayukhno")


def test_a_mark_never_says_checked_for_what_was_not(monkeypatch):
    dialog, _ = _opened(monkeypatch,
                        updates.Seal("unknown", reason="source_checkout"),
                        updates.Seal("predates", "v3.0.9"))

    tcc, skill = (dialog._seal_labels[name].text() for name in ("tcc", "skill"))
    assert tcc == i18n.t("updSealUnknown").format(why=i18n.t("updSealWhy_source_checkout"))
    assert skill == i18n.t("updSealPredates").format(tag="v3.0.9")
    good = i18n.t("updSealGood").split("{")[0]
    assert good not in tcc and good not in skill


@pytest.mark.parametrize("seal, key, fields", [
    (updates.Seal("skipped", "v1.1.3", detail="AUTOSOUND_SKIP_TAG_VERIFY"), "updSealSkipped",
     {"var": "AUTOSOUND_SKIP_TAG_VERIFY"}),
    (updates.Seal("bad", "v1.1.3", "bad_signature", "v1.1.3: No principal matched."),
     "updSealBad", {"tag": "v1.1.3", "detail": "No principal matched."}),
    (updates.Seal("bad", "v1.1.3", "commit_differs", "v1.1.3 → cccc, installed dddd"),
     "updSealMoved", {"tag": "v1.1.3", "detail": "v1.1.3 → cccc, installed dddd"}),
])
def test_each_answer_is_said_in_the_reader_s_language(monkeypatch, seal, key, fields):
    dialog, _ = _opened(monkeypatch, seal, updates.Seal("unknown", reason="not_found"))

    assert dialog._seal_labels["tcc"].text() == i18n.t(key).format(**fields)


def test_could_not_look_says_why_with_git_s_words(monkeypatch):
    dialog, _ = _opened(monkeypatch,
                        updates.Seal("unknown", "v1.1.3", "fetch_failed", "unable to access"),
                        updates.Seal("unknown", reason="clone_no_tag"))

    assert dialog._seal_labels["tcc"].text() == i18n.t("updSealUnknown").format(
        why=f"{i18n.t('updSealWhy_fetch_failed')}: unable to access")
    assert dialog._seal_labels["skill"].text() == i18n.t("updSealUnknown").format(
        why=i18n.t("updSealWhy_clone_no_tag"))


def test_local_changes_are_said_beside_the_method_s_good_signature(monkeypatch):
    dialog, _ = _opened(monkeypatch, updates.Seal("unknown", reason="source_checkout"),
                        updates.Seal("good", "v3.1.3", principal="ayukhno", changed=True))

    text = dialog._seal_labels["skill"].text()
    assert i18n.t("updSealGood").format(tag="v3.1.3", principal="ayukhno") in text
    assert i18n.t("updSealChanged") in text


def test_a_check_that_raised_is_unknown_not_silent(monkeypatch):
    _seals(monkeypatch, updates.Seal("good", "v1.1.3", principal="ayukhno"),
           updates.Seal("good", "v3.1.3", principal="ayukhno"))
    monkeypatch.setattr(updates, "skill_seal", lambda: 1 / 0)
    _app()
    dialog = DiagnosticsDialog()
    dialog._tabs.setCurrentWidget(dialog._updates_tab)
    _finish_seals(dialog)

    text = dialog._seal_labels["skill"].text()
    assert text.startswith(i18n.t("updSealUnknown").split("{")[0]) and "ZeroDivisionError" in text


def test_re_check_asks_again_and_says_checking_meanwhile(monkeypatch):
    dialog, asked = _opened(monkeypatch, updates.Seal("good", "v1.1.3", principal="ayukhno"),
                            updates.Seal("good", "v3.1.3", principal="ayukhno"))
    asked.clear()

    dialog._on_refresh()

    assert dialog._seal_labels["tcc"].text() == i18n.t("updSealChecking")
    _finish_seals(dialog)
    assert sorted(asked) == ["skill", "tcc"]


def test_a_language_switch_redraws_the_marks(monkeypatch):
    dialog, _ = _opened(monkeypatch, updates.Seal("good", "v1.1.3", principal="ayukhno"),
                        updates.Seal("predates", "v3.0.9"))
    before = i18n.current_language()
    try:
        i18n.set_language("uk")
        dialog._retranslate()
        assert dialog._seal_labels["skill"].text() == i18n.T["uk"]["updSealPredates"].format(
            tag="v3.0.9")
    finally:
        i18n.set_language(before)


def test_the_update_window_gets_the_signature_line_in_the_reader_s_language(monkeypatch):
    """The words go with the press; the line is written only when the tag verified (core)."""
    _seals(monkeypatch, updates.Seal("unknown", reason="source_checkout"),
           updates.Seal("unknown", reason="not_found"))
    seen = {}
    monkeypatch.setattr(updates, "prepare_tcc_update", lambda channel="stable", **kw: (
        seen.update(kw) or updates.TccUpdate(None, "no_network")))
    _app()
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("tcc", "1.1.3", "1.1.4", True))

    dialog._update_tcc()
    dialog._tcc_job.join(timeout=10)
    dialog._poll_tcc_job()

    assert seen["words"]["signed"] == i18n.t("updTermSigned")


def test_a_method_update_that_lands_takes_the_old_release_s_mark_away(monkeypatch):
    """The mark was about the release the clone left; the receipt on the row says the new one's
    signature, and the next Re-check checks it."""
    from tests.test_diagnostics_panel import _skill_offered, _update_cleanly

    dialog, _asked = _skill_offered(monkeypatch)
    dialog._show_seal("skill", updates.Seal("good", "v3.0.6", principal="ayukhno"))

    _update_cleanly(dialog, monkeypatch)

    assert dialog._seal_labels["skill"].isHidden() and "skill" not in dialog._seals
