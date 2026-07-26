"""Sibling-name matching for the EQ pair (⇄ L+R) view — the two real naming conventions found in
actual ledgers: a bare trailing letter with no delimiter (`FrontL`/`FrontR`, the real virtual-
channel names) and a standalone word (`Front L Full`, the prototype's own convention)."""

from __future__ import annotations

from autosound_tcc.ui.tcc.detail_pane import _is_left, _sibling_name


def test_sibling_name_bare_suffix():
    assert _sibling_name("FrontL") == "FrontR"
    assert _sibling_name("FrontR") == "FrontL"
    assert _sibling_name("w_L") == "w_R"
    assert _sibling_name("w_R") == "w_L"


def test_sibling_name_standalone_word():
    assert _sibling_name("Front L Full") == "Front R Full"
    assert _sibling_name("Front R Full") == "Front L Full"


def test_sibling_name_none_for_unpaired_channels():
    assert _sibling_name("Center") is None
    assert _sibling_name("Subwoofer") is None
    assert _sibling_name("RearATT") is None


def test_is_left():
    assert _is_left("FrontL") and not _is_left("FrontR")
    assert _is_left("w_L") and not _is_left("w_R")
    assert _is_left("Front L Full") and not _is_left("Front R Full")
