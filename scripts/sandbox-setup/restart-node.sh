#!/usr/bin/env bash
# Re-serve an existing node home (same chain, same history) for a later reviewer.
#   scripts/sandbox-setup/restart-node.sh <run-id>
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
RUN_ID=${1:?usage: restart-node.sh <run-id>}
HOME_DIR=$REPO/.sandbox/$RUN_ID
TOOLS=${NEAR_VAULT_TOOLS:-$HOME/.local/share/near-agent-vault-lab}
BIN=$TOOLS/sandbox-bin/2.13.4/extract/Linux-x86_64/near-sandbox
echo "4e89fbc0f2958634e84af44634f90e87c246288fa11b067d2121ce1394cba2c2  $BIN" | sha256sum -c -
RPC_ADDR=$(sed -n 's/^rpc_addr=//p' "$REPO/evidence/g1/$RUN_ID/node/binary.txt")
NET_ADDR=$(sed -n 's/^net_addr=//p' "$REPO/evidence/g1/$RUN_ID/node/binary.txt")
setsid nohup "$BIN" --home "$HOME_DIR" run --rpc-addr "$RPC_ADDR" --network-addr "$NET_ADDR" \
  >> "$HOME_DIR/node.log" 2>&1 < /dev/null &
echo $! > "$HOME_DIR/node.pid"
for _ in $(seq 1 120); do
  curl -sf -m 2 -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":"s","method":"status","params":[]}' "http://$RPC_ADDR" > /dev/null && break
  sleep 0.5
done
echo "restarted $RUN_ID pid $(cat "$HOME_DIR/node.pid") rpc http://$RPC_ADDR"
