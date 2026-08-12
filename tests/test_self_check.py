"""TCC's own setup, said out loud — and repaired where the repair is TCC's to make.

The class of problem this exists for: a model alias written weeks ago silently redirects every
reviewer call, and the only record is a JSON file the Arbiter has no reason to open. Found by
audit, five days after it started (2026-08-12), pointing every Gemini reviewer at the Generator's
own model.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import model_choices, model_overrides, self_check  # noqa: E402


@pytest.fixture(autouse=True)
def _own_config(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(model_choices, "_CLI_CACHE", {})
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: False)
    yield


def _find(checks, check_id):
    return next(c for c in checks if c.id == check_id)


def test_a_clean_install_says_so_rather_than_staying_silent():
    checks = self_check.run()

    aliases = _find(checks, "aliases")
    assert aliases.status == self_check.OK
    assert not aliases.fixable, "nothing to repair, so no button that does nothing"


def test_an_alias_onto_another_vendor_is_the_bad_one():
    """A substitution inside a vendor is a substitution. One across vendors, on the reviewer, is
    the end of cross-vendor review — and that is not the same severity."""
    model_overrides.set_alias("agy:gemini-3.1-pro-high", "sdk:claude-opus-5", "gone")

    aliases = _find(self_check.run(), "aliases")

    assert aliases.status == self_check.BAD
    assert "agy:gemini-3.1-pro-high" in aliases.detail
    assert "sdk:claude-opus-5" in aliases.detail
    assert aliases.fixable


def test_the_fix_removes_them_and_says_how_many():
    model_overrides.set_alias("agy:gemini-3.1-pro-high", "sdk:claude-opus-5", "gone")
    model_overrides.set_alias("agy:gemini-3.5-flash-high", "sdk:claude-opus-5", "gone")

    message = _find(self_check.run(), "aliases").fix()

    assert "2" in message
    assert model_overrides.load()["aliases"] == {}
    assert _find(self_check.run(), "aliases").status == self_check.OK


def test_the_fix_is_offered_only_for_what_tcc_owns():
    """D-6: the skill writes the project, TCC reads it. Every fixable check must touch TCC's own
    config and nothing under the project — a button here that edited `project.json` would make two
    writers of a file with one owner."""
    model_overrides.set_alias("a:b", "c:d", "gone")

    fixable = [c.id for c in self_check.run() if c.fixable]

    assert set(fixable) <= {"aliases", "catalogue"}


def test_a_probe_that_raises_becomes_a_row_not_a_dead_dialog(monkeypatch):
    monkeypatch.setattr(
        self_check, "_alias_check", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    checks = self_check.run()

    assert any("boom" in (c.detail or "") for c in checks)
    assert len(checks) == 2, "the other probe still ran"


def test_an_installed_cli_that_answered_nothing_gets_a_row_and_a_retry(monkeypatch):
    """The route simply vanishes from the pickers, which reads exactly like "not installed" — and
    that is what wrote the aliases in the first place."""
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "agy")

    catalogue = _find(self_check.run(), "catalogue")

    assert catalogue.status == self_check.WARN
    assert "agy" in catalogue.title
    assert catalogue.fixable


def test_worst_first():
    model_overrides.set_alias("agy:gemini-3.1-pro-high", "sdk:claude-opus-5", "gone")

    statuses = [c.status for c in self_check.run()]

    assert statuses == sorted(statuses, key=lambda s: {"bad": 0, "wait": 1, "done": 2}[s])
