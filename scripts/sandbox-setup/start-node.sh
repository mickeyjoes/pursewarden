#!/usr/bin/env bash
# Start a FRESH, reviewer-owned nearcore 2.13.4 sandbox node outside near-workspaces,
# with retention long enough for an independent reviewer to re-read the run.
#
#   scripts/sandbox-setup/start-node.sh <run-id>
#
# - Verifies the pinned tarball and binary SHA-256 before use (near-sandbox 0.3.16 itself
#   downloads the same URL with no checksum check).
# - `init --fast` exactly as near-sandbox 0.3.16 does, then overrides:
#     genesis.epoch_length = 100000   (default `--fast` is 60; non-archival GC keeps only
#                                      gc_num_epochs_to_keep=5 epochs ~ 300 blocks)
#     config.save_tx_outcomes = true, config.save_receipt_to_tx = true (explicit)
#   No sandbox helper accounts with published keys are added (unlike near-sandbox/workspaces).
# - RPC and P2P bind to 127.0.0.1 only. The sandbox_patch_state / sandbox_fast_forward RPC
#   methods are NOT disabled by this script; the evidence run never calls them and the
#   harness checks for `migration` state-change causes on watched accounts.
# - Node home (contains validator/node PRIVATE keys) lives in .sandbox/<run-id>/ (gitignored).
#   Public identity files are copied to evidence/g1/<run-id>/node/.
set -euo pipefail

RUN_ID=${1:?usage: start-node.sh <run-id>}
REPO=$(cd "$(dirname "$0")/../.." && pwd)
TOOLS=${NEAR_VAULT_TOOLS:-$HOME/.local/share/near-agent-vault-lab}
TARBALL=$TOOLS/sandbox-bin/2.13.4/download/near-sandbox.tar.gz
BIN=$TOOLS/sandbox-bin/2.13.4/extract/Linux-x86_64/near-sandbox
TARBALL_URL=https://s3-us-west-1.amazonaws.com/build.nearprotocol.com/nearcore/Linux-x86_64/2.13.4/near-sandbox.tar.gz
EXPECTED_TARBALL_SHA256=5690a4635172263cf026683f75965cac09dd916912584f12709974fed620163f
EXPECTED_BIN_SHA256=4e89fbc0f2958634e84af44634f90e87c246288fa11b067d2121ce1394cba2c2
RPC_ADDR=${RPC_ADDR:-127.0.0.1:3130}
NET_ADDR=${NET_ADDR:-127.0.0.1:24667}
EPOCH_LENGTH=${EPOCH_LENGTH:-100000}

HOME_DIR=${NODE_HOME:-$REPO/.sandbox/$RUN_ID}
EVID=${NODE_EVIDENCE_DIR:-$REPO/evidence/g1/$RUN_ID/node}
[ -e "$HOME_DIR" ] && { echo "refusing to reuse existing node home $HOME_DIR (fresh node required)" >&2; exit 1; }

if [ ! -x "$BIN" ]; then
  mkdir -p "$(dirname "$TARBALL")" "$TOOLS/sandbox-bin/2.13.4/extract"
  [ -f "$TARBALL" ] || curl -sS --fail -o "$TARBALL" "$TARBALL_URL"
  echo "$EXPECTED_TARBALL_SHA256  $TARBALL" | sha256sum -c -
  tar -xzf "$TARBALL" -C "$TOOLS/sandbox-bin/2.13.4/extract"
fi
echo "$EXPECTED_TARBALL_SHA256  $TARBALL" | sha256sum -c -
echo "$EXPECTED_BIN_SHA256  $BIN" | sha256sum -c -

mkdir -p "$(dirname "$HOME_DIR")" "$EVID"
"$BIN" --home "$HOME_DIR" init --fast > "$EVID/init.log" 2>&1

python3 -I - "$HOME_DIR" "$EPOCH_LENGTH" <<'EOF'
import json, sys
home, epoch_length = sys.argv[1], int(sys.argv[2])
g = json.load(open(f"{home}/genesis.json"))
g["epoch_length"] = epoch_length
json.dump(g, open(f"{home}/genesis.json", "w"), indent=2)
c = json.load(open(f"{home}/config.json"))
c["save_tx_outcomes"] = True
c["save_receipt_to_tx"] = True
c["tracked_shards_config"] = "AllShards"
json.dump(c, open(f"{home}/config.json", "w"), indent=2)
EOF

cp "$HOME_DIR/genesis.json" "$EVID/genesis.json"
cp "$HOME_DIR/config.json" "$EVID/config.json"
( cd "$HOME_DIR" && sha256sum genesis.json config.json ) > "$EVID/home-files.sha256"
{
  echo "binary_path=$BIN"
  echo "binary_sha256=$(sha256sum "$BIN" | cut -d' ' -f1)"
  echo "tarball_url=$TARBALL_URL"
  echo "tarball_sha256=$(sha256sum "$TARBALL" | cut -d' ' -f1)"
  echo "binary_version=$("$BIN" --version 2>&1 | head -1)"
  echo "binary_features=$("$BIN" --version 2>&1 | sed -n 2p)"
  echo "rpc_addr=$RPC_ADDR"
  echo "net_addr=$NET_ADDR"
  echo "epoch_length=$EPOCH_LENGTH"
  echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$EVID/binary.txt"

setsid nohup "$BIN" --home "$HOME_DIR" run --rpc-addr "$RPC_ADDR" --network-addr "$NET_ADDR" \
  > "$HOME_DIR/node.log" 2>&1 < /dev/null &
echo $! > "$HOME_DIR/node.pid"

for _ in $(seq 1 120); do
  if curl -sf -m 2 -H 'Content-Type: application/json' \
      -d '{"jsonrpc":"2.0","id":"s","method":"status","params":[]}' "http://$RPC_ADDR" > "$EVID/status-at-start.json"; then
    break
  fi
  sleep 0.5
done
python3 -I -c 'import json,sys; s=json.load(open(sys.argv[1]))["result"]; print("chain_id", s["chain_id"], "genesis_hash", s["genesis_hash"], "protocol_version", s["protocol_version"], "version", s["version"], "height", s["sync_info"]["latest_block_height"])' "$EVID/status-at-start.json"
echo "node home: $HOME_DIR  pid: $(cat "$HOME_DIR/node.pid")  rpc: http://$RPC_ADDR"
