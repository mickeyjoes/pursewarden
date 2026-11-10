"""Runs INSIDE the runner sandbox and records what the runner can and cannot reach.

  python3 -I isolation_probe.py OUT.json NODE_RPC_PORT FORBIDDEN_PATH...

Expected: the node's RPC port is unreachable directly; node home, reviewer directory, owner key
and the user's home are invisible; administrative/sandbox RPC methods are refused by the filter.
"""
import json
import os
import socket
import sys
import urllib.request


def tcp(host, port):
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect((host, port))
        return "CONNECTED"
    except OSError as exc:
        return f"refused: {exc.__class__.__name__}: {exc}"
    finally:
        s.close()


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": "probe", "method": method, "params": params}).encode()
    req = urllib.request.Request("http://127.0.0.1:3030", data=body, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as r:
            resp = json.loads(r.read())
    except Exception as exc:
        return {"transport_error": str(exc)}
    err = resp.get("error")
    return {"denied_by_filter": bool(err and err.get("message") == "denied by reviewer RPC filter"),
            "error": err, "has_result": "result" in resp}


def main():
    out, port, forbidden = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    probes = {
        "uid": os.getuid(), "home_env": os.environ.get("HOME"),
        "visible_root_entries": sorted(os.listdir("/")),
        "visible_process_ids": sorted(int(x) for x in os.listdir("/proc") if x.isdigit()),
        "direct_node_rpc_127.0.0.1": tcp("127.0.0.1", port),
        "direct_node_rpc_localhost_ipv6": tcp("::1", port) if socket.has_ipv6 else "no ipv6",
        "external_network_1.1.1.1:443": tcp("1.1.1.1", 443),
        "forbidden_paths_exist": {p: os.path.exists(p) for p in forbidden},
        "admin_methods_via_filter": {
            "sandbox_patch_state": rpc("sandbox_patch_state", {"records": []}),
            "sandbox_fast_forward": rpc("sandbox_fast_forward", {"delta_height": 1}),
            "adv_produce_blocks": rpc("adv_produce_blocks", [1, True]),
            "client_config": rpc("client_config", []),
            "network_info": rpc("network_info", []),
            "query_view_access_key_list_allowed": rpc("query", {"request_type": "view_access_key_list",
                                                               "account_id": "test.near", "finality": "final"}),
        },
    }
    ok = (not probes["direct_node_rpc_127.0.0.1"].startswith("CONNECTED")
          and not str(probes["direct_node_rpc_localhost_ipv6"]).startswith("CONNECTED")
          and not probes["external_network_1.1.1.1:443"].startswith("CONNECTED")
          and not any(probes["forbidden_paths_exist"].values())
          and all(v.get("denied_by_filter") for k, v in probes["admin_methods_via_filter"].items()
                  if not k.endswith("_allowed"))
          and probes["admin_methods_via_filter"]["query_view_access_key_list_allowed"].get("has_result"))
    probes["isolation_checks"] = "PASS" if ok else "FAIL"
    with open(out, "w") as f:
        json.dump(probes, f, indent=2)
    print("isolation", probes["isolation_checks"], flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
