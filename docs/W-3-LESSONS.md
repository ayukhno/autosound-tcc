# W-3 · v0.1.44 — what the Mac test taught

The Arbiter's Mac test of 2026-09-27, findings 78–101 in `TEST-FINDINGS.md`, issues on the milestone
`W-3 · v0.1.44`. Seven lessons, each with the rule it leaves behind.

## 1. A route is part of the model's name

omp, the API key, `agy` and `codex` name the same model differently: `google-antigravity/gemini-3.1-pro`
for omp, `gemini-3.1-pro-preview` for the API, `gemini-3.1-pro-high` for `agy`. TCC cut omp's prefix and
sent the rest to the API; the answer was 404 (findings 82, 85).

**Rule.** A pick goes through its own route, under its own name, and nowhere else — the Arbiter's words:
«якщо вибрана ОМР, то і йти треба тільки через цей виклик». Every route is its own row (`API · …`, `OMP · …`),
every model on screen carries its route (the picker, the project panel, the dialog's bubbles). The
method's reviewer script gained the omp route for it (hub #216 TCC-034, v3.0.63).

## 2. «Ready» means «answered», not «configured»

TCC reported `reachable: true, ready: true` for a model Google had retired. A channel that exists is not a
model that answers.

**Rule.** The reviewer is asked once at launch and at once when picked; the frame says what it learned —
grey not known yet, green answered, red refused with the route's own words. A model the route does not
serve (`choose_model`) is a refusal (tcc#74).

## 3. Subscriptions run out; the key does not

In one afternoon: Antigravity's Gemini Pro 429 `RESOURCE_EXHAUSTED`, Codex `usage_limit_reached`, `agy`'s
Pro «not supported in the selected location». Only `API · gemini-pro-latest` (the key) and an omp model on
another provider kept answering.

**Rule.** The reviewer's ladder needs a second route that is not a subscription quota. The API route stays
in the list for that; quota refusals are said as quota, not as a broken model.

## 4. A live session has limits a test does not

Three of them, each invisible until a real session hit it: omp aborts an MCP tool after 30 s
(`OMP_MCP_TIMEOUT_MS`) while a review takes minutes (97); a reviewer on the generator's own model hangs
(99, the method's warned deadlock); and TCC's own hint told the session to retry through the key — against
the Arbiter's rule (98).

**Rule.** TCC's words to the model are policy, not help text: a hint that breaks a rule is a defect.
Anything a session calls is sized for a real call, not a probe.

## 5. The machine around TCC is part of the test

A running Parallels VM published its Windows Terminal to macOS as «Terminal», and `tell application
"Terminal"` reached it (89). Qt's `raise()` on macOS activates the whole app, so a hover tip pulled TCC
back over the terminal it had just opened (79).

**Rule.** Address other apps by bundle id, never by name. Never `raise()` a helper window. Keep the other
program's own words when it refuses (osascript's stderr named the cause at once).

## 6. One colour, one meaning

Red was used for «refused», for «a warning» and for «the mouse is here»; TCC's own lines wore the ledger's
label.

**Rule.** Red — cannot run; yellow — a warning, it still runs; green — answered; grey — not known yet.
Hover never repaints a state. `SYSTEM · TCC` for TCC's own lines; `ledger` only for a record.

## 7. Two copies of the method are two facts

The personal copy was 3.0.62 while the car project's link held a pinned 3.0.61; every screen said
«3.0.62 — актуальна» and the session kept asking which (86, 94).

**Rule.** Show the project's own method beside the personal one whenever they differ; the pin is the
project's choice and is answered in the project's session.

## The process

The collection ran on the Mac all day; it closed when new findings became tails of what the wave had
already touched («доробити!»). Two findings went back to the skill as one ticket (hub #216), answered
with a tag the same day. Left for W-3: Windows (#62, #66) on the VM, the full suite with the VMs
suspended, the release.
