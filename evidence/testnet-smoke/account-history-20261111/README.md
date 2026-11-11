# Account history of the testnet vault (2026-11-11)

**Purpose.** The testnet inspection checks the vault's listed creation transaction and its current state. It cannot see an earlier account of the same name: one that was created with extra actions, deleted, and then re-created cleanly. A sandbox run in the independent delta review showed that such an earlier account can leave a delayed key for the new one (final audit PW-01b; see `docs/FINAL_AUDIT_RESPONSE.md`). This folder records the history of the accounts involved, so that you can check that `pw-vault.pursewarden.testnet` had no earlier life.

**Sources.** All files are public, read-only data. None contains key material.

| File | What it is | Taken by |
| --- | --- | --- |
| `v3_pursewarden.testnet.json` | NearBlocks testnet indexer, `/v3/accounts/pursewarden.testnet/txns?limit=100`, verbatim | independent delta reviewer, 2026-11-11 |
| `v3_pw-vault.pursewarden.testnet.json` | Same, for `pw-vault.pursewarden.testnet`, verbatim | independent delta reviewer, 2026-11-11 |
| `rpc_view_access_key_list_pursewarden.testnet.json` | `view_access_key_list` of the owner at a final block, through `test.rpc.fastnear.com`, verbatim | us, 2026-11-11, block 277232382 |

**What they show.**

- **Owner `pursewarden.testnet`.**
  - The indexer lists five transactions:
    1. its own creation by `testnet` at block 277110947;
    2. `create_payee`;
    3. `create_agent`;
    4. `create_vault` (`BQfmcRW9…`: `CreateAccount`, `Transfer`, `DeployContract`, `new`);
    5. `freeze`.
  - The owner has one key: a full-access key with nonce `277110947000004`. NEAR starts a new key's nonce at its creation block × 10⁶, so this key has signed at most four transactions. The four owner transactions recorded in `../tn-20261110T195542Z/run.json` account for all of them.
- **Vault `pw-vault.pursewarden.testnet`.** The indexer lists eight transactions:
  - the first is that four-action creation;
  - then six `request_payment` calls from the agent;
  - then `freeze`.

**Conclusion.**
- Only the parent `pursewarden.testnet` can create the name `pw-vault.pursewarden.testnet`.
- The parent's only key has signed nothing other than the four recorded transactions.
- So no earlier account of that name was created before this vault.

**Limits.**
- This rests on one indexer and one RPC operator. It is not a proof.
- The nonce argument assumes the owner never had another key. The indexer shows exactly one `AddKey`, in the account's creation.
- This evidence covers this vault only. It is not part of the automated inspection.
