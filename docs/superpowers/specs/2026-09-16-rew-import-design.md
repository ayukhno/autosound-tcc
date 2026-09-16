# Importing from REW — design

Date: 2026-09-16 · Status: design approved by the Arbiter in two parts, 2026-09-16 · Sources: tcc
`docs/TODO.md` F-056 (the Arbiter's description), hub #153 (SKL-036) items A–C, `docs/TEST-FINDINGS.md` 22.

## What the Arbiter asked

1. The import window lacks a field chosen from the list of what still has to be captured — the rename
   field, for example.
2. Protective filters at the end of the row are a good idea, but done the way the form that sets filters
   does it — and protective filters only, nothing more.
3. Not everything green before the import, even when the measurements were found: blue for "it is there,
   but has to be loaded explicitly".

## Decisions (the Arbiter, 2026-09-16)

- **New name:** a list of the names the round still waits for, plus free text. "Give names" stays.
- **Protective filters:** one compact cell per row; a click opens a small form with the Protection form's
  own fields.
- **Series `_N`** when the plan does not name one: the highest `_N` among the rounds; no rounds — ask.
  Never derived from the ledger version.
- **Approach:** rework the existing window, not a wizard and not a mapping from the plan side.
- Design part 1 (the window) and part 2 (checklist, series, channel, old rounds) approved as presented.

## Design

### 1. The import window (`ui/tcc/capture_import_dialog.py`)

Columns: take · # · REW title · when · **new name** · **protective**.

**New name** (`_COL_NAME`)
- An editable combo in the cell. Its list is the open round's outstanding names — full REW names like
  `tw-L_1 (sw)` — in the round's order: what `measurement_panel.outstanding_titles()` returns, which now
  counts both `wait` and `found` rows (section 2).
- A name chosen in another row is left out of every other row's list; a row keeps its own choice.
- Free text is accepted — an extra measurement names itself (`r-L_17 (sw) noXO`, hub #153).
- Choosing or typing a name ticks the row (the existing rule). "Give names" stays. The clash check on
  "Take" stays. The rename in REW on "Take" stays.
- No round open: the list is empty and only free text is left.

**Protective** (`_COL_PROT`, replacing `_COL_HP` and `_COL_LP`)
- One read-only cell with a summary: `HP LR24 80 · LP —`, or `—` when the row has no protective filter
  (the curve is read as measured).
- A click, or Enter on the cell, opens a small dialog titled "Protective filters — in the chain while
  this was measured", with OK, Cancel and Clear. Its body is the legs form shared with the Protection
  dialog: for HP and for LP — frequency, type, slope, and the LR24 button.
- The row's value becomes the legs dict the Protection form writes (`{"hp": {"f", "type", "slope"},
  "lp": {…}}`), instead of two frequencies with LR24 implied.
- The form collects and does not validate: a half-filled leg goes to the method's writer as typed, and
  its refusal is what the person reads (the Protection dialog's existing rule).
- `protective()` keeps recording per channel; two rows of one channel with different filters stay a
  reported conflict, not a merge.

**The shared legs form** (`ui/tcc/protective_dialog.py`)
- `_ChannelRow`'s leg widgets, fill and read (`_leg_widgets`, `_fill_from`, `_leg`) move into one
  widget, `ProtectiveLegs`, used by `_ChannelRow` and by the import cell's dialog. One form, two places.

**The Protection button's channel list** (TEST-FINDINGS 22)
- With a round open: the round's channels (unchanged).
- With no round open: output channels only — the view's `physical_outputs` group and `project.json`
  channels on the ledger tier `channels`. Virtual tiers are not offered: a protective filter sits in an
  output's signal path, and a virtual channel is not measured through one.

### 2. The checklist, the series, the channel, old rounds

**Blue: in REW, not taken** (`state/measurement_view.py`, `ui/tcc/measurement_panel.py`, `ui/tcc/theme.py`)
- New status `STATUS_FOUND = "found"`. In `build_session.status_for`, after the skip and verdict checks:
  a capture that is not taken reads `found` when REW holds a title with the same `name_key` (so
  `c_01 (sw)` answers `c_1 (sw)`), and `wait` otherwise. Green stays for taken.
- "Taken" keeps the rule from tcc#39: a name the open round asks for counts only a take recorded in
  that round.
- Legend entry `("found", "legFound")`: "in REW — import it" / «є в REW — завантаж». Dot class
  `tl-found`, coloured `t.info`.
- `outstanding_titles()` counts `found` with `wait`: both are still to be taken.
- Past rounds (`_session_for_round`) are unchanged.

**Series `_N`** (hub #153 A; `ui/tcc/main_window.py`)
- `_capture_version(state) -> Optional[int]`, in this order:
  1. the open round — the first of its titles (expected, then taken) that `naming.parse_name` reads
     with a version;
  2. the active phase's plan steps — each step name split on `+ , ; :`, each piece read by
     `naming.parse_name`, the first with a version wins (replaces the `_CAPTURE_SERIES` regex);
  3. the highest version among all rounds' titles, read the same way;
  4. `None`.
- The ledger version is never used.
- `None` in the checklist: the panel shows "series not known yet — the first capture round sets it"
  instead of a derived grid.
- `None` at import with no round open: before opening a round, the panel asks for the number
  ("Series number — the DSP state these were measured on", an integer from 1). Cancel writes nothing,
  as the panel does today when it has no version.

**The channel of a title** (hub #153 B; `core/capture_import.py`)
- `channel_from_title` reads the parsed record's `code_current`, then `code`. The string split stays
  only for a title the grammar does not read. `L w+m_3 (sw)` no longer reads as `L`, and a renamed
  channel's titles find its protective record.

**Old rounds** (hub #153 C; `state/measurement_view.py`)
- In `build_session`'s rounds loop, a round counts for series N when its `version` (without `v_` and
  leading zeros) equals N, or when any of its titles (expected or taken) reads with version N — the
  way the method's `protective_record_for` finds a round. A round opened as `v_001` with `_49` titles
  counts for 49.

## Error handling

- Nothing new raises into the window. A method module that cannot be loaded leaves the grammar-based
  steps without an answer: the series falls to the next source, and `channel_from_title` falls to the
  string split, as today.
- A refusal from the method's writer (a half-filled leg, a clash) is shown in its own words, as today.

## Testing

Test-first, in the existing files:

- `tests/test_measurement_view.py` — found / wait / done for the live checklist; a past round shows no
  `found`; an old round `v_001` with `_49` titles counts for 49.
- `tests/test_main_window.py` — `_capture_version`: the open round wins over the plan; the plan read by
  the grammar; the highest among rounds; `None` with none of them; a ledger at `v_007` never becomes 7.
- `tests/test_capture_import.py` — `channel_from_title` on a joint title and on a renamed channel, with
  literal expectations taken from one run of the parser at the pinned method.
- `tests/test_capture_import_dialog.py` — the name list is the outstanding names minus those chosen
  elsewhere; free text; choosing ticks the row; the protective cell's summary; the legs dialog
  round-trips; `protective()` per channel with a conflict.
- `tests/test_measurement_panel.py` — the `found` legend entry; `outstanding_titles` counts `found`; the
  series question at import with no round and no version, and Cancel writes nothing.
- `tests/test_protective.py` (where the Protection dialog is tested today) — the legs widget is the same
  in both places; with no round open, virtual tiers are not offered.

## Out of scope

Waits for the skill's wave release (`test-fixes-2026-09-14`) and a pin bump from `v3.0.52`:

- hub #153 D — showing a clarification (`params`) as what an extra measurement is for; where `(imp)`
  captures belong.
- hub #153 E — showing `explain_name`'s reason for a title outside the grammar.
- hub #153 F — `curve_groups.title_for` building a title by hand when `generate_name` refuses.

Also not here: tcc#21 (capture quality at selection), and anything in how rounds are stored — they are
still written through the method's `process.py`.
