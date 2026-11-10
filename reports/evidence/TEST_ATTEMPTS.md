# Synthetic test attempt record

All executions below ran on the remote server, never the local workstation. No genuine NEAR run occurred. The initial failures were fixture defects and are preserved here rather than being described as passing attempts.

| Attempt | Result | Explanation |
| --- | --- | --- |
| Initial 31-test run | 29 pass, 2 fail; 0.144s | `test_tampered_transaction_identifier` returned RPC_UNAVAILABLE rather than TRANSACTION_MISMATCH; `test_wrong_node_version` did not observe mismatch. Fixture objects shared references between the expected descriptor, graph and chunk/status responses. Mutating the oracle accidentally changed its purported independent comparison input. |
| After per-response deep copies | 31 pass; 0.166s | Independent response objects restored the intended trust-boundary tests. |
| After protocol, H0-absence and raw-state capture | 31 pass; 0.177s | New required source responses provided by the explicitly synthetic fixture. |
| Transport/history expansion | 40 pass; 0.806s | Real loopback HTTP transport against a fake RPC server; no chain execution. |
| Malformed input validation | 41 pass; 0.822s | Adds malformed runner-bundle handling and the final acquisition/schema limits. |
| Final validation | See `test-run.log` | Adds typed historical NO_CONTRACT_CODE handling without invented code bytes. |

The first artifact export is retained under `synthetic-20261029/`; the final export is under `synthetic-final-20261029/`. Neither is a runtime G1 attempt, and neither consumes or supplies a native-pending comparison witness.
