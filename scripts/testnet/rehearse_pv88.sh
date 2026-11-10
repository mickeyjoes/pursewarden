#!/usr/bin/env bash
# Rehearse the testnet smoke plan, unchanged, on a fresh LOCAL sandbox running the same nearcore as
# testnet (2.14.0-rc.5, protocol 88). Nothing touches a public network.
#   scripts/testnet/rehearse_pv88.sh RUN_ID [RPC_PORT]
set -euo pipefail
RUN=${1:?usage: rehearse_pv88.sh RUN_ID [RPC_PORT]}
PORT=${2:-3410}
REPO=$(cd "$(dirname "$0")/../.." && pwd)
TOOLS=${NEAR_VAULT_TOOLS:-$HOME/.local/share/near-agent-vault-lab}
BIN=$TOOLS/sandbox-bin/2.14.0-rc.5/extract/Linux-x86_64/near-sandbox
echo "f0104897d7bc9c9a9f1d869679d2c0b4dca878a53327a4f1bc6901cfdf55699b  $BIN" | sha256sum -c -
ACTOR=${SMOKE_ACTOR:-$REPO/target/debug/smoke_actor}
HOME_DIR=$TOOLS/pv88-rehearsal/$RUN/node
PUB=$REPO/evidence/testnet-rehearsal/$RUN
[ -e "$HOME_DIR" ] || [ -e "$PUB" ] && { echo "fresh run id required" >&2; exit 1; }
mkdir -p "$(dirname "$HOME_DIR")" "$PUB"
"$BIN" --home "$HOME_DIR" init --fast > /dev/null 2>&1
python3 -I - "$HOME_DIR" <<'PY'
import json, sys
h = sys.argv[1]
g = json.load(open(f"{h}/genesis.json")); g["epoch_length"] = 100000; json.dump(g, open(f"{h}/genesis.json", "w"), indent=2)
c = json.load(open(f"{h}/config.json")); c["save_tx_outcomes"] = True; c["save_receipt_to_tx"] = True; c["tracked_shards_config"] = "AllShards"
json.dump(c, open(f"{h}/config.json", "w"), indent=2)
PY
setsid nohup "$BIN" --home "$HOME_DIR" run --rpc-addr 127.0.0.1:$PORT --network-addr 127.0.0.1:$((PORT + 21000)) > "$HOME_DIR/node.log" 2>&1 < /dev/null &
PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT
for _ in $(seq 1 120); do curl -sf -m 2 -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"status","params":[]}' http://127.0.0.1:$PORT > "$PUB/status.json" && break; sleep 0.5; done
python3 -I -c 'import json,sys; s=json.load(open(sys.argv[1]))["result"]; print("node", s["chain_id"], "protocol", s["protocol_version"], s["version"]["version"])' "$PUB/status.json"
"$ACTOR" plan --network sandbox --rpc http://127.0.0.1:$PORT --owner test.near --wasm "$REPO/artifacts/near_agent_vault.wasm" > "$PUB/plan.json"
"$ACTOR" run --network sandbox --confirm-network sandbox --rpc http://127.0.0.1:$PORT --owner test.near \
  --owner-key "$HOME_DIR/validator_key.json" --wasm "$REPO/artifacts/near_agent_vault.wasm" --out "$PUB/run.json"
( cd "$REPO" && python3 -E -s -m packages.verifier inspect-smoke --network sandbox --rpc http://127.0.0.1:$PORT \
  --run "$PUB/run.json" --wasm artifacts/near_agent_vault.wasm --out "$PUB/inspection" )
sed -i "s#$HOME#~#g" "$PUB"/*.json "$PUB"/inspection/*.json 2>/dev/null || true
