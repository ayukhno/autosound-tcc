"""The Dock said "python3.12" and the menu bar said "python" on a fresh install.

The `.app` bundle had the right `CFBundleName` all along. macOS ignores it: it asks the bundle
that owns the RUNNING EXECUTABLE, and a launcher that `exec`s a Python console script leaves that
as Apple's own `Python.app`. `core/macos_identity.py` corrects the main bundle's info dictionary
in memory instead, which is the fix that needs no compiled launcher stub.
"""

from __future__ import annotations

import sys

import pytest

from autosound_tcc.core import macos_identity


@pytest.mark.skipif(sys.platform != "darwin", reason="the whole question is a macOS one")
def test_the_process_can_be_renamed_and_the_rename_reads_back():
    """Both halves matter: `rename` returning True is only worth anything if what macOS now
    reports is the new name — it confirms by reading back rather than by hoping."""
    before = macos_identity.display_name()
    assert before, "macOS always has a name for a process; None means we failed to ask"

    assert macos_identity.rename("Autosound TCC test") is True
    assert macos_identity.display_name() == "Autosound TCC test"

    macos_identity.rename(before)  # leave the process as it was found


def test_it_is_silent_where_it_does_not_apply(monkeypatch):
    """Every path is guarded because this reaches into CoreFoundation through ctypes: a window
    that opens with the wrong name is a blemish, a window that does not open is an app."""
    monkeypatch.setattr(sys, "platform", "linux")

    assert macos_identity.rename("anything") is False
    assert macos_identity.display_name() is None
