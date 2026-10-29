"""No wallet, private key, transaction construction or submission APIs."""
import argparse
import json
from pathlib import Path

from packages.collector import (EvidenceError, Rpc, canonical, digest, local_provenance,
                                read_json, validate_descriptor)
from packages.verifier import verify


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--network", required=True, choices=["sandbox", "testnet", "mainnet"])
    p.add_argument("--rpc", required=True)
    p.add_argument("--descriptor", required=True)
    p.add_argument("--out", required=True, help="new directory; never overwrites a run")
    p.add_argument("--presented", help="untrusted runner capture, optional")
    p.add_argument("--wasm")
    p.add_argument("--node-binary")
    p.add_argument("--node-config")
    p.add_argument("--genesis-file")
    p.add_argument("--inspect-only", action="store_true")
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    source = None
    result = {"schema": "near-g1-result/v1", "verdicts": {k: "INCONCLUSIVE" for k in
              ("safety", "settlement", "evidence", "scenario_coverage")}, "issues": []}
    try:
        d = read_json(args.descriptor)
        validate_descriptor(d)
        if d["network"] != args.network:
            raise EvidenceError("NETWORK_MISMATCH", "CLI and descriptor disagree", "FAIL")
        source = Rpc(args.rpc, args.network, out / "rpc")
        (out / "reviewer-descriptor.json").write_bytes(canonical(d) + b"\n")
        if args.inspect_only:
            status = source.call("status", {})
            genesis = source.call("EXPERIMENTAL_genesis_config", {})
            genesis_block = source.call("block", {"block_id": genesis["genesis_height"]})
            if (status["chain_id"] != d["chain_id"] or genesis["chain_id"] != d["chain_id"]
                or genesis_block["header"]["hash"] != d["genesis_block_hash"]
                or status["version"] != d["node_version"] or digest(genesis) != d["genesis_rpc_sha256"]):
                raise EvidenceError("WRONG_CHAIN", "inspection identity mismatch", "FAIL")
            result["inspection"] = {"status": status, "genesis": genesis, "genesis_block": genesis_block}
            result["issues"].append({"code": "INSPECTION_ONLY", "detail": "No completeness or enforcement verdict"})
        else:
            provenance = local_provenance(d, {"wasm": args.wasm, "node_binary": args.node_binary,
                              "node_config": args.node_config, "genesis_file": args.genesis_file})
            presented = read_json(args.presented) if args.presented else None
            result, capture = verify(source, d, presented)
            result["local_provenance"] = provenance
            if capture is not None:
                (out / "independent-capture.json").write_bytes(canonical(capture) + b"\n")
                result["capture_sha256"] = digest(capture)
    except EvidenceError as exc:
        result["issues"].append({"code": exc.code, "detail": exc.detail})
        result["verdicts"]["evidence"] = exc.verdict
    except (OSError, TypeError, KeyError, ValueError, RecursionError, OverflowError) as exc:
        result["issues"].append({"code": "CONFIG_OR_INPUT_UNAVAILABLE", "detail": str(exc)})
    if source:
        result["metrics"] = source.metrics()
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 1 if "FAIL" in result["verdicts"].values() else 2


if __name__ == "__main__":
    raise SystemExit(main())
