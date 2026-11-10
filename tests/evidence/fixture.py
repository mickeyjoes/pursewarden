"""SYNTHETIC protocol-shaped oracle. Never evidence of executed NEAR transfers."""
import base64
import copy
import hashlib

from packages.collector import EvidenceError, b58, canonical, digest

YOCTO = 10**24
WASM = b"\0asm\x01\0\0\0"  # Empty synthetic module, NOT the protected contract.


def h(label):
    return b58(hashlib.sha256(label.encode()).digest())


def enc(value):
    return base64.b64encode(canonical(value)).decode()


def call(method, args=None):
    return {"FunctionCall": {"method_name": method, "args": enc(args or {}),
                             "gas": 30000000000000, "deposit": "0"}}


def outcome(oid, executor, height, children=(), failure=False, returned=None):
    status = {"Failure": {"ActionError": {"index": 0, "kind": {"AccountDoesNotExist": {"account_id": "missing.test.near"}}}}} if failure else {"SuccessValue": ""}
    if returned:
        status = {"SuccessReceiptId": returned}
    return {"id": oid, "block_hash": h(f"block-{height}"), "proof": [],
            "outcome": {"executor_id": executor, "receipt_ids": list(children), "status": status,
                        "logs": [], "gas_burnt": 0, "tokens_burnt": "0"}}


def receipt(rid, predecessor, receiver, signer, actions):
    return {"receipt_id": rid, "predecessor_id": predecessor, "receiver_id": receiver,
            "receipt": {"Action": {"signer_id": signer, "signer_public_key": "ed25519:" + "1"*32,
                                   "gas_price": "0", "input_data_ids": [], "output_data_receivers": [],
                                   "actions": actions, "is_promise_yield": False}}}


def permission(vault):
    return {"FunctionCall": {"allowance": str(YOCTO), "receiver_id": vault,
                             "method_names": ["request_payment"]}}


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


def fixture():
    owner, vault, agent = "owner.test.near", "vault.owner.test.near", "agent.owner.test.near"
    recipients = ["missing.test.near", "recipient.test.near"]
    genesis = {"chain_id": "synthetic-g1", "genesis_height": 0, "protocol_version": 86}
    protocol = {"protocol_version": 86, "shard_layout": {"V2": {"shard_ids": [0, 1], "boundary_accounts": ["m"]}}}
    version = {"version": "2.13.4", "build": "SYNTHETIC", "rustc_version": "SYNTHETIC"}
    d = {"schema": "near-g1-reviewer/v1", "network": "sandbox", "chain_id": "synthetic-g1",
         "genesis_block_hash": h("block-0"), "genesis_rpc_sha256": digest(genesis),
         "h0_hash": h("block-10"), "h0_height": 10, "q_hash": h("block-20"), "q_height": 20,
         "vault": vault, "owner": owner, "agent": agent, "recipients": recipients,
         "policy_hash": h("synthetic-policy"), "budget": str(5*YOCTO), "max_per_request": str(2*YOCTO),
         "wasm_sha256": hashlib.sha256(WASM).hexdigest(), "node_version": version,
         "protocol_config_sha256": digest(protocol),
         "node_binary_sha256": "0"*64, "node_config_sha256": "0"*64, "genesis_file_sha256": "0"*64,
         "max_blocks": 100, "max_roots": 100, "shard_ids": [0, 1]}
    responses, graphs = {}, {}

    def put(method, params, value):
        responses[(method, canonical(params))] = value if isinstance(value, Exception) else copy.deepcopy(value)

    for aid in (vault, agent):
        params = {"request_type": "view_account", "account_id": aid, "block_id": d["h0_hash"]}
        put("query", params, EvidenceError("RPC_UNAVAILABLE", {"method": "query", "params": params,
             "error": {"cause": {"name": "UNKNOWN_ACCOUNT", "info": {"requested_account_id": aid,
                                   "block_hash": d["h0_hash"], "block_height": d["h0_height"]}}}}))

    def make_root(label, signer, receiver, actions, height, extra_receipts=(), extra_outcomes=(), children=()):
        txid, first = h(label), h(label + "-first")
        tx = {"hash": txid, "signer_id": signer, "receiver_id": receiver, "actions": actions,
              "nonce": height, "public_key": "ed25519:" + "1"*32, "signature": "ed25519:" + "1"*64}
        graph = {"final_execution_status": "FINAL", "status": {"SuccessValue": ""}, "transaction": tx,
                 "transaction_outcome": outcome(txid, signer, height, [first], returned=first),
                 "receipts": [receipt(first, signer, receiver, signer, actions)] + list(extra_receipts),
                 "receipts_outcome": [outcome(first, receiver, height, children)] + list(extra_outcomes)}
        graphs[txid] = graph
        put("EXPERIMENTAL_tx_status", {"tx_hash": txid, "sender_account_id": signer, "wait_until": "FINAL"}, graph)
        return tx

    creation = make_root("creation", owner, vault,
                         ["CreateAccount", {"Transfer": {"deposit": str(20*YOCTO)}},
                          {"DeployContract": {"code": base64.b64encode(WASM).decode()}}, call("new")], 12)
    transactions = {12: [creation]}
    admissions = []
    for number, recipient, amount, height in ((1, recipients[1], YOCTO, 13), (2, recipients[0], 2*YOCTO, 14)):
        native, callback, refund, gas = (h(f"{name}-{number}") for name in ("native", "callback", "refund", "gas"))
        terms = {"request_id": str(number), "recipient": recipient, "amount": str(amount), "policy_hash": d["policy_hash"]}
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
                    outcome(callback, vault, 19), outcome(gas, agent, 17)]
        if failed:
            outcomes.append(outcome(refund, vault, 17))
        tx = make_root(f"payment-{number}", agent, vault, [call("request_payment", terms)], height,
                       receipts, outcomes, [native, callback])
        transactions[height] = [tx]
        admissions.append({"request_id": str(number), "recipient": recipient, "amount": str(amount),
                           "admission_sequence": number, "callback_status": "CbFailed" if failed else "CbSucceeded"})
    transactions[18] = [make_root("freeze", owner, vault, [call("freeze")], 18)]
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
    put("block", {"finality": "final"}, blocks[20])
    put("status", {}, {"chain_id": d["chain_id"], "version": version})
    put("EXPERIMENTAL_genesis_config", {}, genesis)
    for bh in (d["h0_hash"], d["q_hash"]):
        put("EXPERIMENTAL_protocol_config", {"block_id": bh}, protocol)
    qmeta = {"block_hash": d["q_hash"], "block_height": d["q_height"]}
    code_hash = b58(hashlib.sha256(WASM).digest())
    for role, aid in (("vault", vault), ("agent", agent)):
        values = {"view_account": {"code_hash": code_hash if role == "vault" else "1"*32},
                  "view_code": {"code_base64": base64.b64encode(WASM if role == "vault" else b"").decode(),
                                "code_hash": code_hash if role == "vault" else "1"*32},
                  "view_access_key_list": {"keys": [] if role == "vault" else
                                           [{"public_key": h(f"key-{i}"), "access_key": {"permission": permission(vault)}} for i in range(8)]}}
        for kind, value in values.items():
            put("query", {"request_type": kind, "account_id": aid, "block_id": d["q_hash"]}, qmeta | value)
    mandate = {"vault": vault, "owner": owner, "agent": agent, "chain_id": d["chain_id"],
               "policy_hash": d["policy_hash"], "budget": d["budget"], "charged": str(3*YOCTO),
               "accepted_count": 2, "frozen": True, "sequence": 5}
    for method, value in (("get_admissions", admissions), ("get_mandate", mandate)):
        put("query", {"request_type": "call_function", "account_id": vault, "method_name": method,
                      "args_base64": "e30=", "block_id": d["q_hash"]}, qmeta | {"result": list(canonical(value))})
    put("query", {"request_type": "view_state", "account_id": vault, "prefix_base64": "", "include_proof": True,
                  "block_id": d["q_hash"]}, qmeta | {"values": [], "proof": []})
    for height in heights[2:]:
        for kind in ("account_changes", "all_access_key_changes", "contract_code_changes", "data_changes"):
            params = {"block_id": h(f"block-{height}"), "changes_type": kind, "account_ids": [vault, agent]}
            if kind == "data_changes":
                params["key_prefix_base64"] = ""
            changes = []
            if height == 12 and kind == "contract_code_changes":
                changes = [{"type": "contract_code_update", "cause": {"type": "receipt_processing", "receipt_hash": h("creation-first")},
                            "change": {"account_id": vault, "code_base64": base64.b64encode(WASM).decode()}}]
            put("EXPERIMENTAL_changes", params, {"block_hash": h(f"block-{height}"), "changes": changes})
    return d, SyntheticNode(responses)
