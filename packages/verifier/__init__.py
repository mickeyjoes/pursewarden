"""Strict graph/effect reconciliation; never a verdict imported from the runner.

Adapter for the actual nearcore 2.13.4 RPC representations of the G1 vault
(`view_code.hash`, decimal-string `seq`/`admission_seq`, JSON-number count/index fields,
32-byte `DeployContract.code` digests in receipt views). Failed receipts are classified before
any argument is interpreted. Raw Borsh state, the ten-field policy hash, records/index,
committed events and the state-change history are reconciled independently.
"""

import hashlib

from packages.collector import (EvidenceError, account, b58, b58decode32, canonical, decimal,
                                decode64, digest, hash_id, loads, require)
from packages.verifier.state import (decode_record, decode_state, decode_view_state,
                                     descriptor_policy_body, policy_hash, request_digest,
                                     classify_key)

EVENT_PREFIX = "EVENT_JSON:"
EVENT_STANDARD = "near-agent-vault-lab"
EVENT_VERSION = "1.0.0"
VIEW_METHODS = {"get_mandate", "get_request", "get_admissions", "contract_source_metadata"}
SAFETY_CODES = {"CAP_EXCEEDED", "UNMATCHED_VAULT_OUTFLOW", "FAILED_ADMISSION_DISPATCH",
                "FAILED_RECEIPT_DISPATCH", "UNRETAINED_OR_DUPLICATE_DISPATCH", "VAULT_HAS_KEYS",
                "VAULT_KEY_HISTORY", "CHARGE_DECREASED", "FAILED_RECEIPT_COMMITTED_STATE",
                "CODE_DEPLOYMENT_HISTORY", "UNEXPECTED_VAULT_ACTION", "UNEXPECTED_VAULT_METHOD",
                "TRANSFER_TERMS", "ADMISSION_AUTHORITY", "STORAGE_DELETED", "POLICY_MUTATED",
                "RECORD_MUTATED", "INDEX_MUTATED", "UNFROZEN"}


def index_unique(items, field):
    result = {}
    for item in items:
        key = hash_id(item[field])
        require(key not in result, "DUPLICATE_IDENTIFIER", key)
        result[key] = item
    return result


def outcome_kind(outcome):
    status = outcome["outcome"]["status"]
    require(isinstance(status, dict) and len(status) == 1, "OUTCOME_UNKNOWN", outcome["id"], "INCONCLUSIVE")
    kind = next(iter(status))
    require(kind in {"SuccessValue", "SuccessReceiptId", "Failure"},
            "OUTCOME_UNKNOWN", outcome["id"], "INCONCLUSIVE")
    if kind == "SuccessValue":
        decode64(status[kind])
    if kind == "SuccessReceiptId":
        hash_id(status[kind])
    return kind


def action_body(receipt):
    require(set(receipt["receipt"]) == {"Action"}, "UNSUPPORTED_RECEIPT_KIND",
            receipt["receipt_id"], "INCONCLUSIVE")
    body = receipt["receipt"]["Action"]
    require(not body.get("is_promise_yield", False) and body.get("refund_to") is None,
            "UNSUPPORTED_RECEIPT_FEATURE", receipt["receipt_id"], "INCONCLUSIVE")
    account(receipt["predecessor_id"])
    account(receipt["receiver_id"])
    account(body["signer_id"])
    decimal(body["gas_price"])
    require(isinstance(body["actions"], list) and body["actions"], "EMPTY_ACTIONS", receipt["receipt_id"])
    return body


def graph_check(txid, graph, included_block, block_heights, globally_seen):
    require(graph["final_execution_status"] == "FINAL", "NOT_FINAL", txid, "INCONCLUSIVE")
    tx = graph["transaction"]
    require(tx["hash"] == txid and graph["transaction_outcome"]["id"] == txid,
            "ROOT_IDENTIFIER", txid)
    bodies = index_unique(graph["receipts"], "receipt_id")
    outcomes = index_unique([graph["transaction_outcome"]] + graph["receipts_outcome"], "id")
    parents, visited, todo = {}, set(), [txid]
    require(txid not in bodies, "ROOT_AS_RECEIPT", txid)
    while todo:
        oid = todo.pop()
        require(oid not in visited, "GRAPH_CYCLE_OR_ALIAS", oid)
        visited.add(oid)
        require(oid in outcomes, "MISSING_OUTCOME", oid, "INCONCLUSIVE")
        out = outcomes[oid]
        kind = outcome_kind(out)
        bh = hash_id(out["block_hash"])
        require(bh in block_heights, "OUTCOME_OUTSIDE_CUT", {"id": oid, "block_hash": bh}, "INCONCLUSIVE")
        require(block_heights[bh] >= block_heights[included_block], "OUTCOME_BEFORE_ROOT", oid)
        if oid == txid:
            require(out["outcome"]["executor_id"] == tx["signer_id"], "TX_EXECUTOR", oid)
        else:
            require(oid in bodies, "MISSING_RECEIPT_BODY",
                    {"id": oid, "self_transaction": tx["signer_id"] == tx["receiver_id"]}, "INCONCLUSIVE")
            body = bodies[oid]
            require(out["outcome"]["executor_id"] == body["receiver_id"], "RECEIPT_EXECUTOR", oid)
            require(block_heights[bh] >= block_heights[outcomes[parents[oid]]["block_hash"]],
                    "CHILD_BEFORE_PARENT", oid)
            require(oid not in globally_seen, "CROSS_ROOT_RECEIPT_ALIAS", oid)
            globally_seen.add(oid)
            ab = action_body(body)
            parent = parents[oid]
            if parent == txid:
                require(body["predecessor_id"] == tx["signer_id"] and body["receiver_id"] == tx["receiver_id"]
                        and ab["signer_id"] == tx["signer_id"]
                        and same_actions(ab["actions"], tx["actions"]), "FIRST_RECEIPT_LINKAGE", oid)
            elif body["predecessor_id"] != "system":
                require(body["predecessor_id"] == bodies[parent]["receiver_id"]
                        and ab["signer_id"] == tx["signer_id"], "CHILD_LINKAGE", oid)
        children = out["outcome"]["receipt_ids"]
        require(len(children) == len(set(children)), "DUPLICATE_CHILD", oid)
        for child in children:
            hash_id(child)
            require(child != txid and child not in parents, "MULTIPLE_RECEIPT_PARENTS", child)
            parents[child] = oid
            todo.append(child)
        if kind == "SuccessReceiptId":
            require(out["outcome"]["status"][kind] in outcomes,
                    "MISSING_RETURN_RECEIPT", oid, "INCONCLUSIVE")
    require(set(outcomes) == visited, "UNLINKED_OUTCOME", sorted(set(outcomes)-visited))
    require(set(bodies) == visited - {txid}, "UNLINKED_BODY", sorted(set(bodies)-(visited-{txid})))
    return bodies, outcomes, parents


def same_actions(receipt_actions, tx_actions):
    """Receipt and transaction views agree except that 2.13.4 receipt views carry a 32-byte
    DeployContract digest while the transaction view carries the same digest representation."""
    return canonical(receipt_actions) == canonical(tx_actions)


def transfer_amount(receipt):
    actions = action_body(receipt)["actions"]
    require(len(actions) == 1 and isinstance(actions[0], dict) and set(actions[0]) == {"Transfer"},
            "EXPECTED_NATIVE_TRANSFER", receipt["receipt_id"])
    return decimal(actions[0]["Transfer"]["deposit"])


def single_function_call(receipt):
    """Return the single FunctionCall action (without parsing its arguments) or None."""
    actions = action_body(receipt)["actions"]
    if len(actions) == 1 and isinstance(actions[0], dict) and set(actions[0]) == {"FunctionCall"}:
        call = actions[0]["FunctionCall"]
        decimal(call["deposit"])
        return call
    return None


def call_args(call):
    """Parse arguments only of a receipt whose execution succeeded."""
    return loads(decode64(call["args"]))


def success_json(outcome):
    raw = decode64(outcome["outcome"]["status"]["SuccessValue"])
    return loads(raw) if raw else None


def failure_summary(outcome):
    f = outcome["outcome"]["status"]["Failure"]
    text = canonical(f).decode()
    if "MethodNotFound" in text:
        return "MethodNotFound"
    if "Failed to deserialize input" in text:
        return "MalformedInput"
    if "doesn't accept deposit" in text:
        return "AttachedDeposit"
    if "is private" in text:
        return "PrivateMethod"
    if "already been initialized" in text:
        return "Reinitialize"
    if "Unauthorized" in text:
        return "Unauthorized"
    if "AccountDoesNotExist" in text:
        return "AccountDoesNotExist"
    return "OtherFailure"


def vault_events(outcome, d):
    """Parse committed events from a SUCCESSFUL vault receipt. Failed receipts are ignored."""
    events = []
    for line in outcome["outcome"]["logs"]:
        if not line.startswith(EVENT_PREFIX):
            continue
        ev = loads(line[len(EVENT_PREFIX):].encode())
        require(ev.get("standard") == EVENT_STANDARD and ev.get("version") == EVENT_VERSION
                and ev.get("event") in {"init", "admission", "denial", "callback", "freeze"},
                "EVENT_SCHEMA", line[:200])
        data = ev["data"]
        require(data["vault"] == d["vault"] and data["policy_hash"] == d["policy_hash"],
                "EVENT_IDENTITY", line[:200])
        events.append({"event": ev["event"], "seq": decimal(data["seq"], 64), "data": data,
                       "receipt_id": outcome["id"], "block_hash": outcome["block_hash"]})
    require(len(events) <= 1, "MULTIPLE_EVENTS_PER_RECEIPT", outcome["id"])
    return events


# ------------------------------------------------------------------------------------------
# Single final cut (Q): views, raw state, keys, code
# ------------------------------------------------------------------------------------------

def one_cut(capture, d):
    q = d["q_hash"]
    for name, response in capture["queries"].items():
        require(response["block_hash"] == q and response["block_height"] == d["q_height"],
                "QUERY_CUT", name)
    queries = capture["queries"]
    code = decode64(queries["vault/view_code"]["code_base64"])
    sha = hashlib.sha256(code).digest()
    require(sha.hex() == d["wasm_sha256"], "WRONG_CONTRACT", "compiled WASM mismatch")
    # 2.13.4: view_code returns `hash`; view_account returns `code_hash`.
    require(queries["vault/view_code"]["hash"] == b58(sha), "WRONG_CODE_HASH", "vault/view_code")
    require(queries["vault/view_account"]["code_hash"] == b58(sha), "WRONG_CODE_HASH", "vault/view_account")
    require(queries["vault/view_access_key_list"]["keys"] == [], "VAULT_HAS_KEYS", d["vault"])
    agent_code = queries["agent/view_code"]
    if "absence_error" in agent_code:
        require(agent_code["absence_error"]["name"] == "NO_CONTRACT_CODE", "AGENT_CODE_ABSENCE", d["agent"])
    else:
        require(decode64(agent_code["code_base64"]) == b"", "AGENT_HAS_CODE", d["agent"])
    require(queries["agent/view_account"]["code_hash"] == "1" * 32, "AGENT_CODE_HASH", d["agent"])
    keys = queries["agent/view_access_key_list"]["keys"]
    require(len(keys) == 8 and len({k["public_key"] for k in keys}) == 8,
            "AGENT_KEY_COUNT", len(keys))
    for key in keys:
        check_agent_permission(key["access_key"]["permission"], d)

    raw = decode_view_state(queries["vault/view_state"]["values"])
    st = raw["STATE"]
    expected_body = descriptor_policy_body(d)
    require(st["policy_body_hex"] == expected_body.hex(), "POLICY_FIELDS",
            "raw STATE policy prefix differs from the reviewer's ten-field policy")
    require(st["policy_hash"] == d["policy_hash"] == b58(policy_hash(expected_body)),
            "POLICY_HASH", {"state": st["policy_hash"], "descriptor": d["policy_hash"]})

    admissions = loads(bytes(queries["get_admissions"]["result"]))
    mandate = loads(bytes(queries["get_mandate"]["result"]))
    require(isinstance(admissions, list) and len(admissions) <= 64, "ADMISSIONS_SCHEMA", "bounded list")
    # View <-> descriptor: all ten policy fields.
    for field, want in (("vault", d["vault"]), ("owner", d["owner"]), ("agent", d["agent"]),
                        ("chain_id", d["chain_id"]), ("policy_hash", d["policy_hash"]),
                        ("budget", d["budget"]), ("max_per_request", d["max_per_request"]),
                        ("allowed_recipients", d["recipients"]), ("expires_at_ns", d["expires_at_ns"]),
                        ("asset", "NativeNear")):
        require(mandate.get(field) == want, "MANDATE_IDENTITY", field)
    require(type(mandate["max_accepted_requests"]) is int
            and mandate["max_accepted_requests"] == d["max_accepted_requests"], "MANDATE_IDENTITY", "K")
    # View <-> raw state.
    require(type(mandate["accepted_count"]) is int and mandate["accepted_count"] == st["accepted_count"]
            == len(admissions), "ADMISSION_COUNT", "view/raw disagreement")
    for field in ("charged", "cb_succeeded_amount", "cb_failed_amount", "reserve_total"):
        require(decimal(mandate[field]) == st[field], "VIEW_RAW_MISMATCH", field)
    require(decimal(mandate["seq"], 64) == st["seq"], "VIEW_RAW_MISMATCH", "seq")
    require(decimal(mandate["storage_bound_bytes"], 64) == st["storage_bound_bytes"], "VIEW_RAW_MISMATCH", "S_max")
    require(mandate["frozen"] is st["frozen"], "VIEW_RAW_MISMATCH", "frozen")
    require(decimal(mandate["headroom"]) == st["budget"] - st["charged"], "HEADROOM", mandate["headroom"])
    require(st["charged"] <= st["budget"], "CAP_EXCEEDED", {"C": str(st["charged"]), "B": str(st["budget"])})
    require(st["frozen"] is True, "NOT_FROZEN", "final closure", "INCONCLUSIVE")

    # Records and index: positions 0..count-1, each mapping to a distinct retained record.
    count = st["accepted_count"]
    require(sorted(raw["index"]) == list(range(count)), "INDEX_POSITIONS", sorted(raw["index"]))
    ids = [raw["index"][i] for i in range(count)]
    require(len(set(ids)) == count and set(ids) == set(raw["records"]), "RECORD_INDEX",
            {"index": ids, "records": sorted(raw["records"])})
    require(sum(raw["records"][i]["amount"] for i in ids) == st["charged"], "CHARGE_RECORDS",
            "C must equal the sum of retained record amounts")
    last = 0
    ph_bytes = b58decode32(st["policy_hash"])
    for pos, rid in enumerate(ids):
        rec, row = raw["records"][rid], admissions[pos]
        recipient = d["recipients"][rec["recipient_index"]] if rec["recipient_index"] < len(d["recipients"]) else None
        require(recipient is not None, "RECORD_RECIPIENT_INDEX", rid)
        require(row["request_id"] == str(rid) and decimal(row["amount"]) == rec["amount"]
                and row["recipient"] == recipient and row["recipient_index"] == rec["recipient_index"]
                and decimal(row["admission_seq"], 64) == rec["admission_seq"]
                and row["callback_status"] == rec["callback_status"], "ADMISSION_VIEW_RAW", rid)
        require(row["request_digest_hex"] == request_digest(d["vault"], ph_bytes, d["agent"], rid,
                                                            recipient, rec["amount"]),
                "REQUEST_DIGEST", rid)
        require(0 < rec["amount"] <= int(d["max_per_request"]), "RECORD_AMOUNT", rid)
        require(last < rec["admission_seq"] <= st["seq"], "ADMISSION_SEQUENCE", rid)
        last = rec["admission_seq"]
    return admissions, mandate, raw


def check_agent_permission(permission, d):
    require(isinstance(permission, dict) and set(permission) == {"FunctionCall"},
            "AGENT_KEY_PERMISSION", permission)
    p = permission["FunctionCall"]
    require(p["receiver_id"] == d["vault"] and p["method_names"] == ["request_payment"]
            and p["allowance"] is not None and decimal(p["allowance"]) > 0,
            "AGENT_KEY_PERMISSION", p)


# ------------------------------------------------------------------------------------------
# State-change history over (H0, Q]
# ------------------------------------------------------------------------------------------

def history_check(capture, d, creation_block, effects, failed_receipts, policy_body_hex, final_state):
    code_updates, code_repr = [], set()
    allowed_types = {"account_changes": {"account_update", "account_deletion"},
                     "all_access_key_changes": {"access_key_update", "access_key_deletion"},
                     "contract_code_changes": {"contract_code_update", "contract_code_deletion"},
                     "data_changes": {"data_update", "data_deletion"}}
    heights = {b["header"]["hash"]: b["header"]["height"] for b in capture["blocks"]}
    state_series, records, index = [], {}, {}
    for entry in sorted(capture["history"], key=lambda e: heights[e["block_hash"]]):
        for item in entry["result"]["changes"]:
            typ, change = item["type"], item["change"]
            require(typ in allowed_types[entry["kind"]], "STATE_CHANGE_SCHEMA", typ)
            aid = change["account_id"]
            require(aid in {d["vault"], d["agent"]}, "STATE_CHANGE_ACCOUNT", aid)
            cause = item["cause"]
            require(cause["type"] in {"transaction_processing", "action_receipt_processing_started",
                                      "action_receipt_gas_reward", "receipt_processing"},
                    "UNEXPECTED_STATE_CAUSE", cause, "INCONCLUSIVE")
            effect_id = cause.get("tx_hash") if cause["type"] == "transaction_processing" else cause.get("receipt_hash")
            require(effect_id in effects and effects[effect_id] == entry["block_hash"],
                    "STATE_CAUSE_UNMAPPED", cause, "INCONCLUSIVE")
            if typ == "account_deletion":
                raise EvidenceError("ACCOUNT_DELETED", aid, "FAIL")
            if entry["kind"] == "all_access_key_changes":
                require(aid != d["vault"], "VAULT_KEY_HISTORY", item)
                require(typ == "access_key_update", "AGENT_KEY_DELETED", item)
                check_agent_permission(change["access_key"]["permission"], d)
            if entry["kind"] == "contract_code_changes":
                require(aid == d["vault"] and typ == "contract_code_update", "CODE_HISTORY", item)
                code = decode64(change["code_base64"])
                if len(code) == 32:
                    code_repr.add("sha256-digest")
                    require(code.hex() == d["wasm_sha256"], "CODE_HISTORY_HASH", item)
                else:
                    code_repr.add("wasm-bytes")
                    require(hashlib.sha256(code).hexdigest() == d["wasm_sha256"], "CODE_HISTORY_HASH", item)
                code_updates.append(entry["block_hash"])
            if entry["kind"] == "data_changes":
                require(aid == d["vault"], "AGENT_DATA", item)
                require(typ == "data_update", "STORAGE_DELETED", item)
                # A failed receipt may only earn a gas reward; it must never commit data.
                require(cause["type"] == "receipt_processing" and effect_id not in failed_receipts,
                        "FAILED_RECEIPT_COMMITTED_STATE", cause)
                key, value = decode64(change["key_base64"]), decode64(change["value_base64"])
                kind, n = classify_key(key)
                if kind == "STATE":
                    st = decode_state(value)
                    require(st["policy_body_hex"] == policy_body_hex, "POLICY_MUTATED", effect_id)
                    if state_series:
                        prev = state_series[-1]
                        require(st["charged"] >= prev["charged"], "CHARGE_DECREASED",
                                {"from": str(prev["charged"]), "to": str(st["charged"]), "receipt": effect_id})
                        require(st["seq"] >= prev["seq"] and st["accepted_count"] >= prev["accepted_count"],
                                "SEQUENCE_DECREASED", effect_id)
                        require(st["frozen"] or not prev["frozen"], "UNFROZEN", effect_id)
                        require(st["cb_succeeded_amount"] >= prev["cb_succeeded_amount"]
                                and st["cb_failed_amount"] >= prev["cb_failed_amount"], "CALLBACK_COUNTER_DECREASED", effect_id)
                    require(st["charged"] <= st["budget"], "CAP_EXCEEDED", {"C": str(st["charged"]), "B": str(st["budget"])})
                    state_series.append(dict(st, block_height=heights[entry["block_hash"]], receipt=effect_id))
                elif kind == "record":
                    rec = decode_record(value)
                    if n in records:
                        old = records[n]
                        require(all(old[f] == rec[f] for f in ("recipient_index", "amount", "admission_seq")),
                                "RECORD_MUTATED", n)
                        require(old["callback_status"] == rec["callback_status"]
                                or old["callback_status"] == "Pending", "RECORD_MUTATED", n)
                    records[n] = rec
                else:
                    require(len(value) == 8, "INDEX_VALUE", n)
                    rid = int.from_bytes(value, "little")
                    require(index.get(n, rid) == rid, "INDEX_MUTATED", n)
                    index[n] = rid
    require(code_updates == [creation_block], "CODE_DEPLOYMENT_HISTORY", code_updates)
    require(state_series, "STATE_HISTORY_MISSING", "no STATE writes observed", "INCONCLUSIVE")
    last = state_series[-1]
    for f in ("charged", "seq", "accepted_count", "frozen", "cb_succeeded_amount", "cb_failed_amount"):
        require(last[f] == final_state[f], "HISTORY_FINAL_MISMATCH", f)
    return {"state_writes": len(state_series),
            "charged_series": [str(s["charged"]) for s in state_series],
            "seq_series": [s["seq"] for s in state_series],
            "records_written": sorted(records), "index_written": sorted(index),
            "code_change_representation": sorted(code_repr)}


# ------------------------------------------------------------------------------------------
# Full analysis of an independently acquired capture
# ------------------------------------------------------------------------------------------

def analyze(capture, d):
    """Analyze only a capture acquired by the caller's trusted source object."""
    require(capture["descriptor_sha256"] == digest(d), "DESCRIPTOR_BINDING", "capture")
    heights = {b["header"]["hash"]: b["header"]["height"] for b in capture["blocks"]}
    admissions, mandate, raw = one_cut(capture, d)
    st = raw["STATE"]
    retained = {row["request_id"]: row for row in admissions}
    matched, payments, refunds, gas_refunds, all_seen, vault_effects = set(), [], [], [], set(), []
    creation, effects, events, denials, failures, other_calls = [], {}, [], [], [], []
    failed_receipts, callback_receipts, freeze_receipts = set(), {}, []
    for txid, graph in sorted(capture["graphs"].items()):
        bodies, outcomes, parents = graph_check(txid, graph, capture["root_blocks"][txid], heights, all_seen)
        effects.update({oid: out["block_hash"] for oid, out in outcomes.items()})
        for rid, receipt in bodies.items():
            ab = action_body(receipt)
            kind = outcome_kind(outcomes[rid])
            if kind == "Failure":
                failed_receipts.add(rid)
            if receipt["predecessor_id"] == "system":
                amount = transfer_amount(receipt)
                require(ab["gas_price"] == "0" and not ab["input_data_ids"] and not ab["output_data_receivers"],
                        "REFUND_SHAPE", rid)
                refund = {"tx_hash": txid, "receipt_id": rid, "parent_id": parents[rid],
                          "recipient": receipt["receiver_id"], "amount": str(amount),
                          "outcome": kind, "block_hash": outcomes[rid]["block_hash"]}
                if ab["signer_id"] == "system":
                    # Principal (balance) refund: only from a FAILED parent, back to its predecessor,
                    # for exactly the parent's attached deposit.
                    parent = bodies.get(parents[rid])
                    require(parent is not None and outcome_kind(outcomes[parents[rid]]) == "Failure",
                            "FAKE_PRINCIPAL_REFUND", rid)
                    deposit = sum(decimal(a[next(iter(a))]["deposit"]) for a in action_body(parent)["actions"]
                                  if isinstance(a, dict) and set(a) in ({"Transfer"}, {"FunctionCall"}))
                    require(receipt["receiver_id"] == parent["predecessor_id"] and amount == deposit,
                            "REFUND_PRINCIPAL_LINKAGE", rid)
                    refunds.append(refund)
                else:
                    require(ab["signer_id"] == receipt["receiver_id"], "FAKE_GAS_REFUND", rid)
                    gas_refunds.append(refund)
                continue
            if receipt["predecessor_id"] == d["vault"]:
                vault_effects.append(rid)
                call = single_function_call(receipt)
                if call is not None:
                    require(receipt["receiver_id"] == d["vault"] and call["method_name"] == "on_payment_result"
                            and call["deposit"] == "0", "UNEXPECTED_VAULT_CALL", rid)
                else:
                    transfer_amount(receipt)
            if receipt["receiver_id"] != d["vault"]:
                continue
            actions = ab["actions"]
            children = outcomes[rid]["outcome"]["receipt_ids"]
            vault_children = [c for c in children if bodies[c]["predecessor_id"] == d["vault"]]
            # 1. Failure first: a failed receipt's arguments are never interpreted. It may only
            #    produce system refunds; data/outflow effects are checked here and in history.
            if kind == "Failure":
                require(not vault_children, "FAILED_RECEIPT_DISPATCH", rid)
                method = actions[0]["FunctionCall"]["method_name"] if (
                    len(actions) == 1 and isinstance(actions[0], dict) and "FunctionCall" in actions[0]) else None
                failures.append({"tx_hash": txid, "receipt_id": rid, "predecessor": receipt["predecessor_id"],
                                 "method": method, "class": failure_summary(outcomes[rid]),
                                 "block_hash": outcomes[rid]["block_hash"]})
                continue
            if actions[0] == "CreateAccount":
                # 2.13.4 receipt views carry DeployContract.code as the 32-byte SHA-256 of the WASM.
                require(receipt["predecessor_id"] == d["owner"] and len(actions) == 4
                        and set(actions[1]) == {"Transfer"} and set(actions[2]) == {"DeployContract"}
                        and set(actions[3]) == {"FunctionCall"} and actions[3]["FunctionCall"]["method_name"] == "new"
                        and actions[3]["FunctionCall"]["deposit"] == "0"
                        and decode64(actions[2]["DeployContract"]["code"]).hex() == d["wasm_sha256"],
                        "KEYLESS_CONSTRUCTION", rid)
                require(not vault_children, "CONSTRUCTION_DISPATCH", rid)
                creation.append(outcomes[rid]["block_hash"])
                events.extend(vault_events(outcomes[rid], d))
                continue
            call = single_function_call(receipt)
            if call is None:
                # A successful plain deposit into the vault is inflow, not authority.
                require(len(actions) == 1 and isinstance(actions[0], dict) and set(actions[0]) == {"Transfer"},
                        "UNEXPECTED_VAULT_ACTION", rid)
                other_calls.append({"tx_hash": txid, "receipt_id": rid, "class": "InboundDeposit"})
                continue
            require(call["deposit"] == "0", "VAULT_ATTACHED_DEPOSIT", rid)
            method = call["method_name"]
            ev = vault_events(outcomes[rid], d)
            events.extend(ev)
            if method == "on_payment_result":
                require(receipt["predecessor_id"] == d["vault"] and not vault_children, "CALLBACK_AUTHORITY", rid)
                callback_receipts[rid] = {"args": call_args(call), "events": ev}
                continue
            if method == "freeze":
                require(receipt["predecessor_id"] == d["owner"] and not vault_children, "FREEZE_AUTHORITY", rid)
                freeze_receipts.append({"tx_hash": txid, "receipt_id": rid, "events": ev})
                continue
            if method in VIEW_METHODS:
                require(not vault_children and not ev, "VIEW_CALL_EFFECT", rid)
                other_calls.append({"tx_hash": txid, "receipt_id": rid, "class": "ViewCallTransaction"})
                continue
            require(method == "request_payment", "UNEXPECTED_VAULT_METHOD", {"receipt": rid, "method": method})
            require(receipt["predecessor_id"] == d["agent"], "ADMISSION_AUTHORITY", rid)
            args = call_args(call)
            result = success_json(outcomes[rid])
            require(isinstance(result, dict) and result.get("decision") in {"Admitted", "Denied"},
                    "DECISION_SCHEMA", rid)
            if result["decision"] == "Denied":
                require(not vault_children, "DENIAL_DISPATCH", rid)
                require(len(ev) == 1 and ev[0]["event"] == "denial" and ev[0]["data"]["reason"] == result["reason"]
                        and ev[0]["seq"] == decimal(result["seq"], 64), "DENIAL_EVENT", rid)
                denials.append({"tx_hash": txid, "receipt_id": rid, "request_id": args.get("request_id"),
                                "recipient": args.get("recipient"), "amount": args.get("amount"),
                                "reason": result["reason"], "seq": result["seq"],
                                "block_hash": outcomes[rid]["block_hash"]})
                continue
            direct_transfers = [bodies[c] for c in vault_children
                                if single_function_call(bodies[c]) is None]
            require(len(direct_transfers) == 1, "ADMISSION_AUTHORITY_OR_MULTIPLE_TRANSFERS", rid)
            request_id = args["request_id"]
            decimal(request_id, 64)
            amount = decimal(args["amount"])
            require(args["policy_hash"] == d["policy_hash"] and request_id in retained and request_id not in matched,
                    "UNRETAINED_OR_DUPLICATE_DISPATCH", request_id)
            native = direct_transfers[0]
            native_id = native["receipt_id"]
            require(amount == transfer_amount(native) and 0 < amount <= int(d["max_per_request"])
                    and native["receiver_id"] == args["recipient"] and args["recipient"] in d["recipients"]
                    and retained[request_id]["amount"] == args["amount"]
                    and retained[request_id]["recipient"] == args["recipient"]
                    and result["request_id"] == request_id and result["amount"] == args["amount"]
                    and result["recipient"] == args["recipient"]
                    and result["request_digest_hex"] == retained[request_id]["request_digest_hex"],
                    "TRANSFER_TERMS", request_id)
            require(len(ev) == 1 and ev[0]["event"] == "admission"
                    and ev[0]["seq"] == decimal(retained[request_id]["admission_seq"], 64)
                    and ev[0]["data"]["request_id"] == request_id and ev[0]["data"]["amount"] == args["amount"],
                    "ADMISSION_EVENT", request_id)
            callbacks = [c for c in vault_children if single_function_call(bodies[c]) is not None]
            require(len(callbacks) == 1 and call_args(single_function_call(bodies[callbacks[0]]))["request_id"] == request_id,
                    "CALLBACK_LINKAGE", request_id)
            callback_data = action_body(bodies[callbacks[0]])["input_data_ids"]
            native_data = action_body(native)["output_data_receivers"]
            require(len(callback_data) == 1 and native_data == [{"data_id": callback_data[0], "receiver_id": d["vault"]}],
                    "CALLBACK_DEPENDENCY", request_id)
            hash_id(callback_data[0])
            nkind = outcome_kind(outcomes[native_id])
            require(nkind in {"SuccessValue", "Failure"}, "NATIVE_OUTCOME", native_id)
            payments.append({"request_id": request_id, "tx_hash": txid, "admission_receipt": rid,
                             "transfer_receipt": native_id, "recipient": native["receiver_id"],
                             "amount": str(amount), "class": "F" if nkind == "Failure" else "S",
                             "native_failure": failure_summary(outcomes[native_id]) if nkind == "Failure" else None,
                             "admission_block": outcomes[rid]["block_hash"],
                             "execution_block": outcomes[native_id]["block_hash"],
                             "callback_receipt": callbacks[0],
                             "callback_outcome": outcome_kind(outcomes[callbacks[0]]),
                             "callback_status_retained": retained[request_id]["callback_status"],
                             "admission_seq": retained[request_id]["admission_seq"]})
            matched.add(request_id)
    require(len(creation) == 1, "CONSTRUCTION_MISSING_OR_REPEATED", creation, "INCONCLUSIVE")
    require(matched == set(retained), "UNMATCHED_ADMISSIONS", sorted(set(retained)-matched), "INCONCLUSIVE")
    mapped = {p["transfer_receipt"] for p in payments} | {p["callback_receipt"] for p in payments}
    require(set(vault_effects) == mapped, "UNMATCHED_VAULT_OUTFLOW", sorted(set(vault_effects)-mapped))

    # Native settlement and principal refunds (distinct from callback observations).
    for p in payments:
        linked = [r for r in refunds if r["parent_id"] == p["transfer_receipt"]]
        require(len(linked) == (1 if p["class"] == "F" else 0), "PRINCIPAL_REFUND_MISSING_OR_EXTRA",
                p["request_id"], "INCONCLUSIVE")
        if linked:
            require(linked[0]["outcome"] == "SuccessValue" and linked[0]["recipient"] == d["vault"]
                    and linked[0]["amount"] == p["amount"], "REFUND_NOT_SUCCESSFUL", linked[0], "INCONCLUSIVE")
            p["principal_refund_receipt"] = linked[0]["receipt_id"]
            p["principal_refund_block"] = linked[0]["block_hash"]
        cb = callback_receipts.get(p["callback_receipt"])
        require(cb is not None and p["callback_outcome"] == "SuccessValue", "CALLBACK_UNCONFIRMED",
                p["request_id"], "INCONCLUSIVE")
        expected_status = "CbFailed" if p["class"] == "F" else "CbSucceeded"
        require(p["callback_status_retained"] == expected_status and len(cb["events"]) == 1
                and cb["events"][0]["data"]["callback_status"] == expected_status,
                "CALLBACK_NATIVE_DISAGREEMENT", p["request_id"], "INCONCLUSIVE")
        p["callback_seq"] = str(cb["events"][0]["seq"])

    # Committed event sequence: exactly 0..seq, once each, in execution order, consistent with C.
    events.sort(key=lambda e: e["seq"])
    require([e["seq"] for e in events] == list(range(st["seq"] + 1)), "EVENT_SEQUENCE",
            {"observed": [e["seq"] for e in events], "final_seq": st["seq"]})
    require(events[0]["event"] == "init", "EVENT_INIT", events[0]["event"])
    order = [heights[e["block_hash"]] for e in events]
    require(order == sorted(order), "EVENT_ORDER", order)
    running, cb_s, cb_f, frozen_seen = 0, 0, 0, False
    for e in events[1:]:
        data = e["data"]
        require(not frozen_seen or e["event"] not in {"admission"}, "ADMISSION_AFTER_FREEZE", e["seq"])
        if e["event"] == "admission":
            require(decimal(data["charged_before"]) == running, "EVENT_CHARGE", e["seq"])
            running += decimal(data["amount"])
            require(decimal(data["charged_after"]) == running <= int(d["budget"]), "EVENT_CHARGE", e["seq"])
        elif e["event"] == "denial":
            require(decimal(data["charged"]) == running, "EVENT_CHARGE", e["seq"])
        elif e["event"] == "callback":
            require(decimal(data["charged"]) == running, "EVENT_CHARGE", e["seq"])
            cb_s, cb_f = decimal(data["cb_succeeded_amount"]), decimal(data["cb_failed_amount"])
        elif e["event"] == "freeze":
            require(decimal(data["charged"]) == running and not frozen_seen, "EVENT_FREEZE", e["seq"])
            frozen_seen = True
        else:
            raise EvidenceError("EVENT_REPEATED_INIT", e["seq"], "FAIL")
    require(running == st["charged"] and cb_s == st["cb_succeeded_amount"] and cb_f == st["cb_failed_amount"]
            and frozen_seen == st["frozen"], "EVENT_STATE_RECONCILIATION", "final")
    require(len(freeze_receipts) >= 1, "FREEZE_MISSING", "final closure", "INCONCLUSIVE")

    hist = history_check(capture, d, creation[0], effects, failed_receipts, st["policy_body_hex"], st)

    c = sum(int(p["amount"]) for p in payments)
    s = sum(int(p["amount"]) for p in payments if p["class"] == "S")
    f = sum(int(p["amount"]) for p in payments if p["class"] == "F")
    u = c - s - f
    require(c == st["charged"], "CHARGE_RECONCILIATION", {"derived": str(c), "state": str(st["charged"])})
    require(c <= int(d["budget"]), "CAP_EXCEEDED", {"C": str(c), "B": d["budget"]})
    principal = [r for r in refunds if r["parent_id"] in {p["transfer_receipt"] for p in payments}]
    return {"root_ids": sorted(capture["graphs"]), "payments": payments,
            "denials": denials, "failed_calls": failures, "other_vault_calls": other_calls,
            "freeze": freeze_receipts,
            "principal_refunds": principal, "balance_refunds": refunds, "gas_refunds": gas_refunds,
            "events": [{"seq": e["seq"], "event": e["event"], "receipt_id": e["receipt_id"],
                        "block_height": heights[e["block_hash"]]} for e in events],
            "state_history": hist,
            "ledger": {"C": str(c), "S": str(s), "F": str(f), "U": str(u),
                       "headroom": str(int(d["budget"]) - c), "accepted_count": st["accepted_count"]},
            "callback_observation": {"cb_succeeded_amount": str(st["cb_succeeded_amount"]),
                                     "cb_failed_amount": str(st["cb_failed_amount"])},
            "attribution": {"vault": d["vault"], "chain_id": d["chain_id"],
                            "genesis_block_hash": d["genesis_block_hash"], "wasm_sha256": d["wasm_sha256"],
                            "policy_hash": d["policy_hash"],
                            "h0": {"hash": d["h0_hash"], "height": d["h0_height"]},
                            "q": {"hash": d["q_hash"], "height": d["q_height"]}}}


def scenario_check(recovered, d):
    """Compare against the reviewer's declared expectation (never the runner's)."""
    exp = d.get("expected")
    if not exp:
        return "INCONCLUSIVE", ["no reviewer expectation declared"]
    got = {"ledger": recovered["ledger"],
           "principal_refunds": len(recovered["principal_refunds"]),
           "denial_reasons": sorted(x["reason"] for x in recovered["denials"]),
           "failed_call_classes": sorted(x["class"] for x in recovered["failed_calls"])}
    diffs = [k for k in exp if canonical(exp[k]) != canonical(got.get(k))]
    return ("PASS" if not diffs else "FAIL"), diffs


def compare_bundle(capture, presented, recovered=None):
    """Checksums are diagnostic only. Compare actual independent root/graph sets."""
    differences = []
    require(isinstance(presented, dict) and presented.get("schema") == "near-g1-capture/v1",
            "PRESENTED_SCHEMA", "expected capture object")
    require(isinstance(presented.get("graphs"), dict) and isinstance(presented.get("status"), dict),
            "PRESENTED_SCHEMA", "graphs/status must be objects")
    for txid in presented["graphs"]:
        hash_id(txid)
    trusted = capture["graphs"]
    supplied = presented["graphs"]
    for txid in sorted(set(trusted) - set(supplied)):
        item = {"code": "OMITTED_ROOT", "tx_hash": txid,
                "recovered_receipts": sorted(r["receipt_id"] for r in trusted[txid]["receipts"])}
        if recovered:
            item["recovered_effects"] = {
                k: [x for x in recovered.get(k, []) if x.get("tx_hash") == txid]
                for k in ("payments", "denials", "failed_calls", "balance_refunds", "gas_refunds")}
        differences.append(item)
    for txid in sorted(set(supplied) - set(trusted)):
        differences.append({"code": "INVENTED_ROOT", "tx_hash": txid})
    for txid in sorted(set(trusted) & set(supplied)):
        if canonical(trusted[txid]) != canonical(supplied[txid]):
            differences.append({"code": "TAMPERED_GRAPH", "tx_hash": txid})
    for field in ("descriptor_sha256", "root_blocks", "queries", "blocks", "chunks", "protocol", "initial_absence", "history", "genesis", "genesis_block"):
        if canonical(capture[field]) != canonical(presented.get(field)):
            differences.append({"code": "TAMPERED_CAPTURE_FIELD", "field": field})
    if any(capture["status"].get(k) != presented.get("status", {}).get(k) for k in ("chain_id", "version")):
        differences.append({"code": "TAMPERED_CAPTURE_FIELD", "field": "status identity"})
    return differences


LIMITATIONS = [
    "Trusted-node observations from the reviewer-selected endpoint, not consensus/light-client inclusion proofs.",
    "Binary file hash is recorded; RPC process-to-binary correspondence is not cryptographically authenticated.",
    "Runner isolation, ingress closure and retention are run-level properties recorded by the run tooling, not by this verifier.",
    "Bounded adapter: one epoch, unchanged shard layout, sandbox network only (public networks are inspection-only).",
    "No native-pending witness; simultaneous RPC sends cannot establish one.",
]


def verify(source, descriptor, presented=None):
    from packages.collector import collect
    result = {"schema": "near-g1-result/v1", "mode": source.mode,
              "verdicts": {k: "INCONCLUSIVE" for k in ("safety", "settlement", "evidence", "scenario_coverage")},
              "chain_evidence_checks": "INCONCLUSIVE", "issues": [], "recovery": None,
              "limitations": LIMITATIONS}
    capture = None
    try:
        capture = collect(source, descriptor)
        result.update(evaluate(capture, descriptor, source.mode, presented))
    except EvidenceError as exc:
        result["issues"].append({"code": exc.code, "detail": exc.detail})
        result["verdicts"]["evidence"] = exc.verdict
        if exc.code in SAFETY_CODES and exc.verdict == "FAIL":
            result["verdicts"]["safety"] = "FAIL"
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError, IndexError) as exc:
        result["issues"].append({"code": "UNSUPPORTED_OR_MALFORMED_SCHEMA", "detail": repr(exc)})
    return result, capture


def evaluate(capture, descriptor, mode, presented=None):
    """Offline evaluation of an already-acquired capture (no network)."""
    out = {"verdicts": {k: "INCONCLUSIVE" for k in ("safety", "settlement", "evidence", "scenario_coverage")},
           "chain_evidence_checks": "INCONCLUSIVE", "issues": [], "recovery": None}
    try:
        recovered = analyze(capture, descriptor)
    except EvidenceError as exc:
        out["issues"].append({"code": exc.code, "detail": exc.detail})
        out["verdicts"]["evidence"] = exc.verdict
        if exc.code in SAFETY_CODES and exc.verdict == "FAIL":
            out["verdicts"]["safety"] = "FAIL"
        return out
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError, IndexError) as exc:
        out["issues"].append({"code": "UNSUPPORTED_OR_MALFORMED_SCHEMA", "detail": repr(exc)})
        return out
    out["chain_evidence_checks"] = "PASS"
    out["recovery"] = recovered
    scenario, diffs = scenario_check(recovered, descriptor)
    computed = {"safety": "PASS", "settlement": "PASS" if recovered["ledger"]["U"] == "0" else "INCONCLUSIVE",
                "evidence": "PASS", "scenario_coverage": scenario}
    if diffs:
        out["issues"].append({"code": "SCENARIO_MISMATCH", "detail": diffs})
    if presented is not None:
        differences = compare_bundle(capture, presented, recovered)
        out["issues"].extend(differences)
        if differences:
            computed["evidence"] = "FAIL"
    if mode == "LIVE":
        out["verdicts"] = computed
    else:
        # Synthetic or replayed sources never yield a runtime PASS; FAIL still propagates.
        out["computed_if_live"] = computed
        out["verdicts"] = {k: ("FAIL" if v == "FAIL" else "INCONCLUSIVE") for k, v in computed.items()}
        out["issues"].append({"code": "NOT_LIVE_ACQUISITION", "detail": mode})
    return out
