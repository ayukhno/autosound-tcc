"""The Critic channel — a wrapper around the skill's own reviewer scripts, not a new integration.

The tuning method is a three-role loop (SKILL.md §Three Roles): the Generator proposes, the
Critic challenges, the Arbiter decides. The Critic is deliberately **stateless** — a one-shot call
that re-reads state from disk — which is what makes it a drift-watchdog rather than a second
agent, and what makes it cheap to run as a subprocess.

The skill already ships a working reviewer channel, so TCC calls it instead of building one:
`scripts/autosound_ai.py <role> <package.md> [trace.csv]`. That script is stdlib-only and
cross-platform (its bash sibling `gemini_critic.sh` is macOS/Linux), and it already knows how to
reach a local CLI (`agy`/`gemini`), a cloud API, or fall back to the clipboard.

**The contract that matters, and the trap in it:** the critique is written to *stdout* and ends
with a `— [critic: <model>]` marker; progress goes to *stderr*. When neither an API nor a CLI is
reachable the script does not fail — it compiles the package, copies it to the clipboard, and
returns **exit code 0 with empty stdout**. So a caller that trusts the return code reports success
and shows an empty critique. Clipboard mode is a legitimate outcome (it is the zero-cost path:
paste into any free web chat and bring the answer back), but it has to be reported as *manual*,
never as an answer.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Mapping, Optional

from autosound_tcc.core import app_log, child
from autosound_tcc.core import config, vendor_loader

DEFAULT_TIMEOUT_S = 600.0
# The script prints this as its last stdout line on a real answer: `— [critic: Gemini 3.1 Pro]`.
_MODEL_MARKER = re.compile(r"^—\s*\[(?P<role>\w+):\s*(?P<model>.+?)\]\s*$", re.MULTILINE)
_CLIPBOARD_MARKER = "CLIPBOARD MODE"
# The script writes the critique to `process/reviews/<ts>-<role>.md` and says so on stderr in two
# forms; this is the machine-readable one, so nothing here parses a translated sentence (SCR-027).
_REVIEW_MARKER = re.compile(r"^>>\s*REVIEW_FILE:\s*(?P<path>.+?)\s*$", re.MULTILINE)
#: The package the clipboard rung takes, named on stderr the same machine-readable way (v3.0.53).
_PACKAGE_MARKER = re.compile(r"^>>\s*PACKAGE_FILE:\s*(?P<path>.+?)\s*$", re.MULTILINE)

MODE_API_OR_CLI = "answered"
MODE_CLIPBOARD = "clipboard"
MODE_ERROR = "error"
#: The reviewer asking WHICH MODEL, with the key's own list of what it can call. Its own mode
#: because it is a question, not a fault: the script exits 3 and prints the list on stderr
#: (skill@af9d7e3), and reading that as "error, fall back to the clipboard" throws away the one
#: thing that would fix it. Bought on a live key: `gemini-2.5-*` answered 404 while the key
#: worked (2026-09-08), and the answer was in the list nobody was shown.
MODE_CHOOSE_MODEL = "choose_model"
#: Exit code the reviewer uses for that question. A code rather than a phrase in stderr: the text
#: is Ukrainian prose that will be reworded, the code is a contract.
_CHOOSE_MODEL_EXIT = 3
#: No answer (hub #154 §5, the method's v3.0.53): the reviewer exits 4, lists every reason under
#: "⛔ РЕЦЕНЗІЇ НЕ ОТРИМАНО" and files nothing as a review; the package is still made ready for the
#: clipboard rung. Its own mode because read as an error the stderr tail was the package lines and
#: the reasons were lost above them.
MODE_REFUSED = "refused"
_REFUSED_EXIT = 4
#: The reviewer was not called because the PROJECT is not ready — no contract, no context, which
#: is the ordinary state of a folder that has not been through intake yet. Distinct from
#: `MODE_ERROR` because it is not a fault and reporting it as one sends somebody debugging a
#: working channel: on a fresh project the first thing anyone tries is "check the reviewer", and
#: what came back was two missing filenames in English under a Ukrainian UI (user, 2026-08-13).
MODE_NOT_READY = "not_ready"

#: The method's plain-question task, `autosound_ai.py ask` (skill#27): the same reviewer and
#: channel as a review, with no tuning contract and no project needed (finding 124, tcc#116).
ASK = "ask"


@dataclass(frozen=True)
class CriticResult:
    """What came back from one reviewer call."""

    mode: str  # answered | clipboard | error | not_ready
    text: str  # the critique itself, marker line stripped; "" unless mode == answered
    model: Optional[str]  # as reported by the script, e.g. "Gemini 3.1 Pro (High)"
    role: str
    detail: str  # stderr tail — why it fell back, or what failed
    duration_s: float
    called_at: str
    # Project-relative path to the critique's own text (SCR-027). The reasoning used to live only
    # in the chat stream, so a session rendered from disk knew a review happened and not what it
    # argued. `None` when the script could not write it.
    review: Optional[str] = None
    #: The models this key can actually call, when the reviewer asked which one to use. Empty for
    #: every other mode. Names only — nothing here is a key.
    models: list = field(default_factory=list)
    #: Project-relative path to the package the clipboard step takes, when the reviewer made one.
    package: Optional[str] = None
    #: The pins in a critic-env or the environment this run's own `--model` set aside, as the
    #: method named them (`_pins_set_aside`, tcc#113). None when the run named no model by the
    #: flag or never ran: then nothing is known either way.
    pins_set_aside: Optional[list] = None
    #: The vendor the method said it called the API of (`>> Підключення до API (<provider>, …)`),
    #: read from the whole of its stderr, or "": an answered run's `detail` is the last six lines,
    #: and that line is never among them (review of #129). Names the key in `fallback_note`.
    api_vendor: str = ""

    @property
    def ok(self) -> bool:
        return self.mode == MODE_API_OR_CLI


#: The list lines of the reviewer's question: `>>     <name>`, indented under the `=<модель>`
#: line. Matched by SHAPE rather than by the sentences around them, which are prose in Ukrainian
#: and will be reworded; a name is `[a-z0-9.-]` and nothing else.
_OFFERED = re.compile(r"^>>\s{4,}([a-z0-9][a-z0-9.\-]*)\s*$", re.M)


def _models_offered(stderr: str) -> list:
    """The models the key can call, in the order the reviewer listed them.

    Order is not cosmetic: the script puts the pointer ids (`gemini-pro-latest`) first on purpose,
    because a dated id stays put until Google retires it and the list lags the retirements.
    """
    return [name for name in _OFFERED.findall(stderr or "")]


def script_path() -> Path:
    """`autosound_ai.py` inside the vendored skill."""
    return vendor_loader.REW_TOOL_DIR.parent / "scripts" / "autosound_ai.py"


def is_available() -> bool:
    return script_path().is_file()


_OMP_ROUTE_CACHE: dict = {}


def omp_route_available() -> bool:
    """Whether the method's reviewer script calls through omp — `"omp"` in its `VIA_ROUTES`.

    The Arbiter's rule (tcc#74): an OMP pick goes through omp only, and until the script has the
    route (hub #216 TCC-034) OMP reviewer picks call nothing. Read from the script, not a version:
    the Arbiter tests on the skill's working tree before the tag. Cached by the file's size and
    mtime — the picker asks this while it is being filled."""
    import re

    path = script_path()
    try:
        stat = path.stat()
    except OSError:
        return False
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _OMP_ROUTE_CACHE:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        found = re.search(r"^VIA_ROUTES\s*=\s*\(([^)]*)\)", text, re.MULTILINE)
        _OMP_ROUTE_CACHE.clear()
        _OMP_ROUTE_CACHE[key] = bool(found) and re.search(r"[\"']omp[\"']", found.group(1)) is not None
    return _OMP_ROUTE_CACHE[key]


_MODEL_FLAG_CACHE: dict = {}
#: The usage line names the flag from v3.0.65 (hub #226); v3.0.64's ends at `[trace.csv]`.
_MODEL_FLAG_USAGE = "[--model <id>]"


def takes_model_flag() -> bool:
    """Whether the method's reviewer script takes the run's own model as `--model <id>`.

    Read from the script, as `omp_route_available` is, and not from a version: the method's usage
    line names the flag from v3.0.65 (hub #226). It has to be asked, because an older method takes
    `--model <id>` for positional words — `--model` itself for the trace file when none is given.
    Cached by the file's size and mtime — an update replaces the file."""
    path = script_path()
    try:
        stat = path.stat()
    except OSError:
        return False
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _MODEL_FLAG_CACHE:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        _MODEL_FLAG_CACHE.clear()
        _MODEL_FLAG_CACHE[key] = _MODEL_FLAG_USAGE in text
    return _MODEL_FLAG_CACHE[key]


#: The one stderr line the method prints when this run's `--model` / `--provider` set a pin aside
#: (`lost_pins`, hub #226): `>> --model <id>: … не діють для нього: VAR=value (<file>, рядок N);
#: VAR=value (змінна середовища). …`. Read by shape — the flag that opens it, then `VAR=value
#: (where)` entries, each closed by `; ` before the next or by the full stop — never by its words.
_PINS_LINE = re.compile(r"^>>\s*--(?:model|provider)\s.*$", re.M)
_PIN = re.compile(r"(?<!\w)(?P<var>[A-Z][A-Z0-9_]*)=(?P<value>.+?) \((?P<where>.+?)\)"
                  r"(?=; [A-Z][A-Z0-9_]*=|\.(?:\s|$))")
#: `<file>, <word> N`: a pin in a file, at its line. Anything else is the inherited environment.
_PIN_IN_FILE = re.compile(r"^(?P<file>.+), \S+ (?P<line>\d+)$")


def _pins_set_aside(stderr: str) -> list:
    """The pins this run's own model set aside, in the method's order, as `{variable, value, file,
    line}` — `file` and `line` None for the environment. [] when the method named none."""
    match = _PINS_LINE.search(stderr or "")
    if not match:
        return []
    pins = []
    for pin in _PIN.finditer(match.group(0)):
        where = _PIN_IN_FILE.match(pin.group("where"))
        pins.append({"variable": pin.group("var"), "value": pin.group("value"),
                     "file": where.group("file") if where else None,
                     "line": int(where.group("line")) if where else None})
    return pins


def _project_mirror(project_dir: Path) -> Path:
    """Where the script looks for the data contract and project context."""
    return project_dir / "rew_analitic"


def _find_for_script(project_dir: Path, name: str) -> Optional[Path]:
    """The same places `autosound_ai.py` looks, in the same order.

    It searched only `rew_analitic/` here, while the script itself accepts the project root and
    `$AUTOSOUND_DIR` too — so TCC could refuse a project the script would have run in perfectly
    well. Two implementations of one rule, and this is the half that says no (user, on a fresh
    Windows install, 2026-08-19: the Critic short-circuited before it was ever called).

    The last place is the SKILL's own `assets/`, because the data contract belongs to the method
    and travels with it; nothing copies it into a project.
    """
    candidates = [_project_mirror(project_dir) / name, project_dir / name]
    canon = os.environ.get("AUTOSOUND_DIR", "")
    if canon:
        candidates.append(Path(canon).expanduser() / name)
    try:
        candidates.append(vendor_loader.skill_dir() / "assets" / name)
    except Exception:  # noqa: BLE001 — no skill is its own, louder problem, reported above
        pass
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def script_missing() -> list[str]:
    """The one reason that holds back every task, `ask` included: no reviewer script at all."""
    return [] if is_available() else [f"reviewer script not found at {script_path()}"]


def preflight(project_dir: Optional[Path] = None) -> list[str]:
    """Reasons the Critic cannot run yet, as user-facing lines. Empty list = ready.

    Checked here rather than left to the script because the script exits with a bare message on a
    missing file, and "nothing happened" is the worst thing a button can do.
    """
    project_dir = Path(project_dir or config.project_dir())
    problems = script_missing()
    for name in ("data-contract-template.md", "autosound_context.md"):
        if _find_for_script(project_dir, name) is None:
            problems.append(f"{name} not found in {project_dir} (nor in rew_analitic/)")
    return problems


#: Reviewer CLIs to fall back to, best first. `agy` is the one actually installed on the machine
#: this was found on; `gemini` stays because a setup that really has it should keep it.
_CRITIC_CLIS = ("agy", "gemini")

#: The CLI each picker route is actually run with. `sdk` and `omp` are not here on purpose:
#: neither is a reviewer CLI, and naming one would send the script at a binary that cannot
#: take a review.
_HARNESS_CLIS = {"agy": "agy", "codex": "codex", "gemini": "gemini"}


def critic_bin_override(*, harness: str = "", environ=None, which=None) -> dict:
    """`{"AUTOSOUND_CRITIC_BIN": <cli>}` when the inherited reviewer binary cannot work, else `{}`.

    The skill's reviewer honours `GEMINI_BIN` under its historical name and lets it OUTRANK
    autodetection, so a stale value silently decides the channel. On the Arbiter's machine it
    named `gemini` — a path Google has closed — so every call tried that, failed, and degraded to
    the clipboard: eight calls, zero critiques, and `agy`, which was installed all along, never
    tried once (measured 2026-09-11, TCC-002).

    `AUTOSOUND_CRITIC_BIN` is checked FIRST by that same reviewer, so naming a working CLI there
    settles it without touching anybody's environment. Deliberately narrow: it acts only when the
    inherited name is not on PATH and a working one is, and it never overrides a choice the person
    made for themselves.
    """
    environ = os.environ if environ is None else environ
    which = which or shutil.which
    if environ.get("AUTOSOUND_CRITIC_BIN"):
        return {}
    # What the Arbiter PICKED, and it outranks anything inherited. That ordering is the bug the
    # session finally named: the project said `critic: agy:…`, the machine exported
    # `GEMINI_BIN=gemini`, and the reviewer reads the env var first — so ten calls in a row went
    # to a CLI nobody chose, down a path Google has closed, and came back as clipboard packages
    # with `model: null` (measured 2026-09-11). TCC already sends the picked MODEL; not sending
    # the binary beside it is what let the two disagree.
    #
    # `which`, because a pick naming a CLI this machine does not have is worse than no override:
    # it would replace one dead name with another.
    route = (harness or "").strip().lower()
    wanted = _HARNESS_CLIS.get(route)
    if wanted and which(wanted):
        return {"AUTOSOUND_CRITIC_BIN": wanted}
    if route == "sdk":
        # The `claude` the footer found, by its path: a Dock-launched TCC has no `~/.local/bin` on
        # PATH, so the method's own search found none and an «SDK · …» review went to the clipboard
        # once it went by the CLI (review of tcc#127, M1). The method reads the flavour from the
        # file's name.
        from autosound_tcc.core import claude_sdk

        found = claude_sdk.cli_path()
        if found:
            return {"AUTOSOUND_CRITIC_BIN": found}
    inherited = environ.get("GEMINI_BIN")
    if not inherited or which(inherited):
        return {}
    for candidate in _CRITIC_CLIS:
        if which(candidate):
            return {"AUTOSOUND_CRITIC_BIN": candidate}
    return {}


def package_dir(project_dir: Optional[Path] = None) -> Path:
    """Where TCC drops packages it composed itself.

    Under `.tcc/` rather than `rew_analitic/`: packages the skill's Generator writes belong to the
    project record and are named by the skill, and mixing TCC-generated ones into the same folder
    would blur which of the two authored a given review.
    """
    return config.tcc_dir(project_dir) / "packages"


def write_package(markdown: str, project_dir: Optional[Path] = None) -> Path:
    """Persist a package so the reviewer call has a file to read, and so the call is auditable."""
    folder = package_dir(project_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"pkg_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def ask_package(question: str, context: str = "") -> str:
    """What `ask` reads from its file: the question, then the session's own context under a heading.

    The method takes a file, not text (`autosound_ai.py ask <question.md>`), puts it under
    «GENERATOR'S QUESTION», and adds the project's `autosound_context.md` as background itself
    when there is one — so only what the session adds goes here (tcc#116).
    """
    context = (context or "").strip()
    return (question or "").strip() + (f"\n\n## Context\n\n{context}" if context else "") + "\n"


def _package_file(package: str, project_dir: Path) -> Optional[Path]:
    """The package file `package` names — `None` when `package` is the package's own text.

    A relative path is the PROJECT's, tried there before TCC's working folder. TCC prints the
    clipboard package as `process/reviews/…-critic-package.md` under a failed call; the Generator
    handed that back, checked against TCC's own folder it named nothing, and the path went to the
    reviewer as the package's text — «ви передали лише шлях до файлу» (finding 133, tcc#119).
    """
    text = package.strip()
    if len(text.splitlines()) != 1 or not text.endswith(".md"):
        return None
    candidate = Path(text)
    tried = (candidate,) if candidate.is_absolute() else (project_dir / candidate, candidate)
    return next((path for path in tried if path.is_file()), None)


def _shaped_like_a_package_path(package: str) -> bool:
    """One line, ending in `.md`, with a separator in it: a path, not a package's text. Such a
    string that names no file is refused by that name — sent as text it is a review of a file
    name (tcc#119). Both separators, because the path may have been printed on another platform."""
    text = package.strip()
    return len(text.splitlines()) == 1 and text.endswith(".md") and bool(re.search(r"[\\/]", text))


def configured(project_dir: Path) -> tuple[str, str]:
    """`(model, route)` of the reviewer this project's footer is set to — `("", "")` when none.

    One answer for every caller: the MCP tool that runs the reviewer and the session environment
    that a direct call inherits read the same pair (findings 17/21, `#45`).
    """
    from autosound_tcc.core import model_choices, project_settings

    resolved, choice = model_choices.resolve_critic(
        project_settings.get(config.tcc_dir(project_dir), "critic", "") or "")
    model = model_choices.reviewer_model(choice) if choice is not None else ""
    route = resolved.key.partition(":")[0] if ":" in resolved.key else ""
    return model, route


def session_env(project_dir: Path) -> dict:
    """What a tuning session's own shell should know about the reviewer the Arbiter picked.

    A session that runs the reviewer script itself — the route the method still documents — did
    not inherit the pick and was refused for "no model" (findings 17, 21; `#45` point 3). The
    reviewer reads `AUTOSOUND_CRITIC_MODEL` first, and the binary TCC would use goes with it.

    And the pick's route, in `AUTOSOUND_CRITIC_VIA` (hub #236 TCC-046, the method's v3.1.0): a
    session's own run names no `--via`, and with a key in the OS store such a run went to the
    vendor's API whatever the footer said. The route is the one `run` asks for by `--via`.
    """
    model, route = configured(project_dir)
    if not model:
        return {}
    if route == "omp":
        # An OMP pick goes through omp or not at all (tcc#74). Without the script's omp route a
        # model handed over here would reach the vendor's API under another name.
        if not omp_route_available():
            return {}
        return {"AUTOSOUND_CRITIC_MODEL": model, "AUTOSOUND_CRITIC_BIN": "omp",
                "AUTOSOUND_CRITIC_VIA": "omp"}
    env = {"AUTOSOUND_CRITIC_MODEL": model}
    via = via_of(route)
    if via:
        env["AUTOSOUND_CRITIC_VIA"] = via
    env.update(critic_bin_override(harness=route))
    return env


#: The routes one reviewer run may ask for by name — the script's own `--via` (skill `VIA_ROUTES`).
VIA_ROUTES = ("api", "cli", "clipboard", "omp")
#: The vendors the script's `--provider` takes (skill `_PROVIDERS`); any other word it refuses.
PROVIDERS = ("google", "anthropic", "openai")

#: The API key that makes the reviewer take the API instead of the CLI a person picked — per CLI
#: route (the reviewer's own provider table: `agy` is Google's CLI, `codex` OpenAI's).
_CLI_REROUTING_KEYS = {"agy": ("GEMINI_API_KEY",), "codex": ("OPENAI_API_KEY",),
                       # And the SDK's: the method runs `claude -p` for it, and `claude -p` bills an
                       # `ANTHROPIC_API_KEY` in its environment over the subscription (review of
                       # tcc#127, I1).
                       "sdk": ("ANTHROPIC_API_KEY",)}
#: The picks that run on a login rather than a key — the routes `model_choices.ROUTES` bills to
#: a subscription: agy's, codex's, and the SDK's Claude login, which the method reaches through
#: the `claude` CLI. Each run goes as `--via cli` (tcc#127).
_LOGIN_ROUTES = ("agy", "codex", "sdk")


def via_of(harness: str) -> str:
    """The method's route word for a pick's harness: `run`'s `--via` and a session's
    `AUTOSOUND_CRITIC_VIA` (hub #236) — one mapping, so the two cannot drift (task 9 review, M2).

    «API · …» is the key's route and nothing else; «OMP · …» is omp's (tcc#74); a login's route
    is its CLI, which the method starts with no vendor key (tcc#127): with a key stored, agy's
    untiered and Claude models, codex and the SDK all went to the vendor's API under a pick that
    said «subscription» (measured on the method, finding 136). Any other route names none and
    leaves the method its own default.
    """
    route = (harness or "").strip().lower()
    if route in ("api", "omp"):
        return route
    return "cli" if route in _LOGIN_ROUTES else ""


def run(
    package: str,
    project_dir: Optional[Path] = None,
    trace_path: Optional[str] = None,
    role: str = "critic",
    model: Optional[str] = None,
    harness: str = "",
    timeout_s: float = DEFAULT_TIMEOUT_S,
    python_executable: Optional[str] = None,
    extra_env: Optional[Mapping[str, str]] = None,
    via: str = "",
    provider: str = "",
) -> CriticResult:
    """Call the reviewer once. `package` is either markdown or a path to an existing package file;
    a relative path is the project's (tcc#119).

    `model` is the run's own model: the method's `--model` from v3.0.65, which no critic-env pin
    outranks (hub #226, tcc#113), and `GEMINI_CRITIC_MODEL` in the environment for a method before
    it. `provider` — `google`, `anthropic`, `openai` — goes beside it as `--provider` when TCC
    knows the pick's vendor; otherwise the method reads the vendor from the model's name.

    `extra_env` carries variables for this call only, applied last.

    `via` — `api`, `cli` or `clipboard` — is the route for THIS run, the script's own `--via`
    (tcc#59): after a cut-off CLI stream the method says to take one review through the key.
    Without it the pick's own route goes: `api`, `omp`, or `cli` for a login's pick (tcc#127).

    `role` is the method's task: `critic` (the default), `advisor`, or `ask` (`ASK`) — a question,
    which needs neither the contract nor the context and is always sent as text (tcc#116).
    """
    # The console interpreter, not TCC's windowed one (`child.script_interpreter`).
    python_executable = python_executable or child.script_interpreter()
    project_dir = Path(project_dir or config.project_dir())
    started = time.monotonic()
    called_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # `ask` runs where intake has not been (skill#27) — and «check the Critic at the start» is
    # asked exactly there (finding 124) — so only a missing script holds it back.
    problems = script_missing() if role == ASK else preflight(project_dir)
    if problems:
        # A missing SCRIPT is a broken install; missing project files are a project that has not
        # started yet. Same list, two different things to say about it.
        mode = MODE_ERROR if not is_available() else MODE_NOT_READY
        return CriticResult(mode, "", None, role, "; ".join(problems), 0.0, called_at)

    if role == ASK:
        # A question is text, always: «what does process/reviews/x.md say?» is about that file,
        # and sent as the file — or refused as one that is missing — it answers nobody (tcc#116).
        package_path = write_package(package, project_dir)
    else:
        package_path = _package_file(package, project_dir)
        if package_path is None and _shaped_like_a_package_path(package):
            return CriticResult(MODE_ERROR, "", None, role, f"no package file at {package.strip()}",
                                0.0, called_at)
        package_path = package_path or write_package(package, project_dir)

    argv = [python_executable, str(script_path()), role, str(package_path)]
    if trace_path:
        argv.append(str(trace_path))
    via = (via or "").strip().lower() or via_of(harness)
    if via in VIA_ROUTES:
        argv += ["--via", via]
    # The run's own model by the method's flag (hub #226). An environment variable is outranked by
    # every critic-env line, which the method writes over the environment: on the VM a pinned
    # `gpt-5.6-terra` ran under the footer's «API · gemini-3.1-pro-preview» (finding 130, tcc#113).
    # An omp pick's vendor is omp's business (tcc#74), so no `--provider` goes with it.
    by_flag = bool(model) and takes_model_flag()
    if by_flag:
        argv += ["--model", model]
        if (provider or "").strip().lower() in PROVIDERS and via != "omp":
            argv += ["--provider", provider.strip().lower()]

    env_overrides = {"PROJECT_MIRROR": str(_project_mirror(project_dir))}
    if model:
        # ONE variable, for both tasks. The advisor's own model variables are no longer read by
        # the reviewer (`v3.0.49`, hub SKL-032): a value left in one of them is named on stderr,
        # not obeyed. And writing one was the whole of #130 — TCC set the critic's model, the
        # advisor door looked for its own, found none, and the channel answered as a clipboard
        # package with `model: null` for thirteen calls. Still set beside `--model`: the only road
        # to a method before v3.0.65, and to a newer one a value equal to the run's own model is
        # no pin it set aside.
        env_overrides["GEMINI_CRITIC_MODEL"] = model

    # TCC-002: a stale `GEMINI_BIN` inherited from the machine outranks the reviewer's own
    # autodetection and sends every call down a path Google closed. Corrected only when it cannot
    # work and a working CLI is installed — see `critic_bin_override`.
    override = critic_bin_override(harness=harness)
    env_overrides.update(override)
    env_overrides.update(extra_env or {})

    env = vendor_loader.child_env(**env_overrides)
    # Finding 32: the reviewer tries the API BEFORE the CLI whenever its key is set, so a key in the
    # shell that started TCC sent a CLI pick down the API — where the CLI's model name is a 404 —
    # and the call failed two different ways on one machine without saying which. With a CLI
    # picked, the key that would reroute it stays out of this child's environment. The person's
    # own `critic-env` file is the reviewer's to read and is not touched.
    # Unless this run ASKS for the API: then the key is the route (tcc#59).
    rerouting = () if via == "api" else _CLI_REROUTING_KEYS.get((harness or "").lower(), ())
    dropped = [var for var in rerouting if env.pop(var, None)]
    if dropped:
        app_log.logger().info("critic: %s left out for the %s pick", ", ".join(dropped), harness)
    # Said out loud, because not saying it cost a whole round trip. `AUTOSOUND_CRITIC_BIN` is put
    # into the CHILD's environment and nowhere else, so looking at TCC's own `os.environ` shows
    # `None` on a fixed build exactly as it does on a broken one — and a session on the machine
    # read that as "the fix did not arrive" (2026-09-11). This line answers the only question that
    # matters: which binary this call actually went out with, and who decided it.
    app_log.logger().info(
        "critic: bin=%s (%s) model=%s (%s) harness=%r inherited GEMINI_BIN=%r",
        env.get("AUTOSOUND_CRITIC_BIN") or env.get("GEMINI_BIN") or "(the script autodetects)",
        "TCC, from the Arbiter's pick" if override else "not set by TCC",
        model or "(the script's default)",
        "--model" if by_flag else "GEMINI_CRITIC_MODEL" if model else "none sent",
        harness, os.environ.get("GEMINI_BIN"))
    try:
        proc = subprocess.run(
            argv,
            cwd=str(project_dir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s, **child.quiet())
    except subprocess.TimeoutExpired:
        return CriticResult(
            MODE_ERROR, "", None, role, f"reviewer timed out after {timeout_s:.0f}s",
            time.monotonic() - started, called_at,
        )
    except OSError as exc:
        return CriticResult(
            MODE_ERROR, "", None, role, str(exc), time.monotonic() - started, called_at
        )

    duration = time.monotonic() - started
    stdout, stderr = proc.stdout or "", proc.stderr or ""
    tail = "\n".join(line for line in stderr.strip().splitlines()[-6:])
    # Whatever the outcome: the method names a pin it set aside before it calls anybody.
    pins = _pins_set_aside(stderr) if by_flag else None
    called = _API_CONNECT.search(stderr.lower())
    api_vendor = called.group(1) if called else ""

    # Deliberately not `proc.returncode == 0`: clipboard mode returns 0 with nothing on stdout.
    match = _MODEL_MARKER.search(stdout)
    review_match = _REVIEW_MARKER.search(stderr)
    # As a POSIX path, whatever the OS: the method builds it with `os.path.join`, so on Windows it
    # read `process\reviews\…` in the bubble, the journal and the tools' answers alike — and the
    # journal is read on other machines (tcc#116, CI on Windows). The path is project-relative.
    review = PureWindowsPath(review_match.group("path")).as_posix() if review_match else None
    if stdout.strip():
        text = _MODEL_MARKER.sub("", stdout).strip()
        return CriticResult(
            MODE_API_OR_CLI, text, match.group("model") if match else None, role, tail,
            duration, called_at, review, pins_set_aside=pins, api_vendor=api_vendor,
        )
    if proc.returncode == _REFUSED_EXIT:
        package_match = _PACKAGE_MARKER.search(stderr)
        return CriticResult(MODE_REFUSED, "", None, role, _why_refused(stderr) or tail,
                            duration, called_at,
                            package=package_match.group("path") if package_match else None,
                            pins_set_aside=pins, api_vendor=api_vendor)
    if proc.returncode == _CHOOSE_MODEL_EXIT:
        return CriticResult(MODE_CHOOSE_MODEL, "", None, role, stderr.strip() or tail,
                            duration, called_at, review, _models_offered(stderr),
                            pins_set_aside=pins, api_vendor=api_vendor)
    if _CLIPBOARD_MARKER in stderr:
        # The clipboard path writes the compiled PACKAGE to the same place, so a review the Arbiter
        # works by hand is on the record rather than looking like no review at all.
        return CriticResult(MODE_CLIPBOARD, "", None, role, _why_clipboard(stderr) or tail,
                            duration, called_at, review, pins_set_aside=pins,
                            api_vendor=api_vendor)
    return CriticResult(MODE_ERROR, "", None, role, tail or "reviewer produced no output",
                        duration, called_at, pins_set_aside=pins, api_vendor=api_vendor)


def log_path(project_dir: Optional[Path] = None) -> Path:
    return config.tcc_dir(project_dir) / "critic-log.jsonl"


def _why_refused(stderr: str) -> str:
    """The reasons a refusal lists: the lines after "⛔" up to the rule that closes the block.

    By shape, not by sentence: the heading and the lines are Ukrainian prose the method may reword,
    the block is the stop sign and the `=` rule after it.
    """
    lines = stderr.splitlines()
    start = next((i for i, line in enumerate(lines) if "⛔" in line), None)
    if start is None:
        return ""
    out = []
    for line in lines[start + 1:]:
        if line.strip() and not set(line.strip()) - set("="):
            break
        if line.strip():
            out.append(line.strip())
    return "\n".join(out)


def _why_clipboard(stderr: str) -> str:
    """What the reviewer said BEFORE it gave up, which is the one thing nobody could see.

    `tail` takes the last six lines, and for this mode those are always the same six: the clipboard
    banner the script prints on its way out ("open any AI chat and press Ctrl+V"). The reason —
    what the CLI actually answered — is printed just ABOVE it and was pushed off the end every
    time. Thirteen calls in a row reported "mode: clipboard" with nothing to act on, and the code
    was dutifully reporting the wrong end of the same string (measured 2026-09-11).

    So: the lines immediately before the banner, minus the decoration the script draws with.
    """
    head = stderr.split(_CLIPBOARD_MARKER)[0]
    lines = [
        line.strip() for line in head.strip().splitlines()
        if line.strip() and set(line.strip()) - set("=-─━ ")
    ]
    return "\n".join(lines[-8:])


#: Where the Antigravity CLI keeps its settings. Read out of the binary itself (2026-09-11),
#: because the obvious guesses are all wrong: not `~/.agy`, not `%APPDATA%\agy`. A session on the
#: Arbiter's machine looked in both, found nothing, and concluded the file had to be created.
AGY_SETTINGS = "~/.gemini/antigravity-cli/settings.json"

#: What the reviewer's own words look like when it is one of the three things we can act on. Matched
#: loosely and case-insensitively: these come from a CLI that is free to reword them, so a miss must
#: degrade to "here is what it said" rather than to a wrong instruction.
_PERMISSION_WORDS = ("permission", "not allowed", "trust", "дозвіл", "settings.json")
_BAD_KEY_WORDS = ("http 400", "400 bad request", "api key", "api_key", "invalid key")
#: Checked BEFORE the model words: "Selected model is not supported in the selected location" also
#: says "model", and the model advice (names drift, press ↻) is wrong for it — the CLI still lists
#: the model, so ↻ brings it straight back (Windows session, 2026-09-13).
_LOCATION_WORDS = ("selected location", "your location", "your region", "not available in your country")
#: A CLI refusing the model it was given, in its own words: the method's recogniser (`_FAILURES`'
#: `bad_model`), agy's «model '…' is not available», the method's own 404 for a model the key
#: cannot call, its «Модель `…` omp не знає: …» / «… CLI 'agy' не знає: …», and its «CLI 'agy' не
#: знає `…` (так модель називає API)» for an API id stepped down to agy (skill #85). Not the bare
#: word «model»: the method's line naming the pins a run set aside (`AUTOSOUND_CRITIC_MODEL=…`, hub
#: #226) says it, and an answered run read as refused (VM-4). Nor «API не знає `…` (404), а CLI її
#: знає»: that is the method taking the CLI for a model it serves, not a refusal.
_BAD_MODEL_WORDS = ("invalid model", "not recognized as a known model", "unknown model",
                    "not available", "цей ключ викликати не може", "не підтримується")
_MODEL_NOT_FOUND = re.compile(
    r'\bmodel "[^"]*" not found|модель `[^`]*`[^\n]* не знає:|cli \'[^\']*\' не знає `[^`]+`')
#: The method's step down from a failed API call to a CLI: `>> Помилка виклику API (<why>). Спроба
#: локального CLI...`. On a run that answered, the one line that can say the key was rejected.
_API_STEP_DOWN = re.compile(r"^>> Помилка виклику API \(.*$", re.M)
#: The key a vendor's words point to, for a line that names no variable itself.
_KEY_VARS = (("gemini", "GEMINI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"),
             ("claude", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY"))
#: The key of a vendor as the method names it (`provider`).
_VENDOR_VARS = {"google": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY"}
#: The method's line before its API call, naming the vendor it calls (lowercased, as `_said` reads
#: it): `>> Підключення до API (<provider>, <model>), чекаю до … с...`.
_API_CONNECT = re.compile(r"^>> підключення до api \((google|anthropic|openai), ", re.M)
#: A refusal block's line for the API rung (`failures`, `· API <provider>: <e>`): the same words
#: as the step-down line, which a run that did not answer carries only here (`_why_refused`).
_API_REFUSED = re.compile(r"^\s*· api (google|anthropic|openai): .*$", re.M)
#: The status that is the KEY when the words name none: Anthropic and OpenAI calls let urllib's
#: own `HTTP Error 401: Unauthorized` through, and no key word matched it (tcc#129). 401 only: a
#: bare 403 is most often not the key — Anthropic's «Request not allowed» from a region, a proxy
#: or a VPN, OpenAI's a country it does not serve — and the words cannot tell it from a key's
#: permissions (review of #129). Gemini's errors come wrapped in its own words (`Помилка запиту до
#: Gemini API: …`), and its rejected key says «API key not valid».
_KEY_STATUS = re.compile(r"\bhttp error 401\b")
#: The vendors whose errors come bare, so a bare 401 names one of their keys (`_post_json`).
_BARE_VENDORS = ("anthropic", "openai")


def _said(detail: str) -> str:
    """A failure's words as the hints read them: lowercased, and without the line that names the
    pins the run set aside — #113 reads that into the footer's note, never as a refusal (VM-4)."""
    return _PINS_LINE.sub("", detail or "").lower()


def _key_note(line: str, vendor: str = "") -> str:
    """The rejected-key note, naming the variable `line` (lowercased) points to — not Gemini's for
    every key (VM-4 review) — or else `vendor`'s, the one the method said it called (tcc#129); a
    line and a run that name no vendor name no variable."""
    named = re.search(r"\b[a-z]+_api_key\b", line)
    var = named.group(0).upper() if named else (
        _VENDOR_VARS.get(vendor) or next((var for word, var in _KEY_VARS if word in line), ""))
    return (
        f"{f'`{var}`' if var else 'The API key'} is set and the API rejected it. It is tried "
        "BEFORE the CLI, so every call spends that time first and then falls back. Replace the "
        "key or remove the variable — with it gone the call goes straight to the CLI, which is "
        "the path that works on a subscription login."
    )


def fallback_note(detail: str, *, vendor: str = "") -> str:
    """On a run that ANSWERED, the one hint still true of it, or "": the API rejected the key and a
    CLI answered after it, so every call spends the API's attempt first (VM-4 review).

    Read from the method's own step-down line only, never the whole tail: an answered `--via api`
    run names the key it took in another line («api_key»), and the pins line names variables too.
    The variable named is the vendor's the method said it called: from its line before the call,
    or — that line always outside an answered run's six-line tail — `vendor`, which `run` read
    from the whole of its stderr (`CriticResult.api_vendor`, review of #129).
    """
    for said, called in _api_failures(detail, refusal=False, vendor=vendor):
        note = _key_rejection(said, called)
        if note:
            return note
    return ""


def _api_failures(detail: str, *, refusal: bool, vendor: str = "") -> list[tuple[str, str]]:
    """`(line, vendor)`, lowercased, for each of the method's own lines saying its API call failed:
    the step-down — its vendor from the line before the call, else `vendor` — and, with `refusal`,
    a refusal block's `· API <vendor>: …`, which names its own."""
    said = (detail or "").lower()
    called = _API_CONNECT.search(said)
    vendor = called.group(1) if called else vendor
    lines = [(line.lower(), vendor) for line in _API_STEP_DOWN.findall(detail or "")]
    if refusal:
        lines += [(match.group(0), match.group(1)) for match in _API_REFUSED.finditer(said)]
    return lines


def _key_rejection(said: str, vendor: str) -> str:
    """The rejected-key note for the method's API-failure line `said`, or "": a key word, or the
    bare 401 that names no key (tcc#129). Unwrapped, those words are Anthropic's or OpenAI's, so a
    vendor said to be another names no variable rather than the wrong one."""
    if any(word in said for word in _BAD_KEY_WORDS):
        return _key_note(said, vendor)
    if not _KEY_STATUS.search(said) or "gemini api" in said:
        return ""
    return _key_note(said, vendor if vendor in _BARE_VENDORS else "")


def _refused_tool(said: str) -> str:
    """The tool agy says it refused, spelled as agy spells it (`read_file`), or ""."""
    match = re.search(r'"([a-z_]+)"\s+permission', said) or re.search(r"\b([a-z_]+)\(", said)
    return match.group(1) if match else ""


def remedy(detail: str, *, harness: str = "", project_dir: Optional[Path] = None) -> str:
    """ONE concrete thing to do, or "" when we cannot name one honestly.

    The reviewer's own words are now carried out (`_why_clipboard`), and they are precise enough to
    act on — but only to somebody who already knows where that CLI keeps its settings. Nobody did:
    a session on the machine advised `--dangerously-skip-permissions`, which is a bigger hammer
    than the situation needs and leaves no trace of a decision.

    So this turns a diagnosis into an instruction: which file, which key, which value. A message
    that explains a failure without naming the next action is the same dead end as `mode:
    clipboard` with nothing in it — one step further along, and still nowhere.
    """
    said = _said(detail)
    if not said.strip():
        return ""
    if any(word in said for word in _PERMISSION_WORDS):
        where = project_dir or config.project_dir()
        # agy's own words, not a guess about its settings (tcc#36). This used to name
        # `trustedWorkspaces`; the Arbiter followed it on Windows and the refusal came back
        # byte-identical — the project folder was never the gate. It also offered
        # `toolPermission: always-proceed` next, which after a narrow fix that did nothing walks a
        # person to "every folder" by elimination. The method answered in v3.0.53 (hub #150): agy
        # gets the package on STDIN, so no file is read, and a per-run CLI flag can be passed with
        # `AUTOSOUND_CRITIC_CLI_ARGS`. A refusal here therefore means an older method or a tool the
        # prompt made agy call on its own — said so, with agy's own remedy and the per-run route
        # (findings 23, 25).
        tool = _refused_tool(said) or "read_file"
        return (
            f"agy runs the reviewer headless, so it cannot ask for the `{tool}` permission and "
            f"refuses it. Since the method's v3.0.53 the package goes to agy on stdin and no file "
            f"has to be read — if this persists, update the method. agy's own answer is an "
            f"allow-rule under `permissions.allow` in `{AGY_SETTINGS}`, in the form it prints: "
            f"`{tool}(<target>)`; this project is at {where}. A flag for one run goes through "
            f"`AUTOSOUND_CRITIC_CLI_ARGS`. Meanwhile the clipboard step works: paste the package "
            f"into a web chat and bring the answer back."
        ) if (harness or "").lower() == "agy" else (
            f"the reviewer CLI is asking permission it has no standing answer for. It needs that "
            f"answer in its own settings; this project is at {where}."
        )
    keyed = [line for line in said.splitlines() if any(word in line for word in _BAD_KEY_WORDS)]
    if keyed:
        return _key_note(keyed[0])
    # A status that is the key, read from the method's own API lines only: a CLI's 401 is its
    # sign-in, not the key (tcc#129).
    for line, vendor in _api_failures(detail, refusal=True):
        note = _key_rejection(line, vendor)
        if note:
            return note
    if any(word in said for word in _LOCATION_WORDS):
        return (
            "the reviewer's vendor does not offer this model from where this machine is — the CLI "
            "refused it by location, before the model ran. ↻ will not help: the CLI still lists it. "
            "Pick a different Critic model in TCC's footer."
        )
    if any(word in said for word in _BAD_MODEL_WORDS) or _MODEL_NOT_FOUND.search(said):
        return (
            "the reviewer CLI refused the model it was given. Model names drift and the CLI prints "
            "its own list; pick another Critic in TCC's footer, or press ↻ beside it to re-read "
            "what this machine can actually run."
        )
    return ""


def refusal_reason(detail: str) -> Optional[str]:
    """The availability reason a failed call's own words point to, or None when there are none.

    A location refusal is named as such — it is the one reason nothing on this machine can fix. Any
    other words are a refusal too: the call went out and no review came back."""
    from autosound_tcc.core import availability

    said = _said(detail)
    if not said.strip():
        return None
    if any(word in said for word in _LOCATION_WORDS):
        return availability.LOCATION
    return availability.REFUSED


def log_call(result: CriticResult, package_path: Optional[Path], project_dir: Optional[Path] = None,
             *, asked: str = "") -> None:
    """Append one reviewer call to an append-only log.

    "Which AI reviewed this, on which model, when" is part of the process record the concept calls
    for (TCC-Concept §4: the advisor panel shows vendor/model and when it was last called). It
    lives here until SCR-004's `process-state.json` exists to hold it properly.

    `asked` is the model the call asked for, beside the one that answered (`model`): only the two
    together say a fallback happened. Without it a review by the reviewer picked BEFORE read as a
    fallback of the one picked now (finding 142, tcc#140). A line without it is no evidence.
    """
    import json

    path = log_path(project_dir)
    entry = {
        "at": result.called_at,
        "role": result.role,
        "mode": result.mode,
        "asked": asked or None,
        "model": result.model,
        "duration_s": round(result.duration_s, 1),
        "package": str(package_path) if package_path else None,
        "review": result.review,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # the log is a convenience; losing it must not fail the call that succeeded


def last_call(project_dir: Optional[Path] = None) -> Optional[dict]:
    """The most recent reviewer call, for the footer's advisor status. None if never called."""
    import json

    path = log_path(project_dir)
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def doctor(project_dir: Optional[Path] = None, python_executable: Optional[str] = None) -> str:
    """The script's own environment check, for a settings/status screen."""
    if not is_available():
        return f"reviewer script not found at {script_path()}"
    # The console interpreter, not TCC's windowed one (`child.script_interpreter`).
    python_executable = python_executable or child.script_interpreter()
    project_dir = Path(project_dir or config.project_dir())
    try:
        proc = subprocess.run(
            [python_executable, str(script_path()), "doctor"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=vendor_loader.child_env(**critic_bin_override()),  # TCC-002, as above
            **child.quiet(),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"doctor failed: {exc}"
    return (proc.stdout or proc.stderr).strip()
