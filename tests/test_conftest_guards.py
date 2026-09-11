"""The suite must not be able to read this machine.

`conftest.py` states the rule for `cli_available` and patches it; these tests are the same claim,
checked rather than assumed. Written after the first CI runs (2026-09-07) found two tests that
passed on the author's laptop and failed everywhere else — the rule was right and the guard had a
second door nobody had noticed.
"""
from pathlib import Path

from autosound_tcc.core import model_choices


def test_the_suite_cannot_see_which_clis_this_machine_has():
    assert model_choices.cli_available("agy") is False


def test_the_suite_cannot_see_whether_a_critic_is_reachable():
    """`critic_reaches` asks `os.environ` and `shutil.which` directly, so patching
    `cli_available` never covers it. That gap is what made
    `test_no_row_repeats_what_the_row_already_says` green on a machine with `agy` installed and
    red on both CI platforms."""
    choice = model_choices.Choice(
        harness="agy",
        model="gemini-3.1-pro-high",
        label="Gemini 3.1 Pro (High)",
        provider="google",
    )
    assert model_choices.critic_reaches(choice) is False


def test_the_suite_cannot_read_this_machines_reviewer_key(monkeypatch, real_critic_reaches):
    """A third door onto the same machine, opened the day `critic_reaches` learned to look in
    `~/.config/autosound/critic-env` (SKL-024): a developer with a real key there would get a
    reachable critic and CI would not, which is the 2026-09-07 failure again wearing a new coat.
    `real_critic_reaches` deliberately un-stubs the function — so if the isolation is missing,
    this test reads the actual laptop and says so."""
    from autosound_tcc.core import critic_env

    # Both cleared FIRST, and that is the fix rather than a tidy-up. A developer's laptop has
    # neither set, so the assertion below passed here and failed on every CI runner: GitHub sets
    # `XDG_CONFIG_HOME` on Linux and `APPDATA` on Windows, and either one takes the resolution
    # away from HOME before the isolation can be observed. The property being tested is "HOME
    # still decides"; a test of it has to be the one deciding what else is in the environment.
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    # What isolates this is `conftest`'s tmp HOME, and that only works while the path is resolved
    # through `~` on every call. Hard-code it, or cache it at import time, and the suite silently
    # starts reading the developer's own key again. `Path.home()` is already the tmp one here,
    # which is the isolation working.
    assert Path.home() in critic_env.machine_config_path().parents

    other = Path.home().parent / "somewhere-else"
    monkeypatch.setenv("HOME", str(other))
    monkeypatch.setenv("USERPROFILE", str(other))  # what `~` follows on Windows

    assert critic_env.machine_config_path() == other / ".config" / "autosound" / "critic-env"
