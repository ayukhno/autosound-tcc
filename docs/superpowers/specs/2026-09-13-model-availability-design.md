# Model availability: read at every start, red when unavailable, one short reason

Date: 2026-09-13 · Status: design approved by the Arbiter, not implemented · Origin: the Arbiter's
notes on v0.1.38 (Windows)

## Problem

- **What the machine can run is not re-read.** `agy models` is asked once per machine and kept on
  disk (`model_choices._skip_agy`), so new `agy` models never appear until ↻. The Claude sign-in is
  asked once per process (`claude_sdk.probe_signed_in`). Codex is found through `PATH` when a
  picker is filled, with a hard-coded model list. The Arbiter: "I went to install codex, and TCC
  never learns about it."
- **A refused model looks ready.** The pickers mark only "CLI not installed" (grey, disabled),
  "unconfirmed" (remembered from a previous launch) and, for the reviewer, "clipboard only". A
  reviewer the vendor refuses — `error: Selected model is not supported in the selected location.`
  — looked like every other row, and `get_tcc_state` reported `reachable: true, ready: true` right
  before the call failed in two seconds.
- **The explanation is long.** What went wrong reaches the Arbiter as a paragraph from the agent; a
  person needs to understand it at a glance.

## Decisions (the Arbiter, 2026-09-13)

1. Model catalogues are read on **every** start. On Windows the reading happens **inside the first,
   forced console window**, and the start **waits for it, up to a cap**; then the splash. On macOS
   there is no console and nothing to hide: the reading runs in the background, without waiting.
2. **Two colours.** Plain text = ready. **Red** = everything else, with **one word** for the reason.
3. A refusal stays red **until the next start**. ↻ is an explicit re-check: it re-reads and forgets
   refusals. A successful call clears a refusal; a failed one sets it.
4. The reviewer model is probed with one short `ask` call **at the start of a session, and only if a
   reviewer model is chosen** — a fresh install has none, and nothing turns red for that.
5. One unit holds the answer: `core/availability.py`. Pickers, the reviewer footer and
   `get_tcc_state` read it; nothing else decides "why is this red".
6. Where there is more than one reason, the most serious wins:
   `not installed` > `sign in` > `location` / other refusal > `not checked`.

## Design

### `core/availability.py` — the one source of truth

State for this launch only, in memory, behind a lock (it is written from worker threads and read on
the GUI thread).

- Reasons, in priority order: `NOT_INSTALLED`, `SIGN_IN`, `LOCATION`, `REFUSED`, `NOT_CHECKED`.
- Writers:
  - `begin_reading(harnesses)` — everything not yet read is `NOT_CHECKED`;
  - `finish_reading(harness, installed: bool)` — clears `NOT_CHECKED`, sets `NOT_INSTALLED` if absent;
  - `signed_in(value: bool)` — `SIGN_IN` for the SDK route when false;
  - `refused(model_key, reason, detail)` / `succeeded(model_key)` — per model;
  - `forget_refusals()` — ↻.
- Reader: `status(choice) -> Status(ready: bool, reason: str | None, detail: str)`.
- Text: `word(reason)` for a picker row and `phrase(reason)` for the footer and the agent, from i18n
  in all four languages. `detail` is the long remedy, for tooltips only.
- Recognising a refusal reuses `critic`'s word lists: a location refusal → `LOCATION`; permission,
  key and model refusals → `REFUSED` with their own phrase.

### Startup reading

- **Windows.** The console's single line reads `Autosound TCC: reading models...` (still ASCII, one
  line, ≤ 32 characters). A thread runs `refresh_cli_catalogue(force=True)` and
  `probe_signed_in(force=True)` and writes `availability`. `app.py` waits for it up to
  `STARTUP_MODELS_CAP_S = 8.0`; the console hides after `max(APP_CONSOLE_VISIBLE_S, reading or cap)`.
  At the cap the thread keeps going; what it has not read stays `NOT_CHECKED` (red) and the pickers
  repaint when it finishes.
- **macOS.** The same thread starts at launch; the start does not wait; the pickers repaint when it
  finishes.
- `_skip_agy` stays for the background refreshes it was written for — window activation and closing
  dialogs — and no longer applies to the start.

### Reviewer probe at session start

When a tuning session starts and a reviewer model is chosen, one background call:
`critic.run(task="ask", …)` with a minimal question. Success → `succeeded`; a refusal → `refused`
with the recognised reason; the footer and the pickers refresh. No reviewer chosen → no call. Every
real `call_critic` result writes `succeeded` / `refused` the same way.

### What a person sees

- **Pickers** (`MainWindow._fill_combo`): ready rows unchanged; red rows get the theme's red
  foreground and `· <word>`. `NOT_INSTALLED` stays disabled, as today; other red rows can be chosen
  (e.g. to retry after signing in). Existing notes (free, clipboard only) stay.
- **Reviewer footer**: `<model> · <phrase>` when red, the long remedy in the tooltip.
- **`get_tcc_state.reviewer`**: `ready: false`, `not_ready_because: [<phrase>]` when red.
- **↻**: forced re-read plus `forget_refusals()`.

## Error handling

- A reading thread that raises leaves its harness `NOT_CHECKED` and logs the exception; the start
  never waits past the cap.
- A reviewer with no transport at all keeps today's "clipboard only" note; that is not a refusal.
- The probe's own failure to launch (no script, no Python) is logged and changes nothing on screen.

## Testing

- `availability`: priority order; per-launch memory; success clears a refusal; ↻ forgets refusals;
  thread-safety of concurrent writers and a reader.
- Startup: with an injected slow reader, the wait stops at the cap and the console hides then; with a
  fast reader it hides after `APP_CONSOLE_VISIBLE_S`; macOS path does not wait.
- Pickers: red foreground and word; `NOT_INSTALLED` disabled; other red rows enabled.
- Reviewer footer and `get_tcc_state`: the short phrase, the remedy only in the tooltip.
- Probe: runs at session start only with a reviewer chosen; a location refusal lands as `LOCATION`.
- i18n: every word and phrase exists in all four languages.

## Out of scope

- Probing generator models (a real call per model per session is not asked for).
- A console on macOS.
- Counting quota spent by the probe.
