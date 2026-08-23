"""Start a new project from an existing one's system parameters instead of from nothing.

**The cost this removes.** A new project asks for the whole car: equipment, drivers per channel,
the naming glossary, the DSP's controls. That is the right question the first time and the wrong
one every time after — the car has not changed. It is wrongest when the tune arrives from
OUTSIDE: whoever wrote that plan has none of our system parameters and never will, so a person
importing it would be retyping their own car to receive somebody else's crossovers (the user, via
the cockpit, 2026-08-23: "each next project demands a full description — and that should not have
to be done").

**What "system parameters" means here, and what it deliberately does not.** `project.json` holds
three different kinds of thing (`rew_tool/project-schema.md`), and only one of them is a
description of the car:

* **the system** — `car`, `source`, `dsp`, `amps`, `mic`, `hardware`, `channels`, `glossary`,
  `channel_summary`, `presets`. True of the installation, not of any one tune. This is what
  travels.
* **the findings** — `acoustics.flaws` and `_open_questions`. Measured or decided IN a project.
  The cabin's 32 Hz null is a fact about the car and will very likely reappear; the entry that
  records it also carries `evidence` naming measurements that exist only in the project it came
  from. So: offered, off by default, never silent.
* **this project's own** — `project_rev` (its own write counter), and most of `paths`, which
  points at a REW file, a baseline set and a ledger version belonging to that project. Only
  `measurements_repo` travels, because it points at the car, not at the tune.

`sources` travels with the facts. Dropping it would leave the new project asserting a driver's Fs
with no record of where the number came from, which is worse than saying it was inherited — and
the seeding itself is appended there as one more source, so the file says what happened to it.

**An allowlist, not a blocklist.** Only the keys and files named here are copied. A project's
`state/`, `process/`, `journal/`, `rew_analitic/`, its ledger snapshots and its `.tcc/` are not
excluded by a rule that has to be kept up to date — they are simply never reached. Whatever the
method adds next stays behind until somebody decides it should travel.

Qt-free on purpose: the window is one caller (`ui/tcc/new_project_dialog.py`), and the same act
has to be available to anything else that creates a project.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from autosound_tcc.core import vendor_loader

#: Facts about the installation. True whichever tune is running, so they travel whole.
SYSTEM_KEYS = (
    "car", "source", "dsp", "amps", "mic", "hardware",
    "channels", "glossary", "channel_summary", "presets",
)

#: Measured or decided inside a project. Offered separately because the entries reference their
#: own project's evidence -- see the module docstring.
FINDING_KEYS = ("acoustics", "_open_questions")

#: The one path that is about the car rather than about the tune: the measurement corpus for this
#: vehicle. `rew_project`, `baseline_set`, `set0_*` are the other project's own and stay there.
PATHS_THAT_TRAVEL = ("measurements_repo",)

#: Prose. Copied whole because it IS the description the person would otherwise retype, and marked
#: at the top because a reader must not mistake an inherited profile for one written here.
PROSE_FILES = ("autosound_context.md", "preference-profile.md")

#: The DSP's capabilities. Hardware, so it travels verbatim -- and the new project needs it before
#: anything can check whether a filter is even enterable.
PROFILE_FILE = "dsp_profile.json"

#: Default marker for the prose files. English because this module has no language; the window
#: passes a translated one (`i18n.t("npSeedNote")`).
DEFAULT_NOTE = "**Inherited from `{source}` ({when}).** The system profile was copied from that " \
               "project, not written here — check it against this build before relying on it."


@dataclass
class Summary:
    """What a candidate source project IS, in the few words a picker can show."""

    car: str
    dsp: str
    channels: int


@dataclass
class Seeded:
    """What actually happened, in numbers the caller can render in any language.

    Deliberately not pre-rendered sentences: this module is imported by a window that speaks two
    languages and by tests that speak neither.
    """

    ok: bool
    written: list[str] = field(default_factory=list)
    channels: int = 0
    amps: int = 0
    flaws: int = 0
    questions: int = 0
    #: One technical sentence when `ok` is False -- a path, or what the method's validator said.
    problem: Optional[str] = None


def _read_project(source: Path) -> Optional[dict]:
    path = source / "project.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def describe(source: Path) -> Optional[Summary]:
    """The one-line identity of a project worth seeding from, or None if it is not one.

    Used by the picker to answer "is this a project, and which car is it" before anything is
    copied. Reads the file directly rather than through the method's loader: an unreadable or
    2.x `project.json` is a "no" here, not an exception in a dialog.
    """
    data = _read_project(source)
    if data is None:
        return None
    car = data.get("car") or {}
    dsp = data.get("dsp") or {}
    car_line = " ".join(
        str(car[key]) for key in ("make", "model", "year") if car.get(key) not in (None, "")
    )
    dsp_line = " ".join(
        str(dsp[key]) for key in ("vendor", "model") if dsp.get(key) not in (None, "")
    )
    channels = data.get("channels")
    return Summary(
        car=car_line or source.name,
        dsp=dsp_line,
        channels=len(channels) if isinstance(channels, list) else 0,
    )


def dsp_of(source: Path) -> Optional[tuple[str, str]]:
    """The source project's DSP as (vendor, model), for prefilling the profile picker.

    The vendor/model strings are matched EXACTLY against the bundled profiles
    (`dsp_profile.find_bundled()`, project-intake.md §4), so handing over the two strings a real
    project already uses is worth more than any free typing.
    """
    data = _read_project(source)
    if data is None:
        return None
    dsp = data.get("dsp") or {}
    vendor, model = str(dsp.get("vendor") or "").strip(), str(dsp.get("model") or "").strip()
    return (vendor, model) if vendor and model else None


def _mark(text: str, note: str) -> str:
    """Put the note where a reader meets it first, without displacing the document's title."""
    lines = text.split("\n")
    if lines and lines[0].startswith("#"):
        return "\n".join([lines[0], "", f"> {note}"] + lines[1:])
    return f"> {note}\n\n{text}"


def seed(
    source: Path,
    target: Path,
    *,
    include_findings: bool = False,
    copy_profile: bool = True,
    note: str = DEFAULT_NOTE,
    today: Optional[date] = None,
) -> Seeded:
    """Copy `source`'s system parameters into `target`. Never writes into `source`.

    Refuses rather than merges when `target` already has a `project.json`: seeding is the first
    act of a new project, and quietly overwriting facts somebody has already confirmed is the one
    outcome nobody could want.

    The file is written through the method's own `Project.save()` -- so it is validated, written
    atomically, and gets `project_rev` 1 rather than inheriting the source's count of writes it
    was not part of.

    `copy_profile=False` is for the one case where the source is the wrong authority on it: the
    person picked a DIFFERENT DSP for the new build. Everything else about the car still travels
    -- the same drivers in the same doors, on a new processor -- but its capabilities are then a
    question for the onboarding interview, not a file to inherit.
    """
    source, target = Path(source).expanduser(), Path(target).expanduser()
    if source.resolve() == target.resolve():
        return Seeded(False, problem="the source and the new project are the same folder")
    data = _read_project(source)
    if data is None:
        return Seeded(False, problem=f"no readable project.json in {source}")
    if (target / "project.json").is_file():
        return Seeded(False, problem=f"{target} already has a project.json")

    when = (today or date.today()).isoformat()
    seeded: dict = {"project_rev": 0}
    for key in SYSTEM_KEYS:
        if key in data:
            seeded[key] = data[key]
    if include_findings:
        for key in FINDING_KEYS:
            if key in data:
                seeded[key] = data[key]
    paths = data.get("paths")
    if isinstance(paths, dict):
        travelling = {k: paths[k] for k in PATHS_THAT_TRAVEL if k in paths}
        if travelling:
            seeded["paths"] = travelling
    sources = data.get("sources")
    seeded["sources"] = (list(sources) if isinstance(sources, list) else []) + [
        f"system parameters seeded from project '{source.name}' on {when} — "
        "inherited, not re-measured here"
    ]

    result = Seeded(True)
    try:
        project = vendor_loader.load_project().Project(str(target))
        project.save(seeded)
    except Exception as exc:  # noqa: BLE001 — the method's validator, or a disk that said no
        return Seeded(False, problem=f"{type(exc).__name__}: {exc}")
    result.written.append("project.json")

    target.mkdir(parents=True, exist_ok=True)
    profile = source / PROFILE_FILE
    if copy_profile and profile.is_file():
        shutil.copy2(profile, target / PROFILE_FILE)
        result.written.append(PROFILE_FILE)

    marker = note.format(source=source.name, when=when)
    for name in PROSE_FILES:
        prose = source / name
        if not prose.is_file():
            continue
        try:
            text = prose.read_text(encoding="utf-8")
        except OSError:
            continue
        (target / name).write_text(_mark(text, marker), encoding="utf-8")
        result.written.append(name)

    channels = seeded.get("channels")
    amps = seeded.get("amps")
    result.channels = len(channels) if isinstance(channels, list) else 0
    result.amps = len(amps) if isinstance(amps, list) else 0
    flaws = ((seeded.get("acoustics") or {}).get("flaws")) if include_findings else None
    result.flaws = len(flaws) if isinstance(flaws, list) else 0
    questions = seeded.get("_open_questions") if include_findings else None
    result.questions = len(questions) if isinstance(questions, list) else 0
    return result
