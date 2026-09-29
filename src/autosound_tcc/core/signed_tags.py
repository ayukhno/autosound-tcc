"""Who signs TCC's own release tags: the trust anchor the updater checks them against (tcc#102,
hub #83 HUB-032).

A CONSTANT, never a file read from the tag being verified: a tag's own `allowed_signers` would
vouch for itself. The skill holds its anchor the same way (`upkeep.py` SIGNING_KEY, skill #99);
TCC's own sits here, apart from `scripts/ship.py`, so the updater can import it without importing
the release script. `allowed_signers` at the repository root carries the same line for people and
for `git verify-tag`, and `tests/test_signed_tags.py` holds the two equal.

Named `TCC_*` because the skill's anchor stands beside it in `core/updates.py` as `SKILL_*`: the
same key today, two facts — each is held to its own file.
"""
from __future__ import annotations

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
