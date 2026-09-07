# Cross-platform failures — implementation plan

Written 2026-09-07, from the first CI runs this repo has ever had
(`.github/workflows/ci.yml`, HUB-045). Sources: `ayukhno/autosound-tcc#17` (26 Windows
failures) and `#18` (two machine-dependent tests).

**Goal:** every platform green — Windows 26 → 0, Linux 2 → 0, macOS stays at 0.

**Approach:** fix by cause, not by test. The 28 failures are five causes, and the order below
is by ratio of harm removed to risk taken: the guard that makes any result trustworthy first,
then the one that loses a tuner's own words, then the noise that hides the next real thing.

## Global constraints

- **Windows and Linux cannot be checked locally.** macOS is the only machine here. Every task's
  real verification is a CI run: push, then `gh run view <id>`. `make test` on macOS is the
  pre-check, never the proof.
- **The short loop is `tests/cross-platform-suspects.txt`.** It holds exactly the node ids that
  fail off macOS, and the `suspects` job runs only those on Windows and Linux — about a minute
  against the full suite's nine. Delete a line when it is fixed; the file is the progress count.
  On a Windows VM the same list runs by hand:

      uv run --extra dev --python 3.12 python -m pytest $(grep -vE '^\s*(#|$)' tests/cross-platform-suspects.txt)

  It narrows the loop, it does not replace it: the full jobs still run, because a fix for one
  platform can break another test anywhere.
- **`make test` must stay at `1687 passed, 1 skipped`** — a fix for another platform that costs
  a macOS test is a regression, not a fix.
- **`vendor/autosound-tuning-skill` is not ours.** A cause that lands inside it goes to the
  `skill` role as a bus ticket (`ROLES` §0.1), never as an edit here.
- Comments and docstrings in English, like the rest of the tree.
- Commit per task; the CI run of that commit is the task's evidence.

---

## Task 1: the conftest probe guard (`#18`)

Two tests read the developer's PATH and pass only on a machine that has `agy`/`gemini`
installed. Until this is fixed, no other result on this list can be trusted — a green run might
just mean "same laptop".

**Files:**
- Modify: `tests/conftest.py:172-173` (the autouse fixture that already patches `cli_available`)
- Test: `tests/test_conftest_guards.py` (create)

**Why here and not in the two tests:** `conftest.py:165-169` already states the rule — a probe of
the machine must not decide a test's outcome — and already patches `cli_available`. This is the
same rule with a second door: `model_choices.critic_reaches()` calls `os.environ.get()` and
`shutil.which()` directly, so the existing patch never sees it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_conftest_guards.py
"""The suite must not be able to read this machine. `conftest` says so for `cli_available`;
these tests are the same claim, checked rather than assumed."""
from autosound_tcc.core import model_choices


def test_the_suite_cannot_see_which_clis_this_machine_has():
    assert model_choices.cli_available("agy") is False


def test_the_suite_cannot_see_whether_a_critic_is_reachable():
    """`critic_reaches` probes `os.environ` and `shutil.which` directly, so patching
    `cli_available` does not cover it — that gap is what made
    `test_no_row_repeats_what_the_row_already_says` pass on one laptop and fail on CI."""
    choice = model_choices.Choice(
        harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro (High)",
        provider="google",
    )
    assert model_choices.critic_reaches(choice) is False
```

- [ ] **Step 2: Run it and watch the second one fail**

`uv run --extra dev --python 3.12 python -m pytest tests/test_conftest_guards.py -v`

Expected on this machine: first passes, second FAILS (`agy` is at `~/.local/bin/agy` and
`GEMINI_API_KEY` is set, so `critic_reaches` returns True). On a bare machine both pass —
that asymmetry is exactly the defect.

- [ ] **Step 3: Add the guard beside the one already there**

```python
    monkeypatch.setattr(model_choices, "_CLI_CACHE", {}, raising=False)
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: False, raising=False)
    # ...and the same for the reachability probe, which does NOT go through `cli_available`:
    # it asks `os.environ` and `shutil.which` itself. Without this the critic badge and the
    # footer warning are decided by what the developer happens to have installed.
    monkeypatch.setattr(model_choices, "critic_reaches", lambda choice: False, raising=False)
```

- [ ] **Step 4: Both guard tests pass, and the two victims now fail HERE**

`uv run --extra dev --python 3.12 python -m pytest tests/test_conftest_guards.py tests/test_main_window.py -q`

Expected: the guards pass, and `test_no_row_repeats_what_the_row_already_says` +
`test_the_footer_says_when_the_reviewer_is_not_what_it_appears_to_be` now fail on macOS too —
the CI failure reproduced locally. That is the point of the step.

- [ ] **Step 5: Fix the two tests to state what they mean**

They are about badge composition and footer wording, not about this machine. Each patches what
it needs:

```python
    monkeypatch.setattr(mc, "critic_reaches", lambda choice: True)
```

in `test_no_row_repeats_what_the_row_already_says` (it asserts the absence of a badge, so it
must say the critic IS reachable), and in
`test_the_footer_says_when_the_reviewer_is_not_what_it_appears_to_be` per what that test asserts
— read the assertion before choosing True or False.

- [ ] **Step 6: Whole suite green**

`make test` → `1689 passed, 1 skipped` (1687 + the two new guards).

- [ ] **Step 7: Commit and let CI answer**

```bash
git add tests/conftest.py tests/test_conftest_guards.py tests/test_main_window.py
git commit -m "Тест не має права читати машину: гард conftest не покривав critic_reaches (tcc#18)"
git push
gh run list --limit 1
```

Expected in CI: Linux `2 failed` → `0 failed`, Windows `26 failed` → `24 failed`.

---

## Task 2: `encoding="utf-8"` on every subprocess (`#17`, pile 3)

14 calls across 10 modules pass `text=True` with no encoding, so Python decodes the child's
output with the parent's locale. On macOS that is UTF-8 and every one of them has been right by
accident; on a Polish or German Windows it mis-decodes. This is the pile that loses a tuner's
own words.

**Files (all `Modify`):** `core/install_report.py`, `core/model_choices.py` (2 calls),
`core/updates.py`, `core/contract_check.py`, `core/profile_writer.py`, `core/critic.py` (2),
`core/process_writer.py`, `core/desktop_entry.py` (3), `core/claude_sdk.py`,
`state/project_view.py`
**Test:** `tests/test_packaging.py` (add — it is where this tree keeps its AST-level rules)

- [ ] **Step 1: Write the failing test**

```python
def test_no_subprocess_decodes_with_the_machines_locale():
    """`text=True` without `encoding` decodes using the parent's locale. On macOS that is UTF-8,
    which is why 14 calls were right by accident for a year; on a Polish or German Windows the
    same bytes come back mis-decoded, and a mis-decode is not readable the way the skill's
    console fallback is (found on the first Windows CI run, 2026-09-07)."""
    import ast

    offenders = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kwargs = {kw.arg for kw in node.keywords if kw.arg}
            if "text" in kwargs and "encoding" not in kwargs:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert not offenders, (
        "text=True without encoding= decodes with the locale, not UTF-8: " + ", ".join(offenders)
    )
```

- [ ] **Step 2: Run it, expect 14 offenders**

`uv run --extra dev --python 3.12 python -m pytest tests/test_packaging.py::test_no_subprocess_decodes_with_the_machines_locale -v`

Expected: FAIL listing 14 `file:line` pairs.

- [ ] **Step 3: Add `encoding="utf-8"` to each**

One argument per call, next to `text=True`. In `core/process_writer.py:127` add a line saying
why, since that is the call the CI failure came through:

```python
                proc = subprocess.run(
                    [sys.executable, str(script), str(_process_dir(project_dir)), *args],
                    capture_output=True,
                    text=True,
                    # NOT the locale's. The skill writes UTF-8 to disk on every platform and folds
                    # only what a console cannot draw; decoding its stdout with a Windows ANSI page
                    # turns a verdict into mojibake on the way back (CI, 2026-09-07).
                    encoding="utf-8",
                    timeout=timeout_s,
                    env=vendor_loader.child_env(),
                    **child.quiet(),
                )
```

- [ ] **Step 4: Test passes, suite green**

`uv run --extra dev --python 3.12 python -m pytest tests/test_packaging.py -q` then `make test`.

- [ ] **Step 5: Commit and read CI**

```bash
git commit -am "Підпроцес декодується UTF-8, а не локаллю: 14 викликів у 10 модулях (tcc#17)"
git push
```

Expected to clear on Windows: `test_diagnostics_panel::test_the_report_is_read_only_when_the_tab_is_opened`,
`test_listening::test_a_verdict_reaches_the_journal_and_reads_back`, and the three
`test_attach_image` failures (all three assert on a Cyrillic filename fragment). Verify against
the run rather than assuming — `test_contract_check` and `test_skill_selftests` may or may not
be in this set; Task 5 owns whatever is left.

---

## Task 3: assertions that hard-code `/` (`#17`, pile 2)

The code is right on Windows; the test compares against a POSIX string.

**Files:** `tests/test_model_choices.py`, `tests/test_packaging.py` (4 tests),
`tests/test_skill_selftests.py`

- [ ] **Step 1: See each one's actual assertion**

```bash
uv run --extra dev --python 3.12 python -m pytest \
  tests/test_model_choices.py::test_a_model_id_is_written_in_exactly_one_module -q
```

The failures name the shape: `['autosound_tcc\\core\\model_choices.py:60']` against an expected
`autosound_tcc/core/model_choices.py`, and `['state\\FULL\\v_001.json']`.

- [ ] **Step 2: Compare paths as paths, not as strings**

Where the test builds an expected string, build a `Path` and compare `Path` to `Path`; where it
must stay a string (a report's text), normalise with `.as_posix()` on the produced value. Do not
`.replace("\\", "/")` — that hides a real backslash in a name.

- [ ] **Step 3: `make test` green, commit, read CI**

Expected: Windows drops these 6.

---

## Task 4: tests written for POSIX (`#17`, pile 1)

Nine tests assert macOS/Linux behaviour and cannot pass on Windows by construction; two assert
Windows behaviour with POSIX separators.

**File:** `tests/test_desktop_entry.py`, `tests/test_terminal_launcher.py`,
`tests/test_target_curve.py`, `tests/test_project_gate.py`

- [ ] **Step 1: Mark the ones that are about a platform**

```python
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX launcher behaviour")
```

per test, not per file, where only some tests in the file are POSIX-bound:

- `test_desktop_entry.py`: `test_launcher_is_executable_and_execs_the_installed_binary`
  (asserts the `0o100` bit), `test_a_launcher_path_with_a_space_stays_one_word`,
  `test_a_platform_with_no_desktop_entry_says_how_to_start_it`,
  `test_the_launcher_is_found_beside_this_interpreter_first`
- `test_terminal_launcher.py`: `test_macos_builds_an_applescript_that_cds_then_runs_the_cli`,
  `test_macos_quotes_a_path_that_would_break_applescript` — AppleScript; the second one also
  cannot even construct its path on Windows (`we"ird \ dir` is an illegal filename)
- `test_target_curve.py::test_a_platform_with_no_select_form_opens_the_folder` —
  `NotImplementedError: cannot instantiate 'PosixPath'`
- `test_project_gate.py::test_an_unwritable_path_does_not_accept` — uses `/proc`; give it a
  Windows-side unwritable path instead of a skip if one exists, else skip with the reason

- [ ] **Step 2: Fix the two that are about WINDOWS and still fail there**

`test_windows_shortcut_script_points_at_the_installed_launcher` and
`test_windows_shortcut_script_uses_the_packaged_icon` assert `"C:/bin/..."` while the code
correctly writes `C:\bin\...`. These are Task 3's cause in Task 4's file — compare as `Path`.

- [ ] **Step 3: `make test` green (skips do not fire on macOS), commit, read CI**

---

## Task 5: what is left, and whose it is

After Tasks 1–4, re-read the Windows job and sort the remainder. Two are already known not to be
simple:

- `test_contract_check::test_a_caller_can_end_the_check_early` and
  `test_skill_selftests::test_skill_selftest_passes[contract.py]` both report
  `contract.py produced no report (exit 1)`. `contract.py` lives in
  `vendor/autosound-tuning-skill` — **not ours**. If Task 2 does not clear it, read the child's
  stderr from the CI log, and if the fault is inside the skill, open a bus ticket to the `skill`
  role with the run link. Their `#21` is the same neighbourhood (console code pages), so this may
  already be known there.
- `test_main_window::test_the_left_column_is_one_scroll_and_the_tree_does_not_have_its_own`
  (`AssertionError: the column is what scrolls`) is a layout assertion that fails on Windows and
  Linux alike — likely a real difference in Qt's default scroll policy per platform, and the
  only one on this list that might be a product bug rather than a test bug. Investigate before
  touching: `systematic-debugging`, not a guess.

## Not in this plan: the Windows crash (`#19`)

Found while checking the `suspects` job, 2026-09-07: the Windows suite dies with
`Windows fatal exception: access violation` in
`test_dialog_live.py::test_shutdown_ends_a_worker_stuck_mid_turn`, about one run in three. It is
the process dying, not a test asserting, so it is not one of the 26 and no task here addresses it.

It does change how the results of this plan are read: while `#19` is open, a red `windows` job may
mean "26 known failures" or may mean "the suite never finished" — check which before concluding
anything. The `suspects` job is unaffected (it does not run `test_dialog_live.py`), which is the
second reason the short loop is worth having.

**Done means:** a CI run where Windows, Linux and macOS are all green, linked in `#17` and `#18`
when closing them.
