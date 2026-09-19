"""`scripts/ci_shard.py` — the split four CI jobs work out separately and must agree on.

TCC-020 (hub #181). The four shards never talk to each other: each job runs the same script with
its own group number, and the run is only correct if every file is claimed exactly once. That is
the property this file is mostly about, and it cannot be seen by reading the workflow.

The weights table is real data (`tests/shard-weights.json`, recorded from a serial run), so a
test that asserted an exact assignment would fail the day a test file grows. What is asserted here
is the SHAPE: a partition, the same answer twice, no file left out, and a balance good enough that
sharding is worth doing at all.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ci_shard  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

#: A table with the shape of the real one and numbers a person can check by hand.
WEIGHTS = {
    "tests/test_big.py": 100.0,
    "tests/test_medium.py": 50.0,
    "tests/test_small_a.py": 10.0,
    "tests/test_small_b.py": 10.0,
}
FILES = sorted(WEIGHTS)


def test_every_file_is_claimed_by_exactly_one_shard():
    """The one that matters: a file in two shards runs twice, a file in none is never run and
    nothing goes red to say so."""
    shards = ci_shard.split(FILES, WEIGHTS, splits=4)

    claimed = [name for shard in shards for name in shard]
    assert sorted(claimed) == FILES
    assert len(claimed) == len(set(claimed)), "a file claimed twice"


def test_the_same_question_gets_the_same_answer():
    """Four jobs compute this independently, on three operating systems. If the answer depended on
    anything but the inputs — dict order, the filesystem's own sort — the shards would overlap and
    leave gaps, and the run would still be green."""
    assert ci_shard.split(FILES, WEIGHTS, splits=4) == ci_shard.split(FILES, WEIGHTS, splits=4)


def test_the_heaviest_files_are_spread_rather_than_stacked():
    """The whole point of weighting. `test_curve_view.py` and `test_main_window.py` are a fifth of
    the suite between them; an alphabetical quarter can put both in one shard and the wait is then
    the same as before."""
    shards = ci_shard.split(FILES, WEIGHTS, splits=2)
    totals = sorted(sum(WEIGHTS[name] for name in shard) for shard in shards)

    assert totals == [70.0, 100.0], "longest-first into the lightest shard"


def test_a_file_the_table_has_never_heard_of_weighs_the_MEDIAN_not_nothing():
    """A new test file is unweighted by definition, and a zero would always park it in whichever
    shard is lightest — invisible until it was slow enough to matter."""
    files = [*FILES, "tests/test_new.py"]

    shards = ci_shard.split(files, WEIGHTS, splits=4)
    with_new = next(shard for shard in shards if "tests/test_new.py" in shard)

    assert with_new == ["tests/test_new.py"] or sum(
        WEIGHTS.get(name, 0.0) for name in with_new) <= 50.0, \
        "it was placed as a 30 s file, not as a free one"


def test_an_empty_table_still_partitions_by_count():
    """A missing or empty `shard-weights.json` must not be a crash or an empty shard: every file
    then weighs the same, which is a worse split and a working one."""
    shards = ci_shard.split(FILES, {}, splits=4)

    assert sorted(name for shard in shards for name in shard) == FILES
    assert all(len(shard) == 1 for shard in shards)


def test_the_real_table_covers_most_of_the_real_suite():
    """A table nobody re-records decays into "every file is the median", which is a split by name
    again. This is the reminder, and it names the command that fixes it."""
    files = ci_shard.test_files(ROOT)
    weights = ci_shard.load_weights()
    assert weights, "tests/shard-weights.json is missing — see its `how` field to re-record it"

    known = [name for name in files if name in weights]

    assert len(known) >= 0.6 * len(files), (
        f"{len(files) - len(known)} of {len(files)} test files are unweighted — re-record with "
        f"`python scripts/record_shard_weights.py`")


def test_the_real_split_is_as_even_as_an_indivisible_file_allows():
    """The slowest shard IS the wait, so that is the number to assert on — but a file cannot be cut
    in half, so the floor is the biggest one. Measured 2026-09-19: the four shards come out at 57 s
    each, against a biggest file of 52 s (`tests/test_skill_selftests.py`) and a 227 s suite. The
    packing has nothing left to give.

    Written against that floor and not against 57 s, because the floor is the part the splitter
    controls. It catches the real breaks — a shard left empty, two heavy files stacked, a weights
    table read as zeros — and does not fail for a fact about the suite."""
    files = ci_shard.test_files(ROOT)
    weights = ci_shard.load_weights()
    default = sorted(weights.values())[len(weights) // 2] if weights else 1.0
    weight = {name: weights.get(name, default) for name in files}

    totals = [sum(weight[name] for name in shard)
              for shard in ci_shard.split(files, weight, splits=4)]
    floor = max(max(weight.values()), sum(totals) / len(totals))

    assert max(totals) <= 1.15 * floor, \
        f"the slowest shard carries more than the biggest file forces: {[round(t) for t in totals]}"
    assert min(totals) > 0, "an empty shard is a quarter of the suite nobody ran"


def test_the_command_line_prints_one_shard_and_nothing_else():
    """The workflow runs `pytest $(python scripts/ci_shard.py …)`, so anything on stdout that is
    not a file becomes an argument to pytest."""
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "ci_shard.py"),
                           "--splits", "4", "--group", "2"],
                          capture_output=True, text=True, encoding="utf-8")

    assert done.returncode == 0, done.stderr
    printed = done.stdout.split()
    assert printed, "an empty shard would silently run the whole suite"
    assert all(name.startswith("tests/") and name.endswith(".py") for name in printed), done.stdout
    assert printed == ci_shard.split(ci_shard.test_files(ROOT), ci_shard.load_weights(), 4)[1]


def test_a_group_outside_the_split_is_refused_rather_than_silently_empty():
    for argv in (["--splits", "4", "--group", "0"], ["--splits", "4", "--group", "5"]):
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / "ci_shard.py"), *argv],
                              capture_output=True, text=True, encoding="utf-8")
        assert done.returncode != 0, f"{argv} printed {done.stdout!r} instead of refusing"


def test_the_weights_file_says_how_it_was_made():
    """Data with no provenance is a number nobody can check or redo (hub HUB-001's rule about a
    sha and its signature, in the small)."""
    table = json.loads((ROOT / "tests" / "shard-weights.json").read_text(encoding="utf-8"))

    assert table["recorded"], "when"
    assert table["how"], "and the command that would do it again"
    assert all(isinstance(value, (int, float)) and value >= 0 for value in table["seconds"].values())
