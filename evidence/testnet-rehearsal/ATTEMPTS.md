# Testnet-plan rehearsals on a local PV88 sandbox (nearcore 2.14.0-rc.5)

LOCAL SANDBOX evidence that the testnet smoke plan works unchanged on testnet's protocol version. Not testnet evidence.

| Run | Code | Result |
| --- | --- | --- |
| `pv88-dev-01` | uncommitted tree | inspection PASS (same as below); development run |
| `pv88-20261110T172933Z` | `36e9fc7` (clean) | **inspection PASS** on fresh chain `test-chain-COz4m` (protocol 88): all six decisions as planned, C = 0.8, headroom 0.2, 0 vault keys, frozen |
| `pv88-20261110T194351Z` | hardened actor (`release/testnet-proof`) | **inspection PASS** on fresh chain `test-chain-041sx` (protocol 88). The tool now refuses any WASM other than `c7c77263…`, checks the owner key file (near-cli-rs shape, account and public key) and its FullAccess permission on chain, and stops on the first mismatch. `refusals.txt` records five refusals (wrong WASM, wrong network, non-loopback RPC, key for another account, mismatched key) before the real run. |
| `pv88-20261110T195514Z` | final pre-broadcast actor | **inspection PASS** on fresh chain `test-chain-49yCL` (protocol 88). Same refusals, plus: every hash that may have been broadcast is polled by hash and recorded, never re-signed; testnet spend cap of 3.5 NEAR checked against the live gas price before signing. This build is the one used on testnet. |
