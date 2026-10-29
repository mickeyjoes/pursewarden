#!/usr/bin/env bash
# Stop a sandbox node started by start-node.sh; its home (and history) is kept on disk.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
HOME_DIR=$REPO/.sandbox/${1:?usage: stop-node.sh <run-id>}
PID=$(cat "$HOME_DIR/node.pid")
kill "$PID"
for _ in $(seq 1 60); do kill -0 "$PID" 2>/dev/null || { echo "stopped $PID"; exit 0; }; sleep 0.5; done
echo "node $PID did not exit" >&2; exit 1
