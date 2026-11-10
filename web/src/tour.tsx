import { useEffect } from "react";
import { ArrowLeft, ArrowRight, Check, ExternalLink, EyeOff, FileSearch, X } from "lucide-react";
import { VerdictChip } from "./components";
import { near, REPO_URL, short, type Bundle } from "./data";

const STEPS = 3;
const blob = (path: string) => `${REPO_URL}/blob/master/${path}`;

/** Guided judging tour: three claims, each with the evidence and a command to re-check it. */
export function Tour({ bundle, step }: { bundle: Bundle; step: number }) {
  const s = Math.min(Math.max(step, 1), STEPS);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest?.("input,textarea")) return;
      if (e.key === "ArrowRight" && s < STEPS) location.hash = `#/tour/${s + 1}`;
      if (e.key === "ArrowLeft" && s > 1) location.hash = `#/tour/${s - 1}`;
      if (e.key === "Escape") location.hash = "#/";
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [s]);
  const g = bundle.g2_runs?.[0];
  const r = bundle.runs[0];
  return (
    <section className="section tour" style={{ paddingTop: 36 }} aria-labelledby="tour-title">
      <div className="toolbar" style={{ marginBottom: 18 }}>
        <div className="eyebrow" style={{ margin: 0 }}>Guided tour · step {s} of {STEPS}</div>
        <ol className="dots" aria-label="Tour progress">
          {Array.from({ length: STEPS }, (_, i) => (
            <li key={i}><a href={`#/tour/${i + 1}`} aria-current={i + 1 === s ? "step" : undefined} aria-label={`Step ${i + 1}`} /></li>
          ))}
        </ol>
      </div>
      {s === 1 && g && <StepBudget bundle={bundle} />}
      {s === 2 && g && <StepWitness bundle={bundle} />}
      {s === 3 && r && <StepOmission bundle={bundle} />}
      <nav className="tour-nav" aria-label="Tour navigation">
        {s > 1 ? <a className="btn" href={`#/tour/${s - 1}`}><ArrowLeft aria-hidden /> Back</a> : <a className="btn" href="#/"><X aria-hidden /> Exit tour</a>}
        <span className="subtle" style={{ fontSize: 12.5 }}>Use ← → to move, Esc to exit</span>
        {s < STEPS ? <a className="btn primary" href={`#/tour/${s + 1}`}>Next <ArrowRight aria-hidden /></a>
          : <a className="btn primary" href="#/lab">Open the full Attack Lab <ArrowRight aria-hidden /></a>}
      </nav>
    </section>
  );
}

function Verify({ cmd, files }: { cmd: string; files: [string, string][] }) {
  return (
    <div className="verify-box">
      <div className="eyebrow" style={{ marginBottom: 8 }}>Check it yourself (no wallet, about 2 s)</div>
      <pre>{cmd}</pre>
      <div className="files">
        {files.map(([label, path]) => (
          <a key={path} href={blob(path)} target="_blank" rel="noreferrer noopener">{label} <ExternalLink size={12} aria-hidden /></a>
        ))}
      </div>
    </div>
  );
}

function StepBudget({ bundle }: { bundle: Bundle }) {
  const g = bundle.g2_runs[0];
  const P = g.protected, V = g.vulnerable, G = g.generous;
  const B = BigInt(P.budget);
  const scale = BigInt(V.delivered_principal) > B ? BigInt(V.delivered_principal) : B;
  const w = (x: string) => `${Number((BigInt(x) * 10000n) / scale) / 100}%`;
  const pAdm = P.requests.filter((q) => q.request_id !== "1" && q.decision === "Admitted").length;
  const inBudget = Number((B * 10000n) / BigInt(V.delivered_principal)) / 100;  // share of the fixture's outflow within B
  return (
    <div className="tour-step">
      <h1 id="tour-title">Eight payment requests at once. <span>A 5 NEAR budget.</span></h1>
      <p className="lede">
        A compromised agent sends eight 2 NEAR requests in parallel, each signed with a different authorized key, after one
        normal 1 NEAR payment. Same workload, same local chain, two contracts.
      </p>
      <div className="duel">
        <div className="duel-row">
          <div className="duel-label"><strong>Pursewarden vault</strong><span>charges the budget when it admits a payment</span></div>
          <div className="duel-bar"><div className="fill ok" style={{ width: w(P.ledger.C) }}>{near(P.ledger.C)} NEAR</div><div className="budget-line" style={{ left: w(P.budget) }} /></div>
          <div className="duel-result"><Check aria-hidden /> {pAdm} of 8 admitted · stops exactly at B</div>
        </div>
        <div className="duel-row">
          <div className="duel-label"><strong>Teaching fixture</strong><span>our own deliberately broken contract: counts only settled spend</span></div>
          <div className="duel-bar"><div className="fill bad" style={{ width: w(V.delivered_principal), background: `linear-gradient(90deg, var(--allow) 0 ${inBudget}%, var(--deny) ${inBudget}% 100%)` }}>{near(V.delivered_principal)} NEAR</div><div className="budget-line" style={{ left: w(V.budget) }} /></div>
          <div className="duel-result bad"><X aria-hidden /> 8 of 8 admitted · {near(V.overspend)} NEAR over budget</div>
        </div>
        <div className="duel-axis"><span>0</span><span style={{ left: w(P.budget) }}>B = {near(B)} NEAR</span></div>
      </div>
      <p className="muted" style={{ fontSize: 14, marginTop: 16 }}>
        Control: the same vault code with a 100 NEAR budget admits all eight (C = {near(G.ledger.C)} NEAR), so the harness is not
        simply rejecting payments. Amounts are delivered principal from native transfer receipts, rebuilt by the reviewer from its
        own capture of a fresh <span className="chip net">SANDBOX</span> chain ({g.node.chain_id}).
      </p>
      <Verify cmd="python3 -m unittest tests.evidence.test_g2_replay -v"
        files={[["G2 result", "docs/G2_RESULT.md"], ["Teaching fixture source", "fixtures/vulnerable-settled-only/src/lib.rs"],
          ["Run evidence", `evidence/g2-independent/${g.run_id}/run-summary.json`]]} />
    </div>
  );
}

function StepWitness({ bundle }: { bundle: Bundle }) {
  const g = bundle.g2_runs[0];
  const P = g.protected;
  const burst = P.requests.filter((q) => q.request_id !== "1");
  const hb = burst[0]?.height;
  const ht = burst.find((q) => q.transfer_height)?.transfer_height;
  const wit = P.pending_witness.filter((x) => x.witness);
  const w0 = P.pending_witness[0];
  return (
    <div className="tour-step">
      <h1 id="tour-title">Six denials while the money was <span>still in flight.</span></h1>
      <p className="lede">
        The hard case for a budget is the one a balance check misses: payments that have been approved but have not landed yet.
      </p>
      <div className="flight">
        <div className="flight-block">
          <div className="bh">block #{hb}</div>
          {burst.map((q) => (
            <div key={q.request_id} className={`ev ${q.decision === "Admitted" ? "adm" : "den"}`}>
              <span className="mono">id {q.request_id}</span>
              <span>{q.decision === "Admitted" ? "admitted" : q.reason}</span>
              <span className="subtle">{q.decision === "Admitted" ? `seq ${q.seq} · charged at admission` : `C ${near(q.charged_at_decision ?? "0")} + 2 > ${near(P.budget)}`}</span>
            </div>
          ))}
        </div>
        <div className="flight-arrow" aria-hidden>→</div>
        <div className="flight-block later">
          <div className="bh">block #{ht}</div>
          {burst.filter((q) => q.transfer_height === ht).map((q) => (
            <div key={q.request_id} className="ev xfer"><span className="mono">id {q.request_id}</span><span>2 NEAR transfer executes</span><span className="subtle">delivered</span></div>
          ))}
        </div>
      </div>
      <div className="callout ok" style={{ marginTop: 16 }}>
        <Check aria-hidden />
        <div>
          <strong>{wit.length} of {P.pending_witness.length} denials are verified witnesses.</strong> Each executed in block #{hb}. The two
          admitted transfers only executed in block #{ht}. Settled spend at that moment:{" "}
          {w0?.same_block_settlement_ambiguity ? `between ${near(w0.settled_before_denial_min)} and ${near(w0.settled_before_denial_max)}` : `exactly ${near(w0?.settled_before_denial_max ?? "0")}`} NEAR
          {w0?.same_block_settlement_ambiguity ? "" : " (no earlier admitted transfer settled in that block)"}. A settled-only check would have said yes; the vault had already charged{" "}
          {near(w0?.charged_at_decision ?? "0")} NEAR and said no. Same-block cases that can't be ordered are reported as
          ambiguous and never counted.
        </div>
      </div>
      <Verify cmd="python3 -m unittest tests.evidence.test_g2_replay.PendingWitnessLogic -v"
        files={[["Witness definition", "docs/G2_RESULT.md"], ["Verifier code", "packages/verifier/__init__.py"],
          ["Independent review (W1)", "reports/G2_CODEX_POSTFIX_REVIEW_2026-11-10.md"]]} />
    </div>
  );
}

function StepOmission({ bundle }: { bundle: Bundle }) {
  const r = bundle.runs[0];
  const om = r.omission.omitted_tx_hash[0];
  const rec = r.omission.recovered_payment[0];
  const roots = r.timeline.filter((t) => t.signer === r.policy.agent);
  return (
    <div className="tour-step">
      <h1 id="tour-title">The operator hides a payment. <span>The verifier finds it.</span></h1>
      <p className="lede">
        In this test the orchestrator plays a dishonest operator. It removes one real failed payment from its evidence bundle:
        the transaction, every receipt, the refund, the stored record and the history rows. Then it recomputes every checksum.
        The verifier is never told the transaction exists.
      </p>
      <div className="split">
        <div className="card">
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}><EyeOff size={16} aria-hidden /><h3 style={{ margin: 0 }}>Operator's bundle</h3>
            <span style={{ marginLeft: "auto" }}><VerdictChip v={r.omission.forged_verdicts.evidence} label="evidence" /></span></div>
          <ul className="rootlist">{roots.map((t) => (
            <li key={t.tx_hash} className={t.tx_hash === om ? "gone" : ""}><span>#{t.height}</span><span>{short(t.tx_hash, 6)}</span>
              <span className="lbl">{t.tx_hash === om ? "hidden" : (t.runner_intent?.label ?? t.decision).replaceAll("_", " ")}</span></li>))}</ul>
        </div>
        <div className="card">
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}><FileSearch size={16} aria-hidden /><h3 style={{ margin: 0 }}>Verifier's own chain scan</h3>
            <span style={{ marginLeft: "auto" }}><VerdictChip v={r.verdicts_live.evidence} label="evidence" /></span></div>
          <ul className="rootlist">{roots.map((t) => (
            <li key={t.tx_hash} className={t.tx_hash === om ? "found" : ""}><span>#{t.height}</span><span>{short(t.tx_hash, 6)}</span>
              <span className="lbl">{t.tx_hash === om ? "recovered" : (t.runner_intent?.label ?? t.decision).replaceAll("_", " ")}</span></li>))}</ul>
        </div>
      </div>
      {rec && <div className="callout ok" style={{ marginTop: 16 }}><Check aria-hidden /><div>
        Recovered from the reviewer's own block and chunk scan: {near(rec.amount)} NEAR to <code>{rec.recipient}</code>,
        transfer failed ({rec.native_failure}), and its system refund. {r.omission.recovered_receipts.length} receipts in all.
        The forged bundle gets <strong>evidence FAIL</strong>. Separately, 18 deliberate test tamperings of the genuine data
        are all rejected.</div></div>}
      <Verify cmd={"python3 -m unittest tests.evidence.test_real_rpc -v   # replays real recorded RPC: omission recovery + 18 tamperings"}
        files={[["Forged-bundle comparison", r.sources.compare_forged], ["G1 result", "docs/G1_INDEPENDENT_RESULT.md"],
          ["Raw RPC capture", r.sources.raw_rpc]]} />
      {bundle.testnet_runs?.[0] && <p className="muted" style={{ marginTop: 18 }}>
        All three steps ran on local sandboxes. The same contract also ran a narrow smoke test on public testnet, with explorer links:{" "}
        <a href="#/testnet">see the testnet proof</a>.</p>}
    </div>
  );
}
