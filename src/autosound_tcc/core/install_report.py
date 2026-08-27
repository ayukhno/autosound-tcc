"""What is actually installed on this machine, in one block a person can paste into a message.

A beta with an outside tester runs on reports from a machine nobody debugging it can see. Every
question that took a round trip today — which TCC is that, which skill, is `agy` really there,
where is the log — is a line here, so the answer is one screenshot instead of five (user, on
Windows 11, 2026-08-19: "логічно десь в аплікації показувати версію… дати всю інфу по складу
інсталяції").

Qt-free on purpose: the dialog renders it, and so could the MCP server or a `--report` flag later.

**Every import is at the top, and that is not style.** These functions run on a worker thread, and
PySide6 installs an import hook that reads a module's SOURCE with `inspect.getsource` on every
import it sees. An import inside a function therefore pays that on the worker, contending with the
main thread — measured here: the same report that takes 2.7 s from a shell never finished at all
inside the dialog's thread (2026-08-19). Imported once, at module load, on the main thread.
The probes are all cheap and none of them writes anything — this file answers questions, it does
not fix or install.

**Nothing here is allowed to raise.** A report that dies on one missing tool reports nothing at
all, which is worse than a line saying "not found": that line IS the finding, most of the time.
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution, version as package_version
from pathlib import Path
from typing import Optional

from autosound_tcc.core import app_log, child, config, model_overrides, vendor_loader

from autosound_tcc.core import child

#: How long a `--version` may take before it is written off. These are local binaries printing a
#: string; three seconds is already generous, and a hung one must not hang the panel.
_PROBE_TIMEOUT = 3.0

#: How much of a sha is shown where the whole thing will not fit — the title bar, the update row.
#: Git's own abbreviation length: unambiguous in a repository this size, short enough to leave the
#: project path readable. Everything that shortens uses THIS, so the short form is one prefix and
#: not several (`skill_sha_short`).
SHA_SHORT = 12

#: What a commit looks like, so that a git error message cannot be mistaken for one.
_SHA = re.compile(r"^[0-9a-f]{40}$")

#: The command-line tools TCC's own routes and the method's scripts reach for, and what each one
#: is FOR — the value of this section is telling the reader which absence matters.
_TOOLS: tuple[tuple[str, str], ...] = (
    ("claude", "the Claude session (SDK route) and the terminal front-end"),
    ("agy", "the Gemini reviewer"),
    ("gemini", "the Gemini reviewer, Google's own CLI"),
    ("codex", "a Codex reviewer"),
    ("omp", "every non-Claude model in the picker"),
    ("uv", "how TCC itself is installed and updated"),
    ("gh", "the project backup to GitHub"),
    ("git", "the method's own files and the backup"),
)


@dataclass(frozen=True)
class Item:
    """One line: what it is, what it says, and where it came from."""

    label: str
    value: str
    detail: str = ""


@dataclass(frozen=True)
class Section:
    title: str
    items: list


def _run(argv: list[str]) -> str:
    """First line of a command's output, or "" — never an exception, never a traceback."""
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=_PROBE_TIMEOUT, check=False, **child.quiet())
    except Exception:  # noqa: BLE001 — a probe that fails is a finding, not a crash
        return ""
    out = (done.stdout or done.stderr or "").strip().splitlines()
    return out[0].strip() if out else ""


def _package_version(name: str) -> str:
    try:
        return package_version(name)
    except (PackageNotFoundError, Exception):  # noqa: BLE001 — a checkout, or a broken install
        return ""


def install_source() -> tuple[str, str]:
    """`(url, commit)` for a package installed from git, both "" otherwise.

    pip and uv write `direct_url.json` beside the metadata when a package came from a URL rather
    than an index, and it carries the exact commit. That is the one fact a bug report needs and a
    version number cannot give: `0.1.0` is every build since the tag, the commit is the build.

    Public for the same reason: `core/updates.py` compares this commit against the head of the
    repository, because the version number cannot tell an old build from a new one.
    """
    try:
        raw = distribution("autosound-tcc").read_text("direct_url.json")
        if not raw:
            return "", ""
        data = json.loads(raw)
        return str(data.get("url") or ""), str((data.get("vcs_info") or {}).get("commit_id") or "")
    except Exception:  # noqa: BLE001 — a checkout has no direct_url.json, which is itself an answer
        return "", ""


def app_version() -> str:
    """TCC's own version, or "" when it cannot be told.

    For an installed app that is the package metadata. For a SOURCE CHECKOUT it is the checkout's
    own `pyproject.toml`, because the metadata there is whatever was installed into the virtualenv
    once and never again: a tree at 0.1.6 reported `TCC 0.0.1` in its title bar (user, running
    `python -m autosound_tcc.app`, 2026-08-19). The version a developer needs is the one in the
    files they are editing.
    """
    version = _package_version("autosound-tcc")
    _url, commit = install_source()
    if commit:
        return version  # installed from git: the metadata IS the build
    try:
        text = (Path(__file__).parents[3] / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return version
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else version


def _manifest() -> Optional[Path]:
    """The plugin manifest, through the installer's link. None when there is no repository."""
    root = vendor_loader.skill_repo_root()
    return None if root is None else root / ".claude-plugin" / "plugin.json"


def skill_version() -> str:
    """The method's version, from the plugin manifest at the skill repository's root, or "".

    A SIGNATURE FOR A PERSON, and not an identifier — `skill_sha()` is that. This number is kept
    by hand and in the method's own repository the two already disagree: `main` carries 3.0.36
    while `marketplace.json` still says 2.8.3 (measured 2026-08-27). It goes on screen because it
    is what a person quotes; nothing is ever DECIDED by comparing it.

    One file read. Public because the window puts both versions in its title bar — the first thing
    on screen in any screenshot, which is where a version is worth most (user, 2026-08-19).
    """
    try:
        path = _manifest()
        if path is None:
            return ""
        return str(json.loads(path.read_text(encoding="utf-8")).get("version") or "")
    except Exception:  # noqa: BLE001 — a checkout without the manifest is still a skill
        return ""


def skill_sha() -> str:
    """The commit the method's checkout is at, or "" when it cannot be told.

    **THE identifier of the method.** `skill_version()` is the signature beside it. Where anything
    is compared this decides; where anything is shown, the version stands next to it. Two
    identifiers would be one key kept in two places, and this pair has already been seen to drift
    (see `skill_version`) — a version string is maintained by hand and a sha is not.

    Read here and ONLY here. `core/self_check.py` and `core/updates.py` both call this instead of
    asking git themselves, so the number in the title bar, the number in this report and the
    number an update is decided by cannot come apart (autosound-hub HUB-001).

    "" for a skill folder that is in no repository at all — a real answer, and the same one
    `skill_version()` gives for a checkout with no manifest.
    """
    try:
        root = vendor_loader.skill_repo_root()
        if root is None:
            return ""
        out = _run(["git", "-C", str(root), "rev-parse", "HEAD"])
        # `_run` hands back git's STDERR when git fails, so the answer is RECOGNISED rather than
        # trusted: "fatal: not a git repository" in the field that identifies the method would be
        # worse than an empty one, because it looks like data.
        return out if _SHA.match(out) else ""
    except Exception:  # noqa: BLE001 — no git on the machine is a finding, not a crash
        return ""


def skill_sha_short() -> str:
    """`skill_sha()` cut to `SHA_SHORT`, for the two places the whole thing will not fit.

    A PREFIX of the one number, never a second spelling of it: this report prints all forty
    characters, and everything that shortens goes through here.
    """
    return skill_sha()[:SHA_SHORT]


def _skill() -> Section:
    """Where the method is, which commit, which version, and whether TCC can actually read it."""
    items: list[Item] = []
    try:
        path = vendor_loader.skill_dir()
        usable = vendor_loader.is_available()
        items.append(Item("found", "yes" if usable else "no", str(path)))
        # `plugin.json` sits at the REPOSITORY root — reached by following the installer's link,
        # never by counting levels up from the link itself (see vendor_loader.skill_repo_root).
        manifest = _manifest()
        # The commit ABOVE the version, and whole. This is the line that says which method a
        # screenshot was taken against, and it is the only one of the two a person can hand back
        # to git. Half a sha would not be pasteable; the version below is what they read (HUB-001).
        sha = skill_sha()
        items.append(Item("commit", sha or "unknown",
                          str(vendor_loader.skill_repo_root() or "") if sha
                          else "not a git checkout"))
        version = skill_version()
        items.append(Item("version", version or "unknown", str(manifest) if version else ""))
        if not usable:
            older = vendor_loader.older_skill_found()
            if older is not None:
                items.append(Item("2.x found instead", "yes", str(older)))
    except Exception as exc:  # noqa: BLE001
        items.append(Item("found", "could not be asked", f"{type(exc).__name__}: {exc}"))
    return Section("The method", items)


def _tools() -> Section:
    """Every known tool, asked at once rather than one after another.

    Eight independent `--version` calls taken in turn is eight round trips of process startup —
    measured at about twelve seconds on a laptop where each one is fine. They do not depend on
    each other, so they go in a pool and the section costs about as long as its slowest member.
    """
    found = [(exe, what, shutil.which(exe)) for exe, what in _TOOLS]
    versions: dict[str, str] = {}
    live = [exe for exe, _what, where in found if where]
    if live:
        with ThreadPoolExecutor(max_workers=min(8, len(live))) as pool:
            for exe, version in zip(live, pool.map(lambda e: _run([e, "--version"]), live)):
                versions[exe] = version
    items: list[Item] = []
    for exe, what, where in found:
        if not where:
            items.append(Item(exe, "not found", what))
            continue
        items.append(Item(exe, versions.get(exe) or "installed", f"{what} · {where}"))
    return Section("Command-line tools", items)


def _app() -> Section:
    url, commit = install_source()
    items = [Item("version", _package_version("autosound-tcc") or "unknown")]
    if commit:
        items.append(Item("commit", commit[:12], url))
    elif url:
        items.append(Item("installed from", url))
    else:
        items.append(Item("installed from", "a source checkout", str(Path(__file__).parents[3])))
    for package in ("PySide6-Essentials", "PySide6", "pyqtgraph", "mcp", "uvicorn",
                    "claude-agent-sdk", "numpy"):
        version = _package_version(package)
        if version:
            items.append(Item(package, version))
    return Section("Autosound TCC", items)


def _machine() -> Section:
    return Section("This machine", [
        Item("system", f"{platform.system()} {platform.release()}", platform.platform()),
        Item("python", platform.python_version(), sys.executable),
    ])


def vendor_dir() -> Optional[Path]:
    try:
        return vendor_loader.skill_dir()
    except Exception:  # noqa: BLE001
        return None


def _paths(project_dir: Optional[Path] = None, extra: Optional[dict] = None) -> Section:
    items: list[Item] = []
    try:
        here = Path(project_dir) if project_dir else config.project_dir()
        items.append(Item("project", str(here), "exists" if here.is_dir() else "does not exist"))
        log = app_log.log_path()
        items.append(Item("log", str(log) if log else "not writing to a file"))
        items.append(Item("settings", str(model_overrides.config_dir())))
        items.append(Item("skill", str(vendor_dir()) if vendor_dir() else "—"))
    except Exception as exc:  # noqa: BLE001
        items.append(Item("paths", "could not be read", f"{type(exc).__name__}: {exc}"))
    for label, value in (extra or {}).items():
        items.append(Item(label, str(value)))
    return Section("Where things are", items)


def tools() -> Section:
    """The command-line tools alone — the only part that runs anything.

    Its own entry point because it is the only SLOW part, and the caller may want to put it on a
    thread while the rest is on screen already. Everything else here reads files and metadata.
    """
    return _tools()


def report(
    project_dir: Optional[Path] = None,
    extra: Optional[dict] = None,
    with_tools: bool = True,
    tools_section: Optional[Section] = None,
) -> list:
    """Every section, in the order a reader needs them: what this is, then what it runs on.

    `extra` is for facts only the running window knows — the MCP server's URL, whether REW answers
    — passed in rather than reached for, so this module keeps no dependency on the GUI.

    `with_tools=False` leaves out the one section that starts processes, and `tools_section` puts
    a ready-made one back in. That split is not premature: `importlib.metadata` — which the app
    section leans on — turned out to crawl when it is called from a worker thread, because
    PySide6's import hook reads the SOURCE of every module imported while it is installed, and
    metadata lookups import as they go. The metadata is milliseconds on the main thread and
    minutes off it; the subprocesses are the opposite. So each runs where it is cheap.
    """
    sections = [_app(), _skill()]
    if tools_section is not None:
        sections.append(tools_section)
    elif with_tools:
        sections.append(_tools())
    sections += [_machine(), _paths(project_dir, extra)]
    return sections


def as_text(sections: Optional[list] = None) -> str:
    """The whole report as one block, ready to paste into a message.

    Plain text and aligned by spaces: it ends up in a chat, an issue or a screenshot, and every one
    of those keeps a monospace block readable and mangles a table.
    """
    lines: list[str] = []
    for section in sections if sections is not None else report():
        lines.append(f"[{section.title}]")
        width = max((len(item.label) for item in section.items), default=0)
        for item in section.items:
            line = f"  {item.label.ljust(width)}  {item.value}"
            if item.detail:
                line += f"   ({item.detail})"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
