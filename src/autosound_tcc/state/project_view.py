"""Read the skill-owned `project.json` into the shapes the left panel's sections render.

TCC is a schema *consumer* here too (same posture as `process_view.py`/`measurement_view.py`):
the skill's `rew_tool/project.py` owns `project.json` and is the only writer. This module turns
that file into flat `(label, value)` rows for two sections that used to be static placeholders
(SKILL-CHANGE-REQUESTS.md SCR-015/016). Rows are built from the FACTS in that file — a
`param_sections` key used to ship ready-made label/value rows for these same panels, and was
dropped in skill schema v3 because it restated values already stored as fields here:

* **System params** — the equipment side of the project: DSP model, amps, mic, source (SCR-015
  point 1).
* **Project params' channel-tier summary** — "8 virtual channels (1 off), 12 output channels
  (2 off)" (SCR-016): a project-scoped FACT the skill already knows at intake, not re-derived
  client-side from the ledger + profile (that re-derivation is possible but deliberately avoided —
  the skill owns the schema and writes the data, TCC renders it).
* **`_open_questions`** as onboarding TODO chips, so unresolved intake facts are visible in the UI,
  not only on disk.

**Car audio analysis is no longer a placeholder** (it was, under SCR-015 point 2, while
`project.json` had no schema for acoustic facts). The schema arrived and so did the loader — it
lives one module over, in `state/acoustics_view.py::load_flaws`, and `main_window._rebuild_acoustics`
renders a row per flaw. This note is kept rather than deleted because the sentence it replaces
outlived the work by weeks and sent a reader looking for something that was already there.

Returns empty tuples when `project.json` doesn't exist yet, same convention as
`state/dsp_state.py::load_hardware_controls` — a brand-new project reads as "nothing yet", not an
error.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from autosound_tcc.core import child, config

# A panel row is not worth a stall: a slow mount answers "say nothing".
_GIT_TIMEOUT_S = 2.0


def fact_value(x: Any) -> Any:
    """Unwrap a `fact(value, source, at)` object, or pass a bare value through.

    Mirrors `rew_tool/project.py::fact_value`, deliberately rather than importing it: this is two
    lines of FORMAT reading (documented in `project-schema.md`'s Provenance section), and every
    other loader in this module works without the submodule being checked out. Reading a fact is
    not the same as owning one — the values themselves still come only from the skill's file.

    A reader never needs to know which fields are wrapped, which is the point: `fs_hz` is, `role`
    is not, and both go through here.
    """
    return x.get("value") if isinstance(x, dict) and "value" in x else x


def fact_inherited(x: Any) -> bool:
    """Whether a fact was carried in from another project rather than established on this build.

    `origin: inherited` since the method's v3.0.53 (hub #154 §4): `project_seed.py` marks what it
    copies, and the pre-sweep gate holds a fragile driver's inherited Fs until the Arbiter confirms
    or measures it. Absent means `here`, as every fact written before.
    """
    return isinstance(x, dict) and x.get("origin") == "inherited"


def has_project(project_dir_: Optional[Path] = None) -> bool:
    return config.project_path(project_dir_).is_file()


def _load(project_dir_: Optional[Path] = None) -> dict:
    path = config.project_path(project_dir_)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_system_params(project_dir_: Optional[Path] = None) -> tuple[tuple[str, str], ...]:
    """`(label, value)` rows for the System params section: DSP model, amps, mic, source.

    Only facts actually present render — an intake that hasn't reached a given block yet simply
    omits that row, not an empty value (same "lenient on absent facts" convention as the rest of
    the machine-file family: `state.py`/`process.py`/`project.py`).
    """
    data = _load(project_dir_)
    rows: list[tuple[str, str]] = []

    dsp = data.get("dsp") or {}
    dsp_name = " ".join(filter(None, (dsp.get("vendor"), dsp.get("model"))))
    if not dsp_name:
        # `project.json` arrives late: the intake asks about the car, the drivers and their Fs
        # before it is written, and a session can legitimately spend a whole conversation short of
        # that. `dsp_profile.json` arrives early -- it is finalised as soon as the DSP is named --
        # so it is the first real fact a session produces, and a panel that shows nothing while it
        # sits on disk reads as a session that did nothing.
        dsp_name = dsp_from_profile(project_dir_) or ""
    if dsp_name:
        rows.append(("DSP", dsp_name))

    for amp in data.get("amps") or []:
        if not isinstance(amp, dict):
            continue
        name = " ".join(filter(None, (amp.get("make"), amp.get("model"))))
        if not name:
            continue
        label = f"Amp ({amp['role']})" if amp.get("role") else "Amp"
        rows.append((label, name))

    mic = (data.get("mic") or {}).get("model")
    if mic:
        rows.append(("Mic", str(mic)))

    source = (data.get("source") or {}).get("head_unit")
    if source:
        rows.append(("Source", str(source)))

    return tuple(rows)


def dsp_from_profile(project_dir_: Optional[Path] = None) -> Optional[str]:
    """`vendor model` out of `dsp_profile.json`, or None.

    Read as plain JSON rather than through the skill's loader: this is one label for a sidebar
    row, and going through `vendor_loader` would make a missing submodule turn an empty panel
    into an exception.
    """
    path = config.dsp_profile_path(project_dir_)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    profile = data.get("dsp_profile") if isinstance(data, dict) else None
    if not isinstance(profile, dict):
        return None
    name = " ".join(
        str(part) for part in (profile.get("vendor"), profile.get("name") or profile.get("model"))
        if part and str(part).lower() != "unknown"
    ).strip()
    return name or None


def load_channel_summary(
    project_dir_: Optional[Path] = None,
) -> tuple[tuple[str, int, int], ...]:
    """`(tier_id, total, off)` for the project-scoped channel-tier summary (SCR-016), e.g.
    `("virtual_channels", 8, 1)`. Not re-derived from the ledger client-side — the skill already
    counts this at intake and writes it here.

    The tier ID and not a label: this used to title each row by prettifying the JSON key
    (`virtual_channels` → `Virtual channels`) and to spell the count `8 (1 off)`, so a Ukrainian
    panel read "Virtual channels 8 (1 off)" among its Ukrainian rows (user, 2026-08-21). A key can
    be translated where an English sentence built here cannot, so the words belong to the renderer
    — the same store-facts/derive-views split the ledger follows.
    """
    summary = _load(project_dir_).get("channel_summary") or {}
    if not isinstance(summary, dict):
        return ()
    rows = []
    for tier_id, counts in summary.items():
        if not isinstance(counts, dict):
            continue
        total = counts.get("total")
        if not isinstance(total, int):
            continue
        off = counts.get("off")
        rows.append((str(tier_id), total, off if isinstance(off, int) else 0))
    return tuple(rows)


#: The identity parts of a car, in the order they are read. `year` is deliberately not here:
#: `save_car` says it "describes this one car; it classifies nothing", so it is display, not
#: identity, and its absence is not a gap worth naming.
CAR_PARTS = ("make", "model", "generation", "body")


def load_car(project_dir_: Optional[Path] = None) -> tuple[str, tuple[str, ...]]:
    """`(one line to show, the identity parts that are missing)` from `project.json["car"]`.

    A project records the cabin it is about and nothing in the app ever showed it back, so the
    panel described the whole rig — DSP, amps, mic, source — without saying which car any of it is
    installed in (tcc#11). The second half of the answer is the load-bearing one: `save_car` warns
    that an unrecorded body is a SILENT loss ("nothing breaks today, and the material is simply not
    there tomorrow"), and a blank row is exactly how silence stays silent.

    **The generation is not repeated.** Projects written before `save_car` folded it into the
    nameplate (`"model": "Passat B8"`), and joining the parts blindly reads `VW Passat B8 B8`.
    """
    car = _load(project_dir_).get("car")
    if not isinstance(car, dict):
        return "", CAR_PARTS
    parts = {key: str(car.get(key) or "").strip() for key in CAR_PARTS}
    missing = tuple(key for key in CAR_PARTS if not parts[key])
    words: list[str] = []
    for key in CAR_PARTS:
        value = parts[key]
        if not value:
            continue
        if key == "generation" and words and words[-1].lower().endswith(value.lower()):
            continue  # already inside the nameplate — the legacy shape
        words.append(value)
    line = " ".join(words)
    year = car.get("year")
    if line and year:
        line = f"{line} · {year}"
    wheel = str(car.get("wheel") or "").strip()
    if line and wheel:
        line = f"{line} ({wheel})"
    return line, missing


def channel_name(entry: dict) -> Optional[str]:
    """The name a channel goes by today — its `code` (SCR-039).

    A ledger row's key is the channel's *id*, so the key is not the label: after a rename they are
    the old name and the new one. Every renderer asks here rather than showing the key, which is
    what makes a rename visible in the app without rewriting a single snapshot.
    """
    code = fact_value((entry or {}).get("code"))
    return str(code) if code else None


def load_channels(project_dir_: Optional[Path] = None) -> dict[str, dict]:
    """`project.json`'s `channels[]`, keyed by every name a ledger row might use.

    SCR-001, resolved 2026-07-31: **`project.json` owns channel identity, the ledger owns tunable
    state, consumers join on `code`.** The mechanical test for which side a field belongs to is
    "does it change from snapshot to snapshot?" — `driver`, `fs_hz`, `slot`, `descr`, `role`,
    `order`, `hidden` do not; gain, delay, crossover and EQ do.

    Skill schema v3 removed those fields from the ledger row outright, so a migrated project has
    exactly one home for each. `state/dsp_state.py` still falls back to a ledger row's copy, which
    is a 2.x reader and nothing more.

    Rows without a `code` are skipped rather than guessed at — an entry with no join key cannot be
    matched to anything, and inventing one would attach a driver to the wrong channel.

    **The ledger's row key is the channel's `id`, not its name** (SCR-039). The id defaults to the
    code, so for a project that has never renamed a channel this map is exactly what it always was:
    one key per channel. After a rename the same entry answers to three — the id every snapshot was
    written with, the name it goes by now, and each name it went by before — because a snapshot is
    immutable and an old REW title cannot be edited at all. A live code always wins over another
    channel's history, so a name handed on resolves to whoever holds it now rather than to whoever
    happens to come first in the file.
    """
    channels = _load(project_dir_).get("channels") or []
    if not isinstance(channels, list):
        return {}
    out: dict[str, dict] = {}
    for entry in channels:
        if not isinstance(entry, dict) or not entry.get("code"):
            continue
        previous = entry.get("previous_names")
        keys = [entry.get("id"), entry.get("code")]
        keys += list(previous) if isinstance(previous, list) else []
        for key in keys:
            if key and (str(key) not in out or key == entry.get("code")):
                out[str(key)] = entry
    return out


def driver_label(entry: dict) -> Optional[str]:
    """`{"make": "Audiofrog", "model": "GB25"}` -> `"Audiofrog GB25"`.

    Tolerates the bare string an older file (or a ledger row) might carry, and returns None when
    there is no driver assigned — an unassigned slot renders without the line, not with an empty one.
    """
    driver = fact_value((entry or {}).get("driver"))
    if isinstance(driver, str):
        return driver or None
    if not isinstance(driver, dict):
        return None
    name = " ".join(
        str(part) for part in (driver.get("make"), driver.get("model")) if part
    )
    return name or None


def load_open_questions(project_dir_: Optional[Path] = None) -> tuple[str, ...]:
    """Unresolved intake facts (dotted paths) for onboarding TODO chips — `project.json`'s
    `_open_questions`, the same convention `dsp_profile.json` and the skill's own
    `rew_tool/project.py::open_questions` use."""
    return tuple(str(q) for q in (_load(project_dir_).get("_open_questions") or []))


def open_questions_by_file(project_dir_: Optional[Path] = None) -> frozenset[str]:
    """The same unresolved facts, keyed `<file>:<dotted.path>` — the spelling a plan step uses.

    A step's `covers` (method SKL-047) names the facts it closes in exactly this form, so the two
    compare directly and nothing here normalises anything: a normalisation is a guess about the
    other side's format, and the point of the field was to stop guessing.

    Two files rather than one, because a step closes facts in both, and `load_open_questions`
    above answers for `project.json` alone and drops the prefix — right for the onboarding chips
    it feeds, wrong here.

    Read off disk on every call rather than out of a contract report: the report is run on demand
    and can be absent or stale, while `_open_questions` is written by whoever answered the
    question. Silent when a file is missing or unreadable, the way `_load` is: "nothing open" is
    the honest reading of a project that has not been described yet.
    """
    project = Path(project_dir_ or config.project_dir())
    out: set[str] = set()
    for name, path in (("project.json", config.project_path(project)),
                       ("dsp_profile.json", config.dsp_profile_path(project))):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        out.update(f"{name}:{q}" for q in (data.get("_open_questions") or []))
    return frozenset(out)


@dataclass(frozen=True)
class GitStatus:
    """Is the tune's history kept, and is it backed up — the project folder's git, in facts.

    `works` is whether `git` runs on this machine at all: on the Arbiter's Mac it did not, for an
    unknown while (TEST-FINDINGS 40), and every question below would then just go unanswered.
    """

    works: bool
    repo: bool
    branch: str = ""
    changed: Optional[int] = None
    #: Where the backup goes, as a person reads it (`github.com/owner/name`); "" for none.
    remote: str = ""
    #: Commits the remote does not have yet; None when there is no upstream to count against.
    unpushed: Optional[int] = None

    @property
    def level(self) -> str:
        """`bad` — no history kept; `wait` — kept but not backed up, or behind; `done` — backed up."""
        if not self.works or not self.repo:
            return "bad"
        if not self.remote or self.unpushed:
            return "wait"
        return "done"


def _remote_label(url: str) -> str:
    """`git@github.com:owner/name.git` / `https://github.com/owner/name` → `github.com/owner/name`."""
    text = url.strip()
    text = re.sub(r"^[a-z+]+://", "", text)
    text = re.sub(r"^[^@/]+@", "", text)
    text = text.replace(":", "/", 1) if "/" not in text.split(":", 1)[0] and ":" in text else text
    return text[:-4] if text.endswith(".git") else text


def _git_works() -> bool:
    """Does `git` run here — asked without setting off the Mac's "install the developer tools" window.

    On a Mac `/usr/bin/git` is a shim: with the Command Line Tools missing it does not run git, it
    opens an installer dialog. `xcode-select -p` answers the same question with no window.
    """
    exe = shutil.which("git")
    if not exe:
        return False
    if sys.platform == "darwin" and os.path.realpath(exe) == "/usr/bin/git":
        try:
            probe = subprocess.run(["xcode-select", "-p"], capture_output=True,
                                   timeout=_GIT_TIMEOUT_S, **child.quiet())
        except (OSError, subprocess.SubprocessError):
            return False
        if probe.returncode != 0:
            return False
    return _git(Path.home(), "--version") is not None


def git_status(project_dir_: Optional[Path] = None) -> GitStatus:
    """What the project's git says, never raising and never blocking for long.

    It used to say NOTHING for a folder that is not a repository — "not a git repo would be noise
    on the ones that are not". The Arbiter's live project turned out to be exactly that, with no
    history and no backup, and nothing told him (TCC F-074, 2026-09-23); he asked to see whether
    there is a repository and whether there is git at all.
    """
    project = Path(project_dir_ or config.project_dir())
    works = _git_works()
    if not works:
        return GitStatus(works=False, repo=(project / ".git").exists())
    if not (project / ".git").exists() or _git(project, "rev-parse", "--git-dir") is None:
        return GitStatus(works=True, repo=False)
    # `rev-parse HEAD` fails on a repo with no commits yet -- which a project is for its whole
    # first session -- so the branch comes from the ref itself, with rev-parse as the fallback for
    # a detached head.
    branch = _git(project, "symbolic-ref", "--short", "HEAD") or _git(
        project, "rev-parse", "--short", "HEAD"
    ) or ""
    status = _git(project, "status", "--porcelain")
    changed = (len([line for line in status.splitlines() if line.strip()])
               if status is not None else None)
    url = _git(project, "remote", "get-url", "origin") or ""
    if not url:
        remotes = (_git(project, "remote") or "").split()
        url = _git(project, "remote", "get-url", remotes[0]) or "" if remotes else ""
    ahead = _git(project, "rev-list", "--count", "@{u}..HEAD") if url else None
    return GitStatus(works=True, repo=True, branch=branch, changed=changed,
                     remote=_remote_label(url) if url else "",
                     unpushed=int(ahead) if ahead and ahead.isdigit() else None)


def git_facts(project_dir_: Optional[Path] = None) -> tuple[tuple[str, str], ...]:
    """Branch and working-tree state of the project folder, when it is a git repo — the two rows
    it has always had; `git_status` is the whole answer."""
    state = git_status(project_dir_)
    if not state.repo or not state.works:
        return ()
    rows: list[tuple[str, str]] = []
    if state.branch:
        rows.append(("Git", state.branch))
    if state.changed is not None:
        rows.append(("Git changes", str(state.changed) if state.changed else "clean"))
    return tuple(rows)


def _git(project: Path, *args: str) -> Optional[str]:
    try:
        done = subprocess.run(
            ["git", "-C", str(project), *args],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_S, **child.quiet(),
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None
