# Public NEAR testnet smoke: `tn-20261110T195542Z`

**TESTNET SMOKE. PASS.** The protected artifact `c7c77263…` was deployed to public NEAR testnet and enforced its mandate. This is not an independent completeness proof (the transaction list comes from the runner; a public node gives no reviewer-owned fresh frontier), and it is not a concurrency or adversarial-runner result. Those remain the local-sandbox G1 and G2 evidence.

- Owner approval: explicit, for exactly this 10-transaction plan from `pursewarden.testnet`, with a 3.5 testnet NEAR cap.
- Tool: `smoke_actor` built from commit `4cc6020` (clean tree), rehearsed with the same build on a local protocol-88 chain (`evidence/testnet-rehearsal/pv88-20261110T195514Z`).
- Network: `chain_id testnet`, protocol 88, nearcore 2.14.0-rc.5, via `scripts/testnet/https_rpc_forwarder.py` → `rpc.testnet.near.org`.

## Accounts

| Role | Account | After the run |
| --- | --- | --- |
| Owner | [`pursewarden.testnet`](https://testnet.nearblocks.io/address/pursewarden.testnet) | 6.70753 NEAR (spent 3.29247) |
| Vault | [`pw-vault.pursewarden.testnet`](https://testnet.nearblocks.io/address/pw-vault.pursewarden.testnet) | 2.26899 NEAR, **0 access keys**, code SHA-256 `c7c772635acea0938bd88450d02bcdb9215d9aa65fc407b4070459cd225dd768`, frozen |
| Agent | [`pw-agent.pursewarden.testnet`](https://testnet.nearblocks.io/address/pw-agent.pursewarden.testnet) | 0.49816 NEAR, 3 FunctionCall keys (`request_payment` on the vault only) |
| Payee | [`pw-payee.pursewarden.testnet`](https://testnet.nearblocks.io/address/pw-payee.pursewarden.testnet) | 0.5 NEAR (0.1 + the 0.4 payment), 0 keys |
| Missing payee | `pw-missing.pursewarden.testnet` | does not exist (allowlisted on purpose; the payment to it fails) |
| Attacker | `pw-attacker.pursewarden.testnet` | does not exist (not allowlisted) |

## Policy

B = 1 NEAR, M = 0.4 NEAR, K = 3, recipients [`pw-missing`, `pw-payee`], expiry `1794427035179574414` ns. Policy hash `fAFXFPi76a5wsebUX5maGCFUyMc6YsY9EneG3rQZhzL`: returned by `new`, equal to the independent encoder before any request was sent, and recomputed from the raw Borsh state by the inspector.

## Transactions

| # | Step | Signer → receiver | Planned | Observed (inspector, re-read from the node) | Explorer |
| --- | --- | --- | --- | --- | --- |
| 1 | `create_payee` | owner → pw-payee | payee created (keyless), 0.1 | FINAL; receipt graph closes; effect confirmed in the final state | [`2A8oQYdwSa…`](https://testnet.nearblocks.io/txns/2A8oQYdwSaz3eKdUGigFxgpzntPKTNXFxmYTtc6WYBQ7) |
| 2 | `create_agent` | owner → pw-agent | agent created, 0.5, 3 FunctionCall keys | FINAL; receipt graph closes; effect confirmed in the final state | [`24LFJWbvUH…`](https://testnet.nearblocks.io/txns/24LFJWbvUHwQXqU1f5UyaD3umxDCggqzXdZKypp1ipP5) |
| 3 | `create_vault` | owner → pw-vault | vault created, `c7c77263` deployed, `new(...)` returns the policy hash | FINAL; receipt graph closes; effect confirmed in the final state | [`BQfmcRW99T…`](https://testnet.nearblocks.io/txns/BQfmcRW99TYjL2L96eszJ4boAN4jkhxsFJDcA2DF2YVw) |
| 4 | `pay_1_payee` | pw-agent → pw-vault | Admitted; 0.4 transfer to payee succeeds | Admitted / native S | [`E5SFPvQgwY…`](https://testnet.nearblocks.io/txns/E5SFPvQgwYu7utMH49S3cPE1PVk7PSWP3zgau9cCAhG1) |
| 5 | `pay_2_missing` | pw-agent → pw-vault | Admitted; 0.4 transfer to `pw-missing` fails (`AccountDoesNotExist`); principal refunded to the vault | Admitted / native F / principal refund | [`8neZRYBVKK…`](https://testnet.nearblocks.io/txns/8neZRYBVKKx83JmEUHKN9WcnuiqDPNQBN3iydccoUBzo) |
| 6 | `replay_1` | pw-agent → pw-vault | Denied `DuplicateRequest` | Denied / DuplicateRequest | [`CWVnny9d3x…`](https://testnet.nearblocks.io/txns/CWVnny9d3xxMLFf7cMurjstFZxYQ3XGSYh6MYDzv1Ljr) |
| 7 | `over_cap` | pw-agent → pw-vault | Denied `AboveMaxPerRequest` | Denied / AboveMaxPerRequest | [`F1nMCJX9o7…`](https://testnet.nearblocks.io/txns/F1nMCJX9o7x1rpJY6bJPwsdNGNfi2HDQbXnJ9sL4LkBL) |
| 8 | `exfiltrate` | pw-agent → pw-vault | Denied `RecipientNotAllowed` | Denied / RecipientNotAllowed | [`3NMC6E5UVx…`](https://testnet.nearblocks.io/txns/3NMC6E5UVxmyFFe46AEisnHbMZmrWzTj7d2ruBreFkUk) |
| 9 | `budget_exceeded` | pw-agent → pw-vault | Denied `BudgetExceeded` (C 0.8 + 0.3 > B 1, one slot still free) | Denied / BudgetExceeded | [`94tmQWg9Vf…`](https://testnet.nearblocks.io/txns/94tmQWg9VfGpfbU2cFgUNg8wst4MRW1igb7Uk5tX7Q14) |
| 10 | `freeze` | owner → pw-vault | owner freezes the vault | FINAL; receipt graph closes; effect confirmed in the final state | [`69SHdQWoNt…`](https://testnet.nearblocks.io/txns/69SHdQWoNtTBu7ACq9tSYFwkFsgQzirqPgbb4LaAYgNR) |

## Final state (inspector, final block 277113571 `HDzAuuMEUe9ayUCw2vaB537oE9hLeq2bf8eWun88txRE`)

- Code SHA-256 = artifact `c7c772635acea0938bd88450d02bcdb9215d9aa65fc407b4070459cd225dd768`.
- Vault access keys: **0**.
- C = 0.8 NEAR = sum of the two admission records; headroom 0.2. The failed payment's refund did not restore C.
- accepted_count = 2, seq = 9, frozen = true.
- Owner spend: 3.29247 testnet NEAR = 3.26899 transfers + 0.02348 gas (cap 3.5).

## Files

- `plan-before.json`: read-only plan immediately before broadcasting.
- `actor.log`, `run.json`: the runner's log and transaction list with each FINAL `EXPERIMENTAL_tx_status` response.
- `inspection/inspection.json`, `inspection/rpc/`: the inspector's verdict and every raw RPC request/response it used.
- `after.json`: raw read-only RPC snapshot of every account afterwards.
- No key material: the owner key file was read only by `smoke_actor` and never written; the agent keys were generated in memory and discarded.

Reproduce the inspection (read-only):
```bash
python3 scripts/testnet/https_rpc_forwarder.py --port 3399 --upstream https://rpc.testnet.near.org &
python3 -m packages.verifier inspect-smoke --network testnet --rpc http://127.0.0.1:3399 \
  --run evidence/testnet-smoke/tn-20261110T195542Z/run.json --wasm artifacts/near_agent_vault.wasm --out /tmp/reinspect
```
Public nodes keep recent data only; after a few days, re-reading the transactions needs an archival endpoint.
