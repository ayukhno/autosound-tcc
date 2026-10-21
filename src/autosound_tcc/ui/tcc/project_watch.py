"""Whether a change the project folder watcher reports is worth a reload (#225). Qt-free.

While `state/` is missing the whole project folder is watched, and Qt reports only the folder's
path, not what changed in it. TCC's own `.tcc/` (a reviewer pick, a setting) lands there too, and
cost two reloads. The folder's entry list, minus `.tcc`, tells the two apart.

Ignored: a change that leaves every entry but `.tcc` as it was, and the root files named in
`READ_FILES` as they were (mtime, size). Not ignored: a new or removed entry, an edited `READ_FILES`
file. `project.json` and `dsp_profile.json` are watched as files and need no entry here.
"""

from __future__ import annotations

from pathlib import Path

OWN_DIR = ".tcc"
#: Root files the intake gate reads (the vendored `contract.py`: `project.json`, `dsp_profile.json`,
#: `glossary.json`) that Qt does not watch as files. Rewriting one leaves the entry list as it was,
#: so the listing alone would call it "nothing happened" and the gate would not re-run.
READ_FILES = ("glossary.json",)


def _entries(folder: Path) -> tuple:
    try:
        names = frozenset(p.name for p in folder.iterdir() if p.name != OWN_DIR)
    except OSError:
        return (frozenset(), ())
    stats = []
    for name in READ_FILES:
        try:
            st = (folder / name).stat()
            stats.append((st.st_mtime_ns, st.st_size))
        except OSError:
            stats.append(None)
    return (names, tuple(stats))


def watch_folder(host, project_dir: Path) -> list[str]:
    """The folder as a watch path, its listing noted first so the first event has one to compare."""
    host.__dict__.setdefault("_project_listing", {}).setdefault(project_dir, _entries(project_dir))
    return [str(project_dir)]


def worth_reload(host, args: tuple, project_dir: Path | None) -> bool:
    """False only for a change of the project folder itself that left every entry but `.tcc` as it
    was. A file's own change, a call with no path, a changed listing: reload. The listing is kept
    on `host`, per folder."""
    if project_dir is None or not args:
        return True
    seen: dict = host.__dict__.setdefault("_project_listing", {})
    now = _entries(project_dir)
    before = seen.get(project_dir)
    seen[project_dir] = now
    return not (Path(str(args[0])) == project_dir and before == now)
