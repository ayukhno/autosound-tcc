"""TCC's own setup, said out loud — and repaired where the repair is TCC's to make.

The class of problem this exists for: a model alias written weeks ago silently redirects every
reviewer call, and the only record is a JSON file the Arbiter has no reason to open. Found by
audit, five days after it started (2026-08-12), pointing every Gemini reviewer at the Generator's
own model.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import model_choices, model_overrides, self_check  # noqa: E402


@pytest.fixture(autouse=True)
def _own_config(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(model_choices, "_CLI_CACHE", {})
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: False)
    # The window hands the core its translations (HUB-051); these tests compare against them, so
    # they hand them in too rather than depend on some earlier test having imported the window.
    from autosound_tcc.ui.tcc import i18n

    monkeypatch.setattr(self_check, "_translate", i18n.t)
    yield


def _find(checks, check_id):
    return next(c for c in checks if c.id == check_id)


def test_a_clean_install_says_so_rather_than_staying_silent():
    checks = self_check.run()

    aliases = _find(checks, "aliases")
    assert aliases.status == self_check.OK
    assert not aliases.fixable, "nothing to repair, so no button that does nothing"


def test_an_alias_onto_another_vendor_is_the_bad_one():
    """A substitution inside a vendor is a substitution. One across vendors, on the reviewer, is
    the end of cross-vendor review — and that is not the same severity."""
    model_overrides.set_alias("agy:gemini-3.1-pro-high", "sdk:claude-opus-5", "gone")

    aliases = _find(self_check.run(), "aliases")

    assert aliases.status == self_check.BAD
    assert "agy:gemini-3.1-pro-high" in aliases.detail
    assert "sdk:claude-opus-5" in aliases.detail
    assert aliases.fixable


def test_the_fix_removes_them_and_says_how_many():
    model_overrides.set_alias("agy:gemini-3.1-pro-high", "sdk:claude-opus-5", "gone")
    model_overrides.set_alias("agy:gemini-3.5-flash-high", "sdk:claude-opus-5", "gone")

    message = _find(self_check.run(), "aliases").fix()

    assert "2" in message
    assert model_overrides.load()["aliases"] == {}
    assert _find(self_check.run(), "aliases").status == self_check.OK


def test_the_fix_is_offered_only_for_what_tcc_owns():
    """D-6: the skill writes the project, TCC reads it. Every fixable check must touch TCC's own
    config and nothing under the project — a button here that edited `project.json` would make two
    writers of a file with one owner."""
    model_overrides.set_alias("a:b", "c:d", "gone")

    fixable = [c.id for c in self_check.run() if c.fixable]

    assert set(fixable) <= {"aliases", "catalogue"}


def test_a_probe_that_raises_becomes_a_row_not_a_dead_dialog(monkeypatch):
    monkeypatch.setattr(
        self_check, "_alias_check", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    checks = self_check.run()

    assert any("boom" in (c.detail or "") for c in checks)
    # By id, not by count: a test that has to be edited every time a probe is added is a test that
    # eventually gets edited without being read.
    assert {"catalogue", "reviewer_actual", "recommendation"} <= {c.id for c in checks}


def test_an_installed_cli_that_answered_nothing_gets_a_row_and_a_retry(monkeypatch):
    """The route simply vanishes from the pickers, which reads exactly like "not installed" — and
    that is what wrote the aliases in the first place."""
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "agy")
    # Asked, and answered nothing: a route never asked is "not checked", not "silent". This used to
    # come from whichever test had asked last, so it held only after `test_model_choices.py`.
    monkeypatch.setitem(model_choices._LAST_ASKED, "agy", 0.0)

    catalogue = _find(self_check.run(), "catalogue")

    assert catalogue.status == self_check.WARN
    assert "agy" in catalogue.title
    assert catalogue.fixable


def test_worst_first():
    model_overrides.set_alias("agy:gemini-3.1-pro-high", "sdk:claude-opus-5", "gone")

    statuses = [c.status for c in self_check.run()]

    assert statuses == sorted(statuses, key=lambda s: {"bad": 0, "wait": 1, "done": 2}[s])


# ---- who actually answered (live session, 2026-08-12) -----------------------------------------


_ASKED_BY_THE_PICK = object()


def _last_call(tmp_path, monkeypatch, model, mode="answered", asked=_ASKED_BY_THE_PICK):
    """The log's last line: `model` answered a call that asked for `asked` — the pick's own model
    unless a test says otherwise, and no `asked` at all for None, as a log written before tcc#140."""
    import json
    from autosound_tcc.core import config, critic, project_settings

    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "agy:gemini-3.1-pro-high")
    entry = {"at": "2026-08-12T06:24:58+00:00", "role": "critic", "mode": mode, "model": model}
    if asked is _ASKED_BY_THE_PICK:
        entry["asked"] = "gemini-3.1-pro-high"
    elif asked is not None:
        entry["asked"] = asked
    path = critic.log_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry) + "\n", encoding="utf-8")


def test_a_different_model_answering_is_caught_even_with_no_alias(tmp_path, monkeypatch):
    """`substituted` was empty and the picker said Pro while Flash did the reviewing — the swap
    happened inside the reviewer script's API→CLI fallback, which no flag in TCC records. Both
    halves were already on disk; nothing compared them."""
    _last_call(tmp_path, monkeypatch, "gemini-3.6-flash-high")

    check = _find(self_check.run(), "reviewer_actual")

    assert check.status == self_check.BAD
    assert "gemini-3.1-pro-high" in check.detail and "gemini-3.6-flash-high" in check.detail
    assert not check.fixable, "TCC cannot fix what another program's fallback chose"
    assert self_check.reviewer_mismatch() == ("gemini-3.1-pro-high", "gemini-3.6-flash-high")


def test_two_spellings_of_the_same_model_are_not_a_mismatch(tmp_path, monkeypatch):
    """The picker's key and the script's recorded name differ in punctuation, not in model."""
    _last_call(tmp_path, monkeypatch, "Gemini 3.1 Pro (High)")

    assert _find(self_check.run(), "reviewer_actual").status == self_check.OK
    assert self_check.reviewer_mismatch() is None


def test_a_review_asked_for_another_model_is_no_fallback_of_this_pick(tmp_path, monkeypatch):
    """Finding 142 (tcc#140): a new reviewer was picked and answered its check, and the footer's «!»
    said «answered by gemini-3.1-pro-preview» — the previous pick's last review — with a detail
    claiming the script had fallen back. That call asked for its own model and got it. A fallback
    is claimed only from a call that asked for this pick's model."""
    _last_call(tmp_path, monkeypatch, "gemini-3.1-pro-preview", asked="gemini-3.1-pro-preview")

    check = _find(self_check.run(), "reviewer_actual")

    assert check.status == self_check.OK
    assert self_check.reviewer_mismatch() is None
    assert "gemini-3.1-pro-preview" in check.title, "it still says who answered last"


def test_a_log_line_that_does_not_say_what_it_asked_for_is_no_evidence(tmp_path, monkeypatch):
    """The log written before tcc#140 has no `asked`: such a line cannot tell a fallback from a
    review by the reviewer picked before — the Arbiter's log on the VM is all of this kind. It
    claims neither, nor that what answered is what was asked for."""
    from autosound_tcc.ui.tcc import i18n

    _last_call(tmp_path, monkeypatch, "gemini-3.6-flash-high", asked=None)

    check = _find(self_check.run(), "reviewer_actual")

    assert check.status == self_check.OK
    assert self_check.reviewer_mismatch() is None
    assert check.title != i18n.t("selfReviewerOkTitle").format(model="gemini-3.6-flash-high")


def test_a_clipboard_round_is_not_evidence_of_anything(tmp_path, monkeypatch):
    """Clipboard mode means nobody was called; comparing against it would invent a mismatch."""
    _last_call(tmp_path, monkeypatch, "", mode="clipboard")

    assert _find(self_check.run(), "reviewer_actual").status == self_check.OK


def test_the_no_alias_row_no_longer_claims_more_than_it_knows():
    """It said "every picker runs what it says", which the same night's session disproved. An
    assurance that reaches past its evidence is the one a reader stops checking."""
    from autosound_tcc.ui.tcc import i18n

    assert "runs what it says" not in i18n.t("selfAliasNoneTitle")
    assert "reviewer script" in i18n.t("selfAliasNoneDetail")


def test_a_harness_prefix_is_not_a_vendor_collapse():
    """`claude-opus-5 → sdk:claude-opus-5` is one model written twice: the second says which
    harness starts it. The check read it as a substitution onto another vendor and painted the
    app's own red dot over a name repair — a bare key has no harness, so the fallback Choice got
    an empty provider, which differs from every real one (user, 2026-08-23: "what is that, and is
    it worth removing?").
    """
    model_overrides.set_alias("claude-opus-5", "sdk:claude-opus-5", "written without its prefix")

    aliases = _find(self_check.run(), "aliases")

    assert aliases.status == self_check.WARN, "worth listing, not worth an alarm"
    assert "claude-opus-5 → sdk:claude-opus-5" in aliases.detail
    assert i18n_text("selfAliasSameModel") in aliases.detail
    assert i18n_text("selfAliasCrossVendor") not in aliases.detail
    assert aliases.fixable, "and still removable, because an indirection is worth being rid of"


def i18n_text(key: str) -> str:
    """The fixed half of a template, for asserting WHICH sentence was chosen.

    Everything after the last placeholder, because these two both OPEN with `{keys}` -- taking
    what comes before it returns the empty string, and an empty string is in every detail there
    has ever been.
    """
    from autosound_tcc.ui.tcc import i18n

    return i18n.t(key).rsplit("}", 1)[-1].strip()



def _pin_git(monkeypatch, answers: dict, tmp_path):
    """Fake the method's checkout: `updates._git` by its first two arguments."""
    from autosound_tcc.core import install_report, updates, vendor_loader

    monkeypatch.setattr(vendor_loader, "skill_repo_root", lambda: tmp_path)

    def fake(*args, **kwargs):
        for key, value in answers.items():
            if args[: len(key)] == key:
                return value
        return (False, "")

    monkeypatch.setattr(updates, "_git", fake)
    # This row no longer runs its own `rev-parse HEAD`: since HUB-001 the method's sha is read in
    # one place, so that this check, the title bar and the update row cannot end up naming
    # different commits. Fed from the same answers, so the tests below say what they always said.
    head_ok, head = answers.get(("rev-parse", "HEAD"), (False, ""))
    monkeypatch.setattr(install_report, "skill_sha", lambda: head if head_ok else "")


def test_a_pin_behind_a_released_tag_is_said_out_loud(monkeypatch, tmp_path):
    """F-029. The pin is right and stays; what was missing is anyone SAYING it fell behind. It sat
    on v3.0.11 while the method already had v3.0.12 with a changed `align_delay_polarity`
    contract, and that surfaced only when somebody bumped it by hand."""
    _pin_git(monkeypatch, {
        ("rev-parse", "--show-superproject-working-tree"): (True, "/repo/tcc"),
        ("rev-parse", "HEAD"): (True, "aaaaaaa"),
        ("for-each-ref",): (True, "v3.0.34\nv3.0.33\n"),
        ("rev-parse", "v3.0.34^{commit}"): (True, "bbbbbbb"),
        ("rev-list", "--count"): (True, "3"),
    }, tmp_path)

    check = self_check._pin_check()

    assert check.status == self_check.WARN
    assert "v3.0.34" in check.title and "3" in check.title
    assert check.fix is None, "a bump is a decision, not a deterministic repair — no button"
    assert "checkout v3.0.34" in check.detail, "the command is named, since we cannot press it"


def test_a_pin_at_the_newest_tag_says_which_one_and_that_it_is_local(monkeypatch, tmp_path):
    """The OK row names the tag AND the limit of the answer: the tags are read from this checkout,
    without asking the network, so a newer one may exist that was never fetched. A check that
    cannot see everything should say what it looked at — otherwise it is the reassuring kind."""
    _pin_git(monkeypatch, {
        ("rev-parse", "--show-superproject-working-tree"): (True, "/repo/tcc"),
        ("rev-parse", "HEAD"): (True, "bbbbbbb"),
        ("for-each-ref",): (True, "v3.0.34\n"),
        ("rev-parse", "v3.0.34^{commit}"): (True, "bbbbbbb"),
    }, tmp_path)

    check = self_check._pin_check()

    assert check.status == self_check.OK
    assert "v3.0.34" in check.title


def test_an_installed_skill_is_not_this_rows_business(monkeypatch, tmp_path):
    """No superproject means no submodule: an installed skill belongs to the update row
    (`updates.check_skill`), and two rows saying the same thing in different words is worse."""
    _pin_git(monkeypatch, {
        ("rev-parse", "--show-superproject-working-tree"): (True, ""),
    }, tmp_path)

    assert self_check._pin_check().status == self_check.OK


def test_running_ahead_of_the_releases_is_not_being_behind(monkeypatch, tmp_path):
    """A developer pinned in FRONT of the newest tag is not out of date, and a row telling them to
    check out backwards would be wrong — the same judgement `check_tcc` already makes."""
    _pin_git(monkeypatch, {
        ("rev-parse", "--show-superproject-working-tree"): (True, "/repo/tcc"),
        ("rev-parse", "HEAD"): (True, "ccccccc"),
        ("for-each-ref",): (True, "v3.0.34\n"),
        ("rev-parse", "v3.0.34^{commit}"): (True, "bbbbbbb"),
        ("rev-list", "--count"): (True, "0"),
    }, tmp_path)

    assert self_check._pin_check().status == self_check.OK


def test_no_tags_to_compare_against_is_silence_not_an_alarm(monkeypatch, tmp_path):
    """F-029's own rule: never BAD, never blocking. A shallow clone with no tags fetched has
    nothing to say, and saying it loudly would train the reader to ignore the row."""
    _pin_git(monkeypatch, {
        ("rev-parse", "--show-superproject-working-tree"): (True, "/repo/tcc"),
        ("rev-parse", "HEAD"): (True, "aaaaaaa"),
        ("for-each-ref",): (True, ""),
    }, tmp_path)

    assert self_check._pin_check().status == self_check.OK


def test_an_installed_agy_says_how_it_signs_in_from_the_methods_own_reading(monkeypatch):
    """hub #235, tcc#135: which sign-in agy will use — Google Cloud's ADC, its account, or none —
    shown where TCC shows its setup. The method reads it (`agy_sign_in`, from disk and the
    environment its runs start with, critic-env included); TCC shows its words, not a copy."""
    from autosound_tcc.core import critic

    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "agy")
    monkeypatch.setattr(critic, "agy_sign_in",
                        lambda project_dir=None: ("adc", "ADC (Google Cloud), /home/x/adc.json"))

    row = _find(self_check.run(), "agy_sign_in")

    assert row.status == self_check.OK
    assert "ADC" in row.title
    assert row.detail == "ADC (Google Cloud), /home/x/adc.json"


def test_an_agy_with_no_sign_in_is_a_warning_with_the_methods_way_out(monkeypatch):
    from autosound_tcc.core import critic

    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "agy")
    monkeypatch.setattr(critic, "agy_sign_in",
                        lambda project_dir=None: ("none", "agy без входу: запусти `agy` раз і увійди"))

    row = _find(self_check.run(), "agy_sign_in")

    assert row.status == self_check.WARN
    assert row.detail.startswith("agy без входу")


def test_no_agy_no_row(monkeypatch):
    from autosound_tcc.core import critic

    monkeypatch.setattr(critic, "agy_sign_in", lambda project_dir=None: ("adc", "x"))

    assert "agy_sign_in" not in {c.id for c in self_check.run()}


def test_a_method_that_cannot_say_leaves_no_row(monkeypatch):
    from autosound_tcc.core import critic

    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "agy")
    monkeypatch.setattr(critic, "agy_sign_in", lambda project_dir=None: None)

    assert "agy_sign_in" not in {c.id for c in self_check.run()}
