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
  changes it and REW's **filters** hide part of the list in its UI. Capture time is what "по черзі"
  means, and it is the one order neither of those touches.

**Where the imported set lives:** `.tcc/imported-measurements.json` in the project —
`uuid -> {title at import, round id, when}`. Per project, because "already imported" is a fact
about this car's work, not about this machine.

## The import dialog

Opened by ⤓ (which stops folding anything in by itself).

| column | what it is |
|---|---|
| ☑ | take this one. Pre-ticked for every row the default window shows |
| REW title | what REW calls it now |
| when | `date`, so the sequence is visible and arguable |
| new name | empty = leave the title alone. Filled by hand or by **"Give names"** |
| protection | the answer for that channel: `—` / `OFF` / `HP 80 LR24`, edited in place |

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
3. **The protection column**, and the card's button turned into review-and-correct.
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
