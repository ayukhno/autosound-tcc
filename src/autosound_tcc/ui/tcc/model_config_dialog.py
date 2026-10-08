"""Which of omp's models this user actually has. Ticks, not a text field.

omp reports several hundred models and nobody holds credentials for most of them, so the generator
picker cannot just show the catalogue. TCC will not choose a subset on the user's behalf either —
that would be an app deciding what someone is allowed to run with their own accounts. So the
catalogue is browsable here and the marks are remembered.

The free/paid column is the reason this dialog is worth its own screen rather than being a list of
strings: the whole harness decision was made on cost (`spike/HANDOFF.md` §5-bis), and a model's
price belongs where the model is being chosen.

Claude's models are absent on purpose: they run through the Agent SDK against the user's own CLI,
which is a fixed list this dialog has no say over.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from autosound_tcc.core import config, model_choices, terminal_launcher
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.copy_menu import enable_copy
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip


class ModelConfigDialog(QDialog):
    """Pick the omp models to offer in the generator picker. `active` holds the result."""

    def __init__(self, active: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.t("configureModelsTitle"))
        self.active: list[str] = list(active)
        self._error: Optional[str] = None
        #: Whether omp's own configurator was opened from here. The catalogue is re-read once when
        #: this window comes back to the front afterwards — see `changeEvent`.
        self._setup_launched = False

        # Twice the width it opened at (the Arbiter, finding 75): a row reads «K2.7 Code Highspeed ·
        # kimi-code/kimi-for-coding-highspeed · безкоштовно», and it was cut on the right.
        self.setMinimumWidth(720)
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        blurb = QLabel(i18n.t("configureModelsBlurb"))
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText(i18n.t("configureModelsFilter"))
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        self._list = QListWidget()
        # Its own check boxes: the native ones drew nothing for an empty box in the dark theme and
        # sat over the row's text in the light one (finding 75, tcc#70).
        self._list.setProperty("class", "check-list")
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self._list, 1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        # This line is where the install command lands when omp is missing, and a command you
        # cannot copy is a command you have to retype from a screenshot (user, on a fresh Mac
        # 2026-08-13). Selectable AND right-click-copyable, because a one-line label gives no
        # affordance for either on its own.
        self._status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._status.setCursor(Qt.CursorShape.IBeamCursor)
        enable_copy(self._status, value=self._status.text)
        layout.addWidget(self._status)

        # Finding 108 (tcc#99): before this, an empty list under a failed catalogue read showed
        # only omp's own subprocess text -- true, but not a thing the Arbiter could act on. This
        # line leads instead; `_error_detail` still carries omp's text, verbatim, for a report --
        # it is one click away behind `_error_toggle` rather than gone.
        self._error_line = QLabel("")
        self._error_line.setWordWrap(True)
        self._error_line.setVisible(False)
        layout.addWidget(self._error_line)

        self._error_toggle = QPushButton()
        self._error_toggle.setCheckable(True)
        self._error_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._error_toggle.setAutoDefault(False)
        self._error_toggle.setVisible(False)
        self._error_toggle.toggled.connect(self._set_error_expanded)
        layout.addWidget(self._error_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self._error_detail = QLabel("")
        self._error_detail.setWordWrap(True)
        self._error_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._error_detail.setCursor(Qt.CursorShape.IBeamCursor)
        enable_copy(self._error_detail, value=self._error_detail.text)
        self._error_detail.setVisible(False)
        layout.addWidget(self._error_detail)
        self._set_error_expanded(False)

        # omp's own configurator, opened in the user's terminal (user, 2026-08-19). It is where
        # accounts and API keys are set up, and what is set up there is exactly what decides
        # whether the list above has three models in it or three hundred — so the way to it
        # belongs on this screen and nowhere else.
        #
        # A terminal rather than something in-app: `omp setup` is an interactive TUI that asks for
        # keys and opens browser sign-ins. TCC holds no credentials and reads no stdout from it
        # (`core/terminal_launcher`'s whole point), so the session belongs to the user, in their
        # own terminal — Terminal.app on macOS, the shell on Windows.
        #
        # In a row with the button box rather than inside it: `QDialogButtonBox` places a button by
        # ROLE and each platform has its own opinion about where a ResetRole lands. This one has to
        # sit on the LEFT of Ok/Cancel, and a plain layout says so once instead of per platform.
        self._setup_btn = QPushButton(i18n.t("configureModelsSetup"))
        self._setup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_btn.setAutoDefault(False)  # Enter belongs to Ok, not to a terminal launch
        attach_tip(self._setup_btn, i18n.t("configureModelsSetupTip"))
        self._setup_btn.clicked.connect(self._open_setup)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addWidget(self._setup_btn)
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)

        self._populate()

    # ---- contents ----------------------------------------------------------

    def _populate(self) -> None:
        # Collapsed and hidden until the `except` below says otherwise -- a `_reload()` after a
        # setup run has to be able to go from an error state back to a clean one.
        self._error_toggle.setChecked(False)
        self._error_line.setVisible(False)
        self._error_toggle.setVisible(False)
        self._status.setVisible(True)
        try:
            catalogue = model_choices.omp_catalogue()
        except model_choices.OmpCatalogueError as exc:
            # Marked models stay marked even when the catalogue cannot be read: forgetting a
            # user's choices because a subprocess failed would be a worse answer than an empty
            # list with the reason under it.
            self._error = str(exc)
            if not model_choices.omp_available():
                # omp itself is missing. Its own message already names the fix (install it), and
                # «Configure omp…» is not a next step here -- there is nothing on PATH for it to
                # launch. This stays the one plain line it always was, with no toggle behind it.
                self._status.setText(self._error)
                return
            # omp is on PATH but could not list its models -- not set up yet, or broken (finding
            # 108, tcc#99). The raw subprocess text alone left no next step; this line leads, and
            # the raw text -- still needed for a report -- is one click away behind the toggle.
            self._error_line.setText(
                i18n.t("configureModelsError").format(btn=i18n.t("configureModelsSetup"))
            )
            self._error_detail.setText(self._error)
            self._error_line.setVisible(True)
            self._error_toggle.setVisible(True)
            self._status.setVisible(False)
            return
        known = {choice.model for choice in catalogue}
        # A model marked earlier that omp no longer reports still belongs on screen -- otherwise
        # unticking it is impossible and it silently haunts the picker.
        for selector in self.active:
            if selector not in known:
                catalogue.append(
                    model_choices.Choice(harness="omp", model=selector, label=selector)
                )
        for choice in sorted(catalogue, key=lambda c: (c.provider, c.label.lower())):
            label = f"{choice.label}  ·  {choice.model}"
            if choice.free:
                label += f"  ·  {i18n.t('modelFree')}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, choice.model)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if choice.model in self.active else Qt.CheckState.Unchecked
            )
            self._list.addItem(item)
        self._status.setText(i18n.t("configureModelsCount").format(n=self._list.count()))

    def _set_error_expanded(self, expanded: bool) -> None:
        """Show or hide omp's own text, and keep `_error_toggle`'s own label saying which."""
        self._error_detail.setVisible(expanded)
        arrow = "▾" if expanded else "▸"  # ▾ / ▸
        self._error_toggle.setText(f"{arrow} {i18n.t('configureModelsErrorDetails')}")

    def _open_setup(self) -> None:
        """Open `omp setup` in a terminal — omp's onboarding: providers, keys, sign-ins.

        Errors land on the status line, which is the line that already carries "omp is not on
        PATH" and can be copied. A button that does nothing visible is the one outcome a launcher
        must not have (`terminal_launcher.launch` says the same in its own docstring). Made
        visible again here: `_populate` hides it while the catalogue error line leads instead, and
        this button is reachable from that state too (finding 108, tcc#99).
        """
        self._status.setVisible(True)
        try:
            # No tuning session runs in it, so no project's copy of the method is asked of it (#169).
            terminal_launcher.launch(self._launch_dir(), cli="omp", extra=("setup",), method=False)
        except terminal_launcher.TerminalLaunchError as exc:
            self._status.setText(str(exc))
            return
        self._setup_launched = True
        self._status.setText(i18n.t("configureModelsSetupOpened"))

    @staticmethod
    def _launch_dir() -> Path:
        """Where to open the terminal. The project folder when there is a real one, the home
        folder otherwise: `omp setup` configures the machine, not the car, and a launcher that
        refuses because a project has never been chosen would be refusing for the wrong reason."""
        try:
            here = config.project_dir()
            if here.is_dir():
                return here
        except Exception:  # noqa: BLE001 — an unconfigured install is the ordinary case here
            pass
        return Path.home()

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Re-read omp's catalogue when this window comes back from the configurator.

        Once, and only after the button was actually pressed: the catalogue is a subprocess call,
        and paying for it on every alt-tab would make this dialog feel broken. The point is that
        somebody who has just authenticated a provider sees its models without closing and
        re-opening the window.
        """
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.ActivationChange
            and self.isActiveWindow()
            and self._setup_launched
        ):
            self._setup_launched = False
            self._reload()

    def _reload(self) -> None:
        """Read the catalogue again, keeping the ticks that are on screen right now."""
        self.active = self._checked()
        self._error = None
        self._list.clear()
        self._populate()

    def _checked(self) -> list[str]:
        return [
            self._list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self._list.count())
            if self._list.item(row).checkState() == Qt.CheckState.Checked
        ]

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self._list.count()):
            item = self._list.item(row)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _accept(self) -> None:
        if self._error is not None:
            # Nothing was listed, so nothing was unticked -- keep what was there rather than
            # writing an empty list the user never chose.
            self.accept()
            return
        self.active = self._checked()
        self.accept()
