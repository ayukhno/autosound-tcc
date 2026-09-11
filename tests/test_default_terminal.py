"""Which terminal Windows hands a new console to — and why TCC has to care.

The flash during an AI session is `claude`'s Bash tool spawning shells, each allocating its own
console window. The fix is to give the agent ONE console and hide it, so the shells inherit it
(`core/child.py`). That fix has a precondition which is not ours to assume: it works only when
the default terminal is the old **conhost**.

Measured on Windows 11, 2026-09-11. Under Windows Terminal the console window belongs to
`WindowsTerminal.exe`, not to our child: enumerating windows by our pid returns `[]` and
`AttachConsole` is refused with error 5. There is nothing of ours to hide. Under conhost the same
window is ours, hides in ~250 ms, and stays hidden after one re-hide.

So TCC reads this setting, offers once to change it, and can put it back — the restore half
matters more than the switch, because a setting an application changes and cannot undo is one it
had no business changing.

Everything here is injected. The registry is Windows-only and this suite runs on macOS.
"""

from __future__ import annotations

from autosound_tcc.core import default_terminal as dt


def test_conhost_is_recognised_from_both_keys():
    reading = {"DelegationConsole": dt.CONHOST, "DelegationTerminal": dt.CONHOST}
    assert dt.current(read=lambda: reading) == "conhost"


def test_windows_terminal_is_named_as_what_it_is():
    """It has to be named rather than lumped into "not conhost": it is the one value where the
    fix cannot work at all, and the question TCC asks says so out loud."""
    reading = {"DelegationConsole": dt.WINDOWS_TERMINAL, "DelegationTerminal": dt.WINDOWS_TERMINAL}
    assert dt.current(read=lambda: reading) == "windows-terminal"


def test_let_windows_decide_is_its_own_answer():
    """The out-of-the-box value. On Windows 11 it resolves to Windows Terminal, but it is not the
    same setting and putting the wrong one back on restore would be a change, not an undo."""
    reading = {"DelegationConsole": dt.LET_WINDOWS_DECIDE,
               "DelegationTerminal": dt.LET_WINDOWS_DECIDE}
    assert dt.current(read=lambda: reading) == "default"


def test_an_unreadable_setting_is_unknown_rather_than_a_guess():
    """A machine where the key cannot be read is not a machine where conhost is on."""
    assert dt.current(read=lambda: {}) == "unknown"
    assert dt.current(read=lambda: None) == "unknown"


def test_switching_saves_what_was_there_before_it_writes():
    """The undo is the whole point, so the previous pair is captured BEFORE the new one lands."""
    was = {"DelegationConsole": dt.WINDOWS_TERMINAL, "DelegationTerminal": dt.WINDOWS_TERMINAL}
    saved, written = {}, {}

    assert dt.set_conhost(read=lambda: was, write=written.update, save=saved.update) is True

    assert saved == was, "the previous setting has to be kept or it cannot be put back"
    assert written == {"DelegationConsole": dt.CONHOST, "DelegationTerminal": dt.CONHOST}


def test_restore_puts_back_exactly_what_was_saved():
    was = {"DelegationConsole": dt.WINDOWS_TERMINAL, "DelegationTerminal": dt.WINDOWS_TERMINAL}
    written = {}

    assert dt.restore(load=lambda: was, write=written.update) is True

    assert written == was


def test_restore_with_nothing_saved_falls_back_to_letting_windows_decide():
    """Better than refusing: somebody whose backup is gone still needs a way out, and "let Windows
    decide" is the value a machine ships with."""
    written = {}

    assert dt.restore(load=lambda: {}, write=written.update) is True

    assert written == {"DelegationConsole": dt.LET_WINDOWS_DECIDE,
                       "DelegationTerminal": dt.LET_WINDOWS_DECIDE}


def test_the_switch_is_offered_once_and_only_where_it_would_help():
    """Four ways to be the wrong moment, and each is a real machine: not Windows at all; already
    on conhost; asked once already and told no; and a setting we could not read, where offering
    would be guessing at somebody's system."""
    offer = dict(on_windows=lambda: True, state=lambda: "windows-terminal",
                 already_asked=lambda: False)

    assert dt.should_offer(**offer) is True

    assert dt.should_offer(**{**offer, "on_windows": lambda: False}) is False
    assert dt.should_offer(**{**offer, "state": lambda: "conhost"}) is False
    assert dt.should_offer(**{**offer, "state": lambda: "unknown"}) is False
    assert dt.should_offer(**{**offer, "already_asked": lambda: True}) is False


def test_the_default_setting_is_offered_too_because_windows_11_resolves_it_to_terminal():
    """"Let Windows decide" is not conhost, and on Windows 11 it lands on Windows Terminal — so
    the flash is there and the offer belongs there too."""
    assert dt.should_offer(on_windows=lambda: True, state=lambda: "default",
                           already_asked=lambda: False) is True


def test_only_a_terminal_WE_switched_is_one_we_put_back():
    """The uninstall must not undo a choice the person made themselves. The backup is the proof
    that the switch was ours: no backup, nothing of ours to take back."""
    assert dt.switched_by_us(exists=lambda: True) is True
    assert dt.switched_by_us(exists=lambda: False) is False


def test_the_restore_file_is_a_reg_file_windows_will_accept():
    """Handed to the person as a FILE as well as a command: a `.reg` they can read before running
    is a different kind of promise from an application saying "trust me, I will undo it"."""
    text = dt.restore_file_text({"DelegationConsole": dt.WINDOWS_TERMINAL,
                                 "DelegationTerminal": dt.WINDOWS_TERMINAL})

    assert text.startswith("Windows Registry Editor Version 5.00")
    assert r"[HKEY_CURRENT_USER\Console\%%Startup]" in text
    assert f'"DelegationConsole"="{dt.WINDOWS_TERMINAL}"' in text
    assert f'"DelegationTerminal"="{dt.WINDOWS_TERMINAL}"' in text
    assert text.endswith("\r\n"), "a .reg file Windows reads is CRLF to the last line"
