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
  every process on the machine (`ps`), stdin is not.

A vendored method older than these commands answers neither. Then `status()` is None and the
reachability question falls back to `critic_env`, exactly as before — so TCC works with the method
it has on either side of the vendoring, with no window in which a key goes unseen.

No value is logged, cached, or kept here: `set_key` hands it to the child and lets go.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import threading
from typing import Optional

from autosound_tcc.core import app_log, child, critic_env, vendor_loader

#: The providers the method stores keys for, in the order the screen lists them.
PROVIDERS = ("google", "anthropic", "openai")

_TIMEOUT_S = 20
_LOCK = threading.Lock()
#: `False` = not asked yet; `None` = asked, and the method cannot answer; a dict = its answer.
_STATUS: object = False


def script_path():
    """`autosound_ai.py` inside the vendored skill — the same file the reviewer runs."""
    return vendor_loader.REW_TOOL_DIR.parent / "scripts" / "autosound_ai.py"


def _run(args: list[str], *, stdin: Optional[str] = None) -> Optional[subprocess.CompletedProcess]:
    script = script_path()
    if not script.is_file():
        return None
    try:
        return subprocess.run(
            [child.script_interpreter(), str(script), *args],
            input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_TIMEOUT_S, env=vendor_loader.child_env(), **child.quiet())
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
    """`[{var, file, line}]` — keys still exported from a shell profile, as the method found them."""
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
    return proc.returncode == 0, said


def move_shell_line() -> str:
    """The shell line that runs the method's own `key move-shell` — which ASKS before it moves.

    For a terminal the Arbiter watches: the command is interactive on purpose, and running it is
    his to approve (the ticket: "never run it without the user's OK").
    """
    argv = [child.script_interpreter(), str(script_path()), "key", "move-shell"]
    if sys.platform.startswith("win"):
        return subprocess.list2cmdline(argv)
    return " ".join(shlex.quote(a) for a in argv)
