"""Reports without GitHub: a report sent straight to the Arbiter's Google Form (TODO F-042).

The window's only report route used to be a GitHub issue, and a person without an account — the
ordinary tester since the installer stopped installing `gh` unless asked — had nowhere to say that
something broke. The Arbiter's decision (2026-09-17): his Google Form, sent from the window with no
browser and no sign-in, into a sheet on his Drive. **Text only.** A file question would make Google
demand a sign-in for the whole form, and that would close it to a session sending the same way
(autosound-hub #157, TCC-017) — pictures keep going through GitHub, or separately.

The questions are the Arbiter's (2026-09-17): who wrote, so he can answer; what kind of report it
is; for a problem, how far it stops the tuning; the words; and the versions it ran on, which the
window fills in. Each goes to its own question, so each is its own column in the sheet.

The destination is fixed here, in code, and nowhere else: a place that decides where a person's
words go is a place that can be talked into sending them somewhere else — the posture of the
method's side-effect gate (`rew_tool/gates/side_effect.py`), kept for a destination of our own. The
question ids and the choice words below are read from the published form; a choice it does not
list, or a required answer left out, is not taken.

"Sent" is what the form CONFIRMS, never what the request did. The form answers 200 with its own page
when it did not take the answer (closed, changed, a required answer missing), so the one proof is
the confirmation page's "submit another response" link — measured on 2026-09-17 with test entries
that landed in the sheet, and absent from the form page itself.
"""

from __future__ import annotations

import platform
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from autosound_tcc.core import install_report

FORM_POST_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSdMzITv6Rzh8PWITy5QWc3xQMcAn9aDl1k0QbpZykHEQd6A4g/formResponse"
)
#: The form's questions, as published on 2026-09-17.
FIELD_SENDER = "entry.240346646"  # «Від кого», required
FIELD_KIND = "entry.2096497360"  # «Тип», required
FIELD_IMPACT = "entry.42935929"  # «Наскільки заважає налаштуванню»
FIELD_MESSAGE = "entry.970390217"  # «Повідомлення», required
FIELD_VERSIONS = "entry.1476583291"  # «Версії»
#: The form's own words for each choice: anything else is not an answer it takes.
KIND_ANSWERS = {"problem": "Проблема", "wish": "Побажання", "feedback": "Відгук", "test": "Тест"}
IMPACT_ANSWERS = {
    "stops": "Зупиняє: далі налаштовувати не можу",
    "workaround": "Заважає, але можна обійти",
    "none": "Не заважає",
}
KINDS = tuple(KIND_ANSWERS)
#: What a person writing a report chooses from. "Тест" is for probes: a kind of its own, so the
#: sheet needs no cleaning after a check (the Arbiter, 2026-09-17).
PERSON_KINDS = ("problem", "wish", "feedback")
IMPACTS = tuple(IMPACT_ANSWERS)
#: Only the confirmation page carries it: the link to submit another response.
ACCEPTED_MARKER = "usp=form_confirm"
TIMEOUT_S = 20


@dataclass(frozen=True)
class Report:
    """One report. `impact` is "" when it was not said — the form asks it of a problem only."""

    sender: str
    kind: str
    message: str
    versions: str = ""
    impact: str = ""


@dataclass(frozen=True)
class Sent:
    """`reason` is "" when the form confirmed, else "unconfirmed", "network" or "http"."""

    ok: bool
    reason: str = ""
    detail: str = ""


def versions_line(lang: str, *, tcc=None, method=None, system=None) -> str:
    """`TCC 0.1.41 · method 3.0.54 · Windows 11 · lang=uk` — what the report ran on.

    `tcc`, `method` and `system` are read from this installation when not given. What cannot be
    told is written as "unknown", never left out: a missing part reads as a line cut short.
    """
    if tcc is None:
        tcc = install_report.app_version()
    if method is None:
        method = install_report.skill_version()
    if system is None:
        system = f"{platform.system()} {platform.release()}".strip()
    return (f"TCC {tcc or 'unknown'} · method {method or 'unknown'} · {system or 'unknown'} · "
            f"lang={lang}")


def compose(message: str, attachment: str = "") -> str:
    """The person's words, and what goes with them under those."""
    parts = [message.strip()]
    if attachment.strip():
        parts.append(attachment.strip())
    return "\n\n".join(parts)


def fields(report: Report) -> dict[str, str]:
    """The form's question ids with their answers. Raises `ValueError` for what the form would
    not take: no sender, no words, or a choice it does not list."""
    if not report.sender.strip():
        raise ValueError("a report says who wrote it: the Arbiter answers people")
    if not report.message.strip():
        raise ValueError("a report without words is not a report")
    if report.kind not in KIND_ANSWERS:
        raise ValueError(f"a report is one of {', '.join(KINDS)}, not {report.kind!r}")
    if report.impact and report.impact not in IMPACT_ANSWERS:
        raise ValueError(f"how far it stops the tuning is one of {', '.join(IMPACTS)}, "
                         f"not {report.impact!r}")
    answers = {
        FIELD_SENDER: report.sender.strip(),
        FIELD_KIND: KIND_ANSWERS[report.kind],
        FIELD_MESSAGE: report.message.strip(),
    }
    if report.impact:
        answers[FIELD_IMPACT] = IMPACT_ANSWERS[report.impact]
    if report.versions.strip():
        answers[FIELD_VERSIONS] = report.versions.strip()
    return answers


def as_text(report: Report) -> str:
    """The whole report as plain text, for a clipboard when the form did not take it."""
    lines = [f"Від кого: {report.sender.strip()}",
             f"Тип: {KIND_ANSWERS.get(report.kind, report.kind)}"]
    if report.impact:
        lines.append(f"Наскільки заважає: {IMPACT_ANSWERS.get(report.impact, report.impact)}")
    if report.versions.strip():
        lines.append(f"Версії: {report.versions.strip()}")
    return "\n".join(lines) + "\n\n" + report.message.strip()


def _context() -> ssl.SSLContext:
    # A Python built outside the system (uv's own) may not find the system's certificates on macOS;
    # certifi's bundle is on every install that has it, and the default context is the fallback.
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 — no certifi: the system's store is what there is
        return ssl.create_default_context()


def _post(url: str, data: bytes, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=timeout, context=_context()) as response:
        return response.status, response.read().decode("utf-8", "replace")


def send(report: Report, *, url: str = FORM_POST_URL, post=_post,
         timeout: float = TIMEOUT_S) -> Sent:
    """Post `report` to the form and say whether the form confirmed it. Raises only for a report
    the form would not take (`fields`); a network or a form that says no is a `Sent`."""
    data = urllib.parse.urlencode(fields(report)).encode("utf-8")
    try:
        status, body = post(url, data, timeout)
    except urllib.error.HTTPError as exc:
        return Sent(False, "http", f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        return Sent(False, "network", str(getattr(exc, "reason", None) or exc))
    if status != 200 or ACCEPTED_MARKER not in body:
        return Sent(False, "unconfirmed", f"HTTP {status}")
    return Sent(True)
