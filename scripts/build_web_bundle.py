#!/usr/bin/env python3
"""Build web/public/bundle.json for the Attack Lab from committed run evidence.

  python3 scripts/build_web_bundle.py [RUN_ID ...]

Every chain fact in the bundle is re-derived here by replaying the run's committed raw RPC
responses (evidence/g1-independent/RUN/independent/rpc.jsonl.gz) through the verifier. The
runner's own log contributes only clearly labelled, untrusted fields: its stated intent and the
RPC errors for attempts the node rejected before they reached the chain.
"""
import gzip
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from packages.collector import b58, canonical, collect, decode64, digest, loads  # noqa: E402
from packages.verifier import analyze, verify  # noqa: E402
from packages.verifier.control import run_control  # noqa: E402
from packages.verifier.forge import ReplayNode, load_rpc_records  # noqa: E402

NEAR = 10**24


def read(p):
    return json.loads(Path(p).read_text())


def receipt_kind(r, graph_tx, d, parents):
    ab = r["receipt"]["Action"]
    a0 = ab["actions"][0]
    if r["predecessor_id"] == "system":
        return "principal_refund" if ab["signer_id"] == "system" else "gas_refund"
    if r["predecessor_id"] == d["vault"]:
        return "callback" if isinstance(a0, dict) and "FunctionCall" in a0 else "transfer"
    if r["receiver_id"] == d["vault"]:
        if a0 == "CreateAccount":
            return "construction"
        return "vault_call"
    return "account_setup"


def action_summary(r):
    out = []
    for a in r["receipt"]["Action"]["actions"]:
        if isinstance(a, str):
            out.append(a)
        elif "Transfer" in a:
            out.append(f"Transfer {int(a['Transfer']['deposit']) / NEAR:g} NEAR"
                       if int(a["Transfer"]["deposit"]) >= 10**18 else f"Transfer {a['Transfer']['deposit']} yocto")
        elif "FunctionCall" in a:
            out.append(f"FunctionCall {a['FunctionCall']['method_name']}")
        elif "DeployContract" in a:
            out.append("DeployContract sha256:" + decode64(a["DeployContract"]["code"]).hex()[:16] + "…")
        elif "AddKey" in a:
            perm = a["AddKey"]["access_key"]["permission"]
            out.append("AddKey " + ("FullAccess" if perm == "FullAccess" else "FunctionCall→request_payment"))
        else:
            out.append(next(iter(a)))
    return out


def status_of(o):
    st = o["outcome"]["status"]
    k = next(iter(st))
    if k == "Failure":
        text = canonical(st[k]).decode()
        for name in ("AccountDoesNotExist", "MethodNotFound", "Failed to deserialize input"):
            if name in text:
                return {"kind": "Failure", "detail": "MalformedInput" if name.startswith("Failed") else name}
        return {"kind": "Failure", "detail": text[:160]}
    return {"kind": "Success"}


def isolation_from_logs(run_dir, iso):
    """Recompute forwarded/denied runner methods from every reviewer filter-proxy log present."""
    entries = []
    for f in ("proxy-probe.jsonl", "proxy-submit.jsonl", "proxy-read.jsonl"):
        p = run_dir / "runner" / f
        if p.exists():
            entries += [json.loads(x) for x in p.read_text().splitlines()]
    return dict(iso, runner_methods_forwarded=sorted({e["method"] for e in entries if e.get("decision") == "forward"}),
                runner_methods_denied=sorted({e["method"] for e in entries if e.get("decision") == "deny"}))


def build_run(run_dir):
    run = run_dir.name
    d = read(run_dir / "reviewer-descriptor.json")
    summary = read(run_dir / "run-summary.json")
    records = load_rpc_records(run_dir / "independent/rpc.jsonl.gz")
    capture = collect(ReplayNode(records), d)
    rec = analyze(capture, d)
    heights = {b["header"]["hash"]: b["header"]["height"] for b in capture["blocks"]}
    runner = read(run_dir / "runner/runner-log.json")
    by_tx = {a["result"]["tx_hash"]: a for a in runner["attempts"]}
    payments = {p["tx_hash"]: p for p in rec["payments"]}
    denials = {x["tx_hash"]: x for x in rec["denials"]}
    failures = {x["tx_hash"]: x for x in rec["failed_calls"]}
    events_by_receipt = {e["receipt_id"]: e for e in rec["events"]}

    def tree(txid):
        g = capture["graphs"][txid]
        outs = {o["id"]: o for o in g["receipts_outcome"]}
        parents = {}
        for o in [g["transaction_outcome"]] + g["receipts_outcome"]:
            for c in o["outcome"]["receipt_ids"]:
                parents[c] = o["id"]
        nodes = []
        for r in g["receipts"]:
            o = outs[r["receipt_id"]]
            nodes.append({"id": r["receipt_id"], "parent": parents.get(r["receipt_id"]),
                          "kind": receipt_kind(r, g["transaction"], d, parents),
                          "predecessor": r["predecessor_id"], "receiver": r["receiver_id"],
                          "actions": action_summary(r), "status": status_of(o),
                          "block_height": heights[o["block_hash"]],
                          "event": (events_by_receipt.get(r["receipt_id"]) or {}).get("event")})
        nodes.sort(key=lambda n: (n["block_height"], n["kind"] != "vault_call"))
        return {"tx_hash": txid, "signer": g["transaction"]["signer_id"], "receiver": g["transaction"]["receiver_id"],
                "included_height": heights[capture["root_blocks"][txid]], "receipts": nodes}

    timeline = []
    for txid in sorted(capture["graphs"], key=lambda t: heights[capture["root_blocks"][t]]):
        g = capture["graphs"][txid]
        a = by_tx.get(txid)
        item = {"tx_hash": txid, "height": heights[capture["root_blocks"][txid]],
                "signer": g["transaction"]["signer_id"], "receiver": g["transaction"]["receiver_id"],
                "tree": tree(txid), "source": "verifier (independent capture)"}
        fc = [x["FunctionCall"] for x in g["transaction"]["actions"] if isinstance(x, dict) and "FunctionCall" in x]
        if a:
            item["runner_intent"] = {"label": a["label"], "intent": a["intent"], "expected": a["expected"],
                                     "source": "runner log (UNTRUSTED)"}
        if fc:
            item["method"] = fc[0]["method_name"]
            try:
                item["args"] = loads(decode64(fc[0]["args"]))
            except Exception:
                item["args_raw"] = decode64(fc[0]["args"]).decode(errors="replace")
        if txid in payments:
            p = payments[txid]
            item.update(decision="Admitted", request_id=p["request_id"], amount=p["amount"], recipient=p["recipient"],
                        settlement=p["class"], native_failure=p["native_failure"],
                        admission_seq=p["admission_seq"], callback=p["callback_observation"],
                        principal_refund=p.get("principal_refund_receipt"))
        elif txid in denials:
            x = denials[txid]
            item.update(decision="Denied", reason=x["reason"], request_id=x["request_id"], amount=x["amount"],
                        recipient=x["recipient"], seq=x["seq"])
        elif txid in failures:
            item.update(decision="ReceiptFailure", reason=failures[txid]["class"])
        elif g["transaction"]["receiver_id"] == d["vault"] and item.get("method") == "freeze":
            item.update(decision="Frozen")
        elif g["transaction"]["receiver_id"] == d["vault"]:
            item.update(decision="Construction")
        else:
            item.update(decision="Setup")
        timeline.append(item)
    # Attempts the node rejected before inclusion leave no chain trace: runner-reported only.
    offchain = [{"label": a["label"], "intent": a["intent"], "expected": a["expected"],
                 "tx_hash": a["result"]["tx_hash"],
                 "rpc_error": (a["result"].get("validation_rejected") or {}).get("data")
                 or (a["result"].get("validation_rejected") or {}).get("cause"),
                 "source": "runner log + filter-proxy log (no on-chain trace by construction)"}
                for a in runner["attempts"] if "validation_rejected" in a["result"]]
    # Corroborate against the reviewer's own filter-proxy record of node responses (runs made
    # after the C1 fix log submission response bodies; older runs stay runner-reported only).
    observed = []
    proxy_log = run_dir / "runner/proxy-submit.jsonl"
    if proxy_log.exists():
        for line in proxy_log.read_text().splitlines():
            e = json.loads(line)
            if e.get("method") == "send_tx" and "response" in e:
                try:
                    observed.append(canonical(json.loads(e["response"]).get("error")))
                except ValueError:
                    pass
    for o, a in zip(offchain, [a for a in runner["attempts"] if "validation_rejected" in a["result"]]):
        assert o["tx_hash"] not in capture["graphs"], "a validation-rejected attempt appeared on chain"
        o["observed_by_reviewer_proxy"] = canonical(a["result"]["validation_rejected"]) in observed
        if o["observed_by_reviewer_proxy"]:
            o["source"] = "node error recorded by the reviewer's filter proxy (and the runner log); no on-chain trace"
    code = decode64(capture["queries"]["vault/view_code"]["code_base64"])
    cmp_forged = read(run_dir / "compare-forged.json")
    omitted = [i for i in cmp_forged["issues"] if i["code"] == "OMITTED_ROOT"]
    mut = read(run_dir / "mutations.json")
    ret = run_dir / "retention-compare.json"
    construct = read(run_dir / "reviewer/construct.json")
    return {
        "run_id": run, "mode": "REPLAY", "network": "SANDBOX",
        "captured_at": summary["log"][0][:20] if summary.get("log") else None,
        "repo_commit": summary["repo_commit"],
        "node": summary["node"] | {"binary_sha256": d["node_binary_sha256"]},
        "artifact": {"wasm_sha256": hashlib.sha256(code).hexdigest(), "code_hash": b58(hashlib.sha256(code).digest()),
                     "bytes": len(code)},
        "policy": {"vault": d["vault"], "owner": d["owner"], "agent": d["agent"], "recipients": d["recipients"],
                   "budget": d["budget"], "max_per_request": d["max_per_request"],
                   "max_accepted_requests": d["max_accepted_requests"], "expires_at_ns": d["expires_at_ns"],
                   "policy_hash": d["policy_hash"], "chain_id": d["chain_id"],
                   "agent_keys": len(construct["agent_public_keys"]), "vault_keys": 0},
        "window": {"h0": {"hash": d["h0_hash"], "height": d["h0_height"]},
                   "q": {"hash": d["q_hash"], "height": d["q_height"]}},
        "verdicts_live": summary["independent"]["verdicts"],
        "frozen_at_q": any(e["event"] == "freeze" for e in rec["events"]),
        "ledger": rec["ledger"], "callback_observation": rec["callback_observation"],
        "events": rec["events"], "state_history": rec["state_history"],
        "timeline": timeline, "offchain_rejections": offchain,
        "isolation": isolation_from_logs(run_dir, summary["isolation"]),
        "omission": {"forged_verdicts": cmp_forged["verdicts"],
                     "omitted_tx_hash": [i["tx_hash"] for i in omitted],
                     "recovered_receipts": omitted[0]["recovered_receipts"] if omitted else [],
                     "recovered_payment": (omitted[0]["recovered_effects"]["payments"] if omitted else []),
                     "genuine_differences": summary["omission"]["genuine_presentation_differences"]},
        "mutations": [{"name": k, "rejected": v["rejected"], "issues": v["issues"]} for k, v in mut["mutations"].items()],
        "retention": (read(ret) | {"produced_blocks_after_q": summary["retention"]["produced_blocks_after_q"]})
        if ret.exists() else summary.get("retention"),
        "replay_check": {"capture_sha256": digest(capture), "rpc_records": len(records)},
        "sources": {k: f"evidence/g1-independent/{run}/{v}" for k, v in {
            "descriptor": "reviewer-descriptor.json", "summary": "run-summary.json",
            "raw_rpc": "independent/rpc.jsonl.gz", "independent_result": "independent/result.json",
            "runner_log": "runner/runner-log.json", "isolation": "runner/isolation.json",
            "forged_presentation": "runner/forged-presentation.json", "compare_forged": "compare-forged.json",
            "compare_genuine": "compare-genuine.json", "mutations": "mutations.json",
            "retention": "retention-compare.json"}.items()},
    }


def g2_target(run_dir, name):
    """Replay one protected G2 target through the verifier; return burst-level facts."""
    d = read(run_dir / name / "reviewer-descriptor.json")
    records = load_rpc_records(run_dir / name / "rpc.jsonl.gz")
    res, capture = verify(ReplayNode(records), d)
    assert res["chain_evidence_checks"] == "PASS", res["issues"]
    rec = res["recovery"]
    h = {b["header"]["hash"]: b["header"]["height"] for b in capture["blocks"]}
    reqs = []
    for p in rec["payments"]:
        reqs.append({"request_id": p["request_id"], "decision": "Admitted", "seq": int(p["admission_seq"]),
                     "height": h[p["admission_block"]], "transfer_height": h[p["execution_block"]],
                     "amount": p["amount"], "settlement": p["class"], "tx_hash": p["tx_hash"]})
    for x in rec["denials"]:
        reqs.append({"request_id": x["request_id"], "decision": "Denied", "reason": x["reason"], "seq": int(x["seq"]),
                     "height": h[x["block_hash"]], "amount": x["amount"], "charged_at_decision": x["charged_at_decision"],
                     "tx_hash": x["tx_hash"]})
    reqs.sort(key=lambda r: r["seq"])
    return {"vault": d["vault"], "budget": d["budget"], "max_per_request": d["max_per_request"],
            "max_accepted_requests": d["max_accepted_requests"], "agent_keys": d["agent_key_count"],
            "computed_if_live": res["computed_if_live"], "verdicts_live": read(run_dir / name / "result.json")["verdicts"],
            "ledger": rec["ledger"], "requests": reqs, "pending_witness": rec["pending_witness"],
            "replay_capture_sha256": digest(capture), "rpc_records": len(records)}


def g2_control(run_dir):
    d = read(run_dir / "vulnerable/control-descriptor.json")
    res, _ = run_control(ReplayNode(load_rpc_records(run_dir / "vulnerable/rpc.jsonl.gz")), d)
    assert not res["issues"], res["issues"]
    return {k: res[k] for k in ("label", "vault", "budget", "admissions", "denials", "delivered_principal", "overspend",
                                "budget_exceeded_on_chain", "admissions_per_block", "stale_settled_seen", "transfers")}


def build_g2(run_dir):
    s = read(run_dir / "run-summary.json")
    return {"run_id": run_dir.name, "mode": "REPLAY", "network": "SANDBOX", "repo_commit": s["repo_commit"],
            "node": s["node"], "isolation": s["isolation"], "elapsed_seconds": s["elapsed_seconds"],
            "fixture_wasm_sha256": s["fixture_wasm_sha256"], "wasm_sha256": s["wasm_sha256"],
            "protected": g2_target(run_dir, "protected"), "generous": g2_target(run_dir, "generous"),
            "vulnerable": g2_control(run_dir),
            "sources": {"summary": f"evidence/g2-independent/{run_dir.name}/run-summary.json",
                        "fixture_source": "fixtures/vulnerable-settled-only/src/lib.rs"}}


def main():
    root = REPO / "evidence/g1-independent"
    # Newest first: the most recent run (on the latest tooling) is the default view.
    names = sys.argv[1:] or sorted((p.name for p in root.glob("g1i-*") if "-dev-" not in p.name
                                    and (p / "run-summary.json").exists()), reverse=True)
    bundle = {"schema": "pursewarden-bundle/v1",
              "note": "Every chain fact below was re-derived by replaying committed raw RPC responses through "
                      "the verifier (packages/verifier). Provenance: REPLAY of local SANDBOX runs.",
              "runs": [build_run(root / n) for n in names],
              "g2_runs": [build_g2(p) for p in sorted((REPO / "evidence/g2-independent").glob("g2i-*"), reverse=True)
                          if "-dev-" not in p.name and (p / "run-summary.json").exists()
                          and not (p / "SUPERSEDED").exists()]}
    out = REPO / "web/public/bundle.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(bundle, indent=1, sort_keys=False) + "\n"
    out.write_text(data)
    print(f"wrote {out.relative_to(REPO)} ({len(data)} bytes) runs={names} sha256={hashlib.sha256(data.encode()).hexdigest()}")


if __name__ == "__main__":
    main()
