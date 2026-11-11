#!/usr/bin/env python3
"""Independent G1 run on a FRESH reviewer-owned sandbox node.

  python3 scripts/g1-independent/run_g1.py RUN_ID [--rpc-port 3230] [--net-port 24767]
                                            [--retention-blocks 2000]

Roles:
  reviewer  this process: owns the node home (validator key), the owner key, H0/Q selection,
            the filter proxy and the independent collector, which reads the node directly.
  runner    an untrusted agent workload inside bubblewrap (all namespaces unshared, no network
            route to the node, only the runner directory + a filtered RPC socket visible). It
            holds eight agent function-call keys and nothing else.

Phases: fresh node -> reviewer setup -> H0 -> keyless construction -> isolation probe ->
runner attack -> ingress closed -> owner freeze -> settle -> Q -> independent acquisition
(no runner input) -> runner presentation (through the read-only filter) -> forged presentation
with the entire 2 NEAR failed-payment root removed -> offline comparison -> mutation suite over
the genuine recorded responses -> >= 2000 produced blocks (no fast-forward) -> retention re-read.

Private material (node home, owner key, agent keys) stays under
~/.local/share/near-agent-vault-lab/g1-independent/RUN_ID/. Public evidence is written to
evidence/g1-independent/RUN_ID/.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from packages.collector import canonical, digest  # noqa: E402
from packages.verifier.forge import export_rpc_records, omit_request_root  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_import import (import_json, validate_capture, validate_isolation,  # noqa: E402
                         validate_runner_log)

TOOLS = Path(os.environ.get("NEAR_VAULT_TOOLS", Path.home() / ".local/share/near-agent-vault-lab"))
NODE_BIN = TOOLS / "sandbox-bin/2.13.4/extract/Linux-x86_64/near-sandbox"
ACTOR = REPO / "target/debug/g1_actor"
WASM = REPO / "artifacts/near_agent_vault.wasm"
SCRIPTS = REPO / "scripts/g1-independent"
NEAR = 10**24
LOG = []


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    LOG.append(line)
    print(line, flush=True)


def rpc(url, method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": "r", "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=30) as r:
        resp = json.loads(r.read())
    if "error" in resp:
        raise RuntimeError(f"{method}: {resp['error']}")
    return resp["result"]


def final_block(url):
    return rpc(url, "block", {"finality": "final"})


def wait_final_height(url, h):
    while True:
        b = final_block(url)
        if b["header"]["height"] >= h:
            return b
        time.sleep(0.25)


def outcome_heights(url, tx_results):
    hs = []
    for t in tx_results:
        fin = t.get("final")
        if not fin:
            continue
        for o in [fin["transaction_outcome"]] + fin["receipts_outcome"]:
            hs.append(rpc(url, "block", {"block_id": o["block_hash"]})["header"]["height"])
    return hs


def run(cmd, **kw):
    log("$ " + " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2) + "\n")


BRIDGE = "python3 -I /runner-scripts/sandbox_bridge.py /sock/rpc.sock 3030 >/tmp/bridge.log 2>&1 & sleep 0.5; "


def sandbox(script, ro=(), rw=()):
    """Run `script` (sh) in the runner sandbox: all namespaces unshared, no network route,
    only the listed (host, guest) binds exist inside. The proxy socket directory is always
    bound READ-ONLY; the only runner-writable host directory is the one passed in `rw`, and the
    reviewer reads it afterwards solely through safe_import (no-follow, descriptor-relative)."""
    cmd = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
           "--setenv", "HOME", "/tmp", "--setenv", "PATH", "/usr/bin:/bin",
           "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
           "--symlink", "usr/bin", "/bin", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
           "--ro-bind", str(ACTOR), "/runner-bin/g1_actor",
           "--ro-bind", str(SCRIPTS), "/runner-scripts",
           "--ro-bind", str(REPO / "packages"), "/runner-pkg/packages"]
    for host, guest in ro:
        cmd += ["--ro-bind", str(host), guest]
    for host, guest in rw:
        cmd += ["--bind", str(host), guest]
    cmd += ["--chdir", "/tmp", "/bin/sh", "-ec", script]
    return run(cmd)


SOCKET_PATH_MAX = 107  # Linux sun_path is 108 bytes including the terminating NUL


def require_short_socket_path(base):
    """Fail before any work if the proxy socket path would be too long for AF_UNIX, instead of
    dying mid-run with "AF_UNIX path too long" (final audit PW-07). Nothing else changes."""
    longest = base / "sock-submit" / "rpc.sock"
    n = len(os.fsencode(str(longest)))
    if n > SOCKET_PATH_MAX:
        sys.exit(f"socket path would be {n} bytes, over the Linux limit of {SOCKET_PATH_MAX}: {longest}\n"
                 "Use a shorter run id, or set NEAR_VAULT_TOOLS to a shorter directory (see README steps 5-6).")


def fresh_dir(base, name):
    d = base / name
    d.mkdir(mode=0o700)  # never reused: a runner can only ever have touched dirs it was given
    return d


class Proxy:
    def __init__(self, sock, upstream, mode, logfile):
        self.sock = Path(sock)
        Path(logfile).parent.mkdir(parents=True, exist_ok=True)
        self.p = subprocess.Popen(["/usr/bin/python3", "-I", str(SCRIPTS / "rpc_filter_proxy.py"),
                                   "--socket", str(sock), "--upstream", upstream,
                                   "--mode", mode, "--log", str(logfile)])
        Path(logfile).parent.mkdir(parents=True, exist_ok=True)
        for _ in range(100):
            if self.sock.exists() or self.p.poll() is not None:
                break
            time.sleep(0.05)
        if self.p.poll() is not None or not self.sock.exists():
            raise RuntimeError(f"filter proxy failed to start (exit {self.p.poll()})")
        log(f"filter proxy {mode} pid {self.p.pid}")

    def close(self):
        self.p.terminate()
        self.p.wait(timeout=10)
        log("filter proxy closed (runner ingress closed)")


def verifier(*args, cwd=REPO, check=False):
    cmd = ["/usr/bin/python3", "-E", "-s", "-m", "packages.verifier", *map(str, args)]
    log("$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=cwd, check=check)


def sanitize_home(pub):
    """Public evidence must not carry the operator's home path."""
    home = str(Path.home())
    for f in pub.rglob("*"):
        if f.is_file() and f.suffix in {".json", ".jsonl", ".log", ".txt", ".sha256"}:
            text = f.read_text(errors="strict")
            if home in text:
                f.write_text(text.replace(home, "~"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--rpc-port", type=int, default=3230)
    ap.add_argument("--net-port", type=int, default=24767)
    ap.add_argument("--retention-blocks", type=int, default=2000)
    a = ap.parse_args()
    t0 = time.time()
    base = TOOLS / "g1-independent" / a.run_id
    require_short_socket_path(base)
    rev, runner = base / "reviewer", base / "runner"
    node_home = rev / "node"
    pub = REPO / "evidence" / "g1-independent" / a.run_id
    assert not base.exists() and not pub.exists(), "fresh run directories required"
    for d in (rev, runner, runner / "out"):  # created by the reviewer before any sandbox runs
        d.mkdir(parents=True, mode=0o700)
    url = f"http://127.0.0.1:{a.rpc_port}"
    summary = {"schema": "g1-independent/run/v1", "run_id": a.run_id, "network": "SANDBOX (local)",
               "repo_commit": subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                                             text=True).stdout.strip(),
               "repo_dirty": bool(subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "packages",
                                                  "scripts", "tests", "contracts", "artifacts"],
                                                 capture_output=True, text=True).stdout.strip()),
               "wasm_sha256": sha256_file(WASM), "actor_sha256": sha256_file(ACTOR),
               "node_binary_sha256": sha256_file(NODE_BIN), "phases": {}}
    node_pid = None
    try:
        # 1. Fresh reviewer-owned node.
        env = dict(os.environ, NODE_HOME=str(node_home), NODE_EVIDENCE_DIR=str(pub / "node"),
                   RPC_ADDR=f"127.0.0.1:{a.rpc_port}", NET_ADDR=f"127.0.0.1:{a.net_port}")
        run([REPO / "scripts/sandbox-setup/start-node.sh", a.run_id], env=env)
        node_pid = int((node_home / "node.pid").read_text())
        status = rpc(url, "status", [])
        genesis = rpc(url, "EXPERIMENTAL_genesis_config", {})
        gblock = rpc(url, "block", {"block_id": genesis["genesis_height"]})
        summary["node"] = {"chain_id": status["chain_id"], "genesis_hash": status["genesis_hash"],
                           "genesis_block_hash": gblock["header"]["hash"], "version": status["version"],
                           "protocol_version": status["protocol_version"], "rpc": url}
        log(f"node {status['chain_id']} genesis {gblock['header']['hash']}")

        # 2. Reviewer setup with the validator key (owner, keyless recipient, keyless attacker).
        run([ACTOR, "reviewer-prepare", "--rpc", url, "--node-home", node_home, "--reviewer-dir", rev,
             "--out", pub / "reviewer/prepare.json"])
        prep = json.loads((pub / "reviewer/prepare.json").read_text())
        hmax = max(outcome_heights(url, prep["transactions"]))
        h0 = wait_final_height(url, hmax + 2)
        h0h = h0["header"]
        log(f"H0 {h0h['height']} {h0h['hash']} (before any vault/agent construction)")

        # 3. Keyless construction by the owner; only agent FC keys are placed in the runner dir.
        run([ACTOR, "reviewer-construct", "--rpc", url, "--reviewer-dir", rev, "--runner-dir", runner,
             "--wasm", WASM, "--out", pub / "reviewer/construct.json"])
        cons = json.loads((pub / "reviewer/construct.json").read_text())

        # 4a. Isolation probe in its own sandbox invocation (same filter as the workload faces).
        #     Its result is imported into reviewer storage BEFORE any untrusted workload runs.
        forbidden = [str(node_home), str(rev), str(Path.home()), str(rev / "owner.key.json"),
                     str(node_home / "validator_key.json"), str(REPO), str(base)]
        sock, probe_out = fresh_dir(base, "sock-probe"), fresh_dir(base, "probe-out")
        proxy = Proxy(sock / "rpc.sock", url, "submit", pub / "runner/proxy-probe.jsonl")
        try:
            sandbox(BRIDGE + f"python3 -I /runner-scripts/isolation_probe.py /probe/isolation.json {a.rpc_port} "
                    + " ".join(forbidden) + " || echo 'isolation probe reported FAIL'",
                    ro=[(sock, "/sock"), (runner, "/runner")], rw=[(probe_out, "/probe")])
        finally:
            proxy.close()
        iso_bytes, iso = import_json(probe_out, "isolation.json", 1 << 20, validate_isolation)
        (pub / "runner").mkdir(parents=True, exist_ok=True)
        (pub / "runner/isolation.json").write_bytes(iso_bytes)
        if iso["isolation_checks"] != "PASS":
            raise RuntimeError("isolation probe FAIL: not starting the untrusted workload")

        # 4b. Untrusted agent workload: agent FC keys + read-only socket dir; writes only /runner.
        sock = fresh_dir(base, "sock-submit")
        proxy = Proxy(sock / "rpc.sock", url, "submit", pub / "runner/proxy-submit.jsonl")
        try:
            sandbox(BRIDGE + "/runner-bin/g1_actor runner-attack --rpc http://127.0.0.1:3030 --runner-dir /runner "
                    "--out /runner/out/runner-log.json",
                    ro=[(sock, "/sock")], rw=[(runner, "/runner")])
        finally:
            proxy.close()
        log_bytes, _ = import_json(runner, "out/runner-log.json", 16 << 20, validate_runner_log)
        (pub / "runner/runner-log.json").write_bytes(log_bytes)
        summary["isolation"] = {"checks": iso["isolation_checks"],
                                "direct_node_rpc": iso["direct_node_rpc_127.0.0.1"],
                                "forbidden_paths_visible": [p for p, v in iso["forbidden_paths_exist"].items() if v],
                                "admin_methods_denied": {k: v.get("denied_by_filter") for k, v in
                                                         iso["admin_methods_via_filter"].items()}}
        proxied = [json.loads(x) for f in ("proxy-probe.jsonl", "proxy-submit.jsonl")
                   for x in (pub / "runner" / f).read_text().splitlines()]
        summary["isolation"]["runner_methods_forwarded"] = sorted({x["method"] for x in proxied if x.get("decision") == "forward"})
        summary["isolation"]["runner_methods_denied"] = sorted({x["method"] for x in proxied if x.get("decision") == "deny"})

        # 5. Owner freeze (reviewer), settle, choose Q.
        run([ACTOR, "reviewer-freeze", "--rpc", url, "--reviewer-dir", rev, "--out", pub / "reviewer/freeze.json"])
        frz = json.loads((pub / "reviewer/freeze.json").read_text())
        settle = max(outcome_heights(url, [frz["transaction"]])) + 20
        q = wait_final_height(url, settle)
        qh = q["header"]
        log(f"Q {qh['height']} {qh['hash']}")

        # 6. Reviewer descriptor (reviewer-selected; contains no transaction hashes).
        protocol = rpc(url, "EXPERIMENTAL_protocol_config", {"block_id": h0h["hash"]})
        shards = protocol["shard_layout"]["V2"]["shard_ids"]
        d = {"schema": "near-g1-reviewer/v1", "network": "sandbox", "chain_id": status["chain_id"],
             "genesis_block_hash": gblock["header"]["hash"], "genesis_rpc_sha256": digest(genesis),
             "node_version": status["version"], "protocol_config_sha256": digest(protocol),
             "h0_hash": h0h["hash"], "h0_height": h0h["height"], "q_hash": qh["hash"], "q_height": qh["height"],
             "vault": cons["vault"], "owner": cons["owner"], "agent": cons["agent"],
             "recipients": cons["recipients"], "policy_hash": cons["policy_hash"], "budget": cons["budget"],
             "max_per_request": cons["max_per_request"], "expires_at_ns": cons["expires_at_ns"],
             "max_accepted_requests": cons["max_accepted_requests"], "asset": "NativeNear",
             "wasm_sha256": sha256_file(WASM), "node_binary_sha256": sha256_file(NODE_BIN),
             "node_config_sha256": sha256_file(node_home / "config.json"),
             "genesis_file_sha256": sha256_file(node_home / "genesis.json"),
             "max_blocks": 10000, "max_roots": 1000, "shard_ids": shards,
             "expected": {"ledger": {"C": str(3 * NEAR), "S": str(NEAR), "F": str(2 * NEAR), "U": "0",
                                     "headroom": str(2 * NEAR), "accepted_count": 2},
                          "principal_refunds": 1,
                          "denial_reasons": sorted(["DuplicateRequest", "AboveMaxPerRequest",
                                                    "RecipientNotAllowed", "RecordQuotaExhausted"]),
                          "failed_call_classes": ["MalformedInput"]}}
        write(pub / "reviewer-descriptor.json", d)
        # Delivered through a FRESH reviewer-created directory mounted read-only, never by writing
        # into the runner-writable tree (a planted symlink there would redirect the write).
        runner_input = fresh_dir(base, "runner-input")
        write(runner_input / "descriptor.json", d)

        # 7. Independent acquisition: direct node access, NO runner input of any kind.
        ind = base / "independent"
        verifier("--network", "sandbox", "--rpc", url, "--descriptor", pub / "reviewer-descriptor.json",
                 "--wasm", WASM, "--node-binary", NODE_BIN, "--node-config", node_home / "config.json",
                 "--genesis-file", node_home / "genesis.json", "--out", ind)
        (pub / "independent").mkdir(parents=True)
        shutil.copy(ind / "result.json", pub / "independent/result.json")
        n = export_rpc_records(ind / "rpc", pub / "independent/rpc.jsonl.gz")
        cap_bytes = (ind / "independent-capture.json").read_bytes()
        summary["independent"] = json.loads((ind / "result.json").read_text())
        summary["independent"] = {k: summary["independent"].get(k) for k in
                                  ("verdicts", "chain_evidence_checks", "issues", "metrics", "capture_sha256")}
        summary["independent"]["rpc_records_exported"] = n
        log(f"independent verdicts {summary['independent']['verdicts']}")

        # 8. Runner presentation through the READ-ONLY filter (submission now refused).
        sock, pres_out = fresh_dir(base, "sock-read"), fresh_dir(base, "presentation-out")
        proxy = Proxy(sock / "rpc.sock", url, "read", pub / "runner/proxy-read.jsonl")
        try:
            sandbox(BRIDGE + "cd /runner-pkg && "
                    "python3 -E -s -m packages.verifier collect --network sandbox --rpc http://127.0.0.1:3030 "
                    "--descriptor /input/descriptor.json --out /presentation/p",
                    ro=[(sock, "/sock"), (runner_input, "/input")], rw=[(pres_out, "/presentation")])
        finally:
            proxy.close()
        pres_bytes, presented = import_json(pres_out, "p/presented-capture.json", 128 << 20, validate_capture)

        # 9. The runner's lie: drop request 2's entire root, descendants, refund, rows; rehash.
        forged, omitted = omit_request_root(presented, "2")
        forged_bytes = canonical(forged)
        assert omitted.encode() not in forged_bytes, "forged presentation still names the omitted root"
        (pub / "runner/forged-presentation.json").write_bytes(forged_bytes + b"\n")
        (pub / "runner/genuine-presentation.sha256").write_text(digest(presented) + "\n")
        write(pub / "runner/forger-record.json", {"note": "Adversary's own record, written AFTER independent "
                                                  "acquisition; never given to the collector.",
                                                  "omitted_tx_hash": omitted})

        # 10. Offline comparisons against the reviewer's own capture.
        (base / "capture.json").write_bytes(cap_bytes)
        (base / "presented.json").write_bytes(pres_bytes)
        verifier("compare", "--capture", base / "capture.json", "--descriptor", pub / "reviewer-descriptor.json",
                 "--presented", base / "presented.json", "--out", pub / "compare-genuine.json")
        verifier("compare", "--capture", base / "capture.json", "--descriptor", pub / "reviewer-descriptor.json",
                 "--presented", pub / "runner/forged-presentation.json", "--out", pub / "compare-forged.json")
        cg = json.loads((pub / "compare-genuine.json").read_text())
        cf = json.loads((pub / "compare-forged.json").read_text())
        omitted_issue = [i for i in cf["issues"] if i["code"] == "OMITTED_ROOT"]
        rec = omitted_issue[0]["recovered_effects"] if omitted_issue else {}
        summary["omission"] = {
            "genuine_presentation_differences": [i["code"] for i in cg["issues"]],
            "genuine_presentation_verdicts": cg["verdicts"],
            "forged_presentation_verdicts": cf["verdicts"],
            "forged_differences": sorted({i["code"] for i in cf["issues"]}),
            "omitted_root_recovered": [i["tx_hash"] for i in omitted_issue],
            "omitted_root_matches_forger": [i["tx_hash"] for i in omitted_issue] == [omitted],
            "recovered_payment": rec.get("payments"),
            "recovered_principal_refunds": [r for r in rec.get("balance_refunds", [])],
        }

        # 11. Mutation suite over the genuine recorded responses (offline replay).
        verifier("mutate", "--rpc-records", pub / "independent/rpc.jsonl.gz", "--descriptor",
                 pub / "reviewer-descriptor.json", "--out", pub / "mutations.json")
        mut = json.loads((pub / "mutations.json").read_text())
        summary["mutations"] = {"baseline_replay": mut["baseline"]["chain_evidence_checks"],
                                "all_applied_and_rejected": mut["all_applied_and_rejected"],
                                "count": len(mut["mutations"])}

        # 12. Retention: >= N produced blocks after Q, no fast-forward; re-acquire and compare.
        target = qh["height"] + a.retention_blocks
        log(f"waiting for final height {target} (no fast-forward)")
        later = wait_final_height(url, target)
        ret = base / "retention"
        verifier("--network", "sandbox", "--rpc", url, "--descriptor", pub / "reviewer-descriptor.json",
                 "--wasm", WASM, "--node-binary", NODE_BIN, "--node-config", node_home / "config.json",
                 "--genesis-file", node_home / "genesis.json", "--out", ret)
        c1 = json.loads(cap_bytes)
        c2 = json.loads((ret / "independent-capture.json").read_text())
        # final_head and the live status snapshot change over time; from status compare identity
        # only (see retention_compare.py, which writes the authoritative comparison).
        same = {k: (all(c1[k].get(x) == c2[k].get(x) for x in ("chain_id", "genesis_hash", "version",
                                                                  "protocol_version"))
                    if k == "status" else canonical(c1[k]) == canonical(c2[k]))
                for k in c1 if k != "final_head"}
        r2 = json.loads((ret / "result.json").read_text())
        summary["retention"] = {"q_height": qh["height"], "reacquired_at_final_height": later["header"]["height"],
                                "produced_blocks_after_q": later["header"]["height"] - qh["height"],
                                "fields_identical": all(same.values()),
                                "differing_fields": [k for k, v in same.items() if not v],
                                "verdicts": r2["verdicts"]}
        write(pub / "retention.json", summary["retention"])
    finally:
        if node_pid:
            try:
                os.kill(node_pid, 15)
                log(f"node {node_pid} stopped; history kept at {node_home}")
            except ProcessLookupError:
                pass
        summary["elapsed_seconds"] = round(time.time() - t0, 1)
        summary["log"] = [line.replace(str(Path.home()), "~") for line in LOG]
        if pub.exists():
            write(pub / "run-summary.json", summary)
            sanitize_home(pub)
    print(json.dumps({k: summary.get(k) for k in ("isolation", "independent", "omission", "mutations", "retention")},
                     indent=2, default=str))


if __name__ == "__main__":
    main()
