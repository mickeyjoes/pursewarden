#!/usr/bin/env python3
"""Print a compact, read-only replay of a recorded demo run (no node, no model needed).

  python3 demo/llm-agent/show_run.py demo/llm-agent/evidence/<run-id> [--episodes inject-1,control-1]

Everything printed is read from the run's evidence files: the model's tool calls and final message
from transcript.jsonl, the vault's decisions from gateway-log.jsonl (cross-checked against the
chain by evidence_check.py).
"""
import json
import sys
from pathlib import Path

DIM, BOLD, RED, GREEN, YEL, OFF = ("\033[2m", "\033[1m", "\033[31m", "\033[32m", "\033[33m", "\033[0m") \
    if sys.stdout.isatty() else ("",) * 6


def lines(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    run = Path(sys.argv[1])
    only = sys.argv[3].split(",") if len(sys.argv) > 3 and sys.argv[2] == "--episodes" else None
    s = json.loads((run / "summary.json").read_text())
    print(f"{BOLD}run {s['run_id']}{OFF} · {s['network']} · chain {s['node']['chain_id']} · model {s['model']['requested']}"
          f" via {s['model']['claude_code_version']}")
    for ep in s["episodes"]:
        if only and ep["name"] not in only:
            continue
        d = run / "episodes" / ep["name"]
        who = f"{BOLD}{ep['init_model']}{OFF}" if ep["agent_kind"] == "llm" else f"{YEL}{BOLD}DETERMINISTIC CONTROL (scripted, not an LLM){OFF}"
        print(f"\n{BOLD}── {ep['name']}{OFF} · scenario {ep['scenario']} · agent: {who}")
        if ep["agent_kind"] == "llm":
            print(f"{DIM}   owner: {(d / 'prompt.txt').read_text().splitlines()[1]}{OFF}")
        log = iter([e for e in lines(d / "gateway-log.jsonl") if e.get("op") == "propose_payment"])
        if ep["agent_kind"] == "llm":
            calls = [c for e in lines(d / "transcript.jsonl") if e.get("type") == "assistant"
                     for c in e["message"].get("content", []) if c.get("type") == "tool_use"]
        else:
            calls = [{"name": "propose_payment", "input": st["args"]}
                     for st in json.loads((d / "control-log.json").read_text())["steps"]]
        for c in calls:
            name = c["name"].rsplit("__", 1)[-1]
            if name != "propose_payment":
                print(f"   agent → {name}()")
                continue
            a = c["input"]
            e = next(log)  # evidence_check.py verifies the one-to-one order for model episodes
            assert e["args_received"] == a, "transcript and gateway log disagree; run evidence_check.py"
            r = e["response"]
            st = r.get("status")
            col = GREEN if st == "ADMITTED" else RED if st == "DENIED" else YEL
            verdict = {"ADMITTED": f"vault: Admitted, transfer {r.get('transfer')}",
                       "DENIED": f"vault: Denied {r.get('reason')}"}.get(st, f"tool: {st}, not submitted to the vault")
            tx = f" {DIM}tx {r['tx_hash'][:10]}…{OFF}" if r.get("tx_hash") else ""
            print(f"   agent → propose_payment {a['amount_near']} NEAR → {a['recipient']} ({a['invoice_id']})"
                  f"  ⇒ {col}{verdict}{OFF}{tx}")
        if not any(c["name"].endswith("propose_payment") for c in calls):
            print(f"   {BOLD}no payment proposed{OFF}")
        if ep["agent_kind"] == "llm" and ep.get("final_text"):
            print(f"   model to owner: \"{ep['final_text'].splitlines()[0]}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
