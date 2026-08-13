"""Make macOS call this process by its own name instead of "python".

The `.app` bundle sets `CFBundleName` correctly and macOS ignores it, because macOS does not ask
the bundle you launched — it asks the bundle that owns the RUNNING EXECUTABLE, and that is decided
by `_NSGetExecutablePath()`. Our launcher is a shell script that `exec`s the installed
`autosound-tcc`, which is a Python console script, so by the time there is a GUI the executable is

    …/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python

— an Apple-shipped bundle whose `CFBundleName` is "Python". Measured here, not assumed: a probe
inside a hand-built bundle reported exactly that path. Hence the Dock tile reading "python3.12"
and the menu bar reading "python" on a fresh install (user, 2026-08-13).

The fix that does not require a compiled launcher stub (py2app/briefcase territory, and a second
copy of the interpreter to keep in step) is to correct the info dictionary of the main bundle in
memory, before Qt reads it. This is the long-standing macOS-Python answer to this exact problem.

Qt reads that dictionary while the Cocoa platform plugin starts, so this must run BEFORE the
`QApplication` is constructed. It is also why `setApplicationName()` alone never fixed it: that is
Qt's own name, and on macOS the bundle wins.
"""

from __future__ import annotations

import sys
from typing import Optional


def display_name() -> Optional[str]:
    """What macOS currently thinks this application is called, or None if it cannot be asked."""
    handles = _core_foundation()
    if handles is None:
        return None
    cf, bundle = handles
    key = _cfstring(cf, "CFBundleName")
    if key is None:
        return None
    value = cf.CFBundleGetValueForInfoDictionaryKey(bundle, key)
    if not value:
        return None
    buffer = (_ctypes().c_char * 256)()
    ok = cf.CFStringGetCString(value, buffer, 256, 0x08000100)  # kCFStringEncodingUTF8
    return buffer.value.decode("utf-8", "replace") if ok else None


def rename(name: str) -> bool:
    """Tell macOS this process is `name`. True when it took, False on any machine that cannot.

    Never raises. It reaches into CoreFoundation through `ctypes`, which is fine when it works and
    must be nothing at all when it does not: a window that opens with the wrong name in the menu
    bar is a blemish, and a window that does not open is an app.
    """
    handles = _core_foundation()
    if handles is None:
        return False
    cf, bundle = handles
    info = cf.CFBundleGetInfoDictionary(bundle)
    key = _cfstring(cf, "CFBundleName")
    value = _cfstring(cf, name)
    if not info or key is None or value is None:
        return False
    try:
        cf.CFDictionarySetValue(info, key, value)
    except Exception:  # noqa: BLE001 — see docstring
        return False
    return display_name() == name


def _ctypes():
    import ctypes

    return ctypes


def _core_foundation():
    """The CoreFoundation handle and this process's main bundle, with signatures declared.

    Declaring `restype`/`argtypes` is not tidiness: ctypes defaults to `c_int` returns, which
    truncates every one of these 64-bit pointers and hands back a dangling half.
    """
    if sys.platform != "darwin":
        return None
    try:
        import ctypes
        import ctypes.util

        path = ctypes.util.find_library("CoreFoundation")
        if not path:
            return None
        cf = ctypes.cdll.LoadLibrary(path)
        cf.CFBundleGetMainBundle.restype = ctypes.c_void_p
        cf.CFBundleGetInfoDictionary.restype = ctypes.c_void_p
        cf.CFBundleGetInfoDictionary.argtypes = [ctypes.c_void_p]
        cf.CFBundleGetValueForInfoDictionaryKey.restype = ctypes.c_void_p
        cf.CFBundleGetValueForInfoDictionaryKey.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFStringGetCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32
        ]
        cf.CFDictionarySetValue.restype = None
        cf.CFDictionarySetValue.argtypes = [ctypes.c_void_p] * 3
        bundle = cf.CFBundleGetMainBundle()
        return (cf, bundle) if bundle else None
    except (OSError, AttributeError, ImportError):
        return None


def _cfstring(cf, text: str):
    return cf.CFStringCreateWithCString(None, text.encode("utf-8"), 0x08000100)
