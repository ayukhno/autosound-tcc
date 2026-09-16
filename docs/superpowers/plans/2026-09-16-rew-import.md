# Importing from REW Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The import window names a measurement from the list of what the round still waits for and takes protective filters with the Protection form's own fields; the checklist shows blue for "in REW, not taken"; the series `_N` is read by the method's grammar and never derived from the ledger version.

**Architecture:** Rework in place (no new windows): `state/measurement_view.py` gains a `found` status, a grammar-based series reader and round matching by the `_N` of a round's titles; `ui/tcc/main_window.py` derives the series from the open round, the plan, then the rounds; `ui/tcc/protective_dialog.py` shares its leg fields with a one-row form; `ui/tcc/capture_import_dialog.py` gets a name-list delegate and a protective cell.

**Tech Stack:** Python 3.12, PySide6 (QTableWidget, QStyledItemDelegate, QInputDialog), pytest, the method's `rew_tool/naming.py` at the `v3.0.52` pin.

**Spec:** `docs/superpowers/specs/2026-09-16-rew-import-design.md`

## Global Constraints

- The method is pinned at `v3.0.52`: `naming.parse_name` returns `code`, `code_current`, `version` (str), `version_n` (int), `method`, `modifier`, `position`, `control`, `title`; no `params`, no `(imp)`, no `explain_name`.
- The ledger version (`v_NNN`) is never used as the series `_N`.
- Status strings: `done`, `wait`, `bad`, `skip`, and new `found`; QSS dot class `tl-found`, colour `t.info`.
- Output channels are the view group `physical_outputs` and `project.json` channels whose `tier` is absent, empty, or `channels`.
- Every user-visible string goes through `i18n.t` with en, uk, pl and de entries.
- Tests serial and targeted: `uv run --extra dev --python 3.12 python -m pytest <files> -q -n 0`; ruff `uvx ruff@0.12.0 check <paths>`. The full suite runs once at the end of the wave, not in this plan.
- Commits on `wave-0.1.40`, English subject lines, ending with the session's attribution lines.
- i18n insertions: each new key goes on the line after an existing anchor key in all four language blocks, in file order en, uk, pl, de. The helper below does it; every task that adds keys runs it with its own `KEYS`.

```python
# i18n insertion helper — run from the tcc root with the task's ANCHOR and KEYS filled in.
from pathlib import Path

ANCHOR = '"legWait"'                     # the task names its anchor
KEYS = ['...en line...', '...uk line...', '...pl line...', '...de line...']  # full lines, with "\n"

p = Path("src/autosound_tcc/ui/tcc/i18n.py")
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
at = [i for i, line in enumerate(lines) if ANCHOR in line]
assert len(at) == 4, at
for index, text in sorted(zip(at, KEYS), reverse=True):
    lines.insert(index + 1, text)
p.write_text("".join(lines), encoding="utf-8")
```

---

### Task 1: Blue `found`, and old rounds counted by the series of their titles

**Files:**
- Modify: `src/autosound_tcc/state/measurement_view.py` (status constants; `build_session` rounds loop and `status_for`; `_extras`)
- Test: `tests/test_measurement_view.py`

**Interfaces:**
- Produces: `measurement_view.STATUS_FOUND = "found"`; module function `_round_is_at(round_: dict, version, naming, glossary) -> bool`.

- [ ] **Step 1: Write the failing tests**

In `test_a_title_rew_is_showing_is_not_a_capture_this_project_took`, change the three `STATUS_WAIT` assertions on titles REW is showing to `STATUS_FOUND`, and add a docstring line:

```python
def test_a_title_rew_is_showing_is_not_a_capture_this_project_took(project):
    """User, 2026-09-06: "я ще нічого не зробив, тільки відкрив вікно, а криві замірів вже зелені".

    REW's open list is another application's window — it decides what can be OFFERED. What this
    project took in is what colours a row, and the two are passed in separately for that reason.
    Not green, then — but blue, "it is there, load it" (F-056, the Arbiter 2026-09-16).
    """
    showing = ["sw_1 (sw)", "w-L_1 (sw)"]

    nothing_taken = mv.build_session("0", 1, showing, project, taken=[])
    statuses = {item.name: item.status for g in nothing_taken.groups for item in g.items}
    assert statuses["sw_1 (sw)"] == mv.STATUS_FOUND
    assert statuses["w-L_1 (sw)"] == mv.STATUS_FOUND
    assert statuses["w-R_1 (sw)"] == mv.STATUS_WAIT, "not in REW either: yellow"

    one_taken = mv.build_session("0", 1, showing, project, taken=["sw_1 (sw)"])
    statuses = {item.name: item.status for g in one_taken.groups for item in g.items}
    assert statuses["sw_1 (sw)"] == mv.STATUS_DONE
    assert statuses["w-L_1 (sw)"] == mv.STATUS_FOUND
```

In `test_an_extra_rew_holds_is_green_only_once_it_was_taken`, the first assertion becomes:

```python
    assert extras and extras[0].status == mv.STATUS_FOUND
```

Append:

```python
def test_a_capture_the_open_round_asks_for_again_is_blue_while_rew_holds_it(project):
    process = _round(project, version=1, expected=["w-L_1 (sw)"], taken=["w-L_1 (sw)"])
    process.close_capture("done")
    process.start_capture(1, expected=[_as_typed("w-L_1 (sw)")])

    session = mv.build_session("0", 1, ["w-L_01 (sw)"], project, taken=[])
    statuses = {item.name: item.status for g in session.groups for item in g.items}

    assert statuses["w-L_1 (sw)"] == mv.STATUS_FOUND


def test_an_old_round_opened_with_the_ledger_version_counts_by_the_series_of_its_titles(project):
    """hub #153 C. A round opened as `capture-start v_001` holding `_49` titles was skipped for
    series 49, because only its `version` was compared, and its captures read as not taken. The
    ledger version and `_N` are different counters; the method finds a round by either."""
    process = _round(project, version="v_001", expected=["w-L_49 (sw)"], taken=["w-L_49 (sw)"])
    process.close_capture("done")

    session = mv.build_session("0", 49, [], project, taken=[])
    statuses = {item.name: item.status for g in session.groups for item in g.items}

    assert statuses["w-L_49 (sw)"] == mv.STATUS_DONE
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_measurement_view.py -q -n 0`
Expected: FAIL — `AttributeError: module ... has no attribute 'STATUS_FOUND'`, and the old-round test `'wait' == 'done'`.

- [ ] **Step 3: Implement**

After `STATUS_SKIPPED = "skip"` add:

```python
#: In REW under the name the checklist asks for, and not taken in yet (F-056, the Arbiter
#: 2026-09-16): "not everything green before the import, even when the measurements were found —
#: blue for 'it is there, but has to be loaded explicitly'". Yellow stays for what REW does not
#: hold either.
STATUS_FOUND = "found"
```

Add a module function above `build_session`:

```python
def _round_is_at(round_: dict, version, naming, glossary) -> bool:
    """Whether a round was captured at series `version`: by its own `version`, or by the `_N` its
    titles carry (hub #153 C).

    The two can differ. A round opened with the ledger version (`capture-start v_001`) holding
    `_49` titles is at 49: the ledger's `v_NNN` and the DSP state `_N` are different counters (the
    method's naming-and-structure §3, §5), and its own `protective_record_for` finds a round by
    either.
    """
    wanted = str(version).lstrip("v_").lstrip("0")
    if str(round_.get("version") or "").lstrip("v_").lstrip("0") in ("", wanted):
        return True
    for title in list(round_.get("expected") or []) + list(round_.get("taken") or {}):
        entry = naming.parse_name(str(title), glossary)
        if entry and str(entry.get("version_n")) == wanted:
            return True
    return False
```

In `build_session`, replace:

```python
    for round_at in process_view.capture_rounds(project):
        if str(round_at.get("version") or "").lstrip("v_").lstrip("0") not in (
                "", str(version).lstrip("v_").lstrip("0")):
            continue
```

with:

```python
    for round_at in process_view.capture_rounds(project):
        if not _round_is_at(round_at, version, naming, glossary):
            continue
```

After the line `taken_here = {_key(t) for t in recorded_taken} - {None}` add:

```python
    def not_taken(key) -> str:
        """Blue while REW holds it under this name, yellow while it does not (F-056)."""
        return STATUS_FOUND if key is not None and key in parsed else STATUS_WAIT
```

In `status_for`, replace:

```python
        if key is not None and key in asked_again:
            if key not in taken_here and name not in recorded_taken:
                return STATUS_WAIT  # asked for again by the open round, not taken in it yet
        elif key not in taken_keys and name not in recorded_taken:
            # Waiting, even when REW is showing a curve by that name: a title in another
            # application's list is not this project taking a measurement in (user, 2026-09-06).
            # The read window opens on it ticked, and the tick is what makes it done.
            return STATUS_WAIT
```

with:

```python
        if key is not None and key in asked_again:
            if key not in taken_here and name not in recorded_taken:
                return not_taken(key)  # asked for again by the open round, not taken in it yet
        elif key not in taken_keys and name not in recorded_taken:
            # Not done, even when REW is showing a curve by that name: a title in another
            # application's list is not this project taking a measurement in (user, 2026-09-06).
            # It is blue, though — there to be taken (F-056) — and the tick is what makes it done.
            return not_taken(key)
```

In `_extras`, replace:

```python
                # Ours, at this version, off the checklist — and green only once it was taken in.
                # A curve REW is holding is an offer, not a capture (see `build_session`).
                status=STATUS_DONE if taken_keys is None or key in taken_keys else STATUS_WAIT,
```

with:

```python
                # Ours, at this version, off the checklist — and green only once it was taken in.
                # A curve REW is holding is an offer, not a capture: blue (see `build_session`).
                status=STATUS_DONE if taken_keys is None or key in taken_keys else STATUS_FOUND,
```

In `CHANGELOG.md`, under `## [Unreleased]` → `### Changed`, append:

```markdown
- **A capture REW holds but nobody took in is blue, not yellow** — "it is there, import it". Green
  stays for what was taken in. An old round opened with the ledger version (`v_001`) now counts for
  the series its titles carry (`_49`).
```

- [ ] **Step 4: Run the tests and ruff**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_measurement_view.py -q -n 0` → PASS
Run: `uvx ruff@0.12.0 check src/autosound_tcc/state/measurement_view.py tests/test_measurement_view.py` → `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/state/measurement_view.py tests/test_measurement_view.py CHANGELOG.md
git commit -m "Checklist: blue for a capture REW holds and nobody took in; old rounds found by the series of their titles (F-056, hub #153 C)"
```

---

### Task 2: The panel draws `found` and counts it as outstanding

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/measurement_panel.py` (`_LEGEND`, `outstanding_titles`)
- Modify: `src/autosound_tcc/ui/tcc/theme.py` (the `tl-*` rules)
- Modify: `src/autosound_tcc/ui/tcc/i18n.py` (`legFound`)
- Test: `tests/test_measurement_panel.py`

**Interfaces:**
- Consumes: `STATUS_FOUND = "found"` (Task 1).
- Produces: `_LEGEND` entry `("found", "legFound")`; `outstanding_titles()` returns `wait` and `found` rows.

- [ ] **Step 1: Write the failing test**

In `test_the_dialog_is_told_what_the_round_is_waiting_for`, the count line becomes:

```python
    assert len(seen["expected"]) == sum(
        1 for row in panel._rows if row.status in ("wait", "found") and not row.additional)
```

Append:

```python
def test_a_capture_in_rew_that_nobody_took_in_is_still_outstanding():
    """Blue is not done (F-056): the import window has to offer its name like any yellow one."""
    from autosound_tcc.state.models import MeasGroup, MeasItem
    from autosound_tcc.ui.tcc.mock_data import MeasSession

    _app()
    panel = MeasurementPanel()
    panel.set_sessions([MeasSession(
        id="cap_001", version={"en": "Series 1", "uk": "Серія 1"},
        groups=(MeasGroup(type="sw", method="sw", items=(
            MeasItem(name="w-L_1 (sw)", status="found"),
            MeasItem(name="w-R_1 (sw)", status="wait"),
            MeasItem(name="sw_1 (sw)", status="done"),
        )),),
    )], version=1)

    assert panel.outstanding_titles() == ["w-L_1 (sw)", "w-R_1 (sw)"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_measurement_panel.py -q -n 0 -k "outstanding or waiting_for"`
Expected: FAIL — `['w-R_1 (sw)'] == ['w-L_1 (sw)', 'w-R_1 (sw)']`.

- [ ] **Step 3: Implement**

`measurement_panel.py`, `_LEGEND` becomes:

```python
_LEGEND = (
    ("wait", "legWait"),
    # In REW under its name, not taken in yet (F-056, the Arbiter 2026-09-16).
    ("found", "legFound"),
    ("done", "legDone"),
    ("bad", "legBad"),
    # Recorded as decided against, with a reason (SCR-034) -- not the same as outstanding, which is
    # what it looked like before the skill kept a record of the round.
    ("skip", "legSkip"),
)
```

`outstanding_titles` return line becomes:

```python
        return [with_method(row.item_name, row.method_suffix) for row in self._rows
                if row.status in ("wait", "found") and not row.additional]
```

`theme.py`, after `QLabel[class~="tl-wait"] {{ background: {t.yellow}; }}` add:

```python
    QLabel[class~="tl-found"] {{ background: {t.info}; }}
```

i18n, `ANCHOR = '"legWait"'`:

```python
KEYS = [
    '        "legFound": "in REW — import it",\n',
    '        "legFound": "є в REW — завантаж",\n',
    "        \"legFound\": 'jest w REW — zaimportuj',\n",
    "        \"legFound\": 'in REW — importieren',\n",
]
```

- [ ] **Step 4: Run the tests and ruff**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_measurement_panel.py -q -n 0` → PASS
Run: `uvx ruff@0.12.0 check src/autosound_tcc/ui/tcc tests/test_measurement_panel.py` → `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/ui/tcc/measurement_panel.py src/autosound_tcc/ui/tcc/theme.py src/autosound_tcc/ui/tcc/i18n.py tests/test_measurement_panel.py
git commit -m "Capture panel: a blue dot and a legend entry for 'in REW, import it'; it counts as outstanding (F-056)"
```

---

### Task 3: The series `_N` from the open round, the plan, then the rounds — never the ledger

**Files:**
- Modify: `src/autosound_tcc/state/measurement_view.py` (add `series_of`, `highest_series`)
- Modify: `src/autosound_tcc/ui/tcc/main_window.py` (`_capture_version`, `_CAPTURE_SERIES`, `_refresh_capture_task`)
- Modify: `src/autosound_tcc/ui/tcc/measurement_panel.py` (add `set_series_unknown`; the import dialog's `has_task` and `name_sets`)
- Modify: `src/autosound_tcc/ui/tcc/i18n.py` (`measSeriesUnknown`)
- Test: `tests/test_measurement_view.py`, `tests/test_main_window.py`, `tests/test_measurement_panel.py`

**Interfaces:**
- Produces: `measurement_view.series_of(titles, project_dir=None) -> Optional[int]`; `measurement_view.highest_series(project_dir=None) -> Optional[int]`; `MainWindow._capture_version(state) -> Optional[int]`; `MeasurementPanel.set_series_unknown() -> None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_measurement_view.py`, append:

```python
def test_the_series_is_read_by_the_grammar(project):
    """hub #153 A: one reader of a title. Padding is the grammar's business too."""
    assert mv.series_of(["Baseline solo", " w-L_07 (sw) "], project) == 7
    assert mv.series_of(["not a title"], project) is None


def test_the_highest_series_among_the_rounds(project):
    process = _round(project, version=1, expected=["w-L_1 (sw)"], taken=["w-L_1 (sw)"])
    process.close_capture("done")
    process.start_capture(3, expected=[_as_typed("w-L_3 (sw)")])

    assert mv.highest_series(project) == 3
```

`tests/test_main_window.py`, replace `test_a_plan_that_names_no_series_falls_back_to_the_ledger` with:

```python
def test_the_ledger_version_never_becomes_the_series(monkeypatch):
    """hub #153 A. The ledger's `v_NNN` also moves for changes that are not DSP changes, and a
    project can start with the two apart (`v_001` measured as `_49`). With no round and no plan
    step naming a series, the answer is "not known", not the ledger."""
    from autosound_tcc.state import process_view

    _app()
    window = MainWindow()

    class View:
        version = "v_003"

    window._view = View()
    monkeypatch.setattr(process_view, "capture_round", lambda *a, **k: None)
    monkeypatch.setattr(process_view, "capture_rounds", lambda *a, **k: [])

    assert window._capture_version({"active_phase": "0", "plan": []}) is None


def test_the_open_round_names_the_series_before_the_plan(monkeypatch):
    """A pass taken again after a DSP change is the round's series, whatever the plan said first."""
    from autosound_tcc.state import process_view

    _app()
    window = MainWindow()
    window._view = None
    monkeypatch.setattr(process_view, "capture_round",
                        lambda *a, **k: {"id": "cap_002", "expected": ["w-L_07 (sw)"]})
    state = {"active_phase": "0",
             "plan": [{"id": "m0", "phase": "0", "name": "Baseline solo: tw-L_1 (sw)"}]}

    assert window._capture_version(state) == 7


def test_with_no_round_open_the_highest_series_among_the_rounds(monkeypatch):
    from autosound_tcc.state import process_view

    _app()
    window = MainWindow()
    window._view = None
    monkeypatch.setattr(process_view, "capture_round", lambda *a, **k: {"closed": True})
    monkeypatch.setattr(process_view, "capture_rounds", lambda *a, **k: [
        {"id": "cap_001", "expected": ["w-L_48 (sw)"], "taken": {}},
        {"id": "cap_002", "expected": ["w-L_49 (sw)"], "taken": {"w-L_49 (sw)": {}}},
    ])

    assert window._capture_version({"active_phase": "0", "plan": []}) == 49
```

In `test_the_capture_series_comes_from_the_plan_not_the_ledger`, before the assertion add:

```python
    from autosound_tcc.state import process_view

    monkeypatch.setattr(process_view, "capture_round", lambda *a, **k: None)
```

and add `monkeypatch` to its parameters.

`tests/test_measurement_panel.py`, append:

```python
def test_an_unknown_series_says_so_and_leaves_the_read_button():
    """hub #153 A: nothing names the series, so there is no checklist to derive — but taking
    measurements in is how a first round gets its number, so ⤓ stays."""
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS, version=6)

    panel.set_series_unknown()

    assert panel._no_project_label.text() == i18n.t("measSeriesUnknown")
    assert panel._read_btn.isVisibleTo(panel)
    assert panel._capture_version is None
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_measurement_view.py tests/test_main_window.py tests/test_measurement_panel.py -q -n 0 -k "series or ledger_version or read_button"`
Expected: FAIL — `series_of` / `highest_series` / `set_series_unknown` missing; `3 is None`.

- [ ] **Step 3: Implement**

`measurement_view.py`, after `has_glossary`:

```python
def _series_reader(project_dir: Optional[Path] = None):
    """`title -> _N or None`, through the method's grammar with this project's glossary.

    Built once per question: reading the glossary per title is a file read per title, and a
    project has rounds of sixteen. No method on the machine answers None for every title.
    """
    project = Path(project_dir or config.project_dir())
    try:
        naming = vendor_loader.load_naming()
        glossary = naming.Glossary.for_project(str(project)) if has_glossary(project) else None
    except Exception:  # noqa: BLE001 — no method, no glossary: nothing here can read a title
        return lambda _title: None

    def read(title) -> Optional[int]:
        entry = naming.parse_name(str(title).strip(), glossary)
        value = entry.get("version_n") if entry else None
        return value if isinstance(value, int) else None

    return read


def series_of(titles, project_dir: Optional[Path] = None) -> Optional[int]:
    """The `_N` of the first of `titles` the method's grammar reads with one, or None (hub #153 A).

    Through `naming.parse_name` and nothing of our own: a second reader of the grammar is the defect
    the method's #34 was.
    """
    read = _series_reader(project_dir)
    for title in titles:
        found = read(title)
        if found is not None:
            return found
    return None


def highest_series(project_dir: Optional[Path] = None) -> Optional[int]:
    """The highest `_N` among every round's titles, or None when no round names one."""
    read = _series_reader(project_dir)
    found = [
        read(title)
        for round_ in process_view.capture_rounds(project_dir)
        for title in list(round_.get("expected") or []) + list(round_.get("taken") or {})
    ]
    found = [n for n in found if n is not None]
    return max(found) if found else None
```

`main_window.py`: delete the line `_CAPTURE_SERIES = re.compile(r"_(\d+)\s*\((?:sw|rta)\)", re.IGNORECASE)` and replace the whole `_capture_version` method with:

```python
    def _capture_version(self, state: Optional[dict] = None) -> Optional[int]:
        """The series `_N` the current captures are named with, or None when nothing says (hub #153 A).

        `_N` is the DSP state the measurements were taken on. The ledger's `v_NNN` is a different
        counter — it also moves for changes that are not DSP changes, and a project can start with
        the two apart (`v_001` measured as `_49`) — so the ledger is not read here. In order:

        1. the open round: its titles are the pass being taken now;
        2. the active phase's plan steps ("Baseline solo: tw-L_1 (sw) + tw-L_1 (rta)"), each piece
           read by the method's grammar;
        3. the highest `_N` among all rounds (the Arbiter, 2026-09-16);
        4. None: the checklist says the series is not known yet, and an import with no round open
           asks for it.
        """
        round_ = process_view.capture_round() or {}
        if round_ and not round_.get("closed"):
            found = measurement_view.series_of(
                list(round_.get("expected") or []) + list(round_.get("taken") or {}))
            if found is not None:
                return found
        for step in (state or {}).get("plan") or []:
            if not isinstance(step, dict) or str(step.get("phase")) != str(
                (state or {}).get("active_phase")
            ):
                continue
            found = measurement_view.series_of(re.split(r"[+,;:]", str(step.get("name") or "")))
            if found is not None:
                return found
        return measurement_view.highest_series()
```

In `_refresh_capture_task`, replace:

```python
        version = self._capture_version(state)
        sessions = measurement_view.build_sessions(phase, version, titles, taken=taken)
```

with:

```python
        version = self._capture_version(state)
        if version is None:
            # Nothing names the series and the ledger version is not it (hub #153 A). Said, with ⤓
            # left working: an import with no round open asks for the number.
            self._meas_panel.set_series_unknown()
            return
        sessions = measurement_view.build_sessions(phase, version, titles, taken=taken)
```

`measurement_panel.py`, after `set_no_project`:

```python
    def set_series_unknown(self) -> None:
        """No series to derive a checklist at (hub #153 A) — said, with ⤓ still there to press.

        Unlike `set_no_project`, the read button stays: taking measurements in is how a first round
        gets its number, and the import asks for it.
        """
        self.set_no_project(i18n.t("measSeriesUnknown"))
        self._capture_version = None
        self._read_btn.setVisible(True)
```

In `_on_import_offer`, the dialog arguments become:

```python
            has_task=bool(self._has_real_sessions and self._sessions and self._sessions[0].groups),
            name_sets=self._method_channel_pairs() if self._has_real_sessions else {},
```

i18n, `ANCHOR = '"measNoTask"'`:

```python
KEYS = [
    '        "measSeriesUnknown": "The series is not known yet: no open round, plan step or earlier round names it. Take measurements in with ⤓ — the first round asks for its number.",\n',
    '        "measSeriesUnknown": "Серія ще не відома: її не називає ні відкритий раунд, ні крок плану, ні попередній раунд. Візьми заміри через ⤓ — перший раунд спитає номер.",\n',
    "        \"measSeriesUnknown\": 'Seria nie jest jeszcze znana: nie podaje jej ani otwarta runda, ani krok planu, ani wcześniejsza runda. Pobierz pomiary przez ⤓ — pierwsza runda zapyta o numer.',\n",
    "        \"measSeriesUnknown\": 'Die Serie ist noch nicht bekannt: weder eine offene Runde noch ein Planschritt noch eine frühere Runde nennt sie. Messungen mit ⤓ übernehmen — die erste Runde fragt nach der Nummer.',\n",
]
```

In `CHANGELOG.md`, under `### Changed`, append:

```markdown
- **The series `_N` is no longer taken from the ledger version.** It comes from the open round, then
  the plan, then the highest series among the rounds; with none of them the capture card says the
  series is not known yet (hub #153).
```

- [ ] **Step 4: Run the tests and ruff**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_measurement_view.py tests/test_main_window.py tests/test_measurement_panel.py -q -n 0` → PASS
Run: `uvx ruff@0.12.0 check src tests/test_measurement_view.py tests/test_main_window.py tests/test_measurement_panel.py` → `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/state/measurement_view.py src/autosound_tcc/ui/tcc/main_window.py src/autosound_tcc/ui/tcc/measurement_panel.py src/autosound_tcc/ui/tcc/i18n.py tests/test_measurement_view.py tests/test_main_window.py tests/test_measurement_panel.py CHANGELOG.md
git commit -m "Series _N from the open round, the plan, then the rounds, read by the method's grammar; never the ledger (hub #153 A)"
```

---

### Task 4: A first round with no series asks for the number

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/measurement_panel.py` (Qt import; `_write_ledger`; add `_ask_series`)
- Modify: `src/autosound_tcc/ui/tcc/i18n.py` (`askSeriesTitle`, `askSeriesLabel`)
- Test: `tests/test_measurement_panel.py`

**Interfaces:**
- Consumes: `set_series_unknown()` (Task 3).
- Produces: `MeasurementPanel._ask_series() -> Optional[int]`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_measurement_panel.py`:

```python
def _first_pass(panel, tmp_path) -> None:
    panel._taking = capture_import.candidates(
        {"1": {"title": "w-L_49 (sw)", "uuid": "u1", "date": "2026-Aug-25 20:11:31"}}, tmp_path)
    panel._expected = []
    panel._protective = {}


def test_a_first_round_with_no_series_asks_for_the_number(tmp_path, monkeypatch):
    """hub #153 A: nothing names the series, so the number is asked rather than invented."""
    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc import measurement_panel as mp

    _app()
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    captured = _fake_ledger(monkeypatch)
    panel = MeasurementPanel()
    panel.set_series_unknown()
    _first_pass(panel, tmp_path)
    monkeypatch.setattr(mp.QInputDialog, "getInt", lambda *a, **k: (49, True))

    panel._finish_import({})

    assert captured["version"] == 49


def test_cancelling_the_series_question_opens_no_round(tmp_path, monkeypatch):
    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc import measurement_panel as mp

    _app()
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    captured = _fake_ledger(monkeypatch)
    panel = MeasurementPanel()
    panel.set_series_unknown()
    _first_pass(panel, tmp_path)
    monkeypatch.setattr(mp.QInputDialog, "getInt", lambda *a, **k: (1, False))

    panel._finish_import({})

    assert captured == {}, "the ledger is left alone"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_measurement_panel.py -q -n 0 -k "series_question or asks_for_the_number"`
Expected: FAIL — `module ... has no attribute 'QInputDialog'`.

- [ ] **Step 3: Implement**

Add `QInputDialog,` to the `PySide6.QtWidgets` import list of `measurement_panel.py` (after `QHBoxLayout,`).

In `_write_ledger`, replace:

```python
        if not self._round_id and self._capture_version is None:
            # Nothing to open a round AT. Rather than invent a version, leave the ledger alone and
            # keep the measurements where they already are.
            return
```

with:

```python
        if not self._round_id and self._capture_version is None:
            # No round and no series (hub #153 A). The number is asked rather than invented — the
            # ledger version is a different counter — and Cancel leaves the ledger alone, as it
            # always did when there was nothing to open a round AT.
            asked = self._ask_series()
            if asked is None:
                return
            self._capture_version = asked
```

Add after `_write_ledger`:

```python
    def _ask_series(self) -> Optional[int]:
        """The series number for a first round, asked because nothing else says it (hub #153 A)."""
        value, ok = QInputDialog.getInt(
            self, i18n.t("askSeriesTitle"), i18n.t("askSeriesLabel"), 1, 1, 9999, 1)
        return int(value) if ok else None
```

i18n, `ANCHOR = '"measNoTask"'`:

```python
KEYS = [
    '        "askSeriesTitle": "Series number",\n        "askSeriesLabel": "The DSP state these were measured on (_N in the names):",\n',
    '        "askSeriesTitle": "Номер серії",\n        "askSeriesLabel": "Стан DSP, на якому це знято (_N у назвах):",\n',
    "        \"askSeriesTitle\": 'Numer serii',\n        \"askSeriesLabel\": 'Stan DSP, na którym to zmierzono (_N w nazwach):',\n",
    "        \"askSeriesTitle\": 'Seriennummer',\n        \"askSeriesLabel\": 'Der DSP-Zustand, auf dem gemessen wurde (_N in den Namen):',\n",
]
```

- [ ] **Step 4: Run the tests and ruff**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_measurement_panel.py -q -n 0` → PASS
Run: `uvx ruff@0.12.0 check src/autosound_tcc/ui/tcc tests/test_measurement_panel.py` → `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/ui/tcc/measurement_panel.py src/autosound_tcc/ui/tcc/i18n.py tests/test_measurement_panel.py
git commit -m "Capture import: a first round with no series asks for its number; Cancel opens nothing (hub #153 A)"
```

---

### Task 5: A title's channel is the grammar's current code

**Files:**
- Modify: `src/autosound_tcc/core/capture_import.py` (`channel_from_title`)
- Test: `tests/test_capture_import.py`

**Interfaces:**
- Produces: `channel_from_title(title, project_dir)` returns `code_current`, else `code`, else the string split.

- [ ] **Step 1: Write the failing test** — append to `tests/test_capture_import.py` (`json` is already imported there):

```python
@needs_the_method
def test_a_renamed_channel_s_old_titles_answer_to_its_current_code(tmp_path):
    """hub #153 B. `channel_from_title` asked the grammar for a key it never returned (`channel`),
    so every title fell through to the string split: `m-L_2 (sw)`, taken before `m-L` was renamed
    `w-L` (SCR-039), read as `m-L` and missed the channel's protective record."""
    (tmp_path / "glossary.json").write_text(json.dumps({
        "schema_version": 1,
        "channels": [{"code": "w-L", "active": True, "previous_names": ["m-L"]}],
        "pairs": {}, "combos": {}, "joints": {}, "sides": {},
    }), encoding="utf-8")

    assert ci.channel_from_title("m-L_2 (sw)", tmp_path) == "w-L"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_capture_import.py -q -n 0 -k renamed_channel`
Expected: FAIL — `'m-L' == 'w-L'`.

- [ ] **Step 3: Implement** — in `channel_from_title`, replace:

```python
        parsed = naming.parse_name(title, glossary)
        if parsed and parsed.get("channel"):
            return str(parsed["channel"])
```

with:

```python
        parsed = naming.parse_name(title, glossary)
        # `code_current`, then `code` (hub #153 B): the record has never had a `channel` key, so
        # this used to fall through to the split below for every title, and a renamed channel's
        # old titles (SCR-039) missed its protective record.
        code = (parsed or {}).get("code_current") or (parsed or {}).get("code")
        if code:
            return str(code)
```

In `CHANGELOG.md`, under `### Fixed`, append:

```markdown
- **A renamed channel's earlier captures find its protective record**: a title's channel is the
  grammar's current code (hub #153).
```

- [ ] **Step 4: Run the tests and ruff**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_capture_import.py tests/test_measurement_view.py tests/test_protective.py -q -n 0` → PASS
Run: `uvx ruff@0.12.0 check src/autosound_tcc/core/capture_import.py tests/test_capture_import.py` → `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/core/capture_import.py tests/test_capture_import.py CHANGELOG.md
git commit -m "Capture import: a title's channel is the grammar's code_current (hub #153 B)"
```

---

### Task 6: One set of leg fields for both forms; the Protection button offers outputs only

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/protective_dialog.py` (move leg widgets to module functions; add `ProtectiveLegsDialog`; output filter in `channel_codes` and `project_channel_codes`)
- Modify: `src/autosound_tcc/ui/tcc/i18n.py` (`protFormTitle`, `protFormClear`, `protFormOk`)
- Test: `tests/test_protective.py`

**Interfaces:**
- Produces: `leg_widgets(grid, row, col, label_key) -> (QLineEdit, QComboBox, QComboBox, QPushButton)`; `quick_fill(kind, slope)`; `fill_leg(freq, typ, slope, leg: dict)`; `read_leg(freq, typ, slope) -> Optional[dict]`; `OUTPUT_TIER = "physical_outputs"`; `class ProtectiveLegsDialog(QDialog)` with `__init__(legs=None, parent=None)`, attributes `hp` and `lp` (the four widgets each), `_clear()`, `legs() -> Optional[dict]`.

- [ ] **Step 1: Write the failing tests** — in `tests/test_protective.py`:

In `test_the_view_leads_and_the_project_fills_in_what_it_left_out`, the fake group gets an id:

```python
    class _Group:
        id = "physical_outputs"

        def __init__(self, names):
            self._names = names
```

Append:

```python
def test_with_no_round_open_only_output_channels_are_offered(tmp_path):
    """TEST-FINDINGS 22: the dialog listed VFL…VSW before the outputs. A protective filter sits in
    an OUTPUT's signal path, the driver being measured; a virtual channel is not measured through
    one."""
    from autosound_tcc.ui.tcc.protective_dialog import channel_codes

    class _Row:
        def __init__(self, name):
            self.name = name

    class _Group:
        def __init__(self, group_id, names):
            self.id = group_id
            self._names = names

        def rows_visible(self):
            return [_Row(name) for name in self._names]

    class _View:
        groups = (_Group("virtual_channels", ["VFL", "VFR"]), _Group("physical_outputs", ["w-L", "w-R"]))

    project = _described(tmp_path, [{"code": "w-L"}, {"code": "VC", "tier": "virtual_channels"},
                                    {"code": "tw-L", "tier": "channels"}])

    assert channel_codes(_View(), project) == ["w-L", "w-R", "tw-L"]


def test_the_row_form_has_the_protection_form_s_own_fields():
    """F-056, the Arbiter 2026-09-16: the import row's filters "done the way the form that sets
    filters does it". One set of fields, two places."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.protective_dialog import TYPES, ProtectiveLegsDialog

    QApplication.instance() or QApplication([])
    form = ProtectiveLegsDialog({"hp": {"f": 80.0, "type": "BW", "slope": 12}})

    freq, kind, slope, _quick = form.hp
    assert (freq.text(), kind.currentData(), slope.currentData()) == ("80", "BW", 12)
    assert [kind.itemData(i) for i in range(1, kind.count())] == list(TYPES)
    assert form.legs() == {"hp": {"f": 80.0, "type": "BW", "slope": 12}}

    form._clear()
    assert form.legs() is None, "cleared is 'read the curve as measured'"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_protective.py -q -n 0`
Expected: FAIL — `['VFL', 'VFR', 'w-L', 'w-R', 'VC', 'tw-L'] == ['w-L', 'w-R', 'tw-L']` and `cannot import name 'ProtectiveLegsDialog'`.

- [ ] **Step 3: Implement** in `protective_dialog.py`.

After `QUICK_LABEL = f"{QUICK_TYPE}{QUICK_SLOPE}"` add:

```python
#: The one tier a protective filter can sit in (TEST-FINDINGS 22): the outputs, the drivers being
#: measured. `physical_outputs` is the group id every DSP profile has; in `project.json` the same
#: tier is `channels` (the method's `dsp_profile.ledger_tier_key`).
OUTPUT_TIER = "physical_outputs"


def leg_widgets(grid: QGridLayout, row: int, col: int, label_key: str):
    """Frequency, type, slope and the LR24 button for one leg, placed in `grid` from `col`.

    Shared by the Protection form's channel rows and the import row's form (F-056): one set of
    fields in both places.
    """
```

— followed by the body of `_ChannelRow._leg_widgets` moved verbatim (from `freq = QLineEdit()` to `return freq, kind, slope, quick`), with `self._quick_fill(kind, slope)` replaced by `quick_fill(kind, slope)`. Then:

```python
def quick_fill(kind: QComboBox, slope: QComboBox) -> None:
    """LR24 into this leg — the type and slope nearly every protective filter actually is."""
    kind.setCurrentIndex(max(0, kind.findData(QUICK_TYPE)))
    slope.setCurrentIndex(max(0, slope.findData(QUICK_SLOPE)))


def fill_leg(freq: QLineEdit, typ: QComboBox, slope: QComboBox, leg: dict) -> None:
    """Show one recorded leg in its fields, unchanged."""
    value = leg.get("f")
    freq.setText(f"{value:g}" if isinstance(value, (int, float)) else str(value or ""))
    typ.setCurrentIndex(max(0, typ.findData(leg.get("type"))))
    slope.setCurrentIndex(max(0, slope.findData(leg.get("slope"))))


def read_leg(freq: QLineEdit, typ: QComboBox, slope: QComboBox):
    """One leg as the ledger states it, or None when the fields are empty.

    Empty is passed through as absent rather than as a refusal: a channel with only a high-pass is
    ordinary. A HALF-filled leg is not repaired here — it goes to the writer as typed, and the
    writer's refusal is what the person reads.
    """
    text = freq.text().strip()
    if not text and not typ.currentData() and not slope.currentData():
        return None
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        value = text  # the gate says what is wrong with it, in its own words
    return {"f": value, "type": typ.currentData() or "", "slope": slope.currentData() or ""}
```

In `_ChannelRow`: `__init__` calls `leg_widgets(grid, row, 1, "protHp")` and `leg_widgets(grid, row, 5, "protLp")`; delete the methods `_leg_widgets`, `_quick_fill` and `_leg`; `_fill_from`'s loop body becomes `fill_leg(freq, typ, slope, leg)` after the `if not leg: continue`; `answer()` calls `read_leg(...)` instead of `self._leg(...)`.

After `class ProtectiveDialog` add:

```python
class ProtectiveLegsDialog(QDialog):
    """One import row's protective filters, with the Protection form's own fields (F-056).

    The import table took a bare frequency and implied LR24; the Arbiter asked for the form's
    fields, and for protective filters only (2026-09-16). It collects and does not validate, like
    the form: a half-filled leg reaches the method's writer as typed.
    """

    def __init__(self, legs=None, parent=None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(i18n.t("protFormTitle"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        head = QLabel(i18n.t("protFormTitle"))
        head.setWordWrap(True)
        head.setProperty("class", "kv-lbl")
        layout.addWidget(head)

        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        self.hp = leg_widgets(grid, 0, 0, "protHp")
        self.lp = leg_widgets(grid, 0, 4, "protLp")
        layout.addWidget(holder)

        live = legs if isinstance(legs, dict) else {}
        for kind, widgets in (("hp", self.hp), ("lp", self.lp)):
            if isinstance(live.get(kind), dict):
                fill_leg(*widgets[:3], live[kind])

        actions = QHBoxLayout()
        clear = QPushButton(i18n.t("protFormClear"))
        clear.setProperty("class", "reason-btn")
        clear.clicked.connect(self._clear)
        actions.addWidget(clear)
        actions.addStretch(1)
        cancel = QPushButton(i18n.t("npCancel"))
        cancel.setProperty("class", "reason-btn")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        ok = QPushButton(i18n.t("protFormOk"))
        ok.setProperty("class", "composer-send-ok")
        ok.clicked.connect(self.accept)
        actions.addWidget(ok)
        layout.addLayout(actions)

    def _clear(self) -> None:
        for freq, kind, slope, _quick in (self.hp, self.lp):
            freq.clear()
            kind.setCurrentIndex(0)
            slope.setCurrentIndex(0)

    def legs(self):
        """`{hp, lp}` with what was filled in, or None for "no protective filter"."""
        out = {}
        for kind, (freq, typ, slope, _quick) in (("hp", self.hp), ("lp", self.lp)):
            leg = read_leg(freq, typ, slope)
            if leg:
                out[kind] = leg
        return out or None
```

In `project_channel_codes`, replace:

```python
        if code and code not in codes and not entry.get("hidden"):
            codes.append(code)
```

with:

```python
        # Outputs only (TEST-FINDINGS 22): a channel on another tier is not measured through a
        # protective filter. No `tier` is an output, as every project written before SCR-042 is.
        if entry.get("tier") not in (None, "", "channels"):
            continue
        if code and code not in codes and not entry.get("hidden"):
            codes.append(code)
```

In `channel_codes`, replace:

```python
    for group in getattr(view, "groups", ()) or ():
        for row in group.rows_visible():
```

with:

```python
    for group in getattr(view, "groups", ()) or ():
        if getattr(group, "id", "") != OUTPUT_TIER:
            continue  # TEST-FINDINGS 22: virtual channels and inputs have no protective filter
        for row in group.rows_visible():
```

i18n, `ANCHOR = '"protSave"'`:

```python
KEYS = [
    '        "protFormTitle": "Protective filters — what was in the chain while this was measured",\n        "protFormClear": "Clear",\n        "protFormOk": "OK",\n',
    '        "protFormTitle": "Захисні фільтри — що було в тракті під час заміру",\n        "protFormClear": "Очистити",\n        "protFormOk": "Гаразд",\n',
    "        \"protFormTitle\": 'Filtry ochronne — co było w torze podczas pomiaru',\n        \"protFormClear\": 'Wyczyść',\n        \"protFormOk\": 'OK',\n",
    "        \"protFormTitle\": 'Schutzfilter — was während der Messung im Signalweg war',\n        \"protFormClear\": 'Leeren',\n        \"protFormOk\": 'OK',\n",
]
```

In `CHANGELOG.md`, under `### Fixed`, append:

```markdown
- **The Protection form offers output channels only** when no round is open — not the virtual
  channels, which are not measured through a protective filter (TEST-FINDINGS 22).
```

- [ ] **Step 4: Run the tests and ruff**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_protective.py -q -n 0` → PASS
Run: `uvx ruff@0.12.0 check src/autosound_tcc/ui/tcc/protective_dialog.py tests/test_protective.py` → `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/ui/tcc/protective_dialog.py src/autosound_tcc/ui/tcc/i18n.py tests/test_protective.py CHANGELOG.md
git commit -m "Protection: one set of leg fields for the form and the import row; outputs only with no round open (TEST-FINDINGS 22)"
```

---

### Task 7: The import row's protective cell opens the form

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/capture_import_dialog.py` (columns; `_render`; `_on_item_changed`; `protective()`; add `uuid_at`, `set_legs`, `_on_cell_clicked`, `legs_summary`)
- Modify: `src/autosound_tcc/core/capture_import.py` (delete `legs_from` and `QUICK_LEG`)
- Modify: `src/autosound_tcc/ui/tcc/i18n.py` (`capImportColProt`, `capImportHp`, `capImportLp`; new `capImportProtTip` text; delete `capImportColHp`, `capImportColLp`)
- Test: `tests/test_capture_import_dialog.py`

**Interfaces:**
- Consumes: `ProtectiveLegsDialog(legs, parent)` with `.exec()` and `.legs()` (Task 6).
- Produces: `CaptureImportDialog.uuid_at(row) -> str`; `CaptureImportDialog.set_legs(uuid, legs) -> None`; `CaptureImportDialog._on_cell_clicked(row, column)`; module `legs_summary(legs) -> str`; column constants `_COL_NAME = 4`, `_COL_PROT = 5`.

- [ ] **Step 1: Write the failing tests** — in `tests/test_capture_import_dialog.py`, replace everything from the line `# ---- what was in the signal path, typed on the row` to the end of the file with:

```python
# ---- what was in the signal path, entered for the row -----------------------------------------

_LR24_80 = {"hp": {"f": 80.0, "type": "LR", "slope": 24}}


def test_the_row_s_filters_are_the_whole_statement(tmp_path):
    """What the row says was in its chain is recorded for its channel — entered with the Protection
    form's own fields now (F-056, the Arbiter 2026-09-16), not a bare frequency with LR24 implied."""
    dialog = _dialog(_rew(2), tmp_path, waiting=2)
    dialog._table.item(0, 4).setText("w-L_02 (sw)")

    dialog.set_legs(dialog.uuid_at(0), {"hp": {"f": 80.0, "type": "BW", "slope": 12}})

    assert dialog.protective() == {"w-L": {"hp": {"f": 80.0, "type": "BW", "slope": 12}}}


def test_the_cell_says_what_is_in_the_chain(tmp_path):
    dialog = _dialog(_rew(1), tmp_path, waiting=1)
    assert dialog._table.item(0, 5).text() == "—"

    dialog.set_legs(dialog.uuid_at(0), {"hp": {"f": 80.0, "type": "LR", "slope": 24},
                                        "lp": {"f": 3500.0, "type": "LR", "slope": 24}})

    hp, lp = i18n.t("capImportHp"), i18n.t("capImportLp")
    assert dialog._table.item(0, 5).text() == f"{hp} LR24 80 · {lp} LR24 3500"


def test_clicking_the_cell_opens_the_form_and_keeps_its_answer(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc import capture_import_dialog as cid

    class _Form:
        def __init__(self, legs=None, parent=None):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def legs(self):
            return _LR24_80

    monkeypatch.setattr(cid, "ProtectiveLegsDialog", _Form)
    dialog = _dialog(_rew(1), tmp_path, waiting=1)
    dialog._table.item(0, 4).setText("w-L_02 (sw)")

    dialog._on_cell_clicked(0, 5)

    assert dialog.protective() == {"w-L": _LR24_80}


def test_an_empty_row_says_nothing_at_all(tmp_path):
    """Empty means "read this curve as measured" — not a claim that the chain was empty. There is
    nearly always something in it, the DSP's own working crossovers, and they belong there."""
    dialog = _dialog(_rew(3), tmp_path, waiting=3)

    assert dialog.protective() == {}


def test_the_channel_comes_from_the_name_the_row_is_being_given(tmp_path):
    """"Імʼя або є, або буде в цій таблиці" — so the row knows its channel by the time it matters."""
    answer = _rew(1)
    answer["1"]["title"] = "tw-R_02 (sw)"  # already named in REW
    dialog = _dialog(answer, tmp_path, waiting=1)

    dialog.set_legs(dialog.uuid_at(0), {"hp": {"f": 2500.0, "type": "LR", "slope": 24}})

    assert list(dialog.protective()) == ["tw-R"]


def test_entering_a_filter_takes_the_row_with_it(tmp_path):
    dialog = _dialog(_rew(12), tmp_path, waiting=1)
    uuid = dialog.uuid_at(0)
    assert uuid not in dialog._ticked

    dialog.set_legs(uuid, _LR24_80)

    assert uuid in dialog._ticked


def test_one_channel_described_two_ways_is_a_question_not_a_merge(tmp_path):
    """The same channel captured with two methods is two rows and one signal path. Two rows that
    disagree are not silently merged — that is a question for the person."""
    dialog = _dialog(_rew(2), tmp_path, waiting=2)
    dialog._table.item(0, 4).setText("w-L_02 (sw)")
    dialog._table.item(1, 4).setText("w-L_02 (rta)")
    dialog.set_legs(dialog.uuid_at(0), _LR24_80)
    dialog.set_legs(dialog.uuid_at(1), {"hp": {"f": 100.0, "type": "LR", "slope": 24}})

    dialog._on_apply()

    assert dialog.result() != int(dialog.DialogCode.Accepted), "nothing left the dialog"
    assert "w-L" in dialog._note.text()


def test_the_same_chain_on_two_rows_of_one_channel_is_fine(tmp_path):
    dialog = _dialog(_rew(2), tmp_path, waiting=2)
    dialog._table.item(0, 4).setText("w-L_02 (sw)")
    dialog._table.item(1, 4).setText("w-L_02 (rta)")
    dialog.set_legs(dialog.uuid_at(0), _LR24_80)
    dialog.set_legs(dialog.uuid_at(1), _LR24_80)

    assert list(dialog.protective()) == ["w-L"]
    assert dialog.protective_conflicts == []
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_capture_import_dialog.py -q -n 0`
Expected: FAIL — `'CaptureImportDialog' object has no attribute 'uuid_at'` / `'set_legs'`.

- [ ] **Step 3: Implement** in `capture_import_dialog.py`:

Import: `from autosound_tcc.ui.tcc.protective_dialog import ProtectiveLegsDialog`.

Columns:

```python
_COL_TAKE, _COL_NUM, _COL_TITLE, _COL_WHEN, _COL_NAME, _COL_PROT = range(6)
```

Table: `QTableWidget(0, 6)`; the header labels end with `i18n.t("capImportColName"), i18n.t("capImportColProt")])`; replace the two resize lines for `_COL_HP` and `_COL_LP` with `header.setSectionResizeMode(_COL_PROT, QHeaderView.ResizeMode.ResizeToContents)`; after `self._table.itemChanged.connect(self._on_item_changed)` add:

```python
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.cellActivated.connect(self._on_cell_clicked)
```

The `_legs` comment becomes:

```python
        #: `{uuid: {"hp": {f, type, slope}, "lp": {…}}}` — what was in each row's chain, as the
        #: Protection form's fields gave it. No entry means "read this curve as measured", which is
        #: not a claim that the chain was empty; see `core/protective.py`.
```

In `_render`, replace the whole `for column, key in ((_COL_HP, "hp"), (_COL_LP, "lp")):` block (and its comment) with:

```python
            # What was in the chain, as one line; a click opens the Protection form's own fields
            # for this row (F-056, the Arbiter 2026-09-16 — it used to be two typed frequencies).
            prot = QTableWidgetItem(legs_summary(self._legs.get(row.uuid)))
            prot.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            prot.setToolTip(i18n.t("capImportProtTip") if row.identified
                            else i18n.t("capImportNoUuid"))
            self._table.setItem(index, _COL_PROT, prot)
```

In `_on_item_changed`, delete the `elif item.column() in (_COL_HP, _COL_LP):` branch.

In `protective()`, replace:

```python
            legs = capture_import.legs_from(*(self._legs.get(row.uuid, {}).get(k, "")
                                              for k in ("hp", "lp")))
            if legs is None:
                continue
```

with:

```python
            legs = self._legs.get(row.uuid)
            if not legs:
                continue
```

Add methods after `ticked_rows`:

```python
    def uuid_at(self, row: int) -> str:
        """The uuid of the measurement on table row `row`, or ""."""
        take = self._table.item(row, _COL_TAKE)
        return str(take.data(_UUID) or "") if take is not None else ""

    def set_legs(self, uuid: str, legs) -> None:
        """What was in this row's chain: a `{hp, lp}` dict, or None for "read it as measured"."""
        if legs:
            self._legs[uuid] = dict(legs)
            self._ticked.add(uuid)  # a record nobody takes in is none
        else:
            self._legs.pop(uuid, None)
        self._render()

    def _on_cell_clicked(self, row: int, column: int) -> None:
        """The protective cell opens the Protection form's own fields for this one row (F-056)."""
        if column != _COL_PROT:
            return
        uuid = self.uuid_at(row)
        if not any(candidate.uuid == uuid and candidate.identified for candidate in self._all):
            return
        form = ProtectiveLegsDialog(self._legs.get(uuid), parent=self)
        if form.exec() == QDialog.DialogCode.Accepted:
            self.set_legs(uuid, form.legs())
```

Add a module function after the column constants:

```python
def legs_summary(legs) -> str:
    """`HP LR24 80 · LP —` for a row, `—` when nothing was in its chain."""
    if not legs:
        return "—"
    parts = []
    for kind, key in (("hp", "capImportHp"), ("lp", "capImportLp")):
        leg = legs.get(kind)
        if not leg:
            parts.append(f"{i18n.t(key)} —")
            continue
        value = leg.get("f")
        freq = f"{value:g}" if isinstance(value, (int, float)) else str(value or "?")
        parts.append(f"{i18n.t(key)} {leg.get('type') or ''}{leg.get('slope') or ''} {freq}")
    return " · ".join(parts)
```

`core/capture_import.py`: delete `QUICK_LEG = {"type": "LR", "slope": 24}` and the whole `legs_from` function (`grep -rn "legs_from\|QUICK_LEG" src tests` must print nothing afterwards).

i18n: in each language block delete the lines with `"capImportColHp"` and `"capImportColLp"`; replace the `"capImportProtTip"` line with these texts (en, uk, pl, de):

```python
        "capImportProtTip": "What was in the signal path while this was measured — protective filters only. Click to enter them with the Protection form's fields. Empty means the curve is read as measured.",
        "capImportProtTip": "Що було в тракті, поки це знімалось, — лише захисні фільтри. Клік — ввести їх полями форми «Захист». Порожньо — криву читають як зняту.",
        "capImportProtTip": 'Co było w torze sygnału podczas tego pomiaru — tylko filtry ochronne. Kliknij, aby wpisać je polami formularza ochrony. Puste oznacza, że krzywą czyta się tak, jak zmierzono.',
        "capImportProtTip": 'Was während dieser Messung im Signalweg war — nur Schutzfilter. Klicken, um sie mit den Feldern des Schutzformulars einzugeben. Leer heißt: die Kurve wird so gelesen, wie gemessen.',
```

then insert with `ANCHOR = '"capImportProtTip"'`:

```python
KEYS = [
    '        "capImportColProt": "protective",\n        "capImportHp": "HP",\n        "capImportLp": "LP",\n',
    '        "capImportColProt": "захисні",\n        "capImportHp": "ФВЧ",\n        "capImportLp": "ФНЧ",\n',
    "        \"capImportColProt\": 'ochronne',\n        \"capImportHp\": 'HP',\n        \"capImportLp\": 'LP',\n",
    "        \"capImportColProt\": 'Schutz',\n        \"capImportHp\": 'HP',\n        \"capImportLp\": 'TP',\n",
]
```

In `CHANGELOG.md`, under `### Changed`, append:

```markdown
- **The import row's protective filters are entered with the Protection form's fields** — type,
  slope, frequency and the LR24 button, for the high-pass and the low-pass — from one cell that says
  what is in the chain (F-056). It used to be two typed frequencies with LR24 implied.
```

- [ ] **Step 4: Run the tests and ruff**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_capture_import_dialog.py tests/test_capture_import.py tests/test_measurement_panel.py tests/test_protective.py -q -n 0` → PASS
Run: `uvx ruff@0.12.0 check src tests/test_capture_import_dialog.py` → `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/ui/tcc/capture_import_dialog.py src/autosound_tcc/core/capture_import.py src/autosound_tcc/ui/tcc/i18n.py tests/test_capture_import_dialog.py CHANGELOG.md
git commit -m "Capture import: the row's protective cell opens the Protection form's fields (F-056)"
```

---

### Task 8: The new name is chosen from what the round still waits for

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/capture_import_dialog.py` (imports; add `_NameDelegate`, `name_choices`, `_refresh_name_lists`; `_render`; `_on_item_changed`; delegate installed in `__init__`)
- Modify: `src/autosound_tcc/ui/tcc/i18n.py` (`capImportNamePick`)
- Test: `tests/test_capture_import_dialog.py`

**Interfaces:**
- Consumes: `uuid_at(row)` (Task 7).
- Produces: `CaptureImportDialog.name_choices(uuid) -> list[str]`; a persistent editable `QComboBox` in every identified row's `_COL_NAME` cell, reachable as `dialog._table.indexWidget(dialog._table.model().index(row, 4))`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_capture_import_dialog.py`:

```python
# ---- the new name, chosen from what the round still waits for -----------------------------------

def _name_editor(dialog, row: int):
    return dialog._table.indexWidget(dialog._table.model().index(row, 4))


def test_the_new_name_offers_what_the_round_still_waits_for(tmp_path):
    """F-056, the Arbiter 2026-09-16: the import window lacked a field chosen from the list of what
    still has to be captured."""
    dialog = _dialog(_rew(2), tmp_path, expected=["w-L_02 (sw)", "w-R_02 (sw)"])

    assert dialog.name_choices(dialog.uuid_at(0)) == ["w-L_02 (sw)", "w-R_02 (sw)"]
    editor = _name_editor(dialog, 0)
    assert [editor.itemText(i) for i in range(editor.count())] == ["w-L_02 (sw)", "w-R_02 (sw)"]


def test_a_name_chosen_in_one_row_leaves_the_other_rows_lists(tmp_path):
    dialog = _dialog(_rew(2), tmp_path, expected=["w-L_02 (sw)", "w-R_02 (sw)"])
    first, second = dialog.uuid_at(0), dialog.uuid_at(1)

    dialog._table.item(0, 4).setText("w-L_02 (sw)")

    assert dialog.name_choices(second) == ["w-R_02 (sw)"]
    assert dialog.name_choices(first) == ["w-L_02 (sw)", "w-R_02 (sw)"], "a row keeps its own"


def test_choosing_from_the_list_takes_the_row_and_renames_it(tmp_path):
    dialog = _dialog(_rew(1), tmp_path, expected=["w-L_02 (sw)"])
    uuid = dialog.uuid_at(0)
    editor = _name_editor(dialog, 0)

    editor.setCurrentIndex(0)
    editor.activated.emit(0)

    assert uuid in dialog._ticked
    assert (uuid, "w-L_02 (sw)") in dialog.renames()


def test_a_name_nobody_planned_can_still_be_typed(tmp_path):
    """An extra measurement names itself — what it is and what it is for (hub #153)."""
    dialog = _dialog(_rew(1), tmp_path, expected=["w-L_02 (sw)"])
    uuid = dialog.uuid_at(0)

    dialog._table.item(0, 4).setText("r-L_17 (sw) noXO")

    assert (uuid, "r-L_17 (sw) noXO") in dialog.renames()
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_capture_import_dialog.py -q -n 0 -k "new_name or name_chosen or choosing_from or nobody_planned"`
Expected: FAIL — `'CaptureImportDialog' object has no attribute 'name_choices'`, `'NoneType' object has no attribute 'itemText'`.

- [ ] **Step 3: Implement** in `capture_import_dialog.py`:

Imports: `from PySide6.QtCore import Qt, QTimer`; add `QComboBox,` and `QStyledItemDelegate,` to the `PySide6.QtWidgets` list.

Before `class CaptureImportDialog`:

```python
class _NameDelegate(QStyledItemDelegate):
    """The new-name cell as a list of what the round still waits for, with room to type (F-056).

    A delegate over the cell's own item, not a widget beside it: the item stays the one place the
    name lives, so "Give names", a typed name and the clash check keep working on the item.
    """

    def __init__(self, dialog: "CaptureImportDialog") -> None:
        super().__init__(dialog)
        self._dialog = dialog

    def createEditor(self, parent, option, index):  # noqa: N802 — Qt's name
        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.lineEdit().setPlaceholderText(i18n.t("capImportNamePick"))
        # Every choice lands at once: a persistent editor otherwise commits only when focus leaves.
        combo.activated.connect(lambda _index, c=combo: self.commitData.emit(c))
        combo.lineEdit().editingFinished.connect(lambda c=combo: self.commitData.emit(c))
        return combo

    def setEditorData(self, editor, index):  # noqa: N802
        editor.blockSignals(True)
        editor.clear()
        editor.addItems(self._dialog.name_choices(self._dialog.uuid_at(index.row())))
        editor.setCurrentText(str(index.data() or ""))
        editor.blockSignals(False)

    def setModelData(self, editor, model, index):  # noqa: N802
        text = editor.currentText().strip()
        if text != str(index.data() or ""):
            model.setData(index, text)
```

In `__init__`, after the table's edit triggers are set:

```python
        self._table.setItemDelegateForColumn(_COL_NAME, _NameDelegate(self))
```

Methods after `set_legs`:

```python
    def name_choices(self, uuid: str) -> list[str]:
        """What the round still waits for, minus the names other rows have already chosen."""
        chosen_elsewhere = {name for other, name in self._names.items() if other != uuid}
        return [name for name in self._expected if name not in chosen_elsewhere]

    def _refresh_name_lists(self) -> None:
        """Re-offer every row's list once a name was chosen or cleared somewhere else."""
        delegate = self._table.itemDelegateForColumn(_COL_NAME)
        for row in range(self._table.rowCount()):
            index = self._table.model().index(row, _COL_NAME)
            editor = self._table.indexWidget(index)
            if editor is not None:
                delegate.setEditorData(editor, index)
```

In `_render`, after `self._table.setItem(index, _COL_NAME, name)` add:

```python
            if row.identified:
                self._table.openPersistentEditor(name)
```

In `_on_item_changed`, at the end of the `elif item.column() == _COL_NAME:` branch add:

```python
            # Deferred: this runs inside the editor's own commit, and repopulating that editor
            # while it is still emitting is not something to do under Qt.
            QTimer.singleShot(0, self._refresh_name_lists)
```

i18n, `ANCHOR = '"capImportColProt"'`:

```python
KEYS = [
    '        "capImportNamePick": "choose or type…",\n',
    '        "capImportNamePick": "вибери або впиши…",\n',
    "        \"capImportNamePick\": 'wybierz lub wpisz…',\n",
    "        \"capImportNamePick\": 'auswählen oder eingeben…',\n",
]
```

In `CHANGELOG.md`, under `### Added`, append:

```markdown
- **The import window's new name is a list** of the names the round still waits for, without the
  ones other rows already took; a name nobody planned can still be typed (F-056).
```

- [ ] **Step 4: Run the tests and ruff**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_capture_import_dialog.py tests/test_measurement_panel.py -q -n 0` → PASS
Run: `uvx ruff@0.12.0 check src/autosound_tcc/ui/tcc/capture_import_dialog.py tests/test_capture_import_dialog.py` → `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/ui/tcc/capture_import_dialog.py src/autosound_tcc/ui/tcc/i18n.py tests/test_capture_import_dialog.py CHANGELOG.md
git commit -m "Capture import: the new name is chosen from what the round still waits for, or typed (F-056)"
```

---

## Not in this plan

- hub #153 D, E, F and `(imp)` — after the skill's wave release and a pin bump from `v3.0.52`.
- tcc#21 — capture quality at selection.
- Closing hub #153 — after this plan lands, with the Arbiter's word on D–F.
