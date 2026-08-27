# One shape across every tree in this project — the hub already has `make test`, `make digest`,
# `make guards` and `make roles`, so TCC's entry points are spelled the same way rather than
# hiding in `scripts/` where only the person who wrote them remembers the path.

PY ?= uv run --extra dev --python 3.12 python

.PHONY: help test ship

help:
	@echo "make test           the whole suite (~5 min; there is no fast subset on purpose)"
	@echo "make ship           dry run: work out the next patch, check everything, write nothing"
	@echo "make ship REAL=1    the real release — bump, test, commit, tag, push"

test:
	$(PY) -m pytest tests/ -q

# Dry run is the default and the real run is asked for by name. The last thing `ship` does is
# publish a tag, and a published tag can never be moved or deleted by anyone afterwards.
#
# Note for whoever edits this: the hub's `guard-release` hook does NOT see git commands run from
# inside a make recipe — it parses the command line, and `make ship` has no git verb in it. There
# is no safety net under this target; `scripts/ship.py` carries the rule itself, and checks it
# against the hook rather than remembering it. Filed as autosound-hub#8.
ship:
ifeq ($(REAL),1)
	$(PY) scripts/ship.py --release
else
	$(PY) scripts/ship.py
endif
