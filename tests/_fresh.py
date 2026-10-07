"""Which Qt modules a piece of code loads, asked of a fresh interpreter (G13, #160–#163).

The modules said to have "no Qt" are proven this way; `test_i18n_features` shows the probe
going red on code that does load Qt, so a slip in the filter cannot make every probe pass.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


def qt_loaded(code: str) -> str:
    """Run `code`, then print the PySide6/shiboken6 modules now loaded; return that line."""
    probe = textwrap.dedent(code) + textwrap.dedent("""
        import sys as _sys
        print(sorted(m for m in _sys.modules if m.split(".")[0] in ("PySide6", "shiboken6")))
    """)
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                          timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip().splitlines()[-1]
