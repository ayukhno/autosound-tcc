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
   goes first.
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
