"""Regressions against the recorded PUBLIC TESTNET smoke inspection (evidence/testnet-smoke/tn-*).

The inspector's raw RPC responses are replayed through packages.verifier.inspect_smoke. The replay
must reproduce the committed PASS exactly, and tampered responses must not pass. This is a narrow
smoke inspection (runner-listed transactions), not an independent completeness proof.
"""
import base64
import copy
import hashlib
import json
import unittest
from pathlib import Path

from packages.collector import EvidenceError, loads
from packages.verifier.forge import ReplayNode, load_rpc_records
from packages.verifier.inspect_smoke import inspect

REPO = Path(__file__).resolve().parents[2]
RUNS = sorted(p for p in (REPO / "evidence/testnet-smoke").glob("tn-*") if (p / "inspection/rpc").is_dir())
WASM_SHA = hashlib.sha256((REPO / "artifacts/near_agent_vault.wasm").read_bytes()).hexdigest()


def edit(records, method, match, fn):
    """Return a copy of records with fn applied to every decoded response whose request matches."""
    out, hits = copy.deepcopy(records), 0
    for r in out:
        req = r["request"]
        if req["method"] == method and all(req["params"].get(k) == v for k, v in match.items()):
            resp = loads(base64.b64decode(r["response_base64"]))
            fn(resp)
            r["response_base64"] = base64.b64encode(json.dumps(resp).encode()).decode()
            hits += 1
    assert hits, (method, match)
    return out


def verdict(records, run):
    try:
        return inspect(ReplayNode(records), run, WASM_SHA)["result"]
    except EvidenceError as exc:
        return f"error:{exc.code}"


@unittest.skipUnless(RUNS, "no testnet smoke evidence present")
class TestnetSmokeReplay(unittest.TestCase):
    def setUp(self):
        self.dir = RUNS[-1]
        self.run = json.loads((self.dir / "run.json").read_text())
        self.records = load_rpc_records(self.dir / "inspection/rpc")

    def test_replay_reproduces_committed_pass(self):
        res = inspect(ReplayNode(self.records), self.run, WASM_SHA)
        committed = json.loads((self.dir / "inspection/inspection.json").read_text())
        committed.pop("metrics", None)
        self.assertEqual(res, committed)
        self.assertEqual(res["result"], "PASS")
        self.assertEqual(res["network"], "testnet")
        self.assertEqual(res["cut"]["code_sha256"], WASM_SHA)
        self.assertEqual(res["cut"]["vault_keys"], 0)
        self.assertTrue(res["cut"]["frozen"])
        self.assertEqual(res["ledger"]["C"], res["ledger"]["sum_records"])
        got = {s["label"]: (s.get("decision"), s.get("reason") or s.get("native")) for s in res["steps"] if "decision" in s}
        self.assertEqual(got, {"pay_1_payee": ("Admitted", "S"), "pay_2_missing": ("Admitted", "F"),
                               "replay_1": ("Denied", "DuplicateRequest"), "over_cap": ("Denied", "AboveMaxPerRequest"),
                               "exfiltrate": ("Denied", "RecipientNotAllowed"), "budget_exceeded": ("Denied", "BudgetExceeded")})
        refund = next(s for s in res["steps"] if s["label"] == "pay_2_missing")
        self.assertTrue(refund["principal_refund"])

    def test_tampered_decision_fails(self):
        tx = next(t for t in self.run["transactions"] if t["label"] == "budget_exceeded")

        def flip(resp):
            first = resp["result"]["transaction_outcome"]["outcome"]["receipt_ids"][0]
            for o in resp["result"]["receipts_outcome"]:
                if o["id"] == first:
                    dec = loads(base64.b64decode(o["outcome"]["status"]["SuccessValue"]))
                    dec["reason"] = "AboveMaxPerRequest"
                    o["outcome"]["status"]["SuccessValue"] = base64.b64encode(json.dumps(dec).encode()).decode()
        recs = edit(self.records, "EXPERIMENTAL_tx_status", {"tx_hash": tx["tx_hash"]}, flip)
        self.assertNotEqual(verdict(recs, self.run), "PASS")

    def test_vault_key_appears_fails(self):
        def add_key(resp):
            resp["result"]["keys"].append({"public_key": "ed25519:11111111111111111111111111111111",
                                           "access_key": {"nonce": 0, "permission": "FullAccess"}})
        recs = edit(self.records, "query", {"request_type": "view_access_key_list", "account_id": self.run["vault"]}, add_key)
        self.assertNotEqual(verdict(recs, self.run), "PASS")

    def test_wrong_chain_refused(self):
        def mainnet(resp):
            resp["result"]["chain_id"] = "mainnet"
        recs = edit(self.records, "status", {}, mainnet)
        self.assertEqual(verdict(recs, self.run), "error:WRONG_CHAIN")

    def test_wrong_artifact_fails(self):
        try:
            res = inspect(ReplayNode(self.records), self.run, "00" * 32)["result"]
        except EvidenceError as exc:
            res = f"error:{exc.code}"
        self.assertNotEqual(res, "PASS")


if __name__ == "__main__":
    unittest.main()
