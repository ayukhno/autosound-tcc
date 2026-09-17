"""Reports without GitHub: text sent straight to the Arbiter's Google Form (TODO F-042).

The window's only report route used to be a GitHub issue, and a person without an account — the
ordinary tester since the installer stopped installing `gh` unless asked — had nowhere to say that
something broke. The Arbiter's decision (2026-09-17): his Google Form, sent from the window with no
browser and no sign-in, into a sheet on his Drive. **Text only.** A file question would make Google
demand a sign-in for the whole form, and that would close it to a session sending the same way
(autosound-hub #157, TCC-017) — pictures keep going through GitHub, or separately.

The destination is fixed here, in code, and nowhere else: a place that decides where a person's
words go is a place that can be talked into sending them somewhere else — the posture of the
method's side-effect gate (`rew_tool/gates/side_effect.py`), kept for a destination of our own.

"Sent" is what the form CONFIRMS, never what the request did. The form answers 200 with its own page
when it did not take the answer (closed, changed, a check for robots), so the one proof is the
confirmation page's "submit another response" link — measured on 2026-09-17, one test entry that
landed in the sheet, and absent from the form page itself.
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
#: The form's one paragraph question; the whole text goes into it.
FORM_FIELD = "entry.970390217"
#: Only the confirmation page carries it: the link to submit another response.
ACCEPTED_MARKER = "usp=form_confirm"
#: What the first line may call a report. The author sorts the sheet by it, so a fourth spelling
#: is a row nobody finds.
KINDS = ("problem", "wish", "feedback")
TIMEOUT_S = 20


@dataclass(frozen=True)
class Sent:
    """`reason` is "" when the form confirmed, else "unconfirmed", "network" or "http"."""

    ok: bool
    reason: str = ""
    detail: str = ""


def first_line(kind: str, lang: str, *, tcc=None, method=None, system=None) -> str:
    """`[wish] · TCC 0.1.41 · method 3.0.54 · Windows 11 · lang=uk` — one line the author can sort by.

    `tcc`, `method` and `system` are read from this installation when not given. What cannot be
    told is written as "unknown", never left out: a missing field reads as a row cut short.
    """
    if kind not in KINDS:
        raise ValueError(f"a report is one of {', '.join(KINDS)}, not {kind!r}")
    if tcc is None:
        tcc = install_report.app_version()
    if method is None:
        method = install_report.skill_version()
    if system is None:
        system = f"{platform.system()} {platform.release()}".strip()
    return (f"[{kind}] · TCC {tcc or 'unknown'} · method {method or 'unknown'} · "
            f"{system or 'unknown'} · lang={lang}")


def compose(first: str, text: str, attachment: str = "") -> str:
    """The first line, the person's words under it, and what goes with them under those."""
    parts = [first, text.strip()]
    if attachment.strip():
        parts.append(attachment.strip())
    return "\n\n".join(parts)


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


def send(text: str, *, url: str = FORM_POST_URL, post=_post, timeout: float = TIMEOUT_S) -> Sent:
    """Post `text` to the form and say whether the form confirmed it. Never raises."""
    data = urllib.parse.urlencode({FORM_FIELD: text}).encode("utf-8")
    try:
        status, body = post(url, data, timeout)
    except urllib.error.HTTPError as exc:
        return Sent(False, "http", f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        return Sent(False, "network", str(getattr(exc, "reason", None) or exc))
    if status != 200 or ACCEPTED_MARKER not in body:
        return Sent(False, "unconfirmed", f"HTTP {status}")
    return Sent(True)
