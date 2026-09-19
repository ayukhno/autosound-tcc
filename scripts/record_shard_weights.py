"""Re-record `tests/shard-weights.json` from a real serial run of the suite.

    python scripts/record_shard_weights.py            # runs the suite, writes the table
    python scripts/record_shard_weights.py --from run.txt   # from a run somebody already has

The table is what `scripts/ci_shard.py` packs the CI shards with, and it decays: every test file
added since it was recorded weighs the median instead of itself. `test_ci_shard.py` fails when too
many do, and this is the command that answer names.

Seconds per FILE, setup + call + teardown together, because a file is the unit the shards move
(`docs/TESTING.md`, why `--dist loadfile` exists). The run is serial and whole, for the same
reason a release is: a parallel run's per-test seconds are the seconds of a loaded machine, and
they would encode this laptop's core count into the split.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "tests" / "shard-weights.json"

#: `--durations=0` prints one line per phase: `0.35s call     tests/test_x.py::test_y`.
_LINE = re.compile(r"^\s*([\d.]+)s\s+(setup|call|teardown)\s+(tests/[^:]+\.py)::", re.M)

HOW = ("python scripts/record_shard_weights.py — a serial `pytest tests/ -q --durations=0`, "
       "seconds per file with setup and teardown counted in")


def seconds_per_file(report: str) -> dict:
    """Every phase of every test, summed onto the file it belongs to."""
    totals: dict[str, float] = defaultdict(float)
    for seconds, _phase, name in _LINE.findall(report):
        totals[name] += float(seconds)
    return {name: round(totals[name], 2) for name in sorted(totals)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="report", type=Path, default=None,
                        help="a saved `pytest --durations=0` log, instead of running the suite")
    args = parser.parse_args(argv)

    if args.report:
        report = args.report.read_text(encoding="utf-8", errors="replace")
    else:
        print("running the whole suite, serially — this is the ~10 minutes the shards save later")
        done = subprocess.run(
            ["uv", "run", "--extra", "dev", "--python", "3.12", "python", "-m", "pytest",
             "tests/", "-q", "-p", "no:cacheprovider", "--durations=0"],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
        report = done.stdout
        if done.returncode != 0:
            # A red suite still measures, and a table recorded from one is a table recorded from a
            # tree nobody should be sharding yet. Say so rather than deciding for the person.
            print(f"the suite exited {done.returncode} — read the run before trusting this table",
                  file=sys.stderr)

    seconds = seconds_per_file(report)
    if not seconds:
        print("no `--durations` lines in that report — nothing to record", file=sys.stderr)
        return 1

    TABLE.write_text(json.dumps(
        {"recorded": date.today().isoformat(), "how": HOW, "seconds": seconds},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    total = sum(seconds.values())
    print(f"{TABLE.relative_to(ROOT)}: {len(seconds)} files, {total:.0f} s in total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
