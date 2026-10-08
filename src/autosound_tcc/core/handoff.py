"""Is everything the NEXT session needs on disk? — the method's `handoff`, asked (hub #201, S-044).

A session can neither restart itself nor clear, and a phase boundary is where the chat holding
the only copy of something gets thrown away. The method's `process.py <dir> handoff --json`
answers whether the next session has what it needs, and writes nothing either way:

    {ok, missing: [str], phase, resume, warnings: [str], next_message}

`missing` names, item by item, the command that fixes it; `next_message` is what the new session
starts with («продовжуй»); `resume` says what must stay open (the REW session with the round's
captures). `warnings` (the method's v3.0.65, S-084, hub #227) never moves `ok`: a ▶️ CONTINUE
block naming a HEAD the ledger is not at, prose to bring up to date. TCC shows the answer and
starts nothing without the Arbiter's click.

Asked through `process_writer.handoff_json`, as every call to the method goes: a read, so with no
lock to wait for. No answer is said as what it is (#169 review I4): «update the method» is the fix
for a method too old for the check, and for nothing else — not a copy TCC will not run, nor a run
that crashed, timed out or printed no answer, where updating a current method mends nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from autosound_tcc.core import app_log, method_cli, process_writer

#: What the window says for a check that got no answer: TCC's words around the method's or the
#: system's. English, as every sentence `core` writes is — it does not import the ui.
NO_ANSWER = "The method did not answer the handoff check: {why}"
CRASHED = "The method crashed on the handoff check: {why}"


def ask(project_dir: Path) -> tuple[Optional[dict], Optional[str]]:
    """The method's answer and None — or None and why there is none, for the window to say:

    * None — the method is too old for `handoff --json`: it answered with its usage text
      (`process_writer.TooOld`), or its `process.py` does not know `--json` (`UnknownFlag`). The
      one case «update the method» fixes; the window says that in the Arbiter's language.
    * the binding's sentence — a copy of the method TCC will not run (#169): re-link it, or
      approve it. `method_cli` has logged it.
    * `NO_ANSWER` — a timeout, an interpreter that would not start, the script not there, the
      method's own refusal, output that is no answer — or `CRASHED`, with the exception's own line;
      the last two logged at WARNING with the stderr's tail.
    """
    try:
        code, out, err = process_writer.handoff_json(Path(project_dir))
    except (process_writer.TooOld, process_writer.UnknownFlag) as exc:
        app_log.logger().info("handoff: the method is too old for the check: %s", exc)
        return None, None
    except process_writer.Refused as exc:
        return None, str(exc)
    except process_writer.ProcessWriterError as exc:
        app_log.logger().info("handoff: no answer: %s", exc)
        return None, NO_ANSWER.format(why=exc)
    app_log.logger().info("handoff --json -> exit %s", code)
    answer = None
    if code in (0, 1):
        try:
            answer = json.loads(out)
        except ValueError:
            pass
    if not isinstance(answer, dict) or "ok" not in answer:
        why = process_writer.refusal(code, err) or process_writer.last_words(code, out, err)
        said = (CRASHED if process_writer.crashed(err) else NO_ANSWER).format(why=why)
        app_log.logger().warning("handoff: %s (exit %s)%s", said, code,
                                 f"; its stderr ends:\n{method_cli.tail(err)}" if err else "")
        return None, said
    answer["missing"] = [str(m) for m in answer.get("missing") or []]
    # Absent from a method before v3.0.65, which did not say: none (#126).
    answer["warnings"] = [str(w) for w in answer.get("warnings") or []]
    return answer, None
