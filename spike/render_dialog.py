"""Build the role-legible dialogue from `process/journal.jsonl` — not from the model's stream.

The claim under test: the journal already carries "who did what, and on what evidence", so the
transcript can be rendered from files. Prose is merged in by timestamp as garnish, and the
`--events-only` view proves the picture still reads without it — which is what makes the dialogue
independent of whichever harness happens to be driving.

    python spike/render_dialog.py spike/fixture -o /tmp/dialog.html
    python spike/render_dialog.py spike/fixture --events-only -o /tmp/events.html

Reads, all optional except the journal:
    <project>/process/journal.jsonl       the transcript (skill-written, append-only)
    <project>/process/process-state.json  current phase/plan/reviewer, for the header
    <project>/proposals/v_NNN.json        banked settings sheets, rendered as cards
    <project>/prose.jsonl                 what the harness streamed (TCC-side capture)
"""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path

ROLE_OF_EVENT = {
    "phase_entered": "system",
    "step_added": "generator",
    "attempt_started": "generator",
    "step_done": "generator",
    "step_skipped": "generator",
    "step_blocked": "generator",
    "config_change": "generator",
    "critic_called": "critic",
}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _clock(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except ValueError:
        return iso[11:16] if len(iso) > 16 else iso


def _esc(text: object) -> str:
    return html.escape(str(text))


def _evidence(items: list) -> str:
    if not items:
        return ""
    pills = "".join(f"<code>{_esc(e)}</code>" for e in items)
    return f'<span class="ev">evidence {pills}</span>'


def chip_html(ev: dict) -> str:
    """One journal event as a process chip. Everything shown here is machine-recorded."""
    kind = ev.get("type")
    when = _clock(ev.get("at", ""))
    role = ROLE_OF_EVENT.get(kind, "system")

    if kind == "phase_entered":
        body = f'<b>Фаза {_esc(ev.get("phase"))}</b> — {_esc(ev.get("title", ""))}'
    elif kind == "step_added":
        origin = "ситуативний" if ev.get("source") == "project" else "з шаблону фази"
        body = (f'крок <b>{_esc(ev.get("step") or ev.get("id"))}</b> додано — {_esc(ev.get("name"))} '
                f'<span class="dim">({origin})</span>')
    elif kind == "attempt_started":
        attempt = ev.get("attempt", 1)
        again = f' <span class="warn">спроба {attempt}</span>' if attempt > 1 else ""
        body = f'крок <b>{_esc(ev.get("step") or ev.get("id"))}</b> у роботі{again}'
    elif kind == "step_done":
        body = (f'крок <b>{_esc(ev.get("step") or ev.get("id"))}</b> закрито '
                f'{_evidence(ev.get("evidence", []))}')
    elif kind == "step_skipped":
        body = f'крок <b>{_esc(ev.get("step") or ev.get("id"))}</b> знято — {_esc(ev.get("reason", ""))}'
    elif kind == "step_blocked":
        body = f'крок <b>{_esc(ev.get("step") or ev.get("id"))}</b> заблоковано — {_esc(ev.get("reason", ""))}'
    elif kind == "config_change":
        impact = ev.get("impact") or []
        inval = (f'<span class="ev warn">інвалідує '
                 + "".join(f"<code>{_esc(i)}</code>" for i in impact) + "</span>") if impact else ""
        body = (f'<b>{_esc(ev.get("path"))}</b> {_esc(ev.get("from"))} → '
                f'<b>{_esc(ev.get("to"))}</b> {inval}')
    elif kind == "critic_called":
        outcome = ev.get("outcome", "")
        cls = {"apply": "ok", "revise": "warn"}.get(outcome, "dim")
        body = (f'Радник <b>{_esc(ev.get("vendor"))} / {_esc(ev.get("model"))}</b> '
                f'по кроку {_esc(ev.get("step"))} — <span class="{cls}">{_esc(outcome)}</span>')
    else:
        body = _esc(json.dumps(ev, ensure_ascii=False))

    return (f'<div class="chip {role}"><span class="t">{when}</span>'
            f'<span class="k">{_esc(kind)}</span>{body}</div>')


def bubble_html(item: dict) -> str:
    role = item.get("role", "generator")
    label = {"generator": "Оркестратор", "critic": "Радник",
             "user": "Арбітр", "system": "Система"}.get(role, role)
    cls = {"generator": "gen", "critic": "crit", "user": "user"}.get(role, "sys")
    return (f'<div class="msg {cls}"><div class="who">{_esc(label)} '
            f'<span class="t">{_clock(item.get("at", ""))}</span></div>'
            f'<div>{_esc(item.get("text", ""))}</div></div>')


def sheet_html(proposal: dict) -> str:
    """The settings sheet as a card built from the banked snapshot — not retyped by the model."""
    rows = []
    for s in proposal.get("settings", []):
        unchanged = s.get("unchanged")
        was = s.get("was")
        change = (f'<span class="dim">{_esc(was)}</span> → <b>{_esc(s["value"])}</b>'
                  if was and not unchanged else
                  f'<b>{_esc(s["value"])}</b>' + ('<span class="dim"> (без змін)</span>'
                                                  if unchanged else ""))
        rows.append(
            f'<tr><td><code>{_esc(s.get("tier"))}</code></td>'
            f'<td><b>{_esc(s.get("channel"))}</b></td>'
            f'<td>{_esc(s.get("param"))}</td><td>{change}</td></tr>')
    gate = proposal.get("eq_gate", "")
    return (
        f'<div class="sheet"><div class="sheet-head">'
        f'<span class="badge">{_esc(proposal.get("version"))}</span>'
        f'<b>Аркуш для введення</b> · пресет {_esc(proposal.get("preset"))}'
        f'<span class="t">{_clock(proposal.get("at", ""))}</span></div>'
        f'<div class="note">{_esc(proposal.get("note", ""))}</div>'
        f'<table>{"".join(rows)}</table>'
        f'<div class="gate">✔ {_esc(gate)}</div>'
        f'<div class="acts"><button>Застосовано в DSP</button>'
        f'<button class="ghost">Відкласти</button></div></div>')


def header_html(state: dict) -> str:
    if not state:
        return ""
    phase = state.get("active_phase")
    title = state.get("phases", {}).get(phase, {}).get("title", "")
    rev = state.get("reviewer") or {}
    done = sum(1 for s in state.get("plan", []) if s.get("status") == "done")
    total = len(state.get("plan", []))
    rev_txt = (f'{_esc(rev.get("vendor"))} / {_esc(rev.get("model"))} · '
               f'{_clock(rev.get("at", ""))} · {_esc(rev.get("outcome"))}') if rev else "—"
    return (f'<div class="head"><div><span class="badge">Фаза {_esc(phase)}</span> '
            f'<b>{_esc(title)}</b> <span class="dim">кроки {done}/{total}</span></div>'
            f'<div class="dim">Радник: {rev_txt}</div></div>')


CSS = """
:root{--panel:#161b22;--panel2:#1b222c;--panel3:#222a36;--border:#263040;--border2:#334055;
--text:#dfe6ee;--muted:#8b97a6;--dim:#5f6b7a;--accent:#e8973c;--info:#5aa9e6;--ok:#4bbf87;
--warn:#e05c5c;--yellow:#c99a12;--r:7px;
--ui:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
*{box-sizing:border-box}
body{margin:0;padding:18px;background:#0f1318;color:var(--text);font:13px/1.5 var(--ui)}
.wrap{max-width:860px;margin:0 auto}
.head{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;
padding:10px 14px;background:var(--panel);border:1px solid var(--border);border-radius:var(--r);
margin-bottom:6px}
.bar{display:flex;gap:8px;align-items:center;margin:10px 0 14px}
.bar button{background:var(--panel3);border:1px solid var(--border2);color:var(--muted);
border-radius:20px;padding:5px 13px;font:inherit;font-size:11.5px;cursor:pointer}
.bar button.on{background:color-mix(in srgb,var(--info) 16%,var(--panel2));
border-color:var(--info);color:var(--info);font-weight:600}
.feed{display:flex;flex-direction:column;gap:9px}
.msg{max-width:82%;padding:9px 12px;border-radius:10px}
.msg .who{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);
margin-bottom:3px}
.msg.gen{align-self:flex-start;background:var(--panel2);border:1px solid var(--border);
border-top-left-radius:3px}
.msg.crit{align-self:flex-start;background:color-mix(in srgb,var(--info) 12%,var(--panel2));
border:1px solid color-mix(in srgb,var(--info) 30%,var(--border));border-top-left-radius:3px}
.msg.crit .who{color:var(--info)}
.msg.user{align-self:flex-end;background:color-mix(in srgb,var(--accent) 16%,var(--panel2));
border:1px solid color-mix(in srgb,var(--accent) 30%,var(--border));border-top-right-radius:3px}
.msg .t{float:right;color:var(--dim);letter-spacing:0}
.chip{align-self:center;max-width:96%;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;
padding:5px 11px;border-radius:20px;font-size:11.5px;background:var(--panel2);
border:1px solid var(--border);color:var(--muted)}
.chip .t{color:var(--dim);font-family:var(--mono);font-size:10.5px}
.chip .k{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.06em;
color:var(--dim);border:1px solid var(--border2);border-radius:10px;padding:0 6px}
.chip.critic{border-color:color-mix(in srgb,var(--info) 45%,var(--border));
background:color-mix(in srgb,var(--info) 8%,var(--panel2))}
.chip.system{border-style:dashed;border-color:color-mix(in srgb,var(--accent) 45%,var(--border));
background:color-mix(in srgb,var(--accent) 8%,var(--panel2))}
.chip b{color:var(--text)}
.ev{color:var(--dim)}
.ev code,.chip code{font-family:var(--mono);font-size:10.5px;background:var(--panel3);
padding:1px 5px;border-radius:3px;margin-left:4px;color:var(--muted)}
.ok{color:var(--ok);font-weight:600}.warn{color:var(--warn);font-weight:600}
.dim{color:var(--dim)}
.badge{font-family:var(--mono);font-size:10.5px;background:var(--panel3);border:1px solid
var(--border2);border-radius:4px;padding:1px 6px;color:var(--accent);margin-right:6px}
.sheet{align-self:flex-start;max-width:92%;background:var(--panel);border:1px solid
color-mix(in srgb,var(--accent) 40%,var(--border));border-radius:var(--r);overflow:hidden}
.sheet-head{display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--panel2);
border-bottom:1px solid var(--border)}
.sheet-head .t{margin-left:auto;color:var(--dim);font-family:var(--mono);font-size:10.5px}
.sheet .note{padding:7px 12px;color:var(--muted);font-size:11.5px}
.sheet table{width:100%;border-collapse:collapse;font-size:12px}
.sheet td{padding:5px 12px;border-top:1px solid var(--border)}
.sheet td code{font-family:var(--mono);font-size:10.5px;color:var(--dim)}
.sheet .gate{padding:6px 12px;color:var(--ok);font-size:11.5px;border-top:1px solid var(--border)}
.sheet .acts{display:flex;gap:8px;padding:9px 12px;border-top:1px solid var(--border);
background:var(--panel2)}
.sheet .acts button{background:var(--accent);border:0;color:#1b1206;border-radius:5px;
padding:6px 14px;font:inherit;font-weight:600;cursor:pointer}
.sheet .acts button.ghost{background:transparent;border:1px solid var(--border2);color:var(--muted)}
body.events-only .msg{display:none}
"""

JS = """
const b=document.getElementById('toggle');
b.onclick=()=>{document.body.classList.toggle('events-only');
b.classList.toggle('on');
b.textContent=document.body.classList.contains('events-only')
?'Показано лише події з журналу':'Події + проза';};
"""


def build(project: Path, events_only: bool) -> str:
    journal = _read_jsonl(project / "process" / "journal.jsonl")
    state = _read_json(project / "process" / "process-state.json")
    prose = [] if events_only else _read_jsonl(project / "prose.jsonl")

    items: list[tuple[str, str]] = []
    for ev in journal:
        items.append((ev.get("at", ""), chip_html(ev)))
        # A banked version in the evidence means there is a settings sheet to render.
        for ref in ev.get("evidence", []) or []:
            sheet = project / "proposals" / f"{str(ref).strip()}.json"
            if sheet.exists():
                items.append((ev.get("at", ""), sheet_html(_read_json(sheet))))
    for item in prose:
        items.append((item.get("at", ""), bubble_html(item)))
    items.sort(key=lambda pair: pair[0])

    feed = "\n".join(html_ for _, html_ in items)
    cls = ' class="events-only"' if events_only else ""
    on = " on" if events_only else ""
    label = "Показано лише події з журналу" if events_only else "Події + проза"
    return (f'<!doctype html><meta charset="utf-8"><title>TCC — діалог із журналу</title>'
            f'<style>{CSS}</style><body{cls}><div class="wrap">{header_html(state)}'
            f'<div class="bar"><button id="toggle" class="{on.strip()}">{label}</button>'
            f'<span class="dim">джерело: process/journal.jsonl — прозу можна прибрати, '
            f'історія лишається читабельною</span></div>'
            f'<div class="feed">{feed}</div></div><script>{JS}</script>')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("/tmp/dialog.html"))
    ap.add_argument("--events-only", action="store_true")
    args = ap.parse_args()
    args.out.write_text(build(args.project, args.events_only), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
