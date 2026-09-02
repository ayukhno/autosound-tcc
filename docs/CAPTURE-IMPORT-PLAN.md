# Importing captures: a dialog instead of folding in everything REW holds

What this is: the design note for the change the user raised on 2026-09-02, after a live Windows
run. Written before the code, like `CURVE-ANALYSIS-PLAN.md`, because the identity model underneath
it (what makes two REW measurements "the same one") decides whether the feature can tell the truth
at all.

## Why

Today the ⤓ button reads **every title REW holds** and folds all of it into the task card. On the
run that produced this note: **102 titles, 16 matched, 86 appended** as "additional" rows — a card
1864 px tall, most of it somebody else's library, inside a card titled "IN FOCUS NOW". The user's
own words: a REW file can hold very many measurements, and reading them all every time is a
collapse.

And the card is not a summary anybody glances at. Asked directly whether they watch the card or REW
while capturing, the user answered **"дивлюсь в картку"** — so it is the working surface, and noise
in it is expensive.

## What was decided (user, 2026-09-02)

| | decision |
|---|---|
| **Apply** | rename in REW **+** mark the checklist **+** write the protective record. The curve DATA stays in REW; the curve window pulls it on demand, as it does now |
| **How much is listed** | as many as the round is still waiting for, extended by **+10** at a time; a checkbox **"unprocessed only"**, on by default, hides what this project has already imported |
| **Protection** | leaves the card, becomes a **column** in the import table — and stays correctable afterwards |
| **Listening** | leaves the card for the **dialog composer row**, beside the attach-image button, and appears only in the phase where listening happens (phase 4) |
| **Naming** | the rename column is filled from a row downwards by a **"Give names"** action: pick the set and the order, apply |

## The identity model, because everything rests on it

`GET /measurements` returns `{ordinal: {title, uuid, date, …}}`.

- **The ordinal is not identity.** REW reshuffles it on a sort, a delete, or a new sweep, and the
  method's own hygiene note is explicit: never cache an index (`rew-api-quirks.md`).
- **The `uuid` is.** It survives renames and reshuffles, which is exactly what "do not show me what
  I already imported" needs: a measurement we imported and then renamed by hand in REW must stay
  hidden, and a title match cannot promise that.
- **The `date` is the order.** Not REW's list order: the user warns that REW's own **sorting**
  changes it and REW's **filters** hide part of the list. Capture time is what "по черзі" means.
  But `date` is a DISPLAY string, not ISO — measured on a live instance: `2026-Jun-22 12:10:35`,
  the month as a word, i.e. formatted by REW's (Java) locale. On a Ukrainian Windows it may not be
  `Jun`. So: parse tolerantly, and where the parse fails, keep REW's own order and say on screen
  that the order is REW's rather than capture time. Never sort by a string compare of that field.

**Where the imported set lives:** `.tcc/imported-measurements.json` in the project —
`uuid -> {title at import, round id, when}`. Per project, because "already imported" is a fact
about this car's work, not about this machine.

### REW's UI filter reaches the API — measured, 2026-09-02

This was the open risk of the first draft, and the answer is the bad one. With **"impedance and RTA
only"** switched on in REW's own list, `GET /measurements` returned **17 measurements, every one of
them `(imp)` or `(rta)`**. The API does not serve what REW HOLDS; it serves what REW is currently
SHOWING.

Two consequences, and the second is the dangerous one.

1. **"Everything REW holds" is not available to us.** The dialog must not claim it. One line under
   the list: what is shown is what REW is showing now.
2. **A filter breaks "по черзі" exactly where it matters.** The ordinals came back renumbered
   `1..17` with **no gaps**, so a hidden measurement leaves no trace to detect. With a filter on,
   two adjacent rows in our list need not be adjacent captures — and "Give names" fills downwards
   in sequence, so names would land on the wrong curves. That is precisely the failure the method's
   identity hygiene was written against (`m-R` data pulled under the `m-L` label).

**Confirmed a second time, same session:** the filter was switched to sweeps only and the same
call returned **85 measurements, every one `(sw)`** — a set that does not overlap the first answer
at all. Same REW, same file, two filters, two different truths.

That second answer carried two facts the first one could not show, and both change the design:

- **REW's list order is not capture order.** Rows 74–85 were captured at 13:25–13:28 and are served
  AFTER rows 11–73, captured at 20:11–20:34. So "the last ones in the list" and "the last ones
  captured" are different sets, and sorting by `date` is not a refinement — it is the only way to
  get the sequence the tuner means.
- **A re-take breaks the name order, and only the date shows it.** `tw-L p8_49 (sw)` is timed
  20:17:29 and `tw-L p9_49 (sw)` 20:17:02 — p8 was taken again after p9. Read by name, that pair
  is in order; read by time, it is not. This is the concrete case the date column beside the
  proposed name is for.

**Unfiltered, the same call returns 102** — 7 `(imp)` + 10 `(rta)` + 85 `(sw)`, and 102 is exactly
the number the Windows run reported. The two filtered answers partition the whole set, so the file
is the same one that produced this note.

That third answer settles what an ordinal IS: **`sw_01 (sw)` is number 1 under the sweep filter and
number 18 with no filter** — one measurement, one uuid, two positions. The ordinal is the index of
a VIEW.

And a fourth, on purpose: the user swapped rows 101 and 102 **by hand** in REW. The call reflects
it exactly — the two exchanged ordinals, every uuid, title and date unchanged. So the position
moves for three different reasons (a filter, a sort, a hand) and the uuid for none of them.

The swap also left the tail out of time order — 101 is `13:28:01`, 102 is `13:27:20` — which is the
same shape as the honest case the user named: **a re-take of something that did not come out** ends
up out of sequence. Their instruction on it is the design rule here: **worth the tuner's attention,
not a stopper.** "Give names" fills downwards and MARKS the rows where capture time disagrees with
the fill order; it does not refuse, and it does not renumber anything on its own.

What the dialog does about the filter, since it cannot see its state:

- **the date column carries its weight here** — it is the one visible sign that the sequence has a
  hole in it, so it sits beside the proposed name and the tuner reads them together before Apply;
- **a count the tuner can compare**: this project has N measurements recorded as imported; if some
  of them are not in REW's current answer, say so — "REW is showing 17; 6 of this project's
  imported measurements are not among them" is either a deletion or a filter, and both are worth
  knowing before renaming anything;
- **nothing is renamed without the tuner seeing the whole table**, which is the design anyway:
  names are proposals in a column until Apply.

## The import dialog

Opened by ⤓ (which stops folding anything in by itself).

| column | what it is |
|---|---|
| ☑ | take this one. Pre-ticked for every row the default window shows |
| REW title | what REW calls it now |
| when | `date`, so the sequence is visible and arguable |
| new name | empty = leave the title alone. Filled by hand or by **"Give names"** |
| protection | what to take out of this curve before it is analysed: empty (take nothing out) or a filter, `HP 80 LR24`, edited in place |

**Controls:** the "unprocessed only" checkbox (on), **+10** (another portion of older ones),
**"Give names"**, **Apply**.

**"Give names"** is today's ⇅ flow moved into the dialog and pointed at a starting row: select the
first capture, press it, choose the **set** (the round's capture method — SOLO (SW), SOLO (RTA), …)
and the **order** (the drag-to-reorder list that already exists as `ChannelOrderDialog`), apply —
the names fill downwards from the selected row, in sequence. That is exactly the case the user
described, and the sequence is honest here for the reason they gave: the new captures that need
names always arrive in capture order.

**Apply**, per ticked row: rename in REW where the new name differs from the title, mark the
matching checklist row captured, write the protective record for that row's channel, record the
uuid as imported. A row that fails says so **on its own line** — a rename refused by REW must not
take the other nineteen down with it, and must not be reported as one sentence about "the import".

**The protective value is per CHANNEL, not per row.** The same channel captured with two methods is
two rows and one chain: the cell mirrors across the rows of that channel, and Apply writes it once.

## What the protective record actually is: an instruction, not a description

Corrected by the user on 2026-09-02, and the correction goes deeper than the wording. The first
draft of this note treated the record as a description of the measuring chain, and proposed that an
empty cell be written as `OFF` — "swept with nothing in the chain".

**That is false, and the reason is the car.** There is nearly always something in the chain: the
DSP's own working crossovers, which are supposed to be there and which must NOT be taken out of the
curve. Writing `OFF` would claim the opposite.

The record is not about the chain. It is an instruction to the analysis:

| the cell | what it means |
|---|---|
| empty | **process the curve as measured** — take nothing out |
| a filter | **take this out first**, then process |

That is the whole model, and it is simpler than the three states it replaces because it stops
asking the tuner a question about the world and asks them one about the work.

### What it costs, said once

Under the old model a channel with no record was refused by `de_embed`: a correction over an
unknown chain produces data that looks corrected, so silence was treated as "nobody answered" and
blocked. Under the new one, silence is a valid instruction — and the case that refusal caught, a
protective filter that was in the chain and never written down, now passes through and its phase is
read as the driver's own.

Two things make that acceptable rather than a loss:

- the column now stands in the import dialog, on **every row being imported**, so the question is
  asked at the moment the answer is known, instead of being remembered later;
- the analysis can still SAY what it assumed — "no protective record for this channel; read as
  measured" — which is the honest half of the old refusal without the blocking half.

### The method already says this — the stricter reading is ours

Checked before writing a ticket, and the ticket is not needed. `rew_tool/protective.py` already
carries exactly the model above, in `should_de_embed(record, channel, baseline=)`:

* `("no", …)` — **the default**, in its own words: *"a working capture: it measured the system as
  configured, so whatever filters were in it belong there. This is the DEFAULT and it is an answer,
  not a shrug."*
* `("yes", legs)` — marked raw, and here is what to take out.
* `("check", …)` — it looks raw and is not marked.

`de_embed(None)` does raise, but not because silence is unknowable: its own message says the caller
should have asked `should_de_embed` first, and that under the working-by-default rule there is
nothing to take out.

**The reading that treats silence as an unanswered question is TCC's own** — the docstring of
`core/protective.py` and the `protWhy` sentence in the UI ("leaving a channel unrecorded is not the
same thing, and nothing will be corrected for it"). Both are ours to fix, and fixing them is cheap
in the most useful way: **nothing consumes the correction yet.** `de_embed` and `default_corrected`
have no caller in any window today; the dialog only reads existing legs. So the semantics can be
put right before there is a single curve drawn from them.

### What we keep from the method that this design almost threw away

`should_de_embed`'s third answer, `"check"`, is worth more here than anywhere: it fires when a
**baseline** capture — one taken before any crossover was designed — carries no protective record.
That is the single case where a forgotten flag is recoverable, because filters in force during a
baseline sweep are protection almost by definition.

And baseline is exactly where the tuner is when this dialog is most used. So: on a baseline round,
a row left empty is **marked** in the table — "baseline, not marked; was protection in force?" —
in the same shape as the order warning above. It asks; it does not block, and it does not fill
anything in on the tuner's behalf.

## The way back for a protective record

The user asked for one, and the case is real: a channel captured yesterday, an error noticed today.
The card's **"Protection"** button therefore does not disappear — it stops being the way to ENTER
the record and becomes the way to review and correct what is already written. (Which also gives the
answer to F-041's own open half: what it opens is a review of the round, and it needs the channel
list only for the rows it already has.)

## Steps, each one shippable on its own

1. **The imported store and the dialog's list.** ⤓ opens a dialog that lists REW's measurements by
   date with the "unprocessed only" filter and +10; Apply marks the checklist and records the
   uuids. No renaming, no protection yet. **This is the step that stops the card growing**, so it
   goes first. **Done 2026-09-02.** Two things came out different from this note, and both are in
   the code's own comments: the pre-tick is the round's own count and NOT the whole window (the
   window is deliberately wider, and the extra rows are context — ticking them would take
   measurements into a round nobody captured them for); and `known_titles()` is the UNION of the
   store and what REW showed this session rather than the store alone, so an existing project does
   not read as uncaptured on the first launch after the update. What the tick decides is what this
   project has taken IN; what REW holds stays a separate fact, and the plan audit and the curve
   window's title list both ask for that one.
2. **The rename column and "Give names"**, moving the ⇅ button's flow into the dialog.
3. **The protection column**, and the card's button turned into review-and-correct. Nothing waits
   on the method: the semantics are already the method's, and what changes is TCC's own reading of
   them (`core/protective.py`'s docstring and the `protWhy` text) plus the two marks above.
4. **Listening to the composer row**, shown only in phase 4.

## Risks and what is not yet known

- **Do REW's UI filters hide measurements from the API too?** Unverified, and it decides whether
  the dialog can ever be trusted as "everything REW holds". Check on the next live run: the count
  in REW's own list against the count in the dialog, with a filter on in REW.
- **Duplicate titles.** `rew_api.duplicate_titles` exists because the method's identity model rests
  on titles being unique. The dialog must refuse to rename a measurement into a title REW already
  holds, before it sends anything.
- **`rename_measurement` is verified against a live REW** (its own docstring says so, 2026-07-12),
  but twenty renames in one Apply is not the same as one rename. Apply them one at a time and stop
  on the first refusal rather than firing them all and reporting afterwards.
- **A round with no expected rows** (a phase that captures nothing) still has an import dialog:
  there is nothing to tick against, and the honest answer is the list plus a line saying this phase
  expects no captures.

## Not in this change

- **Pulling the curve data into the project.** Offered and declined for now: the data stays in REW
  and the curve window fetches it on demand.
- **The shape of the checklist grid itself** (a row per channel with a dot per method, instead of a
  column per method). Named on 2026-09-02 as a separate question and left open — this note is about
  what gets INTO the card, not how the card is laid out.

---

# Implementation plan

Written 2026-09-02 against `tcc@076e555`, after reading the seams the change goes through. The
design above says WHAT; this says WHERE in the code, WHAT gets retired, and HOW each step proves
itself. Each step lands as its own commit set with the full suite green, and step 1 is a patch on
its own.

## Four seams, and what happens at each

| seam | today | after |
|---|---|---|
| **"captured" in the checklist** | `measurement_view.build_session(phase, version, titles)` — `titles` is `panel.known_titles()`, i.e. what REW showed THIS SESSION | `known_titles()` = titles recorded in the imported store **∪** what REW showed. The checklist stays true with REW closed, or filtered |
| **⤓ Read** | `_on_read_done` folds every REW title into the grid; unmatched ones become "additional" rows | ⤓ opens the import dialog. Nothing is folded in without a tick |
| **⇅ Give names** | `_on_scan_done`: "the `expected` highest ordinals are the newest batch" — the heuristic the measurements above disprove | the dialog's rows, ordered by `date`, resolved to ordinals by `uuid` **at rename time** |
| **rename itself** | `_RewRenameWorker`: pairs `(ordinal, title)`, one call each, stops at the first refusal, reports how far it got | kept as is — it already does exactly what the design asks. The pairs are built later and better |

## Modules

- **`core/capture_import.py` — new, no Qt.** The imported store (`.tcc/imported-measurements.json`,
  schema `{"schema": 1, "measurements": {uuid: {title, round, when, date}}}`), the tolerant `date`
  parser, the window ("as many as are waiting, +10 backwards"), the "unprocessed only" filter, the
  uuid→ordinal resolve against a fresh `measurements()` answer, and the two sequence checks
  (re-take out of order; imported-but-not-shown count). Everything the dialog decides lives here and
  is tested without a window.
- **`ui/tcc/capture_import_dialog.py` — new.** The table and its four controls. Owns no logic that
  `capture_import` could own.
- **`ui/tcc/protective_legs.py` — new, extracted.** The leg editor now inside
  `protective_dialog._ChannelRow` (frequency, type, slope ×2) plus the `LR24` button, so the
  import table and the review dialog show the same widget.
- **Changed:** `measurement_panel.py` (⤓ and ⇅ rewired, "additional" rows and the fold retired,
  `known_titles` union), `main_window.py` (wiring; listening visibility), `dialog_panel.py`
  (listening button), `protective_dialog.py` (review mode), `core/protective.py` (docstring;
  `should_de_embed` wrapper), `i18n.py` (strings ×4).

## Step 1 — the store and the list (the patch that stops the card growing)

**Build:** `capture_import` (store, parser, window, filter); the dialog with columns ☑ · REW title ·
when, the checkbox, `+10`, Apply; ⤓ opens it. Apply records the ticked uuids and marks the
checklist through the `known_titles` union → `titlesChanged`. The footer line under the list:
"showing what REW is showing now" + the imported-but-not-shown count when it is non-zero.

**Retire:** `_add_dynamic_row`, `_additional_titles`, the `measReadOk` "matched/extra" line, and the
fold in `_on_read_done`. `_RewReadWorker` stays as the fetcher the dialog uses.

**Tests — new:** store round-trip and per-project scope; the parser on `2026-Jun-22 12:10:35`, on a
non-English month (falls back, keeps REW order, says so), on garbage; the window at 3 waiting / 0
waiting / fewer measurements than N; the filter hiding imported uuids and the checkbox showing
them again; Apply → store written, `titlesChanged` emitted, checklist row turns done **with REW
returning nothing** (the closed-REW case, which is the point of the union).
**Tests — retired:** the seven `test_read_done_*`, `test_second_read_does_not_duplicate_additional_rows`,
`test_read_on_a_phase_with_no_columns_does_not_blow_up` (its concern moves into the dialog: a round
with no expected rows still lists, and says the phase expects nothing).

**Proves itself when:** on the 102-measurement file the card holds only the round's rows, and the
dialog opens on ≤ N rows where N is what the round is waiting for.

## Step 2 — names

**Build:** the *new name* column; **"Give names"** = `ChannelOrderDialog` opened from the selected
row, filling downwards; the re-take mark (date order ≠ fill order — a badge on the row, never a
block, per the user's rule); the duplicate guard (proposed titles checked against REW's current
titles AND against each other before anything is sent); Apply renames through `_RewRenameWorker`
with pairs resolved **inside the worker** from a fresh `measurements()` — the shortest possible
window between resolve and rename. A refused rename is written on its row; the rows before it stay
done, the rows after it stay pending.

**Retire:** the ⇅ button on the card, `_scan_and_match`, `_on_scan_done`'s ordinal heuristic,
`_pending_order`. The saved-order settings key (`ui/capture_order/<preset>/<method>`) is kept and
still seeds the order dialog.

**Tests — new:** fill-downwards from row k; the mark on an out-of-order date; refuse a duplicate
target (both kinds); **the reshuffle test** — a fake bridge whose ordinals change between the list
call and the rename call, and the right measurement is still renamed because the pair was resolved
by uuid at rename time; a refusal mid-batch leaves exactly the rows before it renamed.
**Tests — retired:** `test_scan_match_*` (2), `test_rename_done_and_failed_update_status_label`.

## Step 3 — protection

**Build:** `protective_legs` extracted, with `LR24`; the column in the table (per channel, mirrored
across that channel's rows); Apply writes `process_writer.set_protective` **only for filled rows** —
an empty cell writes nothing, by the corrected model; the baseline mark ("baseline, not marked —
was protection in force?") on empty rows when the round is a baseline one; the card's button opens
`protective_dialog` in **review mode** over the channels the round has (`capture.expected` parsed to
codes) — which also closes F-041's open half. `core/protective.py`: docstring rewritten to the
method's own model, `should_de_embed` wrapped for the curve window to use later; `protWhy` rewritten
in four languages.

**Tests:** `LR24` fills type and slope; mirroring across two rows of one channel; empty writes
nothing and `record_for` shows no entry; the baseline mark appears on a phase-0 round and not on a
later one; review mode lists the round's channels and nothing else; the four `protWhy` strings no
longer say "nothing will be corrected for it".

## Step 4 — listening

**Build:** `DialogPanel.set_listening_available(bool)` + a button beside the attach button, hidden
by default; `main_window._refresh_capture_task` flips it on `active_phase == "4"` and wires it to
`_open_listening`; the card's button and `listeningRequested` go.

**Tests:** hidden in phases −1..3, shown in 4; the click opens the same dialog `_open_listening`
did.

## Order, and what ships when

1 → 2 → 3 → 4. Step 1 alone is a release-worthy patch (it is the fix for the 1864-px card); 2 and 3
ship together (both are columns of the same table); 4 is small and rides with whichever comes next.
Each step: its own commits, full suite green, TODO/plan updated in the same commit set.

## Still open until a machine answers

- **`date` on a Ukrainian Windows.** The parser logs the raw string when it cannot read it, so the
  first failure on that machine tells us the format instead of just falling back.
- **What `baseline` means to `should_de_embed`.** Phase 0 → `True` is the obvious source; whether a
  later phase's `_N` re-baseline should count is the method's call. Step 3 passes phase-0 only and
  says so in the mark's text.
- **The REW filter.** Known and unfixable from here; the dialog says what it shows and counts what
  it cannot see.
