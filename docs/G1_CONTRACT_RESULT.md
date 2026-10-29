# G1 contract + local-sandbox feasibility result

| | |
| --- | --- |
| Date | 2026-10-29 (UTC run 21:40:36Z–21:41:35Z) |
| Branch / worktree | `feat/g1-vault` · `near-agent-vault-contract` |
| Code commit that produced the evidence | **`c9da90ceb8676e81d96620f45d40ace2aa3a8914`** (clean tree at run time). This report and the run evidence are committed in the next commit on this branch. |
| Artifact | `artifacts/near_agent_vault.wasm`, 154,714 bytes, SHA-256 **`5b05246bb41e11857f56845aca62edf92888e2ebbd210443f29577c22c216b26`**, NEAR code_hash `78Jec2oNSaHTZ4QRT4oxQHAFHNQNFfyHStBqHx3bVFau` |
| Evidence node | nearcore 2.13.4 sandbox, chain_id **`test-chain-4U2k3`**, genesis_hash **`kSN1GRyg2fN1TG7tPXKRpJGRfCnyHuME2ZqVP5NzCp5`**, PV 86, one shard |
| Evidence run | `evidence/g1/g1-20261029a/` — **115 / 115 checks PASS**, 74 transactions, 1,367 RPC calls |
| Network | **Local sandbox only.** No testnet or mainnet transaction, deployment, push, merge or real-money signature. |

## 0. Verdict

**G1 contract + sandbox gate: PASS for the scope below, on local-sandbox evidence only.** The SPEC-V1.1 / Phase0_E §3.3 two-payment probe executed with real receipts. With B = 5 NEAR, M = 2 NEAR and K = 2, a 1 NEAR payment succeeded and a 2 NEAR payment to a confirmed-absent allowlisted account failed and was refunded exactly. After freeze, the single-block cut shows **count = 2, C = 3 NEAR, S = 1, F = 2, U = 0, headroom = 2 NEAR**.

This is the runner's own evidence. It does **not** replace Agent B's independent collector, root discovery or omission-recovery gates, or Agent E's adjudication. Several SPEC validation-matrix rows are **not yet executed** (§8): late-failure atomicity, the FAULT builds, the K = 64 storage bound, liquidity and expiry, and runner isolation from the sandbox admin RPC. Node retention passed a 2,000-block re-read and a restart (§5.3).

## 1. Inputs read (provenance)

Read in full before coding (SHA-256 of the files as read):

| File | SHA-256 |
| --- | --- |
| `NEAR/reports/SPEC_V1_1_RECONCILED_DRAFT.md` | `7b2d8aa5126543c84297afb663e0ecdf74683928f5d7e5df154ad2e09954cefc` |
| `NEAR/reports/Phase0_E_Prebuild_Decision_2026-10-20.md` | `0b1e4cf500e835300fb21a3063ee53e86a72a4e5e43c50ead51ba0da271c8c63` |
| `NEAR/reports/Phase0_A_Runtime_and_Construction_Preflight_2026-10-20.md` | `d3be2453db46fe1495dde7fe4a2afa30afb253cd112c69aeca9d52e55880fcd7` |
| `NEAR/NEAR_Dual_Network_Implementation_Handoff_2026-10-23/NEAR_Dual_Network_Execution_Plan_2026-10-23.md` | `e091dfda2f5256e64780189c1c6ef35634b948a636f503d8fcdf8a63a29b7ab9` |
| `NEAR/NEAR_Dual_Network_Implementation_Handoff_2026-10-23/NEAR_Agent_Runbook_Dual_Network_2026-10-23.md` | `dcabc09638f9af4f12e426cef9edbddd0a2ba3ad3c4127fdb8c2fe236db9a4dd` |
| `NEAR/NEAR_Immediate_Build_Kickoff_2026-10-29.md` | `400691951d1d9f981c82cddc3edcb92ca72fb1578e225c73eb5cf15b5feaa7fa` |

The handoff folder's copies of the SPEC and the Phase0_E decision are byte-identical to the `reports/` copies. The research archive was not modified.

Repository state at start: `origin = https://github.com/mickeyjoes/near-agent-vault-lab.git`; the owner created the init commit `2ca4b51` and the worktrees `feat/g1-vault` / `feat/g1-evidence` during this session. Nothing was pushed.

## 2. Environment and pins

| Component | Pin / observed | Notes |
| --- | --- | --- |
| Host | Linux 6.8.0-147-generic x86_64, Python 3.12.3 | |
| Rust | `rust-toolchain.toml` → **1.93.0** (`rustc 1.93.0 (254b59607 2026-01-19)`, `cargo 1.93.0 (083ac5135 2025-12-15)`), target `wasm32-unknown-unknown` | sha256(rust-toolchain.toml) `492ca684…e81e7cd` |
| near-sdk | `=5.29.1` → near-sdk-macros 5.29.1, near-sdk-core **4.2.3**, near-sdk-env 0.1.6, near-sys 0.2.14 | Workspace `resolver = "3"` with `rust-version = "1.93"` keeps MSRV-compatible versions. near-sdk-core 4.3.0 / sdk 5.30.0 need Rust 1.95 and were not selected. |
| cargo-near | **0.22.0** (crates.io checksum `6c7efe31…69c1`, matches preflight), installed `--locked --no-default-features` (ledger off) into `~/.local/share/near-agent-vault-lab/cargo-near-0.22.0`; binary sha256 `ea59da15…4631fe` | cargo-near-build 0.11.5, wasm-opt `=0.116.1` |
| Lockfile | `Cargo.lock` committed, sha256 `ebaaefad725e778f75ae615b202c7d09a77469ae98b72e4432ef2185da4bf5da`; all builds/tests use `--locked` | |
| Harness deps | near-primitives / near-crypto `=0.37.4` (the versions near-workspaces 0.23.0 resolves), reqwest 0.12 (no TLS), tokio 1 | See §9 for why near-workspaces is not used |
| Sandbox binary | `near-sandbox` from the URL near-sandbox 0.3.16 uses for version `2.13.4`: `https://s3-us-west-1.amazonaws.com/build.nearprotocol.com/nearcore/Linux-x86_64/2.13.4/near-sandbox.tar.gz` | tarball sha256 **`5690a4635172263cf026683f75965cac09dd916912584f12709974fed620163f`**; binary sha256 **`4e89fbc0f2958634e84af44634f90e87c246288fa11b067d2121ce1394cba2c2`**; self-reported `neard (release 2.13.4) (build 2.13.4) (commit 44f7ae6cd7ef08bab604e20a473bf77e35d4c993) (rustc 1.93.0) (protocol 86) (db 49)`, features `[default, dump_test_contract, json_rpc, near_dump_test_contract, rosetta_rpc, sandbox]`. A hash records identity; it does not authenticate the binary (upstream publishes no checksum). |

## 3. Artifact

Build: `scripts/build-contract.sh`. It runs `cargo-near near build non-reproducible-wasm --locked --no-abi --env 'RUSTFLAGS=-C link-arg=-s --remap-path-prefix=$CARGO_HOME/registry/src=/cargo/registry/src --remap-path-prefix=$REPO=/build'`. cargo-near force-appends `--cfg near`, and wasm-opt `-O --enable-nontrapping-float-to-int --enable-bulk-memory` runs afterwards.

- **SHA-256 `5b05246bb41e11857f56845aca62edf92888e2ebbd210443f29577c22c216b26`**, 154,714 bytes, base58 code hash `78Jec2oNSaHTZ4QRT4oxQHAFHNQNFfyHStBqHx3bVFau`. The deployed `code_hash` and the `view_code` bytes equal the artifact.
- **Rebuild:** rebuilt from a copy at a different path with a fresh target directory → byte-identical. This shows path independence on this machine and toolchain only; cross-machine reproduction has not been tested. The build is not cargo-near's Docker `reproducible-wasm`.
- **Capability gate** (`scripts/inspect_wasm.py`, stdlib-only, fail-closed; report in `artifacts/near_agent_vault.inspect.json`): **PASS**.
  - **Imports (24, all `env`):** account_balance, attached_deposit, block_index, block_timestamp, chain_id, current_account_id, input, log_utf8, panic_utf8, predecessor_account_id, promise_batch_action_function_call, promise_batch_action_transfer, promise_batch_create, promise_batch_then, promise_result, promise_results_count, read_register, register_len, sha256, storage_has_key, storage_read, storage_usage, storage_write, value_return.
  - **Denylist:** no Phase0_A §1.2 entry is imported. That list covers create/deploy/stake/add-key/delete-key/delete-account/global-contract/state-init/gas-key/yield, `promise_create/then/and/return`, refund redirection, and `function_call_weight`.
  - **Callable exports:** exactly `new, request_payment, on_payment_result, freeze, get_mandate, get_request, get_admissions, contract_source_metadata`. The last is generated unconditionally by near-sdk 5.29.1 for `#[near(contract_state)]` (NEP-330); it returns `{"version":"0.1.0","link":"https://github.com/mickeyjoes/near-agent-vault-lab","standards":[{"standard":"nep330","version":"1.3.0"}],"build_info":null}`.
  - **Non-callable exports:** `memory`, plus the immutable linker globals `__data_end` and `__heap_base`. These are accepted by exact name only after the global section shows them immutable.
  - **Other checks:** no multi-value function types, no start function.
  - **Self-test:** a synthetic module importing `promise_batch_action_delete_account` and exporting `withdraw` FAILS the gate.
- The import check proves absence of a host capability, not argument correctness. Arguments are verified on executed receipts (§6.2).

## 4. Contract (what was built)

`contracts/vault/src/{lib.rs,policy.rs,canonical.rs}`, about 600 lines.

- **Construction.** One owner-signed batch to `vault.<owner>`: `CreateAccount, Transfer(F), DeployContract(wasm), FunctionCall(new, deposit 0)`. There is no `AddKey`.
- **Initializer.** `new` is `#[init]`, nonpayable, not private, and rejects re-initialization. It requires:
  - vault is a direct subaccount of owner (the predecessor);
  - the agent is not owner or vault;
  - 0 < M ≤ B;
  - 1–8 named recipients (each containing `.`), none of them a role account, in strictly increasing UTF-8 byte order;
  - expiry later than the init block's timestamp;
  - 1 ≤ K ≤ 64 (default 64);
  - chain_id ≤ 64 bytes;
  - balance ≥ R_total.

  `new` returns the base58 policy hash via `env::value_return`.
- **Policy identity.** Exact SPEC §3 Borsh layout and the 32-byte domains `near-agent-vault-lab/mandate/v1\0` and `…/request/v1\0`. **TV1, TV2 and TV3** body bytes and hashes, TV1+1 yocto, and both request digests are reproduced byte-for-byte (`cargo test -p near-agent-vault`). The harness's separately written encoder reproduces TV1 and computes the on-chain hash from the observed chain ID.
- **Canonical inputs.** Integers are JSON strings matching `0|[1-9][0-9]*` (≤ 20 digits for u64, ≤ 39 for u128, range-checked); the grammar is applied to the decoded string, so `"1"` is ID 1. Policy hashes must be canonical base58 of exactly 32 bytes (≤ 44 chars, re-encode equality). `#[deny_unknown_arguments]` is set on `new`, `request_payment` and `on_payment_result`, and serde rejects duplicate keys.
- **Admission order** (SPEC §4):
  1. `predecessor == agent`, nonpayable and schema guards → receipt failure, not a denial;
  2. then, in order: PolicyMismatch, Frozen, Expired, DuplicateRequest, RecipientNotAllowed, ZeroAmount, AboveMaxPerRequest, BudgetExceeded (checked add), RecordQuotaExhausted, InsufficientLiquidity (`balance < amount + R_total`).

  A denial increments only `seq` and emits an event. An admission, in one receipt, does: C += a, count += 1, seq += 1; writes the record and the index entry; creates **one** `promise_batch_create(recipient) + promise_batch_action_transfer(a)`, then `promise_batch_then(self) + promise_batch_action_function_call("on_payment_result", {"request_id":"<id>"}, deposit 0, 20 Tgas)`.
- **Callback.** `on_payment_result` is private and requires exactly one promise result. Pending → CbSucceeded/CbFailed with the matching amount counter; a terminal duplicate is a no-op. It never touches C, policy, count, index or frozen.
- **Freeze.** `freeze` is owner-only, nonpayable, irreversible and idempotent (the no-op emits no event and leaves seq unchanged; the SDK wrapper still rewrites identical STATE bytes, observed in §8).
- **No outflow paths.** There is no withdraw, sweep, upgrade, key, re-init, policy-mutation or unfreeze path. Residual funds are locked by design.
- **Storage bound.**
  - `S_max = storage_usage_in_new (account record 100 + code) + (5 + 1024 + 40) [STATE] + K × 128`, where 128 = index entry (5 + 8 + 40) + record entry (9 + 26 + 40).
  - `R_total = S_max × 10^19 + 0.01 NEAR` margin.
  - Unit tests prove a maximal STATE ≤ 1024 bytes and a fixed 26-byte record. The runtime parameters (10^19 yocto per byte, 40 extra bytes per record, 100 account bytes) are checked against `EXPERIMENTAL_protocol_config` in the run.

## 5. Node and retention

### 5.1 Start (reviewer-owned, outside near-workspaces)

`scripts/sandbox-setup/start-node.sh g1-20261029a` does the following:

- Verifies the tarball and binary SHA-256.
- Runs `near-sandbox --home .sandbox/g1-20261029a init --fast`, then patches `genesis.epoch_length = 100000` and `config.save_tx_outcomes = true`, `save_receipt_to_tx = true`, `tracked_shards_config = AllShards`.
- Runs `near-sandbox --home … run --rpc-addr 127.0.0.1:3130 --network-addr 127.0.0.1:24667`.

No genesis helper accounts with published keys are added; genesis has only `test.near` (validator/root) and `near`. Started 2026-10-29T21:24:44Z.

Effective configuration, read back through the `client_config` RPC (the `EXPERIMENTAL_client_config` alias does not exist on 2.13.4): `archive = false`, `save_tx_outcomes = true`, `save_receipt_to_tx = true`, `save_state_changes = true`, `save_trie_changes = true`, `gc_num_epochs_to_keep = 5`, `epoch_length = 100000`, `tracked_shards_config = AllShards`.

Genesis: `min_gas_price = 1e8`, `transaction_validity_period = 100`, one shard (`ShardLayout V2`, shard 0). Hashes of the patched files: genesis.json `39ec60b8…27cad69`, config.json `53b8465f…929e65a`. Copies of both are in `evidence/g1/g1-20261029a/node/`.

The observed rate was about 7.9 blocks/s. With 5-epoch GC at 100,000 blocks per epoch, garbage collection cannot start before 500,000 blocks (about 17 h at the observed rate). This is a configuration inference, not a guarantee.

### 5.2 Run interval

| Point | Height | Hash |
| --- | --- | --- |
| H0 (final head before application setup) | 7501 | `4yLGk3C1ffvxQkESZc43WY5KCNvqTV73NhcKVW1cuP6T` |
| Vault creation receipt executed | 7531 | `6Z3rtCTqjj7wP8mXLwzZ8nGeEbqbSUWYyhjKQSMTH7xz` |
| Q (single final cut, vault 1, after freeze) | 7908 | `FyjkrDZXRCMnoKHbuHN4qi4366Fm6B4hgLQckuH3hAQU` |
| End of run (after vault-2 probe) | 7962 | `7Z5s2vCfH2axrQsdywGQ79gJqCQXHMZp5N4idJ8Ls5qF` |

### 5.3 Retention re-check

**PASS (7 / 7), `retention.json`.** After the run ended at height 7962, the test waited without fast-forward until final height **9962** (`BuE6F4pKwi6Dj6x8WMdYyZrRotWGuReEPBUMpTJxY5oT`). That is 2,000 blocks after the run end and 2,431 after vault creation. It then re-queried:

- **all 74** transactions' `EXPERIMENTAL_tx_status(FINAL)`: every response is byte-identical to the captured one;
- the creation block `6Z3rtCTq…`;
- the inclusion block `7LNZ1y7w…` (height 7530) and its shard-0 chunk, which contains the creation transaction;
- historical state at the creation block: `view_account` (code hash = artifact, storage 155,154), zero access keys, and `get_mandate` with seq 0 and C 0;
- `EXPERIMENTAL_receipt` for refund `AV2qULRX…` (predecessor `system`, `Transfer 2e24`), with `EXPERIMENTAL_receipt_to_tx` mapping it to payment-2 root `GsWjon2U…`;
- `EXPERIMENTAL_changes` at the refund block 7817.

**Restart (`restart-check.json`): PASS.** `scripts/sandbox-setup/stop-node.sh` followed by `restart-node.sh` on the same home kept the same chain ID and genesis, and the FINAL outcomes of the creation, payment-1, payment-2 and freeze transactions were byte-identical at head 10249.

This shows retention for a bounded run plus a 2,000-block gap and one restart. It is not archival permanence; the node is non-archival with 5-epoch GC.

**State left running:** the evidence node is serving at `http://127.0.0.1:3130` (pid in `.sandbox/g1-20261029a/node.pid`) for Agent B / E.

## 6. Results

### 6.1 Test counts

| Suite | Command | Result |
| --- | --- | --- |
| Contract unit tests (vectors, parser, storage constants, encodings) | `cargo test -p near-agent-vault --locked` | **12 / 12 pass** |
| Harness unit test (independent encoder vs TV1 + request vector) | `cargo test -p g1-sandbox-tests --locked --lib` | **1 / 1 pass** |
| Sandbox scenario (evidence run `g1-20261029a`) | `G1_RUN_ID=g1-20261029a cargo test -p g1-sandbox-tests --locked --test g1 -- --nocapture` | **115 / 115 checks pass** (critical checks stop the run on failure) |
| Retention (≥ 2,000 blocks after run end) | `G1_RUN_ID=g1-20261029a cargo test -p g1-sandbox-tests --locked --test retention -- --nocapture` | **7 / 7 pass** (+ restart check PASS) |

Check groups in `evidence/g1/g1-20261029a/checks.json`: failure_no_effect 45 (44 receipts + 1 aggregate), denial 15, authority 9, probe2 7, construction 6, payment2 5, ledger 5, cut 4, node 3, storage 3, payment1 3, freeze 2, interval 2, and 1 each for runtime, artifact, setup, events, accounting and gas.

### 6.2 The G1 two-payment probe (vault 1)

- **Policy.** vault `vault.owner.test.near`, owner `owner.test.near`, agent `agent.owner.test.near`, recipients `["alice.test.near","missing.test.near"]`, B = 5 NEAR, M = 2 NEAR, K = 2, expiry `1793396439698529554`.
- **Policy hash.** `4uykmePuXrCjgcHkDwVunSeEQyvpqDjdxcL7QutuUTao` (hex `3a256f7f7c34ba873856071c1ceaf0f33a63fb2a3d730b4f7ec08ed87cf40428`). It equals the harness's independent encoding over the observed `test-chain-4U2k3`.
- **Funding.** F = 7.57139 NEAR = B + R_total (1.57139 NEAR; S_max = 156,139 bytes) + 1 NEAR.
- **Preconditions.** `alice.test.near` was created keyless with 1 NEAR. `missing.test.near` returned `UNKNOWN_ACCOUNT` before the run and again at Q.

| Step | Transaction | Receipts (height) | Observed |
| --- | --- | --- | --- |
| Create vault | `HowLK1P5AkMTLd2XniF29Mo2AvAp1WteAXRnTgWsDDVQ` | `5i2ydQS2e1hyL1yYX88gtqiYNNFD9TcLpri3TR1g4Cf8` (7531): `[CreateAccount, Transfer(7.57139 NEAR), DeployContract(code hash = artifact), FunctionCall(new, deposit 0)]` | Success; returned the policy hash; **zero keys at the creation block** |
| Payment 1: ID `1`, 1 NEAR → alice | `45bGCF8dtnaDhkL48CwZ1GZMBeZ1cxyr6i7hdwXzzENS` | admission `7bMRmqF2LQUf1nZ7QgDMQYG9bSX6aUjUxyQArEqPk556` (7807); transfer `3ts7Sxsgg3e67bcBVqhAruwo6nqZeDJPqDhnuZQkeZAj` vault→alice `[Transfer 1e24]` (7808) **SuccessValue**; callback `2c39RzrpFpsTypE5KS3nM9ahJ4NBrW5kJG89CszQYrkn` vault→vault `[FunctionCall on_payment_result, deposit 0, gas 20 Tgas, args {"request_id":"1"}]` (7809) success, CbSucceeded | Admitted, C 0 → 1 NEAR, request digest equals the independent digest |
| Payment 2: ID `2`, 2 NEAR → missing | `GsWjon2UCLHTGpFagSBXfViwZXY7sy1FeWGJPUsNXowZ` | admission `2tR2JwUWYLrW59bm6soKrDVq36kBgnQErdAsdFGFK61Z` (7815); transfer `9WSb4SpC5VcVgvBdEvx8RF7TczpwjeJs1z9nP9F9fnb6` vault→missing `[Transfer 2e24]` (7816) **Failure: AccountDoesNotExist**; refund `AV2qULRXpBMJxceXubJWhw66trdandPJvyqj8zzcdoeL` predecessor `system` → vault `[Transfer 2e24]` (7817) success; callback `5pwHQKPYnrXJQdTFGqJtgp9ZhzxchG1RcKDm1VPCE31W` (7817) success, CbFailed | Admitted, C 1 → **3 NEAR**, digest equals the independent digest |
| Freeze (owner) | `HCqEQ1tZqtspZCbi7pP6VqXoh5zWsNWMGcrtueL4hfhz` | `5b3pPXUwwhN2wU4EJYfqgeuihJzzJtPr1thfWyusCmCv` (7889) | frozen, seq 18 → 19; a second freeze was a no-op (seq unchanged, no event) |

Every admission produced **exactly two application receipts** (receipts whose predecessor is the vault): one Transfer of the requested amount to the allowlisted recipient and one zero-deposit callback to self. All other receipts are `system` refunds. Across all 74 transactions in the run, exactly the 5 admissions (2 on vault 1, 3 on vault 2) produced vault-predecessor receipts, two each; no denial, failure, freeze or view call produced any. Receipt-graph closure is complete for every transaction: every referenced receipt has an outcome and every outcome has a body (`transactions.json` → `graph_closure`). All roots reached `final_execution_status = FINAL`.

**Single-cut state at Q = 7908.** `get_mandate`, `get_admissions`, raw `view_state`, `view_access_key_list` and `view_account` were all answered at block `FyjkrDZX…`. The raw state was decoded independently by the harness.

| Quantity | Value | Source |
| --- | --- | --- |
| C (charged) | **3 NEAR** | view = raw STATE = Σ admissions |
| headroom B − C | **2 NEAR** | view |
| accepted_count / records / index | 2 / `r‖1`, `r‖2` / `i‖0→1`, `i‖1→2` | raw state |
| S / F / U (native transfer outcomes) | **1 / 2 / 0 NEAR** | FINAL transfer-receipt outcomes, not balances |
| cb_succeeded / cb_failed / callback-unconfirmed | 1 / 2 / 0 NEAR | view (separate observation) |
| seq / frozen | 19 / true | view = raw |
| Vault keys | `[]` | `view_access_key_list` at the creation block and at Q |
| storage_usage | 155,154 after init → 155,410 at Q (exactly +128 × 2) ≤ bound 156,139 | `view_account` |

**Interval scan, heights 7531–7908** (378 blocks, no missing heights):

- **C never decreases.** 21 STATE writes decoded; C goes 0 → 1 → 3 NEAR and stays at 3 through the refund.
- **No key changes.** Zero vault access-key changes.
- **One code change.** Exactly one vault code change, at height 7531, cause `receipt_processing` of the creation receipt.
- **No migration.** Zero `migration`-cause changes on the vault, i.e. no `sandbox_patch_state` on the vault.

**Contract state versus balance.** Each of the **44** failed vault receipts left **no contract-data change** (data changes filtered by `cause.receipt_hash`).

- **31 of them** (every failure that executed WASM) still credited the vault an `action_receipt_gas_reward` balance change. The same filter matches that account change, so the empty-data result is not vacuous.
- **The 13 `MethodNotFound` receipts** left **no vault account change at all**: method resolution fails before execution, so no function-call gas is burnt and no reward is credited.

This confirms Phase0_E's correction that a gas-reward trace is not universal: failed vault receipts must be discovered by transaction/chunk enumeration, not from vault state changes. Across the failed calls the balance rose by 0.000224 NEAR while seq and C stayed 0. Over both payments the vault balance fell by only **0.99984 NEAR**, while C rose by 3 NEAR. Principal is therefore taken from Transfer receipts and their outcomes, never from balance differences.

### 6.3 Authority, method restriction, malformed input and replay

- **Rejected at validation; no on-chain trace.** These are agent function-call key attempts. Key 0's on-chain nonce and the vault's seq were unchanged afterwards.
  - `freeze` and `get_mandate` → `MethodNameMismatch`;
  - `request_payment` with 1 yocto attached → `DepositWithFunctionCall`;
  - a different receiver → `ReceiverMismatch`;
  - plain Transfer of 1 yocto → `RequiresFullAccess`;
  - plain Transfer of 1 NEAR → `NotEnoughAllowance` (on 2.13.4 the allowance check runs before the permission check; see §9);
  - two actions in one transaction → `RequiresFullAccess`;
  - AddKey on the agent → `RequiresFullAccess`.
- **Agent shape.** No code (`code_hash 1111…`); exactly 8 keys, each `FunctionCall{receiver_id: vault, method_names: ["request_payment"], allowance: 0.25 NEAR}`; no full-access key.
- **Receipt failures with no contract-data change and zero application receipts** (44 receipts):
  - owner `request_payment` and stranger `request_payment`/`freeze` → `Unauthorized`;
  - owner `on_payment_result` → `Method on_payment_result is private`;
  - owner `freeze` and `request_payment` with 1 yocto → `doesn't accept deposit`;
  - owner second `new` → `The contract has already been initialized`;
  - 13 non-exported names (`withdraw, transfer, sweep, upgrade, migrate, add_key, delete_key, delete_account, deploy, stake, set_policy, unfreeze, reset_budget`) → `MethodNotFound`;
  - 24 malformed agent requests → `Failed to deserialize input from JSON`. These were: ID `+7`, `07`, ` 7`, `7 `, JSON number `7`, `7.0`, `1e1`, `-7`, `""`, `0x7`, and 2^64; amount `+1`, `01`, JSON number, `1e24`, and 2^128; policy hash given in hex, 45 chars, or non-base58; a duplicate `request_id` key; an unknown field; a missing field; an invalid AccountId; and non-JSON input.
- **Committed denials** (seq +1 each, no application receipt, C stays 3, count stays 2):
  - ID 1 replay, same terms → DuplicateRequest (`terms_match` true);
  - ID 2 replay (the failed-transfer ID) → DuplicateRequest;
  - ID 1 with different terms → DuplicateRequest (`terms_match` false);
  - `"1"` → DuplicateRequest, same identity as ID 1;
  - TV1's policy hash → PolicyMismatch;
  - bob, owner, or the vault itself as recipient → RecipientNotAllowed;
  - amount 0 → ZeroAmount;
  - 2 NEAR + 1 yocto → AboveMaxPerRequest;
  - 2 NEAR to alice with ID 3 → **RecordQuotaExhausted** (C + 2 = 5 ≤ B, so budget was not the reason);
  - after freeze, a new ID and ID 1 → Frozen.
- **Retry of a denied ID.** Before payment 1, ID 1 with amount 0 → ZeroAmount, and `get_request("1")` returned null. ID 1 was then admitted, so denied IDs are not retained. `get_request("3")` was null at the end.

### 6.4 Remaining authority, demonstrated behaviourally (vault 2)

With M = 2, vault 1 cannot show `BudgetExceeded` once C = 3: every amount ≤ M fits the remaining 2 NEAR. A second vault with its own agent and keys therefore shows that the remaining authority is exactly 2 NEAR. It used B = 5 NEAR, M = 3 NEAR, K = 4, the same recipients, and policy hash `9edEviPcxSjpiC6B3HcidV8WT5hjUAfjJrk7mzJ5zSzt`. It was created keyless, and its hash equals the independent encoding.

| Tx | Request | Result |
| --- | --- | --- |
| `99fbwb4y14h2UXJd3V7DZcA924cNobDfkti7AZSuyWM7` | ID 1, 1 NEAR → alice | Admitted, transfer success |
| `AnyRLsvKXj9XpQqxLxRm8H6sQDnXwZuvhQ7a3EvjQ3bC` | ID 2, 2 NEAR → missing | Admitted, transfer failed, refunded |
| `4eKy3nJpFuGSSxkhu3TEm5BSgDgjJejnCpGwzieSSHsN` | ID 3, 3 NEAR → alice (after the refund; liquidity available) | **BudgetExceeded** |
| `Ftw3nQJBrfZb4BbotVaD5v2DBk7PA4JTiouFfGPo6Go3` | ID 4, 2 NEAR → alice | Admitted, C = 5 |
| `HuBozQfW7DRBDcDarCUi4h2zQceUZ8Lj3bHCvY8EXxEf` | ID 5, 1 yocto → alice | **BudgetExceeded** |

Final state: C = 5 NEAR, headroom 0, S = 3, F = 2, count 3. The refund never restored authority.

### 6.5 Gate table

| # | Gate (kickoff / Phase0_A R-id) | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Pinned toolchain + lockfile | **PASS** | §2; `--locked` everywhere |
| 2 | SPEC vectors in Rust/Borsh (R1) | **PASS** | unit tests; on-chain hash = independent encoding |
| 3 | Canonical ID/amount/hash parsing (R5) | **PASS** for 24 on-chain + 19 unit aliases | §6.3 |
| 4 | Forbidden WASM capabilities absent; exact exports (R1) | **PASS** | §3, `artifacts/near_agent_vault.inspect.json` |
| 5 | Deploy on PV86 (no PrepareError) (R1) | **PASS** | creation receipt success |
| 6 | Keyless from inception in one creation batch (R2) | **PASS** | creation actions; zero keys at creation block and Q; zero key changes in the interval |
| 7 | Agent restricted to zero-deposit `request_payment` (R2) | **PASS** | §6.3 |
| 8 | No alternative transfer/capability methods; no owner outflow | **PASS** (exports + 13 names + authority failures) | §3, §6.3 |
| 9 | Successful 1 NEAR payment (R8) | **PASS** | §6.2 |
| 10 | Failed 2 NEAR payment to absent account with exact refund (R8) | **PASS** | §6.2 |
| 11 | C = 3 after failed transfer; S1/F2/U0; headroom 2 | **PASS** | §6.2 cut, interval scan |
| 12 | Remaining authority = 2 on a 5 NEAR mandate (behavioural) | **PASS** | §6.4 |
| 13 | Malformed / replay requests denied; denied IDs not retained | **PASS** | §6.3 |
| 14 | Callback cannot release authority (success and failure paths) | **PASS** for real callbacks; forced-panic callback (R4) **NOT RUN** | §6.2; §8 |
| 15 | Contract state distinguished from balance | **PASS** | §6.2 |
| 16 | Callback gas ≥ 3 × burnt | **PASS** (1.744 Tgas burnt vs 20 Tgas prepaid, ≈ 11×) | checks.json `gas.*` |
| 17 | Storage within declared bound | **PASS for K = 2**; K = 64 (R6) **NOT RUN** | §6.2 |
| 18 | Node retention after ≥ 2,000 blocks (Phase0_E §3.1) | **PASS** (74 / 74 outcomes identical; old block, chunk and historical state served; survives restart) | `retention.json`, `restart-check.json` |
| 19 | Runner cannot use admin RPC (Phase0_E §2) | **NOT DEMONSTRATED** | §8 |

## 7. Reproduce

```bash
# from the feat/g1-vault worktree root
rustup toolchain install 1.93.0 --target wasm32-unknown-unknown --profile minimal   # rust-toolchain.toml selects it
cargo +1.93.0 install cargo-near --version =0.22.0 --locked --no-default-features \
  --root ~/.local/share/near-agent-vault-lab/cargo-near-0.22.0

cargo test -p near-agent-vault --locked                 # 12 vector/parser/storage unit tests
cargo test -p g1-sandbox-tests --locked --lib           # independent encoder
scripts/build-contract.sh                               # must print 5b05246b…2c216b26 and "capability gate: PASS"
git diff --exit-code artifacts/                         # rebuilt artifact equals the committed one

RUN=g1-$(date -u +%Y%m%dT%H%M%SZ)
scripts/sandbox-setup/start-node.sh "$RUN"              # downloads/verifies 2.13.4, fresh home, port 3130
G1_RUN_ID=$RUN cargo test -p g1-sandbox-tests --locked --test g1 -- --nocapture
G1_RUN_ID=$RUN cargo test -p g1-sandbox-tests --locked --test retention -- --nocapture   # waits ≥ 2,000 blocks
scripts/sandbox-setup/stop-node.sh "$RUN"                 # history stays on disk
scripts/sandbox-setup/restart-node.sh "$RUN"              # re-serve the same chain later
```

- **Ports.** `RPC_ADDR` / `NET_ADDR` override the defaults (127.0.0.1:3130 / 24667), and `G1_RPC_URL` must then match. The dry runs used 3131 / 24668.
- **Fresh node per run.** A fresh chain gets a new random `test-chain-*` ID, so policy hashes differ per node by design (SPEC §3: `chain_id` is a policy field).
- **Reusing a stopped evidence node.** To re-serve the evidence node later: `scripts/sandbox-setup/restart-node.sh g1-20261029a` (it verifies the binary hash and reuses the recorded ports). The node home is gitignored and holds the validator and node private keys.

## 8. Unknowns, open items and blockers

No STOP condition fired. None of the following blocks the G1 contract claim as scoped above, but each one blocks a stronger claim:

1. **Runner/admin isolation is not demonstrated.** `sandbox_patch_state` and `sandbox_fast_forward` are reachable by anyone who can reach 127.0.0.1:3130. In this run the harness also used the validator `test.near` key from the node home, for setup only. The only corroboration is zero `migration`-cause changes on the vault over the interval. *Smallest next fix:* give the runner an RPC proxy that forwards only `send_tx`, `EXPERIMENTAL_tx_status`, `query` and `block`, plus agent keys only; the reviewer keeps the node home. This belongs to the Agent B / E boundary.
2. **Not executed: late-failure atomicity (R3).** That covers the gas sweep and the FAULT builds (late panic, `LackBalanceForState`). The atomicity claim currently rests on runtime source (Phase0_A §1.3) plus the 44 observed no-effect failures, all of which failed before any mutation.
3. **Not executed: forced callback failure (R4).** It needs the FAULT build. Only real callbacks were observed: success and failed-transfer paths both left C intact.
4. **Not executed: K = 64 storage ceiling (R6)** with B = 65 yocto, M = 1, 64-character recipients. G1 used K = 2; the per-admission growth matched the model exactly (128 bytes).
5. **Not tested: InsufficientLiquidity (R7) and Expired.** Expiry needs time travel, which must not happen on the evidence node.
6. **This is runner evidence.** The harness knows its own transaction hashes. Independent root discovery and omission recovery (R9, Phase0_E §3.4–3.5) are Agent B's deliverable. `evidence/g1/g1-20261029a/transactions.json` is a convenience index, not a trust anchor.
7. **Binary identity is not authenticated.** No upstream checksum exists for the sandbox tarball, so the SHA-256 is recorded but unverified against a source. Cross-machine build reproducibility is also not established.
8. **Deliberate choices a reviewer may want to revisit:**
   - unknown JSON fields are rejected;
   - the vault must be a *direct* subaccount of the owner;
   - chain_id must be ≤ 64 bytes;
   - the reserve margin is 0.01 NEAR;
   - callback gas is 20 Tgas;
   - `freeze` and the duplicate-callback no-op still rewrite identical STATE bytes, which appear as a `data_update` with unchanged value. Observed for the second freeze: receipt `D4CDfeg8Ln5qjWZ8SzQVJikWGSfkKqnfpECvvNL4Attw` wrote one `data_update` to key `STATE`, with seq unchanged. A verifier must not treat such a write as a semantic transition.
9. **Repository link in the artifact.** `contract_source_metadata` embeds the private repository URL.
10. **Possible overlap with Agent B's node.** If Agent B starts its own node on the default ports, they do not collide with 3130/24667.

## 9. Deviations from the candidate plan (with reasons)

- **near-workspaces 0.23.0 / near-sandbox 0.3.16 are not linked.** Workspaces' `transact()` retries any error up to four times and re-signs with a fresh nonce (`rpc/client.rs` `send_batch_tx_and_retry`). That can create an extra root transaction. It also settles on `broadcast_tx_commit` (EXECUTED_OPTIMISTIC, without refunds). Phase0_A §2.4 asks for raw calls with no hidden helpers, so the harness signs each transaction once with the same near-primitives/near-crypto 0.37.4 types, submits it through `send_tx(wait_until=INCLUDED)`, and settles with `EXPERIMENTAL_tx_status(wait_until=FINAL)`. The node binary is the exact file near-sandbox 0.3.16 would download for `"2.13.4"`.
- **Rejection reason differed from the preflight's expected check order.** On 2.13.4 an FC-key transfer larger than the allowance reports `NotEnoughAllowance` before `RequiresFullAccess`. Dry run 1 stopped on this, the expectation was corrected to the observed behaviour, and a 1-yocto case was added that shows `RequiresFullAccess`. Both are validation rejections.
- **Path remapping was added to the build** (`--remap-path-prefix`), after dry runs 1–2, so the artifact embeds no home or checkout paths. This changed the artifact hash. Dry runs 1–2 used `771fbc09…3415732c`; dry run 3 and the evidence run used the final `5b05246b…2c216b26`.

## 10. Minimal interface contract for Agent B

**Network.** The evidence node (reviewer-readable) is at `http://127.0.0.1:3130`, chain `test-chain-4U2k3`, genesis `kSN1GRyg2fN1TG7tPXKRpJGRfCnyHuME2ZqVP5NzCp5`, interval heights 7501–7962. Treat everything in `evidence/` as untrusted runner output; re-derive it from your own node view.

**Construction.**

- Vault: one owner-signed transaction to `<name>.<owner>` with actions exactly `[CreateAccount, Transfer(F), DeployContract(code), FunctionCall("new", args, deposit 0)]`; never AddKey.
- Expected: zero vault keys forever, exactly one code change, `code_hash = base58(sha256(wasm))`.
- Agent: one owner-signed transaction `[CreateAccount, Transfer, AddKey(FunctionCall{receiver_id: vault, method_names: ["request_payment"], allowance: finite}) × n]`, no code and no full-access key.

**Methods** (JSON in and out; every integer is a canonical decimal *string*; hashes are base58):

| Method | Caller / deposit | Args | Returns / effect |
| --- | --- | --- | --- |
| `new` | owner (predecessor) in the creation batch; deposit 0 | `{agent, budget, max_per_request, allowed_recipients[1..8 sorted by bytes], expires_at_ns, max_accepted_requests?}` | JSON string: policy hash (base58). Event `init` (seq "0") |
| `request_payment` | `predecessor == agent`; deposit 0 | `{request_id, recipient, amount, policy_hash}` | `{"decision":"Admitted", seq, request_id, recipient, amount, request_digest_hex, charged_before, charged_after}` or `{"decision":"Denied", seq, request_id, recipient, amount, reason, charged, original_admission_seq, terms_match}` |
| `on_payment_result` | private (predecessor = vault); deposit 0 | `{request_id}` | none. Event `callback` |
| `freeze` | owner; deposit 0 | `{}` | none. Event `freeze` the first time only |
| `get_mandate` | view | `{}` | policy fields, `policy_hash`, `policy_hash_hex`, `storage_bound_bytes`, `reserve_margin`, `reserve_total`, `callback_gas`, `charged`, `headroom`, `cb_succeeded_amount`, `cb_failed_amount`, `callback_unconfirmed`, `accepted_count`, `seq`, `frozen`, `expired`, `block_height`, `block_timestamp_ns`, `account_balance`, `storage_usage` |
| `get_request` | view | `{request_id}` | `{request_id, recipient, recipient_index, amount, admission_seq, callback_status, request_digest_hex}` or `null` |
| `get_admissions` | view | `{}` | array of the above in admission order (≤ K ≤ 64) |

**Receipt shape of one admission.** Executor = vault, predecessor = agent. It creates exactly:

- `vault → recipient`: `[Transfer{deposit: amount}]`;
- `vault → vault`: `[FunctionCall{method_name: "on_payment_result", args: {"request_id":"<id>"}, gas: 20000000000000, deposit: 0}]`, data-dependent on the transfer.

If the transfer fails, the runtime adds `system → vault` `[Transfer{deposit: amount}]`. Every other receipt with predecessor `system` is a gas refund. Denials and failures create no vault-predecessor receipts.

**Events.** Log lines of the form `EVENT_JSON:{"standard":"near-agent-vault-lab","version":"1.0.0","event":"init|admission|denial|callback|freeze","data":{seq, vault, policy_hash, …}}`. Ignore logs from failed receipts.

**Raw state** (`view_state`, prefix ""):

| Key | Value (Borsh, little-endian) |
| --- | --- |
| `STATE` | the policy fields in SPEC §3 order (chain_id String, vault, owner, agent, asset u8 = 0, budget u128, max_per_request u128, recipients Vec&lt;String&gt;, expires_at_ns u64, K u32), then `policy_hash [u8;32]`, `storage_bound_bytes u64`, `reserve_total u128`, `charged u128`, `cb_succeeded_amount u128`, `cb_failed_amount u128`, `frozen u8`, `accepted_count u32`, `seq u64` |
| `b'r' ‖ u64 LE request_id` (9 bytes) | `recipient_index u8, amount u128, admission_seq u64, status u8 (0 Pending, 1 CbSucceeded, 2 CbFailed)` (26 bytes) |
| `b'i' ‖ u32 LE position` (5 bytes) | `request_id u64 LE` (8 bytes) |

The first 9 STATE fields Borsh-encode exactly the policy body. Therefore `policy_hash = SHA256("near-agent-vault-lab/mandate/v1\0" ‖ STATE[0..policy_len])`, and `request_digest = SHA256("near-agent-vault-lab/request/v1\0" ‖ Borsh(vault, policy_hash, agent, id u64, recipient, amount u128))`. A reference decoder is `decode_state` / `decode_record` in `tests/sandbox/src/lib.rs`.

**Discovery caveat (observed).** A call to a non-exported method fails with `MethodNotFound` and leaves no vault account or data change, so it is invisible to vault-scoped `EXPERIMENTAL_changes`. In this run there are 13 such receipts. Enumerate transactions from chunks.

**Ledger rule.** C equals the sum of record amounts and never decreases. S/F/U come from Transfer receipt outcomes only. The callback counters are a separate observation.

## 11. Evidence index (`evidence/g1/g1-20261029a/`)

| Path | Content |
| --- | --- |
| `node/binary.txt`, `node/status-at-start.json`, `node/genesis.json`, `node/config.json`, `node/home-files.sha256`, `node/client_config.json`, `node/init.log` | Node identity captured at start, before any application transaction |
| `node/status.json`, `node/genesis_config.json`, `node/protocol_config.json`, `node/client_config_at_test_start.json`, `node/h0_block.json` | Identity at test start |
| `txs/<label>.json` (74) | Raw `EXPERIMENTAL_tx_status(FINAL)` response for every transaction (includes receipt bodies) |
| `transactions.json` | Per-transaction summary: hash, nonce, receipts, predecessors, actions, statuses, blocks, graph closure |
| `checks.json` | All 115 checks with their supporting data |
| `state/final_cut_vault1.json` | Views, raw state decoded, keys, account and missing-account check, all at Q |
| `state/vault1_interval_scan.json` | C series, key/code/migration changes for heights 7531–7908 |
| `state/vault_mandate_after_init.json`, `state/vault_mandate_after_payments.json`, `state/vault2_mandate_final.json` | Mandate snapshots |
| `balance_log.json` | Vault balance vs C / seq at four points |
| `summary.json` | Accounts, policies, key transaction and receipt IDs, metrics |
| `retention.json`, `retention-test-run.log`, `restart-check.json` | §5.3 |
| `g1-test-run.log` | Console log of the evidence run |

## 12. Attempt registry (all retained)

| Run | Node chain_id / genesis | Artifact | Result |
| --- | --- | --- | --- |
| `dryrun-1` | `test-chain-CP0EB` / `Evzc5WCN…co5WS` | `771fbc09…` | **STOP** at check 19: expected `RequiresFullAccess`, observed `NotEnoughAllowance` (see §9) |
| `dryrun-2` | `test-chain-7a95k` / `4xiJKVfq…8LiR` | `771fbc09…` | 114 / 114 PASS; short-gap retention smoke test PASS |
| `dryrun-3` | `test-chain-W41mX` / `87kditEP…tHsxd` | `5b05246b…` (final) | 115 / 115 PASS |
| **`g1-20261029a`** | **`test-chain-4U2k3` / `kSN1GRyg…zCp5`** | **`5b05246b…`** | **115 / 115 PASS** (evidence run) |

Dry runs used separate nodes on ports 3131 / 24668. They are labelled DRYRUN and are not evidence for the gate.
