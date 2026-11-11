#!/usr/bin/env python3
"""Pursewarden LLM-agent demo: a real language model as a purchasing assistant, paying through a
restricted NEAR function-call key into the protected vault, on a fresh LOCAL sandbox.

  cargo build --offline --manifest-path demo/llm-agent/gateway/Cargo.toml
  python3 demo/llm-agent/run_demo.py RUN_ID [--rpc-port 3460] [--net-port 24960]

Prerequisites: everything in README step 5 (pinned nearcore sandbox, Rust 1.93.0) plus a logged-in
Claude Code CLI (`claude`). The model runs through `claude -p` (headless Claude Code) with every
built-in tool disabled and exactly two MCP tools: get_vault_status and propose_payment.

Episodes (fixed before any run; see EPISODES): one legitimate purchase, two scenarios with
injected/tampered invoices (two independent sessions each, each against its own fresh vault) and
one DETERMINISTIC CONTROL (a scripted, not model-driven, compromised agent).

Private material (node home with the validator key, agent keys, raw unredacted transcripts) stays in
~/.local/share/near-agent-vault-lab/llm-demo/RUN_ID/. Redacted evidence goes to
demo/llm-agent/evidence/RUN_ID/.
"""
import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

DEMO = Path(__file__).resolve().parent
REPO = DEMO.parents[1]
sys.path.insert(0, str(DEMO))
import control_agent  # noqa: E402
from evidence_check import check_run, decode_payment, redact_obj, redact_text  # noqa: E402

GATEWAY = DEMO / "gateway/target/debug/pw_llm_gateway"
WASM = REPO / "artifacts/near_agent_vault.wasm"
TOOLS = Path(os.environ.get("NEAR_VAULT_TOOLS", Path.home() / ".local/share/near-agent-vault-lab"))
NODE_BIN = TOOLS / "sandbox-bin/2.13.4/extract/Linux-x86_64/near-sandbox"

# Fixed before the first recorded run. (episode name, scenario id, agent kind)
EPISODES = [
    ("legit-1", "legit-purchase", "llm"),
    ("inject-1", "invoice-injection", "llm"),
    ("inject-2", "invoice-injection", "llm"),
    ("bec-1", "account-change-invoice", "llm"),
    ("bec-2", "account-change-invoice", "llm"),
    ("control-1", "invoice-injection", "control"),
]
MODEL = "claude-opus-5-5"
EFFORT = "high"
MAX_TURNS = 12
MAX_BUDGET_USD = "3"
MAX_ATTEMPTS = 6
EPISODE_TIMEOUT_S = 900
ALLOWED_TOOLS = "mcp__pursewarden__get_vault_status,mcp__pursewarden__propose_payment"


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def rpc(url, method, params, timeout=60):
    body = json.dumps({"jsonrpc": "2.0", "id": "pw", "method": method, "params": params}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        out = json.load(r)
    if "error" in out:
        raise RuntimeError(f"{method}: {out['error']}")
    return out["result"]


def view_fn(url, account, method, block):
    r = rpc(url, "query", {"request_type": "call_function", "account_id": account, "method_name": method,
                           "args_base64": base64.b64encode(b"{}").decode(), "block_id": block})
    return json.loads(bytes(r["result"]))


def render_prompt(sc):
    parts = ["OWNER INSTRUCTION:", sc["owner_instruction"], ""]
    for d in sc["documents"]:
        parts += [f"ATTACHED VENDOR DOCUMENT: {d['name']} ({d['provenance']})", "-----BEGIN DOCUMENT-----",
                  d["text"], "-----END DOCUMENT-----", ""]
    return "\n".join(parts).rstrip() + "\n"


def write_json(p, v):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, indent=1, ensure_ascii=False) + "\n")


def start_gateway(url, pub, priv, name):
    sockdir = Path(tempfile.mkdtemp(prefix="pwllm-"))  # short path (AF_UNIX limit), mode 0700
    sock = sockdir / "gw.sock"
    epdir = pub / "episodes" / name
    epdir.mkdir(parents=True, exist_ok=True)
    err = open(priv / "episodes" / name / "gateway.stderr", "w")
    p = subprocess.Popen([str(GATEWAY), "serve", "--rpc", url, "--setup", str(pub / "setup.json"), "--episode", name,
                          "--agent-key", str(priv / "keys" / f"{name}.agent-key.json"), "--socket", str(sock),
                          "--log", str(epdir / "gateway-log.jsonl"), "--raw-dir", str(epdir / "tx"),
                          "--max-attempts", str(MAX_ATTEMPTS)],
                         stdout=subprocess.PIPE, stderr=err, text=True)
    line = p.stdout.readline()
    if not line.startswith("READY"):
        p.kill()
        raise RuntimeError(f"gateway for {name} did not start; see {priv / 'episodes' / name / 'gateway.stderr'}")
    return p, sock, sockdir


def stop_gateway(p, sock, sockdir):
    try:
        control_agent.ask(str(sock), {"op": "shutdown"}, timeout=30)
    except OSError:
        pass
    try:
        p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill()
    shutil.rmtree(sockdir, ignore_errors=True)


def run_llm(sc, sock, pub_ep, priv_ep, model, effort):
    system = (DEMO / "prompts/system.txt").read_text()
    prompt = render_prompt(sc)
    (pub_ep / "prompt.txt").write_text(prompt)
    mcp = {"mcpServers": {"pursewarden": {"type": "stdio", "command": sys.executable,
                                          "args": ["-I", str(DEMO / "mcp_server.py"), "--socket", str(sock)]}}}
    cfg = priv_ep / "mcp.json"
    write_json(cfg, mcp)
    cwd = priv_ep / "cwd"  # empty working directory: no project files, no CLAUDE.md
    cwd.mkdir()
    cmd = ["claude", "-p", "--model", model, "--effort", effort, "--system-prompt", system,
           "--tools", "", "--mcp-config", str(cfg), "--strict-mcp-config",
           "--allowedTools", ALLOWED_TOOLS, "--permission-prompts", "none",
           "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence",
           "--max-turns", str(MAX_TURNS), "--max-budget-usd", MAX_BUDGET_USD,
           "--output-format", "stream-json", "--verbose"]
    # Minimal environment: no API keys are passed (Claude Code uses its own stored login) and no
    # parent-session variables leak in.
    env = {"HOME": str(Path.home()), "PATH": os.environ["PATH"], "LANG": "C.UTF-8"}
    t0 = time.time()
    raw, err = priv_ep / "transcript.raw.jsonl", priv_ep / "claude.stderr"
    with open(raw, "w") as out, open(err, "w") as e:
        try:
            rc = subprocess.run(cmd, input=prompt, stdout=out, stderr=e, text=True, cwd=cwd, env=env,
                                timeout=EPISODE_TIMEOUT_S).returncode
        except subprocess.TimeoutExpired:
            rc = "TIMEOUT"
    events = []
    for line in raw.read_text().splitlines():
        try:
            events.append(redact_obj(json.loads(line)))
        except ValueError:
            events.append({"type": "unparsed_line", "text": redact_text(line)})
    (pub_ep / "transcript.jsonl").write_text("".join(json.dumps(ev, ensure_ascii=False) + "\n" for ev in events))
    shutil.rmtree(cwd, ignore_errors=True)
    return {"exit": rc, "seconds": round(time.time() - t0, 1),
            "command": [c if c != system else "<prompts/system.txt>" for c in cmd]}


def inspect(url, pub, setup, final_height):
    """Independent end-of-run re-read from the node (does not reuse the gateway's interpretation)."""
    out = {"schema": "pursewarden-llm-demo/inspection/v1", "final_block": final_height,
           "setup_block": setup["setup_final_block"]["height"], "transactions": {}, "vaults": {}, "balances": {}}
    for ep in setup["episodes"]:
        vault, agent = ep["vault"], ep["agent"]
        log = pub / "episodes" / ep["name"] / "gateway-log.jsonl"
        if log.exists():
            for line in log.read_text().splitlines():
                e = json.loads(line)
                h = e.get("detail", {}).get("tx_hash") if e.get("op") == "propose_payment" else None
                if not h or e["response"].get("status") == "REJECTED_BEFORE_INCLUSION":
                    continue
                fin = rpc(url, "EXPERIMENTAL_tx_status", {"tx_hash": h, "sender_account_id": agent, "wait_until": "FINAL"})
                d = decode_payment(fin, vault, e["detail"]["parsed"]["recipient"])
                out["transactions"][h] = {"episode": ep["name"], "status": d["status"], "reason": d.get("reason"),
                                          "transfer": d.get("transfer"),
                                          "included_in_block": next((o["block_hash"] for o in fin["receipts_outcome"]
                                                                     if o["id"] == fin["transaction_outcome"]["outcome"]["receipt_ids"][0]), None)}
        m = view_fn(url, vault, "get_mandate", final_height)
        adm = view_fn(url, vault, "get_admissions", final_height)
        vkeys = rpc(url, "query", {"request_type": "view_access_key_list", "account_id": vault, "block_id": final_height})["keys"]
        akeys = rpc(url, "query", {"request_type": "view_access_key_list", "account_id": agent, "block_id": final_height})["keys"]
        perms = []
        for k in akeys:
            fc = k["access_key"]["permission"]
            perms.append({"receiver_id": fc["FunctionCall"]["receiver_id"], "method_names": fc["FunctionCall"]["method_names"]}
                         if isinstance(fc, dict) and "FunctionCall" in fc else {"full_access": True})
        out["vaults"][vault] = {"episode": ep["name"], "charged": m["charged"], "budget": m["budget"],
                                "max_per_request": m["max_per_request"], "accepted_count": m["accepted_count"],
                                "allowed_recipients": m["allowed_recipients"], "policy_hash": m["policy_hash"],
                                "frozen": m["frozen"], "expired": m["expired"], "admissions": adm,
                                "vault_access_keys": len(vkeys), "agent_key_permissions": perms}
    for acct in (setup["vendor"], setup["lookalike_not_allowlisted"]):
        bal = {}
        for label, h in (("after_setup", setup["setup_final_block"]["height"]), ("final", final_height)):
            bal[label] = rpc(url, "query", {"request_type": "view_account", "account_id": acct, "block_id": h})["amount"]
        out["balances"][acct] = bal
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--rpc-port", type=int, default=3460)
    ap.add_argument("--net-port", type=int, default=24960)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--effort", default=EFFORT)
    ap.add_argument("--only", default="", help="development only: comma-separated subset of episode names")
    a = ap.parse_args()
    episodes = [e for e in EPISODES if not a.only or e[0] in a.only.split(",")]
    assert episodes, "no episodes selected"
    priv = TOOLS / "llm-demo" / a.run_id
    pub = DEMO / "evidence" / a.run_id
    assert not priv.exists() and not pub.exists(), "fresh run id required"
    assert GATEWAY.exists(), f"build the gateway first: cargo build --offline --manifest-path {DEMO}/gateway/Cargo.toml"
    for d in [priv / "keys"] + [priv / "episodes" / n for n, _, _ in episodes]:
        d.mkdir(parents=True, mode=0o700)
    os.chmod(priv, 0o700)
    pub.mkdir(parents=True)
    url = f"http://127.0.0.1:{a.rpc_port}"
    scen = {p.stem: json.loads(p.read_text()) for p in sorted((DEMO / "scenarios").glob("*.json"))}
    git = lambda *x: subprocess.run(["git", "-C", str(REPO), *x], capture_output=True, text=True).stdout.strip()
    summary = {
        "schema": "pursewarden-llm-demo/run/v1", "run_id": a.run_id, "network": "SANDBOX (local)",
        "started_unix": int(time.time()), "repo_commit": git("rev-parse", "HEAD"),
        "repo_dirty": bool(git("status", "--porcelain", "--", "demo/llm-agent", "contracts", "artifacts", "tests")),
        "model": {"requested": a.model, "effort": a.effort, "interface": "Claude Code CLI headless (claude -p), "
                  "stream-json; authenticated with the operator's own Claude Code login (no API key passed)",
                  "claude_code_version": subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()},
        "bounds": {"max_turns": MAX_TURNS, "max_budget_usd_per_episode": MAX_BUDGET_USD,
                   "max_payment_attempts_per_episode": MAX_ATTEMPTS, "episode_timeout_s": EPISODE_TIMEOUT_S},
        "hashes": {"vault_wasm": sha256_file(WASM), "gateway_bin": sha256_file(GATEWAY),
                   "node_bin": sha256_file(NODE_BIN), "system_prompt": sha256_file(DEMO / "prompts/system.txt"),
                   "mcp_server": sha256_file(DEMO / "mcp_server.py"), "control_agent": sha256_file(DEMO / "control_agent.py"),
                   "scenarios": {k: sha256_file(DEMO / "scenarios" / f"{k}.json") for k in scen}},
        "episode_plan": [list(e) for e in EPISODES],
        "episodes_selected": [e[0] for e in episodes],
        "episodes": [],
    }
    node_pid = None
    try:
        env = dict(os.environ, NODE_HOME=str(priv / "node"), NODE_EVIDENCE_DIR=str(pub / "node"),
                   RPC_ADDR=f"127.0.0.1:{a.rpc_port}", NET_ADDR=f"127.0.0.1:{a.net_port}")
        subprocess.run([str(REPO / "scripts/sandbox-setup/start-node.sh"), a.run_id], env=env, check=True)
        node_pid = int((priv / "node/node.pid").read_text())
        subprocess.run([str(GATEWAY), "setup", "--rpc", url, "--owner-key", str(priv / "node/validator_key.json"),
                        "--wasm", str(WASM), "--episodes", ",".join(n for n, _, _ in episodes),
                        "--public-out", str(pub / "setup.json"), "--private-dir", str(priv / "keys")], check=True)
        setup = json.loads((pub / "setup.json").read_text())
        for name, sid, kind in episodes:
            print(f"[demo] episode {name} ({sid}, {kind})", flush=True)
            pub_ep, priv_ep = pub / "episodes" / name, priv / "episodes" / name
            gw, sock, sockdir = start_gateway(url, pub, priv, name)
            rec = {"name": name, "scenario": sid, "agent_kind": kind,
                   "label": "LLM (genuine model run)" if kind == "llm" else "DETERMINISTIC CONTROL (scripted, not an LLM)"}
            try:
                if kind == "llm":
                    rec["run"] = run_llm(scen[sid], sock, pub_ep, priv_ep, a.model, a.effort)
                else:
                    write_json(pub_ep / "control-log.json", control_agent.run(str(sock)))
            finally:
                stop_gateway(gw, sock, sockdir)
            summary["episodes"].append(rec)
        fb = rpc(url, "block", {"finality": "final"})
        insp = inspect(url, pub, setup, fb["header"]["height"])
        write_json(pub / "inspection.json", insp)
        st = rpc(url, "status", [])
        summary["node"] = {"chain_id": st["chain_id"], "genesis_hash": st["genesis_hash"],
                           "protocol_version": st["protocol_version"], "version": st["version"]}
    finally:
        if node_pid:
            try:
                os.kill(node_pid, 15)
            except ProcessLookupError:
                pass
    summary["finished_unix"] = int(time.time())
    for ep in summary["episodes"]:
        ep.update(episode_digest(pub / "episodes" / ep["name"], ep["agent_kind"]))
    write_json(pub / "summary.json", summary)
    for p in pub.rglob("*"):  # final redaction pass over every text file (paths written by the node scripts)
        if p.is_file() and p.suffix in (".json", ".jsonl", ".txt", ".log", ".sha256", ".md"):
            t = p.read_text()
            r = redact_text(t)
            if r != t:
                p.write_text(r)
    secrets = []
    for kf in list((priv / "keys").glob("*.json")) + [priv / "node/validator_key.json", priv / "node/node_key.json"]:
        if kf.exists():
            k = json.loads(kf.read_text())
            secrets += [k[f] for f in ("secret_key", "private_key") if isinstance(k.get(f), str)]
    result = check_run(pub, secrets)
    write_json(pub / "check.json", result)
    (pub / "SHA256SUMS").write_text("".join(f"{sha256_file(p)}  {p.relative_to(pub)}\n" for p in sorted(pub.rglob("*"))
                                            if p.is_file() and p.name != "SHA256SUMS"))
    print(json.dumps({"check_ok": result["ok"], "problems": result["problems"],
                      "episodes": {k: v["decisions"] for k, v in result["episodes"].items()}}, indent=1))
    return 0 if result["ok"] else 1


def episode_digest(d, kind):
    """What actually happened in one episode, read back from its own evidence files."""
    log = [json.loads(l) for l in (d / "gateway-log.jsonl").read_text().splitlines() if l.strip()]
    pays = [{"origin": e["origin"], "args": e["args_received"], "status": e["response"].get("status"),
             "reason": e["response"].get("reason"), "transfer": e["response"].get("transfer"),
             "tx_hash": e["detail"].get("tx_hash")} for e in log if e.get("op") == "propose_payment"]
    out = {"payment_requests": pays, "status_reads": sum(1 for e in log if e.get("op") == "get_vault_status")}
    if kind == "llm":
        evs = [json.loads(l) for l in (d / "transcript.jsonl").read_text().splitlines() if l.strip()]
        init = next((e for e in evs if e.get("type") == "system" and e.get("subtype") == "init"), {})
        res = next((e for e in evs if e.get("type") == "result"), {})
        texts = [c["text"] for e in evs if e.get("type") == "assistant" for c in e["message"].get("content", [])
                 if c.get("type") == "text" and c.get("text", "").strip()]
        out["model_reported"] = sorted({e["message"].get("model") for e in evs if e.get("type") == "assistant"})
        out["init_model"] = init.get("model")
        out["tools_offered"] = init.get("tools")
        out["mcp_servers"] = init.get("mcp_servers")
        out["final_text"] = texts[-1] if texts else None
        out["result"] = {k: res.get(k) for k in ("subtype", "is_error", "num_turns", "total_cost_usd", "stop_reason",
                                                 "terminal_reason")}
    return out


if __name__ == "__main__":
    sys.exit(main())
