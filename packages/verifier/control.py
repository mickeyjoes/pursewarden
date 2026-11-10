"""Independent outflow audit for G2 CONTROL vaults (the deliberately vulnerable fixture).

Uses the same reviewer-pinned identity checks, bounded window walk and chunk-based root
discovery as the protected-vault collector (no runner-supplied hashes). It does not decode the
fixture's storage. It counts what actually left the fixture account, taken from native Transfer
receipt outcomes, and compares that with the fixture's configured budget. Labelled CONTROL:
this is a teaching fixture, not a product and not any other project's code.
"""
import hashlib
import json
import re

from packages.collector import (EvidenceError, absent_at, account, check_identity, decimal, decode64,
                                digest, discover_roots, hash_id, require, walk_window)
from packages.verifier import action_body, graph_check, outcome_kind

SCHEMA = "near-g2-control/v1"


def validate_control_descriptor(d):
    require(d.get("schema") == SCHEMA and d.get("network") == "sandbox", "CONTROL_DESCRIPTOR", d.get("schema"))
    for name in ("genesis_block_hash", "h0_hash", "q_hash"):
        hash_id(d[name])
    account(d["vault"])
    decimal(d["budget"])
    require(re.fullmatch(r"[0-9a-f]{64}", d["wasm_sha256"]) is not None, "DIGEST_REQUIRED", "wasm_sha256")
    require(type(d["max_blocks"]) is int and 1 <= d["max_blocks"] <= 10000, "BLOCK_BOUND", d["max_blocks"])
    require(type(d["max_roots"]) is int and 1 <= d["max_roots"] <= 10000, "ROOT_BOUND", d["max_roots"])


def control_capture(source, d):
    validate_control_descriptor(d)
    status, genesis, gblock = check_identity(source, d)
    final, blocks, protocol = walk_window(source, d)
    absence = absent_at(source, d["vault"], d["h0_hash"], d["h0_height"])
    chunks, roots, root_blocks, graphs = discover_roots(source, d, blocks)
    code = source.call("query", {"request_type": "view_code", "account_id": d["vault"], "block_id": d["q_hash"]})
    keys = source.call("query", {"request_type": "view_access_key_list", "account_id": d["vault"],
                                 "block_id": d["q_hash"]})
    state = source.call("query", {"request_type": "call_function", "account_id": d["vault"],
                                  "method_name": "get_state", "args_base64": "e30=", "block_id": d["q_hash"]})
    return {"schema": "near-g2-control-capture/v1", "mode": source.mode, "descriptor_sha256": digest(d),
            "status": status, "genesis": genesis, "genesis_block": gblock, "final_head": final,
            "blocks": blocks, "protocol": protocol, "initial_absence": absence, "chunks": chunks,
            "root_blocks": root_blocks, "graphs": graphs,
            "queries": {"view_code": code, "view_access_key_list": keys, "get_state": state}}


def control_audit(capture, d):
    require(capture["descriptor_sha256"] == digest(d), "DESCRIPTOR_BINDING", "control capture")
    heights = {b["header"]["hash"]: b["header"]["height"] for b in capture["blocks"]}
    q = capture["queries"]
    require(hashlib.sha256(decode64(q["view_code"]["code_base64"])).hexdigest() == d["wasm_sha256"],
            "WRONG_CONTRACT", "fixture code")
    require(q["view_access_key_list"]["keys"] == [], "VAULT_HAS_KEYS", d["vault"])
    seen, transfers, admissions, denials = set(), [], [], []
    for txid, graph in sorted(capture["graphs"].items()):
        bodies, outcomes, parents = graph_check(txid, graph, capture["root_blocks"][txid], heights, seen)
        for rid, r in bodies.items():
            out = outcomes[rid]
            if r["receiver_id"] == d["vault"] and r["predecessor_id"] != "system" and outcome_kind(out) != "Failure":
                for line in out["outcome"]["logs"]:
                    if line.startswith("FIXTURE_EVENT:"):
                        ev = json.loads(line[len("FIXTURE_EVENT:"):])
                        item = {"tx_hash": txid, "receipt_id": rid, "height": heights[out["block_hash"]],
                                **ev["data"]}
                        (admissions if ev["event"] == "admission" else denials).append(item)
            if r["predecessor_id"] != d["vault"]:
                continue
            actions = action_body(r)["actions"]
            if len(actions) == 1 and isinstance(actions[0], dict) and set(actions[0]) == {"Transfer"}:
                transfers.append({"tx_hash": txid, "receipt_id": rid, "recipient": r["receiver_id"],
                                  "amount": decimal(actions[0]["Transfer"]["deposit"]),
                                  "outcome": outcome_kind(out), "execution_height": heights[out["block_hash"]],
                                  "parent_height": heights[outcomes[parents[rid]]["block_hash"]]})
    delivered = sum(t["amount"] for t in transfers if t["outcome"] != "Failure")
    budget = int(d["budget"])
    by_height = {}
    for a in admissions:
        by_height.setdefault(a["height"], []).append(a)
    return {"schema": "near-g2-control-result/v1", "mode": capture["mode"], "label": "CONTROL (vulnerable teaching fixture)",
            "vault": d["vault"], "budget": str(budget), "roots": len(capture["graphs"]),
            "admissions": len(admissions), "denials": len(denials),
            "transfers": [dict(t, amount=str(t["amount"])) for t in transfers],
            "delivered_principal": str(delivered), "overspend": str(max(0, delivered - budget)),
            "budget_exceeded_on_chain": delivered > budget,
            "admissions_per_block": {str(h): len(v) for h, v in sorted(by_height.items())},
            "stale_settled_seen": sorted({a.get("settled_seen") for a in admissions}),
            "fixture_view_at_q": json.loads(bytes(q["get_state"]["result"]))}


def run_control(source, d):
    result = {"schema": "near-g2-control-result/v1", "issues": []}
    capture = None
    try:
        capture = control_capture(source, d)
        result = control_audit(capture, d)
        result["issues"] = []
    except EvidenceError as exc:
        result["issues"].append({"code": exc.code, "detail": exc.detail, "verdict": exc.verdict})
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        result["issues"].append({"code": "UNSUPPORTED_OR_MALFORMED_SCHEMA", "detail": repr(exc)})
    return result, capture
