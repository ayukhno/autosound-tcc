"""Ticking which omp models this user actually has."""

from __future__ import annotations

import json
import os
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import model_choices  # noqa: E402
from autosound_tcc.ui.tcc.model_config_dialog import ModelConfigDialog  # noqa: E402

CATALOGUE = [
    {"provider": "google", "selector": "google/gemini-3.1-pro-preview",
     "name": "Gemini 3.1 Pro", "cost": {"input": 1.25, "output": 10.0}},
    {"provider": "opencode", "selector": "opencode/nemotron-3-ultra-free",
     "name": "Nemotron 3 Ultra", "cost": {"input": 0, "output": 0}},
]


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def catalogue(monkeypatch):
    monkeypatch.setattr(model_choices, "omp_available", lambda: True)
    monkeypatch.setattr(
        model_choices.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps({"models": CATALOGUE}), ""),
    )


def _rows(dialog):
    return {
        dialog._list.item(i).data(Qt.ItemDataRole.UserRole): dialog._list.item(i)
        for i in range(dialog._list.count())
    }


def test_marked_models_come_back_ticked(catalogue):
    dialog = ModelConfigDialog(["google/gemini-3.1-pro-preview"])

    rows = _rows(dialog)
    assert rows["google/gemini-3.1-pro-preview"].checkState() == Qt.CheckState.Checked
    assert rows["opencode/nemotron-3-ultra-free"].checkState() == Qt.CheckState.Unchecked


def test_a_free_model_is_labelled_free(catalogue):
    dialog = ModelConfigDialog([])

    assert "free" in _rows(dialog)["opencode/nemotron-3-ultra-free"].text()


def test_ticking_a_model_adds_it_to_the_result(catalogue):
    dialog = ModelConfigDialog([])

    _rows(dialog)["opencode/nemotron-3-ultra-free"].setCheckState(Qt.CheckState.Checked)
    dialog._accept()

    assert dialog.active == ["opencode/nemotron-3-ultra-free"]


def test_a_model_omp_no_longer_reports_is_still_listed_so_it_can_be_unticked(catalogue):
    """Otherwise it haunts the picker with no way to remove it."""
    dialog = ModelConfigDialog(["some/retired-model"])

    rows = _rows(dialog)
    assert rows["some/retired-model"].checkState() == Qt.CheckState.Checked


def test_the_filter_hides_non_matching_rows(catalogue):
    dialog = ModelConfigDialog([])

    dialog._filter.setText("nemotron")

    rows = _rows(dialog)
    assert rows["opencode/nemotron-3-ultra-free"].isHidden() is False
    assert rows["google/gemini-3.1-pro-preview"].isHidden() is True


def test_an_unreadable_catalogue_keeps_the_existing_marks(monkeypatch):
    """A failed subprocess must not be a way to silently unmark everything the user chose."""
    monkeypatch.setattr(model_choices, "omp_available", lambda: False)
    dialog = ModelConfigDialog(["google/gemini-3.1-pro-preview"])

    assert dialog._list.count() == 0
    assert "brew install" in dialog._status.text()

    dialog._accept()

    assert dialog.active == ["google/gemini-3.1-pro-preview"]
