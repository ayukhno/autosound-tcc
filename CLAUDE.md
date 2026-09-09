# TCC — how to work in this repo

Assembled from the places the rules already live (`scripts/ship.py`, `tests/conftest.py`,
`docs/TESTING.md`) rather than written fresh beside them — a second copy of a rule drifts from its
owner, and this repo has paid for that shape often enough (HUB-048).

## The three commands

```sh
make test                                     # the whole suite, serial, ~8 min. Run it whole.
uvx ruff@0.12.0 check src tests scripts       # what CI lints with. `make test` does NOT run it.
make ship                                     # dry run: works out the next patch, writes nothing
```

**`make test` green is not the same claim as CI green.** CI also runs the linter above, and runs
the suite on Linux and Windows where this repo has real, open flakiness (`docs/TESTING.md`,
"Known flakiness"). Run the linter before saying anything is ready.

Parallel is available and is **not** the default:

```sh
PYTEST_ADDOPTS='-n auto --dist loadfile' make test    # ~1 min, kills a Qt worker now and then
```

Use it while iterating, where a dead worker costs one re-run and is obvious. Never to decide that
something is green — see `tcc#22`.

## Releases

`make ship` is a dry run and `make ship REAL=1` is the real one, asked for by name. Its last act
publishes a tag, and **a published tag can never be moved or deleted by anyone**. There is no
hand-rolled version of this: `git commit && git tag && git push` typed out one by one is the same
release with the gates missing.

**The neighbouring `hub` checkout is required.** The channel half of the preflight — clean tree,
HEAD published, `push.followTags`, the tag free on the remote — is `hub/scripts/release-preflight.py`,
called rather than copied (HUB-003). No hub on the machine means nothing is checking the release,
and unknown is a refusal, never "no objections". The hub's git hook cannot see any of this either:
it parses the command line, and `make ship` contains no git verb at all.

## The bus

Work arrives as tickets in `ayukhno/autosound-hub`, labelled `to:tcc`. `hub/bin/ticket queue`
shows the queue, receipts, and this repo's own issues — which never reach the bus and which
nobody else will relay.

> **Closing a ticket carries a COMMAND somebody else can re-run, not a description of the result.**

`bin/ticket close N done "<proof>"` refuses a proof line that only says what was done — the
changes already show that. `git -C vendor/... describe --tags → v3.0.47` is a proof;
"raised the pin" is not. Learned by being refused (2026-09-09).

A ticket addressed to another role goes to the bus (`bin/ticket open`), never as a PR and never
relayed through a person. Anything that needs a decision from the Arbiter stays open with the
question in it, rather than being closed as "done except".

## Tests

Written first, watched failing, then made to pass — the failure is the only proof the test can
catch anything. Two rules this repo keeps re-learning:

* **The suite must not be able to read this machine.** `tests/conftest.py` redirects QSettings, a
  tmp `HOME`, the project dir, the agent-CLI probe, the critic probe and the network. Two tests
  once passed on the author's laptop and failed on both CI platforms because a probe had a second
  door nobody had noticed (`tests/test_conftest_guards.py` is that lesson, checked).
* **A stub nobody compares to the real thing is how a green suite starts lying.** `test_ship.py`
  says it in its header, and it caught a live one on 2026-09-09: a function used a pattern that
  did not exist in its module, and every test passed because the fixture stubbed the function out.

## Skills

`superpowers:brainstorming` before building anything, `superpowers:test-driven-development` for
every change, `hub:seam` on every ticket — it says which rule wins when the engine and the bus
disagree. The queue is not an order: it is shown and the Arbiter decides.
