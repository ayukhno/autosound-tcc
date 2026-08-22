"""Put the installed app where the operating system expects to find it.

macOS gets an `Autosound TCC.app` bundle in `~/Applications` (plus a Desktop alias); Windows gets
`Autosound TCC.lnk` on the Desktop and in the Start Menu. Both point at the INSTALLED launcher
rather than carrying a copy of it, so `uv tool upgrade` updates what they start.

**Why this lives in the app.** It used to be `scripts/make-macos-app.sh` in the method's
repository, called by the installer -- which meant the method's repository carried a builder for
somebody else's application, and the installer had to FIND it: `$SKILL_SRC/scripts/…` with a
fallback to `dirname $0`, which under `curl | bash` is whatever folder the person was standing in.
That fallback missed on a clean M1 (2026-08-13). It also had to go looking for the icon through
the console script's shebang, because the icon ships inside TCC's package and the script was
outside it -- an archaeology that broke once already when a long home path made uv write a
`/bin/sh` trampoline instead of a plain shebang (2026-08-17).

Both problems are the same problem: packaging TCC from outside TCC. From in here the icon is a
path in this package, the interpreter is the one running this line, and the version of the builder
is by construction the version of the app (F-026, boundary settled 2026-08-22 -- the installer
belongs to the method and may KNOW about TCC; building TCC is not knowing).

Nothing here imports Qt: `--install-desktop` has to work on a light install too, where there is no
window to show but the command is still worth having on the Dock for when the extras arrive.
"""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: What the bundle and the shortcuts are called. Not the package name -- `autosound-tcc` is what
#: you type, "Autosound TCC" is what it is.
BUNDLE_NAME = "Autosound TCC.app"
SHORTCUT_NAME = "Autosound TCC.lnk"
#: Reverse-DNS, and stable: macOS keys a bundle's registration, its Dock position and its window
#: state to this string. Changing it turns an update into a different application.
BUNDLE_ID = "dev.autosound.tcc"
#: The console scripts this all points at, best first. On Windows that is `-gui`, the launcher
#: built from a `gui_scripts` entry point, which is the one that opens no console window behind
#: the app; everywhere else the two are the same program and the plain name is what a person
#: types, so it is the one to name in a bundle somebody may read.
LAUNCHER_NAMES = ("autosound-tcc-gui", "autosound-tcc") if os.name == "nt" \
    else ("autosound-tcc", "autosound-tcc-gui")

#: Registers ONE bundle with Launch Services. Not `-kill -r -domain local -domain user`, which
#: rebuilds the whole database and takes minutes.
_LSREGISTER = (
    "/System/Library/Frameworks/CoreServices.framework/Frameworks"
    "/LaunchServices.framework/Support/lsregister"
)


@dataclass
class Result:
    """What happened, in lines a person can read. `ok` is what the exit code is made of."""

    ok: bool
    lines: list[str] = field(default_factory=list)

    def say(self, line: str) -> "Result":
        self.lines.append(line)
        return self


def _assets() -> tuple[str, Path, Path]:
    """The display name and the two icons, from the module that owns them.

    Imported here rather than at the top because `app` imports this package's `core` modules; a
    module-level import back into `app` would be a cycle the first time anything in `core` is
    loaded before it.
    """
    from autosound_tcc.app import APP_DISPLAY_NAME, APP_ICNS, APP_ICO

    return APP_DISPLAY_NAME, APP_ICNS, APP_ICO


def resolve_launcher() -> Path | None:
    """The installed console script this bundle or shortcut should start.

    `sys.executable` is the interpreter uv built the tool with, and its `bin`/`Scripts` folder is
    where uv put the console scripts -- so the first place to look is beside ourselves, which is
    right even when `UV_TOOL_BIN_DIR` sent the user-facing copy somewhere unusual. PATH is the
    fallback for the case this is running from a source checkout.
    """
    here = Path(sys.executable).resolve().parent
    suffix = ".exe" if os.name == "nt" else ""
    for name in LAUNCHER_NAMES:
        candidate = here / f"{name}{suffix}"
        if candidate.is_file():
            return candidate
    for name in LAUNCHER_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


# ── macOS ─────────────────────────────────────────────────────────────────────────────────────


def _plist(display_name: str, icon_name: str) -> str:
    icon = f"\n  <key>CFBundleIconFile</key>        <string>{icon_name}</string>" if icon_name else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>            <string>{display_name}</string>
  <key>CFBundleDisplayName</key>     <string>{display_name}</string>
  <key>CFBundleIdentifier</key>      <string>{BUNDLE_ID}</string>
  <key>CFBundleVersion</key>         <string>1</string>
  <key>CFBundleShortVersionString</key> <string>1.0</string>
  <key>CFBundlePackageType</key>     <string>APPL</string>
  <key>CFBundleExecutable</key>      <string>autosound-tcc</string>{icon}
  <key>NSHighResolutionCapable</key> <true/>
  <!-- A regular foreground app: it owns a menu bar and a Dock tile. Without this a bundle around
       a script can end up as an accessory, which is how a window ends up with no way back to it
       once something else takes focus. -->
  <key>LSUIElement</key>             <false/>
  <key>NSRequiresAquaSystemAppearance</key> <false/>
</dict>
</plist>
"""


def _launcher_script(launcher: Path) -> str:
    """The tiny shell script inside the bundle.

    It looks the binary up again at LAUNCH time and only falls back to the path we resolved now,
    so a `uv tool upgrade` that moves the script still starts. Finder gives a bundle almost no
    PATH, hence the explicit locations.
    """
    return f"""#!/bin/bash
# Launch the INSTALLED binary rather than a copy: `uv tool upgrade` then updates this app too.
# Finder gives a bundle almost no PATH, so the usual install locations are named explicitly.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
BIN="$(command -v autosound-tcc || echo {shlex.quote(str(launcher))})"
if [ ! -x "$BIN" ]; then
  /usr/bin/osascript -e 'display alert "Autosound TCC is not installed" \
message "Run the installer again, or: uv tool install autosound-tcc[gui,claude]"'
  exit 1
fi
# No --project-dir: TCC asks which project to open, and remembers the answer. A bundle cannot know
# which car you meant.
exec "$BIN" "$@"
"""


def build_macos_bundle(apps_dir: Path, launcher: Path) -> tuple[Path, bool]:
    """Write the bundle. Returns where it went and whether it got TCC's own icon.

    Pure filesystem work, deliberately: it runs the same on any platform so a test does not need a
    Mac to check the layout. Registering it with Launch Services is the part that needs macOS, and
    that is `install_desktop`'s job, not this one's.
    """
    display_name, icns, _ = _assets()
    bundle = apps_dir / BUNDLE_NAME
    (bundle / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
    (bundle / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)

    icon_name = ""
    if icns.is_file():
        shutil.copyfile(icns, bundle / "Contents" / "Resources" / "AutosoundTCC.icns")
        icon_name = "AutosoundTCC"

    (bundle / "Contents" / "Info.plist").write_text(_plist(display_name, icon_name))
    exe = bundle / "Contents" / "MacOS" / "autosound-tcc"
    exe.write_text(_launcher_script(launcher))
    exe.chmod(0o755)
    return bundle, bool(icon_name)


def link_on_desktop(bundle: Path, result: Result, desktop: Path | None = None) -> None:
    """A Desktop alias, and only ever our own.

    Anything else sitting there under that name is somebody's file and stays. An existing link of
    ours is REPLACED rather than left alone: Finder caches an icon against the item that has it,
    so a link first drawn when the bundle had no icon keeps the blank tile even after the bundle
    is fixed (user, 2026-08-19). A link made a moment ago is an item Finder has never drawn, so it
    asks Launch Services, which by then has the answer.
    """
    desktop = desktop or Path.home() / "Desktop"
    if not desktop.is_dir():
        return
    link = desktop / BUNDLE_NAME
    if link.is_symlink() and Path(os.readlink(link)) == bundle:
        link.unlink()
    if link.exists() or link.is_symlink():
        result.say(f"  left alone: something else is already called {BUNDLE_NAME} on the Desktop")
        return
    link.symlink_to(bundle)
    result.say("  and an alias on the Desktop")


def _install_macos(apps_dir: Path, launcher: Path) -> Result:
    result = Result(True)
    bundle, has_icon = build_macos_bundle(apps_dir, launcher)
    result.say(f"Built: {bundle}").say(f"It runs: {launcher}")

    # Touch, so Finder notices the bundle changed -- otherwise a rebuilt app keeps the old icon
    # and the old name until the icon cache happens to refresh.
    os.utime(bundle, None)
    # ...and TELL Launch Services, which the touch alone does not do. Finder does not read a
    # bundle's Info.plist to draw its icon; it asks Launch Services, and a bundle created a second
    # ago is not in that database yet. Until something scans it, the app -- and every alias to it
    # -- is drawn with the blank white placeholder, which is exactly what a fresh install showed
    # on a second Mac (user, 2026-08-19: the bundle was correct, the .icns was in place, and the
    # Desktop shortcut still had no icon). Best effort: an unregistered bundle is as correct as a
    # registered one, only drawn plainly.
    if Path(_LSREGISTER).is_file():
        subprocess.run(
            [_LSREGISTER, "-f", str(bundle)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    link_on_desktop(bundle, result)

    if not has_icon:
        result.say("note: no icon in this package — the bundle gets the generic one.")
    result.say(
        "Unsigned, which is fine for the machine that built it. Copied to another Mac it shows a "
        "Gatekeeper warning there — right-click → Open once."
    )
    return result


# ── Windows ───────────────────────────────────────────────────────────────────────────────────


def _shortcut_script(targets: list[Path], launcher: Path, icon: Path | None) -> str:
    """PowerShell that writes the `.lnk` files, via the same COM object the installer uses.

    A `.lnk` is a binary format with no standard-library writer, and pulling in `pywin32` for four
    properties would put a compiled dependency into every install for the sake of two shortcuts.
    """
    icon_line = f'    $s.IconLocation = "{icon},0"\n' if icon else ""
    paths = ", ".join(f'"{p}"' for p in targets)
    return (
        "$ErrorActionPreference = 'Stop'\n"
        "$ws = New-Object -ComObject WScript.Shell\n"
        f"foreach ($lnk in @({paths})) {{\n"
        "    $s = $ws.CreateShortcut($lnk)\n"
        # Points at the INSTALLED launcher, so `uv tool upgrade` updates what the shortcut starts
        # -- the same reason the macOS bundle execs rather than copies.
        f'    $s.TargetPath = "{launcher}"\n'
        '    $s.WorkingDirectory = $HOME\n'
        '    $s.Description = "Autosound Tuning Command Center"\n'
        f"{icon_line}"
        "    $s.Save()\n"
        "}\n"
    )


def _windows_targets() -> list[Path]:
    desktop = Path.home() / "Desktop"
    programs = Path(
        os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    ) / "Microsoft/Windows/Start Menu/Programs"
    return [d / SHORTCUT_NAME for d in (desktop, programs) if d.is_dir()]


def _install_windows(launcher: Path) -> Result:
    result = Result(True)
    _, _, ico = _assets()
    targets = _windows_targets()
    if not targets:
        return Result(False).say("neither the Desktop nor the Start Menu folder was found")

    script = _shortcut_script(targets, launcher, ico if ico.is_file() else None)
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # The command still works from a terminal, and saying so is the difference between a
        # failed install and a missing shortcut.
        return Result(False).say(
            f"the shortcuts were not created: {(proc.stderr or '').strip()[:200]}"
        ).say(f"The command still works:  {launcher}")
    for target in targets:
        result.say(f"Built: {target}")
    result.say(f"They run: {launcher}")
    if not ico.is_file():
        result.say("note: no icon in this package — the shortcuts get the generic one.")
    return result


# ── the entry point ───────────────────────────────────────────────────────────────────────────


def install_desktop(apps_dir: Path | None = None, launcher: Path | None = None) -> Result:
    """Make this install startable the way the platform expects. Called by `--install-desktop`."""
    launcher = launcher or resolve_launcher()
    if launcher is None:
        return Result(False).say(
            "autosound-tcc was not found beside this interpreter or on PATH, so there is nothing "
            "for a shortcut to start."
        )

    system = platform.system()
    if system == "Darwin":
        apps_dir = apps_dir or Path.home() / "Applications"
        apps_dir.mkdir(parents=True, exist_ok=True)
        return _install_macos(apps_dir, launcher)
    if system == "Windows":
        return _install_windows(launcher)
    # Linux is a real install target for the CLI half (the installer says "macOS (and Linux)"),
    # and a .desktop file would be the equivalent -- but nobody has run TCC's window there yet, so
    # writing one now would be a guess shipped as a feature.
    return Result(False).say(
        f"--install-desktop has nothing to do on {system}: start the app with  {launcher}"
    )
