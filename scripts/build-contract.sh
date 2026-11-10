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
# rustc rewrites std's virtual /rustc/<commit>/ paths to the local rust-src checkout when the
# rust-src component is installed, so generic std code monomorphized into the contract embeds
# "$SYSROOT/lib/rustlib/src/rust/..." panic paths (the builder's home directory). Map them back
# to the canonical virtual prefix so the bytes do not depend on the builder's home or on
# whether rust-src is installed. (Added 2026-11-10; the 5b05246b artifact predates this.)
SYSROOT=$(cd "$REPO" && rustc --print sysroot)
RUSTC_COMMIT=$(cd "$REPO" && rustc -vV | sed -n 's/^commit-hash: //p')
RUSTFLAGS_WASM="-C link-arg=-s --remap-path-prefix=$CARGO_HOME_DIR/registry/src=/cargo/registry/src --remap-path-prefix=$REPO=/build --remap-path-prefix=$SYSROOT/lib/rustlib/src/rust=/rustc/$RUSTC_COMMIT"

"$CARGO_NEAR" near --version
( cd "$REPO/contracts/vault" && rustc --version && \
  "$CARGO_NEAR" near build non-reproducible-wasm --locked --no-abi --env "RUSTFLAGS=$RUSTFLAGS_WASM" )

mkdir -p "$REPO/artifacts"
cp "$REPO/target/near/near_agent_vault/near_agent_vault.wasm" "$REPO/artifacts/near_agent_vault.wasm"
( cd "$REPO/artifacts" && sha256sum near_agent_vault.wasm | tee near_agent_vault.wasm.sha256 )
if strings -n 6 "$REPO/artifacts/near_agent_vault.wasm" | grep -q "$HOME"; then
  echo "artifact still embeds $HOME" >&2; exit 1
fi
# Relative paths keep the builder's checkout path out of the committed report.
( cd "$REPO" && python3 -I scripts/inspect_wasm.py artifacts/near_agent_vault.wasm \
  --json artifacts/near_agent_vault.inspect.json > /dev/null ) \
  && echo "capability gate: PASS" || { echo "capability gate: FAIL (see artifacts/near_agent_vault.inspect.json)" >&2; exit 1; }
