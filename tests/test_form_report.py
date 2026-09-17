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

from autosound_tcc.core import form_report
from autosound_tcc.core.form_report import Report


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
        form_report.FIELD_SENDER: "Олег, @oleg",
        form_report.FIELD_KIND: "Проблема",
        form_report.FIELD_IMPACT: "Зупиняє: далі налаштовувати не можу",
        form_report.FIELD_MESSAGE: "it froze",
        form_report.FIELD_VERSIONS: "TCC 1",
    }


def test_what_was_not_said_is_left_out_rather_than_sent_empty():
    got = form_report.fields(_report(kind="wish", impact="", versions=""))

    assert form_report.FIELD_IMPACT not in got and form_report.FIELD_VERSIONS not in got


def test_the_answers_are_the_forms_own_words():
    # A choice the form does not list is not taken. These are the published form's words,
    # read from it on 2026-09-17 after the Arbiter's questions were added.
    assert form_report.KIND_ANSWERS == {
        "problem": "Проблема", "wish": "Побажання", "feedback": "Відгук", "test": "Тест"}
    assert form_report.IMPACT_ANSWERS == {
        "stops": "Зупиняє: далі налаштовувати не можу",
        "workaround": "Заважає, але можна обійти",
        "none": "Не заважає",
    }


def test_a_person_is_offered_every_kind_but_the_test_one():
    # "Тест" is for probes (the Arbiter, 2026-09-17: a kind of its own, so the sheet needs no
    # cleaning after a check) — not a choice for someone writing about their car.
    assert form_report.PERSON_KINDS == ("problem", "wish", "feedback")


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

    assert seen["url"] == form_report.FORM_POST_URL
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
