"""#19 stress v2 (rows-first): rows out first, widgets dropped after; 150 cycles in one process. See _repro_common.py."""
from _repro_common import make_stress

test_stress = make_stress("rows-first")
