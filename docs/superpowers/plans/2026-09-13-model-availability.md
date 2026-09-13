# Model Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every model TCC offers is either ready (plain) or red with one word for why, the catalogues are re-read on every start, and the reviewer is probed at session start when one is chosen.

**Architecture:** One core unit, `core/availability.py`, answers "can this model run, and if not, why" by combining what already exists (`Choice.available`, `claude_sdk.signed_in()`, `model_choices.unconfirmed()`) with two new facts it owns: refusals recorded this launch and harnesses still being read. A UI helper turns its reason codes into words and phrases. Startup reading runs on a thread started from `app.py`; on Windows the start and the console's hide wait for it up to a cap.

**Tech Stack:** Python 3.12, PySide6 6.11, pytest (serial), ruff 0.12.0.

**Spec:** `docs/superpowers/specs/2026-09-13-model-availability-design.md`

## Global Constraints

- `core/` and `state/` must not import `ui/` (HUB-051): reason codes and agent phrases live in `core/availability.py`; UI words live in `ui/tcc/availability_view.py` via `i18n`.
- Every new i18n key exists in all four languages (`en`, `uk`, `pl`, `de`) — `tests/test_i18n_languages.py::test_every_language_has_every_key` enforces it.
- Reasons, in priority order: `not_installed` > `sign_in` > `location` > `refused` > `not_checked`.
- Red is the theme's `warn` colour (`current_theme().warn`). Two colours only: plain = ready, red = everything else.
- `STARTUP_MODELS_CAP_S = 8.0`. The console line stays ASCII, one line, ≤ 32 characters: `Autosound TCC: reading models...`.
- A refusal lives in memory for this launch only; the reload button (↻, `MainWindow._reload_from_disk`) forgets refusals.
- Reviewer probe only when a reviewer key is set; never on a fresh install.
- TDD: each test is run and seen failing before the code. Commit messages and docs in English. `make check` green before calling the work done. Do not edit the tree while a suite is running.

---

### Task 1: `core/availability.py` — reasons, refusals, reading, status

**Files:**
- Create: `src/autosound_tcc/core/availability.py`
- Test: `tests/test_availability.py`

**Interfaces:**
- Produces:
  - constants `NOT_INSTALLED="not_installed"`, `SIGN_IN="sign_in"`, `LOCATION="location"`, `REFUSED="refused"`, `NOT_CHECKED="not_checked"`, `PRIORITY` (tuple in that order), `PHRASES: dict[str, str]` (English, for the agent)
  - `@dataclass(frozen=True) class Status: ready: bool; reason: Optional[str] = None; detail: str = ""`
  - `begin_reading(harnesses: Iterable[str]) -> None`, `finish_reading(harness: str) -> None`
  - `refused(key: str, reason: str, detail: str = "") -> None`, `succeeded(key: str) -> None`, `forget_refusals() -> None`, `reset() -> None`
  - `status(choice, *, signed_in=None, unconfirmed=None) -> Status` (`signed_in`, `unconfirmed` are optional callables for tests)

- [ ] **Step 1: Write the failing tests**

```python
"""What can run on this machine right now, and in one word why not."""
from __future__ import annotations

import threading

import pytest

from autosound_tcc.core import availability
from autosound_tcc.core.model_choices import Choice


@pytest.fixture(autouse=True)
def _clean():
    availability.reset()
    yield
    availability.reset()


def _choice(harness="agy", model="gemini-3.1-pro-high", available=True):
    return Choice(harness=harness, model=model, label=model, available=available)


def _status(choice, signed_in=None, unconfirmed=False):
    return availability.status(choice, signed_in=lambda: signed_in,
                               unconfirmed=lambda _c: unconfirmed)


def test_a_model_with_nothing_against_it_is_ready():
    assert _status(_choice()) == availability.Status(True)


def test_a_route_without_its_cli_is_not_installed():
    assert _status(_choice(harness="codex", available=False)).reason == availability.NOT_INSTALLED


def test_the_claude_route_without_a_login_asks_to_sign_in():
    assert _status(_choice(harness="sdk", model="claude-opus-5"), signed_in=False).reason \
        == availability.SIGN_IN
    assert _status(_choice(harness="sdk", model="claude-opus-5"), signed_in=None).ready, \
        "None means the probe could not tell — that is not a reason to go red"


def test_a_refusal_is_red_with_its_reason_and_detail_until_it_succeeds():
    choice = _choice()
    availability.refused(choice.key, availability.LOCATION, "not supported in the selected location")

    state = _status(choice)
    assert (state.ready, state.reason) == (False, availability.LOCATION)
    assert "selected location" in state.detail

    availability.succeeded(choice.key)
    assert _status(choice).ready


def test_forgetting_refusals_is_what_the_reload_button_does():
    choice = _choice()
    availability.refused(choice.key, availability.REFUSED, "no")
    availability.forget_refusals()
    assert _status(choice).ready


def test_a_harness_still_being_read_is_not_checked():
    availability.begin_reading(["agy"])
    assert _status(_choice()).reason == availability.NOT_CHECKED
    availability.finish_reading("agy")
    assert _status(_choice()).ready


def test_an_entry_remembered_from_last_launch_is_not_checked():
    assert _status(_choice(), unconfirmed=True).reason == availability.NOT_CHECKED


def test_the_most_serious_reason_wins():
    choice = _choice(harness="codex", available=False)
    availability.refused(choice.key, availability.LOCATION, "x")
    availability.begin_reading(["codex"])
    assert _status(choice, unconfirmed=True).reason == availability.NOT_INSTALLED
    assert list(availability.PRIORITY) == [availability.NOT_INSTALLED, availability.SIGN_IN,
                                          availability.LOCATION, availability.REFUSED,
                                          availability.NOT_CHECKED]


def test_every_reason_has_a_phrase_for_the_agent():
    assert set(availability.PHRASES) == set(availability.PRIORITY)


def test_concurrent_writers_and_a_reader_do_not_trip_over_each_other():
    choice = _choice()

    def write():
        for i in range(500):
            availability.refused(f"agy:m{i}", availability.REFUSED, "x")
            availability.succeeded(f"agy:m{i}")

    threads = [threading.Thread(target=write) for _ in range(4)]
    for thread in threads:
        thread.start()
    for _ in range(500):
        _status(choice)
    for thread in threads:
        thread.join()
    assert _status(choice).ready
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_availability.py -q -p no:cacheprovider`
Expected: collection error — `ImportError: cannot import name 'availability'`

- [ ] **Step 3: Implement**

```python
"""What can run on this machine right now, and in one word why not.

One place answers it, so the pickers, the reviewer footer and `get_tcc_state` cannot disagree
(spec: docs/superpowers/specs/2026-09-13-model-availability-design.md). Most of the answer already
exists elsewhere — whether the CLI is installed (`Choice.available`), whether Claude is signed in
(`claude_sdk.signed_in`), whether an entry was only remembered (`model_choices.unconfirmed`). This
unit owns the two facts nothing else holds: what refused this launch, and what is still being read.

In memory, for this launch only: a refusal stays red until the next start, a successful call, or
the reload button. No `ui` import — words for people live in `ui/tcc/availability_view.py`.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

NOT_INSTALLED = "not_installed"
SIGN_IN = "sign_in"
LOCATION = "location"
REFUSED = "refused"
NOT_CHECKED = "not_checked"
PRIORITY = (NOT_INSTALLED, SIGN_IN, LOCATION, REFUSED, NOT_CHECKED)

#: For the agent, in `get_tcc_state` — English, like the rest of that payload.
PHRASES = {
    NOT_INSTALLED: "its CLI is not installed on this machine",
    SIGN_IN: "not signed in to Claude on this machine",
    LOCATION: "not available in your region",
    REFUSED: "the last call to it was refused",
    NOT_CHECKED: "not checked yet since TCC started",
}


@dataclass(frozen=True)
class Status:
    ready: bool
    reason: Optional[str] = None
    detail: str = ""


_lock = threading.Lock()
_refusals: dict[str, tuple[str, str]] = {}
_reading: set[str] = set()


def begin_reading(harnesses: Iterable[str]) -> None:
    with _lock:
        _reading.update(harnesses)


def finish_reading(harness: str) -> None:
    with _lock:
        _reading.discard(harness)


def refused(key: str, reason: str, detail: str = "") -> None:
    with _lock:
        _refusals[key] = (reason, detail)


def succeeded(key: str) -> None:
    with _lock:
        _refusals.pop(key, None)


def forget_refusals() -> None:
    with _lock:
        _refusals.clear()


def reset() -> None:
    """Everything back to a fresh launch. For tests."""
    with _lock:
        _refusals.clear()
        _reading.clear()


def status(choice, *, signed_in: Optional[Callable[[], Optional[bool]]] = None,
           unconfirmed: Optional[Callable[[object], bool]] = None) -> Status:
    """Ready, or the most serious reason it is not (see `PRIORITY`)."""
    if signed_in is None:
        from autosound_tcc.core import claude_sdk
        signed_in = claude_sdk.signed_in
    if unconfirmed is None:
        from autosound_tcc.core import model_choices
        unconfirmed = model_choices.unconfirmed
    found: list[tuple[str, str]] = []
    if not getattr(choice, "available", True):
        found.append((NOT_INSTALLED, ""))
    if choice.harness == "sdk" and signed_in() is False:
        found.append((SIGN_IN, ""))
    with _lock:
        refusal = _refusals.get(choice.key)
        being_read = choice.harness in _reading
    if refusal:
        found.append(refusal)
    if being_read or unconfirmed(choice):
        found.append((NOT_CHECKED, ""))
    if not found:
        return Status(True)
    reason, detail = min(found, key=lambda item: PRIORITY.index(item[0]))
    return Status(False, reason, detail)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_availability.py -q -p no:cacheprovider`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/core/availability.py tests/test_availability.py
git commit -m "Availability: one unit answers whether a model can run, and in one word why not"
```

---

### Task 2: Recognise a refusal, and record a reviewer call's outcome

**Files:**
- Modify: `src/autosound_tcc/core/critic.py` (add `refusal_reason` after `remedy`)
- Modify: `src/autosound_tcc/core/availability.py` (add `record_reviewer_outcome`)
- Test: `tests/test_critic.py`, `tests/test_availability.py`

**Interfaces:**
- Consumes: `availability.refused / succeeded / LOCATION / REFUSED` (Task 1); `critic.CriticResult`, `critic.MODE_CLIPBOARD`, `critic._LOCATION_WORDS`; `model_choices.critic_reaches(choice) -> bool`
- Produces: `critic.refusal_reason(detail: str) -> Optional[str]`; `availability.record_reviewer_outcome(key: str, result, *, reaches=None) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_critic.py`:

```python
def test_a_refusal_is_named_by_its_reason_or_not_at_all():
    from autosound_tcc.core import availability, critic

    assert critic.refusal_reason("error: Selected model is not supported in the selected location.") \
        == availability.LOCATION
    assert critic.refusal_reason("Gemini API: HTTP 400 Bad Request") == availability.REFUSED
    assert critic.refusal_reason("") is None
```

Append to `tests/test_availability.py`:

```python
def _result(mode, detail=""):
    from autosound_tcc.core import critic
    return critic.CriticResult(mode, "", None, "critic", detail, 0.0, "2026-09-13T00:00:00+00:00")


def test_a_reviewer_refused_by_location_goes_red_and_an_answer_clears_it():
    from autosound_tcc.core import critic

    key = "agy:gemini-3.1-pro-high"
    availability.record_reviewer_outcome(
        key, _result(critic.MODE_CLIPBOARD, "not supported in the selected location"),
        reaches=lambda _c: True)
    assert _status(_choice()).reason == availability.LOCATION

    availability.record_reviewer_outcome(key, _result(critic.MODE_API_OR_CLI), reaches=lambda _c: True)
    assert _status(_choice()).ready


def test_clipboard_by_design_is_not_a_refusal():
    """No key and no CLI for that vendor: clipboard is the designed fallback, not a failure."""
    from autosound_tcc.core import critic

    availability.record_reviewer_outcome(
        "agy:gemini-3.1-pro-high", _result(critic.MODE_CLIPBOARD, "no transport"),
        reaches=lambda _c: False)
    assert _status(_choice()).ready


def test_a_project_that_is_not_ready_changes_nothing():
    from autosound_tcc.core import critic

    availability.record_reviewer_outcome(
        "agy:gemini-3.1-pro-high", _result(critic.MODE_NOT_READY, "context missing"),
        reaches=lambda _c: True)
    assert _status(_choice()).ready
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_critic.py::test_a_refusal_is_named_by_its_reason_or_not_at_all tests/test_availability.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module 'autosound_tcc.core.critic' has no attribute 'refusal_reason'` and `... availability ... has no attribute 'record_reviewer_outcome'`

- [ ] **Step 3: Implement**

In `critic.py`, after `remedy`:

```python
def refusal_reason(detail: str) -> Optional[str]:
    """The availability reason a failed call's own words point to, or None when there are none.

    A location refusal is named as such — it is the one reason nothing on this machine can fix. Any
    other words are a refusal too: the call went out and no review came back."""
    from autosound_tcc.core import availability

    said = (detail or "").lower()
    if not said.strip():
        return None
    if any(word in said for word in _LOCATION_WORDS):
        return availability.LOCATION
    return availability.REFUSED
```

In `availability.py`, at the end:

```python
def record_reviewer_outcome(key: str, result, *, reaches=None) -> None:
    """One reviewer call's outcome into the state: an answer clears a refusal, a refusal sets one.

    A clipboard package for a vendor this machine has no transport for is the designed fallback and
    records nothing; so does a project that is not ready to be reviewed yet."""
    from autosound_tcc.core import critic, model_choices

    if not key:
        return
    if result.ok:
        succeeded(key)
        return
    if result.mode != critic.MODE_CLIPBOARD:
        return
    harness, _, model = key.partition(":")
    choice = model_choices.Choice(harness=harness or "omp", model=model or key, label=key)
    if not (reaches or model_choices.critic_reaches)(choice):
        return
    reason = critic.refusal_reason(result.detail)
    if reason:
        refused(key, reason, result.detail)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_critic.py tests/test_availability.py -q -p no:cacheprovider`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/core/critic.py src/autosound_tcc/core/availability.py tests/test_critic.py tests/test_availability.py
git commit -m "A reviewer call's outcome turns its model red or clears it; clipboard by design does not"
```

---

### Task 3: The agent sees it — `call_critic` records, `get_tcc_state` reports

**Files:**
- Modify: `src/autosound_tcc/core/mcp_server.py` (`_reviewer_state`, `call_critic` after `critic.log_call(...)`)
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `availability.status`, `availability.PHRASES`, `availability.record_reviewer_outcome` (Tasks 1–2)
- Produces: `_reviewer_state(...)["ready"]` false and `["not_ready_because"]` carrying the phrase when the reviewer is red

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp_server.py`:

```python
def test_a_refused_reviewer_is_not_ready_and_says_why_in_one_phrase(tmp_path, monkeypatch):
    """Windows, 2026-09-13: the payload said `ready: true` and the call failed in two seconds —
    "Selected model is not supported in the selected location"."""
    from autosound_tcc.core import availability, config, project_settings
    from autosound_tcc.core.mcp_server import _reviewer_state

    availability.reset()
    key = "agy:gemini-3.1-pro-high"
    project_settings.set_value(config.tcc_dir(tmp_path), "critic", key)
    monkeypatch.setattr("autosound_tcc.core.critic.preflight", lambda _p: [])
    availability.refused(key, availability.LOCATION, "not supported in the selected location")
    try:
        state = _reviewer_state(tmp_path)
    finally:
        availability.reset()

    assert state["ready"] is False
    assert availability.PHRASES[availability.LOCATION] in state["not_ready_because"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mcp_server.py::test_a_refused_reviewer_is_not_ready_and_says_why_in_one_phrase -q -p no:cacheprovider`
Expected: FAIL — `assert True is False`

- [ ] **Step 3: Implement**

In `mcp_server.py` add `availability` to the `from autosound_tcc.core import ...` line. In `_reviewer_state`, replace the two last keys of the returned dict:

```python
        "ready": not missing,
        "not_ready_because": missing,
```

with

```python
        # And what this launch has LEARNED about it: a refusal (region, key) or a catalogue still
        # being read. Configured and reachable are not the same as answering (2026-09-13).
        "ready": not because,
        "not_ready_because": because,
```

and, just before `return {`, compute:

```python
    state = availability.status(choice)
    because = list(missing) + ([availability.PHRASES[state.reason]] if not state.ready else [])
```

In `call_critic`, right after `critic.log_call(result, None, project_dir)`:

```python
        availability.record_reviewer_outcome(
            project_settings.get(config.tcc_dir(project_dir), "critic", "") or "", result)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_mcp_server.py -q -p no:cacheprovider`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/core/mcp_server.py tests/test_mcp_server.py
git commit -m "get_tcc_state: a refused reviewer is not ready, and says why in one phrase"
```

---

### Task 4: Words for people, and red rows in the pickers

**Files:**
- Create: `src/autosound_tcc/ui/tcc/availability_view.py`
- Modify: `src/autosound_tcc/ui/tcc/i18n.py` (10 keys × 4 languages)
- Modify: `src/autosound_tcc/ui/tcc/main_window.py` (`MainWindow._fill_combo`, ~3950–4010)
- Modify: `src/autosound_tcc/ui/tcc/project_gate_dialog.py` (~203, same note)
- Modify: `tests/test_main_window.py:2867`
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `availability.status`, reason constants (Task 1)
- Produces: `availability_view.word(state: Status) -> str`, `availability_view.phrase(state: Status) -> str` (both `""` for a ready state)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main_window.py`:

```python
def test_a_model_that_cannot_run_is_red_with_one_word_and_the_rest_stay_plain():
    """The Arbiter, 2026-09-13: "models must be red when they are not available". Two colours:
    plain is ready, red is everything else, with one word for why."""
    from PySide6.QtGui import QColor

    from autosound_tcc.core import availability, model_choices
    from autosound_tcc.ui.tcc.theme import current_theme

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    combo = window._ai_critic_combo
    fine = model_choices.Choice(harness="agy", model="gemini-3.1-flash", label="Gemini 3.1 Flash")
    refused = model_choices.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro")
    availability.reset()
    availability.refused(refused.key, availability.LOCATION, "selected location")
    try:
        MainWindow._fill_combo(combo, [fine, refused], fine.key, critic=True)
    finally:
        availability.reset()

    assert combo.itemData(0, Qt.ItemDataRole.ForegroundRole) is None
    assert combo.itemData(1, Qt.ItemDataRole.ForegroundRole) == QColor(current_theme().warn)
    assert i18n.t("availLocation") in combo.itemText(1)
    assert combo.model().item(1).isEnabled() is True, "a refused model can still be chosen"
```

Change `tests/test_main_window.py:2867` from

```python
    assert i18n.t("modelInstallCli").format(cli="codex") in rows[1]
```

to

```python
    assert i18n.t("availNotInstalled") in rows[1]
    assert i18n.t("modelInstallCli").format(cli="codex") in combo.itemData(1, Qt.ItemDataRole.ToolTipRole)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest "tests/test_main_window.py::test_a_model_that_cannot_run_is_red_with_one_word_and_the_rest_stay_plain" "tests/test_main_window.py::test_a_route_whose_cli_is_missing_is_greyed_and_says_what_it_needs" -q -p no:cacheprovider`
Expected: FAIL — `KeyError`/missing key `availLocation` (i18n) and the foreground assertion

- [ ] **Step 3: Implement**

`i18n.py` — add to each language table (after `modelUnconfirmed`):

```python
# en
        "availNotInstalled": "not installed",
        "availSignIn": "sign in",
        "availLocation": "region",
        "availRefused": "refused",
        "availNotChecked": "not checked",
        "availPhraseNotInstalled": "CLI not installed",
        "availPhraseSignIn": "sign in required",
        "availPhraseLocation": "not available in your region",
        "availPhraseRefused": "the last call was refused",
        "availPhraseNotChecked": "not checked yet",
# uk
        "availNotInstalled": "не встановлено",
        "availSignIn": "увійти",
        "availLocation": "регіон",
        "availRefused": "відмова",
        "availNotChecked": "не перевірено",
        "availPhraseNotInstalled": "CLI не встановлено",
        "availPhraseSignIn": "потрібен вхід",
        "availPhraseLocation": "недоступна у твоєму регіоні",
        "availPhraseRefused": "останній виклик відхилено",
        "availPhraseNotChecked": "ще не перевірено",
# pl
        "availNotInstalled": 'nie zainstalowano',
        "availSignIn": 'zaloguj się',
        "availLocation": 'region',
        "availRefused": 'odmowa',
        "availNotChecked": 'niesprawdzone',
        "availPhraseNotInstalled": 'CLI nie jest zainstalowane',
        "availPhraseSignIn": 'wymagane logowanie',
        "availPhraseLocation": 'niedostępny w twoim regionie',
        "availPhraseRefused": 'ostatnie wywołanie odrzucono',
        "availPhraseNotChecked": 'jeszcze niesprawdzone',
# de
        "availNotInstalled": 'nicht installiert',
        "availSignIn": 'anmelden',
        "availLocation": 'Region',
        "availRefused": 'abgelehnt',
        "availNotChecked": 'nicht geprüft',
        "availPhraseNotInstalled": 'CLI nicht installiert',
        "availPhraseSignIn": 'Anmeldung nötig',
        "availPhraseLocation": 'in deiner Region nicht verfügbar',
        "availPhraseRefused": 'der letzte Aufruf wurde abgelehnt',
        "availPhraseNotChecked": 'noch nicht geprüft',
```

`ui/tcc/availability_view.py`:

```python
"""Availability for people: one word for a picker row, one short phrase for the footer."""
from __future__ import annotations

from autosound_tcc.core import availability
from autosound_tcc.ui.tcc import i18n

_WORDS = {
    availability.NOT_INSTALLED: "availNotInstalled",
    availability.SIGN_IN: "availSignIn",
    availability.LOCATION: "availLocation",
    availability.REFUSED: "availRefused",
    availability.NOT_CHECKED: "availNotChecked",
}
_PHRASES = {
    availability.NOT_INSTALLED: "availPhraseNotInstalled",
    availability.SIGN_IN: "availPhraseSignIn",
    availability.LOCATION: "availPhraseLocation",
    availability.REFUSED: "availPhraseRefused",
    availability.NOT_CHECKED: "availPhraseNotChecked",
}


def word(state: availability.Status) -> str:
    return "" if state.ready else i18n.t(_WORDS[state.reason])


def phrase(state: availability.Status) -> str:
    return "" if state.ready else i18n.t(_PHRASES[state.reason])
```

`MainWindow._fill_combo` — replace the block

```python
            if not choice.available:
                ...
                notes.append(i18n.t("modelInstallCli").format(cli=choice.harness))
            elif critic and not model_choices.critic_reaches(choice):
                notes.append(i18n.t("modelClipboardOnly"))
            if model_choices.unconfirmed(choice):
                ...
                notes.append(i18n.t("modelUnconfirmed"))
```

with

```python
            # One word for why it cannot run, or nothing (spec 2026-09-13). "Not installed" and
            # "remembered from last launch" are two of the reasons now, not two separate badges.
            state = availability.status(choice)
            if not state.ready:
                notes.append(availability_view.word(state))
            elif critic and not model_choices.critic_reaches(choice):
                notes.append(i18n.t("modelClipboardOnly"))
```

and, after `combo.setItemData(row, tip, Qt.ItemDataRole.ToolTipRole)`, replace that line's `tip` assembly so the long reason stays reachable, then colour the row:

```python
            tip = f"{choice.route_note}\n{choice.model}"
            if not choice.available:
                tip += "\n" + i18n.t("modelInstallCli").format(cli=choice.harness)
            if state.detail:
                tip += "\n" + state.detail
            combo.setItemData(row, tip, Qt.ItemDataRole.ToolTipRole)
            if not state.ready:
                combo.setItemData(row, QColor(current_theme().warn), Qt.ItemDataRole.ForegroundRole)
```

Add imports at the top of `main_window.py`: `availability` to the `from autosound_tcc.core import ...` line and `from autosound_tcc.ui.tcc import availability_view`.

`project_gate_dialog.py:203` — replace `notes.append(i18n.t("modelInstallCli").format(cli=choice.harness))` with `notes.append(availability_view.word(availability.status(choice)))` inside the same `if not choice.available:` branch, and add the same two imports.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_main_window.py tests/test_i18n_languages.py tests/test_project_gate_dialog.py -q -p no:cacheprovider`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/ui/tcc/availability_view.py src/autosound_tcc/ui/tcc/i18n.py src/autosound_tcc/ui/tcc/main_window.py src/autosound_tcc/ui/tcc/project_gate_dialog.py tests/test_main_window.py
git commit -m "Pickers: a model that cannot run is red with one word for why; the rest stay plain"
```

---

### Task 5: The reviewer footer's short phrase, and the reload button forgets refusals

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/main_window.py` (`_refresh_critic_status` ~3532, `_reload_from_disk` 1667)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `availability.status / forget_refusals`, `availability_view.phrase` (Tasks 1, 4)

- [ ] **Step 1: Write the failing tests**

```python
def test_a_red_reviewer_says_why_in_the_footer_and_the_reload_button_forgets_it(monkeypatch):
    """"A short answer, so the person understands at once" (the Arbiter, 2026-09-13)."""
    from autosound_tcc.core import availability, model_choices

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    chosen = model_choices.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro")
    window._critic_choices = [chosen]
    MainWindow._fill_combo(window._ai_critic_combo, [chosen], chosen.key, critic=True)
    monkeypatch.setattr(window, "_refresh_cli_catalogue", lambda force=False: None)
    monkeypatch.setattr(window, "_ping_rew", lambda: None)
    availability.reset()
    availability.refused(chosen.key, availability.LOCATION, "not supported in the selected location")
    try:
        window._refresh_critic_status()
        assert i18n.t("availPhraseLocation") in window._critic_status.text()
        assert "selected location" in window._critic_status.toolTip()

        window._reload_from_disk()
        assert availability.status(chosen).ready
    finally:
        availability.reset()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest "tests/test_main_window.py::test_a_red_reviewer_says_why_in_the_footer_and_the_reload_button_forgets_it" -q -p no:cacheprovider`
Expected: FAIL — the footer text lacks the phrase

- [ ] **Step 3: Implement**

At the top of `_refresh_critic_status`, after `self._refresh_critic_warning()`:

```python
        key = str(self._ai_critic_combo.currentData() or "")
        chosen = model_choices.resolve(self._critic_choices, key).choice if key else None
        if chosen is not None:
            state = availability.status(chosen)
            if not state.ready:
                self._critic_status.setText(f"{chosen.label} · {availability_view.phrase(state)}")
                self._critic_status.setToolTip(state.detail or availability_view.phrase(state))
                return
        self._critic_status.setToolTip("")
```

In `_reload_from_disk`, immediately before `self._refresh_cli_catalogue(force=True)`:

```python
        # ↻ is the explicit re-check: what refused earlier in this launch gets another chance.
        availability.forget_refusals()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_main_window.py -q -p no:cacheprovider`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/ui/tcc/main_window.py tests/test_main_window.py
git commit -m "Reviewer footer: one phrase for why it is red; the reload button forgets refusals"
```

---

### Task 6: Read the catalogues on every start — Windows waits inside the console, up to a cap

**Files:**
- Modify: `src/autosound_tcc/core/availability.py` (`STARTUP_MODELS_CAP_S`, `StartupReading`, `start_startup_reading`, `startup_reading`)
- Modify: `src/autosound_tcc/core/child.py` (`open_app_console`, `_hide_after_showing`: `ready`, `cap`)
- Modify: `src/autosound_tcc/app.py` (`STARTUP_CONSOLE_TEXT`, startup wiring after `open_app_console`)
- Modify: `src/autosound_tcc/ui/tcc/main_window.py` (`_CliCatalogueWorker`: `wait_for`; construction at ~820)
- Test: `tests/test_availability.py`, `tests/test_child.py`

**Interfaces:**
- Consumes: `availability.begin_reading / finish_reading` (Task 1); `model_choices.refresh_cli_catalogue(force, active_omp)`; `claude_sdk.probe_signed_in(force)`
- Produces:
  - `availability.STARTUP_MODELS_CAP_S = 8.0`
  - `class StartupReading: done: threading.Event; start() -> StartupReading; wait(cap: float) -> bool`
  - `availability.start_startup_reading(read=None) -> StartupReading` (registers it), `availability.startup_reading() -> Optional[StartupReading]`
  - `child.open_app_console(message, *, alloc=None, write=None, hide=None, defer=None, ready=None, cap=None) -> bool`
  - `child._hide_after_showing(*, hide, seconds, sleep=None, keeper=None, ready=None, cap=None)`
  - `_CliCatalogueWorker(force=False, active_omp=None, wait_for=None)`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_availability.py`:

```python
import time


def test_the_start_waits_for_the_reading_only_up_to_the_cap():
    release = threading.Event()
    reading = availability.StartupReading(lambda: release.wait(5)).start()

    started = time.monotonic()
    assert reading.wait(0.1) is False
    assert time.monotonic() - started < 1.0, "the cap, not the reader, decides how long the start waits"

    release.set()
    assert reading.wait(2.0) is True


def test_a_reader_that_raises_still_finishes_the_reading():
    def boom():
        raise RuntimeError("agy exploded")

    assert availability.StartupReading(boom).start().wait(2.0) is True


def test_the_default_reader_marks_harnesses_not_checked_until_it_is_done(monkeypatch):
    from autosound_tcc.core import claude_sdk, model_choices

    seen = []
    monkeypatch.setattr(model_choices, "refresh_cli_catalogue",
                        lambda **kw: seen.append(availability.status(_choice(), signed_in=lambda: None,
                                                                       unconfirmed=lambda _c: False).reason))
    monkeypatch.setattr(claude_sdk, "probe_signed_in", lambda **kw: None)

    availability.read_catalogues()

    assert seen == [availability.NOT_CHECKED]
    assert _status(_choice()).ready
```

Append to `tests/test_child.py`:

```python
def test_the_console_stays_up_until_the_models_are_read_or_the_cap(monkeypatch):
    """The Arbiter, 2026-09-13: read the models inside the first window. The console hides when the
    reading is done — never before its readable second, never after the cap."""
    import threading

    order: list = []
    ready = threading.Event()
    waited: list = []

    class _Ready:
        def wait(self, timeout):
            waited.append(timeout)
            return ready.wait(0)

    child._hide_after_showing(
        hide=lambda: order.append("hide"),
        seconds=1.2,
        sleep=lambda s: order.append(f"waited {s}"),
        keeper=lambda pid, **kw: order.append("keeper"),
        ready=_Ready(),
        cap=8.0,
    )

    assert order == ["waited 1.2", "hide", "keeper"]
    assert waited == [pytest.approx(6.8)], "the rest of the cap, after the readable second"
```

In `tests/test_startup_console.py` nothing changes: the new text still satisfies it.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_availability.py tests/test_child.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: ... has no attribute 'StartupReading'`, and `TypeError: _hide_after_showing() got an unexpected keyword argument 'ready'`

- [ ] **Step 3: Implement**

`availability.py` — append:

```python
import logging

#: How long a Windows start waits inside its console for the catalogues (the Arbiter, 2026-09-13).
STARTUP_MODELS_CAP_S = 8.0
_STARTUP_HARNESSES = ("agy", "sdk", "codex")
_startup: "Optional[StartupReading]" = None


def read_catalogues() -> None:
    """Ask every CLI now, forced: a CLI installed since the last start is noticed on this one."""
    from autosound_tcc.core import claude_sdk, model_choices

    begin_reading(_STARTUP_HARNESSES)
    try:
        model_choices.refresh_cli_catalogue(force=True)
        claude_sdk.probe_signed_in(force=True)
    finally:
        for harness in _STARTUP_HARNESSES:
            finish_reading(harness)


class StartupReading:
    """The start's catalogue read, on its own thread, with an event that says it is over."""

    def __init__(self, read=None) -> None:
        self._read = read or read_catalogues
        self.done = threading.Event()

    def start(self) -> "StartupReading":
        threading.Thread(target=self._run, name="tcc-read-models", daemon=True).start()
        return self

    def _run(self) -> None:
        try:
            self._read()
        except Exception:  # noqa: BLE001 — a failed read leaves models red, never a failed start
            logging.getLogger("autosound_tcc").exception("startup model reading failed")
        finally:
            self.done.set()

    def wait(self, cap: float) -> bool:
        return self.done.wait(cap)


def start_startup_reading(read=None) -> StartupReading:
    global _startup
    _startup = StartupReading(read)
    return _startup


def startup_reading() -> Optional[StartupReading]:
    return _startup
```

Note: `start_startup_reading` only CREATES and registers; `app.py` calls `.start()` after the console exists, so children inherit it.

`child.py` — `open_app_console` signature gains `ready=None, cap=None`, and the deferred call becomes:

```python
    (defer or _spawn_daemon)(_hide_after_showing,
                             {"hide": hide, "seconds": APP_CONSOLE_VISIBLE_S,
                              "ready": ready, "cap": cap})
```

`_hide_after_showing` signature gains `ready=None, cap=None`; after the sleep:

```python
    (sleep or time.sleep)(seconds)
    if ready is not None and cap is not None:
        # Held until the models are read (the Arbiter, 2026-09-13), but never past the cap.
        ready.wait(max(0.0, cap - seconds))
```

`app.py` — `STARTUP_CONSOLE_TEXT = "Autosound TCC: reading models..."`, and the startup call becomes:

```python
    try:
        from autosound_tcc.core import availability
        reading = availability.start_startup_reading()
    except ImportError:  # a light install without the GUI extras reads nothing at start
        availability, reading = None, None
    console = child.open_app_console(
        STARTUP_CONSOLE_TEXT,
        ready=reading.done if reading else None,
        cap=availability.STARTUP_MODELS_CAP_S if reading else None)
    child.hide_console_windows()
    if reading is not None:
        reading.start()
        if console:
            # Windows: the start waits inside the console for what the machine can run.
            reading.wait(availability.STARTUP_MODELS_CAP_S)
```

`main_window.py` — `_CliCatalogueWorker.__init__` gains `wait_for=None` (stored as `self._wait_for`); `run` begins:

```python
        if self._wait_for is not None:
            # The start already asked everything, forced. Wait for it, then only what it skips
            # (omp for marked models) — asking agy and claude a second time is a second window.
            self._wait_for.done.wait()
            model_choices.refresh_cli_catalogue(force=False, active_omp=self._active_omp)
            self.done.emit()
            return
```

and at construction (~820) the worker is built as
`_CliCatalogueWorker(wait_for=availability.startup_reading())`.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_availability.py tests/test_child.py tests/test_startup_console.py tests/test_main_window.py -q -p no:cacheprovider`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/core/availability.py src/autosound_tcc/core/child.py src/autosound_tcc/app.py src/autosound_tcc/ui/tcc/main_window.py tests/test_availability.py tests/test_child.py
git commit -m "Read the model catalogues on every start; on Windows inside the console, up to a cap"
```

---

### Task 7: Probe the reviewer at session start, only when one is chosen

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/main_window.py` (new `_ReviewerProbeWorker` beside `_CliCatalogueWorker`; `_probe_reviewer`, `_on_reviewer_probed`; call after `self._dialog.attach_agent(...)` ~3785)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `critic.run(package, project_dir, role="ask", model, harness) -> CriticResult`; `availability.record_reviewer_outcome` (Task 2)
- Produces: `_ReviewerProbeWorker(key: str, project_dir: Path)` with `done = Signal()`; `MainWindow._probe_reviewer() -> None`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_reviewer_probe_turns_a_refused_model_red(tmp_path, monkeypatch):
    from autosound_tcc.core import availability, critic, model_choices
    from autosound_tcc.ui.tcc.main_window import _ReviewerProbeWorker

    key = "agy:gemini-3.1-pro-high"
    calls = []
    monkeypatch.setattr(critic, "run", lambda package, **kw: calls.append(kw) or critic.CriticResult(
        critic.MODE_CLIPBOARD, "", None, "ask", "not supported in the selected location", 1.0, "t"))
    monkeypatch.setattr(model_choices, "critic_reaches", lambda _c: True)
    availability.reset()
    try:
        _ReviewerProbeWorker(key, tmp_path).run()
        state = availability.status(model_choices.Choice(harness="agy", model="gemini-3.1-pro-high",
                                                         label="x"))
    finally:
        availability.reset()

    assert calls and calls[0]["role"] == "ask" and calls[0]["model"] == "gemini-3.1-pro-high"
    assert state.reason == availability.LOCATION


def test_no_reviewer_chosen_means_no_probe(monkeypatch):
    """A fresh install has no reviewer — nothing to probe and nothing to turn red (the Arbiter)."""
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    monkeypatch.setattr(window, "_project_setting", lambda key: "")
    started = []
    monkeypatch.setattr("autosound_tcc.ui.tcc.main_window._ReviewerProbeWorker.start",
                        lambda self: started.append(self))

    window._probe_reviewer()

    assert started == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest "tests/test_main_window.py::test_the_reviewer_probe_turns_a_refused_model_red" "tests/test_main_window.py::test_no_reviewer_chosen_means_no_probe" -q -p no:cacheprovider`
Expected: FAIL — `ImportError: cannot import name '_ReviewerProbeWorker'`

- [ ] **Step 3: Implement**

Beside `_CliCatalogueWorker`:

```python
#: What the probe asks. Short, so the call costs as little as a real call can.
_REVIEWER_PROBE_QUESTION = "Reply with the single word: ready."


class _ReviewerProbeWorker(QThread):
    """One short `ask` to the chosen reviewer at session start, so a refusal (region, key) is red
    before the first review instead of being found by it (the Arbiter, 2026-09-13)."""

    done = Signal()

    def __init__(self, key: str, project_dir) -> None:
        super().__init__()
        self._key = key
        self._project_dir = project_dir

    def run(self) -> None:
        import tempfile

        harness, _, model = self._key.partition(":")
        # A package FILE outside the project: `critic.run` writes markdown it is handed into the
        # project, and a probe must leave nothing behind there.
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "reviewer-probe.md"
            package.write_text(_REVIEWER_PROBE_QUESTION, encoding="utf-8")
            result = critic.run(str(package), project_dir=self._project_dir, role="ask",
                                model=model or None, harness=harness)
        availability.record_reviewer_outcome(self._key, result)
        self.done.emit()
```

In `MainWindow`:

```python
    def _probe_reviewer(self) -> None:
        key = self._project_setting(_CRITIC_KEY)
        if not key or os.environ.get("AUTOSOUND_TCC_MCP", "1") == "0":
            return
        worker = _ReviewerProbeWorker(key, config.project_dir())
        worker.done.connect(self._on_reviewer_probed)
        self._reviewer_probe = worker
        worker.start()

    def _on_reviewer_probed(self) -> None:
        self._reload_model_choices()
        self._refresh_critic_status()
```

After `self._dialog.attach_agent(...)` in the session-start path (~3785–3791), add `self._probe_reviewer()`.

Make sure `Path`, `critic`, `availability` and `qt_shutdown` are imported in `main_window.py` (add to the existing import lines if absent).

In `MainWindow.stop_workers` (~4406), right after the `_cli_catalogue` wait:

```python
        probe = getattr(self, "_reviewer_probe", None)
        if probe is not None and probe.isRunning():
            probe.wait(5000)
            if probe.isRunning():
                # A real model call can outlast any wait worth making at quit; hand it over rather
                # than let Qt destroy a running thread (F-027, `qt_shutdown.detach`).
                qt_shutdown.detach(probe)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_main_window.py -q -p no:cacheprovider`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/ui/tcc/main_window.py tests/test_main_window.py
git commit -m "Probe the chosen reviewer with one short ask at session start"
```

---

### Task 8: The whole suite, and the change log

**Files:**
- Modify: `CHANGELOG.md` (add `## [Unreleased]` entry if the release form from #140 is not in yet; otherwise the next version's entry)

- [ ] **Step 1: Run everything**

Run: `make check`
Expected: ruff clean; all tests pass (the count before this plan was 1895 passed, 1 skipped, plus the new ones)

- [ ] **Step 2: Write the change log entry**

```markdown
### Changed

- **Models are re-read on every start.** A CLI installed since the last start — codex, or a new agy
  model — is on the list the next time TCC opens. On Windows the reading happens inside the first
  console window (`Autosound TCC: reading models...`), waiting up to 8 seconds.
- **A model that cannot run is red, with one word for why** — not installed, sign in, region,
  refused, not checked. The reviewer footer says it in one short phrase, and the agent sees the same
  reason in `get_tcc_state`. The reload button re-checks and forgets earlier refusals.
- **The chosen reviewer is probed at session start** with one short question, so a model refused
  for this region is red before the first review.
```

- [ ] **Step 3: Commit and push**

```bash
git add CHANGELOG.md
git commit -m "CHANGELOG: models re-read on every start, red when they cannot run, reviewer probed"
git push origin main
```
