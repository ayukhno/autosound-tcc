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


# ── the relaunch half (F-037) ─────────────────────────────────────────────────────────────────
#
# Claiming the id fixed the process. It did NOT fix a pin of the live window: Windows builds that
# from the window's own relaunch properties, and with none set falls back to the process image --
# `pythonw.exe`, hence a pin called "Python" that silently started nothing (Windows 11, 2026-08-28).
# None of this can be exercised on macOS, so what is testable is split out and tested: the strings
# that go into the properties, and the numbers that say which properties they are.


def test_the_property_ids_are_the_documented_ones():
    """A wrong pid is not an error anywhere — it writes a real property nothing reads, and the pin
    stays Python's. So the numbers are pinned here against the `PKEY_AppUserModel_*` set."""
    assert windows_identity.PID_RELAUNCH_COMMAND == 2
    assert windows_identity.PID_RELAUNCH_ICON == 3
    assert windows_identity.PID_RELAUNCH_DISPLAY_NAME == 4
    assert windows_identity.PID_APP_ID == 5


def test_the_property_set_is_the_appusermodel_one():
    """Same failure as a wrong pid, one level up: a wrong fmtid writes into a property set nobody
    asks about. {9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}."""
    fmtid = windows_identity.APP_USER_MODEL_FMTID
    assert (fmtid.Data1, fmtid.Data2, fmtid.Data3) == (0x9F4C2855, 0x9F79, 0x4B39)
    assert bytes(fmtid.Data4) == bytes((0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3))


def test_the_relaunch_command_is_quoted():
    """It is a command line, not a path. `C:\\Program Files\\...` unquoted splits at the space into
    a program that does not exist — which is the F-037 symptom reached from the other direction."""
    props = windows_identity.relaunch_properties(launcher=r"C:\Program Files\tcc\tcc-gui.exe")
    assert props[windows_identity.PID_RELAUNCH_COMMAND] == r'"C:\Program Files\tcc\tcc-gui.exe"'


def test_the_icon_is_a_resource_reference_and_is_not_quoted():
    """`path,index`, read by the shell's resource parser, which takes quotes as part of the path."""
    props = windows_identity.relaunch_properties(ico=r"C:\tcc\app-icon.ico")
    assert props[windows_identity.PID_RELAUNCH_ICON] == r"C:\tcc\app-icon.ico,0"


def test_a_missing_source_omits_its_property_rather_than_writing_it_empty():
    """An empty RelaunchCommand is a pin that starts nothing — exactly the fault being fixed. The
    id is the one property with no source to be missing, so it is always there."""
    props = windows_identity.relaunch_properties()
    assert props == {windows_identity.PID_APP_ID: windows_identity.APP_USER_MODEL_ID}


def test_the_window_is_stamped_with_the_same_identity_the_process_claims():
    """Two calls, two Windows questions, one application. If these ever differ, the pin and the
    running window are two taskbar buttons again — the bug this whole module exists for."""
    props = windows_identity.relaunch_properties(launcher="x", ico="y", display_name="z")
    assert props[windows_identity.PID_APP_ID] == windows_identity.APP_USER_MODEL_ID


def test_stamp_window_refuses_a_handle_that_is_not_one():
    """Zero is what `winId()` gives for a widget with no native window yet. Writing a property
    store for it is not a thing that can work, and this must not be where the app raises."""
    assert windows_identity.stamp_window(0) is False


@pytest.mark.skipif(os.name == "nt", reason="the negative case is every other machine")
def test_stamping_is_silent_where_it_does_not_apply():
    assert windows_identity.stamp_window(12345) is False


def test_startup_stamps_the_window_it_just_built():
    """The seam is only useful if it is called. `main` builds the window and must stamp it before
    `show()` — a pin can be made the moment the window is on screen, and the properties have to be
    there already."""
    import inspect

    from autosound_tcc import app

    source = inspect.getsource(app.main)
    assert "windows_identity.stamp_window(int(window.winId()))" in source
    assert source.index("stamp_window") < source.index("window.show()")
