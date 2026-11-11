"""Tests for the LLM-agent demo (standard library only).

  python3 -m unittest discover -s demo/llm-agent/tests

- MCP shim: protocol, strict tool surface, and fail-closed behaviour on an unanswered payment.
- Redaction and the leak scan.
- The recorded evidence run(s): the offline check must pass, and tampering with the transcript,
  the gateway log, the raw chain outcome, the model identity or the control label must fail it.
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO))
import evidence_check as ec  # noqa: E402

EVIDENCE = DEMO / "evidence"
RECORDED = sorted(p for p in EVIDENCE.glob("llm-*") if (p / "summary.json").exists()) if EVIDENCE.exists() else []


class FakeGateway:
    """Unix-socket stand-in for the Rust gateway. `script` lists, per connection, a reply or None
    (None = accept, read the request, then close without answering)."""

    def __init__(self, script):
        self.dir = tempfile.mkdtemp(prefix="pwfake-")
        self.path = os.path.join(self.dir, "gw.sock")
        self.script, self.requests = list(script), []
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(self.path)
        self.srv.listen(4)
        self.t = threading.Thread(target=self.loop, daemon=True)
        self.t.start()

    def loop(self):
        while self.script:
            c, _ = self.srv.accept()
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = c.recv(65536)
                if not chunk:
                    break
                buf += chunk
            self.requests.append(json.loads(buf))
            reply = self.script.pop(0)
            if reply is not None:
                c.sendall((json.dumps(reply) + "\n").encode())
            c.close()

    def close(self):
        self.srv.close()
        shutil.rmtree(self.dir, ignore_errors=True)


def mcp_session(sock_path, messages):
    p = subprocess.run([sys.executable, "-I", str(DEMO / "mcp_server.py"), "--socket", sock_path],
                       input="".join(json.dumps(m) + "\n" for m in messages), capture_output=True, text=True, timeout=60)
    return [json.loads(l) for l in p.stdout.splitlines()]


PAY = {"recipient": "gpu-vendor.test.near", "amount_near": "0.6", "invoice_id": "INV-1002", "reason": "October compute"}


class McpShim(unittest.TestCase):
    def test_protocol_and_tool_surface(self):
        gw = FakeGateway([{"status": "OK", "budget_near": "2"}])
        try:
            out = mcp_session(gw.path, [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_vault_status", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 4, "method": "resources/list"},
            ])
        finally:
            gw.close()
        self.assertEqual([m["id"] for m in out], [1, 2, 3, 4])  # the notification gets no answer
        self.assertEqual(out[0]["result"]["protocolVersion"], "2025-06-18")
        tools = {t["name"]: t for t in out[1]["result"]["tools"]}
        self.assertEqual(sorted(tools), ["get_vault_status", "propose_payment"])
        schema = tools["propose_payment"]["inputSchema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(sorted(schema["required"]), ["amount_near", "invoice_id", "reason", "recipient"])
        self.assertFalse(out[2]["result"]["isError"])
        self.assertEqual(gw.requests, [{"op": "get_vault_status", "origin": "model"}])
        self.assertEqual(out[3]["error"]["code"], -32601)

    def test_payment_is_forwarded_verbatim_and_unanswered_payment_halts_the_session(self):
        denied = {"status": "DENIED", "reason": "RecipientNotAllowed", "submitted": True}
        gw = FakeGateway([denied, None])
        call = lambda i: {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                          "params": {"name": "propose_payment", "arguments": PAY}}
        try:
            out = mcp_session(gw.path, [call(1), call(2), call(3)])
        finally:
            gw.close()
        bodies = [json.loads(m["result"]["content"][0]["text"]) for m in out]
        self.assertEqual(bodies[0], denied)
        self.assertFalse(out[0]["result"]["isError"])
        self.assertEqual(bodies[1]["status"], "UNCERTAIN")
        self.assertTrue(out[1]["result"]["isError"])
        self.assertEqual(bodies[2]["status"], "HALTED")
        # The third call never reached the gateway; the first two were forwarded unchanged.
        self.assertEqual(gw.requests, [{"op": "propose_payment", "origin": "model", "args": PAY}] * 2)


class Redaction(unittest.TestCase):
    def test_redacts_real_addresses_and_home_but_keeps_fictional_ones(self):
        s = "user someone@realmail.com, vendor billing@gpu-vendor.example, path /home/u/x"
        r = ec.redact_text(s, home="/home/u")
        self.assertNotIn("someone@realmail.com", r)
        self.assertIn("billing@gpu-vendor.example", r)
        self.assertIn("~/x", r)
        self.assertEqual(ec.redact_obj({"plugins": [1], "a": {"memory_paths": 1, "b": "x"}}), {"a": {"b": "x"}})

    def test_leak_scan(self):
        d = Path(tempfile.mkdtemp())
        try:
            sig = "ed25519:" + "3" * 87
            (d / "ok.json").write_text(json.dumps({"signature": sig, "public_key": "ed25519:" + "2" * 44}))
            self.assertEqual(ec.leak_scan(d), [])
            (d / "bad.json").write_text(json.dumps({"k": sig}))
            self.assertEqual(ec.leak_scan(d), ["LEAK_KEY_MATERIAL bad.json"])
            (d / "bad.json").write_text("contact: someone@realmail.com")
            self.assertEqual(ec.leak_scan(d), ["LEAK_EMAIL bad.json"])
            (d / "bad.json").write_text("xyzSECRETxyz")
            self.assertEqual(ec.leak_scan(d, ["SECRET"]), ["LEAK_EXACT_SECRET bad.json"])
        finally:
            shutil.rmtree(d)


@unittest.skipUnless(RECORDED, "no recorded llm-* run under demo/llm-agent/evidence")
class RecordedRun(unittest.TestCase):
    def test_recorded_runs_pass(self):
        for run in RECORDED:
            r = ec.check_run(run)
            self.assertTrue(r["ok"], f"{run.name}: {r['problems']}")

    def tamper(self, fn):
        run = RECORDED[-1]
        d = Path(tempfile.mkdtemp()) / run.name
        shutil.copytree(run, d)
        try:
            fn(d, json.loads((d / "summary.json").read_text()))
            return ec.check_run(d)
        finally:
            shutil.rmtree(d.parent)

    @staticmethod
    def first(d, summary, kind, predicate):
        for ep in summary["episodes"]:
            if ep["agent_kind"] != kind:
                continue
            for line in (d / "episodes" / ep["name"] / "gateway-log.jsonl").read_text().splitlines():
                e = json.loads(line)
                if predicate(e):
                    return ep["name"], e
        return None, None

    def test_flipped_chain_decision_fails(self):
        def f(d, s):
            name, e = self.first(d, s, "control", lambda e: e.get("response", {}).get("status") == "DENIED")
            p = d / "episodes" / name / "tx" / f"{e['detail']['tx_hash']}.json"
            fin = json.loads(p.read_text())
            first = fin["transaction_outcome"]["outcome"]["receipt_ids"][0]
            for o in fin["receipts_outcome"]:
                if o["id"] == first:
                    dec = json.loads(base64.b64decode(o["outcome"]["status"]["SuccessValue"]))
                    dec["reason"] = "BudgetExceeded" if dec["reason"] != "BudgetExceeded" else "Frozen"
                    o["outcome"]["status"]["SuccessValue"] = base64.b64encode(json.dumps(dec).encode()).decode()
            p.write_text(json.dumps(fin))
        r = self.tamper(f)
        self.assertFalse(r["ok"])
        self.assertTrue(any("chain says" in p for p in r["problems"]), r["problems"])

    def test_extra_gateway_payment_not_requested_by_the_model_fails(self):
        llm = [e for e in json.loads((RECORDED[-1] / "summary.json").read_text())["episodes"] if e["agent_kind"] == "llm"]
        if not llm:
            self.skipTest("no LLM episode")

        def f(d, s):
            log = d / "episodes" / llm[0]["name"] / "gateway-log.jsonl"
            lines = log.read_text().splitlines()
            fake = {"op": "propose_payment", "origin": "model", "args_received": PAY, "gateway_seq": 999,
                    "detail": {}, "response": {"status": "REJECTED_BY_TOOL", "submitted": False}}
            log.write_text("\n".join(lines + [json.dumps(fake)]) + "\n")
        r = self.tamper(f)
        self.assertFalse(r["ok"])
        self.assertTrue(any("one-to-one" in p for p in r["problems"]), r["problems"])

    def test_relabelled_model_identity_fails(self):
        llm = [e for e in json.loads((RECORDED[-1] / "summary.json").read_text())["episodes"] if e["agent_kind"] == "llm"]
        if not llm:
            self.skipTest("no LLM episode")

        def f(d, s):
            t = d / "episodes" / llm[0]["name"] / "transcript.jsonl"
            evs = [json.loads(l) for l in t.read_text().splitlines()]
            for e in evs:
                if e.get("type") == "assistant":
                    e["message"]["model"] = "some-other-model"
                    break
            t.write_text("".join(json.dumps(e) + "\n" for e in evs))
        r = self.tamper(f)
        self.assertFalse(r["ok"])
        self.assertTrue(any("report models" in p for p in r["problems"]), r["problems"])

    def test_control_relabelled_as_model_fails(self):
        def f(d, s):
            for ep in s["episodes"]:
                if ep["agent_kind"] == "control":
                    log = d / "episodes" / ep["name"] / "gateway-log.jsonl"
                    log.write_text(log.read_text().replace('"origin":"deterministic-control"', '"origin":"model"'))
        r = self.tamper(f)
        self.assertFalse(r["ok"])
        self.assertTrue(any("expected 'deterministic-control'" in p for p in r["problems"]), r["problems"])

    def test_leaked_address_fails(self):
        def f(d, s):
            (d / "episodes" / s["episodes"][0]["name"] / "note.txt").write_text("someone@realmail.com")
        r = self.tamper(f)
        self.assertIn("LEAK_EMAIL note.txt", r["problems"])


if __name__ == "__main__":
    unittest.main()
