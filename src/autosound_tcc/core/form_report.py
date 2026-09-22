"""Reports without GitHub: a report sent straight to the Arbiter's Google Form (TODO F-042).

The window's only report route used to be a GitHub issue, and a person without an account — the
ordinary tester since the installer stopped installing `gh` unless asked — had nowhere to say that
something broke. The Arbiter's decision (2026-09-17): his Google Form, sent from the window with no
browser and no sign-in, into a sheet on his Drive. **Text only.** A file question would make Google
demand a sign-in for the whole form, and that would close it to a session sending the same way
(autosound-hub #157, TCC-017) — pictures keep going through GitHub, or separately.

**The form itself belongs to the METHOD** (`rew_tool/gates/side_effect.py`), and this module reads
it from there rather than keeping a copy: the address, the five question ids, the words each choice
must be answered with, what counts as confirmed, and how long to wait. The user's decision,
2026-09-17 — a session writes to that same sheet, so the form is the method's fact, and TCC refers
to it. Both copies agreed the day they were written; the cost of two is a question id that moves in
one of them and a column quietly filled by the other.

What stays here is the half the gate has no view of: the versions line with TCC's own version in
it, the clipboard text for a report the form did not take, and the `Sent` the window renders. The
validation and the post-verification are called, not restated — the posture `core/issue_assets.py`
keeps for the same gate.

**No method, no form route.** `post_url()` is then "", and the dialog's own contract — an empty form
URL leaves GitHub as the only destination — carries it from there; a pin older than the method's
`v3.0.56` has no form in it either, which is the same case and asks the same question
(`is_available()`, the `issue_assets.available()` posture).

"Sent" is what the form CONFIRMS, never what the request did. The form answers 200 with its own page
when it did not take the answer (closed, changed, a required answer missing), so the one proof is
the confirmation page's "submit another response" link — measured on 2026-09-17 with test entries
that landed in the sheet, and absent from the form page itself. That rule is `verify_form_reply` in
the gate, and it is asked rather than repeated.
"""

from __future__ import annotations

import platform
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from autosound_tcc.core import install_report, vendor_loader

#: The method's side-effect gate. The module has been there for a long time; the form route arrives
#: with `v3.0.56`, so the file being importable is NOT the same question as the form existing, and
#: `is_available()` asks the second one.
_MODULE = "gates/side_effect.py"

#: What a person writing a report chooses from — the form's kinds minus "Тест", which is for probes
#: so the sheet needs no cleaning after a check (the Arbiter, 2026-09-17). The split is the gate's
#: too (`FORM_PERSON_KINDS`); this name is what the window reads.
_FALLBACK_TIMEOUT_S = 20


class NoForm(RuntimeError):
    """Raised when something asks about the form and the method that owns it is not installed."""


def _gate():
    try:
        return vendor_loader.load(_MODULE)
    except Exception:  # noqa: BLE001 — no skill checked out, or one without this module
        return None


def _form_gate():
    """The gate, if it carries the form route; else None."""
    gate = _gate()
    if gate is None:
        return None
    needed = ("FORM_POST_URL", "FORM_KINDS", "FORM_IMPACTS", "form_answers", "verify_form_reply")
    return gate if all(hasattr(gate, name) for name in needed) else None


def _required_gate():
    gate = _form_gate()
    if gate is None:
        raise NoForm(
            "the form belongs to the method (`rew_tool/gates/side_effect.py`) and this "
            "installation has no method with it — the report goes through GitHub, or to the "
            "clipboard"
        )
    return gate


def is_available() -> bool:
    """Whether this installation knows where the form is — i.e. can offer the route at all."""
    return _form_gate() is not None


def post_url() -> str:
    """The form's POST address, or "" when there is no method to read it from."""
    gate = _form_gate()
    return str(gate.FORM_POST_URL) if gate is not None else ""


def kind_answers() -> dict[str, str]:
    """`{"problem": "Проблема", …}` — the form's own words, empty without the method."""
    gate = _form_gate()
    return dict(gate.FORM_KINDS) if gate is not None else {}


def impact_answers() -> dict[str, str]:
    """`{"stops": "Зупиняє: …", …}` — the form's own words, empty without the method."""
    gate = _form_gate()
    return dict(gate.FORM_IMPACTS) if gate is not None else {}


def kinds() -> tuple[str, ...]:
    """Every kind the form takes, the probe kind included."""
    return tuple(kind_answers())


def person_kinds() -> tuple[str, ...]:
    """What a person writing a report chooses from: the form's kinds without the probe kind.

    "Тест" is for probes — a kind of its own, so the sheet needs no cleaning after a check (the
    Arbiter, 2026-09-17). The split is the gate's (`FORM_PERSON_KINDS`); an older or newer method
    that does not name it is read as "every kind a person may choose".
    """
    gate = _form_gate()
    if gate is None:
        return ()
    named = getattr(gate, "FORM_PERSON_KINDS", None)
    return tuple(named) if named else tuple(kind_answers())


def impacts() -> tuple[str, ...]:
    """How far a problem stops the tuning, in the order the form asks it."""
    return tuple(impact_answers())


def timeout_s() -> float:
    """How long to wait for the form, as the gate sets it."""
    gate = _form_gate()
    return float(getattr(gate, "FORM_TIMEOUT_S", _FALLBACK_TIMEOUT_S) if gate is not None
                 else _FALLBACK_TIMEOUT_S)


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
    """`reason` is "" when the form confirmed, else "unconfirmed", "network", "http" or "no_form"."""

    ok: bool
    reason: str = ""
    detail: str = ""


def versions_line(lang: str, *, tcc=None, method=None, system=None) -> str:
    """`TCC 0.1.41 · method 3.0.56 · Windows 11 · lang=uk` — what the report ran on.

    TCC's own, not the gate's `versions_line`: a report from the window has to say which WINDOW
    sent it, and the method's line names the method and the channel instead.

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
    """The form's question ids with their answers, built by the gate.

    Raises `ValueError` for what the form would not take — no sender, no words, or a choice it does
    not list — and `NoForm` when there is no method to ask.
    """
    gate = _required_gate()
    return dict(gate.form_answers(report.sender, report.kind, report.message,
                                  report.impact, report.versions))


def as_text(report: Report) -> str:
    """The whole report as plain text, for a clipboard when the form did not take it.

    The column names are the FORM's (`FORM_LABELS`, in the form's own order), because the lines
    are read beside the sheet whose columns wear exactly those words — and they are not a
    translation: a column's name belongs to the form (F-061; this file kept its own copy of them
    until then). The ANSWERS are the form's too, so what a person pastes is what the sheet would
    have held. Without the method its field names are all there is, and they are written rather
    than dropped.
    """
    gate = _form_gate()
    labels = dict(getattr(gate, "FORM_LABELS", None) or {}) if gate is not None else {}
    names = ("sender", "kind", "impact", "message", "versions")
    if labels:
        ids = {getattr(gate, f"FORM_FIELD_{name.upper()}", name): name for name in names}
    else:
        ids = {name: name for name in names}
        labels = {name: name for name in names}
    values = {
        "sender": report.sender.strip(),
        "kind": kind_answers().get(report.kind, report.kind),
        "impact": impact_answers().get(report.impact, report.impact) if report.impact else "",
        "versions": report.versions.strip(),
    }
    lines = [f"{label}: {values[ids[field_id]]}" for field_id, label in labels.items()
             if ids.get(field_id) in values and values[ids[field_id]]]
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


def send(report: Report, *, url: str = "", post=None, timeout: float = 0.0) -> Sent:
    """Post `report` to the form and say whether the form confirmed it.

    Raises only for a report the form would not take (`fields`); a network, a form that says no,
    and a method that is not installed are all a `Sent`. The address, the timeout and the verdict
    on the answer are the gate's — `url` and `timeout` are for a test, not for a caller choosing
    where a person's words go.
    """
    gate = _form_gate()
    if gate is None:
        return Sent(False, "no_form", "no method installed, so there is no form to send to")
    data = urllib.parse.urlencode(fields(report)).encode("utf-8")
    try:
        status, body = (post or _post)(url or post_url(), data, timeout or timeout_s())
    except urllib.error.HTTPError as exc:
        return Sent(False, "http", f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        return Sent(False, "network", str(getattr(exc, "reason", None) or exc))
    ok, detail = gate.verify_form_reply(status, body)
    if not ok:
        return Sent(False, "unconfirmed", f"HTTP {status}")
    return Sent(True, "", detail)
