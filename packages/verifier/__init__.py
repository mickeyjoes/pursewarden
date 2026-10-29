"""Strict graph/effect reconciliation; never a verdict imported from the runner."""

import hashlib

from packages.collector import (EvidenceError, account, b58, canonical, decimal,
                                decode64, digest, hash_id, loads, require)


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
                        and ab["actions"] == tx["actions"] and ab["signer_id"] == tx["signer_id"],
                        "FIRST_RECEIPT_LINKAGE", oid)
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


def transfer_amount(receipt):
    actions = action_body(receipt)["actions"]
    require(len(actions) == 1 and isinstance(actions[0], dict) and set(actions[0]) == {"Transfer"},
            "EXPECTED_NATIVE_TRANSFER", receipt["receipt_id"])
    return decimal(actions[0]["Transfer"]["deposit"])


def function_call(receipt):
    actions = action_body(receipt)["actions"]
    if len(actions) == 1 and isinstance(actions[0], dict) and set(actions[0]) == {"FunctionCall"}:
        call = actions[0]["FunctionCall"]
        decimal(call["deposit"])
        return call, loads(decode64(call["args"]))
    return None


def one_cut(capture, d):
    q = d["q_hash"]
    for name, response in capture["queries"].items():
        require(response["block_hash"] == q and response["block_height"] == d["q_height"],
                "QUERY_CUT", name)
    queries = capture["queries"]
    code = decode64(queries["vault/view_code"]["code_base64"])
    sha = hashlib.sha256(code).digest()
    require(sha.hex() == d["wasm_sha256"], "WRONG_CONTRACT", "compiled WASM mismatch")
    for name in ("vault/view_account", "vault/view_code"):
        require(queries[name]["code_hash"] == b58(sha), "WRONG_CODE_HASH", name)
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
    admissions = loads(bytes(queries["get_admissions"]["result"]))
    mandate = loads(bytes(queries["get_mandate"]["result"]))
    # This is a strict integration adapter, not aliases guessed from runner labels.
    require(isinstance(admissions, list) and len(admissions) <= 64, "ADMISSIONS_SCHEMA", "bounded list")
    require(mandate["vault"] == d["vault"] and mandate["agent"] == d["agent"]
            and mandate["owner"] == d["owner"] and mandate["chain_id"] == d["chain_id"]
            and mandate["policy_hash"] == d["policy_hash"] and mandate["budget"] == d["budget"],
            "MANDATE_IDENTITY", "expected reviewer policy")
    require(mandate["frozen"] is True, "NOT_FROZEN", "final closure", "INCONCLUSIVE")
    require(type(mandate["accepted_count"]) is int and mandate["accepted_count"] == len(admissions),
            "ADMISSION_COUNT", "view disagreement")
    decimal(mandate["charged"])
    require(type(mandate["sequence"]) is int and 0 <= mandate["sequence"] < 2**64,
            "SEQUENCE_SCHEMA", mandate["sequence"])
    return admissions, mandate


def check_agent_permission(permission, d):
    require(isinstance(permission, dict) and set(permission) == {"FunctionCall"},
            "AGENT_KEY_PERMISSION", permission)
    p = permission["FunctionCall"]
    require(p["receiver_id"] == d["vault"] and p["method_names"] == ["request_payment"]
            and p["allowance"] is not None and decimal(p["allowance"]) > 0,
            "AGENT_KEY_PERMISSION", p)


def history_check(capture, d, creation_block, effects):
    code_updates = []
    allowed_types = {"account_changes": {"account_update", "account_deletion"},
                     "all_access_key_changes": {"access_key_update", "access_key_deletion"},
                     "contract_code_changes": {"contract_code_update", "contract_code_deletion"},
                     "data_changes": {"data_update", "data_deletion"}}
    for entry in capture["history"]:
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
                require(aid == d["vault"] and typ == "contract_code_update",
                        "CODE_HISTORY", item)
                require(hashlib.sha256(decode64(change["code_base64"])).hexdigest() == d["wasm_sha256"],
                        "CODE_HISTORY_HASH", item)
                code_updates.append(entry["block_hash"])
    require(code_updates == [creation_block], "CODE_DEPLOYMENT_HISTORY", code_updates)


def analyze(capture, d):
    """Analyze only a capture acquired by the caller's trusted source object."""
    require(capture["descriptor_sha256"] == digest(d), "DESCRIPTOR_BINDING", "capture")
    heights = {b["header"]["hash"]: b["header"]["height"] for b in capture["blocks"]}
    admissions, mandate = one_cut(capture, d)
    retained, sequences = {}, set()
    last_sequence = 0
    for row in admissions:
        rid = row["request_id"]
        decimal(rid, 64)
        decimal(row["amount"])
        account(row["recipient"])
        require(rid not in retained, "DUPLICATE_ACCEPTED_ID", rid)
        require(type(row["admission_sequence"]) is int and last_sequence < row["admission_sequence"] <= mandate["sequence"],
                "ADMISSION_SEQUENCE", rid)
        last_sequence = row["admission_sequence"]
        require(row["admission_sequence"] not in sequences, "DUPLICATE_ADMISSION_SEQUENCE", rid)
        sequences.add(row["admission_sequence"])
        retained[rid] = row
    matched, payments, refunds, gas_refunds, all_seen, vault_effects = set(), [], [], [], set(), []
    creation, effects = [], {}
    for txid, graph in capture["graphs"].items():
        bodies, outcomes, parents = graph_check(txid, graph, capture["root_blocks"][txid], heights, all_seen)
        effects.update({oid: out["block_hash"] for oid, out in outcomes.items()})
        for rid, receipt in bodies.items():
            ab = action_body(receipt)
            if receipt["predecessor_id"] == "system":
                amount = transfer_amount(receipt)
                require(ab["gas_price"] == "0" and not ab["input_data_ids"] and not ab["output_data_receivers"],
                        "REFUND_SHAPE", rid)
                refund = {"tx_hash": txid, "receipt_id": rid, "parent_id": parents[rid],
                          "recipient": receipt["receiver_id"], "amount": str(amount),
                          "outcome": outcome_kind(outcomes[rid])}
                if ab["signer_id"] == "system":
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
            if receipt["predecessor_id"] == d["vault"]:
                vault_effects.append(rid)
                call = function_call(receipt)
                if call:
                    require(receipt["receiver_id"] == d["vault"] and call[0]["method_name"] == "on_payment_result"
                            and call[0]["deposit"] == "0", "UNEXPECTED_VAULT_CALL", rid)
                else:
                    transfer_amount(receipt)
            if receipt["receiver_id"] != d["vault"] or receipt["predecessor_id"] == "system":
                continue
            actions = ab["actions"]
            if actions[0] == "CreateAccount":
                require(receipt["predecessor_id"] == d["owner"] and len(actions) == 4
                        and set(actions[1]) == {"Transfer"} and set(actions[2]) == {"DeployContract"}
                        and set(actions[3]) == {"FunctionCall"} and actions[3]["FunctionCall"]["method_name"] == "new"
                        and actions[3]["FunctionCall"]["deposit"] == "0"
                        and hashlib.sha256(decode64(actions[2]["DeployContract"]["code"])).hexdigest() == d["wasm_sha256"]
                        and outcome_kind(outcomes[rid]) != "Failure", "KEYLESS_CONSTRUCTION", rid)
                creation.append(outcomes[rid]["block_hash"])
                continue
            fc = function_call(receipt)
            require(fc is not None, "UNEXPECTED_VAULT_ACTION", rid)
            call, args = fc
            require(call["deposit"] == "0", "VAULT_ATTACHED_DEPOSIT", rid)
            method = call["method_name"]
            if method != "request_payment":
                require((method == "freeze" and receipt["predecessor_id"] == d["owner"])
                        or (method == "on_payment_result" and receipt["predecessor_id"] == d["vault"]),
                        "VAULT_METHOD_AUTHORITY", rid)
                continue
            direct_transfers = [bodies[c] for c in outcomes[rid]["outcome"]["receipt_ids"]
                                if bodies[c]["predecessor_id"] == d["vault"]
                                and any(isinstance(a, dict) and "Transfer" in a for a in action_body(bodies[c])["actions"])]
            if outcome_kind(outcomes[rid]) == "Failure":
                require(not direct_transfers, "FAILED_ADMISSION_DISPATCH", rid)
                continue
            if not direct_transfers:
                continue  # Denial has no authority; never infer admission from logs.
            require(receipt["predecessor_id"] == d["agent"] and len(direct_transfers) == 1,
                    "ADMISSION_AUTHORITY_OR_MULTIPLE_TRANSFERS", rid)
            request_id = args["request_id"]
            decimal(request_id, 64)
            amount = decimal(args["amount"])
            require(args["policy_hash"] == d["policy_hash"] and request_id in retained and request_id not in matched,
                    "UNRETAINED_OR_DUPLICATE_DISPATCH", request_id)
            native = direct_transfers[0]
            native_id = native["receipt_id"]
            require(amount == transfer_amount(native) and amount > 0 and amount <= int(d["max_per_request"])
                    and native["receiver_id"] == args["recipient"] and args["recipient"] in d["recipients"]
                    and retained[request_id]["amount"] == args["amount"]
                    and retained[request_id]["recipient"] == args["recipient"], "TRANSFER_TERMS", request_id)
            callbacks = [c for c in outcomes[rid]["outcome"]["receipt_ids"]
                         if bodies[c]["predecessor_id"] == d["vault"] and function_call(bodies[c])]
            require(len(callbacks) == 1 and function_call(bodies[callbacks[0]])[1]["request_id"] == request_id,
                    "CALLBACK_LINKAGE", request_id)
            callback_data = action_body(bodies[callbacks[0]])["input_data_ids"]
            native_data = action_body(native)["output_data_receivers"]
            require(len(callback_data) == 1 and native_data == [{"data_id": callback_data[0], "receiver_id": d["vault"]}],
                    "CALLBACK_DEPENDENCY", request_id)
            hash_id(callback_data[0])
            kind = outcome_kind(outcomes[native_id])
            require(kind in {"SuccessValue", "Failure"}, "NATIVE_OUTCOME", native_id)
            payments.append({"request_id": request_id, "tx_hash": txid, "admission_receipt": rid,
                             "transfer_receipt": native_id, "recipient": native["receiver_id"],
                             "amount": str(amount), "class": "F" if kind == "Failure" else "S",
                             "execution_block": outcomes[native_id]["block_hash"],
                             "callback_receipt": callbacks[0],
                             "callback_outcome": outcome_kind(outcomes[callbacks[0]])})
            matched.add(request_id)
    require(len(creation) == 1, "CONSTRUCTION_MISSING_OR_REPEATED", creation, "INCONCLUSIVE")
    history_check(capture, d, creation[0], effects)
    require(matched == set(retained), "UNMATCHED_ADMISSIONS", sorted(set(retained)-matched), "INCONCLUSIVE")
    mapped = {p["transfer_receipt"] for p in payments} | {p["callback_receipt"] for p in payments}
    require(set(vault_effects) == mapped, "UNMATCHED_VAULT_OUTFLOW", sorted(set(vault_effects)-mapped))
    for p in payments:
        linked = [r for r in refunds if r["parent_id"] == p["transfer_receipt"]]
        require(len(linked) == (1 if p["class"] == "F" else 0), "PRINCIPAL_REFUND_MISSING_OR_EXTRA",
                p["request_id"], "INCONCLUSIVE")
        if linked:
            require(linked[0]["outcome"] == "SuccessValue", "REFUND_NOT_SUCCESSFUL", linked[0], "INCONCLUSIVE")
            p["principal_refund_receipt"] = linked[0]["receipt_id"]
    c = sum(int(p["amount"]) for p in payments)
    s = sum(int(p["amount"]) for p in payments if p["class"] == "S")
    f = sum(int(p["amount"]) for p in payments if p["class"] == "F")
    require(c == int(mandate["charged"]), "CHARGE_RECONCILIATION", {"derived": str(c), "view": mandate["charged"]})
    require(c <= int(d["budget"]), "CAP_EXCEEDED", {"C": str(c), "B": d["budget"]})
    return {"root_ids": sorted(capture["graphs"]), "payments": payments,
            "principal_refunds": [r for r in refunds if r["parent_id"] in {p["transfer_receipt"] for p in payments}],
            "balance_refunds": refunds, "gas_refunds": gas_refunds,
            "ledger": {"C": str(c), "S": str(s), "F": str(f), "U": "0",
                       "headroom": str(int(d["budget"])-c)},
            "attribution": {"vault": d["vault"], "chain_id": d["chain_id"],
                            "genesis_block_hash": d["genesis_block_hash"], "wasm_sha256": d["wasm_sha256"],
                            "h0_hash": d["h0_hash"], "q_hash": d["q_hash"]}}


def compare_bundle(capture, presented):
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
        differences.append({"code": "OMITTED_ROOT", "tx_hash": txid,
                            "recovered_receipts": sorted(r["receipt_id"] for r in trusted[txid]["receipts"])})
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


def verify(source, descriptor, presented=None):
    from packages.collector import collect
    result = {"schema": "near-g1-result/v1", "mode": source.mode,
              "verdicts": {k: "INCONCLUSIVE" for k in ("safety", "settlement", "evidence", "scenario_coverage")},
              "chain_evidence_checks": "INCONCLUSIVE", "issues": [], "recovery": None}
    capture = None
    try:
        capture = collect(source, descriptor)
        recovered = analyze(capture, descriptor)
        result["chain_evidence_checks"] = "PASS"
        result["recovery"] = recovered
        if presented is not None:
            result["issues"].extend(compare_bundle(capture, presented))
            if result["issues"]:
                result["verdicts"]["evidence"] = "FAIL"
        # Deliberate gate: checked graphs alone do not prove isolation, 2000-block
        # retention, state/event sequence or artifact/runtime qualification.
        result["limitations"] = [
            "No independent runtime G1 run or fresh-instance rerun has qualified this implementation.",
            "Runner/admin isolation and empty H0 receipt frontier require reviewer demonstration.",
            "Binary file hash is recorded, but RPC process-to-binary correspondence is not authenticated.",
            "State/event sequence, raw storage decoding, reserve/gas and WASM capability gates remain outside this adapter.",
            "No native-pending witness; simultaneous RPC sends cannot establish one.",
            "Trusted-node observations, not consensus inclusion proofs or public-network completeness."]
    except EvidenceError as exc:
        result["issues"].append({"code": exc.code, "detail": exc.detail})
        result["verdicts"]["evidence"] = exc.verdict
        if exc.code in {"CAP_EXCEEDED", "UNMATCHED_VAULT_OUTFLOW", "FAILED_ADMISSION_DISPATCH",
                        "UNRETAINED_OR_DUPLICATE_DISPATCH", "VAULT_HAS_KEYS", "VAULT_KEY_HISTORY"}:
            result["verdicts"]["safety"] = "FAIL"
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        result["issues"].append({"code": "UNSUPPORTED_OR_MALFORMED_SCHEMA", "detail": str(exc)})
    return result, capture
