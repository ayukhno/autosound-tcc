"""Re-record `tests/shard-weights.json` — each test file timed in ITS OWN process.

    python scripts/record_shard_weights.py              # every file
    python scripts/record_shard_weights.py --only tests/test_ship.py tests/test_ci_shard.py

The table is what `scripts/ci_shard.py` packs the CI shards with, and it decays: every test file
added since it was recorded weighs the median instead of itself. `test_ci_shard.py` fails when too
many do, and this is the command that answer names.

## Why one process per file, and not `--durations` from one big run

Because the two disagree by a factor of six, and the big run is the one that lies about a shard.
Measured 2026-09-19 on the author's M1 Pro:

    tests/test_main_window.py alone .................  53 s
    the same file inside the whole suite ............ 302 s   (--durations=0, summed per file)

Nothing about the file changed. What changed is the process it ran in: the suite keeps windows
alive, and an app-wide stylesheet change re-polishes every widget of every one of them
(`tests/test_measurement_panel.py` carries that note from 2026-09-06). Cost per test therefore
rises with how much is already alive — which is superlinear, and which a shard does not pay.

A weights table taken from the whole run is a table of that penalty, not of the file. Used on the
CI shards it packed one file alone into a shard that finished in 83 s while another shard ran 201,
measured on run 35429188848. One process per file is the condition a shard is closest to, so that
is what is recorded — and the cost is one pytest start-up per file, which is the price of a number
that means something.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "tests" / "shard-weights.json"

HOW = ("python scripts/record_shard_weights.py — each test file run alone, wall seconds, because "
       "a file's cost inside the whole suite is mostly the windows the suite is keeping alive")


def test_files() -> list[str]:
    return sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / "tests").glob("test_*.py"))


def time_one(name: str) -> tuple[float, int]:
    """Wall seconds for one file in a fresh process, and pytest's exit code."""
    started = time.monotonic()
    done = subprocess.run(
        ["uv", "run", "--extra", "dev", "--python", "3.12", "python", "-m", "pytest", name,
         "-q", "-p", "no:cacheprovider"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return round(time.monotonic() - started, 2), done.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", default=None,
                        help="re-time just these files, keeping the rest of the table")
    args = parser.parse_args(argv)

    names = args.only or test_files()
    seconds = {}
    if args.only and TABLE.is_file():
        seconds = json.loads(TABLE.read_text(encoding="utf-8")).get("seconds", {})

    red = []
    for index, name in enumerate(names, 1):
        took, code = time_one(name)
        seconds[name] = took
        if code != 0:
            red.append(name)
        print(f"  {index:3d}/{len(names)}  {took:7.2f} s  {name}"
              f"{'  ← red, and timed anyway' if code else ''}", flush=True)

    # A red file still has a cost, and a shard still has to carry it. Say it once at the end rather
    # than refusing to record: the table is about seconds, and the suite is about green.
    if red:
        print(f"\n{len(red)} file(s) exited non-zero and were timed anyway: {', '.join(red)}",
              file=sys.stderr)

    seconds = {name: seconds[name] for name in sorted(seconds) if (ROOT / name).is_file()}
    TABLE.write_text(json.dumps(
        {"recorded": date.today().isoformat(), "how": HOW, "seconds": seconds},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n{TABLE.relative_to(ROOT)}: {len(seconds)} files, {sum(seconds.values()):.0f} s in total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
