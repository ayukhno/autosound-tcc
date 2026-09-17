"""Reports without GitHub (core/form_report.py, TODO F-042).

What is worth a test is the part a person cannot see from the window: which form the text goes to,
in which field, and when the window may say "sent". A form page that comes back without the
confirmation is a report that did not arrive, however cleanly the request went.
"""

from __future__ import annotations

import urllib.error
import urllib.parse

import pytest

from autosound_tcc.core import form_report


def test_the_first_line_names_the_kind_and_what_it_ran_on():
    line = form_report.first_line("wish", "uk", tcc="0.1.41", method="3.0.54", system="Windows 11")

    assert line == "[wish] · TCC 0.1.41 · method 3.0.54 · Windows 11 · lang=uk"


def test_a_version_that_cannot_be_told_is_said_rather_than_left_blank():
    line = form_report.first_line("problem", "en", tcc="", method="", system="")

    assert line == "[problem] · TCC unknown · method unknown · unknown · lang=en"


def test_a_kind_outside_the_three_is_refused():
    # The first line is what the author sorts rows by; a fourth spelling is a row nobody finds.
    with pytest.raises(ValueError):
        form_report.first_line("bug", "en", tcc="1", method="1", system="x")


def test_the_text_goes_under_the_first_line_and_the_attachment_under_the_text():
    got = form_report.compose("[problem] · TCC 1", "  it froze  ", "[Autosound TCC]\n  version 1\n")

    assert got == "[problem] · TCC 1\n\nit froze\n\n[Autosound TCC]\n  version 1"
    assert form_report.compose("[feedback] · TCC 1", "fine") == "[feedback] · TCC 1\n\nfine"


def test_the_text_is_posted_to_the_form_in_its_one_field():
    seen = {}

    def post(url, data, timeout):
        seen["url"], seen["data"] = url, data
        return 200, '<a href="viewform?usp=form_confirm">'

    form_report.send("[problem] · TCC 1\n\nit froze", post=post)

    assert seen["url"] == form_report.FORM_POST_URL
    assert urllib.parse.parse_qs(seen["data"].decode("utf-8")) == {
        form_report.FORM_FIELD: ["[problem] · TCC 1\n\nit froze"]}


def test_sent_only_when_the_form_confirms():
    confirmed = form_report.send("x", post=lambda *_: (200, "… viewform?usp=form_confirm …"))
    assert confirmed.ok

    # The form page itself comes back 200 too — a closed form, a changed form, a captcha. None of
    # them is a report that arrived.
    page = form_report.send("x", post=lambda *_: (200, "<html>the form page, unanswered</html>"))
    assert not page.ok and page.reason == "unconfirmed"


def test_a_network_failure_is_said_not_swallowed():
    def offline(*_):
        raise urllib.error.URLError("no route to host")

    got = form_report.send("x", post=offline)

    assert not got.ok and got.reason == "network" and "no route to host" in got.detail


def test_an_http_refusal_is_said_with_its_code():
    def refused(url, *_):
        raise urllib.error.HTTPError(url, 405, "Method Not Allowed", None, None)

    got = form_report.send("x", post=refused)

    assert not got.ok and got.reason == "http" and "405" in got.detail
