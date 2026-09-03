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


def test_this_checkout_cannot_publish_yet_and_says_so_plainly():
    """Not a placeholder assertion: the pin is behind the method that has the uploader (#60), and
    `available()` is what keeps the window from offering a control nothing could carry. The day
    the pin moves this flips on its own — which is the point of asking the FUNCTION, not the file.
    """
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
    """`guarded_run` answers with a dict; the uploader is documented as answering with the URL.
    Both are read rather than one of them assumed — this call cannot be exercised against the real
    gate until the pin reaches it (#60), and guessing which one would be the whole bug."""
    assert issue_assets._url_of(answer) == expect


def test_nothing_is_claimed_when_the_uploader_is_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(issue_assets, "_gate", lambda: object())
    shot = tmp_path / "a.png"
    shot.write_bytes(b"x")

    got = issue_assets.publish([shot], consented=True)

    assert not got.ok and got.urls == ()
