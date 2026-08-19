"""Ticking which omp models this user actually has."""

from __future__ import annotations

import json
import os
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pathlib import Path  # noqa: E402

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QDialogButtonBox  # noqa: E402

from autosound_tcc.core import config, model_choices, terminal_launcher  # noqa: E402
from autosound_tcc.ui.tcc import i18n  # noqa: E402
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


def test_choosing_a_model_does_not_mutate_the_combo_while_the_signal_runs(tmp_path, monkeypatch):
    """Removing an item from a combo inside that combo's own `currentIndexChanged` frees the view's
    internals while Qt is still walking them — a segfault, reported after picking a model
    (2026-08-06), and the same shape as deleting a widget from its own event handler."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.main_window import MainWindow

    QApplication.instance() or QApplication([])
    window = MainWindow()
    combo = window._ai_main_combo
    combo.blockSignals(True)
    combo.clear()
    combo.addItem("— choose —", "")
    combo.addItem("Claude Sonnet 5", "sdk:claude-sonnet-5")
    combo.setCurrentIndex(1)
    combo.blockSignals(False)
    before = combo.count()

    window._on_generator_model_changed(1)

    assert combo.count() == before  # nothing removed yet: it happens after the signal returns
    window._drop_model_placeholder()
    assert combo.count() == before - 1


# ---- omp's own configurator, from this screen (user, 2026-08-19) -------------------------------


def _bottom_row(dialog):
    """The widgets on the dialog's last row, left to right (spacers dropped)."""
    row = dialog.layout().itemAt(dialog.layout().count() - 1).layout()
    return [row.itemAt(i).widget() for i in range(row.count()) if row.itemAt(i).widget()]


def test_the_configure_button_sits_to_the_left_of_ok_and_cancel(catalogue):
    """User, 2026-08-19: "внизу вікна вибора моделі там де Ок і Cancel — тільки ліворуч в тому ж
    ряду". In a layout rather than in the QDialogButtonBox, which places by role and lands a
    ResetRole somewhere different on each platform."""
    dialog = ModelConfigDialog([])

    widgets = _bottom_row(dialog)

    assert widgets[0] is dialog._setup_btn, "first on the row, before the stretch"
    assert dialog._setup_btn.text() == i18n.t("configureModelsSetup")
    box = [w for w in widgets if isinstance(w, QDialogButtonBox)]
    assert box, "and the Ok/Cancel box is on the same row"
    assert dialog._setup_btn.autoDefault() is False, "Enter still belongs to Ok"


def test_pressing_it_opens_omp_setup_in_a_terminal(catalogue, monkeypatch):
    """`omp setup` is omp's onboarding — providers, keys, sign-ins — and it is an interactive TUI,
    so it belongs in the user's own terminal and not inside TCC."""
    calls = []
    monkeypatch.setattr(
        terminal_launcher, "launch",
        lambda project_dir, **kw: calls.append((project_dir, kw)) or "omp",
    )
    dialog = ModelConfigDialog([])

    dialog._setup_btn.click()

    assert len(calls) == 1
    _dir, kw = calls[0]
    assert kw["cli"] == "omp" and kw["extra"] == ("setup",)
    assert dialog._status.text() == i18n.t("configureModelsSetupOpened")


def test_a_terminal_that_cannot_be_opened_says_so_on_the_line_you_can_copy(catalogue, monkeypatch):
    """The status line is the one that already carries "omp is not on PATH", and it is
    selectable — a button that does nothing visible is the one outcome a launcher must not have."""
    def _boom(*_a, **_kw):
        raise terminal_launcher.TerminalLaunchError("'omp' is not on PATH")

    monkeypatch.setattr(terminal_launcher, "launch", _boom)
    dialog = ModelConfigDialog([])

    dialog._setup_btn.click()

    assert "not on PATH" in dialog._status.text()
    assert dialog._setup_launched is False, "nothing to re-read: nothing was opened"


def test_coming_back_from_the_configurator_reads_the_catalogue_again_once(catalogue, monkeypatch):
    """Somebody who has just authenticated a provider should see its models without closing and
    re-opening the window — and the ticks they made before pressing it survive. Once, because the
    catalogue is a subprocess call and paying for it on every alt-tab would feel broken."""
    monkeypatch.setattr(terminal_launcher, "launch", lambda *a, **k: "omp")
    dialog = ModelConfigDialog([])
    _rows(dialog)["google/gemini-3.1-pro-preview"].setCheckState(Qt.CheckState.Checked)
    reads = []
    real = ModelConfigDialog._populate
    monkeypatch.setattr(
        ModelConfigDialog, "_populate",
        lambda self: (reads.append(1), real(self))[1],
    )

    # "the window is at the front again" — offscreen, nothing ever becomes the active window, and
    # the production condition (`isActiveWindow`) is the right one: coming BACK is the moment to
    # re-read, going away is not.
    dialog.isActiveWindow = lambda: True

    dialog._setup_btn.click()
    dialog.changeEvent(QEvent(QEvent.Type.ActivationChange))  # comes back to the front

    assert len(reads) == 1, "read again after the configurator"
    assert dialog.active == ["google/gemini-3.1-pro-preview"], "and the tick survived"
    assert _rows(dialog)["google/gemini-3.1-pro-preview"].checkState() == Qt.CheckState.Checked

    dialog.changeEvent(QEvent(QEvent.Type.ActivationChange))

    assert len(reads) == 1, "not again on every activation"


def test_the_terminal_opens_in_the_home_folder_when_there_is_no_project(monkeypatch):
    """`omp setup` configures the machine, not the car. A launcher that refused because a project
    has never been chosen would be refusing for the wrong reason."""
    monkeypatch.setattr(config, "project_dir", lambda: Path("/nope/not/a/folder"))

    assert ModelConfigDialog._launch_dir() == Path.home()
