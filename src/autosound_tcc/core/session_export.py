"""The last N agent sessions of a project, as one readable Markdown file (TODO F-054).

Claude Code writes every session to `~/.claude/projects/<project folder, as a name>/<id>.jsonl` —
the ones TCC's window runs and the ones a terminal opened in the project folder runs alike. Getting
them out took a hand-typed PowerShell line, and on a machine with no shared folder there was no
easy way at all (the Arbiter, 2026-09-14). The file is for reading where a session spends its words
— the intake above all: who said what, each tool call as one line, a tool's output cut to its first
lines. The Arbiter's choices, 2026-09-17: readable Markdown, a save dialog, every session of the
project.

Qt-free: the dialog asks where to save; this module finds, reads and renders.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

#: How much of a tool's output a session file keeps: enough to see what came back, not a log dump.
OUTPUT_LINES = 3
#: How long one line of a tool call or its output may run before it is cut.
LINE_CHARS = 160


def folder_name(project_dir) -> str:
    """The folder Claude Code keeps a project's sessions in: every character but letters, digits
    and `-` becomes `-`. Measured on both machines — `/Users/o.yukhno/dev/autosound/hub` is
    `-Users-o-yukhno-dev-autosound-hub`, and the VM's `C:\\Users\\o.yukhno\\_autosound\\testTCC8`
    is `C--Users-o-yukhno--autosound-testTCC8`."""
    return re.sub(r"[^A-Za-z0-9-]", "-", str(project_dir))


def recent_transcripts(project_dir, count: int, home: Optional[Path] = None) -> list[Path]:
    """The newest `count` sessions of this project, newest first; [] when there are none.

    Both spellings of the folder are looked in — as TCC knows it and with links resolved — because
    the name is whatever the session's working directory was, and on macOS a temporary folder is
    reachable as `/tmp` and `/private/tmp`.
    """
    root = Path(home or Path.home()) / ".claude" / "projects"
    names = {folder_name(project_dir)}
    try:
        names.add(folder_name(Path(project_dir).resolve()))
    except OSError:
        pass
    found: dict[Path, float] = {}
    for name in names:
        for path in (root / name).glob("*.jsonl"):
            try:
                found[path] = path.stat().st_mtime
            except OSError:
                continue
    return sorted(found, key=found.get, reverse=True)[:max(0, int(count))]


def phases_by_session(project_dir) -> dict[str, str]:
    """`session id -> phase`, from TCC's own `.tcc/sessions.json`; {} when there is none."""
    try:
        data = json.loads((Path(project_dir) / ".tcc" / "sessions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    phases = data.get("phases") if isinstance(data, dict) else None
    return {
        str(entry["session_id"]): str(phase)
        for phase, entry in (phases or {}).items()
        if isinstance(entry, dict) and entry.get("session_id")
    }


def render(paths: Iterable[Path], phases: Optional[dict] = None,
           title: str = "", now: Optional[datetime] = None) -> str:
    """One Markdown document: a heading per session, oldest first, and the exchange under it."""
    paths = list(paths)
    ordered = sorted(paths, key=lambda path: _mtime(path))
    out = [f"# Sessions{f' — {title}' if title else ''}",
           "",
           f"Written {(now or datetime.now()).isoformat(timespec='minutes')} · "
           f"{len(ordered)} session(s)",
           ""]
    for path in ordered:
        out.extend(_session(path, (phases or {}).get(path.stem)))
    return "\n".join(out).rstrip() + "\n"


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _lines(path: Path) -> list[dict]:
    records = []
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                try:
                    record = json.loads(raw)
                except ValueError:
                    continue  # a half-written last line of a session still running
                if isinstance(record, dict):
                    records.append(record)
    except OSError:
        pass
    return records


def _cut(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= LINE_CHARS else text[:LINE_CHARS - 1] + "…"


def _tool_line(block: dict) -> str:
    """`→ Bash: <the command's first line>` — the call, not its arguments dumped."""
    arguments = block.get("input") or {}
    if isinstance(arguments, dict) and isinstance(arguments.get("command"), str):
        summary = arguments["command"].strip().splitlines()[0] if arguments["command"].strip() else ""
    else:
        summary = json.dumps(arguments, ensure_ascii=False)
    return f"> → {block.get('name') or 'tool'}: {_cut(summary)}"


def _output_lines(block: dict) -> list[str]:
    content = block.get("content")
    if isinstance(content, list):
        content = "\n".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    lines = [line for line in str(content or "").splitlines() if line.strip()]
    shown = [f">   {_cut(line)}" for line in lines[:OUTPUT_LINES]]
    if len(lines) > OUTPUT_LINES:
        shown.append(f">   … {len(lines) - OUTPUT_LINES} more lines")
    return shown


def _clock(record: dict) -> str:
    stamp = str(record.get("timestamp") or "")
    return stamp[11:16] if len(stamp) >= 16 else ""


def _session(path: Path, phase: Optional[str]) -> list[str]:
    body: list[str] = []
    turns = words = calls = 0
    stamps = []
    for record in _lines(path):
        kind = record.get("type")
        message = record.get("message")
        if kind not in ("user", "assistant") or not isinstance(message, dict):
            continue
        if record.get("isMeta") or record.get("isSidechain"):
            continue  # injected skill text and subagents' own traffic are not the exchange
        if record.get("timestamp"):
            stamps.append(str(record["timestamp"]))
        content = message.get("content")
        if kind == "user" and isinstance(content, str):
            turns += 1
            body.extend([f"**Arbiter** · {_clock(record)}", "", content.strip(), ""])
            continue
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if kind == "assistant" and block.get("type") == "text" and str(block.get("text")).strip():
                words += len(str(block["text"]).split())
                body.extend([f"**Model** · {_clock(record)}", "", str(block["text"]).strip(), ""])
            elif kind == "assistant" and block.get("type") == "tool_use":
                calls += 1
                body.extend([_tool_line(block), ""])
            elif kind == "user" and block.get("type") == "tool_result":
                shown = _output_lines(block)
                if shown:
                    body.extend([*shown, ""])
    heading = f"## Session {path.stem}" + (f" · phase {phase}" if phase else "")
    if stamps:
        start, end = stamps[0][:16].replace("T", " "), stamps[-1][:16].replace("T", " ")
        span = f"{start} → {end if end[:10] != start[:10] else end[11:]}"
    else:
        span = "no timestamps"
    return [heading, "",
            f"{span} · Arbiter turns: {turns} · model words: {words} · tool calls: {calls}", "",
            *body]
