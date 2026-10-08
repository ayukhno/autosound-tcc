"""Who signs TCC's own release tags: the trust anchor the updater checks them against (tcc#102,
hub #83 HUB-032).

A CONSTANT, never a file read from the tag being verified: a tag's own `allowed_signers` would
vouch for itself. The skill holds its anchor the same way (`upkeep.py` SIGNING_KEY, skill #99);
TCC's own sits here, apart from `scripts/ship.py`, so the updater can import it without importing
the release script. `allowed_signers` at the repository root carries the same line for people and
for `git verify-tag`, and `tests/test_signed_tags.py` holds the two equal.

Named `TCC_*` because the skill's anchor stands beside it in `core/updates.py` as `SKILL_*`: the
same key today, two facts — each is held to its own file.

How `git verify-tag` runs is here too, one recipe for its two callers: the updater
(`core/updates._verify_tag`) and the release machine's check of the tag it made
(`scripts/ship.py`, `verify_signed_tag`) — `VERIFY_PROGRAM` and `verify_env` (#174).
"""
from __future__ import annotations

from collections.abc import Mapping

TCC_SIGNING_PRINCIPAL = "ayukhno"
TCC_SIGNING_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHLm4x1yz9JbFfBlxdQA8vR8yYMupVktswes3CL7QE1y"

#: The first signed TCC tag, W-4's. Tags before it predate signing: they stay installable, with a
#: line saying so, not refused.
TCC_SIGNED_FROM = "v0.1.45"

#: The developer's switch, the skill's own name (`upkeep.py` SKIP_VERIFY_VAR): `=1` skips the
#: check, and the line shown says it was skipped.
SKIP_VERIFY_VAR = "AUTOSOUND_SKIP_TAG_VERIFY"


def allowed_signers_line(principal: str = TCC_SIGNING_PRINCIPAL,
                         key: str = TCC_SIGNING_KEY) -> str:
    """One `allowed_signers` line in the form git's SSH verification reads: who, the `git`
    namespace, the key. The updater writes it to a temporary file; the repository's file holds it."""
    return f'{principal} namespaces="git" {key}'


#: git checks an SSH signature with `gpg.ssh.program`, and somebody who signs through a helper
#: (1Password's) has it set to that helper: through it a good release was refused (T-35, R-bc,
#: #174). Pinned to git's own default on the command line, where it outranks every config file.
VERIFY_PROGRAM = ("-c", "gpg.ssh.program=ssh-keygen")


def verify_env(parent: Mapping[str, str]) -> dict[str, str]:
    """The environment `git verify-tag` runs in: `parent` with git's messages in English and the
    charset `parent` ran (R-bd, R-bf, R-bg, #174).

    The updater reads git's answer by its sentences (`core/updates._CANNOT_CHECK`), and git ships
    translations, Ukrainian among them. So `LC_MESSAGES=C`; `LC_ALL` goes, because it would
    override that, and `LANGUAGE` goes, because gettext reads it before the locale. The charset
    stays: a non-empty `LC_ALL` outranked `LC_CTYPE` in `parent`, so its value becomes the
    child's `LC_CTYPE`, and a non-ASCII temp path (a Cyrillic Windows user name) is passed as it
    was. An empty `LC_ALL` counts as unset (POSIX). Nothing else changes, `parent` included."""
    env = {name: value for name, value in parent.items() if name not in ("LC_ALL", "LANGUAGE")}
    if parent.get("LC_ALL"):
        env["LC_CTYPE"] = parent["LC_ALL"]
    env["LC_MESSAGES"] = "C"
    return env
