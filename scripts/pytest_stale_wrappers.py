"""pytest plugin for `#19`: after every test, walk every entry of shiboken's wrapper map.

Loaded by `scripts/ci_native_debug.sh` when a series is dispatched with `stale_check: true`, and
never otherwise.

The crash, as cdb shows it (2026-09-12, 10 captures of 10): a NEW Qt object is built, its
`tp_init` asks `cptr->metaObject()`, the generated wrapper looks its Python half up by address
alone (`BindingManager::retrieveWrapper(this)` — an `unordered_multimap`, no type check), and
`SignalManager::retrieveMetaObject` dies reading that wrapper at +0x24. A wrapper that is not
there is what an entry left behind for an object that no longer exists looks like, once a new
object lands on its address.

Under `PYTHONMALLOC=debug` freed Python memory is filled with a marker, so walking the map touches
such an entry the moment it exists — the crash moves from "whenever an address repeats" to the
end of the test that left it, and the last `[stale-check] after` line names that test.
"""
import os

import pytest


# A copy of stderr taken at import. pytest captures at the file-descriptor level, so even a raw
# `os.write(2, ...)` lands in its capture and is shown only for a failing test — and a process that
# dies never reports at all (the first local run printed nothing, 2026-09-12). `-p` plugins are
# imported before capture starts, so this descriptor still points at the real output.
_TERMINAL = os.dup(2)


def _say(text: str) -> None:
    os.write(_TERMINAL, (text + "\n").encode())


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item, nextitem):
    from shiboken6 import Shiboken

    _say(f"[stale-check] after {item.nodeid}")
    alive = Shiboken.getAllValidWrappers()
    # The other shape of a left-behind entry: the wrapper is still ALIVE (a layout keeps a Qt-made
    # QWidgetItem's wrapper as its child after Qt deleted the item), so nothing above can see it.
    # Two live wrappers of DIFFERENT types on one C++ address is that entry meeting a new object.
    # Only whole addresses count: `getCppPointer` pads its tuple with 0, and counting each element
    # read those zeros as 416 wrappers on one address (a false lead, 2026-09-12).
    by_address: dict = {}
    for wrapper in alive:
        try:
            pointers = Shiboken.getCppPointer(wrapper)
        except Exception:  # noqa: BLE001 — a wrapper we cannot read is not evidence either way
            continue
        for address in pointers:
            if address:
                by_address.setdefault(address, {})[id(wrapper)] = type(wrapper).__name__
    mixed = {address: sorted(set(kinds.values())) for address, kinds in by_address.items()
             if len(set(kinds.values())) > 1}
    for address, kinds in list(mixed.items())[:5]:
        _say(f"[stale-check]   MIXED at {hex(address)}: {kinds}")
    _say(f"[stale-check]   ok, {len(alive)} valid wrappers, {len(mixed)} mixed addresses")
