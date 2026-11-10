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
# Owner key in the near-cli-rs shape used on testnet (private_key, no account_id, extra fields), plus two
# deliberately wrong copies. The secret is the throwaway local validator key; nothing here is published.
python3 -I - "$HOME_DIR" <<'PY'
import json, sys
h = sys.argv[1]
k = json.load(open(f"{h}/validator_key.json"))
cli = {"implicit_account_id": "rehearsal", "master_seed_phrase": "rehearsal placeholder",
       "seed_phrase_hd_path": "m/44'/397'/0'", "private_key": k["secret_key"], "public_key": k["public_key"]}
json.dump(cli, open(f"{h}/owner-cli-rs.json", "w"))
json.dump(dict(cli, account_id="someone-else.near"), open(f"{h}/owner-wrong-account.json", "w"))
json.dump(dict(cli, public_key="ed25519:11111111111111111111111111111111"), open(f"{h}/owner-wrong-public.json", "w"))
PY
REFUSE=$PUB/refusals.txt; : > "$REFUSE"
refuse() { local name=$1; shift; if "$@" > /dev/null 2>> "$REFUSE.err"; then echo "$name: NOT REFUSED" >> "$REFUSE"; exit 1; fi
  echo "$name: refused: $(tail -1 "$REFUSE.err")" >> "$REFUSE"; }
head -c 1000 /dev/zero > "$HOME_DIR/not-the-artifact.wasm"
refuse wrong_wasm_plan "$ACTOR" plan --network sandbox --rpc http://127.0.0.1:$PORT --owner test.near --wasm "$HOME_DIR/not-the-artifact.wasm"
refuse wrong_network "$ACTOR" plan --network testnet --rpc http://127.0.0.1:$PORT --owner test.near --wasm "$REPO/artifacts/near_agent_vault.wasm"
refuse non_loopback_rpc "$ACTOR" plan --network sandbox --rpc http://203.0.113.1:$PORT --owner test.near --wasm "$REPO/artifacts/near_agent_vault.wasm"
for bad in wrong-account wrong-public; do
  refuse "owner_key_$bad" "$ACTOR" run --network sandbox --confirm-network sandbox --rpc http://127.0.0.1:$PORT --owner test.near \
    --owner-key "$HOME_DIR/owner-$bad.json" --wasm "$REPO/artifacts/near_agent_vault.wasm" --out "$HOME_DIR/never.json"
done
rm -f "$REFUSE.err"; cat "$REFUSE"
"$ACTOR" run --network sandbox --confirm-network sandbox --rpc http://127.0.0.1:$PORT --owner test.near \
  --owner-key "$HOME_DIR/owner-cli-rs.json" --wasm "$REPO/artifacts/near_agent_vault.wasm" --out "$PUB/run.json"
( cd "$REPO" && python3 -E -s -m packages.verifier inspect-smoke --network sandbox --rpc http://127.0.0.1:$PORT \
  --run "$PUB/run.json" --wasm artifacts/near_agent_vault.wasm --out "$PUB/inspection" )
sed -i "s#$HOME#~#g" "$PUB"/*.json "$PUB"/inspection/*.json 2>/dev/null || true
