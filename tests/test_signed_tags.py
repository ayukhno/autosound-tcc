"""Who signs TCC's release tags: the constant the updater checks against, and the file people
and `git verify-tag` read, are one fact (tcc#102, hub #83 HUB-032)."""

from __future__ import annotations

from pathlib import Path

from autosound_tcc.core import signed_tags, updates

ROOT = Path(__file__).resolve().parents[1]


def test_allowed_signers_carries_the_constant_the_updater_checks_against():
    """The updater never reads `allowed_signers` — a tag's own copy would vouch for itself — so the
    constant and the file are two copies of one line, and this is what keeps them one."""
    text = (ROOT / "allowed_signers").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]

    assert lines == [signed_tags.allowed_signers_line()]
    assert signed_tags.TCC_SIGNING_PRINCIPAL == "ayukhno"


def test_signed_tags_start_at_this_waves_release():
    assert signed_tags.TCC_SIGNED_FROM == "v0.1.45"


def test_the_developer_switch_is_the_one_the_skill_s_check_already_reads():
    """One name for both checks, the skill's own (`upkeep.py` SKIP_VERIFY_VAR): `test_updates.py`
    holds `updates`' copy to the vendored script, this holds ours to that one."""
    assert signed_tags.SKIP_VERIFY_VAR == updates.SKIP_VERIFY_VAR == "AUTOSOUND_SKIP_TAG_VERIFY"
