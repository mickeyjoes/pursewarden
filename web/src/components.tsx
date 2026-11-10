import { useEffect, useRef } from "react";
import { AlertTriangle, Check, CircleDot, History, Server, X, XCircle } from "lucide-react";
import { near, short, type Receipt, type Run, type TimelineItem, type Verdict, REASON_TEXT } from "./data";

export function VerdictChip({ v, label }: { v: Verdict; label?: string }) {
  const cls = v === "PASS" ? "pass" : v === "FAIL" ? "fail" : "inconclusive";
  const Icon = v === "PASS" ? Check : v === "FAIL" ? XCircle : AlertTriangle;
  return (
    <span className={`chip ${cls}`}>
      <Icon aria-hidden /> {label ? `${label}: ` : ""}{v}
    </span>
  );
}

export function ProvenanceBar({ run }: { run: Run | null }) {
  return (
    <div className="provenance" role="region" aria-label="Data provenance">
      <div className="provenance-inner">
        <span className="chip replay" title="Recorded run, replayed from committed raw RPC responses. Not live.">
          <History aria-hidden /> REPLAY
        </span>
        <span className="chip net" title="Local reviewer-owned nearcore sandbox. Not testnet or mainnet.">
          <Server aria-hidden /> SANDBOX
        </span>
        {run ? (
          <>
            <span>run <code>{run.run_id}</code></span>
            <span>chain <code>{run.node.chain_id}</code></span>
            <span>nearcore {run.node.version.version}</span>
            <span>window H0 #{run.window.h0.height} → Q #{run.window.q.height}</span>
            <span title={run.replay_check.capture_sha256}>capture <code>{short(run.replay_check.capture_sha256, 5)}</code></span>
          </>
        ) : (
          <span>loading evidence…</span>
        )}
        <span style={{ marginLeft: "auto" }}>No wallet · no keys · read-only</span>
      </div>
    </div>
  );
}

/** S | F | U | headroom on the scale of B. Colour plus pattern plus text (WCAG 1.4.1). */
export function AuthorityBar({ run }: { run: Run }) {
  const B = BigInt(run.policy.budget);
  const pct = (x: string) => Number((BigInt(x) * 10000n) / B) / 100;
  const segs = [
    { k: "s", v: run.ledger.S, label: "S settled" },
    { k: "f", v: run.ledger.F, label: "F failed (charged)" },
    { k: "u", v: run.ledger.U, label: "U unresolved" },
    { k: "h", v: run.ledger.headroom, label: "headroom" },
  ].filter((s) => BigInt(s.v) > 0n);
  return (
    <div>
      <div className="bar" role="img"
        aria-label={`Budget ${near(B)} NEAR: settled ${near(run.ledger.S)}, failed but charged ${near(run.ledger.F)}, unresolved ${near(run.ledger.U)}, remaining authority ${near(run.ledger.headroom)}`}>
        {segs.map((s) => (
          <div key={s.k} className={`seg ${s.k}`} style={{ width: `${pct(s.v)}%` }}>
            {near(s.v)} N
          </div>
        ))}
      </div>
      <div className="legend">
        <span><i style={{ background: "var(--allow)" }} />S: delivered to recipient</span>
        <span><i style={{ background: "repeating-linear-gradient(135deg,var(--failed-seg) 0 3px,transparent 3px 6px)" }} />F: transfer failed, refunded, still charged</span>
        <span><i style={{ background: "repeating-linear-gradient(90deg,var(--pending) 0 2px,transparent 2px 4px)" }} />U: unresolved</span>
        <span><i style={{ border: "1px solid var(--hairline)" }} />Headroom = B − C</span>
      </div>
    </div>
  );
}

export function DecisionLabel({ item }: { item: TimelineItem }) {
  switch (item.decision) {
    case "Admitted":
      return <span className="dec admit"><Check aria-hidden /> ADMITTED</span>;
    case "Denied":
      return <span className="dec deny"><X aria-hidden /> DENIED</span>;
    case "ReceiptFailure":
      return <span className="dec fail"><AlertTriangle aria-hidden /> RECEIPT FAILED</span>;
    case "Frozen":
      return <span className="dec neutral"><CircleDot aria-hidden /> FROZEN</span>;
    default:
      return <span className="dec neutral"><CircleDot aria-hidden /> {item.decision.toUpperCase()}</span>;
  }
}

const KIND_LABEL: Record<string, string> = {
  vault_call: "vault call", transfer: "native transfer", callback: "callback (observation)",
  principal_refund: "principal refund (system)", gas_refund: "gas refund", construction: "keyless construction",
  account_setup: "account setup",
};

export function ReceiptTree({ item }: { item: TimelineItem }) {
  // Depth-first order so every receipt sits directly under its parent (e.g. a principal refund
  // under the failed transfer that caused it); siblings by block height.
  const kids = new Map<string, Receipt[]>();
  for (const r of item.tree.receipts) {
    const k = r.parent ?? item.tx_hash;
    kids.set(k, [...(kids.get(k) ?? []), r].sort((a, b) => a.block_height - b.block_height));
  }
  const ordered: { r: Receipt; d: number }[] = [];
  const walk = (id: string, d: number) => { for (const r of kids.get(id) ?? []) { ordered.push({ r, d }); walk(r.id, d + 1); } };
  walk(item.tx_hash, 0);
  const nodes = ordered.map((x) => x.r);
  const depthOf = new Map(ordered.map((x) => [x.r.id, x.d]));
  const depth = (r: Receipt) => depthOf.get(r.id) ?? 0;
  return (
    <ol className="tree" aria-label="Receipt tree">
      <li style={{ ["--depth" as string]: 0 }}>
        <div className="tk">transaction · block #{item.tree.included_height}</div>
        <div className="hash">{item.tx_hash}</div>
        <div className="subtle" style={{ fontSize: 12.5 }}>{item.signer} → {item.receiver}</div>
      </li>
      {nodes.map((r) => (
        <li key={r.id} className={`k-${r.kind} ${r.status.kind === "Failure" ? "fail" : ""}`} style={{ ["--depth" as string]: depth(r) + 1 }}>
          <div className="tk">{KIND_LABEL[r.kind] ?? r.kind} · block #{r.block_height}{r.event ? ` · event ${r.event}` : ""}</div>
          <div style={{ fontSize: 13.5 }}>
            {r.actions.join(", ")}{" "}
            {r.status.kind === "Success"
              ? <span className="chip pass" style={{ marginLeft: 4 }}>success</span>
              : <span className="chip inconclusive" style={{ marginLeft: 4 }}>failure: {r.status.detail}</span>}
          </div>
          <div className="subtle" style={{ fontSize: 12.5 }}>{r.predecessor} → {r.receiver}</div>
          <div className="hash">{r.id}</div>
        </li>
      ))}
    </ol>
  );
}

export function Drawer({ item, run, onClose }: { item: TimelineItem; run: Run; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [onClose]);
  const raw = { tx_hash: item.tx_hash, decision: item.decision, reason: item.reason, request_id: item.request_id,
    amount: item.amount, recipient: item.recipient, settlement: item.settlement, args: item.args ?? item.args_raw };
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title" tabIndex={-1} ref={ref}>
        <header>
          <div>
            <div className="eyebrow" style={{ marginBottom: 6 }}>Evidence · block #{item.height}</div>
            <h2 id="drawer-title">{item.runner_intent?.label ?? item.method ?? item.decision}</h2>
          </div>
          <button className="close" onClick={onClose} aria-label="Close evidence drawer"><X size={16} /></button>
        </header>
        <div style={{ display: "grid", gap: 16 }}>
          <div className="card" style={{ padding: 16 }}>
            <dl className="kv">
              <dt>Decision</dt><dd><DecisionLabel item={item} />{item.reason ? <> · <code>{item.reason}</code></> : null}</dd>
              {item.reason && REASON_TEXT[item.reason] && (<><dt>Meaning</dt><dd>{REASON_TEXT[item.reason]}</dd></>)}
              {item.amount && (<><dt>Request</dt><dd>ID <code>{item.request_id}</code> · {near(item.amount)} NEAR → <code>{item.recipient}</code></dd></>)}
              {item.settlement && (<><dt>Native outcome</dt><dd>{item.settlement === "S" ? "Transfer succeeded (S)" : `Transfer failed: ${item.native_failure}. ${near(item.amount ?? "0")} NEAR came back to the vault as a system refund, but C stays charged (F)`}</dd></>)}
              {item.callback && (<><dt>Callback</dt><dd>{item.callback} (recorded separately from the native outcome)</dd></>)}
              <dt>Source</dt><dd>{item.source}</dd>
            </dl>
          </div>
          {item.runner_intent && (
            <div className="callout warn">
              <AlertTriangle aria-hidden />
              <div><strong>Runner's stated intent (untrusted):</strong> {item.runner_intent.intent}. Expected: {item.runner_intent.expected}.</div>
            </div>
          )}
          <div>
            <h3 style={{ fontSize: 14, marginBottom: 8 }}>Receipt tree (from the reviewer's own capture)</h3>
            <ReceiptTree item={item} />
          </div>
          <div>
            <h3 style={{ fontSize: 14, marginBottom: 8 }}>Raw extract</h3>
            <pre className="raw">{JSON.stringify(raw, null, 2)}</pre>
          </div>
          <p className="subtle" style={{ fontSize: 12.5 }}>
            Chain data was read by the reviewer from its own sandbox node and is replayed here from{" "}
            <code>{run.sources.raw_rpc}</code>. A digest proves a file is unchanged; it is not a NEAR consensus proof.
          </p>
        </div>
      </aside>
    </>
  );
}
