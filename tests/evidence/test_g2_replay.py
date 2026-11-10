"""G2 regressions on ACTUAL recorded responses (committed evidence/g2-independent runs).

Replayed sources are labelled REPLAY and never yield a runtime PASS; `computed_if_live` shows
what the same checks give on the recorded data."""
import json
import unittest
from pathlib import Path

from packages.verifier import pending_witness, verify
from packages.verifier.control import run_control
from packages.verifier.forge import ReplayNode, load_rpc_records

REPO = Path(__file__).resolve().parents[2]
NEAR = 10**24


def g2_runs():
    root = REPO / "evidence/g2-independent"
    return sorted(p for p in root.glob("g2i-*") if "-dev-" not in p.name and (p / "run-summary.json").exists())


class G2Replay(unittest.TestCase):
    def setUp(self):
        self.runs = g2_runs()
        if not self.runs:
            self.skipTest("no committed G2 run")

    def replay(self, run, name):
        d = json.loads((run / name / "reviewer-descriptor.json").read_text())
        return verify(ReplayNode(load_rpc_records(run / name / "rpc.jsonl.gz")), d)[0]

    def test_protected_vault_admits_exactly_two_of_eight_with_pending_witness(self):
        for run in self.runs:
            with self.subTest(run=run.name):
                r = self.replay(run, "protected")
                self.assertEqual(r["chain_evidence_checks"], "PASS", r["issues"])
                self.assertTrue(all(v == "PASS" for v in r["computed_if_live"].values()))
                rec = r["recovery"]
                self.assertEqual(rec["ledger"], {"C": str(5 * NEAR), "S": str(5 * NEAR), "F": "0", "U": "0",
                                                 "headroom": "0", "accepted_count": 3})
                burst = [p for p in rec["payments"] if p["request_id"] != "1"]
                self.assertEqual(len(burst), 2)
                self.assertEqual(sorted(x["reason"] for x in rec["denials"]), ["BudgetExceeded"] * 6)
                w = rec["pending_witness"]
                self.assertEqual(len(w), 6)
                for x in w:
                    self.assertTrue(x["witness"], x)
                    self.assertEqual((x["settled_before_denial_min"], x["settled_before_denial_max"]), (str(NEAR), str(NEAR)))
                    self.assertFalse(x["same_block_settlement_ambiguity"])
                    self.assertIs(x["settled_only_check_would_admit"], True)
                    self.assertEqual(x["charged_at_decision"], str(5 * NEAR))
                    self.assertEqual(len(x["pending_admitted_transfers"]), 2)
                    for t in x["pending_admitted_transfers"]:
                        self.assertGreater(t["transfer_execution_height"], x["denial_height"])

    def test_generous_control_admits_all_eight(self):
        for run in self.runs:
            with self.subTest(run=run.name):
                r = self.replay(run, "generous")
                self.assertEqual(r["chain_evidence_checks"], "PASS", r["issues"])
                self.assertEqual(r["recovery"]["ledger"]["C"], str(17 * NEAR))
                self.assertEqual(len(r["recovery"]["payments"]), 9)
                self.assertEqual(r["recovery"]["denials"], [])

    def test_vulnerable_fixture_overspends_under_a_genuine_race(self):
        for run in self.runs:
            with self.subTest(run=run.name):
                d = json.loads((run / "vulnerable/control-descriptor.json").read_text())
                res, _ = run_control(ReplayNode(load_rpc_records(run / "vulnerable/rpc.jsonl.gz")), d)
                self.assertEqual(res["issues"], [])
                self.assertEqual(res["delivered_principal"], str(17 * NEAR))
                self.assertEqual(res["overspend"], str(12 * NEAR))
                self.assertTrue(res["budget_exceeded_on_chain"])
                self.assertIn(8, res["admissions_per_block"].values())  # the whole burst in one block
                self.assertTrue(all(t["outcome"] == "SuccessValue" for t in res["transfers"]))

    def test_control_rejects_wrong_fixture_code(self):
        run = self.runs[0]
        d = dict(json.loads((run / "vulnerable/control-descriptor.json").read_text()), wasm_sha256="0" * 64)
        res, _ = run_control(ReplayNode(load_rpc_records(run / "vulnerable/rpc.jsonl.gz")), d)
        self.assertIn("WRONG_CONTRACT", [i["code"] for i in res["issues"]])


class PendingWitnessLogic(unittest.TestCase):
    """The witness must require strict ordering; settled transfers are not 'pending'."""
    H = {"b10": 10, "b11": 11, "b12": 12}

    def pay(self, rid, seq, adm, exe, cls="S", amt=2):
        return {"request_id": rid, "admission_seq": str(seq), "admission_block": adm, "execution_block": exe,
                "class": cls, "amount": str(amt * NEAR)}

    def deny(self, rid, seq, blk, amt=2):
        return {"request_id": rid, "seq": str(seq), "block_hash": blk, "amount": str(amt * NEAR),
                "reason": "BudgetExceeded", "charged_at_decision": str(5 * NEAR)}

    def test_transfer_executed_before_denial_is_not_pending(self):
        pays = [self.pay("1", 1, "b10", "b11", amt=1), self.pay("2", 2, "b10", "b11"), self.pay("3", 3, "b10", "b11")]
        w = pending_witness(pays, [self.deny("4", 4, "b12")], self.H, 5 * NEAR)
        self.assertEqual(w[0]["pending_admitted_transfers"], [])
        self.assertFalse(w[0]["witness"])
        self.assertEqual(w[0]["settled_before_denial_max"], str(5 * NEAR))
        self.assertIs(w[0]["settled_only_check_would_admit"], False)

    def test_same_block_execution_is_not_counted_as_pending(self):
        pays = [self.pay("2", 2, "b10", "b10")]
        w = pending_witness(pays, [self.deny("4", 4, "b10")], self.H, 5 * NEAR)
        self.assertFalse(w[0]["witness"])

    def test_same_block_success_with_a_pending_transfer_is_ambiguous_not_a_witness(self):
        # Independent review W1 counterexample (B = 5, request 2): ID 2's transfer succeeds in the
        # denial's own block 10, ID 3's in block 11. Settled is 2 or 4 depending on in-block order.
        H = {"b8": 8, "b9": 9, "b10": 10, "b11": 11}
        pays = [self.pay("1", 1, "b8", "b9"), self.pay("2", 2, "b9", "b10"), self.pay("3", 4, "b10", "b11", amt=1)]
        w = pending_witness(pays, [self.deny("4", 5, "b10")], H, 5 * NEAR)[0]
        self.assertEqual([t["request_id"] for t in w["pending_admitted_transfers"]], ["3"])
        self.assertEqual((w["settled_before_denial_min"], w["settled_before_denial_max"]), (str(2 * NEAR), str(4 * NEAR)))
        self.assertTrue(w["same_block_settlement_ambiguity"])
        self.assertIsNone(w["settled_only_check_would_admit"])
        self.assertFalse(w["witness"])

    def test_same_block_success_that_cannot_change_the_answer_stays_a_witness(self):
        # Even counting the same-block success, settled 1 + 1 + 2 <= 5: unambiguous admit.
        H = {"b8": 8, "b9": 9, "b10": 10, "b11": 11}
        pays = [self.pay("1", 1, "b8", "b9", amt=1), self.pay("2", 2, "b9", "b10", amt=1), self.pay("3", 3, "b10", "b11")]
        w = pending_witness(pays, [self.deny("4", 5, "b10")], H, 5 * NEAR)[0]
        self.assertTrue(w["same_block_settlement_ambiguity"])
        self.assertIs(w["settled_only_check_would_admit"], True)
        self.assertTrue(w["witness"])

    def test_later_admission_is_not_counted(self):
        pays = [self.pay("9", 9, "b10", "b11")]
        w = pending_witness(pays, [self.deny("4", 4, "b10")], self.H, 5 * NEAR)
        self.assertEqual(w[0]["pending_admitted_transfers"], [])


if __name__ == "__main__":
    unittest.main()
