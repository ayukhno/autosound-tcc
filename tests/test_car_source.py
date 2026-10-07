"""G13 C1: copying a car takes its source through one interface; a folder is the first source."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from autosound_tcc.ui.tcc import car_source
from autosound_tcc.ui.tcc.car_source import Chooser, FolderSource, Line, Picker, Resolved


class _Counting:
    """A file source that counts what it opens and lets go of."""

    chooser = Chooser("file", "npBrowse", "npSeedFrom")

    def __init__(self) -> None:
        self.resolved = []
        self.released = 0

    def accepts(self, path):
        return path.suffix == ".car"

    def resolve(self, path):
        self.resolved.append(path)
        return Resolved(path.parent)

    def release(self) -> None:
        self.released += 1


def test_the_same_path_is_resolved_once_and_released_on_change(tmp_path):
    source = _Counting()
    picker = Picker([source])
    first, second = tmp_path / "a.car", tmp_path / "b.car"

    assert picker.resolve(str(first)) == Resolved(tmp_path)
    picker.resolve(str(first))
    assert source.resolved == [first], "the same text is not opened twice"

    picker.resolve(str(second))
    assert source.resolved == [first, second] and source.released == 1, "a new path lets go"
    picker.release()
    assert source.released == 2


def test_a_folder_and_a_path_not_made_yet_are_folders(tmp_path):
    picker = Picker()
    assert picker.resolve(str(tmp_path)) == Resolved(tmp_path)
    assert picker.resolve(str(tmp_path / "later")) == Resolved(tmp_path / "later")


def test_a_file_no_source_takes_is_refused_as_not_a_project(tmp_path):
    a_file = tmp_path / "x.zip"
    a_file.write_text("", encoding="utf-8")
    assert Picker().resolve(str(a_file)) == Resolved(None, problem=Line("npSeedNotAProject"))


def test_blank_text_resolves_to_nothing():
    assert Picker().resolve("   ") is None


def test_the_sources_are_read_when_a_picker_is_made(monkeypatch, tmp_path):
    monkeypatch.setattr(car_source, "SOURCES", (_Counting, FolderSource))
    assert Picker().resolve(str(tmp_path / "a.car")) == Resolved(tmp_path)


def test_the_car_source_imports_no_qt():
    done = subprocess.run([sys.executable, "-c", textwrap.dedent("""
        import sys
        from autosound_tcc.ui.tcc import car_source
        print(sorted(m for m in sys.modules if m.split(".")[0] in ("PySide6", "shiboken6")))
    """)], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"


class _Raising:
    """A source whose `accepts` or `resolve` fails the way a package's unpacking can."""

    chooser = Chooser("file", "npBrowse", "npSeedFrom")

    def __init__(self, where="resolve", release_fails=False):
        self.where, self.release_fails, self.released = where, release_fails, 0

    def accepts(self, path):
        if self.where == "accepts":
            raise PermissionError(13, "Permission denied", str(path))
        return path.suffix == ".car"

    def resolve(self, path):
        if self.where == "resolve":
            raise OSError("the package is damaged")
        return Resolved(path.parent)

    def release(self):
        self.released += 1
        if self.release_fails:
            raise PermissionError(32, "The file is in use", "car.tmp")


def test_a_source_that_raises_is_said_not_taken_for_nothing_typed(tmp_path, caplog):
    """A raised fault and a returned refusal end the same way: the copy is refused, in words —
    not remembered as "nothing typed", which made «Copy» create an empty project."""
    source = _Raising("resolve")
    picker = Picker([source])
    broken = str(tmp_path / "broken.car")

    answer = picker.resolve(broken)
    assert answer == Resolved(None, problem=Line("npSeedFailed", {"problem": "the package is damaged"}))
    assert picker.resolve(broken) == answer, "the same text keeps the same answer"
    assert "the package is damaged" in caplog.text and "_Raising" in caplog.text
    picker.resolve(str(tmp_path / "other.car"))
    assert source.released == 1, "what the failed source held is still let go"


def test_a_source_whose_accepts_raises_is_said_too(tmp_path):
    answer = Picker([_Raising("accepts")]).resolve(str(tmp_path / "locked.car"))
    assert answer.folder is None and answer.problem.key == "npSeedFailed"
    assert "Permission denied" in answer.problem.args["problem"]


def test_a_release_that_raises_still_lets_go(tmp_path, caplog):
    """A temporary folder Windows will not delete (a file still held) must not keep the dialog
    open or the picker on the old path."""
    source = _Raising(where="", release_fails=True)
    picker = Picker([source])
    picker.resolve(str(tmp_path / "a.car"))

    picker.resolve(str(tmp_path / "b.car"))  # lets go of a.car: raises inside, said in the log
    picker.release()
    assert source.released == 2
    assert "The file is in use" in caplog.text
    assert picker.resolve(str(tmp_path / "c.car")) == Resolved(tmp_path), "and it moves on"


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="a folder nobody may enter")
def test_a_path_inside_a_folder_nobody_may_enter_is_still_a_folder(tmp_path):
    """`Path.is_file()` raises on EACCES (3.12); the folder source answers, and the seeder then
    says "no readable project.json", as before the picker."""
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        assert Picker().resolve(str(locked / "car")) == Resolved(locked / "car")
    finally:
        locked.chmod(0o700)


def test_a_chooser_of_an_unknown_kind_is_refused():
    with pytest.raises(ValueError, match="kind"):
        Chooser("archive", "npBrowse", "npSeedFrom")


def test_an_answer_with_a_folder_and_a_problem_is_refused(tmp_path):
    """The contract says one or the other: a drawn-as-good source refused only at Create."""
    with pytest.raises(ValueError, match="problem"):
        Resolved(tmp_path, problem=Line("npSeedNotAProject"))


def unknown_source_keys(sources, known) -> list[str]:
    """Every key a source's browse button shows that the strings do not have."""
    lost = []
    for kind in sources:
        chooser = kind.chooser
        for key in (chooser.label_key, chooser.title_key, chooser.filter_key):
            if key and key not in known:
                lost.append(f"{kind.__name__}: {key}")
    return lost


def test_every_key_a_source_shows_exists():
    from autosound_tcc.ui.tcc import i18n

    assert unknown_source_keys(car_source.SOURCES, set(i18n.T["en"])) == []
    assert i18n.t("npSeedFailed").format(problem="x").endswith("x"), "the picker's own refusal"


def test_the_source_key_guard_goes_red_on_a_typo():
    from autosound_tcc.ui.tcc import i18n

    class _Typo:
        chooser = Chooser("file", "npBrowse", "npSeedFromPakage", "noSuchFilter")

    assert unknown_source_keys([_Typo, FolderSource], set(i18n.T["en"])) == [
        "_Typo: npSeedFromPakage", "_Typo: noSuchFilter"]
