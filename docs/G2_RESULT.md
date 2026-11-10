# G2 concurrency result

| | |
| --- | --- |
| Date | 2026-11-10. The G2 timebox started at 15:36 UTC. The implementation commit `acd6ba6` is at 15:42 UTC, and the current evidence runs C/D at 15:52 UTC (commit times). |
| Branch | `feat/g2-concurrency`, from G1 release `d948613`. The G1 baseline is unchanged: its tests and replay digests are identical. |
| Network | **Local sandbox only** (nearcore 2.13.4, one fresh chain per run). No public network and no real funds. |
| Protected artifact | `c7c77263…dd768`, the same as G1 |
| Teaching fixture | `artifacts/fixtures/vulnerable_settled_only.wasm`, SHA-256 `07360b1f38bee8753ea4c21ee10fbce529980d96dc4fde65789af1b10f69c4a6`, built by `scripts/build-fixture.sh` with no builder paths. Source: `fixtures/vulnerable-settled-only/` (stand-alone workspace and lockfile). |

## Verdict

**G2: PASS on local-sandbox evidence.** Two clean fresh-node evidence runs (C and D) are current. Runs A and B, and an uncommitted clean-clone run, gave identical results.

After a settled 1 NEAR payment, eight 2 NEAR requests were pre-signed with eight separately authorized agent keys and submitted concurrently. The protected vault admitted **exactly two** and denied **six as `BudgetExceeded`**, ending at **C = 5 NEAR = B**.

All six denials executed in the same block, **while both admitted native transfers were still unexecuted**; those ran in the next block. At that moment only 1 NEAR had settled, so a settled-only check would have admitted every one of them. This **native-pending witness** comes only from the reviewer's independently captured receipts.

Two sandbox controls run in the same window:

| Control | Budget | Result |
| --- | --- | --- |
| Generous protected vault | B = 100 | All 8 admitted (C = 17). The infrastructure does admit when the budget allows. |
| Deliberately vulnerable teaching fixture (checks only settled spend) | B = 5 | All 8 admitted **in one block**, against a stale `settled = 1 NEAR`. **17 NEAR delivered against a 5 NEAR budget (overspend 12 NEAR)**, counted from native transfer receipt outcomes. |

## Runs

Runs C and D are the current evidence: commit `7d66b4c` (clean tree), fixture `07360b1f`, chains `test-chain-hzS0c` / `test-chain-PkbbB`. Same outcome: protected 2 of 8 burst admitted with 6/6 witnesses, generous 8/8, fixture 8 admissions in block #106 with 17 NEAR delivered. The detailed table below is for runs A and B, which were identical except for the fixture build (superseded; see `ATTEMPTS.md`).

| | Run A (superseded) | Run B (superseded) |
| --- | --- | --- |
| Run ID | `g2i-20261110T154252Z-a` | `g2i-20261110T154313Z-b` |
| Code | `acd6ba6` (clean tree), fixture `d2eef2fd` | `acd6ba6` (clean tree), fixture `d2eef2fd` |
| Chain | `test-chain-OPkoc` | `test-chain-G0vKO` |
| Window H0 → Q | #14 → #140 | #15 → #141 |
| Runner isolation probe | PASS (socket directory read-only) | PASS |
| Protected: admitted IDs (seq) | 1 (1), then burst 5 (3), 8 (4) | 1 (1), then burst 8 (3), 7 (4) |
| Protected: burst denials | 6 × BudgetExceeded, all in block #73 | 6 × BudgetExceeded, all in block #74 |
| Protected: admitted transfers execute | block #74 | block #75 |
| Pending witness | **6 / 6** (settled before denial 1 NEAR; charged at decision 5 NEAR) | **6 / 6** |
| Protected verdicts (live) | safety, settlement, evidence, scenario: PASS | PASS |
| Generous control | 9/9 admitted, C = 17, verdicts PASS | same |
| Vulnerable fixture | admissions per block {#97: 1, #105: 8}; transfers at #98 and #106; 17 NEAR delivered (overspend 12) | {#98: 1, #106: 8}; transfers at #99 and #107; same totals |
| Protected acquisition | 809 RPC calls, 1.52 MB | 809 RPC calls, 1.52 MB |
| Whole run | 21.5 s | 21.8 s |

Evidence is in `evidence/g2-independent/<run>/`:

| File | What it holds |
| --- | --- |
| `{protected,generous}/reviewer-descriptor.json` | Reviewer-selected inputs. No transaction hashes. |
| `{protected,generous}/result.json` | Full verifier output, including `pending_witness` |
| `{protected,generous}/rpc.jsonl.gz` | Exact raw RPC |
| `vulnerable/control-descriptor.json` | Control descriptor |
| `vulnerable/result.json` | Outflow audit |
| `vulnerable/rpc.jsonl.gz` | Exact raw RPC |
| `runner/` | Isolation probe, untrusted runner log, filter-proxy logs |
| `run-summary.json` | Run summary |

Attempts are listed in `evidence/g2-independent/ATTEMPTS.md` (`g2i-dev-01` was a development run on an uncommitted tree with the same outcome).

## How the witness is computed (`packages/verifier/__init__.py:pending_witness`)

For each `BudgetExceeded` denial *d*, using only captured receipts:
- **Earlier admissions:** payments whose admission seq is below *d*'s seq.
- **Pending:** earlier admissions whose native transfer outcome is in a block **strictly higher** than *d*'s block. Same-block execution is not counted as pending.
- **Settled before *d*:** successful transfers that executed in a block strictly lower than *d*'s.
- **Witness:** the pending set is non-empty **and** settled + amount ≤ B. In other words, a settled-only design would have admitted *d*.

Edge cases are unit-tested in `tests/evidence/test_g2_replay.py::PendingWitnessLogic`.

## Reproduce

```bash
cargo +1.93.0 build -p g1-sandbox-tests --locked --bin g2_actor
python3 scripts/g2-independent/run_g2.py my-g2 --rpc-port 3290 --net-port 24827   # about 25 s on Linux with bubblewrap
python3 -m unittest tests.evidence.test_g2_replay -v                               # replays the committed runs
```

## Scope and limits

- **Sandbox only.** There is one shard and one validator. All requests go to one vault account, so NEAR executes them sequentially in receipt order. That ordering is the protocol behaviour the protected design relies on: charging at admission inside a single receipt.
- **The vulnerable target is our own deliberately broken fixture.** It is not any other project's design, and nothing here claims another product is vulnerable.
- **Burst timing is real but not adversarially optimized.** We used a single submission attempt per key. "Concurrent" means pre-signed and submitted in parallel; in both runs every burst request landed in one block.
- **Not run:** a multi-shard topology, cross-contract callers, load beyond eight requests, testnet.
