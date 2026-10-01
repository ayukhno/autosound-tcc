"""The reviewer's key, as the METHOD reports it (hub #197, SKL-051).

The method moves the key out of shell profiles and into the OS keystore — the macOS Keychain, or on
Windows a file encrypted with the user's login (DPAPI) — with the 0600 `critic-env` kept as the
fallback (the user's decision, W-2, 2026-09-23). TCC cannot read a keystore, and must not try:
`critic_env` mirrors the FILE only, and a mirror of a store it cannot read is SKL-024's blind
footer all over again — "unreachable" while the call goes through, the start-of-session probe
skipped, and the model told to hand out a clipboard package.

So TCC asks the one reader of all three stores, the method's own script:

* `autosound_ai.py key status --json` says where each provider's key is used from — keystore,
  file, environment, or nowhere — and never prints a value;
* `autosound_ai.py key set <provider>` stores a key, which it reads from STDIN: argv is visible to
  every process on the machine (`ps`), stdin is not;
* `autosound_ai.py key move-shell` moves an exported key into the store, reading it where it is
  exported — no value from TCC (tcc#117); `key move-shell <provider> --drop` (v3.0.65, hub #230)
  removes one provider's exported copy without storing it, for a key the keystore already holds.

A vendored method older than these commands answers neither. Then `status()` is None and the
reachability question falls back to `critic_env`, exactly as before — so TCC works with the method
it has on either side of the vendoring, with no window in which a key goes unseen.

No value is logged, cached, or kept here: `set_key` hands it to the child and lets go — and
nothing holds a pasted key across a question either, now that the method can drop a copy without
storing it (hub #230).
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import threading
from typing import Optional

from autosound_tcc.core import app_log, availability, child, critic_env, vendor_loader

#: The providers the method stores keys for, in the order the screen lists them.
PROVIDERS = ("google", "anthropic", "openai")

_TIMEOUT_S = 20
_LOCK = threading.Lock()
#: `False` = not asked yet; `None` = asked, and the method cannot answer; a dict = its answer.
_STATUS: object = False
#: `drops_exports`' answer and the script file it was asked of — `((path, mtime, size), bool)` —
#: or None before the first question.
_DROPS: Optional[tuple[tuple, bool]] = None
#: The method's own words for «no export of this provider», ending its one honest exit 1 of
#: `move-shell <provider> --drop --yes` (`· GEMINI_API_KEY у профілях оболонки не знайдено`). An
#: exit 1 without them is Python's own: an exception the method did not catch.
_NOTHING_FOUND = "у профілях оболонки не знайдено"
#: What `drop_export` makes of the method's answer.
DROPPED, NOTHING, NOT_DROPPED = "dropped", "nothing", "not_dropped"


def script_path():
    """`autosound_ai.py` inside the vendored skill — the same file the reviewer runs."""
    return vendor_loader.REW_TOOL_DIR.parent / "scripts" / "autosound_ai.py"


def _run(args: list[str], *, stdin: Optional[str] = None) -> Optional[subprocess.CompletedProcess]:
    script = script_path()
    if not script.is_file():
        return None
    quiet = child.quiet()
    if stdin is not None:
        # `quiet()` closes the child's stdin, and `input=` needs it open: the key goes there.
        quiet.pop("stdin", None)
    try:
        return subprocess.run(
            [child.script_interpreter(), str(script), *args],
            input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_TIMEOUT_S, env=vendor_loader.child_env(), **quiet)
    except (OSError, subprocess.SubprocessError) as exc:
        # The exception names the command, never the input: a key cannot reach the log this way.
        app_log.logger().info("reviewer key: %s failed: %s", " ".join(args[:2]), type(exc).__name__)
        return None


def _ask() -> Optional[dict]:
    proc = _run(["key", "status", "--json"])
    if proc is None or proc.returncode != 0:
        return None
    try:
        answer = json.loads(proc.stdout)
    except ValueError:
        return None
    return answer if isinstance(answer, dict) and isinstance(answer.get("providers"), dict) else None


def status(*, refresh: bool = False) -> Optional[dict]:
    """The method's `key status --json`, or None when the vendored method cannot answer it.

    Asked once and kept: a picker asks per model on every repaint, and where a key lives changes
    when somebody stores or moves one — `set_key` and the key screen drop the answer then.
    """
    global _STATUS
    with _LOCK:
        if refresh or _STATUS is False:
            _STATUS = _ask()
        return _STATUS if isinstance(_STATUS, dict) else None


def prefetch() -> None:
    """Ask in the background, so the first repaint that needs the answer does not wait for it."""
    threading.Thread(target=status, name="reviewer-key-status", daemon=True).start()


def forget() -> None:
    global _STATUS
    with _LOCK:
        _STATUS = False


def has_key(var: str) -> bool:
    """Is a key for `var` (e.g. `GEMINI_API_KEY`) used by the reviewer — from any store.

    The method's answer when it has one: `used` is `keystore`, `file`, `env` or `none`, and a
    `none` includes a file that deliberately blanks the key to force the CLI route. Without it,
    the environment and the machine file, as `critic_env` has always read them.
    """
    answer = status()
    if answer is not None:
        for entry in answer.get("providers", {}).values():
            if isinstance(entry, dict) and entry.get("var") == var:
                return entry.get("used", "none") != "none"
    return critic_env.has_key(var)


def shell_exports() -> list[dict]:
    """`[{var, file, line}]` — keys still exported from a shell profile, as the method found them.

    On Windows also the user's environment variables: `file` is `HKCU\\Environment` and `line` is
    None, the method's own mark for the registry (finding 125, tcc#117)."""
    answer = status()
    exports = answer.get("shell_exports") if answer else None
    return [e for e in exports if isinstance(e, dict)] if isinstance(exports, list) else []


def set_key(provider: str, value: str) -> tuple[bool, str]:
    """Store `value` for `provider` through the method. Returns (stored, what the method said).

    The value goes to the child's stdin, one line, and nowhere else. Exit 0 means stored and its
    one line of stdout says where; exit 2 means refused, with the reason on stderr.
    """
    if provider not in PROVIDERS:
        return False, f"unknown provider {provider!r}"
    proc = _run(["key", "set", provider], stdin=value.strip() + "\n")
    forget()
    if proc is None:
        return False, ""
    said = (proc.stdout if proc.returncode == 0 else proc.stderr).strip()
    app_log.logger().info("reviewer key: set %s -> exit %s", provider, proc.returncode)
    if proc.returncode == 0:
        # What refused for want of a key may answer now: the picker read «API · … · відмова»
        # after the save until ↻ (finding 128, tcc#117). Only the key's own route.
        availability.forget_refusals("api")
    return proc.returncode == 0, said


def drops_exports() -> bool:
    """Does the method here take `key move-shell <provider> --drop` (v3.0.65, hub #230)?

    Asked of its usage, not of its version, as `process_writer._refuse_if_too_old` does: `key`
    with a word it does not know prints the usage line and exits 2 on every method that has `key`,
    and touches nothing. It has to be asked: v3.0.64 reads `move-shell google --drop --yes` as
    `move-shell --yes`, and moves AND STORES every export there is. Kept for the script file it
    was asked of; an update replaces the file, and the next question asks again.
    """
    global _DROPS
    script = script_path()
    try:
        stat = script.stat()
    except OSError:
        return False
    seen = (str(script), stat.st_mtime_ns, stat.st_size)
    if _DROPS is None or _DROPS[0] != seen:
        proc = _run(["key", "help"])
        if proc is None:
            # No answer is not «no `--drop`»: kept, it would say «update the method» to a method
            # that has it until the file changed. Asked again next time.
            return False
        _DROPS = (seen, "--drop" in f"{proc.stdout or ''}\n{proc.stderr or ''}")
    return _DROPS[1]


def drop_export(provider: str) -> tuple[Optional[str], str]:
    """The method's `key move-shell <provider> --drop --yes`: `provider`'s exported copy — its
    profile lines, and on Windows the user environment's value — removed WITHOUT storing it, the
    OS keystore holding the key already (finding 127, hub #230). (what happened, its words); what
    happened is None when the method gave no answer.

    Read from the exit code (hub #230): 0 `DROPPED`; 1 `NOTHING` — but only beside the method's
    own «не знайдено» and no traceback, because Python exits 1 on an exception the method did not
    catch (a profile it may not write, the registry); 3 refused or failed (the keystore does not
    hold the key — the export is then the only copy — or a line sets it by an expression). That,
    a crash, a usage error after the probe said yes, a signal: `NOT_DROPPED`. Of a traceback only
    its last line goes into the words — the exception, not the method's source.

    Only after the window asked and the Arbiter said yes: `--yes` skips the method's own prompt,
    the same question a second time. Only the provider goes on argv, nothing on stdin; and never
    to a method without the form (`drops_exports`).
    """
    if provider not in PROVIDERS:
        return NOT_DROPPED, f"unknown provider {provider!r}"
    proc = _run(["key", "move-shell", provider, "--drop", "--yes"])
    forget()
    if proc is None:
        return None, ""
    app_log.logger().info("reviewer key: move-shell %s --drop -> exit %s", provider,
                          proc.returncode)
    out, err = (proc.stdout or "").strip(), (proc.stderr or "").strip()
    crashed = "Traceback (most recent call last)" in err
    if crashed:
        err = err.splitlines()[-1].strip()
    words = "\n".join(part for part in (out, err) if part)
    if proc.returncode == 0:
        return DROPPED, words
    if proc.returncode == 1 and _NOTHING_FOUND in out and not crashed:
        return NOTHING, words
    return NOT_DROPPED, words


def move_shell_line() -> str:
    """The shell line that runs the method's own `key move-shell` — which ASKS before it moves.

    For a terminal the Arbiter watches: the command is interactive on purpose, and running it is
    his to approve (the ticket: "never run it without the user's OK").
    """
    argv = [child.script_interpreter(), str(script_path()), "key", "move-shell"]
    if sys.platform.startswith("win"):
        return subprocess.list2cmdline(argv)
    return " ".join(shlex.quote(a) for a in argv)
