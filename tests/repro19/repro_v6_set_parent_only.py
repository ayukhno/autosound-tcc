"""#19 bisection v6 (set-parent-only): drop = hide + setParent(None), no deleteLater. See _repro_common.py."""
from _repro_common import make_tests

test_1_mock_transcript, test_2_attach_clears, test_3_next_panel = make_tests("set-parent-only")
