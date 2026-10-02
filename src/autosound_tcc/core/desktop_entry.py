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
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from autosound_tcc.core import app_log, child

# Every spawn here goes through `child.quiet()`, like the other twelve modules that spawn. It was
# the one exception (tcc#14) and got away with it only because `app.py` installs a process-wide
# `Popen` patch before the `--install-desktop` branch runs — a house rule that holds by accident
# somewhere else is not a rule this module keeps.

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
    #: Lines for stderr even on success. `--uninstall-desktop` promises the calling installer that
    #: stdout carries the removed PATHS and nothing else, so "I left this alone, it is not mine"
    #: has to go somewhere that is still read but not parsed.
    notes: list[str] = field(default_factory=list)

    def say(self, line: str) -> "Result":
        self.lines.append(line)
        return self

    def note(self, line: str) -> "Result":
        self.notes.append(line)
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

    # UTF-8 by name, like every other file this app writes: the display name comes from the
    # caller and the launcher line carries a path, and neither is guaranteed to be ASCII.
    (bundle / "Contents" / "Info.plist").write_text(_plist(display_name, icon_name),
                                                    encoding="utf-8")
    exe = bundle / "Contents" / "MacOS" / "autosound-tcc"
    exe.write_text(_launcher_script(launcher), encoding="utf-8")
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
    # Named, not described. The installer that calls `--install-desktop` echoes these lines to the
    # person installing, and it asked for the PATHS one per line: "Built: <path>" is what the
    # Windows branch already prints per shortcut, and an alias nobody names is one nothing can
    # remove later. Prose here ("and an alias on the Desktop") left the only created path that the
    # caller could not act on.
    result.say(f"Built: {link}")


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
            **child.quiet(),
        )
    link_on_desktop(bundle, result)

    if not has_icon:
        # Two lines, on purpose. `icon: none` is the MACHINE-READABLE one: a stable token the
        # method's installers can match instead of prose, offered to them 2026-08-22 and theirs to
        # switch to. Until they do, the phrase "no icon" in the human line is load-bearing --
        # `install.sh` matches `*"no icon"*` and `install.ps1` `-match "no icon"` to add "(with the
        # generic icon)" to their own output (SCR-056, v3.0.16). Reword the rest freely; keep those
        # two words until the token replaces them, or their note stops appearing with no error on
        # either side. `icon: bundled` is deliberately NOT printed: absence of the token is the
        # normal case, and a line printed on every successful install is noise.
        result.say("icon: none").say(
            "note: no icon in this package — the bundle gets the generic one."
        )
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


def _ps_literal(path: Path) -> str:
    """A path as a single-quoted PowerShell literal: data, nothing in it expanded.

    PowerShell takes the typographic quotes ‘ ’ ‚ ‛ for `'` as well, so each is doubled like `'`
    -- a profile folder called `O’Brien` would otherwise end the literal halfway.
    """
    return "'" + re.sub("(['‘’‚‛])", r"\1\1", str(path)) + "'"


def _stamp_script(targets: list[Path], app_id: str) -> str:
    """PowerShell that writes `System.AppUserModel.ID` into each `.lnk`.

    **Why a second pass at all.** A pinned shortcut and the running window are one taskbar button
    only when they claim the same application. The window claims one now (`core/windows_identity`);
    a shortcut claims whatever Windows derives from its target path, which is the uv trampoline —
    so pinning the Desktop icon and then clicking it produced TWO buttons under two different
    icons (user, Parallels VM, 2026-08-23, with the screenshot to prove it).

    **Why not in the `WScript.Shell` pass above.** That COM object exposes four properties and this
    is not one of them: the id lives in the shortcut's property store, reachable only through
    `IPropertyStore`, which means declaring the two COM interfaces by hand. `Add-Type` compiles
    that against the .NET Framework every Windows PowerShell already ships, so it still costs the
    install nothing — no `pywin32`, no compiled dependency.

    Kept a SEPARATE PowerShell run on purpose: the shortcuts are saved by the time this runs, so a
    machine where `Add-Type` cannot compile loses the grouping and keeps its shortcuts.
    """
    # Literals, not `"..."`: since tcc#111 these paths include pins found on disk, named by
    # whoever pinned them, and `"..."` would expand a `$` or a backtick in one -- a stamp that
    # fails there fails again, with a PowerShell run, on every start.
    paths = ", ".join(_ps_literal(p) for p in targets)
    # A single-quoted here-string: PowerShell expands nothing inside it, and C# is full of the
    # characters it would otherwise try to expand.
    return (
        "$ErrorActionPreference = 'Stop'\n"
        "$source = @'\n" + _STAMP_CS + "\n'@\n"
        "Add-Type -TypeDefinition $source\n"
        f'foreach ($lnk in @({paths})) {{ [AutosoundTcc.Shortcut]::Stamp($lnk, "{app_id}") }}\n'
    )


#: The two COM interfaces a shortcut's property store needs, declared by hand because there is no
#: type library to import from. `[PreserveSig]` on every method is deliberate: without it the
#: runtime rewrites each signature into "throw on a bad HRESULT and return the out-parameter",
#: which does not match what is declared here and silently corrupts the vtable call.
_STAMP_CS = """using System;
using System.Runtime.InteropServices;

namespace AutosoundTcc {
  [StructLayout(LayoutKind.Sequential)]
  public struct PropertyKey {
    public Guid fmtid; public uint pid;
    public PropertyKey(Guid g, uint p) { fmtid = g; pid = p; }
  }

  [StructLayout(LayoutKind.Sequential)]
  public struct PropVariant {
    public ushort vt; public ushort r1; public ushort r2; public ushort r3;
    public IntPtr p; public IntPtr p2;
  }

  [ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IPropertyStore {
    [PreserveSig] int GetCount(out uint count);
    [PreserveSig] int GetAt(uint index, out PropertyKey key);
    [PreserveSig] int GetValue(ref PropertyKey key, out PropVariant value);
    [PreserveSig] int SetValue(ref PropertyKey key, ref PropVariant value);
    [PreserveSig] int Commit();
  }

  [ComImport, Guid("0000010b-0000-0000-C000-000000000046"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IPersistFile {
    [PreserveSig] int GetClassID(out Guid id);
    [PreserveSig] int IsDirty();
    [PreserveSig] int Load([MarshalAs(UnmanagedType.LPWStr)] string file, uint mode);
    [PreserveSig] int Save([MarshalAs(UnmanagedType.LPWStr)] string file,
                           [MarshalAs(UnmanagedType.Bool)] bool remember);
    [PreserveSig] int SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string file);
    [PreserveSig] int GetCurFile(out IntPtr file);
  }

  [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
  public class ShellLink { }

  public static class Shortcut {
    // PKEY_AppUserModel_ID, and 5 is its property id -- the pair is the shortcut's answer to
    // "which application am I", the same string the process claims at startup.
    static readonly Guid AppUserModel = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");

    // Tells Explorer that one file changed. The id alone left a pin that still did not group, even
    // after an Explorer restart (27.09, finding 104); with this after the save it was one button
    // (finding 121, tcc#111) -- the call Chromium's MigrateTaskbarPins makes after the same save.
    [DllImport("shell32.dll")]
    static extern void SHChangeNotify(int eventId, uint flags,
                                      [MarshalAs(UnmanagedType.LPWStr)] string item1, IntPtr item2);

    public static void Stamp(string lnk, string id) {
      var link = new ShellLink();
      var file = (IPersistFile)link;
      Marshal.ThrowExceptionForHR(file.Load(lnk, 2));  // STGM_READWRITE
      var store = (IPropertyStore)link;
      var key = new PropertyKey(AppUserModel, 5);
      var value = new PropVariant();
      value.vt = 31;  // VT_LPWSTR
      value.p = Marshal.StringToCoTaskMemUni(id);
      try {
        Marshal.ThrowExceptionForHR(store.SetValue(ref key, ref value));
        Marshal.ThrowExceptionForHR(store.Commit());
        // TRUE: the shortcut keeps the file it was loaded from as its own, which is what makes
        // this a re-save of that .lnk rather than a copy written somewhere else.
        Marshal.ThrowExceptionForHR(file.Save(lnk, true));
        SHChangeNotify(0x2000, 0x1005, lnk, IntPtr.Zero);  // SHCNE_UPDATEITEM; SHCNF_PATHW | SHCNF_FLUSH
      } finally {
        Marshal.FreeCoTaskMem(value.p);
      }
    }
  }
}"""


def _windows_targets() -> list[Path]:
    desktop = Path.home() / "Desktop"
    programs = Path(
        os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    ) / "Microsoft/Windows/Start Menu/Programs"
    return [d / SHORTCUT_NAME for d in (desktop, programs) if d.is_dir()]


def _pinned_root() -> Path:
    """Where Windows keeps the copies it pins: "they make a copy of the shortcut and pin the copy"
    (Raymond Chen), into `TaskBar` or into a hex-named folder under `ImplicitAppShortcuts`."""
    return Path(
        os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    ) / "Microsoft/Internet Explorer/Quick Launch/User Pinned"


def _unstamped_pins(pinned: Path, launcher_name: str) -> list[Path]:
    """TCC's pins without TCC's id, found by reading bytes, so finding none spawns nothing.

    A pin is TCC's when the launcher's file name is in it: as UTF-16LE in the target's shell item,
    as 8-bit in its LinkInfo path, in whatever case Windows wrote it. It is stamped when the id is
    in it as UTF-16LE, the way the property store holds a `VT_LPWSTR`. Asking COM instead would be
    a PowerShell per start, and TCC has a history of flashing windows (findings 14, 43).
    """
    folders = [pinned / "TaskBar"]
    try:
        folders += sorted(p for p in (pinned / "ImplicitAppShortcuts").iterdir() if p.is_dir())
    except OSError:
        pass  # no implicit pins on this machine
    name = launcher_name.lower()
    ours = (name.encode("utf-16-le"), name.encode("utf-8"))
    stamp = BUNDLE_ID.encode("utf-16-le")
    found = []
    for folder in folders:
        for link in sorted(folder.glob("*.lnk")):
            try:
                data = link.read_bytes()
            except OSError:
                continue
            if stamp not in data and any(n in data.lower() for n in ours):
                found.append(link)
    return found


def repair_pins(pinned: Path | None = None, launcher: Path | None = None) -> list[Path]:
    """Stamp TCC's own taskbar pins that lack its id, and tell Explorer (tcc#111). Never raises.

    A pin made from the Desktop shortcut is a copy Windows makes WITHOUT the id (finding 104), so
    the pin and the window it starts are two buttons. The same stamp the install gives the
    shortcuts, followed by the notify, made such a pin one button on the VM (finding 121). It
    helps from the NEXT start: the window this start opened was already counted as another app.

    Returns the pins it stamped, or tried to; empty on an ordinary start, which spawns nothing.
    """
    try:
        launcher = launcher or resolve_launcher()
        pins = _unstamped_pins(pinned or _pinned_root(), launcher.name) if launcher else []
    except OSError:
        return []
    if not pins:
        return []
    result = Result(True)
    try:
        stamped = _stamp_windows(pins, result)
    except OSError as exc:  # no PowerShell to run
        stamped = False
        result.say(str(exc))
    app_log.logger().info("pins: %s %s%s", "stamped" if stamped else "NOT stamped",
                          ", ".join(str(p) for p in pins),
                          "" if stamped else f" -- {app_log.brief(' '.join(result.lines))}")
    return pins


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
        encoding="utf-8",
        errors="replace",
        **child.quiet(),
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
    _stamp_windows(targets, result)
    if not ico.is_file():
        # "no icon" again -- see the note on the macOS branch above; the Windows installer
        # matches the same two words.
        result.say("icon: none").say(
            "note: no icon in this package — the shortcuts get the generic one."
        )
    return result


#: How long the stamp's PowerShell may take. `Add-Type` compiles C# on every run, which costs
#: seconds; a minute is a hang, not a slow machine.
STAMP_TIMEOUT_S = 60.0


def _stamp_windows(targets: list[Path], result: Result) -> bool:
    """Give the shortcuts the same application identity the running window claims.

    Best effort, and it says so either way: without this a pinned shortcut and the window it
    started are two taskbar buttons under two icons, WITH it they are one -- but a machine where
    `Add-Type` cannot compile still has working shortcuts, so this never turns an install into a
    failure. See `_stamp_script` for what is being written and why it needs COM. True when the
    script ran clean.
    """
    try:
        # `run_bounded`, not `subprocess.run`: at the timeout `run` kills PowerShell alone and then
        # waits, unbounded, for pipes a hung `csc.exe` from `Add-Type` still holds (tcc#132).
        proc = child.run_bounded(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             _stamp_script(targets, BUNDLE_ID)],
            timeout=STAMP_TIMEOUT_S,
            text=True,
            encoding="utf-8",
            errors="replace",
            **child.quiet(),
        )
        ran, said = proc.returncode == 0, (proc.stderr or "").strip()
    except subprocess.TimeoutExpired:
        # Not stamped, and said like any other failure: from `--install-desktop` a PowerShell that
        # hangs would hang the install (final review, Minor 4).
        ran, said = False, f"PowerShell did not answer in {STAMP_TIMEOUT_S:.0f} s."
    if ran:
        # «Pinned and running are one button» held for a pin made from the RUNNING window only: a
        # pin made from the shortcut loses the id (Windows drops it when it pins a shortcut, and
        # stamping the pinned copy afterwards did not help — finding 104, tcc#62). Stamping it AND
        # notifying does, and `repair_pins` does that at startup (finding 121, tcc#111) — from the
        # second start on, so the first one still shows two buttons and the hint stays.
        result.say(f"They are: {BUNDLE_ID}")
        result.say("To pin TCC to the taskbar, pin it from its running window: a pin made from "
                   "the shortcut starts it as a second button.")
        return True
    result.say(
        "note: the shortcuts could not be given the app id — pinning one will show a second "
        f"taskbar button when it runs. {said[:160]}"
    )
    return False


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


# ── taking it back out ────────────────────────────────────────────────────────────────────────
#
# The installer's own `--uninstall` removed the bundle and the alias by paths it GUESSED, while
# the side that created them is this one. So it deletes what it did not make and cannot say
# whether it got everything — asked for by the method's session, 2026-08-26, and the reason is
# exactly the reason `--install-desktop` exists.
#
# The rule this half adds: **remove only what is recognisably ours.** Somebody's own file under
# our name is theirs; it is left, named on stderr, and the exit code stays 0 — a person who put
# it there did so on purpose, and an uninstaller that eats it is worse than one that misses it.


def _is_our_bundle(bundle: Path) -> bool:
    """A `.app` is ours if its Info.plist claims our bundle id.

    The id is the one thing in there we own and macOS keys registration to — a folder with our
    NAME could be anybody's, and matching on the name alone is how an uninstaller deletes
    somebody's own app.
    """
    try:
        return BUNDLE_ID in (bundle / "Contents" / "Info.plist").read_text(encoding="utf-8")
    except OSError:
        return False


def _is_our_alias(link: Path) -> bool:
    """A Desktop entry is ours if it is a SYMLINK pointing at something called `BUNDLE_NAME`.

    By target, not by name: the name is what a collision looks like. A dangling link counts —
    that is what our own alias becomes the moment the bundle goes, and refusing to tidy it would
    leave the one piece of litter this command exists to prevent.
    """
    if not link.is_symlink():
        return False
    return Path(os.readlink(link)).name == BUNDLE_NAME


def _remove(path: Path, result: Result, ours: bool) -> None:
    """Delete one thing of ours, or say why it stayed. Never raises."""
    if not ours:
        result.note(f"Kept: {path} (not ours)")
        return
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)
    except OSError as exc:
        result.ok = False
        result.note(f"Could not remove {path}: {exc}")
        return
    result.say(f"Removed: {path}")


def _uninstall_macos(apps_dir: Path) -> Result:
    result = Result(True)
    bundle = apps_dir / BUNDLE_NAME
    link = Path.home() / "Desktop" / BUNDLE_NAME
    # The alias FIRST, while the bundle it points at still exists: after the bundle goes the link
    # dangles, and `_is_our_alias` reads the target rather than following it precisely so that
    # order does not decide the answer. Doing it in this order anyway keeps the two independent.
    if link.exists() or link.is_symlink():
        _remove(link, result, _is_our_alias(link))
    if bundle.exists():
        _remove(bundle, result, _is_our_bundle(bundle))
    return result


def _windows_target_of(shortcut: Path) -> str:
    """What a `.lnk` starts, or "" when it cannot be read. A COM call, like the one that made it."""
    # Single-quoted PowerShell literal, doubling any quote inside it: a path is data here, and
    # the `"..."` form the writing script uses would expand a `$` in somebody's folder name.
    literal = _ps_literal(shortcut)
    script = (
        "$s = New-Object -ComObject WScript.Shell; "
        f"$l = $s.CreateShortcut({literal}); "
        "Write-Output $l.TargetPath"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=False, capture_output=True, text=True, encoding="utf-8", errors="replace", **child.quiet())
    except OSError:
        return ""
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def _uninstall_windows() -> Result:
    result = Result(True)
    for target in _windows_targets():
        if not target.exists():
            continue
        points_at = _windows_target_of(target)
        ours = Path(points_at).stem in LAUNCHER_NAMES if points_at else False
        _remove(target, result, ours)
    return result


def uninstall_desktop(apps_dir: Path | None = None) -> Result:
    """Take back exactly what `install_desktop` put down. Called by `--uninstall-desktop`.

    Success means nothing of ours is left, which INCLUDES there having been nothing to begin with:
    the installer runs this before it removes the package, and "already gone" is the same outcome
    as "just removed" to whoever is uninstalling. Run it twice and the second run prints nothing
    and still exits 0.

    Never touches a project folder, a virtualenv or the package: those are the installer's, and it
    handles them after this returns.
    """
    system = platform.system()
    if system == "Darwin":
        return _uninstall_macos(apps_dir or Path.home() / "Applications")
    if system == "Windows":
        result = _uninstall_windows()
        # The default terminal is the other thing TCC may have changed on this machine: the
        # agent's console can only be hidden under conhost (TCC-006), so TCC offers to switch it.
        # An uninstall that leaves it switched is a change nobody can trace back to us. Only a
        # switch WE made is ours to take back, and the backup file is the proof of that.
        from autosound_tcc.core import default_terminal

        if default_terminal.switched_by_us():
            result.note(
                "default terminal put back to what it was before TCC changed it"
                if default_terminal.restore()
                else "could NOT put the default terminal back — run restore-default-terminal.reg"
            )
        return result
    return Result(True)
