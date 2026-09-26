# Plan · W-3 · v0.1.44 — what this wave builds, what it leaves, and in which order

Written 2026-09-26, when the Arbiter closed the collection («збір завершено»). This is a PROPOSAL:
a task is built only after his explicit OK on it, recorded as the label `ok` on its issue
(`WAVES.md` §1 step 2). Eight tasks had their OK during the collection and are built on
`wave-0.1.44`; the rest below waits for his word, task by task.

The name was read, not agreed: milestone `W-3 · v0.1.44` (#3) here, `W-3 · v3.0.62` in the skill.
The skill's milestone holds 24 issues, so this wave moves `vendor/autosound-tuning-skill` (today
`v3.0.60`): one wave on two products, the skill released first (`WAVES.md` §1 step 4).

## Where the work comes from

Everything open in five places was read, 2026-09-26:

| source | open | on the milestone |
|---|---|---|
| `docs/TEST-FINDINGS.md` | 42–74, the W-3 pool: 33 findings | 9 built (47, 65–69, 71, 73, 74); 22 as 12 tasks (#56–#67); 61 and 72 belong to other roles |
| older findings (1–41) | none left for TCC | W-2 closed 17, 20–23, 25, 28–34, 37, 38, 41; 18 closed by the Arbiter 2026-09-24 |
| `docs/TODO.md` | F-065, F-066, F-071 (back at this review); F-068, F-023, F-057 (deferred); F-044 (→ finding 44) | #69 for the first three |
| the bus, `to:tcc` | #202 SKL-053, #209 PAS-009, #211 PAS-011 (in work); #83 (deferred) | the three close with this wave's tag |
| `ayukhno/autosound-tcc` issues | #50, #21 | #50 (#21 stays deferred) |

Plus the skill's W-3: its capture-round and reviewer issues have TCC halves (#68 here).

## Built during the collection, on the Arbiter's OK

| issue | what | findings |
|---|---|---|
| #47, #48, #49 | the GUI guide, the target-curve guide, Help → User guide | — (hub #202) |
| #51 | control mode's tables: one navigation, EQ and back, status dots, compare across configurations | 47, 65, 66 |
| #52 | the band card: DSP band number, type colour, bypass, field order | 67–69 (hub #209, #211) |
| #53 | the EQ view's tier pickers, band counts, no empty tabs | 71 |
| #54 | the compared version's EQ row, new / changed / removed marks | 73 |
| #55 | the tree's band changes as dots with counts | 74 |

## Proposed for W-3

### 1 · The loop: the session and the critic — first, because a tune stops without them

- **#56** omp: a session does not start (TypeError on `language`), and a switch away from it saves
  state for nothing (53 high, 54).
- **#57** the critic through omp sends `google-antigravity/…`, which neither route takes (58 high).
  With the skill's #85 (the reviewer ladder).
- **#58** the critic picker's own grey / green / red, the pick reaching the project params at once,
  no all-red list after one cut call (55, 59, 62).
- **#59** the critic's reply in its own bubble; the Generator's proposal not labelled
  «SYSTEM · LEDGER» (63). Needs an API route through `call_critic`, agreed with the skill (#68, #85).

### 2 · The capture panel — with the skill's capture rounds

- **#60** «In focus now» reads the open round, not the phase plan; a next round is not shown done;
  rows stay compact (64 high, 57, 49). The method's side is skill #78, #79, #80, #83 (hub #205):
  built against the skill's W-3 branch, pinned to its tag before ours.

### 3 · Small defects

- **#61** the curve window says REW is offline instead of waiting (56).
- **#63** quitting while REW is pinged destroys a running worker (46; finding 35's class).
- **#64** the SDK model list is behind Anthropic's and says nothing about its age (48).
- **#65** the key screen's two languages, the theme button's word, the faint grey, the dark
  theme's search box (42, 50, 51, 52).
- **#50** a state file's name and its `version` field disagree, and nothing says so.

### 4 · A settings menu

- **#67** «Налаштування» for TCC's technical settings, the band card's field order first (70).

### 5 · Windows — one session on the VM, with the update path

- **#62** two terminals before the splash, windows flashing on entering control mode, a pin from
  the desktop shortcut (43, 44, 45).
- **#66** «порівняти з» shows «…» on Windows (60) — checked first: #52's wider list may have fixed it.

### 6 · The shared wave

- **#68** the vendor pin to the skill's W-3 tag, and TCC's halves of its issues as they land
  (the round's grouping → #60; the reviewer ladder → #57, #59; the target-curve page's two numbers,
  skill #67 / hub #203 — the guide drops its Δ dB sentence once the page says it).

## Proposed to leave out, and why

| item | why |
|---|---|
| **#69** F-065, F-066 | Machinery with no product effect; both need CI measurements. Deferred again. |
| **#69** F-071 | Not seen in six full `-n 4` runs on 2026-09-26 (2347–2357 passed): proposed closed as not reproduced. |
| F-068 the drivers' Fs checkbox | The method's flag does not exist (hub #185); it is not on the skill's W-3. |
| F-023, F-057, hub #83, tcc#21 | Already deferred; not touched. |

## Other roles

| finding | whose | where it stands |
|---|---|---|
| 61 the agy stream cut off, the ladder steps down | the skill's | hub #204 TCC-030 → skill #68, on its W-3 |
| 64, the method's half | the skill's | hub #205 TCC-031 → skill #83, on its W-3 |
| 72 other presets' ledgers carry no band `i` | the car session's | hub #212 TCC-032, sent 2026-09-26 |

## Order

1. **The loop** (1) — the session and the critic, tested together.
2. **The capture panel** (2), against the skill's W-3 branch.
3. **Small** (3) and **settings** (4) — no order inside.
4. **Windows** (5) — the VM session, with the update path walked.
5. **The shared wave** (6) — pinned to the skill's PUBLISHED tag, then ours.

## Exit criteria

`WAVES.md` §3.1: a green PR run, the full serial run on `main`, `make ship REAL=1` for `v0.1.44`
pinned to the skill's published W-3 tag (skill first), the installer walked on macOS and the update
path on the Windows VM. The tag closes hub #202, #209 and #211.

## The review, 2026-09-26

The Arbiter took the plan as proposed («з усім згоден. го»): `ok` on #50 and #56–#68; #69 off the
milestone (F-065, F-066 deferred again; F-071 closed as not reproduced); finding 72 sent to the car
session as hub #212.
