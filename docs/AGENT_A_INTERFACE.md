# G1 evidence integration handoff (Agent B)

This adapter is provisional until exercised against the protected artifact. It does not change SPEC-V1.1 or its acceptance criteria. No runner-provided roots or verdicts seed collection.

Agent A: expose a reviewer-controlled sandbox endpoint through loopback/SSH. The reviewer supplies the descriptor, node binary/config/genesis files, and compiled WASM through a channel independent of runner evidence. Keep owner/validator keys and admin RPC outside runner access. Do not copy keys into this tree.

Required node APIs: `status`, `EXPERIMENTAL_genesis_config`, `EXPERIMENTAL_protocol_config`, `block`, `chunk`, receipt-inclusive `EXPERIMENTAL_tx_status` with `wait_until=FINAL`, `query`, `EXPERIMENTAL_changes`. Missing or unsupported responses stop acquisition. No guessed alias fallback. This first adapter supports a bounded interval in one epoch with unchanged shard layout.

Record H0 **before vault and agent creation**, with a fresh empty application receipt frontier. Record Q after freeze, transfers, callbacks and refunds are finalized. Required outcome blocks must be in the H0..Q parent chain. A self-transaction with omitted first receipt body is INCONCLUSIVE; the adapter does not fabricate it. All roots are scanned, including setup and roots with receivers other than the vault.

The current strict view adapter expects:

```text
get_admissions({}) -> [
  { request_id: decimal-string, recipient: AccountId, amount: decimal-string,
    admission_sequence: integer, callback_status: string }, ...
]
get_mandate({}) -> {
  vault, owner, agent, chain_id, policy_hash: base58-32,
  budget: decimal-string, charged: decimal-string,
  accepted_count: integer, frozen: boolean, sequence: integer, ...
}
request_payment({ request_id, recipient, amount, policy_hash })
on_payment_result({ request_id })
```

Both view responses must carry node query metadata at exactly Q. If A uses another JSON layout for these specified fields, change only `one_cut()` / input extraction in B's tree after inspecting the actual artifact; add a recorded-response regression. Never infer a schema or outcome from runner labels. Extra fields are preserved in raw capture.

Bytecode creation must be one owner-to-vault receipt with exactly CreateAccount, Transfer, DeployContract, nonpayable `new`, and no keys. Every accepted `request_payment` must directly generate one matching native Transfer and one zero-deposit private callback. The native receipt's output data ID must be the callback's input data ID. Gas and balance refunds use the pinned runtime's actual system-receipt shape; unsupported variants stop rather than being relabeled.

For the real G1 handoff, provide **paths/endpoint and reviewer setup procedure, not a transaction-root list**:

- Node binary, exact status version, source/download provenance, effective config/genesis, genesis block hash, protocol config, H0 and Q hashes/heights, all shard IDs.
- Compiled protected WASM and SHA-256; source/dependency identity, exports/imports review, reserve/gas qualification.
- Public role/recipient account IDs, expected policy hash, B=5 NEAR, M=2 NEAR, K=2, eight restricted agent keys.
- Demonstrated runner isolation and retention after 2,000 produced blocks; bounded ingress closure and freeze procedure.
- One actual 1 NEAR success and 2 NEAR missing-account failure/principal refund. Keep all failed attempts.

The collector records raw RPC responses and reconstructs the root inventory itself. It also fetches vault raw state, account/code/key histories and final inventories. Raw state decoding, sequence/event reconciliation, runtime qualification and a fresh-instance rerun remain explicit G1 blockers; no overall PASS can be emitted by this initial implementation. The 1+8 controlled comparison and native-pending witness are not implemented before real G1 succeeds.
