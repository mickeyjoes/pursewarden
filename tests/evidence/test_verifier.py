import copy
import unittest

from packages.collector import EvidenceError, canonical, collect, decimal, digest, loads
from packages.verifier import verify
from tests.evidence.fixture import YOCTO, fixture, h


def remove_entire_root(capture, txid):
    forged = copy.deepcopy(capture)
    del forged["graphs"][txid]
    del forged["root_blocks"][txid]
    for chunk in forged["chunks"].values():
        chunk["transactions"] = [t for t in chunk["transactions"] if t["hash"] != txid]
    # A runner can remove its own rows and rehash everything; neither is trusted.
    forged["runner_rows"] = []
    rows = loads(bytes(forged["queries"]["get_admissions"]["result"]))
    forged["queries"]["get_admissions"]["result"] = list(canonical([r for r in rows if r["request_id"] != "2"]))
    mandate = loads(bytes(forged["queries"]["get_mandate"]["result"]))
    mandate.update({"charged": str(YOCTO), "accepted_count": 1})
    forged["queries"]["get_mandate"]["result"] = list(canonical(mandate))
    forged["checksums"] = {"graphs": digest(forged["graphs"]), "chunks": digest(forged["chunks"])}
    forged["checksum_sha256"] = digest(forged)
    forged["verdicts"] = {"evidence": "PASS", "safety": "PASS"}
    return forged


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.d, self.node = fixture()

    def graph(self, number=2):
        return self.node.responses[("EXPERIMENTAL_tx_status", canonical({"tx_hash": h(f"payment-{number}"),
                    "sender_account_id": self.d["agent"], "wait_until": "FINAL"}))]

    def assert_closed(self, result, code=None):
        self.assertNotEqual(result["verdicts"]["evidence"], "PASS")
        self.assertNotEqual(result["verdicts"]["safety"], "PASS")
        if code:
            self.assertIn(code, [i["code"] for i in result["issues"]], result)

    def test_complete_synthetic_chain_reconciles_but_is_not_runtime_g1(self):
        result, capture = verify(self.node, self.d)
        self.assertEqual(result["chain_evidence_checks"], "PASS", result)
        self.assertEqual(result["recovery"]["ledger"], {"C": str(3*YOCTO), "S": str(YOCTO),
                         "F": str(2*YOCTO), "U": "0", "headroom": str(2*YOCTO)})
        self.assertEqual(len(capture["graphs"]), 4)
        self.assertEqual(len(result["recovery"]["principal_refunds"]), 1)
        self.assertEqual(len(result["recovery"]["gas_refunds"]), 2)
        self.assertTrue(all(v == "INCONCLUSIVE" for v in result["verdicts"].values()))

    def test_entire_root_and_descendants_removed_rehashed_recovers_from_node(self):
        complete = collect(self.node, self.d)
        forged = remove_entire_root(complete, h("payment-2"))
        self.assertNotIn(h("payment-2"), canonical(forged).decode())
        self.node.calls.clear()
        result, capture = verify(self.node, self.d, forged)
        self.assertEqual(result["verdicts"]["evidence"], "FAIL")
        omitted = [i for i in result["issues"] if i["code"] == "OMITTED_ROOT"]
        self.assertEqual([i["tx_hash"] for i in omitted], [h("payment-2")])
        self.assertIn(h("refund-2"), omitted[0]["recovered_receipts"])
        self.assertEqual(result["recovery"]["ledger"]["F"], str(2*YOCTO))
        self.assertIn(h("payment-2"), capture["graphs"])
        self.assertIn(("chunk", {"chunk_id": h("chunk-14-0")}), self.node.calls)
        self.assertIn(("EXPERIMENTAL_tx_status", {"tx_hash": h("payment-2"),
                        "sender_account_id": self.d["agent"], "wait_until": "FINAL"}), self.node.calls)

    def test_bundle_outcome_tamper_detected_after_rehash(self):
        presented = collect(self.node, self.d)
        presented["graphs"][h("payment-2")]["receipts_outcome"][1]["outcome"]["status"] = {"SuccessValue": ""}
        presented["checksum_sha256"] = digest(presented)
        result, _ = verify(self.node, self.d, presented)
        self.assert_closed(result, "TAMPERED_GRAPH")
        self.assertEqual(result["recovery"]["ledger"]["F"], str(2*YOCTO))

    def test_bundle_wrong_vault_and_code_cannot_override_reviewer(self):
        presented = collect(self.node, self.d)
        presented["descriptor_sha256"] = "f"*64
        presented["queries"]["vault/view_code"]["code_base64"] = "ZmFrZQ=="
        presented["rpc"] = "http://attacker.invalid"
        result, _ = verify(self.node, self.d, presented)
        self.assert_closed(result, "TAMPERED_CAPTURE_FIELD")
        self.assertEqual(result["recovery"]["attribution"]["vault"], self.d["vault"])

    def test_malformed_runner_bundle_never_suppresses_result(self):
        for presented in ([], {"schema": "near-g1-capture/v1", "graphs": [], "status": {}},
                          {"schema": "near-g1-capture/v1", "graphs": {}, "status": 0}):
            with self.subTest(presented=presented):
                self.assert_closed(verify(self.node, self.d, presented)[0], "PRESENTED_SCHEMA")

    def test_wrong_chain(self):
        self.node.responses[("status", canonical({}))]["chain_id"] = "mainnet"
        self.assert_closed(verify(self.node, self.d)[0], "WRONG_CHAIN")

    def test_same_chain_id_different_genesis(self):
        self.node.responses[("block", canonical({"block_id": 0}))]["header"]["hash"] = h("other-genesis")
        self.assert_closed(verify(self.node, self.d)[0], "WRONG_GENESIS")

    def test_wrong_genesis_configuration(self):
        self.node.responses[("EXPERIMENTAL_genesis_config", canonical({}))]["protocol_version"] = 999
        self.assert_closed(verify(self.node, self.d)[0], "GENESIS_CONFIG")

    def test_wrong_node_version(self):
        self.node.responses[("status", canonical({}))]["version"]["build"] = "OTHER"
        self.assert_closed(verify(self.node, self.d)[0], "NODE_VERSION")

    def test_wrong_contract(self):
        key = ("query", canonical({"request_type": "view_code", "account_id": self.d["vault"], "block_id": self.d["q_hash"]}))
        self.node.responses[key]["code_base64"] = "ZmFrZQ=="
        self.assert_closed(verify(self.node, self.d)[0], "WRONG_CONTRACT")

    def test_wrong_vault_is_not_silently_replaced_by_bundle(self):
        self.d["vault"] = "other.owner.test.near"
        self.assert_closed(verify(self.node, self.d)[0], "RPC_UNAVAILABLE")

    def test_pruned_produced_block(self):
        del self.node.responses[("block", canonical({"block_id": h("block-14")}))]
        result, _ = verify(self.node, self.d)
        self.assert_closed(result, "RPC_UNAVAILABLE")
        self.assertEqual(result["verdicts"]["evidence"], "INCONCLUSIVE")

    def test_missing_chunk(self):
        del self.node.responses[("chunk", canonical({"chunk_id": h("chunk-14-0")}))]
        self.assert_closed(verify(self.node, self.d)[0], "RPC_UNAVAILABLE")

    def test_missing_shard(self):
        self.node.responses[("block", canonical({"block_id": h("block-14")}))]["chunks"].pop()
        self.assert_closed(verify(self.node, self.d)[0], "INCOMPLETE_SHARDS")

    def test_carried_chunks_and_skipped_height_are_not_false_missing_history(self):
        result, _ = verify(self.node, self.d)
        self.assertEqual(result["chain_evidence_checks"], "PASS", result)
        block_requests = [params for method, params in self.node.calls if method == "block"]
        self.assertNotIn({"block_id": 11}, block_requests)
        chunk_requests = [p["chunk_id"] for m, p in self.node.calls if m == "chunk"]
        self.assertEqual(chunk_requests.count(h("chunk-16-1")), 1)

    def test_missing_outcome(self):
        self.graph()["receipts_outcome"] = [o for o in self.graph()["receipts_outcome"] if o["id"] != h("native-2")]
        self.assert_closed(verify(self.node, self.d)[0], "MISSING_OUTCOME")

    def test_missing_refund_body(self):
        self.graph()["receipts"] = [r for r in self.graph()["receipts"] if r["receipt_id"] != h("refund-2")]
        self.assert_closed(verify(self.node, self.d)[0], "MISSING_RECEIPT_BODY")

    def test_fake_refund_amount(self):
        refund = next(r for r in self.graph()["receipts"] if r["receipt_id"] == h("refund-2"))
        refund["receipt"]["Action"]["actions"][0]["Transfer"]["deposit"] = "1"
        self.assert_closed(verify(self.node, self.d)[0], "REFUND_PRINCIPAL_LINKAGE")

    def test_gas_refund_cannot_stand_in_for_principal(self):
        refund = next(r for r in self.graph()["receipts"] if r["receipt_id"] == h("refund-2"))
        refund["receipt"]["Action"]["signer_id"] = self.d["vault"]
        self.assert_closed(verify(self.node, self.d)[0], "PRINCIPAL_REFUND_MISSING_OR_EXTRA")

    def test_tampered_native_success_with_failure_refund_is_inconsistent(self):
        native = next(o for o in self.graph()["receipts_outcome"] if o["id"] == h("native-2"))
        native["outcome"]["status"] = {"SuccessValue": ""}
        self.assert_closed(verify(self.node, self.d)[0], "FAKE_PRINCIPAL_REFUND")

    def test_tampered_transaction_identifier(self):
        self.graph()["transaction"]["hash"] = h("manipulated")
        self.assert_closed(verify(self.node, self.d)[0], "TRANSACTION_MISMATCH")

    def test_duplicate_outcome(self):
        self.graph()["receipts_outcome"].append(copy.deepcopy(self.graph()["receipts_outcome"][0]))
        self.assert_closed(verify(self.node, self.d)[0], "DUPLICATE_IDENTIFIER")

    def test_child_not_final_at_q(self):
        self.graph()["receipts_outcome"][1]["block_hash"] = h("later-than-q")
        self.assert_closed(verify(self.node, self.d)[0], "OUTCOME_OUTSIDE_CUT")

    def test_final_label_does_not_replace_missing_body(self):
        self.graph()["receipts"].pop(0)
        self.assert_closed(verify(self.node, self.d)[0], "MISSING_RECEIPT_BODY")

    def test_nonfinal_graph(self):
        self.graph()["final_execution_status"] = "EXECUTED"
        self.assert_closed(verify(self.node, self.d)[0], "NOT_FINAL")

    def test_callback_failure_does_not_change_native_success(self):
        graph = self.graph(1)
        callback = next(o for o in graph["receipts_outcome"] if o["id"] == h("callback-1"))
        callback["outcome"]["status"] = {"Failure": {"ActionError": "SYNTHETIC callback panic"}}
        result, _ = verify(self.node, self.d)
        self.assertEqual(result["chain_evidence_checks"], "PASS", result)
        self.assertEqual(result["recovery"]["ledger"]["S"], str(YOCTO))

    def test_callback_without_native_dependency_is_rejected(self):
        callback = next(r for r in self.graph()["receipts"] if r["receipt_id"] == h("callback-2"))
        callback["receipt"]["Action"]["input_data_ids"] = []
        self.assert_closed(verify(self.node, self.d)[0], "CALLBACK_DEPENDENCY")

    def test_query_cut_is_explicit(self):
        key = ("query", canonical({"request_type": "view_account", "account_id": self.d["vault"], "block_id": self.d["q_hash"]}))
        self.node.responses[key]["block_hash"] = h("different-cut")
        self.assert_closed(verify(self.node, self.d)[0], "QUERY_CUT")

    def test_unknown_history_cannot_be_empty(self):
        key = next(k for k in self.node.responses if k[0] == "EXPERIMENTAL_changes")
        del self.node.responses[key]
        self.assert_closed(verify(self.node, self.d)[0], "RPC_UNAVAILABLE")

    def test_vault_transient_key_is_detected(self):
        key = next(k for k in self.node.responses if k[0] == "EXPERIMENTAL_changes" and b"all_access_key_changes" in k[1])
        self.node.responses[key]["changes"] = [{"type": "access_key_update", "cause": {"type": "receipt_processing", "receipt_hash": h("creation-first")},
                                                "change": {"account_id": self.d["vault"]}}]
        self.assert_closed(verify(self.node, self.d)[0], "VAULT_KEY_HISTORY")

    def test_public_modes_have_no_sandbox_completeness(self):
        for network in ("testnet", "mainnet"):
            with self.subTest(network=network):
                self.d["network"] = network
                self.assert_closed(verify(self.node, self.d)[0], "PUBLIC_COMPLETENESS_UNSUPPORTED")

    def test_canonical_numbers_and_duplicate_json(self):
        for value in (1, "01", "+1", "1e1", " 1", "-1", "1.0", "١", str(2**128)):
            with self.subTest(value=value), self.assertRaises(EvidenceError):
                decimal(value)
        with self.assertRaises(EvidenceError):
            loads('{"root":1,"root":2}')
        with self.assertRaises(EvidenceError):
            loads('{"x":NaN}')


if __name__ == "__main__":
    unittest.main()
