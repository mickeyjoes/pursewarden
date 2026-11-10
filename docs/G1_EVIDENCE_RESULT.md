# G1 evidence result — Agent B — 2026-10-29

**Verdict: NARROW / G1 INCONCLUSIVE. Stop before the 1+8 comparison harness.** The collector/verifier is executable and its synthetic adversarial regressions work. No genuine protected-contract sandbox execution, independent node provenance package, 2,000-produced-block retention proof, isolation demonstration or fresh-instance rerun was available. Synthetic output is not G1 evidence. No contract exploit or other provider's vulnerability is claimed.

Worktree: `/home/mickey/Dev/Hackathons/NEAR/near-agent-vault-evidence`, branch `feat/g1-evidence`, common base `2ca4b51`. Obtain the exact implementation commit with `git rev-parse feat/g1-evidence`. Only this worktree was written. The research archive, Agent A's branch and acceptance criteria were left unchanged. No pushes, merges, deployments, wallets, public-chain requests, paid services or signing occurred.

## Implemented behavior

`packages/collector/` is a Python standard-library-only read-only RPC collector. Reviewer CLI arguments select the endpoint, expected descriptor and local provenance files. Presented runner JSON cannot change any of them. It hashes the supplied node binary/config/genesis and WASM; compares RPC chain ID, exact version object, genesis configuration digest and genesis block hash; pins protocol configuration and all shard IDs.

The collector walks finalized head → Q → H0 by parent hashes, permits skipped heights, checks every shard and chunk inclusion mask, skips carried chunks and discovers **every transaction root** from newly included chunks. There is no expected root count or runner-root discovery seed. It requests receipt-inclusive `EXPERIMENTAL_tx_status(..., FINAL)` for all discovered roots, including setup and roots whose direct receiver is not the vault. It captures final account/code/key inventories, raw vault state, admissions and mandate at exactly Q, plus account/key/code/data history across the produced blocks.

`packages/verifier/` checks unique IDs, graph reachability, child/outcome/body closure, transaction/first-receipt linkage, predecessor/executor linkage and outcome block ancestry. Unsupported local-first-receipt reconstruction, protocol features, schema or missing evidence stop verification. It validates keyless construction, exact WASM, empty vault keys, eight restricted code-free agent keys, observed authority/code history and state-change origins. It maps actual Transfer actions to request inputs and retained records; matches callback data dependencies; separately derives native success/failure, principal refunds and gas refunds. A successful native transfer remains S when its callback fails. Missing evidence never becomes F or a zero-U ledger.

Runner bundle checksums and verdicts are ignored as trust anchors. The verifier compares the independently fetched root/graph sets and immutable capture fields. Demonstrated omission or contradiction yields evidence FAIL. Recovery is returned separately and never silently blesses the forged bundle.

The CLI has explicit `sandbox`, `testnet`, `mainnet` modes and only read methods. Sandbox RPC must be loopback (SSH forwarding is supported). Public networks support `--inspect-only`; public completeness is explicitly unsupported. New output directories preserve exact response bytes, requests, endpoint, acquisition timestamps, metrics and structured results. Limits: 300 seconds, 10 seconds/request, 32 MiB/response, 256 MiB total, bounded interval/roots, no automatic retry or endpoint/alias fallback. No private-key-loading or transaction-submission code exists.

## Tests and raw artifacts

The final suite runs on `root@85.10.198.17` under a 512 MiB address-space limit, with Python 3.12.3 on Linux x86_64. No dependencies or services were installed. Its loopback HTTP server is a **fake RPC oracle**, not a NEAR sandbox, and is shut down after each test. Node/runtime performance is not measured by these tests.

- [Final test output](../reports/evidence/test-run.log): **42 tests passed**. Tests cover complete synthetic acquisition, whole-root omission, rehashed runner rows/state, wrong chain/genesis/version/WASM/account, pruned blocks/chunks/shards/history, missing bodies/outcomes, fake refunds, gas/principal distinction, altered outcomes/IDs, duplicate identifiers, finality/cut mismatch, callback failure/dependency, transient keys, unknown state origins, malformed runner JSON, canonical numbers and read-only RPC restrictions. A typed historical NO_CONTRACT_CODE result for the agent is recorded as an error observation, never fabricated as an empty receipt/code body.
- [Final synthetic results](../reports/evidence/synthetic-final-20261029/results.SYNTHETIC.json) and [independent capture](../reports/evidence/synthetic-final-20261029/independent-capture.SYNTHETIC.json).
- [Forged bundle](../reports/evidence/synthetic-final-20261029/forged-root-omission.SYNTHETIC.json): request 2's entire root, admission, transfer, callback, gas/principal refund descendants, chunk transaction entry and runner-side retained rows are removed; checksums are recomputed. The missing root hash is absent from the forged JSON. The collector is not told it; its own chunk scan recovers it and its refund.
- [Exact baseline RPC bytes](../reports/evidence/synthetic-final-20261029/baseline-rpc.jsonl), [omission-recovery RPC bytes](../reports/evidence/synthetic-final-20261029/omission-rpc.jsonl), [file digests](../reports/evidence/synthetic-final-20261029/sha256.json). Digests establish artifact consistency only.
- [Earlier synthetic run](../reports/evidence/synthetic-20261029/results.SYNTHETIC.json) and [test attempt history](../reports/evidence/TEST_ATTEMPTS.md) are retained.
- [Actual CLI missing-provenance refusal](../reports/evidence/cli-missing-provenance/result.json): exit 2, `PROVENANCE_MISSING: wasm`, zero RPC requests.

The synthetic oracle has four roots over heights 10..20 (height 11 skipped), two shards and a carried chunk. Its modeled C=3, S=1, F=2, U=0, headroom=2 NEAR is arithmetic over generated objects. The independent acquisition discovers all four roots; the omission mutation recovers the missing payment root and all five receipts. This is **software regression coverage**, not executed payments. Both baseline and omission acquisitions use 83 RPC requests. Exact byte/time measurements are in each result; they describe fake RPC transport only.

| Negative case | Observed treatment |
| --- | --- |
| Whole legitimate root and every descendant removed, all runner hashes recomputed | Evidence FAIL (`OMITTED_ROOT`); independent graph/payment/refund recovered |
| Outcome changed in presented bundle and rehashed | Evidence FAIL (`TAMPERED_GRAPH`); independent failure preserved |
| Wrong chain, same chain ID with another genesis, different node version/WASM | Evidence FAIL |
| Fake refund amount or gas refund used as principal refund | FAIL or INCONCLUSIVE; never accepted as completed principal refund |
| Pruned block/chunk/shard/history, missing outcome/body, effect after Q | INCONCLUSIVE; no complete ledger emitted |
| Signing/admin method, non-loopback sandbox, public completeness attempt | Rejected before sending or collecting |

`chain_evidence_checks: PASS` names only this implementation's internal checks over its selected source. It is **not** a G1, enforcement, network, settlement or marketing badge. The four SPEC verdict dimensions remain INCONCLUSIVE on the synthetic baseline. A forged presentation gets evidence FAIL. The initial implementation deliberately has no code path that emits an overall G1 PASS or CLI exit 0: exit 1 is FAIL; exit 2 is INCONCLUSIVE.

## Reproduce without changing Agent A's worktree

Local control-plane commands (tests and fixture server run remotely):

```bash
cd /home/mickey/Dev/Hackathons/NEAR/near-agent-vault-evidence
ssh root@85.10.198.17 'free -h; swapon --show; df -h /'
ssh root@85.10.198.17 'mkdir -p /tmp/near-g1-evidence-b-review'
rsync -a --exclude=.git --exclude=__pycache__ --exclude=.work \
  ./ root@85.10.198.17:/tmp/near-g1-evidence-b-review/
ssh root@85.10.198.17 \
  'cd /tmp/near-g1-evidence-b-review && ulimit -v 524288 && timeout 60s python3 -m unittest discover -s tests/evidence -t . -v'
ssh root@85.10.198.17 \
  'cd /tmp/near-g1-evidence-b-review && ulimit -v 524288 && timeout 60s python3 -m tests.evidence.export --out .work/reviewer-synthetic-run-1'
```

Each export output directory must be new. The tests use no third-party packages. Check remote capacity before execution; do not fall back to local tests. The task-owned development directory was `/tmp/near-g1-evidence-b-20261029`; no containers, node process, packages or persistent listeners were created by B.

Real acquisition command, **not executed here**, on the reviewer-controlled remote host after independently obtaining the required runtime package:

```bash
python3 -m packages.verifier \
  --network sandbox --rpc http://127.0.0.1:3030 \
  --descriptor /reviewer/g1/reviewer-descriptor.json \
  --wasm /reviewer/g1/protected.wasm \
  --node-binary /reviewer/g1/near-sandbox \
  --node-config /reviewer/g1/config.json \
  --genesis-file /reviewer/g1/genesis.json \
  --out .work/g1-independent-run-1
```

To compare a runner presentation, repeat with a **new** output directory and `--presented /untrusted/runner-capture.json`. The endpoint and descriptor are still reviewer inputs. Do not derive either from that file. The final Q is fixed; any later outcomes require a newly selected Q and all views/history to be reacquired. Use the same command with `--network testnet` or `--network mainnet`, the correct independent descriptor/RPC and `--inspect-only` for non-signing inspection. No public completeness claim follows.

Descriptor schema/strict view layout and exact required node methods are documented in [the Agent A interface](AGENT_A_INTERFACE.md). The committed synthetic descriptor demonstrates field encoding only; its fake digests, empty WASM and chain identity must never be used for a real run. Real digests require the actual independently obtained files and canonical RPC configurations.

## Precise blockers and Agent E handoff

1. **Runtime input unavailable:** at the last handoff check, Agent A's tree had contract scaffolding and no `docs/G1_CONTRACT_RESULT.md`, sandbox RPC endpoint, compiled protected WASM, node binary/config/genesis identity, H0/Q or runtime evidence. B did not start or impersonate A's node. Supply the reviewer-owned runtime package described in `AGENT_A_INTERFACE.md`; then probe these exact APIs without supplying transaction roots.
2. **Adapter qualification incomplete:** the strict view/input JSON adapter is provisional until compared to A's actual artifact. Raw vault state is captured but not decoded; complete event/sequence reconciliation and independent canonical policy recomputation remain unimplemented. Runtime/source/binary correspondence, WASM capabilities, reserve/gas measurements, 2,000-block retention, runner/admin isolation, initial empty frontier and fresh-instance rerun remain unproved. These block G1 PASS even if all current chain checks succeed. Merely changing verdict strings is not a fix.
3. **No genuine omission mutation yet:** repeat the whole-root attack on genuinely executed protected-contract evidence and demonstrate recovery from the independent node. Unit tests over generated JSON do not meet that acceptance criterion.
4. **Comparison/witness deferred:** no vulnerable/protected/generous 1+8 harness or native-pending witness was prepared. This follows the required real-G1-first gate; concurrent RPC calls would not satisfy the witness.

Agent E should review only this branch's diff against `2ca4b51`, replay the synthetic tests as software checks, and retain **NARROW / runtime G1 INCONCLUSIVE**. Do not approve G2, public claims or UI on this package. After A supplies real provenance, integrate the minimal view adapter, close the named missing checks, run the actual two-payment acquisition/mutations and repeat on a fresh instance within the shared G1 budget. B proposes no merge; E/owner controls integration. No branch was pushed or merged.

Confidence: high that the exercised omission/mutation logic behaves as recorded against the synthetic oracle; unmeasured against the protected artifact or a genuine node. No testnet/mainnet enforcement confidence is claimed.
