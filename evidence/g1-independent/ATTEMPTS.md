# Independent G1 run attempts (all retained)

| Run | Result | Cause |
| --- | --- | --- |
| `g1i-dev-01` | STOPPED at runner phase | Orchestrator bug: the filter proxy's log directory did not exist, the proxy exited, and the in-sandbox isolation probe failed closed (admin-method probes got transport errors instead of filter denials). Node/path isolation itself held. |
| `g1i-dev-02` | STOPPED at independent acquisition (evidence FAIL `CHUNK_HEADER`) | Real-representation mismatch: nearcore 2.13.4 serves `height_included: 0` for a chunk fetched by hash. Fixed by binding chunk hash/shard/`height_created` to the block's chunk header. The same node was restarted afterwards for offline adapter iteration (not evidence). |

Development attempts are not gate evidence. Evidence runs are listed in `docs/G1_INDEPENDENT_RESULT.md`.

## Evidence runs

| Run | Code commit | Chain | Result |
| --- | --- | --- | --- |
| `g1i-20261110T135044Z-a` | `91c4ce6` (clean) | `test-chain-oJOg4` | Isolation PASS; independent acquisition PASS (safety/settlement/evidence/scenario); forged presentation evidence FAIL with the omitted root recovered; 18/18 mutations rejected; retention re-read after 2,000 produced blocks identical |
| `g1i-20261110T135407Z-b` | `e783dac` (clean) | `test-chain-6J4eY` | Same results on a second fresh node (retention after 2,001 blocks) |
| `review-codex-20261110-b` | `7fa66e2` | `test-chain-QDgMG` | Codex's independent review run: same results. (`review-codex-20261110` was stopped at startup by Codex's own sandbox network policy.) |
| `g1i-20261110T144905Z-c` | `71a679c` (clean) | `test-chain-d8AyA` | **Post-C1-fix run.** Same results. Isolation probe in its own invocation; socket directory read-only; all runner output via `safe_import`; 4/4 pre-inclusion rejections reviewer-observed; retention after 2,000 blocks identical (orchestrator now reports `fields_identical: true` directly). |

Runs A and B used the pre-fix import path (`shutil.copy` from the runner tree). Their workload is the committed, non-hostile `runner-attack`, so their chain evidence is unaffected; they do not demonstrate the repaired file boundary. Run C does.

Correction recorded, not hidden: `run-summary.json` of both runs reports `retention.fields_identical: false` with `differing_fields: ["status"]`. The orchestrator compared the live `status` snapshot (head height, time) byte-for-byte, which always changes. `retention-compare.json` (written by `scripts/g1-independent/retention_compare.py`) compares only node identity from `status` and every other capture field byte-for-byte: all identical. The orchestrator was fixed after both runs.
