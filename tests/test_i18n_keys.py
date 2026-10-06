"""G13 B2: a key typed wrong shows on screen as the raw key, and nothing caught it."""

from __future__ import annotations

import ast
from pathlib import Path

from autosound_tcc.ui.tcc import i18n

UI = Path(__file__).resolve().parents[1] / "src" / "autosound_tcc" / "ui"


def literal_keys(source: str) -> set[str]:
    """Every string constant passed first to `i18n.t(...)`, both branches of a conditional there
    included. A key built at run time (a name, an f-string, `+`) is not a literal and is skipped."""
    keys: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and node.args and isinstance(node.func, ast.Attribute)
                and node.func.attr == "t" and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "i18n"):
            continue
        arg = node.args[0]
        branches = [arg.body, arg.orelse] if isinstance(arg, ast.IfExp) else [arg]
        keys |= {b.value for b in branches if isinstance(b, ast.Constant) and isinstance(b.value, str)}
    return keys


def test_the_key_guard_goes_red_on_a_typo():
    source = ('i18n.t("npCancel")\n'
              'i18n.t("noSuchKeyAnywhere")\n'
              'i18n.t("npCreate" if ok else "noSuchOtherKey")\n'
              'i18n.t(name)\n')
    assert literal_keys(source) - set(i18n.T["en"]) == {"noSuchKeyAnywhere", "noSuchOtherKey"}


def test_every_literal_key_the_ui_names_exists():
    missing = {}
    for path in sorted(UI.rglob("*.py")):
        lost = literal_keys(path.read_text(encoding="utf-8")) - set(i18n.T["en"])
        if lost:
            missing[path.relative_to(UI).as_posix()] = sorted(lost)
    assert not missing, missing
