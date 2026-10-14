"""Codex on this machine: where it is, which version, whether it is signed in, which models it
offers, and the argv pieces a Codex session is started with (W-10, tcc#181, task 4).

Qt-free. Three costs, kept apart on purpose:

* `find()` — stat calls (and one small read for a script's first line), cached; safe on the GUI
  thread, where the picker asks per row. `forget()` is ↻.
* `version(found)` — runs `codex --version`, once per (path, mtime). **Worker thread only.**
* `probe()` — one `codex app-server`: `account/read`, then `model/list` page by page. **Worker
  thread only**, at the start's read after agy and the SDK, and on ↻ — never on window activation
  (the agy flash: a child per activation is a console per alt-tab on Windows). `signed_in()` and
  `models()` read what it left and never spawn.

The Arbiter's rule: an installed Codex is used. A version TCC cannot read is used too, with a
warning in the log; only one known to be older than `MIN_VERSION` is not — the blocker (tasks 8/9)
offers TCC's own copy then.
"""

from __future__ import annotations

import asyncio
import os
import platform as _platform
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from autosound_tcc.core import app_log, child, codex_rpc

#: The oldest Codex whose app-server TCC speaks to: the protocol recorded in the fixtures.
MIN_VERSION = (0, 162, 0)
#: The version TCC installs as its own copy (task 9, `codex_install`): the wheel
#: `openai-codex-cli-bin==PIN`.
PIN = "0.162.1"

#: Where `find()` found it.
SOURCE_PATH = "path"          # on PATH as TCC was started
SOURCE_FOLDER = "folder"      # a place a Dock/Start-menu app's PATH misses (`dock_folders`)
SOURCE_TCC = "tcc"            # TCC's own copy (`tcc_copy_path`)

#: `codex --version` and the probe: long enough for a cold start, short enough not to hold a read.
VERSION_TIMEOUT_S = 10.0
PROBE_TIMEOUT_S = 15.0
#: Pages of `model/list` read at most; 0.162.1 answers in one.
MAX_PAGES = 10
PAGE_LIMIT = 100

_VERSION_RE = re.compile(r"codex-cli\s+(\d+)\.(\d+)\.(\d+)")
#: An MCP server name `-c mcp_servers.<name>.enabled=false` can carry as a bare TOML key.
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class Found:
    """A usable Codex binary: the native executable itself, never a shim. `shim` names the npm
    shim it was resolved from, "" when it was found directly."""

    path: str
    source: str
    shim: str = ""

    @property
    def folder(self) -> str:
        return str(Path(self.path).parent)


@dataclass(frozen=True)
class Probe:
    """What one `codex app-server` said: the login (True / False / None = could not tell), the
    models it lists (the raw `model/list` entries, hidden ones left out), and — when it gave no
    list — why, in a line for the rows that stand in for it."""

    signed_in: Optional[bool] = None
    models: tuple = ()
    why: str = ""
    asked: bool = False


# --- where -----------------------------------------------------------------------------------------

def _is_windows(windows: Optional[bool]) -> bool:
    return sys.platform.startswith("win") if windows is None else windows


#: Homebrew's two prefixes (Apple silicon, Intel): Codex's cask and npm's global bin land there.
SYSTEM_FOLDERS: tuple[Path, ...] = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))


def dock_folders(*, home: Optional[Path] = None, environ: Optional[Mapping[str, str]] = None,
                 windows: Optional[bool] = None) -> list[Path]:
    """The places Codex is installed into that an app started from the Dock (or the Start menu)
    does not have on its PATH."""
    home = Path(home) if home is not None else Path.home()
    environ = os.environ if environ is None else environ
    if _is_windows(windows):
        appdata = environ.get("APPDATA")
        return [Path(appdata) / "npm"] if appdata else []
    return [*SYSTEM_FOLDERS, home / ".local" / "bin", home / ".npm-global" / "bin"]


def tcc_copy_path(*, home: Optional[Path] = None, environ: Optional[Mapping[str, str]] = None,
                  windows: Optional[bool] = None, pin: str = PIN) -> Path:
    """Where TCC's own Codex lives once task 9 installed it: the wheel's `codex_cli_bin/` folder,
    unpacked whole (it is a folder, not one file — «Learned in task 1»), under TCC's own data
    folder and outside the uv tool environment, so a TCC update does not wipe it."""
    home = Path(home) if home is not None else Path.home()
    environ = os.environ if environ is None else environ
    if _is_windows(windows):
        base = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return base / "autosound-tcc" / "codex" / pin / "codex_cli_bin" / "bin" / "codex.exe"
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    return base / "autosound-tcc" / "codex" / pin / "codex_cli_bin" / "bin" / "codex"


def _arch_words() -> tuple[str, ...]:
    machine = _platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return ("aarch64", "arm64")
    return ("x86_64", "x64", "amd64")


def _first_line(path: Path) -> bytes:
    try:
        with path.open("rb") as fh:
            return fh.read(256).split(b"\n", 1)[0]
    except OSError:
        return b""


def _native_in(node_modules: Path, windows: bool) -> Optional[Path]:
    """The native Codex an npm install bundles under `node_modules/@openai/codex*/**`: the
    platform package's `vendor/<target>/codex/codex(.exe)`. The machine's own architecture first."""
    scope = node_modules / "@openai"
    if not scope.is_dir():
        return None
    name = "codex.exe" if windows else "codex"
    found: list[Path] = []
    try:
        for package in sorted(scope.glob("codex*")):
            for candidate in package.rglob(name):
                if candidate.is_file() and (windows or not _first_line(candidate).startswith(b"#!")):
                    found.append(candidate)
    except OSError:
        return None
    if not found:
        return None
    words = _arch_words()
    mine = [p for p in found if any(w in str(p).lower() for w in words)]
    return (mine or found)[0]


def _node_modules_for(shim: Path, windows: bool) -> list[Path]:
    """Where a shim's package lives: beside it on Windows (`%APPDATA%\\npm\\node_modules`); on
    macOS up the shim's link (`…/lib/node_modules/@openai/codex/bin/codex.js`), or the prefix's
    `lib/node_modules` for a shim that is a copy rather than a link."""
    out = [shim.parent / "node_modules"]
    if not windows:
        try:
            real = Path(os.path.realpath(shim))
        except OSError:
            real = shim
        out += [p for p in real.parents if p.name == "node_modules"][:1]
        out.append(shim.parent.parent / "lib" / "node_modules")
    return out


def _resolve_shim(shim: Path, windows: bool) -> Optional[Path]:
    for node_modules in _node_modules_for(shim, windows):
        native = _native_in(node_modules, windows)
        if native is not None:
            return native
    return None


def _usable_in(folder: Path, windows: bool) -> Optional[tuple[Path, str]]:
    """`(binary, shim)` for a Codex in `folder`, or None. On Windows only a `.exe` counts: an npm
    `.cmd`/`.ps1`/sh shim resolves to the native `codex.exe` beside it or is not usable — TCC never
    starts Codex through a shell. On macOS a node-script shim resolves the same way (an app started
    from the Dock has no `node`)."""
    if windows:
        exe = folder / "codex.exe"
        if exe.is_file():
            return exe, ""
        for name in ("codex.cmd", "codex.ps1", "codex"):
            shim = folder / name
            if shim.is_file():
                native = _resolve_shim(shim, True)
                return (native, str(shim)) if native is not None else None
        return None
    binary = folder / "codex"
    if not (binary.is_file() and os.access(binary, os.X_OK)):
        return None
    line = _first_line(binary)
    if line.startswith(b"#!"):
        native = _resolve_shim(binary, False)
        if native is not None:
            return native, str(binary)
        if b"node" in line:
            return None  # a node script with no native binary beside it: a Dock app cannot run it
    return binary, ""


_lock = threading.RLock()
_FOUND: Optional[Found] = None
_LOOKED = False


def find(*, environ: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
         windows: Optional[bool] = None) -> Optional[Found]:
    """Where this machine's Codex is: PATH, then the places a Dock-started app misses, then TCC's
    own copy. Stat calls only; cached until `forget()` (pass any argument to look afresh, uncached
    — the tests' door)."""
    global _FOUND, _LOOKED
    fresh = environ is not None or home is not None or windows is not None
    with _lock:
        if _LOOKED and not fresh:
            return _FOUND
    win = _is_windows(windows)
    env = os.environ if environ is None else environ
    path_dirs = [Path(p) for p in (env.get("PATH") or "").split(";" if win else os.pathsep) if p]
    found: Optional[Found] = None
    for source, folders in ((SOURCE_PATH, path_dirs),
                            (SOURCE_FOLDER, dock_folders(home=home, environ=env, windows=win))):
        for folder in folders:
            hit = _usable_in(folder, win)
            if hit is not None:
                found = Found(str(hit[0]), source, hit[1])
                break
        if found is not None:
            break
    if found is None:
        own = tcc_copy_path(home=home, environ=env, windows=win)
        if own.is_file() and (win or os.access(own, os.X_OK)):
            found = Found(str(own), SOURCE_TCC)
    if not fresh:
        with _lock:
            _FOUND, _LOOKED = found, True
    return found


def forget() -> None:
    """↻: the next `find()` looks again, and the next probe asks again."""
    global _FOUND, _LOOKED
    with _lock:
        _FOUND, _LOOKED = None, False


# --- version ---------------------------------------------------------------------------------------

#: (path, mtime) -> the version read, None when it could not be read.
_VERSIONS: dict[tuple[str, float], Optional[tuple]] = {}


def _stamp(found: Found) -> Optional[tuple[str, float]]:
    try:
        return found.path, os.stat(found.path).st_mtime
    except OSError:
        return None


def parse_version(text: str) -> Optional[tuple]:
    match = _VERSION_RE.search(text or "")
    return tuple(int(part) for part in match.groups()) if match else None


def version(found: Found) -> Optional[tuple]:
    """`codex --version` as `(X, Y, Z)`, once per (path, mtime); None when it cannot be read —
    then Codex is used anyway and the log says so. **Worker thread only.**"""
    stamp = _stamp(found)
    with _lock:
        if stamp is not None and stamp in _VERSIONS:
            return _VERSIONS[stamp]
    try:
        proc = child.run_bounded([found.path, "--version"], timeout=VERSION_TIMEOUT_S, text=True,
                                 encoding="utf-8", errors="replace", **child.quiet())
        said = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    except (OSError, subprocess.SubprocessError) as exc:
        said = str(exc)
    read = parse_version(said)
    if read is None:
        app_log.logger().warning("codex: the version of %s could not be read (%s); used anyway",
                                 found.path, said.strip()[:200])
    with _lock:
        if stamp is not None:
            _VERSIONS[stamp] = read
    return read


def too_old(found: Optional[Found]) -> bool:
    """Known to be older than `MIN_VERSION` — from the cache, never by running anything."""
    if found is None:
        return False
    stamp = _stamp(found)
    with _lock:
        read = _VERSIONS.get(stamp) if stamp is not None else None
    return read is not None and read < MIN_VERSION


def usable() -> Optional[Found]:
    """`find()`, unless the version already read is too old. No subprocess."""
    found = find()
    return None if found is None or too_old(found) else found


def version_text(read: Optional[tuple]) -> str:
    return ".".join(str(part) for part in read) if read else "unknown"


# --- probe -----------------------------------------------------------------------------------------

_PROBE = Probe()


def signed_in() -> Optional[bool]:
    """Codex's login as last probed: True, False, None (not asked, or could not tell). Never runs
    anything — the pickers read it on the GUI thread."""
    with _lock:
        return _PROBE.signed_in


def models() -> tuple:
    """The `model/list` entries the last probe read (hidden ones left out); () when none."""
    with _lock:
        return _PROBE.models


def last_probe() -> Probe:
    with _lock:
        return _PROBE


def supported_efforts(model: str) -> tuple[str, ...]:
    """The reasoning efforts Codex says `model` takes, from the last probe; () when not known."""
    return efforts_in(models(), model)


def efforts_in(entries, model: str) -> tuple[str, ...]:
    """The reasoning efforts `model`'s entry in a `model/list` page offers; () when it is not
    there. Pure: the session reads its own app-server's list with it (task 6)."""
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        if entry.get("model") == model or entry.get("id") == model:
            return tuple(str(item.get("reasoningEffort")) for item in
                         entry.get("supportedReasoningEfforts") or []
                         if isinstance(item, dict) and item.get("reasoningEffort"))
    return ()


def _signed_in_from(reply: Any) -> Optional[bool]:
    """`account/read`: an account is a login; none, where OpenAI auth is required, is signed out;
    an error or an answer of another shape is «could not tell»."""
    if not isinstance(reply, dict) or "account" not in reply:
        return None
    if reply.get("account"):
        return True
    if reply.get("requiresOpenaiAuth") is False:
        return True  # a provider that needs no OpenAI login
    return False


async def _ask(binary: str, timeout: float) -> tuple[Any, list, str]:
    """One app-server: `account/read`, then `model/list` with its cursor until the last page.
    `(account reply, entries, why)` — a reply is a dict or the `RpcError`; `why` is "" when the
    list was read. `ask_blocking` takes a fixed list of calls, and the cursor of a page is only
    known from the one before it, so this holds the server itself (`codex_rpc.AppServer`)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    server = codex_rpc.AppServer([binary, "app-server"], spawn_kwargs=child.flags())

    def left() -> float:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(f"no answer in {timeout:g} s")
        return remaining

    entries: list = []
    try:
        await server.open(timeout=left())
        try:
            account: Any = await server.request("account/read", {}, timeout=left())
        except codex_rpc.RpcError as exc:
            account = exc
        cursor = None
        for _page in range(MAX_PAGES):
            params: dict = {"limit": PAGE_LIMIT}
            if cursor:
                params["cursor"] = cursor
            try:
                page = await server.request("model/list", params, timeout=left())
            except codex_rpc.RpcError as exc:
                return account, entries, f"codex app-server: {exc.message}"
            for entry in page.get("data") or []:
                if isinstance(entry, dict) and not entry.get("hidden") and (
                        entry.get("model") or entry.get("id")):
                    entries.append(entry)
            cursor = page.get("nextCursor")
            if not cursor:
                break
        return account, entries, "" if entries else "codex app-server listed no models"
    finally:
        await server.close(grace=child.REAP_TIMEOUT_S)


def probe(*, force: bool = False) -> Probe:
    """Ask Codex once — its login and its models — and remember the answer (`signed_in()`,
    `models()`). **Worker thread only.** Again only with `force` (↻)."""
    global _PROBE
    with _lock:
        if _PROBE.asked and not force:
            return _PROBE
    found = find()
    if found is None:
        result = Probe(asked=True)
    else:
        read = version(found)
        if read is not None and read < MIN_VERSION:
            result = Probe(asked=True, why=(f"Codex {version_text(read)} is older than "
                                            f"{version_text(MIN_VERSION)}, the oldest TCC speaks to"))
        else:
            result = _run_probe(found)
    with _lock:
        _PROBE = result
    return result


def _run_probe(found: Found) -> Probe:
    try:
        account, entries, why = asyncio.run(_ask(found.path, PROBE_TIMEOUT_S))
    except TimeoutError:
        return Probe(asked=True, why=f"codex app-server gave no answer in {int(PROBE_TIMEOUT_S)} s")
    except (codex_rpc.ConnectionLost, OSError) as exc:
        return Probe(asked=True, why=f"codex app-server: {exc}")
    return Probe(signed_in=_signed_in_from(account), models=tuple(entries), why=why, asked=True)


def reset() -> None:
    """Back to a fresh launch. For tests."""
    global _PROBE
    forget()
    with _lock:
        _PROBE = Probe()
        _VERSIONS.clear()


# --- argv pieces (task 6) --------------------------------------------------------------------------

#: The user's own Codex extras, off in TCC's sessions (the Arbiter: TCC's sessions run TCC's tools).
OFF_FEATURES: tuple[str, ...] = (
    "plugins", "apps", "hooks", "browser_use", "computer_use", "in_app_browser",
    "image_generation", "multi_agent", "goals", "tool_suggest", "memories", "remote_plugin",
)
#: Enabled in a recorded `config/read` and left on: they add nothing the session would run.
HARMLESS_FEATURES: tuple[str, ...] = ("api_key_model_discovery", "auth_elicitation", "mentions_v2")
#: The environment variable that carries TCC's MCP token; no shell Codex starts sees it.
TOKEN_ENV = "TCC_MCP_TOKEN"


def _c(key: str, value: str) -> list[str]:
    return ["-c", f"{key}={value}"]


def _toml_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def tcc_tool_args(url: str, *, timeout_sec: int) -> list[str]:
    """TCC's MCP server for a Codex session: its url, the token by name from the environment
    (`TCC_MCP_TOKEN` — never in argv), tools approved by TCC's own gate, and a tool timeout above
    a confirmation's and a review's (Codex's ~60 s default would cut one)."""
    return [
        *_c("mcp_servers.tcc.url", _toml_string(url)),
        *_c("mcp_servers.tcc.env_http_headers", '{"X-TCC-Token"="' + TOKEN_ENV + '"}'),
        *_c("mcp_servers.tcc.default_tools_approval_mode", '"approve"'),
        *_c("mcp_servers.tcc.tool_timeout_sec", str(int(timeout_sec))),
    ]


def _config(config_read: Mapping) -> Mapping:
    inner = config_read.get("config") if isinstance(config_read, Mapping) else None
    return inner if isinstance(inner, Mapping) else (config_read or {})


def _server_names(config_read: Mapping) -> list[str]:
    servers = _config(config_read).get("mcp_servers")
    return [str(name) for name in servers if name != "tcc"] if isinstance(servers, Mapping) else []


def unsafe_server_names(config_read: Mapping) -> list[str]:
    """MCP servers in the user's config whose names `-c` cannot carry as a bare key: left out of
    `isolation_args` (a malformed `-c` kills the start) and said in a Notice instead."""
    return [name for name in _server_names(config_read) if not _BARE_KEY.match(name)]


def isolation_args(config_read: Mapping) -> list[str]:
    """The `-c` pieces that turn the user's own extras off for a TCC session, from `config/read`.

    Only servers actually in the config are named: `mcp_servers.<name>.enabled=false` for a name
    that is not there makes app-server exit 1 at start («invalid transport», task 1)."""
    args: list[str] = []
    for name in _server_names(config_read):
        if _BARE_KEY.match(name):
            args += _c(f"mcp_servers.{name}.enabled", "false")
    args += _c("notify", "[]")
    for feature in OFF_FEATURES:
        args += _c(f"features.{feature}", "false")
    args += _c("project_doc_max_bytes", "0")
    args += _c("skills.bundled.enabled", "false")
    args += _c("shell_environment_policy.exclude", f'["{TOKEN_ENV}"]')
    return args


def unknown_enabled_features(config_read: Mapping) -> list[str]:
    """Features `config/read` shows enabled that are on neither list — a new default-on extra
    the session would leak until someone decides which list it belongs on."""
    features = _config(config_read).get("features")
    if not isinstance(features, Mapping):
        return []
    known = set(OFF_FEATURES) | set(HARMLESS_FEATURES)
    return sorted(name for name, value in features.items()
                  if (value is True or (isinstance(value, Mapping) and value.get("enabled")))
                  and name not in known)


__all__ = [
    "Found", "Probe", "MIN_VERSION", "PIN", "SOURCE_PATH", "SOURCE_FOLDER", "SOURCE_TCC",
    "find", "forget", "version", "too_old", "usable", "probe", "signed_in", "models",
    "supported_efforts", "efforts_in", "tcc_copy_path", "dock_folders", "tcc_tool_args",
    "isolation_args",
    "unsafe_server_names", "unknown_enabled_features", "OFF_FEATURES", "HARMLESS_FEATURES",
]
