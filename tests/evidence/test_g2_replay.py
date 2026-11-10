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
                    self.assertEqual(x["settled_before_denial"], str(NEAR))
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
        self.assertEqual(w[0]["settled_before_denial"], str(5 * NEAR))

    def test_same_block_execution_is_not_counted_as_pending(self):
        pays = [self.pay("2", 2, "b10", "b10")]
        w = pending_witness(pays, [self.deny("4", 4, "b10")], self.H, 5 * NEAR)
        self.assertFalse(w[0]["witness"])

    def test_later_admission_is_not_counted(self):
        pays = [self.pay("9", 9, "b10", "b11")]
        w = pending_witness(pays, [self.deny("4", 4, "b10")], self.H, 5 * NEAR)
        self.assertEqual(w[0]["pending_admitted_transfers"], [])


if __name__ == "__main__":
    unittest.main()
