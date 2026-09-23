# TCC in eight screens

**In one line:** a short tour of the TCC window: what each part shows and where you click. Every
panel in detail is in the [full reference](REFERENCE.md).

The screenshots come from a real tuning project: a VW Passat B8 with a Helix DSP Ultra S, its notes
translated into English. The conversation in the dialog panel is an example.

## 1. The window

![The TCC main window: the DSP tree on the left, the AI dialog in the middle, the plan and the capture card on the right](img/overview.webp)

The window has three columns:

- **Left**: the project, the car, what the cabin does to the sound, and the DSP tree with every
  channel's crossover, gain, polarity and EQ.
- **Middle**: the AI dialog. You are the **Arbiter**, the **Generator** proposes and the **Critic**
  (the reviewer) checks the proposal. Write in any language, then press *Send*.
- **Right**: the plan (*Plan — fact*) above, and below it *In focus now*, the measurements the
  current step asks for.

The footer holds the models: *AI main* (the Generator), *Effort*, *AI critic*, and the reviewer's
status.

## 2. The header

![The header bar: menu, project name, preset, target curve, control mode, reload, diagnostics, language, text size and theme](img/header.webp)

From left to right: **☰ Menu**, the project folder, the **Preset** you are looking at (SQ, FULL…),
and the **Target curve**, which opens in the target-curve tool (see
[the house curve in TCC](HOUSE-CURVE.md)). On the right: **Control mode**
(see screen 8), **⟳** reloads the project from disk, **⚙** opens diagnostics and updates, then the
language, the text size and the light/dark theme.

## 3. The DSP settings as a table

![The output channels as one table: HPF, LPF, gain, delay, polarity and EQ bands per channel](img/table-outputs.webp)

Click a tier in the DSP tree (*Output*, *Virtual*), or *params · all parameters as a table*, and
the channels open as one table above the dialog. **compare with** shows each value next to the
configuration this one continues from (here `v_006`), so you can see what changed. *close ×* hides
the pane again.

## 4. A channel's EQ

![The EQ bands of the m-L channel: type, frequency, Q and gain of each band](img/eq.webp)

Click a channel's **EQ n** chip to see the bands in use, every parameter of each band at once.
**⇄ L + R** puts the left and right channel side by side. **Copy EQ** puts the whole bank on the
clipboard in your DSP software's format, so you don't have to retype it.

TCC never writes to the processor. You enter or import the values yourself.

## 5. The plan

![The plan: phases −1 to 5, the current phase open with its steps ticked or open](img/plan.webp)

The tuning runs in phases, from intake (−1) to variations (5). The current phase is orange. Open it
to see its steps: a tick means done. **unproven** means the step was reported done, but the
evidence it names cannot be found on disk.

## 6. A capture round

![The In focus now card: a capture round with sweeps waiting and MMM captures done](img/capture-round.webp)

When a step needs measurements, *In focus now* lists them by name and method (sweep, MMM RTA). The
colours: yellow **waiting**, blue **in REW**, green **done**, red **unusable** (a retake), grey
**skipped**. Take the measurements in REW under these names, then press **⬇** to read them from
REW, matched against what the round expects. When they are all in, **Done** tells the AI to start on
them. The picker at the top opens earlier rounds. **Protection** records the protective filters a
raw capture was taken through.

## 7. The curves

![The curve window: two frequency responses from REW, markers and the delay and all-pass controls](img/curves-frequency.webp)

The **∿** button on the capture card opens the measurements straight from REW. Pick what to see (frequency response,
impulse, phase), add curves with **Choose…**, and press **Σ** to draw what the drivers do
*together*. Try a delay or an all-pass in the boxes below, and the sum redraws before anything
reaches the DSP.

## 8. Control mode

![Control mode: TCC as a compact side window with the session feed, the tables and the panels](img/control-mode.webp)

If you prefer the terminal, **Control mode** moves TCC to the right half of the screen: you type in
the terminal, and TCC shows what the session writes (*Monitoring*), the tables and your panels. The
*Done* and *Listening* buttons reach the session as signals. **Active TCC** brings the full window
back.

---

Next: [the full reference](REFERENCE.md), every panel, dialog and button.
