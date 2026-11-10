// Types for web/public/bundle.json (built by scripts/build_web_bundle.py from committed evidence).
export type Verdict = "PASS" | "FAIL" | "INCONCLUSIVE";

export interface Receipt {
  id: string; parent: string | null; kind: string; predecessor: string; receiver: string;
  actions: string[]; status: { kind: "Success" | "Failure"; detail?: string }; block_height: number; event: string | null;
}
export interface TimelineItem {
  tx_hash: string; height: number; signer: string; receiver: string; source: string;
  tree: { tx_hash: string; signer: string; receiver: string; included_height: number; receipts: Receipt[] };
  runner_intent?: { label: string; intent: string; expected: string; source: string };
  method?: string; args?: Record<string, unknown>; args_raw?: string;
  decision: "Admitted" | "Denied" | "ReceiptFailure" | "Frozen" | "Construction" | "Setup";
  reason?: string; request_id?: string; amount?: string; recipient?: string; settlement?: "S" | "F";
  native_failure?: string | null; admission_seq?: string; callback?: string; principal_refund?: string | null; seq?: string;
}
export interface Run {
  run_id: string; mode: "REPLAY"; network: "SANDBOX"; captured_at: string | null; repo_commit: string;
  node: { chain_id: string; genesis_block_hash: string; version: { version: string; commit: string }; protocol_version: number; binary_sha256: string };
  artifact: { wasm_sha256: string; code_hash: string; bytes: number };
  policy: { vault: string; owner: string; agent: string; recipients: string[]; budget: string; max_per_request: string;
    max_accepted_requests: number; expires_at_ns: string; policy_hash: string; chain_id: string; agent_keys: number; vault_keys: number };
  window: { h0: { hash: string; height: number }; q: { hash: string; height: number } };
  verdicts_live: Record<"safety" | "settlement" | "evidence" | "scenario_coverage", Verdict>;
  frozen_at_q: boolean;
  ledger: { C: string; S: string; F: string; U: string; headroom: string; accepted_count: number };
  callback_observation: { cb_succeeded_amount: string; cb_failed_amount: string; callback_unconfirmed: string };
  events: { seq: number; event: string; receipt_id: string; block_height: number }[];
  state_history: { state_writes: number; charged_series: string[]; seq_series: number[] };
  timeline: TimelineItem[];
  offchain_rejections: { label: string; intent: string; expected: string; tx_hash: string; rpc_error: unknown; source: string; observed_by_reviewer_proxy?: boolean }[];
  isolation: { checks: Verdict; direct_node_rpc: string; forbidden_paths_visible: string[];
    admin_methods_denied: Record<string, boolean>; runner_methods_forwarded: string[]; runner_methods_denied: string[] };
  omission: { forged_verdicts: Record<string, Verdict>; omitted_tx_hash: string[]; recovered_receipts: string[];
    recovered_payment: { request_id: string; class: string; amount: string; recipient: string; native_failure: string;
      principal_refund_receipt?: string; transfer_receipt: string }[]; genuine_differences: string[] };
  mutations: { name: string; rejected: boolean; issues: string[] }[];
  retention: { all_identical: boolean; graphs_compared: number; graphs_identical: number; produced_blocks_after_q: number;
    first_final_head: number; later_final_head: number };
  replay_check: { capture_sha256: string; rpc_records: number };
  sources: Record<string, string>;
}
export interface G2Request { request_id: string; decision: "Admitted" | "Denied"; reason?: string; seq: number; height: number;
  transfer_height?: number; amount: string; settlement?: string; charged_at_decision?: string; tx_hash: string }
export interface G2Target { vault: string; budget: string; max_per_request: string; max_accepted_requests: number; agent_keys: number;
  computed_if_live: Record<string, Verdict>; verdicts_live: Record<string, Verdict>; ledger: Run["ledger"];
  requests: G2Request[]; pending_witness: { request_id: string; denial_height: number; settled_before_denial_min: string;
    settled_before_denial_max: string; same_block_settlement_ambiguity: boolean;
    charged_at_decision: string; settled_only_check_would_admit: boolean | null; witness: boolean;
    pending_admitted_transfers: { request_id: string; transfer_execution_height: number }[] }[];
  replay_capture_sha256: string; rpc_records: number }
export interface G2Control { label: string; vault: string; budget: string; admissions: number; denials: number;
  delivered_principal: string; overspend: string; budget_exceeded_on_chain: boolean; admissions_per_block: Record<string, number>;
  stale_settled_seen: string[]; transfers: { amount: string; outcome: string; parent_height: number; execution_height: number }[] }
export interface G2Run { run_id: string; mode: "REPLAY"; network: "SANDBOX"; repo_commit: string; node: { chain_id: string };
  isolation: { checks: Verdict }; fixture_wasm_sha256: string; protected: G2Target; generous: G2Target; vulnerable: G2Control;
  sources: Record<string, string> }
export interface TestnetStep { label: string; tx_hash: string; signer: string; receiver: string; receipts: number;
  decision?: "Admitted" | "Denied"; reason?: string; native?: "S" | "F"; native_failure?: string; principal_refund?: boolean;
  request_id?: string; amount?: string; recipient?: string }
export interface TestnetRun { run_id: string; mode: "REPLAY"; network: "TESTNET"; label: string;
  node: { chain_id: string; version: string; protocol_version: number }; tool_commit: string; artifact_sha256: string;
  accounts: { owner: string; vault: string; agent: string; payee: string; missing: string; attacker: string };
  policy: { budget: string; max_per_request: string; max_accepted_requests: number; recipients: string[]; expires_at_ns: string; policy_hash: string };
  cut: { q_height: number; q_hash: string; code_sha256: string; vault_keys: number; policy_hash: string; charged: string;
    accepted_count: number; seq: number; frozen: boolean };
  ledger: { C: string; sum_records: string; headroom: string; S: string; F: string; U: string };
  agent_keys: number; steps: TestnetStep[]; rpc_records: number;
  owner_spend: { source: string; total: string; transfers: string; gas: string; cap: string };
  explorer: string; sources: Record<string, string> }
export interface Bundle { schema: string; note: string; runs: Run[]; g2_runs: G2Run[]; testnet_runs?: TestnetRun[] }

export const REPO_URL = "https://github.com/mickeyjoes/near-agent-vault-lab";
export const YOCTO = 10n ** 24n;

export function near(yocto: string | bigint, digits = 2): string {
  const v = typeof yocto === "bigint" ? yocto : BigInt(yocto);
  const whole = v / YOCTO;
  const frac = v % YOCTO;
  if (frac === 0n) return `${whole}`;
  const fs = frac.toString().padStart(24, "0");
  const trimmed = fs.replace(/0+$/, "");
  // Exact: never round an amount that a check depends on (e.g. M + 1 yoctoNEAR).
  return `${whole}.${trimmed.length < digits ? trimmed.padEnd(digits, "0") : trimmed}`;
}
const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
/** Base58 (32-byte NEAR hash) to lowercase hex. */
export function b58ToHex(s: string): string {
  let n = 0n;
  for (const c of s) {
    const i = B58.indexOf(c);
    if (i < 0) throw new Error("not base58");
    n = n * 58n + BigInt(i);
  }
  return n.toString(16).padStart(64, "0");
}
export const nsToUtc = (ns: string) => new Date(Number(BigInt(ns) / 1000000n)).toISOString().replace("T", " ").slice(0, 16) + " UTC";
export const short = (h: string, n = 6) => (h.length > 2 * n + 1 ? `${h.slice(0, n)}…${h.slice(-n)}` : h);
export const ratio = (a: string, b: string) => Number((BigInt(a) * 10000n) / BigInt(b)) / 100;

export const REASON_TEXT: Record<string, string> = {
  DuplicateRequest: "This request ID was already admitted. Retained IDs can never be paid twice.",
  AboveMaxPerRequest: "The amount is above the per-request cap M.",
  RecipientNotAllowed: "The recipient is not on the mandate's allowlist.",
  RecordQuotaExhausted: "All K accepted-request slots are used. The refund did not give any back.",
  BudgetExceeded: "C + amount would exceed the fixed budget B.",
  MalformedInput: "Non-canonical input. The receipt failed before admission and committed no vault data (gas and nonce are still spent).",
  PolicyMismatch: "The request names a different mandate.",
  Frozen: "The owner froze the vault.",
};

export async function loadBundle(): Promise<Bundle> {
  const r = await fetch("./bundle.json", { cache: "no-store" });
  if (!r.ok) throw new Error(`bundle.json: HTTP ${r.status}`);
  return r.json();
}
