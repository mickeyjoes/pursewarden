# Testnet smoke demonstration: plan for owner approval

**Status: prepared and rehearsed locally on testnet's exact protocol version. NOT broadcast.** Nothing is sent to testnet until the owner approves. Mainnet is out of scope; the tooling refuses `chain_id: mainnet`.

## Purpose

Show that the same protected artifact (`c7c77263…dd768`) deploys and enforces its mandate on **public NEAR testnet**, with public transaction links. This is a narrow smoke test. The adversarial evidence, the independent completeness verification, G1 and G2 all remain **local sandbox** results.

## Feasibility (2026-11-10)

| Check | Result |
| --- | --- |
| Testnet RPC (`rpc.testnet.near.org`, `test.rpc.fastnear.com`) | Reachable; `chain_id: testnet`; **protocol 88**, nearcore 2.14.0-rc.5 |
| Same nearcore locally | Official sandbox build 2.14.0-rc.5 (protocol 88). Tarball SHA-256 `11ff2021…ed0a5e`, binary `f0104897…f55699b`. These are recorded hashes; upstream publishes no checksum. |
| **Rehearsal of this exact plan on a fresh PV88 local chain** | **PASS.** The artifact deploys (no PrepareError on PV88). Decisions as expected: admit / admit + failed transfer with principal refund / DuplicateRequest / AboveMaxPerRequest / RecipientNotAllowed / **BudgetExceeded** / frozen. At the inspector's final block: code hash = artifact, 0 vault keys, policy hash recomputed from raw state, C = 0.8, headroom 0.2. See `evidence/testnet-rehearsal/`. |
| Read-only `plan` against real testnet | Works through the forwarder; it used only `status` and `query` |
| Safety refusals | A non-loopback RPC, a `--network` / `chain_id` mismatch, a WASM other than `c7c77263…`, and a testnet `run` without the approval flag are all refused before any key is loaded. A key file for another account, or whose secret does not match its public key, is refused before anything is signed. The key must also be a FullAccess key of the owner on chain. |
| Stop on first mismatch | `run` checks every decision and native transfer outcome against the table below as it goes. On the first difference it sends nothing more, writes what it has with `"stopped"`, and exits non-zero. |
| Hardened tool rehearsed | `pv88-20261110T194351Z` on fresh chain `test-chain-041sx` (protocol 88): five refusals recorded in `refusals.txt`, then the full plan with the owner key in the near-cli-rs file shape, **inspection PASS**. |

## Owner account (preflight 2026-11-10, read-only)

`evidence/testnet-smoke/preflight-20261110T194516Z/` records the raw RPC responses (`rpc.json`) and the plan output (`plan.json`), all from public testnet at final block 277112107.

| Check | Result |
| --- | --- |
| Account | `pursewarden.testnet`: 10 testnet NEAR, no contract code |
| Keys | One key, `ed25519:5kifqyd3…8gPFk`, **FullAccess**. It matches the public key in the owner's credential file. |
| Credential file | `~/.near-credentials/testnet/pursewarden.testnet.json`, near-cli-rs shape (`private_key`, no `account_id`). The tool accepts it and takes the account from `--owner`. Its secret is never printed, logged or written. |
| Subaccounts | `pw-vault`, `pw-agent`, `pw-payee`, `pw-missing` and `pw-attacker` `.pursewarden.testnet` are all absent. Only `pursewarden.testnet` can create them, so `pw-missing` and `pw-attacker` stay nonexistent. |
| Plan | `sufficient: true`, artifact SHA-256 `c7c772635acea0938bd88450d02bcdb9215d9aa65fc407b4070459cd225dd768` (154,346 bytes) |

## What the owner needs to provide

1. A **testnet** account you control with **≥ 3.47 testnet NEAR** (provided: `pursewarden.testnet`). The faucet gives free testnet NEAR (hackathon FAQ Q-008: near-cli faucet or near-faucet.io). Example: `pursewarden-demo.testnet`.
2. Its full-access key as a local file in the near-cli KeyFile shape (`{"account_id", "public_key", "secret_key"}`), **outside the repository**, e.g. `~/.near-credentials/testnet/<account>.json`. It is never committed. The tool reads it only for `run`.

## Accounts and transactions (all testnet; owner `<O>`)

| # | Signer → receiver | Actions | Expected |
| --- | --- | --- | --- |
| 1 | `<O>` → `pw-payee.<O>` | CreateAccount, Transfer 0.1 | keyless allowlisted payee |
| 2 | `<O>` → `pw-agent.<O>` | CreateAccount, Transfer 0.5, AddKey FunctionCall(`pw-vault.<O>`, `request_payment`, allowance 0.25) × 3 | restricted agent |
| 3 | `<O>` → `pw-vault.<O>` | CreateAccount, Transfer ≈ 2.669, DeployContract `c7c77263`, `new(B = 1, M = 0.4, K = 3, recipients = [pw-missing.<O>, pw-payee.<O>], expiry +24 h)` | keyless vault; policy hash checked against an independent encoder |
| 4 | agent → vault | `request_payment` id 1, 0.4 → payee | Admitted; transfer succeeds |
| 5 | agent → vault | id 2, 0.4 → `pw-missing.<O>` (never created) | Admitted; transfer fails; principal refunded; C stays 0.8 |
| 6 | agent → vault | id 1 again | Denied `DuplicateRequest` |
| 7 | agent → vault | id 3, 0.5 | Denied `AboveMaxPerRequest` |
| 8 | agent → vault | id 4, 0.4 → `pw-attacker.<O>` | Denied `RecipientNotAllowed` |
| 9 | agent → vault | id 5, 0.3 → payee (C 0.8 + 0.3 > 1; a slot is still free) | Denied `BudgetExceeded` |
| 10 | `<O>` → vault | `freeze` | Frozen |

**Funds.** The owner sends exactly **3.26899 testnet NEAR** (0.1 + 0.5 + 2.66899) plus gas for its 4 transactions (about 0.023 in the rehearsal). The balance precondition of 3.46899 adds 0.2 of gas headroom, which is not sent.

**None of it can come back.** About 2.27 stays in `pw-vault` (keyless, no withdrawal path by design). The payee ends with 0.5 (keyless). The agent keeps about 0.5 less its gas (FunctionCall keys only, and their secrets are discarded after the run). **Maximum committed for good: about 3.30 testnet NEAR.** The owner keeps about 6.7 of 10. No mainnet key, no mainnet transaction, no real funds.

## Commands (after approval)

```bash
cargo +1.93.0 build -p g1-sandbox-tests --locked --bin smoke_actor
python3 scripts/testnet/https_rpc_forwarder.py --port 3399 --upstream https://rpc.testnet.near.org &
#   wait for: "testnet forwarder http://127.0.0.1:3399 -> https://rpc.testnet.near.org (chain_id testnet)"
target/debug/smoke_actor plan --network testnet --rpc http://127.0.0.1:3399 --owner <O> --wasm artifacts/near_agent_vault.wasm
#   check: "sufficient": true, every accounts_must_not_exist value true
target/debug/smoke_actor run --network testnet --confirm-network testnet --owner-approved-testnet-broadcast yes \
  --rpc http://127.0.0.1:3399 --owner <O> --owner-key ~/.near-credentials/testnet/<O>.json \
  --wasm artifacts/near_agent_vault.wasm --out evidence/testnet-smoke/<run-id>/run.json
python3 -m packages.verifier inspect-smoke --network testnet --rpc http://127.0.0.1:3399 \
  --run evidence/testnet-smoke/<run-id>/run.json --wasm artifacts/near_agent_vault.wasm --out evidence/testnet-smoke/<run-id>/inspection
```

Each transaction hash in `run.json` can be opened in a testnet explorer (for example `https://testnet.nearblocks.io/txns/<hash>`).

## How it must be described afterwards

**"TESTNET smoke."** It shows that the protected contract deploys and enforces on public testnet. The inspection re-reads the runner-listed transactions and the final vault state from a public node. It is **not** an independent completeness proof, because public nodes give no reviewer-owned fresh frontier and runner-unlisted roots are not discovered. It is also not a concurrency or adversarial-runner result. Those remain local-sandbox evidence (G1, G2).

## Stop conditions

Stop if any of the following happens; it would be a security regression or an unverifiable result:
- the plan's preconditions fail;
- any decision differs from the table;
- the policy hash differs from the independent encoder;
- the vault shows any access key;
- C ≠ sum of records;
- the inspection does not PASS.

In that case keep the sandbox evidence and report the failure as it is.
