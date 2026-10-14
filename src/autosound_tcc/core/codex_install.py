"""TCC's own Codex, from OpenAI's official wheel (W-10, tcc#181, task 9).

The Arbiter (2026-10-14): a Codex already installed is used; when there is none, TCC installs it
from the official source. The source is `openai-codex-cli-bin==PIN` on PyPI — OpenAI's own wheel,
built by openai/codex's CI, one package for macOS x86_64/arm64 and Windows amd64/arm64, with the
native binary inside: no Node, no Homebrew, no administrator rights.

What it guarantees:

* **The file is the one pinned here.** Its sha256 is in this source (`WHEELS`, read 2026-10-14),
  and PyPI's JSON must name the same digest before anything is downloaded — a swapped index answer
  cannot pass, and neither can a swapped file. HTTPS only.
* **The wheel is a folder, not one file** («Learned in task 1»): all of `codex_cli_bin/` is
  unpacked, each member with its mode from the zip, and `bin/*` / `codex-path/*` executable at
  least. A member outside it (but the wheel's own dist-info, which is skipped), absolute, with
  `..`, or a link refuses the whole wheel.
* **Nothing half-done.** The download goes to a temp file and the unpack to a temp folder, both
  beside the target in TCC's `codex/` folder; the new copy is renamed into exactly the folder
  `codex_cli.tcc_copy_path()` names only once it is whole and says the pinned version; an older
  complete copy is replaced only then. Any failure — a digest, a cancel, a full disk, a wrong
  version — leaves no temp file and no partial folder, and the older copy as it was; what an
  install cut short by a crash left is swept by the next one.

Qt-free. **Worker thread only**: it downloads ~130 MB and runs `codex --version`.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform as _platform
import shutil
import stat
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, NamedTuple, Optional
from urllib.parse import urlparse

from autosound_tcc.core import app_log, codex_cli

#: The package and the version TCC installs; `codex_cli.PIN` is the one source of the version.
PACKAGE = "openai-codex-cli-bin"
INDEX_URL = f"https://pypi.org/pypi/{PACKAGE}/{codex_cli.PIN}/json"
#: Where a person on another platform gets Codex (the sentence `install` refuses with).
CODEX_URL = "https://github.com/openai/codex"
#: The folder inside the wheel that is Codex; everything else in it is the wheel's own metadata.
ROOT = "codex_cli_bin"
DIST_INFO = f"openai_codex_cli_bin-{codex_cli.PIN}.dist-info"
#: Read and hashed this much at a time; a cancel is heard between two.
CHUNK = 1 << 20
#: The index and the file: long enough for a slow line to start answering.
TIMEOUT_S = 60.0
#: The new binary's first `--version`: on Windows a fresh .exe may sit under a Defender scan.
VERSION_TIMEOUT_S = 90.0
#: A refused rename is tried again after each of these (a scan holds a fresh .exe a moment).
RETRY_DELAYS: tuple[float, ...] = (0.25, 0.5, 1.0, 2.0)
#: A leftover of an install cut short (a crash, a kill) older than this is swept by the next one;
#: a younger one may be another TCC's install under way.
STALE_S = 30 * 60


class Wheel(NamedTuple):
    filename: str
    sha256: str


#: The four wheels of `openai-codex-cli-bin==0.162.1`, read from PyPI on 2026-10-14
#: (`tests/fixtures/codex/wheel-0.162.1.json`). A new PIN pins new rows.
WHEELS: dict[str, Wheel] = {
    "macos-x86_64": Wheel("openai_codex_cli_bin-0.162.1-py3-none-macosx_10_9_x86_64.whl",
                          "590aece9bcdeea1a4019a080ef39f6391db92ae2a9f7144fd326bbb2373be0db"),
    "macos-arm64": Wheel("openai_codex_cli_bin-0.162.1-py3-none-macosx_11_0_arm64.whl",
                         "490d395201c322e5bafc9c02075e36878a0c3b48d6d70ca0f0787629cb7c1c4c"),
    "windows-amd64": Wheel("openai_codex_cli_bin-0.162.1-py3-none-win_amd64.whl",
                           "5faae6b914d61c8cb2aee29a30d362f6afd2c06efabca5ac2546f678af2c3672"),
    "windows-arm64": Wheel("openai_codex_cli_bin-0.162.1-py3-none-win_arm64.whl",
                           "64381407d97fb2155a9fe48e7a2c43fe882cae2e85eb266e812d2281a23aeeb1"),
}

#: Members that must be executable whatever the zip says.
_EXECUTABLE_DIRS = ("bin", "codex-path")


class InstallError(Exception):
    """Codex was not installed; `str()` is the English sentence (the log's), `key` and `args`
    the same sentence for the window's language (`strings/codex.py`)."""

    def __init__(self, sentence: str, *, key: str = "", **fields) -> None:
        super().__init__(sentence)
        self.key = key
        self.fields = fields


@dataclass
class _Download:
    path: Path
    sha256: str
    size: int


def platform_key(system: Optional[str] = None, machine: Optional[str] = None) -> Optional[str]:
    """Which of `WHEELS` this machine takes; None for any other platform."""
    system = sys.platform if system is None else system
    machine = (_platform.machine() if machine is None else machine).lower()
    arm = machine in ("arm64", "aarch64")
    intel = machine in ("x86_64", "amd64", "x64")
    if system == "darwin":
        return "macos-arm64" if arm else "macos-x86_64" if intel else None
    if system.startswith("win"):
        return "windows-arm64" if arm else "windows-amd64" if intel else None
    return None


def _https(url: str) -> bool:
    return urlparse(url).scheme == "https"


def _open(opener: Callable, url: str):
    if not _https(url):
        raise InstallError(f"{url} is not an https address; nothing was downloaded",
                           key="codexInstallNetwork", error=f"not https: {url}")
    try:
        response = opener(url, timeout=TIMEOUT_S)
    except OSError as exc:  # URLError is an OSError
        raise InstallError(f"Codex could not be downloaded: {exc}", key="codexInstallNetwork",
                           error=str(exc)) from exc
    final = getattr(response, "geturl", lambda: url)()
    if final and not _https(final):
        response.close()
        raise InstallError(f"{url} was redirected to {final}, which is not https",
                           key="codexInstallNetwork", error=f"not https: {final}")
    return response


def _file_entry(opener: Callable, wheel: Wheel) -> dict:
    """PyPI's row for the pinned file, checked against the pin before anything is downloaded."""
    with _open(opener, INDEX_URL) as response:
        try:
            index = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise InstallError(f"PyPI's answer for {PACKAGE} could not be read: {exc}",
                               key="codexInstallNetwork", error=str(exc)) from exc
    rows = index.get("urls") if isinstance(index, dict) else None
    entry = next((row for row in rows or () if isinstance(row, dict)
                  and row.get("filename") == wheel.filename), None)
    if entry is None:
        raise InstallError(f"PyPI lists no {wheel.filename}", key="codexInstallNetwork",
                           error=f"PyPI lists no {wheel.filename}")
    said = str((entry.get("digests") or {}).get("sha256") or "").lower()
    if said != wheel.sha256:
        raise InstallError(f"PyPI's digest for {wheel.filename} ({said or 'none'}) is not the "
                           f"pinned {wheel.sha256}; nothing was downloaded",
                           key="codexInstallMismatch")
    if not _https(str(entry.get("url") or "")):
        raise InstallError(f"PyPI's address for {wheel.filename} is not https",
                           key="codexInstallNetwork", error=f"not https: {entry.get('url')}")
    return entry


def _number(value) -> int:
    """A size from a header or the index; 0 when it is not one (progress then shows no total)."""
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _download(opener: Callable, entry: dict, into: Path, progress, cancelled) -> _Download:
    """Stream the file to a temp file in `into`, hashing as it goes. On any failure the temp file
    is removed here; on success it is the caller's."""
    handle = tempfile.NamedTemporaryFile(dir=into, prefix=".codex-", suffix=".whl.part",
                                         delete=False)
    path = Path(handle.name)
    digest = hashlib.sha256()
    done = 0
    try:
        with handle, _open(opener, str(entry["url"])) as response:
            headers = getattr(response, "headers", {}) or {}
            total = _number(headers.get("Content-Length")) or _number(entry.get("size"))
            progress(0, total)
            while True:
                if cancelled():
                    raise InstallError("the installation was cancelled",
                                       key="codexInstallCancelled")
                try:
                    chunk = response.read(CHUNK)
                except OSError as exc:
                    raise InstallError(f"Codex could not be downloaded: {exc}",
                                       key="codexInstallNetwork", error=str(exc)) from exc
                if not chunk:
                    break
                try:
                    handle.write(chunk)
                except OSError as exc:
                    raise InstallError(f"Codex could not be written to the disk: {exc}",
                                       key="codexInstallDisk", error=str(exc)) from exc
                digest.update(chunk)
                done += len(chunk)
                progress(done, total)
    except InstallError:
        _remove(path)
        raise
    except OSError as exc:  # closing a full disk's file
        _remove(path)
        raise InstallError(f"Codex could not be written to the disk: {exc}",
                           key="codexInstallDisk", error=str(exc)) from exc
    except BaseException:
        _remove(path)
        raise
    return _Download(path, digest.hexdigest(), done)


def _member_parts(name: str) -> Optional[tuple[str, ...]]:
    """The member's path inside `ROOT`, as parts; None for the wheel's own dist-info (skipped).
    Anything else outside `ROOT`, absolute, with `..` or a drive refuses the wheel."""
    if "\\" in name or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise InstallError(f"the wheel holds a member with an unsafe path: {name!r}",
                           key="codexInstallBadWheel", error=f"unsafe path {name!r}")
    parts = PurePosixPath(name).parts
    if any(part in ("..", "") for part in parts):
        raise InstallError(f"the wheel holds a member with an unsafe path: {name!r}",
                           key="codexInstallBadWheel", error=f"unsafe path {name!r}")
    if parts and parts[0] == DIST_INFO:
        return None
    if not parts or parts[0] != ROOT:
        raise InstallError(f"the wheel holds a member outside {ROOT}/: {name!r}",
                           key="codexInstallBadWheel", error=f"outside {ROOT}/: {name!r}")
    return parts


def _copy(src, dst) -> None:
    """One member's bytes; the seam a test fails mid-unpack."""
    shutil.copyfileobj(src, dst, CHUNK)


def _mode(info: zipfile.ZipInfo, parts: tuple[str, ...]) -> int:
    mode = (info.external_attr >> 16) & 0o777
    if not mode:
        mode = 0o644
    if len(parts) > 2 and parts[1] in _EXECUTABLE_DIRS:
        mode |= 0o755
    return mode


def _unpack(wheel_path: Path, into: Path, cancelled) -> None:
    """All of `ROOT` from the wheel into `into` (which then holds `ROOT/`), modes kept. Every
    member is checked before the first is written."""
    try:
        archive = zipfile.ZipFile(wheel_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise InstallError(f"the Codex package is not a readable zip: {exc}",
                           key="codexInstallBadWheel", error=str(exc)) from exc
    with archive:
        members = []
        for info in archive.infolist():
            parts = _member_parts(info.filename)
            if parts is None:
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                raise InstallError(f"the wheel holds a link: {info.filename!r}",
                                   key="codexInstallBadWheel", error=f"a link {info.filename!r}")
            members.append((info, parts))
        root = into.resolve()
        for info, parts in members:
            if cancelled():
                raise InstallError("the installation was cancelled", key="codexInstallCancelled")
            dest = into.joinpath(*parts)
            if root not in dest.resolve().parents:
                raise InstallError(f"the wheel holds a member outside its folder: "
                                   f"{info.filename!r}", key="codexInstallBadWheel",
                                   error=f"outside {ROOT}/: {info.filename!r}")
            try:
                if info.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, open(dest, "wb") as dst:
                    _copy(src, dst)
                if os.name != "nt":
                    os.chmod(dest, _mode(info, parts))
            except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
                raise InstallError(f"the Codex package could not be unpacked: {exc}",
                                   key="codexInstallBadWheel", error=str(exc)) from exc
            except OSError as exc:
                raise InstallError(f"Codex could not be written to the disk: {exc}",
                                   key="codexInstallDisk", error=str(exc)) from exc


def _remove(path: Optional[Path]) -> None:
    """Gone, file or folder: this is the cleanup of a failure already being said. What will not
    go is named in the log (a Windows .exe a scan still holds, for one)."""
    if path is None:
        return
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists() or path.is_symlink():
            path.unlink()
    except OSError:
        pass
    if path.exists() or path.is_symlink():
        app_log.logger().warning("codex install: %s could not be removed; the next install "
                                 "sweeps it once it is older than %d min", path, STALE_S // 60)


def _leftovers(parent: Path, pin: str) -> list[Path]:
    """What an install cut short leaves in TCC's `codex/` folder: its own patterns only."""
    patterns = (".codex-*.whl.part", f".{pin}-new-*", f".{pin}-old-*")
    try:
        return [path for pattern in patterns for path in parent.glob(pattern)]
    except OSError:
        return []


def _sweep(parent: Path, pin: str) -> None:
    """Remove the leftovers older than `STALE_S`; a younger one may be another TCC's install."""
    now = time.time()
    for path in _leftovers(parent, pin):
        try:
            age = now - path.lstat().st_mtime
        except OSError:
            continue
        if age > STALE_S:
            app_log.logger().info("codex install: sweeping %s, left by an install cut short", path)
            _remove(path)


def _replace(src, dst) -> None:
    """One rename; the seam a test refuses."""
    os.replace(src, dst)


def _replace_retrying(src: Path, dst: Path) -> None:
    """`_replace`, tried again after each of `RETRY_DELAYS` while it is refused — a fresh .exe
    under a virus scan refuses a rename for a moment on Windows. The last refusal is raised."""
    for delay in (*RETRY_DELAYS, None):
        try:
            _replace(src, dst)
            return
        except OSError:
            if delay is None:
                raise
            time.sleep(delay)


def _place(staging: Path, folder: Path) -> None:
    """`staging` becomes `folder`; an older `folder` is moved aside first and removed only once
    the new one is in place, put back if the rename fails."""
    aside: Optional[Path] = None
    if folder.exists():
        aside = Path(tempfile.mkdtemp(dir=folder.parent, prefix=f".{folder.name}-old-"))
        aside.rmdir()
        try:
            _replace_retrying(folder, aside)
        except OSError as exc:
            raise InstallError(f"the older Codex at {folder} could not be replaced (is a session "
                               f"using it?): {exc}", key="codexInstallDisk", error=str(exc)) from exc
    try:
        _replace_retrying(staging, folder)
    except OSError as exc:
        if aside is not None:
            try:
                _replace_retrying(aside, folder)
            except OSError:
                app_log.logger().error("codex install: the older copy is left at %s", aside)
        raise InstallError(f"Codex could not be put in place at {folder}: {exc}",
                           key="codexInstallDisk", error=str(exc)) from exc
    _remove(aside)


def _reads_pin(binary: Path) -> Optional[tuple]:
    """`codex --version` of `binary` with the first run's bound; None when it says nothing."""
    return codex_cli.version(codex_cli.Found(str(binary), codex_cli.SOURCE_TCC),
                             timeout=VERSION_TIMEOUT_S)


def _complete(binary: Path) -> bool:
    """Is a whole copy of the pinned Codex at `binary` — another TCC's install that won a race."""
    return binary.is_file() and codex_cli.version_text(_reads_pin(binary)) == codex_cli.PIN


def install(progress: Callable[[int, int], None], cancelled: Callable[[], bool],
            opener: Callable = urllib.request.urlopen, *, target: Optional[Path] = None,
            platform: Optional[str] = "") -> Path:
    """Install TCC's own Codex; the path of its binary, or `InstallError`. **Worker thread only.**

    `progress(done, total)` in bytes as the file arrives; `cancelled()` is read between chunks and
    between members. `target` is the binary's path (`codex_cli.tcc_copy_path()` by default) and
    `platform` a `WHEELS` key ("" = this machine's) — the tests' doors.
    """
    key = platform_key() if platform == "" else platform
    if key not in WHEELS:
        raise InstallError(f"TCC installs Codex on macOS and Windows only; on this computer "
                           f"install it yourself: {CODEX_URL}", key="codexInstallUnsupported",
                           url=CODEX_URL)
    wheel = WHEELS[key]
    binary = Path(target) if target is not None else codex_cli.tcc_copy_path(
        windows=key.startswith("windows"))
    folder = binary.parents[2]  # …/codex/<PIN>: the binary is <PIN>/codex_cli_bin/bin/codex
    inside = binary.relative_to(folder)
    log = app_log.logger()
    log.info("codex install: %s into %s", wheel.filename, folder)
    entry = _file_entry(opener, wheel)
    try:
        folder.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InstallError(f"TCC's folder for Codex could not be made: {exc}",
                           key="codexInstallDisk", error=str(exc)) from exc
    _sweep(folder.parent, folder.name)
    staging: Optional[Path] = None
    part: Optional[Path] = None
    try:
        download = _download(opener, entry, folder.parent, progress, cancelled)
        part = download.path
        if download.sha256 != wheel.sha256:
            raise InstallError(f"the downloaded {wheel.filename} has sha256 {download.sha256}, "
                               f"not the pinned {wheel.sha256}", key="codexInstallMismatch")
        try:
            staging = Path(tempfile.mkdtemp(dir=folder.parent, prefix=f".{folder.name}-new-"))
        except OSError as exc:
            raise InstallError(f"Codex could not be written to the disk: {exc}",
                               key="codexInstallDisk", error=str(exc)) from exc
        _unpack(part, staging, cancelled)
        _remove(part)
        part = None
        new_binary = staging / inside
        if not new_binary.is_file():
            raise InstallError(f"the wheel has no {inside.as_posix()}", key="codexInstallBadWheel",
                               error=f"no {inside.as_posix()}")
        read = _reads_pin(new_binary)
        if read is None:
            raise InstallError(f"the unpacked Codex could not be asked its version in "
                               f"{VERSION_TIMEOUT_S:g} s (the log has what it said)",
                               key="codexInstallUnreadVersion")
        if codex_cli.version_text(read) != codex_cli.PIN:
            said = codex_cli.version_text(read)
            raise InstallError(f"the unpacked Codex says {said}, not {codex_cli.PIN}",
                               key="codexInstallWrongVersion", version=said, pin=codex_cli.PIN)
        if cancelled():
            raise InstallError("the installation was cancelled", key="codexInstallCancelled")
        try:
            _place(staging, folder)
        except InstallError:
            # Two TCCs installing at once: the other one's whole copy is the same Codex.
            if not _complete(binary):
                raise
            log.info("codex install: another install put Codex %s at %s first", codex_cli.PIN,
                     folder)
        else:
            staging = None
    except InstallError as exc:
        log.warning("codex install: %s", exc)
        raise
    finally:
        _remove(part)
        _remove(staging)
    # Found again from here on; the versions already read are kept — a wipe made `find()` answer
    # an old Codex on PATH again until the next probe ended (task 9's review, M1).
    codex_cli.forget()
    log.info("codex install: Codex %s is at %s", codex_cli.PIN, binary)
    return binary


__all__ = ["InstallError", "Wheel", "WHEELS", "INDEX_URL", "PACKAGE", "install", "platform_key"]
