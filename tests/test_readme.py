"""The README's install line installs the release it was written for (tcc#174).

That line is what a person pastes when they install by hand. With no tag it installs whatever is
on `main` that day, finished or not — the reason TCC's own updater asks for a release tag since
F-024 (`core/updates.py`, `TCC_TAG_GLOB`). With a tag it goes stale the moment the version moves,
and nothing in the release reminds anyone: this test is that reminder, so the version commit
moves the README together with `pyproject.toml`.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from autosound_tcc.core import updates

ROOT = Path(__file__).resolve().parents[1]


def test_the_readmes_install_line_names_this_versions_tag():
    version = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    lines = [line for line in readme.splitlines()
             if line.startswith("uv tool install") and "autosound-tcc[" in line]

    assert len(lines) == 1, f"README.md should carry one install line for TCC, found: {lines}"
    named = re.search(re.escape(f"git+{updates.TCC_REPO}") + r"@(v[^'\"\s]+)", lines[0])
    assert named, f"README.md's install line names no tag, so it installs `main`: {lines[0]}"
    assert named.group(1) == f"v{version}", (
        f"README.md's install line installs {named.group(1)} and pyproject.toml says {version} — "
        f"the version commit moves both")
