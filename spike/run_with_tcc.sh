#!/usr/bin/env bash
# The comparison run: same project, same prompt, one variable — TCC's MCP server is up.
#
# The bare run (no TCC) spent ten minutes hunting for `rew_tool` and wrote nothing to
# process/journal.jsonl. The question this answers: with TCC's own tools on the wire, does
# the agent record the process instead of shelling out to find the recorder?
#
#   ./spike/run_with_tcc.sh <project_dir> [model]
#
# Leaves the TCC server running in the background and prints the command to run the turn.
set -euo pipefail

PROJECT="${1:?usage: run_with_tcc.sh <project_dir> [model]}"
MODEL="${2:-google/gemini-3.1-pro-preview}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-$REPO/.venv}"
PY="$VENV/bin/python"
OUT="${SPIKE_OUT:-/tmp/spike}"

[ -x "$PY" ] || { echo "no interpreter at $PY — set VENV=… to the venv that has mcp+uvicorn"; exit 1; }
mkdir -p "$OUT"

echo "== starting TCC's MCP server (headless, real one) =="
SPIKE_OUT="$OUT" HOLD_S="${HOLD_S:-4}" LIFETIME_S="${LIFETIME_S:-3600}" \
  "$PY" "$REPO/spike/serve_tcc.py" "$PROJECT" > "$OUT/serve.out" 2> "$OUT/serve.err" &
SERVE_PID=$!
sleep 5
[ -s "$OUT/serve.out" ] || { echo "server did not report a port; see $OUT/serve.err"; kill $SERVE_PID; exit 1; }
cat "$OUT/serve.out"

# OpenCode does not read .mcp.json — it needs the same server declared in opencode.json.
# Merge rather than overwrite: the file may already carry a provider block.
"$PY" - "$PROJECT" "$OUT/serve.out" <<'PY'
import json, sys
from pathlib import Path
project, serve_out = Path(sys.argv[1]), Path(sys.argv[2])
info = json.loads(serve_out.read_text())
cfg_path = project / "opencode.json"
cfg = {}
if cfg_path.exists():
    try:
        cfg = json.loads(cfg_path.read_text())
    except ValueError:
        cfg = {}
cfg.setdefault("$schema", "https://opencode.ai/config.json")
cfg.setdefault("mcp", {})["tcc"] = {
    "type": "remote",
    "url": info["url"],
    "headers": {"X-TCC-Token": info["token"]},
    "enabled": True,
}
cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
print(f"wrote {cfg_path}")
PY

cat <<EOF

== next ==
Restart 'opencode serve' from $PROJECT so it picks up the new opencode.json, then:

  curl -s http://127.0.0.1:4096/mcp          # expect {"tcc":{"status":"connected"}}

  python3 $REPO/spike/real_turn.py "$PROJECT" \\
    --model $MODEL \\
    --prompt "Start a tuning project here. Read what is on disk first, then tell me where we are and what the next step is."

Watch for: does the agent call the tcc_* tools (report_phase, get_tcc_state) instead of
hunting for rew_tool? And does process/journal.jsonl finally grow?

TCC server pid $SERVE_PID · logs in $OUT/ (http.log has the JSON-RPC both ways)
Stop it with: kill $SERVE_PID
EOF
