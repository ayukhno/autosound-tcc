# TCC — interface & interaction concept (working notes)

Status: the read-only **state-view pilot** is done (virtual + output channel
tables fed from a project-local ledger). Next step is to design the **interface
& interaction concept** (in Claude Design) *before* writing more app code — the
data model may change to fit the concept.

These notes capture the direction so nothing is lost. They are design intent,
not a spec.

---

## 0. Processor-agnostic — critical constraint

Different DSPs expose different parameters. The model must **not** hard-code
Helix concepts as universal.

- **Helix DSP Ultra S** has a *virtual-channel* tier.
- **MUSWAY** (e.g. M6v4) does **not** have virtual channels at all.

So "virtual channels" is a *processor capability*, not something every project
has. The UI and data model must describe whatever the project's processor
actually exposes.

---

## 1. Helix channel model — correction to the pilot

Recorded now; the pilot's virtual model is a **known-wrong placeholder** to be
reworked later (do not trust it).

**Virtual channels:** 8. Recommended names: `VFL, VFR, VRL, VRR, VC, VSW`.
Parameters per virtual channel: **phase, delay, gain, INV, MUTE, BYPASS EQ**.
→ **No crossovers on virtual channels.** (The pilot wrongly gave the virtual
Center a crossover — disregard / zero it.)

**Output channels:** up to **20**.

**EQ (per channel, both tiers):** **30 bands**. Per band: **BYPASS**, filter
type ∈ `{PK, LSH, HSH, APF1, APF2}`.

**FX is a parameter, not a channel.** (The pilot wrongly modeled FX as a virtual
channel — to be removed.)

All of the above is **Helix-specific and varies by model** — treat as one
processor profile, not the schema.

---

## 2. What the TCC must show (concept inputs)

The DSP status view is **only a control-check** — not the centre of the app.
The centre is the **process**.

1. **Map of active settings** — which of the project's virtual/output channels
   are actually in use (e.g. 6 of 8 virtual, 10 of 12 output for a full
   front+center+rear tune; a different DSP or scope differs). Show what's live.
2. **Target curve** — which one is selected (by name). Viewing the curve itself
   is done in REW or NTT (a tool we have), not necessarily in-app.
3. **Process, front and centre** — the tuning process steps + status of each,
   **compact but always visible**. Two levels: high-level *phases*, and the
   *current plan* (steps + progress) that can be discussed and adjusted.
4. **AI dialog = the main working window** (Generator ↔ Critic/Advisor ↔ User).
5. **Measurement task, prominent** — the measurement number to take; whether
   that measurement already exists; whether it is *valid* (a sweep can drift —
   analysis math exists to check). Naming-convention hint available on demand.
6. **Advisor / Critic panel** — is it engaged, which AI + model, when last
   called (phase, plan step, time ago).
7. Curves from REW in-app: **probably not needed** (REW is at hand) — tentative.

---

## 3. Presets & target curves

- A project can have **more than one preset**.
- Each preset can have its **own target curve / goal** (unique per preset), not
  just its own channel gains.
- (Real example: SQ vs FULL presets — different gains, different active
  channels; here modeled first as FULL only.)

---

## 4. Data storage — to clarify

Concern raised: **where project data lives must be crisp.** The pilot seeds
`data/private/state/<preset>/v_NNN.json` (gitignored, inside the app repo), and
finding the source values meant grepping across `~/dev` — that is not a
convention. Design a clear one: likely a **per-project folder the user points
the app at**, documented, not scattered or auto-discovered by search.

---

## 5. Not yet discussed

- **EQ** visualization & interaction (30-band, per-tier) — separate design pass.
- Visual/form design — to be done in Claude Design.
