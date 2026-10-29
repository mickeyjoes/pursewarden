# Read-only implementation inputs

Research files were read from `/home/mickey/Dev/Hackathons/NEAR/` and not edited or copied into the implementation tree.

| File | SHA-256 |
| --- | --- |
| reports/SPEC_V1_1_RECONCILED_DRAFT.md | 7b2d8aa5126543c84297afb663e0ecdf74683928f5d7e5df154ad2e09954cefc |
| reports/Phase0_E_Prebuild_Decision_2026-10-20.md | 0b1e4cf500e835300fb21a3063ee53e86a72a4e5e43c50ead51ba0da271c8c63 |
| reports/Phase0_B_Independent_Evidence_Preflight_2026-10-20.md | a5b27b36e2b8bbeb2d1495a6f15a0a59a0a06bc5e097e195d226ce0cba9d3fcb |
| NEAR_Dual_Network_Implementation_Handoff_2026-10-23/NEAR_Dual_Network_Execution_Plan_2026-10-23.md | e091dfda2f5256e64780189c1c6ef35634b948a636f503d8fcdf8a63a29b7ab9 |

The October 29 user instruction and immediate build kickoff supersede the old November 1 start assumption. No acceptance criteria were changed.

Implementation schema references use the existing preflight's nearcore source pin `44f7ae6cd7ef08bab604e20a473bf77e35d4c993`, not a claim about an installed runtime:

- [RPC query errors and block metadata](https://github.com/near/nearcore/blob/44f7ae6cd7ef08bab604e20a473bf77e35d4c993/chain/jsonrpc-primitives/src/types/query.rs).
- [Transaction/receipt/action/state-change JSON types](https://github.com/near/nearcore/blob/44f7ae6cd7ef08bab604e20a473bf77e35d4c993/core/primitives/src/views.rs).
- [Balance and gas refund construction](https://github.com/near/nearcore/blob/44f7ae6cd7ef08bab604e20a473bf77e35d4c993/core/primitives/src/receipt.rs).
- [Runtime refund handling](https://github.com/near/nearcore/blob/44f7ae6cd7ef08bab604e20a473bf77e35d4c993/runtime/runtime/src/lib.rs).

No binaries, contracts or real block/transaction/receipt IDs were available from these source references. Synthetic IDs/digests belong solely to generated regression fixtures. Runtime source/binary correspondence remains a blocker.
