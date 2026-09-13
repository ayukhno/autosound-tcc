# Release candidates in `make ship` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `make ship` covers three cases the way the skill does: a beta candidate
(`CANDIDATE=vX.Y.Z`), the next patch, or a named version (`VERSION=vX.Y.Z`). CI also runs on every
push, so the hub's release gate always has a run to read.

**Architecture:**
- `scripts/ship.py` stays the one release script.
- The hub's `release-preflight.py` stays the authority on the channel: tag names, roles, and the
  promote and Breaking rules.
- `ship.py` adds three things:
  - which question it asks that carrier: next patch, candidate, or a named tag, with the role taken
    from `HUB_ROLE`;
  - the CHANGELOG form each mode requires, mirroring the skill's `tag-check.sh`;
  - a candidate path that tags HEAD without writing anything.
- CI loses its `paths-ignore`.

**Tech Stack:**
- Python 3.12 stdlib (argparse, re, subprocess, os);
- pytest, with the existing real-git fixture repo in `tests/test_ship.py`;
- GNU make;
- GitHub Actions YAML.

**Spec:** `docs/superpowers/specs/2026-09-13-release-candidates-design.md`

## Global Constraints

**Order and publishing**
- Every refusal happens before anything is written. One run names every refusal the carrier returned.
- A tag is pushed by name, never with `--tags` or `--follow-tags`. ship never runs `gh release`.
- In every mode ship runs the carrier's own three commands: `git tag <tag>`, `git push origin main`,
  `git push origin <tag>`.

**Hub rules and modes**
- ship keeps no copy of the hub's rules: tag grammar, role rule, promote rule, Breaking rule. A
  malformed `CANDIDATE`/`VERSION` is refused by the carrier's own `tag` check. This amends one spec
  line; Task 3 edits it.
- The role is `os.environ.get("HUB_ROLE") or "tcc"`.
- The Makefile passes `CANDIDATE`/`VERSION` only when they were given on the command line. An
  environment variable of that name does not change the mode.

**Process**
- English in code, comments, commits and docs. A commit-msg hook refuses Cyrillic.
- Tests run with `uv run --extra dev --python 3.12 python -m pytest tests/test_ship.py -q -n 0`.
  Lint with `uvx ruff@0.12.0 check scripts tests`.
- Implementers run their task's test file and ruff, not the whole suite. `make check` runs once, in
  Task 3. Do not edit files while it runs.
- Work on branch `release-candidates` in `/Users/o.yukhno/dev/autosound/tcc`. No push, no merge.

## File Structure

- `scripts/ship.py` — modified:
  - new: `section`, `_filled`, `_read_changelog`, `check_candidate_changelog`, `publish`;
  - changed: `check_changelog` (release form), `check_paired_method(changelog, method_sha, tag)`,
    `channel_checks(..., candidate, version)`, `Plan.mode`, `ship(..., candidate, version)`, `main`
    (`--candidate` / `--tag`).
- `Makefile` — `SHIP_ARGS`, the `ship` recipe, two help lines.
- `tests/test_ship.py` — fixture template, the stand-in helper, new tests.
- `.github/workflows/ci.yml` — header paragraph; `on.push` without `paths-ignore`.
- `CHANGELOG.md` — one preamble paragraph.
- `CLAUDE.md` — two command lines.
- `docs/superpowers/specs/2026-09-13-release-candidates-design.md` — one line amended.

---

### Task 1: The CHANGELOG forms

**Files:**
- Modify: `scripts/ship.py`:
  - add `section`, `_filled`, `_read_changelog` and `check_candidate_changelog` beside `check_changelog` (~183);
  - change `check_changelog` (~183–200) and `check_paired_method` (~203–228);
  - change the one call in `ship()` (~349).
- Test: `tests/test_ship.py`.

**Interfaces:**
- Consumes: nothing new.
- Produces (Task 2 relies on these exact names):
  - `section(text: str, heading: str) -> str | None`
  - `check_changelog(root: Path, tag: str) -> str` — release form; raises `Stop`
  - `check_candidate_changelog(root: Path, version: str) -> None` — raises `Stop`
  - `check_paired_method(changelog: str, method_sha: str, tag: str) -> None`
  - `RELEASE_NOTE_MIN_LINES = 3`

- [ ] **Step 1: Write the failing tests**

In `tests/test_ship.py`, replace the `CHANGELOG` template. A release note now needs 3 non-empty
lines, and the fixture's own entry must stay a valid release:

```python
CHANGELOG = """# Changelog

## [{tag}] — 2026-08-27 · a sentence a person wrote

Paired with method `{sha}`.

- something changed
- and something else
"""

UNRELEASED = """# Changelog

## [Unreleased]

- a candidate carries this

## [v0.1.24] — 2026-08-20 · the one before

Paired with method `{sha}`.

- old
- older
"""
```

Add these tests after `test_a_dry_run_writes_nothing_at_all`:

```python
# ---------------------------------------------------------------- the CHANGELOG, per mode


def test_a_release_refuses_while_unreleased_is_still_there(repo):
    """The skill's rule (tag-check.sh): the notes are renamed to the tag BEFORE it is cut."""
    text = CHANGELOG.format(tag="v0.1.25", sha=METHOD_SHA).replace(
        "# Changelog\n", "# Changelog\n\n## [Unreleased]\n\n- not renamed yet\n")
    (repo / "CHANGELOG.md").write_text(text, encoding="utf-8")

    with pytest.raises(ship_mod.Stop) as stop:
        ship_mod.check_changelog(repo, "v0.1.25")

    assert "rename it to `## [v0.1.25]` first" in str(stop.value)


def test_a_release_entry_shorter_than_three_lines_is_a_forgotten_note(repo):
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [v0.1.25] — 2026-08-27 · short\n\nPaired with method `x`.\n",
        encoding="utf-8")

    with pytest.raises(ship_mod.Stop) as stop:
        ship_mod.check_changelog(repo, "v0.1.25")

    assert "forgotten note" in str(stop.value)


def test_a_candidate_reads_its_notes_from_unreleased(repo):
    (repo / "CHANGELOG.md").write_text(UNRELEASED.format(sha=METHOD_SHA), encoding="utf-8")

    ship_mod.check_candidate_changelog(repo, "v0.2.0")  # no Stop


def test_a_candidate_reads_its_own_section_when_the_version_is_already_named(repo):
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [v0.2.0] — 2026-09-20 · named early\n\n- tried\n", encoding="utf-8")

    ship_mod.check_candidate_changelog(repo, "v0.2.0")  # no Stop


def test_an_empty_unreleased_is_a_forgotten_note_for_a_candidate_too(repo):
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [v0.1.24] — x\n\n- old\n", encoding="utf-8")

    with pytest.raises(ship_mod.Stop) as stop:
        ship_mod.check_candidate_changelog(repo, "v0.2.0")

    assert "forgotten note" in str(stop.value)


def test_a_candidate_with_no_notes_at_all_is_refused(repo):
    # The fixture's CHANGELOG has only `## [v0.1.25]`: neither the version nor Unreleased.
    with pytest.raises(ship_mod.Stop) as stop:
        ship_mod.check_candidate_changelog(repo, "v0.2.0")

    assert "nothing says what the candidate carries" in str(stop.value)


def test_the_paired_line_is_read_from_the_tags_own_section():
    """Not from whatever block happens to be first: an Unreleased section above has no pairing."""
    text = ("# Changelog\n\n## [Unreleased]\n\n- no pairing here\n\n"
            f"## [v0.1.25] — 2026-08-27 · x\n\nPaired with method `{METHOD_SHA}`.\n\n- a\n- b\n")

    ship_mod.check_paired_method(text, METHOD_SHA, "v0.1.25")  # no Stop
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_ship.py -q -n 0`

Expected failures:
- `AttributeError: module 'ship' has no attribute 'check_candidate_changelog'`;
- `TypeError` for `check_paired_method` taking 3 arguments;
- no `Stop` in `test_a_release_refuses_while_unreleased_is_still_there` and in the three-line test.

- [ ] **Step 3: Implement**

In `scripts/ship.py`, directly above `def check_changelog`, add:

```python
#: `## [Unreleased]`, in any case — where a line's notes sit between tags (hub RELEASE-CHANNEL.md
#: §11.5), renamed to the tag in the commit a release is cut from.
_UNRELEASED = re.compile(r"^## \[unreleased\]", re.I | re.M)

#: A release note shorter than this is a forgotten note. The skill's `tag-check.sh` holds the same
#: floor; one rule, two doors, and they should not drift apart.
RELEASE_NOTE_MIN_LINES = 3


def section(text: str, heading: str) -> str | None:
    """The body under `## [heading]`, up to the next `## `; None when there is no such heading."""
    found = re.search(rf"^## \[{re.escape(heading)}\][^\n]*\n(.*?)(?=^## |\Z)", text,
                      re.M | re.S | re.I)
    return found.group(1) if found else None


def _filled(body: str) -> int:
    return sum(1 for line in body.splitlines() if line.strip())


def _read_changelog(root: Path) -> str:
    path = root / "CHANGELOG.md"
    if not path.is_file():
        raise Stop("no CHANGELOG.md")
    return path.read_text(encoding="utf-8")
```

Replace `check_changelog` with:

```python
def check_changelog(root: Path, tag: str) -> str:
    """The top entry must already be this release's.

    A gate, not a convenience. The heading is a sentence about what changed — content, and ship
    does not write content. Requiring it here also means the release notes exist BEFORE the tag
    rather than being written afterwards against a published number.

    So `## [Unreleased]` must be gone by then: the notes gathered under it are renamed to this
    heading, by hand, in the commit the release is cut from — the skill's model (hub
    RELEASE-CHANNEL.md §11.3, `tag-check.sh`).
    """
    text = _read_changelog(root)
    if _UNRELEASED.search(text):
        raise Stop(f"CHANGELOG.md still has a `## [Unreleased]` heading — rename it to `## [{tag}]` "
                   "first; the heading is yours to word, not ship's")
    found = re.search(r"^## \[(v\d+\.\d+\.\d+)\]", text, re.M)
    if not found:
        raise Stop("CHANGELOG.md has no `## [vX.Y.Z]` heading to read")
    if found.group(1) != tag:
        raise Stop(f"CHANGELOG.md's top entry is `{found.group(1)}`, and ship is cutting `{tag}` "
                   f"— write the entry first; its heading is yours to word, not ship's")
    lines = _filled(section(text, tag) or "")
    if lines < RELEASE_NOTE_MIN_LINES:
        raise Stop(f"the `## [{tag}]` entry has {lines} non-empty line(s) — an empty note is a "
                   "forgotten note")
    return text


def check_candidate_changelog(root: Path, version: str) -> None:
    """What a candidate carries: `## [vX.Y.Z]` if the version is already named, else `## [Unreleased]`.

    A candidate writes nothing, so its notes may still sit under `## [Unreleased]`: the release
    commit renames them (hub RELEASE-CHANNEL.md §11.3, the skill's `tag-check.sh --candidate`). They
    must say something all the same — an empty note is a forgotten note for a candidate too.
    """
    text = _read_changelog(root)
    for heading in (version, "Unreleased"):
        body = section(text, heading)
        if body is None:
            continue
        if not _filled(body):
            raise Stop(f"`## [{heading}]` has no entry — an empty note is a forgotten note")
        return
    raise Stop(f"CHANGELOG.md has neither `## [{version}]` nor `## [Unreleased]` — nothing says "
               "what the candidate carries")
```

In `check_paired_method`:
- change the signature to `def check_paired_method(changelog: str, method_sha: str, tag: str) -> None:`;
- replace the two lines `entry = changelog.split("## [", 2)` / `body = entry[1] if len(entry) > 1 else changelog` with:

```python
    body = section(changelog, tag) or ""
```

- change the "no pairing line" refusal to name the entry:

```python
        raise Stop(f"the `## [{tag}]` entry has no `Paired with method` line — a release that "
                   "does not say which method it was built against cannot be reproduced")
```

In `ship()`, change the call to `check_paired_method(changelog, plan.method_sha, plan.tag)`.

- [ ] **Step 4: Run the tests and ruff**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_ship.py -q -n 0`
Expected: all pass. The existing parametrized refusal test still finds "top entry" and
"Paired with method" in its messages.

Run: `uvx ruff@0.12.0 check scripts tests`
Expected: no findings.

- [ ] **Step 5: Commit**

```bash
git add scripts/ship.py tests/test_ship.py
git commit -m "ship: the CHANGELOG form per mode — no Unreleased at release, notes for a candidate"
```

---

### Task 2: Three modes — patch, candidate, named version

**Files:**
- Modify: `scripts/ship.py`:
  - add `import os`;
  - `Plan` gains a `mode` field;
  - change `channel_checks` (~169–177), `ship()` (~318–392) and `main()` (~395–415);
  - add `publish`.
- Modify: `Makefile` — help lines (~13–20), `SHIP_ARGS` plus the `ship` recipe (~52–57).
- Test: `tests/test_ship.py`.

**Interfaces:**
- Consumes (from Task 1): `check_changelog(root, tag) -> str`,
  `check_candidate_changelog(root, version) -> None`,
  `check_paired_method(changelog, method_sha, tag) -> None`.
- Produces:
  - `channel_checks(root: Path, path: Path = CARRIER, *, candidate: str | None = None, version: str | None = None)`
  - `ship(root, release, test_command=None, channel=channel_checks, read_method_sha=method_sha, read_pinned_sha=pinned_method_sha, relock_with=relock, say=print, candidate: str = "", version: str = "") -> Plan`
  - `Plan.mode` in `{"patch", "candidate", "version"}`
  - `publish(root: Path, tag: str, say) -> None`
  - `main(argv)` with the mutually exclusive `--candidate vX.Y.Z` / `--tag vX.Y.Z`
  - Makefile `CANDIDATE=` → `--candidate`, `VERSION=` → `--tag` (command line only)

- [ ] **Step 1: Write the failing tests**

In `tests/test_ship.py`, add `import os` to the imports.

Change the stand-in helper so it takes the mode's question:

```python
def channel(tag="v0.1.25", answers=(("clean-tree", OK), ("rule", OK))):
    """A stand-in for `ship.channel_checks`: the carrier, without the carrier."""
    return lambda _root, **_asked: (tag, checks(*answers))
```

Change `_run` to pass a mode through:

```python
def _run(repo, release=True, test_exit=0, ask=None, say=lambda _m: None, **mode):
```

At its end, add `**mode` to the `ship_mod.ship(...)` call, after `relock_with=_relock, say=say`.

In `test_ship_asks_the_carrier_as_tcc_and_for_the_next_patch`:
- give `Recorder.preflight` the signature `def preflight(self, root, role, tag=None, want_next=False, candidate=None):`;
- record `candidate=candidate` too;
- add `monkeypatch.delenv("HUB_ROLE", raising=False)` before the call;
- add `assert seen["candidate"] is None`.

In `test_the_stand_in_has_the_carriers_shape`, after the verdict-words assertion, add:

```python
    asks = inspect.signature(carrier.preflight).parameters
    assert {"tag", "want_next", "candidate"} <= set(asks), (
        "ship asks the carrier for a patch, a candidate or a named tag; one of those questions is gone")
```

Add these tests after `test_ship_asks_the_carrier_as_tcc_and_for_the_next_patch`:

```python
class _Recorder:
    def __init__(self):
        self.seen = {}

    def preflight(self, root, role, tag=None, want_next=False, candidate=None):
        self.seen.update(root=root, role=role, tag=tag, want_next=want_next, candidate=candidate)
        return "v0.2.0", []


@pytest.mark.parametrize("asked, expect", [
    ({"candidate": "v0.2.0"}, {"candidate": "v0.2.0", "tag": None, "want_next": False}),
    ({"version": "v0.2.0"}, {"candidate": None, "tag": "v0.2.0", "want_next": False}),
    ({}, {"candidate": None, "tag": None, "want_next": True}),
])
def test_each_mode_asks_the_carrier_its_own_question(monkeypatch, tmp_path, asked, expect):
    recorder = _Recorder()
    monkeypatch.setattr(ship_mod, "load_carrier", lambda *_a, **_k: recorder)
    monkeypatch.delenv("HUB_ROLE", raising=False)

    ship_mod.channel_checks(tmp_path, **asked)

    assert {key: recorder.seen[key] for key in expect} == expect
    assert recorder.seen["role"] == "tcc"


def test_the_role_comes_from_the_session_so_release_can_cut_a_minor(monkeypatch, tmp_path):
    """ship does not restate who may cut what: it passes the session's role, and the hook decides."""
    recorder = _Recorder()
    monkeypatch.setattr(ship_mod, "load_carrier", lambda *_a, **_k: recorder)
    monkeypatch.setenv("HUB_ROLE", "release")

    ship_mod.channel_checks(tmp_path, version="v0.2.0")

    assert recorder.seen["role"] == "release"


def _write_changelog(repo, text):
    """Commit and publish a CHANGELOG — the state a release is cut from."""
    (repo / "CHANGELOG.md").write_text(text, encoding="utf-8")
    git(repo, "commit", "--quiet", "-am", "changelog")
    git(repo, "push", "--quiet", "origin", "main")


def test_a_candidate_dry_run_names_the_beta_tag_and_writes_nothing(repo):
    _write_changelog(repo, UNRELEASED.format(sha=METHOD_SHA))
    before = git(repo, "rev-parse", "HEAD")

    plan = _run(repo, release=False, ask=channel(tag="beta-v0.2.0-rc1"), candidate="v0.2.0")

    assert (plan.mode, plan.tag) == ("candidate", "beta-v0.2.0-rc1")
    assert plan.commands == ["git tag beta-v0.2.0-rc1", "git push origin main",
                             "git push origin beta-v0.2.0-rc1"]
    assert git(repo, "rev-parse", "HEAD") == before
    assert git(repo, "tag", "--list", "beta-v0.2.0-rc1") == ""


def test_a_candidate_tags_head_pushes_the_tag_and_writes_nothing_else(repo):
    _write_changelog(repo, UNRELEASED.format(sha=METHOD_SHA))
    before = git(repo, "rev-parse", "HEAD")
    lock = (repo / "uv.lock").read_text(encoding="utf-8")

    # A red suite stops a release; here it proves that no suite runs for a candidate at all.
    _run(repo, test_exit=1, ask=channel(tag="beta-v0.2.0-rc1"), candidate="v0.2.0")

    assert git(repo, "rev-parse", "HEAD") == before, "no commit"
    assert git(repo, "rev-parse", "beta-v0.2.0-rc1^{commit}") == before, "the tag is on HEAD"
    assert "refs/tags/beta-v0.2.0-rc1" in git(repo, "ls-remote", "--tags", "origin"), "published"
    assert 'version = "0.1.24"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert (repo / "uv.lock").read_text(encoding="utf-8") == lock


def test_a_candidate_without_notes_stops_before_the_tag(repo):
    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo, ask=channel(tag="beta-v0.2.0-rc1"), candidate="v0.2.0")

    assert "nothing says what the candidate carries" in str(stop.value)
    assert git(repo, "tag", "--list", "beta-v0.2.0-rc1") == ""


def test_a_patch_with_unreleased_on_top_stops_before_anything_is_written(repo):
    _write_changelog(repo, CHANGELOG.format(tag="v0.1.25", sha=METHOD_SHA).replace(
        "# Changelog\n", "# Changelog\n\n## [Unreleased]\n\n- not renamed yet\n"))

    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo)

    assert "rename it to" in str(stop.value)
    assert 'version = "0.1.24"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert git(repo, "tag", "--list", "v0.1.25") == ""


def test_an_explicit_version_releases_like_a_patch(repo):
    seen = {}

    def ask(_root, **asked):
        seen.update(asked)
        return "v0.1.25", checks(("clean-tree", OK), ("rule", OK))

    plan = _run(repo, ask=ask, version="v0.1.25")

    assert seen == {"candidate": None, "version": "v0.1.25"}
    assert plan.mode == "version"
    assert git(repo, "tag", "--list", "v0.1.25") == "v0.1.25"
    assert 'version = "0.1.25"' in (repo / "pyproject.toml").read_text(encoding="utf-8")


def test_candidate_and_version_exclude_each_other(repo):
    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo, candidate="v0.2.0", version="v0.2.0")

    assert "exclude each other" in str(stop.value)


def test_the_command_line_takes_one_mode(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(ship_mod, "ship", lambda root, **kw: seen.update(kw))

    assert ship_mod.main(["--root", str(tmp_path), "--candidate", "v0.2.0"]) == 0
    assert (seen["candidate"], seen["version"], seen["release"]) == ("v0.2.0", "", False)

    with pytest.raises(SystemExit) as usage:
        ship_mod.main(["--candidate", "v0.2.0", "--tag", "v0.2.0"])
    assert usage.value.code == 2


@pytest.mark.skipif(shutil.which("make") is None, reason="no make on this machine")
@pytest.mark.parametrize("assignment, flag", [
    ("CANDIDATE=v0.2.0", "--candidate v0.2.0"),
    ("VERSION=v0.2.0", "--tag v0.2.0"),
])
def test_make_ship_passes_the_mode_to_the_script(assignment, flag):
    for extra in ([], ["REAL=1"]):
        done = subprocess.run(["make", "-n", "ship", assignment, *extra], cwd=str(ROOT),
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        assert flag in done.stdout, done.stdout


@pytest.mark.skipif(shutil.which("make") is None, reason="no make on this machine")
def test_a_version_in_the_environment_does_not_change_the_mode():
    """`VERSION` is a common enough variable name that a shell may carry one; only a word typed
    after `make ship` may turn a patch into a named release."""
    done = subprocess.run(["make", "-n", "ship"], cwd=str(ROOT), capture_output=True, text=True,
                          env={**os.environ, "VERSION": "v9.9.9", "CANDIDATE": "v9.9.9"})
    assert done.returncode == 0, done.stderr
    assert "--tag" not in done.stdout and "--candidate" not in done.stdout, done.stdout
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_ship.py -q -n 0`

Expected failures:
- `TypeError: ship() got an unexpected keyword argument 'candidate'`;
- `TypeError` from `channel_checks` for the `candidate` and `version` keywords;
- `AttributeError` for `plan.mode`;
- the make tests fail to find `--candidate`.

- [ ] **Step 3: Implement**

In `scripts/ship.py`, add `import os` beside the other imports.

In `Plan`, add a field after `root`:

```python
    mode: str = "patch"
```

Replace `channel_checks` with:

```python
def channel_checks(root: Path, path: Path = CARRIER, *, candidate: str | None = None,
                   version: str | None = None):
    """Every channel precondition, asked of the carrier. Returns `(tag, checks)`, writes nothing.

    One question per mode: the next patch, the next candidate for `candidate`, or the named
    `version`. The carrier names the tag in the first two and judges it in all three — including
    whether `candidate` or `version` looks like a version at all; ship keeps no copy of that pattern.

    The role is the session's (`HUB_ROLE`), and `tcc` when there is none. It decides which
    repository and line the carrier reports on and which tags the hook lets this session cut: a
    minor is the `release` role's. ship does not restate that rule; it passes the role on.
    """
    role = os.environ.get("HUB_ROLE") or "tcc"
    carrier = load_carrier(path)
    if candidate:
        return carrier.preflight(root, role=role, candidate=candidate)
    if version:
        return carrier.preflight(root, role=role, tag=version)
    return carrier.preflight(root, role=role, want_next=True)
```

Add directly above `def ship`:

```python
def publish(root: Path, tag: str, say: Callable[[str], None]) -> None:
    """Tag HEAD and publish that one tag by name — the last act of every mode."""
    run(["git", "tag", tag], root)
    say(f"  tagged {tag} (still local — `git tag -d {tag}` undoes it)")
    run(["git", "push", "origin", "main"], root)
    # The one irreversible line in this file. By NAME, never `--tags`: a bulk push has no target
    # in the command, and a published tag cannot be moved or removed by anybody afterwards.
    run(["git", "push", "origin", tag], root)
    say(f"  pushed {tag}")
```

Replace `ship()` with the version below. The bump / relock / suite / commit block is unchanged
from today's code.

```python
def ship(root: Path, release: bool, test_command=None,
         channel: Callable[..., tuple] = channel_checks,
         read_method_sha: Callable[[Path], str] = method_sha,
         read_pinned_sha: Callable[[Path], str] = pinned_method_sha,
         relock_with: Callable[[Path], None] = relock,
         say: Callable[[str], None] = print,
         candidate: str = "", version: str = "") -> Plan:
    """The whole thing. Reads and decides first; writes only when `release` is true.

    Three modes, the skill's model (hub RELEASE-CHANNEL.md §11): the next patch; a candidate for
    `candidate`, which writes nothing and tags HEAD `beta-vX.Y.Z-rcN`; a named `version`, released
    the way a patch is.
    """
    if candidate and version:
        raise Stop("CANDIDATE and VERSION exclude each other — one run cuts one tag")
    plan = Plan(root=root, mode="candidate" if candidate else "version" if version else "patch")

    tag, checks = channel(root, candidate=candidate or None, version=version or None)
    say("  channel preflight — hub/scripts/release-preflight.py:")
    for check in checks:
        # The carrier's own verdicts and sentences, not a translation of them: rewording somebody
        # else's refusal is how the wording drifts from what they actually said.
        say(f"    {check.verdict:<12} {check.name:<34} {check.line}")
    refused = [check for check in checks if check.gates]
    if refused:
        raise Stop(f"the channel preflight refuses this release — {len(refused)} of "
                   f"{len(checks)}:\n"
                   + "\n".join(f"    {check.name}: {check.line}" for check in refused))
    if not tag:
        # Belt: the carrier returns no tag only alongside a refusal, and ship invents no number.
        raise Stop("the channel preflight worked out no tag and refused nothing — ask it "
                   "directly before shipping")
    plan.tag = tag

    if plan.mode == "candidate":
        check_candidate_changelog(root, candidate)
    else:
        plan.version = tag.lstrip("v")
        changelog = check_changelog(root, plan.tag)

    plan.method_sha = read_method_sha(root)
    check_method_pin(read_pinned_sha(root), plan.method_sha)
    if plan.mode != "candidate":
        check_paired_method(changelog, plan.method_sha, plan.tag)

    # The three lines that will actually run. The carrier builds the SAME three to put in front
    # of the hook, from its own literal — so an edit here that is not made there would leave the
    # oracle vouching for lines nobody runs. Pinned on this side by
    # `test_ship_never_pushes_in_BULK_and_never_releases`; the other side is the hub's.
    plan.commands = [
        f"git tag {plan.tag}",
        "git push origin main",
        f"git push origin {plan.tag}",
    ]

    say(f"  {plan.mode:<17}: {plan.tag}")
    say(f"  method           : {plan.method_sha[:12] or '(unknown)'}")

    if not release:
        again = {"candidate": f" CANDIDATE={candidate}",
                 "version": f" VERSION={version}"}.get(plan.mode, "")
        say(f"\n  DRY RUN — nothing was written. Real run: make ship{again} REAL=1")
        return plan

    if plan.mode == "candidate":
        # Nothing to bump and nothing new to test: the tree being tagged is HEAD, and the carrier
        # has already refused a HEAD that is unpublished or whose CI is not green.
        publish(root, plan.tag, say)
        return plan

    was = bump(root, plan.version)
    relock_with(root)
    say(f"\n  version {was} -> {plan.version}")
    say("  running the suite…")
    done = subprocess.run(test_command or TEST_COMMAND, cwd=str(root))
    if done.returncode != 0:
        bump(root, was)
        relock_with(root)
        raise Stop(f"the suite failed ({done.returncode}) — the version bump was rolled back "
                   "and nothing was committed")

    files = ["pyproject.toml", "CHANGELOG.md"]
    if tracked(root, "uv.lock"):
        files.append("uv.lock")
    run(["git", "add", *files], root)
    run(["git", "commit", "-m", f"{plan.tag}: paired with method {plan.method_sha[:12]}"], root)
    say(f"  committed {plan.tag}")
    publish(root, plan.tag, say)
    return plan
```

Replace `main()`'s parser block with:

```python
    parser = argparse.ArgumentParser(
        description="Cut a release: the next patch, a beta candidate, or a named version.")
    parser.add_argument("--release", action="store_true",
                        help="actually write, commit, tag and push (default: dry run)")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--candidate", metavar="vX.Y.Z", default="",
                      help="the next beta candidate for this version (beta-vX.Y.Z-rcN, named by "
                           "the hub); writes nothing but the tag")
    mode.add_argument("--tag", metavar="vX.Y.Z", default="",
                      help="release this version instead of the next patch; the hub decides "
                           "whether this role may")
    args = parser.parse_args(argv)
```

In the same function, change the call to:
`ship(root, release=args.release, candidate=args.candidate, version=args.tag)`.

In `Makefile`, after the `@echo "make ship REAL=1 …"` help line, add:

```make
	@echo "make ship CANDIDATE=vX.Y.Z   dry run of a beta candidate (beta-vX.Y.Z-rcN on HEAD); REAL=1 tags it"
	@echo "make ship VERSION=vX.Y.Z     dry run of a named release instead of the next patch; REAL=1 cuts it"
```

Replace the `ship:` recipe with:

```make
#: The mode, from the command line only — `VERSION` is a common enough name that a shell may carry
#: one, and an environment variable must not turn a patch into something else.
#: `CANDIDATE=vX.Y.Z` cuts the next beta candidate for that version and writes nothing but the tag;
#: `VERSION=vX.Y.Z` releases that version instead of the next patch (a minor is the `release`
#: role's — the hub decides, from HUB_ROLE).
SHIP_ARGS = $(if $(filter command line,$(origin CANDIDATE)),--candidate $(CANDIDATE)) \
            $(if $(filter command line,$(origin VERSION)),--tag $(VERSION))

ship:
ifeq ($(REAL),1)
	$(PY) scripts/ship.py --release $(SHIP_ARGS)
else
	$(PY) scripts/ship.py $(SHIP_ARGS)
endif
```

If any existing test asserts the old `next patch       :` line, update it to the new
`patch            : v0.1.25` form. The mode word is padded to 17 characters.

- [ ] **Step 4: Run the tests and ruff**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_ship.py -q -n 0`
Expected: all pass. `test_the_stand_in_has_the_carriers_shape` runs when the hub is beside the
tree, and skips loudly otherwise.

Run: `uvx ruff@0.12.0 check scripts tests`
Expected: no findings.

- [ ] **Step 5: Commit**

```bash
git add scripts/ship.py Makefile tests/test_ship.py
git commit -m "make ship: CANDIDATE= tags HEAD as the next beta candidate, VERSION= releases a named version"
```

---

### Task 3: CI on every push, the docs, and the whole suite

**Files:**
- Modify: `.github/workflows/ci.yml` — lines 9–15 (header paragraph) and 20–24 (`paths-ignore` with its comment).
- Modify: `CHANGELOG.md` — a preamble paragraph before `## [v0.1.38]`.
- Modify: `CLAUDE.md` — after line 11.
- Modify: `docs/superpowers/specs/2026-09-13-release-candidates-design.md` — the "Arguments" bullet.
- Test: `tests/test_ship.py`.

**Interfaces:**
- Consumes: nothing from Tasks 1–2 in code. The docs describe their modes.
- Produces: nothing later tasks rely on.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ship.py`, after `test_no_pytest_caller_carries_its_own_distribution_flags`:

```python
def test_ci_runs_on_every_push_so_the_release_gate_has_a_run_to_read():
    """HUB-057 made green CI on HEAD a condition of every tag, and the commit a release starts from
    is a CHANGELOG commit by construction — a path filter would leave it with no run (hub #136)."""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    triggers = text.split("\non:\n", 1)[1].split("\njobs:\n", 1)[0]

    assert "paths-ignore" not in triggers and "paths:" not in triggers
    assert "NOT a release gate" not in text, "the header still says CI holds no tag back"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_ship.py -q -n 0 -k ci_runs_on_every_push`
Expected: FAIL on `"paths-ignore" not in triggers`.

- [ ] **Step 3: Edit the workflow, the CHANGELOG, CLAUDE.md and the spec**

`.github/workflows/ci.yml` — replace the three comment paragraphs from `# NOT a release gate.`
through `# with no way to merge. Whoever makes this a gate has to drop \`paths-ignore\` in the same change.`
with:

```yaml
# A release gate since HUB-057. The hub's `release-preflight.py`, which `scripts/ship.py` calls,
# refuses a tag unless CI on HEAD is green: red, still running, or no run on the sha all refuse.
# So every push runs, prose included -- the commit a release starts from is a CHANGELOG commit by
# construction, and a path filter would leave it with no run to read (HUB-058, hub #136).
```

In the same file, replace

```yaml
  push:
    # Prose does not warm three runners. Narrow on purpose: `pyproject.toml`, `uv.lock` and
    # `.github/**` are NOT ignored, so a dependency bump or an edit to this file still runs.
    paths-ignore:
      - "docs/**"
      - "**.md"
  pull_request:
```

with

```yaml
  push:
  pull_request:
```

`CHANGELOG.md` — after the intro paragraph that ends with
`differ, and the newer of them is the fresh install.`, add one blank line and this paragraph (the
blank line before `## [v0.1.38]` stays):

```markdown
Between tags, what has landed is written under `## [Unreleased]` at the top. In the commit a release
is cut from, that heading is renamed to `## [vX.Y.Z] — date · title`, with its `Paired with method`
line. The heading is written by hand; `make ship` only checks it. A `### Breaking` section marks a
change the user must act on, and such a change is not a patch. A candidate, `beta-vX.Y.Z-rcN`, is
tagged from the Unreleased notes with `make ship CANDIDATE=vX.Y.Z` and reaches only a beta channel.
```

`CLAUDE.md` — directly after line 11
(`make ship                                     # dry run: works out the next patch, writes nothing`),
add these two lines. Their `#` sits in the same column as line 11's:

```
make ship CANDIDATE=vX.Y.Z                    # dry run of a beta candidate; REAL=1 tags HEAD, writes nothing else
make ship VERSION=vX.Y.Z                      # dry run of a named release (a minor is the release role's)
```

`docs/superpowers/specs/2026-09-13-release-candidates-design.md` — replace

```markdown
- **Arguments:** `CANDIDATE` and `VERSION` exclude each other, and each must look like `vX.Y.Z`.
  `ship.py` refuses a malformed value before asking the hub.
```

with

```markdown
- **Arguments:** `CANDIDATE` and `VERSION` exclude each other, and only a value given on the
  command line counts. A malformed value is refused by the carrier's own `tag` check: ship keeps no
  copy of the version pattern (HUB-003).
```

- [ ] **Step 4: Run the test file and ruff, then the whole suite once**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_ship.py -q -n 0`
Expected: all pass.

Run: `uvx ruff@0.12.0 check scripts tests`
Expected: no findings.

Run: `make check`
- It takes about 10 minutes. Give it a timeout of at least 15 minutes, or run it in the background
  and wait for its exit code.
- Do not edit files while it runs.
- Expected: exit 0, ruff clean, and a pytest summary with `0 failed`.
- Record that summary line exactly in the report.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml CHANGELOG.md CLAUDE.md docs/superpowers/specs/2026-09-13-release-candidates-design.md tests/test_ship.py
git commit -m "CI runs on every push so the release gate has a run to read (hub #136); docs for the ship modes"
```
