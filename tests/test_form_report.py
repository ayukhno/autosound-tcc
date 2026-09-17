"""Reports without GitHub (core/form_report.py, TODO F-042).

What is worth a test is the part a person cannot see from the window: which form the report goes
to, which answer lands in which question, and when the window may say "sent". A form page that
comes back without the confirmation is a report that did not arrive, however cleanly the request
went.
"""

from __future__ import annotations

import urllib.error
import urllib.parse

import pytest

from autosound_tcc.core import form_report, vendor_loader
from autosound_tcc.core.form_report import Report

#: The form belongs to the METHOD (the user's decision, 2026-09-17): its address, its question
#: ids and its answer words are read from the gate, and this module refers to them the same way
#: TCC does rather than keeping a second copy for the test to agree with itself.
_GATE = vendor_loader.load("gates/side_effect.py")

pytestmark = pytest.mark.skipif(
    not form_report.is_available(),
    reason="no method with the form route (rew_tool/gates/side_effect.py, v3.0.56+)",
)


def _report(**overrides):
    fields = dict(sender="Олег, @oleg", kind="problem", impact="stops", message="it froze",
                  versions="TCC 1")
    fields.update(overrides)
    return Report(**fields)


def test_the_versions_line_names_what_it_ran_on():
    line = form_report.versions_line("uk", tcc="0.1.41", method="3.0.54", system="Windows 11")

    assert line == "TCC 0.1.41 · method 3.0.54 · Windows 11 · lang=uk"


def test_a_version_that_cannot_be_told_is_said_rather_than_left_blank():
    line = form_report.versions_line("en", tcc="", method="", system="")

    assert line == "TCC unknown · method unknown · unknown · lang=en"


def test_every_answer_goes_to_its_own_question():
    assert form_report.fields(_report()) == {
        _GATE.FORM_FIELD_SENDER: "Олег, @oleg",
        _GATE.FORM_FIELD_KIND: "Проблема",
        _GATE.FORM_FIELD_IMPACT: "Зупиняє: далі налаштовувати не можу",
        _GATE.FORM_FIELD_MESSAGE: "it froze",
        _GATE.FORM_FIELD_VERSIONS: "TCC 1",
    }


def test_the_question_ids_are_the_methods_and_not_a_copy_here(monkeypatch):
    """The point of the consolidation (the user, 2026-09-17): the form is the method's, and this
    module refers to it. A copy here would keep answering with the old id after the method's
    moved — the sheet filling a column nobody reads."""
    monkeypatch.setattr(_GATE, "FORM_POST_URL", "https://example.invalid/formResponse")
    monkeypatch.setattr(_GATE, "FORM_KINDS", dict(_GATE.FORM_KINDS, wish="Wish"))

    assert form_report.post_url() == "https://example.invalid/formResponse"
    assert form_report.kind_answers()["wish"] == "Wish"


def test_what_was_not_said_is_left_out_rather_than_sent_empty():
    got = form_report.fields(_report(kind="wish", impact="", versions=""))

    assert _GATE.FORM_FIELD_IMPACT not in got and _GATE.FORM_FIELD_VERSIONS not in got


def test_the_answers_are_the_forms_own_words():
    # A choice the form does not list is not taken. These are the published form's words,
    # read from it on 2026-09-17 after the Arbiter's questions were added.
    assert form_report.kind_answers() == dict(_GATE.FORM_KINDS)
    assert form_report.impact_answers() == dict(_GATE.FORM_IMPACTS)
    # The window has a label for each of these, so the keys are the contract, not the wording.
    assert set(form_report.kind_answers()) >= {"problem", "wish", "feedback"}
    assert set(form_report.impact_answers()) == {"stops", "workaround", "none"}


def test_a_person_is_offered_every_kind_but_the_test_one():
    # "Тест" is for probes (the Arbiter, 2026-09-17: a kind of its own, so the sheet needs no
    # cleaning after a check) — not a choice for someone writing about their car.
    assert form_report.person_kinds() == ("problem", "wish", "feedback")
    assert "test" in form_report.kinds()


def test_a_report_without_a_sender_or_words_is_refused():
    # Both are required by the form: the Arbiter answers people, so he must know who wrote.
    with pytest.raises(ValueError):
        form_report.fields(_report(sender="  "))
    with pytest.raises(ValueError):
        form_report.fields(_report(message="  "))


def test_a_kind_or_an_impact_outside_the_forms_list_is_refused():
    with pytest.raises(ValueError):
        form_report.fields(_report(kind="bug"))
    with pytest.raises(ValueError):
        form_report.fields(_report(impact="blocker"))


def test_the_words_come_first_and_the_attachment_under_them():
    got = form_report.compose("  it froze  ", "[Autosound TCC]\n  version 1\n")

    assert got == "it froze\n\n[Autosound TCC]\n  version 1"
    assert form_report.compose("fine") == "fine"


def test_the_report_as_text_keeps_every_answer_for_a_paste():
    text = form_report.as_text(_report())

    for part in ("Олег, @oleg", "Проблема", "Зупиняє", "it froze", "TCC 1"):
        assert part in text


def test_the_report_is_posted_to_the_form_answer_by_answer():
    seen = {}

    def post(url, data, timeout):
        seen["url"], seen["data"] = url, data
        return 200, '<a href="viewform?usp=form_confirm">'

    form_report.send(_report(), post=post)

    assert seen["url"] == _GATE.FORM_POST_URL
    assert urllib.parse.parse_qs(seen["data"].decode("utf-8")) == {
        key: [value] for key, value in form_report.fields(_report()).items()}


def test_sent_only_when_the_form_confirms():
    confirmed = form_report.send(_report(), post=lambda *_: (200, "… viewform?usp=form_confirm …"))
    assert confirmed.ok

    # The form page itself comes back 200 too — a closed form, a changed form, a missing
    # required answer. None of them is a report that arrived.
    page = form_report.send(_report(), post=lambda *_: (200, "<html>the form page, unanswered</html>"))
    assert not page.ok and page.reason == "unconfirmed"


def test_a_network_failure_is_said_not_swallowed():
    def offline(*_):
        raise urllib.error.URLError("no route to host")

    got = form_report.send(_report(), post=offline)

    assert not got.ok and got.reason == "network" and "no route to host" in got.detail


def test_an_http_refusal_is_said_with_its_code():
    def refused(url, *_):
        raise urllib.error.HTTPError(url, 405, "Method Not Allowed", None, None)

    got = form_report.send(_report(), post=refused)

    assert not got.ok and got.reason == "http" and "405" in got.detail


def test_no_method_means_no_form_route_rather_than_a_guess(monkeypatch):
    """Without the method there is no form to send to, and TCC says so instead of inventing an
    address: `post_url()` is "", which is the dialog's own "GitHub is the only route" case."""
    monkeypatch.setattr(form_report, "_gate", lambda: None)

    assert not form_report.is_available()
    assert form_report.post_url() == ""
    assert form_report.kind_answers() == {} and form_report.person_kinds() == ()

    got = form_report.send(_report(), post=lambda *_: (200, "usp=form_confirm"))
    assert not got.ok and got.reason == "no_form"
    with pytest.raises(form_report.NoForm):
        form_report.fields(_report())


def test_a_method_older_than_the_form_route_is_the_same_case(monkeypatch):
    """A pin before the method's v3.0.56 has the gate but no form in it (`issue_assets.available()`
    posture): the module is importable and the route still must not be offered."""
    monkeypatch.delattr(_GATE, "FORM_POST_URL")

    assert not form_report.is_available()
    assert form_report.post_url() == ""
