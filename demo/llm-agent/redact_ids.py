"""Second redaction pass over the LLM demo transcripts (release integration, 2026-11-11).

  python3 -I redact_ids.py RUN_DIR            # rewrite transcripts in place, then verify
  python3 -I redact_ids.py RUN_DIR --verify ORIGINAL_RUN_DIR

Removes identifiers that link the run to the operator's Claude account and are not needed to
check the run:
  - every event's `session_id` and `uuid`;
  - assistant events' `request_id` and `message.id`;
  - `rate_limit_event.rate_limit_info` (account usage, replaced by "<redacted>");
  - tool-use IDs (`toolu_…`) are replaced by `tool-ref-N` (N by first appearance in the
    transcript), consistently, so every tool call still links to its result.
Everything else is byte-for-byte the same value; lines are re-serialized as the run did
(json.dumps(ev, ensure_ascii=False) + "\n").
"""
import json, re, sys
from pathlib import Path

TOOLU = re.compile(r"toolu_[A-Za-z0-9]+")


def redact_events(lines):
    refs = {}
    out = []
    for line in lines:
        line = TOOLU.sub(lambda m: refs.setdefault(m.group(0), f"tool-ref-{len(refs) + 1}"), line)
        ev = json.loads(line)
        ev.pop("session_id", None)
        ev.pop("uuid", None)
        if ev.get("type") == "assistant":
            ev.pop("request_id", None)
            if isinstance(ev.get("message"), dict):
                ev["message"].pop("id", None)
        if ev.get("type") == "rate_limit_event" and "rate_limit_info" in ev:
            ev["rate_limit_info"] = "<redacted>"
        out.append(ev)
    return out, refs


def verify(orig_dir, new_dir):
    """Independent structural check: the only differences are the listed ones."""
    problems = []
    for op in sorted(Path(orig_dir).glob("episodes/*/transcript.jsonl")):
        np_ = Path(new_dir) / op.relative_to(orig_dir)
        o = [json.loads(l) for l in op.read_text().splitlines() if l.strip()]
        n = [json.loads(l) for l in np_.read_text().splitlines() if l.strip()]
        if len(o) != len(n):
            problems.append(f"{op}: event count {len(o)} -> {len(n)}")
            continue
        ids = {}

        def cmp(a, b, path):
            if isinstance(a, dict) and isinstance(b, dict):
                # Tool ids can also be dict keys: pair them through the (one-to-one) mapping.
                old_keys = [k for k in a if TOOLU.fullmatch(k)]
                new_keys = [k for k in b if re.fullmatch(r"tool-ref-[0-9]+", k)]
                if len(old_keys) != len(new_keys):
                    problems.append(f"{op.parent.name}: tool-id key count at {path}")
                for k in old_keys:
                    if k not in ids:
                        free = [y for y in new_keys if y not in ids.values()]
                        if len(free) != 1:
                            problems.append(f"{op.parent.name}: cannot pair tool-id key at {path}")
                            continue
                        ids[k] = free[0]
                a = {ids.get(k, k) if TOOLU.fullmatch(k) else k: v for k, v in a.items()}
                for k in set(a) | set(b):
                    p = f"{path}.{k}"
                    if k not in b:
                        if not (k in ("session_id", "uuid") and path.count(".") == 0
                                or k == "request_id" and path == "assistant"
                                or k == "id" and path == "assistant.message"):
                            problems.append(f"{op.parent.name}: removed {p}")
                        elif isinstance(a[k], str) and TOOLU.search(a[k]):
                            problems.append(f"{op.parent.name}: removed a tool id at {p}")
                    elif k not in a:
                        problems.append(f"{op.parent.name}: added {p}")
                    else:
                        cmp(a[k], b[k], p)
            elif isinstance(a, list) and isinstance(b, list):
                if len(a) != len(b):
                    problems.append(f"{op.parent.name}: list length at {path}")
                for x, y in zip(a, b):
                    cmp(x, y, path + "[]")
            elif isinstance(a, str) and isinstance(b, str) and TOOLU.search(a):
                olds, news = TOOLU.findall(a), re.findall(r"tool-ref-[0-9]+", b)
                if len(olds) != len(news):
                    problems.append(f"{op.parent.name}: tool id count at {path}")
                for x, y in zip(olds, news):
                    if ids.setdefault(x, y) != y:
                        problems.append(f"{op.parent.name}: inconsistent tool id mapping at {path}")
                rest = a
                for x in olds:
                    rest = rest.replace(x, ids.get(x, x), 1)
                if rest != b:
                    problems.append(f"{op.parent.name}: other text changed at {path}")
            elif path == "rate_limit_event.rate_limit_info":
                if b != "<redacted>":
                    problems.append(f"{op.parent.name}: rate limit info not redacted")
            elif a != b:
                problems.append(f"{op.parent.name}: value changed at {path}")

        for x, y in zip(o, n):
            cmp(x, y, x.get("type", "?"))
        if len(set(ids.values())) != len(ids):
            problems.append(f"{op.parent.name}: tool id mapping not one-to-one")
        text = np_.read_text()
        for pat in (TOOLU, re.compile(r"msg_[A-Za-z0-9]{10,}"), re.compile(r"req_[A-Za-z0-9]{10,}"),
                    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), re.compile("utilization")):
            if pat.search(text):
                problems.append(f"{op.parent.name}: still contains {pat.pattern[:20]}")
    return problems


def main():
    run = Path(sys.argv[1])
    if len(sys.argv) == 4 and sys.argv[2] == "--verify":
        p = verify(sys.argv[3], run)
        print(json.dumps({"ok": not p, "problems": p}, indent=1))
        return 0 if not p else 1
    report = {}
    for t in sorted(run.glob("episodes/*/transcript.jsonl")):
        events, refs = redact_events([l for l in t.read_text().splitlines() if l.strip()])
        t.write_text("".join(json.dumps(ev, ensure_ascii=False) + "\n" for ev in events))
        report[t.parent.name] = {"events": len(events), "tool_ids_pseudonymized": len(refs)}
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
