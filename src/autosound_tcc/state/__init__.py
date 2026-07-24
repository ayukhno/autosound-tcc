"""Tuning-state models, kept separate from the UI (MVVM-style).

The physical car DSP's crossovers, gains, time-alignment and polarity are NOT
readable via REW's API — they live in a project-local, hand-maintained JSON
ledger (the vendored `state/state.py` `PresetHistory`). This package wraps that
ledger into typed models for the UI to display.
"""
