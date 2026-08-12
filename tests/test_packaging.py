"""The light half stays light, and the heavy half fails in a sentence.

`autosound-tcc` ships in two sizes: the base install is `claude-agent-sdk` and nothing else, the
window is an extra because PySide6 + pyqtgraph is hundreds of megabytes. That split is only real
while the CLI entry points import no Qt — and adding one import to a `core/` module breaks it
invisibly, because every developer machine has the GUI installed. Hence a test.

Decision and reasoning: `docs/ARCHITECTURE-NOTES.md` §3 (2026-08-12).
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Everything a light install must be able to run. The MCP server is on the list because TCC's
#: whole non-GUI story is "the model talks to the project through it".
LIGHT_MODULES = (
    "autosound_tcc.tuning_session_cli",
    "autosound_tcc.dsp_profile_interview",
    "autosound_tcc.core.mcp_server",
    "autosound_tcc.core.app_log",
    "autosound_tcc.core.config",
    "autosound_tcc.core.delay_bank",
    "autosound_tcc.core.project_settings",
    "autosound_tcc.core.contract_check",
)

#: Blocked as a group: shiboken6 is PySide6's own runtime, and numpy arrives with pyqtgraph.
_HEAVY = ("PySide6", "pyqtgraph", "shiboken6", "numpy")

_BLOCKER = f'''
import sys

_HEAVY = {_HEAVY!r}


class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in _HEAVY:
            raise ImportError("not installed in a light install: " + name)
        return None


sys.meta_path.insert(0, _Block())
'''


def _run(body: str) -> subprocess.CompletedProcess:
    """A fresh interpreter, because the import blocker has to be in place before anything else.

    A subprocess and not `monkeypatch`: pytest itself has already imported Qt by the time any test
    runs, so an in-process check would be testing a cache rather than an install.
    """
    return subprocess.run(
        [sys.executable, "-c", _BLOCKER + body],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )


@pytest.mark.parametrize("module", LIGHT_MODULES)
def test_the_cli_half_imports_with_no_gui_installed(module):
    proc = _run(f"import {module}")
    assert proc.returncode == 0, (
        f"{module} needs the GUI extra, so a light install cannot run it\n"
        f"--- stderr ---\n{proc.stderr[-3000:]}"
    )


def test_asking_for_the_window_without_it_prints_what_to_type():
    """A traceback about `PySide6.QtWidgets` tells the reader nothing they can act on."""
    proc = _run(
        "import sys; sys.argv = ['autosound-tcc']\n"
        "from autosound_tcc.app import main\n"
        "raise SystemExit(main())"
    )

    assert proc.returncode == 2, "a refusal, not a crash and not a success"
    assert "uv tool install" in proc.stderr and "[gui]" in proc.stderr
    assert "Traceback" not in proc.stderr
    # A command that fails with "no such package" sends its reader hunting for a typo of their
    # own. `autosound-tcc` is not on PyPI, so the line printed here has to carry the git URL —
    # caught by actually running it (2026-08-12).
    assert "git+https://" in proc.stderr, "the printed command must be one that works"


def test_the_two_sizes_are_declared_the_way_the_split_assumes():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    base = data["project"]["dependencies"]
    extras = data["project"]["optional-dependencies"]

    assert not [d for d in base if d.split(">")[0].strip().lower() in ("pyside6", "pyqtgraph")], (
        "the base install must not carry the toolkit; that is what the `gui` extra is for"
    )
    assert any("PySide6" in d for d in extras["gui"])
    # The suite is mostly Qt, run offscreen — `dev` has to pull the window in.
    assert any("gui" in d for d in extras["dev"])


def test_every_dependency_has_an_upper_bound():
    """An open `>=` is not a version policy. It says "whatever exists on the day this is
    installed", which for a tool taken to a competition means a resolver picks the Qt major in a
    car park. Bounds are cheap to raise deliberately and expensive to discover the absence of
    (user, 2026-08-12: "як наш пакет буде себе вести з часом з оновленнями версій?")."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = list(data["project"]["dependencies"])
    for name, group in data["project"]["optional-dependencies"].items():
        # `dev` pulls this package's own extra (`autosound-tcc[gui]`) — a self-reference has no
        # version of its own to bound.
        declared += [d for d in group if not d.startswith("autosound-tcc")]

    unbounded = [d for d in declared if "<" not in d and "==" not in d and "~=" not in d]
    assert not unbounded, f"no upper bound, so a breaking major installs itself: {unbounded}"


def test_the_python_floor_is_one_that_has_actually_been_run():
    """`>=3.10` was declared and never exercised — no CI, and every run on this project has been
    3.12 or newer. A floor nobody tests is a claim, not support."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    floor = data["project"]["requires-python"]

    assert floor == ">=3.11", floor
    assert sys.version_info >= (3, 11), "and the interpreter running the suite must satisfy it"


def test_the_window_uses_only_what_the_essentials_wheel_ships():
    """The `gui` extra asks for PySide6-Essentials, which is 800 MB smaller and does NOT contain
    Qt3D, Charts, WebEngine or Multimedia. One import of any of those turns a working install
    into an ImportError for everyone who took the recommended path."""
    addons_only = {
        "Qt3DCore", "Qt3DRender", "QtCharts", "QtDataVisualization", "QtWebEngineCore",
        "QtWebEngineWidgets", "QtMultimedia", "QtMultimediaWidgets", "QtBluetooth", "QtNfc",
        "QtRemoteObjects", "QtScxml", "QtSensors", "QtSerialPort", "QtWebSockets", "QtCharts",
    }
    used = set()
    for path in (ROOT / "src").rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(("from PySide6.", "import PySide6.")):
                used.add(line.split("PySide6.", 1)[1].split()[0].split(".")[0])

    assert used, "the scan found no Qt imports at all, which means it is not scanning"
    assert not (used & addons_only), f"needs the Addons wheel: {sorted(used & addons_only)}"


def test_every_console_script_points_at_something_that_exists():
    """A dangling entry point is only discovered by the person who typed the command."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    for name, target in data["project"]["scripts"].items():
        module, _, func = target.partition(":")
        path = ROOT / "src" / Path(module.replace(".", "/") + ".py")
        assert path.exists(), f"{name} -> {module} has no module"
        assert f"def {func}(" in path.read_text(encoding="utf-8"), f"{name} -> {target} missing"


# ---- what an INSTALLED copy can find (found by installing it, 2026-08-12) ----------------------


def _fake_skill(root: Path) -> Path:
    skill = root / "skills" / "autosound-tuning"
    (skill / "rew_tool").mkdir(parents=True)
    (skill / "rew_tool" / "rew_api.py").write_text("# enough to be recognised\n")
    return skill


def test_the_bundled_profiles_ship_inside_the_package():
    """They lived in `<repo>/data/dsp_profiles`, which exists in a checkout and nowhere else — so
    an installed TCC opened New Project with no bundled profile in the list, silently. A wheel
    contains what is under `src/autosound_tcc` and nothing more."""
    from autosound_tcc.core import config

    directory = config.bundled_profiles_dir()

    assert directory.is_dir() and list(directory.glob("*.json")), directory
    assert (ROOT / "src" / "autosound_tcc") in directory.parents, (
        "outside the package directory it will not be in the wheel"
    )


def test_an_installed_tcc_finds_the_skill_where_claude_code_put_it(tmp_path, monkeypatch):
    """`vendor/` is a submodule of the CHECKOUT. From a wheel that path resolves to
    `.../lib/python3.x/vendor/...`, so the install came out with no skill and told the user to run
    `git submodule update` in a repository they do not have."""
    from autosound_tcc.core import vendor_loader

    installed = _fake_skill(tmp_path / "home" / ".claude")
    monkeypatch.setattr(vendor_loader, "_SUBMODULE_DIR", tmp_path / "no-checkout-here")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv(vendor_loader.SKILL_DIR_ENV, raising=False)

    assert vendor_loader.is_available()
    assert vendor_loader.skill_dir() == installed
    assert vendor_loader.REW_TOOL_DIR == installed / "rew_tool", "the live attribute follows"


def test_the_env_override_outranks_everything(monkeypatch):
    """How a developer points TCC at a working tree of the skill, and how a packaged install can
    be told where the skill went instead of being made to guess."""
    from autosound_tcc.core import vendor_loader

    monkeypatch.delenv(vendor_loader.SKILL_DIR_ENV, raising=False)
    assert list(vendor_loader._candidates())[0] == vendor_loader._SUBMODULE_DIR, (
        "with no override, a checkout comes before any installed copy"
    )

    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, "/somewhere/else")

    assert list(vendor_loader._candidates())[0] == Path("/somewhere/else")


def test_the_missing_skill_message_fits_both_readers(tmp_path, monkeypatch):
    """A developer who forgot the submodule, and someone who installed TCC and has no repo."""
    from autosound_tcc.core import vendor_loader

    monkeypatch.setattr(vendor_loader, "_SUBMODULE_DIR", tmp_path / "nope")
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    monkeypatch.delenv(vendor_loader.SKILL_DIR_ENV, raising=False)

    with pytest.raises(vendor_loader.VendorNotInitializedError) as caught:
        vendor_loader.load("rew_api.py")

    message = str(caught.value)
    assert "git submodule update" in message
    assert vendor_loader.SKILL_DIR_ENV in message
    assert "Looked in:" in message, "it names the places, so the reader can check one"
