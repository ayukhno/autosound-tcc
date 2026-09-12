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
    _say(f"[stale-check]   ok, {len(alive)} valid wrappers")
