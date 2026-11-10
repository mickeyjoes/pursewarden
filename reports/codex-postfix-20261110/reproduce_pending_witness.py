#!/usr/bin/env python3
"""Review-only counterexample: block heights do not order same-block settlements.

This invokes the production helper on synthetic facts, not a new on-chain run.
It uses no keys, RPC, private files, or modified implementation code.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from packages.verifier import pending_witness  # noqa: E402

N = 10**24


def main():
    # All three payments were admitted before the denial, charging exactly B=5.
    # One 2 NEAR transfer already succeeded in block 9. Another succeeds in
    # block 10, the denial's block. The newest 1 NEAR transfer stays pending
    # until block 11. Sequence 3 can be the first payment's callback. The
    # same-block transfer's order relative to the denial is not an input to
    # pending_witness.
    payments = [
        {"request_id": "1", "admission_seq": "1", "admission_block": "b8",
         "execution_block": "b9", "class": "S", "amount": str(2 * N)},
        {"request_id": "2", "admission_seq": "2", "admission_block": "b9",
         "execution_block": "b10", "class": "S", "amount": str(2 * N)},
        {"request_id": "3", "admission_seq": "4", "admission_block": "b10",
         "execution_block": "b11", "class": "S", "amount": str(N)},
    ]
    denial = {"request_id": "4", "seq": "5", "block_hash": "b10",
              "amount": str(2 * N), "reason": "BudgetExceeded",
              "charged_at_decision": str(5 * N)}
    heights = {"b8": 8, "b9": 9, "b10": 10, "b11": 11}
    witness = pending_witness(payments, [denial], heights, 5 * N)[0]
    same_block_success = sum(int(p["amount"]) for p in payments
                             if p["class"] == "S" and p["execution_block"] == "b10")
    upper = int(witness["settled_before_denial"]) + same_block_success
    result = {
        "kind": "synthetic helper counterexample, not an executed chain trace",
        "production_output": witness,
        "same_block_successful_principal": str(same_block_success),
        "settled_lower_bound": witness["settled_before_denial"],
        "settled_upper_bound": str(upper),
        "would_admit_if_same_block_successes_precede_denial": upper + 2 * N <= 5 * N,
        "production_claims_unconditional_admission": witness["settled_only_check_would_admit"],
        "conservative_witness": bool(witness["pending_admitted_transfers"]) and upper + 2 * N <= 5 * N,
    }
    assert witness["witness"] is True
    assert result["would_admit_if_same_block_successes_precede_denial"] is False
    assert result["conservative_witness"] is False
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
