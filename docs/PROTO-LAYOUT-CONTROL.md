# Prototype — «Режим контролю» (F-069), throwaway

Branch `proto-layout-control`, on top of `wave-0.1.43`. Not for merging: it exists so the Arbiter
can judge the shape on his own project before the real thing is built (2026-09-22). The code is
`src/autosound_tcc/ui/tcc/control_layout.py` plus one button in the header.

## Run it

```bash
cd ~/dev/autosound/tcc && git switch proto-layout-control
uv run --extra gui --extra claude autosound-tcc
```

The header has a **«Режим контролю»** button; it becomes **«Активний TCC»** and back.

## What it does (the Arbiter's description, DECISIONS-W-2 A9–A13)

- TCC moves to the RIGHT half of the screen; if Terminal is running, its front window moves to the
  LEFT half (macOS).
- The top window is full width: **Моніторинг** · **Таблиця-V** · **Таблиця-О** · EQ · Рівень ·
  Затримки · Фази. Below it the left and right panels side by side, equal; both borders drag.
- **Моніторинг** is read-only: the project's process journal (phases, steps, capture rounds,
  decisions), newest last, refreshed every 2 s, and two bus buttons — «Готово» and «Прослухати».
  Typing is in the terminal.
- TCC's own confirmation strip sits ABOVE the tabs and appears only when a request arises.
- To fit half a screen: language, zoom and theme leave the header (they are in the menu); the
  preset and target shrink; the in-app Generator's model and effort leave the footer (the session
  runs in the terminal, so they steer nothing); the reviewer stays (`call_critic` uses it).

## What to look at, and the questions it raises

1. **Width.** Measured on the Passat: 812 px is the narrowest the window goes in this mode. Half of
   a 14" MacBook (1512) is 756 — 56 px over; on 1920 and wider it fits with room. The header is the
   limit (preset + target + buttons). *Is 812 acceptable, or should the header lose more?*
2. **Моніторинг shows the JOURNAL, not the conversation.** TCC cannot see the terminal session's
   words — only what it writes to disk and the tools it calls on TCC. *Is the journal the right
   feed, or should TCC's own MCP tool calls be in it too (they are not yet)?*
3. **Таблиця-V / Таблиця-О** are today's group tables, one line of parameters per channel. *Which
   columns does quick access need — the same, or gain · delay · polarity · EQ count as columns?*
4. **EQ** opens on the outputs table; a row click opens that channel's EQ (the pane's own
   table/EQ switch is kept there). Рівень / Затримки / Фази are the one-parameter tables, across
   the rig, as today.
5. **The confirmation strip** is TCC's own gate (writes to the register); the terminal's permission
   prompts stay in the terminal.
6. **Leaving the mode** puts every panel back and restores the window's size.

Screenshots of this branch at 812 px are in `hub/scratch/tcc/shots/control-*.png` (not tracked).
