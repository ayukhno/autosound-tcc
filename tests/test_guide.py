"""The user guide lives online, in this repository, and the app opens it at the INSTALLED version.

`docs/` does not ship in the `uv tool` package, so the guide is a page on GitHub. The screens change
between versions, and a link to `main` would show a guide for a build the user does not have
(hub #202 SKL-053, ask 4; tcc #49).
"""

from __future__ import annotations

from autosound_tcc.core import guide

_BLOB = "https://github.com/ayukhno/autosound-tcc/blob"


def test_the_tag_the_app_was_installed_at_is_the_one_linked():
    assert guide.guide_url("0.1.44", "v0.1.44") == f"{_BLOB}/v0.1.44/docs/guide/QUICK-GUIDE.md"


def test_a_candidate_build_links_its_own_candidate_tag_not_the_release_in_its_metadata():
    # A candidate's metadata may still carry the release before it (RELEASE-CHANNEL.md §11.3).
    assert guide.guide_url("0.1.43", "beta-v0.1.44-rc1") == (
        f"{_BLOB}/beta-v0.1.44-rc1/docs/guide/QUICK-GUIDE.md"
    )


def test_without_a_requested_tag_the_version_names_it():
    assert guide.guide_url("0.1.44", "") == f"{_BLOB}/v0.1.44/docs/guide/QUICK-GUIDE.md"


def test_a_ref_that_is_not_a_tag_does_not_become_the_link():
    # Installed from a branch or a commit: the version still says which release this is.
    assert guide.guide_url("0.1.44", "main") == f"{_BLOB}/v0.1.44/docs/guide/QUICK-GUIDE.md"


def test_with_nothing_known_the_guide_opens_on_main():
    assert guide.guide_url("", "") == f"{_BLOB}/main/docs/guide/QUICK-GUIDE.md"


def test_another_page_of_the_guide_can_be_asked_for():
    assert guide.guide_url("0.1.44", "v0.1.44", "HOUSE-CURVE.md") == (
        f"{_BLOB}/v0.1.44/docs/guide/HOUSE-CURVE.md"
    )
