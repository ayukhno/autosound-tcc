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
import posixpath
import re
import shlex
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

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
_RUINOUS = frozenset({"mkfs", "fdisk", "shutdown", "reboot", "halt", "diskutil", "format"})
#: `mkfs.ext4`, `mkfs.vfat` — the family is spelled with a suffix, and matching the bare name
#: would let every real invocation through.
_RUINOUS_PREFIXES = ("mkfs.",)
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
    return _script_is_dangerous(command.strip(), depth=0)


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

    def is_empty(self) -> bool:
        return not (self.words or self.redirects or self.stdin or self.compound)


@dataclass
class _Heredoc:
    command: _Command
    delimiter: str
    quoted: bool
    strip_tabs: bool
    depth: int


def _script_is_dangerous(text: str, depth: int, inherited: Iterable[str] = ()) -> bool:
    """`inherited`: the names the line around this script has already made unknown. A script body —
    `bash -c '…'`, a heredoc fed to a shell, `trap`, `alias` — runs with the variables of the line
    that holds it, so `HOME='…' bash -c '$HOME/x'` is `HOME='…'; $HOME/x` (review of tcc#128)."""
    try:
        commands: list[_Command] = []
        _Reader(text, commands, depth).read()
        tainted = _tainted(commands, inherited)
        return any(_command_is_dangerous(command, tainted, depth) for command in commands)
    except (_Unreadable, RecursionError):
        return True  # unknown is not safe


class _Reader:
    r"""Takes a command line apart the way the shell would — close enough to judge it.

    Not a shell. It knows quoting, by the shell's own rule: a backslash escapes inside double quotes
    and not inside single ones, which is what keeps `grep "a\|b"` one word (2026-09-11) and a
    markdown backtick inside `'…'` text (2026-09-19). It knows the separators (`;`, `&&`, `||`, `|`,
    `&`, a newline), comments, `$( … )`, backticks, `<( … )`, `${ … }`, `( … )`, redirections and
    heredocs. Every simple command it meets — at the top, inside a substitution, in a loop body —
    lands in `commands`. Anything else raises `_Unreadable`, and unreadable is dangerous.
    """

    def __init__(self, text: str, commands: list[_Command], depth: int) -> None:
        if depth > _MAX_DEPTH:
            raise _Unreadable
        self.text = text
        self.i = 0
        self.commands = commands
        self.depth = depth
        self.heredocs: list[_Heredoc] = []

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
        command = _Command()

        def end_command() -> None:
            nonlocal command
            if not command.is_empty():
                pipeline.append(command)
            command = _Command()

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
                self._list(")", depth + 1)
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
        _Reader("".join(body), self.commands, depth + 1).read()
        word.text += text[start:self.i]
        word.started = word.dynamic = word.output = True

    def _dollar(self, word: _Word, depth: int, in_double: bool) -> None:
        text = self.text
        start, nxt = self.i, self._peek(1)
        word.started = True
        if nxt == "(":
            self.i += 2
            self._list(")", depth + 1)  # `$((…))` too: an arithmetic body reads as a subshell
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
        self._list(")", depth + 1)
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
                _Reader(body.text, self.commands, depth + 1).expand(body)
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
                    if words[1].text == "HOME" or any(_runs(word, tainted) for word in words[2:]):
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
    if name in _UNREAD_KEYWORDS or name in ("sudo", "eval"):
        return True  # sudo: asking for the whole machine is the definition of worth a question
    if name in _RUINOUS or name.startswith(_RUINOUS_PREFIXES):
        return True
    if name in ("source", "."):
        # It runs a file the line names — unless the line does not name it: `. <(curl …)`, or
        # names stdin, where what runs is the heredoc or the pipe.
        if arguments and _is_stdin_path(arguments[0].text):
            return _stdin_script_is_dangerous(command, tainted, depth)
        return any(argument.dynamic or _runs(argument, tainted) for argument in arguments)
    if name in ("trap", "alias"):
        return _code_arguments_are_dangerous(name, arguments, tainted, depth)
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
    if name == "cmd":
        return _cmd_is_dangerous(arguments, command, tainted, depth)
    if name in ("powershell", "pwsh"):
        return _powershell_is_dangerous(arguments, command, tainted, depth)
    if name in ("remove-item", "ri"):
        return _remove_item_is_dangerous(arguments, command.piped)
    if name in _INTERPRETERS or name.startswith("python"):
        return _interpreter_is_dangerous(name, arguments, command, tainted)
    if name in ("rm", "find", "dd", "chmod") and any(_runs(a, tainted) for a in arguments):
        return True  # its arguments decide, and one is another command's output: `rm $(echo -rf /)`
    if name == "rm":
        return _rm_is_dangerous(arguments)
    if name in _WINDOWS_DELETES:
        # cmd's `rd /s`, and PowerShell's aliases of Remove-Item: `rd -Recurse ~` (Ruling 41).
        return _reach_is_dangerous(arguments, _is_windows_switch,
                                   lambda text: "s" in _switch_letters(text), bare=False
                                   ) or _remove_item_is_dangerous(arguments, command.piped)
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
                                   bare=False)
    if name == "git":
        return _git_is_dangerous(arguments, tainted)
    if name in _FETCHERS and command.piped:
        return True
    return False


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
    return not any(_is_wide_target(root) for root in roots)


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


def _rm_is_dangerous(arguments: list[_Word]) -> bool:
    """`rm` is judged by its arguments rather than by its name: `rm build/tmp.json` is a Tuesday.
    With no target it is fed by `xargs` or a pipe, and deletes what is not on the line."""
    return _reach_is_dangerous(arguments, lambda text: text.startswith("-"), _is_recursive_flag,
                               bare=True)


def _reach_is_dangerous(arguments: list[_Word], is_option: Callable[[str], bool],
                        is_recursive: Callable[[str], bool], bare: bool) -> bool:
    """A recursive delete (`rm -r`, `rd /s`) or `chmod -R`, judged by what it reaches.

    A target the line does not spell — `"$f"` in `for f in *`, `$(cat list)` — is unknown, and a
    recursive delete of something unknown is the case this check exists for; so is one of a whole
    home or system folder (`_is_wide_target`).

    And an OPTION the line does not spell counts as the recursive one (tcc#128): `x=-rf; rm $x ~` is
    `rm -rf ~`, and xargs's appended word may be `-R`. An unquoted one (or `"$@"`) may split into
    several words, the flag and the target at once (`x='-rf ~'; rm $x`); a quoted one is one word,
    either the flag or the target, so it takes another unknown or wide word beside it to be both.
    `rm "$tmp"` stays a delete of one file.
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
    if any(option.dynamic or is_recursive(option.text) for option in options):
        if not operands:
            return bare
        return any(operand.dynamic or _is_wide_target(operand.text) for operand in operands)
    if not could_be_options:
        return False
    return (any(_may_be_several_words(word) for word in could_be_options)
            or sum(operand.dynamic for operand in operands) > 1
            or any(not operand.dynamic and _is_wide_target(operand.text) for operand in operands))


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
                                          depth + 1)
    return command.piped or bool(command.stdin) or any(
        operator in ("<", "<>", "<&") for operator, _ in command.redirects)


def _cmd_line_is_dangerous(line: str, tainted: set[str], depth: int) -> bool:
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
        if _command_name(words[0].text) in ("if", "else", "do"):
            # cmd runs the command after `if exist x`, `if not … ==…`, `else` and `for … do`; where
            # the condition ends is cmd's to say, so every tail is read as that command (Ruling 41).
            readings.extend(words[at:] for at in range(1, len(words)))
        if any(_words_are_dangerous(reading, _Command(piped=in_pipe), tainted, depth)
               for reading in readings):
            return True
    return False


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
    return any(_powershell_line_is_dangerous(" ".join(word.text for word in line[start:]), depth + 1)
               for start in range(len(line)))


def _powershell_line_is_dangerous(line: str, depth: int) -> bool:
    """A PowerShell line, read closely enough to judge Remove-Item: `;`, `|`, `&`, braces and
    parentheses part statements, `'…'` is literal, `"…"` and a backtick escape, `$HOME` and
    `$env:USERPROFILE` are the home, any other `$…` is a value the line does not spell. A statement
    that is not PowerShell's own is judged by the shell rules (`cmd /c …`, `git push --force`)."""
    if depth > _MAX_DEPTH:
        return True
    statements: list[list[_Word]] = [[]]
    piped: list[bool] = [False]
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
            called.append(ch == "&" and "&" not in (line[i - 1:i], line[i + 1:i + 2]))
        else:
            word = word or _Word(started=True)
            word.text += ch
        i += 1
    if quote:
        return True  # a quote that never closes: unknown is not safe
    finish()
    return any(_powershell_statement_is_dangerous(words, in_pipe, call, depth)
               for words, in_pipe, call in zip(statements, piped, called) if words)


def _powershell_statement_is_dangerous(words: list[_Word], piped: bool, called: bool,
                                       depth: int) -> bool:
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
    if name in _PS_REMOVERS:
        return _remove_item_is_dangerous(words[1:], piped)
    return _words_are_dangerous(words, _Command(piped=piped), set(), depth)


def _remove_item_is_dangerous(arguments: list[_Word], piped: bool) -> bool:
    """PowerShell's `Remove-Item -Recurse` (`-r`, `-rec`, `-Recurse:$true`, any case, any order) on
    a wide target: a drive root, the home, `C:\\Users`, a climb, `*` — or one it does not spell, or
    none when a pipe feeds it (`gci C:\\ | Remove-Item -Recurse`). Every word that is not a
    parameter is taken as a target, and a `-Path:x` value too: a parameter's value read as a target
    can only add a question, never hide one (Ruling 41)."""
    recurse = False
    targets: list[_Word] = []
    for word in arguments:
        text = word.text
        if text.startswith("-") and len(text) > 1 and not word.quoted:
            name, has_value, value = text[1:].partition(":")
            if name and "recurse".startswith(name.lower()):
                recurse |= value.lower() != "$false"
            elif has_value and value:
                targets.append(_Word(text=value, started=True, dynamic="$" in value))
            continue
        targets.append(word)
    splat = any(target.text.startswith("@") for target in targets)  # `@args` may hold -Recurse
    if not (recurse or splat):
        return False
    if not targets:
        return piped
    return any(target.dynamic or _is_wide_target(target.text)
               or posixpath.normpath(target.text.replace("\\", "/")) in ("*", "*.*")
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
        return _script_is_dangerous(operands[0].text, depth + 1, tainted)
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
        if body.dynamic or _script_is_dangerous(body.text, depth + 1, tainted):
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
                                  depth: int) -> bool:
    """`trap 'rm -rf ~' EXIT` and `alias x='rm -rf ~'` hold a script for later — it is read now."""
    for argument in arguments:
        if name == "trap" and argument.text in ("-p", "-l", "--"):
            continue
        code = argument.text.partition("=")[2] if name == "alias" else argument.text
        if argument.dynamic or _script_is_dangerous(code, depth + 1, tainted):
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
