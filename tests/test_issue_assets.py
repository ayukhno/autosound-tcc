"""Publishing a screenshot that goes with a problem report (`core/issue_assets.py`, SKL-019).

The gate is the method's and is not re-implemented here — it pins the repo and the branch, refuses
without consent, and post-verifies the URL. What this adapter owns is the naming, the tolerance
about what the gate hands back, and the one thing a person must never be lied to about: how much
already went public when something stopped half-way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autosound_tcc.core import issue_assets


class _Gate:
    """The method's uploader, as documented in SKL-019, with the calls recorded."""

    def __init__(self, answer=lambda dest: f"https://raw.githubusercontent.com/x/{dest}"):
        self.calls = []
        self._answer = answer

    def upload_issue_asset(self, image_path, dest_name, *, consented=False, **kwargs):
        self.calls.append((image_path, dest_name, consented, kwargs))
        if not consented:
            raise RuntimeError("SideEffectRefused: consented=True is required")
        return self._answer(dest_name)


def test_publishing_is_offered_only_where_the_gate_has_an_uploader():
    """`available()` is what keeps the window from offering a control nothing could carry. It asks
    for the FUNCTION rather than the file, which is why it flipped on its own the day the pin
    reached v3.0.40 — the gate module itself had been there for months (#60)."""
    gate = issue_assets._gate()
    assert gate is not None, "the side-effect gate itself has been in the method for a long time"
    assert issue_assets.available() is hasattr(gate, "upload_issue_asset")


def test_a_file_is_named_by_the_run_not_by_what_it_was_called_here():
    """A local file name is the one part of a screenshot nobody checks before sending and everyone
    can read after: `passat-ivanenko-final.png` publishes a name that was never in the frame."""
    assert issue_assets.dest_name("20260903-201500", 1, Path("/x/passat-ivanenko.png")) == \
        "20260903-201500-1.png"
    assert issue_assets.dest_name("20260903-201500", 2, Path("/x/shot.JPG")) == \
        "20260903-201500-2.jpg"
    # Anything the window would not have shown as an image travels as `.png` rather than as-is.
    assert issue_assets.dest_name("20260903-201500", 3, Path("/x/report.pdf")).endswith(".png")


def test_consent_travels_to_the_gate_and_the_gate_is_what_refuses(monkeypatch, tmp_path):
    gate = _Gate()
    monkeypatch.setattr(issue_assets, "_gate", lambda: gate)
    shot = tmp_path / "a.png"
    shot.write_bytes(b"x")

    ok = issue_assets.publish([shot], consented=True)
    assert ok.ok and len(ok.urls) == 1
    assert gate.calls[0][2] is True

    refused = issue_assets.publish([shot], consented=False)
    assert not refused.ok and "consented" in refused.problem


def test_a_stop_half_way_reports_what_is_already_public(monkeypatch, tmp_path):
    """Two uploaded, the third refused: two pictures ARE public and cannot be taken back. A result
    that reported only the failure would read as "nothing was sent"."""
    def answer(dest):
        if dest.endswith("-3.png"):
            raise RuntimeError("gh: rate limited")
        return f"https://raw.githubusercontent.com/x/{dest}"

    monkeypatch.setattr(issue_assets, "_gate", lambda: _Gate(answer))
    shots = []
    for name in ("a.png", "b.png", "c.png"):
        (tmp_path / name).write_bytes(b"x")
        shots.append(tmp_path / name)

    got = issue_assets.publish(shots, consented=True)

    assert not got.ok and "rate limited" in got.problem
    assert len(got.urls) == 2, "what went up is reported, not swallowed with the failure"


@pytest.mark.parametrize("answer, expect", [
    ("https://raw.githubusercontent.com/x/1.png", "https://raw.githubusercontent.com/x/1.png"),
    ({"url": "https://raw.githubusercontent.com/x/2.png"},
     "https://raw.githubusercontent.com/x/2.png"),
    ({"stdout": "https://raw.githubusercontent.com/x/3.png\n"},
     "https://raw.githubusercontent.com/x/3.png"),
    ({"detail": "verified: https://raw.githubusercontent.com/x/4.png"},
     "https://raw.githubusercontent.com/x/4.png"),
    ({"returncode": 0}, None),
])
def test_the_url_is_read_out_of_whatever_the_gate_answers(answer, expect):
    """`guarded_run` answers with a dict; the uploader is DOCUMENTED as answering with the URL.
    Both are read rather than one of them assumed — and the tolerance turned out to be the working
    half: the real gate returns the dict. The shapes are kept side by side here so a later change
    to either one is a failing case rather than a silent `None`."""
    assert issue_assets._url_of(answer) == expect


def test_nothing_is_claimed_when_the_uploader_is_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(issue_assets, "_gate", lambda: object())
    shot = tmp_path / "a.png"
    shot.write_bytes(b"x")

    got = issue_assets.publish([shot], consented=True)

    assert not got.ok and got.urls == ()


def test_the_real_gate_answers_a_dict_and_the_url_is_still_found(tmp_path):
    """Against the METHOD'S OWN uploader, with the network faked at the runner.

    Worth its own test because the one thing this adapter could not check until the pin moved was
    the shape of the answer — and the docstring and the code disagree: `upload_issue_asset` is
    documented as returning "its verified raw URL" and actually returns `guarded_run`'s dict. The
    tolerant read was not caution, it was the difference between working and not.
    """
    shot = tmp_path / "a.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n")
    seen = {}

    def runner(argv):
        seen["argv"] = argv
        return 0, "https://raw.githubusercontent.com/ayukhno/autosound-tuning-skill/" \
                  "issue-assets/issues/20260903-1.png\n", ""

    got = issue_assets.publish([shot], consented=True, runner=runner)

    assert got.ok, got.problem
    assert got.urls[0].endswith("/issues/20260903-1.png")
    # The repo and the branch are the gate's, hardcoded there; the caller only names the file.
    assert seen["argv"][:4] == ["gh", "api", "-X", "PUT"]
    assert "ayukhno/autosound-tuning-skill" in seen["argv"][4]


def test_the_gate_refuses_a_publish_nobody_consented_to(tmp_path):
    """The method's own rail, not ours: this is the assertion that proves the window's `consented`
    is load-bearing rather than decorative."""
    shot = tmp_path / "a.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n")

    got = issue_assets.publish([shot], consented=False, runner=lambda argv: (0, "", ""))

    assert not got.ok and "SIDE-EFFECT REFUSED" in got.problem
