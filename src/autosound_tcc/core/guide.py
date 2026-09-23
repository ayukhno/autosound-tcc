"""Where the user guide is, for the build that is running.

The guide is `docs/guide/` in this repository, and `docs/` does not ship in the `uv tool` package,
so the app opens it on GitHub, which renders the Markdown and opens a screenshot at full size on a
click. It opens at the INSTALLED version: the screens change between versions, and a link to `main`
would show a guide for a build the user does not have (hub #202 SKL-053, ask 4; tcc #49).
"""

from __future__ import annotations

import re

from autosound_tcc.core import install_report
from autosound_tcc.core.updates import TCC_REPO

QUICK_GUIDE = "QUICK-GUIDE.md"

#: A release tag (`v0.1.44`) or a candidate's (`beta-v0.1.44-rc1`). Anything else a package can be
#: installed at -- a branch, a commit -- says nothing about which release's screens these are.
_TAG = re.compile(r"^(beta-)?v\d+\.\d+\.\d+")


def guide_url(version: str, revision: str, page: str = QUICK_GUIDE) -> str:
    """The guide page on GitHub at the ref this build is: the tag it was installed at, else the
    release its version names, else `main` when neither is known."""
    if _TAG.match(revision or ""):
        ref = revision
    elif version:
        ref = f"v{version}"
    else:
        ref = "main"
    return f"{TCC_REPO}/blob/{ref}/docs/guide/{page}"


def installed_guide_url(page: str = QUICK_GUIDE) -> str:
    """`guide_url` for the build that is running."""
    return guide_url(install_report.app_version(), install_report.requested_revision(), page)
