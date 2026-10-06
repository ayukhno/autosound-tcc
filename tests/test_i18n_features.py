"""G13 B1: strings per feature, joined into one table; the lookup imports no Qt."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from autosound_tcc.ui.tcc import i18n

LANGS = ("en", "uk", "pl", "de")


def _core(**keys):
    return {lang: dict(keys) for lang in LANGS}


def test_a_key_in_core_and_a_table_is_refused_naming_both():
    with pytest.raises(ValueError) as caught:
        i18n.assemble(_core(a="A"), [("strings.demo", {"a": {lang: "x" for lang in LANGS}})])
    said = str(caught.value)
    assert "'a'" in said and "core" in said and "strings.demo" in said


def test_a_key_in_two_tables_is_refused_naming_both():
    row = {lang: "x" for lang in LANGS}
    with pytest.raises(ValueError) as caught:
        i18n.assemble(_core(), [("strings.one", {"b": row}), ("strings.two", {"b": row})])
    said = str(caught.value)
    assert "'b'" in said and "strings.one" in said and "strings.two" in said


def test_a_row_without_one_of_the_languages_is_refused():
    with pytest.raises(ValueError) as caught:
        i18n.assemble(_core(), [("strings.demo", {"c": {"en": "C", "uk": "C", "pl": "C"}})])
    assert "'c'" in str(caught.value) and "de" in str(caught.value)


def test_a_table_s_rows_reach_every_language():
    out = i18n.assemble(_core(a="A"),
                        [("strings.demo", {"d": {"en": "D", "uk": "Д", "pl": "D", "de": "D"}})])
    assert out["uk"]["d"] == "Д" and out["en"]["a"] == "A" and set(out) == set(LANGS)


def test_the_table_the_app_uses_is_the_join():
    assert i18n.T == i18n.assemble(i18n._CORE, i18n.strings.tables())


def _fresh(code: str) -> str:
    done = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output=True,
                          text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_the_lookup_imports_no_qt():
    loaded = _fresh("""
        import sys
        from autosound_tcc.ui.tcc import i18n
        i18n.t("npCancel")
        print(sorted(m for m in sys.modules if m.split(".")[0] in ("PySide6", "shiboken6")))
    """)
    assert loaded == "[]"


def test_the_copy_strings_live_with_their_feature():
    """G13 B3: the new-project dialog's strings live beside it; the two buttons six dialogs share
    stay in the core table."""
    from autosound_tcc.ui.tcc.strings import new_project

    assert "npSeedSummary" in new_project.STRINGS
    assert "npSeedSummary" not in i18n._CORE["en"]
    assert "npCancel" in i18n._CORE["en"] and "npBrowse" in i18n._CORE["en"]


def _strings_modules():
    from pathlib import Path

    folder = Path(i18n.strings.__file__).parent
    return sorted(path for path in folder.glob("*.py") if path.stem != "__init__")


def test_every_strings_module_is_joined():
    assert [path.stem for path in _strings_modules()] == sorted(i18n.strings.FEATURES)


def _imports(source: str) -> list:
    import ast

    return [node for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.Import, ast.ImportFrom))]


def test_a_strings_module_imports_nothing():
    for path in _strings_modules():
        assert not _imports(path.read_text(encoding="utf-8")), path.name


def test_the_imports_guard_goes_red_on_an_import():
    assert _imports("import os\nSTRINGS = {}\n")
    assert not _imports("STRINGS = {'a': {'en': 'b'}}\n")
