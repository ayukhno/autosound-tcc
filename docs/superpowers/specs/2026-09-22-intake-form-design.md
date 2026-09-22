# The intake is the skill's form — TCC starts it, opens it, and offers the session after it

Design, 2026-09-22. Hub `#194` (SKL-049) and `#193` (SKL-048), first step of `W-2 · v0.1.43`
(`docs/PLAN-W-2.md`, package «the skill's halves», pulled forward by the Arbiter).

## Why

The Arbiter decided on 2026-09-22 that there is ONE intake form for every front end: the page the
skill serves itself (`rew_tool/intake_form.py`, skill branch `wave-2026-09-20`, its design in
`skill:docs/DESIGN-2026-09-22-intake-simplified.md`). TCC does not embed it (no WebEngine in
PySide6-Essentials) and does not draw its own form from `intake.py`. Today TCC's intake is a
conversation: `ProfileInterviewDialog` for a new processor, the tuning session or a terminal CLI
for the rest — and the Arbiter's verdict on walking Phase −1 that way was «ГЕМОР».

## Decisions taken at the review (2026-09-22)

1. **The form REPLACES the conversational intake** in the new-project flow. The AI session finishes
   only what the form does not ask (the profile's `finalize`, the channel glossary).
2. **After the form, TCC OFFERS the session**: when `contract.py check --gate` passes, the status
   strip says so with a start button. The start is the Arbiter's click, never automatic.
3. **A child process through `subprocess.Popen`**, like `contract.py` and the reviewer scripts —
   not `QProcess` (it would go around `core/child.py`'s Windows console handling) and not
   in-process (`intake_form` rewrites `sys.path`, the reason `contract.py` is out of process too).

## Components

### `core/intake_form.py` — the form's process, and nothing else

```python
class IntakeForm:
    def __init__(self, project_dir: Path, lang: str, *, popen=subprocess.Popen,
                 script: Path | None = None, timeout_s: float = 10.0): ...
    def open_url(self) -> str          # start if not running, return the URL (idempotent)
    def running(self) -> bool
    def stop(self) -> None             # terminate, wait briefly, kill; safe to call twice
    was_opened: bool                   # true once open_url() has succeeded in this window

class IntakeFormError(Exception): ... # carries a sentence for the Arbiter, not a traceback
```

- Command: `[child.script_interpreter(), <rew_tool>/intake_form.py, "serve", <project_dir>,
  "--lang", <lang>, "--port", "0"]`, `env=vendor_loader.child_env()`, `**child.flags()`,
  `stdout=PIPE`, `stderr=PIPE`, text mode, UTF-8.
- The URL is read from stdout on a daemon thread: the first line starting `INTAKE_URL: `. Other
  lines (the translated human lines above it) are ignored. No line within `timeout_s` → the
  process is stopped and `IntakeFormError` names it: the form did not start, with the tail of
  stderr.
- `script` defaults to `vendor_loader.rew_tool_dir() / "intake_form.py"`. Missing file →
  `IntakeFormError`: the pinned method has no intake form (it arrives with the skill's next tag).
- `lang` is TCC's interface language (`i18n.current_language()`): `uk`, `en`, `de`, `pl`. The
  form writes it as `project.json` `language.reply` on Save; TCC never asks the reply language.
- The process binds 127.0.0.1 only and holds no state; stopping it loses nothing.

### `ui/tcc/main_window.py`

- **Project menu → «Інтейк»** (`menuIntake`, with a tooltip), under «Скопіювати авто». It calls
  `IntakeForm.open_url()` and `QDesktopServices.openUrl()`. A second click opens the same URL.
  `IntakeFormError` goes to the status strip as a warning, in the Arbiter's language.
- One `IntakeForm` per window (a window is one project). `closeEvent` stops it; so does opening
  another project (it builds a new window and closes this one).
- **The gate offer.** The existing project watcher already reloads after the form writes
  `project.json` / `dsp_profile.json` (`_reload_project_files`, coalesced). After that reload, when
  `IntakeForm.was_opened` is true and no tuning session is running, a worker runs
  `contract_check.run(project_dir, gate=True)`. Green → the status strip shows «Інтейк готовий»
  with a «Стартувати сесію» button, once per green (not again on the next reload while nothing
  changed). Red → nothing: the page itself shows what is missing.
- «Стартувати сесію» starts the route the project was created with: the in-app session
  (`_start_tuning_session`), or — when the new-project dialog chose a terminal CLI in this window —
  that terminal, with the hint below. Otherwise the in-app session.

### `core/contract_check.py`

`run(..., gate: bool = False)` passes `--gate`. Nothing else changes; `ok` already carries the
verdict.

### `ui/tcc/status_strip.py`

`notify(text, level="info", action=None)` where `action` is `(label, callback)`: a flat button at
the end of the strip, removed with the message. The strip's timer does not expire a message that
carries an action.

### `ui/tcc/new_project_dialog.py` and the new-project flow

- `ProfileInterviewDialog` is no longer opened. After «Створити» the new window opens and calls
  «Інтейк» itself, so the form is in the browser with no extra click. For a processor the skill has
  no profile for, the form links to its `/new-dsp` page.
- `ui/tcc/profile_interview_dialog.py` is deleted with its tests: nothing else opens it
  (`dsp_profile_interview.py` uses `OnboardingSession` directly and stays).
- A terminal CLI chosen in the dialog is no longer launched at «Створити». It is remembered by the
  new window and launched from the gate offer, with `npOnboardingHint` rewritten: the intake was
  filled on the form; continue from what the method still reports missing.
- **The seat at the copy (`#193`).** In the copy mode a «Місце слухача» combo lists
  `project.PROJECT_TYPES` (driver, passenger, both, all, rear_left, rear_right) with translated
  labels, no default (an empty first entry), and the source's own seat beside it («у джерелі:
  водій», read from the source's `project.json` `project_type`; «не задано» when absent).
  «Створити» stays disabled until a seat is chosen. The choice goes into both `seed()` calls — the
  preview (`_would_travel`) and the real one — as `seat=`.

### Strings

New `i18n` keys in all four languages: `menuIntake`, `menuIntakeTip`, `intakeNoForm`,
`intakeFailed`, `intakeReady`, `intakeStartSession`, `npSeat`, `npSeatSource`, `npSeatUnset`, and
one per seat. `npOnboardingHint` is rewritten in all four.

## The method it needs

`intake_form.py` and `seed(seat=)` exist only on skill branch `wave-2026-09-20` (`c27cd7a`). While
building, `vendor/autosound-tuning-skill` on `wave-0.1.43` points at that branch's sha. The release
pins the skill's PUBLISHED tag (`WAVES.md` §1 step 4; `make ship` refuses otherwise). Until then a
build on the old pin says `intakeNoForm` instead of failing.

## Errors, named

| what happens | what the Arbiter sees |
|---|---|
| the pinned method has no `intake_form.py` | «Ця версія методу ще без форми інтейку» (`intakeNoForm`) |
| the process exits or prints no URL in 10 s | «Форма інтейку не запустилась» + the last stderr line |
| the browser cannot be opened | the URL in the status strip, to open by hand |
| `contract.py` itself fails | nothing new: the offer simply does not appear |

## Tests

- `tests/test_intake_form.py` against a fake `serve` script (prints human lines, then
  `INTAKE_URL: http://127.0.0.1:<port>/`, then sleeps): start returns the URL; a second
  `open_url()` does not start a second process; `stop()` ends it and is idempotent; a script that
  never prints the line → `IntakeFormError` and no process left; a missing script →
  `IntakeFormError` without starting anything; the command carries `--lang` and `--port 0`.
- `contract_check.run(gate=True)` passes `--gate`.
- The status strip's action button: shown, clicked once, removed with the message.
- The gate offer: shown once on green, not while a session runs, not when the form was never
  opened, not again on a reload with nothing changed.
- The new-project dialog: in copy mode «Створити» is disabled until a seat is chosen; the seat
  reaches `seed()` in both calls; the source's seat is named; no `ProfileInterviewDialog` is built.
- By hand, on the branch pin: new project → the form opens in the browser → Save → «Інтейк
  готовий» → the session starts; «Інтейк» from the menu on an existing project; copy with a seat.

## Not in this step

The seat is not editable in TCC after the copy (the form shows it fixed, by the method's rule). No
native form, no embedded browser, no parsing of the page's output — the files on disk are the only
interface.
