"""autosound-tcc — read-only Tuning Command Center for car-audio DSP tuning.

v1 is READ-ONLY by design: it connects to REW's local API and reads the
project-local DSP state ledger, then displays it. It never writes DSP settings.
Automated writes stay out of scope until the safety work behind them is done.
"""

__version__ = "0.0.1"
