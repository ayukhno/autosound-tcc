# autosound-tcc

Cross-platform (macOS + Windows) desktop app for car-audio tuning:
a **Tuning Command Center** and a **Guided Setup Wizard**.

The goal is to lower the barrier to entry for people who are not tuning
experts — show the current state of a system clearly, and guide the manual
steps — rather than to automate the DSP.

> **Status: early scaffold.** Nothing is implemented yet.

## Scope of the first version

- **Read-only.** The app connects to [REW](https://www.roomeqwizard.com/)
  (local API on `localhost:4735`), reads the current measurement and filter
  state, and displays crossovers, delays, gains, EQ and frequency-response
  curves.
- **No DSP writes.** The app does not change processor settings. Automated
  writing is deliberately out of scope until the safety work behind it is
  done.

## Stack

Python + PySide6 (Qt), with `pyqtgraph` for curves. The tuning engine is
Python already, so the app reuses it directly rather than bridging languages.

## Related projects

- [`autosound-tuning-skill`](https://github.com/ayukhno/autosound-tuning-skill)
  — the tuning knowledge base and tooling this app builds on.

## License

Apache-2.0 — see [LICENSE](LICENSE).
