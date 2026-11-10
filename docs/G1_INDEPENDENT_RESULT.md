# G1 independent integration result

| | |
| --- | --- |
| Date | 2026-11-10 (runs 13:50–14:00 UTC) |
| Branch | `integration/g1-recovery` (merge of `feat/g1-vault` and `feat/g1-evidence`, plus the repair commits) |
| Artifact | `artifacts/near_agent_vault.wasm`, 154,346 bytes, SHA-256 `c7c772635acea0938bd88450d02bcdb9215d9aa65fc407b4070459cd225dd768`, NEAR code hash `ESrXNXb3uKaeesbHe2ySHTMUtbwww4ZCKDWrMa3cLoB5` |
| Node | nearcore 2.13.4 sandbox (commit `44f7ae6c…`, protocol 86), binary SHA-256 `4e89fbc0…cba2c2`, one fresh node per run |
| Network | **Local sandbox only.** No testnet or mainnet transaction or deployment. |
| Responds to | Independent integration decision of 2026-10-31 (Agent E, research archive, not in this repository): NARROW, hold at G1 |

## Verdict

**G1: PASS on local-sandbox evidence, against the acceptance gate Agent E defined.** It passed on three fresh, reviewer-owned nodes (runs A, B and C).

The independent Codex review (`reports/G1_CODEX_REVIEW_2026-11-10.md`, of `7fa66e2`) returned **NARROW** with one isolation blocker, C1. The reviewer followed runner-planted symlinks when importing runner output, so a hostile runner could have had a reviewer-only file copied into public evidence. The review also flagged inaccurate denial wording. Both are fixed in `71a679c` (§Isolation) and covered by 11 regressions. **Run C is the fresh run on the fixed code that the review required.** Runs A and B used the pre-fix import path with the fixed, non-hostile workload: their chain evidence is unaffected, but only run C demonstrates the repaired file boundary.

The reviewer's collector was never given the failed payment's transaction hash. It rediscovered the entire genuine 2 NEAR failed-payment root by scanning chunks: the transaction, admission, failed native transfer, system principal refund, callback and gas refunds. The runner's presented bundle had omitted all of that, along with its rows, records and history, and had recomputed its checksums. The forged presentation gets **evidence FAIL (`OMITTED_ROOT`)**. The genuine presentation shows **zero differences**.

What this verdict does **not** cover:
- Agent E's runtime items: late-admission rollback, forced callback failure, K = 64 storage, insufficient liquidity and an executed expiry check.
- G2 concurrency comparisons.
- Any public network.
- Consensus-level proofs: the verifier trusts the reviewer's own node.
- Separate-machine isolation: the runner and reviewer share one host and one Unix user, separated by kernel namespaces.

## Runs

| | Run A | Run B |
| --- | --- | --- | --- |
| Run ID | `g1i-20261110T135044Z-a` | `g1i-20261110T135407Z-b` | `g1i-20261110T144905Z-c` (post-C1 fix) |
| Code commit | `91c4ce6` (clean tree) | `e783dac` (clean tree) | `71a679c` (clean tree) |
| Chain / genesis block | `test-chain-oJOg4` / `FEtCmJuu…HbgDN` | `test-chain-6J4eY` / `5W2M11Zu…Zv3FH` | `test-chain-d8AyA` / `94T7M5B5…kaggt` |
| H0 (before any vault/agent construction) | #21 `E4SBrXbY…9dwob` | #21 `A6HRGssy…KxC2K` | #19 `77S1Bj9x…CVc8B` |
| Q (after freeze; effects settled +20 blocks) | #110 `J1WVzaRY…HQc8S` | #110 `HwoYpHUi…Vhx8y` | #116 `DYK42upq…AQ6dE` |
| Policy hash (ten fields, includes chain ID) | `DfSCNzCN…ud2FC` | `5QkSjMiK…Zv3FH` | `12P3YxD3…Jn4m2` |
| Omitted root, recovered | `CsVXLYPw…H6Ri3` | `3sY8eamk…tzKH` | `DggYL4pr…LhZfd` |
| Recovered principal refund | `FPssFvNX…4Ef33c7` | `EyniEAcb…3zC4Rni` | `EPiZpmTn…X9HUjAZ` |
| Independent acquisition | 562 RPC calls, 953,518 bytes, 0.55 s | 562 RPC calls, 953,488 bytes, 0.60 s | 610 RPC calls, 986,292 bytes, 1.23 s |
| Whole run | 271 s | 271 s | 274 s |

Each run's evidence is in `evidence/g1-independent/<run>/`:

| File | What it holds |
| --- | --- |
| `reviewer-descriptor.json` | Reviewer-selected inputs. No transaction hashes. |
| `independent/result.json` | The verifier's result |
| `independent/rpc.jsonl.gz` | Every raw request and response the collector made, byte-exact |
| `runner/isolation.json` | Isolation probe output |
| `runner/runner-log.json` | Runner's own log. UNTRUSTED. |
| `runner/proxy-*.jsonl` | Filter proxy decisions |
| `runner/forged-presentation.json` | The forged presentation |
| `compare-genuine.json`, `compare-forged.json` | Offline comparisons |
| `mutations.json` | Mutation suite results |
| `retention-compare.json` | Retention comparison |
| `run-summary.json` | Run summary |

Development attempts `g1i-dev-01` and `g1i-dev-02` are retained with their causes in `evidence/g1-independent/ATTEMPTS.md`.

## Acceptance gate (Agent E §4), item by item

| Requirement | Result | Evidence |
| --- | --- | --- |
| Reviewer-controlled fresh node; H0 before construction with no unknown application work | **PASS** | `start-node.sh` with a fresh home per run. H0 is taken after setup reaches FINAL. The vault and agent are confirmed absent at H0 (typed `UNKNOWN_ACCOUNT` at H0). Every vault/agent state change in (H0, Q] maps to a discovered receipt. |
| Separate privileged setup from agent submission; runner has no validator keys, admin RPC or node files, including bypass paths | **PASS (same host, namespace isolation)** | See [Isolation](#isolation). |
| Protected WASM, or a documented, independently rebuilt equivalent | **PASS** | The source is unchanged. Only a build path remap was added, so the binary is a documented equivalent of `5b05246b`. Rebuilt byte-identically from a second checkout path. Capability inventory is identical to `5b05246b`. See [Artifact](#artifact). |
| Keyless deploy; eight restricted agent keys; B=5, M=2, K=2, future expiry; ID 1 pays 1 NEAR to an existing recipient; ID 2 pays 2 NEAR to a confirmed-absent allowlisted recipient | **PASS** | `reviewer/construct.json`, `reviewer/prepare.json` (the absent recipient is checked before the run), and the recovered ledger |
| Freeze; close ingress; drain; finalized Q; independent collection without a runner root list | **PASS** | The submit-mode proxy is stopped before the freeze. Q is the final head at freeze outcome +20 blocks. The descriptor has no hashes. Acquisition reads only the reviewer's node. |
| Block/chunk root inventory; complete bodies, outcomes and refunds; same-Q raw state, code, keys and history | **PASS** | 10 roots from chunk enumeration over (H0, Q]. Graph closure is complete. Q queries cover account, code, keys, raw state and views. Per-block `EXPERIMENTAL_changes` covers the vault and agent. |
| Exact reconciliation: count=2, C=3, S=1, F=2, U=0, headroom=2; 2 NEAR principal refund with no release of charge; native and callback observations kept distinct | **PASS** | `independent/result.json` → `recovery.ledger`, `principal_refunds`, `payments[].callback_observation` |
| Zero vault keys from construction to Q; one deployment; exact code; agent permission constraints; no unexplained changes or outflows; every effect at or before Q | **PASS** | History check (no vault key change; exactly one code change, at the creation block; every change cause mapped). One-cut checks at Q. `OUTCOME_OUTSIDE_CUT` would fail otherwise. |
| Rejected probes discoverable and correctly classified | **PASS** | 4 committed denials (DuplicateRequest, AboveMaxPerRequest, RecipientNotAllowed, RecordQuotaExhausted). 1 receipt failure (MalformedInput) with no committed data. 4 key abuses rejected before inclusion: the runner/proxy logs record them, and the verifier confirms none is on chain. |
| Delete ID 2's whole root, descendants and refund plus rows; recompute checksums; don't give the collector the hash; the collector must recover the actual failure and refund | **PASS** | `runner/forged-presentation.json` does not contain the hash (asserted). `compare-forged.json`: `OMITTED_ROOT` with 7 recovered receipts, payment class F (`AccountDoesNotExist`) and the principal refund receipt. |
| Forged presentation gets FAIL; recovered chain evidence labelled separately | **PASS** | `compare-forged.json` gives evidence FAIL. Safety, settlement and scenario come from the reviewer's capture. |
| Mutations of genesis/vault/artifact, amount/outcome, refund, produced block, record/index/sequence or mapping cannot yield PASS | **PASS (18/18)** | `mutations.json`: each tampers with the genuine recorded responses and replays them |
| Repeat on a fresh reviewer-controlled instance | **PASS** | Run B |
| Re-read after ≥ 2,000 produced blocks without fast-forward | **PASS** | `retention-compare.json`: every block, chunk, the 10 graphs, Q queries and history byte-identical (run A: final head 112 → 2,111; run B: 112 → 2,112). See the correction note in `ATTEMPTS.md`. |
| Record commits, tool/binary hashes, provenance, isolation, H0/freeze/Q, attempts, raw responses, RPC count/bytes/duration | **PASS** | `run-summary.json`, `node/`, `reviewer/`, `ATTEMPTS.md` |
| Time against the 8-hour acquisition budget | Integration merge to evidence commit: 13:34–14:00 UTC on Nov 10 (commit times), plus Agent A/B/E work on Oct 29–31; each run takes 4.5 min | git log |

## Isolation

The runner runs under `bwrap --unshare-all --die-with-parent --clearenv`. The reviewer-side filter proxy logs every request.

**File boundary, after the C1 fix (`71a679c`, demonstrated by run C):**
- Each run uses three separate sandbox invocations: the isolation probe, the workload, and the presentation.
- Each invocation gets a fresh reviewer-created proxy-socket directory, bound **read-only**. The probe asserts this.
- The probe's result is imported into reviewer storage **before** any untrusted workload starts.
- The descriptor reaches the runner through a fresh read-only input directory. Nothing is ever written into the runner-writable tree after the runner has run.
- Every runner output is imported only through `scripts/g1-independent/safe_import.py`:
  - descriptor-relative `O_NOFOLLOW` at every path component;
  - a regular file with a single link, bounded size;
  - strict JSON with secret-field rejection, then a schema check;
  - the bytes are stored by the reviewer and the path is never re-read.
- Regressions (`tests/evidence/test_runner_boundary.py`) plant final-component and intermediate-directory symlinks to a dummy reviewer-only file, both directly and from inside the production sandbox. The import refuses them.
- The proxy now also records the node's response to each submission, so run C's four pre-inclusion rejections are **reviewer-observed**, not only runner-reported.

| Check | Result |
| --- | --- |
| Visible filesystem | `/usr`, the runner binary, scripts, a read-only `packages/`, and the runner directory |
| Node RPC port (`127.0.0.1:<rpc>`) | `ConnectionRefused`. The sandbox has its own network namespace. |
| External network | Unreachable |
| Paths not visible | Node home, `validator_key.json`, owner key, reviewer directory, the user's home, the repository checkout |
| Admin methods (`sandbox_patch_state`, `sandbox_fast_forward`, `adv_produce_blocks`, `client_config`, `network_info`) | Refused by the filter. Codex additionally probed batch arrays, case and whitespace variants, unknown query types and oversized bodies: all refused (`reports/codex-review-20261110/filter-probes.json`). |
| Proxy socket directory | Read-only inside the sandbox (run C) |
| Methods the runner actually used | `send_tx`, `EXPERIMENTAL_tx_status`, `block`, `query` (view types only) |
| Runner credentials | Eight `FunctionCall` keys for `request_payment` on the vault |

Limits:
- The sandbox shares one kernel, one host and one Unix UID with the reviewer.
- The reviewer and runner programs were written by the same author. The independence is in capability separation, not organisational separation.
- The runner's presentation capture was taken through the read-only filter after the freeze.

## Verifier repair (Agent E §3, B's adapter defects)

All of these are implemented in `packages/verifier` and `packages/collector`, with regressions on actual recorded responses (`tests/evidence/test_real_rpc.py`).

| Defect | Fix |
| --- | --- |
| `view_code` returns `hash`, not `code_hash` | `one_cut` binds the code bytes and `hash` to the artifact. `view_account.code_hash` is checked separately. |
| `seq` / `admission_seq` are decimal strings; count/index fields are JSON numbers | Strict canonical decimal parsing for the strings; `type is int` for `accepted_count`, `recipient_index` and `max_accepted_requests` |
| `DeployContract.code` in receipt views is the 32-byte digest | Compared directly with the artifact SHA-256. `EXPERIMENTAL_changes` carries full code bytes; both representations are pinned. |
| Arguments parsed before checking Failure | Failure is classified first. A failed receipt may not dispatch from the vault and may not commit data (`FAILED_RECEIPT_COMMITTED_STATE`). Its arguments are never parsed. |
| No raw-state decoding or policy recomputation | Independent Borsh decode of STATE, `r‖id`, `i‖pos`. The ten-field policy body is compared byte-for-byte with the reviewer's descriptor and its hash recomputed. Records, index, views and request digests are reconciled. |
| No event/sequence reconciliation | Committed events must be exactly seq 0..final, in execution order, each tied to its receipt, with running C consistent |
| Intermediate invariant only from final arithmetic | Every STATE write in (H0, Q] is decoded: C, seq and count are monotone; policy bytes never change; records and index are immutable apart from Pending→terminal; no deletions |
| Ancestry walk spent the budget on head→Q | Q must be canonical at its height under the final head; the walk then goes Q→H0 only |
| Chunk-by-hash `height_included` (found on the first real run) | 2.13.4 returns `0`. The chunk is bound to the block's header via hash, shard and `height_created`. |

PASS verdicts are emitted only for LIVE acquisitions. REPLAY and SYNTHETIC sources cap at INCONCLUSIVE while FAIL still propagates.

## Artifact

The previously committed `5b05246b` artifact embeds `/home/<user>/.rustup/toolchains/1.93.0-…/lib/rustlib/src/rust/library/...` panic paths. Rustc rewrites std's virtual `/rustc/<commit>/` prefix to a locally installed `rust-src`, which the build script's existing remaps did not cover. Its bytes therefore depend on the builder's home and on whether `rust-src` is installed.

`scripts/build-contract.sh` now remaps `$(rustc --print sysroot)/lib/rustlib/src/rust` to `/rustc/254b59607d4417e9dffbc307138ae5c86280fe4c`. The new artifact `c7c77263…`:
- contains no home paths;
- passes the fail-closed capability gate;
- has the same 24 imports, the same 8 callable exports, and identical globals and section IDs as `5b05246b`;
- rebuilds byte-identically from a second checkout path.

`5b05246b` is kept in `artifacts/legacy/` because `evidence/g1/g1-20261029a` refers to it. Cross-machine rebuild (added 2026-11-10): verified on a second machine: GitHub Actions `ci` run 42850602121 (ubuntu-24.04, fresh Rust 1.93.0 and cargo-near 0.22.0, different paths) rebuilt `c7c77263…dd768` byte-identically and passed the capability gate.

## Tests

| Suite | Command | Result |
| --- | --- | --- |
| Contract unit tests (SPEC vectors, parser, storage) | `cargo test -p near-agent-vault --locked` | 12/12 |
| Harness encoder | `cargo test -p g1-sandbox-tests --locked --lib` | 1/1 |
| Evidence suite | `python3 -m unittest discover -s tests/evidence -t .` | 61/61: 11 C1 runner-boundary regressions (3 end-to-end through the production sandbox), 43 synthetic (fake oracle) and 7 on actual recorded 2.13.4 responses (Agent A's Oct 29 graphs, plus full replay of runs A/B: exact ledger, whole-root omission, 18 mutations) |
| Independent G1 runs | `python3 scripts/g1-independent/run_g1.py <run>` | 3/3 PASS (above), plus an uncommitted clean-clone run on `f2f8cce` and Codex's review run `review-codex-20261110-b` on `7fa66e2` |

## Interface errata (requested by Agent E)

- Agent A's interface (`G1_CONTRACT_RESULT.md` §10) says "the first 9 STATE fields Borsh-encode exactly the policy body". It is the first **ten** policy fields, including K (`max_accepted_requests`, u32), as SPEC-V1.1 §3 states.
- "Every integer is a canonical decimal string" holds for amounts, IDs, `seq` and `admission_seq`. `accepted_count`, `max_accepted_requests` and `recipient_index` are JSON numbers.
- `docs/AGENT_A_INTERFACE.md` (B's provisional adapter: integer `sequence`/`admission_sequence`, `view_code.code_hash`) is superseded by this document.

## Still open

R3 late-failure atomicity (FAULT builds), R4 forced callback failure on chain, K = 64 storage, InsufficientLiquidity, executed expiry, G2 concurrency comparisons with a native-pending witness and testnet. (Cross-machine artifact rebuild has since passed in CI.) None of these blocks the G1 claim as scoped. Each one blocks a stronger claim.
