"""Make Windows call this process our application instead of Python's.

Sibling of `macos_identity`, same disease on the other operating system. Qt's
`setWindowIcon` decides what the WINDOW carries — its title bar and its taskbar thumbnail —
and that has been right all along. It does not decide what the taskbar BUTTON carries.
Windows picks that from the application the process claims to be: its AppUserModelID. A
process that never claims one inherits the identity of the executable that hosts it.

Ours is hosted by Python. The Windows launcher `autosound-tcc-gui.exe` is a uv trampoline that
starts the interpreter as a child, so the process that owns the window is `pythonw.exe`, and
the taskbar reads out Python's identity and draws Python's icon next to our window. Measured,
not assumed: the user's Parallels VM on 2026-08-23 showed the generic Python icon on the
taskbar button while the hover thumbnail above it — the same window, its own icon — showed
ours (the UTM VM beside it did not, which is what a cached, install-dependent identity looks
like; the claim below does not depend on either).

`SetCurrentProcessExplicitAppUserModelID` is the documented way to say otherwise, and it must
be called BEFORE the first window exists: Windows resolves the identity when the window is
created and does not go back to ask again.

**What this does not do.** A `.lnk` can also carry the same id (`System.AppUserModel.ID`), and
that is what makes a PINNED shortcut and the running window one taskbar button. Writing that
property needs `IPropertyStore` — the `WScript.Shell` COM object `desktop_entry` writes
shortcuts with cannot set it. Left undone deliberately: it is a grouping nicety, and the icon
is the bug.
"""

from __future__ import annotations

import os

#: Deliberately the same string as `desktop_entry.BUNDLE_ID`, the macOS bundle identifier: one
#: application, one name for it, whichever operating system is asking. Imported rather than
#: retyped so it cannot drift -- `desktop_entry` imports nothing but the standard library at
#: module level (its one import of `app` is inside a function), so this is not a cycle.
from autosound_tcc.core.desktop_entry import BUNDLE_ID as APP_USER_MODEL_ID


def claim() -> bool:
    """Tell Windows this process is us. True when it took, False anywhere it does not apply.

    Never raises, for the same reason `macos_identity.rename` never raises: a window that
    opens under the wrong icon is a blemish, and a window that does not open is an app.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes

        # Declared rather than defaulted. With `restype = HRESULT`, ctypes turns a failing
        # call into OSError instead of handing back an integer nobody reads; `c_wchar_p` is
        # what the API takes (PCWSTR) and getting it wrong would pass a byte string.
        set_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_id.argtypes = [ctypes.c_wchar_p]
        set_id.restype = ctypes.HRESULT
        set_id(APP_USER_MODEL_ID)
    except (AttributeError, OSError, ImportError):
        return False
    return True
