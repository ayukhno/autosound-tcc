"""Has this CABIN been described before — and did we build on it? (SKL-020, `#48` ask 1)

The car-side twin of `check_existing_profile`. For the processor the answer arrives on its own and
a session can put it in front of the person; for the body it depended on a session remembering to
go and look, and on a real intake it looked, decided silently what to do with what it found, and
the material sat unused for two days until the person asked outright (public `skill#19`).

**The rule about matching is the method's and stays there.** `rew_tool/car_profile.py` owns
`body_slug` and the exact-match discipline — a platform sibling is a different car, and the damage
is not a wrong file being read but a wrong one being MENTIONED ("we have something for the Passat
B7, want it?" — the answer is going to be yes). Re-deriving any of that here would be a second
place where a sedan can be equated to a wagon.

What is genuinely ours is the other half of the question: **which projects to look in.** The
method has no registry of projects; TCC has the recent list, and no disk scanning (`config`).

Three answers, never two. A project that did not record its body is NOT a project on another
body, and folding it into "none" is `#19` happening again one floor down — so `unknown` comes
back separately and the tool's instructions say to show it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from autosound_tcc.core import config, vendor_loader

#: The method's module. Arrived in v3.0.40; `available()` asks for it rather than assuming, the
#: same posture `core/issue_assets.py` and `core/eq_export.py` keep.
_MODULE = "car_profile.py"

#: The four parts that identify a CABIN. `year` is deliberately not among them: a generation is
#: already the span of years where the acoustics are counted the same, so two builds of one
#: generation and body are one cabin whether 2017 or 2018, and the same year in another shell is
#: another cabin. The year describes THIS car and never classifies (owner, 2026-09-03).
IDENTITY = ("make", "model", "generation", "body")


def _module():
    try:
        return vendor_loader.load(_MODULE)
    except Exception:  # noqa: BLE001 — no skill, or one older than v3.0.40
        return None


def available() -> bool:
    """Whether this installation can answer the cabin question at all."""
    return _module() is not None


def look_up(
    make: str,
    model: str,
    generation: str = "",
    body: str = "",
    *,
    dirs: Optional[Sequence[Path]] = None,
) -> dict:
    """`{"bundled_exact_match", "prior_projects", "unknown", "slug"}` — or an `error`.

    `bundled_exact_match` is `None` when nobody has described this cabin, and that IS the answer:
    it is what a session needs to hear before starting an intake from scratch. It never means
    "close enough exists" — the method offers no near miss and neither does this.
    """
    module = _module()
    if module is None:
        return {"error": "this build has no car library (the method is older than v3.0.40)"}
    candidates = [Path(d) for d in dirs] if dirs is not None else config.recent_projects()
    current = config.chosen_project_dir()
    if current is not None and current not in candidates:
        # The project open right now is a candidate like any other, and it is the one a person
        # would be most surprised to see missing from the answer.
        candidates = [current, *candidates]
    matches, unknown = module.find_prior_projects(
        [str(d) for d in candidates], make, model, generation, body
    )
    return {
        "slug": module.body_slug(make, model, generation, body),
        "bundled_exact_match": module.find_bundled_car(make, model, generation, body),
        "prior_projects": matches,
        "unknown": unknown,
    }


def record(
    project_dir: Path,
    make: str,
    model: str,
    generation: str = "",
    body: str = "",
    year=None,
) -> dict:
    """Write the four parts into `project.json.car`, through the METHOD'S writer.

    Load-modify-save with `Project`, never a JSON dump of our own: that writer validates, writes
    atomically, and refuses to treat an unreadable file as an empty project — a rule bought by an
    audit that watched a whole project get replaced by a skeleton.

    `year` is kept when given because it describes this car; it takes no part in identity.
    """
    project = vendor_loader.load_project()
    handle = project.Project(str(project_dir))
    data = handle.load()
    car = dict(data.get("car") or {})
    car.update({"make": make, "model": model, "generation": generation, "body": body})
    if year is not None:
        car["year"] = year
    # Empty parts are dropped rather than stored as "": a blank `body` is the state the library
    # calls "no body recorded", and it should read that way rather than as a body named nothing.
    data["car"] = {k: v for k, v in car.items() if v not in ("", None)}
    handle.save(data)
    return data["car"]
