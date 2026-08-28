# One shape across every tree in this project — the hub already has `make test`, `make digest`,
# `make guards` and `make roles`, so TCC's entry points are spelled the same way rather than
# hiding in `scripts/` where only the person who wrote them remembers the path.

PY ?= uv run --extra dev --python 3.12 python

.PHONY: help test ship

help:
	@echo "make test           the whole suite (~5 min; there is no fast subset on purpose)"
	@echo "make ship           dry run: work out the next patch, check everything, write nothing"
	@echo "make ship REAL=1    the real release — bump, test, commit, tag, push"
	@echo ""
	@echo "Asking for a release — \"new tag\", \"ship it\", \"cut a patch\" — means REAL=1,"
	@echo "but it is never the first thing done: the dry run and its plan come first, and"
	@echo "REAL=1 waits for a yes. An irreversible act is not performed on a guess."
	@echo "There is no hand-rolled version of this. commit + tag + push typed out one by"
	@echo "one is the same release with the gates missing."

test:
	$(PY) -m pytest tests/ -q

# Dry run is the default and the real run is asked for by name. The last thing `ship` does is
# publish a tag, and a published tag can never be moved or deleted by anyone afterwards.
#
# Note for whoever edits this: the hub's `guard-release` hook does NOT see git commands run from
# inside a make recipe — it parses the command line, and `make ship` has no git verb in it. That
# is settled and deliberate on the hub's side, written down as a boundary rather than a defect
# (`governance/RELEASE-CHANNEL.md` §8.10): an opaque launch is not catchable, so the hub does not
# claim to catch it. There is no safety net under this target: what checks a release is
# `scripts/ship.py`, and the channel half of what it checks is the hub's own
# `scripts/release-preflight.py` — called, not copied here (HUB-003). No hub on the machine means
# nothing is checking, so ship refuses rather than carrying on.
ship:
ifeq ($(REAL),1)
	$(PY) scripts/ship.py --release
else
	$(PY) scripts/ship.py
endif
