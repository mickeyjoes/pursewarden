import { useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, ArrowRight, Ban, Check, EyeOff, FileSearch, KeyRound, Lock, Server, ShieldOff, Wallet, X } from "lucide-react";
import { AuthorityBar, DecisionLabel, Drawer, VerdictChip } from "./components";
import { near, REPO_URL, short, REASON_TEXT, type Bundle, type G2Target, type Run, type TimelineItem } from "./data";
import { TestnetTeaser } from "./testnet";

/* ------------------------------------------------------------------ Landing */
export function Landing({ bundle }: { bundle: Bundle }) {
  const run = bundle.runs[0];
  const denials = run.timeline.filter((t) => t.decision === "Denied").length;
  const failedCalls = run.timeline.filter((t) => t.decision === "ReceiptFailure").length;
  return (
    <>
      <section className="hero">
        <div>
          <div className="eyebrow">AI Security &amp; Defense · NEAR</div>
          <h1>Your agent can spend.<br /><span>It can't overspend.</span></h1>
          <p className="lede">
            Pursewarden gives an AI agent a NEAR vault with one fixed, non-refillable budget. Each payment is charged
            before it is sent, and a failed payment still counts. The agent only ever holds a key that can ask.
            An independent verifier rebuilds every effect from the chain, so the agent's own report doesn't have to be trusted.
          </p>
          <p className="qualifier"><AlertTriangle aria-hidden />
            Experimental prototype. The main evidence comes from a local NEAR sandbox and is replayed here; a narrow smoke test also
            ran on <a href="#/testnet">public testnet</a>. Not audited. Not for real custody. Mainnet is not claimed.</p>
          <div className="cta">
            <a className="btn primary" href="#/tour/1">Take the 3-step tour <ArrowRight aria-hidden /></a>
            <a className="btn" href="#/lab">Open the Attack Lab</a>
          </div>
          {bundle.g2_runs?.[0] && <ProofStrip bundle={bundle} />}
        </div>
        <div className="card" aria-label="Recorded run summary">
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
            <span className="chip replay">REPLAY</span><span className="chip net">SANDBOX</span>
            <VerdictChip v={run.verdicts_live.safety} label="safety" />
          </div>
          <div className="grid2" style={{ gap: 18 }}>
            <div className="stat"><span className="v">{near(run.policy.budget)} N</span><span className="l">fixed budget B</span></div>
            <div className="stat"><span className="v">{near(run.ledger.C)} N</span><span className="l">charged C (never decreases)</span></div>
            <div className="stat"><span className="v">{run.ledger.accepted_count}</span><span className="l">payments admitted</span></div>
            <div className="stat"><span className="v">{denials + failedCalls + run.offchain_rejections.length}</span><span className="l">rejected probes: {denials} denied on chain · {failedCalls} receipt failure · {run.offchain_rejections.length} refused before inclusion</span></div>
          </div>
          <div style={{ marginTop: 20 }}><AuthorityBar run={run} /></div>
          <p className="subtle" style={{ fontSize: 12.5, marginTop: 14 }}>
            Run <code>{run.run_id}</code> on a fresh sandbox chain <code>{run.node.chain_id}</code>. Repeated on {bundle.runs.length - 1} more fresh node{bundle.runs.length > 2 ? "s" : ""} with the same results.
          </p>
        </div>
      </section>

      <section className="section" aria-labelledby="how">
        <div className="eyebrow">How it works</div>
        <h2 id="how" style={{ fontSize: 30, marginBottom: 24 }}>Three accounts. Only one can move money, and it has no keys.</h2>
        <div className="grid3">
          <div className="card"><h3><KeyRound size={16} style={{ verticalAlign: -3 }} /> Owner</h3>
            <p className="muted">Creates the vault once with an immutable mandate: budget B, per-request cap M, an allowlist, an expiry and at most K payments. The owner can freeze the vault and can never raise the budget.</p></div>
          <div className="card"><h3><Lock size={16} style={{ verticalAlign: -3 }} /> Vault</h3>
            <p className="muted">A NEAR contract account created <strong>keyless</strong> in one batch. It has no withdraw, upgrade or key-adding code path. It charges C before it sends, so a refund never restores authority.</p></div>
          <div className="card"><h3><Wallet size={16} style={{ verticalAlign: -3 }} /> Agent</h3>
            <p className="muted">Holds only function-call keys that can call <code>request_payment</code> on the vault with zero deposit. It cannot transfer, deploy, add keys or call anything else.</p></div>
        </div>
      </section>

      <section className="section" aria-labelledby="proof">
        <div className="eyebrow">What the recorded run shows</div>
        <h2 id="proof" style={{ fontSize: 30, marginBottom: 24 }}>One run, end to end</h2>
        <div className="flow">
          <div><span className="n">01</span><h3>A normal payment</h3><p>1 NEAR to an allowlisted account. Admitted, delivered. C = 1.</p></div>
          <div><span className="n">02</span><h3>A failed payment still counts</h3><p>2 NEAR to an allowlisted account that doesn't exist. The transfer fails and the 2 NEAR is refunded. C = 3 anyway.</p></div>
          <div><span className="n">03</span><h3>The agent attacks</h3><p>A replay, a cap overrun, an exfiltration, reuse of the refund, malformed input and four key abuses. All are stopped.</p></div>
          <div><span className="n">04</span><h3>A dishonest report is caught</h3><p>A test plays a lying operator whose evidence bundle silently drops the failed payment. The verifier finds the missing transaction on its own.</p></div>
        </div>
      </section>

      {bundle.g2_runs?.[0] && <BurstTeaser bundle={bundle} />}

      <TestnetTeaser bundle={bundle} />

      <section className="section claims" aria-labelledby="claims">
        <div className="eyebrow">Claims ledger</div>
        <h2 id="claims" style={{ fontSize: 30, marginBottom: 24 }}>What we claim, what we assume, what we don't</h2>
        <div className="grid3">
          <div className="card"><h3><Check aria-hidden style={{ color: "var(--allow)" }} /> Claimed (tested)</h3><ul>
            <li>Admitted principal C never exceeds B, and nothing decreases C.</li>
            <li>A failed transfer is charged (F) even though its principal is refunded.</li>
            <li>Denied requests (replay, cap, allowlist, quota) make no transfer, don't increase C and don't use up an admission slot; each denial advances the audit sequence. Malformed input commits no vault data.</li>
            <li>The vault has zero access keys from creation to cut; its code is deployed once.</li>
            <li>An independent collector recovers an omitted transaction root from its own node.</li>
            <li>Under a burst of eight concurrent requests, admissions stop exactly at B, even while earlier transfers are still pending.</li>
            <li>On public testnet, the same artifact deployed keyless and enforced its mandate across a 10-transaction smoke test (not a completeness or concurrency result).</li></ul></div>
          <div className="card"><h3><AlertTriangle aria-hidden style={{ color: "var(--pending)" }} /> Assumed</h3><ul>
            <li>The NEAR runtime executes receipts as specified.</li>
            <li>The owner sets an honest mandate and an allowlist they trust.</li>
            <li>The reviewer's node reports the chain truthfully. The verifier checks consistency, not consensus proofs.</li>
            <li>The deployed bytes match the reviewed source (checked by hash and by a reproducible rebuild).</li></ul></div>
          <div className="card"><h3><Ban aria-hidden style={{ color: "var(--deny)" }} /> Not claimed</h3><ul>
            <li>Prompt-injection defence: an agent can still waste its budget on allowlisted payees.</li>
            <li>Mainnet enforcement or production custody. On testnet, only the narrow smoke test.</li>
            <li>Audit, formal verification, recurring budgets, tokens other than NEAR.</li>
            <li>Comparisons against other projects. Our vulnerable control is our own deliberately broken fixture.</li>
            <li>Organisational independence: one team wrote the vault, runner and verifier.</li></ul></div>
        </div>
      </section>
    </>
  );
}

/* ------------------------------------------------------------------ Lab */
export function Lab({ bundle }: { bundle: Bundle }) {
  const [ri, setRi] = useState(0);
  const run = bundle.runs[ri];
  const [open, setOpen] = useState<TimelineItem | null>(null);
  const [filter, setFilter] = useState<"agent" | "all">("agent");
  const items = useMemo(() => run.timeline.filter((t) => filter === "all" || t.signer === run.policy.agent || t.method === "freeze"), [run, filter]);
  return (
    <>
      <section className="section" style={{ paddingTop: 40 }}>
        <div className="toolbar">
          <div>
            <div className="eyebrow">Attack Lab</div>
            <h1 style={{ fontSize: 34 }}>A compromised agent against a fixed mandate</h1>
          </div>
          <div className="tabs" role="group" aria-label="Select recorded run">
            {bundle.runs.map((r, i) => (
              <button key={r.run_id} aria-pressed={i === ri} onClick={() => { setRi(i); setOpen(null); }}>
                Run {runLabel(r.run_id)} · {r.node.chain_id}
              </button>
            ))}
          </div>
        </div>
        <p className="lede" style={{ marginTop: 12 }}>
          These are real transactions from a local NEAR sandbox. The workload ran inside an isolated sandbox holding only the agent's
          function-call keys. Every decision, receipt and number below comes from the reviewer's own capture.
          Select a row to see its receipts.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 16 }}>
          {Object.entries(run.verdicts_live).map(([k, v]) => <VerdictChip key={k} v={v} label={k.replace("_", " ")} />)}
          <span className="chip replay">REPLAY of recorded raw RPC</span>
        </div>
      </section>

      <section className="section" style={{ paddingTop: 28 }}>
        <div className="lab-top">
          <div className="card">
            <h3>Mandate (immutable)</h3>
            <dl className="kv">
              <dt>Budget B</dt><dd className="mono">{near(run.policy.budget)} NEAR</dd>
              <dt>Per request M</dt><dd className="mono">{near(run.policy.max_per_request)} NEAR</dd>
              <dt>Max payments K</dt><dd className="mono">{run.policy.max_accepted_requests}</dd>
              <dt>Allowlist</dt><dd>{run.policy.recipients.map((r) => <code key={r} style={{ display: "block" }}>{r}</code>)}</dd>
              <dt>Vault</dt><dd><code>{run.policy.vault}</code> · <strong style={{ color: "var(--allow)" }}>{run.policy.vault_keys} keys</strong></dd>
              <dt>Agent</dt><dd><code>{run.policy.agent}</code> · {run.policy.agent_keys} FC keys → <code>request_payment</code></dd>
              <dt>Policy hash</dt><dd className="hash">{run.policy.policy_hash}</dd>
              <dt>Code</dt><dd className="hash">sha256 {short(run.artifact.wasm_sha256, 8)}</dd>
            </dl>
          </div>
          <div className="card">
            <h3>Budget authority at the final cut Q (#{run.window.q.height})</h3>
            <AuthorityBar run={run} />
            <div className="table-wrap" style={{ marginTop: 16 }}>
              <table>
                <thead><tr><th>Quantity</th><th>Verifier (from receipts)</th><th>Meaning</th></tr></thead>
                <tbody>
                  <tr><td><strong>C</strong> charged</td><td className="mono">{near(run.ledger.C)}</td><td className="muted">Sum of admitted requests. Also equal to the contract's raw state and its view.</td></tr>
                  <tr><td><strong>S</strong> settled</td><td className="mono">{near(run.ledger.S)}</td><td className="muted">Native transfers that succeeded</td></tr>
                  <tr><td><strong>F</strong> failed</td><td className="mono">{near(run.ledger.F)}</td><td className="muted">Native transfers that failed. Principal refunded, budget still charged.</td></tr>
                  <tr><td><strong>U</strong> unresolved</td><td className="mono">{near(run.ledger.U)}</td><td className="muted">Transfers with no final outcome at Q</td></tr>
                  <tr><td><strong>B − C</strong></td><td className="mono">{near(run.ledger.headroom)}</td><td className="muted">Unused budget</td></tr>
                  <tr><td><strong>Spendable now</strong></td><td className="mono">{near(spendable(run))}</td>
                    <td className="muted">{spendableWhy(run)}</td></tr>
                </tbody>
              </table>
            </div>
            <p className="subtle" style={{ fontSize: 12.5, marginTop: 10 }}>
              C over the run: {run.state_history.charged_series.map((c) => near(c)).filter((v, i, a) => a.indexOf(v) === i).join(" → ")} NEAR,
              taken from {run.state_history.state_writes} independently decoded STATE writes. It never decreases.
            </p>
          </div>
        </div>
      </section>

      <section className="section" style={{ paddingTop: 28 }} aria-labelledby="trace">
        <div className="toolbar" style={{ marginBottom: 14 }}>
          <h2 id="trace" style={{ fontSize: 20 }}>Trace: intent → request → decision → effects</h2>
          <div className="tabs" role="group" aria-label="Filter rows">
            <button aria-pressed={filter === "agent"} onClick={() => setFilter("agent")}>Agent + freeze</button>
            <button aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All roots in window ({run.timeline.length})</button>
          </div>
        </div>
        <div className="card" style={{ padding: "14px 0 0" }}>
          <div className="lanes-head"><div>Block</div><div>Intent (runner, untrusted)</div><div>Request</div><div>Decision</div><div>Effects (verified)</div></div>
          {items.map((t) => (
            <button key={t.tx_hash} className="lane-row" aria-expanded={open?.tx_hash === t.tx_hash} onClick={() => setOpen(t)}>
              <div className="h">#{t.height}</div>
              <div>
                <div className="t">{t.runner_intent?.label.replaceAll("_", " ") ?? (t.method === "freeze" ? "owner freeze" : t.decision.toLowerCase())}</div>
                <div className="s">{t.runner_intent?.intent ?? `${t.signer} → ${t.receiver}`}</div>
              </div>
              <div>
                <div className="t mono" style={{ fontSize: 12.5 }}>{t.method ?? "—"}{t.request_id ? ` · id ${t.request_id}` : ""}</div>
                <div className="s">{t.amount ? `${near(t.amount)} NEAR → ${t.recipient}` : t.args_raw ? short(t.args_raw, 18) : short(t.tx_hash)}</div>
              </div>
              <div>
                <DecisionLabel item={t} />
                {t.reason && <div className="s mono">{t.reason}</div>}
                {t.decision === "Admitted" && <div className="s">admission seq {t.admission_seq}</div>}
              </div>
              <div className="s" style={{ marginTop: 0 }}>{effects(t)}</div>
            </button>
          ))}
        </div>
      </section>

      <section className="section" style={{ paddingTop: 28 }} aria-labelledby="offchain">
        <h2 id="offchain" style={{ fontSize: 20, marginBottom: 6 }}>Stopped before reaching the chain</h2>
        <p className="muted" style={{ marginBottom: 14, fontSize: 14 }}>
          NEAR rejected these key abuses when the agent submitted them, so they leave no chain trace. The verifier confirmed that none of
          these transactions is on chain. "Reviewer-observed" means the reviewer's filter proxy recorded the node's error itself. Runs made
          before that logging existed show the error as runner-reported.
        </p>
        <div className="grid2">
          {run.offchain_rejections.map((o) => (
            <div key={o.tx_hash} className="card" style={{ padding: 16 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                <ShieldOff size={16} style={{ color: "var(--deny)" }} aria-hidden />
                <strong>{o.label.replaceAll("_", " ")}</strong>
                {o.observed_by_reviewer_proxy
                  ? <span className="chip info" style={{ marginLeft: "auto" }}>reviewer-observed</span>
                  : <span className="chip untrusted" style={{ marginLeft: "auto" }}>runner-reported</span>}
              </div>
              <div className="muted" style={{ fontSize: 13.5 }}>{o.expected}</div>
              <code style={{ fontSize: 12, color: "var(--subtle)", overflowWrap: "anywhere" }}>{errorName(o.rpc_error)}</code>
            </div>
          ))}
        </div>
      </section>
      {open && <Drawer item={open} run={run} onClose={() => setOpen(null)} />}
    </>
  );
}

const runLabel = (id: string) => id.split("-").pop()!.toUpperCase();

/** Unused budget is not the same as spendable authority: K slots and the freeze also bind. */
function spendable(run: Run): string {
  const slotsLeft = run.policy.max_accepted_requests - run.ledger.accepted_count;
  if (run.frozen_at_q || slotsLeft <= 0) return "0";
  const h = BigInt(run.ledger.headroom), m = BigInt(run.policy.max_per_request);
  return (h < m * BigInt(slotsLeft) ? h : m * BigInt(slotsLeft)).toString();
}
function spendableWhy(run: Run): string {
  const used = `${run.ledger.accepted_count} of K = ${run.policy.max_accepted_requests} payment slots used`;
  const frozen = run.frozen_at_q ? " The vault is frozen at Q, so no new admissions are possible." : "";
  return run.ledger.accepted_count >= run.policy.max_accepted_requests
    ? `${used}, so the remaining ${near(run.ledger.headroom)} NEAR of budget cannot be spent.${frozen}`
    : `${used}.${frozen}`;
}

function effects(t: TimelineItem): string {
  if (t.decision === "Admitted") {
    return t.settlement === "S"
      ? `Transfer ${near(t.amount!)} NEAR delivered · callback ${t.callback}`
      : `Transfer failed (${t.native_failure}) · ${near(t.amount!)} NEAR system refund · still charged · callback ${t.callback}`;
  }
  if (t.decision === "Denied") return `No transfer, C unchanged, audit sequence +1 · ${REASON_TEXT[t.reason ?? ""] ?? ""}`;
  if (t.decision === "ReceiptFailure") return "Receipt failed: no transfer, no vault data committed (checked in history)";
  if (t.decision === "Frozen") return "Vault frozen: irreversible, no new admissions";
  if (t.decision === "Construction") return "Keyless creation batch: create, fund, deploy, init";
  return "Account setup";
}

function errorName(e: unknown): string {
  const s = JSON.stringify(e);
  const m = s.match(/"(MethodNameMismatch|RequiresFullAccess|DepositWithFunctionCall|ReceiverMismatch|NotEnoughAllowance)"/);
  return m ? m[1] : s.slice(0, 90);
}

/* ------------------------------------------------------------------ Verify */
export function Verify({ bundle }: { bundle: Bundle }) {
  const [ri, setRi] = useState(0);
  const run = bundle.runs[ri];
  const omitted = run.omission.omitted_tx_hash[0];
  const agentRoots = run.timeline.filter((t) => t.signer === run.policy.agent || t.receiver === run.policy.vault || t.receiver === run.policy.agent);
  const rec = run.omission.recovered_payment[0];
  return (
    <>
      <section className="section" style={{ paddingTop: 40 }}>
        <div className="toolbar">
          <div>
            <div className="eyebrow">Independent verification</div>
            <h1 style={{ fontSize: 34 }}>Don't trust the runner. Rebuild the run.</h1>
          </div>
          <div className="tabs" role="group" aria-label="Select recorded run">
            {bundle.runs.map((r, i) => (
              <button key={r.run_id} aria-pressed={i === ri} onClick={() => setRi(i)}>Run {runLabel(r.run_id)}</button>
            ))}
          </div>
        </div>
        <p className="lede" style={{ marginTop: 12 }}>
          Suppose the operator running the agent hands over an evidence bundle that looks complete and has valid checksums, but
          silently leaves out the failed 2 NEAR payment: the transaction, every receipt, the refund, the retained record and the
          history rows. Here the test orchestrator plays that dishonest operator on purpose. It builds the forged bundle from the
          runner's genuine one. It is a test of the verifier, not an observed AI attack.
          The reviewer's collector is <strong>never given that transaction hash</strong>. It walks every block and chunk from H0 to Q on its own node.
        </p>
      </section>

      <section className="section" style={{ paddingTop: 28 }}>
        <div className="split">
          <div className="card">
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
              <EyeOff size={16} aria-hidden /> <h3 style={{ margin: 0 }}>Runner's presented bundle</h3>
              <span style={{ marginLeft: "auto" }}><VerdictChip v={run.omission.forged_verdicts.evidence} label="evidence" /></span>
            </div>
            <ul className="rootlist">
              {agentRoots.map((t) => (
                <li key={t.tx_hash} className={t.tx_hash === omitted ? "gone" : ""}>
                  <span>#{t.height}</span><span>{short(t.tx_hash, 7)}</span>
                  <span className="lbl">{t.tx_hash === omitted ? "omitted by runner" : (t.runner_intent?.label ?? t.method ?? t.decision).replaceAll("_", " ")}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="card">
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
              <FileSearch size={16} aria-hidden /> <h3 style={{ margin: 0 }}>Reviewer's independent capture</h3>
              <span style={{ marginLeft: "auto" }}><VerdictChip v={run.verdicts_live.evidence} label="evidence" /></span>
            </div>
            <ul className="rootlist">
              {agentRoots.map((t) => (
                <li key={t.tx_hash} className={t.tx_hash === omitted ? "found" : ""}>
                  <span>#{t.height}</span><span>{short(t.tx_hash, 7)}</span>
                  <span className="lbl">{t.tx_hash === omitted ? "recovered from chunk scan" : (t.runner_intent?.label ?? t.method ?? t.decision).replaceAll("_", " ")}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
        {rec && (
          <div className="callout ok" style={{ marginTop: 16 }}>
            <Check aria-hidden />
            <div>
              <strong>Recovered:</strong> request <code>{rec.request_id}</code>: {near(rec.amount)} NEAR to <code>{rec.recipient}</code>,
              native transfer <strong>failed ({rec.native_failure})</strong>, principal refund receipt <code>{short(rec.principal_refund_receipt ?? "", 6)}</code>,
              {" "}{run.omission.recovered_receipts.length} receipts in all. The forged bundle gets <strong>evidence FAIL</strong> (<code>OMITTED_ROOT</code>).
              The genuine bundle matches exactly ({run.omission.genuine_differences.length} differences).
            </div>
          </div>
        )}
      </section>

      <section className="section" style={{ paddingTop: 40 }} aria-labelledby="mut">
        <h2 id="mut" style={{ fontSize: 20, marginBottom: 6 }}>{run.mutations.filter((m) => m.rejected).length} of {run.mutations.length} tamperings rejected</h2>
        <p className="muted" style={{ marginBottom: 14, fontSize: 14 }}>Each row is a deliberate tampering generated by the test suite (<code>packages/verifier/forge.py</code>). It edits the genuine recorded RPC responses, replays them, and requires the verifier to refuse a complete PASS. These are regression tests, not observed attacks.</p>
        <div className="card" style={{ padding: 0 }}>
          <div className="table-wrap"><table>
            <thead><tr><th>Tampering</th><th>Result</th><th>Verifier finding</th></tr></thead>
            <tbody>{run.mutations.map((m) => (
              <tr key={m.name}><td>{m.name.replaceAll("_", " ")}</td>
                <td>{m.rejected ? <span className="chip pass"><Check aria-hidden /> rejected</span> : <span className="chip fail"><X aria-hidden /> accepted</span>}</td>
                <td className="mono" style={{ fontSize: 12.5 }}>{m.issues.join(", ")}</td></tr>))}
            </tbody></table></div>
        </div>
      </section>

      <section className="section" style={{ paddingTop: 40 }} aria-labelledby="iso">
        <h2 id="iso" style={{ fontSize: 20, marginBottom: 14 }}>Runner isolation and retention</h2>
        <div className="grid2">
          <div className="card">
            <h3>Runner sandbox (bubblewrap, all namespaces unshared) <VerdictChip v={run.isolation.checks} /></h3>
            <dl className="kv">
              <dt>Direct node RPC</dt><dd>{run.isolation.direct_node_rpc.split(":")[0]}</dd>
              <dt>Node home / owner key</dt><dd>{run.isolation.forbidden_paths_visible.length === 0 ? "not visible" : "VISIBLE"}</dd>
              <dt>Admin RPC</dt><dd>{run.isolation.runner_methods_denied.join(", ")}: denied by the reviewer filter</dd>
              <dt>Runner used</dt><dd>{run.isolation.runner_methods_forwarded.join(", ")}</dd>
            </dl>
          </div>
          <div className="card">
            <h3>Retention re-read {run.retention.all_identical ? <span className="chip pass">identical</span> : <span className="chip fail">differs</span>}</h3>
            <dl className="kv">
              <dt>Produced blocks after Q</dt><dd className="mono">{run.retention.produced_blocks_after_q} (no fast-forward)</dd>
              <dt>Transaction graphs</dt><dd className="mono">{run.retention.graphs_identical}/{run.retention.graphs_compared} byte-identical</dd>
              <dt>Blocks, chunks, Q state, history</dt><dd>byte-identical</dd>
            </dl>
          </div>
        </div>
      </section>
    </>
  );
}

/* ------------------------------------------------------------------ Docs */
export function Docs({ bundle }: { bundle: Bundle }) {
  const run = bundle.runs[0];
  return (
    <section className="section" style={{ paddingTop: 40, maxWidth: 860 }}>
      <div className="eyebrow">Reproduce</div>
      <h1 style={{ fontSize: 34, marginBottom: 12 }}>Check it yourself</h1>
      <p className="lede">Three paths, from cheapest to strongest. None of them needs a wallet or funds. Everything runs on your machine.</p>
      {[
        ["1 · Re-verify the recorded runs (seconds, Python 3 stdlib only)",
          "python3 -m unittest discover -s tests/evidence -t .   # 70 tests: synthetic, runner-boundary, G1/G2 replay of real recorded RPC"],
        ["2 · Rebuild the contract and compare bytes",
          `scripts/build-contract.sh   # expect sha256 ${run.artifact.wasm_sha256}\ngit diff --exit-code artifacts/`],
        ["3 · Run a fresh independent G1 experiment (~5 min, Linux + bubblewrap)",
          "cargo build -p g1-sandbox-tests --locked --bin g1_actor\npython3 scripts/g1-independent/run_g1.py my-run --rpc-port 3240 --net-port 24777"],
        ["4 · Run the G2 concurrency comparison (~25 s, Linux + bubblewrap)",
          "cargo build -p g1-sandbox-tests --locked --bin g2_actor\npython3 scripts/g2-independent/run_g2.py my-g2 --rpc-port 3290 --net-port 24827"],
        ["5 · Re-inspect the public testnet smoke (read-only, needs internet)",
          "python3 scripts/testnet/https_rpc_forwarder.py --port 3399 --upstream https://rpc.testnet.near.org &\npython3 -m packages.verifier inspect-smoke --network testnet --rpc http://127.0.0.1:3399 \\\n  --run evidence/testnet-smoke/tn-20261110T195542Z/run.json --wasm artifacts/near_agent_vault.wasm --out /tmp/reinspect"],
      ].map(([t, c]) => (
        <div key={t} className="cmd" style={{ marginTop: 22 }}><h3 style={{ fontSize: 15 }}>{t}</h3><pre>{c}</pre></div>
      ))}
      <div className="callout" style={{ marginTop: 28 }}>
        <Server aria-hidden />
        <div><strong>Where things ran.</strong> The attack lab, the concurrency burst (G2), the omission recovery and the independent
          verifier (G1) all come from fresh local NEAR sandboxes (nearcore 2.13.4). A separate, owner-approved 10-transaction smoke test ran on
          <strong> public NEAR testnet</strong> (protocol 88) after a rehearsal on a local copy of testnet's version: see <a href="#/testnet">Testnet</a>.
          Nothing runs on mainnet.</div>
      </div>
      <div className="callout warn" style={{ marginTop: 12 }}>
        <AlertTriangle aria-hidden />
        <div>Trust statement: chain data was read by the reviewer from a single-validator local sandbox node it started itself. The verifier
          checks consistency, completeness within the window, and the vault's invariants. A file digest proves that a file is unchanged,
          not that NEAR consensus included it.</div>
      </div>
      <p className="muted" style={{ marginTop: 24 }}>Full documentation, the threat model and the limits are in the <a href={REPO_URL}>repository README</a>.</p>
    </section>
  );
}

/* ------------------------------------------------------------------ Burst (G2) */
export function Burst({ bundle }: { bundle: Bundle }) {
  const [ri, setRi] = useState(0);
  if (!bundle.g2_runs?.length) return <p className="muted" style={{ paddingTop: 48 }}>No G2 run recorded.</p>;
  const g = bundle.g2_runs[ri];
  const P = g.protected, V = g.vulnerable, G = g.generous;
  const burstOf = (t: G2Target) => t.requests.filter((r) => r.request_id !== "1");
  const pAdm = burstOf(P).filter((r) => r.decision === "Admitted").length;
  const gAdm = burstOf(G).filter((r) => r.decision === "Admitted").length;
  const vBurst = V.admissions - 1;  // all fixture admissions minus the initial 1 NEAR payment
  const witnesses = P.pending_witness.filter((w) => w.witness).length;
  const w0 = P.pending_witness[0];
  const burstBlock = burstOf(P)[0]?.height;
  const transferBlock = burstOf(P).find((r) => r.transfer_height)?.transfer_height;
  const vBlocks = Object.entries(V.admissions_per_block).map(([h, n]) => [Number(h), n] as const).sort((a, b) => a[0] - b[0]);
  return (
    <>
      <section className="section" style={{ paddingTop: 40 }}>
        <div className="toolbar">
          <div>
            <div className="eyebrow">G2 · concurrency</div>
            <h1 style={{ fontSize: 34 }}>Eight requests at once. One budget.</h1>
          </div>
          <div className="tabs" role="group" aria-label="Select recorded G2 run">
            {bundle.g2_runs.map((r, i) => (
              <button key={r.run_id} aria-pressed={i === ri} onClick={() => setRi(i)}>Run {runLabel(r.run_id)} · {r.node.chain_id}</button>
            ))}
          </div>
        </div>
        <p className="lede" style={{ marginTop: 12 }}>
          After one normal 1 NEAR payment, a compromised agent fires <strong>eight 2 NEAR payment requests in parallel</strong>,
          each signed with a different authorized key. The same workload runs against three targets on one fresh local chain.
          Every number below is rebuilt from the reviewer's own capture of that chain.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 16 }}>
          <span className="chip replay">REPLAY</span><span className="chip net">SANDBOX</span>
          <VerdictChip v={g.isolation.checks} label="runner isolation" />
        </div>
      </section>

      <section className="section" style={{ paddingTop: 28 }}>
        <div className="grid3">
          <BurstCard title="Protected vault" tag={<span className="chip pass"><Check aria-hidden /> C ≤ B</span>}
            admitted={pAdm} spent={P.ledger.C} budget={P.budget} spentLabel="charged C"
            note={`${8 - pAdm} denied BudgetExceeded. C = ${near(P.ledger.C)} NEAR = B.`} />
          <BurstCard title="Vulnerable teaching fixture" tag={<span className="chip fail"><X aria-hidden /> overspent</span>}
            admitted={vBurst} spent={V.delivered_principal} budget={V.budget} spentLabel="delivered"
            note={`${near(V.overspend)} NEAR over budget. It checks only settled spend: our own deliberately broken contract, sandbox only.`} />
          <BurstCard title="Generous control" tag={<span className="chip info">B = {near(G.budget)}</span>}
            admitted={gAdm} spent={G.ledger.C} budget={G.budget} spentLabel="charged C"
            note="Same vault code with a large budget: all eight admitted. The harness does admit when the budget allows." />
        </div>
      </section>

      <section className="section" style={{ paddingTop: 36 }} aria-labelledby="blocks">
        <h2 id="blocks" style={{ fontSize: 20, marginBottom: 6 }}>Protected vault, block by block</h2>
        <p className="muted" style={{ fontSize: 14, marginBottom: 14 }}>
          NEAR executes the vault's receipts one at a time. In these runs, each transfer the vault scheduled ran in the next block.
        </p>
        <div className="blocks">
          {[...new Set(P.requests.flatMap((r) => [r.height, r.transfer_height]).filter(Boolean) as number[])].sort((a, b) => a - b).map((h) => (
            <div key={h} className={`block ${h === burstBlock ? "hot" : ""}`}>
              <div className="bh">block #{h}</div>
              {P.requests.filter((r) => r.height === h).map((r) => (
                <div key={`d${r.request_id}`} className={`ev ${r.decision === "Admitted" ? "adm" : "den"}`}>
                  <span className="mono">id {r.request_id}</span>
                  <span>{r.decision === "Admitted" ? <><Check size={13} aria-hidden /> admitted</> : <><X size={13} aria-hidden /> {r.reason}</>}</span>
                  <span className="subtle">{r.decision === "Denied" ? `C ${near(r.charged_at_decision ?? "0")} + 2 > ${near(P.budget)}` : `seq ${r.seq}`}</span>
                </div>
              ))}
              {P.requests.filter((r) => r.transfer_height === h).map((r) => (
                <div key={`t${r.request_id}`} className="ev xfer">
                  <span className="mono">id {r.request_id}</span><span>transfer {near(r.amount)} NEAR executes</span><span className="subtle">{r.settlement === "S" ? "delivered" : "failed"}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
        {w0 && (
          <div className="callout ok" style={{ marginTop: 16 }}>
            <Check aria-hidden />
            <div>
              <strong>Native-pending witness ({witnesses} of {P.pending_witness.length} denials).</strong> Every BudgetExceeded denial executed in
              block #{burstBlock}, while the two admitted transfers were still unexecuted: they ran in block #{transferBlock}.
              At that moment only {near(w0.settled_before_denial_max)} NEAR had settled
              {w0.same_block_settlement_ambiguity ? " (at most)" : ". No earlier admitted transfer settled in the denials' block, so that amount is exact"}.
              A check that counts only settled spend would therefore have admitted every witnessed denial. The vault counts
              admitted principal instead, so C was already {near(w0.charged_at_decision)} NEAR.
              {P.pending_witness.some((w) => w.same_block_settlement_ambiguity) && " Some denials share a block with another settlement; those are not counted as witnesses."}
            </div>
          </div>
        )}
      </section>

      <section className="section" style={{ paddingTop: 36 }} aria-labelledby="vuln">
        <h2 id="vuln" style={{ fontSize: 20, marginBottom: 6 }}>What a settled-only check does under the same burst</h2>
        <div className="blocks">
          {[...new Set([...vBlocks.map(([h]) => h), ...V.transfers.map((t) => t.execution_height)])].sort((a, b) => a - b).map((h) => {
            const n = vBlocks.find(([bh]) => bh === h)?.[1] ?? 0;
            const ts = V.transfers.filter((t) => t.execution_height === h);
            return (
              <div key={h} className={`block ${n > 1 ? "hot bad" : ""}`}>
                <div className="bh">block #{h}</div>
                {n > 0 && <div className="ev adm"><span className="mono">{n}×</span><span>admitted</span>
                  <span className="subtle">settled seen: {n > 1 ? near(V.stale_settled_seen[V.stale_settled_seen.length - 1]) : "0"} NEAR</span></div>}
                {ts.length > 0 && <div className="ev xfer"><span className="mono">{ts.length}×</span><span>transfers delivered</span>
                  <span className="subtle">{near(ts.reduce((a, t) => a + BigInt(t.amount), 0n))} NEAR</span></div>}
              </div>
            );
          })}
        </div>
        <p className="subtle" style={{ fontSize: 12.5, marginTop: 12 }}>
          The fixture (<code>{g.sources.fixture_source}</code>, sha256 {short(g.fixture_wasm_sha256, 6)}) is a project-owned teaching contract
          used only as a negative control on the local sandbox. It does not represent any other project. Its outflows come from the
          reviewer's chunk scan and the native transfer outcomes, not from its own state.
        </p>
      </section>
    </>
  );
}

function BurstCard({ title, tag, admitted, spent, budget, spentLabel, note }:
  { title: string; tag: ReactNode; admitted: number; spent: string; budget: string; spentLabel: string; note: string }) {
  const B = BigInt(budget), S = BigInt(spent);
  const scale = S > B ? S : B;
  const pct = (x: bigint) => Number((x * 10000n) / scale) / 100;
  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}><h3 style={{ margin: 0 }}>{title}</h3><span style={{ marginLeft: "auto" }}>{tag}</span></div>
      <div className="stat"><span className="v">{admitted} of 8</span><span className="l">burst requests admitted</span></div>
      <div className="bar" style={{ marginTop: 14, height: 26 }} role="img"
        aria-label={`${spentLabel} ${near(spent)} NEAR against budget ${near(budget)} NEAR`}>
        <div className={`seg ${S > B ? "over" : "s"}`} style={{ width: `${pct(S > B ? B : S)}%` }}>{near(S > B ? B : S)}</div>
        {S > B && <div className="seg overflow" style={{ width: `${pct(S - B)}%` }}>+{near(S - B)}</div>}
      </div>
      <div className="legend"><span>{spentLabel} {near(spent)} NEAR · budget {near(budget)} NEAR</span></div>
      <p className="muted" style={{ fontSize: 13.5, marginTop: 10 }}>{note}</p>
    </div>
  );
}

function BurstTeaser({ bundle }: { bundle: Bundle }) {
  const g = bundle.g2_runs[0];
  const adm = g.protected.requests.filter((r) => r.request_id !== "1" && r.decision === "Admitted").length;
  const w = g.protected.pending_witness.filter((x) => x.witness).length;
  return (
    <section className="section" aria-labelledby="burst-teaser">
      <div className="eyebrow">Concurrency (G2)</div>
      <h2 id="burst-teaser" style={{ fontSize: 30, marginBottom: 24 }}>Eight requests at once, one budget</h2>
      <div className="grid3">
        <div className="card"><div className="stat"><span className="v">{adm} of 8</span><span className="l">admitted by the protected vault: C = {near(g.protected.ledger.C)} NEAR = B</span></div></div>
        <div className="card"><div className="stat"><span className="v">{w} of {g.protected.pending_witness.length}</span><span className="l">denials executed while admitted transfers were still pending</span></div></div>
        <div className="card"><div className="stat"><span className="v" style={{ color: "var(--deny)" }}>+{near(g.vulnerable.overspend)} N</span><span className="l">overspent by our settled-only teaching fixture under the same burst</span></div></div>
      </div>
      <div className="cta"><a className="btn" href="#/burst">See the burst block by block <ArrowRight aria-hidden /></a></div>
    </section>
  );
}

function ProofStrip({ bundle }: { bundle: Bundle }) {
  const g = bundle.g2_runs[0];
  const w = g.protected.pending_witness.filter((x) => x.witness).length;
  return (
    <ul className="proof-strip" aria-label="Headline results (local sandbox)">
      <li><a href="#/tour/1"><strong>{near(g.protected.ledger.C)} vs {near(g.vulnerable.delivered_principal)} NEAR</strong><span>8 requests against a 5 NEAR budget</span></a></li>
      <li><a href="#/tour/2"><strong>{w} of {g.protected.pending_witness.length}</strong><span>denials while transfers were in flight</span></a></li>
      <li><a href="#/tour/3"><strong>1 hidden payment</strong><span>found by the verifier on its own</span></a></li>
    </ul>
  );
}
