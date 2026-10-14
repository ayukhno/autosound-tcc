"""The permission gate's reading of a shell command — which commands a session may run unasked.

Two questions, one per gate mode, asked by both adapters (`core.tuning_session` for the Agent SDK,
`core.omp_session` for omp), so "stop asking" means one thing whichever harness is driving:

* `bash_is_read_only` — is this one of the reads the skill makes all day (the `writes`/`foreign`
  modes let those through and ask about the rest);
* `bash_is_dangerous` — can this not be taken back (the `auto` mode asks about these and nothing
  else; `never` lets them through and says so in the dialog).

It lived inside the Agent-SDK adapter until tcc#128, and `omp_session` imported it from there; the
lexer and the rules are one unit and have nothing to do with which harness runs the model, so they
moved here unchanged.
"""

from __future__ import annotations

import fnmatch
import glob
import itertools
import os
import posixpath
import re
import shlex
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional, Sequence

from autosound_tcc.core import app_log, own_store, project_settings

# Which writes still ask. `writes` gates everything that is not read-only; `foreign` also lets the
# skill write its own files (`process/`, `state/`, and the project files it owns) and asks only
# about what reaches outside them. The choice belongs to the project (SCR-004's "the skill owns
# its namespace" read as a permission rule).
GATE_WRITES = "writes"
GATE_FOREIGN = "foreign"
# Nothing from the harness asks. Chosen by the Arbiter, and narrower than it sounds: TCC's own
# tools raise their confirmations *inside* the tool, so a DSP or REW write still stops for a
# human. What this turns off is the shell-and-file traffic, which is where the noise was -- and a
# gate that fires on `ls` is a gate that gets clicked through, which protects nothing.
GATE_AUTO = "auto"
# Nothing asks, not even what cannot be undone: a delete or an overwrite outside the project goes
# through unasked. The Arbiter's own proposal (2026-10-01, tcc#115) after `auto` stopped him on a
# read for the fourth time (finding 123), and named for what it lifts. Never silent: what `auto`
# would have stopped is said in the dialog (`agent_events.Unasked`). TCC's own tools still
# confirm inside the tool, so a DSP or REW write still stops for a human.
GATE_NEVER = "never"

# What a project starts on. `auto`, not `writes` (user, 2026-08-21): the reason the strictest
# setting was the default -- "start with every write and narrow it if it gets in the way" -- is an
# argument for a gate that TEACHES, and what it taught was clicking through. TCC's own tools still
# confirm inside themselves, so what this default hands over is the shell-and-file traffic and
# nothing that reaches the DSP.
GATE_DEFAULT = GATE_AUTO


def effective_gate(project_choice: str = "", machine_choice: str = "") -> str:
    """Which mode a project runs in: its own choice, else this machine's, else the default.

    Three layers and they are not interchangeable. The PROJECT wins when it was set — that is
    somebody deciding about this car. The MACHINE answer is what a new project starts from.
    And when the machine has never been asked, the window asks it once and keeps the answer.
    """
    return project_choice or machine_choice or GATE_DEFAULT


#: Which field of the project's own store holds its gate (`main_window._GATE_KEY`).
PROJECT_KEY = "gate"

#: What the strip is told when the project's gate cannot be read (R-bt): which gate runs, why, and
#: until when — so the line, which stands until its ✕, stays true once a gate is picked: the pick
#: holds for the run and wins (the re-review, N1). English, as every sentence `core/` writes is.
STRICTEST_SAID = ("{path} holds this project's gate and could not be read, so TCC asks before "
                  "every write — the strictest gate — until a gate is picked or the file can be "
                  "read again")

#: The same, for a store that did not parse and was set aside (`own_store`), with no gate written
#: since (the end-of-branch review, code I1): the file reads again — absent, or the fresh one the
#: next write lands — and the gate it held is gone with the old one, so only a pick ends it. Across
#: a restart too: the next run finds the copy (`STRICTEST_COPY_SAID`).
STRICTEST_ASIDE_SAID = ("{path} held this project's gate and could not be read, so it was set "
                        "aside and TCC asks before every write — the strictest gate — until a "
                        "gate is picked")

#: The same, for a run that did not see it set aside: a store with no gate and a copy of it set
#: aside beside it, left by an earlier run whose count went with it (Fable's re-review of the
#: branch fix, I1). Before, the strictest the line above promised ended at the next launch, with
#: nothing said. The copy stays until the person deletes it, so only a pick ends this either.
STRICTEST_COPY_SAID = ("{path} holds no gate, and {copy} beside it is a copy of it set aside as "
                       "broken, so TCC asks before every write — the strictest gate — until a "
                       "gate is picked")

#: The same, when the folder could not be listed for such a copy while the store itself reads:
#: whether one is there is not known, and an unknown is the strictest, as for R-bt.
STRICTEST_UNLISTED_SAID = ("{path} holds no gate, and its folder could not be looked in for a "
                           "copy of it set aside as broken ({why}), so TCC asks before every "
                           "write — the strictest gate — until a gate is picked")

#: The stores the strictest gate has been said for in this stretch of answering it, with what was
#: said: once per stretch, not once per permission judged — and again when why changes.
_strictest_said: dict[str, str] = {}
#: For each store, how many times it had been set aside (`own_store.times_set_aside`) when a gate
#: was last read from it, or held for the run: set aside more often than that, no gate has been
#: written since.
_gate_seen: dict[str, int] = {}
#: For each store, what looking beside it for a copy set aside found while it held no gate: the
#: store as `stat` saw it then (`own_store.file_state`) with its folder's mtime, the sentence to say (`STRICTEST_COPY_SAID`,
#: `STRICTEST_UNLISTED_SAID`) or "", and the copies seen. Looked again only when the store changed
#: — another process can set it aside after this one looked (Fable's re-review of the branch fix,
#: round 2, I1) — not at every permission judged. Dropped when a gate is picked.
_copy_seen: dict[str, tuple[tuple, str, frozenset]] = {}
#: For each store, the copies beside it when a gate was picked: history the pick ended, never the
#: strictest again this run. A copy made after the pick — another TCC setting the store aside — is.
_copy_history: dict[str, frozenset] = {}
_strictest_lock = threading.Lock()


def project_gate(tcc_dir: Path, machine_choice: str = "",
                 on_strictest: Optional[Callable[[], None]] = None) -> str:
    """`effective_gate` over the project's own store: a gate picked this run first, saved or not
    (`project_settings.get`, #173 I2), then the project's, the machine's, the default.

    A store that is there and cannot be read is no preference of anyone's: the gate it holds is
    unknown, and the machine's answer ran a car set to ask about every write on a looser one,
    with nothing said (I2). So the strictest, `writes`, until it can be read (R-bt) — and said,
    once for each stretch of not being readable, with the store's own refusal said beside it.

    A store that did not parse is the same: `own_store` sets it aside and answers `{}`, and that
    `{}` read as «no gate» ran the car on the machine's gate or `auto` (the end-of-branch review,
    code I1). Set aside with no gate read from the store or held since — a write of another field
    lands a fresh file with none in it — it is the strictest until a gate is picked
    (`STRICTEST_ASIDE_SAID`). `own_store`'s count is the process's; what outlives it is the copy
    set aside beside the store, so a store with no gate and such a copy beside it is the same in
    a later run (`STRICTEST_COPY_SAID`, Fable's re-review of the branch fix, I1) — looked at again
    only when the store or the copies' names and sizes beside it change (#208). A folder that cannot be looked in leaves it unknown: the
    strictest too (`STRICTEST_UNLISTED_SAID`).

    `on_strictest` hears that same first answer: the window pushes the strictest to a session
    already running on another gate, so the session, the menu and the strip agree (the re-review,
    N1). Called after the stretch is marked, so a push that reads the gate again is not a first."""
    path = project_settings.path_for(tcc_dir)
    store = str(path)
    asides = own_store.times_set_aside(path)  # before the read: one during it comes after
    try:
        chosen = project_settings.get(tcc_dir, PROJECT_KEY, "", strict=True) or ""
    except own_store.StoreUnreadable:
        return _strictest(store, STRICTEST_SAID.format(path=store), on_strictest)
    since = own_store.times_set_aside(path)
    with _strictest_lock:
        if chosen:  # read from the store, or held for the run: picked either way
            _gate_seen[store] = max(_gate_seen.get(store, 0), asides)
            seen = _copy_seen.pop(store, None)  # and a copy already beside it is history
            if seen:
                _copy_history[store] = _copy_history.get(store, frozenset()) | seen[2]
        gone = not chosen and since > _gate_seen.get(store, 0)
        seen = None if chosen or gone else _copy_seen.get(store)
        history = _copy_history.get(store, frozenset())
    copy = ""
    if not chosen and not gone:
        state = (own_store.file_state(path), own_store.set_aside_state(path))
        if seen is not None and seen[0] == state:
            copy = seen[1]
        else:
            copy, names = _look_for_copy(path, history)
            with _strictest_lock:
                _copy_seen[store] = (state, copy, names)
    if gone:
        return _strictest(store, STRICTEST_ASIDE_SAID.format(path=store), on_strictest)
    if copy:
        return _strictest(store, copy, on_strictest)
    with _strictest_lock:
        _strictest_said.pop(store, None)
    return effective_gate(chosen, machine_choice)


def _look_for_copy(path: Path, history: frozenset) -> tuple[str, frozenset]:
    """What looking beside a store with no gate found, and the copies seen: the sentence for the
    newest copy of it set aside as broken that a pick has not ended (`history`), the one for a
    folder that cannot be looked in, or "" — no such copy there."""
    try:
        copies = own_store.set_aside_copies(path)
    except OSError as exc:
        return STRICTEST_UNLISTED_SAID.format(path=path, why=exc.strerror or str(exc)), frozenset()
    live = [name for name in copies if name not in history]
    said = STRICTEST_COPY_SAID.format(path=path, copy=live[-1]) if live else ""
    return said, frozenset(copies)


def _strictest(store: str, said: str, on_strictest: Optional[Callable[[], None]]) -> str:
    """`GATE_WRITES`, said when this stretch of it starts or its reason changes, and pushed
    (`on_strictest`) when the stretch starts."""
    with _strictest_lock:
        before = _strictest_said.get(store)
        _strictest_said[store] = said
    if before != said:
        app_log.report(said)
        if before is None and on_strictest is not None:
            on_strictest()
    return GATE_WRITES


# Read-only commands the skill runs constantly. Anything outside this set still works -- it just
# has to be confirmed by the Arbiter first, rather than being refused outright.
_SAFE_COMMANDS = frozenset(
    {"ls", "cat", "head", "tail", "wc", "grep", "rg", "find", "file", "stat", "pwd", "echo", "which",
     # Path questions the skill asks constantly, because its install is a symlink and every
     # "where am I really" answer costs a permission dialog otherwise.
     "readlink", "realpath", "basename", "dirname", "sort", "uniq", "cut", "column", "jq"}
)
_SAFE_GIT_SUBCOMMANDS = frozenset({"status", "log", "diff", "show", "branch", "remote"})
# `git remote` reads the URL; `git remote set-url` rewrites where a push goes. Same for `branch`:
# listing is a read, `-D`/`-M` throw work away. The subcommand alone never said which one it was.
_SAFE_GIT_REMOTE_ARGS = frozenset({"-v", "--verbose", "show", "get-url"})
_UNSAFE_GIT_BRANCH_ARGS = frozenset(
    {"-D", "-d", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy", "-f", "--force", "-u",
     "--unset-upstream", "--edit-description"}
)
# `find` walks and names -- until an action turns the walk into a command run on every hit. This
# is the whole distance between `find . -name '*.mdap'` and `find / -exec rm -rf {} +`.
_FIND_ACTIONS = frozenset(
    {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
)
# Everything before the first predicate is a starting point, and starting points are paths.
_FIND_LEADING_FLAGS = frozenset({"-H", "-L", "-P"})
#: The options `find` takes before its paths that stand alone, GNU and macOS together; `-f` (macOS:
#: a path), `-D` (GNU: a value) and `-O<n>` are read apart (`_find_roots`, tcc#128).
_FIND_FLAG_LETTERS = frozenset("HLPEXdsx")
#: Predicates and actions a `find` line may start with when it names no path. Anything else that
#: starts with `-` before the paths is read as options — and an unknown one asks.
_FIND_PREDICATES = frozenset({
    "-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-regex", "-iregex",
    "-lname", "-ilname", "-type", "-xtype", "-maxdepth", "-mindepth", "-mtime", "-mmin", "-atime",
    "-amin", "-ctime", "-cmin", "-newer", "-newermt", "-size", "-perm", "-user", "-group", "-uid",
    "-gid", "-nouser", "-nogroup", "-empty", "-executable", "-readable", "-writable", "-links",
    "-inum", "-samefile", "-print", "-print0", "-printf", "-ls", "-prune", "-quit", "-delete",
    "-exec", "-execdir", "-ok", "-okdir", "-depth", "-follow", "-mount", "-xdev", "-noleaf",
    "-true", "-false", "-not", "-and", "-or", "-regextype", "-daystart", "-fstype", "-fprint",
    "-fprint0", "-fprintf", "-fls", "-flags", "-help", "-version",
})
# Commands whose non-flag arguments are files to read. They are bounded by the same roots as
# `Read`/`Grep`/`Glob` (`_read_roots_for`), because "the agent may read the project" is one
# policy, not one per tool: `cat ~/.ssh/id_rsa` is outside it however read-only `cat` is.
_PATH_ARGUMENT_COMMANDS = frozenset(
    {"cat", "head", "tail", "grep", "rg", "find", "ls", "wc", "stat", "file"}
)
# ... of which these take a pattern first, and a pattern is not a path.
_PATTERN_FIRST_COMMANDS = frozenset({"grep", "rg"})
_PATTERN_FLAGS = frozenset({"-e", "--regexp"})
# Reading commands that can be told to write their output to a file instead of stdout.
_OUTPUT_FLAG_COMMANDS = frozenset({"sort", "uniq", "jq", "cut", "column"})
# `rew_tool` scripts that only read REW and compute. `apply.py` is pointedly not here: it writes
# the ledger, which is a banked decision and belongs in front of a human.
_SAFE_REW_SCRIPTS = frozenset(
    {
        "rew_tool.py",
        "analysis.py",
        "joint_analysis.py",
        "curve_view.py",
        "target_curves.py",
        "target_bands.py",
        "dsp_math.py",
        "eq_gate.py",
        "spot_check.py",
        # `verify.py`, not `verify_measurements.py`: the latter was the Passat session's one-off
        # script and the method deleted it (skill 2026-09-07, SKL-001). `verify.py` answers the
        # question the checklist actually asks — does this measurement exist, and is it usable —
        # and keeps those two apart, which is two different colours of row and two different
        # conversations with the tuner.
        "verify.py",
        "level_offsets.py",
        "xover_select.py",
        "equal_loudness.py",
        "nono_curves.py",
        "make_plot.py",
        "atf_eq.py",
    }
)
# Substitution hides a whole second command inside an approved-looking one, and there is no
# reading of `$(...)` or backticks that keeps the allowlist meaningful. Always ask — but only
# where the shell would actually substitute, which is what `_has_substitution` below decides.

# Redirects that write a file. `2>&1`, `2>/dev/null` and `>/dev/null` are not among them -- they
# move or discard a stream, which is why the model appends one to almost every command it runs.
# Treating those as writes is what put a permission dialog in front of `ls -la … 2>&1`, and a gate
# that fires on `ls` is a gate the Arbiter learns to click through.
_DISCARD_REDIRECT = re.compile(r"(?:\d?>&\d|\d?>\s*/dev/null|\d?>&-)")
_FILE_REDIRECT = re.compile(r"[<>]")

# What separates one command from the next. Each part is judged on its own: a chain of read-only
# commands is read-only, and refusing the whole chain because it *is* a chain is what made the
# skill's own "where does this symlink point" one-liner need approval.
_SEPARATORS = re.compile(r"\|\||&&|[;|]")


def _is_within(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False



def _within_roots(argument: str, roots: tuple[Path, ...]) -> bool:
    """Whether a path argument lands inside the roots the agent may read.

    Relative paths are resolved against the *project*, not this process's working directory: the
    agent runs with `cwd=project_dir` (`_options`), while TCC's own cwd is wherever the GUI was
    started from. `~` is expanded here because the shell would have expanded it too, and a check
    that reads `~/.ssh/id_rsa` as a relative name inside the project is no check at all.
    """
    if not roots:
        return False
    path = Path(argument).expanduser()
    if not path.is_absolute():
        path = roots[0] / path
    return any(_is_within(path, root) for root in roots)


def _find_is_read_only(rest: list[str], roots: tuple[Path, ...]) -> bool:
    index = 0
    while index < len(rest) and rest[index] in _FIND_LEADING_FLAGS:
        index += 1
    while index < len(rest) and not rest[index].startswith("-") and rest[index] not in ("(", "!"):
        if not _within_roots(rest[index], roots):
            return False
        index += 1
    return not any(argument in _FIND_ACTIONS for argument in rest[index:])


def _path_arguments_are_within_roots(name: str, rest: list[str], roots: tuple[Path, ...]) -> bool:
    pattern_pending = name in _PATTERN_FIRST_COMMANDS
    value_of_flag = False
    for argument in rest:
        if value_of_flag:
            value_of_flag = False
            continue
        if argument == "--":
            continue
        if argument.startswith("-") and argument != "-":
            if name in _PATTERN_FIRST_COMMANDS and argument in _PATTERN_FLAGS:
                value_of_flag = True
                pattern_pending = False
            continue
        if pattern_pending:
            pattern_pending = False
            continue
        if not _within_roots(argument, roots):
            return False
    return True


def _writes_its_output_to_a_file(rest: list[str]) -> bool:
    return any(
        argument == "-o" or argument.startswith("-o") and len(argument) > 2 or argument.startswith("--output")
        for argument in rest
    )


def _git_is_read_only(rest: list[str]) -> bool:
    if not rest or rest[0] not in _SAFE_GIT_SUBCOMMANDS:
        return False
    subcommand, *arguments = rest
    if subcommand == "remote":
        return not arguments or arguments[0] in _SAFE_GIT_REMOTE_ARGS
    if subcommand == "branch":
        return not any(
            argument in _UNSAFE_GIT_BRANCH_ARGS or argument.startswith("--set-upstream")
            for argument in arguments
        )
    return True


#: Commands that cannot be taken back. NOT "everything that writes" — the gate's whole point is
#: that ordinary writes are silent, and a classifier that flags `mkdir` teaches the Arbiter to
#: click through, which is worse protection than asking nothing at all (the 2026-08-21 noise).
#: What is here either destroys data outside a single named file, overwrites a device, rewrites
#: published history, or runs something fetched from the network.
#: `format` is Windows' `format.com`, which Git Bash finds on its PATH (tcc#128).
_RUINOUS = frozenset({"mkfs", "fdisk", "shutdown", "reboot", "halt", "poweroff", "diskutil",
                      "format", "stop-computer", "restart-computer"})
#: `systemctl poweroff` and its kin: the machine goes down with whatever was unsaved.
_SYSTEMCTL_DOWN = frozenset({"poweroff", "reboot", "halt", "kexec"})
#: Writers that destroy what a file held — a delete's twin: judged by reach, as `rm` is (Fable's
#: final review, I1: `truncate -s 0 ~/*`, `echo | tee ~/*`).
_OVERWRITERS = frozenset({"truncate", "tee", "shred", "unlink", "srm"})
#: PowerShell's: they empty or replace what a file held.
_PS_OVERWRITERS = frozenset({"clear-content", "clc", "set-content"})
#: PowerShell's listings — what feeds a delete down a pipe or a `foreach`.
_PS_LISTERS = frozenset({"get-childitem", "gci", "dir", "ls", "get-item", "gi", "resolve-path",
                         "rvpa"})
#: PowerShell's process stoppers and listing.
_PS_STOPPERS = frozenset({"stop-process", "spps", "kill"})
_PS_PROCESS_LISTERS = frozenset({"get-process", "gps", "ps"})
#: A .NET call that deletes, overwrites or runs code — `[IO.Directory]::Delete(…)`,
#: `(Get-Item …).Delete($true)`, `[scriptblock]::Create(…)`, `.Invoke()`: the reader does not take
#: PowerShell's member calls apart, so the call itself asks (Fable's final review, I2).
_PS_DOTNET = re.compile(r"(?:::|\.)\s*(?:delete\w*|writeall\w*|create|invoke\w*|start|kill|format"
                        r"|truncate|setlength|encrypt|movedirectory|copydirectory)\s*\(", re.I)
#: A registry key by its hive: `HKCU:\\Software`, `HKEY_LOCAL_MACHINE\\SYSTEM`, `Registry::HKLM\\…`.
_REGISTRY = re.compile(r"(?:registry::)?(hkey_current_user|hkcu|hkey_local_machine|hklm|"
                       r"hkey_classes_root|hkcr|hkey_users|hku|hkey_current_config|hkcc):?(?=/|$)",
                       re.I)
#: Keys a delete of which is somebody's whole configuration: a hive's own first level, and these.
_REGISTRY_WIDE_SECOND = frozenset({"microsoft", "classes", "policies", "wow6432node"})
#: `mkfs.ext4`, `mkfs.vfat` — the family is spelled with a suffix, and matching the bare name
#: would let every real invocation through.
_RUINOUS_PREFIXES = ("mkfs.",)
#: Windows' disk-level tools — PowerShell's Storage cmdlets and `diskpart`: each formats, wipes,
#: repartitions or takes a disk away, as `mkfs`/`diskutil` do in bash, and any invocation asks, as
#: `diskutil list` does (group fix C2: they passed `auto` and a `Bash` tick). PowerShell has no
#: default aliases for them and no abbreviated command names; `Storage\Clear-Disk` and
#: `diskpart.exe` reduce to these through `_command_name`. `format D:` is `_RUINOUS`'s `format`.
_DISK_TOOLS = frozenset({"format-volume", "clear-disk", "remove-partition", "initialize-disk",
                         "set-disk", "remove-volume", "reset-physicaldisk", "remove-physicaldisk",
                         "remove-virtualdisk", "remove-storagepool", "diskpart"})
#: What runs the program named after it: PowerShell's `Start-Process`/`saps`/`start`, cmd's `start`.
_STARTERS = frozenset({"start-process", "saps", "start"})
#: A PowerShell parameter bound with a colon — `-Path:'C:\Users'`: a parameter whatever quotes its
#: value carries (the quotes only made `quoted` true; the narrow re-review of the group fix, 1).
_COLON_PARAM = re.compile(r"-[A-Za-z][\w-]*:")
#: A raw device by its Win32 name — `\\.\PhysicalDrive1`, `\\.\Harddisk0Partition1`, a volume
#: `\\.\D:` (not a path under it: `\\?\C:\Users\x` is a long path) — Windows' `/dev/disk2`.
#: Named anywhere in a command it asks: writing it overwrites a disk, and nothing in a tune reads
#: one. bash leaves one backslash of a doubled pair, so one or two are taken.
_RAW_DEVICE = re.compile(r"(?:^|[^\w.])[\\/]{1,2}[.?][\\/]?(?:physicaldrive\d|harddisk\d|"
                         r"harddiskvolume\d|globalroot[\\/]|[a-z]:(?![\\/]*\w))", re.I)
#: Writing over a path nobody in this project owns. `> /etc/hosts` is not a chain and not a
#: recursive delete, so nothing above catches it, and it is exactly the quiet kind.
_PROTECTED_ROOTS = ("/etc/", "/usr/", "/bin/", "/sbin/", "/System/", "/Library/", "/var/", "/dev/")
#: `rm` is judged by its arguments rather than by its name: `rm build/tmp.json` is a Tuesday.
_RM_RECURSIVE = re.compile(r"(?:^|\s)-[a-zA-Z]*[rR][a-zA-Z]*(?:\s|$)")
#: The paths that are somebody's whole machine or whole home — `_is_wide_target` reads a target
#: against them. A recursive delete of one of these is the case this check exists for. `~` and `/`
#: were known; `/Users`, the system's own folders and a home spelled as a path were not (tcc#128).
#: Lower case, because the comparison is: macOS and Windows disks ignore case.
_SYSTEM_DIRS = frozenset({"/etc", "/usr", "/bin", "/sbin", "/system", "/library", "/var", "/dev",
                          "/users", "/home", "/applications", "/volumes", "/private", "/opt",
                          "/root", "/mnt", "/media"})
#: One level below these is a whole thing: a home (`/Users/<x>`, `/home/<x>`), a mounted disk
#: (`/Volumes/<x>`, `/mnt/<x>`, `/media/<x>`); `/media/<user>/<x>` is a disk too (Ruling 43).
_ONE_LEVEL_WIDE = re.compile(r"/(?:users|home|volumes|mnt)/[^/]+|/media/[^/]+(?:/[^/]+)?")
#: The same on a Windows disk, as Git Bash, WSL and Cygwin spell it: a drive, its system folders,
#: the folder the homes live in, and one home.
_WINDOWS_WIDE = re.compile(r"(?:[a-z]:|/[a-z]|/mnt/[a-z]|/cygdrive/[a-z])"
                           r"(?:/(?:windows|program files(?: \(x86\))?|programdata|users(?:/[^/]+)?))?")
#: The names that make a path wide under some folder, for a bracket glob to be tried against:
#: `/[e]tc`, `C:/[W]indows`, `~/[.][.]`, `/[c]` (a drive, as Git Bash spells it).
_WIDE_NAMES = (".", "..", *sorted(name.lstrip("/") for name in _SYSTEM_DIRS), "windows",
               "program files", "program files (x86)", "programdata", *"abcdefghijklmnopqrstuvwxyz")
#: Filters that pass on lines unchanged, for `_keeps_names`: (options alone, options with a value,
#: long options → whether they take a value, whether the first operand is a pattern).
_NAME_FILTERS: dict[str, tuple[str, str, dict[str, bool], bool]] = {
    "grep": ("vEFGPiwxsyz", "efm", {"--invert-match": False, "--ignore-case": False,
                                     "--extended-regexp": False, "--fixed-strings": False,
                                     "--basic-regexp": False, "--perl-regexp": False,
                                     "--word-regexp": False, "--line-regexp": False,
                                     "--no-messages": False, "--null-data": False,
                                     "--regexp": True, "--file": True, "--max-count": True}, True),
    "head": ("q", "n", {"--lines": True, "--quiet": False, "--silent": False}, False),
    "tail": ("qr", "n", {"--lines": True, "--quiet": False, "--silent": False}, False),
    "sort": ("bdfghiMnrRsuVz", "ktST", {"--reverse": False, "--unique": False,
                                         "--ignore-case": False, "--numeric-sort": False,
                                         "--version-sort": False, "--key": True,
                                         "--field-separator": True}, False),
    "uniq": ("diuDz", "fsw", {"--repeated": False, "--unique": False, "--ignore-case": False,
                              "--skip-fields": True, "--skip-chars": True,
                              "--check-chars": True}, False),
}
#: PowerShell's names for Remove-Item, its home spelled as a variable, and its keywords — whose
#: conditions and bodies `_powershell_line_is_dangerous` reads as statements of their own.
_PS_REMOVERS = frozenset({"remove-item", "ri", "rm", "del", "rd", "rmdir", "erase"})
_PS_HOME = re.compile(r"\$(?:home|\{home\}|env:userprofile|\{env:userprofile\})(?![\w:])",
                      re.IGNORECASE)
_PS_KEYWORDS = frozenset({"if", "elseif", "else", "foreach", "for", "while", "do", "until",
                          "switch", "try", "catch", "finally", "function", "filter", "param",
                          "begin", "process", "end", "return", "break", "continue", "exit",
                          "throw"})
#: The commands that move the folder a line runs in, by the shell that reads them.
_CD_COMMANDS = {"bash": ("cd", "pushd", "chdir"), "cmd": ("cd", "chdir", "pushd"),
                "powershell": ("cd", "chdir", "sl", "set-location", "pushd", "push-location")}
#: What a word the line does not spell starts with when nothing spelled stands before it: `$x`,
#: `` `…` ``, `{a,b}`, `$'\x2d'`, cmd's `%x%`, and the word `xargs` appends (`_xargs_command`).
_EXPANSION_STARTS = ("$", "`", "{", "\\", "%", "…")
#: A head whose only expansion is the home: `"$HOME/.local/bin/omp"`, `${HOME}/bin/tool`. Every
#: part after it is a plain name, so the last one is what runs.
_HOME_HEAD = re.compile(r"(?:\$HOME|\$\{HOME\})(?:/[\w.+@-]+)*/([\w.+-]+)")
#: cmd's own deletes. `/s` makes `rd` take the whole tree and `del` reach every folder under it —
#: the Windows spelling of `rm -r` (tcc#128).
_WINDOWS_DELETES = frozenset({"rd", "rmdir", "del", "erase"})
#: A cmd switch: `/s`, `/Q`, `/s/q`, `/a:h` — and Git Bash's `//c` for the `/c` it would otherwise
#: turn into a path.
_WINDOWS_SWITCH = re.compile(r"(?://?[A-Za-z](?::[A-Za-z0-9-]*)?)+")
#: A name with its switches glued on, `rd/s/q`; and cmd's `/c` with its line glued on, `/crd`.
_CMD_GLUED_SWITCH = re.compile(r"([\w-]+)(/.*)")
_CMD_GLUED_LINE = re.compile(r"(?://?[A-Za-z](?::[A-Za-z0-9-]*)?)*?//?[ckCK]([^/:].*)", re.S)
#: `curl … | sh` and its family: what runs is fetched at that moment and nobody has read it.
_FETCHERS = frozenset({"curl", "wget", "fetch"})
#: Shells. What they run is a script, and a script written on the line is read like the line —
#: `bash -c 'rm -rf ~'` was a command named `bash` until tcc#115.
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
#: Interpreters whose program is NOT read: `python3 -c` passes as it always did. What they must not
#: run is a program that is another command's output — `python3 -c "$(curl …)"` is `curl … | python3`.
#: Lower case, as `_command_name` gives names: `Rscript` is `rscript` here.
_INTERPRETERS = frozenset({"python", "python3", "pypy", "pypy3", "ruby", "perl", "node", "php",
                           "osascript", "rscript", "lua"})
#: Interpreter options that take the next word as a value — a library, a folder, a setting — so the
#: walk steps over it to the program. `-r` is php's code but ruby's and node's library, and the walk
#: stopped at `json` in `ruby -r json -e "$(curl …)"` (review of tcc#115, parked into tcc#128).
_INTERPRETER_VALUES = {
    "python": frozenset({"-W", "-X"}),
    "ruby": frozenset({"-r", "-I", "-C", "-E"}),
    "node": frozenset({"-r", "--require", "--import", "--loader", "--experimental-loader", "-C",
                       "--conditions"}),
    "perl": frozenset({"-I"}),
    "php": frozenset({"-c", "-d"}),
    "lua": frozenset({"-l"}),
    "osascript": frozenset({"-l", "-s"}),
}
#: `git push` options that rewrite or delete what others already have; `--force-with-lease` and
#: `--force-if-includes` are `--force` with a condition, and still a force.
_PUSH_REWRITES = frozenset({"--force", "--delete", "--mirror", "--prune"})
#: `find` actions that run a command on every hit. `-exec rm` asked; `-execdir` is the same delete
#: run from each hit's folder, `-ok`/`-okdir` the same behind a prompt (tcc#128).
_FIND_RUNNERS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})


def bash_is_dangerous(command: str, roots: Sequence[Path]) -> bool:
    """Whether this command has to reach the Arbiter even when the gate is set to "don't ask".

    "Don't ask" is the user's decision and it stands (2026-09-06): the noise it removed was
    ordinary safe commands, and since HUB-027 those are silent. It was never a decision to let
    something unrecoverable through unseen — and the gate's `auto` branch used to return Allow
    BEFORE Bash was looked at, so nothing checked a command at all (HUB-028).

    Deliberately narrow, and the narrowness is the point. Everything this flags is destructive
    beyond one named file, overwrites a device, rewrites published history, or executes something
    just fetched from the network. Anything else — including ordinary writes and deletes inside
    the project — passes silently, because a warning that fires on `mkdir` is a warning nobody
    reads by the third day.

    A substitution and a loop are READ, not refused (tcc#115). Refusing every `$( … )` was safe and
    wrong: `f=$(grep … | head -1); grep -n … $f` only reads, and a mode set to never ask stopped on
    it as «Команда, яку не відкотити» — the fourth time (finding 123, after 7, 15 and the `|` of
    0.1.41). So `_Reader` takes the line apart the way the shell does, and every command it finds —
    at the top, inside `$( … )` or backticks, in a loop or `if` body, in `bash -c '…'` — is judged
    by the same narrow rules. The line is dangerous when one of them is.

    Two things keep "the way past the check is one backtick" closed. What the reader cannot read
    stays dangerous: quoting that never closes, a `case` or a function it does not take apart,
    nesting deeper than anybody writes. And a substitution's OUTPUT is unknown — it is another
    command's — so where it lands in what the rules judge (the name of what runs, a recursive
    delete's target, a redirect, the program of `sh -c` or `python3 -c`) the answer is dangerous:
    `rm -rf $(cat list)` and `sh -c "$(curl …)"` ask, however harmless the inside reads.
    """
    with _in_project(roots):
        return _script_is_dangerous(command.strip(), depth=0)


#: The project a line runs in while the danger check reads it: what a link is resolved against
#: (`roots[0]`, as `_read_roots_for` gives it). None when the caller named none — then only the
#: line's text is judged, as it always was.
_PROJECT: ContextVar[Optional[Path]] = ContextVar("shell_gate_project", default=None)
#: Every root the line may read — the project and the method's copy (`read_roots`): what is
#: «inside» for the Arbiter's rule on recursive and glob deletes (`_outside_roots`).
_ROOTS: ContextVar[tuple[Path, ...]] = ContextVar("shell_gate_roots", default=())


@contextmanager
def _in_project(roots: Sequence[Path]) -> Iterator[None]:
    token = _PROJECT.set(Path(roots[0]) if roots else None)
    every = _ROOTS.set(tuple(Path(root) for root in roots))
    after = _AFTER_ANOTHER.set(False)  # each line starts with nothing run before it
    try:
        yield
    finally:
        _AFTER_ANOTHER.reset(after)
        _ROOTS.reset(every)
        _PROJECT.reset(token)


def _has_substitution(text: str) -> bool:
    """Whether the shell would run a second command inside this one.

    The shell's own rule, and nothing wider: inside SINGLE quotes a backtick and a `$(` are just
    characters. The check used to be a regex over the whole line, so a markdown table written with
    `printf '| `target-curves/` | … |'` counted as a substitution, and a gate set to never ask
    stopped for it (the user, with the screenshot, 2026-09-19). Same shape as the `|` inside
    `grep "a\\|b"` a week earlier: quoting is part of reading a command, not a detail.

    Unterminated quoting is not decided here. It reaches `_split_on_separators`, which answers
    `None` for it, and unreadable stays dangerous.
    """
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote == "'":
            if ch == "'":
                quote = ""
            i += 1
            continue
        if ch == "\\" and quote != "'":
            i += 2  # escaped: the next character is a character, whatever it is
            continue
        if quote == '"':
            if ch == '"':
                quote = ""
                i += 1
                continue
        elif ch in "'\"":
            quote = ch
            i += 1
            continue
        if ch == "`" or text.startswith("$(", i):
            return True
        i += 1
    return False


#: How deep a substitution inside a substitution, or a `bash -c` inside one, is followed before the
#: line counts as unreadable. Real commands nest two or three deep; past this nobody wrote it to be
#: read — and a recursion with no floor is a crash inside the gate.
_MAX_DEPTH = 8
#: Reserved words that open or close a compound command. They are not what runs: `do rm -rf "$f"`
#: read as a command named `do` is how a loop body would pass unread (tcc#115).
_RESERVED = frozenset({"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!",
                       "{", "}"})
#: Constructs the reader does not take apart. A `case` pattern ends in `)`, a function is a body
#: defined now and run later; read wrongly, either could hide a command, so they stay unknown.
_UNREAD_KEYWORDS = frozenset({"case", "esac", "function", "coproc"})
#: Words that run the command written after them. Their own options differ and some take a value
#: (`nice -n 5`, `timeout 5`, `xargs -n 1`), so every tail of the line is judged as a command.
#: `call` and `start` are cmd's: `cmd /c call rd /s /q C:\` (tcc#128).
_WRAPPERS = frozenset({"env", "command", "builtin", "exec", "nohup", "nice", "time", "timeout",
                       "stdbuf", "ionice", "caffeinate", "setsid", "flock", "chronic", "unbuffer",
                       "noglob", "nocorrect", "repeat", "-", "call", "start"})
#: `xargs` options that take a value — attached (`-n1`) or as the next word (`-n 1`) — and the
#: ones whose value can only be attached (`-i{}`, `-l5`, `-eEOF`). GNU and BSD together.
_XARGS_VALUE_FLAGS = frozenset("InLsPdEaJRS")
_XARGS_ATTACHED_FLAGS = frozenset("ile")
_XARGS_LONG_VALUES = frozenset({"--arg-file", "--delimiter", "--max-chars", "--max-procs",
                                "--max-args", "--process-slot-var"})
#: Redirections that write a file. `>&` only when what follows is a file, not a descriptor.
_WRITE_REDIRECTS = frozenset({">", ">>", ">|", ">!", ">>!", "&>", "&>>", "&>|", "&>!", "<>", ">&"})
#: Longest first, so `<<<` is not read as `<<` and a `<`.
#: Where a write is not a file written: a stream thrown away or shown. `2>/dev/null` is on most lines
#: an agent writes, and asking about it is finding 123 over again (review of tcc#115).
_STREAM_DEVICES = frozenset({"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"})
_REDIRECT_OPERATORS = ("&>>", "&>|", "&>!", "&>", "<<<", "<<-", "<<", "<>", "<&", ">>!", ">>",
                       ">|", ">!", ">&", "<", ">")
_PARAM_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]*\])?\+?=")
_HOME_ASSIGNMENT = re.compile(r"HOME(?:\[[^\]]*\])?\+?=")
#: An assignment by expansion: `${NAME:=value}` and `${NAME=value}` set NAME when it is unset.
_DEFAULT_ASSIGNMENT = re.compile(r"\$\{(\w+)(?:\[[^\]]*\])?:?=")
_ARRAY_START = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
_FD = re.compile(r"[0-9]+|\{[A-Za-z_][A-Za-z0-9_]*\}")
_DECLARERS = frozenset({"export", "local", "declare", "typeset", "readonly"})
_STDIN_READERS = frozenset({"read", "mapfile", "readarray"})


class _Unreadable(Exception):
    """The reader met something it does not take apart. Unknown is not safe."""


@dataclass
class _Word:
    """One shell word as the rules see it: its text with the quotes removed, and where its value
    comes from. An expansion is kept as written (`$HOME`, `$(…)`), because the rules compare text."""

    text: str = ""
    started: bool = False
    quoted: bool = False
    #: Its value is not written on the line: a variable, a substitution, `{a,b}`, `$'\x72'`.
    dynamic: bool = False
    #: It holds another command's output: `$( … )`, a backtick, `<( … )`.
    output: bool = False
    glob: bool = False
    #: The variables it reads — for `f=$(…); bash -c "$f"`.
    refs: set[str] = field(default_factory=set)

    def take(self, other: "_Word") -> None:
        self.dynamic |= other.dynamic
        self.output |= other.output
        self.refs |= other.refs


@dataclass
class _Command:
    """One simple command, with what it writes to and what it reads."""

    words: list[_Word] = field(default_factory=list)
    redirects: list[tuple[str, _Word]] = field(default_factory=list)
    #: Heredoc bodies and here-strings: what the command reads on stdin.
    stdin: list[_Word] = field(default_factory=list)
    piped: bool = False
    #: A `( … )` stood here; the commands inside it were read on their own.
    compound: bool = False
    #: The command whose output this one reads in a pipeline: `ls` in `ls | xargs chmod 755`.
    producer: Optional[_Command] = None
    #: The subshells it runs in, outermost first: a `cd` in one does not move the line outside it.
    scope: tuple[int, ...] = ()
    #: Where it runs, as `_follow_cd` reads the line: "" the project, a path (relative to the
    #: project, or absolute, or under `~`), None a folder the line does not spell (Ruling 49).
    cwd: Optional[str] = ""

    def is_empty(self) -> bool:
        return not (self.words or self.redirects or self.stdin or self.compound)


@dataclass
class _Heredoc:
    command: _Command
    delimiter: str
    quoted: bool
    strip_tabs: bool
    depth: int


def _script_is_dangerous(text: str, depth: int, inherited: Iterable[str] = (),
                         cwd: Optional[str] = "") -> bool:
    """`inherited`: the names the line around this script has already made unknown. A script body —
    `bash -c '…'`, a heredoc fed to a shell, `trap`, `alias` — runs with the variables of the line
    that holds it, so `HOME='…' bash -c '$HOME/x'` is `HOME='…'; $HOME/x` (review of tcc#128).
    `cwd`: where it runs — `cd / && bash -c 'rm -rf *'` deletes `/*` (Ruling 49)."""
    try:
        commands: list[_Command] = []
        _Reader(text, commands, depth).read()
        _follow_cd(commands, cwd)
        tainted = _tainted(commands, inherited)
        for command in commands:
            if _command_is_dangerous(command, tainted, depth):
                return True
            _ran(command.words)
        return False
    except (_Unreadable, RecursionError):
        return True  # unknown is not safe


#: Ids for subshells, so a `cd` in one is known not to move the commands outside it.
_SUBSHELLS = itertools.count(1)


def _follow_cd(commands: list[_Command], cwd: Optional[str]) -> None:
    """Set each command's `cwd` — where it runs — by the `cd`, `pushd` and `chdir` before it on the
    line, in order. A subshell starts where its parent stood and keeps its own `cd`s; a piped `cd`
    runs in a subshell of its own and moves nothing. Every separator counts alike — `;`, `&&`, `||`,
    a newline: what runs after `cd x || …` is not known to run where it started (Ruling 49)."""
    where: dict[tuple[int, ...], Optional[str]] = {(): cwd}
    cdpath = False
    for command in commands:
        scope = command.scope
        while scope not in where:
            scope = scope[:-1]
        command.cwd = here = where[scope]
        if command.piped:
            continue
        for words in _segments(command):
            cdpath |= _sets_cdpath(words)
            moved, target = _cd_target(words, here, shell="bash", cdpath=cdpath)
            if moved:
                here = where[command.scope] = target


def _sets_cdpath(words: list[_Word]) -> bool:
    """Whether a command gives CDPATH a value — `CDPATH=/ cd x`, `export CDPATH=/`: from then on a
    relative `cd` may land in any of its folders (Ruling 50). An empty one is no CDPATH."""
    return any((match := _ASSIGNMENT.match(word.text)) and match.group(1) == "CDPATH"
               and (word.dynamic or word.text[match.end():]) for word in words)


def _cd_target(words: list[_Word], here: Optional[str], shell: str,
               cdpath: bool = False) -> tuple[bool, Optional[str]]:
    """(whether `words` change the folder, where to: a path, or None when the line does not spell
    it). bash's `cd` alone is the home and `cd -` the last folder; cmd's `cd` alone only prints.
    `builtin cd` and `command cd` are `cd` (`command -v cd` only prints); with a CDPATH set, a
    relative target that does not start with `.` is looked up in it, so it is not known (Ruling 50)."""
    cdpath |= _sets_cdpath(words)
    while words and _ASSIGNMENT.match(words[0].text):
        words = words[1:]
    while shell == "bash" and words and _command_name(words[0].text) in ("builtin", "command"):
        if len(words) > 1 and words[1].text in ("-v", "-V"):
            return False, here
        words = words[2:] if len(words) > 1 and words[1].text == "-p" else words[1:]
    if not words:
        return False, here
    name = _command_name(words[0].text)
    if name not in _CD_COMMANDS.get(shell, ()):
        return False, here
    arguments = words[1:]
    if shell == "powershell":
        # `-Path`, `-LiteralPath`: the path is the word after; `-Path:'C:\'` carries it.
        arguments = [_Word(text=word.text.partition(":")[2], started=True,
                           dynamic=word.dynamic) if _is_parameter(word) and ":" in word.text
                     else word for word in arguments
                     if not _is_parameter(word) or word.text.partition(":")[2]]
    else:
        while arguments and (arguments[0].text in ("-L", "-P", "-e", "-@", "-n", "--")
                             or shell == "cmd" and _is_windows_switch(arguments[0].text)):
            arguments = arguments[1:]
    if not arguments:
        return (False, here) if shell == "cmd" else (True, None if name == "pushd" else "~")
    target = arguments[0]
    if target.dynamic or target.output or target.text in ("-", "") or target.text[:1] in "+-%!":
        return True, None
    if cdpath and not _is_absolute(target.text) and not target.text.startswith("."):
        return True, None  # `CDPATH=/ cd Users`: /Users, if CDPATH has it first
    if _is_absolute(target.text) or here == "":
        return True, target.text
    return True, None if here is None else posixpath.join(here, target.text.replace("\\", "/"))


def _is_absolute(text: str) -> bool:
    """A path that does not depend on the folder a command runs in: `/x`, `\\x`, `~`, `C:\\x`, and a
    registry key by its hive (`HKCU:\\Software`)."""
    return text.startswith(("/", "\\", "~")) or bool(re.match(r"[A-Za-z]:", text)) or bool(
        _REGISTRY.match(text.replace("\\", "/")))


def _is_wide_here(text: str, cwd: Optional[str]) -> bool:
    """`_is_wide_target` of an operand where its command runs: a relative one joined to the
    folder a `cd` moved to, and wide outright when that folder is not spelled (Ruling 49)."""
    if cwd == "" or _is_absolute(text):
        return _is_wide_target(text)
    if cwd is None:
        return True
    return _is_wide_target(posixpath.join(cwd.replace("\\", "/"), text.replace("\\", "/")))


class _Reader:
    r"""Takes a command line apart the way the shell would — close enough to judge it.

    Not a shell. It knows quoting, by the shell's own rule: a backslash escapes inside double quotes
    and not inside single ones, which is what keeps `grep "a\|b"` one word (2026-09-11) and a
    markdown backtick inside `'…'` text (2026-09-19). It knows the separators (`;`, `&&`, `||`, `|`,
    `&`, a newline), comments, `$( … )`, backticks, `<( … )`, `${ … }`, `( … )`, redirections and
    heredocs. Every simple command it meets — at the top, inside a substitution, in a loop body —
    lands in `commands`. Anything else raises `_Unreadable`, and unreadable is dangerous.
    """

    def __init__(self, text: str, commands: list[_Command], depth: int,
                 scope: tuple[int, ...] = ()) -> None:
        if depth > _MAX_DEPTH:
            raise _Unreadable
        self.text = text
        self.i = 0
        self.commands = commands
        self.depth = depth
        self.heredocs: list[_Heredoc] = []
        self.scope = scope

    def _subshell(self, depth: int) -> None:
        """`( … )`, `$( … )`, `<( … )`: commands of a subshell, whose `cd` stays inside it."""
        outer = self.scope
        self.scope = outer + (next(_SUBSHELLS),)
        try:
            self._list(")", depth)
        finally:
            self.scope = outer

    def read(self) -> None:
        self._list(None, self.depth)
        if self.heredocs:
            raise _Unreadable  # a heredoc whose body never came

    def expand(self, word: _Word) -> None:
        """An unquoted heredoc's body: text, except that `$`, backticks and `\\` work in it as they
        do inside double quotes — `$( … )` in it runs."""
        scratch = _Word()
        while self.i < len(self.text):
            ch = self.text[self.i]
            if ch == "\\":
                self.i += 2
            elif ch == "`":
                self._backtick(scratch, self.depth, in_double=False)
            elif ch == "$":
                self._dollar(scratch, self.depth, in_double=True)
            else:
                self.i += 1
        word.take(scratch)

    def _peek(self, offset: int = 0) -> str:
        at = self.i + offset
        return self.text[at] if at < len(self.text) else ""

    def _list(self, closer: Optional[str], depth: int) -> None:
        """Commands up to `closer` — the `)` of a substitution or a subshell — or the end."""
        if depth > _MAX_DEPTH:
            raise _Unreadable
        text = self.text
        pipeline: list[_Command] = []
        command = _Command(scope=self.scope)

        def end_command() -> None:
            nonlocal command
            if not command.is_empty():
                pipeline.append(command)
            command = _Command(scope=self.scope)

        def end_pipeline() -> None:
            end_command()
            if len(pipeline) > 1:
                for member in pipeline:
                    member.piped = True
                for producer, member in zip(pipeline, pipeline[1:]):
                    member.producer = producer
            self.commands.extend(pipeline)
            pipeline.clear()

        while True:
            if self.i >= len(text):
                if closer:
                    raise _Unreadable  # a `$(` that never closes
                end_pipeline()
                return
            ch, nxt = text[self.i], self._peek(1)
            if ch in " \t":
                self.i += 1
            elif ch == "\\" and nxt == "\n":
                self.i += 2  # the line goes on
            elif ch == "#":
                # A comment, to the end of the line. Only at the start of a word — `a#b` is a word
                # and `$#` a parameter, and neither reaches this branch.
                end = text.find("\n", self.i)
                self.i = len(text) if end < 0 else end
            elif ch == "\n":
                end_pipeline()
                self.i += 1
                self._heredoc_bodies(depth)
            elif ch == ";":
                end_pipeline()
                self.i += 1
            elif ch == "&" and nxt == ">":
                self._redirect(command, depth)
            elif ch == "&":
                end_pipeline()
                self.i += 2 if nxt == "&" else 1
            elif ch == "|" and nxt == "|":
                end_pipeline()
                self.i += 2
            elif ch == "|":
                end_command()  # the next command reads this one's output
                self.i += 2 if nxt == "&" else 1
            elif ch == ")":
                if closer != ")":
                    raise _Unreadable
                end_pipeline()
                self.i += 1
                return
            elif ch == "(":
                if not _at_command_start(command):
                    raise _Unreadable  # `f()`, `for ((…))`: not taken apart here
                self.i += 1
                self._subshell(depth + 1)
                command.compound = True
            elif ch in "<>" and nxt == "(":
                command.words.append(self._process_substitution(depth))
            elif ch in "<>":
                self._redirect(command, depth)
            else:
                word = self._word(depth)
                if (self._peek() in ("<", ">") and self._peek(1) != "(" and not word.quoted
                        and _FD.fullmatch(word.text)):
                    self._redirect(command, depth)  # `2>`, `{fd}>`: the number is the redirect's
                else:
                    command.words.append(word)

    def _word(self, depth: int) -> _Word:
        text = self.text
        word = _Word()
        brace = 0  # 1 after an unquoted `{`, 2 once a `,` or `..` follows it: `{a,b}` expands
        bracket = False
        while self.i < len(text):
            ch = text[self.i]
            if ch in " \t\n;&|<>)":
                break
            if ch == "(":
                if word.quoted or not _ARRAY_START.fullmatch(word.text):
                    raise _Unreadable  # an extglob, a zsh glob qualifier, `f()`
                start = self.i
                self._array(word, depth + 1)
                word.text += text[start:self.i]
                continue
            word.started = True
            if ch == "\\":
                if self.i + 1 >= len(text):
                    raise _Unreadable
                if text[self.i + 1] != "\n":
                    word.text += text[self.i + 1]
                    word.quoted = True
                self.i += 2
            elif ch == "'":
                end = text.find("'", self.i + 1)
                if end < 0:
                    raise _Unreadable
                word.text += text[self.i + 1:end]
                word.quoted = True
                self.i = end + 1
            elif ch == '"':
                self._double(word, depth)
            elif ch == "`":
                self._backtick(word, depth, in_double=False)
            elif ch == "$":
                self._dollar(word, depth, in_double=False)
            else:
                if ch in "*?":
                    word.glob = True
                elif ch == "[":
                    bracket = True
                elif ch == "]" and bracket:
                    word.glob = True
                elif ch == "{":
                    brace = brace or 1
                elif brace and (ch == "," or ch == "." and self._peek(1) == "."):
                    brace = 2
                elif ch == "}" and brace == 2:
                    word.dynamic = True
                word.text += ch
                self.i += 1
        return word

    def _array(self, word: _Word, depth: int) -> None:
        """`name=( … )`: its elements are words, read for the substitutions they may hold."""
        if depth > _MAX_DEPTH:
            raise _Unreadable
        self.i += 1
        while True:
            ch = self._peek()
            if not ch or ch in ";&|<>(":
                raise _Unreadable
            if ch in " \t\n":
                self.i += 1
            elif ch == ")":
                self.i += 1
                word.dynamic = True
                return
            else:
                word.take(self._word(depth))

    def _double(self, word: _Word, depth: int) -> None:
        text = self.text
        word.started = word.quoted = True
        self.i += 1
        while True:
            if self.i >= len(text):
                raise _Unreadable
            ch = text[self.i]
            if ch == '"':
                self.i += 1
                return
            if ch == "\\":
                nxt = self._peek(1)
                if not nxt:
                    raise _Unreadable
                if nxt in '$`"\\':
                    word.text += nxt
                elif nxt != "\n":
                    word.text += "\\" + nxt
                self.i += 2
            elif ch == "`":
                self._backtick(word, depth, in_double=True)
            elif ch == "$":
                self._dollar(word, depth, in_double=True)
            else:
                word.text += ch
                self.i += 1

    def _backtick(self, word: _Word, depth: int, in_double: bool) -> None:
        """`` `…` ``, the old spelling of `$( … )`. Inside it a backslash escapes `$`, a backtick
        and itself (and `"` within double quotes); what is left is read as a script of its own."""
        text = self.text
        start, at = self.i, self.i + 1
        escapable = '$`\\"' if in_double else "$`\\"
        body: list[str] = []
        while True:
            if at >= len(text):
                raise _Unreadable
            ch = text[at]
            if ch == "\\" and at + 1 < len(text) and text[at + 1] in escapable:
                body.append(text[at + 1])
                at += 2
            elif ch == "`":
                break
            else:
                body.append(ch)
                at += 1
        self.i = at + 1
        _Reader("".join(body), self.commands, depth + 1, self.scope + (next(_SUBSHELLS),)).read()
        word.text += text[start:self.i]
        word.started = word.dynamic = word.output = True

    def _dollar(self, word: _Word, depth: int, in_double: bool) -> None:
        text = self.text
        start, nxt = self.i, self._peek(1)
        word.started = True
        if nxt == "(":
            self.i += 2
            self._subshell(depth + 1)  # `$((…))` too: an arithmetic body reads as a subshell
            word.dynamic = word.output = True
        elif nxt == "{":
            self.i += 2
            self._param(word, depth + 1, in_double)
            word.dynamic = True
        elif nxt == "'" and not in_double:
            # `$'…'`: text with C escapes, and `$'\x72\x6d'` is `rm`. The escapes are not decoded
            # here, so a word holding one is not known to be what it looks like.
            end = self.i + 2
            while True:
                if end >= len(text):
                    raise _Unreadable
                if text[end] == "\\":
                    end += 2
                elif text[end] == "'":
                    break
                else:
                    end += 1
            body = text[self.i + 2:end]
            self.i = end + 1
            word.quoted = True
            word.dynamic |= "\\" in body
            word.text += body
            return
        elif nxt == '"' and not in_double:
            self.i += 1
            self._double(word, depth)
            return
        else:
            name = _PARAM_NAME.match(text, self.i + 1)
            if name:
                word.refs.add(name.group())
                word.dynamic = True
                self.i = name.end()
            elif nxt and nxt in "@*#?$!-":
                word.dynamic = True
                self.i += 2
            else:
                self.i += 1  # a `$` with nothing after it to expand is a dollar sign
        word.text += text[start:self.i]

    def _param(self, word: _Word, depth: int, in_double: bool) -> None:
        """`${ … }` up to its own `}`; what it holds — `${x:-$(…)}` — is read like the rest."""
        if depth > _MAX_DEPTH:
            raise _Unreadable
        text = self.text
        name = _PARAM_NAME.match(text, self.i)
        if name:
            word.refs.add(name.group())
        while True:
            if self.i >= len(text):
                raise _Unreadable
            ch = text[self.i]
            if ch == "}":
                self.i += 1
                return
            if ch == "\\":
                self.i += 2
            elif ch == "'" and not in_double:
                end = text.find("'", self.i + 1)
                if end < 0:
                    raise _Unreadable
                self.i = end + 1
            elif ch in '"`$':
                inner = _Word()
                if ch == '"':
                    self._double(inner, depth)
                elif ch == "`":
                    self._backtick(inner, depth, in_double)
                else:
                    self._dollar(inner, depth, in_double)
                word.take(inner)
            else:
                self.i += 1

    def _process_substitution(self, depth: int) -> _Word:
        """`<( … )` or `>( … )`: a command whose output is a file name on the line."""
        start = self.i
        self.i += 2
        self._subshell(depth + 1)
        return _Word(text=self.text[start:self.i], started=True, dynamic=True, output=True)

    def _redirect(self, command: _Command, depth: int) -> None:
        text = self.text
        operator = next(op for op in _REDIRECT_OPERATORS if text.startswith(op, self.i))
        self.i += len(operator)
        while self._peek() in (" ", "\t"):
            self.i += 1
        ch = self._peek()
        if ch in ("<", ">") and self._peek(1) == "(":
            target = self._process_substitution(depth)
        elif not ch or ch in " \t\n;&|<>()#":
            raise _Unreadable  # a redirect with nothing to point at
        else:
            target = self._word(depth)
        if operator in ("<<", "<<-"):
            if target.dynamic:
                raise _Unreadable  # an end marker spelled with an expansion
            self.heredocs.append(
                _Heredoc(command, target.text, target.quoted, operator == "<<-", depth))
        elif operator == "<<<":
            command.stdin.append(target)
        else:
            command.redirects.append((operator, target))

    def _heredoc_bodies(self, depth: int) -> None:
        """After a newline: the bodies of the heredocs opened on the line it ended, in order.

        A quoted end marker (`<<'EOF'`) makes the body plain text — its backticks, `$( … )` and
        apostrophes are the file's, not the shell's; before the reader an apostrophe in one read as
        quoting that never closes (finding 15). An unquoted one expands, so `$( … )` in it runs.
        """
        text = self.text
        while self.heredocs:
            doc = self.heredocs.pop(0)
            if doc.depth != depth:
                raise _Unreadable  # a body that would start inside another construct
            lines: list[str] = []
            while True:
                if self.i >= len(text):
                    raise _Unreadable  # no end marker: the shell takes the rest, we do not guess
                end = text.find("\n", self.i)
                line = text[self.i:] if end < 0 else text[self.i:end]
                self.i = len(text) if end < 0 else end + 1
                if (line.lstrip("\t") if doc.strip_tabs else line) == doc.delimiter:
                    break
                lines.append(line)
            body = _Word(text="".join(line + "\n" for line in lines), started=True,
                         quoted=doc.quoted)
            if not doc.quoted:
                _Reader(body.text, self.commands, depth + 1, self.scope).expand(body)
            doc.command.stdin.append(body)


def _is_reserved(word: _Word) -> bool:
    return not word.quoted and not word.dynamic and word.text in _RESERVED


def _at_command_start(command: _Command) -> bool:
    return not (command.redirects or command.stdin or command.compound) and all(
        _is_reserved(word) for word in command.words)


def _runs(word: _Word, tainted: set[str]) -> bool:
    """Whether the word's value is another command's output — directly, or through a variable."""
    return word.output or not tainted.isdisjoint(word.refs)


def _segments(command: _Command) -> list[list[_Word]]:
    """The command's words cut where an unquoted `{` or `}` stands alone — zsh's `if … { … }` puts
    a body there — each piece without the reserved words that open it."""
    pieces: list[list[_Word]] = [[]]
    for word in command.words:
        if _is_reserved(word) and word.text in ("{", "}"):
            pieces.append([])
        else:
            pieces[-1].append(word)
    result = []
    for piece in pieces:
        start = 0
        while start < len(piece) and _is_reserved(piece[start]):
            start += 1
        if piece[start:]:
            result.append(piece[start:])
    return result


def _tainted(commands: list[_Command], inherited: Iterable[str] = ()) -> set[str]:
    """Variables holding another command's output somewhere on this line: `f=$( … )`, a loop over
    one, `read`. Order is not followed — a name set from a substitution ANYWHERE on the line counts
    — which can only make the answer more careful.

    And `HOME`, set on the line to anything: `_home_head_name` reads `$HOME` as the home, and a home
    the line sets is not one — `HOME='/bin/rm -rf / '; $HOME/x` splits into a delete (tcc#128). A
    `HOME=` word anywhere in a command counts, so `env HOME=… bash -c …` does too: at worst it costs
    a question about a `$HOME` head on the same line. So does `${HOME:=…}`, and `${f:=$(…)}` taints
    `f` as `f=$(…)` does (re-review of tcc#128)."""
    tainted: set[str] = set(inherited)
    while True:
        before = len(tainted)
        for command in commands:
            for word in [*command.words, *command.stdin, *(target for _, target in command.redirects)]:
                tainted.update(name for name in _DEFAULT_ASSIGNMENT.findall(word.text)
                               if name == "HOME" or _runs(word, tainted))
            for words in _segments(command):
                head = words[0].text
                if any(_HOME_ASSIGNMENT.match(word.text) for word in words):
                    tainted.add("HOME")
                if head in ("for", "select") and len(words) > 1:
                    if words[1].text == "HOME" or any(
                            _runs(word, tainted) or not word.dynamic and (
                                _is_wide_target(word.text) or any(ch in word.text for ch in "*?[")
                                and _outside_roots(word.text, ""))
                            for word in words[3:]):
                        # A loop over another command's output, or over a home or a system folder
                        # (`for f in ~/*`): what its body deletes is that (Fable's review, I1).
                        tainted.add(words[1].text)
                elif head in _STDIN_READERS:
                    tainted.update(word.text for word in words[1:] if _NAME.fullmatch(word.text))
                elif head == "printf":
                    tainted.update(value.text for flag, value in zip(words, words[1:])
                                   if flag.text == "-v")
                else:
                    for word in words[1:] if head in _DECLARERS else words:
                        assignment = _ASSIGNMENT.match(word.text)
                        if assignment and (_runs(word, tainted) or assignment.group(1) == "HOME"):
                            tainted.add(assignment.group(1))
                        elif not assignment and head not in _DECLARERS:
                            break
        if len(tainted) == before:
            return tainted


def _command_is_dangerous(command: _Command, tainted: set[str], depth: int) -> bool:
    for operator, target in command.redirects:
        if operator not in _WRITE_REDIRECTS:
            continue
        if operator == ">&" and (target.text == "-" or _FD.fullmatch(target.text)):
            continue  # `2>&1`: a stream moved, not a file written
        if target.text in _STREAM_DEVICES and not target.dynamic:
            continue
        # Somebody else's system file, or a name another command printed. `> /etc/hosts` is not a
        # chain and not a recursive delete, so nothing else catches it, and it is the quiet kind.
        if _runs(target, tainted) or target.text.startswith(_PROTECTED_ROOTS):
            return True
    return any(_words_are_dangerous(words, command, tainted, depth)
               for words in _segments(command))


def _command_name(text: str) -> str:
    """What runs, as the rules name it: the last part of its path (`/` or `\\`), `.exe` or `.com`
    dropped (`format.com`), in lower case — macOS and Windows disks ignore case, so `RM -rf ~` runs
    `/bin/rm` there (tcc#128)."""
    parts = [part for part in re.split(r"[\\/]", text) if part]
    name = parts[-1].lower() if parts else ""
    return name[:-4] if name.endswith((".exe", ".com")) else name


def _home_head_name(head: _Word) -> Optional[str]:
    """The name a head runs when its only expansion is `$HOME`: `"$HOME/.local/bin/omp" --version`
    reads as `omp`, as `~/.local/bin/omp` always did. The home is not what the command is, and a
    question about a version check is finding 123's class (tcc#128). None for anything else."""
    if head.refs != {"HOME"} or head.output or head.glob:
        return None
    match = _HOME_HEAD.fullmatch(head.text)
    return _command_name(match.group(1)) if match else None


def _words_are_dangerous(words: list[_Word], command: _Command, tainted: set[str], depth: int,
                         unwrap: bool = True) -> bool:
    start = 0
    while start < len(words) and (_is_reserved(words[start])
                                  or _ASSIGNMENT.match(words[start].text)):
        start += 1
    words = words[start:]
    if not words:
        return False
    head, arguments = words[0], words[1:]
    if _runs(head, tainted):
        return True  # what runs is another command's output: `$(echo rm)`
    name = _home_head_name(head)
    if name is None:
        if head.dynamic or head.glob:
            return True  # what runs is not written on the line: `$x`, `/bin/r?`
        name = _command_name(head.text)
    texts = [argument.text for argument in arguments]
    if name in ("for", "select"):
        return False  # its list was read word by word, and its body is commands of their own
    if name in _LINK_FOLLOWERS and _reaches_out_through_a_link(arguments, command.cwd):
        return True  # `rm -rf h/` where `h` is `ln -s ~ h`: the home, not a folder of the project
    if name == "ln":
        return _ln_is_dangerous(arguments, command.cwd)
    if name == "mklink":
        return _mklink_is_dangerous(arguments, command.cwd)
    if name in ("new-item", "ni"):
        return _new_item_is_dangerous(arguments, command.cwd)
    if name in _UNREAD_KEYWORDS or name in ("sudo", "eval"):
        return True  # sudo: asking for the whole machine is the definition of worth a question
    if name in _RUINOUS or name.startswith(_RUINOUS_PREFIXES) or name in _DISK_TOOLS:
        return True
    if any(_RAW_DEVICE.search(word.text) for word in words):
        return True  # `dd of=\\.\PhysicalDrive1`, `Set-Content \\.\PhysicalDrive1`
    if name == "cipher":
        # `cipher /w:C:\` overwrites the free space of a whole volume; `/c`, `/e` only look or encrypt.
        return any(text.lower() == "/w" or text.lower().startswith("/w:") for text in texts)
    if name in _STARTERS and _start_is_dangerous(arguments, command, depth):
        return True  # `Start-Process diskpart -Verb RunAs`, `Start-Process cmd '/c format D:'`
    if name in ("source", "."):
        # It runs a file the line names — unless the line does not name it: `. <(curl …)`, or
        # names stdin, where what runs is the heredoc or the pipe.
        if arguments and _is_stdin_path(arguments[0].text):
            return _stdin_script_is_dangerous(command, tainted, depth)
        return any(argument.dynamic or _runs(argument, tainted) for argument in arguments)
    if name in ("trap", "alias"):
        return _code_arguments_are_dangerous(name, arguments, tainted, depth, command.cwd)
    if name == "xargs":
        tail = _xargs_command(arguments)
        return tail is None or bool(tail) and _words_are_dangerous(tail, command, tainted, depth,
                                                                   unwrap)
    if name in _WRAPPERS:
        # Each tail once, and a wrapper met in a tail is not unwrapped again: the outer loop already
        # covers the tails after it, and `env env env … rm` must not cost 2ⁿ.
        return unwrap and any(_words_are_dangerous(words[at:], command, tainted, depth, unwrap=False)
                              for at in range(1, len(words)))
    if name in _SHELLS:
        return _shell_is_dangerous(arguments, command, tainted, depth)
    if name == "wsl":
        return _wsl_is_dangerous(arguments, command, tainted, depth)
    if name == "cmd":
        return _cmd_is_dangerous(arguments, command, tainted, depth)
    if name in ("powershell", "pwsh"):
        return _powershell_is_dangerous(arguments, command, tainted, depth)
    if name in ("remove-item", "ri"):
        return _remove_item_is_dangerous(arguments, command.piped, command.cwd)
    if name in _INTERPRETERS or name.startswith("python"):
        return _interpreter_is_dangerous(name, arguments, command, tainted)
    if name in ("rm", "find", "dd", "chmod", *_OVERWRITERS) and any(
            _runs(a, tainted) for a in arguments):
        return True  # its arguments decide, and one is another command's output: `rm $(echo -rf /)`
    if name == "rm":
        return _rm_is_dangerous(arguments, command.cwd)
    if name in _OVERWRITERS:
        return any(_reaches_wide(operand, command.cwd) for operand in _operand_words(arguments))
    if name in _PS_OVERWRITERS:
        return any(_reaches_wide(operand, command.cwd) for operand in _ps_operands(arguments))
    if name in _WINDOWS_DELETES:
        # cmd's `rd /s`, and PowerShell's aliases of Remove-Item: `rd -Recurse ~` (Ruling 41).
        return _reach_is_dangerous(arguments, _is_windows_switch,
                                   lambda text: "s" in _switch_letters(text), bare=False,
                                   cwd=command.cwd, wide_alone=True, outside=True
                                   ) or _remove_item_is_dangerous(
                                       [a for a in arguments if not _is_windows_switch(a.text)],
                                       command.piped, command.cwd)
    if name in ("icacls", "cacls", "takeown"):
        # chmod -R's twin: `/T` (icacls) or `/R` (takeown) over a home or a system folder.
        return _reach_is_dangerous(arguments, lambda text: bool(re.fullmatch(r"/[A-Za-z]+", text)),
                                   lambda text: text.lower() in ("/t", "/r"), bare=False,
                                   cwd=command.cwd)
    if name == "reg":
        return _reg_is_dangerous(arguments, command.cwd)
    if name == "rsync":
        return _rsync_is_dangerous(arguments, command.cwd)
    if name == "systemctl":
        return any(a.text.lower() in _SYSTEMCTL_DOWN for a in arguments)
    if name == "crontab":
        return any(a.text.startswith("-") and "r" in a.text[1:] for a in arguments)
    if name == "kill":
        return _kill_is_dangerous(arguments)
    if name in ("pkill", "killall"):
        return _pkill_is_dangerous(name, arguments)
    if name == "taskkill":
        return _taskkill_is_dangerous(arguments)
    if name == "find":
        return _find_is_dangerous(arguments, command, tainted, depth)
    if name == "dd":
        return any(text.startswith("of=/dev/") for text in texts)
    if name == "chmod" and _lists_names_below_a_narrow_folder(command.producer):
        # Ruling 35: what `xargs` appends to a chmod is read as one file, not as a chance at `-R /`
        # — a mode on named files is undone by another chmod (finding 123). `-R` on the line asks.
        # Ruling 37: only when the names come from a listing whose reach is not a whole home.
        arguments = [replace(a, quoted=True) if a.dynamic and a.text == "…" else a for a in arguments]
    if name == "chmod":
        return _reach_is_dangerous(arguments, lambda text: text.startswith("-"), _is_recursive_flag,
                                   bare=False, cwd=command.cwd, mode_first=True)
    if name == "git":
        return _git_is_dangerous(arguments, tainted)
    if name in _FETCHERS and command.piped:
        return True
    return False


#: Start-Process's switches (no value); every other parameter takes the word after it.
_START_SWITCHES = ("wait", "passthru", "nonewwindow", "usenewenvironment", "loaduserprofile",
                   "whatif", "confirm", "verbose", "debug")
#: The programs whose argument string is a shell line of their own.
_SHELL_PROGRAMS = frozenset({"cmd", "powershell", "pwsh", "wsl", "bash"})
#: wsl's options that take the word after them.
_WSL_VALUED = frozenset({"-d", "--distribution", "-u", "--user", "--cd", "--shell-type"})
#: wsl's own commands that cannot be taken back for a distro's state: `--unregister` deletes its
#: disk with everything in it; `--shutdown`/`--terminate` kill what runs there unsaved; an import
#: or a conversion rewrites one; `--manage` moves or resizes its disk.
_WSL_RUINOUS = frozenset({"--unregister", "--shutdown", "--terminate", "-t", "--import",
                          "--import-in-place", "--set-version", "--manage"})
#: wsl's own commands that only look or set things up: no Linux command line follows them.
_WSL_OWN = frozenset({"-l", "--list", "--status", "--version", "-v", "--help", "--install",
                      "--update", "--export", "--set-default", "-s", "--set-default-version",
                      "--mount", "--unmount", "--debug-shell"})


def _wsl_is_dangerous(arguments: list[_Word], command: _Command, tainted: set[str],
                      depth: int) -> bool:
    """`wsl …` runs a Linux command line the gate reads as bash (the narrow re-review, 2): the
    words after `-e`/`--exec` as one command, after `--` or after wsl's own options (`-d <distro>`,
    `-u <user>`, `--cd <dir>`) as a line its shell runs. wsl alone is an interactive shell; its
    listing and status commands pass; `--unregister`, `--shutdown` and the like ask."""
    at = 0
    while at < len(arguments):
        word = arguments[at]
        if word.dynamic or _runs(word, tainted):
            return True  # an option or a command the line does not spell
        text = word.text.lower()
        if text in ("-e", "--exec"):
            rest = arguments[at + 1:]
            return bool(rest) and _words_are_dangerous(rest, command, tainted, depth)
        if text == "--" or not text.startswith("-"):
            rest = arguments[at + 1:] if text == "--" else arguments[at:]
            if any(w.dynamic or _runs(w, tainted) for w in rest):
                return True
            return bool(rest) and _script_is_dangerous(" ".join(w.text for w in rest), depth + 1,
                                                       tainted, command.cwd)
        if text in _WSL_RUINOUS:
            return True
        if text in _WSL_OWN:
            return False
        at += 2 if text in _WSL_VALUED else 1
    return False


def _start_is_dangerous(arguments: list[_Word], command: _Command, depth: int) -> bool:
    """`Start-Process`/`saps`/`start`: a disk tool started (`Start-Process diskpart`), or cmd or
    PowerShell started with a line — by `-FilePath` or positionally, the line by `-ArgumentList`
    (`-Args`, any prefix; a PowerShell array `'/c','format D:'`) or positionally — read as that
    shell's own line, unwrapped as a direct `cmd /c …` / `powershell -Command …` is
    (`-EncodedCommand` asks there). The re-review of the group fix, C."""
    program: Optional[str] = None
    lines: list[list[str]] = []
    positional: list[str] = []
    at = 0
    while at < len(arguments):
        word = arguments[at]
        at += 1
        text = word.text
        if not _is_parameter(word):
            positional.append(text)
            continue
        key, inline, value = text[1:].partition(":")
        key = key.lower()
        if not inline and key and any(s.startswith(key) for s in _START_SWITCHES) and not (
                "argumentlist".startswith(key) or "filepath".startswith(key)):
            continue
        values = [value] if inline else []
        if not inline and at < len(arguments):
            values.append(arguments[at].text)
            at += 1
            while values[-1].endswith(",") and at < len(arguments):  # `'a', 'b'`: one array
                values.append(arguments[at].text)
                at += 1
        if key and ("argumentlist".startswith(key) or key == "args"):
            lines.append(values)
        elif key and ("filepath".startswith(key) or key in ("path", "pspath")):
            program = " ".join(values)
    if any(_command_name(text) in _DISK_TOOLS | _RUINOUS for text in [program or "", *positional]):
        return True
    if program is None:
        shells = [i for i, text in enumerate(positional) if _command_name(text) in _SHELL_PROGRAMS]
        if not shells:
            return False
        program, rest = positional[shells[0]], positional[shells[0] + 1:]
    else:
        rest = positional
    if _command_name(program) not in _SHELL_PROGRAMS:
        return False
    for given in [*lines, rest] if rest else lines:
        joined = " ".join(given)
        # An element boundary and a comma in one quoted string read alike here: both readings.
        for line in {joined.replace(",", " "), joined}:
            if _powershell_line_is_dangerous(f"{_command_name(program)} {line}", depth + 1,
                                             command.cwd):
                return True
    return False


def _is_parameter(word: _Word) -> bool:
    """A PowerShell parameter (or a bash option): `-x` unquoted, or `-name:value` with the value
    quoted — `'-Recurse'` whole in quotes is a string, as PowerShell reads it."""
    text = word.text
    return text.startswith("-") and len(text) > 1 and (
        not word.quoted or bool(_COLON_PARAM.match(text)))


def _reg_is_dangerous(arguments: list[_Word], cwd: Optional[str]) -> bool:
    """`reg delete <key>` of a hive or a key that is somebody's whole configuration; `reg restore`
    writes over a key from a file."""
    words = [a for a in arguments if not re.fullmatch(r"/[A-Za-z]+", a.text)]
    if not words:
        return False
    verb = words[0].text.lower()
    if verb == "restore":
        return True
    return verb == "delete" and any(w.dynamic or _is_wide_target(w.text) for w in words[1:2])


def _rsync_is_dangerous(arguments: list[_Word], cwd: Optional[str]) -> bool:
    """`rsync --delete` (any of its spellings) makes the destination match the source: an empty
    source deletes it. Asks when that destination — the last operand — is wide or unknown."""
    options = [a.text for a in arguments if a.text.startswith("-")]
    if not any(o.startswith("--del") or o == "--remove-source-files" for o in options):
        return False
    operands = [a for a in arguments if not a.text.startswith("-")]
    if not operands:
        return True
    dest = operands[-1]
    return dest.dynamic or _is_wide_here(dest.text, cwd) or _outside_roots(dest.text, cwd)


#: `kill`'s options that take the word after them.
_KILL_VALUED = frozenset({"-s", "-n", "--signal"})


def _kill_is_dangerous(arguments: list[_Word]) -> bool:
    """`kill -9 -1` (and `kill -- -1`): pid -1 is every process the user may signal — TCC and
    REW with them, captures unsaved. The last word is a pid even when it looks like an option."""
    words = [a.text for a in arguments]
    if "--" in words:
        return "-1" in words[words.index("--") + 1:]
    at = 0
    while at < len(words) - 1 and words[at].startswith("-"):
        at += 2 if words[at] in _KILL_VALUED else 1
    return "-1" in words[at:]


#: pkill's and killall's options that take the word after them.
_PKILL_VALUED = frozenset({"-u", "-U", "-g", "-G", "-P", "-s", "-t", "-F", "--signal", "-o",
                           "-y", "--user", "-n"})
_MATCHES_ALL = frozenset({".", ".*", "^", "", "*", ".+", "^.*$"})


def _pkill_is_dangerous(name: str, arguments: list[_Word]) -> bool:
    """`pkill .`, `killall -r .`, `pkill -u me` with no name: every process of the user."""
    patterns: list[str] = []
    by_user = False
    at = 0
    while at < len(arguments):
        text = arguments[at].text
        if text.startswith("-") and len(text) > 1:
            by_user |= text in ("-u", "-U", "--user")
            if text in _PKILL_VALUED:
                at += 1
        else:
            patterns.append(text)
        at += 1
    return any(p in _MATCHES_ALL for p in patterns) or by_user and not patterns


def _taskkill_is_dangerous(arguments: list[_Word]) -> bool:
    """`taskkill /F /IM *`: every process by name."""
    texts = [a.text for a in arguments]
    return any(t.lower() == "/im" and at + 1 < len(texts)
               and texts[at + 1].strip("\"'") in ("*", "*.*", "*.exe")
               for at, t in enumerate(texts))


def _lists_names_below_a_narrow_folder(producer: Optional[_Command]) -> bool:
    """Whether a pipe's producer prints file names, and only below a folder that is not somebody's
    whole home or system: `ls`, `find`, `git ls-files`, every word spelled (Ruling 37). `echo` and
    `printf` print what they are told — `echo '-R /' | xargs chmod 755` is `chmod 755 -R /` to GNU
    chmod — and `find ~` reaches what `chmod -R 644 ~` does."""
    while producer is not None and _keeps_names(producer):
        producer = producer.producer  # `ls | grep sh | xargs …`: grep passes ls's names on
    if producer is None or producer.compound or producer.redirects or producer.stdin:
        return False
    segments = _segments(producer)
    if len(segments) != 1:
        return False
    words = segments[0]
    while words and _ASSIGNMENT.match(words[0].text):
        words = words[1:]
    if not words or any(word.dynamic or word.output for word in words):
        return False
    name, texts = _command_name(words[0].text), [word.text for word in words[1:]]
    if name == "git":
        return texts[:1] == ["ls-files"]
    if name == "ls":
        roots = [text for text in texts if not text.startswith("-")]
    elif name == "find":
        roots = _find_roots(texts)
        if roots is None:
            return False
    else:
        return False
    return not any(_is_wide_here(root, producer.cwd) for root in roots or ["."])


def _keeps_names(command: _Command) -> bool:
    """Whether a pipe member only passes on some of the lines it reads, unchanged: `grep` (not
    `-o`, `-r`, `-c`, `-n`, … — only the options in `_NAME_FILTERS`), `head`, `tail`, `sort`,
    `uniq`, reading the pipe and no file. Never `sed`, `awk`, `tr`, `cut`: they can turn a name
    into `-R /` (Ruling 41)."""
    if command.compound or command.redirects or command.stdin:
        return False
    segments = _segments(command)
    if len(segments) != 1:
        return False
    words = segments[0]
    while words and _ASSIGNMENT.match(words[0].text):
        words = words[1:]
    if not words or any(word.dynamic or word.output for word in words):
        return False
    rule = _NAME_FILTERS.get(_command_name(words[0].text))
    if rule is None:
        return False
    flags, valued, longs, takes_pattern = rule
    operands: list[str] = []
    texts = [word.text for word in words[1:]]
    at = 0
    while at < len(texts):
        text = texts[at]
        at += 1
        if text == "--":
            operands.extend(texts[at:])
            break
        if text.startswith("--"):
            option, has_value, _ = text.partition("=")
            if option not in longs:
                return False
            if longs[option]:
                at += 0 if has_value else 1
                takes_pattern &= option not in ("--regexp", "--file")
            continue
        if not text.startswith("-") or len(text) < 2:
            operands.append(text)
            continue
        if text[1:].isdigit() or text.startswith("-n+"):
            continue  # `head -5`
        for index, letter in enumerate(text[1:], start=1):
            if letter in flags:
                continue
            if letter not in valued:
                return False  # an option that may rewrite what it prints
            at += 0 if text[index + 1:] else 1
            takes_pattern &= letter not in "ef"
            break
    return len(operands) <= (1 if takes_pattern else 0)  # a file operand reads the file, not the pipe


def _find_roots(texts: list[str]) -> Optional[list[str]]:
    """The folders `find` walks; None when an option before them is not one the gate knows.

    The options come before the paths, and some hide one: macOS's `-f path` is a path, GNU's
    `-D x` takes a value, `-O2` and `--` stand alone, and macOS's `-E -d -s -x` can be glued
    (`-sx`). Skipping only `-H -L -P` let `find -s ~ -type f` read as having no root (re-review of
    tcc#128). A predicate first (`-name x`) means the default root, the current folder."""
    roots: list[str] = []
    at = 0
    while at < len(texts):
        text = texts[at]
        if text == "--":
            at += 1
            break
        if not text.startswith("-") or text in _FIND_PREDICATES:
            break
        at += 1
        for index, letter in enumerate(text[1:], start=1):
            rest = text[index + 1:]
            if letter in _FIND_FLAG_LETTERS:
                continue
            if letter == "O" and (not rest or rest.isdigit()):
                break  # `-O2`: the level is glued to it
            if letter not in "fD":
                return None  # an option the gate does not know may hide a path
            if not rest and at >= len(texts):
                return None
            value = rest or texts[at]
            at += 0 if rest else 1
            if letter == "f":
                roots.append(value)  # macOS: `-f path` is a path
            break
    while at < len(texts) and not texts[at].startswith("-") and texts[at] not in ("(", "!"):
        roots.append(texts[at])
        at += 1
    return roots


def _xargs_command(arguments: list[_Word]) -> Optional[list[_Word]]:
    """The command `xargs` runs, as the rules should see it; None when its options are not readable.

    xargs only APPENDS what it reads — one word the line does not spell, at the end — so `xargs rm
    -rf build` deletes more than `build` and `xargs git log -1 --` is still a `log`. With a
    placeholder (`-I X`, `-i`, `-J`, `--replace`) it appends nothing and fills exactly the words that
    hold the placeholder, the command's own name included: `xargs -I{} {} --version` runs whatever
    came in. (Re-review of tcc#115: marking every word of the tail read `-c` and `log` as unknown.)
    """
    placeholder: Optional[str] = None
    at = 0
    while at < len(arguments):
        word = arguments[at]
        if word.dynamic:
            return None  # an option the line does not spell
        text = word.text
        if text == "--":
            at += 1
            break
        if text.startswith("--"):
            option, has_value, value = text.partition("=")
            if option == "--replace":
                placeholder = value if has_value else "{}"
            elif option in _XARGS_LONG_VALUES and not has_value:
                at += 1
            at += 1
            continue
        if len(text) < 2 or not text.startswith("-"):
            break
        at += 1
        for index, letter in enumerate(text[1:], start=1):
            attached = text[index + 1:]
            if letter in _XARGS_VALUE_FLAGS:
                if attached:
                    value = attached
                elif at < len(arguments) and not arguments[at].dynamic:
                    value = arguments[at].text
                    at += 1
                else:
                    return None
                if letter in "IJ":
                    placeholder = value
                break
            if letter in _XARGS_ATTACHED_FLAGS:
                if letter == "i":
                    placeholder = attached or "{}"
                break
    tail = arguments[at:]
    if not tail:
        return []  # it runs `echo`
    if placeholder is not None:
        # The placeholder takes a whole input line as ONE argument — never split, so as one quoted
        # word: `xargs -I{} chmod 644 {}` is a chmod of one file, not a chance at `-R /` (tcc#128).
        return [replace(word, dynamic=True, quoted=True) if placeholder in word.text else word
                for word in tail]
    return [*tail, _Word(text="…", started=True, dynamic=True)]


#: What acts on the place a link points to rather than on the link: a delete or a move of `h/`
#: where `h` is `ln -s ~ h` reaches the home (macOS's `rm -rf link/` follows it; Windows
#: PowerShell's `Remove-Item -Recurse` follows a junction). The third fix round of tcc#181.
_LINK_FOLLOWERS = frozenset({"rm", "unlink", "mv", "remove-item", "ri", "del", "erase", "rd",
                             "rmdir", "move-item", "mi", "move"})
#: Whether a statement ran before this one in the same line (`_after`): what it made — a link by
#: `python3 -c`, `perl`, an archive — is not on the disk the check reads.
_AFTER_ANOTHER: ContextVar[bool] = ContextVar("shell_gate_after_another", default=False)


#: Statements that only change the folder: they make nothing a later one could trip over.
_FOLDER_CHANGES = frozenset({"cd", "pushd", "popd", "chdir", "set-location", "sl", "push-location",
                             "pop-location"})
#: …and the others that cannot make a link: they set, look up or say, and run nothing.
_MAKES_NOTHING = _FOLDER_CHANGES | {"export", "local", "declare", "typeset", "readonly", "unset",
                                    "set", "true", "false", ":", "echo", "printf", "type", "which",
                                    "test", "["}


def _ran(words: list[_Word]) -> None:
    """A statement of the line was read: every one after it is «after another» (`_AFTER_ANOTHER`),
    unless it makes nothing (`_MAKES_NOTHING`, behind its assignments and a `builtin`/`command`;
    `command -v` only looks). A nested script inherits its line's mark."""
    at = 0
    while at < len(words) and _ASSIGNMENT.match(words[at].text):
        at += 1
    while at < len(words) and _command_name(words[at].text) in ("builtin", "command"):
        if at + 1 < len(words) and words[at + 1].text in ("-v", "-V"):
            return
        at += 1
    if at < len(words) and _command_name(words[at].text) not in _MAKES_NOTHING:
        _AFTER_ANOTHER.set(True)


#: What `New-Item -ItemType` makes that is a link.
_LINK_KINDS = frozenset({"symboliclink", "junction", "hardlink"})
#: How far a recursive PowerShell delete is looked into for a junction; past it, it asks.
_WALK_LIMIT = 5000


def _operand_words(arguments: list[_Word]) -> list[_Word]:
    """The words a command acts on: not its options, `-Path:x`'s value, every word after `--`."""
    operands: list[_Word] = []
    ended = False
    for word in arguments:
        text = word.text
        if not ended and text == "--":
            ended = True
        elif not ended and _is_parameter(word):
            _, colon, value = text.partition(":")
            if colon and value:
                operands.append(_Word(text=value, started=True, dynamic="$" in value))
        else:
            operands.append(word)
    return operands


def _base(cwd: Optional[str]) -> Optional[str]:
    """The folder a command runs in, absolute; None when the line does not spell it."""
    project = _PROJECT.get()
    if project is None or cwd is None:
        return None
    if cwd.startswith("~"):
        return os.path.expanduser(cwd)
    return cwd if _is_absolute(cwd) else os.path.join(str(project), cwd)


def _resolve(text: str, base: str) -> Optional[str]:
    """Where a path lands as written, absolute and normalised (links not followed yet); None for a
    Windows place (`C:/…`, `//server/…`) on a machine that has none — outside the project there."""
    text = text.replace("\\", "/")
    if re.match(r"[A-Za-z]:", text) or text.startswith("//"):
        if os.name != "nt":
            return None
        path = text
    elif text.startswith("~"):
        path = os.path.expanduser(text)
    elif text.startswith("/"):
        path = text
    else:
        path = os.path.join(base, text)
    return os.path.normpath(path)


def _within(path: str, root: str) -> bool:
    path, root = os.path.normcase(path), os.path.normcase(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _in_the_project(path: str) -> bool:
    """Whether a path, as written, is inside the project — given or resolved (`/var` is
    `/private/var` on macOS)."""
    project = _PROJECT.get()
    return project is not None and (_within(path, os.path.normpath(str(project)))
                                    or _within(path, os.path.realpath(project)))


def _lands_outside(path: str) -> bool:
    """Whether a path, every link on it followed, lands outside the project."""
    project = _PROJECT.get()
    return project is not None and not _within(os.path.realpath(path), os.path.realpath(project))


def _outside_roots(text: str, cwd: Optional[str]) -> bool:
    """The Arbiter, 2026-10-14 («Питати поза проєктом»): whether a recursive or glob delete's or
    overwrite's operand lies outside the project and the method's copy — the rule under `auto` is
    inside vs outside, with no list of important folders. A glob is judged by the folder it stands
    in (`/Users/me/Documents/*`); a place the line does not spell (an unknown `cd`) is outside, and
    so is a Windows drive on a machine that has none. With no roots given, only the text is
    judged, as before."""
    roots = _ROOTS.get()
    project = _PROJECT.get()
    if not roots or project is None:
        return False
    base = _base(cwd)
    if base is None and not _is_absolute(text):
        return True
    path = _resolve(text, base or str(project))
    if path is None:
        return True
    fixed = re.split(r"[*?\[]", path, maxsplit=1)[0]
    if fixed != path:
        fixed = fixed if fixed.endswith(("/", os.sep)) else os.path.dirname(fixed)
    fixed = os.path.normpath(fixed or os.sep)
    for root in roots:
        for spelled in {os.path.normpath(str(root)), os.path.realpath(root)}:
            if _within(fixed, spelled) or _within(os.path.realpath(fixed), spelled):
                return False
    return True


def _matches(path: str) -> list[str]:
    """A path, or for a glob what it matches and the folder it is in."""
    if not re.search(r"[*?\[]", path):
        return [path]
    fixed = os.path.dirname(re.split(r"[*?\[]", path, maxsplit=1)[0]) or path
    return [fixed, *glob.glob(path, include_hidden=True)]


def _reaches_out_through_a_link(arguments: list[_Word], cwd: Optional[str]) -> bool:
    """A delete's or a move's operand written inside the project that a link takes outside it.
    What is written outside is left to the narrow rules: `rm /tmp/x.txt` is not this case."""
    base = _base(cwd)
    if base is None:
        return False
    for word in _operand_words(arguments):
        if word.dynamic:
            continue  # what the line does not spell: the narrow rules have their own answer
        path = _resolve(word.text, base)
        if path is None or not _in_the_project(path):
            continue
        matches = _matches(path)
        if any(_lands_outside(match) for match in matches):
            return True
        if _AFTER_ANOTHER.get() and not any(os.path.lexists(match) for match in matches):
            # Not there when the line is read, and something ran before it in the same line:
            # `python3 -c '…os.symlink(home, "h")' && rm -rf h/`. The disk cannot answer for it.
            return True
    return False


def _holds_a_link_out(target: _Word, cwd: Optional[str]) -> bool:
    """A folder inside the project holding a link or junction to outside it, looked for as deep as
    `_WALK_LIMIT` entries; past that, unknown — and so it asks."""
    base = _base(cwd)
    if base is None or target.dynamic:
        return False
    path = _resolve(target.text, base)
    if path is None or not _in_the_project(path):
        return False
    seen = 0
    for match in _matches(path):
        if not os.path.isdir(match) or os.path.islink(match):
            continue
        for folder, folders, files in os.walk(match, followlinks=False):
            for name in folders + files:
                seen += 1
                if seen > _WALK_LIMIT:
                    return True
                entry = os.path.join(folder, name)
                if _lands_outside(entry):  # a link or a junction, whichever this Python can tell
                    return True
    return False


def _link_target_is_outside(target: str, link: Optional[str], symbolic: bool,
                            cwd: Optional[str]) -> bool:
    """Whether a link made to `target` points outside the project. A symbolic link's relative
    target is read from the link's folder (`ln -s .. state/up` is the project), a hard link's or a
    junction's from where the command runs. Without a project, any target that is absolute, the
    home or a climb is outside."""
    text = target.replace("\\", "/")
    base = _base(cwd)
    if base is None:
        return _is_absolute(text) or ".." in text.split("/")
    if symbolic and link is not None:
        link_path = _resolve(link, base)
        if link_path is None:
            return True
        base = link_path if os.path.isdir(link_path) else os.path.dirname(link_path)
    path = _resolve(text, base)
    return path is None or _lands_outside(path)


def _ln_is_dangerous(arguments: list[_Word], cwd: Optional[str]) -> bool:
    """`ln` making a link to outside the project: once it stands, a delete of the link with a slash
    — or anything that writes through it — reaches there (third fix round of tcc#181)."""
    options = [word.text for word in arguments
               if word.text.startswith("-") and len(word.text) > 1 and not word.quoted]
    if "--" in [word.text for word in arguments]:
        options = options[:[w.text for w in arguments].index("--")]
    operands = _operand_words(arguments)
    if not operands:
        return False
    if any(word.dynamic for word in operands):
        return True
    shorts = "".join(option[1:] for option in options if not option.startswith("--"))
    if "t" in shorts or any(option.startswith("--target") for option in options):
        return True  # the link's folder given as an option: not read here
    symbolic = "s" in shorts or "--symbolic" in options
    targets = operands[:-1] if len(operands) > 1 else operands
    link = operands[-1].text if len(operands) > 1 else None
    return any(_link_target_is_outside(word.text, link, symbolic, cwd) for word in targets)


def _mklink_is_dangerous(arguments: list[_Word], cwd: Optional[str]) -> bool:
    """cmd's `mklink [/D|/H|/J] link target`, judged as `ln` is."""
    switches = {word.text.lower() for word in arguments if word.text.lower() in ("/d", "/h", "/j")}
    operands = [word for word in arguments if word.text.lower() not in ("/d", "/h", "/j")]
    if len(operands) != 2 or any(word.dynamic for word in operands):
        return True
    symbolic = not switches & {"/h", "/j"}
    return _link_target_is_outside(operands[1].text, operands[0].text, symbolic, cwd)


def _is_param(name: str, full: str, shortest: int) -> bool:
    return len(name) >= shortest and full.startswith(name)


def _new_item_is_dangerous(arguments: list[_Word], cwd: Optional[str]) -> bool:
    """`New-Item -ItemType SymbolicLink|Junction|HardLink … -Value <target>`: a link, and its
    `-Value` (or `-Target`) is where it points — dangerous when that is outside the project, or
    when the line does not spell the kind or the target."""
    kind: Optional[_Word] = None
    target: Optional[_Word] = None
    at = 0
    while at < len(arguments):
        word = arguments[at]
        text = word.text
        if _is_parameter(word):
            name, colon, value = text[1:].partition(":")
            name = name.lower()
            takes = any(_is_param(name, full, 2) for full in ("itemtype", "type", "value",
                                                             "target", "path", "name"))
            given: Optional[_Word] = None
            if colon:
                given = _Word(text=value, started=True, dynamic="$" in value)
            elif takes and at + 1 < len(arguments):
                at += 1
                given = arguments[at]
            if _is_param(name, "itemtype", 2) or _is_param(name, "type", 2):
                kind = given
            elif _is_param(name, "value", 2) or _is_param(name, "target", 3):
                target = given
        elif text.lower() in _LINK_KINDS:
            kind = word
        at += 1
    if kind is None:
        return False
    if kind.dynamic:
        return True
    if kind.text.lower() not in _LINK_KINDS:
        return False
    if target is None or target.dynamic:
        return True
    return _link_target_is_outside(target.text, None, symbolic=False, cwd=cwd)


def _rm_is_dangerous(arguments: list[_Word], cwd: Optional[str] = "") -> bool:
    """`rm` is judged by its arguments rather than by its name: `rm build/tmp.json` is a Tuesday.
    With no target it is fed by `xargs` or a pipe, and deletes what is not on the line."""
    return _reach_is_dangerous(arguments, lambda text: text.startswith("-"), _is_recursive_flag,
                               bare=True, cwd=cwd, wide_alone=True, outside=True)


def _reach_is_dangerous(arguments: list[_Word], is_option: Callable[[str], bool],
                        is_recursive: Callable[[str], bool], bare: bool, cwd: Optional[str] = "",
                        mode_first: bool = False, wide_alone: bool = False,
                        outside: bool = False) -> bool:
    """A recursive delete (`rm -r`, `rd /s`) or `chmod -R`, judged by what it reaches.

    A target the line does not spell — `"$f"` in `for f in *`, `$(cat list)` — is unknown, and a
    recursive delete of something unknown is the case this check exists for; so is one of a whole
    home or system folder (`_is_wide_target`).

    And an OPTION the line does not spell counts as the recursive one (tcc#128): `x=-rf; rm $x ~` is
    `rm -rf ~`, and xargs's appended word may be `-R`. An unquoted one (or `"$@"`) may split into
    several words, the flag and the target at once (`x='-rf ~'; rm $x`); a quoted one is one word,
    either the flag or the target, so it takes another unknown or wide word beside it to be both.
    `rm "$tmp"` stays a delete of one file.

    A relative operand is judged where the command runs (`cwd`, `_follow_cd`); chmod's mode — its
    first operand (`mode_first`) — is not a path and is judged as it is written.
    """
    options: list[_Word] = []
    operands: list[_Word] = []
    could_be_options: list[_Word] = []
    options_over = False
    for argument in arguments:
        if not options_over and argument.text == "--" and not argument.dynamic:
            options_over = True
        elif not options_over and is_option(argument.text):
            options.append(argument)
        else:
            operands.append(argument)
            if not options_over and _could_be_an_option(argument):
                could_be_options.append(argument)
    def wide(operand: _Word) -> bool:
        if mode_first and operands and operand is operands[0]:
            return _is_wide_target(operand.text)
        return _is_wide_here(operand.text, cwd) or outside and _outside_roots(operand.text, cwd)

    if any(option.dynamic or is_recursive(option.text) for option in options):
        if not operands:
            return bare
        return any(operand.dynamic or wide(operand) for operand in operands)
    if wide_alone and any(_reaches_wide(operand, cwd) for operand in operands):
        return True  # `rm ~/*`: every file of a home, recursive or not (Fable's final review, I1)
    if not could_be_options:
        return False
    return (any(_may_be_several_words(word) for word in could_be_options)
            or sum(operand.dynamic for operand in operands) > 1
            or any(not operand.dynamic and wide(operand) for operand in operands))


def _reaches_wide(operand: _Word, cwd: Optional[str]) -> bool:
    """A non-recursive delete's or overwrite's operand that is a glob over a whole home or system
    folder — `~/*`, `/Users/*/Desktop/*`, `*` after `cd ~` — judged where it runs. A folder named
    alone is not: without recursion it is refused (`Remove-Item -Recurse:$false ~`)."""
    text = operand.text
    if operand.dynamic or not any(ch in text for ch in "*?["):
        return False  # one unknown file, as `rm "$tmp"` always was; a wide loop taints it instead
    return _is_wide_here(text, cwd) or _outside_roots(text, cwd)


def _is_recursive_flag(text: str) -> bool:
    """`-r`, `-R`, `-rf`, `--recursive` — and any start of it GNU accepts, `--rec`."""
    return bool(_RM_RECURSIVE.search(text)) or len(text) > 2 and "--recursive".startswith(text)


def _may_be_several_words(word: _Word) -> bool:
    """An unquoted expansion splits; `"$@"` and `"${a[@]}"` are several words even quoted."""
    return not word.quoted or bool(re.search(r"\$@|\$\{@|\[@\]", word.text))


def _could_be_an_option(word: _Word) -> bool:
    """Whether a word the line does not spell could be an option: it starts with an expansion, and
    no spelled `/` after it makes it a path. `"$x"` and `${x}f` could be `-rf`; `"$dir/a.json"` cannot.
    Unquoted, the `/` saves nothing: `$x` splits first, so `x='-rf ~'; rm $x/` is `rm -rf ~/`
    (review of tcc#128), and `rm $dir/a.json` asks as `rm $f` does."""
    return (word.dynamic and word.text.startswith(_EXPANSION_STARTS)
            and ("/" not in word.text or _may_be_several_words(word)))


def _is_wide_target(text: str) -> bool:
    """Whether a path is somebody's whole machine or home: `/`, `~`, `$HOME`, `/Users`, a system
    folder, `/Users/someone`, `C:\\`, `C:\\Users` — or a glob over one (`~/*`, `/Users/*`), or a
    climb to one (`~/../*`), which reach the same files (tcc#128). Without case: macOS and Windows
    disks ignore it."""
    path = text.replace("\\", "/").lower()
    hive = _REGISTRY.match(path)
    if hive:
        # A hive, a key one level down (`HKCU:\\Software`), or Windows' own under Software.
        keys = [key for key in path[hive.end():].split("/") if key]
        cut = next((at for at, key in enumerate(keys) if any(ch in key for ch in "*?[")), len(keys))
        keys = keys[:cut]
        return len(keys) <= 1 or len(keys) == 2 and keys[0] == "software" and (
            keys[1] in _REGISTRY_WIDE_SECOND)
    home = re.match(r"~[^/]*|\$home|\$\{home\}", path)
    if home and path[home.end():home.end() + 1] in ("", "/"):
        # A home, wherever it lives, is one folder among the homes: `~/..` is all of them.
        path = "/users/" + home.group() + path[home.end():]
    # `//Users` is `/Users` on macOS and Linux, and `normpath` keeps exactly two leading slashes
    # (POSIX leaves them to the system), so they are folded first (review of tcc#128).
    path = re.sub(r"^/{2,}", "/", path)
    if path:
        path = posixpath.normpath(path)
    # A glob reaches the folder it stands in, wherever it stands: `~/*`, `~/.[!.]*`, and
    # `/Users/*/Library`, which is in every home. One in the first part of a relative path is the
    # folder the command runs in — the project's own (`rm -rf *.tmp`). A bracket alone spells a
    # few names, and is as narrow as they are: `~/[.]config` is `~/.config` (Ruling 41).
    parts = path.split("/")
    for at, part in enumerate(parts):
        if any(ch in part for ch in "*?["):
            if at == 0:
                return False
            if "*" not in part and "?" not in part and _spells_narrow_names("/".join(parts[:at]),
                                                                             part):
                continue
            parts = parts[:at]
            break
    path = "/".join(parts).rstrip("/")
    if path and not path.startswith("/") and not _WINDOWS_WIDE.match(path):
        # A session runs in the project, so `..` is the folder that holds it: a climb that does
        # not come back down — `..`, `../*` — or that climbs twice — `../..`, `../../x` — leaves
        # the project for something wider. `../build` is one sibling (Ruling 41).
        climbs = path.split("/")
        return climbs == [".."] or climbs[:2] == ["..", ".."]
    return (path == "" or path in _SYSTEM_DIRS or bool(_ONE_LEVEL_WIDE.fullmatch(path))
            or bool(_WINDOWS_WIDE.fullmatch(path)))


def _spells_narrow_names(parent: str, part: str) -> bool:
    """Whether a bracket glob — `[.]config`, no `*` or `?` — can spell only names that are narrow
    under `parent`: none of the names that make a path wide there (a system folder, a drive's,
    `.` or `..`), and `parent` not a folder where every name is somebody's home (Ruling 41)."""
    if _is_wide_target(f"{parent}/\0"):
        return False  # `/Users/[s]omeone`: whatever it spells is a home
    if re.search(r"\[[\^!]|\[[^\]]*\[[:=.]", part):
        # A negation (`[^x]`, `[!x]`) or a POSIX class (`[[:alpha:]]`, `[[=e=]]`, `[[.a.]]`):
        # `fnmatch` reads `[^` as a caret and has no classes, so `/[^x]tc` read as a name that is
        # not `/etc` (Ruling 44). `[.]config` is none of these: a `[.` counts only inside a bracket.
        return False
    spelled = re.compile(fnmatch.translate(part))
    return not any(spelled.match(name) and _is_wide_target(f"{parent}/{name}")
                   for name in _WIDE_NAMES)


def _is_windows_switch(text: str) -> bool:
    return bool(_WINDOWS_SWITCH.fullmatch(text))


def _switch_letters(text: str) -> str:
    """`/s/Q` → `sq`: the letters of a cmd switch, without case."""
    return "".join(re.findall(r"/([A-Za-z])", text)).lower()


def _find_is_dangerous(arguments: list[_Word], command: _Command, tainted: set[str],
                       depth: int) -> bool:
    """`-delete`, or an action that runs a command on every hit (`_FIND_RUNNERS`): a delete of every
    hit asks whatever its flags, as `find -exec rm` always did, and anything else it runs is judged
    by the same rules — `{}` being each hit's name, one word the line does not spell."""
    texts = [argument.text for argument in arguments]
    if "-delete" in texts:
        return True
    joined = " ".join(texts)
    for at, argument in enumerate(arguments):
        if argument.text not in _FIND_RUNNERS:
            continue
        if " rm " in f" {joined} " or " rm" in joined:
            return True  # the old reading, kept: it also catches `-exec sh -c 'rm "$1"' _ {} ;`
        end = at + 1
        while end < len(arguments) and arguments[end].text not in (";", "+"):
            end += 1
        run = [replace(word, dynamic=True, quoted=True) if "{}" in word.text else word
               for word in arguments[at + 1:end]]
        if run and (_command_name(run[0].text) == "rm"
                    or _words_are_dangerous(run, command, tainted, depth)):
            return True
    return False


def _cmd_is_dangerous(arguments: list[_Word], command: _Command, tainted: set[str],
                      depth: int) -> bool:
    """`cmd /c …` runs a line in cmd's own language, which `_Reader` does not speak: it is read by
    `_cmd_line_is_dangerous`. Without `/c` or `/k`, cmd runs what comes in on stdin. cmd takes the
    line glued to the switch too — `cmd /crd /s /q C:\\` (review of tcc#128)."""
    for at, word in enumerate(arguments):
        if word.dynamic or _runs(word, tainted):
            return True  # a switch the line does not spell could be `/c`
        glued = _CMD_GLUED_LINE.fullmatch(word.text)
        if not _is_windows_switch(word.text) and not glued:
            break
        if glued or set(_switch_letters(word.text)) & {"c", "k"}:
            line = arguments[at + 1:]
            if any(rest.dynamic or _runs(rest, tainted) for rest in line):
                return True  # the line cmd runs is not written here
            texts = [glued.group(1)] if glued else []
            return _cmd_line_is_dangerous(" ".join(texts + [rest.text for rest in line]), tainted,
                                          depth + 1, command.cwd)
    return command.piped or bool(command.stdin) or any(
        operator in ("<", "<>", "<&") for operator, _ in command.redirects)


def _cmd_line_is_dangerous(line: str, tainted: set[str], depth: int,
                           cwd: Optional[str] = "") -> bool:
    """A cmd line, read closely enough to judge: `&`, `|`, `(` and `)` part commands, a double quote
    holds spaces, `^` escapes, and `%NAME%` or `!NAME!` is a value the line does not spell. Each
    command is judged by the same rules as a shell one — `rd /s` among them (tcc#128) — and one on
    either side of a `|` as piped: `cmd /c "curl … | sh"` (review of tcc#128). It runs with the
    variables of the line that started cmd, so `tainted` comes along."""
    if depth > _MAX_DEPTH:
        return True
    commands: list[list[_Word]] = [[]]
    piped: list[bool] = [False]
    word: Optional[_Word] = None
    quoted = skip = False
    i = 0
    while i < len(line):
        ch = line[i]
        delimiter = not quoted and (ch in " \t,;=&|()<>")
        if delimiter and word is not None:
            word.dynamic = bool(re.search(r"[%!]", word.text))
            if not skip and not (ch in "<>" and word.text.isdigit()):
                commands[-1].append(word)
            skip = False
            word = None
        if ch == '"':
            quoted = not quoted
            word = word or _Word(started=True)
            word.quoted = True
        elif not quoted and ch == "^" and i + 1 < len(line):
            word = word or _Word(started=True)
            word.text += line[i + 1]
            i += 1
        elif not quoted and ch == "&" and line[i - 1:i] in ("<", ">"):
            pass  # `2>&1`: a stream moved, not a command after it
        elif not quoted and ch in "&|()":
            pipe = ch == "|" and "|" not in (line[i - 1:i], line[i + 1:i + 2])  # `||` is not one
            piped[-1] |= pipe
            commands.append([])
            piped.append(pipe)
            skip = False
        elif not quoted and ch in "<>":
            skip = True  # the next word is where the stream goes, not an argument
        elif not delimiter:
            word = word or _Word(started=True)
            word.text += ch
        i += 1
    if quoted:
        return True  # a quote that never closes: unknown is not safe
    if word is not None and not skip:
        word.dynamic = bool(re.search(r"[%!]", word.text))
        commands[-1].append(word)
    for words, in_pipe in zip(commands, piped):
        if not words:
            continue
        if words[0].text.startswith("@"):
            words[0] = replace(words[0], text=words[0].text[1:])  # `@rd`: the echo stays off
        readings = [words]
        glued = _CMD_GLUED_SWITCH.fullmatch(words[0].text)
        if glued:
            # `rd/s/q`: cmd ends a command's name at a `/`. Read both ways — as a path it is
            # judged by its last part, as cmd reads it by its first.
            readings.append([replace(words[0], text=glued.group(1)),
                             _Word(text=glued.group(2), started=True), *words[1:]])
        sure = len(readings)
        if _command_name(words[0].text) in ("if", "else", "do"):
            # cmd runs the command after `if exist x`, `if not … ==…`, `else` and `for … do`; where
            # the condition ends is cmd's to say, so every tail is read as that command (Ruling 41).
            readings.extend(words[at:] for at in range(1, len(words)))
        if any(_words_are_dangerous(reading, _Command(piped=in_pipe, cwd=cwd), tainted, depth)
               for reading in readings):
            return True
        if not any(reading and _command_name(reading[0].text) in _FOLDER_CHANGES
                   for reading in readings):
            _ran(words)  # `if exist x cd build` only changes the folder, read either way
        if not in_pipe:
            cwd = _cmd_cd(readings, sure, cwd)  # `cd /d C:\ && rd /s /q .`
    return False


def _cmd_cd(readings: list[list[_Word]], sure: int, cwd: Optional[str]) -> Optional[str]:
    """Where a cmd command leaves the folder. The first `sure` readings run as written; a `cd`
    found only in a tail behind `if`, `else` or `do` may not run, so it moves the folder only from
    one that is narrow — from a wide one, the `cd` that did not run is the wider case (Ruling 50)."""
    for at, reading in enumerate(readings):
        moved, target = _cd_target(reading, cwd, shell="cmd")
        if moved:
            return target if at < sure or not _is_wide_here(".", cwd) else cwd
    return cwd


def _powershell_is_dangerous(arguments: list[_Word], command: _Command, tainted: set[str],
                             depth: int) -> bool:
    """`powershell -Command …` (or its first word that is not an option, Windows PowerShell's
    default) runs a line in PowerShell's language: read by `_powershell_line_is_dangerous`. An
    `-EncodedCommand` is base64, unreadable here, so it asks; `-File` runs a script that is not on
    the line, as `bash x.sh` does; `-Command -` and no command at all read stdin (Ruling 41)."""
    at = 0
    while at < len(arguments):
        word = arguments[at]
        if _runs(word, tainted):
            return True
        text = word.text.lower()
        if not text.startswith("-") or text == "-":
            break
        at += 1
        if text == "-c" or len(text) > 3 and "-command".startswith(text):
            break
        if text in ("-e", "-ec") or len(text) > 2 and "-encodedcommand".startswith(text):
            return True
        if text == "-f" or len(text) > 2 and "-file".startswith(text):
            if at < len(arguments) and arguments[at].text == "-":
                return command.piped or bool(command.stdin)
            return at < len(arguments) and _runs(arguments[at], tainted)
    line = arguments[at:]
    if not line or line[0].text == "-":
        return command.piped or bool(command.stdin)
    # bash expands what is not in single quotes before PowerShell sees it; only the home is known.
    if any(_runs(word, tainted) or word.dynamic and word.refs != {"HOME"} for word in line):
        return True
    # An option the walk took for a switch may have taken a value: every tail is read as the line.
    return any(_powershell_line_is_dangerous(" ".join(word.text for word in line[start:]), depth + 1,
                                             command.cwd)
               for start in range(len(line)))


def _powershell_line_is_dangerous(line: str, depth: int, cwd: Optional[str] = "") -> bool:
    """A PowerShell line, read closely enough to judge Remove-Item: `;`, `|`, `&`, braces and
    parentheses part statements, `'…'` is literal, `"…"` and a backtick escape, `$HOME` and
    `$env:USERPROFILE` are the home, any other `$…` is a value the line does not spell. A statement
    that is not PowerShell's own is judged by the shell rules (`cmd /c …`, `git push --force`)."""
    if depth > _MAX_DEPTH:
        return True
    if _PS_DOTNET.search(line):
        return True  # a .NET call that deletes, overwrites or runs code: not taken apart here
    statements: list[list[_Word]] = [[]]
    piped: list[bool] = [False]
    fed: list[bool] = [False]  # the statement takes a pipe's input
    called: list[bool] = [False]  # after a lone `&`, PowerShell's call operator
    word: Optional[_Word] = None
    quote = ""

    def finish() -> None:
        nonlocal word
        if word is not None:
            text = _PS_HOME.sub("~", word.text)
            word = replace(word, text=text, dynamic=word.dynamic or "$" in text
                           or text.startswith("@"))
            statements[-1].append(word)
            word = None

    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == quote and quote == "'" and line[i + 1:i + 2] == "'":
                word.text += "'"
                i += 1
            elif ch == quote:
                quote = ""
            elif ch == "`" and quote == '"' and i + 1 < len(line):
                word.text += line[i + 1]
                i += 1
            else:
                word.text += ch
        elif ch in "'\"":
            word = word or _Word(started=True)
            word.quoted = True
            quote = ch
        elif ch == "`" and i + 1 < len(line):
            word = word or _Word(started=True)
            word.text += line[i + 1]
            i += 1
        elif ch == "$" and line[i + 1:i + 2] == "{":
            end = line.find("}", i)
            word = word or _Word(started=True)
            word.text += line[i:] if end < 0 else line[i:end + 1]
            i = len(line) if end < 0 else end
        elif ch == "#" and word is None:
            end = line.find("\n", i)
            i = len(line) if end < 0 else end
            continue
        elif ch in " \t":
            finish()
        elif ch in ";\n{}()|&":
            if ch == "(" and statements[-1]:
                finish()
                statements[-1].append(_Word(text="(…)", started=True, dynamic=True))
            finish()
            pipe = ch == "|" and "|" not in (line[i - 1:i], line[i + 1:i + 2])
            piped[-1] |= pipe
            statements.append([])
            piped.append(pipe)
            fed.append(pipe)
            called.append(ch == "&" and "&" not in (line[i - 1:i], line[i + 1:i + 2]))
        else:
            word = word or _Word(started=True)
            word.text += ch
        i += 1
    if quote:
        return True  # a quote that never closes: unknown is not safe
    finish()
    if _powershell_feeds_are_dangerous(statements, fed, cwd):
        return True
    for words, in_pipe, call in zip(statements, piped, called):
        if not words:
            continue
        if _powershell_statement_is_dangerous(words, in_pipe, call, depth, cwd):
            return True
        _ran(words)
        moved, target = _cd_target(words, cwd, shell="powershell")  # `Set-Location ~; ri -r .`
        if moved and not in_pipe:
            cwd = target
    return False


def _ps_body(words: list[_Word]) -> list[_Word]:
    """A statement without its assignment: `$all = gci ~ -r` is `gci ~ -r`."""
    if words and words[0].text.startswith("$") and len(words) > 1 and words[1].text in (
            "=", "+=", "-=", "*=", "/="):
        return words[2:]
    return words


def _ps_operands(arguments: list[_Word]) -> list[_Word]:
    """A cmdlet's operands: every word that is not a parameter, and a `-Name:value`'s value."""
    out: list[_Word] = []
    for word in arguments:
        if _is_parameter(word):
            value = word.text.partition(":")[2]
            if value:
                out.append(_Word(text=value, started=True, dynamic="$" in value))
        else:
            out.append(word)
    return out


def _ps_lister_at(words: list[_Word], names: frozenset) -> Optional[int]:
    return next((at for at, word in enumerate(words)
                 if not word.quoted and _command_name(word.text) in names), None)


def _ps_lists_wide(words: list[_Word], cwd: Optional[str]) -> bool:
    """A listing that reaches far: recursive (`-Recurse`, `-r`, `-Depth`), or over a home, a
    system folder or a place the line does not spell (`gci ~`, `dir C:\\Users`, `gci $p`)."""
    at = _ps_lister_at(words, _PS_LISTERS)
    if at is None:
        return False
    arguments = words[at + 1:]
    for word in arguments:
        if _is_parameter(word):
            name = word.text[1:].partition(":")[0].lower()
            if name and ("recurse".startswith(name) or len(name) > 1 and "depth".startswith(name)):
                return True
    return any(op.dynamic or _is_wide_here(op.text, cwd) or _outside_roots(op.text, cwd)
               for op in _ps_operands(arguments))


def _powershell_feeds_are_dangerous(statements: list[list[_Word]], fed: list[bool],
                                    cwd: Optional[str]) -> bool:
    """What a delete gets from elsewhere on the line (Fable's final review, C1 — bash's `xargs`
    rule): a remover or an emptier fed by a pipe, or one whose target the line does not spell
    (`% { Remove-Item $_.FullName }`, `foreach ($f in …) { ri $f }`), asks when the line lists
    recursively or wide — `gci ~ -Recurse | Remove-Item` — and a pipe-fed one when nothing on the
    line is a listing at all (`Get-Content list.txt | Remove-Item`: names the line does not show).
    And a process stopper fed by an unfiltered `Get-Process`, or told `-Name *`: everything."""
    bodies = [_ps_body(words) for words in statements]
    reaching = any(_ps_lists_wide(body, cwd) for body in bodies)
    listing = any(_ps_lister_at(body, _PS_LISTERS) is not None for body in bodies)
    every_process = False
    for body in bodies:
        at = _ps_lister_at(body, _PS_PROCESS_LISTERS)
        if at is not None and not _ps_operands(body[at + 1:]) and not any(
                _is_parameter(w) and w.text[1:].partition(":")[0].lower() in (
                    "name", "id", "n", "processname", "inputobject") for w in body[at + 1:]):
            every_process = True
    for body, from_pipe in zip(bodies, fed):
        if not body or body[0].dynamic:
            continue
        head = _command_name(body[0].text)
        targets = _ps_operands(body[1:])
        if head in _PS_REMOVERS | _PS_OVERWRITERS | _WINDOWS_DELETES:
            unspelled = not targets or any(t.dynamic for t in targets)
            if from_pipe and (reaching or not listing) or unspelled and reaching:
                return True
        if head in _PS_STOPPERS:
            names = [w.text.partition(":")[2] if ":" in w.text else ""
                     for w in body[1:] if _is_parameter(w)]
            if any(t.text in _MATCHES_ALL for t in targets) or "*" in names:
                return True
            if from_pipe and not targets and every_process:
                return True
    return False


def _powershell_statement_is_dangerous(words: list[_Word], piped: bool, called: bool,
                                       depth: int, cwd: Optional[str] = "") -> bool:
    if words[0].text.startswith("$"):
        if len(words) > 1 and words[1].text in ("=", "+=", "-=", "*=", "/="):
            words = words[2:]  # `$p = Get-Location`: what is assigned is the statement
            if not words:
                return False
        else:
            # An expression — `$p`, `$_.Name -like '*.tmp'` — runs nothing; `& $cmd` runs what
            # the line does not spell.
            return called
    name = _command_name(words[0].text)
    if words[0].dynamic:
        return True  # what runs is not written on the line
    if name in _PS_KEYWORDS:
        return False  # its condition and its body are statements of their own
    if name in ("iex", "invoke-expression"):
        return True  # PowerShell's `eval`
    if name in _LINK_FOLLOWERS and _reaches_out_through_a_link(words[1:], cwd):
        return True
    if name in _PS_REMOVERS:
        return _remove_item_is_dangerous(words[1:], piped, cwd)
    return _words_are_dangerous(words, _Command(piped=piped, cwd=cwd), set(), depth)


def _remove_item_is_dangerous(arguments: list[_Word], piped: bool, cwd: Optional[str] = "") -> bool:
    """PowerShell's `Remove-Item -Recurse` (`-r`, `-rec`, `-Recurse:$true`, any case, any order) on
    a wide target: a drive root, the home, `C:\\Users`, a climb, `*` — or one it does not spell, or
    none when a pipe feeds it (`gci C:\\ | Remove-Item -Recurse`). Every word that is not a
    parameter is taken as a target, and a `-Path:x` value too: a parameter's value read as a target
    can only add a question, never hide one (Ruling 41)."""
    recurse = False
    targets: list[_Word] = []
    for word in arguments:
        text = word.text
        if _is_parameter(word):
            name, has_value, value = text[1:].partition(":")
            if name and "recurse".startswith(name.lower()):
                recurse |= value.lower() != "$false"
            elif has_value and value:
                targets.append(_Word(text=value, started=True, dynamic="$" in value))
            continue
        targets.append(word)
    splat = any(target.text.startswith("@") for target in targets)  # `@args` may hold -Recurse
    if not (recurse or splat):
        # Not recursive: still a delete of every file a wide glob or name reaches (`Remove-Item
        # ~\\*`, Fable's final review, I1); fed by a pipe it is judged with its producer.
        return any(_reaches_wide(target, cwd) for target in targets)
    if any(_holds_a_link_out(target, cwd) for target in targets):
        return True  # Windows PowerShell 5.1 recurses through a junction inside what it deletes
    if not targets:
        return piped
    return any(target.dynamic or _is_wide_here(target.text, cwd)
               or _outside_roots(target.text, cwd)
               or cwd == "" and posixpath.normpath(target.text.replace("\\", "/")) in ("*", "*.*")
               for target in targets)


def _git_is_dangerous(arguments: list[_Word], tainted: set[str]) -> bool:
    """A force push, a deleted remote branch or a mirror rewrites what others already have."""
    at = 0
    while at < len(arguments):
        argument = arguments[at]
        if argument.dynamic or _runs(argument, tainted):
            return True  # what git is told to do is not on the line
        if argument.text in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
            at += 2
        elif argument.text.startswith("-"):
            at += 1
        else:
            break
    if at >= len(arguments) or arguments[at].text != "push":
        return False
    return any(_push_word_is_dangerous(argument, tainted) for argument in arguments[at + 1:])


def _push_word_is_dangerous(word: _Word, tainted: set[str]) -> bool:
    """One word of `git push`: a force (`--force`, `-f`, `+main`), a delete (`--delete`, `-d`,
    `:main`), `--mirror`, `--prune` — or a word the line does not spell, which could be any of them:
    `echo --force | xargs git push origin main` (tcc#128). `"feature/$name"` cannot."""
    if _runs(word, tainted) or word.dynamic and word.text.startswith(_EXPANSION_STARTS):
        return True
    text = word.text
    if text.startswith("--"):
        return text.partition("=")[0] in _PUSH_REWRITES or text.startswith("--force")
    if text.startswith("-"):
        for letter in text[1:]:
            if letter in "fd":
                return True
            if letter == "o":
                return False  # `-o<option>`: the rest is its value
        return False
    return text.startswith(("+", ":"))


def _shell_is_dangerous(arguments: list[_Word], command: _Command, tainted: set[str],
                        depth: int) -> bool:
    """`bash -c '…'` is a script on the line, and it is read like the line. A script that is NOT on
    the line — a variable, a substitution, a pipe — is what `curl … | sh` always was."""
    if any(_runs(argument, tainted) for argument in arguments):
        return True
    command_string = from_stdin = False
    at = 0
    while at < len(arguments):
        text = arguments[at].text
        if arguments[at].dynamic:
            return True  # an option the line does not spell could be `-c`
        if len(text) < 2 or text[0] not in "-+":
            break
        at += 1
        if text == "--":
            break
        if text in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            at += 1
        elif not text.startswith("--"):
            command_string |= "c" in text[1:]
            from_stdin |= "s" in text[1:]
    operands = arguments[at:]
    if command_string:
        if not operands or operands[0].dynamic:
            return True  # the script is not written on the line
        return _script_is_dangerous(operands[0].text, depth + 1, tainted, command.cwd)
    if operands and not from_stdin and not _is_stdin_path(operands[0].text):
        return False  # a script file: not read here, as before tcc#115
    return _stdin_script_is_dangerous(command, tainted, depth)


def _is_stdin_path(text: str) -> bool:
    """A file name that IS the command's input: `bash /dev/stdin <<'EOF'` runs the heredoc."""
    return text in ("-", "/dev/stdin") or text.startswith(("/dev/fd/", "/proc/self/fd/"))


def _stdin_script_is_dangerous(command: _Command, tainted: set[str], depth: int) -> bool:
    """A script that comes in on stdin: a pipe, a heredoc, a here-string, a redirect."""
    if command.piped:
        return True
    for body in command.stdin:
        if body.dynamic or _script_is_dangerous(body.text, depth + 1, tainted, command.cwd):
            return True
    return any(operator in ("<", "<>", "<&") and (target.dynamic or _runs(target, tainted))
               for operator, target in command.redirects)


def _interpreter_is_dangerous(name: str, arguments: list[_Word], command: _Command,
                              tainted: set[str]) -> bool:
    """The program is not read — but it must not be another command's output."""
    values = _INTERPRETER_VALUES.get(
        "python" if name.startswith(("python", "pypy")) else name, frozenset())
    at = 0
    while at < len(arguments):
        text = arguments[at].text
        if (text.partition("=")[0] in values or text[:2] in values) and _runs(arguments[at],
                                                                                tainted):
            return True  # glued: `node --import="$(curl …)"`, `ruby -r"$(curl …)"` (Ruling 44)
        if text in values:
            if at + 1 < len(arguments) and _runs(arguments[at + 1], tainted):
                return True  # `node --import "$(curl …)"`: a data: URL is code (Ruling 43)
            at += 2  # its value — a library, a folder, a setting — is not the program
            continue
        # `-c` python, `-e`/`-E` perl, ruby, node, osascript, Rscript, lua, `-p` node, `-r` php.
        code_flag = text in ("--eval", "--print") or (
            len(text) > 1 and text[0] == "-" and text[1] != "-" and text[-1] in "ceEpr")
        if code_flag or text == "-m":
            follows = arguments[at + 1] if at + 1 < len(arguments) else None
            return follows is not None and _runs(follows, tainted)
        if _is_stdin_path(text):
            break
        if not text.startswith("-"):
            return _runs(arguments[at], tainted)  # the script: `python3 <(curl …)`
        at += 1
    # The program comes in on stdin: `curl … | python3`, or a heredoc with a `$( … )` in it.
    if command.piped:
        return True
    return any(_runs(body, tainted) for body in command.stdin) or any(
        operator in ("<", "<>", "<&") and _runs(target, tainted)
        for operator, target in command.redirects)


def _code_arguments_are_dangerous(name: str, arguments: list[_Word], tainted: set[str],
                                  depth: int, cwd: Optional[str] = "") -> bool:
    """`trap 'rm -rf ~' EXIT` and `alias x='rm -rf ~'` hold a script for later — it is read now."""
    for argument in arguments:
        if name == "trap" and argument.text in ("-p", "-l", "--"):
            continue
        code = argument.text.partition("=")[2] if name == "alias" else argument.text
        if argument.dynamic or _script_is_dangerous(code, depth + 1, tainted, cwd):
            return True
        if name == "trap":
            return False  # the rest are signal names
    return False


def bash_is_read_only(command: str, roots: Sequence[Path]) -> bool:
    """Whether `command` is one of the read-only invocations the skill makes all day.

    Conservative by construction: anything unparseable, substituted or redirected into a file is
    not read-only, so the answer degrades to "ask the Arbiter" rather than to "allow".

    A chain is judged part by part rather than refused for being a chain. Refusing it outright was
    the wrong kind of caution: `ls -la … 2>&1; echo ---; readlink -f …` is three reads and a
    stream redirect, and putting that in front of the Arbiter teaches them to approve without
    looking — which is worse protection than not asking. Every part must pass on its own, so the
    chain can only be as permissive as its least permissive command.
    """
    if not command.strip() or _has_substitution(command):
        return False  # nothing to judge is not the same as nothing to worry about
    parts = [part for part in _SEPARATORS.split(command) if part.strip()]
    return bool(parts) and all(_single_command_is_read_only(part, tuple(roots)) for part in parts)


def _single_command_is_read_only(command: str, roots: tuple[Path, ...]) -> bool:
    without_discards = _DISCARD_REDIRECT.sub(" ", command)
    if _FILE_REDIRECT.search(without_discards):
        return False  # a redirect that writes somewhere real
    try:
        parts = shlex.split(without_discards)
    except ValueError:
        return False
    if not parts:
        return False
    head, *rest = parts
    name = Path(head).name
    if name in _SAFE_COMMANDS:
        # The name is where the judgement starts, not where it ends. `find`, `sort` and `cat` are
        # all on this list, and all three reach past reading the project when their arguments say
        # so -- which is how the 06.09 audit walked five commands through a gate that only ever
        # read the first word (`hub:docs/AUDIT-FF-2026-09-06.md` §1.1).
        if name == "find":
            return _find_is_read_only(rest, roots)
        if name in _OUTPUT_FLAG_COMMANDS and _writes_its_output_to_a_file(rest):
            return False
        if name in _PATH_ARGUMENT_COMMANDS:
            return _path_arguments_are_within_roots(name, rest, roots)
        return True
    if name == "git":
        return _git_is_read_only(rest)
    if name.startswith("python"):
        # `-c` is arbitrary code with a shell's reach, so it is never on this list however
        # harmless the snippet looks; `-m` is the same reach spelled as a module name
        # (`python3 -m http.server` serves the tuner's project to the network). A named script
        # from the skill's read-only set is a different thing -- but the name is not the script:
        # `/tmp/evil/analysis.py` passed the basename check, so the file itself has to be one of
        # the project's own.
        if "-c" in rest or "-m" in rest:
            return False
        script = next((arg for arg in rest if arg.endswith(".py")), None)
        if script is None or Path(script).name not in _SAFE_REW_SCRIPTS:
            return False
        return _within_roots(script, roots)
    return False


# ---- the one decision: omp's gate, and Codex's approvals (tcc#181) ------------------------------
#
# Lifted from `OmpSession._auto_allowed` and `_gate` with its order kept, so the two harnesses TCC
# drives itself answer one table. The Agent SDK route keeps its own (`TuningSession._can_use_tool`):
# it shares the two readings above, not this order.

# Tools that only look. Auto-approved because `--approval-mode always-ask` otherwise puts a
# dialog in front of every file the skill opens -- and the skill is built on opening files, so the
# Arbiter learns to click through, which is worse than not asking.
READ_ONLY_TOOLS = frozenset({"read", "glob", "grep", "ls", "list", "todo", "hub"})

# Never auto-approved, whatever else is true: these can overwrite a measurement, a ledger or the
# project's own files, which is the evidence everything else is built on.
ALWAYS_GATED_TOOLS = frozenset({"write", "edit", "ast_edit", "eval", "browser", "task"})

#: Every name this table has a row for: omp's tools (`omp_session._ENABLED_TOOLS` among them —
#: a test holds that). Any other name, unless it is TCC's own `mcp__tcc…`, is a stranger: it asks
#: under every gate that asks at all, `auto` included, and `never` says it (the fix round of
#: tcc#181, the Arbiter 2026-10-14 — `auto` let a stranger through without a look).
OMP_TOOLS = READ_ONLY_TOOLS | ALWAYS_GATED_TOOLS | {"bash", "ask", "inspect_image"}

#: The names a Codex session passes, mapped onto omp's — the names this table is written in.
#: `item/commandExecution/requestApproval` is "Bash" (the inner command), `item/fileChange/
#: requestApproval` is "Edit" (its paths); TCC's tools come as `mcp__tcc__<tool>` and need no
#: mapping (the `mcp__tcc` prefix is the rule). Any other name is taken as it is, and one not in
#: `OMP_TOOLS` asks. omp's own names (`bash`, `edit`, …) map to themselves.
TOOL_NAMES = {"Bash": "bash", "Edit": "edit"}

# What the skill's own writers do, so a permission can ask about the effect instead of the command
# line. "Allow bash: python3 rew_tool/apply.py --preset FULL ..." is not a question anyone can
# answer -- it is a script that starts a Python that computes -- while "write a ledger snapshot"
# is. Only the writers are listed: readers never reach the gate.
_EFFECTS: tuple[tuple[str, str], ...] = (
    ("state/process.py", "effectProcess"),
    ("dsp_profile.py", "effectProfile"),
    ("apply.py", "effectLedger"),
    ("project.py", "effectProject"),
    ("contract.py", "effectContract"),
)

# Paths the skill legitimately owns inside a project: a path is the skill's when it STARTS with one
# of these, relative to the project (see `touches_only_skill_files`).
_SKILL_OWNED = ("process/", "state/", "dsp_profile.json", "dsp_profile.draft.json",
                "project.json", "autosound_context.md", "tuning-changelog", "audit-trail.md")

#: The shells `judge_action` reads a command line as.
SHELL_BASH = "bash"
SHELL_POWERSHELL = "powershell"

#: The method's ledger writer, inside the skill's own folder. Run by an interpreter it is the skill
#: doing its job, and its ARGUMENTS are data — `capture-knobs SubRC=4/4`, `done -1.1 project.json`
#: — not paths: the writer writes only the project's skill files, that is its contract.
_SKILL_WRITER = ("rew_tool", "state", "process.py")
#: What runs it: the interpreter, and the options that change nothing about what it runs.
_WRITER_RUNNERS = re.compile(r"python(?:3(?:\.\d+)?)?|py")
_WRITER_RUNNER_OPTIONS = frozenset({"-u", "-B", "-3"})
#: The variable a session's shell holds the method's copy in (`method_binding.SKILL_ROOT_ENV`).
_SKILL_ROOT_REFS = ("$AUTOSOUND_SKILL_ROOT/", "${AUTOSOUND_SKILL_ROOT}/")

#: The owned folders by their own name, without the slash: `./process` is `process/`.
_SKILL_FOLDERS = frozenset(owned.rstrip("/") for owned in _SKILL_OWNED if owned.endswith("/"))

#: What may run in a line `foreign` lets through as the skill's own: an allow-list, not a list of
#: what looks like a path (the second fix round of tcc#181 — `rm -rf measurements process/a.json`
#: hid a bare word behind one owned path). Commands whose every operand is a path the skill owns:
_FOREIGN_PATH_HEADS = {
    SHELL_BASH: frozenset({"cat", "tee", "mkdir", "touch", "cp", "mv", "rm"}),
    SHELL_POWERSHELL: frozenset({"set-content", "add-content", "new-item", "copy-item",
                                      "move-item", "remove-item", "out-file",
                                      "cat", "tee", "mkdir", "cp", "mv", "rm"}),
}
#: …and commands whose operands are text, not files (only their redirections are judged):
_FOREIGN_DATA_HEADS = {
    SHELL_BASH: frozenset({"echo", "printf"}),
    SHELL_POWERSHELL: frozenset({"echo", "write-output"}),
}
#: PowerShell parameters whose value is text, not a path: `Set-Content process/a.json -Value x`.
#: Exact names only — a guess at an abbreviation would skip a path unread.
_PS_DATA_PARAMS = frozenset({"-value", "-encoding", "-itemtype", "-type"})
#: What PowerShell's line may not hold for `foreign` to read it at all: a value the line does not
#: spell (`$`, `@`, `(…)`, `{…}`), an escape, a call (`&`), input (`<`), a comment.
_PS_UNREAD = frozenset("`$@(){}&<#")
#: What runs rather than reads: never a skill file, even in `state/` (`cat > state/evil.py`).
_SCRIPT_SUFFIXES = (".py", ".sh", ".bash", ".zsh", ".ps1", ".psm1", ".bat", ".cmd", ".exe",
                    ".command")
#: The ways a shell changes folder: only into the project itself, and only first (`cd <project> &&`).
_CD_HEADS = frozenset({"cd", "set-location", "sl", "chdir"})



@dataclass(frozen=True)
class Verdict:
    """What the gate decided about one request, complete enough to act on without deciding again.

    `allowed` — run it without asking. `unasked` — set only when `never` let through what `auto`
    would have stopped: the caller says it in the dialog (`agent_events.Unasked(unasked)`), never
    silently (tcc#115). When not allowed, the rest is the confirmation's text, field for field as
    `mcp_server.ConfirmRequest` takes it: `tool` (the effect's i18n key, else the tool's name — also
    what a «don't ask again» tick remembers; the effect only for a command), `title`, `detail` (the
    command itself when it cannot be undone) and `reason` (`gateIrreversible` when the danger check
    flagged the command, whichever gate asked). `title` is an i18n key and `title_args` its values:
    the bar words it in the window's language (`ALLOW_TITLE`)."""

    allowed: bool
    unasked: str = ""
    tool: str = ""
    title: str = ""
    detail: str = ""
    reason: str = ""
    title_args: dict = field(default_factory=dict)


#: The question the gate asks — «Allow {tool}?» — as an i18n key: core stays language-free, and the
#: bar words it in the window's language (it was «Дозволити …?» in an English window, W-10).
ALLOW_TITLE = "confirmAllowTitle"


def allow_title_args(tool: str, shell: str = SHELL_BASH) -> dict:
    """`ALLOW_TITLE`'s values: the tool by its name, and a shell line by the shell that runs it —
    a PowerShell line is not «Bash» to the person reading it (Codex on Windows, W-10)."""
    if shell == SHELL_POWERSHELL and TOOL_NAMES.get(tool, tool) == "bash":
        return {"tool": "PowerShell"}
    return {"tool": tool}


def effect_of(command: str) -> Optional[str]:
    """An i18n key naming what a prescribed command writes, or None if TCC does not know it."""
    for needle, key in _EFFECTS:
        if needle in command:
            return key
    return None


def touches_only_skill_files(command: str, *, shell: str = "bash", project: Optional[Path] = None,
                             skill: Optional[Path] = None) -> bool:
    """Whether the line does nothing but the skill's own work in its own namespace (`foreign`'s
    pass). Says nothing about danger — `judge_action` asks that first.

    An allow-list (the second fix round of tcc#181). Every simple command — split on `;`, `&&`,
    `||`, `|` and new lines — must be one of three things: a command on `_FOREIGN_PATH_HEADS` whose
    every operand is a skill path; one on `_FOREIGN_DATA_HEADS` (its operands are text); or the
    method's writer run by an interpreter (`_runs_the_writer`; its arguments are data). Every
    redirection target of each must be a skill path, or a stream. A first `cd` into the project
    itself is the folder the line runs in anyway; any other `cd`, `ln`, `git`, `chmod`, `python3 -c`,
    `bash`, an assignment, a substitution, a `( … )` or `if` — anything not on the list — asks. And
    a line with no skill path and no writer is not «only skill files»: nothing to judge is not the
    same as nothing to worry about.

    A skill path (`_skill_path`) is relative to the project, starts with an owned prefix, has no
    `..`, no variable, no `~`; an absolute one inside the project is read relative to it first, and
    one a symlink takes out of the namespace is not the skill's. `project`, `skill`: the project's
    folder and the method's copy (`_read_roots_for`'s two roots); without them only relative paths
    are read and no writer is known."""
    statements = (_powershell_simple_statements(command) if shell == SHELL_POWERSHELL
                  else _bash_simple_statements(command))
    if not statements:
        return False
    if _is_cd_into(statements[0][0], project, shell):
        statements = statements[1:]
    named = False
    for words, targets in statements:
        if not words:
            return False
        for target in targets:
            if target in _STREAM_DEVICES or re.fullmatch(r"\d+|-", target):
                continue  # a stream, not a file: `2>/dev/null`, `2>&1`
            if _skill_path(target, project, shell) is None:
                return False
            named = True
        head, operands = _command_name(words[0]), words[1:]
        if _runs_the_writer(head, operands, project, skill, shell):
            named = True
            continue
        if head in _FOREIGN_DATA_HEADS[shell]:
            continue
        if head not in _FOREIGN_PATH_HEADS[shell]:
            return False
        if head == "new-item" and not _new_item_is_a_file_or_folder(operands):
            return False
        paths = _powershell_operands(operands) if shell == SHELL_POWERSHELL else _bash_operands(
            operands)
        if paths is None or any(_skill_path(path, project, shell) is None for path in paths):
            return False
        named |= bool(paths)
    return named


def _bash_simple_statements(line: str) -> Optional[list[tuple[list[str], list[str]]]]:
    """The line as `_Reader` takes it apart: (words, redirection targets) per simple command, or
    None when anything in it is more than a simple command with words written on the line."""
    try:
        commands: list[_Command] = []
        _Reader(line.strip(), commands, 0).read()
    except (_Unreadable, RecursionError):
        return None
    statements = []
    for command in commands:
        if command.compound or not command.words:
            return None
        if _ASSIGNMENT.match(command.words[0].text) or _is_reserved(command.words[0]):
            return None  # `X=1 rm …`, `if`, `for`: not a simple command
        if any(word.output for word in command.words) or any(
                target.output or target.dynamic for _, target in command.redirects):
            return None  # another command's output, or a target the line does not spell
        if any(word.dynamic for word in command.words[:1]):
            return None
        # A word whose value the line does not spell (`{a,b}`, `$'…'`) keeps a `$`, so no
        # reading below can take it for a skill path.
        statements.append(([("$" if word.dynamic and "$" not in word.text else "") + word.text
                            for word in command.words],
                           [target.text for _, target in command.redirects]))
    return statements


def _powershell_simple_statements(line: str) -> Optional[list[tuple[list[str], list[str]]]]:
    """A PowerShell line, read only as far as `foreign` needs and no further: statements split on
    `;`, `|` and new lines, words on blanks and commas, `'…'` and `"…"` quoted, `>`/`>>` (with a
    stream number before it) a redirection. None for a line holding anything in `_PS_UNREAD` or a
    quote that never closes — what is not read here is asked about."""
    if any(ch in _PS_UNREAD for ch in line):
        return None
    statements: list[tuple[list[str], list[str]]] = [([], [])]
    word: Optional[str] = None
    quote = ""
    redirect = False

    def finish() -> None:
        nonlocal word, redirect
        if word is not None:
            words, targets = statements[-1]
            (targets if redirect else words).append(word)
            word, redirect = None, False

    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == quote:
                quote = ""
            else:
                word += ch
        elif ch in "'\"":
            word = word or ""
            quote = ch
        elif ch in " \t\r,":
            finish()
        elif ch in ";|\n":
            finish()
            statements.append(([], []))
        elif ch == ">":
            if word is not None and re.fullmatch(r"\d|\*", word):
                word = None  # `2>`, `*>`: which stream, not a word
            finish()
            if line[i + 1:i + 2] == ">":
                i += 1
            redirect = True
        else:
            word = (word or "") + ch
        i += 1
    if quote or redirect and word is None:
        return None
    finish()
    return [statement for statement in statements if statement[0] or statement[1]]


def _new_item_is_a_file_or_folder(operands: list[str]) -> bool:
    """`New-Item` takes `foreign`'s pass as a file or a folder only: as a link its `-Value` is where
    the link points, not text (`-ItemType Junction -Value C:/Users`)."""
    kinds = [value for name, _, value in (word.partition(":") for word in operands)
             if value and name.lower() in ("-itemtype", "-type")]
    kinds += [operands[at + 1] for at, word in enumerate(operands[:-1])
              if word.lower() in ("-itemtype", "-type")]
    if any(word.lower() in _LINK_KINDS for word in operands):
        return False
    return all(kind.lower() in ("file", "directory") for kind in kinds)


def _bash_operands(operands: list[str]) -> Optional[list[str]]:
    """What a path command names: every word but its options, and an option's `=value`."""
    paths = []
    ended = False
    for word in operands:
        if not ended and word == "--":
            ended = True
        elif not ended and word.startswith("-") and len(word) > 1:
            if "=" in word:
                paths.append(word.split("=", 1)[1])
        else:
            paths.append(word)
    return paths


def _powershell_operands(operands: list[str]) -> Optional[list[str]]:
    """What a cmdlet names: every word but its switches and the values of `_PS_DATA_PARAMS`; a
    `-Path:x` value is a path. A word after any other parameter is read as a path too — a switch's
    neighbour or a parameter's value, either way it may only add a question."""
    paths = []
    skip = ended = False
    for word in operands:
        if skip:
            skip = False
            continue
        if not ended and word == "--":
            ended = True
            continue
        if not ended and word.startswith("-") and len(word) > 1:
            name, colon, value = word.partition(":")
            if name.lower() in _PS_DATA_PARAMS:
                skip = not colon
            elif colon and value:
                paths.append(value)
            continue
        paths.append(word)
    return paths


def _is_cd_into(words: list[str], project: Optional[Path], shell: str) -> bool:
    """`cd <project>` exactly: the folder the line runs in anyway, so it may lead a line."""
    if project is None or len(words) != 2 or _command_name(words[0]) not in _CD_HEADS:
        return False
    target = _slashed(words[1], shell)
    return _is_absolute(target) and _inside(target, project) == ""


def _runs_the_writer(head: str, operands: list[str], project: Optional[Path],
                     skill: Optional[Path], shell: str) -> bool:
    """An interpreter running the method's writer in the skill's own folder: by an absolute path,
    by `$AUTOSOUND_SKILL_ROOT/…`, through the project's link (`.claude/skills/autosound-tuning/…`),
    or as the method's documents write it (`rew_tool/state/process.py`) when the project holds
    nothing at that path (then the line fails rather than runs something else). Whatever it resolves
    to must be the writer in `skill`: a `process.py` in the project's `state/` is not it."""
    if skill is None or not _WRITER_RUNNERS.fullmatch(head):
        return False
    at = 0
    while at < len(operands) and operands[at] in _WRITER_RUNNER_OPTIONS:
        at += 1
    if at >= len(operands) or not _is_the_writer(_slashed(operands[at], shell), project, skill):
        return False
    # Its arguments are data — but the first is the folder it writes into (`--root <folder>` the
    # same), and that must be the project's own: `… process.py /etc done x` is not a skill write.
    rest = operands[at + 1:]
    if rest and rest[0] == "--root":
        rest = rest[1:]
    elif rest and rest[0].startswith("--root="):
        rest = [rest[0].split("=", 1)[1], *rest[1:]]
    return bool(rest) and _skill_path(rest[0], project, shell) is not None


def _is_the_writer(script: str, project: Optional[Path], skill: Path) -> bool:
    writer = os.path.realpath(skill.joinpath(*_SKILL_WRITER))
    for ref in _SKILL_ROOT_REFS:
        if script.startswith(ref):
            return os.path.realpath(skill / script[len(ref):]) == writer
    if "$" in script or "%" in script or script.startswith("~"):
        return False
    if _is_absolute(script):
        return os.path.realpath(script) == writer
    if ".." in script.split("/") or project is None:
        return False
    there = project / script
    if os.path.lexists(there):
        return os.path.realpath(there) == writer
    return posixpath.normpath(script) == "/".join(_SKILL_WRITER)


def _slashed(word: str, shell: str) -> str:
    """A PowerShell path with `/` for `\\`: `.\\process\\a.json` is `./process/a.json`, and
    `C:\\x`, `\\\\server\\share` stay absolute (`C:/x`, `//server/share`)."""
    return word.replace("\\", "/") if shell == SHELL_POWERSHELL else word


def _inside(path: str, project: Path) -> Optional[str]:
    """An absolute path relative to the project ("" for the project itself), or None outside it.
    The project as given and as resolved both count: macOS's `/var` is `/private/var`."""
    norm = posixpath.normpath(path)
    given = {project.as_posix(), Path(os.path.realpath(project)).as_posix()}
    # Git Bash names a drive `/c/…`: the same folder as `C:/…` (the Windows pass of PR #215). A
    # Windows drive ignores case, in either spelling; nothing else here is folded.
    roots = {(root, bool(re.match(r"[A-Za-z]:", root))) for root in given}
    roots |= {(f"/{drive.group(1)}/{drive.group(2)}", True) for drive in
              (re.match(r"([A-Za-z]):/(.*)", root) for root in given) if drive}
    for root, fold in roots:
        here, there = (norm.lower(), root.lower()) if fold else (norm, root)
        if here == there:
            return ""
        if here.startswith(there.rstrip("/") + "/"):
            return norm[len(root.rstrip("/")) + 1:]
    return None


def _skill_path(word: str, project: Optional[Path], shell: str) -> Optional[str]:
    """The word as a path the skill owns, relative to the project — or None.

    Relative, an owned prefix (or an owned folder by its name), no `..`, no variable, no `~`, no
    backslash left; an absolute path inside the project is read relative to it first. On disk, the
    folder it lands in must still be the skill's: `ln -s .. state/up` makes `state/up/` the
    project, and a check of the text alone would let `rm -rf state/up/` delete it."""
    path = _slashed(word, shell)
    if any(mark in path for mark in ("\\", "$", "%")) or path.startswith("~"):
        return None
    if _is_absolute(path):
        path = _inside(path, project) if project is not None else None
        if not path:
            return None
    if ".." in path.split("/"):
        return None
    while path.startswith("./"):
        path = path[2:]
    if not _is_owned(path) or path.lower().endswith(_SCRIPT_SUFFIXES):
        return None  # the namespace holds data; a script there is one the next line could run
    if project is not None:
        fixed = re.split(r"[*?\[]", path, maxsplit=1)[0]  # a glob's folder, not its pattern
        fixed = fixed if fixed == path else posixpath.dirname(fixed)
        places = [str(project / fixed)] if fixed else [""]
        if fixed != path:  # and every match, each landing where its own links take it
            places += glob.glob(str(project / path), include_hidden=True)
        for place in places:
            real = os.path.realpath(place) if place else ""
            landed = os.path.relpath(real, os.path.realpath(project)) if real else ""
            if (not landed or landed.startswith("..")
                    or not _is_owned(landed.replace(os.sep, "/"))):
                return None
    return path


def _is_owned(path: str) -> bool:
    return path.startswith(_SKILL_OWNED) or path.rstrip("/") in _SKILL_FOLDERS


def _is_dangerous(command: str, roots: Sequence[Path], shell: str) -> bool:
    """`bash_is_dangerous`, and for a line the caller knows is PowerShell its own reader as well:
    read as bash, `C:\\Users` loses its backslash and a recursive delete of it passes. Either
    reading that flags it asks, so a PowerShell line is never judged more loosely than a bash one."""
    if bash_is_dangerous(command, roots):
        return True
    with _in_project(roots):
        return shell == SHELL_POWERSHELL and _powershell_line_is_dangerous(command.strip(),
                                                                           depth=0)


#: The method's root as the line may READ it; any other mention of the name sets it, or might.
_SKILL_ROOT_READS = re.compile(r"\$AUTOSOUND_SKILL_ROOT(?![\w=:\[])|\$\{AUTOSOUND_SKILL_ROOT\}")


def _sets_skill_root(line: str) -> bool:
    """`export`/`set`/`$env:`/an assignment of `AUTOSOUND_SKILL_ROOT`: the root is TCC's to set
    (`binding.session_env`), and the writer check trusts it — a persistent shell would carry one
    the line set into every line after it. So it asks, in every gate that asks."""
    return "autosound_skill_root" in _SKILL_ROOT_READS.sub("", line).lower()


def judge_action(tool: str, detail: str, *, gate: str, always_allowed: Iterable[str] = (),
                 read_roots: Sequence[Path] = (), command: Optional[str] = None,
                 shell: str = SHELL_BASH) -> Verdict:
    """Whether this can go through without asking, and if not, what the question says.

    `tool` is omp's name or Codex's (`TOOL_NAMES`); `detail` what it wants to do, shown when it
    asks; `command` the shell line inside `detail` (omp's `Command: …` already split off by the
    caller — this does not parse it, so a line that SAYS «Command:» cannot hide its head), or
    `detail` itself when None. `shell`: `powershell` for a line the caller knows is PowerShell —
    never read-only, and judged dangerous by either reader; any other value raises ValueError.
    `read_roots` is `_read_roots_for`'s: the project first, the method's copy after it — the
    `foreign` pass reads both (`touches_only_skill_files`). `gate` and `always_allowed` are read
    per call, so a gate narrowed mid-session takes effect on
    the next request. A name outside `OMP_TOOLS` and `mcp__tcc…` asks even under `auto`.

    Three things pass, and the reasoning for each is different. TCC's own tools raise their
    own confirmation *inside* the tool, so asking here too prompts twice for one action and
    teaches the Arbiter to click through both. Tools that only look cannot damage the evidence
    the tune is built on. And a bash command already judged read-only by the SDK adapter's
    allowlist -- one definition, shared -- is the same command whichever harness runs it.

    Everything else asks, and a short list can never be talked into passing: anything that
    writes or evaluates goes in front of the Arbiter even if it looks harmless, because what
    it can overwrite is a measurement or a ledger.
    """
    if shell not in (SHELL_BASH, SHELL_POWERSHELL):
        raise ValueError(f"judge_action reads bash or powershell lines, not {shell!r}")
    name = TOOL_NAMES.get(tool, tool)
    line = detail if command is None else command
    stranger = name not in OMP_TOOLS and not name.startswith("mcp__tcc")
    rooted = name == "bash" and _sets_skill_root(line)
    dangerous = False  # read once, only where it decides or names the question
    if name == "bash" and gate in (GATE_NEVER, GATE_AUTO, GATE_FOREIGN):
        dangerous = _is_dangerous(line, read_roots, shell)
    if gate == GATE_NEVER:
        # `never` asks about nothing, and is never silent about what `auto` would have asked
        # (tcc#115) — the same line as on the Agent SDK side. A stranger `auto` would have asked.
        return Verdict(True, unasked=line if dangerous or stranger or rooted else "")
    ticked = frozenset(always_allowed)
    if tool in ticked or name in ticked:
        # The Arbiter, 2026-10-14: a «don't ask again» tick removes the question for an ordinary
        # command only — it never outranks «cannot be undone» (it did since 2026-09-11; a tick
        # on any Bash question then let `cd ~ && rm -rf *` through). The same on the SDK route.
        if name == "bash" and gate == GATE_WRITES:
            dangerous = _is_dangerous(line, read_roots, shell)
        allowed = not dangerous
    elif gate == GATE_AUTO:
        # "Don't ask" never meant "don't look" (HUB-028). This returned True before any look,
        # so on omp a delete passed silently while the menu told the Arbiter `auto` still asks
        # about what cannot be undone (review of tcc#115). The SDK adapter's narrow check, shared.
        # A name this table has no row for is not looked at by that check, so it asks.
        allowed = not (dangerous or stranger or rooted)
    elif name in ALWAYS_GATED_TOOLS:
        allowed = False
    elif name.startswith("mcp__tcc") or name in READ_ONLY_TOOLS:
        allowed = True
    elif name == "bash":
        # `foreign`: the skill writing its own namespace is the skill doing its job, and asking
        # about it teaches the Arbiter to click through the ones that matter. Danger first: a
        # line that also deletes the home is not the skill doing its job (`rm -rf process/ ~`).
        allowed = not rooted and (shell != SHELL_POWERSHELL and bash_is_read_only(line, read_roots)
                   or gate == GATE_FOREIGN and not dangerous and touches_only_skill_files(
                       line, shell=shell, project=read_roots[0] if read_roots else None,
                       skill=read_roots[1] if len(read_roots) > 1 else None))
    else:
        allowed = False
    if allowed:
        return Verdict(True)
    # What cannot be undone says so, whichever gate asked — under `auto` it is the only thing
    # that asks about a command — by the same key as the SDK side (review of tcc#115).
    if name == "bash" and gate == GATE_WRITES and not dangerous:
        dangerous = _is_dangerous(line, read_roots, shell)
    return Verdict(
        False,
        # The question is what it will change, not what it will run: a command line three
        # nested calls deep is not something anyone can read and judge, so they approve it
        # unread -- which is worse protection than no gate at all. Only a command has an
        # effect: an edit of `apply.py` changes the script, it does not write a ledger.
        tool=(effect_of(line) if name == "bash" else None) or tool,
        title=ALLOW_TITLE,
        title_args=allow_title_args(tool, shell),
        # Under `auto` the command alone, as it always was; elsewhere what omp sent with it
        # (its `Description:`) stays.
        detail=line if dangerous and gate == GATE_AUTO else detail,
        reason="gateIrreversible" if dangerous else "",
    )
