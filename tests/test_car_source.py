"""G13 C1: copying a car takes its source through one interface; a folder is the first source."""

from __future__ import annotations

import subprocess
import sys
import textwrap

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
