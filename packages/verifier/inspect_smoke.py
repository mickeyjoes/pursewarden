"""Read-only inspection of a smoke run (testnet or sandbox), labelled as such.

This is NOT the independent completeness check used for the sandbox evidence:
- The transaction list comes from the runner's file. Every hash is re-read from the node, never
  trusted from the file.
- A public node gives no reviewer-owned fresh frontier. Roots the runner did not list are not
  discovered.

What it does verify, at one final block Q chosen by the inspector:
- deployed code hash = the reviewed artifact;
- zero vault access keys;
- the agent's keys are FunctionCall-only (request_payment on the vault);
- the raw Borsh state decodes to the ten-field policy, and the policy hash is recomputed;
- records, index, views and request digests are consistent;
- the vault is frozen;
- each listed transaction's FINAL receipt graph closes;
- the decisions and native transfer outcomes match the expected smoke scenario.
"""
import json

from packages.collector import EvidenceError, account, decode64, loads, require
from packages.verifier import action_body, graph_check, one_cut, outcome_kind, failure_summary

EXPECT = {"pay_1_payee": ("Admitted", "S"), "pay_2_missing": ("Admitted", "F"), "replay_1": ("Denied", "DuplicateRequest"),
          "over_cap": ("Denied", "AboveMaxPerRequest"), "exfiltrate": ("Denied", "RecipientNotAllowed"),
          "budget_exceeded": ("Denied", "BudgetExceeded")}


def inspect(source, run, wasm_sha256):
    out = {"schema": "pursewarden-smoke-inspection/v1", "network": run["network"],
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
    steps, seen = [], set()
    for t in run["transactions"]:
        if "validation_rejected" in t:
            steps.append({"label": t["label"], "result": "rejected at validation"}); continue
        g = source.call("EXPERIMENTAL_tx_status", {"tx_hash": t["tx_hash"], "sender_account_id": t["signer"],
                                                   "wait_until": "FINAL"})
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
