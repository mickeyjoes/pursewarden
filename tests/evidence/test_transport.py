import tempfile
import unittest
from pathlib import Path

from packages.collector import EvidenceError, Rpc, canonical, local_provenance, read_json
from packages.verifier import verify
from tests.evidence.fixture import fixture, h
from tests.evidence.transport import fake_rpc


class TransportTests(unittest.TestCase):
    def test_read_only_rpc_and_raw_acquisition(self):
        descriptor, node = fixture()
        with tempfile.TemporaryDirectory() as td, fake_rpc(node) as endpoint:
            rpc = Rpc(endpoint, "sandbox", Path(td)/"rpc")
            rpc.mode = "SYNTHETIC"
            result, capture = verify(rpc, descriptor)
            self.assertEqual(result["chain_evidence_checks"], "PASS", result)
            self.assertEqual(capture["mode"], "SYNTHETIC")
            self.assertEqual(len(list((Path(td)/"rpc").glob("*.json"))), rpc.count)
            self.assertGreater(rpc.metrics()["response_bytes"], 0)
            self.assertTrue(all(v == "INCONCLUSIVE" for v in result["verdicts"].values()))
            count = rpc.count
            with self.assertRaises(EvidenceError):
                rpc.call("broadcast_tx_commit", {"signed_tx_base64": ""})
            self.assertEqual(rpc.count, count)

    def test_missing_provenance_has_no_fallback(self):
        descriptor, _ = fixture()
        with self.assertRaises(EvidenceError) as caught:
            local_provenance(descriptor, {})
        self.assertEqual(caught.exception.code, "PROVENANCE_MISSING")

    def test_typed_no_contract_code_is_recorded_without_invented_body(self):
        descriptor, node = fixture()
        params = {"request_type": "view_code", "account_id": descriptor["agent"], "block_id": descriptor["q_hash"]}
        node.responses[("query", canonical(params))] = EvidenceError("RPC_UNAVAILABLE", {
            "error": {"cause": {"name": "NO_CONTRACT_CODE", "info": {
                "contract_account_id": descriptor["agent"], "block_hash": descriptor["q_hash"], "block_height": descriptor["q_height"]}}}})
        result, capture = verify(node, descriptor)
        self.assertEqual(result["chain_evidence_checks"], "PASS", result)
        self.assertNotIn("code_base64", capture["queries"]["agent/view_code"])

    def test_sandbox_endpoint_must_be_loopback(self):
        with tempfile.TemporaryDirectory() as td, self.assertRaises(EvidenceError):
            Rpc("https://rpc.mainnet.near.org", "sandbox", Path(td)/"rpc")

    def test_gc_is_not_account_absence(self):
        descriptor, node = fixture()
        params = {"request_type": "view_account", "account_id": descriptor["vault"], "block_id": descriptor["h0_hash"]}
        node.responses[("query", canonical(params))] = EvidenceError("RPC_UNAVAILABLE", {
            "error": {"cause": {"name": "GARBAGE_COLLECTED_BLOCK", "info": {"block_hash": descriptor["h0_hash"]}}}})
        result, _ = verify(node, descriptor)
        self.assertEqual(result["verdicts"]["evidence"], "INCONCLUSIVE")
        self.assertEqual(result["issues"][0]["code"], "RPC_UNAVAILABLE")

    def test_preexisting_vault_is_rejected(self):
        descriptor, node = fixture()
        params = {"request_type": "view_account", "account_id": descriptor["vault"], "block_id": descriptor["h0_hash"]}
        node.responses[("query", canonical(params))] = {"amount": "1"}
        result, _ = verify(node, descriptor)
        self.assertEqual(result["issues"][0]["code"], "ACCOUNT_PREEXISTS_H0")

    def test_protocol_shard_mismatch_is_rejected(self):
        descriptor, node = fixture()
        descriptor["shard_ids"] = [0]
        result, _ = verify(node, descriptor)
        self.assertEqual(result["issues"][0]["code"], "PROTOCOL_SHARDS")

    def test_unknown_state_cause_stops(self):
        descriptor, node = fixture()
        key = next(k for k in node.responses if k[0] == "EXPERIMENTAL_changes" and node.responses[k]["changes"])
        node.responses[key]["changes"][0]["cause"] = {"type": "sandbox_patch"}
        result, _ = verify(node, descriptor)
        self.assertEqual(result["issues"][0]["code"], "UNEXPECTED_STATE_CAUSE")

    def test_state_change_without_root_linkage_stops(self):
        descriptor, node = fixture()
        key = next(k for k in node.responses if k[0] == "EXPERIMENTAL_changes" and node.responses[k]["changes"])
        node.responses[key]["changes"][0]["cause"]["receipt_hash"] = h("unknown-origin")
        result, _ = verify(node, descriptor)
        self.assertEqual(result["issues"][0]["code"], "STATE_CAUSE_UNMAPPED")

    def test_rpc_method_cannot_be_supplied_by_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            rpc = Rpc("http://127.0.0.1:1", "sandbox", Path(td)/"rpc")
            with self.assertRaises(EvidenceError):
                rpc.call("sandbox_patch_state", {})
            self.assertEqual(rpc.count, 0)


if __name__ == "__main__":
    unittest.main()
