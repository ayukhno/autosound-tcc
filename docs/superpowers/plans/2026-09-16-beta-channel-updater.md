# Beta channel in the updater (TCC's own half) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A beta checkbox in Diagnostics → Installation that makes TCC's own update row also offer `beta-vX.Y.Z-rcN` candidates, ordered and compared the way hub RELEASE-CHANNEL.md §11.2 says.

**Architecture:** `core/updates.py` stays Qt-free and takes the channel as a parameter; the GUI thread reads it through `config` (QSettings) and `install_report.requested_revision()`. On beta TCC is compared by commit, because a candidate's metadata can carry another version. The method half is NOT in this plan: it keeps following released tags on both channels until the Arbiter decides how the project link behaves (hub #145 answer, `installation.md` "Two channels on one machine").

**Tech Stack:** Python 3.12, PySide6, pytest, `git ls-remote`, uv `direct_url.json`.

**Spec:** `docs/superpowers/specs/2026-09-13-beta-channel-updater-design.md` (§1–§5, §7, §8 for TCC; §6 and the method part of §5 excluded — see its "The method on beta" section).

## Global Constraints

- Channel values: `stable` (default) and `beta`; anything else reads as `stable`. QSettings key `updates/channel`.
- Globs, identical to the method's installers: `TCC_TAG_GLOB = "v*"`, `TCC_BETA_GLOB = "beta-v*"`.
- Sort key: release `vX.Y.Z` → `(X, Y, Z, 1, 0)`; candidate `beta-vX.Y.Z-rcN` → `(X, Y, Z, 0, N)`; any other name dropped.
- Stable is unchanged to the letter: same `ls-remote` arguments, same `_version_key` ordering, existing tests untouched except stand-ins that must now accept a `channel` argument.
- An app installed from a `beta-v*` tag whose setting was never set starts on beta (the Arbiter, 2026-09-14). The checkbox is otherwise unchecked.
- Nothing raises; an unanswerable question is "unknown", never "up to date".
- Tests serial (`-n 0`) and targeted per task; the full suite once at the end of the wave, not here.
- Commits on the wave branch `wave-0.1.40`, English subject lines.

---

### Task 1: Beta listing and order in `updates.py`

**Files:**
- Modify: `src/autosound_tcc/core/updates.py:45-58` (constants), `:183-231` (`_version_key`, `_newest_tag_in`, `newest_tcc_tag`)
- Test: `tests/test_updates.py`

**Interfaces:**
- Produces: `updates.STABLE = "stable"`, `updates.BETA = "beta"`, `updates.TCC_BETA_GLOB = "beta-v*"`, `updates.channel_key(name: str) -> Optional[tuple[int, int, int, int, int]]`, `updates._newest_tag_in(repo: str, *globs: str, key=_version_key) -> tuple[str, str]`, `updates.newest_tcc_tag(channel: str = STABLE) -> str`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_updates.py`:

```python
@pytest.mark.parametrize("name, expected", [
    ("v3.1.0", (3, 1, 0, 1, 0)),
    ("beta-v3.1.0-rc2", (3, 1, 0, 0, 2)),
    ("v3.1.1-foo", None),
    ("beta-v3.1.0", None),
    ("3.1.0", None),
])
def test_channel_keys(name, expected):
    assert updates.channel_key(name) == expected


def test_the_beta_order_is_the_installers_own():
    """Hub RELEASE-CHANNEL.md §11.2 — the cases the method's `newest_on_channel` is held to."""
    key = updates.channel_key
    assert key("v3.1.0") > key("beta-v3.1.0-rc2"), "a release above its own candidates"
    assert key("beta-v3.1.0-rc10") > key("beta-v3.1.0-rc2"), "rc10 above rc2"
    assert key("beta-v3.1.0-rc1") > key("v3.0.49"), "a candidate for 3.1.0 above 3.0.49"


def test_beta_lists_releases_and_candidates_each_with_its_own_peel(monkeypatch):
    calls = _git_answers(monkeypatch, {"ls-remote": (True, "\n".join([
        f"{_HERE}\trefs/tags/v0.1.39",
        f"{_THERE}\trefs/tags/beta-v0.1.40-rc2",
        f"{'c' * 40}\trefs/tags/beta-v0.1.40-rc10",
        f"{'d' * 40}\trefs/tags/beta-v0.1.40-rc10^{{}}",
    ]))})

    assert updates._newest_tag_in(
        updates.TCC_REPO, updates.TCC_TAG_GLOB, updates.TCC_BETA_GLOB, key=updates.channel_key,
    ) == ("beta-v0.1.40-rc10", "d" * 40), "the newest by the key, and the peeled commit wins"
    assert calls[-1][-4:] == ("v*", "v*^{}", "beta-v*", "beta-v*^{}")
    assert updates.newest_tcc_tag(updates.BETA) == "beta-v0.1.40-rc10"


def test_stable_still_asks_for_releases_only(monkeypatch):
    calls = _git_answers(monkeypatch, {"ls-remote": (True, f"{_HERE}\trefs/tags/v0.1.39")})

    assert updates.newest_tcc_tag() == "v0.1.39"
    assert calls[-1] == ("ls-remote", "--tags", updates.TCC_REPO, "v*", "v*^{}")
```

And in `test_our_installer_constants_agree_with_the_installers_own`, after the `TCC_TAG_GLOB` assertion:

```python
    assert theirs.get("TCC_BETA_GLOB") == updates.TCC_BETA_GLOB
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_updates.py -q -n 0`
Expected: FAIL — `AttributeError: module 'autosound_tcc.core.updates' has no attribute 'channel_key'` (and `BETA`, `TCC_BETA_GLOB`).

- [ ] **Step 3: Implement** — in `updates.py`, after `TCC_TAG_GLOB = "v*"`:

```python
#: The beta channel's own tags (hub RELEASE-CHANNEL.md §11.1). The first letter keeps them out of
#: `v*`, so a stable installation never sees one; the method's installers carry the same value
#: (`installer-consistency.py --print TCC_BETA_GLOB`).
TCC_BETA_GLOB = "beta-v*"

#: The two channels (§11.2). Anything else a setting could hold reads as stable.
STABLE = "stable"
BETA = "beta"
```

Replace `_newest_tag_in` and `newest_tcc_tag`, and add `channel_key` after `_version_key`:

```python
_RELEASE_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
_CANDIDATE_RE = re.compile(r"beta-v(\d+)\.(\d+)\.(\d+)-rc(\d+)")


def channel_key(name: str) -> Optional[tuple[int, int, int, int, int]]:
    """The order on the beta channel (hub RELEASE-CHANNEL.md §11.2); None for a name of neither shape.

    A release `vX.Y.Z` is `(X, Y, Z, 1, 0)` and a candidate `beta-vX.Y.Z-rcN` is `(X, Y, Z, 0, N)`:
    a release above its own candidates, candidates of one version by N — `rc10` above `rc2`, which
    a string compare gets wrong — and a candidate for 3.1.0 above 3.0.49. The same key as the
    method's installers (`newest_on_channel`, HUB-060), so the app and `install.sh --channel beta`
    agree on what "newest" is.
    """
    if match := _RELEASE_RE.fullmatch(name):
        return (int(match[1]), int(match[2]), int(match[3]), 1, 0)
    if match := _CANDIDATE_RE.fullmatch(name):
        return (int(match[1]), int(match[2]), int(match[3]), 0, int(match[4]))
    return None


def _newest_tag_in(repo: str, *globs: str, key=_version_key) -> tuple[str, str]:
    """The newest tag matching any of `globs` in `repo`, and the COMMIT it names. `("", "")` if unaskable.

    (keep the existing docstring body from "**No `--refs`…" to "…bring back the very bug above.")

    Several globs are one `ls-remote`, each with its own peel pattern, for the same reason. `key`
    orders the names and drops the ones it returns None for — the beta channel passes
    `channel_key`; stable keeps `_version_key`, which drops nothing.
    """
    patterns = [pattern for glob in globs for pattern in (glob, f"{glob}^{{}}")]
    ok, out = _git("ls-remote", "--tags", repo, *patterns)
    if not ok or not out:
        return "", ""
    shas: dict[str, str] = {}
    for line in out.splitlines():
        sha, _tab, ref = line.partition("\t")
        if "/" not in ref:
            continue
        name = ref.rsplit("/", 1)[-1]
        peeled = name.endswith("^{}")
        name = name[:-3] if peeled else name
        if peeled or name not in shas:
            shas[name] = sha.strip()
    ranked = {name: sha for name, sha in shas.items() if key(name) is not None}
    if not ranked:
        return "", ""
    newest = max(ranked, key=key)
    return newest, ranked[newest]


def newest_tcc_tag(channel: str = STABLE) -> str:
    """The newest tag of TCC itself on `channel` — a release, or on beta possibly a candidate — or ""."""
    if channel == BETA:
        return _newest_tag_in(TCC_REPO, TCC_TAG_GLOB, TCC_BETA_GLOB, key=channel_key)[0]
    return _newest_tag_in(TCC_REPO, TCC_TAG_GLOB)[0]
```

- [ ] **Step 4: Run the tests and ruff**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_updates.py -q -n 0` → PASS (all, old and new)
Run: `uvx ruff@0.12.0 check src/autosound_tcc/core/updates.py tests/test_updates.py` → `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/core/updates.py tests/test_updates.py
git commit -m "Updater: beta listing and order for TCC's own tags (hub #140)"
```

---

### Task 2: TCC compared by commit on beta; a candidate build names itself

**Files:**
- Modify: `src/autosound_tcc/core/install_report.py:130-148` (`install_source`), `:308-323` (`_app`)
- Modify: `src/autosound_tcc/core/updates.py:306-340` (`check_tcc`, `check_all`)
- Test: `tests/test_install_report.py`, `tests/test_updates.py`

**Interfaces:**
- Consumes: `updates.BETA`, `updates.TCC_BETA_GLOB`, `updates.channel_key`, `updates._newest_tag_in(repo, *globs, key=)` from Task 1.
- Produces: `install_report.requested_revision() -> str`, `install_report.shown_version(version: str, revision: str) -> str`, `updates.check_tcc(channel: str = STABLE) -> Status`, `updates.check_all(channel: str = STABLE) -> tuple[Status, Status]`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_install_report.py`:

```python
class _Dist:
    """A stand-in for `importlib.metadata.distribution(...)` holding one `direct_url.json`."""

    def __init__(self, text):
        self._text = text

    def read_text(self, name):
        return self._text if name == "direct_url.json" else None


def test_the_ref_a_package_was_installed_at_is_read_from_direct_url(monkeypatch):
    """uv writes the ref beside the commit (uv 0.12.3, measured 2026-09-16, `@v0.1.39`)."""
    raw = ('{"url":"https://github.com/ayukhno/autosound-tcc","vcs_info":{"vcs":"git",'
           '"commit_id":"6ad4f82bb4ad694fb333c17cf63a8c0981000034","requested_revision":"v0.1.39"}}')
    monkeypatch.setattr(install_report, "distribution", lambda name: _Dist(raw))

    assert install_report.requested_revision() == "v0.1.39"
    assert install_report.install_source() == (
        "https://github.com/ayukhno/autosound-tcc", "6ad4f82bb4ad694fb333c17cf63a8c0981000034")

    monkeypatch.setattr(install_report, "distribution", lambda name: _Dist(None))
    assert install_report.requested_revision() == ""
    assert install_report.install_source() == ("", "")


def test_a_candidate_build_says_which_candidate_it_is():
    assert install_report.shown_version("0.1.38", "beta-v0.2.0-rc1") == "0.1.38 (beta-v0.2.0-rc1)"
    assert install_report.shown_version("0.1.39", "v0.1.39") == "0.1.39"
    assert install_report.shown_version("0.1.39", "") == "0.1.39"


def test_the_installation_block_names_the_candidate(monkeypatch):
    monkeypatch.setattr(install_report, "install_source", lambda: ("git+…", "a" * 40))
    monkeypatch.setattr(install_report, "requested_revision", lambda: "beta-v0.2.0-rc1")
    monkeypatch.setattr(install_report, "_package_version",
                        lambda name: "0.1.38" if name == "autosound-tcc" else "")

    assert install_report._app().items[0].value == "0.1.38 (beta-v0.2.0-rc1)"
```

Append to `tests/test_updates.py`:

```python
_RC1, _RC2, _REL = "1" * 40, "2" * 40, "3" * 40


def _tcc_installed(monkeypatch, version: str, commit: str, revision: str = ""):
    monkeypatch.setattr(install_report, "app_version", lambda: version)
    monkeypatch.setattr(install_report, "install_source", lambda: ("u", commit))
    monkeypatch.setattr(install_report, "requested_revision", lambda: revision)


def _tcc_tags(monkeypatch, *lines: str):
    _git_answers(monkeypatch, {"ls-remote": (True, "\n".join(lines))})


def test_on_beta_the_installed_candidate_is_current(monkeypatch):
    """A candidate writes nothing, so rc1 can say 0.1.38. By version it would be offered to itself
    forever; by commit it is what it is."""
    _tcc_installed(monkeypatch, "0.1.38", _RC1, "beta-v0.2.0-rc1")
    _tcc_tags(monkeypatch, f"{_HERE}\trefs/tags/v0.1.38", f"{_RC1}\trefs/tags/beta-v0.2.0-rc1")

    status = updates.check_tcc(updates.BETA)

    assert status.newer is False
    assert status.installed == "0.1.38 (beta-v0.2.0-rc1)"
    assert status.latest == "0.2.0-rc1"


def test_on_beta_the_next_candidate_and_then_the_release_are_newer(monkeypatch):
    _tcc_installed(monkeypatch, "0.1.38", _RC1, "beta-v0.2.0-rc1")
    _tcc_tags(monkeypatch, f"{_RC1}\trefs/tags/beta-v0.2.0-rc1",
              f"{_RC2}\trefs/tags/beta-v0.2.0-rc2")
    status = updates.check_tcc(updates.BETA)
    assert status.newer is True and status.latest == "0.2.0-rc2"

    _tcc_tags(monkeypatch, f"{_RC2}\trefs/tags/beta-v0.2.0-rc2", f"{_REL}\trefs/tags/v0.2.0")
    status = updates.check_tcc(updates.BETA)
    assert status.newer is True and status.latest == "0.2.0", "the release is cut on its candidates"


def test_on_beta_the_release_once_installed_is_current(monkeypatch):
    _tcc_installed(monkeypatch, "0.2.0", _REL, "v0.2.0")
    _tcc_tags(monkeypatch, f"{_RC2}\trefs/tags/beta-v0.2.0-rc2", f"{_REL}\trefs/tags/v0.2.0")

    status = updates.check_tcc(updates.BETA)

    assert status.newer is False
    assert status.installed == "0.2.0", "a release shows its version alone"


def test_on_beta_a_build_ahead_of_the_newest_tag_is_not_sent_back(monkeypatch):
    _tcc_installed(monkeypatch, "0.2.1", "e" * 40)
    _tcc_tags(monkeypatch, f"{_REL}\trefs/tags/v0.2.0")

    status = updates.check_tcc(updates.BETA)

    assert status.newer is False and status.latest == "0.2.1"


def test_on_beta_a_candidate_already_carrying_its_version_is_offered_the_next(monkeypatch):
    """Waves commit the version before the tag (hub #148), so rc1 can already say 0.2.0 — equal to
    the newest tag's X.Y.Z is not ahead of it."""
    _tcc_installed(monkeypatch, "0.2.0", _RC1, "beta-v0.2.0-rc1")
    _tcc_tags(monkeypatch, f"{_RC1}\trefs/tags/beta-v0.2.0-rc1",
              f"{_RC2}\trefs/tags/beta-v0.2.0-rc2")

    assert updates.check_tcc(updates.BETA).newer is True


def test_on_beta_an_unreachable_github_is_not_up_to_date(monkeypatch):
    _tcc_installed(monkeypatch, "0.1.38", _RC1)
    _git_answers(monkeypatch, {"ls-remote": (False, "fatal: unable to access")})

    status = updates.check_tcc(updates.BETA)

    assert (status.newer, status.latest, status.reason) == (False, "", "no_network")


def test_check_all_hands_the_channel_to_tcc_and_not_to_the_method(monkeypatch):
    seen = []
    monkeypatch.setattr(updates, "check_tcc", lambda channel="stable": seen.append(channel) or "t")
    monkeypatch.setattr(updates, "check_skill", lambda: "s")

    assert updates.check_all(updates.BETA) == ("t", "s")
    assert seen == ["beta"]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_install_report.py tests/test_updates.py -q -n 0`
Expected: FAIL — `requested_revision` / `shown_version` missing; `check_tcc() takes 0 positional arguments but 1 was given`.

- [ ] **Step 3: Implement** — `install_report.py`, replace `install_source` and add two functions after it:

```python
def _direct_url() -> dict:
    """The installed package's `direct_url.json`, `{}` when there is none or it cannot be read."""
    try:
        raw = distribution("autosound-tcc").read_text("direct_url.json")
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — a checkout has no direct_url.json, which is itself an answer
        return {}


def install_source() -> tuple[str, str]:
    """(keep the existing docstring)"""
    data = _direct_url()
    return str(data.get("url") or ""), str((data.get("vcs_info") or {}).get("commit_id") or "")


def requested_revision() -> str:
    """The ref the package was installed AT — `v0.1.39`, `beta-v0.2.0-rc1` — or "".

    uv writes it beside the commit when the URL names one (uv 0.12.3, measured 2026-09-16). A
    candidate is a tag on a commit whose metadata may still carry the release before it (hub
    RELEASE-CHANNEL.md §11.3), so this is where a candidate build says which candidate it is, and
    what `updates.channel_for` reads to start an app installed from one on beta.
    """
    return str((_direct_url().get("vcs_info") or {}).get("requested_revision") or "")


def shown_version(version: str, revision: str) -> str:
    """`0.1.38 (beta-v0.2.0-rc1)` for a candidate build, the version alone for anything else."""
    if version and revision.startswith("beta-v"):
        return f"{version} ({revision})"
    return version
```

In `_app()` replace the first item:

```python
    items = [Item("version", shown_version(
        _package_version("autosound-tcc") or "unknown", requested_revision()))]
```

`updates.py` — in `check_tcc` change the signature and add the beta branch right after the `source_checkout` return; add a paragraph to its docstring; add `_check_tcc_on_beta`; change `check_all`:

```python
def check_tcc(channel: str = STABLE) -> Status:
    """(existing docstring, then:)

    On the beta channel the comparison is by commit instead (`_check_tcc_on_beta`).
    """
    version = install_report.app_version()
    _url, commit = install_report.install_source()
    if not commit:
        return Status("tcc", version, "", False, "source_checkout", updatable=False)
    if channel == BETA:
        return _check_tcc_on_beta(version, commit)
    tag = newest_tcc_tag()
    # (the rest unchanged)


def _check_tcc_on_beta(version: str, commit: str) -> Status:
    """On beta TCC is compared by COMMIT, the way the method always is.

    A candidate writes nothing — `make ship CANDIDATE=` tags HEAD — so an app built from
    `beta-v0.2.0-rc1` may carry the version of the release before it, and a version compare would
    offer rc1 to an installation that already is rc1, forever. So: the commit of the newest tag on
    the channel is current; a version above that tag's X.Y.Z is a build ahead of the releases,
    current too (the rule `check_tcc` keeps on stable); anything else is newer — rc2 over rc1, and
    the release cut on top of its candidates. Equal X.Y.Z is NOT ahead: under waves the version is
    committed before the tag (hub #148), so rc1 can already say 0.2.0.
    """
    tag, sha = _newest_tag_in(TCC_REPO, TCC_TAG_GLOB, TCC_BETA_GLOB, key=channel_key)
    if not tag:
        return Status("tcc", version, "", False, "no_network")
    installed = install_report.shown_version(version, install_report.requested_revision())
    latest = tag.removeprefix("beta-").removeprefix("v")
    if sha == commit:
        return Status("tcc", installed, latest, False, installed_sha=commit, latest_sha=sha)
    if version and _version_key(version)[:3] > channel_key(tag)[:3]:
        return Status("tcc", installed, version, False, installed_sha=commit, latest_sha=sha)
    return Status("tcc", installed, latest, True, installed_sha=commit, latest_sha=sha)


def check_all(channel: str = STABLE) -> tuple[Status, Status]:
    """Both halves. Two network calls; run it off the GUI thread.

    The channel reaches TCC's half only: the method follows released tags on both channels until
    its beta copy is wired (hub #145 answer, `installation.md` "Two channels on one machine").
    """
    return check_tcc(channel), check_skill()
```

- [ ] **Step 4: Run the tests and ruff**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_install_report.py tests/test_updates.py -q -n 0` → PASS
Run: `uvx ruff@0.12.0 check src/autosound_tcc/core tests/test_install_report.py tests/test_updates.py` → `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/core/install_report.py src/autosound_tcc/core/updates.py tests/test_install_report.py tests/test_updates.py
git commit -m "Updater: on beta TCC is compared by commit; a candidate build names its tag (hub #140)"
```

---

### Task 3: The channel setting

**Files:**
- Modify: `src/autosound_tcc/core/config.py` (after `set_project_dir`)
- Modify: `src/autosound_tcc/core/updates.py` (import `config`; add `channel_for`, `current_channel` after `check_all`)
- Test: `tests/test_updates.py`

**Interfaces:**
- Consumes: `install_report.requested_revision()` (Task 2), `updates.STABLE`/`BETA` (Task 1).
- Produces: `config.update_channel() -> str` ("" when never set), `config.set_update_channel(value: str) -> None`, `updates.channel_for(saved: str, revision: str) -> str`, `updates.current_channel() -> str`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_updates.py`:

```python
@pytest.mark.parametrize("saved, revision, expected", [
    ("", "", "stable"),
    ("", "v0.1.39", "stable"),
    ("", "beta-v0.2.0-rc1", "beta"),
    ("stable", "beta-v0.2.0-rc1", "stable"),
    ("beta", "", "beta"),
    ("nightly", "beta-v0.2.0-rc1", "stable"),
])
def test_the_channel_is_the_choice_else_what_the_app_was_installed_from(saved, revision, expected):
    assert updates.channel_for(saved, revision) == expected


def test_the_channel_setting_round_trips(monkeypatch):
    from autosound_tcc.core import config

    monkeypatch.setattr(install_report, "requested_revision", lambda: "")
    assert config.update_channel() == ""
    assert updates.current_channel() == "stable"

    config.set_update_channel("beta")

    assert config.update_channel() == "beta"
    assert updates.current_channel() == "beta"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_updates.py -q -n 0`
Expected: FAIL — `module 'autosound_tcc.core.updates' has no attribute 'channel_for'`.

- [ ] **Step 3: Implement** — `config.py`, after `set_project_dir`:

```python
#: Which tags the update rows follow (hub #140): "stable" or "beta", "" while never chosen. What an
#: unset or unknown value MEANS is `updates.channel_for`'s call — it reads how the app was installed,
#: which this module cannot import without a cycle (`install_report` imports it).
_UPDATE_CHANNEL_KEY = "updates/channel"


def update_channel() -> str:
    """The saved update channel, "" when it was never set."""
    return str(_settings().value(_UPDATE_CHANNEL_KEY, "") or "")


def set_update_channel(value: str) -> None:
    _settings().setValue(_UPDATE_CHANNEL_KEY, value)
```

`updates.py` — import line becomes `from autosound_tcc.core import child, config, install_report, vendor_loader`; after `check_all`:

```python
def channel_for(saved: str, revision: str) -> str:
    """The channel to follow: the saved choice, or — never chosen — what the app was installed from.

    Installed from a `beta-v*` tag and never set → beta: `install.sh --channel beta` put a candidate
    here, and moving its tester to stable at the first update check, without a word, would undo
    that (the Arbiter, 2026-09-14). An unknown saved value reads as stable.
    """
    if saved in (STABLE, BETA):
        return saved
    if not saved and revision.startswith("beta-v"):
        return BETA
    return STABLE


def current_channel() -> str:
    """`channel_for` on this installation. Reads QSettings: call it on the GUI thread, pass the value."""
    return channel_for(config.update_channel(), install_report.requested_revision())
```

- [ ] **Step 4: Run the tests and ruff**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_updates.py -q -n 0` → PASS
Run: `uvx ruff@0.12.0 check src/autosound_tcc/core tests/test_updates.py` → `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/core/config.py src/autosound_tcc/core/updates.py tests/test_updates.py
git commit -m "Updater: the channel setting, starting on beta for an app installed from a candidate (hub #140)"
```

---

### Task 4: The checkbox, the window's two checks, the CHANGELOG

**Files:**
- Modify: `src/autosound_tcc/ui/tcc/diagnostics_panel.py` — imports (`:24-42`), `_UpdateProbe` (`:255-277`), `_build_update_row` (`:414-448`), `_update_tcc` (`:520-535`), `_start_update_check` (`:630-642`), `_retranslate` (`:742-757`)
- Modify: `src/autosound_tcc/ui/tcc/main_window.py:3282-3300` (`_check_for_updates`)
- Modify: `src/autosound_tcc/ui/tcc/i18n.py` — after `"updSkillName"` at `:150`, `:1098`, `:1985`, `:2936`
- Modify: `tests/conftest.py:303-307`, `tests/test_diagnostics_panel.py` (two stand-ins: `:470`, `:492`)
- Modify: `CHANGELOG.md` (an `## [Unreleased]` section above `## [v0.1.39]`)
- Test: `tests/test_diagnostics_panel.py`

**Interfaces:**
- Consumes: `updates.current_channel()`, `updates.BETA`, `updates.STABLE`, `config.set_update_channel()`, `updates.check_all(channel)`, `updates.newest_tcc_tag(channel)`.
- Produces: `DiagnosticsDialog._beta_box: QCheckBox`, `_UpdateProbe(channel: str = "stable")`, i18n key `updBetaChannel`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_diagnostics_panel.py`:

```python
def test_the_beta_box_is_unticked_by_default_and_ticking_it_asks_again_on_beta(monkeypatch):
    """The Arbiter's answers of 2026-09-14: unticked unless the app came from a candidate, next to
    the rows it changes — and those rows answer again, for the channel just chosen."""
    from autosound_tcc.core import config, install_report, updates

    _app()
    monkeypatch.setattr(install_report, "requested_revision", lambda: "")
    asked = []
    monkeypatch.setattr(updates, "check_all", lambda channel="stable": asked.append(channel) or (
        updates.Status("tcc", "0.1.3", "", False), updates.Status("skill", "3.0.8", "3.0.8", False)))
    dialog = DiagnosticsDialog()
    assert dialog._beta_box.isChecked() is False

    dialog._beta_box.setChecked(True)

    assert config.update_channel() == "beta"
    assert dialog._update_rows["tcc"][0].text() == i18n.t("updChecking")
    dialog._update_probe._thread.join(timeout=5)
    assert asked[-1] == "beta"


def test_an_app_installed_from_a_candidate_opens_with_the_box_ticked(monkeypatch):
    from autosound_tcc.core import install_report

    _app()
    monkeypatch.setattr(install_report, "requested_revision", lambda: "beta-v0.2.0-rc1")

    assert DiagnosticsDialog()._beta_box.isChecked() is True


def test_updating_tcc_on_beta_pins_the_candidate(monkeypatch):
    from autosound_tcc.core import config, terminal_launcher, updates

    _app()
    config.set_update_channel("beta")
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("tcc", "0.1.38", "0.2.0-rc2", True))
    seen = []
    monkeypatch.setattr(terminal_launcher, "run_line", lambda line: seen.append(line))
    monkeypatch.setattr(updates, "newest_tcc_tag",
                        lambda channel="stable": "beta-v0.2.0-rc2" if channel == "beta" else "v0.1.39")

    dialog._update_tcc()

    assert "@beta-v0.2.0-rc2" in seen[0]
```

Stand-ins that must take the argument now (behaviour unchanged):
- `tests/conftest.py`: `lambda: (updates.Status("tcc", …` → `lambda channel="stable": (updates.Status("tcc", …`
- `tests/test_diagnostics_panel.py`, `test_updating_tcc_is_handed_to_a_terminal`: `lambda: "v0.9.9"` → `lambda channel="stable": "v0.9.9"`
- `tests/test_diagnostics_panel.py`, `test_re_check_asks_about_updates_again`: `lambda: asked.append(1) or (` → `lambda channel="stable": asked.append(1) or (`

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_diagnostics_panel.py -q -n 0`
Expected: the three new tests FAIL with `AttributeError: 'DiagnosticsDialog' object has no attribute '_beta_box'`; the rest PASS.

- [ ] **Step 3: Implement**

`diagnostics_panel.py` — add `QCheckBox` to the `PySide6.QtWidgets` import and `config` to the `autosound_tcc.core` import. `_UpdateProbe`:

```python
    def __init__(self, channel: str = "stable") -> None:
        self.result = None
        self._channel = channel
        self._thread = threading.Thread(target=self._run, name="tcc-updates", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self.result = updates.check_all(self._channel)
        except Exception:  # noqa: BLE001 — an unanswered question is a row that says so
            self.result = None
```

In `_build_update_row`, after the `for name, key …` loop and before `self._update_probe = None`:

```python
        # Under the rows it changes (the Arbiter, 2026-09-14). The method is not on it yet: it keeps
        # following released tags on both channels, and the label says TCC for that reason.
        self._beta_box = QCheckBox(i18n.t("updBetaChannel"))
        self._beta_box.setChecked(updates.current_channel() == updates.BETA)
        self._beta_box.toggled.connect(self._on_beta_toggled)
        grid.addWidget(self._beta_box)
```

New method after `_show_update`:

```python
    def _on_beta_toggled(self, checked: bool) -> None:
        """The channel is a setting, and the rows above must answer for the one just chosen.

        A probe still running asks for the OLD channel; it is let go rather than waited for — a
        daemon thread holding no Qt object — and a new one starts.
        """
        config.set_update_channel(updates.BETA if checked else updates.STABLE)
        self._update_probe = None
        self._start_update_check()
```

`_start_update_check`: `self._update_probe = _UpdateProbe()` → `self._update_probe = _UpdateProbe(updates.current_channel())`.

`_update_tcc`: `updates.tcc_install_line(tag=updates.newest_tcc_tag())` → `updates.tcc_install_line(tag=updates.newest_tcc_tag(updates.current_channel()))`.

`_retranslate`, after the `for name, key …` loop: `self._beta_box.setText(i18n.t("updBetaChannel"))`.

`main_window.py` `_check_for_updates` — before `def ask()`:

```python
        # Read here, on the GUI thread: the channel lives in QSettings.
        channel = updates.current_channel()
```

and in `ask()`: `holder["result"] = updates.check_all(channel)`.

`i18n.py`, one line after each `"updSkillName"`:

```python
        "updBetaChannel": "Beta channel: also offer TCC release candidates",
```
```python
        "updBetaChannel": "Бета-канал: пропонувати й кандидати в реліз ТСС",
```
```python
        "updBetaChannel": 'Kanał beta: proponuj też kandydatów do wydania TCC',
```
```python
        "updBetaChannel": 'Beta-Kanal: auch Release-Kandidaten von TCC anbieten',
```

`CHANGELOG.md`, above `## [v0.1.39]`:

```markdown
## [Unreleased]

### Added

- **A beta channel for TCC's own updates.** Diagnostics → Installation has a checkbox under the
  update rows: "Beta channel: also offer TCC release candidates". Ticked, the TCC row also offers
  `beta-vX.Y.Z-rcN` tags, in the hub's order (a release above its own candidates), and the button
  installs the one on offer. An installed candidate reads as up to date by its commit, whatever
  version its metadata carries. Unticked by default; an app installed from a `beta-v*` tag opens
  ticked until the box is used. The method keeps following released tags on both channels.
- **A candidate build says which one it is**: `0.1.38 (beta-v0.2.0-rc1)` on the update row and in
  the installation block.
```

- [ ] **Step 4: Run the tests and ruff**

Run: `uv run --extra dev --python 3.12 python -m pytest tests/test_diagnostics_panel.py tests/test_updates.py tests/test_install_report.py tests/test_main_window.py -q -n 0` → PASS
Run: `uvx ruff@0.12.0 check src tests` → `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/autosound_tcc/ui/tcc/diagnostics_panel.py src/autosound_tcc/ui/tcc/main_window.py src/autosound_tcc/ui/tcc/i18n.py tests/conftest.py tests/test_diagnostics_panel.py CHANGELOG.md
git commit -m "Diagnostics: a beta checkbox for TCC's own updates, read by both update checks (hub #140)"
```

---

## Not in this plan

- **The method on beta** — the Arbiter's decision first: how `<project>/.claude/skills/autosound-tuning` and `AUTOSOUND_SKILL_ROOT` behave for the two routes (hub #145 answer).
- **The self-check pin row** (spec §6) — follows the method half.
- **Closing hub #140** — after the method half is decided: built, or split off with the Arbiter's word.
