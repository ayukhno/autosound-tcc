""""Create new project" entry point (docs/TCC-TZ.md): folder + DSP vendor/model + how the AI
runs. The intake itself is the skill's served form, which the new window opens straight away (hub
#194, the Arbiter 2026-09-22: one form for every front end) -- this dialog no longer starts a
conversational interview.

Since 2026-08-23 it can also START FROM AN EXISTING PROJECT instead of from nothing: pick a folder
that already has a `project.json` and the car, the drivers, the glossary and the prose come over
(the method's `rew_tool/project_seed.py`, reached through `vendor_loader`), leaving the person
to adjust rather than to describe their own car again.
Two consequences show up here rather than in that module:

* picking a source fills the DSP vendor/model from it, because those two strings are matched
  EXACTLY against the bundled profiles and the source already holds a pair that matched once;
* if the DSP is the same one, its profile travels with the copy; change the DSP and it does not,
  the rest still does, and the form's own `/new-dsp` page asks for the new processor.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
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

from autosound_tcc.core import app_log, config, model_choices, terminal_launcher, vendor_loader
from autosound_tcc.ui.tcc import car_source, i18n
from autosound_tcc.ui.tcc.mock_data import AI_MAIN_MODELS, AI_MODEL_IDS


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("class", "kv-lbl")
    return label


def _said(line: car_source.Line) -> str:
    """A source's sentence in the reader's language; unfilled, and logged, when its arguments do
    not fit the sentence -- a note slot that raised would leave the note on the previous path."""
    text = i18n.t(line.key)
    if not line.args:
        return text
    try:
        return text.format(**line.args)
    except (KeyError, IndexError, ValueError):
        app_log.logger().warning("the sentence %r does not take the arguments %s", line.key,
                                 sorted(line.args), exc_info=True)
        return text


def _seeder():
    """The method's seeding module, or None on an install that has no skill checked out.

    None is a real state, not a bug: `_bundled_profiles` below offers only «Add new» without a
    skill for the same reason -- this dialog is the first screen a fresh install meets, and it
    has to open and say something useful even when the submodule is missing.
    """
    try:
        return vendor_loader.load_project_seed()
    except Exception:  # noqa: BLE001 — no skill: the seeding option simply cannot be offered
        return None


#: What v3.1.2's seed reads beside `project.json`, by the names its `project_seed` gives them
#: (`PROFILE_FILE`, `PROSE_FILES`). Contract 1 does not list those names, so a release may rename
#: either: the preview's memory then keys on these, and says so (`_seed_reads`, G1).
_SEED_READS_V312 = {"PROFILE_FILE": "dsp_profile.json", "PROSE_FILES": ("autosound_context.md",)}


#: The method's seats, in its order, when the skill cannot be loaded (the dialog must still open).
_SEATS_FALLBACK = ("driver", "passenger", "both", "all", "rear_left", "rear_right")


def _seats() -> tuple[str, ...]:
    try:
        return tuple(vendor_loader.load_project().PROJECT_TYPES)
    except Exception:  # noqa: BLE001 — no skill: offer the seats the method is known to have
        return _SEATS_FALLBACK


def _seat_label(seat: str) -> str:
    """The seat in the method's own words (its form's translations), so the form and this dialog
    name a seat the same way; the code itself when no translation says otherwise."""
    import json

    for lang in (i18n.current_language(), "en"):
        path = vendor_loader.rew_tool_dir() / "intake_i18n" / f"{lang}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        label = (((data.get("fields") or {}).get("goal.reference_seat") or {})
                 .get("enum") or {}).get(seat)
        if label:
            return str(label)
    return seat


def _source_seat(source: Path) -> Optional[str]:
    """The seat the source project was tuned for, or None when it never said."""
    import json

    try:
        data = json.loads((source / "project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        return vendor_loader.load_project().project_type(data)
    except Exception:  # noqa: BLE001 — an older method: read the field itself
        return data.get("project_type")


def _fs_carried(target: Path) -> Optional[int]:
    """How many channels of a freshly seeded project carry a driver's Fs, or None when its
    `project.json` cannot be read. A carried Fs arrives wrapped as a fact (`{"value": …}`), an
    older one may still be a bare number; either counts while it holds a value."""
    import json

    try:
        data = json.loads((target / "project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    count = 0
    for row in data.get("channels") or []:
        fs = row.get("fs_hz") if isinstance(row, dict) else None
        if isinstance(fs, dict):
            fs = fs.get("value")
        if fs is not None:
            count += 1
    return count


def _bundled_profiles() -> list[tuple[str, str]]:
    """(vendor, name) pairs of the method's library of reference profiles, in its own order:
    `list_bundled()` of the skill TCC loads, over `config.bundled_profiles_dir()` (#175 D-1).

    Picking one of these guarantees an EXACT match against `dsp_profile.find_bundled()`'s
    deliberately strict, no-fuzzy-matching check (project-intake.md §4) -- free-typing "Helix" /
    "Ultra S" against a profile actually keyed `Audiotec-Fischer` / `Helix DSP Ultra S` is exactly
    how a real bundled profile gets missed (user report 2026-07-29).

    Empty, with a warning in the log, when there is no library to read: no skill found, one that
    does not load here, or one older than v3.0.19, which keeps none. The picker then offers only
    «Add new», whose fields name a DSP all the same -- this dialog is the first screen a fresh
    install meets, and it has to open."""
    try:
        library = config.bundled_profiles_dir()
        rows = [] if library is None else vendor_loader.load_dsp_profile().list_bundled(str(library))
        pairs = [(str(vendor).strip(), str(name).strip()) for vendor, name, _path in rows]
    except Exception as exc:  # noqa: BLE001 — no skill, or one that does not load: only «Add new»
        app_log.logger().warning(
            "the New-project picker offers no reference DSP profile: the method's library could "
            "not be read (%s: %s)", type(exc).__name__, exc,
            exc_info=not isinstance(exc, vendor_loader.VendorNotInitializedError))
        return []
    if library is None:
        app_log.logger().warning("the New-project picker offers no reference DSP profile: the "
                                 "skill at %s keeps no library (it arrived in v3.0.19)",
                                 vendor_loader.skill_dir())
    return [(vendor, name) for vendor, name in pairs if vendor and name]


#: How long the seed-note redraw waits for typing to stop. Below the threshold where the note
#: feels laggy, above any typing rhythm — see `NewProjectDialog._refresh_seed_note` for what the
#: redraw actually costs.
_SEED_NOTE_DELAY_MS = 250


class NewProjectDialog(QDialog):
    """Collects folder + vendor + model + how the AI runs, creates the project, and hands the
    caller (`main_window._open_new_project_dialog`) what it needs to open the new window on the
    intake form."""

    def __init__(self, parent=None, seed_first: bool = False) -> None:
        """`seed_first` opens straight on "copy from an existing project": the main menu offers
        that as its own act ("Copy the car…"), because starting from a car somebody has already
        described is a different intent from starting a project from nothing -- not a second
        button for the same one."""
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(i18n.t("npTitle"))
        self.setMinimumWidth(420)
        #: `describe()`'s answer for the folder currently picked, kept so the note can be redrawn
        #: when the DSP choice changes without reading the folder again.
        self._seed_describes = None
        #: `_prefill_dsp` writes into the DSP fields, and those fields redraw the note -- without
        #: this the two would call each other. Set while prefilling, cleared after.
        self._prefilling = False
        #: Drawing the seed note runs a real seed, and everything that asks for one comes through
        #: this timer (#172). See `_refresh_seed_note`. Single-shot and restarted, so a run of
        #: keystrokes, ticks and picks is one run.
        self._seed_note_timer = QTimer(self)
        self._seed_note_timer.setSingleShot(True)
        self._seed_note_timer.timeout.connect(self._refresh_seed_note_now)
        #: The last preview: what its seed read, and what it answered (`_would_travel`, #172).
        self._preview_memo: Optional[tuple] = None
        #: The seeder's names `_seed_reads` last had to stand in for, said once (G1).
        self._seed_names_said: Optional[tuple[str, ...]] = None
        # Set by _on_create() instead when "run via" picks a terminal CLI rather than the in-app
        # chat -- main_window._open_new_project_dialog() branches on whichever ended up non-None.
        self.open_terminal_cli: Optional[str] = None
        self.project_dir: Optional[Path] = None
        self.onboarding_vendor: str = ""
        self.onboarding_model: str = ""
        self.onboarding_ai_model: Optional[str] = None
        #: The in-app pick, kept for the new window: no interview carries it any more (hub #194),
        #: and a model chosen here and dropped is a window that opens on "no model chosen" (user,
        #: 2026-08-23).
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
        # The typed text goes through the source picker (G13 C2): a folder is itself, and a new
        # source of a car is a module in `car_source.SOURCES`, not code here.
        self._picker = car_source.Picker()
        self._seed_resolved: Optional[car_source.Resolved] = None
        self._seed_edit = QLineEdit()
        self._seed_edit.setPlaceholderText(i18n.t("npSeedPlaceholder"))
        self._seed_edit.textChanged.connect(self._on_seed_source)
        seed_row.addWidget(self._seed_edit, stretch=1)
        # One browse button per source; the first is `_seed_browse`, as before.
        self._seed_browse_buttons: list[QPushButton] = []
        for source in self._picker.sources:
            button = QPushButton(i18n.t(source.chooser.label_key))
            button.setProperty("class", "reason-btn")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, chooser=source.chooser: self._on_browse_source(chooser))
            seed_row.addWidget(button)
            self._seed_browse_buttons.append(button)
        self._seed_browse = self._seed_browse_buttons[0]
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

        # ON by default, the other way round from the findings: the drivers' Fs are the same
        # drivers in the same doors, and «імпеданс складна штука і міряти його другий раз це
        # подвиг» (the Arbiter, hub #185; tcc#93). Unticked, this build measures its own.
        self._seed_fs = QCheckBox(i18n.t("npSeedFs"))
        self._seed_fs.setChecked(True)
        self._seed_fs.toggled.connect(self._refresh_seed_note)
        layout.addWidget(self._seed_fs)

        # The seat never travels: another seat is why a copy exists (hub #193, SKL-048). So it
        # is chosen HERE, with no default, and the source's own seat is said beside the choice.
        self._seat_label = _field_label(i18n.t("npSeat"))
        layout.addWidget(self._seat_label)
        self._seat_combo = QComboBox()
        self._seat_combo.setProperty("class", "mini-select")
        self._seat_combo.addItem(i18n.t("npSeatPick"), None)
        for seat in _seats():
            self._seat_combo.addItem(_seat_label(seat), seat)
        self._seat_combo.currentIndexChanged.connect(self._sync_create_enabled)
        self._seat_combo.currentIndexChanged.connect(self._refresh_seed_note)
        layout.addWidget(self._seat_combo)
        self._seat_source = QLabel("")
        self._seat_source.setWordWrap(True)
        self._seat_source.setProperty("class", "kv-lbl")
        layout.addWidget(self._seat_source)

        layout.addWidget(_field_label(i18n.t("npProfile")))
        self._profile_combo = QComboBox()
        self._profile_combo.setProperty("class", "mini-select")
        for vendor, name in _bundled_profiles():
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
        # The default by name, not the list's first row: the list is newest first, and a new
        # model joining it must not move what a new project starts on (tcc#64).
        default = {model: name for name, model in model_choices.SDK_MODELS}.get(
            model_choices.DEFAULT_SDK_MODEL)
        if default:
            self._ai_combo.setCurrentText(default)
        layout.addWidget(self._ai_combo)

        # Terminal path's own model field: free-text, since each CLI has its own model-name
        # vocabulary (TCC doesn't maintain a Gemini/Codex catalog the way it does for Claude) --
        # passed through as `--model <value>` (terminal_launcher.launch), blank = CLI's own default.
        self._terminal_model_label = _field_label(i18n.t("npTerminalModel"))
        layout.addWidget(self._terminal_model_label)
        self._terminal_model_edit = QLineEdit()
        # The examples are model names, so they live in the catalogue, not in the sentence:
        # spelled out here they were four translations to edit every generation (HUB-052).
        self._terminal_model_edit.setPlaceholderText(
            i18n.t("npTerminalModelPlaceholder").format(
                models=", ".join(model_choices.TERMINAL_MODEL_EXAMPLES)))
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
        for widget in (self._seed_edit, *self._seed_browse_buttons, self._seed_summary,
                       self._seed_findings, self._seed_fs, self._seat_label, self._seat_combo,
                       self._seat_source):
            widget.setVisible(copying)
        if copying:
            self._on_seed_source(self._seed_edit.text())

    def _seed_source(self) -> Optional[Path]:
        """The folder to seed from, or None -- the single place that answers "are we copying".

        Through the picker: another source's input resolves to the folder it holds, and one no
        source takes leaves a problem (`_seed_problem`) instead of a folder."""
        if self._seed_combo.currentData() != "copy":
            self._seed_resolved = None
            return None
        self._seed_resolved = self._picker.resolve(self._seed_edit.text())
        return self._seed_resolved.folder if self._seed_resolved is not None else None

    def _seed_problem(self) -> Optional[car_source.Line]:
        """Why the typed source cannot be copied from, as its source said it; None if it can."""
        return self._seed_resolved.problem if self._seed_resolved is not None else None

    def _on_seed_source(self, _text: str) -> None:
        """Say what the picked folder is while it is still being picked.

        A folder either has a readable `project.json` or it does not, and that is knowable the
        moment it is typed -- so it is answered here rather than as a failure after Create.
        """
        source = self._seed_source()
        seeder = _seeder()
        summary = seeder.describe(source) if (source is not None and seeder) else None
        self._seed_describes = summary
        seat = _source_seat(source) if (source is not None and summary is not None) else None
        self._seat_source.setText(i18n.t("npSeatSource").format(
            seat=_seat_label(seat) if seat else i18n.t("npSeatUnset")) if summary else "")
        if source is None:
            problem = self._seed_problem()
            self._set_seed_note(_said(problem) if problem else "", warn=problem is not None)
            return
        if summary is None:
            # What the source says about itself stays: a package that unpacked into no project
            # still names itself and what it warns of.
            resolved = self._seed_resolved
            lines = [i18n.t("npSeedNotAProject")] + [
                _said(line) for line in ((resolved.about + resolved.warnings) if resolved else ())]
            self._set_seed_note("\n".join(lines), warn=True)
            return
        self._prefill_dsp(source)
        # On the pause, as everything else that draws the note (#172). It was drawn at once, for
        # picking a folder is one deliberate act -- but the field fires per character, typed or
        # pasted, and each draw is a whole seed. `_prefill_dsp` has armed the same timer through
        # the DSP fields, so the folder and the DSP it filled in are one preview, not two.
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

        Returns `(report, fs)`: `fs` is how many drivers' Fs landed, read off the preview's own
        `project.json` before the folder goes, because the report has no count for them (tcc#93).

        The last answer is remembered (#172). The seed's last act is `project_repo.init`: six to
        eight git children, and `gh api user` for up to 30 s where git has no identity -- all on
        the GUI thread. So a question asked again is answered from memory: a box ticked and
        unticked inside one pause, the same folder picked twice, a redraw nothing changed.
        `_preview_key` says what counts as the same question. Only an ok answer is kept: a refusal
        can be passing -- an antivirus holding the temporary file at `os.replace`, a full temporary
        disk -- and every refusal in `seed()` comes before `project_repo.init`, so asking again
        starts no git child. Nor is a preview that raised.
        """
        seeder = _seeder()
        if seeder is None:
            return None, None
        key = self._preview_key(seeder, source)
        if key is not None and self._preview_memo is not None and self._preview_memo[0] == key:
            return self._preview_memo[1]
        self._preview_memo = None
        with tempfile.TemporaryDirectory(prefix="tcc-seed-preview-") as tmp:
            target = Path(tmp) / "preview"
            target.mkdir()
            try:
                report = seeder.seed(
                    source,
                    target,
                    include_findings=self._seed_findings.isChecked(),
                    include_fs=self._seed_fs.isChecked(),
                    copy_profile=seeder.dsp_of(source) == (
                        self._vendor_edit.text().strip(), self._model_edit.text().strip()),
                    note=i18n.t("npSeedNote"),
                    seat=self._seat_combo.currentData(),
                )
                # Inside too: it reads what the seed wrote, which nobody has checked (tcc#123).
                answer = report, _fs_carried(target)
            except Exception:      # noqa: BLE001 — a preview must never take the dialog down
                # …and must leave a trace (the group review, M4): a method bug in `seed()` for
                # this source was invisible until Create hit it.
                app_log.logger().warning("the seed preview for %s raised", source, exc_info=True)
                return None, None
        if key is not None and report is not None and report.ok:
            self._preview_memo = (key, answer)
        return answer

    def _preview_key(self, seeder, source: Path) -> tuple:
        """Everything the preview's seed reads, as it is now — the files by the seeder's own
        names, or v3.1.2's where it lacks one (`_seed_reads`), so the memory never goes off unseen.

        From the dialog: every argument `_would_travel` hands `seed()`, as the fields hold it --
        vendor and model rather than the `copy_profile` they decide, and the profile choice with
        them. From the source folder: each file the seed reads -- `project.json`, the DSP profile,
        the prose -- by path, modification time and size, so a save from the source's own window,
        a file put there or taken away, is a new question. And the seeder itself: an update reads
        the method again while the dialog is open (#126).

        Left out, because they cannot change what the note draws -- whether the seed is ok, its
        counts, the Fs:

        * the source's `process/` record. It lands in the import record as
          `protective_by_channel()` rows, `{legs, round, version, source}`. `save()`'s validator
          walks every fact wrapper (`{value, source, at}`) in the file, the import record's
          included, and refuses one whose `origin` it does not know; the rows are never wrappers,
          and their `legs` is one only in a journal written by hand. `_protective_history`
          swallows its own errors besides. Were the method to carry wrappers there, this record
          would belong in the key;
        * whether its `measurements_repo` path exists: that moves one string between `paths` and
          the import record, and the validator has no rule for `paths`;
        * today's date, and what `project_repo.init` finds (`report.repo`, `.git` in `written`).
        """
        files = []
        for name in ("project.json", *self._seed_reads(seeder)):
            path = Path(source) / name
            try:
                stat = path.stat()
            except (OSError, ValueError):  # not there, not ours to read, not a path at all
                files.append((str(path), None, None))
            else:
                files.append((str(path), stat.st_mtime_ns, stat.st_size))
        return (seeder, str(source), tuple(files),
                self._seed_findings.isChecked(), self._seed_fs.isChecked(),
                self._vendor_edit.text().strip(), self._model_edit.text().strip(),
                self._profile_combo.currentData(), self._seat_combo.currentData(),
                i18n.t("npSeedNote"))

    def _seed_reads(self, seeder) -> tuple[str, ...]:
        """The files the seed reads besides `project.json`, by the seeder's own names (G1).

        `PROFILE_FILE` and `PROSE_FILES` are outside contract 1, and a seeder that lacked one made
        the key None: the memory switched off without a word, and every redraw was a whole seed on
        the GUI thread again, the freeze #172 removed. A name the seeder lacks, or holds as no
        name, is v3.1.2's instead, with one WARNING naming it — a release that reads another file
        is then answered from memory when that file changes, and the log says why."""
        profile = getattr(seeder, "PROFILE_FILE", None)
        prose = getattr(seeder, "PROSE_FILES", None)
        missing = []
        if not isinstance(profile, str):
            missing.append("PROFILE_FILE")
            profile = _SEED_READS_V312["PROFILE_FILE"]
        if not (isinstance(prose, (tuple, list)) and all(isinstance(name, str) for name in prose)):
            missing.append("PROSE_FILES")
            prose = _SEED_READS_V312["PROSE_FILES"]
        if missing and tuple(missing) != self._seed_names_said:
            self._seed_names_said = tuple(missing)
            app_log.logger().warning(
                "the method's project_seed names no %s; the seed preview is remembered under "
                "TCC's copy of v3.1.2's names instead (%s)", " or ".join(missing),
                ", ".join(f"{name}={_SEED_READS_V312[name]!r}" for name in missing))
        return (profile, *prose)

    def _refresh_seed_note(self, *_args) -> None:
        """Ask for a redraw — on a short delay, because drawing this note runs a whole seed.

        Every trigger comes here (#172): the source field and the vendor and model fields are
        `textChanged`, so they fire per CHARACTER, and the two ticks, the seat and the profile
        come with them. And `_would_travel` is not a lookup: it creates a temporary directory, runs
        the real seeder into it (read the source project, validate it against the schema, write a
        new `project.json`, a `.gitignore`, copy the DSP profile and the prose, make it a git
        repository), reads the report and deletes the lot — on the GUI thread. Typing
        "Audiotec-Fischer" did that seventeen times, and the dialog resized under the cursor after
        each one; the source field and the ticks still drew at once until #172.

        A quarter of a second is below the threshold where the note feels laggy and above any
        typing rhythm, so what runs is one seed per pause rather than one per keystroke — and
        none, when the pause ends on a question already answered (`_would_travel`).
        """
        self._seed_note_timer.start(_SEED_NOTE_DELAY_MS)

    def _refresh_seed_note_now(self) -> None:
        """Redraw the note: what the timer runs once the pause is over. Asked for again whenever
        the DSP choice changes, because the DSP is what decides how much of the source travels."""
        if self._prefilling or self._seed_describes is None:
            return
        # The DSP fields are built after this label, and `_on_seed_mode` can fire in between.
        if getattr(self, "_vendor_edit", None) is None:
            return
        source = self._seed_source()
        if source is None:
            return
        summary = self._seed_describes
        resolved = self._seed_resolved
        lines = [i18n.t("npSeedSummary").format(
            car=summary.car, dsp=summary.dsp or "—", channels=summary.channels)]
        # What the source says about itself sits under the summary; its warnings come last.
        lines += [_said(line) for line in (resolved.about if resolved else ())]
        report, fs = self._would_travel(source)
        if report is not None and report.ok:
            key = "npSeedTravelsFindings" if self._seed_findings.isChecked() else "npSeedTravels"
            travels = i18n.t(key).format(
                channels=report.channels, amps=report.amps,
                flaws=report.flaws, questions=report.questions)
            if self._seed_fs.isChecked() and fs is not None:
                # Zero is said too, as a real answer: the source measured none, or a different
                # processor leaves the channels behind and their Fs with them (the line below).
                # The last part of the one line that says what travels (tcc#122: it was a second
                # «Travels:» line of its own).
                travels += " · " + i18n.t("npSeedTravelsFs").format(fs=fs)
            lines.append(travels)
            if self._seed_findings.isChecked() and (report.flaws or report.questions):
                # Where those rows POINT, not just how many: their `evidence` names captures that
                # exist in the source project and nowhere in this one. Carrying them is legitimate
                # — they are the same car — but a row whose proof lives elsewhere is a different
                # thing from one measured here, and the person ticking the box is who has to know.
                lines.append(i18n.t("npSeedFindingsEvidence"))
            if summary.channels and not report.channels:
                # The one a person has to read BEFORE pressing Create: wanting the findings and
                # not the channels was impossible, so the working answer was to go around the
                # seeder by hand — and the findings only travel with it.
                lines.append(i18n.t("npSeedNoChannels"))
        lines += [_said(line) for line in (resolved.warnings if resolved else ())]
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
        holds a pair that matched once already -- so when it is in the library, select that entry;
        when it is not, fall to "Add new" with the fields filled, which is the same state a person
        reaches by typing them correctly.
        """
        seeder = _seeder()
        pair = seeder.dsp_of(source) if seeder else None
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
        them for a DSP that isn't in the method's library yet."""
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
        copying = self._seed_combo.currentData() == "copy"
        seat_combo = getattr(self, "_seat_combo", None)  # built after the seed picker
        self._create_btn.setEnabled(
            bool(self._folder_edit.text().strip())
            and bool(self._vendor_edit.text().strip())
            and bool(self._model_edit.text().strip())
            and (not copying or (seat_combo is not None and seat_combo.currentData() is not None))
        )

    def _on_browse(self) -> None:
        start = self._folder_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, i18n.t("npFolder"), start)
        if chosen:
            self._folder_edit.setText(chosen)

    def _on_browse_source(self, chooser: car_source.Chooser) -> None:
        start = self._seed_edit.text().strip() or str(config.project_dir())
        title = i18n.t(chooser.title_key)
        if chooser.kind == "file":
            wanted = i18n.t(chooser.filter_key) if chooser.filter_key else ""
            chosen, _filter = QFileDialog.getOpenFileName(self, title, start, wanted)
        else:
            chosen = QFileDialog.getExistingDirectory(self, title, start)
        if chosen:
            self._seed_edit.setText(chosen)

    def done(self, result: int) -> None:  # Qt override: accept and reject both end here
        """Closing lets go of whatever a source held (a package's temporary folder, later), and
        of a preview still waiting for its pause: it would seed for nobody, from a source just let
        go of (#172)."""
        self._seed_note_timer.stop()
        self._picker.release()
        super().done(result)

    def _on_create(self) -> None:
        # Create answers for the fields as they are now; a preview still waiting for its pause
        # would draw over the refusal below (#172).
        self._seed_note_timer.stop()
        source = self._seed_source()  # what the picker holds for the text as it is now
        problem = self._seed_problem()
        if problem is not None or (source is None and self._seed_combo.currentData() == "copy"):
            # A refused source creates nothing — not an empty project in the copy's place; and
            # «Copy» with nothing named is not a new project either.
            self._set_seed_note(_said(problem) if problem else i18n.t("npSeedEmpty"), warn=True)
            return
        project_dir = Path(self._folder_edit.text().strip()).expanduser()
        vendor = self._vendor_edit.text().strip()
        model = self._model_edit.text().strip()

        # Mirrors dsp_profile_interview.py's CLI path exactly -- OnboardingSession itself does not
        # create the folder.
        project_dir.mkdir(parents=True, exist_ok=True)

        # Before `set_project_dir`, deliberately: a seeding that fails leaves the folder as it was
        # and TCC pointed where it was, rather than parked on a half-made project.
        if source is not None:
            seeder = _seeder()
            if seeder is None:
                self._set_seed_note(i18n.t("npSeedNoSkill"), warn=True)
                return
            report = seeder.seed(
                source,
                project_dir,
                include_findings=self._seed_findings.isChecked(),
                include_fs=self._seed_fs.isChecked(),
                # The profile travels only when it is the same DSP. Pick a different one and its
                # capabilities are a question for the form's /new-dsp page, not a file to inherit.
                copy_profile=seeder.dsp_of(source) == (vendor, model),
                note=i18n.t("npSeedNote"),
                seat=self._seat_combo.currentData(),
            )
            if not report.ok:
                # The module answers in English, with a path in it, because it is a library and
                # has no language. The two refusals a person actually meets get said HERE, in
                # theirs, and the raw sentence is kept only for the ones nobody predicted.
                self._set_seed_note(self._why_refused(source, project_dir, report), warn=True)
                return
            # Named after what the person picked (a package file, later), not the folder a source
            # unpacked it into: that one is gone once the dialog closes.
            self.seeded = report
            self.seeded_from = Path(self._seed_edit.text().strip()).expanduser()

        config.set_project_dir(project_dir)
        self.project_dir = project_dir

        cli = self._run_via_combo.currentData()
        if cli is None:
            self.in_app_model = AI_MODEL_IDS.get(self._ai_combo.currentText())
        else:
            self.open_terminal_cli = cli
            self.onboarding_vendor = vendor
            self.onboarding_model = model
            self.onboarding_ai_model = self._terminal_model_edit.text().strip() or None
        self.accept()
