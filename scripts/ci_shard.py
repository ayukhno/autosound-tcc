"""Which test files one CI shard runs — a stable split by FILE, weighted by a recorded run.

    python scripts/ci_shard.py --splits 4 --group 1

Prints the files for that group, space-separated, for `pytest $(…)`. Nothing else: no pytest
flags, because how the suite is distributed has one source and it is not a caller
(`test_no_pytest_caller_carries_its_own_distribution_flags`).

## Why a shard at all

Measured 2026-09-18 (hub `docs/PLAN-CI-WAIT-2026-09-18.md`, step 1): the wait for a pull request
is the suite, and the suite is uniform volume, not a handful of slow tests. Windows ran 2104 tests
in 1273 s and its forty slowest were 290 s of that — deleting every one of them would move 21.2
minutes to 16.4. Four machines each running a quarter, serially, is what shortens the wait.

## Why BY FILE, and not by test

`docs/TESTING.md` already carries the reason under `--dist loadfile`: a session-scoped
`QApplication` and module-level state make a whole file on one process the safe unit. A splitter
that cuts inside a file would be a second, quieter answer to a question this repository has
already answered.

## Why WEIGHTED, and not alphabetically

An alphabetical quarter moves the moment a test file is added, and it balances by name rather than
by time: `test_curve_view.py` and `test_main_window.py` alone are a fifth of the run. The weights
are seconds from a real serial run (`tests/shard-weights.json`), and the packing is longest-first
into the lightest shard — the standard greedy, which is deterministic and needs no state.

A file the table has never heard of gets the MEDIAN of the ones it has, never zero: an unweighted
new file would always land in the shard that happens to be lightest and would be invisible until
it was slow. Unknown files are named on stderr, so a stale table shows in the job log rather than
in a mysteriously long shard.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "tests" / "shard-weights.json"


def test_files(root: Path = ROOT) -> list[str]:
    """Every collectible test file, as posix paths, in a fixed order.

    Sorted so the input to the packing never depends on the filesystem's own ordering, which
    differs between macOS and Linux and would hand two platforms different shards.
    """
    return sorted(path.relative_to(root).as_posix()
                  for path in (root / "tests").glob("test_*.py"))


def load_weights(path: Path = WEIGHTS) -> dict:
    """The recorded seconds per file, or an empty table when there is none.

    A missing table is not a failure: every file then weighs the same and the split is by count,
    which is worse than by time and still better than by name.
    """
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("seconds", {})


def split(files: list[str], weights: dict, splits: int) -> list[list[str]]:
    """`splits` lists of files, packed longest-first into whichever shard is lightest so far.

    Ties broken by name and then by shard index, so the answer is the same on every machine and in
    every run — four jobs computing this independently must agree without talking to each other.
    """
    known = sorted(float(weights[name]) for name in weights if name in set(files))
    default = known[len(known) // 2] if known else 1.0
    unknown = [name for name in files if name not in weights]
    if unknown:
        print(f"ci_shard: {len(unknown)} file(s) not in the weights table, each counted as "
              f"{default:.1f} s: {', '.join(unknown)}", file=sys.stderr)

    shards: list[list[str]] = [[] for _ in range(splits)]
    totals = [0.0] * splits
    for name in sorted(files, key=lambda name: (-float(weights.get(name, default)), name)):
        lightest = min(range(splits), key=lambda index: (totals[index], index))
        shards[lightest].append(name)
        totals[lightest] += float(weights.get(name, default))
    return [sorted(shard) for shard in shards]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--splits", type=int, required=True, help="how many shards in total")
    parser.add_argument("--group", type=int, required=True, help="which one to print, 1-based")
    args = parser.parse_args(argv)
    if args.splits < 1 or not 1 <= args.group <= args.splits:
        parser.error(f"group {args.group} of {args.splits} is not a shard")

    files = test_files()
    weights = load_weights()
    shards = split(files, weights, args.splits)
    mine = shards[args.group - 1]

    # On stderr, so `pytest $(…)` still gets only the files: what this shard is expected to cost,
    # and what the whole split looks like. The makespan is the slowest shard, and a run whose
    # shards are lopsided says so in its own log rather than in somebody's stopwatch.
    known = sorted(float(weights[name]) for name in weights if name in set(files))
    default = known[len(known) // 2] if known else 1.0
    cost = [sum(float(weights.get(name, default)) for name in shard) for shard in shards]
    print(f"ci_shard: group {args.group}/{args.splits} — {len(mine)} files, about "
          f"{cost[args.group - 1]:.0f} s by the recorded table; the split is "
          f"{[round(seconds) for seconds in cost]} s and the wait is the largest",
          file=sys.stderr)

    print(" ".join(mine))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
