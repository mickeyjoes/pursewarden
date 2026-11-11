#!/usr/bin/env python3
"""G2 concurrency comparison on ONE fresh reviewer-owned local sandbox chain.

  python3 scripts/g2-independent/run_g2.py RUN_ID [--rpc-port 3290] [--net-port 24827]

Targets (all local sandbox; the vulnerable one is a project-owned teaching fixture):
  protected   protected vault, B = 5 NEAR, M = 2, K = 9
  generous    protected vault, B = 100 NEAR, M = 2, K = 9  (control: the harness does admit)
  vulnerable  settled-only fixture, B = 5 NEAR, M = 2       (control: genuine race overspend)
Workload (untrusted, bubblewrap sandbox, agent FC keys only): per target one 1 NEAR payment, then
eight 2 NEAR requests pre-signed with eight different keys and submitted concurrently.
Reviewer: freezes the protected vaults, selects Q, then independently acquires each protected
vault with the G1 verifier (plus the native-pending witness) and audits the fixture's real
outflows. No runner-supplied hash seeds any acquisition. Reuses the hardened G1 tooling
(fresh read-only socket dirs, isolation probe first, safe_import of runner output).
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts/g1-independent"))
_spec = importlib.util.spec_from_file_location("run_g1", REPO / "scripts/g1-independent/run_g1.py")
g1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g1)
from packages.collector import digest  # noqa: E402
from packages.verifier.forge import export_rpc_records  # noqa: E402
from safe_import import ImportRejected, import_json, validate_isolation  # noqa: E402

G2_ACTOR = REPO / "target/debug/g2_actor"
FIXTURE = REPO / "artifacts/fixtures/vulnerable_settled_only.wasm"
NEAR = 10**24


def validate_runner_log_g2(obj):
    if not (isinstance(obj, dict) and obj.get("schema") == "g2-independent/runner-log/v1"
            and isinstance(obj.get("scenarios"), list) and len(obj["scenarios"]) == 3):
        raise ImportRejected("g2 runner log schema")
    for s in obj["scenarios"]:
        if not (isinstance(s, dict) and isinstance(s.get("burst"), list) and len(s["burst"]) == 8
                and all(isinstance(b.get("tx_hash"), str) for b in s["burst"])):
            raise ImportRejected("g2 scenario schema")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--rpc-port", type=int, default=3290)
    ap.add_argument("--net-port", type=int, default=24827)
    a = ap.parse_args()
    g1.ACTOR = G2_ACTOR  # the sandbox binds this binary at /runner-bin/g1_actor
    t0 = time.time()
    base = g1.TOOLS / "g2-independent" / a.run_id
    g1.require_short_socket_path(base)
    rev, runner = base / "reviewer", base / "runner"
    node_home = rev / "node"
    pub = REPO / "evidence" / "g2-independent" / a.run_id
    assert not base.exists() and not pub.exists(), "fresh run directories required"
    for d in (rev, runner, runner / "out"):  # created by the reviewer before any sandbox runs
        d.mkdir(parents=True, mode=0o700)
    url = f"http://127.0.0.1:{a.rpc_port}"
    summary = {"schema": "g2-independent/run/v1", "run_id": a.run_id, "network": "SANDBOX (local)",
               "repo_commit": subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                                             text=True).stdout.strip(),
               "repo_dirty": bool(subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "packages",
                                                  "scripts", "tests", "contracts", "artifacts", "fixtures"],
                                                 capture_output=True, text=True).stdout.strip()),
               "wasm_sha256": g1.sha256_file(g1.WASM), "fixture_wasm_sha256": g1.sha256_file(FIXTURE),
               "actor_sha256": g1.sha256_file(G2_ACTOR), "node_binary_sha256": g1.sha256_file(g1.NODE_BIN)}
    node_pid = None
    try:
        env = dict(os.environ, NODE_HOME=str(node_home), NODE_EVIDENCE_DIR=str(pub / "node"),
                   RPC_ADDR=f"127.0.0.1:{a.rpc_port}", NET_ADDR=f"127.0.0.1:{a.net_port}")
        g1.run([REPO / "scripts/sandbox-setup/start-node.sh", a.run_id], env=env)
        node_pid = int((node_home / "node.pid").read_text())
        status = g1.rpc(url, "status", [])
        genesis = g1.rpc(url, "EXPERIMENTAL_genesis_config", {})
        gblock = g1.rpc(url, "block", {"block_id": genesis["genesis_height"]})
        summary["node"] = {"chain_id": status["chain_id"], "genesis_block_hash": gblock["header"]["hash"],
                           "version": status["version"], "protocol_version": status["protocol_version"]}

        g1.run([G2_ACTOR, "reviewer-prepare", "--rpc", url, "--node-home", node_home, "--reviewer-dir", rev,
                "--out", pub / "reviewer/prepare.json"])
        prep = json.loads((pub / "reviewer/prepare.json").read_text())
        h0 = g1.wait_final_height(url, max(g1.outcome_heights(url, prep["transactions"])) + 2)["header"]
        g1.log(f"H0 {h0['height']} {h0['hash']}")
        g1.run([G2_ACTOR, "reviewer-construct", "--rpc", url, "--reviewer-dir", rev, "--runner-dir", runner,
                "--wasm", g1.WASM, "--fixture-wasm", FIXTURE, "--out", pub / "reviewer/construct.json"])
        cons = json.loads((pub / "reviewer/construct.json").read_text())
        targets = {t["name"]: t for t in cons["targets"]}
        g1.write(runner / "policy-hashes.json", {n: t["policy_hash"] for n, t in targets.items() if t["protected"]})

        # Isolation probe first (own invocation), imported before any untrusted workload runs.
        forbidden = [str(node_home), str(rev), str(Path.home()), str(rev / "owner.key.json"),
                     str(node_home / "validator_key.json"), str(REPO), str(base)]
        sock, probe_out = g1.fresh_dir(base, "sock-probe"), g1.fresh_dir(base, "probe-out")
        proxy = g1.Proxy(sock / "rpc.sock", url, "submit", pub / "runner/proxy-probe.jsonl")
        try:
            g1.sandbox(g1.BRIDGE + f"python3 -I /runner-scripts/isolation_probe.py /probe/isolation.json {a.rpc_port} "
                       + " ".join(forbidden) + " || echo 'isolation probe reported FAIL'",
                       ro=[(sock, "/sock"), (runner, "/runner")], rw=[(probe_out, "/probe")])
        finally:
            proxy.close()
        iso_bytes, iso = import_json(probe_out, "isolation.json", 1 << 20, validate_isolation)
        (pub / "runner/isolation.json").write_bytes(iso_bytes)
        if iso["isolation_checks"] != "PASS":
            raise RuntimeError("isolation probe FAIL: not starting the untrusted workload")
        summary["isolation"] = {"checks": iso["isolation_checks"], "socket_dir_writable": iso.get("socket_dir_writable"),
                                "direct_node_rpc": iso["direct_node_rpc_127.0.0.1"]}

        # Untrusted concurrent workload.
        sock = g1.fresh_dir(base, "sock-submit")
        proxy = g1.Proxy(sock / "rpc.sock", url, "submit", pub / "runner/proxy-submit.jsonl")
        try:
            g1.sandbox(g1.BRIDGE + "/runner-bin/g1_actor runner-burst --rpc http://127.0.0.1:3030 --runner-dir /runner "
                       "--out /runner/out/runner-log.json", ro=[(sock, "/sock")], rw=[(runner, "/runner")])
        finally:
            proxy.close()
        log_bytes, runner_log = import_json(runner, "out/runner-log.json", 32 << 20, validate_runner_log_g2)
        (pub / "runner/runner-log.json").write_bytes(log_bytes)

        # Freeze protected vaults, settle, select Q.
        g1.run([G2_ACTOR, "reviewer-freeze", "--rpc", url, "--reviewer-dir", rev, "--out", pub / "reviewer/freeze.json"])
        frz = json.loads((pub / "reviewer/freeze.json").read_text())
        q = g1.wait_final_height(url, max(g1.outcome_heights(url, frz["transactions"])) + 20)["header"]
        g1.log(f"Q {q['height']} {q['hash']}")
        protocol = g1.rpc(url, "EXPERIMENTAL_protocol_config", {"block_id": h0["hash"]})
        ident = {"network": "sandbox", "chain_id": status["chain_id"], "genesis_block_hash": gblock["header"]["hash"],
                 "genesis_rpc_sha256": digest(genesis), "node_version": status["version"],
                 "protocol_config_sha256": digest(protocol), "h0_hash": h0["hash"], "h0_height": h0["height"],
                 "q_hash": q["hash"], "q_height": q["height"], "max_blocks": 10000, "max_roots": 1000,
                 "shard_ids": protocol["shard_layout"]["V2"]["shard_ids"]}
        expected = {
            "protected": {"ledger": {"C": str(5 * NEAR), "S": str(5 * NEAR), "F": "0", "U": "0", "headroom": "0",
                                     "accepted_count": 3},
                          "principal_refunds": 0, "denial_reasons": ["BudgetExceeded"] * 6, "failed_call_classes": []},
            "generous": {"ledger": {"C": str(17 * NEAR), "S": str(17 * NEAR), "F": "0", "U": "0",
                                    "headroom": str(83 * NEAR), "accepted_count": 9},
                         "principal_refunds": 0, "denial_reasons": [], "failed_call_classes": []},
        }
        results = {}
        for name in ("protected", "generous"):
            t = targets[name]
            d = dict(ident, schema="near-g1-reviewer/v1", vault=t["vault"], owner=cons["owner"], agent=t["agent"],
                     recipients=t["recipients"], policy_hash=t["policy_hash"], budget=t["budget"],
                     max_per_request=t["max_per_request"], expires_at_ns=t["expires_at_ns"],
                     max_accepted_requests=t["max_accepted_requests"], asset="NativeNear", agent_key_count=9,
                     wasm_sha256=g1.sha256_file(g1.WASM), node_binary_sha256=g1.sha256_file(g1.NODE_BIN),
                     node_config_sha256=g1.sha256_file(node_home / "config.json"),
                     genesis_file_sha256=g1.sha256_file(node_home / "genesis.json"), expected=expected[name])
            g1.write(pub / f"{name}/reviewer-descriptor.json", d)
            out = base / f"independent-{name}"
            g1.verifier("--network", "sandbox", "--rpc", url, "--descriptor", pub / f"{name}/reviewer-descriptor.json",
                        "--wasm", g1.WASM, "--node-binary", g1.NODE_BIN, "--node-config", node_home / "config.json",
                        "--genesis-file", node_home / "genesis.json", "--out", out)
            r = json.loads((out / "result.json").read_text())
            (pub / name / "result.json").write_text(json.dumps(r, indent=2) + "\n")
            export_rpc_records(out / "rpc", pub / name / "rpc.jsonl.gz")
            rec = r.get("recovery") or {}
            results[name] = {"verdicts": r["verdicts"], "issues": r["issues"], "ledger": rec.get("ledger"),
                             "admitted": [p["request_id"] for p in rec.get("payments", [])],
                             "denied": [(x["request_id"], x["reason"]) for x in rec.get("denials", [])],
                             "pending_witness": rec.get("pending_witness")}
            g1.log(f"{name}: verdicts {r['verdicts']} ledger {rec.get('ledger')}")
        t = targets["vulnerable"]
        cd = dict(ident, schema="near-g2-control/v1", vault=t["vault"], budget=t["budget"], wasm_sha256=t["wasm_sha256"])
        g1.write(pub / "vulnerable/control-descriptor.json", cd)
        out = base / "control-vulnerable"
        g1.verifier("control", "--network", "sandbox", "--rpc", url, "--descriptor",
                    pub / "vulnerable/control-descriptor.json", "--out", out)
        cr = json.loads((out / "result.json").read_text())
        (pub / "vulnerable/result.json").write_text(json.dumps(cr, indent=2) + "\n")
        export_rpc_records(out / "rpc", pub / "vulnerable/rpc.jsonl.gz")
        results["vulnerable"] = {k: cr.get(k) for k in ("label", "admissions", "denials", "delivered_principal",
                                                        "overspend", "budget_exceeded_on_chain",
                                                        "admissions_per_block", "stale_settled_seen", "issues")}
        summary["results"] = results
    finally:
        if node_pid:
            try:
                os.kill(node_pid, 15)
            except ProcessLookupError:
                pass
        summary["elapsed_seconds"] = round(time.time() - t0, 1)
        summary["log"] = [line.replace(str(Path.home()), "~") for line in g1.LOG]
        if pub.exists():
            g1.write(pub / "run-summary.json", summary)
            g1.sanitize_home(pub)
    print(json.dumps(summary.get("results"), indent=2, default=str))


if __name__ == "__main__":
    main()
