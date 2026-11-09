"""#244: a flaw kind the method knows must read as words on screen, never as its raw key."""

from __future__ import annotations

import pytest

from autosound_tcc.core import vendor_loader
from autosound_tcc.ui.tcc import i18n

pytestmark = pytest.mark.skipif(
    not vendor_loader.is_available(), reason="rew_tool submodule not checked out"
)


@pytest.mark.parametrize("lang", ["en", "uk", "pl", "de"])
def test_every_method_flaw_kind_has_a_label(lang):
    kinds = vendor_loader.load_project().FLAW_KINDS
    previous = i18n.current_language()
    i18n.set_language(lang)
    try:
        for kind in kinds:
            assert i18n.T[lang].get(f"flawKind_{kind}"), (lang, kind)
            assert i18n.flaw_kind(kind) != f"flawKind_{kind}", (lang, kind)
    finally:
        i18n.set_language(previous)


def test_an_unknown_flaw_kind_reads_as_plain_words():
    assert i18n.flaw_kind("some_new_kind") == "some new kind"
