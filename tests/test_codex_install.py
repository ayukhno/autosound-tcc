"""TCC's own Codex from the official wheel (`core/codex_install.py`, W-10 tcc#181 task 9).

No real download: a small wheel is built here with the real member layout and modes
(`tests/fixtures/codex/wheel-0.162.1.json`) and served through `opener`, with a PyPI JSON answer
beside it. The pinned digests are the module's own — a test that serves its fake wheel swaps the
pinned row for the fake's, the way a release would pin a new one. Every failure leaves nothing:
no temp file, no half folder, and an older complete copy untouched.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import sys
import time
import zipfile
from pathlib import Path

import pytest

from autosound_tcc.core import codex_cli, codex_install
from autosound_tcc.core.codex_install import InstallError

HERE = Path(__file__).parent
LAYOUT = json.loads((HERE / "fixtures" / "codex" / "wheel-0.162.1.json").read_text())
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="the fake codex is a POSIX script")
KEY = "macos-arm64"
ROW = LAYOUT["wheels"][KEY]
INDEX_URL = codex_install.INDEX_URL
FILE_URL = "https://files.pythonhosted.org/packages/xx/" + ROW["filename"]

_REAL_FIND = codex_cli.find


def _codex_says(version: str) -> bytes:
    return f"#!{sys.executable}\nprint('codex-cli {version}')\n".encode()


def _wheel(*, says: str = codex_cli.PIN, extra: list[tuple[str, bytes, int]] = ()) -> bytes:
    """The wheel's members as the fixture lists them, each with its mode; `bin/codex` a script
    that says `says`; the dist-info as a real wheel has it."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for member in ROW["members"]:
            path = member["path"]
            data = _codex_says(says) if path == ROW["binary"] else f"{path}\n".encode()
            info = zipfile.ZipInfo(path)
            info.external_attr = int(member["mode"], 8) << 16
            zf.writestr(info, data)
        for path in ROW["dist_info"]:
            zf.writestr(path, "x\n")
        for path, data, mode in extra:
            info = zipfile.ZipInfo(path)
            info.external_attr = mode << 16
            zf.writestr(info, data)
    return buf.getvalue()


class _Response(io.BytesIO):
    def __init__(self, data: bytes, url: str) -> None:
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}
        self._url = url

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class _Opener:
    """`urlopen` for the index and the file; records every url asked."""

    def __init__(self, wheel: bytes, *, json_sha: str | None = None, file_url: str = FILE_URL):
        self.wheel = wheel
        self.asked: list[str] = []
        self.index = {"urls": [{
            "filename": ROW["filename"], "url": file_url, "size": len(wheel),
            "digests": {"sha256": json_sha or hashlib.sha256(wheel).hexdigest()}}]}

    def __call__(self, url, timeout=None):
        url = getattr(url, "full_url", url)
        self.asked.append(url)
        if url == INDEX_URL:
            return _Response(json.dumps(self.index).encode(), url)
        if url == self.index["urls"][0]["url"]:
            return _Response(self.wheel, url)
        raise AssertionError(f"unexpected url {url}")


@pytest.fixture(autouse=True)
def _no_system_folders(monkeypatch):
    """`/opt/homebrew/bin` is this developer's: the trees here are the tests' own."""
    monkeypatch.setattr(codex_cli, "SYSTEM_FOLDERS", ())


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


@pytest.fixture
def target(home):
    """Where `find()` looks for TCC's copy on this test's home (macOS layout on a Mac)."""
    return codex_cli.tcc_copy_path(home=home, environ={}, windows=False)


def _pin(monkeypatch, wheel: bytes) -> None:
    """Pin the fake wheel's digest in the module, as a release pins the real one."""
    monkeypatch.setitem(codex_install.WHEELS, KEY, codex_install.Wheel(
        ROW["filename"], hashlib.sha256(wheel).hexdigest()))


def _install(opener, target, **kw):
    seen: list[tuple[int, int]] = []
    path = codex_install.install(lambda done, total: seen.append((done, total)),
                                 kw.pop("cancelled", lambda: False), opener=opener,
                                 target=target, platform=KEY, **kw)
    return path, seen


def _left(folder: Path) -> list[str]:
    """Everything under the `codex/` folder, relative — what a failure must not leave."""
    if not folder.exists():
        return []
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


def _version_folder(target: Path) -> Path:
    return target.parents[2]  # …/codex/<PIN>


# ---- the pinned source ---------------------------------------------------------------------


def test_the_four_digests_pinned_in_the_source_are_the_fixture_s():
    assert {key: (w.filename, w.sha256) for key, w in codex_install.WHEELS.items()} == {
        key: (row["filename"], row["sha256"]) for key, row in LAYOUT["wheels"].items()}


def test_the_index_is_pypi_s_json_for_the_pinned_version_over_https():
    assert codex_install.INDEX_URL == (
        f"https://pypi.org/pypi/openai-codex-cli-bin/{codex_cli.PIN}/json")


@pytest.mark.parametrize("platform_, machine, key", [
    ("darwin", "arm64", "macos-arm64"), ("darwin", "x86_64", "macos-x86_64"),
    ("win32", "AMD64", "windows-amd64"), ("win32", "ARM64", "windows-arm64"),
    ("linux", "x86_64", None), ("darwin", "ppc", None)])
def test_the_platform_picks_its_wheel(platform_, machine, key):
    assert codex_install.platform_key(platform_, machine) == key


def test_an_unsupported_platform_is_a_sentence_saying_where_to_get_codex(target):
    with pytest.raises(InstallError) as caught:
        codex_install.install(lambda *_: None, lambda: False, opener=_Opener(b""),
                              target=target, platform=None)
    said = str(caught.value)
    assert "Codex" in said and "https://" in said
    assert caught.value.key == "codexInstallUnsupported"
    assert _left(target.parents[3]) == []


# ---- a whole install -----------------------------------------------------------------------


@POSIX_ONLY
def test_the_wheel_is_unpacked_whole_with_its_modes_and_find_sees_tcc_s_copy(
        monkeypatch, home, target):
    wheel = _wheel()
    _pin(monkeypatch, wheel)
    opener = _Opener(wheel)

    path, seen = _install(opener, target)

    assert path == target and target.is_file()
    root = target.parents[1]  # …/codex_cli_bin
    for member in ROW["members"]:
        unpacked = root.parent / member["path"]
        assert unpacked.is_file(), member["path"]
        assert stat.S_IMODE(unpacked.stat().st_mode) == int(member["mode"], 8) & 0o777
    assert not (_version_folder(target) / ROW["dist_info"][0]).exists(), "dist-info is not Codex"
    assert opener.asked == [INDEX_URL, FILE_URL]
    assert seen and seen[-1] == (len(wheel), len(wheel))
    pin = codex_cli.PIN
    assert _left(target.parents[3]) == sorted([pin] + [f"{pin}/{p}" for p in (
        "codex_cli_bin", "codex_cli_bin/__init__.py", "codex_cli_bin/codex-package.json",
        "codex_cli_bin/bin", "codex_cli_bin/bin/codex", "codex_cli_bin/bin/codex-code-mode-host",
        "codex_cli_bin/codex-path", "codex_cli_bin/codex-path/rg", "codex_cli_bin/codex-resources",
        "codex_cli_bin/codex-resources/zsh", "codex_cli_bin/codex-resources/zsh/bin",
        "codex_cli_bin/codex-resources/zsh/bin/zsh")]), "no temp file left beside it"
    found = _REAL_FIND(environ={"PATH": ""}, home=home, windows=False)
    assert found is not None and found.source == codex_cli.SOURCE_TCC and Path(found.path) == target


@POSIX_ONLY
def test_executables_get_x_even_when_the_zip_carries_no_mode(monkeypatch, target):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for member in ROW["members"]:
            data = _codex_says(codex_cli.PIN) if member["path"] == ROW["binary"] else b"x"
            zf.writestr(zipfile.ZipInfo(member["path"]), data)  # external_attr 0
    wheel = buf.getvalue()
    _pin(monkeypatch, wheel)

    _install(_Opener(wheel), target)

    root = target.parents[1]
    for rel in ("bin/codex", "bin/codex-code-mode-host", "codex-path/rg"):
        assert os.access(root / rel, os.X_OK), rel


@POSIX_ONLY
def test_a_new_copy_replaces_an_older_one_only_once_whole(monkeypatch, target):
    old = _version_folder(target)
    (old / "codex_cli_bin" / "bin").mkdir(parents=True)
    (old / "codex_cli_bin" / "stale.txt").write_text("old")
    wheel = _wheel()
    _pin(monkeypatch, wheel)

    _install(_Opener(wheel), target)

    assert target.is_file()
    assert not (old / "codex_cli_bin" / "stale.txt").exists(), "the old copy is gone, not merged"
    assert [p.name for p in old.parent.iterdir()] == [codex_cli.PIN]


@POSIX_ONLY
def test_after_an_install_the_next_find_and_probe_look_again(monkeypatch, target):
    wheel = _wheel()
    _pin(monkeypatch, wheel)
    calls: list[str] = []
    monkeypatch.setattr(codex_cli, "reset", lambda: calls.append("reset"))
    monkeypatch.setattr(codex_cli, "forget", lambda: calls.append("forget"))

    _install(_Opener(wheel), target)

    assert calls == ["forget"], "found again — and the versions already read are kept"


@POSIX_ONLY
def test_an_install_keeps_a_too_old_reading_so_the_old_codex_stays_passed_over(
        monkeypatch, tmp_path, target):
    """The review's M1: a wipe of the versions read made `find()` answer the old Codex on PATH
    again until the next probe ended — «Sign in» on it, the blocker silent."""
    old = tmp_path / "old" / "codex"
    old.parent.mkdir()
    old.write_bytes(b"old")
    found_old = codex_cli.Found(str(old), codex_cli.SOURCE_PATH)
    monkeypatch.setitem(codex_cli._VERSIONS, codex_cli._stamp(found_old), (0, 150, 0))
    wheel = _wheel()
    _pin(monkeypatch, wheel)

    _install(_Opener(wheel), target)

    assert codex_cli.known_version(found_old) == (0, 150, 0)
    assert codex_cli.too_old(found_old)


# ---- nothing half-done ---------------------------------------------------------------------


def _old_copy(target: Path) -> Path:
    marker = _version_folder(target) / "codex_cli_bin" / "bin" / "codex"
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"the older complete copy")
    return marker


def _assert_nothing_left(target: Path, marker: Path) -> None:
    assert marker.read_bytes() == b"the older complete copy", "the older copy untouched"
    codex_folder = target.parents[3]
    assert sorted(p.name for p in codex_folder.iterdir()) == [codex_cli.PIN], \
        "no temp file, no staging folder"
    assert _left(_version_folder(target)) == ["codex_cli_bin", "codex_cli_bin/bin",
                                             "codex_cli_bin/bin/codex"]


def test_a_file_whose_digest_is_not_the_pinned_one_leaves_nothing(monkeypatch, target):
    marker = _old_copy(target)
    wheel = _wheel()
    monkeypatch.setitem(codex_install.WHEELS, KEY, codex_install.Wheel(ROW["filename"], "0" * 64))
    # The index agrees with the pin, the file does not.
    opener = _Opener(wheel, json_sha="0" * 64)

    with pytest.raises(InstallError) as caught:
        _install(opener, target)

    assert caught.value.key == "codexInstallMismatch"
    _assert_nothing_left(target, marker)


def test_an_index_whose_digest_is_not_the_pinned_one_downloads_nothing(monkeypatch, target):
    marker = _old_copy(target)
    wheel = _wheel()
    _pin(monkeypatch, wheel)
    opener = _Opener(wheel, json_sha="f" * 64)  # a swapped index answer, file and all

    with pytest.raises(InstallError) as caught:
        _install(opener, target)

    assert caught.value.key == "codexInstallMismatch"
    assert opener.asked == [INDEX_URL], "the file is not even asked for"
    _assert_nothing_left(target, marker)


def test_a_file_url_that_is_not_https_is_refused(monkeypatch, target):
    wheel = _wheel()
    _pin(monkeypatch, wheel)
    opener = _Opener(wheel, file_url="http://files.pythonhosted.org/" + ROW["filename"])

    with pytest.raises(InstallError):
        _install(opener, target)

    assert opener.asked == [INDEX_URL]


@pytest.mark.parametrize("bad", ["../evil", "codex_cli_bin/../../evil", "/etc/evil",
                                 "elsewhere/file", "codex_cli_bin/bin/..\\..\\evil"])
def test_a_member_outside_the_codex_folder_refuses_the_whole_wheel(monkeypatch, target, bad):
    marker = _old_copy(target)
    wheel = _wheel(extra=[(bad, b"evil", 0o644)])
    _pin(monkeypatch, wheel)

    with pytest.raises(InstallError) as caught:
        _install(_Opener(wheel), target)

    assert caught.value.key == "codexInstallBadWheel"
    _assert_nothing_left(target, marker)
    assert not (target.parents[3] / "evil").exists()
    assert not (target.parents[4] / "evil").exists()


@POSIX_ONLY
def test_a_symlink_member_refuses_the_whole_wheel(monkeypatch, target):
    marker = _old_copy(target)
    wheel = _wheel(extra=[("codex_cli_bin/link", b"/etc/passwd", stat.S_IFLNK | 0o777)])
    _pin(monkeypatch, wheel)

    with pytest.raises(InstallError):
        _install(_Opener(wheel), target)

    _assert_nothing_left(target, marker)


def test_a_cancel_mid_download_leaves_nothing(monkeypatch, target):
    marker = _old_copy(target)
    wheel = _wheel() + b""  # one chunk is enough: the cancel is read between chunks
    _pin(monkeypatch, wheel)
    monkeypatch.setattr(codex_install, "CHUNK", 64)
    asked = {"n": 0}

    def cancelled() -> bool:
        asked["n"] += 1
        return asked["n"] > 2

    with pytest.raises(InstallError) as caught:
        _install(_Opener(wheel), target, cancelled=cancelled)

    assert caught.value.key == "codexInstallCancelled"
    _assert_nothing_left(target, marker)


def test_a_disk_error_mid_unpack_leaves_nothing(monkeypatch, target):
    marker = _old_copy(target)
    wheel = _wheel()
    _pin(monkeypatch, wheel)
    real = codex_install._copy
    count = {"n": 0}

    def full(src, dst):
        count["n"] += 1
        if count["n"] == 3:
            raise OSError(28, "No space left on device")
        return real(src, dst)

    monkeypatch.setattr(codex_install, "_copy", full)

    with pytest.raises(InstallError) as caught:
        _install(_Opener(wheel), target)

    assert caught.value.key == "codexInstallDisk"
    assert "No space left" in str(caught.value)
    _assert_nothing_left(target, marker)


def test_a_network_error_is_a_sentence_and_leaves_nothing(monkeypatch, target):
    marker = _old_copy(target)

    def offline(url, timeout=None):
        raise OSError("network is unreachable")

    with pytest.raises(InstallError) as caught:
        _install(offline, target)

    assert caught.value.key == "codexInstallNetwork"
    _assert_nothing_left(target, marker)


@POSIX_ONLY
def test_a_binary_that_does_not_say_the_pinned_version_is_removed(monkeypatch, target):
    marker = _old_copy(target)
    wheel = _wheel(says="0.150.0")
    _pin(monkeypatch, wheel)

    with pytest.raises(InstallError) as caught:
        _install(_Opener(wheel), target)

    assert caught.value.key == "codexInstallWrongVersion"
    assert "0.150.0" in str(caught.value)
    _assert_nothing_left(target, marker)


def test_a_failure_with_no_older_copy_leaves_no_folder_at_all(monkeypatch, target):
    wheel = _wheel()
    monkeypatch.setitem(codex_install.WHEELS, KEY, codex_install.Wheel(ROW["filename"], "0" * 64))

    with pytest.raises(InstallError):
        _install(_Opener(wheel, json_sha="0" * 64), target)

    assert _left(target.parents[3]) == []


def test_the_install_never_touches_anything_outside_its_folder(monkeypatch, tmp_path, target):
    """No admin, no Node, no Homebrew: the only paths written are under TCC's `codex/` folder."""
    wheel = _wheel()
    _pin(monkeypatch, wheel)
    before = {p for p in tmp_path.rglob("*")}
    try:
        _install(_Opener(wheel), target)
    except InstallError:
        pass  # on Windows the fake codex cannot run; what was written is the question here
    codex_folder = target.parents[3]
    for path in set(tmp_path.rglob("*")) - before:
        assert path == codex_folder or codex_folder in path.parents \
            or path in codex_folder.parents, path


# ---- the fix round of the task review (M2–M7) ----------------------------------------------


def test_a_redirect_to_plain_http_is_refused(monkeypatch, target):
    marker = _old_copy(target)
    wheel = _wheel()
    _pin(monkeypatch, wheel)

    class Redirected(_Opener):
        def __call__(self, url, timeout=None):
            response = super().__call__(url, timeout)
            if url == FILE_URL:
                response._url = "http://files.pythonhosted.org/" + ROW["filename"]
            return response

    with pytest.raises(InstallError) as caught:
        _install(Redirected(wheel), target)

    assert "http://" in str(caught.value)
    _assert_nothing_left(target, marker)


def test_a_content_length_that_is_not_a_number_is_not_an_error(monkeypatch, target):
    wheel = _wheel()
    _pin(monkeypatch, wheel)

    class Garbled(_Opener):
        def __call__(self, url, timeout=None):
            response = super().__call__(url, timeout)
            response.headers = {"Content-Length": "lots"}
            return response

    seen: list[tuple[int, int]] = []
    if os.name == "nt":
        pytest.skip("the fake codex is a POSIX script")
    codex_install.install(lambda d, t: seen.append((d, t)), lambda: False, opener=Garbled(wheel),
                          target=target, platform=KEY)
    assert seen[-1] == (len(wheel), len(wheel)), "the index's size stands in"


@POSIX_ONLY
def test_a_failed_rename_puts_the_old_copy_back(monkeypatch, target):
    marker = _old_copy(target)
    wheel = _wheel()
    _pin(monkeypatch, wheel)
    monkeypatch.setattr(codex_install, "RETRY_DELAYS", (0, 0))
    real = codex_install._replace

    def refuse_the_new_one(src, dst):
        if ".0.162.1-new-" in str(src) or "-new-" in Path(src).name:
            raise PermissionError(13, "in use")
        return real(src, dst)

    monkeypatch.setattr(codex_install, "_replace", refuse_the_new_one)

    with pytest.raises(InstallError) as caught:
        _install(_Opener(wheel), target)

    assert caught.value.key == "codexInstallDisk"
    _assert_nothing_left(target, marker)


@POSIX_ONLY
def test_a_rename_refused_for_a_moment_is_tried_again(monkeypatch, target):
    """Windows: a fresh .exe under a Defender scan refuses a rename for a moment."""
    wheel = _wheel()
    _pin(monkeypatch, wheel)
    monkeypatch.setattr(codex_install, "RETRY_DELAYS", (0, 0, 0))
    real = codex_install._replace
    refused = {"n": 0}

    def flaky(src, dst):
        if "-new-" in Path(src).name and refused["n"] < 2:
            refused["n"] += 1
            raise PermissionError(13, "being scanned")
        return real(src, dst)

    monkeypatch.setattr(codex_install, "_replace", flaky)

    path, _seen = _install(_Opener(wheel), target)

    assert path.is_file() and refused["n"] == 2


def test_a_cancel_mid_unpack_leaves_nothing(monkeypatch, target):
    marker = _old_copy(target)
    wheel = _wheel()
    _pin(monkeypatch, wheel)
    state = {"cancel": False}
    real = codex_install._copy

    def copy_then_cancel(src, dst):
        real(src, dst)
        state["cancel"] = True

    monkeypatch.setattr(codex_install, "_copy", copy_then_cancel)

    with pytest.raises(InstallError) as caught:
        _install(_Opener(wheel), target, cancelled=lambda: state["cancel"])

    assert caught.value.key == "codexInstallCancelled"
    _assert_nothing_left(target, marker)


def test_the_version_check_waits_long_enough_and_an_unread_version_is_said_so(monkeypatch, target):
    marker = _old_copy(target)
    wheel = _wheel()
    _pin(monkeypatch, wheel)
    asked: list[float] = []

    def unread(found, timeout=None):
        asked.append(timeout)
        return None

    monkeypatch.setattr(codex_cli, "version", unread)

    with pytest.raises(InstallError) as caught:
        _install(_Opener(wheel), target)

    assert asked and asked[0] >= 60, "a first run under a virus scan is slow"
    assert caught.value.key == "codexInstallUnreadVersion"
    assert "could not" in str(caught.value) and "unknown" not in str(caught.value)
    _assert_nothing_left(target, marker)


@POSIX_ONLY
def test_a_staging_folder_that_will_not_go_is_named_in_the_log(monkeypatch, target, caplog):
    wheel = _wheel(says="0.150.0")
    _pin(monkeypatch, wheel)
    monkeypatch.setattr(codex_install.shutil, "rmtree", lambda *a, **k: None)

    with caplog.at_level("WARNING"), pytest.raises(InstallError):
        _install(_Opener(wheel), target)

    left = [p for p in target.parents[3].iterdir() if "-new-" in p.name]
    assert left and str(left[0]) in caplog.text


@POSIX_ONLY
def test_leftovers_of_an_install_cut_short_are_swept_and_a_fresh_one_is_not(monkeypatch, target):
    codex_dir = target.parents[3]
    codex_dir.mkdir(parents=True)
    stale_part = codex_dir / ".codex-abc.whl.part"
    stale_part.write_bytes(b"half")
    stale_new = codex_dir / f".{codex_cli.PIN}-new-xyz"
    (stale_new / "codex_cli_bin").mkdir(parents=True)
    stale_old = codex_dir / f".{codex_cli.PIN}-old-xyz"
    stale_old.mkdir()
    long_ago = time.time() - 3 * 3600
    for path in (stale_part, stale_new, stale_new / "codex_cli_bin", stale_old):
        os.utime(path, (long_ago, long_ago))
    fresh = codex_dir / ".codex-another-process.whl.part"
    fresh.write_bytes(b"still coming")
    unrelated = codex_dir / "notes.txt"
    unrelated.write_text("mine")
    wheel = _wheel()
    _pin(monkeypatch, wheel)

    _install(_Opener(wheel), target)

    assert not stale_part.exists() and not stale_new.exists() and not stale_old.exists()
    assert fresh.exists(), "another TCC may be downloading it right now"
    assert unrelated.exists()


@POSIX_ONLY
def test_a_complete_copy_put_there_by_another_install_is_a_success(monkeypatch, target):
    """Two TCCs installing at once: the second's rename fails, yet Codex is there and whole."""
    wheel = _wheel()
    _pin(monkeypatch, wheel)

    def the_other_won(staging, folder):
        shutil.copytree(staging, folder)
        raise InstallError("the rename lost the race", key="codexInstallDisk", error="ENOTEMPTY")

    monkeypatch.setattr(codex_install, "_place", the_other_won)

    path, _seen = _install(_Opener(wheel), target)

    assert path == target and target.is_file()
    assert [p.name for p in target.parents[3].iterdir()] == [codex_cli.PIN]
