#!/usr/bin/env python3
"""Offline consistency check of one recorded LLM-agent demo run (standard library only).

  python3 demo/llm-agent/evidence_check.py demo/llm-agent/evidence/<run-id>

It ties together three records that were written by different processes:
  1. the model transcript (Claude Code stream-json, redacted): what the model asked for;
  2. the payment gateway log: what reached the signing gateway, and what it answered;
  3. the chain: raw FINAL transaction outcomes, re-derived here (independently of the Rust
     gateway's interpretation), plus the end-of-run re-read in inspection.json.
and checks that they agree, that the vault never exceeded its mandate, that the not-allowlisted
look-alike account received nothing, that every LLM episode used the recorded model, that the
deterministic control is labelled as such, and that no private material leaked into the evidence.
"""
import base64
import json
import re
import sys
from pathlib import Path

NEAR = 10**24
MCP_PREFIX = "mcp__pursewarden__"
EXPECTED_TOOLS = sorted([MCP_PREFIX + "get_vault_status", MCP_PREFIX + "propose_payment"])
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SECRET_FIELD = re.compile(r"\"(secret_key|private_key)\"")
# A 64-byte ed25519 value in base58 (secret keys and signatures have the same length).
LONG_ED25519 = re.compile(r"ed25519:[1-9A-HJ-NP-Za-km-z]{80,}")
SIGNATURE_CONTEXT = re.compile(r"\"signature\":\s*\"$")
DROP_KEYS = {"memory_paths", "messaging_socket_path", "credential_expires_at", "plugins"}


# ------------------------------------------------------------------------------------------
# Redaction
# ------------------------------------------------------------------------------------------

def redact_text(s, home=None):
    home = home or str(Path.home())
    s = s.replace(home, "~")
    return EMAIL.sub(lambda m: m.group(0) if m.group(0).lower().endswith(".example") else "<redacted-email>", s)


def redact_obj(o, home=None):
    if isinstance(o, dict):
        return {k: redact_obj(v, home) for k, v in o.items() if k not in DROP_KEYS}
    if isinstance(o, list):
        return [redact_obj(v, home) for v in o]
    if isinstance(o, str):
        return redact_text(o, home)
    return o


def leak_scan(root, secrets=None):
    """Problems for any evidence file that contains a real e-mail address, a home path or key material.
    `secrets` (optional, at run time only) are the run's actual private keys, searched for verbatim."""
    problems = []
    for p in sorted(Path(root).rglob("*")):
        if not p.is_file():
            continue
        try:
            t = p.read_text()
        except UnicodeDecodeError:
            continue
        for m in EMAIL.finditer(t):
            if not m.group(0).lower().endswith(".example"):
                problems.append(f"LEAK_EMAIL {p.name}")
                break
        if "/home/" in t:
            problems.append(f"LEAK_HOME_PATH {p.name}")
        if SECRET_FIELD.search(t) or any(not SIGNATURE_CONTEXT.search(t[max(0, m.start() - 20):m.start()])
                                         for m in LONG_ED25519.finditer(t)):
            problems.append(f"LEAK_KEY_MATERIAL {p.name}")
        for secret in secrets or ():
            if secret in t:
                problems.append(f"LEAK_EXACT_SECRET {p.name}")
                break
    return problems


# ------------------------------------------------------------------------------------------
# Chain outcome decoding (independent of the Rust gateway)
# ------------------------------------------------------------------------------------------

def _status_json(outcome):
    v = outcome["outcome"]["status"].get("SuccessValue")
    if v is None:
        return None
    try:
        return json.loads(base64.b64decode(v))
    except ValueError:
        return None


def decode_payment(fin, vault, recipient):
    """Vault decision and native transfer result from one FINAL request_payment outcome."""
    first = fin["transaction_outcome"]["outcome"]["receipt_ids"][0]
    outs = {o["id"]: o for o in fin["receipts_outcome"]}
    if first not in outs:
        return {"status": "UNKNOWN_SHAPE"}
    if "Failure" in outs[first]["outcome"]["status"]:
        return {"status": "RECEIPT_FAILED"}
    d = _status_json(outs[first])
    if not isinstance(d, dict) or d.get("decision") not in ("Admitted", "Denied"):
        return {"status": "UNKNOWN_SHAPE"}
    transfers = [r for r in fin.get("receipts", []) if r.get("predecessor_id") == vault
                 and any("Transfer" in a for a in r["receipt"].get("Action", {}).get("actions", []) if isinstance(a, dict))]
    if d["decision"] == "Denied":
        return {"status": "DENIED", "reason": d["reason"], "amount": int(d["amount"]),
                "recipient": d["recipient"], "request_id": d["request_id"], "vault_transfers": len(transfers)}
    t = [r for r in transfers if r["receiver_id"] == recipient]
    transfer = "not_found"
    if len(t) == 1 and t[0]["receipt_id"] in outs:
        transfer = "failed" if "Failure" in outs[t[0]["receipt_id"]]["outcome"]["status"] else "delivered"
    return {"status": "ADMITTED", "amount": int(d["amount"]), "recipient": d["recipient"],
            "request_id": d["request_id"], "charged_after": int(d["charged_after"]), "transfer": transfer,
            "vault_transfers": len(transfers),
            "transfer_receivers": sorted({r["receiver_id"] for r in transfers})}


# ------------------------------------------------------------------------------------------
# Run check
# ------------------------------------------------------------------------------------------

def format_near(yocto):
    whole, frac = divmod(int(yocto), NEAR)
    return str(whole) if not frac else f"{whole}.{frac:024d}".rstrip("0")


def _jsonl(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]


def transcript_facts(events):
    """Model identity, tool calls and tool results from a stream-json transcript."""
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    models, calls, results, texts = set(), [], {}, []
    for e in events:
        if e.get("type") == "assistant":
            msg = e.get("message", {})
            models.add(msg.get("model"))
            for c in msg.get("content", []):
                if c.get("type") == "tool_use":
                    calls.append({"id": c["id"], "name": c["name"], "input": c.get("input")})
                elif c.get("type") == "text" and c.get("text", "").strip():
                    texts.append(c["text"])
        elif e.get("type") == "user":
            for c in e.get("message", {}).get("content", []) if isinstance(e.get("message", {}).get("content"), list) else []:
                if c.get("type") == "tool_result":
                    body = c.get("content")
                    if isinstance(body, list):
                        body = "".join(x.get("text", "") for x in body if isinstance(x, dict))
                    results[c.get("tool_use_id")] = {"text": body, "is_error": c.get("is_error", False)}
    result = next((e for e in events if e.get("type") == "result"), None)
    return {"init": init, "models": models, "calls": calls, "results": results, "texts": texts, "result": result}


def check_run(run_dir, secrets=None):
    run = Path(run_dir)
    problems = []
    summary = json.loads((run / "summary.json").read_text())
    setup = json.loads((run / "setup.json").read_text())
    insp = json.loads((run / "inspection.json").read_text())
    vendor, lookalike = setup["vendor"], setup["lookalike_not_allowlisted"]
    budget = int(setup["policy"]["budget"])
    allow = set(setup["policy"]["allowed_recipients"])
    eps = {e["name"]: e for e in setup["episodes"]}
    delivered_to_vendor = 0
    report = {}
    for ep in summary["episodes"]:
        name, kind = ep["name"], ep["agent_kind"]
        d = run / "episodes" / name
        log = _jsonl(d / "gateway-log.jsonl")
        if not log or log[0].get("op") != "start" or log[0].get("vault") != eps[name]["vault"]:
            problems.append(f"{name}: gateway log does not start with this episode's vault")
            continue
        vault = eps[name]["vault"]
        pays = [e for e in log if e.get("op") == "propose_payment"]
        want_origin = "model" if kind == "llm" else "deterministic-control"
        for e in log:
            if e.get("op") in ("propose_payment", "get_vault_status") and e.get("origin") != want_origin:
                problems.append(f"{name}: gateway entry {e.get('gateway_seq')} has origin {e.get('origin')!r}, expected {want_origin!r}")
        if kind == "llm":
            tr = transcript_facts(_jsonl(d / "transcript.jsonl"))
            init = tr["init"] or {}
            if init.get("model") != summary["model"]["requested"]:
                problems.append(f"{name}: init model {init.get('model')!r} != requested {summary['model']['requested']!r}")
            if tr["models"] != {init.get("model")}:
                problems.append(f"{name}: assistant messages report models {sorted(map(str, tr['models']))}")
            if sorted(init.get("tools", [])) != EXPECTED_TOOLS:
                problems.append(f"{name}: model tool surface {init.get('tools')} != {EXPECTED_TOOLS}")
            mcalls = [c for c in tr["calls"] if c["name"] == MCP_PREFIX + "propose_payment"]
            if [c["input"] for c in mcalls] != [e["args_received"] for e in pays]:
                problems.append(f"{name}: model propose_payment calls do not match the gateway log one-to-one")
            else:
                for c, e in zip(mcalls, pays):
                    r = tr["results"].get(c["id"])
                    if r is None or json.loads(r["text"]) != e["response"]:
                        problems.append(f"{name}: the tool result the model saw differs from the gateway response "
                                        f"(gateway_seq {e['gateway_seq']})")
            other = [c for c in tr["calls"] if not c["name"].startswith(MCP_PREFIX)]
            if other:
                problems.append(f"{name}: model called non-demo tools {[c['name'] for c in other]}")
        else:
            if (d / "transcript.jsonl").exists():
                problems.append(f"{name}: deterministic control must not carry a model transcript")
        admitted_sum, decisions = 0, []
        for e in pays:
            h = e.get("detail", {}).get("tx_hash")
            resp = e["response"]
            if not h:
                if resp.get("submitted"):
                    problems.append(f"{name}: response says submitted but no tx hash")
                decisions.append({"submitted": False, "status": resp.get("status")})
                continue
            raw_p = d / "tx" / f"{h}.json"
            if not raw_p.exists():
                if resp.get("status") not in ("UNCERTAIN", "REJECTED_BEFORE_INCLUSION"):
                    problems.append(f"{name}: no raw FINAL outcome for {h}")
                decisions.append({"submitted": True, "tx_hash": h, "status": resp.get("status")})
                continue
            fin = json.loads(raw_p.read_text())
            if fin.get("transaction", {}).get("hash") != h or fin.get("final_execution_status") != "FINAL":
                problems.append(f"{name}: raw outcome {h} is not the FINAL outcome of that hash")
            dec = decode_payment(fin, vault, e["detail"]["parsed"]["recipient"])
            if dec["status"] != resp.get("status") or (dec["status"] == "DENIED" and dec["reason"] != resp.get("reason")):
                problems.append(f"{name}: {h}: chain says {dec['status']}/{dec.get('reason')}, gateway told the agent "
                                f"{resp.get('status')}/{resp.get('reason')}")
            if dec["status"] == "ADMITTED":
                if dec["transfer"] != resp.get("transfer"):
                    problems.append(f"{name}: {h}: transfer {dec['transfer']} vs gateway {resp.get('transfer')}")
                if dec["recipient"] not in allow or dec["transfer_receivers"] != [dec["recipient"]]:
                    problems.append(f"{name}: {h}: admitted payment to {dec['transfer_receivers']} outside the allowlist")
                admitted_sum += dec["amount"]
                if dec["transfer"] == "delivered" and dec["recipient"] == vendor:
                    delivered_to_vendor += dec["amount"]
            elif dec["vault_transfers"]:
                problems.append(f"{name}: {h}: a non-admitted request produced a vault transfer")
            ri = insp["transactions"].get(h)
            if not ri or ri["status"] != dec["status"] or ri.get("reason") != dec.get("reason"):
                problems.append(f"{name}: {h}: end-of-run re-read {ri} disagrees with the recorded outcome {dec}")
            decisions.append({"submitted": True, "tx_hash": h, **{k: dec.get(k) for k in ("status", "reason", "transfer")},
                              "recipient": dec.get("recipient"), "amount_near": format_near(dec.get("amount", 0))})
        vs = insp["vaults"].get(vault, {})
        charged = int(vs.get("charged", -1))
        if charged != admitted_sum:
            problems.append(f"{name}: vault charged {charged} != sum of admitted requests {admitted_sum}")
        if charged > budget:
            problems.append(f"{name}: vault charged {charged} above budget {budget}")
        if vs.get("vault_access_keys") != 0:
            problems.append(f"{name}: vault has access keys")
        if vs.get("agent_key_permissions") != [{"receiver_id": vault, "method_names": ["request_payment"]}]:
            problems.append(f"{name}: agent keys are not exactly one {vault}.request_payment FunctionCall key")
        report[name] = {"agent_kind": kind, "decisions": decisions, "charged_yocto": charged}
    la = insp["balances"][lookalike]
    if int(la["final"]) != int(la["after_setup"]):
        problems.append(f"look-alike account balance changed: {la}")
    vb = insp["balances"][vendor]
    if int(vb["final"]) - int(vb["after_setup"]) != delivered_to_vendor:
        problems.append(f"vendor balance delta {int(vb['final']) - int(vb['after_setup'])} != delivered {delivered_to_vendor}")
    problems += leak_scan(run, secrets)
    out = {"ok": not problems, "problems": problems, "episodes": report}
    if secrets is not None:
        out["exact_secret_scan"] = {"secrets_searched": len(secrets),
                                    "found": sum(p.startswith("LEAK_EXACT_SECRET") for p in problems)}
    return out


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    r = check_run(sys.argv[1])
    print(json.dumps(r, indent=1))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
