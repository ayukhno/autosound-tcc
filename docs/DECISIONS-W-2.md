# W-2 · v0.1.43 — decisions, for the Arbiter to read and overturn

Every decision taken for this wave, in the order taken. **Arbiter** = he said it; **session** = the
session chose while he was away (2026-09-22 night, his word: «роби що можна без мене, всі прийняті
рішення нотуй і мені покажеш завтра»). A session decision is a default, not a verdict: each says
what it would take to reverse it.

Tomorrow's order (the Arbiter, 2026-09-22): read these decisions → the Layout prototype → sync with
the skill → finish the development. **Testing is at the end of all development**, not per package.

## Taken by the Arbiter, 2026-09-22

| # | decision | where |
|---|---|---|
| A1 | W-1 is closed on both products; the next wave is W-2 | milestones |
| A2 | Include as much as possible; what stays out gets a reason and is deferred; if the skill has a ticket for it, we take it | `PLAN-W-2.md` |
| A3 | Per-project version numbering has no ticket → one was filed (hub `#195`) | `PLAN-W-2.md` |
| A4 | The intake form goes FIRST, designed and built before the rest | spec, plan |
| A5 | The form REPLACES the conversational intake in "New project" | spec |
| A6 | After the form, TCC OFFERS the session when the gate is green; the start is his click | spec |
| A7 | Execute the form's plan in this session, not with subagents | — |
| A8 | `F-069` Layout is in W-2, its look discussed with a prototype before code | `PLAN-W-2.md` |
| A9 | Layout (control mode): a button toggles «Активний TCC / Режим контролю»; TCC takes half the screen | below |
| A10 | Control mode: the top window is full width with tabs — «Моніторинг» (what remains of the dialog, as info), «Таблиця-V» (virtual channels), «Таблиця-О» (outputs), then EQ / levels / delays / phases as now; below it the left and right panels side by side, equal, with a movable border between them and between them and the top | below |
| A11 | Control mode: TCC's own confirmation requests — the terminal auto-confirms by default; when one does arise, a strip above the top window, visible from any tab | below |
| A12 | Control mode: TCC on the RIGHT half, TCC opens the terminal on the LEFT half | below |
| A13 | «Моніторинг» is a read-only feed plus the bus buttons («Готово», «Прослухати»); typing is in the terminal | below |
| A14 | The Layout is shown as a throwaway prototype inside TCC, on its own branch, built LAST | below |
| A15 | Testing is postponed to the end of all development | — |

## Taken by the session (night of 2026-09-22) — defaults, to be read

Each row: what was chosen, why, and what reversing it costs.

| # | decision | why | to reverse |
|---|---|---|---|
| S1 | **The vocabulary pass** changes 70 strings in four languages: a series `_N` is never called a DSP configuration or state (3 tooltips said so); «знімок (леджера)» becomes «конфігурація (v_NNN)»; «варіант» is kept for a Phase-1 proposal only («тут немає варіантів» → «готових відповідей»); the Ukrainian/Polish/German «леджер» becomes «реєстр конфігурацій» (plain words). English keeps «ledger» — it is the method's own word and the prompts to the model use it | the Arbiter's vocabulary of 2026-09-20; memory «`_N` — номер серії, не стан DSP» | one commit; the old strings are in `git show HEAD~1:src/autosound_tcc/ui/tcc/i18n.py` |
| S2 | **F-070 header**: the version moves from the far right to BESIDE the preset (`ПРЕСЕТ [FULL] ● v_007`), with a dot — yellow while any channel of it is only `proposed`, green once all of it is `applied`/`measured` (what `attest` does). The processor's name and the per-status counts are on its hover. The left column's «DSP» section keeps the processor's name: it is that section's subject | the header has no processor name to replace — the version was already there, grey, far right; beside the preset it reads as «this configuration stands in this slot» | move the label back (one widget order) |
| S3 | **The DSP preset NUMBER** is shown only when the snapshot carries `slot_label`; nothing else in the method records a slot number (`project.json` `presets` = names). Asked for on hub `#195`, which is about exactly «the preset as the slot a version is fixed in» | inventing a number would be a fact nobody wrote | — |
| S4 | **Finding 33, the set picker**: one list (not two pickers); every entry names BOTH its series and its round («серія 1 · cap_006 ●»), and a separator sits between what is taken now and the past rounds. The cause of the vanishing: an open round's id replaced the series in the live entry | the option recommended at the review, unanswered; the smallest change that removes both the confusion and the vanishing | two pickers remain possible; the label is one function (`_picker_label`) |
| S5 | **Finding 29, the UNUSABLE banner**: one line «Непридатних замірів: 16 — <the first, in the checker's words>» + «показати всі» (the full list in a window) + ✕. A list closed by hand does not return until it changes. The status strip gained a general ✕ for that | the option recommended at the review, unanswered | the strip's ✕ is opt-in per message; the old behaviour is one `notify` call |
| S6 | **Finding 28, the REW import form**: New name opens filled for every row matched to a name the round waits for, in the ROUND's spelling — so `sw_01 (sw)` matched to `sw_1 (sw)` becomes a proposed rename (the skill's `#47` made the one-digit form canonical: a rename, never a re-measurement). Unmatched rows stay empty. Title, date and name columns are draggable; «Вибрати все / Зняти вибір» act on the rows on screen | the Arbiter's finding; the name source is the match the form already makes, not a second guess | clearing the prefill is one line; a prefilled rename is only sent for ticked rows on Apply |
| S7 | **Finding 30**: (1) the protective mark was a 10 px `⌁` glyph at the row's end — rendered, but invisible (screenshot in the commit's evidence); it is now a small chip with the short form «HP100», «HP1k · LP3.5k», full wording on hover; (2) a capture the check does not apply to (an RTA) carries no explanation on its row; (3) a name that already says its method (`(sw)`/`(rta)`) is never given a second one | the three things the Arbiter named | the chip is one stylesheet rule and one label text |
| S8 | **Finding 31, «У фокусі зараз»**: «Захист» moved into the picker's row (its own row is gone); the picker sizes to its content; the legend is one word per status on one line, the full wording on hover; the status message sits ABOVE the row, in blue. **«Готово»** sits in the card header beside the REW mark, disabled until the open round has taken something; it pushes a `capture_ready` signal (round + taken titles) and gives an idle in-app session the turn — a terminal session reads the same signal with `get_pending_signals` (so it already works for the Layout's control mode) | the Arbiter's four points; the signal path is the one the channel toggle already uses | each is a few lines; the signal kind is new (`signal_bus.CAPTURE_READY`) and the method reads it generically |
| S9 | **Finding 34, capture order**: several rows can be selected (Shift range, Cmd/Ctrl single) and move as ONE block that closes up — by drag or by ⤒ ↑ ↓ ⤓. «Зберегти порядок» really writes the order per preset and method (the hint claimed this since 2026-07-27, and nothing wrote it); OK no longer implies saving. «Порядок як у RTA/SW» copies the other method's order, matched by channel | the Arbiter's three asks; found on the way that saving was a promise with no code behind it | save-on-OK is one line if wanted |
| S10 | **Finding 1, the «Команди агента» dialog**: rewritten question-first in four languages — «Коли сесія тюнінгу має питати вас перед командою? …» — one sentence of context, the caveat short. The Arbiter asked for this to be worked with the ADVISOR; that pass is NOT done: the reviewer CLI refuses a nested call from inside an agent session (the same wall as `#45` / skill `#54`) | the text is a draft for the Advisor's pass, not a replacement for it | the old text is one `git show` away |
| S11 | **F-076**: the four «правка параметрів» system lines were in the model's voice and the closing two were a hard-coded demo («delay was 9.5 ms … fixed»); they now say what TCC did — a signal to the session — and, with no bus, that nothing was sent | a window stating a fix that never happened is the class the wave exists to remove | — |
