"""#19 stress v6 (set-parent-only): drop = hide + setParent(None); 150 cycles in one process. See _repro_common.py."""
from _repro_common import make_stress

test_stress = make_stress("set-parent-only")
