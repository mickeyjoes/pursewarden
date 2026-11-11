"""Regressions against the recorded PUBLIC TESTNET smoke inspection (evidence/testnet-smoke/tn-*).

The inspector's raw RPC responses are replayed through packages.verifier.inspect_smoke. The replay
must reproduce every field of the committed PASS (the committed v1 file predates the creation check,
which v2 adds), and tampered responses must not pass. This is a narrow smoke inspection
(runner-listed transactions), not an independent completeness proof.

The construction regressions (final audit PW-01) cover an omitted creation record, extra actions in
the creation batch, a delayed capability scheduled by the vault during creation, and the real
creation graph recorded from the audit's sandbox PoC (tests/evidence/data/).
"""
import base64
import copy
import hashlib
import json
import unittest
from pathlib import Path

from packages.collector import EvidenceError, loads
from packages.verifier.forge import ReplayNode, load_rpc_records
from packages.verifier.inspect_smoke import check_construction, inspect, replays_committed

REPO = Path(__file__).resolve().parents[2]
RUNS = sorted(p for p in (REPO / "evidence/testnet-smoke").glob("tn-*") if (p / "inspection/rpc").is_dir())
WASM_SHA = hashlib.sha256((REPO / "artifacts/near_agent_vault.wasm").read_bytes()).hexdigest()
TIMEBOMB = REPO / "tests/evidence/data/pw01_timebomb_creation.json"
PRELUDE_DIGEST = base64.b64encode(bytes.fromhex("90ad37d9f7f0aa197d64dbb21614e401cf9acee23d85048a69407d1caa44f89e")).decode()
ZERO_ID = "11111111111111111111111111111111"


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
        self.assertTrue(replays_committed(res, committed))
        self.assertEqual(set(res) - set(committed), {"construction"})
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
        c = res["construction"]
        self.assertEqual(c["tx_hash"], self.creation["tx_hash"])
        self.assertEqual(c["actions"], ["CreateAccount", "Transfer", "DeployContract", "FunctionCall"])
        self.assertEqual(c["deployed_code_sha256"], WASM_SHA)
        self.assertEqual(c["init_returned_policy_hash"], self.run["policy_hash"])
        self.assertEqual(c["other_receipts"], 1)

    # -- Construction (final audit PW-01): fail closed unless the creation batch is exactly approved --

    @property
    def creation(self):
        return next(t for t in self.run["transactions"] if t["label"] == "create_vault")

    def edit_creation(self, fn):
        return edit(self.records, "EXPERIMENTAL_tx_status", {"tx_hash": self.creation["tx_hash"]}, lambda r: fn(r["result"]))

    def test_creation_record_omitted_fails(self):
        run = copy.deepcopy(self.run)
        run["transactions"] = [t for t in run["transactions"] if t["label"] != "create_vault"]
        self.assertEqual(verdict(self.records, run), "error:CREATION_TX_MISSING")

    def test_creation_record_listed_twice_fails(self):
        run = copy.deepcopy(self.run)
        run["transactions"].append(copy.deepcopy(self.creation))
        self.assertEqual(verdict(self.records, run), "error:CREATION_TX_AMBIGUOUS")

    def test_creation_record_from_another_signer_fails(self):
        run = copy.deepcopy(self.run)
        next(t for t in run["transactions"] if t["label"] == "create_vault")["signer"] = self.run["agent"]
        self.assertEqual(verdict(self.records, run), "error:CREATION_TX_IDENTITY")

    def test_creation_not_returned_by_node_fails(self):
        recs = [r for r in self.records if r["request"]["params"].get("tx_hash") != self.creation["tx_hash"]]
        self.assertEqual(verdict(recs, self.run), "error:CREATION_TX_UNAVAILABLE")

    def test_creation_not_final_fails(self):
        def pending(g):
            g["final_execution_status"] = "INCLUDED_FINAL"
        self.assertEqual(verdict(self.edit_creation(pending), self.run), "error:NOT_FINAL")

    def test_prelude_deploy_and_call_in_creation_batch_fails(self):
        """The audit's batch: [CreateAccount, Transfer, DeployContract(prelude), FunctionCall(arm), DeployContract(vault), new]."""
        def prelude(g):
            extra = [{"DeployContract": {"code": PRELUDE_DIGEST}},
                     {"FunctionCall": {"args": "", "deposit": "0", "gas": 100000000000000, "method_name": "arm"}}]
            for actions in (g["transaction"]["actions"], g["receipts"][0]["receipt"]["Action"]["actions"]):
                actions[2:2] = copy.deepcopy(extra)
        self.assertEqual(verdict(self.edit_creation(prelude), self.run), "error:KEYLESS_CONSTRUCTION")

    def test_unexpected_construction_actions_fail(self):
        key = {"AddKey": {"access_key": {"nonce": 0, "permission": "FullAccess"},
                          "public_key": "ed25519:" + ZERO_ID}}
        variants = {
            "add_key": lambda a: a.append(copy.deepcopy(key)),
            "second_deploy": lambda a: a.insert(3, copy.deepcopy(a[2])),
            "wrong_code": lambda a: a[2]["DeployContract"].update(code=PRELUDE_DIGEST),
            "other_init_method": lambda a: a[3]["FunctionCall"].update(method_name="migrate"),
            "deposit_on_new": lambda a: a[3]["FunctionCall"].update(deposit="1"),
            "reordered": lambda a: a.insert(1, a.pop(2)),
        }
        for name, mutate in variants.items():
            with self.subTest(name):
                def apply(g):
                    for actions in (g["transaction"]["actions"], g["receipts"][0]["receipt"]["Action"]["actions"]):
                        mutate(actions)
                self.assertEqual(verdict(self.edit_creation(apply), self.run), "error:KEYLESS_CONSTRUCTION")

    def test_receipt_differing_from_signed_batch_fails(self):
        def receipt_only(g):
            g["receipts"][0]["receipt"]["Action"]["actions"].insert(2, {"DeployContract": {"code": PRELUDE_DIGEST}})
        self.assertNotEqual(verdict(self.edit_creation(receipt_only), self.run), "PASS")

    def _vault_child(self, g, action, yielded=False):
        """Graft a receipt FROM the vault onto the creation receipt, as a prelude would leave behind."""
        first = g["transaction_outcome"]["outcome"]["receipt_ids"][0]
        parent = next(o for o in g["receipts_outcome"] if o["id"] == first)
        body = copy.deepcopy(next(r for r in g["receipts"] if r["receipt_id"] == first))
        body.update(receipt_id=ZERO_ID, predecessor_id=self.run["vault"], receiver_id=self.run["vault"])
        body["receipt"]["Action"].update(actions=[action], is_promise_yield=yielded)
        g["receipts"].append(body)
        g["receipts_outcome"].append({"block_hash": parent["block_hash"], "id": ZERO_ID, "proof": [], "outcome": {
            "executor_id": self.run["vault"], "gas_burnt": 0, "logs": [], "receipt_ids": [], "status": {"SuccessValue": ""},
            "tokens_burnt": "0", "metadata": {"gas_profile": [], "version": 3}}})
        parent["outcome"]["receipt_ids"].append(ZERO_ID)

    def test_delayed_add_key_from_vault_fails(self):
        key = {"AddKey": {"access_key": {"nonce": 0, "permission": "FullAccess"}, "public_key": "ed25519:" + ZERO_ID}}
        recs = self.edit_creation(lambda g: self._vault_child(g, key))
        self.assertEqual(verdict(recs, self.run), "error:CONSTRUCTION_DISPATCH")

    def test_yielded_receipt_from_vault_fails(self):
        call = {"FunctionCall": {"args": "", "deposit": "0", "gas": 30000000000000, "method_name": "get_mandate"}}
        recs = self.edit_creation(lambda g: self._vault_child(g, call, yielded=True))
        self.assertNotEqual(verdict(recs, self.run), "PASS")

    def test_creation_result_must_be_the_policy_hash(self):
        def other_result(g):
            first = g["transaction_outcome"]["outcome"]["receipt_ids"][0]
            out = next(o for o in g["receipts_outcome"] if o["id"] == first)
            out["outcome"]["status"]["SuccessValue"] = base64.b64encode(b'"' + ZERO_ID.encode() + b'"').decode()
        self.assertEqual(verdict(self.edit_creation(other_result), self.run), "error:CONSTRUCTION_RESULT")

    def test_recorded_timebomb_creation_fails(self):
        """The real creation graph from the audit's PoC (local sandbox), recorded after the planted key fired."""
        rec = json.loads(TIMEBOMB.read_text())
        d = {"owner": rec["owner"], "vault": rec["vault"], "policy_hash": rec["policy_hash"], "wasm_sha256": WASM_SHA}
        g = rec["rpc_response"]["result"]
        self.assertEqual(g["final_execution_status"], "FINAL")
        self.assertTrue(any(r["receipt"]["Action"]["is_promise_yield"] for r in g["receipts"]))
        self.assertTrue(any(r["predecessor_id"] == rec["vault"] and "AddKey" in r["receipt"]["Action"]["actions"][0]
                            for r in g["receipts"]))
        with self.assertRaises(EvidenceError) as ctx:
            check_construction(g, d, set())
        self.assertEqual(ctx.exception.code, "KEYLESS_CONSTRUCTION")

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
