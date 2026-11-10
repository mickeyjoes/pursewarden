# Independent Codex G1 review — 2026-11-10

## Decision: NARROW

Reviewed `integration/g1-recovery` at **`7fa66e20a9f22eaee0469fa783fb966e759a3612`**, against `docs/CODEX_REVIEW_HANDOFF.md` and the prior independent decision's §4 acceptance gate. The starting tree was clean. Contract/build-input changes against `c9da90c` are empty.

The recorded execution, independent omission recovery and protected artifact are supported. However, the full isolation claim needs **one bounded repair: safely import files from the untrusted runner directory**. A runner-controlled symlink causes the reviewer to copy a reviewer-only file into public evidence. This is distinct from the disclosed same-host/same-UID limitation.

Keep the result scoped to the demonstrated fixed workload until that repair and its regression pass. This review found no executed cap violation, charge decrease or duplicate dispatch, and does not call for changing the vault contract. No implementation, existing evidence or public wording was edited; only this report, review reproductions and new review-run evidence were added. Nothing was pushed, merged, deployed externally or published.

## High priority — C1: reviewer follows runner symlinks into private files

**Impact:** a malicious runner can induce the reviewer to export a file outside the sandbox, including its known owner-key pathname, into the public evidence directory.

Locations at the reviewed revision:

- `scripts/g1-independent/run_g1.py:112`: the runner directory is mounted writable as `/runner`.
- `scripts/g1-independent/run_g1.py:215`: the isolation probe receives reviewer/node/owner-key host pathnames.
- `scripts/g1-independent/run_g1.py:221` and `:222`: `shutil.copy` follows runner-controlled output symlinks when copying isolation and runner logs into public evidence.
- `scripts/g1-independent/run_g1.py:223` and `:289`: subsequent reviewer-side reads also follow paths in that directory.

The namespace hides the target correctly. That does not prevent creating an absolute symlink whose target resolves later in the reviewer's namespace. For example, after writing a legitimate isolation result, an adversarial workload can replace `out/runner-log.json` with a symlink to the owner-key pathname. The reviewer copies its bytes to `evidence/g1-independent/<run>/runner/runner-log.json`. That copy is not checked against a runner-log schema before export. An intermediate `out` or `presentation` directory can also be a symlink, so checking only the final component is insufficient.

Reproduction:

```bash
python3 reports/codex-review-20261110/reproduce_output_boundary.py
```

The reproduction calls the **production `bwrap` helper**, verifies that a dummy reviewer-only `owner.key.json` is absent inside the runner, plants the symlink inside that sandbox, then performs the same reviewer-side `shutil.copy`. Result:

```json
{
  "production_bwrap_used": true,
  "private_path_absent_inside_runner": true,
  "runner_planted_symlink": true,
  "reviewer_copy_disclosed_dummy_private_file": true,
  "used_real_keys": false
}
```

The retained observation is `reports/codex-review-20261110/output-boundary.json`. No real owner, validator or workstation secret was read or copied. The demonstration proves a privileged file-export flaw; it does **not** demonstrate that the running sandbox directly reads a key or reaches the admin RPC. The supplied fixed workload did not plant such a link, so this finding does not imply the committed runs leaked keys.

**Required fix:** import bounded regular files through trusted directory descriptors, rejecting symlinks at every component (for example, descriptor-relative no-follow opens, with regular-file checks). Copy from the already-open descriptor into reviewer-owned storage, validate the expected JSON schema, then use that stored copy. Apply this to all reads/copies from the runner tree. Preserve isolation-probe results outside runner-writable storage before starting the untrusted workload. Include final-component and intermediate-directory symlink regressions using dummy secrets, and repeat the fresh G1 run. A weaker public claim can describe the supplied workload's direct-access probes, but must not claim a robust arbitrary-runner file boundary before this repair.

## Public wording corrections

`README.md:147` says rejected requests have “no transfer or state effect”; `web/src/pages.tsx:79` similarly says “denied with no effect.” These statements are false for committed denials: `deny` increments `seq` (`contracts/vault/src/lib.rs:506`) and the wrapper persists STATE. Independent replay of **both** runs finds one committed data write for each of the four denials. The malformed-input receipt has no committed vault data write; gas/nonce/account effects are a separate matter.

Suggested wording: **“Denied requests make no transfer and do not increase C or consume an admission slot; denials advance the audit sequence. Malformed-input failures commit no vault data.”** This is a presentation correction, not an additional contract-safety blocker.

The K=2 refund-reuse attempt is denied by **RecordQuotaExhausted** with `C + amount = B`; it is not an executed BudgetExceeded test. The README scenario table correctly states this. Keep the aggregate “9 attacks stopped” adjacent to its breakdown: four committed denials, one receipt failure, four runner-reported pre-inclusion rejections. Prefer “9 rejected probes” in the headline to avoid implying nine independently observed on-chain attacks.

## Validation and scope findings

| Check | Observation |
| --- | --- |
| Python evidence suite | **50/50 OK** after socket access was enabled. Initial restricted execution had one environment error opening the test HTTP socket; no assertion failure. |
| Contract tests | **12/12 OK** with `cargo +1.93.0 test -p near-agent-vault --locked`. |
| Artifact command | `scripts/build-contract.sh` passed the capability gate and `git diff --exit-code artifacts/` was empty. |
| Actual recompilation | Exported reviewed source/build inputs to `/tmp/near-codex-review-rebuild`, reused the build-cache directory, and ran the same script. Cargo recompiled the vault and dependencies and ran wasm-opt. SHA-256 again **`c7c772635acea0938bd88450d02bcdb9215d9aa65fc407b4070459cd225dd768`**, 154,346 bytes, capability gate PASS. This remains a same-machine check. |
| Actor build | `cargo +1.93.0 build -p g1-sandbox-tests --locked --bin g1_actor` succeeded. |
| Committed raw-response mutations | **18/18 applied and rejected**; output `/tmp/near-codex-review-mut.json`. |
| Web data | In-memory re-derivation of every run with `build_run` exactly equals committed `web/public/bundle.json`. No web source or bundle was rewritten. |
| Additional filter probes | Batch arrays, admin methods, case/whitespace variants, unknown query type, array query params and oversized declared bodies were refused. Only the allowed read reached a dummy upstream. See `reports/codex-review-20261110/filter-probes.json`. |
| Additional namespace probe | Host abstract Unix socket connection refused; only three sandbox PIDs visible; host home absent. See `reports/codex-review-20261110/namespace-probes.json`. |

### Discovery and finality

For this fresh, reviewer-orchestrated scenario, H0 follows FINAL setup graphs, precedes vault/agent construction, and both accounts are checked absent with typed errors at H0. Newly included chunks seed roots without runner hashes. Receipt closure, same-cut outcomes and `STATE_CAUSE_UNMAPPED` reject unexplained watched-account effects. Delayed descendants of a discovered root must also close at or before Q; otherwise acquisition is inconclusive. This is not a general completeness proof for arbitrary pre-existing accounts or queued application work before H0.

Checking canonical Q by height under a final head is adequate under the declared trusted-node, single-epoch sandbox assumption. The ancestor walk still binds Q to H0. This review did not find a live completeness counterexample within that scenario.

### Verifier and mutations

Every mutation was rejected by a relevant semantic check; none relied on an unrelated malformed-schema crash. The outcome mutation is rejected by `FAKE_PRINCIPAL_REFUND`, because it changes the native transfer to success while retaining its failure refund. That is a pertinent inconsistency. Principal-refund removal returns **INCONCLUSIVE**, not FAIL; that is sufficient to reject a complete PASS and is correctly distinguished from proved falsity. Node-side chunk omission hits `UNMATCHED_ADMISSIONS` before the later unmapped-history guard; it still prevents acceptance. These single mutations do not establish correctness against all coordinated mutations.

`failure_summary` string matching affects labels and scenario coverage, but native safety/settlement classification uses typed success/failure outcomes and receipt/refund linkage. One event per receipt and the permitted view-call/deposit shapes are conservative restrictions of this adapter. `compare_bundle` excludes changing head/status details; authoritative state, history, blocks/chunks and graphs are compared, and safety is computed from the independent capture rather than imported from the runner.

### Contract and orchestration

Source inspection confirms policy/freeze/expiry/duplicate/allowlist/amount/budget/quota/liquidity admission ordering. Charging and retained-record writes precede promise construction within the receipt. The callback writes status/counters/sequence and does not assign C. Repeated freeze returns before changing fields; a wrapper STATE rewrite can still occur. Reserve additions/multiplications are checked, and liquidity requires `balance >= amount + reserve_total`. No additional runtime claim follows for the explicitly unexecuted cases.

Submission ingress is terminated before owner freeze. All inventoried graph outcomes must lie in the selected ancestry. Q is selected after freeze outcomes plus 20 blocks. The existing `retention-compare.json` comparison correctly excludes the live head and nonidentity status fields while retaining all historical blocks, chunks, graphs, queries and history. The old status-comparison mistake is disclosed rather than concealed.

### Answers to the handoff questions

1. **NARROW:** the fixed-workload sandbox evidence is supported, but repair C1 before claiming the complete adversarial isolation gate is satisfied. No vault change is requested.
2. No incidental schema rejection among the 18 mutations; the caveats above explain which verdicts are FAIL versus INCONCLUSIVE.
3. “Independent verifier” is reasonable if immediately defined as **independent acquisition from the runner's report**, with the same-author/same-host disclosure kept visible. It must not imply an external audit or organizational independence.
4. The committed web bundle faithfully reproduces the recorded numbers checked here. Some provenance fields and live verdicts come from reviewer setup/run records rather than being recomputed by `analyze`; the four pre-inclusion errors come from the runner log. The bundle builder does not independently authenticate those error bodies against proxy logs, which record decisions/byte counts rather than response bodies. Keep their runner-reported labels and correct the no-state-effect wording.

## Fresh review-run record

The new run is `review-codex-20261110-b`, at the reviewed revision. Private node files live under `/tmp/near-codex-review-tools/g1-independent/`; public evidence lives under `evidence/g1-independent/review-codex-20261110-b/`. It uses the existing pinned sandbox binary and a fresh node home. There are no public-network transactions.

Initial run `review-codex-20261110` was stopped during startup after the original execution sandbox prevented local network sockets. Its startup evidence remains under the matching evidence directory; it is not counted as a gate run. The new run was started after the user's permission-profile change.

| Fresh review run | Result |
| --- | --- |
| Chain / genesis | `test-chain-QDgMG` / `GoQDHGbH4n95W6q5ZhuYz2DCQpCX2TLMTLMqdqNn56ZA` |
| H0 / Q | #20 / #109 |
| Duration | 272.3 seconds |
| Independent acquisition | 562 RPC responses; safety, settlement, evidence and scenario coverage PASS; no issues |
| Reconciled ledger | count=2, C=3, S=1, F=2, U=0, headroom=2 NEAR |
| Genuine presentation | Zero differences |
| Forged presentation | Evidence FAIL; omitted root `YiPkERR77qgPEUqiEXeQg9m6e3FKkWiM79S6mkgLUxQ` recovered with seven receipts, native AccountDoesNotExist and the successful 2 NEAR principal refund |
| Mutation suite | 18/18 applied and rejected |
| Retention | 2,000 produced blocks after Q; all historical fields identical; retention acquisition all-PASS |
| Separate retention comparison | `retention-compare.json`: all identical, 10/10 graphs identical; acquisition final heads #111 and #2111 |
| Cleanup | Review node stopped; no review-run process left running; private history retained locally |

These fresh results corroborate the supplied workload. They do not repair or negate C1, which was demonstrated separately with a hostile output symlink and a dummy private file.
