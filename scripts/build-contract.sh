#!/usr/bin/env bash
# Build the G1 vault artifact with the pinned toolchain and write it to artifacts/.
#
#   scripts/build-contract.sh
#
# - rustc 1.93.0 via rust-toolchain.toml; cargo-near 0.22.0 (cargo-near-build 0.11.5,
#   wasm-opt 0.116.1 `-O --enable-nontrapping-float-to-int --enable-bulk-memory`).
# - `--locked`; `--no-abi` (an embedded ABI would add a `__contract_abi` export).
# - RUSTFLAGS keeps cargo-near's default `-C link-arg=-s` and adds --remap-path-prefix so panic
#   location strings do not embed the builder's home directory or checkout path (cargo-near
#   force-appends `--cfg near`, which selects near-sdk's host-function path).
# - Runs the fail-closed import/export gate on the result.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
CARGO_NEAR=${CARGO_NEAR:-$HOME/.local/share/near-agent-vault-lab/cargo-near-0.22.0/bin/cargo-near}
CARGO_HOME_DIR=${CARGO_HOME:-$HOME/.cargo}
RUSTFLAGS_WASM="-C link-arg=-s --remap-path-prefix=$CARGO_HOME_DIR/registry/src=/cargo/registry/src --remap-path-prefix=$REPO=/build"

"$CARGO_NEAR" near --version
( cd "$REPO/contracts/vault" && rustc --version && \
  "$CARGO_NEAR" near build non-reproducible-wasm --locked --no-abi --env "RUSTFLAGS=$RUSTFLAGS_WASM" )

mkdir -p "$REPO/artifacts"
cp "$REPO/target/near/near_agent_vault/near_agent_vault.wasm" "$REPO/artifacts/near_agent_vault.wasm"
( cd "$REPO/artifacts" && sha256sum near_agent_vault.wasm | tee near_agent_vault.wasm.sha256 )
if strings -n 6 "$REPO/artifacts/near_agent_vault.wasm" | grep -q "$HOME"; then
  echo "artifact still embeds $HOME" >&2; exit 1
fi
python3 -I "$REPO/scripts/inspect_wasm.py" "$REPO/artifacts/near_agent_vault.wasm" \
  --json "$REPO/artifacts/near_agent_vault.inspect.json" > /dev/null \
  && echo "capability gate: PASS" || { echo "capability gate: FAIL (see artifacts/near_agent_vault.inspect.json)" >&2; exit 1; }
