"""The bundle and the shortcuts this app builds for itself (F-026).

These used to be a shell script in the method's repository, where nothing here could be tested at
all: it was found by guessing a path and it read the icon out of the installed package through the
console script's shebang. Both of those broke in the field. Everything below runs on any platform
on purpose -- writing a bundle is writing files, and a test that needs a Mac is a test that does
not run on the machine that changes the code.
"""

from __future__ import annotations

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
    script = desktop_entry._shortcut_script(targets, Path("C:/bin/autosound-tcc-gui.exe"), None)

    for target in targets:
        assert str(target) in script
    assert 'TargetPath = "C:/bin/autosound-tcc-gui.exe"' in script
    # No icon given, so no IconLocation at all -- pointing at a file that is not there gets the
    # shortcut drawn blank rather than generic.
    assert "IconLocation" not in script


def test_windows_shortcut_script_uses_the_packaged_icon(tmp_path):
    script = desktop_entry._shortcut_script(
        [tmp_path / "Autosound TCC.lnk"], Path("C:/bin/x.exe"), Path("C:/pkg/app-icon.ico")
    )
    assert 'IconLocation = "C:/pkg/app-icon.ico,0"' in script


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
    assert any("/usr/bin/autosound-tcc" in line for line in result.lines)


def test_the_launcher_is_found_beside_this_interpreter_first(tmp_path, monkeypatch):
    """`UV_TOOL_BIN_DIR` moves the copy on PATH; the one beside our interpreter is always ours."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "autosound-tcc").write_text("#!/bin/sh\n")
    monkeypatch.setattr(desktop_entry.sys, "executable", str(fake_bin / "python"))
    monkeypatch.setattr(desktop_entry.shutil, "which", lambda name: "/somewhere/else")

    assert desktop_entry.resolve_launcher() == fake_bin / "autosound-tcc"


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
    from autosound_tcc.core import app_log, child, install_report

    monkeypatch.setattr(install_report, "app_version", lambda: "9.9.9")
    monkeypatch.setattr(app_log, "setup", lambda *a, **k: None)
    monkeypatch.setattr(child, "hide_console_windows", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["autosound-tcc", "--version"])

    # The guard that makes the second half of the name true: if `main` walked past the version
    # branch it would import the window from here, and `None` in `sys.modules` raises on import.
    monkeypatch.setitem(sys.modules, "autosound_tcc.ui.tcc.main_window", None)

    assert app_module.main() == 0
    assert capsys.readouterr().out.strip() == "9.9.9"


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
