"""The user guide lives online, in this repository, and the app opens it at the INSTALLED version.

`docs/` does not ship in the `uv tool` package, so the guide is a page on GitHub. The screens change
between versions, and a link to `main` would show a guide for a build the user does not have
(hub #202 SKL-053, ask 4; tcc #49).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from autosound_tcc.core import guide, install_report, vendor_loader

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


# ---- the three pages in the menu, and the method's guide behind the header's «?» (tcc#120) ------

_METHOD_BLOB = "https://github.com/ayukhno/autosound-tuning-skill/blob"
_METHOD_GUIDE = "skills/autosound-tuning/references/patterns/target-curves/target_curves_guide.md"
_GUIDE_DIR = Path(__file__).parents[1] / "docs" / "guide"


def test_the_three_guides_of_the_menu_open_at_the_installed_ref(monkeypatch):
    """«Посібники» in the main menu (finding 134): the quick guide, the full one and the
    target-curve page, each at the tag this build was installed at."""
    monkeypatch.setattr(install_report, "app_version", lambda: "0.1.46")
    monkeypatch.setattr(install_report, "requested_revision", lambda: "v0.1.46")

    assert [guide.installed_guide_url(page) for page in
            (guide.QUICK_GUIDE, guide.REFERENCE, guide.HOUSE_CURVE)] == [
        f"{_BLOB}/v0.1.46/docs/guide/QUICK-GUIDE.md",
        f"{_BLOB}/v0.1.46/docs/guide/REFERENCE.md",
        f"{_BLOB}/v0.1.46/docs/guide/HOUSE-CURVE.md",
    ]


def test_every_page_the_menu_names_is_in_the_guide():
    # A name with no file behind it is a 404 at every tag, and nothing else would say so.
    for page in (guide.QUICK_GUIDE, guide.REFERENCE, guide.HOUSE_CURVE):
        assert (_GUIDE_DIR / page).is_file(), page


def test_the_methods_guide_opens_at_the_tag_of_the_method_installed():
    assert guide.method_guide_url("3.0.64") == f"{_METHOD_BLOB}/v3.0.64/{_METHOD_GUIDE}"


def test_without_a_method_version_the_methods_guide_opens_on_main():
    # No manifest, or a version that names no release: a tag made up from it would be a 404.
    assert guide.method_guide_url("") == f"{_METHOD_BLOB}/main/{_METHOD_GUIDE}"
    assert guide.method_guide_url("3.0.64-dev") == f"{_METHOD_BLOB}/main/{_METHOD_GUIDE}"


def test_the_headers_question_mark_links_the_method_this_tcc_runs(monkeypatch):
    monkeypatch.setattr(install_report, "skill_version", lambda: "3.0.64")
    assert guide.method_target_guide_url() == f"{_METHOD_BLOB}/v3.0.64/{_METHOD_GUIDE}"


def test_the_methods_guide_is_where_the_link_says():
    # Read in the vendored method, so a move of the page on the method's side fails here first.
    root = vendor_loader.skill_repo_root()
    if root is None:
        pytest.skip("no method checked out")
    assert (root / guide.METHOD_TARGET_GUIDE).is_file()


_VENDORED = Path(__file__).parents[1] / "vendor" / "autosound-tuning-skill"


def test_the_reference_links_the_methods_guide_at_the_tag_this_tcc_ships_with(monkeypatch):
    """tcc#132: REFERENCE.md linked the method's target-curve guide at `main`, while the «?» it
    describes opens it at the installed method's tag. A Markdown page cannot ask which method is
    installed, so it names the tag of the method this TCC vendors -- read here the way the «?»
    reads it, so the next move of the submodule fails this until the link moves with it."""
    if not (_VENDORED / ".claude-plugin" / "plugin.json").is_file():
        pytest.skip("the method's submodule is not checked out: no pin to hold the link to")
    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV,
                       str(_VENDORED / "skills" / vendor_loader.SKILL_NAME))
    assert vendor_loader.skill_repo_root() == _VENDORED.resolve(), "the vendored method, no other"
    expected = guide.method_target_guide_url()
    assert "/blob/main/" not in expected, f"the vendored manifest names no release: {expected}"

    text = (_GUIDE_DIR / guide.REFERENCE).read_text(encoding="utf-8")
    links = re.findall(r"\]\((https://github\.com/ayukhno/autosound-tuning-skill/[^)\s]*"
                       + re.escape(Path(guide.METHOD_TARGET_GUIDE).name) + r")\)", text)
    assert links == [expected]
