"""SYNTHETIC protocol-shaped oracle. Never evidence of executed NEAR transfers.

Same topology as the original Agent B fixture (four roots over heights 10..20, height 11
skipped, two shards, a carried chunk), now in the ACTUAL nearcore 2.13.4 / vault interface
representation observed on real runs: `view_code.hash`, decimal-string `seq`/`admission_seq`,
JSON-number count/index fields, 32-byte DeployContract digests in receipt views, Borsh raw
state, committed EVENT_JSON logs, request_payment decisions and STATE/record/index history.
State, events and history are generated from one scenario model so variants stay consistent.
"""
import base64
import copy
import hashlib
import json

from packages.collector import EvidenceError, b58, canonical, digest
from packages.verifier.state import policy_body, policy_hash, request_digest

YOCTO = 10**24
WASM = b"\0asm\x01\0\0\0"  # Empty synthetic module, NOT the protected contract.
EXPIRES = 1893456000000000000
S_MAX, RESERVE = 156139, 1571390000000000000000000


def h(label):
    return b58(hashlib.sha256(label.encode()).digest())


def enc(value):
    return base64.b64encode(canonical(value)).decode()


def b64(raw):
    return base64.b64encode(raw).decode()


def call(method, args=None):
    return {"FunctionCall": {"method_name": method, "args": enc(args or {}),
                             "gas": 30000000000000, "deposit": "0"}}


def outcome(oid, executor, height, children=(), failure=False, returned=None, value=b"", logs=()):
    status = {"Failure": {"ActionError": {"index": 0, "kind": {"AccountDoesNotExist": {"account_id": "missing.test.near"}}}}} if failure else {"SuccessValue": b64(value)}
    if returned:
        status = {"SuccessReceiptId": returned}
    return {"id": oid, "block_hash": h(f"block-{height}"), "proof": [],
            "outcome": {"executor_id": executor, "receipt_ids": list(children), "status": status,
                        "logs": list(logs), "gas_burnt": 0, "tokens_burnt": "0"}}


def receipt(rid, predecessor, receiver, signer, actions):
    return {"receipt_id": rid, "predecessor_id": predecessor, "receiver_id": receiver,
            "receipt": {"Action": {"signer_id": signer, "signer_public_key": "ed25519:" + "1"*32,
                                   "gas_price": "0", "input_data_ids": [], "output_data_receivers": [],
                                   "actions": actions, "is_promise_yield": False}}}


def permission(vault):
    return {"FunctionCall": {"allowance": str(YOCTO), "receiver_id": vault,
                             "method_names": ["request_payment"]}}


def event(name, data):
    return "EVENT_JSON:" + json.dumps({"standard": "near-agent-vault-lab", "version": "1.0.0",
                                       "event": name, "data": data}, separators=(",", ":"))


def state_bytes(body, ph, st):
    return (body + ph + S_MAX.to_bytes(8, "little") + RESERVE.to_bytes(16, "little")
            + st["charged"].to_bytes(16, "little") + st["cb_s"].to_bytes(16, "little")
            + st["cb_f"].to_bytes(16, "little") + bytes([1 if st["frozen"] else 0])
            + st["count"].to_bytes(4, "little") + st["seq"].to_bytes(8, "little"))


def record_bytes(rec):
    status = {"Pending": 0, "CbSucceeded": 1, "CbFailed": 2}[rec["status"]]
    return (bytes([rec["recipient_index"]]) + rec["amount"].to_bytes(16, "little")
            + rec["admission_seq"].to_bytes(8, "little") + bytes([status]))


class SyntheticNode:
    mode = "SYNTHETIC"

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))
        key = (method, canonical(params))
        if key not in self.responses:
            raise EvidenceError("RPC_UNAVAILABLE", {"method": method, "params": params})
        value = self.responses[key]
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


def fixture(callback1_fails=False):
    owner, vault, agent = "owner.test.near", "vault.owner.test.near", "agent.owner.test.near"
    recipients = ["missing.test.near", "recipient.test.near"]
    chain = "synthetic-g1"
    body = policy_body(chain, vault, owner, agent, 5*YOCTO, 2*YOCTO, recipients, EXPIRES, 2)
    ph = policy_hash(body)
    phb58 = b58(ph)
    genesis = {"chain_id": chain, "genesis_height": 0, "protocol_version": 86}
    protocol = {"protocol_version": 86, "shard_layout": {"V2": {"shard_ids": [0, 1], "boundary_accounts": ["m"]}}}
    version = {"version": "2.13.4", "build": "SYNTHETIC", "rustc_version": "SYNTHETIC"}
    d = {"schema": "near-g1-reviewer/v1", "network": "sandbox", "chain_id": chain,
         "genesis_block_hash": h("block-0"), "genesis_rpc_sha256": digest(genesis),
         "h0_hash": h("block-10"), "h0_height": 10, "q_hash": h("block-20"), "q_height": 20,
         "vault": vault, "owner": owner, "agent": agent, "recipients": recipients,
         "policy_hash": phb58, "budget": str(5*YOCTO), "max_per_request": str(2*YOCTO),
         "expires_at_ns": str(EXPIRES), "max_accepted_requests": 2, "asset": "NativeNear",
         "wasm_sha256": hashlib.sha256(WASM).hexdigest(), "node_version": version,
         "protocol_config_sha256": digest(protocol),
         "node_binary_sha256": "0"*64, "node_config_sha256": "0"*64, "genesis_file_sha256": "0"*64,
         "max_blocks": 100, "max_roots": 100, "shard_ids": [0, 1]}
    responses, graphs = {}, {}
    data_history = {}  # height -> list of data changes

    def put(method, params, value):
        responses[(method, canonical(params))] = value if isinstance(value, Exception) else copy.deepcopy(value)

    # ---- scenario model: state transitions in execution order ----
    st = {"charged": 0, "cb_s": 0, "cb_f": 0, "frozen": False, "count": 0, "seq": 0}
    records, index = {}, {}

    def ident():
        return {"vault": vault, "policy_hash": phb58}

    def write_state(height, rid):
        data_history.setdefault(height, []).append(
            {"type": "data_update", "cause": {"type": "receipt_processing", "receipt_hash": rid},
             "change": {"account_id": vault, "key_base64": b64(b"STATE"),
                        "value_base64": b64(state_bytes(body, ph, st))}})

    def write_raw(height, rid, key, value):
        data_history.setdefault(height, []).append(
            {"type": "data_update", "cause": {"type": "receipt_processing", "receipt_hash": rid},
             "change": {"account_id": vault, "key_base64": b64(key), "value_base64": b64(value)}})

    for aid in (vault, agent):
        params = {"request_type": "view_account", "account_id": aid, "block_id": d["h0_hash"]}
        put("query", params, EvidenceError("RPC_UNAVAILABLE", {"method": "query", "params": params,
             "error": {"cause": {"name": "UNKNOWN_ACCOUNT", "info": {"requested_account_id": aid,
                                   "block_hash": d["h0_hash"], "block_height": d["h0_height"]}}}}))

    def make_root(label, signer, receiver, actions, height, extra_receipts=(), extra_outcomes=(),
                  children=(), value=b"", logs=()):
        txid, first = h(label), h(label + "-first")
        tx = {"hash": txid, "signer_id": signer, "receiver_id": receiver, "actions": actions,
              "nonce": height, "public_key": "ed25519:" + "1"*32, "signature": "ed25519:" + "1"*64}
        graph = {"final_execution_status": "FINAL", "status": {"SuccessValue": ""}, "transaction": tx,
                 "transaction_outcome": outcome(txid, signer, height, [first], returned=first),
                 "receipts": [receipt(first, signer, receiver, signer, actions)] + list(extra_receipts),
                 "receipts_outcome": [outcome(first, receiver, height, children, value=value, logs=logs)]
                 + list(extra_outcomes)}
        graphs[txid] = graph
        put("EXPERIMENTAL_tx_status", {"tx_hash": txid, "sender_account_id": signer, "wait_until": "FINAL"}, graph)
        return tx

    # Creation (h12): keyless batch; 2.13.4 receipt views carry the 32-byte code digest.
    write_state(12, h("creation-first"))
    creation = make_root("creation", owner, vault,
                         ["CreateAccount", {"Transfer": {"deposit": str(20*YOCTO)}},
                          {"DeployContract": {"code": b64(hashlib.sha256(WASM).digest())}}, call("new")], 12,
                         value=json.dumps(phb58).encode(), logs=[event("init", dict(ident(), seq="0"))])
    transactions = {12: [creation]}
    admissions = []
    callbacks_model, deferred = [], []
    for number, recipient, amount, height in ((1, recipients[1], YOCTO, 13), (2, recipients[0], 2*YOCTO, 14)):
        native, callback, refund, gas = (h(f"{name}-{number}") for name in ("native", "callback", "refund", "gas"))
        terms = {"request_id": str(number), "recipient": recipient, "amount": str(amount), "policy_hash": phb58}
        before = st["charged"]
        st["charged"] += amount
        st["count"] += 1
        st["seq"] += 1
        rindex = recipients.index(recipient)
        records[number] = {"recipient_index": rindex, "amount": amount, "admission_seq": st["seq"], "status": "Pending"}
        index[st["count"] - 1] = number
        first = h(f"payment-{number}-first")
        write_state(height, first)
        write_raw(height, first, b"r" + number.to_bytes(8, "little"), record_bytes(records[number]))
        write_raw(height, first, b"i" + (st["count"] - 1).to_bytes(4, "little"), number.to_bytes(8, "little"))
        rd = request_digest(vault, ph, agent, number, recipient, amount)
        decision = {"decision": "Admitted", "seq": str(st["seq"]), "request_id": str(number),
                    "recipient": recipient, "amount": str(amount), "request_digest_hex": rd,
                    "charged_before": str(before), "charged_after": str(st["charged"])}
        adm_log = event("admission", dict(ident(), seq=str(st["seq"]), request_id=str(number), recipient=recipient,
                                          amount=str(amount), request_digest_hex=rd, charged_before=str(before),
                                          charged_after=str(st["charged"])))
        receipts = [receipt(native, vault, recipient, agent, [{"Transfer": {"deposit": str(amount)}}]),
                    receipt(callback, vault, vault, agent, [call("on_payment_result", {"request_id": str(number)})]),
                    receipt(gas, "system", agent, agent, [{"Transfer": {"deposit": "123"}}])]
        data_id = h(f"callback-data-{number}")
        receipts[0]["receipt"]["Action"]["output_data_receivers"] = [{"data_id": data_id, "receiver_id": vault}]
        receipts[1]["receipt"]["Action"]["input_data_ids"] = [data_id]
        failed = number == 2
        children = [gas]
        if failed:
            receipts.append(receipt(refund, "system", vault, "system", [{"Transfer": {"deposit": str(amount)}}]))
            children.append(refund)
        native_height = 15 if number == 1 else 16
        outcomes = [outcome(native, recipient, native_height, children, failure=failed),
                    outcome(gas, agent, 17)]
        if failed:
            outcomes.append(outcome(refund, vault, 17))
        callbacks_model.append((number, callback, amount, failed, outcomes, receipts))
        # The root is materialized after the callbacks are modelled (make_root snapshots outcomes).
        deferred.append((number, height, terms, receipts, outcomes, [native, callback], decision, adm_log))
    # Freeze (h18).
    st["frozen"] = True
    st["seq"] += 1
    write_state(18, h("freeze-first"))
    transactions[18] = [make_root("freeze", owner, vault, [call("freeze")], 18,
                                  logs=[event("freeze", dict(ident(), seq=str(st["seq"]), charged=str(st["charged"]),
                                                             accepted_count=st["count"]))])]
    # Callbacks (h19), in order.
    for number, callback, amount, failed, outcomes, _ in callbacks_model:
        if number == 1 and callback1_fails:
            outcomes.append({"id": callback, "block_hash": h("block-19"), "proof": [],
                             "outcome": {"executor_id": vault, "receipt_ids": [], "logs": [],
                                         "status": {"Failure": {"ActionError": {"index": 0, "kind": {
                                             "FunctionCallError": {"ExecutionError": "SYNTHETIC callback panic"}}}}},
                                         "gas_burnt": 0, "tokens_burnt": "0"}})
            continue
        status = "CbFailed" if failed else "CbSucceeded"
        if failed:
            st["cb_f"] += amount
        else:
            st["cb_s"] += amount
        st["seq"] += 1
        records[number]["status"] = status
        write_state(19, callback)
        write_raw(19, callback, b"r" + number.to_bytes(8, "little"), record_bytes(records[number]))
        outcomes.append(outcome(callback, vault, 19, logs=[event("callback", dict(
            ident(), seq=str(st["seq"]), request_id=str(number), amount=str(amount), callback_status=status,
            charged=str(st["charged"]), cb_succeeded_amount=str(st["cb_s"]), cb_failed_amount=str(st["cb_f"])))]))
    for number, height, terms, receipts, outcomes, children, decision, adm_log in deferred:
        transactions[height] = [make_root(f"payment-{number}", agent, vault, [call("request_payment", terms)],
                                          height, receipts, outcomes, children, value=canonical(decision),
                                          logs=[adm_log])]
    for number, *_ in callbacks_model:
        rec = records[number]
        admissions.append({"request_id": str(number), "recipient": recipients[rec["recipient_index"]],
                           "recipient_index": rec["recipient_index"], "amount": str(rec["amount"]),
                           "admission_seq": str(rec["admission_seq"]), "callback_status": rec["status"],
                           "request_digest_hex": request_digest(vault, ph, agent, number,
                                                                recipients[rec["recipient_index"]], rec["amount"])})

    heights = [0, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20]  # Height 11 was skipped.
    blocks = {}
    for i, height in enumerate(heights):
        headers = []
        for shard in (0, 1):
            included_height = 16 if height == 17 and shard == 1 else height
            header = {"chunk_hash": h(f"chunk-{included_height}-{shard}"),
                      "height_included": included_height, "shard_id": shard}
            headers.append(header)
            if included_height == height:
                txs = transactions.get(height, []) if shard == height % 2 else []
                put("chunk", {"chunk_id": header["chunk_hash"]}, {"header": header, "transactions": txs, "receipts": []})
        block = {"header": {"hash": h(f"block-{height}"), "height": height,
                            "epoch_id": h("synthetic-epoch"),
                            "prev_hash": h(f"block-{heights[max(0,i-1)]}"),
                            "chunk_mask": [True, height != 17]}, "chunks": headers}
        blocks[height] = block
        put("block", {"block_id": block["header"]["hash"]}, block)
    put("block", {"block_id": 0}, blocks[0])
    put("block", {"block_id": 20}, blocks[20])
    put("block", {"finality": "final"}, blocks[20])
    put("status", {}, {"chain_id": d["chain_id"], "version": version})
    put("EXPERIMENTAL_genesis_config", {}, genesis)
    for bh in (d["h0_hash"], d["q_hash"]):
        put("EXPERIMENTAL_protocol_config", {"block_id": bh}, protocol)
    qmeta = {"block_hash": d["q_hash"], "block_height": d["q_height"]}
    code_hash = b58(hashlib.sha256(WASM).digest())
    for role, aid in (("vault", vault), ("agent", agent)):
        values = {"view_account": {"code_hash": code_hash if role == "vault" else "1"*32},
                  "view_code": {"code_base64": b64(WASM if role == "vault" else b""),
                                "hash": code_hash if role == "vault" else "1"*32},
                  "view_access_key_list": {"keys": [] if role == "vault" else
                                           [{"public_key": h(f"key-{i}"), "access_key": {"permission": permission(vault)}} for i in range(8)]}}
        for kind, value in values.items():
            put("query", {"request_type": kind, "account_id": aid, "block_id": d["q_hash"]}, qmeta | value)
    mandate = {"vault": vault, "owner": owner, "agent": agent, "chain_id": chain, "policy_hash": phb58,
               "policy_hash_hex": ph.hex(), "asset": "NativeNear", "budget": d["budget"],
               "max_per_request": d["max_per_request"], "allowed_recipients": recipients,
               "expires_at_ns": str(EXPIRES), "max_accepted_requests": 2,
               "storage_bound_bytes": str(S_MAX), "reserve_total": str(RESERVE),
               "charged": str(st["charged"]), "headroom": str(5*YOCTO - st["charged"]),
               "cb_succeeded_amount": str(st["cb_s"]), "cb_failed_amount": str(st["cb_f"]),
               "accepted_count": st["count"], "seq": str(st["seq"]), "frozen": st["frozen"]}
    for method, value in (("get_admissions", admissions), ("get_mandate", mandate)):
        put("query", {"request_type": "call_function", "account_id": vault, "method_name": method,
                      "args_base64": "e30=", "block_id": d["q_hash"]}, qmeta | {"result": list(canonical(value))})
    values = [{"key": b64(b"STATE"), "value": b64(state_bytes(body, ph, st))}]
    for n, rec in records.items():
        values.append({"key": b64(b"r" + n.to_bytes(8, "little")), "value": b64(record_bytes(rec))})
    for pos, n in index.items():
        values.append({"key": b64(b"i" + pos.to_bytes(4, "little")), "value": b64(n.to_bytes(8, "little"))})
    put("query", {"request_type": "view_state", "account_id": vault, "prefix_base64": "", "include_proof": True,
                  "block_id": d["q_hash"]}, qmeta | {"values": values, "proof": []})
    for height in heights[2:]:
        for kind in ("account_changes", "all_access_key_changes", "contract_code_changes", "data_changes"):
            params = {"block_id": h(f"block-{height}"), "changes_type": kind, "account_ids": [vault, agent]}
            if kind == "data_changes":
                params["key_prefix_base64"] = ""
            changes = []
            if height == 12 and kind == "contract_code_changes":
                changes = [{"type": "contract_code_update", "cause": {"type": "receipt_processing", "receipt_hash": h("creation-first")},
                            "change": {"account_id": vault, "code_base64": b64(WASM)}}]
            if kind == "data_changes":
                changes = data_history.get(height, [])
            put("EXPERIMENTAL_changes", params, {"block_hash": h(f"block-{height}"), "changes": changes})
    return d, SyntheticNode(responses)
