import { useState } from "react";
import { AlertTriangle, ArrowRight, Check, ExternalLink, Globe, History, RefreshCw, X } from "lucide-react";
import { b58ToHex, near, nsToUtc, REASON_TEXT, REPO_URL, short, type Bundle, type TestnetRun, type TestnetStep } from "./data";

const blob = (p: string) => `${REPO_URL}/blob/master/${p}`;
/** Public testnet RPC endpoints, also allowed by the page's Content-Security-Policy (connect-src). The faster one is
 *  asked first. Both are run by the same operator (rpc.testnet.near.org is a CNAME to FastNear), so the second is a
 *  fallback for availability, not a second opinion. */
const RPCS = ["https://test.rpc.fastnear.com", "https://rpc.testnet.near.org"];
const PER_ENDPOINT_MS = 10000;
const N = (y: string) => `${near(y)} NEAR`;
/** Rounded display for amounts no check depends on (spend and gas). */
const approx = (y: string, d = 4) => (Number(BigInt(y) / 10n ** 16n) / 1e8).toFixed(d);
const nameOf = (t: TestnetRun, a: string) => a.replace(`.${t.accounts.owner}`, "");

const PLAN: Record<string, string> = {
  create_payee: "Create the payee with no keys, 0.1 NEAR",
  create_agent: "Create the agent with 3 keys that can only call request_payment on the vault",
  create_vault: "Create the vault keyless, deploy c7c77263, set the mandate",
  pay_1_payee: "Pay 0.4 NEAR to the payee",
  pay_2_missing: "Pay 0.4 NEAR to an allowlisted account that does not exist",
  replay_1: "Send request 1 again",
  over_cap: "Ask for 0.5 NEAR (the cap is 0.4)",
  exfiltrate: "Pay 0.4 NEAR to an account that is not on the allowlist",
  budget_exceeded: "Ask for 0.3 NEAR when 0.8 of 1 is already charged (a slot is still free)",
  freeze: "Owner freezes the vault",
};

function Observed({ s }: { s: TestnetStep }) {
  if (!s.decision) return <span className="ok-mark"><Check aria-hidden /> FINAL, effect confirmed in the final state</span>;
  if (s.decision === "Denied")
    return <span><span className="chip fail">Denied · {s.reason}</span>
      <span className="subtle" style={{ display: "block", fontSize: 12.5, marginTop: 4 }}>{s.reason ? REASON_TEXT[s.reason] : ""} No transfer.</span></span>;
  return <span><span className="chip pass">Admitted · charged {near(s.amount ?? "0")}</span>
    <span className="subtle" style={{ display: "block", fontSize: 12.5, marginTop: 4 }}>
      {s.native === "S" ? "Native transfer succeeded." :
        `Native transfer failed (${s.native_failure}).${s.principal_refund ? " Principal refunded to the vault; still charged." : ""}`}
    </span></span>;
}

interface Mandate { charged: string; headroom: string; accepted_count: number; frozen: boolean; expired: boolean; policy_hash: string;
  seq: string; budget: string; max_per_request: string; max_accepted_requests: number; allowed_recipients: string[]; expires_at_ns: string;
  owner: string; agent: string; vault: string; chain_id: string }
interface Live { endpoint: string; skipped: string[]; height: number; hash: string; at: string; amount: string; keys: number;
  /** "browser": SHA-256 of the code bytes the node returned, computed here. "node": the node's own code_hash. */
  code_sha256: string; code_source: "browser" | "node"; m: Mandate }

/** Anything the node returns is checked before it is shown; a malformed answer becomes an error message, never a blank page. */
function need(ok: unknown, what: string): asserts ok {
  if (!ok) throw new Error(`unexpected answer from the node: ${what}`);
}
const isDec = (x: unknown): x is string => typeof x === "string" && /^(0|[1-9][0-9]{0,38})$/.test(x);
const isB58 = (x: unknown): x is string => typeof x === "string" && /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(x);
const isAcct = (x: unknown): x is string => typeof x === "string" && x.length >= 2 && x.length <= 64;
const obj = (x: unknown): Record<string, unknown> => { need(x !== null && typeof x === "object" && !Array.isArray(x), "not an object"); return x as Record<string, unknown>; };

async function rpc(url: string, method: string, params: unknown, signal: AbortSignal): Promise<Record<string, unknown>> {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, signal, credentials: "omit",
    referrerPolicy: "no-referrer", body: JSON.stringify({ jsonrpc: "2.0", id: "pursewarden", method, params }) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  let j: Record<string, unknown>;
  try { j = obj(await r.json()); } catch { throw new Error(`unexpected answer from the node: ${method} is not JSON`); }
  if (j.error) {
    const e = j.error as { cause?: { name?: unknown }; name?: unknown };
    throw new Error(String(e?.cause?.name ?? e?.name ?? "RPC error").slice(0, 80));
  }
  const res = obj(j.result);
  if (res.error) throw new Error(String(res.error).slice(0, 120));
  return res;
}

function parseMandate(call: Record<string, unknown>): Mandate {
  const bytes = call.result;
  need(Array.isArray(bytes) && bytes.length < 65536 && bytes.every((b) => Number.isInteger(b) && b >= 0 && b < 256), "get_mandate bytes");
  let m: Record<string, unknown>;
  try { m = obj(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(bytes as number[])))); }
  catch { throw new Error("unexpected answer from the node: get_mandate is not JSON"); }
  for (const k of ["charged", "headroom", "budget", "max_per_request", "seq", "expires_at_ns"]) need(isDec(m[k]), `get_mandate.${k}`);
  for (const k of ["owner", "agent", "vault"]) need(isAcct(m[k]), `get_mandate.${k}`);
  need(isB58(m.policy_hash), "get_mandate.policy_hash");
  need(typeof m.chain_id === "string" && m.chain_id.length <= 64, "get_mandate.chain_id");
  need(Number.isSafeInteger(m.accepted_count) && Number.isSafeInteger(m.max_accepted_requests), "get_mandate counts");
  need(typeof m.frozen === "boolean" && typeof m.expired === "boolean", "get_mandate flags");
  need(Array.isArray(m.allowed_recipients) && m.allowed_recipients.length <= 64 && m.allowed_recipients.every(isAcct), "get_mandate.allowed_recipients");
  return m as unknown as Mandate;
}

const toHex = (buf: ArrayBuffer) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");

async function readOnce(url: string, t: TestnetRun, signal: AbortSignal): Promise<Omit<Live, "skipped">> {
  const b = await rpc(url, "block", { finality: "final" }, signal);
  const header = obj(b.header);
  need(isB58(header.hash) && Number.isSafeInteger(header.height), "block header");
  const hash = header.hash as string;
  // Every read is pinned to the same final block, and each answer must say so.
  const at = { block_id: hash };
  const v = t.accounts.vault;
  const subtle = globalThis.crypto?.subtle;
  const [acc, keys, call, code] = await Promise.all([
    rpc(url, "query", { request_type: "view_account", account_id: v, ...at }, signal),
    rpc(url, "query", { request_type: "view_access_key_list", account_id: v, ...at }, signal),
    rpc(url, "query", { request_type: "call_function", account_id: v, method_name: "get_mandate", args_base64: "e30=", ...at }, signal),
    subtle ? rpc(url, "query", { request_type: "view_code", account_id: v, ...at }, signal) : Promise.resolve(null)]);
  for (const [name, r] of [["view_account", acc], ["view_access_key_list", keys], ["get_mandate", call], ["view_code", code]] as const)
    if (r) need(r.block_hash === hash, `${name} answered for a different block`);
  need(isB58(acc.code_hash) && isDec(acc.amount), "view_account");
  need(Array.isArray(keys.keys), "view_access_key_list");
  const m = parseMandate(call);
  let code_sha256 = b58ToHex(acc.code_hash as string);
  let code_source: Live["code_source"] = "node";
  if (subtle && code) {
    need(typeof code.code_base64 === "string" && code.code_base64.length < 8_000_000, "view_code");
    let bytes: Uint8Array;
    try { bytes = Uint8Array.from(atob(code.code_base64 as string), (c) => c.charCodeAt(0)); }
    catch { throw new Error("unexpected answer from the node: view_code is not base64"); }
    code_sha256 = toHex(await subtle.digest("SHA-256", bytes));
    code_source = "browser";
  }
  return { endpoint: url, height: header.height as number, hash, at: new Date().toISOString().slice(11, 19) + " UTC",
    code_sha256, code_source, amount: acc.amount as string, keys: (keys.keys as unknown[]).length, m };
}

async function readLive(t: TestnetRun): Promise<Live> {
  let last: unknown = null;
  const skipped: string[] = [];
  for (const url of RPCS) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), PER_ENDPOINT_MS);
    try {
      return { ...(await readOnce(url, t, ctrl.signal)), skipped };
    } catch (e) {
      last = ctrl.signal.aborted ? new Error(`no answer within ${PER_ENDPOINT_MS / 1000} s`) : e;
      skipped.push(url.replace("https://", ""));
    } finally {
      clearTimeout(timer);
    }
  }
  throw last instanceof Error ? last : new Error("unreachable");
}

const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);

function LiveViewer({ t }: { t: TestnetRun }) {
  const [live, setLive] = useState<Live | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const go = () => {
    setBusy(true); setErr(null);
    readLive(t).then((l) => setLive(l), (e) => setErr(e instanceof Error ? e.message : String(e))).finally(() => setBusy(false));
  };
  const terms: [string, boolean][] = live ? [
    ["B", live.m.budget === t.policy.budget], ["M", live.m.max_per_request === t.policy.max_per_request],
    ["K", live.m.max_accepted_requests === t.policy.max_accepted_requests],
    ["allowlist", sameList(live.m.allowed_recipients, t.policy.recipients)], ["expiry", live.m.expires_at_ns === t.policy.expires_at_ns],
    ["owner", live.m.owner === t.accounts.owner], ["agent", live.m.agent === t.accounts.agent], ["vault", live.m.vault === t.accounts.vault],
    ["chain", live.m.chain_id === t.node.chain_id]] : [];
  const termsOk = terms.filter(([, ok]) => ok).length;
  const rows: [string, string, string, boolean | null][] = live ? [
    [live.code_source === "browser" ? "Code SHA-256 (hashed in your browser)" : "Code hash (as reported by the node)",
      short(live.code_sha256, 8), short(t.artifact_sha256, 8), live.code_sha256 === t.artifact_sha256],
    ["Vault access keys", String(live.keys), String(t.cut.vault_keys), live.keys === t.cut.vault_keys],
    ["Policy hash", short(live.m.policy_hash, 8), short(t.policy.policy_hash, 8), live.m.policy_hash === t.policy.policy_hash],
    ["Mandate terms", `${termsOk} of ${terms.length} equal`, terms.map(([k]) => k).join(", "), termsOk === terms.length],
    ["Charged C", N(live.m.charged), N(t.ledger.C), live.m.charged === t.ledger.C],
    ["Headroom B − C", N(live.m.headroom), N(t.ledger.headroom), live.m.headroom === t.ledger.headroom],
    ["Admitted payments", String(live.m.accepted_count), String(t.cut.accepted_count), live.m.accepted_count === t.cut.accepted_count],
    ["Audit sequence", String(live.m.seq), String(t.cut.seq), String(live.m.seq) === String(t.cut.seq)],
    ["Frozen", String(live.m.frozen), String(t.cut.frozen), live.m.frozen === t.cut.frozen],
    ["Vault balance", N(live.amount), "", null],
    ["Expired", String(live.m.expired), `expiry ${nsToUtc(t.policy.expires_at_ns)}`, null],
  ] : [];
  const same = rows.filter((r) => r[3] !== null).every((r) => r[3]);
  return (
    <div className="card" aria-labelledby="live-title">
      <div className="live-head">
        <h3 id="live-title" style={{ margin: 0 }}>Live state viewer</h3>
        {live && <span className="chip live"><Globe aria-hidden /> LIVE · block #{live.height}</span>}
        <button className="btn" onClick={go} disabled={busy} aria-describedby="live-note">
          <RefreshCw aria-hidden className={busy ? "spin" : undefined} /> {busy ? "Reading…" : live ? "Refresh" : "Read live from testnet"}
        </button>
      </div>
      <p id="live-note" className="muted" style={{ fontSize: 13.5, marginTop: 0 }}>
        Your browser asks a public testnet RPC node for the vault's current state, hashes the deployed code itself, and compares
        the answers with the recorded inspection. Read-only: no wallet, no signing, nothing sent from this page except these queries.
      </p>
      {err && <div className="callout bad" style={{ marginTop: 8 }}><AlertTriangle aria-hidden /><div>
        Could not read public testnet ({err}). The recorded evidence on this page does not depend on this check.</div></div>}
      {live && (
        <>
          <div className="table-scroll"><table className="tn-table" aria-label="Live versus recorded vault state">
            <thead><tr><th>Field</th><th>Live now</th><th>Recorded</th><th>Same</th></tr></thead>
            <tbody>{rows.map(([k, a, b, ok]) => (
              <tr key={k}><td>{k}</td><td><code>{a}</code></td><td><code>{b}</code></td>
                <td>{ok === null ? <span className="subtle">info</span> : ok ? <span className="ok-mark"><Check aria-hidden /> yes</span>
                  : <span className="bad-mark"><X aria-hidden /> differs</span>}</td></tr>))}</tbody>
          </table></div>
          <p className="subtle" style={{ fontSize: 12.5, marginTop: 10 }}>
            {same ? `All ${rows.filter((r) => r[3] !== null).length} compared fields match the recorded inspection` : "Some fields differ from the recorded inspection"},
            as reported by <code>{live.endpoint.replace("https://", "")}</code>
            {live.skipped.length > 0 && <> (after <code>{live.skipped.join(", ")}</code> did not answer)</>} for final block <code>{short(live.hash, 6)}</code>, read at {live.at}.
          </p>
          <p className="subtle" style={{ fontSize: 12.5, marginTop: 6 }}>
            {live.code_source === "browser" ? "The code hash is computed here from the bytes the node returned; every other value is the node's answer. "
              : "Your browser cannot hash here, so the code hash is the node's own report. "}
            Both endpoints this page uses are run by the same operator, so a fallback is not a second opinion. Zero keys now does not prove
            the vault was always keyless; that rests on its creation transaction above, which the inspector checks is exactly the approved
            four actions. Frozen and keyless, the charge, records and mandate can no longer change; the agent's keys can still send
            requests, which are denied and only advance the audit sequence. The expiry only marks the mandate as expired.
          </p>
        </>
      )}
    </div>
  );
}

export function Testnet({ bundle }: { bundle: Bundle }) {
  const t = bundle.testnet_runs?.[0];
  if (!t) return <section className="section"><p className="muted">No testnet run in this bundle.</p></section>;
  const ex = (h: string) => `${t.explorer}/txns/${h}`;
  const acct = (a: string) => `${t.explorer}/address/${a}`;
  const decided = t.steps.filter((s) => s.decision);
  const B = BigInt(t.policy.budget);
  const pct = (x: string) => Number((BigInt(x) * 10000n) / B) / 100;
  return (
    <>
      <section className="section tn-hero" aria-labelledby="tn-title">
        <div className="eyebrow">Public testnet proof</div>
        <h1 id="tn-title">The same contract, <span>on public NEAR testnet.</span></h1>
        <p className="lede">
          We deployed the exact protected artifact to public testnet and ran a short, owner-approved smoke test: one payment that
          lands, one that fails and is refunded, four requests the vault must refuse, and a freeze. Every transaction is public.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <span className="chip testnet"><Globe aria-hidden /> TESTNET</span>
          <span className="chip replay" title="The inspection on this page is re-derived by replaying the recorded RPC responses"><History aria-hidden /> REPLAY · {t.rpc_records} RPC responses</span>
          <span className="chip pass"><Check aria-hidden /> inspection PASS</span>
        </div>
        <div className="callout warn" style={{ marginTop: 20 }}>
          <AlertTriangle aria-hidden />
          <div><strong>What this does and doesn't show.</strong> It shows that artifact <code>c7c77263…</code> deploys keyless on public testnet
            (its creation transaction is exactly the four approved actions) and enforces its mandate in these {t.steps.length} transactions. It is <strong>not</strong> an independent completeness proof: the
            transaction list comes from our runner, and a public node gives no reviewer-owned frontier. It is <strong>not</strong> a concurrency or
            adversarial-runner test either; those are the local sandbox results (<a href="#/burst">G2</a>, <a href="#/verify">G1</a>).
            Not mainnet. Not audited.</div>
        </div>
      </section>

      <section className="section" style={{ paddingTop: 28 }}>
        <div className="grid2">
          <div className="card">
            <h3>Contract identity</h3>
            <dl className="kv">
              <dt>Vault</dt><dd><a href={acct(t.accounts.vault)} target="_blank" rel="noreferrer noopener"><code>{t.accounts.vault}</code> <ExternalLink size={12} aria-hidden /></a></dd>
              <dt>Code SHA-256</dt><dd><code title={t.cut.code_sha256}>{short(t.cut.code_sha256, 10)}</code>{" "}
                {t.cut.code_sha256 === t.artifact_sha256 && <span className="ok-mark"><Check aria-hidden /> = reviewed artifact</span>}</dd>
              <dt>Access keys</dt><dd><strong>{t.cut.vault_keys}</strong> <span className="subtle">at the inspected block</span></dd>
              {t.construction && <><dt>Created by</dt><dd><a href={ex(t.construction.tx_hash)} target="_blank" rel="noreferrer noopener"
                aria-label="Open the vault's creation transaction in the testnet explorer"><code>{short(t.construction.tx_hash, 5)}</code> <ExternalLink size={12} aria-hidden /></a>{" "}
                <span className="ok-mark"><Check aria-hidden /> exactly {t.construction.actions.join(", ").replace("FunctionCall", "new")}; nothing else scheduled</span>
                <span className="subtle" style={{ display: "block", fontSize: 12.5 }}>Zero keys at one block is not enough on its own: an extra action in
                  the creation batch could leave a delayed key. The inspector checks this transaction.</span></dd></>}
              <dt>Policy hash</dt><dd><code title={t.policy.policy_hash}>{short(t.policy.policy_hash, 10)}</code>{" "}
                <span className="ok-mark"><Check aria-hidden /> recomputed from raw state</span></dd>
              <dt>Status</dt><dd>{t.cut.frozen ? "Frozen by the owner" : "Active"}</dd>
              <dt>Network</dt><dd><code>{t.node.chain_id}</code> · protocol {t.node.protocol_version} · nearcore {t.node.version}</dd>
              <dt>Inspected at</dt><dd>final block #{t.cut.q_height}</dd>
            </dl>
          </div>
          <div className="card">
            <h3>Mandate (immutable)</h3>
            <dl className="kv">
              <dt>Budget B</dt><dd>{N(t.policy.budget)}</dd>
              <dt>Per request M</dt><dd>{N(t.policy.max_per_request)}</dd>
              <dt>Max payments K</dt><dd>{t.policy.max_accepted_requests}</dd>
              <dt>Allowlist</dt><dd>{t.policy.recipients.map((r) => <code key={r} style={{ display: "block" }}>{r}</code>)}</dd>
              <dt>Expiry</dt><dd>{nsToUtc(t.policy.expires_at_ns)}</dd>
              <dt>Agent</dt><dd><a href={acct(t.accounts.agent)} target="_blank" rel="noreferrer noopener"><code>{nameOf(t, t.accounts.agent)}</code></a>{" "}
                <span className="subtle">{t.agent_keys} keys, request_payment only</span></dd>
              <dt>Owner</dt><dd><a href={acct(t.accounts.owner)} target="_blank" rel="noreferrer noopener"><code>{t.accounts.owner}</code></a></dd>
            </dl>
          </div>
        </div>
        <div className="card" style={{ marginTop: 16 }}>
          <h3>Ledger at the inspected block</h3>
          <div className="bar" role="img" aria-label={`Budget ${N(t.policy.budget)}: settled ${N(t.ledger.S)}, failed but charged ${N(t.ledger.F)}, headroom ${N(t.ledger.headroom)}`}>
            {BigInt(t.ledger.S) > 0n && <div className="seg s" style={{ width: `${pct(t.ledger.S)}%` }}>{near(t.ledger.S)} N</div>}
            {BigInt(t.ledger.F) > 0n && <div className="seg f" style={{ width: `${pct(t.ledger.F)}%` }}>{near(t.ledger.F)} N</div>}
            {BigInt(t.ledger.headroom) > 0n && <div className="seg h" style={{ width: `${pct(t.ledger.headroom)}%` }}>{near(t.ledger.headroom)} N</div>}
          </div>
          <div className="legend">
            <span><i style={{ background: "var(--allow)" }} />S: delivered</span>
            <span><i style={{ background: "repeating-linear-gradient(135deg,var(--failed-seg) 0 3px,transparent 3px 6px)" }} />F: failed, refunded, still charged</span>
            <span><i style={{ border: "1px solid var(--hairline)" }} />Headroom = B − C</span>
          </div>
          <p className="muted" style={{ fontSize: 13.5, marginTop: 10 }}>
            C = {N(t.ledger.C)} = the sum of the {t.cut.accepted_count} admission records. The failed payment's refund came back to the vault
            but did not restore C, so the 0.3 NEAR request was refused even though a payment slot was still free.
          </p>
        </div>
      </section>

      <section className="section" style={{ paddingTop: 28 }} aria-labelledby="tn-tx">
        <h2 id="tn-tx" style={{ fontSize: 20, marginBottom: 6 }}>{t.steps.length} public transactions, {decided.length} vault decisions, all as planned</h2>
        <p className="muted" style={{ marginBottom: 14 }}>Each row was re-read from the public node by the inspector. Open any hash in the explorer.</p>
        <div className="card" style={{ padding: 0 }}>
          <div className="table-scroll"><table className="tn-table">
            <thead><tr><th>#</th><th>Planned</th><th>Observed</th><th>Transaction</th></tr></thead>
            <tbody>{t.steps.map((s, i) => (
              <tr key={s.tx_hash}>
                <td className="n">{i + 1}</td>
                <td>{PLAN[s.label] ?? s.label}<span className="subtle" style={{ display: "block", fontSize: 12.5 }}>{nameOf(t, s.signer)} → {nameOf(t, s.receiver)}</span></td>
                <td><Observed s={s} /></td>
                <td><a href={ex(s.tx_hash)} target="_blank" rel="noreferrer noopener" aria-label={`Open transaction ${i + 1} in the testnet explorer`}>
                  {short(s.tx_hash, 5)} <ExternalLink size={12} aria-hidden /></a></td>
              </tr>))}</tbody>
          </table></div>
        </div>
      </section>

      <section className="section" style={{ paddingTop: 28 }}>
        <LiveViewer t={t} />
      </section>

      <section className="section" style={{ paddingTop: 28 }} aria-labelledby="tn-check">
        <h2 id="tn-check" style={{ fontSize: 20, marginBottom: 14 }}>Check it yourself</h2>
        <div className="verify-box">
          <div className="eyebrow" style={{ marginBottom: 8 }}>Replay the recorded inspection (offline, Python 3 stdlib)</div>
          <pre>python3 scripts/build_web_bundle.py   # replays {t.rpc_records} recorded testnet RPC responses through the inspector; asserts PASS</pre>
          <div className="eyebrow" style={{ margin: "14px 0 8px" }}>Re-inspect against public testnet (read-only)</div>
          <pre>{`python3 scripts/testnet/https_rpc_forwarder.py --port 3399 --upstream https://rpc.testnet.near.org &
python3 -m packages.verifier inspect-smoke --network testnet --rpc http://127.0.0.1:3399 \\
  --run ${t.sources.run} --wasm artifacts/near_agent_vault.wasm --out /tmp/reinspect`}</pre>
          <div className="files">
            <a href={blob(t.sources.readme)} target="_blank" rel="noreferrer noopener">Run report <ExternalLink size={12} aria-hidden /></a>
            <a href={blob(t.sources.inspection)} target="_blank" rel="noreferrer noopener">Inspection <ExternalLink size={12} aria-hidden /></a>
            <a href={blob("docs/TESTNET_SMOKE_PLAN.md")} target="_blank" rel="noreferrer noopener">Approved plan <ExternalLink size={12} aria-hidden /></a>
            <a href={acct(t.accounts.vault)} target="_blank" rel="noreferrer noopener">Vault in explorer <ExternalLink size={12} aria-hidden /></a>
          </div>
        </div>
        <p className="subtle" style={{ fontSize: 12.5, marginTop: 12 }}>
          Run <code>{t.run_id}</code> by tool commit <code>{t.tool_commit.slice(0, 7)}</code>. The owner spent about {approx(t.owner_spend.total)} testnet NEAR
          ({near(t.owner_spend.transfers)} sent plus about {approx(t.owner_spend.gas)} gas) under an approved cap of {near(t.owner_spend.cap)}. None of it can be
          withdrawn, by design. Explorer: testnet.nearblocks.io.
        </p>
        <div className="cta"><a className="btn" href="#/tour/1">Back to the guided tour <ArrowRight aria-hidden /></a></div>
      </section>
    </>
  );
}

export function TestnetTeaser({ bundle }: { bundle: Bundle }) {
  const t = bundle.testnet_runs?.[0];
  if (!t) return null;
  const denied = t.steps.filter((s) => s.decision === "Denied").length;
  return (
    <section className="section" aria-labelledby="tn-teaser">
      <div className="eyebrow">Public testnet</div>
      <h2 id="tn-teaser" style={{ fontSize: 30, marginBottom: 24 }}>Also deployed on public NEAR testnet</h2>
      <div className="grid3">
        <div className="card"><div className="stat"><span className="v">0 keys</span><span className="l">on <code>{t.accounts.vault}</code>, running artifact <code>{t.artifact_sha256.slice(0, 8)}</code></span></div></div>
        <div className="card"><div className="stat"><span className="v">{denied} of {denied} refused</span><span className="l">replay, cap, allowlist and budget, each a public transaction</span></div></div>
        <div className="card"><div className="stat"><span className="v">{near(t.ledger.C)} of {near(t.policy.budget)} N</span><span className="l">charged, including a failed payment whose refund did not restore authority</span></div></div>
      </div>
      <p className="subtle" style={{ fontSize: 12.5, marginTop: 12 }}>A narrow smoke test with explorer links, not a completeness or concurrency result.</p>
      <div className="cta"><a className="btn" href="#/testnet">See the testnet proof <ArrowRight aria-hidden /></a></div>
    </section>
  );
}
