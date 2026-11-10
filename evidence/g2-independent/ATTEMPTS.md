# G2 run attempts (all retained)

| Run | Result | Note |
| --- | --- | --- |
| `g2i-dev-01` | Same outcome as the evidence runs (protected 2/8 admitted, C = 5, six pending-transfer witnesses; generous 8/8; fixture overspend 12 NEAR) | Development run on an uncommitted tree (`repo_dirty: true`). Not gate evidence. |
| `g2i-20261110T154252Z-a` | Evidence run at `acd6ba6` (clean), `test-chain-OPkoc` | protected 2/8 burst admitted, 6 BudgetExceeded, C = 5, 6/6 pending witnesses; generous 8/8, C = 17; fixture 8/8 in one block, 17 NEAR delivered (overspend 12) |
| `g2i-20261110T154313Z-b` | Evidence run at `acd6ba6` (clean), `test-chain-G0vKO` | Same results on a second fresh node |
