#!/usr/bin/env bash
# Build the VULNERABLE TEACHING FIXTURE (sandbox-only negative control for G2) with the same
# toolchain and path remaps as scripts/build-contract.sh, so its bytes carry no builder paths.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
CARGO_NEAR=${CARGO_NEAR:-$HOME/.local/share/near-agent-vault-lab/cargo-near-0.22.0/bin/cargo-near}
CARGO_HOME_DIR=${CARGO_HOME:-$HOME/.cargo}
SYSROOT=$(cd "$REPO" && rustc --print sysroot)
RUSTC_COMMIT=$(cd "$REPO" && rustc -vV | sed -n 's/^commit-hash: //p')
FIX=$REPO/fixtures/vulnerable-settled-only
RUSTFLAGS_WASM="-C link-arg=-s --remap-path-prefix=$CARGO_HOME_DIR/registry/src=/cargo/registry/src --remap-path-prefix=$REPO=/build --remap-path-prefix=$SYSROOT/lib/rustlib/src/rust=/rustc/$RUSTC_COMMIT"
( cd "$FIX" && "$CARGO_NEAR" near build non-reproducible-wasm --locked --no-abi --env "RUSTFLAGS=$RUSTFLAGS_WASM" )
mkdir -p "$REPO/artifacts/fixtures"
cp "$FIX/target/near/vulnerable_settled_only.wasm" "$REPO/artifacts/fixtures/vulnerable_settled_only.wasm"
( cd "$REPO/artifacts/fixtures" && sha256sum vulnerable_settled_only.wasm | tee vulnerable_settled_only.wasm.sha256 )
if strings -n 6 "$REPO/artifacts/fixtures/vulnerable_settled_only.wasm" | grep -q "$HOME"; then
  echo "fixture still embeds $HOME" >&2; exit 1
fi
echo "fixture build: no builder paths"
