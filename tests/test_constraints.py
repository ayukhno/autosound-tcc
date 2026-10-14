"""`constraints.txt` says what `uv.lock` says (tcc#194, finding 158).

The update and the install hold uv to this file, so a person gets the set CI ran (`uv run
--locked`) and not whatever the index has that day: the update of 2026-10-14 resolved afresh and
installed PySide6 6.12.0 against the lock's 6.11.2. The file is committed, because the updater
reads it out of the signed tag's tree and a git install has no build step to make it in — so it
can go stale, and these tests are what stops a tag carrying a stale one. `make constraints`
writes it again.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent
CONSTRAINTS = ROOT / "constraints.txt"
LOCK = ROOT / "uv.lock"

#: `make constraints`, minus the output file: the export these tests hold the file to.
EXPORT = ["uv", "export", "--frozen", "--extra", "gui", "--extra", "claude", "--no-dev",
          "--no-emit-project", "--no-hashes", "--no-annotate"]

def _name(text: str) -> str:
    return re.sub(r"[-_.]+", "-", text).lower()


def _pins(text: str) -> set[tuple[str, str, str]]:
    """Every line as (normalised name, version, normalised marker). The marker counts: numpy and
    scipy are pinned twice, by Python version, and two `numpy==` lines without theirs would
    conflict and fail every constrained update (the review of #194). Anything that is not a
    comment or an exact pin fails: a constraint that is not one holds uv to nothing."""
    pins = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pin = Requirement(line)
        specs = list(pin.specifier)
        assert len(specs) == 1 and specs[0].operator == "==" and not pin.extras and not pin.url, (
            f"not an exact pin: {line!r}")
        pins.add((_name(pin.name), specs[0].version, str(pin.marker or "")))
    return pins


def test_every_pin_is_the_version_the_lock_holds():
    """No uv needed: each pin is a package at a version `uv.lock` has. A relock that moved a
    version and left this file behind fails here."""
    lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    locked = {(_name(package["name"]), package["version"]) for package in lock["package"]
              if "version" in package}
    pins = {(name, version) for name, version, _marker in
            _pins(CONSTRAINTS.read_text(encoding="utf-8"))}

    assert pins, "constraints.txt pins nothing"
    assert pins <= locked, f"pinned, but not what uv.lock holds: {sorted(pins - locked)}"
    assert "autosound-tcc" not in {name for name, _ in pins}, "the project itself is no constraint"
    for name in ("pyside6-essentials", "shiboken6", "claude-agent-sdk", "mcp", "uvicorn"):
        assert name in {pinned for pinned, _ in pins}, f"{name} is installed and not pinned"


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv, which CI and `make` both run")
def test_the_file_is_the_lock_s_export():
    """And the whole set: what `make constraints` would write now — a dependency added to the lock
    and missing here would install unpinned, and a marker lost here would make two pins of one
    package conflict. Compared as parsed pins, not as text, so a uv that words a marker
    differently is not a failure."""
    exported = subprocess.run(EXPORT, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                              timeout=60, check=True).stdout

    assert _pins(CONSTRAINTS.read_text(encoding="utf-8")) == _pins(exported), (
        "constraints.txt is not uv.lock's export — run `make constraints`")
