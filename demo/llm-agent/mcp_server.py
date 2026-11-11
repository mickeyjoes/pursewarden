#!/usr/bin/env python3
"""MCP (stdio) tool server exposing the two Pursewarden demo tools to the language model.

  python3 -I mcp_server.py --socket /path/to/gateway.sock

It holds NO key material and makes no policy decisions. Each tool call is forwarded as one JSON
line to the payment gateway's Unix socket (the only process that holds the agent's restricted
FunctionCall key) and the gateway's answer is returned to the model verbatim.

Fail closed: if the gateway does not answer a propose_payment call, the outcome is reported as
UNCERTAIN and every later propose_payment call in this session is refused without contacting
the gateway.
"""
import json
import socket
import sys

SERVER_NAME = "pursewarden"
SERVER_VERSION = "0.1.0"
GATEWAY_TIMEOUT_S = 700  # the gateway waits for FINAL (up to 2 x 300 s in the worst case)

TOOLS = [
    {
        "name": "get_vault_status",
        "description": ("Read the owner's payment vault: its spending mandate (budget, per-payment cap, allowed "
                        "recipients, maximum number of payments, expiry) and how much has been charged so far. "
                        "Read-only; it never moves funds."),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "propose_payment",
        "description": ("Submit ONE payment request to the owner's on-chain payment vault (local NEAR test "
                        "network). The vault checks the owner's mandate and either admits the request (NEAR is "
                        "sent to the recipient) or denies it. A submitted request is final and cannot be undone. "
                        "Reusing an invoice_id reuses its on-chain request ID, which the vault rejects as a "
                        "duplicate."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "description": "NEAR account ID to pay, e.g. name.test.near"},
                "amount_near": {"type": "string",
                                "description": ("Amount in NEAR as a plain decimal string such as \"0.75\". "
                                                "No units, signs, exponents, spaces or separators."),
                                "pattern": "^(0|[1-9][0-9]{0,5})(\\.[0-9]{1,24})?$"},
                "invoice_id": {"type": "string", "description": "Invoice or reference this payment settles.",
                               "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$"},
                "reason": {"type": "string", "maxLength": 500,
                           "description": "One-line justification, recorded for the owner's audit log."},
            },
            "required": ["recipient", "amount_near", "invoice_id", "reason"],
            "additionalProperties": False,
        },
    },
]


class Gateway:
    def __init__(self, path):
        self.path = path
        self.halted = None

    def ask(self, req):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(GATEWAY_TIMEOUT_S)
        try:
            s.connect(self.path)
            s.sendall((json.dumps(req, separators=(",", ":")) + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
            return json.loads(buf)
        finally:
            s.close()

    def call(self, name, arguments):
        if name == "get_vault_status":
            if arguments:
                return {"status": "REJECTED_BY_TOOL", "error": "get_vault_status takes no arguments"}, True
            try:
                r = self.ask({"op": "get_vault_status", "origin": "model"})
            except Exception as e:  # read-only: an error here moves no funds
                return {"status": "ERROR", "error": f"gateway unavailable: {type(e).__name__}"}, True
            return r, r.get("status") != "OK"
        if name == "propose_payment":
            if self.halted:
                return {"status": "HALTED", "submitted": False,
                        "error": f"payments are halted for this session: {self.halted}"}, True
            try:
                r = self.ask({"op": "propose_payment", "origin": "model", "args": arguments})
            except Exception as e:
                self.halted = f"the gateway did not answer ({type(e).__name__})"
                return {"status": "UNCERTAIN", "error": ("The payment gateway did not answer. The request may or "
                                                         "may not have been submitted. Do not retry; payments "
                                                         "are halted.")}, True
            return r, r.get("status") not in ("ADMITTED", "DENIED")
        return {"status": "ERROR", "error": f"unknown tool {name!r}"}, True


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "--socket":
        print("usage: mcp_server.py --socket PATH", file=sys.stderr)
        return 2
    gw = Gateway(sys.argv[2])
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if not isinstance(msg, dict) or "id" not in msg:
            continue  # notifications (e.g. notifications/initialized) need no answer
        mid, method, params = msg["id"], msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            result = {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            body, is_error = gw.call(params.get("name"), params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(body, indent=1)}], "isError": is_error}
        else:
            reply = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
            continue
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
