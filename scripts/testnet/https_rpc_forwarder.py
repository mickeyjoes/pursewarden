#!/usr/bin/env python3
"""Loopback HTTP -> HTTPS JSON-RPC forwarder for NEAR TESTNET only (stdlib).

  python3 scripts/testnet/https_rpc_forwarder.py --port 3399 --upstream https://rpc.testnet.near.org

The Rust harness speaks plain HTTP to loopback only (its HTTP client is built without TLS, and
adding TLS would change the shared lockfile). This forwarder is the only path to a public node:
- the upstream must be an allowlisted TESTNET host;
- at startup the upstream's chain_id must be "testnet", otherwise it exits before listening;
- single JSON-RPC objects only; every forwarded method is logged.
"""
import argparse
import http.server
import json
import sys
import time
import urllib.parse
import urllib.request

ALLOWED = {"rpc.testnet.near.org", "test.rpc.fastnear.com", "rpc.testnet.fastnear.com"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=3399)
    ap.add_argument("--upstream", default="https://rpc.testnet.near.org")
    ap.add_argument("--log", default="-")
    a = ap.parse_args()
    u = urllib.parse.urlparse(a.upstream)
    if u.scheme != "https" or u.hostname not in ALLOWED:
        sys.exit(f"refusing upstream {a.upstream}: only https testnet hosts {sorted(ALLOWED)}")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def post(body):
        req = urllib.request.Request(a.upstream, data=body, headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=60) as r:
            return r.read()

    chain = json.loads(post(b'{"jsonrpc":"2.0","id":"f","method":"status","params":[]}'))["result"]["chain_id"]
    if chain != "testnet":
        sys.exit(f"refusing: upstream chain_id is {chain!r}, not 'testnet'")
    log = sys.stderr if a.log == "-" else open(a.log, "a")

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(min(n, 4 << 20))
            try:
                req = json.loads(raw)
                assert isinstance(req, dict) and isinstance(req.get("method"), str)
            except Exception:
                self.send_response(400); self.end_headers(); return
            try:
                body, code = post(raw), 200
            except Exception as exc:
                body, code = json.dumps({"error": str(exc)}).encode(), 502
            log.write(json.dumps({"t": time.time(), "method": req["method"], "bytes": len(body)}) + "\n"); log.flush()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print(f"testnet forwarder http://127.0.0.1:{a.port} -> {a.upstream} (chain_id {chain})", file=sys.stderr, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
