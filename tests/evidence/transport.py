"""Loopback fake RPC for transport tests. It never runs a NEAR node."""
import contextlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from packages.collector import EvidenceError, canonical, loads


@contextlib.contextmanager
def fake_rpc(node):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            req = loads(self.rfile.read(int(self.headers["Content-Length"])))
            envelope = {"jsonrpc": "2.0", "id": req["id"]}
            try:
                envelope["result"] = node.call(req["method"], req["params"])
            except EvidenceError as exc:
                envelope["error"] = exc.detail.get("error", {"code": -32000, "message": str(exc)})
            data = canonical(envelope)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
