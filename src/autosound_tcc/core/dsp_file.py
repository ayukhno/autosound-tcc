"""A DSP's saved preset file against the journal (#272): which files the method reads, and what its
`compare-file` answered.

**What the method reads comes from the method** (the Arbiter, 2026-11-22). From v3.3.3 the method
declares each saved-file reader in `knowledge/dsp/readers.json` (`readers.v1`, its CONTRACT.md item
15): the vendor family, the file pattern, the verbs that read it, the models it was checked on. TCC
reads that declaration from the copy of the method the project runs. A copy without it (v3.3.2)
gets `FALLBACK`, TCC's own two rows — and a test fails when the vendored contract's item 13 names a
file the table lacks. The table goes when the declaration is pinned.

**The declaration is advice, not a gate.** A DSP of a listed family has the button on whatever its
model: another model is read at the person's own risk, and the method's answer says so. A refusal
is the method's to give and is shown as given. TCC decodes no DSP file itself: every read is
`state/apply.py <project> compare-file`, read only (item 13), and the file is never written.

A comparison with rows that differ, on a reader that lists `propose --from-file`, can be banked as a
new version (#273): `propose` below, under the method's writer lock. The method writes the journal;
TCC never does, and never writes the file.

Qt-free: the window's button and table are `ui/tcc/dsp_file_check.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import NamedTuple, Optional, Union

from autosound_tcc.core import app_log, method_binding, method_cli, vendor_loader
from autosound_tcc.state import ledger_line, preset_settings

#: The method's declaration of its readers, relative to the skill folder (item 15), and its shape.
DECLARATION = Path("knowledge") / "dsp" / "readers.json"
CONTRACT = "readers.v1"
#: The verbs a reader may list (item 15): the comparison, and the two that bank from the file.
COMPARE = "compare-file"
ATTEST = "attest --from-file"
PROPOSE = "propose --from-file"
#: What `compare-file --json` names its shape (item 13).
COMPARE_SHAPE = "compare-file.v1"
#: The method's own script for the read, relative to its `rew_tool/`.
SCRIPT = "state/apply.py"
#: The bound of one read: a file of a few kilobytes, read and compared, well under a second.
TIMEOUT_S = 60.0

#: compare-file's exits (item 13): compared whatever the rows say; the journal refused; the file
#: could not be read (or usage); the file changed while it was read.
EXIT_COMPARED, EXIT_JOURNAL, EXIT_FILE, EXIT_CHANGED = 0, 1, 2, 3
#: The categories a row has (item 13), in the order the method puts them: sound first.
CATEGORIES = ("audio", "system", "naming", "ui_state", "save_metadata", "structure", "unknown")
#: A row's result (item 13); anything else is read as `unknown`, never as a match.
RESULTS = ("match", "differs", "unknown")


class Reader(NamedTuple):
    """One saved-file reader of the method: `readers.v1`'s keys TCC reads."""

    id: str
    family: str
    pattern: str
    verbs: tuple[str, ...]
    models: tuple[str, ...] = ()
    #: `declared` (the method's `readers.json`) or `fallback` (TCC's table, a pin without it).
    source: str = "declared"

    def reads(self, verb: str) -> bool:
        return verb in self.verbs

    def matches(self, file_name: str) -> bool:
        """Whether a file of this name is one the reader reads, by its extension."""
        return _pattern_re(self.pattern).search(file_name or "") is not None


#: Two rows, for a pin whose method declares nothing (v3.3.2): what its CONTRACT.md items 13 and 14
#: say it reads. Its `attest --from-file` refuses a `.PR` file (item 14), so Mosconi's row lists the
#: comparison alone. Goes when the declaration is pinned (#272, «Decided»).
FALLBACK: tuple[Reader, ...] = (
    Reader("helix_pct6", "Audiotec-Fischer", ".pct6", (COMPARE, ATTEST, PROPOSE),
           ("HELIX DSP ULTRA S",), "fallback"),
    Reader("mosconi_pr", "Mosconi", ".PR<n>", (COMPARE,), ("Mosconi PICO 6/8-2 DSP",), "fallback"),
)

#: Brands a family's DSPs are named by, where a profile may name the brand and not the vendor: a
#: profile says `Helix` as often as `Audiotec-Fischer` (`preset_settings.is_audiotec`).
_BRANDS = {"audiotec-fischer": ("helix",)}


def _pattern_re(pattern: str) -> re.Pattern:
    """`.pct6` and `.PR<n>` as an end-of-name match, case-insensitive: `<n>` is a number."""
    parts = re.split(r"<[^<>]*>", pattern or "")
    return re.compile("".join(re.escape(part) + r"\d+" for part in parts[:-1]) + re.escape(parts[-1]) + "$",
                      re.IGNORECASE)


def _reader(item) -> Optional[Reader]:
    """One `readers.v1` entry, or None where any field TCC reads is not of its type: the caller
    takes the whole declaration as unreadable then, never the entries that happen to parse."""
    if not isinstance(item, dict):
        return None
    family, pattern, verbs = item.get("family"), item.get("pattern"), item.get("verbs")
    models = item.get("models", [])
    if not (isinstance(family, str) and family.strip() and isinstance(pattern, str) and pattern.strip()
            and isinstance(verbs, list) and all(isinstance(verb, str) for verb in verbs)
            and isinstance(models, list)
            and all(isinstance(model, dict) and isinstance(model.get("name"), str) for model in models)):
        return None
    return Reader(str(item.get("id") or family), family.strip(), pattern.strip(), tuple(verbs),
                  tuple(model["name"] for model in models), "declared")


#: path -> (mtime_ns, size, readers or None): read again when the file changes.
_CACHE: dict[str, tuple[int, int, Optional[tuple[Reader, ...]]]] = {}


def declared(skill_dir: Union[str, os.PathLike, None]) -> Optional[tuple[Reader, ...]]:
    """The readers the copy at `skill_dir` declares, or None where it declares none: no file (a
    pin before v3.3.3), or one TCC cannot read as `readers.v1` — said in the log, and the fallback
    answers, as on a pin without it."""
    if skill_dir is None:
        return None
    path = Path(skill_dir) / DECLARATION
    try:
        info = path.stat()
    except OSError:
        return None
    key = str(path)
    cached = _CACHE.get(key)
    if cached is not None and cached[:2] == (info.st_mtime_ns, info.st_size):
        return cached[2]
    found: Optional[tuple[Reader, ...]] = None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        listed = (data.get("readers") if isinstance(data, dict) and data.get("contract") == CONTRACT
                  else None)
        parsed = [_reader(item) for item in listed] if isinstance(listed, list) else [None]
        if all(reader is not None for reader in parsed):
            found = tuple(parsed)
        else:
            app_log.logger().warning("dsp file: %s is not %s as TCC reads it; TCC's own table answers",
                                     path, CONTRACT)
    except Exception as exc:  # noqa: BLE001 - an unreadable declaration is the fallback, never a load that fails
        app_log.logger().warning("dsp file: %s cannot be read (%s); TCC's own table answers", path, exc)
    _CACHE[key] = (info.st_mtime_ns, info.st_size, found)
    return found


def skill_folder(project_dir: Union[str, os.PathLike, None] = None) -> Optional[Path]:
    """The skill folder of the copy the project runs (`method_binding`), or TCC's own where the
    project is refused or not given: the declaration is read from the copy that would read the file."""
    try:
        if project_dir is not None:
            binding = method_binding.for_project(project_dir)
            if binding.skill_dir is not None:
                return Path(binding.skill_dir)
        return vendor_loader.skill_dir()
    except Exception:  # noqa: BLE001 - no copy found is no declaration, never a crash on a render
        app_log.logger().exception("dsp file: no copy of the method to read its readers from")
        return None


def readers(project_dir: Union[str, os.PathLike, None] = None) -> tuple[Reader, ...]:
    """The readers of the copy the project runs: its declaration, or `FALLBACK` without one."""
    found = declared(skill_folder(project_dir))
    return FALLBACK if found is None else found


def _words(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _of_family(family: str, vendor, name) -> bool:
    said = " %s " % _words("%s %s" % (vendor or "", name or ""))
    names = (family, *_BRANDS.get(family.strip().lower(), ()))
    return any(f" {_words(word)} " in said for word in names if _words(word))


def reader_for(profile, project_dir: Union[str, os.PathLike, None] = None,
               found: Optional[tuple[Reader, ...]] = None) -> Optional[Reader]:
    """The reader for this DSP profile's family, or None: told by the profile's vendor and name
    against the declared family (and its brand). The model is not asked: another model of the
    family is read at the person's own risk, and the method says so."""
    prof = profile.get("dsp_profile", profile) if isinstance(profile, dict) else {}
    if not isinstance(prof, dict):
        return None
    vendor, name = prof.get("vendor"), prof.get("name")
    found = readers(project_dir) if found is None else found
    for reader in found:
        if _of_family(reader.family, vendor, name):
            return reader
    # The Helix rule before #272, kept for a profile that names neither the vendor nor the brand
    # as a word of its own (`HelixDSP`).
    if preset_settings.is_audiotec(vendor, name):
        return next((r for r in found if r.family.lower().startswith("audiotec")), None)
    return None


# ---- the comparison ---------------------------------------------------------------------------


class Row(NamedTuple):
    channel: str
    parameter: str
    journal: object
    file: object
    result: str
    category: str
    reason: Optional[str]


class Answer(NamedTuple):
    """What one `compare-file` said, as TCC shows it.

    `kind` is `compared` (exit 0, the rows), `refused` (exits 1-3: the method's refusal, the file's
    or the journal's) or `failed` (no answer to read: a refused binding, a timeout, an exit the
    contract does not name, an answer that is not the shape). Only `compared` carries rows."""

    kind: str
    code: Optional[int]
    warning: str = ""
    warning_uk: str = ""
    checked_model: Optional[bool] = None
    device: str = ""
    file_name: str = ""
    md5: str = ""
    saved: str = ""
    counts: dict = {}
    rows: tuple[Row, ...] = ()
    error_kind: str = ""
    message: str = ""


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _row(item) -> Optional[Row]:
    if not isinstance(item, dict):
        return None
    result = item.get("result") if item.get("result") in RESULTS else "unknown"
    category = item.get("category") if isinstance(item.get("category"), str) else "unknown"
    reason = item.get("reason") if isinstance(item.get("reason"), str) else None
    return Row(str(item.get("channel") or ""), str(item.get("parameter") or ""), item.get("journal"),
               item.get("file"), result, category, reason)


def ordered(rows) -> tuple[Row, ...]:
    """Sound rows first, then each category apart, in the method's order; within one, as given."""
    rank = {name: i for i, name in enumerate(CATEGORIES)}
    return tuple(sorted(rows, key=lambda r: rank.get(r.category, len(CATEGORIES))))


def _read(data: dict, code: int, err: str = "") -> Answer:
    file = data.get("file") if isinstance(data.get("file"), dict) else {}
    device = data.get("device") if isinstance(data.get("device"), dict) else {}
    common = dict(code=code, warning=_text(data.get("warning")), warning_uk=_text(data.get("warning_uk")),
                  file_name=_text(file.get("name")), md5=_text(file.get("md5")), saved=_text(file.get("saved")))
    if code != EXIT_COMPARED:
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        return Answer("refused", error_kind=_text(error.get("kind")),
                      message=_text(error.get("message")) or method_cli.tail(err), **common)
    listed = data.get("rows")
    if not isinstance(listed, list) or not all(isinstance(item, dict) for item in listed):
        # A table with rows dropped would disagree with the counts the method printed beside it.
        return Answer("failed", code, message=f"compare-file's rows are not the contract's list of "
                                              f"rows: {method_cli.tail(json.dumps(listed), 1)[:200]}")
    rows = tuple(_row(item) for item in listed)
    checked = data.get("checked_model")
    counts = (data.get("counts") or {}).get("result") if isinstance(data.get("counts"), dict) else None
    return Answer("compared", checked_model=checked if isinstance(checked, bool) else None,
                  device=_text(device.get("name")) or _text(device.get("dev")),
                  counts={k: v for k, v in (counts or {}).items() if k in RESULTS and isinstance(v, int)},
                  rows=ordered(rows), **common)


def interpret(code: int, out: str, err: str) -> Answer:
    """`(exit, stdout, stderr)` of `compare-file --json` as an `Answer` (item 13). An exit the table
    does not name, or a stdout that is not its shape, is `failed` with what the child said: never a
    result, and never «no difference»."""
    if code not in (EXIT_COMPARED, EXIT_JOURNAL, EXIT_FILE, EXIT_CHANGED):
        return Answer("failed", code, message=method_cli.tail(err) or method_cli.tail(out))
    if not out.strip():
        # Usage (exit 2 with nothing on stdout), or a refusal with no JSON: the method's own line.
        if code == EXIT_COMPARED:
            return Answer("failed", code, message=method_cli.tail(err) or "compare-file printed nothing")
        return Answer("refused", code, error_kind="usage" if code == EXIT_FILE else "",
                      message=method_cli.tail(err))
    try:
        data = json.loads(out)
    except ValueError:
        return Answer("failed", code, message=method_cli.tail(err) or method_cli.tail(out))
    if not isinstance(data, dict) or data.get("contract") != COMPARE_SHAPE:
        return Answer("failed", code, message=method_cli.tail(err) or method_cli.tail(out))
    return _read(data, code, err)


def compare(project_dir: Union[str, os.PathLike], version: str, file_path: Union[str, os.PathLike],
            preset: Optional[str] = None) -> Answer:
    """`state/apply.py <project> compare-file <version> FILE --json [--preset P]`, through the
    project's copy of the method: read only, no lock (item 13 takes none). Blocks — run it off
    the GUI thread."""
    # `apply.py`'s first word is the project, as `agents_md` passes it: the verb comes after.
    args = [str(project_dir), COMPARE, version, str(file_path), "--json"]
    if isinstance(preset, str) and preset:
        args += ["--preset", preset]
    try:
        code, out, err = method_cli.spawn(project_dir, SCRIPT, args, timeout_s=TIMEOUT_S, lock=False, holds=0)
    except method_cli.ProcessWriterError as exc:
        return Answer("failed", None, message=str(exc))
    app_log.logger().info("compare-file %s against %s -> exit %s", version, Path(file_path).name, code)
    return interpret(code, out, err)


# ---- a new version from the file (#273) -------------------------------------------------------

#: `propose --from-file`'s exits (item 14): banked; the journal refused; the file cannot be read or
#: interpreted, is a file the copy does not bank from (`model`), or usage; the file changed while it
#: was read. Nothing is banked on 1-3. A held lock, 75, is `method_cli.Busy` before it gets here.
EXIT_BANKED = 0
#: The bound of one bank: the same read as a comparison, then one snapshot under the method's lock
#: (whose wait `method_cli.spawn` adds on top).
PROPOSE_TIMEOUT_S = 60.0
#: The line that names the version banked: `🟡 proposed v_002 on FULL, read from AYA.pct6`, or
#: `🟠 candidate v_002 …` (item 14 has no `--json`, so the text is what there is to read).
_BANKED_LINE = re.compile(r"\b(?:proposed|candidate)\s+(v_\d+)\b")


class Saved(NamedTuple):
    """What one `propose --from-file` said.

    `kind` is `banked` (exit 0), `refused` (exits 1-3: nothing banked), `busy` (exit 75 or TCC's
    own lock past its wait: nothing written, the same call may go through later), `failed` (no
    answer TCC can read: an exit the contract does not name), `timed_out` (the child was cut at its
    bound: a write cut halfway may have landed) or `not_run` (no child: a copy TCC will not run, a
    script not there). TCC's own `stale` is a save it did not start: the read moved. `text` is the method's stdout
    as it printed it — the warning, the model line, the version, what it kept, did not take and
    took short — and `message` its stderr, or TCC's sentence where the method said nothing."""

    kind: str
    code: Optional[int]
    version: str = ""
    text: str = ""
    message: str = ""

    @property
    def may_have_written(self) -> bool:
        """All but the answers that guarantee nothing was written: a refusal (1-3, item 14), a held
        lock (75, item 8), a save TCC stopped before it started (`stale`) or could not start
        (`not_run`). An exit the contract
        does not name, or a child cut at its bound, may have banked: the window re-reads."""
        return self.kind not in ("refused", "busy", "stale", "not_run")


def differs(answer: Answer) -> bool:
    """Whether a comparison has a row that differs: the one result a new version is offered on."""
    return answer.kind == "compared" and any(row.result == "differs" for row in answer.rows)


def md5_of(file_path: Union[str, os.PathLike]) -> Optional[str]:
    """The file's md5, to tell whether it is the read a comparison showed (`compare-file`'s
    `file.md5` is the same hash): its bytes hashed, never decoded. None where it cannot be read —
    the method's own read says why."""
    try:
        return hashlib.md5(Path(file_path).read_bytes()).hexdigest()
    except OSError:
        return None


def journal_head(project_dir: Union[str, os.PathLike], preset: Optional[str]) -> Optional[str]:
    """HEAD of `preset` in the journal `propose` builds on, read now (`ledger_line.line_mark`):
    `<project>/state`, the root `apply.py` takes from its project argument, whatever
    `AUTOSOUND_STATE_ROOT` says. None where it cannot be read now, or no preset is named — the
    caller takes that as a HEAD it cannot confirm, never as the version it compared."""
    if not (isinstance(preset, str) and preset):
        return None
    try:
        return ledger_line.line_mark(Path(project_dir) / "state", preset)[0]
    except Exception:  # noqa: BLE001 - a journal that cannot be read now confirms nothing
        app_log.logger().exception("dsp file: the journal's HEAD could not be read")
        return None


def interpret_propose(code: int, out: str, err: str) -> Saved:
    """`(exit, stdout, stderr)` of `propose --from-file` as a `Saved` (item 14). A refusal is the
    method's line on stderr, whole; an exit the table does not name is `failed`, never a bank."""
    if code == EXIT_BANKED:
        found = _BANKED_LINE.search(out or "")
        return Saved("banked", code, found.group(1) if found else "", out, err)
    if code in (EXIT_JOURNAL, EXIT_FILE, EXIT_CHANGED):
        return Saved("refused", code, text=out, message=method_cli.tail(err, 20) or method_cli.tail(out))
    return Saved("failed", code, text=out, message=method_cli.tail(err) or method_cli.tail(out))


def propose(project_dir: Union[str, os.PathLike], file_path: Union[str, os.PathLike],
            preset: Optional[str] = None) -> Saved:
    """`state/apply.py <project> propose --from-file FILE [--preset P]`, through the project's copy
    of the method and under the writer lock, one hold, as TCC's other ledger writers take it
    (`config_writer`): TCC's thread lock around a child that takes the method's own. A new version
    on HEAD; no banked version is rewritten, and the file is never written. Blocks — run it off
    the GUI thread."""
    args = [str(project_dir), "propose", "--from-file", str(file_path)]
    if isinstance(preset, str) and preset:
        args += ["--preset", preset]
    try:
        code, out, err = method_cli.spawn(project_dir, SCRIPT, args, timeout_s=PROPOSE_TIMEOUT_S, lock=True,
                                          holds=1, cross_process=False)
    except method_cli.Busy as exc:
        return Saved("busy", method_cli.EXIT_BUSY, message=str(exc))
    except method_cli.TimedOut as exc:
        return Saved("timed_out", None, message=str(exc))
    except method_cli.ProcessWriterError as exc:
        # A copy TCC will not run, a script not there, an interpreter that would not start: no child.
        return Saved("not_run", None, message=str(exc))
    app_log.logger().info("propose --from-file %s -> exit %s", Path(file_path).name, code)
    return interpret_propose(code, out, err)
