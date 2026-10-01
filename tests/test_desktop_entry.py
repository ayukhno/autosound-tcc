"""The bundle and the shortcuts this app builds for itself (F-026).

These used to be a shell script in the method's repository, where nothing here could be tested at
all: it was found by guessing a path and it read the icon out of the installed package through the
console script's shebang. Both of those broke in the field. Everything below runs on any platform
on purpose -- writing a bundle is writing files, and a test that needs a Mac is a test that does
not run on the machine that changes the code.
"""

from __future__ import annotations

import os
import plistlib
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from autosound_tcc.core import desktop_entry


def _bundle(tmp_path: Path, launcher: str = "/opt/bin/autosound-tcc") -> tuple[Path, bool]:
    return desktop_entry.build_macos_bundle(tmp_path, Path(launcher))


def test_bundle_has_the_layout_macos_requires(tmp_path):
    bundle, has_icon = _bundle(tmp_path)

    assert bundle.name == "Autosound TCC.app"
    assert (bundle / "Contents" / "Info.plist").is_file()
    assert (bundle / "Contents" / "MacOS" / "autosound-tcc").is_file()
    # The icon ships inside this package, so it is always found -- that is the whole point of
    # building the bundle from in here rather than from another repository.
    assert has_icon and (bundle / "Contents" / "Resources" / "AutosoundTCC.icns").is_file()


def test_plist_is_valid_and_says_what_finder_reads(tmp_path):
    bundle, _ = _bundle(tmp_path)
    info = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())

    assert info["CFBundleIdentifier"] == desktop_entry.BUNDLE_ID
    assert info["CFBundleName"] == "Autosound TCC"
    assert info["CFBundleExecutable"] == "autosound-tcc"
    assert info["CFBundleIconFile"] == "AutosoundTCC"
    # Not an accessory: an accessory bundle owns no Dock tile, and a window that loses focus then
    # has nothing to click to come back to.
    assert info["LSUIElement"] is False


def test_no_icon_in_the_package_means_no_icon_key(tmp_path, monkeypatch):
    """A missing `.icns` gives a bundle with the generic icon, not a bundle with a dead key.

    `CFBundleIconFile` naming a file that is not in `Resources/` is how you get a blank tile that
    no amount of re-registering fixes.
    """
    monkeypatch.setattr(
        desktop_entry,
        "_assets",
        lambda: ("Autosound TCC", tmp_path / "absent.icns", tmp_path / "absent.ico"),
    )
    bundle, has_icon = _bundle(tmp_path)
    info = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())

    assert not has_icon
    assert "CFBundleIconFile" not in info


@pytest.mark.skipif(os.name == "nt", reason="a macOS .app bundle: shell launcher, execute bit")
def test_launcher_is_executable_and_execs_the_installed_binary(tmp_path):
    bundle, _ = _bundle(tmp_path)
    script = bundle / "Contents" / "MacOS" / "autosound-tcc"

    assert script.stat().st_mode & stat.S_IXUSR
    body = script.read_text()
    # Looked up again at launch, with the resolved path only as the fallback: `uv tool upgrade`
    # moves the script, and a bundle pinned to today's path would stop starting.
    assert 'command -v autosound-tcc' in body
    assert "/opt/bin/autosound-tcc" in body
    assert body.rstrip().endswith('exec "$BIN" "$@"')


@pytest.mark.skipif(os.name == "nt", reason="a macOS .app bundle: shell quoting in its launcher")
def test_a_launcher_path_with_a_space_stays_one_word(tmp_path):
    """uv honours `UV_TOOL_BIN_DIR`, and people put it in folders with spaces."""
    bundle, _ = _bundle(tmp_path, "/Users/o'brien/My Apps/autosound-tcc")
    body = (bundle / "Contents" / "MacOS" / "autosound-tcc").read_text()

    assert "'/Users/o'\"'\"'brien/My Apps/autosound-tcc'" in body


def test_building_twice_over_the_same_bundle_is_fine(tmp_path):
    """Re-running the installer is the normal way to fix a bundle, so it must not fail."""
    first, _ = _bundle(tmp_path)
    (first / "Contents" / "Resources" / "stale.txt").write_text("from an older build")
    second, _ = _bundle(tmp_path)

    assert first == second
    assert (second / "Contents" / "Info.plist").is_file()


def test_the_desktop_alias_replaces_only_our_own_link(tmp_path):
    bundle, _ = _bundle(tmp_path / "apps")
    desktop = tmp_path / "Desktop"
    desktop.mkdir()

    result = desktop_entry.Result(True)
    desktop_entry.link_on_desktop(bundle, result, desktop=desktop)
    link = desktop / desktop_entry.BUNDLE_NAME
    assert link.is_symlink() and link.resolve() == bundle.resolve()

    # Again: the old link goes and a fresh one is made, because Finder caches an icon against the
    # item that has it and a link drawn before the bundle was registered keeps the blank tile.
    desktop_entry.link_on_desktop(bundle, result, desktop=desktop)
    assert link.is_symlink()


def test_somebody_elses_file_on_the_desktop_is_left_alone(tmp_path):
    bundle, _ = _bundle(tmp_path / "apps")
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    theirs = desktop / desktop_entry.BUNDLE_NAME
    theirs.write_text("not ours")

    result = desktop_entry.Result(True)
    desktop_entry.link_on_desktop(bundle, result, desktop=desktop)

    assert theirs.read_text() == "not ours"
    assert any("left alone" in line for line in result.lines)


def test_windows_shortcut_script_points_at_the_installed_launcher(tmp_path):
    targets = [tmp_path / "Desktop" / "Autosound TCC.lnk", tmp_path / "Menu" / "Autosound TCC.lnk"]
    exe = Path("C:/bin/autosound-tcc-gui.exe")
    script = desktop_entry._shortcut_script(targets, exe, None)

    for target in targets:
        assert str(target) in script
    # Built from the same Path the call got: a shortcut carries the platform's own spelling, and
    # hard-coding one side of that made a Mac-written test fail on the machine the .lnk is FOR.
    assert f'TargetPath = "{exe}"' in script
    # No icon given, so no IconLocation at all -- pointing at a file that is not there gets the
    # shortcut drawn blank rather than generic.
    assert "IconLocation" not in script


def test_windows_shortcut_script_uses_the_packaged_icon(tmp_path):
    script = desktop_entry._shortcut_script(
        [tmp_path / "Autosound TCC.lnk"], Path("C:/bin/x.exe"), Path("C:/pkg/app-icon.ico")
    )
    assert f'IconLocation = "{Path("C:/pkg/app-icon.ico")},0"' in script


def test_the_shortcuts_are_stamped_with_the_same_id_the_window_claims(tmp_path):
    """Pinning the Desktop icon and clicking it gave two taskbar buttons under two icons (user,
    2026-08-23). One button needs both halves to name the SAME application: the process claims it
    at startup (`core/windows_identity`), the shortcut carries it in its property store."""
    from autosound_tcc.core import windows_identity

    targets = [tmp_path / "Desktop" / "Autosound TCC.lnk", tmp_path / "Menu" / "Autosound TCC.lnk"]
    script = desktop_entry._stamp_script(targets, desktop_entry.BUNDLE_ID)

    for target in targets:
        assert str(target) in script
    assert f'"{desktop_entry.BUNDLE_ID}"' in script
    assert windows_identity.APP_USER_MODEL_ID == desktop_entry.BUNDLE_ID
    # PKEY_AppUserModel_ID and VT_LPWSTR: the property being written, and as what. A wrong
    # property id writes somewhere harmless and the taskbar goes on splitting the button.
    assert "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3" in script
    assert "vt = 31" in script


def test_a_machine_that_cannot_stamp_still_keeps_its_shortcuts(monkeypatch, tmp_path):
    """The shortcuts are already saved when this runs. A PowerShell that cannot compile the COM
    declarations costs the grouping, and must not cost the install."""
    monkeypatch.setattr(
        desktop_entry.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="Add-Type: no compiler"),
    )
    result = desktop_entry.Result(True)
    desktop_entry._stamp_windows([tmp_path / "Autosound TCC.lnk"], result)

    assert result.ok
    assert any("second taskbar button" in line for line in result.lines)


def test_every_spawn_here_goes_through_child_quiet(monkeypatch, tmp_path):
    """This module was the one exception to the house rule (tcc#14): twelve spawning modules pass
    `child.quiet()` and these four did not. They got away with it because `app.py` patches `Popen`
    process-wide before the install branch runs — a rule that holds somewhere else by accident is
    not a rule this module keeps."""
    seen: list = []

    def _run(*args, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(desktop_entry.subprocess, "run", _run)
    result = desktop_entry.Result(True)
    desktop_entry._stamp_windows([tmp_path / "Autosound TCC.lnk"], result)
    desktop_entry._windows_target_of(tmp_path / "Autosound TCC.lnk")

    assert seen, "the spawns were not reached"
    quiet = desktop_entry.child.quiet()
    for kwargs in seen:
        for key, value in quiet.items():
            assert kwargs.get(key) == value, f"{key} not passed: {kwargs}"


# ── the pins TCC repairs itself (finding 121, tcc#111) ──────────────────────────────────────────
#
# A pin made from the Desktop shortcut is a copy Windows makes without the id. Stamping that copy
# and telling Explorer gave one button on the VM (research W-4 §4, 2026-10-01). Nothing here needs
# Windows: the search is bytes in files, and the stamp is a script that can be read.

_OURS = r"C:\Users\a\AppData\Roaming\uv\tools\autosound-tcc\Scripts\autosound-tcc-gui.exe"
#: The same launcher as a Path. Forward slashes, so `.name` is the file name on the Mac too.
_LAUNCHER = Path("C:/Users/a/AppData/Roaming/uv/tools/autosound-tcc/Scripts/autosound-tcc-gui.exe")


def _lnk(target: str, *, stamped: bool = False, encoding: str = "utf-16-le") -> bytes:
    """Enough of a `.lnk` for the byte search: the header's size and magic, the target as Windows
    writes it, and -- when stamped -- the id as the property store holds it, UTF-16LE."""
    data = b"L\x00\x00\x00\x01\x14\x02\x00" + b"\x00" * 68 + target.encode(encoding)
    if stamped:
        data += b"\x00\x00" + desktop_entry.BUNDLE_ID.encode("utf-16-le")
    return data


def _pinned(tmp_path: Path) -> Path:
    """`User Pinned` with one of each: TCC's pins with and without the id, in both folders
    Windows keeps pins in, and other programs' pins beside them."""
    pinned = tmp_path / "User Pinned"
    taskbar = pinned / "TaskBar"
    implicit = pinned / "ImplicitAppShortcuts" / "d249d9ddd424b688"
    taskbar.mkdir(parents=True)
    implicit.mkdir(parents=True)
    (taskbar / "Autosound TCC.lnk").write_bytes(_lnk(_OURS))
    (taskbar / "From the window.lnk").write_bytes(_lnk(_OURS, stamped=True))
    (taskbar / "Notepad.lnk").write_bytes(_lnk(r"C:\Windows\System32\notepad.exe"))
    # TCC's folder, somebody else's program: the launcher is a file name, not a folder.
    (taskbar / "Python.lnk").write_bytes(
        _lnk(r"C:\Users\a\AppData\Roaming\uv\tools\autosound-tcc\Scripts\python.exe"))
    # The 8-bit copy of the path (LinkInfo's LocalBasePath), in capitals: Windows matches file
    # names regardless of case, so the search does too.
    (implicit / "Autosound TCC.lnk").write_bytes(_lnk(_OURS.upper(), encoding="ascii"))
    return pinned


def test_the_byte_search_picks_only_tcc_s_pins_without_the_id(tmp_path):
    pinned = _pinned(tmp_path)

    found = desktop_entry._unstamped_pins(pinned, "autosound-tcc-gui.exe")

    assert found == [pinned / "TaskBar" / "Autosound TCC.lnk",
                     pinned / "ImplicitAppShortcuts" / "d249d9ddd424b688" / "Autosound TCC.lnk"]


def test_the_stamp_tells_explorer_after_each_save(tmp_path):
    """The stamp alone put the id on the pin and it still did not group, even after an Explorer
    restart (27.09, finding 104). With `SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW | SHCNF_FLUSH)`
    after it, the same pin was one button (finding 121). In the C#, so every stamp notifies: the
    install's and the update's as well as the repair's."""
    script = desktop_entry._stamp_script([tmp_path / "Autosound TCC.lnk"], desktop_entry.BUNDLE_ID)

    assert 'DllImport("shell32.dll")' in script
    call = "SHChangeNotify(0x2000, 0x1005, lnk, IntPtr.Zero);"
    assert call in script
    assert script.index("file.Save(lnk, true)") < script.index(call)


def test_a_pin_s_name_reaches_the_stamp_as_data(tmp_path):
    """The repair stamps files found on disk, named by whoever pinned them. In `"..."` PowerShell
    would expand `$HOME` and the backtick; the stamp would miss the file, and miss it again, with
    a PowerShell run, on every start. PowerShell also ends a `'...'` literal at a typographic
    quote, so `O’Brien` is doubled like `O'Brien`."""
    pin = tmp_path / "O’Brien" / "TCC $HOME `n it's mine.lnk"
    script = desktop_entry._stamp_script([pin], desktop_entry.BUNDLE_ID)

    assert "'" + str(pin).replace("'", "''").replace("’", "’’") + "'" in script
    assert f'"{pin}"' not in script


def test_repair_stamps_and_notifies_tcc_s_unstamped_pins_and_no_other(monkeypatch, tmp_path):
    pinned = _pinned(tmp_path)
    scripts: list[str] = []

    def _run(args, **kwargs):
        scripts.append(args[-1])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(desktop_entry.subprocess, "run", _run)

    repaired = desktop_entry.repair_pins(pinned, launcher=_LAUNCHER)

    assert repaired == desktop_entry._unstamped_pins(pinned, "autosound-tcc-gui.exe")
    assert len(scripts) == 1, "one PowerShell for all the pins, not one per pin"
    for pin in repaired:
        assert str(pin) in scripts[0]
    for name in ("From the window.lnk", "Notepad.lnk", "Python.lnk"):
        assert name not in scripts[0]
    assert "SHChangeNotify(0x2000" in scripts[0]


def test_an_ordinary_start_spawns_nothing(monkeypatch, tmp_path):
    """TCC's history of flashing windows (findings 14, 43): a start whose pins are all stamped
    must not run PowerShell to find that out. The byte search decides before anything spawns."""
    pinned = _pinned(tmp_path)
    (pinned / "TaskBar" / "Autosound TCC.lnk").unlink()
    (pinned / "ImplicitAppShortcuts" / "d249d9ddd424b688" / "Autosound TCC.lnk").unlink()

    def _run(*args, **kwargs):
        raise AssertionError(f"spawned: {args}")

    monkeypatch.setattr(desktop_entry.subprocess, "run", _run)

    assert desktop_entry.repair_pins(pinned, launcher=_LAUNCHER) == []
    # Nothing pinned at all, and no `User Pinned` folder: the same nothing.
    assert desktop_entry.repair_pins(tmp_path / "nowhere", launcher=_LAUNCHER) == []


def test_a_repair_that_cannot_spawn_does_not_raise(monkeypatch, tmp_path):
    """It runs on a thread of its own while the window is up, and an exception there is an error
    shown in the window -- for a repair that is best effort, like the stamp it reuses."""
    pinned = _pinned(tmp_path)

    def _run(*args, **kwargs):
        raise OSError("powershell: not found")

    monkeypatch.setattr(desktop_entry.subprocess, "run", _run)

    assert len(desktop_entry.repair_pins(pinned, launcher=_LAUNCHER)) == 2


def test_nothing_installed_is_a_sentence_not_a_traceback(monkeypatch):
    monkeypatch.setattr(desktop_entry, "resolve_launcher", lambda: None)
    result = desktop_entry.install_desktop()

    assert not result.ok
    assert any("was not found" in line for line in result.lines)


def test_a_platform_with_no_desktop_entry_says_how_to_start_it(monkeypatch):
    monkeypatch.setattr(desktop_entry.platform, "system", lambda: "Linux")
    monkeypatch.setattr(desktop_entry, "resolve_launcher", lambda: Path("/usr/bin/autosound-tcc"))
    result = desktop_entry.install_desktop()

    assert not result.ok
    # The sentence carries the path as the platform spells it, so the expectation is built the
    # same way rather than assuming the developer's separator.
    assert any(str(Path("/usr/bin/autosound-tcc")) in line for line in result.lines)


def test_the_launcher_is_found_beside_this_interpreter_first(tmp_path, monkeypatch):
    """`UV_TOOL_BIN_DIR` moves the copy on PATH; the one beside our interpreter is always ours."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    suffix = ".exe" if os.name == "nt" else ""
    (fake_bin / f"autosound-tcc{suffix}").write_text("#!/bin/sh\n")
    monkeypatch.setattr(desktop_entry.sys, "executable", str(fake_bin / "python"))
    monkeypatch.setattr(desktop_entry.shutil, "which", lambda name: "/somewhere/else")

    assert desktop_entry.resolve_launcher() == fake_bin / f"autosound-tcc{suffix}"


def test_the_cli_carries_the_flag():
    """The command exists on a light install too, which is why it is parsed before Qt is looked
    for -- the person who installed without the window still wants the Dock entry."""
    from autosound_tcc import app

    assert app._parse(["autosound-tcc", "--install-desktop"]).install_desktop is True
    assert app._parse(["autosound-tcc"]).install_desktop is False


@pytest.mark.parametrize("name", ["autosound-tcc", "autosound-tcc-gui"])
def test_both_console_scripts_are_known(name):
    assert name in desktop_entry.LAUNCHER_NAMES



def test_version_flag_prints_and_does_not_start_the_app(capsys, monkeypatch):
    """`--version` must ANSWER, not run.

    There was no such flag, and `parse_known_args` — which exists so Qt can take its own flags off
    the same line — swallowed it without a word, so the app started: window, MCP server, the lot.
    A Windows VM too old to have an update panel showed it, through the one command the method's
    test plan uses to ask what is installed there (2026-08-22).

    The Qt import is asserted absent rather than merely unused: it is the step that would make this
    slow, and on a light install it is the step that fails.
    """
    import sys

    from autosound_tcc import app as app_module
    from autosound_tcc.core import app_log, availability, child, install_report

    # The installer runs this. A model reading here is `agy models` and `claude auth status` in
    # front of a one-line answer, and on Windows up to eight seconds of waiting (final review,
    # Important 3). Recorded rather than run, so no real reading thread outlives the test.
    readings: list = []
    monkeypatch.setattr(availability, "start_startup_reading",
                        lambda *a, **k: readings.append(True))
    monkeypatch.setattr(install_report, "app_version", lambda: "9.9.9")
    monkeypatch.setattr(app_log, "setup", lambda *a, **k: None)
    monkeypatch.setattr(child, "hide_console_windows", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["autosound-tcc", "--version"])

    # The guard that makes the second half of the name true: if `main` walked past the version
    # branch it would import the window from here, and `None` in `sys.modules` raises on import.
    monkeypatch.setitem(sys.modules, "autosound_tcc.ui.tcc.main_window", None)

    assert app_module.main() == 0
    assert capsys.readouterr().out.strip() == "9.9.9"
    assert readings == [], "a version query reads no model catalogues"


# ── what the installer reads back (tcc#124) ───────────────────────────────────────────────────
#
# The skill's installer runs `--install-desktop` through a pipe and reads two things: the exit code
# and the lines. On the Windows VM a run came back with a non-zero code and NONE of TCC's lines --
# only uv's launcher warning -- and the next run of the same line was fine (hub #229). Whatever
# ends such a process, its lines must already be with the caller by then: a pipe is block-buffered,
# so until now every line waited for the interpreter's own shutdown to be written at all.

#: A real `main()` in a real child process, with no stdin at all -- what the windowed launcher
#: hands `pythonw.exe` from the installer's pipeline -- and an end that skips Python's own
#: shutdown (`os._exit`), which is where a process killed after `main()` loses what it buffered.
_INSTALL_DESKTOP_CHILD = r"""
import os, sys
sys.stdin = None
try:
    os.close(0)
except OSError:
    pass
from autosound_tcc import app
from autosound_tcc.core import child, desktop_entry

outcome = sys.argv[1]

def fake_install():
    if outcome == "ok":
        return desktop_entry.Result(True).say("Built: /made/Autosound TCC.lnk")
    return desktop_entry.Result(False).say("the shortcuts were not created: refused")

desktop_entry.install_desktop = fake_install
# The console a windowed TCC makes for itself; nothing to do with the contract under test, and on
# a Windows runner with no console it would put one on screen.
child.open_app_console = lambda *a, **k: False
sys.argv = ["autosound-tcc", "--install-desktop"]
os._exit(app.main())
"""


def _run_install_desktop(tmp_path, outcome: str):
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    # The log goes under tmp_path on every platform (`app_log.log_dir`), not into the real one.
    env.update(HOME=str(tmp_path), LOCALAPPDATA=str(tmp_path), XDG_STATE_HOME=str(tmp_path))
    return subprocess.run(
        [sys.executable, "-c", _INSTALL_DESKTOP_CHILD, outcome],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=120,
    )


def test_install_desktop_hands_back_exit_0_and_its_lines_with_no_stdin(tmp_path):
    proc = _run_install_desktop(tmp_path, "ok")

    assert proc.returncode == 0, proc.stderr
    assert "Built: /made/Autosound TCC.lnk" in proc.stdout, (
        "the lines must reach the installer before the process ends, not at its shutdown")
    # And the log says what was decided, so a run whose code is lost on the way out can be told
    # from one that failed (hub #229: only the log of the VM can settle which one it was).
    log = next(tmp_path.rglob("tcc.log")).read_text(encoding="utf-8")
    assert "--install-desktop: exit 0" in log


def test_install_desktop_is_non_zero_only_on_a_real_failure(tmp_path):
    proc = _run_install_desktop(tmp_path, "failed")

    assert proc.returncode == 1
    assert "the shortcuts were not created: refused" in proc.stderr
    log = next(tmp_path.rglob("tcc.log")).read_text(encoding="utf-8")
    assert "--install-desktop: exit 1" in log


def test_every_path_it_creates_is_printed_on_a_line_of_its_own(tmp_path):
    """The caller's contract, stated by the installer that runs this (2026-08-26): print the paths
    created, one per line. It echoes them to whoever is installing, and a path nobody printed is a
    path nothing can remove later.

    The Desktop alias used to be described instead of named — "and an alias on the Desktop" — so
    the ONE created path the caller could not act on was the one it did not own. Asserted against
    the filesystem rather than against the wording: whatever the lines say, everything that now
    exists has to appear in them.
    """
    apps = tmp_path / "apps"
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    launcher = tmp_path / "bin" / "autosound-tcc"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o755)

    result = desktop_entry._install_macos(apps, launcher)
    desktop_entry.link_on_desktop(apps / desktop_entry.BUNDLE_NAME, result, desktop=desktop)

    printed = "\n".join(result.lines)
    for made in (apps / desktop_entry.BUNDLE_NAME, desktop / desktop_entry.BUNDLE_NAME):
        assert made.exists() or made.is_symlink(), f"{made} was not created at all"
        assert str(made) in printed, f"created {made} and did not print it"


# ── taking it back out ────────────────────────────────────────────────────────────────────────


def _installed(tmp_path):
    """A bundle and a Desktop alias, made the way `--install-desktop` makes them."""
    apps = tmp_path / "apps"
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    launcher = tmp_path / "bin" / "autosound-tcc"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o755)
    result = desktop_entry._install_macos(apps, launcher)
    desktop_entry.link_on_desktop(apps / desktop_entry.BUNDLE_NAME, result, desktop=desktop)
    return apps, desktop


def test_it_removes_exactly_what_it_built_and_says_each_path(tmp_path, monkeypatch):
    """The installer's own `--uninstall` deleted these by GUESSED paths while the side that made
    them was this one. Asserted against the filesystem, not the wording: everything that existed
    has to be gone AND named."""
    apps, desktop = _installed(tmp_path)
    monkeypatch.setattr(desktop_entry.Path, "home", staticmethod(lambda: tmp_path))
    made = [apps / desktop_entry.BUNDLE_NAME, desktop / desktop_entry.BUNDLE_NAME]
    assert all(p.exists() or p.is_symlink() for p in made)

    result = desktop_entry._uninstall_macos(apps)

    assert result.ok
    printed = "\n".join(result.lines)
    for path in made:
        assert not (path.exists() or path.is_symlink()), f"{path} survived"
        assert f"Removed: {path}" in printed, f"removed {path} and did not say so"


def test_running_it_twice_is_success_with_nothing_to_report(tmp_path, monkeypatch):
    """"Already gone" is the same outcome as "just removed" to whoever is uninstalling, and the
    installer runs this on every uninstall. Nothing on stdout the second time."""
    apps, _ = _installed(tmp_path)
    monkeypatch.setattr(desktop_entry.Path, "home", staticmethod(lambda: tmp_path))

    first = desktop_entry._uninstall_macos(apps)
    second = desktop_entry._uninstall_macos(apps)

    assert first.ok and first.lines
    assert second.ok and second.lines == [], second.lines


def test_somebody_elses_app_under_our_name_is_left_and_named(tmp_path, monkeypatch):
    """A folder with our NAME could be anybody's; the bundle id in Info.plist is the part we own.
    Deleting on the name alone is how an uninstaller eats somebody's own application."""
    apps = tmp_path / "apps"
    apps.mkdir()
    theirs = apps / desktop_entry.BUNDLE_NAME
    (theirs / "Contents").mkdir(parents=True)
    (theirs / "Contents" / "Info.plist").write_text("<plist>com.someone.else</plist>")
    monkeypatch.setattr(desktop_entry.Path, "home", staticmethod(lambda: tmp_path))

    result = desktop_entry._uninstall_macos(apps)

    assert result.ok, "leaving somebody's file alone is success, not failure"
    assert theirs.is_dir(), "it was not ours to delete"
    assert result.lines == [], "and stdout carries removed paths only"
    assert any("not ours" in note and str(theirs) in note for note in result.notes)


def test_a_desktop_file_that_is_not_our_alias_is_left(tmp_path, monkeypatch):
    """Ours is a SYMLINK to a bundle of that name. A real file there is somebody's own."""
    apps, desktop = _installed(tmp_path)
    link = desktop / desktop_entry.BUNDLE_NAME
    link.unlink()
    link.write_text("mine, actually")
    monkeypatch.setattr(desktop_entry.Path, "home", staticmethod(lambda: tmp_path))

    result = desktop_entry._uninstall_macos(apps)

    assert result.ok
    assert link.read_text() == "mine, actually"
    assert any("not ours" in note for note in result.notes)


def test_the_cli_carries_the_uninstall_flag():
    from autosound_tcc import app

    assert app._parse(["autosound-tcc", "--uninstall-desktop"]).uninstall_desktop is True
    assert app._parse(["autosound-tcc"]).uninstall_desktop is False
