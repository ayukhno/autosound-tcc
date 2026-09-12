"""#19 bisection v7 (unlayout-first): drop takes the widget out of its layout, then hide +
setParent(None) + deleteLater as today — the general fix candidate. See _repro_common.py."""
from _repro_common import make_tests

test_1_mock_transcript, test_2_attach_clears, test_3_next_panel = make_tests("unlayout-first")
