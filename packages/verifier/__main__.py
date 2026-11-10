"""No wallet, private key, transaction construction or submission APIs.

Subcommands (the first form is the original reviewer acquisition interface):

  python3 -m packages.verifier --network sandbox --rpc URL --descriptor D --wasm W \\
      --node-binary B --node-config C --genesis-file G --out NEW_DIR [--presented P]
  python3 -m packages.verifier collect --network sandbox --rpc URL --descriptor D --out NEW_DIR
      (an UNTRUSTED presentation capture, e.g. produced by the runner; no provenance files)
  python3 -m packages.verifier compare --capture C --descriptor D --presented P --out FILE
      (offline: the independent capture never sees the presentation during acquisition)
  python3 -m packages.verifier mutate --rpc-records R --descriptor D --out FILE
  python3 -m packages.verifier export-rpc --raw-dir DIR --out FILE.jsonl.gz
"""
import argparse
import json
import sys
from pathlib import Path

from packages.collector import (EvidenceError, Rpc, canonical, collect, digest, local_provenance,
                                read_json, validate_descriptor)
from packages.verifier import evaluate, verify
from packages.verifier.forge import export_rpc_records, load_rpc_records, run_mutations


def exit_code(result):
    v = result["verdicts"].values()
    if "FAIL" in v:
        return 1
    return 0 if all(x == "PASS" for x in v) else 2


def acquire(argv):
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
    args = p.parse_args(argv)
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
    print(json.dumps({k: result.get(k) for k in ("verdicts", "chain_evidence_checks", "issues", "metrics")}, indent=2))
    return exit_code(result)


def collect_cmd(argv):
    p = argparse.ArgumentParser(prog="collect")
    p.add_argument("--network", required=True, choices=["sandbox"])
    p.add_argument("--rpc", required=True)
    p.add_argument("--descriptor", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=False)
    d = read_json(a.descriptor)
    source = Rpc(a.rpc, a.network, out / "rpc")
    capture = collect(source, d)
    capture["presentation_note"] = "UNTRUSTED presentation capture; not a reviewer acquisition"
    (out / "presented-capture.json").write_bytes(canonical(capture) + b"\n")
    print(json.dumps({"roots": len(capture["graphs"]), "metrics": source.metrics()}))
    return 0


def compare_cmd(argv):
    p = argparse.ArgumentParser(prog="compare")
    p.add_argument("--capture", required=True, help="the reviewer's own independent capture")
    p.add_argument("--descriptor", required=True)
    p.add_argument("--presented", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    capture, d, presented = read_json(a.capture), read_json(a.descriptor), read_json(a.presented)
    validate_descriptor(d)
    result = {"schema": "near-g1-compare/v1", "capture_sha256": digest(capture),
              "presented_sha256": digest(presented), "mode": capture.get("mode")}
    result.update(evaluate(capture, d, capture.get("mode"), presented))
    Path(a.out).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"verdicts": result["verdicts"],
                      "differences": [{k: v for k, v in i.items() if k != "recovered_effects"}
                                      for i in result["issues"]]}, indent=2))
    return exit_code(result)


def mutate_cmd(argv):
    p = argparse.ArgumentParser(prog="mutate")
    p.add_argument("--rpc-records", required=True)
    p.add_argument("--descriptor", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    d = read_json(a.descriptor)
    records = load_rpc_records(a.rpc_records)
    from packages.verifier.forge import ReplayNode
    baseline, _ = verify(ReplayNode(records), d)
    results = run_mutations(records, d, verify)
    summary = {"schema": "near-g1-mutations/v1", "source": "REPLAY of genuine recorded RPC responses",
               "baseline": {"chain_evidence_checks": baseline["chain_evidence_checks"],
                            "computed_if_live": baseline.get("computed_if_live"),
                            "issues": [i["code"] for i in baseline["issues"]]},
               "mutations": results,
               "all_applied_and_rejected": all(r["applied"] and r["rejected"] for r in results.values())}
    Path(a.out).write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"baseline": summary["baseline"]["chain_evidence_checks"],
                      "rejected": {k: r["rejected"] for k, r in results.items()},
                      "all_applied_and_rejected": summary["all_applied_and_rejected"]}, indent=2))
    ok = summary["all_applied_and_rejected"] and baseline["chain_evidence_checks"] == "PASS"
    return 0 if ok else 1


def control_cmd(argv):
    """Independent outflow audit of a G2 CONTROL (vulnerable fixture) vault."""
    from packages.verifier.control import run_control
    p = argparse.ArgumentParser(prog="control")
    p.add_argument("--network", required=True, choices=["sandbox"])
    p.add_argument("--rpc", required=True)
    p.add_argument("--descriptor", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=False)
    d = read_json(a.descriptor)
    source = Rpc(a.rpc, a.network, out / "rpc")
    result, capture = run_control(source, d)
    result["metrics"] = source.metrics()
    if capture is not None:
        (out / "control-capture.json").write_bytes(canonical(capture) + b"\n")
        result["capture_sha256"] = digest(capture)
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result.get(k) for k in ("label", "admissions", "denials", "delivered_principal",
                                                  "overspend", "admissions_per_block", "issues")}, indent=2))
    return 0 if not result["issues"] else 1


def main():
    argv = sys.argv[1:]
    commands = {"collect": collect_cmd, "compare": compare_cmd, "mutate": mutate_cmd, "control": control_cmd,
                "export-rpc": lambda a: (print(export_rpc_records(*_export_args(a))), 0)[1]}
    if argv and argv[0] in commands:
        return commands[argv[0]](argv[1:])
    return acquire(argv)


def _export_args(argv):
    p = argparse.ArgumentParser(prog="export-rpc")
    p.add_argument("--raw-dir", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    return a.raw_dir, a.out


if __name__ == "__main__":
    raise SystemExit(main())
