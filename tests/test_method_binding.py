"""`core.method_binding` — which copy of the method a project runs, and whether TCC trusts it (#169, G5 S1).

Every writer started TCC's own `process.py` whatever the project linked (`process_writer.script_path`),
and `vendor_loader.link_skill_into` leaves an existing link alone whatever it points at. Decision 2: a
link is trusted when it is a copy TCC knows, or one approved once on this machine — HUB-050's reason is
where a copy came from, not what it looks like. What is tested here, on real folders: the table of
states, the «is a link» rule where a parent folder is itself a link, the contract number read without
importing the file, approving, and moving an entry aside to re-link TCC's copy. Nothing calls the module
yet (Tasks 5, 7, 9, 10, 11 wire it in).

The copies of the method are the vendored tree copied under the session's temp folder, with the one
file a test needs changed — `vendor/` itself is never touched.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import pytest

from autosound_tcc.core import config, method_binding, vendor_loader

#: TCC's own copy in a checkout. Every second copy below is made from it.
_SKILL = vendor_loader._SUBMODULE_DIR

pytestmark = pytest.mark.skipif(
    not vendor_loader._looks_like_the_skill(_SKILL),
    reason="the vendored method is not checked out (git submodule update --init --recursive)",
)

_windows_only = pytest.mark.skipif(sys.platform != "win32", reason="a junction is Windows' own link")

#: What a project's entry can be a link of. A symlink everywhere; a junction on Windows, which is
#: what `link_skill_into` falls back to there and what the skill's own installer makes — and which
#: answers False to `is_symlink()`, and when broken to `exists()` too. The junction rows can only go
#: green on the Windows CI shard; their symlink twins are the ones seen red here.
LINKS = ["symlink", pytest.param("junction", marks=_windows_only)]


def _entry(project: Path) -> Path:
    return project / ".claude" / "skills" / vendor_loader.SKILL_NAME


def _link(entry: Path, target: Path, kind: str = "symlink") -> Path:
    entry.parent.mkdir(parents=True, exist_ok=True)
    if kind == "junction":
        import _winapi

        _winapi.CreateJunction(str(target), str(entry))
    else:
        entry.symlink_to(target, target_is_directory=True)
    return entry


def _same_path(a, b) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _is_a_link(path: Path) -> bool:
    """A symlink or a junction, by the rule the module uses — `os.path.islink` misses a junction."""
    return os.path.normcase(os.path.realpath(path)) != os.path.normcase(
        os.path.join(os.path.realpath(path.parent), path.name))


def _copy_of_the_method(root: Path, *, contract_line: str = "") -> Path:
    """The vendored skill folder at `root/skills/autosound-tuning`, the layout of its own repository."""
    skill = root / "skills" / vendor_loader.SKILL_NAME
    shutil.copytree(_SKILL, skill, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if contract_line:
        contract = skill / "rew_tool" / "contract.py"
        contract.write_text(contract.read_text(encoding="utf-8") + f"\n{contract_line}\n",
                            encoding="utf-8")
    return skill


@pytest.fixture(scope="session")
def other_copy(tmp_path_factory) -> Path:
    """A second copy of the method in a repository of its own: the manifest beside `skills/`."""
    root = tmp_path_factory.mktemp("other-method") / "autosound-tuning-skill"
    skill = _copy_of_the_method(root)
    (root / ".claude-plugin").mkdir()
    shutil.copy2(_SKILL.parents[1] / ".claude-plugin" / "plugin.json",
                 root / ".claude-plugin" / "plugin.json")
    return skill


@pytest.fixture(scope="session")
def bare_copy(tmp_path_factory) -> Path:
    """A copy with no manifest and no `.git` above it: a skill folder unpacked on its own."""
    return _copy_of_the_method(tmp_path_factory.mktemp("bare-method"))


@pytest.fixture(scope="session")
def newer_copy(tmp_path_factory) -> Path:
    """A copy whose `contract.py` speaks a contract this TCC does not. No released copy carries a
    number yet (v3.1.1's `contract.py` has none), so the one file is changed by hand (Ruling 3)."""
    return _copy_of_the_method(tmp_path_factory.mktemp("newer-method"),
                               contract_line="CONTRACT_VERSION = 1")


@pytest.fixture(autouse=True)
def _tcc_runs_its_submodule(monkeypatch):
    """TCC's own copy is the submodule here, whatever the developer's shell points the override at.
    `HOME` is the test's `tmp_path` (conftest), so the personal and plugin installs are the test's."""
    monkeypatch.delenv(vendor_loader.SKILL_DIR_ENV, raising=False)
    assert vendor_loader.skill_dir() == _SKILL


@pytest.fixture
def project(tmp_path) -> Path:
    folder = tmp_path / "car"
    folder.mkdir()
    return folder


# ---- the table, one row at a time ------------------------------------------------------------


def test_no_entry_runs_tccs_own_copy(project):
    binding = method_binding.for_project(project)

    own = vendor_loader.skill_dir()
    assert (binding.state, binding.skill_dir, binding.entry) == ("same", own, _entry(project))
    assert (binding.reason, binding.can_approve) == ("", False)
    assert binding.project_dir == project
    assert binding.require() == own
    assert binding.script("state/process.py") == own / "rew_tool" / "state" / "process.py"
    assert binding.session_env() == {"AUTOSOUND_SKILL_ROOT": str(own)}
    assert binding.plugin_root() == vendor_loader.skill_repo_root(), "found the way TCC finds its own"


@pytest.mark.parametrize("kind", LINKS)
def test_a_link_to_tccs_own_copy_is_same(project, kind):
    _link(_entry(project), vendor_loader.skill_dir(), kind)

    binding = method_binding.for_project(project)

    assert (binding.state, binding.skill_dir) == ("same", vendor_loader.skill_dir())
    assert not binding.can_approve


def test_the_link_tcc_makes_itself_is_same(project):
    assert vendor_loader.link_skill_into(project) == _entry(project)

    assert method_binding.for_project(project).state == "same"


@pytest.mark.parametrize("kind", LINKS)
@pytest.mark.parametrize("installed_as", ["personal", "plugin"])
def test_a_link_to_another_copy_tcc_finds_is_known(project, other_copy, kind, installed_as):
    """`_candidates()` yields the paths it found, and an installed copy is a link into its clone —
    so a copy is known by its realpath, never by the path it was found at."""
    claude = Path.home() / ".claude"
    found_at = {
        "personal": claude / "skills" / vendor_loader.SKILL_NAME,
        "plugin": claude / "plugins" / "marketplaces" / "autosound-tuning-skill" / "skills"
        / vendor_loader.SKILL_NAME,
    }[installed_as]
    _link(found_at, other_copy)  # what the installer leaves there
    assert found_at in list(vendor_loader._candidates())
    _link(_entry(project), other_copy, kind)

    binding = method_binding.for_project(project)

    assert binding.state == "known", binding.reason
    assert binding.skill_dir == Path(os.path.realpath(other_copy))
    assert not binding.can_approve
    assert binding.session_env() == {"AUTOSOUND_SKILL_ROOT": str(binding.skill_dir)}


@pytest.mark.parametrize("kind", LINKS)
def test_a_link_to_a_copy_approved_on_this_machine_is_approved(project, other_copy, kind):
    assert config.approve_method(other_copy) is True
    _link(_entry(project), other_copy, kind)

    binding = method_binding.for_project(project)

    real = Path(os.path.realpath(other_copy))
    assert (binding.state, binding.skill_dir, binding.can_approve) == ("approved", real, False)
    assert binding.require() == real
    assert binding.script("state/process.py") == real / "rew_tool" / "state" / "process.py"
    assert binding.session_env() == {"AUTOSOUND_SKILL_ROOT": str(real)}
    assert binding.plugin_root() == real.parents[1], "the manifest beside `skills/` marks its repo"


@pytest.mark.parametrize("kind", LINKS)
def test_a_link_to_a_copy_tcc_does_not_know_is_refused_and_can_be_approved(project, other_copy, kind):
    entry = _link(_entry(project), other_copy, kind)

    binding = method_binding.for_project(project)

    assert (binding.state, binding.can_approve, binding.skill_dir) == ("refused", True, None)
    assert str(entry) in binding.reason and os.path.realpath(other_copy) in binding.reason
    assert "approve" in binding.reason
    with pytest.raises(method_binding.MethodRefused) as caught:
        binding.require()
    assert str(caught.value) == binding.reason
    with pytest.raises(method_binding.MethodRefused):
        binding.script("state/process.py")
    assert binding.session_env() == {}
    assert binding.plugin_root() is None


@pytest.mark.parametrize("kind", LINKS)
def test_a_broken_link_is_refused_and_cannot_be_approved(project, tmp_path, kind):
    """What a project shared between a Mac and a VM carries: a link to a folder on the other side."""
    gone = tmp_path / "unplugged-drive" / vendor_loader.SKILL_NAME
    gone.mkdir(parents=True)
    entry = _link(_entry(project), gone, kind)
    gone.rmdir()
    assert os.path.lexists(entry) and not entry.exists()

    binding = method_binding.for_project(project)

    assert (binding.state, binding.can_approve, binding.skill_dir) == ("refused", False, None)
    assert str(entry) in binding.reason
    assert "which is not on this machine" in binding.reason
    assert os.path.normcase(os.path.realpath(gone)) in os.path.normcase(binding.reason)


@pytest.mark.parametrize("kind", LINKS)
def test_a_link_into_the_project_is_refused(project, other_copy, kind):
    """Even to a whole 3.x copy: what lives in the project came from wherever the project did."""
    inside = project / "copies" / vendor_loader.SKILL_NAME
    shutil.copytree(other_copy, inside)
    entry = _link(_entry(project), inside, kind)

    binding = method_binding.for_project(project)

    assert (binding.state, binding.can_approve, binding.skill_dir) == ("refused", False, None)
    assert str(entry) in binding.reason and "inside the project" in binding.reason


# ---- «inside the project» is what a folder IS, not how a link spells it ------------------------
# `realpath` keeps whatever spelling the link wrote, and on macOS `normcase` changes nothing: the
# project's own copy, spelled `CAR`, in NFD, or through `/System/Volumes/Data`, read as a copy from
# outside — offered for approval, and approved (review of 4f83676, C1).


def _case_insensitive(folder: Path) -> bool:
    probe = folder / "Probe-Of-Case"
    probe.mkdir()
    try:
        return os.path.exists(folder / "PROBE-OF-CASE")
    finally:
        probe.rmdir()


def _refused_as_inside(project: Path) -> None:
    binding = method_binding.for_project(project)
    assert (binding.state, binding.can_approve, binding.skill_dir) == ("refused", False, None), \
        binding.reason
    assert "inside the project" in binding.reason
    with pytest.raises(method_binding.MethodRefused):
        method_binding.approve(binding)
    assert config.approved_methods() == ()


@pytest.mark.parametrize("written", ["relative", "absolute"])
def test_a_link_into_the_project_in_another_case_is_inside(tmp_path, other_copy, written):
    if not _case_insensitive(tmp_path):
        pytest.skip("this disk tells CAR from Car")
    project = tmp_path / "Car"
    shutil.copytree(other_copy, project / "copies" / vendor_loader.SKILL_NAME)
    target = {
        "relative": Path("..", "..", "..", "CAR", "copies", vendor_loader.SKILL_NAME),
        "absolute": tmp_path / "CAR" / "copies" / vendor_loader.SKILL_NAME,
    }[written]
    entry = _link(_entry(project), target)
    if sys.platform == "darwin":
        assert "/CAR/" in os.path.realpath(entry), "realpath answers the spelling the link wrote"

    _refused_as_inside(project)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS's disks take NFD and NFC as one name")
def test_a_link_into_the_project_spelled_in_nfd_is_inside(tmp_path, other_copy):
    nfc, nfd = "Café", "Café"
    project = tmp_path / nfc
    shutil.copytree(other_copy, project / "copies" / vendor_loader.SKILL_NAME)
    if not os.path.exists(tmp_path / nfd):
        pytest.skip("this disk tells the NFD spelling from the NFC one")
    _link(_entry(project), tmp_path / nfd / "copies" / vendor_loader.SKILL_NAME)

    _refused_as_inside(project)


@pytest.mark.skipif(sys.platform != "darwin", reason="the Data-volume firmlink is macOS's")
def test_a_link_into_the_project_through_the_data_firmlink_is_inside(project, other_copy):
    inside = project / "copies" / vendor_loader.SKILL_NAME
    shutil.copytree(other_copy, inside)
    firm = Path("/System/Volumes/Data" + os.path.realpath(inside))
    if not (firm.exists() and os.path.samefile(firm, inside)):
        pytest.skip("this folder has no Data-volume spelling")
    _link(_entry(project), firm)

    _refused_as_inside(project)


def test_a_disk_that_numbers_every_folder_zero_proves_no_two_folders_one(tmp_path, monkeypatch):
    """Identity is (device, inode), and some filesystems give every folder inode 0: there it would
    make every folder on the disk «the project». Where it cannot tell, the spelling alone decides."""
    one, other = tmp_path / "one", tmp_path / "other"
    one.mkdir()
    other.mkdir()
    real_stat = os.stat

    def inode_zero(path, *args, **kwargs):
        st = real_stat(path, *args, **kwargs)
        return os.stat_result((st.st_mode, 0, st.st_dev, st.st_nlink, st.st_uid, st.st_gid,
                               st.st_size, int(st.st_atime), int(st.st_mtime), int(st.st_ctime)))

    with monkeypatch.context() as patched:
        patched.setattr(os, "stat", inode_zero)
        assert method_binding._inside(str(other), str(one)) is False
        assert method_binding._inside(str(one / "copies"), str(one)) is True, "spelled inside is inside"


def test_a_real_folder_is_refused_and_cannot_be_approved(project, other_copy):
    shutil.copytree(other_copy, _entry(project))  # a whole 3.x copy, and still not trusted

    binding = method_binding.for_project(project)

    assert (binding.state, binding.can_approve, binding.skill_dir) == ("refused", False, None)
    assert str(_entry(project)) in binding.reason
    assert "a copy inside the project cannot be trusted" in binding.reason


def test_a_file_in_place_of_the_entry_is_refused(project):
    entry = _entry(project)
    entry.parent.mkdir(parents=True)
    entry.write_text("not a folder\n", encoding="utf-8")

    binding = method_binding.for_project(project)

    assert (binding.state, binding.can_approve) == ("refused", False)
    assert str(entry) in binding.reason and "not a link" in binding.reason


@pytest.mark.parametrize("kind", LINKS)
def test_a_link_to_a_folder_that_is_not_the_method_is_refused(project, tmp_path, kind):
    folder = tmp_path / "somewhere" / vendor_loader.SKILL_NAME
    folder.mkdir(parents=True)
    (folder / "README.md").write_text("not the method\n", encoding="utf-8")
    entry = _link(_entry(project), folder, kind)

    binding = method_binding.for_project(project)

    assert (binding.state, binding.can_approve) == ("refused", False)
    assert str(entry) in binding.reason and "3.x" in binding.reason
    assert "older line" not in binding.reason, "only a 2.x copy is told it is one"


@pytest.mark.parametrize("kind", LINKS)
def test_a_link_to_a_2x_copy_says_it_is_an_older_line(project, tmp_path, kind):
    """A 2.x copy has `rew_api.py` and neither `project.py` nor `contract.py` — what
    `_looks_like_an_older_skill` tells apart from «not the method at all»."""
    old = tmp_path / "old-checkout" / "skills" / vendor_loader.SKILL_NAME
    (old / "rew_tool").mkdir(parents=True)
    shutil.copy2(_SKILL / "rew_tool" / "rew_api.py", old / "rew_tool" / "rew_api.py")
    assert vendor_loader._looks_like_an_older_skill(old)
    entry = _link(_entry(project), old, kind)

    binding = method_binding.for_project(project)

    assert (binding.state, binding.can_approve) == ("refused", False)
    assert str(entry) in binding.reason
    assert "2.x" in binding.reason and "older line" in binding.reason


@pytest.mark.parametrize("kind", LINKS)
@pytest.mark.parametrize("trusted_as", ["unknown", "approved", "known"])
def test_a_copy_on_a_newer_contract_is_refused_however_it_came(project, newer_copy, kind, trusted_as):
    """An approval or a known install does not make a copy one this TCC can drive."""
    if trusted_as == "approved":
        assert config.approve_method(newer_copy)
    elif trusted_as == "known":
        _link(Path.home() / ".claude" / "skills" / vendor_loader.SKILL_NAME, newer_copy)
    entry = _link(_entry(project), newer_copy, kind)
    assert method_binding.KNOWN_CONTRACT == 0, "Ruling 3: this build knows no contract number"
    assert method_binding.read_contract_version(newer_copy) == 1

    binding = method_binding.for_project(project)

    assert (binding.state, binding.can_approve, binding.skill_dir) == ("refused", False, None)
    assert str(entry) in binding.reason
    assert "newer than this TCC — update TCC first" in binding.reason


def test_tccs_own_copy_is_not_held_to_the_contract_check(project, newer_copy, monkeypatch):
    """That check is S3's (W-10). A project on TCC's own copy runs what TCC runs, as it does today."""
    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, str(newer_copy))
    assert vendor_loader.skill_dir() == newer_copy

    assert method_binding.for_project(project).state == "same", "no entry"
    _link(_entry(project), newer_copy)
    binding = method_binding.for_project(project)

    assert (binding.state, binding.skill_dir) == ("same", newer_copy)


# ---- the «is a link» rule where a parent is a link -------------------------------------------


def test_a_project_reached_through_a_linked_parent_reads_the_same(tmp_path):
    """macOS's `/var`, pytest's temp folders, a mapped drive: there `realpath != abspath` holds for
    every path under the link, link or not — so that cannot be what says «this entry is a link»."""
    real = tmp_path / "real-disk"
    (real / "car").mkdir(parents=True)
    alias = tmp_path / "mapped-drive"
    alias.symlink_to(real, target_is_directory=True)
    project = alias / "car"
    assert os.path.realpath(project) != os.path.abspath(project), "the trap is set"

    assert method_binding.for_project(project).state == "same", "no entry"

    _link(_entry(project), vendor_loader.skill_dir())
    assert method_binding.for_project(project).state == "same", "a link to TCC's copy"

    os.unlink(_entry(project))
    _entry(project).mkdir()
    folder = method_binding.for_project(project)
    assert folder.state == "refused"
    assert "is a folder, not a link" in folder.reason, \
        "a real folder under a linked parent is a folder, not a link into the project"


# ---- the contract number, read and never imported ---------------------------------------------


def test_the_contract_number_is_read_without_importing_the_file():
    raising = 'raise SystemExit("importing this would end the run")\nCONTRACT_VERSION = 3\n'
    assert method_binding.contract_number(raising) == 3
    assert method_binding.contract_number("CONTRACT_VERSION: int = 2\n") == 2
    assert method_binding.contract_number("CONTRACT_VERSION = 1\nCONTRACT_VERSION = 4\n") == 4, \
        "the last top-level assignment is the value the module ends up with"

    shipped = (_SKILL / "rew_tool" / "contract.py").read_text(encoding="utf-8")
    assert method_binding.contract_number(shipped) is None, "v3.1.1 carries no number"


@pytest.mark.parametrize("text", [
    "CONTRACT_VERSION = '1'\n",
    "CONTRACT_VERSION = True\n",
    "CONTRACT_VERSION = 1.0\n",
    "CONTRACT_VERSION = ONE\n",
    "CONTRACT_VERSION = -1\n",
    "def f():\n    CONTRACT_VERSION = 1\n",
    "if True:\n    CONTRACT_VERSION = 1\n",
    '"""CONTRACT_VERSION = 1"""\n',
    "# CONTRACT_VERSION = 1\n",
    "CONTRACT_VERSION = (\n",
    "x = 1\n",
    "",
])
def test_the_contract_number_is_only_a_top_level_int(text):
    assert method_binding.contract_number(text) is None


def test_the_contract_number_is_cached_by_path_mtime_and_size(tmp_path, monkeypatch):
    """`for_project` runs on the GUI thread (diagnostics), and `contract.py` is 1800 lines."""
    skill = tmp_path / "copy"
    (skill / "rew_tool").mkdir(parents=True)
    contract = skill / "rew_tool" / "contract.py"
    shipped = (_SKILL / "rew_tool" / "contract.py").read_text(encoding="utf-8")
    contract.write_text(shipped + "\nCONTRACT_VERSION = 1\n", encoding="utf-8")
    parsed = []
    real = method_binding.contract_number
    monkeypatch.setattr(method_binding, "contract_number",
                        lambda text: parsed.append(len(text)) or real(text))

    assert method_binding.read_contract_version(skill) == 1
    assert method_binding.read_contract_version(skill) == 1
    assert len(parsed) == 1, "an unchanged file is not parsed again"

    contract.write_text(shipped + "\nCONTRACT_VERSION = 22\n", encoding="utf-8")
    assert method_binding.read_contract_version(skill) == 22
    assert len(parsed) == 2

    contract.unlink()
    assert method_binding.read_contract_version(skill) is None


# ---- never raises -----------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads everything")
def test_an_entry_tcc_cannot_read_is_refused_and_never_raises(project, request):
    """`os.path.lexists` answers False on a permission error, which would read this entry as absent
    and trust TCC's copy without a word."""
    entry = _link(_entry(project), vendor_loader.skill_dir())
    skills = entry.parent
    request.addfinalizer(lambda: skills.chmod(0o755))
    skills.chmod(0)
    assert not os.path.lexists(entry), "what lexists would have read as «absent»"

    binding = method_binding.for_project(project)

    assert (binding.state, binding.can_approve, binding.skill_dir) == ("refused", False, None)
    assert str(entry) in binding.reason


def test_for_project_answers_even_when_the_search_itself_fails(project, monkeypatch):
    def cannot(*_a, **_k):
        raise RuntimeError("the home folder cannot be determined")

    monkeypatch.setattr(vendor_loader, "skill_dir", cannot)

    binding = method_binding.for_project(project)

    assert (binding.state, binding.can_approve) == ("refused", False)
    assert str(_entry(project)) in binding.reason


# ---- approving on this machine ----------------------------------------------------------------


def test_approving_stores_the_copys_realpath_and_binds_it(project, tmp_path, other_copy):
    """Reached through a link of its own, like every installed copy: the realpath is what is kept."""
    alias = tmp_path / "checkouts"
    alias.symlink_to(other_copy.parent, target_is_directory=True)
    _link(_entry(project), alias / vendor_loader.SKILL_NAME)
    refused = method_binding.for_project(project)
    assert refused.can_approve, refused.reason

    approved = method_binding.approve(refused)

    assert (approved.state, approved.skill_dir) == ("approved", Path(os.path.realpath(other_copy)))
    assert config.approved_methods() == (os.path.realpath(other_copy),)
    assert method_binding.for_project(project).state == "approved", "and it stays approved"


def test_only_an_approvable_binding_can_be_approved(project, tmp_path):
    with pytest.raises(method_binding.MethodRefused):
        method_binding.approve(method_binding.for_project(project))  # `same`: nothing to approve

    gone = tmp_path / "gone"
    gone.mkdir()
    _link(_entry(project), gone)
    gone.rmdir()
    broken = method_binding.for_project(project)
    with pytest.raises(method_binding.MethodRefused) as caught:
        method_binding.approve(broken)

    assert str(caught.value) == broken.reason
    assert config.approved_methods() == ()


def test_an_approval_of_a_link_changed_since_it_was_checked_is_refused(project, other_copy, bare_copy):
    """The person approved the copy the sentence named; a link re-pointed since then is another one."""
    _link(_entry(project), other_copy)
    seen = method_binding.for_project(project)
    os.unlink(_entry(project))
    _link(_entry(project), bare_copy)

    with pytest.raises(method_binding.MethodRefused):
        method_binding.approve(seen)

    assert config.approved_methods() == ()


def test_an_approval_the_settings_drop_raises(project, other_copy, monkeypatch):
    """`_NoSettings` answers before anyone handed the core a store — headless, the light half."""
    _link(_entry(project), other_copy)
    refused = method_binding.for_project(project)
    monkeypatch.setattr(config, "_settings_provider", None)

    assert config.approve_method(other_copy) is False
    with pytest.raises(method_binding.MethodRefused) as caught:
        method_binding.approve(refused)

    assert os.path.realpath(other_copy) in str(caught.value)
    assert method_binding.for_project(project).state == "refused"


def test_an_approval_the_store_could_not_write_answers_false(tmp_path, monkeypatch):
    """QSettings keeps a value in memory when its file cannot be written, and says so only in
    `status()` — an approval that would be gone at the next start."""

    class _UnwritableStore:
        class Status:
            NoError, AccessError = 0, 1

        def __init__(self):
            self.kept = {}

        def value(self, key, default=None):
            return self.kept.get(key, default)

        def setValue(self, key, value):  # noqa: N802 — QSettings' own name
            self.kept[key] = value

        def sync(self):
            pass

        def status(self):
            return self.Status.AccessError

    store = _UnwritableStore()
    monkeypatch.setattr(config, "_settings_provider", lambda: store)

    assert config.approve_method(tmp_path) is False


def test_one_approved_copy_reads_back_from_the_file_an_earlier_run_wrote(_machine_dir):
    """QSettings writes a one-element list as a bare value, and a new process reads it back as a bare
    string (the recent-projects list met the same, `config._recent_raw`)."""
    ini = _machine_dir / "autosound-tcc" / "TCC.ini"
    ini.parent.mkdir(parents=True, exist_ok=True)
    ini.write_text("[method]\napproved=/Users/someone/autosound-tuning\n", encoding="utf-8")
    assert Path(config._settings().fileName()) == ini

    assert config.approved_methods() == ("/Users/someone/autosound-tuning",)


def test_approving_twice_keeps_one_entry(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()

    assert config.approve_method(first) and config.approve_method(second)
    assert config.approve_method(first)

    assert config.approved_methods() == (os.path.realpath(first), os.path.realpath(second))


# ---- re-linking to TCC's copy -----------------------------------------------------------------


@pytest.mark.parametrize("what", ["link", "broken link", "real folder",
                                  pytest.param("junction", marks=_windows_only)])
def test_relink_moves_the_entry_aside_and_links_tccs_copy(project, tmp_path, other_copy, what):
    entry = _entry(project)
    target = {"link": other_copy, "junction": other_copy, "broken link": tmp_path / "gone"}.get(what)
    if what == "real folder":
        entry.mkdir(parents=True)
        (entry / "SKILL.md").write_text("a copy somebody left here\n", encoding="utf-8")
    elif what == "broken link":
        target.mkdir()
        _link(entry, target)
        target.rmdir()
    else:
        _link(entry, target, "junction" if what == "junction" else "symlink")
    refused = method_binding.for_project(project)
    assert refused.state == "refused"

    relinked = method_binding.relink(refused)

    assert relinked.state == "same", relinked.reason
    assert _same_path(entry, vendor_loader.skill_dir()), "a link to TCC's copy in its place"
    assert os.listdir(entry.parent) == [entry.name], "nothing left under .claude/skills for omp to load"
    stamps = os.listdir(project / ".tcc" / "method-aside")
    assert len(stamps) == 1 and re.fullmatch(r"\d{8}-\d{6}", stamps[0]), stamps
    moved = project / ".tcc" / "method-aside" / stamps[0] / vendor_loader.SKILL_NAME
    assert os.path.lexists(moved)
    if target is None:
        assert (moved / "SKILL.md").read_text(encoding="utf-8") == "a copy somebody left here\n"
    else:
        assert _is_a_link(moved), "moved as a link, never followed"
        assert _same_path(moved, target)
    if what == "link":
        assert (other_copy / "SKILL.md").is_file(), "the copy it pointed at is left where it was"


def test_two_relinks_in_one_second_keep_both_entries(project, tmp_path, monkeypatch):
    monkeypatch.setattr(method_binding, "_stamp", lambda: "20261008-120000")
    entry = _entry(project)
    for name in ("first", "second"):
        folder = tmp_path / name
        folder.mkdir()
        if os.path.lexists(entry):
            os.unlink(entry)
        _link(entry, folder)
        assert method_binding.relink(method_binding.for_project(project)).state == "same"

    aside = project / ".tcc" / "method-aside"
    assert sorted(os.listdir(aside)) == ["20261008-120000", "20261008-120000-1"]
    assert _same_path(aside / "20261008-120000" / vendor_loader.SKILL_NAME, tmp_path / "first")
    assert _same_path(aside / "20261008-120000-1" / vendor_loader.SKILL_NAME, tmp_path / "second")


def test_relink_with_no_entry_links_tccs_copy(project):
    relinked = method_binding.relink(method_binding.for_project(project))

    assert relinked.state == "same"
    assert _same_path(_entry(project), vendor_loader.skill_dir())
    assert not (project / ".tcc" / "method-aside").exists(), "nothing was there to move aside"


def test_a_relink_that_cannot_make_the_link_says_where_the_old_entry_went(project, other_copy,
                                                                          monkeypatch):
    """`link_skill_into` answers None when there is nothing to link or the disk refuses — a Windows
    VM over a shared folder, where no junction can be made — and by then the entry is moved: an
    empty entry would read `same`, re-linked, with no method in the project (review of 4f83676, I1)."""
    entry = _link(_entry(project), other_copy)
    refused = method_binding.for_project(project)
    monkeypatch.setattr(vendor_loader, "link_skill_into", lambda project_dir: None)

    with pytest.raises(method_binding.MethodRefused) as caught:
        method_binding.relink(refused)

    stamps = os.listdir(project / ".tcc" / "method-aside")
    moved = project / ".tcc" / "method-aside" / stamps[0] / vendor_loader.SKILL_NAME
    assert _is_a_link(moved) and _same_path(moved, other_copy), "the old entry is aside, a link still"
    assert not os.path.lexists(entry)
    assert str(moved) in str(caught.value) and "no link" in str(caught.value).lower()


def test_a_relink_with_nothing_to_move_that_cannot_make_the_link_raises(project, monkeypatch):
    monkeypatch.setattr(vendor_loader, "link_skill_into", lambda project_dir: None)

    with pytest.raises(method_binding.MethodRefused) as caught:
        method_binding.relink(method_binding.for_project(project))

    assert str(_entry(project)) in str(caught.value) and "no link" in str(caught.value).lower()
    assert not (project / ".tcc" / "method-aside").exists()


# ---- `.claude/skills` that leads out of the project (review of 4f83676, I2) -------------------
# A project whose `.claude` or `.claude/skills` is a link elsewhere — to `~/.claude/skills`, where
# a personal install can be a real folder — does not hold what sits there. The folder row must not
# call it «inside the project», and a re-link must not move it out of there into this project.


def _skills_lead_home(project: Path, personal_install: str, other_copy: Path) -> Path:
    personal = Path.home() / ".claude" / "skills"
    if personal_install == "folder":
        shutil.copytree(other_copy, personal / vendor_loader.SKILL_NAME)
    else:
        _link(personal / vendor_loader.SKILL_NAME, other_copy)
    (project / ".claude").mkdir()
    (project / ".claude" / "skills").symlink_to(personal, target_is_directory=True)
    return personal


def test_a_folder_reached_through_skills_that_lead_out_is_not_called_inside(project, other_copy):
    _skills_lead_home(project, "folder", other_copy)

    binding = method_binding.for_project(project)

    assert (binding.state, binding.can_approve) == ("refused", False)
    assert str(_entry(project)) in binding.reason
    assert "inside the project" not in binding.reason, binding.reason
    assert "outside the project" in binding.reason


@pytest.mark.parametrize("personal_install", ["folder", "link"])
def test_relink_moves_nothing_outside_the_project(project, other_copy, personal_install):
    personal = _skills_lead_home(project, personal_install, other_copy)
    before = method_binding.for_project(project)
    assert before.state == ("refused" if personal_install == "folder" else "known"), before.reason

    with pytest.raises(method_binding.MethodRefused) as caught:
        method_binding.relink(before)

    assert str(_entry(project).parent) in str(caught.value)
    assert os.listdir(personal) == [vendor_loader.SKILL_NAME], "nothing linked or moved there"
    assert _is_a_link(personal / vendor_loader.SKILL_NAME) == (personal_install == "link")
    assert (personal / vendor_loader.SKILL_NAME / "SKILL.md").is_file()
    assert not (project / ".tcc").exists(), "nothing moved aside"


# ---- the bound copy's repository ------------------------------------------------------------


def test_a_copy_in_no_repository_has_no_plugin_root(project, bare_copy):
    assert config.approve_method(bare_copy)
    _link(_entry(project), bare_copy)

    binding = method_binding.for_project(project)

    assert binding.state == "approved"
    assert binding.plugin_root() is None
