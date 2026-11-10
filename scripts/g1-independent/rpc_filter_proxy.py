"""Reviewer-owned JSON-RPC filter exposed to the runner as a Unix socket.

The runner sandbox has no network namespace route to the node; this socket is the ONLY path it
has to the chain. Only ordinary read methods (and, in `submit` mode, transaction submission) are
forwarded. Administrative and sandbox methods (sandbox_patch_state, sandbox_fast_forward,
adv_*, client_config, ...) are refused. Every request and decision is logged.

  python3 -I rpc_filter_proxy.py --socket PATH --upstream http://127.0.0.1:PORT \
      --mode submit|read --log PATH.jsonl
"""
import argparse
import http.server
import json
import os
import socketserver
import sys
import time
import urllib.request

READ = {"status", "block", "chunk", "query", "tx", "EXPERIMENTAL_tx_status",
        "EXPERIMENTAL_genesis_config", "EXPERIMENTAL_protocol_config", "EXPERIMENTAL_changes",
        "gas_price"}
SUBMIT = {"send_tx", "broadcast_tx_async", "broadcast_tx_commit"}
QUERY_TYPES = {"view_account", "view_access_key", "view_access_key_list", "view_code",
               "view_state", "call_function"}
MAX_BODY = 4 * 1024 * 1024


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def make_handler(upstream, allowed, log):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    class Handler(http.server.BaseHTTPRequestHandler):
        def address_string(self):
            return "runner-unix-socket"

        def log_message(self, *a):
            pass

        def reply(self, code, body):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.reply(405, b'{"error":"POST JSON-RPC only"}')

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                return self.reply(413, b'{"error":"bad length"}')
            raw = self.rfile.read(n)
            entry = {"t": time.time(), "bytes": n}
            try:
                req = json.loads(raw)
                ok_shape = isinstance(req, dict) and isinstance(req.get("method"), str)
            except ValueError:
                req, ok_shape = None, False
            if not ok_shape:
                entry.update(decision="deny", reason="not a single JSON-RPC object")
                log.write(json.dumps(entry) + "\n"); log.flush()
                return self.reply(400, b'{"error":"single JSON-RPC object required"}')
            method = req["method"]
            params = req.get("params")
            entry["method"] = method
            reason = None
            if method not in allowed:
                reason = "method not allowed for runner"
            elif method == "query":
                rt = params.get("request_type") if isinstance(params, dict) else None
                entry["request_type"] = rt
                if rt not in QUERY_TYPES:
                    reason = "query type not allowed"
            if reason:
                entry.update(decision="deny", reason=reason)
                log.write(json.dumps(entry) + "\n"); log.flush()
                body = json.dumps({"jsonrpc": "2.0", "id": req.get("id"),
                                   "error": {"code": -32601, "message": "denied by reviewer RPC filter",
                                             "data": {"method": method, "reason": reason}}}).encode()
                return self.reply(200, body)
            try:
                r = urllib.request.Request(upstream, data=raw, headers={"Content-Type": "application/json"})
                with opener.open(r, timeout=60) as resp:
                    body = resp.read()
                entry.update(decision="forward", response_bytes=len(body))
                code = 200
            except Exception as exc:  # upstream unavailable: report, never retry
                entry.update(decision="forward-error", error=str(exc))
                body, code = json.dumps({"error": "upstream unavailable"}).encode(), 502
            log.write(json.dumps(entry) + "\n"); log.flush()
            self.reply(code, body)
    return Handler


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--socket", required=True)
    p.add_argument("--upstream", required=True)
    p.add_argument("--mode", choices=["submit", "read"], required=True)
    p.add_argument("--log", required=True)
    a = p.parse_args()
    allowed = READ | (SUBMIT if a.mode == "submit" else set())
    if os.path.exists(a.socket):
        os.unlink(a.socket)
    log = open(a.log, "a")
    srv = Server(a.socket, make_handler(a.upstream, allowed, log))
    os.chmod(a.socket, 0o600)
    print(f"filter proxy ({a.mode}) on {a.socket} -> {a.upstream}", file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    finally:
        os.unlink(a.socket)


if __name__ == "__main__":
    main()
