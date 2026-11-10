# Focused post-fix Codex review — 2026-11-10

## Decision: NARROW

Reviewed `feat/g2-concurrency` at **`2b4a25d99509629a1741fa423ebe0cf4c66bc704`**, against G1 baseline `d948613` and `docs/CODEX_POSTFIX_REVIEW_HANDOFF.md`. The starting checkout was clean. Current G2 evidence is C/D at `7d66b4c`; A/B are explicitly superseded.

**The C1 repair and recorded G2 results are supported. One bounded blocker remains: the witness helper treats a lower bound on settled spend as an exact amount when another transfer succeeds in the denial's block.** Fix that inference or explicitly refuse the ambiguous case before treating the helper as a general proof of the settled-only counterfactual. No vault change is requested.

This issue does **not** invalidate the six witnesses in either current committed run or the fresh review run: none has a successful earlier payment executing in its denial block. No protected-vault overspend, decreasing charge, or repeated dispatch was demonstrated. The verdict concerns the evidence helper's inference outside those particular timings.

## P2 — W1: same-block successes can produce a false settled-only admission claim

Locations: `packages/verifier/__init__.py:647`, `:655`–`:657`; the corresponding unconditional interpretation is in `docs/G2_RESULT.md:67`–`:68`.

The strict `transfer_execution_height > denial_height` predicate is sound positive evidence that an earlier native transfer had not executed. However, successful transfers with execution height equal to the denial height are excluded from **both** the pending set and settled sum. That makes `settled_before_denial` a lower bound. Using it to assert `settled_only_check_would_admit = true` can be wrong for an execution order in which the same-block success preceded the denial.

Concrete helper counterexample, in NEAR, with B = 5 and requested amount = 2:

| Earlier admission | Amount | Admission block | Successful transfer block |
| --- | --- | --- | --- |
| ID 1, seq 1 | 2 | 8 | 9 |
| ID 2, seq 2 | 2 | 9 | 10 |
| ID 3, seq 4 | 1 | 10 | 11 |

The denial executes in block 10 at seq 5, with C = 5. Seq 3 can be ID 1's callback. The production helper reports settled = 2, one pending transfer, `settled_only_check_would_admit: true`, and `witness: true`. If ID 2's transfer executed before the denial in block 10, actual native settled spend is 4 and **4 + 2 > 5**. Block heights supplied to this helper do not distinguish that order from the reverse one.

Reproduce from the repository root:

```bash
python3 reports/codex-postfix-20261110/reproduce_pending_witness.py
```

The retained output is [`pending-witness-counterexample.json`](codex-postfix-20261110/pending-witness-counterexample.json). This is a **synthetic production-helper counterexample**, not an executed sandbox trace or a contract-safety counterexample. It demonstrates that the inputs cannot support the unconditional inference. The existing same-block test covers a same-block transfer alone, which leaves the pending set empty; it misses the mixed same-block-success plus future-transfer case.

**Bounded fix:** keep the strict pending predicate. Calculate settled bounds for successful earlier admissions:

```python
settled_min = sum(amount(p) for p in earlier_successes if height(p) < denial_height)
settled_max = sum(amount(p) for p in earlier_successes if height(p) <= denial_height)
would_admit = (True if settled_max + amount_requested <= budget
               else False if settled_min + amount_requested > budget
               else None)  # same-block ordering is needed
witness = bool(pending) and would_admit is True
```

Label the lower bound accurately and expose ambiguity instead of reporting an exact settled amount. A simpler safe restriction is to refuse the counterfactual whenever any earlier successful transfer shares the denial block. Add the mixed-case regression above and retain the C/D replay expectations. Update the witness definition in `docs/G2_RESULT.md` accordingly. This repair is described, **not applied**, because this handoff authorizes review only.

The fixture updates its own settled counter in callbacks. That counter can lag native settlement; computing a general counterfactual for that specific callback-based design requires its callback ordering as well. The present C/D workload is unambiguous because the initial payment completed before the burst and both admitted burst transfers execute strictly later than all six denials.

## Review findings on the requested areas

| Area | Assessment |
| --- | --- |
| C1 import completeness | G1 probe, workload log, and presentation imports all use `import_json` / `read_untrusted`; G2 probe and workload do likewise. G2's `policy-hashes.json` write happens before any sandbox invocation. No remaining ordinary reviewer read or write into a previously runner-writable tree was found along these phases. |
| Descriptor-relative walk | Every runner-controlled component is opened with `O_NOFOLLOW`; intermediate directory descriptors and the final file descriptor remain pinned. `/proc/self/fd` symlinks are rejected. Hard links and nonregular files are rejected. The read loop separately enforces the size bound if the file grows. Mutating a runner-owned file's contents can change the untrusted JSON, but does not redirect its open descriptor into a reviewer-only inode. |
| Mounts and phase separation | Namespace-local mount changes do not alter the reviewer's mount namespace. The runner cannot name hidden reviewer files as bind sources. Socket directories are read-only, phase outputs are fresh, and trusted probe results are imported before the workload. Fresh presentation inputs and outputs avoid the prior write-through-symlink path. No bind-mount escape was demonstrated; this remains assessment within the stated namespace boundary. |
| Pending predicate | Strictly later native execution is sufficient for the claimed unresolved-native-transfer observation. Same-block execution is correctly excluded as affirmative pending evidence. The additional settled-only admission inference needs W1's repair. |
| Concurrency scope | The code pre-signs with eight separate FC keys, then submits through concurrent tasks. `docs/G2_RESULT.md` and the README explicitly disclose sequential receipt execution, one shard and one validator. The captured burst landing in one block supports the demonstrated admission-versus-settlement overlap. It does not demonstrate simultaneous contract execution. |
| Control audit | `control_audit` counts single native Transfer receipts whose predecessor is the fixture vault, using closed graphs discovered by independent chunk scanning; successful outcomes determine delivered principal. It checks the fixture's code digest and absence of access keys. I additionally checked the independently captured initializer in C/D and the review run: B = 5 and M = 2 match the reviewer descriptor. All nine counted transfers succeeded. Raw fixture-storage decoding is unnecessary for this bounded delivered-principal comparison; the contract view is supplemental. |
| Collector refactor | The identity, window and discovery operations retain their order and checks. The additional descriptor field defaults to the original eight agent keys; G2 supplies nine. All three G1 bundle run objects, including replay capture digests, have identical canonical bytes to `d948613`. Their replays reconcile. |
| UI honesty | `#/verify` explicitly identifies the forged bundle as generated by the test orchestrator and the 18 tamperings as deliberate regression inputs. The fixture is consistently project-owned and sandbox-only. `#/lab` displays zero spendable authority for every supplied run because K is exhausted, with frozen-at-Q wording. Its helper does not inspect freeze state, so it must not be reused for a frozen run with available slots without adding that state; this does not misstate the current displayed runs. |
| CI | `ci.yml` grants `contents: read`, has no deployment steps or explicit secrets, and performs no public-chain experiment. The exact `cargo-near 0.22.0 --no-default-features` installation and byte-identical protected rebuild have already succeeded on GitHub's Ubuntu runner; see the independently fetched job log below. |

The Burst page's statement that a scheduled transfer “runs one block later” is true of these captures. Prefer “ran in the next block in these runs” if editing that paragraph, to avoid sounding like a general execution-latency guarantee.

## Executed validation

| Check | Result |
| --- | --- |
| `python3 -m unittest discover -s tests/evidence -t . -v` | **68/68 OK**, no skips, including the three production bubblewrap regressions. This also replays the superseded A/B records and current C/D. |
| `cargo +1.93.0 test -p near-agent-vault --locked` | **12/12 passed**, plus zero doc tests. |
| `python3 scripts/build_web_bundle.py` and bundle diff | Regenerated 141,355 bytes; `git diff --exit-code web/public/bundle.json` succeeded. SHA-256 `4e0c47d63c1b19c1c87c4376d1319241e3126a7fc38f875e6406436ce088bc63`. |
| Protected source/build inputs | No diff from `d948613` in `contracts/vault`, `scripts/build-contract.sh`, root Cargo manifest/lockfile or `rust-toolchain.toml`. |
| `cargo +1.93.0 build -p g1-sandbox-tests --locked --bin g2_actor -j 2` | Succeeded. |
| Fresh G2 experiment | **Completed in 21.9 seconds**, clean reviewed source at `2b4a25d`, `review-g2-1794329140`, chain `test-chain-mfEZc`. Isolation PASS; socket directory read-only. Protected and generous targets each had four PASS verdicts and no issues. |
| Fresh protected target | Initial 1 NEAR plus burst IDs 6 and 8 admitted; six BudgetExceeded denials; C = S = 5, F = U = 0, count = 3. Six witnesses, with no same-block settlement ambiguity. |
| Fresh generous target | Nine admissions total; C = S = 17 NEAR. |
| Fresh teaching fixture | Nine successful native transfers delivered **17 NEAR**, **12 NEAR over B**; all eight burst admissions in block 105. No audit issues. |
| Extra C1 probes | `/proc/self/fd` symlink rejected; final-path replacement after `fstat` returned the original public inode; intermediate-directory replacement retained the already-open directory. Dummy data only. |
| Old C1 reproduction | Expected `AttributeError`: `run_g1.bwrap` no longer exists. The replacement boundary suite above passed. |
| Cleanup / edits | Review node stopped. Tracked implementation, docs, artifacts and committed evidence are unchanged. Only this report, review scripts/results, and new local review-run evidence were added. No push, merge, external deployment or publication. Test transactions used fresh local sandbox keys only. |

The independent CI check is [run 42850602121, contract job 129949902002](https://github.com/mickeyjoes/near-agent-vault-lab/actions/runs/42850602121/job/129949902002), at `53a98c0879c0224d7e9a2bdc4841d513b9a99abb`. Its workflow/build inputs equal the reviewed revision. The fetched log records the no-default-features installation, `c7c772635acea0938bd88450d02bcdb9215d9aa65fc407b4070459cd225dd768`, `capability gate: PASS`, and successful artifact diff. All three CI jobs succeeded. I did not start a new workflow.

## Retained review evidence

- [`codex-postfix-20261110/`](codex-postfix-20261110/): runnable helper counterexample, C1 probes, their JSON outputs, C/D/fresh witness checks, G1 baseline/digest comparisons, fixture initializer checks and CI verification excerpts.
- [`../evidence/g2-independent/review-g2-1794329140/`](../evidence/g2-independent/review-g2-1794329140/): fresh reviewer descriptors, raw RPC records, results and run summary. Private keys remain outside the repository.
- Full fresh-run console log: `/home/mickey/Dev/Hackathons/NEAR/reports/codex-postfix-20261110/fresh-g2.log`.

Acceptance after W1: the mixed same-block case must return ambiguity or a conservative non-witness, while current C/D retain six witnesses and all existing evidence tests continue to pass. The demonstrated local-sandbox budget result can remain; broaden no claim beyond those observations.
