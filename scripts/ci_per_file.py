"""Run each test file in its own pytest process, and fail if any of them failed (#275, option A1).

    python scripts/ci_per_file.py tests/test_a.py tests/test_b.py -- -q -m "not method"

Everything after `--` goes to every pytest process as it is. Every file runs, whatever the one
before it did; the exit code is 0 only when every file passed, and the end of the log names each
file that did not, with pytest's own exit code.

## Why a process per file

One process for a whole shard made every test pay for every test before it: the suite keeps its
windows alive (`tests/_windows.py`), and an app-wide restyle, retranslate or collection costs in
proportion to what is alive, so a test that took 2 s alone took 54 s late in a long process, and
the product's own timers fired over the tests that waited on them. Process-wide state with no
per-test reset made which files shared a process decide which test went red
(`docs/CI-ROOT-CAUSE-2026-11-10.md`, RC1 and RC3). A process per file is what
`scripts/record_shard_weights.py` already times, so the shards now run under the condition their
weights were measured in.

A file stays the unit, as in the split (`scripts/ci_shard.py`) and under `--dist loadfile`: a
session-scoped `QApplication` and module-level state make a whole file in one process the safe
unit, and nothing here cuts inside one.

## Exit codes

pytest's 5 is "no tests collected": a file whose every test the `-m` expression deselected has
nothing to run, and that is not a failure; the end of the log names such files. When EVERY file
gives 5 the shard ran nothing at all -- a wrong `-m` -- and that is a failure. Every other non-zero
code is one too, a crash of the process (a negative code, or 134/139) included.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

#: pytest's exit code for "no tests collected" — every test of the file deselected.
NO_TESTS = 5


def _split_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    """The files before `--`, pytest's arguments after it."""
    if "--" in argv:
        at = argv.index("--")
        return argv[:at], argv[at + 1:]
    return argv, []


def _in_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def run(files: list[str], pytest_args: list[str],
        python: str = sys.executable) -> tuple[list[tuple[str, int]], list[str]]:
    """Each file in its own `python -m pytest`, in order.

    → `([(file, exit code)] for the failed, [file] for those with nothing collected)`."""
    failed, empty = [], []
    for index, name in enumerate(files, 1):
        header = f"[{index}/{len(files)}] {name}"
        print(f"::group::{header}" if _in_actions() else f"=== {header}", flush=True)
        started = time.monotonic()
        code = subprocess.call([python, "-m", "pytest", name, *pytest_args])
        took = time.monotonic() - started
        if _in_actions():
            print("::endgroup::", flush=True)
        if code == NO_TESTS:
            empty.append(name)
        elif code != 0:
            failed.append((name, code))
            if _in_actions():
                print(f"::error title=pytest exit {code}::{name}", flush=True)
        print(f"    {name}: exit {code}, {took:.0f} s", flush=True)
    return failed, empty


def ran_nothing(files: list[str], empty: list[str]) -> bool:
    """Every file collected nothing: the selection, not the tests, is what is wrong."""
    return bool(files) and len(empty) == len(files)


def report(files: list[str], failed: list[tuple[str, int]], empty: list[str]) -> str:
    """The closing lines: each failed file by name and code, then each that collected nothing."""
    if ran_nothing(files, empty):
        lines = [f"ci_per_file: none of the {len(files)} file(s) collected a test -- the shard "
                 "ran nothing, so the selection (`-m`, the file list) is wrong"]
    elif failed:
        lines = [f"ci_per_file: {len(failed)} of {len(files)} file(s) failed:"]
        lines += [f"  {name} (pytest exit {code})" for name, code in failed]
    else:
        lines = [f"ci_per_file: all {len(files)} file(s) passed"]
    if empty and not ran_nothing(files, empty):
        lines.append(f"ci_per_file: {len(empty)} file(s) collected nothing (pytest exit 5, "
                     "every test deselected):")
        lines += [f"  {name}" for name in empty]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    files, pytest_args = _split_argv(list(sys.argv[1:] if argv is None else argv))
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", help="test files, one pytest process each")
    args = parser.parse_args(files)

    failed, empty = run(args.files, pytest_args)
    said = report(args.files, failed, empty)
    print(said, flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and ran_nothing(args.files, empty):
        with open(summary, "a", encoding="utf-8") as out:
            out.write("- red: no file collected a test -- the selection is wrong\n")
    elif summary and failed:
        with open(summary, "a", encoding="utf-8") as out:
            out.write("\n".join(f"- red: `{name}` (pytest exit {code})" for name, code in failed)
                      + "\n")
    return 1 if failed or ran_nothing(args.files, empty) else 0


if __name__ == "__main__":
    raise SystemExit(main())
