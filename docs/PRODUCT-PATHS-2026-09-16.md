# Product paths — decisions of 2026-09-16

A grilling session between the Arbiter and the tcc role on how the product develops: the AI
embedded in the GUI, weighed against the alternatives. Facts were checked in the trees; every
decision below is the Arbiter's. Nothing here is started — this is the record the next steps are
cut from.

## Facts that shaped the decisions

- **"Terminal beside panels" already exists.** `core/terminal_launcher.py` (front-end B) opens the
  user's own terminal on their own agent CLI in the project folder; TCC starts no agent and holds no
  credentials; the two meet only at the MCP server, which the CLI finds through the `.mcp.json` TCC
  writes. Provider-agnostic: `claude`, `gemini`, `codex`. Wired into the new-project dialog.
- **The embedded AI is the SDK route:** `core/agent_session.py`, `claude_sdk.py`,
  `tuning_session.py`, `mcp_server.py`. The login, status-strip, splash and permission-gate issues
  live on this route.
- **MCP order is fixed:** streamable-HTTP on loopback; TCC is up first and the agent dials in
  (`mcp_server.py`). Terminal-first would need a stable port and reconnection — unverified.
- **The main window** is PySide6, `resize(1280, 820)` with two `QSplitter`s, no docks, no geometry
  persistence. A compact companion window is standard `QMainWindow` + `QDockWidget` + `QSettings`;
  the terminal window belongs to the OS, not to us.
- **The method's weight since v2.8.3 (2026-08-22):** `SKILL.md` 1 499 → 3 253 words; 23 new files
  under `references/` (virtual-first, resonalyze, helix all-pass, capabilities, estimator-scope,
  project-schema), loaded on demand. Most of the raw growth is `CHANGELOG`, `FAQ` in four languages
  and `CONTRIBUTING`, which a session does not read.
- **Session analysis of 09-14:** about half of the Arbiter's turns went to the product, not the
  car; the intake is "a form in all but the widget"; 229 free Bash calls; the Arbiter already
  answers in one line.

## Decisions

### Product

- Public, for people who already own REW and a microphone.
- One installer that asks "with TCC?", default yes. Two entries: the terminal alone (the method, as
  in 2.x) and TCC.
- Tested provider: Claude Code. Others "may work" and are not in the wave.
- The AI runs in the user's terminal on the user's own subscription.

### TCC

- The terminal is the centre of the process. TCC is a companion beside it: one compact window with
  docks/tabs that remembers its place and size, not a full-screen app. The terminal window is placed
  once by the user.
- Panels that earned their place: plan, DSP parameters, EQ copy. Hidden behind View → show: REW
  (expectations were high; it does not yet work as needed) and the flaw map (useful to the author,
  on request for a user). Code stays; their bugs are fixed.
- Start from TCC: it brings up MCP, writes `.mcp.json`, opens the terminal. Terminal-first is a
  later addition if the trial shows people start there.
- The SDK route (dialogue in the window) is decided by the trial run, which goes through it —
  "maybe not everything is lost". Whether the companion gets a dialogue dock waits on the same
  verdict.

### Method

- Audit 3.x against one rule: a question is asked only when its answer changes the next action;
  information is offered, an answer is recorded when there is one, and what is not critical and
  unanswered is asked later. Trimming goes step by step, each cut checked for logic lost — no word
  target. New maths and knowledge stay; references stay on demand.
- **Controls** (the Arbiter's word: «контролі») — reminders the method keeps for the user:
  - A catalogue in the method: text · moment · mandatory or not · a value where one applies. Built
    first by going through what the method already contains.
  - Moments in v1: session start and before a measurement; more from usage, names unified in a
    separate pass. The catalogue says which control is active at which moment.
  - Per project: the active set, the values, the user's own additions.
  - Flow: at session start the mandatory ones; at intake the full catalogue, the user picks the
    active ones — a control with a value is asked now, one without is asked later; additions any
    time, at intake or mid-session.
  - Before a measurement, also "what was changed on the previous step" — derived from the ledger
    automatically.
- The method's own "later" list — deferred questions and things to recheck — is for the system
  only: the method writes and reads it, the user is not shown it. Other kinds are added when a need
  appears.
- Intake: dialogue in the terminal now — numbered lists, one-line answers, the same in both
  entries. The TCC form (proposal of 09-14) comes after the trial, with the companion.
- Owners: catalogue, files, reading rule — the skill (tickets on the Arbiter's word). Panels — TCC.

### Cycle

1. Fix all nine open issues as the product stands (#20 #21 #24 #25 #27 #36 #37 #38 #39) —
   including what will be hidden, so nothing has to catch up later.
2. Trial run in a car through the SDK route. The car is available; the blocker was the product's
   errors piling up.
3. Then, together: remove what the trial condemns and rebuild the companion.

A clean session: zero turns about the product in the transcript. Gates passing on the first
attempt is not a criterion — a gate can fail for the user's or the setup's reasons. The per-phase
impression is the Arbiter's own, outside the product.

## Waits on the trial

- The SDK route: keep or remove.
- A dialogue dock in the companion.

## Set aside

- REW: what "works as needed" means — a separate conversation when it returns.
- Names of the moments — a unification pass once there is usage.
- Whether the flaws in the knowledge base are right — one-off, author-level.

## Issue triage by route (for step 1)

| route | issues |
|---|---|
| SDK route | #24 (likely — login status for the embedded session) |
| REW panel, to be hidden | #38, #39, #21, #20 |
| flaw map, to be hidden | #37 |
| stays regardless | #25 status strip, #27 splash, #36 reviewer permission advice |

## Next steps and who says go

- tcc: step 1 of the cycle in the wave's work phase; the companion and the View menu after the
  trial.
- skill: three tickets — the catalogue of controls, the "later" file, the audit rule — opened on the
  Arbiter's word, not before.
- Arbiter: the trial run and its per-phase impression.
