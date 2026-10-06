"""UI strings that live with their feature (G13, #162).

Each feature module here holds `STRINGS = {key: {"en": …, "uk": …, "pl": …, "de": …}}` — plain data
that imports nothing, the four languages of a key side by side (uk and en by the builder; pl and de
the English until the Advisor). `i18n` joins them into its one table in the order of FEATURES,
after its own; a key defined twice is refused there, by name.
"""

from __future__ import annotations

import importlib

#: The feature modules, in join order.
FEATURES: tuple[str, ...] = ()


def tables() -> list[tuple[str, dict[str, dict[str, str]]]]:
    """`[(f"strings.{name}", module.STRINGS), …]` for every module in FEATURES, imported now."""
    return [(f"strings.{name}", importlib.import_module(f"{__name__}.{name}").STRINGS)
            for name in FEATURES]
