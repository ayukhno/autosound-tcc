"""Which terminal Windows hands a new console to — and how to put that back.

`core/child.py` gives the agent ONE console and hides it, so the shells `claude`'s Bash tool
starts inherit it instead of each opening a window. That fix has a precondition, and it is not
ours to assume: **it works only when the default terminal is the old conhost.**

Measured on Windows 11, 2026-09-11. Under Windows Terminal the console window belongs to
`WindowsTerminal.exe`, not to our child — enumerating windows by our pid returns `[]` and
`AttachConsole` is refused with error 5. There is nothing of ours to hide, which is also why
`STARTUPINFO`+`SW_HIDE` never worked. Under conhost the same window IS ours: it hides in about
250 ms and stays hidden after one re-hide.

**The undo matters more than the switch.** A setting an application changes on somebody's machine
and cannot put back is a setting it had no business changing, so this module keeps the previous
pair before writing, restores it on demand, and can write the whole thing out as a `.reg` file a
person can read before running. The restore is reachable three ways: the uninstall path, a Start
Menu entry, and that file.

Windows-only, and nothing here raises: a machine where the registry cannot be read is a machine
where TCC still opens, with the flash it always had.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, Optional

#: The key Windows keeps the default-terminal choice in. The subkey really is spelled with two
#: percent signs; it is a literal name, not a format string.
KEY = r"Console\%%Startup"

#: The two values that have to agree. Windows splits "who owns the console" from "who draws it",
#: and setting one without the other leaves a machine in a state neither UI shows.
VALUES = ("DelegationConsole", "DelegationTerminal")

#: The old console host — the only setting under which the agent's console can be hidden.
CONHOST = "{B23D10C0-E52E-411E-9D5B-C09FDF709C7D}"

#: What a machine ships with. On Windows 11 it resolves to Windows Terminal, but it is NOT the
#: same value, and putting the wrong one back on restore would be a change rather than an undo.
LET_WINDOWS_DECIDE = "{00000000-0000-0000-0000-000000000000}"

#: Windows Terminal, whose two halves carry different ids. Named as itself rather than lumped
#: into "not conhost", because it is the one value where the fix cannot work at all and the
#: question TCC asks says so.
WINDOWS_TERMINAL = "{2EACA947-7F5F-4CFA-BA87-8F7FBEEFBE69}"
WINDOWS_TERMINAL_GUIDS = frozenset({WINDOWS_TERMINAL, "{E12CFF52-A866-4C77-9A90-F570A7AA2C6B}"})


def _read_registry() -> dict:
    """Both values, as Windows currently has them. `{}` anywhere this does not apply."""
    if not sys.platform.startswith("win"):
        return {}
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            found = {}
            for name in VALUES:
                try:
                    found[name] = str(winreg.QueryValueEx(key, name)[0])
                except OSError:
                    pass
            return found
    except Exception:  # noqa: BLE001 — an absent key is an answer ("unknown"), not a failure
        return {}


def _write_registry(values: dict) -> None:
    if not sys.platform.startswith("win"):
        raise OSError("the default terminal is a Windows setting")
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def backup_path() -> Path:
    """Beside the other machine-level facts, not in a project: this is about this Windows install.

    Deliberately a plain file rather than QSettings — the uninstall path runs without a window,
    and a restore that needs the toolkit is a restore that cannot run when it is needed.
    """
    from autosound_tcc.core import model_overrides

    return model_overrides.config_dir() / "default-terminal-backup.json"


def _save(values: dict) -> None:
    path = backup_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2), encoding="utf-8")


def _load() -> dict:
    try:
        return dict(json.loads(backup_path().read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 — no backup is a state restore() handles, not an error
        return {}


def should_offer(
    *,
    on_windows: Optional[Callable[[], bool]] = None,
    state: Optional[Callable[[], str]] = None,
    already_asked: Optional[Callable[[], bool]] = None,
) -> bool:
    """Is this a machine where offering the switch would help, and have we not asked already?

    Four ways to be the wrong moment, and each is a real machine: not Windows at all; already on
    conhost, where the console is hidden and nothing flashes; asked once and told no, because a
    question re-asked every launch is not a question but a nag; and a setting we could not read,
    where offering would be guessing at somebody's system.

    `default` — "let Windows decide" — IS offered: it is not conhost, and on Windows 11 it
    resolves to Windows Terminal, so the flash is there.
    """
    on_windows = on_windows or (lambda: sys.platform.startswith("win"))
    state = state or current
    already_asked = already_asked or (lambda: False)
    try:
        if not on_windows() or already_asked():
            return False
        return state() in ("windows-terminal", "default")
    except Exception:  # noqa: BLE001 — a machine we cannot read is one we do not pester
        return False


def switched_by_us(*, exists: Optional[Callable[[], bool]] = None) -> bool:
    """Did TCC switch this machine, or did the person? The backup file is the only proof.

    It decides what the uninstall may touch. Putting back a setting TCC never changed would be a
    change of its own, made at the worst possible moment — while the application is leaving.
    """
    exists = exists or (lambda: backup_path().exists())
    try:
        return bool(exists())
    except Exception:  # noqa: BLE001 — unreadable counts as "not ours", which is the safe side
        return False


def current(*, read: Optional[Callable[[], dict]] = None) -> str:
    """`conhost`, `windows-terminal`, `default`, or `unknown`.

    `unknown` rather than a guess when the key cannot be read: a machine we cannot ask is not a
    machine where the fix is known to work, and the difference decides whether TCC offers.
    """
    read = read or _read_registry
    try:
        values = read() or {}
    except Exception:  # noqa: BLE001
        return "unknown"
    seen = [values.get(name) for name in VALUES]
    if not values or None in seen:
        return "unknown"
    if all(value == CONHOST for value in seen):
        return "conhost"
    if any(value in WINDOWS_TERMINAL_GUIDS for value in seen):
        return "windows-terminal"
    if all(value == LET_WINDOWS_DECIDE for value in seen):
        return "default"
    return "unknown"


def is_conhost(*, read: Optional[Callable[[], dict]] = None) -> bool:
    return current(read=read) == "conhost"


def set_conhost(
    *,
    read: Optional[Callable[[], dict]] = None,
    write: Optional[Callable[[dict], None]] = None,
    save: Optional[Callable[[dict], None]] = None,
) -> bool:
    """Switch to conhost, keeping the previous pair so it can be put back. True when it took."""
    read = read or _read_registry
    write = write or _write_registry
    save = save or _save
    try:
        previous = read() or {}
    except Exception:  # noqa: BLE001 — nothing to keep is still something we can switch from
        previous = {}
    try:
        save(dict(previous))  # BEFORE the write: the undo is the point of the whole module
        write({name: CONHOST for name in VALUES})
        return True
    except Exception:  # noqa: BLE001 — a refused write leaves the machine as it was
        return False


def restore(
    *,
    load: Optional[Callable[[], dict]] = None,
    write: Optional[Callable[[dict], None]] = None,
) -> bool:
    """Put back what was there before TCC switched. True when it took."""
    load = load or _load
    write = write or _write_registry
    try:
        previous = load() or {}
    except Exception:  # noqa: BLE001
        previous = {}
    values = {name: previous.get(name) or LET_WINDOWS_DECIDE for name in VALUES}
    try:
        write(values)
        return True
    except Exception:  # noqa: BLE001
        return False


def restore_file_text(previous: Optional[dict] = None) -> str:
    """The same undo as a `.reg` file. CRLF throughout, which is what `regedit` expects.

    Handed to the person as a file as well as a command on purpose: something they can open and
    read before running is a different kind of promise from an application saying "trust me".
    """
    previous = previous or {}
    values = {name: previous.get(name) or LET_WINDOWS_DECIDE for name in VALUES}
    lines = [
        "Windows Registry Editor Version 5.00",
        "",
        f"[HKEY_CURRENT_USER\\{KEY}]",
        *[f'"{name}"="{value}"' for name, value in values.items()],
    ]
    return "\r\n".join(lines) + "\r\n"


def write_restore_file(path: Optional[Path] = None) -> Optional[Path]:
    """Write the undo file next to the backup. Returns where it went, or None."""
    try:
        target = path or backup_path().with_name("restore-default-terminal.reg")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(restore_file_text(_load()), encoding="utf-8")
        return target
    except Exception:  # noqa: BLE001 — an undo we could not write is named, never pretended
        return None
