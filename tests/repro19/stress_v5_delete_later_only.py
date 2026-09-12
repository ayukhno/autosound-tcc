"""#19 stress v5 (delete-later-only): drop = hide + deleteLater; 150 cycles in one process. See _repro_common.py."""
from _repro_common import make_stress

test_stress = make_stress("delete-later-only")
