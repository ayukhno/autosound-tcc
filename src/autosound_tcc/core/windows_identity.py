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

## A pin is not the window, and there are TWO routes to one

It took a second measurement to learn that, so it is written here rather than left to be
rediscovered. The two routes read different properties:

1. **Pinning a SHORTCUT.** The `.lnk` must carry `System.AppUserModel.ID`, and
   `desktop_entry._stamp_windows` writes it through `IPropertyStore` from PowerShell. (An
   earlier version of this docstring said that half was "left undone deliberately". It was
   true when it was written and stopped being true in the same change that fixed F-032; the
   line is gone rather than corrected in place, because a docstring nobody can trust is worse
   than one that is merely thin — F-037.)

2. **Pinning the LIVE WINDOW.** Windows does not read the window's icon here at all. It looks
   for a shortcut carrying the same id as the PROCESS, and when it cannot find one it falls
   back to the process image — `pythonw.exe`. That is the whole of F-037, measured on Windows
   11 on 2026-08-28: the pin was called `Python`, wore Python's icon, and after the app closed
   a click on it did nothing whatsoever, silently, because it was starting a bare interpreter
   with no script to run.

`stamp_window` below is route 2's half. `SHGetPropertyStoreForWindow` reaches the property
store of the window itself, and the three relaunch properties say what to PUT in the pin —
which command to run, which name to show, which icon to draw — instead of letting Windows
infer it from whoever hosts the process.

**Why this is not a duplicate of the `.lnk` stamp.** Stamping the shortcut is allowed to fail:
`Add-Type` has every right not to compile on a given machine, and `_stamp_windows` deliberately
survives that with a note. When it does fail, route 1 degrades to exactly the F-037 symptom
while the install still looks complete. The relaunch properties do not depend on any shortcut
existing, so the two together are belt and braces on a fault that is invisible from the outside.

**What is measured and what is not.** Everything above the relaunch properties was measured on
a VM. The relaunch half is written from the Windows API contract and cannot be exercised on
macOS at all — `tests/test_windows_identity.py` holds its pure half, and the live check belongs
to the next Windows session (`docs/TODO.md`, "Windows-сеанс").
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

#: Deliberately the same string as `desktop_entry.BUNDLE_ID`, the macOS bundle identifier: one
#: application, one name for it, whichever operating system is asking. Imported rather than
#: retyped so it cannot drift -- `desktop_entry` imports nothing but the standard library at
#: module level (its one import of `app` is inside a function), so this is not a cycle.
from autosound_tcc.core.desktop_entry import BUNDLE_ID as APP_USER_MODEL_ID

#: The four properties this module writes, by their `pid` inside the AppUserModel property set.
#: Named constants rather than literals at the call site because a wrong number here is not an
#: error anywhere -- it writes a real property that nothing reads, and the pin stays Python's.
PID_RELAUNCH_COMMAND = 2
PID_RELAUNCH_ICON = 3
PID_RELAUNCH_DISPLAY_NAME = 4
PID_APP_ID = 5


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_uint32)]


class _PROPVARIANT(ctypes.Structure):
    """Big enough rather than exact.

    The real union is 8 bytes on x86 and 16 on x64; sixteen is taken here on both, so the
    structure is never SMALLER than what `InitPropVariantFromString` writes into it. Over-
    allocating a stack structure costs nothing and under-allocating one corrupts the frame,
    which is the kind of bug that shows up as an unrelated crash three functions later.
    """

    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("data", ctypes.c_byte * 16),
    ]


#: `PKEY_AppUserModel_*` all live in one property set -- {9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}.
APP_USER_MODEL_FMTID = _GUID(
    0x9F4C2855, 0x9F79, 0x4B39, (ctypes.c_ubyte * 8)(0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3)
)

#: IID_IPropertyStore -- {886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}.
IID_IPROPERTYSTORE = _GUID(
    0x886D8EEB, 0x8CF2, 0x4446, (ctypes.c_ubyte * 8)(0x8D, 0x02, 0xCD, 0xBA, 0x1D, 0xBD, 0xCF, 0x99)
)

#: Slots in `IPropertyStore`'s vtable. IUnknown takes the first three, so the interface's own
#: methods start at 3: GetCount, GetAt, GetValue, SetValue, Commit.
_VT_RELEASE = 2
_VT_SET_VALUE = 6
_VT_COMMIT = 7


def claim() -> bool:
    """Tell Windows this process is us. True when it took, False anywhere it does not apply.

    Never raises, for the same reason `macos_identity.rename` never raises: a window that
    opens under the wrong icon is a blemish, and a window that does not open is an app.
    """
    if os.name != "nt":
        return False
    try:
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


def relaunch_properties(
    launcher: Path | str | None = None,
    ico: Path | str | None = None,
    display_name: str | None = None,
) -> dict[int, str]:
    """What the pin should say, as `{pid: string}`. Pure — no Windows, no window, no COM.

    Split out so the part that can be wrong on any machine is checkable on any machine. What is
    left in `stamp_window` is the call itself, and that one genuinely needs Windows.

    Each property is omitted rather than written empty when its source is missing: an empty
    `RelaunchCommand` is a pin that starts nothing, which is the F-037 symptom arrived at from
    the other direction.
    """
    props: dict[int, str] = {PID_APP_ID: APP_USER_MODEL_ID}
    if launcher:
        # Quoted because it is a COMMAND LINE, not a path, and `C:\Program Files\...` splits at
        # the space into a program nobody has and an argument nobody reads.
        props[PID_RELAUNCH_COMMAND] = f'"{launcher}"'
    if ico:
        # `path,index` -- an icon RESOURCE, and the index is not optional. Unquoted: this one is
        # parsed by the shell's resource reader, which treats the quotes as part of the path.
        props[PID_RELAUNCH_ICON] = f"{ico},0"
    if display_name:
        # The one property whose accepted form is not certain from the documentation, which asks
        # for an indirect resource reference (`@some.dll,-42`). A plain string is what shipping
        # applications put here and what Windows shows in practice. If it turns out to be
        # ignored, the pin falls back to the executable's own name -- worse than "Autosound TCC"
        # and no worse than today's `Python`, so it is written rather than left out pending a
        # measurement it cannot get on this machine.
        props[PID_RELAUNCH_DISPLAY_NAME] = display_name
    return props


def stamp_window(hwnd: int, props: dict[int, str] | None = None) -> bool:
    """Write the relaunch properties onto a live window. True when all of them took.

    `hwnd` comes from Qt (`int(window.winId())`) and must be a REAL window handle, so this is
    called after the widget has a native one — before `show()` is early enough, and earlier than
    that there is nothing to stamp.

    Never raises, same contract as `claim`: this decides what a pin looks like, and no icon is
    worth a window that does not open. Every failure is the same answer, `False`, because there
    is nothing the caller could usefully do differently for any of them.
    """
    if os.name != "nt" or not hwnd:
        return False
    if props is None:
        props = relaunch_properties(*_window_sources())
    if not props:
        return False
    try:
        store = ctypes.c_void_p()
        get_store = ctypes.windll.shell32.SHGetPropertyStoreForWindow
        get_store.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)
        ]
        get_store.restype = ctypes.HRESULT
        get_store(ctypes.c_void_p(hwnd), ctypes.byref(IID_IPROPERTYSTORE), ctypes.byref(store))
        if not store:
            return False

        # COM through ctypes is a vtable walk: the object's first member is a pointer to its
        # function table, and each entry is called with the object itself as the first argument.
        vtable = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        set_value = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(_PROPERTYKEY),
            ctypes.POINTER(_PROPVARIANT),
        )(vtable[_VT_SET_VALUE])
        commit = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtable[_VT_COMMIT])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[_VT_RELEASE])

        init_string = ctypes.windll.propsys.InitPropVariantFromString
        init_string.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(_PROPVARIANT)]
        init_string.restype = ctypes.HRESULT
        clear = ctypes.windll.ole32.PropVariantClear
        clear.argtypes = [ctypes.POINTER(_PROPVARIANT)]

        try:
            for pid, value in props.items():
                key = _PROPERTYKEY(APP_USER_MODEL_FMTID, pid)
                variant = _PROPVARIANT()
                # `InitPropVariantFromString` allocates the string with the COM allocator, which
                # is what `PropVariantClear` frees -- hence the pairing, and hence `finally`: the
                # store copies the value on SetValue, so ours is ours to release either way.
                init_string(value, ctypes.byref(variant))
                try:
                    set_value(store, ctypes.byref(key), ctypes.byref(variant))
                finally:
                    clear(ctypes.byref(variant))
            commit(store)
        finally:
            release(store)
    except (AttributeError, OSError, ImportError, ValueError):
        return False
    return True


def _window_sources() -> tuple[Path | None, Path | None, str]:
    """Launcher, icon and display name, from the modules that own each.

    Imported inside the function for the reason `desktop_entry._assets` gives: `app` imports
    this package, so a module-level import back into it is a cycle.
    """
    from autosound_tcc.app import APP_DISPLAY_NAME, APP_ICO
    from autosound_tcc.core.desktop_entry import resolve_launcher

    ico = APP_ICO if APP_ICO.is_file() else None
    return resolve_launcher(), ico, APP_DISPLAY_NAME
