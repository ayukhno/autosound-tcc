"""Where the user guide is, for the build that is running.

The guide is `docs/guide/` in this repository, and `docs/` does not ship in the `uv tool` package,
so the app opens it on GitHub, which renders the Markdown and opens a screenshot at full size on a
click. It opens at the INSTALLED version: the screens change between versions, and a link to `main`
would show a guide for a build the user does not have (hub #202 SKL-053, ask 4; tcc #49).

The method's own target-curve guide is linked the same way, at the tag of the method this TCC runs:
the header's «?» after the curve opens it (finding 134, tcc#120).
"""

from __future__ import annotations

import re

from autosound_tcc.core import install_report
from autosound_tcc.core.updates import SKILL_REPO, TCC_REPO

#: The three pages of «Посібники» in the main menu (finding 134, tcc#120): the short tour, the
#: window panel by panel, and TCC's page on the target curve -- where the header shows it and what
#: the tool's buttons do. What a target curve IS is the method's guide below, which that page links.
QUICK_GUIDE = "QUICK-GUIDE.md"
REFERENCE = "REFERENCE.md"
HOUSE_CURVE = "HOUSE-CURVE.md"

#: The method's guide to target curves -- what one is, how to choose and build it -- from the root
#: of the method's repository.
METHOD_TARGET_GUIDE = (
    "skills/autosound-tuning/references/patterns/target-curves/target_curves_guide.md"
)

#: A release tag (`v0.1.44`) or a candidate's (`beta-v0.1.44-rc1`). Anything else a package can be
#: installed at -- a branch, a commit -- says nothing about which release's screens these are.
_TAG = re.compile(r"^(beta-)?v\d+\.\d+\.\d+")
#: A method release number as its manifest writes it (`3.0.64`); its tag is the same with a `v`.
_METHOD_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


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


def method_guide_url(version: str, path: str = METHOD_TARGET_GUIDE) -> str:
    """A page of the method on GitHub at the tag of its release `version`, else `main`.

    The method installs from a release tag (`updates.SKILL_TAG_GLOB`), so the version its manifest
    carries names the tag the page is read at. Anything else -- no manifest, a version that names
    no release -- would make up a tag that is not there, and `main` at least opens."""
    ref = f"v{version}" if _METHOD_VERSION.match(version or "") else "main"
    return f"{SKILL_REPO}/blob/{ref}/{path}"


def method_target_guide_url() -> str:
    """`method_guide_url` of the target-curve guide, for the method this TCC runs."""
    return method_guide_url(install_report.skill_version())
