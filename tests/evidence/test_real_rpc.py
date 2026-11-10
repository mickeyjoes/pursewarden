"""Regressions against ACTUAL recorded nearcore 2.13.4 RPC responses (not synthetic fixtures).

1. Agent A's original evidence run g1-20261029a (saved EXPERIMENTAL_tx_status responses):
   representation and failure-first classification cases the 2026-10-31 review found.
2. Independent G1 evidence runs (evidence/g1-independent/<run>/independent/rpc.jsonl.gz):
   full replay of every recorded response, whole-root omission and 18 mutations.
Replayed sources are labelled REPLAY and can never produce a runtime PASS verdict.
"""
import base64
import hashlib
import json
import unittest
from pathlib import Path

from packages.collector import canonical, collect, decode64, loads
from packages.verifier import action_body, failure_summary, graph_check, outcome_kind, verify
from packages.verifier.forge import ReplayNode, load_rpc_records, omit_request_root, run_mutations

REPO = Path(__file__).resolve().parents[2]
A_RUN = REPO / "evidence/g1/g1-20261029a"
LEGACY_WASM = REPO / "artifacts/legacy/near_agent_vault.5b05246b.wasm"
NEAR = 10**24


def a_tx(name):
    raw = json.loads((A_RUN / "txs" / f"{name}.json").read_text())
    return raw.get("result", raw)


def evidence_runs():
    root = REPO / "evidence/g1-independent"
    return sorted(p for p in root.glob("g1i-*") if (p / "independent/rpc.jsonl.gz").exists()
                  and "-dev-" not in p.name)


@unittest.skipUnless(A_RUN.exists(), "original evidence run not present")
class AgentAOriginalResponses(unittest.TestCase):
    VAULT = "vault.owner.test.near"

    def first_vault_outcome(self, graph):
        first = graph["transaction_outcome"]["outcome"]["receipt_ids"][0]
        return next(o for o in graph["receipts_outcome"] if o["id"] == first)

    def test_deploy_contract_is_32_byte_digest_in_receipt_view(self):
        g = a_tx("create_vault")
        r = next(x for x in g["receipts"] if x["receiver_id"] == self.VAULT and x["predecessor_id"] != "system")
        code = decode64(r["receipt"]["Action"]["actions"][2]["DeployContract"]["code"])
        self.assertEqual(len(code), 32)
        self.assertEqual(code.hex(), hashlib.sha256(LEGACY_WASM.read_bytes()).hexdigest())
        # Hashing the digest again (the original adapter's mistake) yields the wrong value.
        self.assertEqual(hashlib.sha256(code).hexdigest(),
                         "685579c6b0dc81ebd9e5cc72475d60d33f1e57f0467453524d54cb89138ec664")

    def test_failures_are_classified_before_argument_parsing(self):
        cases = {"malformed_not_json": "MalformedInput", "malformed_unknown_field": "MalformedInput",
                 "owner_freeze_with_deposit": "AttachedDeposit", "owner_request_with_deposit": "AttachedDeposit",
                 "owner_calls_nonexistent_withdraw": "MethodNotFound", "owner_calls_nonexistent_upgrade": "MethodNotFound",
                 "owner_reinitialize": "Reinitialize", "owner_calls_private_callback": "PrivateMethod",
                 "stranger_freeze": "Unauthorized", "owner_request_payment": "Unauthorized"}
        for name, cls in cases.items():
            with self.subTest(name=name):
                g = a_tx(name)
                out = self.first_vault_outcome(g)
                self.assertEqual(outcome_kind(out), "Failure")
                self.assertEqual(failure_summary(out), cls)
                bodies = {r["receipt_id"]: r for r in g["receipts"]}
                # A failed vault receipt produced only system refunds, never a vault-predecessor receipt.
                self.assertTrue(all(bodies[c]["predecessor_id"] == "system" for c in out["outcome"]["receipt_ids"]))
        # The not-JSON case would have crashed an adapter that parsed arguments first.
        args = a_tx("malformed_not_json")["transaction"]["actions"][0]["FunctionCall"]["args"]
        with self.assertRaises(Exception):
            loads(decode64(args))

    def test_principal_refund_is_system_signed_and_exact(self):
        g = a_tx("payment_2_to_missing")
        bodies = {r["receipt_id"]: r for r in g["receipts"]}
        outs = {o["id"]: o for o in g["receipts_outcome"]}
        native = next(r for r in g["receipts"] if r["predecessor_id"] == self.VAULT and r["receiver_id"] == "missing.test.near")
        self.assertEqual(failure_summary(outs[native["receipt_id"]]), "AccountDoesNotExist")
        children = [bodies[c] for c in outs[native["receipt_id"]]["outcome"]["receipt_ids"]]
        # Two system children: the principal (balance) refund, signed by `system`, back to the
        # vault; and a gas refund signed by the agent, back to the agent. Only the former is principal.
        principal = [r for r in children if action_body(r)["signer_id"] == "system"]
        gas = [r for r in children if action_body(r)["signer_id"] != "system"]
        self.assertEqual((len(principal), len(gas)), (1, 1))
        ab = action_body(principal[0])
        self.assertEqual((principal[0]["predecessor_id"], ab["gas_price"], principal[0]["receiver_id"]),
                         ("system", "0", self.VAULT))
        self.assertEqual(ab["actions"], [{"Transfer": {"deposit": str(2 * NEAR)}}])
        self.assertEqual((gas[0]["predecessor_id"], gas[0]["receiver_id"]), ("system", "agent.owner.test.near"))

    def test_saved_graphs_close(self):
        # Internal closure only: the original run's blocks are pruned, so ancestry is unavailable.
        for name in ("payment_1_success", "payment_2_to_missing", "create_vault", "owner_freeze"):
            with self.subTest(name=name):
                g = a_tx(name)
                outs = [g["transaction_outcome"]] + g["receipts_outcome"]
                heights = {o["block_hash"]: 1 for o in outs}
                txid = g["transaction"]["hash"]
                graph_check(txid, g, g["transaction_outcome"]["block_hash"], heights, set())


class IndependentRunReplay(unittest.TestCase):
    def setUp(self):
        runs = evidence_runs()
        if not runs:
            self.skipTest("no committed independent evidence run")
        self.runs = runs

    def load(self, run):
        d = json.loads((run / "reviewer-descriptor.json").read_text())
        return d, load_rpc_records(run / "independent/rpc.jsonl.gz")

    def test_replay_reconciles_exactly_but_is_never_a_runtime_pass(self):
        for run in self.runs:
            with self.subTest(run=run.name):
                d, records = self.load(run)
                result, _ = verify(ReplayNode(records), d)
                self.assertEqual(result["chain_evidence_checks"], "PASS", result["issues"])
                self.assertEqual(result["computed_if_live"], {"safety": "PASS", "settlement": "PASS",
                                                              "evidence": "PASS", "scenario_coverage": "PASS"})
                self.assertTrue(all(v == "INCONCLUSIVE" for v in result["verdicts"].values()))
                led = result["recovery"]["ledger"]
                self.assertEqual(led, {"C": str(3 * NEAR), "S": str(NEAR), "F": str(2 * NEAR), "U": "0",
                                       "headroom": str(2 * NEAR), "accepted_count": 2})
                refunds = result["recovery"]["principal_refunds"]
                self.assertEqual([(r["amount"], r["recipient"], r["outcome"]) for r in refunds],
                                 [(str(2 * NEAR), d["vault"], "SuccessValue")])
                self.assertNotIn("tx_hash", json.dumps(d))  # descriptor carries no runner roots

    def test_whole_root_omission_is_recovered_from_replayed_node(self):
        for run in self.runs:
            with self.subTest(run=run.name):
                d, records = self.load(run)
                presented = collect(ReplayNode(records), d)
                forged, omitted = omit_request_root(presented, "2")
                self.assertNotIn(omitted.encode(), canonical(forged))
                result, capture = verify(ReplayNode(records), d, forged)
                self.assertEqual(result["verdicts"]["evidence"], "FAIL")
                om = [i for i in result["issues"] if i["code"] == "OMITTED_ROOT"]
                self.assertEqual([i["tx_hash"] for i in om], [omitted])
                pay = om[0]["recovered_effects"]["payments"]
                self.assertEqual([(p["request_id"], p["class"], p["amount"]) for p in pay], [("2", "F", str(2 * NEAR))])
                self.assertIn("principal_refund_receipt", pay[0])

    def test_mutations_of_genuine_responses_never_pass(self):
        for run in self.runs:
            with self.subTest(run=run.name):
                d, records = self.load(run)
                results = run_mutations(records, d, verify)
                self.assertEqual(len(results), 18)
                for name, r in results.items():
                    self.assertTrue(r["applied"], (name, r))
                    self.assertTrue(r["rejected"], (name, r))


if __name__ == "__main__":
    unittest.main()
