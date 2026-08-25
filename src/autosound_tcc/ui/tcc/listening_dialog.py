"""Phase 4: what to judge in the track playing, and what you heard.

**The shape is the user's own** (2026-08-25): a tree of tracks on the right; open a track, open a
characteristic, and under it stand the two finished sentences — one for right, one for wrong. Click
one and it lands in the box on the left as a line you then rewrite freely. He asked for exactly
this and it is worth saying why it is better than a form: the hard part of an ear verdict is not
typing, it is knowing what this track was chosen to expose. Handing over a sentence answers that
question and leaves the wording his.

**The tick and the text are both kept, and neither stands for the other.** Clicking a phrase
records a pair (track × characteristic × ok/bad) AND writes a line; editing the line afterwards is
expected and does not touch the pair. The alternative — deriving the structure from the final text
— would have to guess, and would guess wrong the first time somebody wrote "not really" under a
🟢 phrase. So the journal entry carries both, and the panel never pretends they are one thing.

**Music does not come out of this machine.** He plays test tracks from a player or the head unit,
so TCC cannot know what is on — there is no now-playing to read and nothing here tries. The route
says what comes next and the clicks say what happened; that is the whole input.

**The vocabulary is the method's.** Every word in the tree comes from `rew_tool/listening.py`
through `core/listening.py`; this file composes lines out of them and never writes one of its own.
An entry the method has not translated yet is shown in English and SAID to be untranslated, rather
than blanked — translations and new ids arrive in different commits.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import listening, process_writer
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.theme import mini_combo

#: What a tree item carries, when it carries anything. Only a PHRASE item is clickable — the track
#: and characteristic levels are there to be opened, and answer `None` here.
_PAIR = Qt.ItemDataRole.UserRole


class ListeningDialog(QDialog):
    """The tree, the text, and the ticks — with the ledger version they were heard against."""

    def __init__(self, project_dir: Path, sheet: listening.Sheet,
                 ledger_version: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(i18n.t("lsnTitle"))
        self.setMinimumSize(1000, 620)
        self._project_dir = Path(project_dir)
        self._sheet = sheet
        self._version = ledger_version or ""
        #: `[(track, characteristic, ok)]` in click order. A list and not a set: ticking the same
        #: characteristic twice is a person changing their mind, and the LAST answer is the one
        #: that counts -- but the earlier line is already in their text, which is theirs to fix.
        self._pairs: list[tuple[str, str, bool]] = []
        self.written = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        why = QLabel(i18n.t("lsnWhy"))
        why.setWordWrap(True)
        why.setProperty("class", "kv-lbl")
        layout.addWidget(why)

        if sheet.problems:
            problems = QLabel(i18n.t("lsnProblems").format(problems="; ".join(sheet.problems)))
            problems.setWordWrap(True)
            problems.setProperty("class", "kv-warn")
            layout.addWidget(problems)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_left())
        split.addWidget(self._build_right())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 4)
        layout.addWidget(split, stretch=1)

        self._problem = QLabel("")
        self._problem.setWordWrap(True)
        self._problem.setProperty("class", "kv-warn")
        self._problem.setVisible(False)
        layout.addWidget(self._problem)

        actions = QHBoxLayout()
        self._sheet_btn = QPushButton(i18n.t("lsnSheet"))
        self._sheet_btn.setProperty("class", "reason-btn")
        self._sheet_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sheet_btn.clicked.connect(self._open_sheet)
        actions.addWidget(self._sheet_btn)
        actions.addStretch(1)
        cancel = QPushButton(i18n.t("npCancel"))
        cancel.setProperty("class", "reason-btn")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self._save = QPushButton(i18n.t("lsnSave"))
        self._save.setProperty("class", "composer-send-ok")
        self._save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save.clicked.connect(self._on_save)
        actions.addWidget(self._save)
        layout.addLayout(actions)

        self._refresh_ticked()

    # ------------------------------------------------------------------ left
    def _build_left(self) -> QWidget:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 8, 0)
        column.setSpacing(6)

        stamp = QLabel(i18n.t("lsnVersion").format(version=self._version) if self._version
                       else i18n.t("lsnNoVersion"))
        stamp.setWordWrap(True)
        stamp.setProperty("class", "kv-lbl" if self._version else "kv-warn")
        column.addWidget(stamp)

        self._text = QPlainTextEdit()
        self._text.setPlaceholderText(i18n.t("lsnText"))
        column.addWidget(self._text, stretch=1)

        self._ticked = QLabel("")
        self._ticked.setWordWrap(True)
        self._ticked.setTextFormat(Qt.TextFormat.RichText)
        self._ticked.setProperty("class", "kv-lbl")
        column.addWidget(self._ticked)

        drop = QPushButton(i18n.t("lsnDropLast"))
        drop.setProperty("class", "reason-btn")
        drop.setCursor(Qt.CursorShape.PointingHandCursor)
        # Qt's sizeHint for a QPushButton does not account for the horizontal padding the
        # stylesheet adds (`.reason-btn` is `padding: 4px 12px`), so a label longer than the
        # short ones this class was built for gets its first letter clipped -- seen in the render,
        # not in a test. Ask the font how wide the text is and leave room for the padding.
        drop.setMinimumWidth(drop.fontMetrics().horizontalAdvance(drop.text()) + 34)
        drop.setToolTip(i18n.t("lsnRemoveTip"))
        drop.clicked.connect(self._drop_last)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(drop)
        column.addLayout(row)
        self._drop_btn = drop

        hint = QLabel(i18n.t("lsnOwnHint"))
        hint.setWordWrap(True)
        hint.setProperty("class", "kv-lbl")
        column.addWidget(hint)
        return holder

    # ----------------------------------------------------------------- right
    def _build_right(self) -> QWidget:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(8, 0, 0, 0)
        column.setSpacing(6)

        head = QHBoxLayout()
        head.addWidget(QLabel(i18n.t("lsnRoute")))
        self._route = mini_combo()
        for name in self._sheet.routes:
            self._route.addItem(i18n.t(f"lsnRoute_{name}") if f"lsnRoute_{name}" in i18n.T["en"]
                                else name, name)
        self._route.currentIndexChanged.connect(self._fill_tree)
        head.addWidget(self._route)
        head.addStretch(1)
        column.addLayout(head)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setUniformRowHeights(False)
        self._tree.setWordWrap(True)
        self._tree.itemActivated.connect(self._on_item)
        self._tree.itemClicked.connect(self._on_item)
        column.addWidget(self._tree, stretch=1)
        self._fill_tree()
        return holder

    def _fill_tree(self) -> None:
        self._tree.clear()
        route = self._route.currentData()

        steps = self._sheet.routes.get(route, ())
        root = QTreeWidgetItem(self._tree, [i18n.t("lsnRouteRoot")])
        for step in steps:
            track = self._sheet.tracks.get(step.track)
            phrase = self._sheet.phrase(step.track, step.characteristic)
            if track is None or phrase is None:
                continue
            node = QTreeWidgetItem(root, [f"{step.n}. {listening.track_label(track)}"])
            self._add_phrase(node, track.id, phrase)
            node.setExpanded(True)
        root.setExpanded(True)

        everything = QTreeWidgetItem(self._tree, [i18n.t("lsnAll")])
        for library in self._sheet.libraries:
            shelf = QTreeWidgetItem(everything, [library])
            for track in self._sheet.tracks.values():
                if track.library != library or not track.phrases:
                    continue
                node = QTreeWidgetItem(shelf, [listening.track_label(track)])
                for phrase in track.phrases:
                    self._add_phrase(node, track.id, phrase)

    def _add_phrase(self, parent: QTreeWidgetItem, track_id: str,
                    phrase: listening.Phrase) -> None:
        """One characteristic under a track, with its two finished sentences beneath it.

        The timecode rides on the CHARACTERISTIC row, not the track's: one track exposes several
        things and usually only one of them happens at a stated moment (#07 carries four checks and
        only the whisper has a time). Putting it on the track would point at the wrong one.
        """
        label = phrase.label
        if phrase.timecode:
            label = f"{label} · {i18n.t('lsnAt').format(timecode=phrase.timecode)}"
        holder = QTreeWidgetItem(parent, [label])
        tip = i18n.t("lsnCueTip").format(cue=phrase.cue)
        if phrase.route_hint:
            tip = f"{tip}\n{i18n.t('lsnRouteTip').format(route=phrase.route_hint)}"
        if not phrase.translated:
            tip = f"{tip}\n{i18n.t('lsnNotTranslated')}"
        holder.setToolTip(0, tip)
        for ok, text in ((True, phrase.good), (False, phrase.bad)):
            leaf = QTreeWidgetItem(holder, [f"{'🟢' if ok else '❌'} {text}"])
            leaf.setData(0, _PAIR, (track_id, phrase.characteristic, ok))
            leaf.setToolTip(0, tip)

    # --------------------------------------------------------------- clicking
    def _on_item(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        pair = item.data(0, _PAIR)
        if pair is None:
            item.setExpanded(not item.isExpanded())
            return
        track_id, characteristic, ok = pair
        self._pairs.append((track_id, characteristic, ok))
        self._append_line(track_id, characteristic, ok)
        self._refresh_ticked()

    def _append_line(self, track_id: str, characteristic: str, ok: bool) -> None:
        track = self._sheet.tracks.get(track_id)
        phrase = self._sheet.phrase(track_id, characteristic)
        if track is None or phrase is None:
            return
        line = (f"{listening.track_label(track)} — {phrase.label}: "
                f"{phrase.verdict_text(ok)} {'🟢' if ok else '❌'}")
        existing = self._text.toPlainText()
        self._text.setPlainText(f"{existing}\n{line}" if existing.strip() else line)
        self._text.moveCursor(self._text.textCursor().MoveOperation.End)

    def _drop_last(self) -> None:
        """Undo the last tick, and leave the text alone.

        Deliberately does not edit what it wrote: by the time somebody presses this they may have
        rewritten that line, and a widget that goes hunting for its own sentence in edited prose
        deletes the wrong one eventually.
        """
        if self._pairs:
            self._pairs.pop()
            self._refresh_ticked()

    def _refresh_ticked(self) -> None:
        if not self._pairs:
            self._ticked.setText(i18n.t("lsnTickedEmpty"))
            self._drop_btn.setEnabled(False)
            return
        parts = []
        for track_id, characteristic, ok in self._pairs:
            phrase = self._sheet.phrase(track_id, characteristic)
            label = phrase.label if phrase else characteristic
            parts.append(f"{track_id} · {label} {'🟢' if ok else '❌'}")
        self._ticked.setText(i18n.t("lsnTicked").format(n=len(self._pairs))
                             + "<br>" + "<br>".join(parts))
        self._drop_btn.setEnabled(True)

    # ----------------------------------------------------------------- saving
    def _on_save(self) -> None:
        if not self._pairs:
            self._problem.setText(i18n.t("lsnNoPairs"))
            self._problem.setVisible(True)
            return
        try:
            process_writer.record_listening_verdict(
                self._project_dir,
                self._pairs,
                text=self._text.toPlainText().strip(),
                route=self._route.currentData() or "",
                ledger_version=self._version,
            )
        except Exception as exc:  # noqa: BLE001 — the gate's own words, not ours
            self._problem.setText(i18n.t("lsnRefused").format(why=_last_line(str(exc))))
            self._problem.setVisible(True)
            return
        self.written = len(self._pairs)
        self.accept()

    def saved_message(self) -> str:
        return i18n.t("lsnSaved").format(n=self.written, version=self._version or "—")

    # ------------------------------------------------------------ whole sheet
    def _open_sheet(self) -> None:
        """The method's own page, rendered, in a window of its own.

        No format was asked of the skill for this: the file IS the deliverable, and summarising it
        here would put a second copy of the wording in the app — the thing this whole feature was
        shaped to avoid.
        """
        try:
            text = listening.sheet_text(self._sheet.lang)
        except listening.ListeningUnavailable as exc:
            self._problem.setText(i18n.t("lsnUnavailable").format(why=str(exc)))
            self._problem.setVisible(True)
            return
        window = QDialog(self)
        window.setWindowTitle(i18n.t("lsnSheetTitle"))
        window.resize(860, 720)
        box = QVBoxLayout(window)
        box.setContentsMargins(12, 12, 12, 12)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        # Qt's own Markdown reader, not the chat panel's `_markdown`: that one renders "the little
        # of Markdown a tuning answer actually uses" and the cheat sheet is a real document —
        # tables, headings, quotes. GitHub dialect because the tables are pipe tables.
        view.document().setMarkdown(text, QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
        box.addWidget(view)
        window.exec()


def _last_line(text: str) -> str:
    """The gate's sentence, without the traceback the CLI wraps it in."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if not line.startswith(("File \"", "Traceback", "  ")):
            return line
    return lines[-1] if lines else ""


def open_for(project_dir: Path, view=None, parent=None):
    """Build the dialog, or return the reason it cannot be built.

    Returns `(dialog, None)` or `(None, message)`. A window that opens and then explains itself is
    worse than a button that says why it did nothing.
    """
    try:
        sheet = listening.load(i18n.current_language())
    except listening.ListeningUnavailable as exc:
        return None, i18n.t("lsnUnavailable").format(why=str(exc))
    if not sheet.tracks:
        return None, i18n.t("lsnUnavailable").format(why="no tracks in the method's index")
    return ListeningDialog(project_dir, sheet, getattr(view, "version", None), parent=parent), None
