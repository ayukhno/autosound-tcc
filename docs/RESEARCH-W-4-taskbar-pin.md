# Research: a taskbar pin made from the desktop shortcut is a second button (tcc#92)

**Verdict: no lever is proven, so this changes no code.** Windows decides what a pin is when the pin
is made, and keeps that decision where TCC has no documented way in. A pin made from the desktop shortcut
got no app id on the VM. Writing the id into it afterwards changed nothing, even with Explorer restarted.
The hint that ships stays («pin TCC from its running window», `docs/guide/REFERENCE.md` and the output of
`--install-desktop`).

**One step has not been tested yet, and a hand check on the VM can test it without a new build (§4).**
Chromium repairs pins the same way the Arbiter did by hand on 27.09, with one extra step: it tells
Explorer that the file changed (`SHChangeNotify`). If that step gives one button, it becomes a small TCC
change (§4, "what each outcome unlocks"). If it does not, #92 closes on this document.

Written 2026-09-29 on the Mac. Nothing here ran on Windows. Every claim is either quoted from a source
listed in §6 or measured on the VM, and the text says which.

## 1. What is measured (VM, Windows 11, 2026-09-27, TEST-FINDINGS 104)

| fact | evidence |
|---|---|
| The Desktop `Autosound TCC.lnk` has `System.AppUserModel.ID = dev.autosound.tcc` and target `…\AppData\Roaming\uv\tools\autosound-tcc\Scripts\autosound-tcc-gui.exe`. | `vm-logs/probe.txt` in the shared VM folder, 15:33 |
| The copy Windows made in `User Pinned\TaskBar` when the Desktop shortcut was pinned had **no** id. A fresh pin from the Desktop also had none. | finding 104 |
| After TCC's own stamp was run on the pinned copy, the copy **did** have the id: `Autosound TCC = dev.autosound.tcc`. | `vm-logs/probe2.txt`, 16:06 |
| Even after that, and with Explorer restarted, there were still two buttons: «Autosound TCC» (the pin) and «Tuning Command Center» (the running window). | finding 104, screenshot 30 |
| A pin made from the running window gives one button. | F-037, finding 44 |

The third row matters most. The pinned `.lnk` had the right id and the right target, and Explorer was
restarted, but the pin still did not group. So the taskbar is not reading that file's id when it decides
what the pin is.

## 2. (a) Where Windows keeps a pin's identity

- **The pinned `.lnk`.** "When you pin a shortcut to the taskbar or the Start menu, they make a copy of the
  shortcut and pin the copy" (Raymond Chen, [S5]). The copy goes into `%APPDATA%\Microsoft\Internet
  Explorer\Quick Launch\User Pinned\TaskBar`. If Windows finds no matching shortcut when it pins a running
  app, it makes one under `User Pinned\ImplicitAppShortcuts\<16 hex digits>\` instead ([S9]; Microsoft staff
  confirm the same thing for Chrome in [S11]).
- **The `Taskband` registry key.** `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Taskband`
  holds the pin list (`Favorites`) and `FavoritesResolve`, which "include all the taskbar shortcut
  information … taskbar is populated with this registry key" (TechNet Community Support, [S12]). On
  Windows 11, copying a `.lnk` into the folder does not pin anything ([S13]), so the folder is not the list.
  Both values are binary and undocumented. No API reads or writes them.
- **Fixed when the pin is made.** Measured (§1, row 4). Others report the same: after an app started
  setting its id, "the pin had to be re-made in order for the change to be effective. The pin that was
  made using a version of the app that didn't have its AppUserModelID set wasn't compatible"
  (Squirrel.Windows#1094, [S14]).

## 3. (b) Why the desktop-shortcut pin and the window don't group

**The taskbar groups by app id and nothing else.** "Windows groups open windows with the same AUMI to a
taskbar icon" ([S9]). The window claims `dev.autosound.tcc` twice: for the process
(`windows_identity.claim`) and on the window itself (`stamp_window`). The desktop-shortcut pin was made
without an id (§1). A pin without an explicit id gets one that Windows works out from the shortcut's target,
which is the uv trampoline `autosound-tcc-gui.exe`. An id Windows works out can never equal an explicit
one, and "Applications cannot retrieve a system-assigned AppUserModelID" ([S1]). Microsoft's docs describe
this exact setup: when a launcher starts the real app as a second process, "the system [is] unable to
relate the running target process back to the shortcut because the shortcut points to the intermediary
process" ([S1]). Their fix is an explicit id on both the shortcut and the process. TCC already does that.

**On Windows 7 the documented contract covered this route.** "If the application sets an AppUserModelID
in its process, and same AppUserModelID in the shortcut, then when the shortcut is pinned to the taskbar
and the application is launched from it, the application icon will group together with the shortcut"
(Windows Installer team, 2009, [S10]). On the VM, Windows 11 did not keep the id when it pinned the Desktop
shortcut. None of the sources below explains why. **The reason for the drop is not established.** It is a
measured fact about this version of Windows, not something TCC wrote.

**The pin from the running window groups because Windows builds it from the window's id.** The id goes on
the shortcut so that "the taskbar [can] identify the proper shortcut to pin" ([S1]). Windows looks for a
shortcut that carries the window's id and pins that one ([S9]). So the pin is filed under
`dev.autosound.tcc` from the start.

**The two names are a symptom, not the cause.** «Autosound TCC» is the pinned `.lnk`'s name. «Tuning
Command Center» is the title of a window that sits in no group. Renaming either one does not group them,
because the id alone decides grouping.

## 4. (c) Can TCC make them group?

| lever | verdict | why |
|---|---|---|
| Relaunch properties on the window (`RelaunchCommand` / `RelaunchDisplayNameResource` / `RelaunchIconResource`) | **no**; already set (F-037) | They describe what a pin of the **window** starts ([S2], [S3]). Microsoft: "If a shortcut exists to launch the application, an application should apply the AppUserModelID as a property of the shortcut instead of using the relaunch properties" ([S1]). They play no part when the pin is made from a shortcut. |
| Same id and same display name on the shortcut and the window | **no**; the ids already match | The id already matches on both. The name is only what gets displayed (§3). |
| Give the window the id Windows works out for the trampoline | **no** | That id cannot be read ([S1]). The window belongs to `pythonw.exe`, not the trampoline. Dropping the explicit claim would bring back F-037's «Python» pin. |
| `PreventPinning` on the Desktop shortcut | **not a fix**; the Arbiter's product call | Documented to stop a shortcut from being pinned ([S4]). It takes the route away instead of fixing it. It also puts the working route at risk: to pin a running window, Windows looks for a matching shortcut **on the desktop** first ([S9]). Not proposed without a measurement. |
| TCC pins itself | **no** silent way, by design | "there is also no Pin­To­Taskbar function … Because applications would abuse it" (Chen, [S6]). `TaskbarManager.RequestPinCurrentAppAsync` works for unpackaged desktop apps, but only as a request: the user confirms a system dialog, the app must be in the foreground, and it needs a Start menu entry. Windows builds older than KB5074105 (26100/26200.7705) also need a Limited Access Feature token ([S7], [S8]). It pins by app id, like a pin from the window, so it would give one button. That is a **new feature** (a TCC button plus WinRT calls), not a repair of the Desktop-shortcut route. It would go into the pool only if the Arbiter wants it. |
| Write the id into an existing pin | **measured: no** (without a notify) | Done by hand on 27.09 (§1, rows 3–4). |
| Write the id into an existing pin **and** notify the shell | **untested**: the one open candidate | Chromium ships this as `MigrateTaskbarPins`, "so that the appid is fixed and the run-time Chrome icon is merged with the taskbar shortcut". It sets the id and saves the pinned `.lnk` exactly as TCC's stamp does, then calls `SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATH \| SHCNF_FLUSH, path)` ([S15], [S16]). The 27.09 test left out only the notify. An Explorer restart does not replace it if Explorer starts from the cached `Taskband` data (§2). This evidence is weaker than it looks: Chrome runs the migration once, and it was last needed at Chrome 86 (2020). So it proves the approach on Windows 10 at the latest, not on Windows 11. |
| Write the id in the same save that creates the shortcut | **untested, weak** | Microsoft says the id "should be applied to a shortcut when that shortcut is created" ([S1]), and its own 2023 sample creates the Start entry that way ([S8]). TCC saves the shortcut with `WScript.Shell` and adds the id in a second save. The final file is the same either way, so this can only matter if Windows (the Start index) caches the shortcut as it was after the first save. Step 1 below checks that. |

### The hand check (Arbiter, VM; no new build; about 5 minutes)

Close TCC first. Open Windows PowerShell as yourself, not as admin. Each command is one line.

1. **What Start thinks TCC's id is:**
   `Get-StartApps | Where-Object Name -like '*Autosound*' | Format-List Name, AppID`
   `dev.autosound.tcc` means Start knows the id, and the last row of the table is ruled out.
   A path such as `{…}\…\autosound-tcc-gui.exe` means Start indexed the shortcut without the id. Then
   step 5 is worth doing.
2. **Make the failing pin again:** unpin «Autosound TCC» from the taskbar. Then right-click «Autosound
   TCC» on the Desktop → *Show more options* → *Pin to taskbar*.
3. **What the pin carries:**
   `$d="$env:APPDATA\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"; (New-Object -ComObject Shell.Application).NameSpace($d).Items() | ForEach-Object { $_.Name + ' = ' + $_.ExtendedProperty('System.AppUserModel.ID') }`
   After a fresh Desktop pin, 27.09 predicts `Autosound TCC = ` (empty).
4. **Chromium's repair: TCC's own stamp on the pin, then tell Explorer:**
   `& "$env:APPDATA\uv\tools\autosound-tcc\Scripts\python.exe" -c "import ctypes, os, pathlib; from autosound_tcc.core import desktop_entry as d; p = pathlib.Path(os.environ['APPDATA'], 'Microsoft', 'Internet Explorer', 'Quick Launch', 'User Pinned', 'TaskBar', 'Autosound TCC.lnk'); r = d.Result(True); d._stamp_windows([p], r); print(*r.lines, sep=chr(10)); ctypes.windll.shell32.SHChangeNotify(0x2000, 0x1005, ctypes.c_wchar_p(str(p)), None); print('notified:', p)"`
   Run step 3 again. It should now show `= dev.autosound.tcc`. **Start TCC by clicking the pin** and
   count TCC's taskbar buttons once the window is up.
   **One button: the lever is found.** Two buttons: this candidate is ruled out.
5. **Only if step 1 showed a path and step 4 left two buttons:** stamp and notify the Desktop and Start
   Menu shortcuts, then check Start again:
   `& "$env:APPDATA\uv\tools\autosound-tcc\Scripts\python.exe" -c "import ctypes; from autosound_tcc.core import desktop_entry as d; ps = d._windows_targets(); r = d.Result(True); d._stamp_windows(ps, r); print(*r.lines, sep=chr(10)); [ctypes.windll.shell32.SHChangeNotify(0x2000, 0x1005, ctypes.c_wchar_p(str(p)), None) for p in ps]; print('notified:', *ps)"`
   Then repeat step 1. Unpin, and pin again from the Desktop (step 2). Then step 3, start TCC from the
   pin, and count the buttons.

The first line of step 4 uses the Python inside TCC's uv tool, the folder the Desktop shortcut points
at (probe.txt). If `python.exe` is not there, use the `Scripts` folder of whatever the Desktop shortcut's
target is.

**What each outcome unlocks:**

- **Step 4 gives one button.** TCC repairs its own pins. On Windows, after the window is shown, it looks
  at the `.lnk` files in `User Pinned\TaskBar` and `User Pinned\ImplicitAppShortcuts\*`. Any file that
  starts TCC's launcher and lacks the id gets the stamp and the notify. The check is a byte search in
  Python: the launcher's file name is in the file and `dev.autosound.tcc` (UTF-16LE) is not. That way an
  ordinary start spawns nothing, which matters given TCC's history of flashing windows. The C# in
  `_STAMP_CS` gains one P/Invoke for the notify. Tests go in `tests/test_windows_identity.py` and
  `tests/test_desktop_entry.py`. About 30 lines.
- **Step 5 gives one button.** `_stamp_windows` notifies after each save, so an install or update leaves
  Start and the Desktop right before the first pin. About 5 lines and a test.
- **Neither gives one button.** No lever: #92 closes with this document, and the hint stays.

## 5. Noticed on the way, left alone (outside #92)

- Microsoft says the relaunch properties "should be set before setting the System.AppUserModel.ID
  property" ([S17]). `stamp_window` writes the id first, because `relaunch_properties` builds the dict
  with the id first. Raymond Chen's own sample does it in the same order ([S5b]), and the route it
  serves (a pin from the window) is confirmed working (F-037). Not changed.
- "A window's properties must be removed before the window is closed. If this is not done, the resources
  used by those properties are not returned to the system" ([S18]). TCC never clears them. They last
  until the process exits. Not changed.

## 6. Sources

- [S1] Microsoft Learn, *Application User Model IDs (AppUserModelIDs)*.
  https://learn.microsoft.com/en-us/windows/win32/shell/appids
- [S2] Microsoft Learn, *System.AppUserModel.RelaunchCommand*: used "only if a window has an explicit
  AppUserModelID"; must be set together with the display name.
  https://learn.microsoft.com/en-us/windows/win32/properties/props-system-appusermodel-relaunchcommand
- [S3] Microsoft Learn, *System.AppUserModel.RelaunchDisplayNameResource*: "the display name used for the
  shortcut created on the taskbar when the user chooses to pin an application".
  https://learn.microsoft.com/en-us/windows/win32/properties/props-system-appusermodel-relaunchdisplaynameresource
- [S4] Microsoft Learn, *System.AppUserModel.PreventPinning*.
  https://learn.microsoft.com/en-us/windows/win32/properties/props-system-appusermodel-preventpinning
- [S5] Raymond Chen, *How do I pin a program directly to the Start menu rather than a shortcut?* (2011).
  https://devblogs.microsoft.com/oldnewthing/20110427-00/?p=10823
- [S5b] Raymond Chen, *How do I prevent users from pinning my program to the taskbar?* (2011): the
  relaunch sample.
  https://devblogs.microsoft.com/oldnewthing/20110601-00/?p=10523
- [S6] Raymond Chen, *How did that program manage to pin itself to my taskbar when I installed it?* (2014).
  https://devblogs.microsoft.com/oldnewthing/20141230-00/?p=43273
- [S7] Microsoft Learn, *Pin your app to the taskbar* (TaskbarManager, LAF, KB5074105).
  https://learn.microsoft.com/en-us/windows/apps/develop/windows-integration/pin-to-taskbar
- [S8] Microsoft, Windows-classic-samples, *TaskbarManager* (`CppUnpackagedDesktopTaskbarPin`).
  https://github.com/microsoft/Windows-classic-samples/tree/main/Samples/TaskbarManager
- [S9] Chromium docs, *Windows Shortcut and Pinned Taskbar Icon handling*.
  https://chromium.googlesource.com/chromium/src/+/main/docs/windows_shortcut_and_taskbar_handling.md
- [S10] Windows Installer team blog, *Windows 7 Taskbar support with the MsiShortcutProperty table* (2009).
  https://learn.microsoft.com/en-us/archive/blogs/windows_installer_team/windows-7-taskbar-support-with-the-msishortcutproperty-table
- [S11] Microsoft Q&A, *Taskbar folder does not contain all pinned items* (Rita Han, MSFT, 2020).
  https://learn.microsoft.com/en-us/answers/questions/203377/taskbar-folder-does-not-contain-all-pinned-items
- [S12] TechNet forums archive, *Default Pinned Taskbar Shortcuts* (TechNet Community Support, 2012).
  https://learn.microsoft.com/en-us/archive/msdn-technet-forums/50f27606-02f9-47a8-a47a-7d506ff1e1f8
- [S13] Windows OS Hub, *Pin and Unpin Apps to the Taskbar in Windows 11 via PowerShell*.
  https://woshub.com/pin-unpin-apps-taskbar-windows-via-powershell/
- [S14] Squirrel.Windows issue #1094, *Pinned Shortcut Doubled at Runtime*.
  https://github.com/Squirrel/Squirrel.Windows/issues/1094
- [S15] Chromium, `chrome/browser/shell_integration_win.cc` (`MigrateTaskbarPins`,
  `MigrateShortcutsInPathInternal`).
  https://source.chromium.org/chromium/chromium/src/+/main:chrome/browser/shell_integration_win.cc
- [S16] Chromium, `base/win/shortcut.cc` (`CreateOrUpdateShortcutLink`: `Save`, then
  `SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATH | SHCNF_FLUSH, …)`).
  https://source.chromium.org/chromium/chromium/src/+/main:base/win/shortcut.cc
- [S17] Microsoft Learn, *System.AppUserModel.ID*.
  https://learn.microsoft.com/en-us/windows/win32/properties/props-system-appusermodel-id
- [S18] Microsoft Learn, *SHGetPropertyStoreForWindow*.
  https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shgetpropertystoreforwindow
