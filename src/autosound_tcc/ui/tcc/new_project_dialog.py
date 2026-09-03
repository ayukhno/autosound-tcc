""""Create new project" entry point (docs/TCC-TZ.md): folder + vendor/model + AI model, then
hands off to the existing `ProfileInterviewDialog` -- no new interview logic here, just supplying
the three inputs it already needs (the same ones `dsp_profile_interview.py`'s CLI takes as
`--project-dir`/`--vendor`/`--model`; the interview itself asks everything else conversationally).

Since 2026-08-23 it can also START FROM AN EXISTING PROJECT instead of from nothing: pick a folder
that already has a `project.json` and the car, the drivers, the glossary and the prose come over
(the method's `rew_tool/project_seed.py`, reached through `vendor_loader`), leaving the person
to adjust rather than to describe their own car again.
Two consequences show up here rather than in that module:

* picking a source fills the DSP vendor/model from it, because those two strings are matched
  EXACTLY against the bundled profiles and the source already holds a pair that matched once;
* if the DSP is the same one, the capability interview is skipped altogether -- it would be an
  interview about a `dsp_profile.json` that is already sitting in the new folder. Change the DSP
  and the profile does not travel, the rest still does, and the interview runs as before.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from autosound_tcc.core import config, terminal_launcher, vendor_loader
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.mock_data import AI_MAIN_MODELS, AI_MODEL_IDS
from autosound_tcc.ui.tcc.profile_interview_dialog import ProfileInterviewDialog


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("class", "kv-lbl")
    return label


def _seeder():
    """The method's seeding module, or None on an install that has no skill checked out.

    None is a real state, not a bug: `_bundled_profiles` below reads the packaged profiles
    directly for the same reason -- this dialog is the first screen a fresh install meets, and it
    has to open and say something useful even when the submodule is missing.
    """
    try:
        return vendor_loader.load_project_seed()
    except Exception:  # noqa: BLE001 — no skill: the seeding option simply cannot be offered
        return None


def _bundled_profiles(bundled_dir: Path) -> list[tuple[str, str]]:
    """(vendor, name) pairs from the packaged `dsp_profiles/*.json` -- read directly rather than through
    the vendored `rew_tool` so this dialog still works if that submodule isn't checked out.

    Picking one of these guarantees an EXACT match against `dsp_profile.find_bundled()`'s
    deliberately strict, no-fuzzy-matching check (project-intake.md §4) -- free-typing "Helix" /
    "Ultra S" against a profile actually keyed `Audiotec-Fischer` / `Helix DSP Ultra S` is exactly
    how a real bundled profile gets missed (user report 2026-07-29)."""
    import json

    pairs = []
    for path in sorted(bundled_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        profile = data.get("dsp_profile", data) if isinstance(data, dict) else data
        vendor = str(profile.get("vendor", "")).strip()
        name = str(profile.get("name", "")).strip()
        if vendor and name:
            pairs.append((vendor, name))
    return pairs


class NewProjectDialog(QDialog):
    """Collects folder + vendor + model + AI model, then constructs (but does not show)
    `ProfileInterviewDialog` -- the caller (`main_window._open_new_project_dialog`) owns showing
    it and reacting to its `profile_saved` signal, since that's where the "restart pointed at the
    new project" logic belongs."""

    def __init__(self, parent=None, seed_first: bool = False) -> None:
        """`seed_first` opens straight on "copy from an existing project": the main menu offers
        that as its own act ("Copy the car…"), because starting from a car somebody has already
        described is a different intent from starting a project from nothing -- not a second
        button for the same one."""
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(i18n.t("npTitle"))
        self.setMinimumWidth(420)
        self.interview_dialog: Optional[ProfileInterviewDialog] = None
        #: `describe()`'s answer for the folder currently picked, kept so the note can be redrawn
        #: when the DSP choice changes without reading the folder again.
        self._seed_describes = None
        #: `_prefill_dsp` writes into the DSP fields, and those fields redraw the note -- without
        #: this the two would call each other. Set while prefilling, cleared after.
        self._prefilling = False
        # Set by _on_create() instead when "run via" picks a terminal CLI rather than the in-app
        # chat -- main_window._open_new_project_dialog() branches on whichever ended up non-None.
        self.open_terminal_cli: Optional[str] = None
        self.project_dir: Optional[Path] = None
        self.onboarding_vendor: str = ""
        self.onboarding_model: str = ""
        self.onboarding_ai_model: Optional[str] = None
        #: The in-app pick, kept for the path that runs NO interview: a copied project skips the
        #: capability questions, and the model chosen here would otherwise be dropped on the floor
        #: -- the window then opened on "no model chosen" (user, 2026-08-23).
        self.in_app_model: Optional[str] = None
        #: What was copied in, for the caller to report. None when the project starts empty.
        #: Typed loosely on purpose: the class is the method's (`rew_tool/project_seed.py`),
        #: reached through `vendor_loader`, so there is no import here to annotate it with.
        self.seeded = None
        self.seeded_from: Optional[Path] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(10)

        layout.addWidget(_field_label(i18n.t("npFolder")))
        folder_row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        # The currently open project is the most relevant starting point TCC already knows about
        # (user request 2026-07-29) -- more useful than a bare home dir, and still just text the
        # user can edit or browse away from.
        self._folder_edit.setText(str(config.project_dir()))
        self._folder_edit.textChanged.connect(self._sync_create_enabled)
        folder_row.addWidget(self._folder_edit, stretch=1)
        browse_btn = QPushButton(i18n.t("npBrowse"))
        browse_btn.setProperty("class", "reason-btn")
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.clicked.connect(self._on_browse)
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)

        layout.addWidget(_field_label(i18n.t("npSeed")))
        self._seed_combo = QComboBox()
        self._seed_combo.setProperty("class", "mini-select")
        self._seed_combo.addItem(i18n.t("npSeedNone"), None)
        self._seed_combo.addItem(i18n.t("npSeedFrom"), "copy")
        self._seed_combo.currentIndexChanged.connect(self._on_seed_mode)
        layout.addWidget(self._seed_combo)

        seed_row = QHBoxLayout()
        self._seed_edit = QLineEdit()
        self._seed_edit.setPlaceholderText(i18n.t("npSeedPlaceholder"))
        self._seed_edit.textChanged.connect(self._on_seed_source)
        seed_row.addWidget(self._seed_edit, stretch=1)
        self._seed_browse = QPushButton(i18n.t("npBrowse"))
        self._seed_browse.setProperty("class", "reason-btn")
        self._seed_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self._seed_browse.clicked.connect(self._on_browse_seed)
        seed_row.addWidget(self._seed_browse)
        self._seed_row = seed_row
        layout.addLayout(seed_row)

        # What the picked folder IS, or why it cannot be used -- answered while the person is
        # still looking at the field, not after they press Create.
        self._seed_summary = QLabel("")
        self._seed_summary.setWordWrap(True)
        self._seed_summary.setProperty("class", "kv-lbl")
        # A wrapped QLabel keeps the height of ONE line unless it is told its height depends on
        # its width, and the sentence then draws straight over the checkbox under it (user, with
        # the screenshot -- a refusal message unreadable across three overlapping lines).
        self._seed_summary.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding
        )
        layout.addWidget(self._seed_summary)

        # Off by default: these were measured or decided in the OTHER project, and their evidence
        # names measurements that exist only there (see the method's `project_seed.py`).
        self._seed_findings = QCheckBox(i18n.t("npSeedFindings"))
        # The tick changes what travels, so it changes the numbers under it: the flag used to be
        # offered blind -- "and what was measured there" with no count of what "what" is (#48).
        self._seed_findings.toggled.connect(self._refresh_seed_note)
        layout.addWidget(self._seed_findings)

        # Said here rather than discovered afterwards: with the same DSP, the capability interview
        # does not run at all, and a person who chose an AI model below deserves to know why they
        # are never asked anything.
        self._seed_no_interview = QLabel(i18n.t("npSeedNoInterview"))
        self._seed_no_interview.setWordWrap(True)
        self._seed_no_interview.setProperty("class", "kv-lbl")
        self._seed_no_interview.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding
        )
        self._seed_no_interview.setVisible(False)
        layout.addWidget(self._seed_no_interview)

        layout.addWidget(_field_label(i18n.t("npProfile")))
        self._profile_combo = QComboBox()
        self._profile_combo.setProperty("class", "mini-select")
        for vendor, name in _bundled_profiles(config.bundled_profiles_dir()):
            self._profile_combo.addItem(f"{vendor} — {name}", (vendor, name))
        self._profile_combo.addItem(i18n.t("npAddNew"), None)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        self._profile_combo.currentIndexChanged.connect(self._refresh_seed_note)
        layout.addWidget(self._profile_combo)

        self._vendor_edit = QLineEdit()
        self._vendor_edit.setPlaceholderText(i18n.t("npVendorPlaceholder"))
        self._vendor_edit.textChanged.connect(self._sync_create_enabled)
        self._vendor_edit.textChanged.connect(self._refresh_seed_note)
        self._vendor_label = _field_label(i18n.t("npVendor"))
        layout.addWidget(self._vendor_label)
        layout.addWidget(self._vendor_edit)

        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText(i18n.t("npModelPlaceholder"))
        self._model_edit.textChanged.connect(self._sync_create_enabled)
        self._model_edit.textChanged.connect(self._refresh_seed_note)
        self._model_label = _field_label(i18n.t("npModel"))
        layout.addWidget(self._model_label)
        layout.addWidget(self._model_edit)

        # "Terminal" options only appear for CLIs actually installed (terminal_launcher's own
        # detection, already provider-agnostic -- claude/gemini/codex all speak MCP). Onboarding's
        # own MCP tools (core/mcp_server.py) are what makes this path real, not just a raw shell.
        layout.addWidget(_field_label(i18n.t("npRunVia")))
        self._run_via_combo = QComboBox()
        self._run_via_combo.setProperty("class", "mini-select")
        self._run_via_combo.addItem(i18n.t("npRunInApp"), None)
        for exe, label in terminal_launcher.available_clis():
            self._run_via_combo.addItem(f"Terminal — {label}", exe)
        self._run_via_combo.currentIndexChanged.connect(self._on_run_via_selected)
        layout.addWidget(self._run_via_combo)

        self._ai_model_label = _field_label(i18n.t("npAiModel"))
        layout.addWidget(self._ai_model_label)
        self._ai_combo = QComboBox()
        self._ai_combo.setProperty("class", "mini-select")
        self._ai_combo.addItems(AI_MAIN_MODELS)
        layout.addWidget(self._ai_combo)

        # Terminal path's own model field: free-text, since each CLI has its own model-name
        # vocabulary (TCC doesn't maintain a Gemini/Codex catalog the way it does for Claude) --
        # passed through as `--model <value>` (terminal_launcher.launch), blank = CLI's own default.
        self._terminal_model_label = _field_label(i18n.t("npTerminalModel"))
        layout.addWidget(self._terminal_model_label)
        self._terminal_model_edit = QLineEdit()
        self._terminal_model_edit.setPlaceholderText(i18n.t("npTerminalModelPlaceholder"))
        layout.addWidget(self._terminal_model_edit)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_btn = QPushButton(i18n.t("npCancel"))
        cancel_btn.setProperty("class", "reason-btn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)
        self._create_btn = QPushButton(i18n.t("npCreate"))
        self._create_btn.setProperty("class", "reason-btn")
        self._create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._create_btn.setEnabled(False)
        self._create_btn.clicked.connect(self._on_create)
        actions.addWidget(self._create_btn)
        layout.addLayout(actions)

        if seed_first:
            index = self._seed_combo.findData("copy")
            if index >= 0:
                self._seed_combo.setCurrentIndex(index)
        self._on_seed_mode(self._seed_combo.currentIndex())
        self._on_profile_selected(self._profile_combo.currentIndex())
        self._on_run_via_selected(self._run_via_combo.currentIndex())

    def _on_seed_mode(self, _index: int) -> None:
        """"From scratch" hides the whole section rather than greying it: an empty path field and
        an unchecked box under a picker set to "no" are three ways of saying the same nothing."""
        copying = self._seed_combo.currentData() == "copy"
        self._sync_create_enabled()  # the button names the act this mode performs
        for widget in (self._seed_edit, self._seed_browse, self._seed_summary,
                       self._seed_findings):
            widget.setVisible(copying)
        self._seed_no_interview.setVisible(False)
        if copying:
            self._on_seed_source(self._seed_edit.text())

    def _seed_source(self) -> Optional[Path]:
        """The folder to seed from, or None -- the single place that answers "are we copying"."""
        if self._seed_combo.currentData() != "copy":
            return None
        text = self._seed_edit.text().strip()
        return Path(text).expanduser() if text else None

    def _on_seed_source(self, _text: str) -> None:
        """Say what the picked folder is while it is still being picked.

        A folder either has a readable `project.json` or it does not, and that is knowable the
        moment it is typed -- so it is answered here rather than as a failure after Create.
        """
        source = self._seed_source()
        seeder = _seeder()
        summary = seeder.describe(source) if (source is not None and seeder) else None
        self._seed_describes = summary
        if source is None:
            self._set_seed_note("", warn=False)
            self._seed_no_interview.setVisible(False)
            return
        if summary is None:
            self._set_seed_note(i18n.t("npSeedNotAProject"), warn=True)
            self._seed_no_interview.setVisible(False)
            return
        self._prefill_dsp(source)
        self._refresh_seed_note()

    def _would_travel(self, source: Path):
        """What the seeder WOULD carry — asked of the seeder rather than predicted.

        The note used to render `describe()`, which counts what the SOURCE holds. That is a
        different number from what lands, and the gap is about to widen: the profile only travels
        when the processor is the same, and the method is tying the channel topology to that same
        answer, because topology belongs to the processor and the processor is what changed
        (skill, SKL-014). Twenty Helix channels landing in an 8-output DSP is what that costs when
        nobody says so first, and `remove-channel` does not exist.

        So the number is not predicted here. The seed runs into a throwaway folder with exactly
        the flags Create will use, and its report is what gets drawn — which follows the method's
        behaviour without this file having to know it, including the change that has not reached
        our vendored copy yet. `seed()` never writes into the source; that is its own promise.
        """
        seeder = _seeder()
        if seeder is None:
            return None
        with tempfile.TemporaryDirectory(prefix="tcc-seed-preview-") as tmp:
            target = Path(tmp) / "preview"
            target.mkdir()
            try:
                return seeder.seed(
                    source,
                    target,
                    include_findings=self._seed_findings.isChecked(),
                    copy_profile=seeder.dsp_of(source) == (
                        self._vendor_edit.text().strip(), self._model_edit.text().strip()),
                    note=i18n.t("npSeedNote"),
                )
            except Exception:      # noqa: BLE001 — a preview must never take the dialog down
                return None

    def _refresh_seed_note(self, *_args) -> None:
        """Redraw the note. Called again whenever the DSP choice changes, because the DSP is what
        decides how much of the source travels."""
        if self._prefilling or self._seed_describes is None:
            return
        # The DSP fields are built after this label, and `_on_seed_mode` can fire in between.
        if getattr(self, "_vendor_edit", None) is None:
            return
        source = self._seed_source()
        if source is None:
            return
        summary = self._seed_describes
        lines = [i18n.t("npSeedSummary").format(
            car=summary.car, dsp=summary.dsp or "—", channels=summary.channels)]
        report = self._would_travel(source)
        if report is not None and report.ok:
            key = "npSeedTravelsFindings" if self._seed_findings.isChecked() else "npSeedTravels"
            lines.append(i18n.t(key).format(
                channels=report.channels, amps=report.amps,
                flaws=report.flaws, questions=report.questions))
            if summary.channels and not report.channels:
                # The one a person has to read BEFORE pressing Create: wanting the findings and
                # not the channels was impossible, so the working answer was to go around the
                # seeder by hand — and the findings only travel with it.
                lines.append(i18n.t("npSeedNoChannels"))
        self._set_seed_note("\n".join(lines), warn=False)

    def _set_seed_note(self, text: str, *, warn: bool) -> None:
        self._seed_summary.setText(text)
        # The dialog has to grow with the sentence; the layout only re-asks when told.
        self._seed_summary.updateGeometry()
        self.adjustSize()
        self._seed_summary.setProperty("class", "kv-warn" if warn else "kv-lbl")
        self._seed_summary.style().unpolish(self._seed_summary)
        self._seed_summary.style().polish(self._seed_summary)

    def _prefill_dsp(self, source: Path) -> None:
        """Take the DSP from the source project instead of asking for it again.

        The two strings are matched EXACTLY against the bundled profiles, and the source project
        holds a pair that matched once already -- so when it is one of ours, select that entry;
        when it is not, fall to "Add new" with the fields filled, which is the same state a person
        reaches by typing them correctly.
        """
        seeder = _seeder()
        pair = seeder.dsp_of(source) if seeder else None
        self._seed_no_interview.setVisible(pair is not None)
        if pair is None:
            return
        # Guarded: every line below writes into a field that redraws the note, and the note reads
        # these fields back. Without the flag the two would take turns until the stack ran out.
        self._prefilling = True
        try:
            for index in range(self._profile_combo.count()):
                if self._profile_combo.itemData(index) == pair:
                    self._profile_combo.setCurrentIndex(index)
                    return
            for index in range(self._profile_combo.count()):
                if self._profile_combo.itemData(index) is None:
                    self._profile_combo.setCurrentIndex(index)
                    break
            # After the combo, never before: selecting "Add new" clears both fields.
            self._vendor_edit.setText(pair[0])
            self._model_edit.setText(pair[1])
        finally:
            self._prefilling = False

    def _on_run_via_selected(self, _index: int) -> None:
        """The Claude-specific AI_MAIN_MODELS picker only means anything for the in-app path;
        a terminal CLI gets its own free-text model field instead (2026-07-29: "would be right to
        call terminals with a model applied too")."""
        is_in_app = self._run_via_combo.currentData() is None
        self._ai_model_label.setVisible(is_in_app)
        self._ai_combo.setVisible(is_in_app)
        self._terminal_model_label.setVisible(not is_in_app)
        self._terminal_model_edit.setVisible(not is_in_app)

    def _on_profile_selected(self, _index: int) -> None:
        """A bundled pick fills vendor/model with the EXACT strings `find_bundled()` checks
        against and hides the free-text fields (nothing to type); "Add new" clears and reveals
        them for a DSP that isn't in the packaged `dsp_profiles/` yet."""
        pair = self._profile_combo.currentData()
        is_new = pair is None
        if not is_new:
            vendor, model = pair
            self._vendor_edit.setText(vendor)
            self._model_edit.setText(model)
        else:
            self._vendor_edit.clear()
            self._model_edit.clear()
        for widget in (self._vendor_label, self._vendor_edit, self._model_label, self._model_edit):
            widget.setVisible(is_new)
        self._sync_create_enabled()

    def _why_refused(self, source: Path, target: Path, report) -> str:
        """The refusal in the language the window is in.

        Two of them are ordinary and predictable -- the folder is already a project, or the source
        is not one -- and both are conditions this dialog can test itself rather than recognise
        from a sentence. Anything else falls through with the module's own words, which is better
        than a friendly guess about what went wrong.
        """
        if (target / "project.json").is_file():
            return i18n.t("npSeedTargetTaken").format(folder=target.name)
        seeder = _seeder()
        if seeder is None or seeder.describe(source) is None:
            return i18n.t("npSeedNotAProject")
        return i18n.t("npSeedFailed").format(problem=report.problem or "")

    def _sync_create_enabled(self) -> None:
        # "Create" and "Copy" are different acts and the button is the last thing read before
        # either happens (user, 2026-08-23).
        self._create_btn.setText(
            i18n.t("npCopy") if self._seed_combo.currentData() == "copy" else i18n.t("npCreate")
        )
        self._create_btn.setEnabled(
            bool(self._folder_edit.text().strip())
            and bool(self._vendor_edit.text().strip())
            and bool(self._model_edit.text().strip())
        )

    def _on_browse(self) -> None:
        start = self._folder_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, i18n.t("npFolder"), start)
        if chosen:
            self._folder_edit.setText(chosen)

    def _on_browse_seed(self) -> None:
        start = self._seed_edit.text().strip() or str(config.project_dir())
        chosen = QFileDialog.getExistingDirectory(self, i18n.t("npSeedFrom"), start)
        if chosen:
            self._seed_edit.setText(chosen)

    def _on_create(self) -> None:
        project_dir = Path(self._folder_edit.text().strip()).expanduser()
        vendor = self._vendor_edit.text().strip()
        model = self._model_edit.text().strip()

        # Mirrors dsp_profile_interview.py's CLI path exactly -- OnboardingSession itself does not
        # create the folder.
        project_dir.mkdir(parents=True, exist_ok=True)

        # Before `set_project_dir`, deliberately: a seeding that fails leaves the folder as it was
        # and TCC pointed where it was, rather than parked on a half-made project.
        source = self._seed_source()
        if source is not None:
            seeder = _seeder()
            if seeder is None:
                self._set_seed_note(i18n.t("npSeedNoSkill"), warn=True)
                return
            report = seeder.seed(
                source,
                project_dir,
                include_findings=self._seed_findings.isChecked(),
                # The profile travels only when it is the same DSP. Pick a different one and its
                # capabilities are a question for the interview, not a file to inherit.
                copy_profile=seeder.dsp_of(source) == (vendor, model),
                note=i18n.t("npSeedNote"),
            )
            if not report.ok:
                # The module answers in English, with a path in it, because it is a library and
                # has no language. The two refusals a person actually meets get said HERE, in
                # theirs, and the raw sentence is kept only for the ones nobody predicted.
                self._set_seed_note(self._why_refused(source, project_dir, report), warn=True)
                return
            self.seeded, self.seeded_from = report, source

        config.set_project_dir(project_dir)
        self.project_dir = project_dir

        # A project that arrived with its `dsp_profile.json` has nothing left to interview about:
        # the capability checklist would be asking after a file already in the folder. Everything
        # else about the new project is unchanged, including the terminal path below -- a person
        # who asked for a CLI still gets one, told what came over rather than what to ask.
        interview_needed = (
            self.seeded is None or _seeder().PROFILE_FILE not in self.seeded.written
        )

        cli = self._run_via_combo.currentData()
        if cli is None:
            self.in_app_model = AI_MODEL_IDS.get(self._ai_combo.currentText())
            if interview_needed:
                ai_model = self.in_app_model
                self.interview_dialog = ProfileInterviewDialog(
                    project_dir, vendor, model, ai_model, i18n.current_language(),
                    parent=self.parent(),
                )
        else:
            self.open_terminal_cli = cli
            self.onboarding_vendor = vendor
            self.onboarding_model = model
            self.onboarding_ai_model = self._terminal_model_edit.text().strip() or None
        self.accept()
