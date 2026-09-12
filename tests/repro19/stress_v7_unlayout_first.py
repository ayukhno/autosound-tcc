"""#19 stress v7 (unlayout-first): drop takes the widget out of its layout first; 150 cycles in one process. See _repro_common.py."""
from _repro_common import make_stress

test_stress = make_stress("unlayout-first")
