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

import re
from pathlib import Path
from typing import Optional, Sequence

from autosound_tcc.core import config, method_cli, vendor_loader

#: The method's module. Arrived in v3.0.40; `available()` asks for it rather than assuming, the
#: same posture `core/issue_assets.py` and `core/eq_export.py` keep.
_MODULE = "car_profile.py"

#: The car's writer, relative to the method's `rew_tool/`: its `set-car` verb, there since v3.0.59
#: (the file arrived with it, so an older copy answers `method_cli.ScriptMissing`).
_WRITER = "intake.py"

#: Local file I/O and a JSON rewrite, as for the method's other writers; anything near this is a
#: hang, not slowness.
_TIMEOUT_S = 20.0

#: What Python prints in front of the sentence of an exception nobody caught. `set-car` refuses by
#: raising its `IntakeError` uncaught, so its sentence arrives behind this on stderr's last line.
_REFUSAL_PREFIX = re.compile(r"^(?:\w+\.)*IntakeError: ")

#: The four parts that identify a CABIN. `year` is deliberately not among them: a generation is
#: already the span of years where the acoustics are counted the same, so two builds of one
#: generation and body are one cabin whether 2017 or 2018, and the same year in another shell is
#: another cabin. The year describes THIS car and never classifies (owner, 2026-09-03).
IDENTITY = ("make", "model", "generation", "body")


class CarLibraryError(RuntimeError):
    """The car was not recorded. Carries the sentence that says why, verbatim: the method's own
    refusal (a blank part, a body outside its list), or why its copy did not run — a binding TCC
    will not run (`method_cli.Refused`'s sentence), a script that copy does not have, a timeout."""


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
    """`{"bundled_exact_match", "prior_projects", "unknown", "searched", "slug"}` — or an `error`.

    `bundled_exact_match` is `None` when nobody has described this cabin, and that IS the answer:
    it is what a session needs to hear before starting an intake from scratch. It never means
    "close enough exists" — the method offers no near miss and neither does this.

    **`searched` is the scope, and it is part of the answer.** This module has no registry of
    projects and does not scan disks; it looks in the folders TCC has been opened on. An empty
    `prior_projects` therefore means "none among these", and without the list it was read as "no
    prior material for this cabin" — the exact silent loss the `unknown` bucket exists to prevent,
    one floor up (tcc#10). A build that was never opened in TCC is not a build on another body.
    """
    module = _module()
    if module is None:
        return {"error": "this build has no car library (the method is older than v3.0.40)"}
    candidates = _candidates(dirs)
    matches, unknown = module.find_prior_projects(
        [str(d) for d in candidates], make, model, generation, body
    )
    return {
        "slug": module.body_slug(make, model, generation, body),
        "bundled_exact_match": module.find_bundled_car(make, model, generation, body),
        "prior_projects": matches,
        "unknown": unknown,
        "searched": [str(d) for d in candidates],
    }


def _candidates(dirs: Optional[Sequence[Path]] = None) -> list[Path]:
    """Where to look, deduplicated, with the open project first.

    Two things are corrected here rather than in the method, because both are TCC's own half of
    the boundary:

    * **The same project twice.** The open project was prepended after a plain `in` test, and an
      un-normalised path (`~/x/../x`, a different case on Windows) is a different `Path` — so it
      could arrive as its own prior build.
    * **A recent entry that is a sub-folder of a project.** `config.recent_projects()` holds what
      was opened, and a folder inside a project has no `project.json` of its own, so the method
      drops it from BOTH buckets — it does not even come back as `unknown`. That is how a build on
      the very same cabin, one level up, answered "none" (tcc#10). The parent is added as a
      candidate; no scanning, one step up and only when the parent is a project.
    """
    raw = [Path(d) for d in dirs] if dirs is not None else config.recent_projects()
    current = config.chosen_project_dir()
    if current is not None:
        raw = [current, *raw]
    out: list[Path] = []
    seen: set[str] = set()
    for path in raw:
        for candidate in (path, path.parent):
            try:
                key = str(candidate.resolve())
            except OSError:  # a path that no longer resolves is not a candidate
                continue
            if key in seen:
                continue
            if candidate is not path and not (candidate / "project.json").is_file():
                break  # the parent is not a project: this entry contributes only itself
            seen.add(key)
            out.append(candidate)
    return out


def record(
    project_dir: Path,
    make: str,
    model: str,
    generation: str = "",
    body: str = "",
    year=None,
) -> dict:
    """Write the car into `project.json` by the METHOD's own verb — `intake.py set-car` of the copy
    the project is bound to (#169, N9) — and answer the car as the method stored it, read back.

    The method's rule wins, so TCC fills nothing and drops nothing: the four parts go as given.
    `set-car` refuses a blank part — a build recorded without its body answers "no body recorded"
    forever — and a body outside its list, and writes nothing; that is a `CarLibraryError` with
    the method's sentence (`_sentence`). This was a load-modify-save through TCC's own copy of
    `Project`, which dropped a blank part and wrote the rest: the refusal skipped one floor up.

    `year` describes this car and takes no part in identity; it travels as text and is kept as
    the method keeps it. No lock: `project.json` is not the journal the project's lock guards.
    """
    args = ["set-car", str(project_dir), make, model, generation, body,
            *(["--year", str(year)] if year is not None else [])]
    try:
        code, out, err = method_cli.spawn(project_dir, _WRITER, args, timeout_s=_TIMEOUT_S,
                                          lock=False)
    except method_cli.ProcessWriterError as exc:
        raise CarLibraryError(str(exc)) from exc
    if code != 0:
        raise CarLibraryError(_sentence(code, out, err))
    # A read, so through TCC's own copy: what the method stored, not what was sent.
    project = vendor_loader.load_project()
    return dict(project.Project(str(project_dir)).load().get("car") or {})


def _sentence(code: int, out: str, err: str) -> str:
    """The method's own words for a car it did not write: the last line it printed to stderr.

    Its refusal of the car is an `IntakeError` it does not catch, so stderr is a traceback and the
    sentence is its last line, behind the class name Python prints — dropped, because the session
    reads the sentence to know which part to ask for. Any other exception the method lets out (its
    `ProjectError` on an unreadable `project.json`, a crash) keeps its class: there the class is
    part of what happened."""
    lines = [line.strip() for line in err.splitlines() if line.strip()]
    if lines:
        return _REFUSAL_PREFIX.sub("", lines[-1], count=1)
    return out or f"{_WRITER} set-car exited {code}"
