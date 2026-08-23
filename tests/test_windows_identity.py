"""The taskbar button drew Python's icon next to our window (user's Parallels VM, 2026-08-23).

The window's own icon was ours all along — the hover thumbnail proved it. What was Python's was
the process's IDENTITY: a uv trampoline starts the interpreter as a child, so without an explicit
AppUserModelID the taskbar asks `pythonw.exe` what application this is, and draws its icon.
`core/windows_identity.py` claims one before the first window exists.
"""

from __future__ import annotations

import os

import pytest

from autosound_tcc.core import desktop_entry, windows_identity


def test_the_id_is_the_application_s_one_name():
    """Not a second spelling of the same application. macOS keys a bundle to `BUNDLE_ID` and
    Windows keys a taskbar button to this; they are one identity and must stay one string."""
    assert windows_identity.APP_USER_MODEL_ID == desktop_entry.BUNDLE_ID


def test_the_id_is_one_windows_will_accept():
    """Windows rejects an AppUserModelID longer than 128 characters or containing a space, and
    rejecting it is silent — the taskbar simply goes on showing the host executable's icon."""
    assert len(windows_identity.APP_USER_MODEL_ID) <= 128
    assert " " not in windows_identity.APP_USER_MODEL_ID


@pytest.mark.skipif(os.name != "nt", reason="the whole question is a Windows one")
def test_windows_takes_the_claim():
    assert windows_identity.claim() is True


@pytest.mark.skipif(os.name == "nt", reason="the negative case is every other machine")
def test_it_is_silent_where_it_does_not_apply():
    """Reaching into shell32 through ctypes: on a machine where that cannot work this has to be
    nothing at all, not an exception on the path that opens the window."""
    assert windows_identity.claim() is False
