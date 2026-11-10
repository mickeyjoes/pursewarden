# Independent G1 run attempts (all retained)

| Run | Result | Cause |
| --- | --- | --- |
| `g1i-dev-01` | STOPPED at runner phase | Orchestrator bug: the filter proxy's log directory did not exist, the proxy exited, and the in-sandbox isolation probe failed closed (admin-method probes got transport errors instead of filter denials). Node/path isolation itself held. |
| `g1i-dev-02` | STOPPED at independent acquisition (evidence FAIL `CHUNK_HEADER`) | Real-representation mismatch: nearcore 2.13.4 serves `height_included: 0` for a chunk fetched by hash. Fixed by binding chunk hash/shard/`height_created` to the block's chunk header. The same node was restarted afterwards for offline adapter iteration (not evidence). |

Development attempts are not gate evidence. Evidence runs are listed in `docs/G1_INDEPENDENT_RESULT.md`.
