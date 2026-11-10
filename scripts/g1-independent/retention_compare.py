#!/usr/bin/env python3
"""Compare the first independent capture with the >= 2000-block retention re-acquisition.

  python3 retention_compare.py RUN_ID

`final_head` and the live `status` snapshot (sync_info, uptime, validators) legitimately change
over time; from `status` only the node identity is compared. Every other capture field, i.e.
every block, chunk, transaction graph, Q query and state-change history entry, must be
byte-identical. Writes evidence/g1-independent/RUN_ID/retention-compare.json.
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from packages.collector import canonical, digest  # noqa: E402

TOOLS = Path(os.environ.get("NEAR_VAULT_TOOLS", Path.home() / ".local/share/near-agent-vault-lab"))
STATUS_IDENTITY = ("chain_id", "genesis_hash", "version", "protocol_version")


def main():
    run = sys.argv[1]
    base = TOOLS / "g1-independent" / run
    first = json.loads((base / "independent/independent-capture.json").read_text())
    later = json.loads((base / "retention/independent-capture.json").read_text())
    fields = {}
    for k in sorted(set(first) | set(later)):
        if k == "final_head":
            continue
        if k == "status":
            fields[k] = all(first[k].get(x) == later[k].get(x) for x in STATUS_IDENTITY)
        else:
            fields[k] = canonical(first.get(k)) == canonical(later.get(k))
    graphs_same = {t: canonical(first["graphs"][t]) == canonical(later["graphs"].get(t)) for t in first["graphs"]}
    out = {"schema": "g1-independent/retention-compare/v1", "run_id": run,
           "excluded": ["final_head (live head)", "status except " + ", ".join(STATUS_IDENTITY)],
           "fields_identical": fields, "all_identical": all(fields.values()),
           "graphs_compared": len(graphs_same), "graphs_identical": sum(graphs_same.values()),
           "first_final_head": first["final_head"]["header"]["height"],
           "later_final_head": later["final_head"]["header"]["height"],
           "first_capture_sha256": digest(first), "later_capture_sha256": digest(later)}
    p = REPO / "evidence/g1-independent" / run / "retention-compare.json"
    p.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({k: out[k] for k in ("all_identical", "graphs_compared", "graphs_identical",
                                           "first_final_head", "later_final_head")}))
    return 0 if out["all_identical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
