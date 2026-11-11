"""Read-only inspection of a smoke run (testnet or sandbox), labelled as such.

This is NOT the independent completeness check used for the sandbox evidence:
- The transaction list comes from the runner's file. Every hash is re-read from the node, never
  trusted from the file.
- A public node gives no reviewer-owned fresh frontier. Roots the runner did not list are not
  discovered.

What it does verify, at one final block Q chosen by the inspector:
- the vault's creation transaction (listed as `create_vault`; required) is FINAL and is exactly
  [CreateAccount, Transfer, DeployContract(reviewed artifact), FunctionCall(new, no deposit)] from
  the owner, `new` returned the policy hash, and the only other receipt it produced is the
  system's gas refund to the owner. Zero keys and the right code at Q do not prove this on their
  own: an extra deploy-and-call inside the creation batch can leave a postponed receipt (such as
  a delayed AddKey) that no state query shows (final audit PW-01);
- deployed code hash = the reviewed artifact;
- zero vault access keys;
- the agent's keys are FunctionCall-only (request_payment on the vault);
- the raw Borsh state decodes to the ten-field policy, and the policy hash is recomputed;
- records, index, views and request digests are consistent;
- the vault is frozen;
- each listed transaction's FINAL receipt graph closes;
- the decisions and native transfer outcomes match the expected smoke scenario.

What it cannot see: receipts left by an EARLIER account with the same name (created, deleted and
re-created before this vault), and anything the node does not return. Both are trusted to the
single RPC node and to the account's parent, which alone can create the name.
"""
from packages.collector import EvidenceError, account, decode64, loads, require
from packages.verifier import (action_body, failure_summary, graph_check, keyless_construction_actions, one_cut,
                               outcome_kind)

SCHEMA = "pursewarden-smoke-inspection/v2"
SCHEMA_V1 = "pursewarden-smoke-inspection/v1"
CREATION_LABEL = "create_vault"
EXPECT = {"pay_1_payee": ("Admitted", "S"), "pay_2_missing": ("Admitted", "F"), "replay_1": ("Denied", "DuplicateRequest"),
          "over_cap": ("Denied", "AboveMaxPerRequest"), "exfiltrate": ("Denied", "RecipientNotAllowed"),
          "budget_exceeded": ("Denied", "BudgetExceeded")}


def action_names(actions):
    if not isinstance(actions, list):
        return type(actions).__name__
    return [a if isinstance(a, str) else ",".join(a) if isinstance(a, dict) else type(a).__name__ for a in actions]


def tx_status(source, t):
    return source.call("EXPERIMENTAL_tx_status", {"tx_hash": t["tx_hash"], "sender_account_id": t["signer"],
                                                  "wait_until": "FINAL"})


def creation_entry(run):
    """The runner must list the vault's creation transaction exactly once. Fail closed otherwise."""
    listed = [t for t in run["transactions"] if t.get("label") == CREATION_LABEL]
    require(listed, "CREATION_TX_MISSING", "the run lists no create_vault transaction; construction cannot be checked")
    require(len(listed) == 1, "CREATION_TX_AMBIGUOUS", len(listed))
    t = listed[0]
    require("validation_rejected" not in t and isinstance(t.get("tx_hash"), str) and t.get("signer") == run["owner"],
            "CREATION_TX_IDENTITY", {"signer": t.get("signer"), "owner": run["owner"]})
    return t


def check_construction(g, d, seen):
    """Fail closed unless the creation graph is the approved keyless construction and nothing else.

    Same shape rule as the sandbox verifier (KEYLESS_CONSTRUCTION, CONSTRUCTION_DISPATCH), applied to
    one re-read creation transaction instead of an independently discovered graph."""
    tx = g["transaction"]
    require(tx["signer_id"] == d["owner"] and tx["receiver_id"] == d["vault"], "CREATION_TX_IDENTITY",
            {"signer": tx["signer_id"], "receiver": tx["receiver_id"]})
    # Shape first, from the signed transaction: a batch with any extra action fails here, before the
    # graph check would reject an unsupported (e.g. yielded) receipt as merely INCONCLUSIVE.
    require(isinstance(tx["actions"], list) and keyless_construction_actions(tx["actions"], d["wasm_sha256"]),
            "KEYLESS_CONSTRUCTION", {"tx_hash": tx["hash"], "actions": action_names(tx["actions"])})
    heights = {o["block_hash"]: 0 for o in [g["transaction_outcome"]] + g["receipts_outcome"]}
    bodies, outcomes, _ = graph_check(tx["hash"], g, g["transaction_outcome"]["block_hash"], heights, seen)
    first = g["transaction_outcome"]["outcome"]["receipt_ids"]
    require(len(first) == 1, "CONSTRUCTION_RECEIPTS", first)
    rid = first[0]
    receipt = bodies[rid]
    require(receipt["predecessor_id"] == d["owner"] and receipt["receiver_id"] == d["vault"]
            and keyless_construction_actions(action_body(receipt)["actions"], d["wasm_sha256"]),
            "KEYLESS_CONSTRUCTION", rid)
    require(outcome_kind(outcomes[rid]) == "SuccessValue"
            and decode64(outcomes[rid]["outcome"]["status"]["SuccessValue"]) == f'"{d["policy_hash"]}"'.encode(),
            "CONSTRUCTION_RESULT", {"receipt_id": rid, "expected_policy_hash": d["policy_hash"]})
    # Nothing may follow from the creation except the system's gas refund to the owner. A receipt
    # from the vault (a promise, key or deploy) would be a capability the final state does not show.
    for oid, b in bodies.items():
        if oid == rid:
            continue
        ab = action_body(b)
        require(b["predecessor_id"] == "system" and b["receiver_id"] == d["owner"] and ab["signer_id"] == d["owner"]
                and len(ab["actions"]) == 1 and isinstance(ab["actions"][0], dict)
                and set(ab["actions"][0]) == {"Transfer"}, "CONSTRUCTION_DISPATCH",
                {"receipt_id": oid, "predecessor": b["predecessor_id"], "actions": action_names(ab["actions"])})
    summary = {"tx_hash": tx["hash"], "receipt_id": rid, "block_hash": outcomes[rid]["block_hash"],
               "actions": ["CreateAccount", "Transfer", "DeployContract", "FunctionCall"],
               "deployed_code_sha256": d["wasm_sha256"], "init_method": "new",
               "init_returned_policy_hash": d["policy_hash"], "other_receipts": len(bodies) - 1,
               "other_receipts_are": "system gas refunds to the owner only; no receipt from the vault"}
    return summary, len(bodies)


def replays_committed(res, committed):
    """True if a fresh inspection reproduces a committed one. A committed v1 inspection predates the
    construction check: v2 adds the `construction` block and changes nothing else."""
    c = {k: v for k, v in committed.items() if k != "metrics"}
    if c.get("schema") == SCHEMA:
        return res == c
    if c.get("schema") == SCHEMA_V1 and res.get("schema") == SCHEMA and "construction" in res:
        return ({k: v for k, v in res.items() if k not in ("schema", "construction")}
                == {k: v for k, v in c.items() if k != "schema"})
    return False


def inspect(source, run, wasm_sha256):
    creation = creation_entry(run)
    out = {"schema": SCHEMA, "network": run["network"],
           "label": f"{run['network'].upper()} SMOKE INSPECTION: runner-listed transactions re-read from the node; "
                    "not an independent completeness proof", "issues": []}
    status = source.call("status", {})
    require(status["chain_id"] == run["chain_id"] and status["chain_id"] != "mainnet", "WRONG_CHAIN", status["chain_id"])
    final = source.call("block", {"finality": "final"})
    q, qh = final["header"]["hash"], final["header"]["height"]
    vault, agent = account(run["vault"]), account(run["agent"])
    d = {"q_hash": q, "q_height": qh, "vault": vault, "owner": run["owner"], "agent": agent, "chain_id": run["chain_id"],
         "recipients": run["recipients"], "policy_hash": run["policy_hash"], "budget": run["budget"],
         "max_per_request": run["max_per_request"], "expires_at_ns": run["expires_at_ns"],
         "max_accepted_requests": run["max_accepted_requests"], "wasm_sha256": wasm_sha256,
         "agent_key_count": len(run["agent_public_keys"])}
    seen = set()
    # How the vault was born, before what it looks like now.
    try:
        creation_graph = tx_status(source, creation)
    except EvidenceError as exc:
        # A creation batch with an outstanding postponed receipt does not become FINAL until it fires,
        # so "not returned as FINAL" is never read as success.
        raise EvidenceError("CREATION_TX_UNAVAILABLE", {"tx_hash": creation["tx_hash"], "cause": exc.code,
                            "detail": exc.detail, "note": "the node did not return the creation transaction as FINAL"},
                            "INCONCLUSIVE") from exc
    out["construction"], creation_receipts = check_construction(creation_graph, d, seen)
    queries = {}
    for role, aid in (("vault", vault), ("agent", agent)):
        for kind in ("view_account", "view_code", "view_access_key_list"):
            try:
                queries[f"{role}/{kind}"] = source.call("query", {"request_type": kind, "account_id": aid, "block_id": q})
            except EvidenceError as exc:
                cause = exc.detail.get("error", {}).get("cause", {}) if isinstance(exc.detail, dict) else {}
                if role == "agent" and kind == "view_code" and cause.get("name") == "NO_CONTRACT_CODE":
                    queries[f"{role}/{kind}"] = {"block_hash": q, "block_height": qh, "absence_error": cause}
                else:
                    raise
    queries["vault/view_state"] = source.call("query", {"request_type": "view_state", "account_id": vault,
                                                        "prefix_base64": "", "block_id": q})
    for method in ("get_admissions", "get_mandate"):
        queries[method] = source.call("query", {"request_type": "call_function", "account_id": vault,
                                                "method_name": method, "args_base64": "e30=", "block_id": q})
    admissions, mandate, raw = one_cut({"queries": queries}, d)
    out["cut"] = {"q_height": qh, "q_hash": q, "code_sha256": wasm_sha256, "vault_keys": 0,
                  "policy_hash": raw["STATE"]["policy_hash"], "charged": str(raw["STATE"]["charged"]),
                  "accepted_count": raw["STATE"]["accepted_count"], "seq": raw["STATE"]["seq"], "frozen": raw["STATE"]["frozen"]}
    steps = []
    for t in run["transactions"]:
        if "validation_rejected" in t:
            steps.append({"label": t["label"], "result": "rejected at validation"}); continue
        if t is creation:
            steps.append({"label": t["label"], "tx_hash": t["tx_hash"], "receipts": creation_receipts}); continue
        g = tx_status(source, t)
        heights = {o["block_hash"]: 0 for o in [g["transaction_outcome"]] + g["receipts_outcome"]}
        bodies, outcomes, _ = graph_check(t["tx_hash"], g, g["transaction_outcome"]["block_hash"], heights, seen)
        first = g["transaction_outcome"]["outcome"]["receipt_ids"][0]
        st = {"label": t["label"], "tx_hash": t["tx_hash"], "receipts": len(bodies)}
        if t["label"] in EXPECT:
            o = outcomes[first]
            require(outcome_kind(o) == "SuccessValue", "UNEXPECTED_FAILURE", t["label"])
            dec = loads(decode64(o["outcome"]["status"]["SuccessValue"]))
            st["decision"] = dec["decision"]
            if dec["decision"] == "Denied":
                st["reason"] = dec["reason"]
            transfers = [b for b in bodies.values() if b["predecessor_id"] == vault
                         and action_body(b)["actions"] and isinstance(action_body(b)["actions"][0], dict)
                         and "Transfer" in action_body(b)["actions"][0]]
            if transfers:
                k = outcome_kind(outcomes[transfers[0]["receipt_id"]])
                st["native"] = "F" if k == "Failure" else "S"
                if k == "Failure":
                    st["native_failure"] = failure_summary(outcomes[transfers[0]["receipt_id"]])
                    st["principal_refund"] = any(b["predecessor_id"] == "system" and b["receiver_id"] == vault
                                                 and action_body(b)["signer_id"] == "system" for b in bodies.values())
            want = EXPECT[t["label"]]
            got = (st["decision"], st.get("native") if st["decision"] == "Admitted" else st.get("reason"))
            if got != want:
                out["issues"].append({"code": "SCENARIO_MISMATCH", "label": t["label"], "expected": want, "observed": got})
        steps.append(st)
    out["steps"] = steps
    s = sum(int(r["amount"]) for r in admissions)
    out["ledger"] = {"C": str(raw["STATE"]["charged"]), "sum_records": str(s),
                     "headroom": str(int(d["budget"]) - raw["STATE"]["charged"])}
    require(s == raw["STATE"]["charged"] <= int(d["budget"]), "CHARGE", out["ledger"])
    out["result"] = "PASS" if not out["issues"] else "FAIL"
    return out
