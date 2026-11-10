# Public NEAR testnet smoke: attempts

TESTNET evidence. Every broadcast is listed, including failures. There was one broadcast.

| Run | What | Result |
| --- | --- | --- |
| `preflight-20261110T194516Z` | Read-only: account, keys, subaccount absence, plan. Nothing signed. | `pursewarden.testnet` 10 NEAR, 1 FullAccess key; all 5 subaccounts absent; plan sufficient |
| `tn-20261110T195542Z` | The owner-approved 10-transaction plan, `smoke_actor` from `4cc6020` | **PASS**: all 10 FINAL, every decision and native outcome as planned, inspector PASS, 0 vault keys, code = `c7c77263`, C = 0.8 = sum of records, frozen. Owner spent 3.29247 testnet NEAR (cap 3.5). |
