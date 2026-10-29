"""Generate SYNTHETIC regression artifacts. This does not run a NEAR chain."""
import argparse
import copy
import json
import platform
import tempfile
from pathlib import Path

from packages.collector import Rpc, canonical, digest
from packages.verifier import verify
from tests.evidence.fixture import fixture, h
from tests.evidence.test_verifier import remove_entire_root
from tests.evidence.transport import fake_rpc


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    descriptor, node = fixture()
    results = {"warning": "SYNTHETIC: no NEAR node, contract deployment or chain transactions",
               "python": platform.python_version(), "platform": platform.platform(), "cases": {}}
    with tempfile.TemporaryDirectory() as td, fake_rpc(node) as endpoint:
        baseline_rpc = Rpc(endpoint, "sandbox", Path(td)/"baseline")
        baseline_rpc.mode = "SYNTHETIC"
        baseline, capture = verify(baseline_rpc, descriptor)
        baseline["metrics"] = baseline_rpc.metrics()
        forged = remove_entire_root(capture, h("payment-2"))
        mutation_rpc = Rpc(endpoint, "sandbox", Path(td)/"omission")
        mutation_rpc.mode = "SYNTHETIC"
        omission, recovered = verify(mutation_rpc, descriptor, forged)
        omission["metrics"] = mutation_rpc.metrics()
        results["cases"]["complete_synthetic_oracle"] = baseline
        results["cases"]["whole_root_omission_rehashed"] = omission
        for label in ("baseline", "omission"):
            with (out / f"{label}-rpc.jsonl").open("wb") as f:
                for path in sorted((Path(td)/label).glob("*.json")):
                    f.write(path.read_bytes())
    write(out/"reviewer-descriptor.SYNTHETIC.json", descriptor)
    write(out/"independent-capture.SYNTHETIC.json", capture)
    write(out/"forged-root-omission.SYNTHETIC.json", forged)
    for name in ("wrong_chain", "wrong_genesis", "wrong_contract", "pruned_block", "missing_outcome", "fake_refund", "tampered_bundle_outcome"):
        d, source = fixture()
        presented = None
        if name == "wrong_chain":
            source.responses[("status", canonical({}))]["chain_id"] = "mainnet"
        elif name == "wrong_genesis":
            source.responses[("block", canonical({"block_id": 0}))]["header"]["hash"] = h("other-genesis")
        elif name == "wrong_contract":
            key = ("query", canonical({"request_type": "view_code", "account_id": d["vault"], "block_id": d["q_hash"]}))
            source.responses[key]["code_base64"] = "ZmFrZQ=="
        elif name == "pruned_block":
            del source.responses[("block", canonical({"block_id": h("block-14")}))]
        else:
            key = ("EXPERIMENTAL_tx_status", canonical({"tx_hash": h("payment-2"), "sender_account_id": d["agent"], "wait_until": "FINAL"}))
            graph = source.responses[key]
            if name == "missing_outcome":
                graph["receipts_outcome"] = [o for o in graph["receipts_outcome"] if o["id"] != h("native-2")]
            elif name == "fake_refund":
                receipt = next(r for r in graph["receipts"] if r["receipt_id"] == h("refund-2"))
                receipt["receipt"]["Action"]["actions"][0]["Transfer"]["deposit"] = "1"
            else:
                presented = copy.deepcopy(capture)
                presented["graphs"][h("payment-2")]["receipts_outcome"][1]["outcome"]["status"] = {"SuccessValue": ""}
                presented["checksum_sha256"] = digest(presented)
        result, _ = verify(source, d, presented)
        results["cases"][name] = result
    write(out/"results.SYNTHETIC.json", results)
    manifest = {p.name: __import__("hashlib").sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir())}
    write(out/"sha256.json", manifest)
    print(json.dumps({"out": str(out), "cases": {k: v["verdicts"]["evidence"] for k, v in results["cases"].items()}}, indent=2))


if __name__ == "__main__":
    main()
