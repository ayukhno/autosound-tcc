"""Which copy of the method a project runs, and whether TCC trusts it (#169, G5 S1).

A project links its own copy at `<project>/.claude/skills/autosound-tuning` — both session adapters
read that path and nothing else — while every writer started TCC's own `process.py` whatever the link
pointed at, and `vendor_loader.link_skill_into` leaves an existing entry alone whatever it points at.
So a session could advise from one copy while the writers wrote with another, and a project that came
from a backup, a customer or a clone could bring a copy of its own and have it run (HUB-050).

Decision 2: a link is trusted when it is a copy TCC knows, or one approved once on this machine. The
reason is ORIGIN, not shape: a copy inside the project travels with the project, so it is refused
however much it looks like the method. `for_project` answers one `Binding`:

    same      no entry, or a link to TCC's own copy: TCC's copy runs, as it always did
    known     a link to another copy TCC finds itself (`vendor_loader._candidates()`), by realpath
    approved  a link to a copy approved on this machine (`config.approved_methods()`, never the project)
    refused   anything else, with one sentence naming the entry and what to do; `can_approve` when
              approving is the remedy — a 3.x copy outside the project that TCC does not know

«Is a link» is `realpath(entry) != realpath(entry.parent)/entry.name`. Never `realpath != abspath`: that
holds for every path under a linked parent (macOS's `/var`, pytest's temp folders, a mapped drive),
link or not. The realpath also sees a Windows junction, which answers False to `is_symlink()`. Absence
is `os.lstat` raising FileNotFoundError or NotADirectoryError — exactly what `os.path.lexists` tests,
a broken link included — and nothing else is: `lexists` answers False on a permission error too,
which would read an entry TCC cannot see as «no entry» and trust TCC's copy without a word.

«Inside the project» is the folder a path IS, not how a link spells it (`_inside`): `realpath` keeps
the link's spelling, and on macOS `CAR`, an NFD name or `/System/Volumes/Data/…` reach the project's
own folder past any string test. Where `.claude/skills` itself leads out of the project, what sits
there is not the project's: no sentence calls it inside, and `relink` moves nothing out of there.

A copy's contract number (`CONTRACT_VERSION` in its `rew_tool/contract.py`) is read with `ast`, never
by import — importing a copy TCC has not decided to trust would run it — and a copy newer than
`KNOWN_CONTRACT` is refused, as is one whose `contract.py` is there and cannot be read or parsed on
this interpreter: most likely written for a newer TCC (#170). One reader, `contract_of`, for a copy on
disk and for a release at the update press. Not TCC's own copy: holding that one to the number is
S3's (W-10).

Qt-free and light (`tests/test_packaging.py`).
"""

from __future__ import annotations

import ast
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from autosound_tcc.core import app_log, config, vendor_loader

#: The newest contract this TCC drives: 1, the v3.1.x surface the method writes down in its
#: `rew_tool/CONTRACT.md`. v3.1.2 declares it; every copy up to v3.1.1 names no number, and such a
#: copy stays allowed. A copy that names a number above 1 was written for a newer TCC.
KNOWN_CONTRACT = 1

SAME, KNOWN, APPROVED, REFUSED = "same", "known", "approved", "refused"

#: What the method reads as «the copy this session runs» (`rew_tool/deployment.py`, `DECLARED_ENV`):
#: the skill FOLDER, not the repository around it.
SKILL_ROOT_ENV = "AUTOSOUND_SKILL_ROOT"


class MethodRefused(RuntimeError):
    """The project's copy of the method is not one TCC will run. Carries the sentence that says why."""


@dataclass(frozen=True)
class Binding:
    """Which copy a project runs. `skill_dir` is None exactly when `state` is `refused`."""

    project_dir: Path
    state: str
    skill_dir: Optional[Path]
    entry: Path
    reason: str = ""
    can_approve: bool = False

    def require(self) -> Path:
        """The skill folder to run, or `MethodRefused` with the binding's sentence."""
        if self.state == REFUSED or self.skill_dir is None:
            raise MethodRefused(self.reason or f"{self.entry} is not bound to a copy of the method; "
                                               f"re-link it to TCC's copy.")
        return self.skill_dir

    def script(self, rel: str) -> Path:
        """A script of the bound copy, `rew_tool/<rel>` — `MethodRefused` when refused."""
        return self.require() / "rew_tool" / rel

    def plugin_root(self) -> Optional[Path]:
        """The bound copy's repository, where `.claude-plugin/plugin.json` or `.git` is — found the
        way `vendor_loader.skill_repo_root` finds TCC's own: the link followed first, then at most
        four levels up. None when refused, or when the copy is in no repository."""
        if self.state == REFUSED or self.skill_dir is None:
            return None
        here = Path(os.path.realpath(self.skill_dir))
        for parent in (here, *here.parents)[:4]:
            if os.path.isfile(parent / ".claude-plugin" / "plugin.json") \
                    or os.path.exists(parent / ".git"):
                return parent
        return None

    def session_env(self) -> dict[str, str]:
        """What a child of the method is told about the copy it runs; empty when refused."""
        if self.state == REFUSED or self.skill_dir is None:
            return {}
        return {SKILL_ROOT_ENV: str(self.skill_dir)}


def own_copy() -> Path:
    """TCC's own copy of the method: the skill folder a project binds `same` to — with no entry, or
    an entry that links it. The one answer for `for_project` and for a caller with no project
    (`process_writer.script_path`), so the two cannot name different copies. Resolved on every
    call (`vendor_loader.skill_dir`), so the env override holds."""
    return vendor_loader.skill_dir()


def for_project(project_dir: Union[str, os.PathLike]) -> Binding:
    """The copy this project runs, and whether TCC trusts it. Never raises: whatever goes wrong
    while looking is itself an answer — `refused`, with the sentence that says what."""
    project_dir = Path(project_dir)
    entry = project_dir / ".claude" / "skills" / vendor_loader.SKILL_NAME
    try:
        return _bind(project_dir, entry)
    except Exception as exc:  # noqa: BLE001 — the promise is an answer, and a crash is not one
        # The traceback to the log: the row's sentence is all the person sees, and the crash may be
        # TCC's own — a settings value of the wrong type, a home folder that cannot be found.
        app_log.logger().exception("method: could not check %s, so it is refused", entry)
        return _refused(project_dir, entry, f"TCC could not check {entry} "
                                            f"({type(exc).__name__}: {exc}); re-link it to TCC's copy.")


def _bind(project_dir: Path, entry: Path) -> Binding:
    try:
        entry_stat = os.lstat(entry)
    except (FileNotFoundError, NotADirectoryError):  # what `os.path.lexists` reads as absent
        return Binding(project_dir, SAME, own_copy(), entry)
    except OSError as exc:  # what `lexists` would have read as absent too
        return _refused(project_dir, entry, f"TCC cannot read {entry} ({_why(exc)}); fix the "
                                            f"permissions of {entry.parent} and check again.")
    target = os.path.realpath(entry)
    home = os.path.realpath(project_dir)
    parent = os.path.realpath(entry.parent)
    # Where `.claude/skills` really is. Linked out of the project — to `~/.claude/skills`, say — what
    # sits there is not the project's, and `relink` will not move it, so no sentence advises it.
    ours = _inside(parent, home)
    remedy = ("re-link it to TCC's copy" if ours else
              f"make {entry.parent} a folder of the project's own (it leads to {parent} now), then "
              f"re-link it to TCC's copy")
    if not _is_link(entry, target, parent):
        if not stat.S_ISDIR(entry_stat.st_mode):
            return _refused(project_dir, entry, f"{entry} is a file, not a link to a copy of the "
                                                f"method; {remedy}.")
        if ours:
            return _refused(project_dir, entry, f"{entry} is a folder, not a link, and a copy inside "
                                                f"the project cannot be trusted; {remedy}.")
        return _refused(project_dir, entry, f"{entry} is a folder outside the project, not a link; "
                                            f"{remedy}.")
    try:
        os.stat(entry)  # the link followed to its end
    except (FileNotFoundError, NotADirectoryError):
        return _refused(project_dir, entry, f"{entry} points at {target}, which is not on this "
                                            f"machine; {remedy}.")
    except OSError as exc:
        return _refused(project_dir, entry, f"TCC cannot read what {entry} points at ({_why(exc)}); "
                                            f"fix the permissions of {target}, or {remedy}.")
    own = own_copy()
    if _same(target, os.path.realpath(own)):
        return Binding(project_dir, SAME, own, entry)
    if _inside(target, home):
        return _refused(project_dir, entry, f"{entry} points at {target}, inside the project, and a "
                                            f"copy inside the project cannot be trusted; {remedy}.")
    copy = Path(target)
    if not vendor_loader._looks_like_the_skill(copy):
        if vendor_loader._looks_like_an_older_skill(copy):
            return _refused(project_dir, entry, f"{entry} points at {target}, a 2.x copy of the "
                                                f"method — an older line this TCC cannot drive; "
                                                f"{remedy}.")
        return _refused(project_dir, entry, f"{entry} points at {target}, which is not a 3.x copy of "
                                            f"the method; {remedy}.")
    contract = read_contract(copy)
    if contract.unreadable:
        return _refused(project_dir, entry, f"{entry} points at {target}, a copy of the method whose "
                                            f"rew_tool/contract.py TCC cannot read "
                                            f"({contract.unreadable}), so it may be newer than this "
                                            f"TCC; update TCC first, or {remedy}.")
    if contract.newer_than(KNOWN_CONTRACT):
        return _refused(project_dir, entry, f"{entry} points at {target}, a copy of the method on "
                                            f"contract {contract.number}, newer than this TCC — "
                                            f"update TCC first, or {remedy}.")
    if _is_known(target, own):
        return Binding(project_dir, KNOWN, copy, entry)
    if any(_same(target, approved) for approved in config.approved_methods()):
        return Binding(project_dir, APPROVED, copy, entry)
    return Binding(project_dir, REFUSED, None, entry,
                   f"{entry} points at {target}, a copy of the method TCC does not know; approve it "
                   f"on this machine, or {remedy}.", can_approve=True)


def _refused(project_dir: Path, entry: Path, reason: str) -> Binding:
    return Binding(project_dir, REFUSED, None, entry, reason, False)


def _why(exc: OSError) -> str:
    return exc.strerror or str(exc)


def _same(a, b) -> bool:
    return os.path.normcase(os.fspath(a)) == os.path.normcase(os.fspath(b))


def _inside(path: str, folder: str) -> bool:
    """Whether `path` is `folder` or lies under it — the folder it IS, not how it is spelled.

    `realpath` keeps whatever spelling a link wrote, and one folder has several: `CAR` for `Car` on a
    disk that ignores case, NFD for NFC on macOS, `/System/Volumes/Data/…` through the firmlink — and
    on macOS `normcase` changes none of them. The spelling can only say «inside» rightly, so it is
    asked first; past it, the folder's identity (device and inode) is looked for in `path` and in
    every folder above it. A disk that numbers every folder 0 has no identity to compare — every
    folder on it would be «the project» — and there the spelling alone answers.
    """
    spelled, home_spelled = os.path.normcase(path), os.path.normcase(folder)
    if spelled == home_spelled or spelled.startswith(home_spelled.rstrip(os.sep) + os.sep):
        return True
    try:
        home = os.stat(folder)
    except OSError:
        return False
    if not home.st_ino:
        return False
    here = path
    while True:
        try:
            if os.path.samestat(os.stat(here), home):
                return True
        except OSError:  # this spelling of a folder is not there; the one above it still may be
            pass
        above = os.path.dirname(here)
        if above == here:
            return False
        here = above


def _is_link(entry: Path, real: str, parent: str) -> bool:
    """A symlink or a junction, wherever the project itself is reached through a link: the entry's
    realpath is not its parent's realpath with its own name on the end."""
    return not _same(real, os.path.join(parent, entry.name))


def _is_known(target: str, own: Path) -> bool:
    """A copy TCC finds itself, other than the one it chose: `_candidates()` yields the paths it
    found, and an installed copy is a link into its clone, so they are compared by realpath."""
    own_real = os.path.realpath(own)
    for candidate in vendor_loader._candidates():
        real = os.path.realpath(candidate)
        if not _same(real, own_real) and _same(real, target) \
                and vendor_loader._looks_like_the_skill(candidate):
            return True
    return False


# ---- the contract number ----------------------------------------------------------------------

@dataclass(frozen=True)
class Contract:
    """What a `contract.py` says (`contract_of`), one of three: no file (`present` False); read, its
    `number` the top-level `CONTRACT_VERSION` or None when it names none — every v3 release has the
    file; up to v3.1.1 it names none, and from v3.1.2 it names 1; or there and unreadable,
    `unreadable` saying why."""

    present: bool
    number: Optional[int] = None
    #: Why a file that is there was not read: it does not decode or parse on this interpreter, in
    #: Python's words, or the system would not hand it over (`read_contract`). "" when it was read.
    unreadable: str = ""

    def newer_than(self, known: int) -> bool:
        """Whether a TCC that drives the contracts up to `known` must not run it: a number above
        `known`, or a file that is there and cannot be read — most likely written for a newer TCC.
        No number is not newer, and no file is not either."""
        return bool(self.unreadable) or (self.number is not None and self.number > known)


#: path -> (st_mtime_ns, st_size, Contract): one entry per `contract.py`, read again when it changes.
_CONTRACT_CACHE: dict[str, tuple[int, int, Contract]] = {}


def contract_of(source: Union[bytes, str, None]) -> Contract:
    """The one reader of a `contract.py` (#170): a copy's on disk (`read_contract`), and a release's
    at the update press (`updates._extract_upkeep`), so the two cannot read one file two ways.

    None is no file. Anything else goes to `ast.parse` as it is — never imported, so nothing in it
    runs — and bytes are decoded there the way an import decodes them, a BOM and a coding cookie
    honoured. What does not decode or parse on this interpreter is `unreadable`, never «no number»:
    a newer method is the likeliest author of syntax this Python does not know. So is a
    `CONTRACT_VERSION` the module binds some other way than to a plain int (`_number_in`, R-aw)."""
    if source is None:
        return Contract(False)
    try:
        return _number_in(ast.parse(source, filename="contract.py"))
    except (SyntaxError, ValueError, RecursionError) as exc:
        return Contract(True, unreadable=f"{type(exc).__name__}: {exc}")


def contract_number(text: Union[str, bytes]) -> Optional[int]:
    """The top-level `CONTRACT_VERSION = <int>` of a `contract.py`'s text (an annotated one counts),
    or None. Found with `ast`, never by import: a file that raises on import still answers, and
    nothing in it runs. Text that does not parse, or a `CONTRACT_VERSION` bound to anything but an
    int literal, is None — `contract_of` tells both apart, and that is the reader a decision is
    made on."""
    return contract_of(text).number


#: The name a `contract.py` says its contract number with (#170).
_NUMBER_NAME = "CONTRACT_VERSION"


def _number_in(tree: ast.Module) -> Contract:
    """`CONTRACT_VERSION` as the module ends up with it, read without running it (ruling R-aw).

    The last top-level `CONTRACT_VERSION = <int literal>` (an annotated one counts) is the number;
    a module that binds no such name of its own names none. Bound any other way — to a string, a
    float, a bool, a name, an expression or a call; tuple-unpacked; imported; under an `if`, a
    `try`, a `with` or a loop; by a `def`, a `class`, an augmented assignment, a `global` — it is a
    number the file names that TCC cannot know without running it: `unreadable`, so newer, and
    refused by the binding and at the press alike. The method promises a literal (v3.1.2 writes
    `CONTRACT_VERSION = 1`, «an int LITERAL» by its own comment), so failing closed costs nothing
    today; a method that writes `int(...)` is refused until it writes a literal again. A name
    inside a function or a class body, a string or a comment is not the module's.
    """
    number = None
    for node in tree.body:
        literal = _int_literal_bound(node)
        if literal is not None:
            number = literal
        elif _binds(node):
            return _named_unread(node)
    for node in ast.walk(tree):  # a function's `global CONTRACT_VERSION` is the module's name
        if isinstance(node, ast.Global) and _NUMBER_NAME in node.names:
            return _named_unread(node)
    return Contract(True, number)


def _named_unread(node: ast.AST) -> Contract:
    return Contract(True, unreadable=f"{_NUMBER_NAME} on line {getattr(node, 'lineno', '?')} is "
                                     f"not a plain integer at the top level")


def _int_literal_bound(node: ast.stmt) -> Optional[int]:
    """The int a top-level `CONTRACT_VERSION = <int>` (or `CONTRACT_VERSION: T = <int>`) binds, or
    None. A bool is an int to Python and not a contract number to anyone."""
    if isinstance(node, ast.Assign):
        targets, value = node.targets, node.value
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        targets, value = [node.target], node.value
    else:
        return None
    named = any(isinstance(target, ast.Name) and target.id == _NUMBER_NAME for target in targets)
    literal = isinstance(value, ast.Constant) and type(value.value) is int
    return value.value if named and literal else None


def _binds(node: ast.AST) -> bool:
    """Whether a top-level statement binds `CONTRACT_VERSION` in the module's own scope, however:
    as a name stored or deleted, an import, a `def` or a `class`, an `except … as`, a match
    capture. Function and class bodies are scopes of their own and are not looked into."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name == _NUMBER_NAME
    if isinstance(node, ast.Lambda):
        return False
    if isinstance(node, ast.Name):
        return node.id == _NUMBER_NAME and not isinstance(node.ctx, ast.Load)
    if isinstance(node, ast.alias):
        return (node.asname or node.name.split(".")[0]) == _NUMBER_NAME
    if getattr(node, "name", None) == _NUMBER_NAME or getattr(node, "rest", None) == _NUMBER_NAME:
        return True  # `except … as`, a match capture
    return any(_binds(child) for child in ast.iter_child_nodes(node))


def read_contract(skill_dir: Union[str, os.PathLike]) -> Contract:
    """What the copy at `skill_dir` says in its `rew_tool/contract.py`: the file's bytes through
    `contract_of`. Cached by path, mtime and size: diagnostics asks on the GUI thread, and
    `contract.py` is 3400 lines of `ast` to walk (v3.1.2's). A file that is there and that the
    system will not hand over is `unreadable` too, in its words — and not cached, so it is asked
    again."""
    path = os.path.join(os.fspath(skill_dir), "rew_tool", "contract.py")
    try:
        info = os.stat(path)
        key = (info.st_mtime_ns, info.st_size)
        cached = _CONTRACT_CACHE.get(path)
        if cached is not None and cached[:2] == key:
            return cached[2]
        blob = Path(path).read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return Contract(False)
    except OSError as exc:
        return Contract(True, unreadable=f"{type(exc).__name__}: {_why(exc)}")
    contract = contract_of(blob)
    _CONTRACT_CACHE[path] = (*key, contract)
    return contract


def read_contract_version(skill_dir: Union[str, os.PathLike]) -> Optional[int]:
    """The contract number of the copy at `skill_dir`, or None when it names none, has no
    `contract.py`, or it cannot be read — `read_contract` tells the three apart."""
    return read_contract(skill_dir).number


# ---- what the person can do about a refusal ---------------------------------------------------


def approve(binding: Binding) -> Binding:
    """Trust, on this machine, the copy an approvable binding points at, and bind the project to it.

    Only a binding with `can_approve`. The approval is kept in TCC's own settings, never in the
    project — a project must not be able to approve itself — as the copy's realpath, the thing every
    look compares. The link is looked at again first: the person approved the copy the sentence
    named, and a link re-pointed since is another copy. `MethodRefused` when the settings do not
    keep the approval (`config.approve_method` reads it back).
    """
    if not binding.can_approve:
        if binding.state == REFUSED:
            raise MethodRefused(binding.reason)
        raise MethodRefused(f"{binding.entry} already runs a copy TCC trusts ({binding.state}); "
                            f"there is nothing to approve.")
    now = for_project(binding.project_dir)
    if now.state != REFUSED:
        return now
    if not now.can_approve:
        raise MethodRefused(now.reason)
    if now.reason != binding.reason:
        raise MethodRefused(f"{binding.entry} points at another copy than when it was checked; look "
                            f"at it again before approving it.")
    target = os.path.realpath(binding.entry)
    if not config.approve_method(target):
        raise MethodRefused(f"TCC could not keep the approval of {target} for {binding.entry}: its "
                            f"settings on this machine did not store it; approve it again once they "
                            f"can be written.")
    # A trust decision: in the log, where a dialog row does not stay (#169 review m2).
    app_log.logger().info("method: approved %s on this machine, for %s", target, binding.entry)
    return for_project(binding.project_dir)


def relink(binding: Binding) -> Binding:
    """Put a link to TCC's own copy at the project's entry, and whatever was there out of the way.

    `link_skill_into` leaves an existing entry alone, so the entry moves first, by `os.rename` of the
    entry itself: a link moves as a link and is never followed, so what it points at stays where it
    is. It goes to `<project>/.tcc/method-aside/<YYYYMMDD-HHMMSS>/autosound-tuning` — out of
    `.claude/skills/`, where omp would still load it. Nothing is deleted; putting it back is a move.
    A project already on TCC's copy has nothing to move.

    `MethodRefused`, having touched nothing, when `.claude/skills` leads out of the project: what sits
    there — a personal install in `~/.claude/skills`, say — is not the project's to move, and a link
    made there would change every project that reads it. `MethodRefused` too when the move fails,
    and when no link could be made (`link_skill_into` answers None): by then the entry is aside, and
    an empty entry would read `same` with no method in the project.
    """
    project_dir, entry = binding.project_dir, binding.entry
    parent = os.path.realpath(entry.parent)
    if not _inside(parent, os.path.realpath(project_dir)):
        raise MethodRefused(f"{entry.parent} leads out of the project to {parent}, so TCC will not move "
                            f"{entry} or link anything there; make {entry.parent} a folder of the "
                            f"project's own, then re-link it to TCC's copy.")
    moved = None
    if for_project(project_dir).state != SAME:
        try:
            if _present(entry):
                moved = _aside_folder(project_dir) / entry.name
                os.rename(entry, moved)
                # Said when it moved, so a link that then cannot be made leaves it said (m2).
                app_log.logger().info("method: moved %s to %s", entry, moved)
        except OSError as exc:
            raise MethodRefused(f"TCC could not move {entry} out of the way ({_why(exc)}); move it out "
                                f"of {entry.parent} yourself, then re-link it to TCC's copy.") from exc
    if vendor_loader.link_skill_into(project_dir) is None:
        if moved is not None:
            raise MethodRefused(f"TCC moved {entry} to {moved}, but no link to its own copy could be "
                                f"made in its place; make that link by hand, or move the old entry "
                                f"back.")
        raise MethodRefused(f"No link to TCC's own copy could be made at {entry}; make that link by "
                            f"hand.")
    if moved is None:
        app_log.logger().info("method: linked TCC's copy at %s", entry)
    return for_project(project_dir)


def _present(entry: Path) -> bool:
    try:
        os.lstat(entry)
    except (FileNotFoundError, NotADirectoryError):
        return False
    return True


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _aside_folder(project_dir: Path) -> Path:
    """A new folder under `.tcc/method-aside/`, never one already holding an earlier entry: two
    re-links in one second get `<stamp>` and `<stamp>-1`."""
    base = config.tcc_dir(project_dir) / "method-aside"
    stamp = _stamp()
    for n in range(100):
        folder = base / (stamp if n == 0 else f"{stamp}-{n}")
        try:
            folder.mkdir(parents=True)
        except FileExistsError:
            continue
        return folder
    raise FileExistsError(f"{base / stamp} and 99 folders after it already exist")
