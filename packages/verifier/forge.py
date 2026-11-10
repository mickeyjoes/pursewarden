"""ADVERSARIAL TEST TOOLING. Never evidence.

* `ReplayNode` serves previously recorded raw RPC responses (mode REPLAY; never a runtime PASS).
* `omit_request_root` is the forger: it removes an entire genuine transaction root, all its
  descendants and refunds, the matching rows/records/history from a presented capture and
  recomputes every checksum, exactly as a dishonest runner could.
* `MUTATIONS` tamper with genuine recorded RPC responses; none may yield a complete PASS.
"""

import base64
import copy
import hashlib
import gzip
import json
from pathlib import Path

from packages.collector import EvidenceError, b58, canonical, decode64, digest, loads


def load_rpc_records(path):
    """Read a collector raw directory (NNNNNN.json files) or a .jsonl/.jsonl.gz export."""
    p = Path(path)
    if p.is_dir():
        lines = [f.read_bytes() for f in sorted(p.glob("*.json"))]
    else:
        opener = gzip.open if p.suffix == ".gz" else open
        with opener(p, "rb") as f:
            lines = [line for line in f.read().splitlines() if line.strip()]
    return [loads(line) for line in lines]


def export_rpc_records(raw_dir, out_path):
    """Pack a collector raw directory into one gzip JSONL file (deterministic order)."""
    records = load_rpc_records(raw_dir)
    with gzip.GzipFile(out_path, "wb", mtime=0) as f:
        for r in records:
            f.write(canonical(r) + b"\n")
    return len(records)


class ReplayNode:
    mode = "REPLAY"

    def __init__(self, records):
        self.responses = {}
        for rec in records:
            req = rec["request"]
            if "response_base64" not in rec:
                continue
            resp = loads(base64.b64decode(rec["response_base64"]))
            self.responses[(req["method"], canonical(req["params"]))] = resp
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))
        key = (method, canonical(params))
        if key not in self.responses:
            raise EvidenceError("RPC_UNAVAILABLE", {"method": method, "params": params,
                                                   "error": "not in replay"})
        resp = self.responses[key]
        if "error" in resp:
            raise EvidenceError("RPC_UNAVAILABLE", {"method": method, "params": params, "error": resp["error"]})
        return copy.deepcopy(resp["result"])

    # Helpers for mutations ----------------------------------------------------------------
    def find(self, method, pred=lambda params, result: True):
        for (m, p), resp in self.responses.items():
            if m == method and "result" in resp and pred(loads(p), resp["result"]):
                return (m, p)
        raise KeyError(method)

    def result(self, key):
        return self.responses[key]["result"]


def _tx_request_id(graph):
    for a in graph["transaction"]["actions"]:
        if isinstance(a, dict) and "FunctionCall" in a and a["FunctionCall"]["method_name"] == "request_payment":
            return loads(decode64(a["FunctionCall"]["args"])).get("request_id")
    return None


def find_request_root(capture, request_id, admitted_only=True):
    found = [t for t, g in capture["graphs"].items() if _tx_request_id(g) == request_id
             and (not admitted_only or any(r["predecessor_id"] == capture_vault(capture)
                                           for r in g["receipts"]))]
    if len(found) != 1:
        raise KeyError(f"request {request_id}: {found}")
    return found[0]


def capture_vault(capture):
    return loads(bytes(capture["queries"]["get_mandate"]["result"]))["vault"]


def omit_request_root(capture, request_id):
    """Forge a presentation without request `request_id`'s admitted root (the runner's lie)."""
    forged = copy.deepcopy(capture)
    txid = find_request_root(capture, request_id)
    graph = forged["graphs"].pop(txid)
    forged["root_blocks"].pop(txid)
    gone = {txid} | {r["receipt_id"] for r in graph["receipts"]}
    for chunk in forged["chunks"].values():
        chunk["transactions"] = [t for t in chunk["transactions"] if t["hash"] != txid]
    for entry in forged["history"]:
        entry["result"]["changes"] = [c for c in entry["result"]["changes"]
                                      if c["cause"].get("receipt_hash") not in gone
                                      and c["cause"].get("tx_hash") not in gone]
    amount = 0
    rows = loads(bytes(forged["queries"]["get_admissions"]["result"]))
    for r in rows:
        if r["request_id"] == request_id:
            amount = int(r["amount"])
    forged["queries"]["get_admissions"]["result"] = list(canonical([r for r in rows if r["request_id"] != request_id]))
    mandate = loads(bytes(forged["queries"]["get_mandate"]["result"]))
    mandate["charged"] = str(int(mandate["charged"]) - amount)
    mandate["headroom"] = str(int(mandate["headroom"]) + amount)
    mandate["accepted_count"] -= 1
    forged["queries"]["get_mandate"]["result"] = list(canonical(mandate))
    rid_key = base64.b64encode(b"r" + int(request_id).to_bytes(8, "little")).decode()
    forged["queries"]["vault/view_state"]["values"] = [
        v for v in forged["queries"]["vault/view_state"]["values"] if v["key"] != rid_key]
    # A runner can also drop its own rows and rehash; neither is a trust anchor.
    forged["checksums"] = {k: digest(forged[k]) for k in ("graphs", "chunks", "history", "queries")}
    forged["checksum_sha256"] = digest(forged)
    forged["claimed_verdicts"] = {"evidence": "PASS", "safety": "PASS"}
    return forged, txid


# --------------------------------------------------------------------------------------------
# Mutations of genuine recorded RPC responses
# --------------------------------------------------------------------------------------------

def _tx_status_key(node, request_id):
    return node.find("EXPERIMENTAL_tx_status",
                     lambda p, r: _tx_request_id(r) == request_id
                     and any(x["predecessor_id"] != "system" and x["receiver_id"] != r["transaction"]["receiver_id"]
                             for x in r["receipts"]))


def _native(graph, vault):
    return next(r for r in graph["receipts"] if r["predecessor_id"] == vault
                and "Transfer" in r["receipt"]["Action"]["actions"][0])


def _outcome(graph, rid):
    return next(o for o in graph["receipts_outcome"] if o["id"] == rid)


def _mut_tx(node, d, request_id, fn):
    key = _tx_status_key(node, request_id)
    fn(node.result(key), d)


def m_genesis(node, d):
    key = node.find("block", lambda p, r: p.get("block_id") == 0 or r["header"]["height"] == 0)
    node.result(key)["header"]["hash"] = "11111111111111111111111111111111"


def m_chain_id(node, d):
    node.result(node.find("status"))["chain_id"] = "test-chain-FORGED"


def m_artifact(node, d):
    key = node.find("query", lambda p, r: p.get("request_type") == "view_code" and p.get("account_id") == d["vault"])
    code = bytearray(base64.b64decode(node.result(key)["code_base64"]))
    code[-1] ^= 1
    node.result(key)["code_base64"] = base64.b64encode(bytes(code)).decode()


def m_vault_identity(node, d):
    key = node.find("query", lambda p, r: p.get("method_name") == "get_mandate")
    m = loads(bytes(node.result(key)["result"]))
    m["vault"] = "vault2.owner.test.near"
    node.result(key)["result"] = list(canonical(m))


def m_amount(node, d):
    def f(g, d):
        _native(g, d["vault"])["receipt"]["Action"]["actions"][0]["Transfer"]["deposit"] = "1000000000000000000000000"
    _mut_tx(node, d, "2", f)


def m_outcome(node, d):
    def f(g, d):
        _outcome(g, _native(g, d["vault"])["receipt_id"])["outcome"]["status"] = {"SuccessValue": ""}
    _mut_tx(node, d, "2", f)


def m_refund_removed(node, d):
    def f(g, d):
        native = _native(g, d["vault"])
        out = _outcome(g, native["receipt_id"])
        refund = next(r for r in g["receipts"] if r["predecessor_id"] == "system"
                      and r["receipt"]["Action"]["signer_id"] == "system")
        out["outcome"]["receipt_ids"].remove(refund["receipt_id"])
        g["receipts"] = [r for r in g["receipts"] if r["receipt_id"] != refund["receipt_id"]]
        g["receipts_outcome"] = [o for o in g["receipts_outcome"] if o["id"] != refund["receipt_id"]]
    _mut_tx(node, d, "2", f)


def m_refund_amount(node, d):
    def f(g, d):
        refund = next(r for r in g["receipts"] if r["predecessor_id"] == "system"
                      and r["receipt"]["Action"]["signer_id"] == "system")
        refund["receipt"]["Action"]["actions"][0]["Transfer"]["deposit"] = "1"
    _mut_tx(node, d, "2", f)


def m_block_parent(node, d):
    key = node.find("block", lambda p, r: r["header"]["height"] == d["h0_height"] + 5 and "block_id" in p
                    and isinstance(p["block_id"], str))
    node.result(key)["header"]["hash"] = node.result(key)["header"]["prev_hash"]


def _state_query(node, d):
    return node.find("query", lambda p, r: p.get("request_type") == "view_state")


def m_record(node, d):
    key = _state_query(node, d)
    for v in node.result(key)["values"]:
        k = base64.b64decode(v["key"])
        if k[:1] == b"r" and len(k) == 9:
            raw = bytearray(base64.b64decode(v["value"]))
            raw[1] ^= 1  # amount low byte
            v["value"] = base64.b64encode(bytes(raw)).decode()
            return
    raise KeyError("record")


def m_index(node, d):
    key = _state_query(node, d)
    for v in node.result(key)["values"]:
        k = base64.b64decode(v["key"])
        if k[:1] == b"i" and len(k) == 5:
            v["value"] = base64.b64encode((99).to_bytes(8, "little")).decode()
            return
    raise KeyError("index")


def m_event_sequence(node, d):
    def f(g, d):
        for o in g["receipts_outcome"]:
            for i, line in enumerate(o["outcome"]["logs"]):
                if '"event":"admission"' in line:
                    ev = json.loads(line[len("EVENT_JSON:"):])
                    ev["data"]["seq"] = str(int(ev["data"]["seq"]) + 100)
                    o["outcome"]["logs"][i] = "EVENT_JSON:" + json.dumps(ev, separators=(",", ":"))
                    return
        raise KeyError("event")
    _mut_tx(node, d, "2", f)


def m_callback_mapping(node, d):
    def f(g, d):
        cb = next(r for r in g["receipts"] if r["predecessor_id"] == d["vault"] and r["receiver_id"] == d["vault"])
        cb["receipt"]["Action"]["input_data_ids"] = ["11111111111111111111111111111111"]
    _mut_tx(node, d, "2", f)


def _changes(node, d, kind, pred):
    for (m, p), resp in node.responses.items():
        if m == "EXPERIMENTAL_changes" and "result" in resp:
            params = loads(p)
            if params["changes_type"] == kind:
                for c in resp["result"]["changes"]:
                    if pred(c):
                        return c, resp["result"]
    raise KeyError(kind)


def m_charge_decrease(node, d):
    from packages.verifier.state import decode_state
    writes = []
    for (m, p), resp in node.responses.items():
        if m == "EXPERIMENTAL_changes" and "result" in resp and loads(p)["changes_type"] == "data_changes":
            for c in resp["result"]["changes"]:
                if base64.b64decode(c["change"]["key_base64"]) == b"STATE":
                    st = decode_state(base64.b64decode(c["change"]["value_base64"]))
                    if st["charged"] > 0:
                        writes.append((c, st))
    c, st = writes[-1]
    raw = bytearray(base64.b64decode(c["change"]["value_base64"]))
    # charged is the u128 after policy body (len hex/2) + hash 32 + S_max 8 + reserve 16.
    off = len(st["policy_body_hex"]) // 2 + 32 + 8 + 16
    raw[off:off + 16] = (0).to_bytes(16, "little")
    c["change"]["value_base64"] = base64.b64encode(bytes(raw)).decode()


def m_vault_key(node, d):
    key = node.find("query", lambda p, r: p.get("request_type") == "view_access_key_list" and p.get("account_id") == d["vault"])
    node.result(key)["keys"] = [{"public_key": "ed25519:11111111111111111111111111111111",
                                 "access_key": {"nonce": 0, "permission": "FullAccess"}}]


def m_extra_outflow(node, d):
    def f(g, d):
        native = _native(g, d["vault"])
        adm = next(o for o in g["receipts_outcome"] if native["receipt_id"] in o["outcome"]["receipt_ids"])
        extra = copy.deepcopy(native)
        extra["receipt_id"] = b58(hashlib.sha256(b"forged-extra-outflow").digest())
        extra["receiver_id"] = "attacker.test.near"
        extra["receipt"]["Action"]["output_data_receivers"] = []
        eo = copy.deepcopy(_outcome(g, native["receipt_id"]))
        eo["id"] = extra["receipt_id"]
        eo["outcome"]["executor_id"] = "attacker.test.near"
        eo["outcome"]["receipt_ids"] = []
        eo["outcome"]["status"] = {"SuccessValue": ""}
        adm["outcome"]["receipt_ids"].append(extra["receipt_id"])
        g["receipts"].append(extra)
        g["receipts_outcome"].append(eo)
    _mut_tx(node, d, "1", f)


def m_chunk_omission(node, d):
    """Node-side omission: the source itself hides request 2's transaction from its chunk."""
    key = _tx_status_key(node, "2")
    txid = node.result(key)["transaction"]["hash"]
    for (m, p), resp in node.responses.items():
        if m == "chunk" and "result" in resp:
            txs = resp["result"]["transactions"]
            if any(t["hash"] == txid for t in txs):
                resp["result"]["transactions"] = [t for t in txs if t["hash"] != txid]
                return
    raise KeyError("chunk")


def m_failed_receipt_commits(node, d):
    # Attribute an existing STATE write to a failed receipt (a partial commit after rejection).
    failed = None
    for (m, p), resp in node.responses.items():
        if m == "EXPERIMENTAL_tx_status" and "result" in resp:
            for o in resp["result"]["receipts_outcome"]:
                if "Failure" in o["outcome"]["status"] and o["outcome"]["executor_id"] == d["vault"]:
                    failed = o
    c, res = _changes(node, d, "data_changes", lambda c: base64.b64decode(c["change"]["key_base64"]) == b"STATE"
                      and c["cause"].get("type") == "receipt_processing")
    # Copy it into the failed receipt's block, attributed to that failed receipt.
    forged = copy.deepcopy(c)
    forged["cause"]["receipt_hash"] = failed["id"]
    for (m, p), resp in node.responses.items():
        if m == "EXPERIMENTAL_changes" and "result" in resp and loads(p)["changes_type"] == "data_changes" \
                and loads(p)["block_id"] == failed["block_hash"]:
            resp["result"]["changes"].append(forged)
            return
    raise KeyError("failed block changes")


MUTATIONS = {
    "genesis_block_hash": m_genesis,
    "chain_id": m_chain_id,
    "artifact_byte": m_artifact,
    "vault_identity": m_vault_identity,
    "transfer_amount": m_amount,
    "transfer_outcome": m_outcome,
    "principal_refund_removed": m_refund_removed,
    "principal_refund_amount": m_refund_amount,
    "produced_block_identity": m_block_parent,
    "retained_record_amount": m_record,
    "index_mapping": m_index,
    "event_sequence": m_event_sequence,
    "callback_data_mapping": m_callback_mapping,
    "charge_decrease_in_history": m_charge_decrease,
    "vault_access_key": m_vault_key,
    "extra_vault_outflow": m_extra_outflow,
    "node_side_chunk_omission": m_chunk_omission,
    "failed_receipt_commits_state": m_failed_receipt_commits,
}


def run_mutations(records, descriptor, verify):
    """Every mutation must leave the overall result short of a complete PASS."""
    results = {}
    for name, fn in MUTATIONS.items():
        node = ReplayNode(records)
        try:
            fn(node, descriptor)
        except (KeyError, StopIteration, IndexError) as exc:
            results[name] = {"applied": False, "error": repr(exc), "rejected": False}
            continue
        result, _ = verify(node, descriptor)
        computed = result.get("computed_if_live") or result["verdicts"]
        complete_pass = (result["chain_evidence_checks"] == "PASS"
                         and all(v == "PASS" for v in computed.values()))
        results[name] = {"applied": True, "rejected": not complete_pass,
                         "chain_evidence_checks": result["chain_evidence_checks"],
                         "verdicts": result["verdicts"],
                         "issues": [i["code"] for i in result["issues"] if i["code"] != "NOT_LIVE_ACQUISITION"]}
    return results
