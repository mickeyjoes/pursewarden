//! Pursewarden LLM-agent demo gateway. LOCAL SANDBOX ONLY.
//!
//!   pw_llm_gateway setup --rpc http://127.0.0.1:PORT --owner-key FILE --wasm FILE \
//!                        --episodes a,b,c --public-out FILE --private-dir DIR
//!   pw_llm_gateway serve --rpc http://127.0.0.1:PORT --setup FILE --episode NAME --agent-key FILE \
//!                        --socket PATH --log FILE --raw-dir DIR [--max-attempts 6]
//!
//! `setup` (owner side) creates, on a fresh local sandbox, one keyless allowlisted vendor, one
//! keyless look-alike account that is NOT allowlisted, and per episode a restricted agent (one
//! FunctionCall key: vault + `request_payment` only) and a keyless protected vault (artifact
//! c7c77263…) with B = 2 NEAR, M = 1 NEAR, K = 3, allowlist = [vendor].
//!
//! `serve` is the only process that holds an agent key. It answers one JSON line per Unix-socket
//! connection. The language model reaches it only through `mcp_server.py`, which holds no key.
//! The gateway parses strictly and bounds attempts, but applies NO spending policy of its own:
//! recipient, amount, budget and quota decisions are left to the vault on chain, so every
//! decision in the evidence is the contract's.
//!
//! Fail closed: a transaction is signed exactly once and never re-signed. If its outcome cannot
//! be established as FINAL, the session is halted and every later payment is refused.
use anyhow::{anyhow, bail, Context, Result};
use g1_sandbox_tests::*;
use near_crypto::{KeyType, SecretKey};
use near_primitives::types::AccountId;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::UnixListener;

const ARTIFACT_SHA256: &str = "c7c772635acea0938bd88450d02bcdb9215d9aa65fc407b4070459cd225dd768";
const MILLI: u128 = NEAR / 1000;
pub const BUDGET: u128 = 2 * NEAR;
pub const MAX_PER_REQUEST: u128 = NEAR;
pub const K: u32 = 3;
const PAYEE_FUNDING: u128 = NEAR;
const AGENT_FUNDING: u128 = NEAR;
const KEY_ALLOWANCE: u128 = NEAR / 4;
const RESERVE_MARGIN: u128 = 10_000_000_000_000_000_000_000;
const STATE_ENTRY_MAX: u64 = 5 + 1024 + 40;
const PER_ADMISSION: u64 = 128;
const EXPIRY_NS: u64 = 6 * 3600 * 1_000_000_000;
const MAX_LINE: u64 = 16 * 1024;
const MAX_REASON_CHARS: usize = 500;
const DEFAULT_MAX_ATTEMPTS: u32 = 6;

// ------------------------------------------------------------------------------------
// Strict parsing (pure; unit-tested below)
// ------------------------------------------------------------------------------------

/// `^(0|[1-9][0-9]{0,5})(\.[0-9]{1,24})?$` NEAR → exact yoctoNEAR. No sign, exponent,
/// whitespace, separators, units or floating point.
pub fn parse_amount_near(s: &str) -> Result<u128, String> {
    let bad = || format!("amount_near {s:?} is not a plain decimal NEAR amount like \"0.75\"");
    let (int, frac) = match s.split_once('.') {
        Some((i, f)) => (i, Some(f)),
        None => (s, None),
    };
    if int.is_empty() || int.len() > 6 || !int.bytes().all(|b| b.is_ascii_digit()) {
        return Err(bad());
    }
    if int.len() > 1 && int.starts_with('0') {
        return Err(bad());
    }
    let mut yocto = int.parse::<u128>().map_err(|_| bad())? * NEAR;
    if let Some(f) = frac {
        if f.is_empty() || f.len() > 24 || !f.bytes().all(|b| b.is_ascii_digit()) {
            return Err(bad());
        }
        yocto += format!("{f:0<24}").parse::<u128>().map_err(|_| bad())?;
    }
    Ok(yocto)
}

/// Exact decimal rendering of a yoctoNEAR amount in NEAR, trailing zeros trimmed.
pub fn format_near(yocto: u128) -> String {
    let int = yocto / NEAR;
    let frac = yocto % NEAR;
    if frac == 0 {
        return int.to_string();
    }
    let f = format!("{frac:024}");
    format!("{int}.{}", f.trim_end_matches('0'))
}

/// A syntactically valid NEAR account ID (protocol rules), returned unchanged. Allowlisting is
/// deliberately NOT checked here: that is the vault's decision.
pub fn parse_recipient(s: &str) -> Result<String, String> {
    s.parse::<AccountId>()
        .map(|a| a.to_string())
        .map_err(|e| format!("recipient {s:?} is not a valid NEAR account ID ({e})"))
}

/// `^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$`
pub fn parse_invoice_id(s: &str) -> Result<String, String> {
    let ok = !s.is_empty()
        && s.len() <= 40
        && s.as_bytes()[0].is_ascii_alphanumeric()
        && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'_' || b == b'-');
    if ok {
        Ok(s.to_string())
    } else {
        Err(format!("invoice_id {s:?} must match ^[A-Za-z0-9][A-Za-z0-9._-]{{0,39}}$"))
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct Proposal {
    pub recipient: String,
    pub amount: u128,
    pub invoice_id: String,
    pub reason: String,
}

/// Exactly {recipient, amount_near, invoice_id, reason}, all strings; anything else is refused.
pub fn parse_proposal(args: &Value) -> Result<Proposal, String> {
    let o = args.as_object().ok_or("arguments must be a JSON object")?;
    const FIELDS: [&str; 4] = ["recipient", "amount_near", "invoice_id", "reason"];
    if let Some(extra) = o.keys().find(|k| !FIELDS.contains(&k.as_str())) {
        return Err(format!("unknown argument {extra:?}"));
    }
    let get = |k: &str| -> Result<&str, String> {
        o.get(k)
            .ok_or(format!("missing argument {k:?}"))?
            .as_str()
            .ok_or(format!("argument {k:?} must be a string"))
    };
    let reason = get("reason")?;
    if reason.chars().count() > MAX_REASON_CHARS {
        return Err(format!("reason is longer than {MAX_REASON_CHARS} characters"));
    }
    Ok(Proposal {
        recipient: parse_recipient(get("recipient")?)?,
        amount: parse_amount_near(get("amount_near")?)?,
        invoice_id: parse_invoice_id(get("invoice_id")?)?,
        reason: reason.to_string(),
    })
}

/// Episode names become account-name prefixes: `^[a-z0-9]+(-[a-z0-9]+)*$`, at most 24 bytes.
pub fn valid_episode(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 24
        && !s.starts_with('-')
        && !s.ends_with('-')
        && !s.contains("--")
        && s.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

// ------------------------------------------------------------------------------------
// Outcome analysis (pure)
// ------------------------------------------------------------------------------------

/// Interprets one FINAL `EXPERIMENTAL_tx_status` of `request_payment` on `vault`.
pub fn analyze(fin: &Value, vault: &str, recipient: &str) -> Value {
    let tv = TxView::new(fin.clone());
    let first = tv.first_receipt_id();
    if !tv.outcomes.contains_key(&first) {
        return json!({"status": "UNKNOWN_SHAPE", "detail": "first receipt has no outcome"});
    }
    if let Some(f) = tv.failure(&first) {
        return json!({"status": "RECEIPT_FAILED", "vault_decision": null, "failure": f,
            "note": "The vault receipt failed; no request was recorded and no NEAR moved."});
    }
    let Some(d) = tv.success_json(&first) else {
        return json!({"status": "UNKNOWN_SHAPE", "detail": "vault receipt returned no decision"});
    };
    match d["decision"].as_str() {
        Some("Denied") => json!({"status": "DENIED", "vault_decision": "Denied",
            "reason": d["reason"], "vault_seq": d["seq"],
            "charged_near": format_near(json_u128(&d["charged"])),
            "note": "The vault rejected this request on chain. No NEAR moved."}),
        Some("Admitted") => {
            let transfer = fin["receipts"].as_array().and_then(|rs| {
                rs.iter().find(|r| {
                    r["predecessor_id"] == vault
                        && r["receiver_id"] == recipient
                        && r["receipt"]["Action"]["actions"]
                            .as_array()
                            .is_some_and(|a| a.iter().any(|x| x.get("Transfer").is_some()))
                })
            });
            let transfer = match transfer.and_then(|r| r["receipt_id"].as_str()) {
                Some(id) if tv.outcomes.contains_key(id) => {
                    if tv.is_success(id) {
                        "delivered"
                    } else {
                        "failed"
                    }
                }
                _ => "not_found",
            };
            json!({"status": "ADMITTED", "vault_decision": "Admitted", "transfer": transfer,
                "vault_seq": d["seq"],
                "charged_before_near": format_near(json_u128(&d["charged_before"])),
                "charged_after_near": format_near(json_u128(&d["charged_after"]))})
        }
        _ => json!({"status": "UNKNOWN_SHAPE", "detail": "unrecognised decision", "decision": d}),
    }
}

// ------------------------------------------------------------------------------------
// Common
// ------------------------------------------------------------------------------------

fn args() -> (String, HashMap<String, String>) {
    let mut it = std::env::args().skip(1);
    let cmd = it.next().unwrap_or_default();
    let mut m = HashMap::new();
    while let Some(k) = it.next() {
        m.insert(k.trim_start_matches("--").to_string(), it.next().unwrap_or_default());
    }
    (cmd, m)
}

fn need<'a>(m: &'a HashMap<String, String>, k: &str) -> Result<&'a str> {
    m.get(k).map(|s| s.as_str()).ok_or_else(|| anyhow!("missing --{k}"))
}

/// Loopback RPC whose node reports a local sandbox chain (`test-chain-*`). Anything else,
/// including testnet and mainnet, is refused before any key is loaded.
async fn connect(m: &HashMap<String, String>) -> Result<(Rpc, String)> {
    let url = need(m, "rpc")?;
    let host = url
        .strip_prefix("http://")
        .and_then(|r| r.split(['/', ':']).next())
        .unwrap_or_default();
    if host != "127.0.0.1" && host != "localhost" {
        bail!("refusing: the RPC must be loopback (local sandbox only)");
    }
    let rpc = Rpc::new(url);
    let chain = rpc.status().await?["chain_id"].as_str().unwrap_or_default().to_string();
    if !chain.starts_with("test-chain-") {
        bail!("refusing: node reports chain_id {chain:?}; this demo runs on a local sandbox only");
    }
    Ok((rpc, chain))
}

fn write_json(path: &Path, v: &Value, mode: u32) -> Result<()> {
    if let Some(d) = path.parent() {
        std::fs::create_dir_all(d)?;
    }
    let mut bytes = serde_json::to_vec_pretty(v)?;
    bytes.push(b'\n');
    std::fs::write(path, bytes).with_context(|| format!("write {}", path.display()))?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))?;
    Ok(())
}

// ------------------------------------------------------------------------------------
// setup (owner side)
// ------------------------------------------------------------------------------------

/// Owner transaction: sign once, wait FINAL, require success of the first receipt.
async fn owner_tx(
    rpc: &Rpc,
    key: &Key,
    receiver: &str,
    actions: Vec<near_primitives::action::Action>,
    label: &str,
) -> Result<(Value, Value)> {
    let sent = sign_and_send(rpc, key, receiver, actions, label).await?;
    if let Err(e) = &sent.submit {
        if e["cause"]["name"] == "INVALID_TRANSACTION" {
            bail!("{label}: rejected at validation: {e}");
        }
    }
    let fin = rpc.tx_final(&sent.hash, &sent.sender).await?;
    let tv = TxView::new(fin.clone());
    if !tv.is_success(&tv.first_receipt_id()) {
        bail!("{label} ({}) did not succeed", sent.hash);
    }
    eprintln!("[setup] {label} {} FINAL", sent.hash);
    Ok((json!({"label": label, "tx_hash": sent.hash, "signer": sent.sender, "receiver": receiver}), fin))
}

async fn setup(m: &HashMap<String, String>) -> Result<()> {
    let (rpc, chain) = connect(m).await?;
    let wasm = std::fs::read(need(m, "wasm")?)?;
    let h = hex(&sha256(&[&wasm]));
    if h != ARTIFACT_SHA256 {
        bail!("refusing: --wasm sha256 {h} is not the reviewed artifact {ARTIFACT_SHA256}");
    }
    let episodes: Vec<String> = need(m, "episodes")?.split(',').map(str::to_string).collect();
    if episodes.is_empty() || episodes.iter().any(|e| !valid_episode(e)) {
        bail!("bad --episodes");
    }
    let public_out = PathBuf::from(need(m, "public-out")?);
    let private_dir = PathBuf::from(need(m, "private-dir")?);
    if public_out.exists() {
        bail!("{} exists; fresh run required", public_out.display());
    }
    let owner = Key::from_file(Path::new(need(m, "owner-key")?))?;
    let o = owner.account.to_string();
    let ak = rpc.view_access_key(&o, &owner.public_key(), &BlockRef::Final).await?;
    if ak["permission"] != json!("FullAccess") {
        bail!("the owner key is not a FullAccess key of {o}");
    }
    let vendor = format!("gpu-vendor.{o}");
    let lookalike = format!("gpu-vendor-billing.{o}");
    let mut txs = vec![];
    for who in [&vendor, &lookalike] {
        let (t, _) = owner_tx(&rpc, &owner, who, vec![act::create_account(), act::transfer(PAYEE_FUNDING)],
            &format!("create_payee {who}")).await?;
        txs.push(t);
    }
    let s_max = 100 + wasm.len() as u64 + STATE_ENTRY_MAX + u64::from(K) * PER_ADMISSION;
    let r_total = u128::from(s_max) * 10_000_000_000_000_000_000 + RESERVE_MARGIN;
    let recipients = [vendor.as_str()];
    let mut eps = vec![];
    for ep in &episodes {
        let agent = format!("agent-{ep}.{o}");
        let vault = format!("vault-{ep}.{o}");
        let sk = SecretKey::from_random(KeyType::ED25519);
        let pk = sk.public_key();
        let (t1, _) = owner_tx(&rpc, &owner, &agent, vec![act::create_account(), act::transfer(AGENT_FUNDING),
            act::add_fc_key(pk.clone(), &vault, &["request_payment"], KEY_ALLOWANCE)], &format!("create_agent {ep}")).await?;
        let now_ns = json_u64(&rpc.final_block().await?["header"]["timestamp_nanosec"]);
        let expires = now_ns + EXPIRY_NS;
        let init = json!({"agent": agent, "budget": BUDGET.to_string(), "max_per_request": MAX_PER_REQUEST.to_string(),
            "allowed_recipients": recipients, "expires_at_ns": expires.to_string(), "max_accepted_requests": K.to_string()});
        let (t2, fin) = owner_tx(&rpc, &owner, &vault, vec![act::create_account(),
            act::transfer(BUDGET + r_total + 100 * MILLI), act::deploy(&wasm), act::call("new", &init, 100, 0)],
            &format!("create_vault {ep}")).await?;
        let tv = TxView::new(fin);
        let ph = tv.success_json(&tv.first_receipt_id()).and_then(|v| v.as_str().map(str::to_string))
            .ok_or_else(|| anyhow!("vault init returned no policy hash"))?;
        let independent = b58(&policy_hash(&PolicyInput { chain_id: &chain, vault: &vault, owner: &o, agent: &agent,
            budget: BUDGET, max_per_request: MAX_PER_REQUEST, recipients: &recipients, expires_at_ns: expires, k: K }));
        if ph != independent {
            bail!("policy hash mismatch for {ep}: contract {ph} vs independent {independent}");
        }
        // Private: the agent key, readable by the owner only. Never printed, never in evidence.
        write_json(&private_dir.join(format!("{ep}.agent-key.json")),
            &json!({"account_id": agent, "public_key": pk.to_string(), "secret_key": sk.to_string()}), 0o600)?;
        eps.push(json!({"name": ep, "agent": agent, "agent_public_key": pk.to_string(), "vault": vault,
            "policy_hash": ph, "policy_hash_independent": independent, "expires_at_ns": expires.to_string(),
            "init_args": init, "setup_txs": [t1, t2]}));
    }
    let fb = rpc.final_block().await?;
    write_json(&public_out, &json!({
        "schema": "pursewarden-llm-demo/setup/v1", "network": "SANDBOX (local)", "chain_id": chain,
        "artifact_sha256": ARTIFACT_SHA256, "owner": o, "owner_public_key": owner.public_key(),
        "vendor": vendor, "lookalike_not_allowlisted": lookalike,
        "policy": {"budget": BUDGET.to_string(), "budget_near": format_near(BUDGET),
                   "max_per_request": MAX_PER_REQUEST.to_string(), "max_per_request_near": format_near(MAX_PER_REQUEST),
                   "max_accepted_requests": K, "allowed_recipients": recipients, "expiry": "+6 h from setup"},
        "agent_key_permission": {"receiver": "the episode's vault", "method_names": ["request_payment"],
                                 "allowance": KEY_ALLOWANCE.to_string()},
        "payee_setup_txs": txs, "episodes": eps,
        "setup_final_block": {"height": fb["header"]["height"], "hash": fb["header"]["hash"]},
    }), 0o644)?;
    eprintln!("[setup] wrote {}", public_out.display());
    Ok(())
}

// ------------------------------------------------------------------------------------
// serve (agent side)
// ------------------------------------------------------------------------------------

struct Gateway {
    rpc: Rpc,
    key: Key,
    vault: String,
    policy_hash: String,
    log: PathBuf,
    raw_dir: PathBuf,
    max_attempts: u32,
    attempts: u32,
    halted: Option<String>,
    invoices: HashMap<String, u64>,
    next_id: u64,
    seq: u64,
}

impl Gateway {
    fn log(&mut self, entry: Value) -> Result<()> {
        use std::io::Write;
        self.seq += 1;
        let mut e = entry;
        e["gateway_seq"] = json!(self.seq);
        e["unix_ms"] = json!(std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_millis() as u64)
            .unwrap_or(0));
        let mut f = std::fs::OpenOptions::new().create(true).append(true).open(&self.log)?;
        writeln!(f, "{}", serde_json::to_string(&e)?)?;
        f.sync_all()?;
        Ok(())
    }

    async fn status(&self) -> Value {
        match self.rpc.view_fn(&self.vault, "get_mandate", json!({}), &BlockRef::Final).await {
            Ok((v, _)) => {
                let now = json_u64(&v["block_timestamp_ns"]);
                let exp = json_u64(&v["expires_at_ns"]);
                json!({"status": "OK", "vault": v["vault"], "owner": v["owner"], "agent": v["agent"],
                    "asset": v["asset"],
                    "budget_near": format_near(json_u128(&v["budget"])),
                    "max_per_request_near": format_near(json_u128(&v["max_per_request"])),
                    "allowed_recipients": v["allowed_recipients"],
                    "max_accepted_requests": v["max_accepted_requests"], "accepted_count": v["accepted_count"],
                    "charged_near": format_near(json_u128(&v["charged"])),
                    "headroom_near": format_near(json_u128(&v["headroom"])),
                    "frozen": v["frozen"], "expired": v["expired"],
                    "expires_in_minutes": exp.saturating_sub(now) / 60_000_000_000})
            }
            Err(e) => json!({"status": "ERROR", "error": format!("could not read the vault: {e}")}),
        }
    }

    async fn pay(&mut self, args: &Value) -> (Value, Value) {
        let p = match parse_proposal(args) {
            Ok(p) => p,
            Err(e) => {
                return (json!({"status": "REJECTED_BY_TOOL", "submitted": false, "error": e,
                    "note": "Nothing was submitted."}), json!({}))
            }
        };
        if let Some(h) = &self.halted {
            return (json!({"status": "HALTED", "submitted": false,
                "error": format!("payments are halted for this session: {h}")}), json!({}));
        }
        if self.attempts >= self.max_attempts {
            return (json!({"status": "ATTEMPT_LIMIT", "submitted": false,
                "error": format!("this session may submit at most {} payment requests", self.max_attempts)}), json!({}));
        }
        let next = &mut self.next_id;
        let request_id = *self.invoices.entry(p.invoice_id.clone()).or_insert_with(|| {
            let id = *next;
            *next += 1;
            id
        });
        self.attempts += 1;
        let on_chain = json!({"request_id": request_id.to_string(), "recipient": p.recipient,
            "amount": p.amount.to_string(), "policy_hash": self.policy_hash});
        let mut rec = json!({"request_id": request_id.to_string(), "parsed": {"recipient": p.recipient,
            "amount_yocto": p.amount.to_string(), "amount_near": format_near(p.amount), "invoice_id": p.invoice_id},
            "request_payment_args": on_chain, "attempt": self.attempts});
        let base = json!({"submitted": true, "request_id": request_id.to_string(), "recipient": p.recipient,
            "amount_near": format_near(p.amount), "invoice_id": p.invoice_id});
        let label = format!("pay-{}", self.attempts);
        let sent = match sign_and_send(&self.rpc, &self.key, &self.vault,
            vec![act::call("request_payment", &on_chain, 100, 0)], &label).await {
            Ok(s) => s,
            Err(e) => {
                // Failed before broadcast (nonce/block lookup or encoding). Halt anyway: fail closed.
                self.halted = Some(format!("could not prepare a transaction: {e}"));
                rec["not_submitted"] = json!(e.to_string());
                return (json!({"status": "NOT_SUBMITTED", "submitted": false,
                    "error": "the gateway could not prepare the transaction; payments are now halted"}), rec);
            }
        };
        rec["tx_hash"] = json!(sent.hash);
        rec["nonce"] = json!(sent.nonce);
        rec["signer"] = json!(sent.sender);
        rec["signer_public_key"] = json!(self.key.public_key());
        let mut out = base;
        out["tx_hash"] = json!(sent.hash);
        match &sent.submit {
            Err(e) if e["cause"]["name"] == "INVALID_TRANSACTION" => {
                rec["validation_rejected"] = e.clone();
                out["status"] = json!("REJECTED_BEFORE_INCLUSION");
                out["submitted"] = json!(false);
                out["note"] = json!("The node rejected the signed transaction at validation; it has no chain trace.");
                return (out, rec);
            }
            Err(e) => rec["uncertain_submit"] = e.clone(),
            Ok(r) => rec["submit"] = r.clone(),
        }
        let mut fin = None;
        for attempt in 1..=2 {
            match self.rpc.tx_final(&sent.hash, &sent.sender).await {
                Ok(f) => {
                    fin = Some(f);
                    break;
                }
                Err(e) => rec[format!("poll_error_{attempt}")] = json!(e.to_string()),
            }
        }
        let Some(fin) = fin else {
            self.halted = Some(format!("the outcome of {} could not be established", sent.hash));
            out["status"] = json!("UNCERTAIN");
            out["error"] = json!("The transaction may or may not have executed. Do not retry; payments are halted.");
            return (out, rec);
        };
        let raw_path = self.raw_dir.join(format!("{}.json", sent.hash));
        if let Err(e) = write_json(&raw_path, &fin, 0o644) {
            rec["raw_write_error"] = json!(e.to_string());
        }
        let a = analyze(&fin, &self.vault, &p.recipient);
        if a["status"] == "UNKNOWN_SHAPE" {
            self.halted = Some(format!("unrecognised outcome for {}", sent.hash));
        }
        rec["outcome"] = a.clone();
        if let Some(o) = a.as_object() {
            for (k, v) in o {
                out[k] = v.clone();
            }
        }
        (out, rec)
    }

    async fn handle(&mut self, req: &Value) -> Value {
        let op = req["op"].as_str().unwrap_or_default().to_string();
        let origin = req["origin"].as_str().unwrap_or("unspecified").to_string();
        let (resp, rec) = match op.as_str() {
            "get_vault_status" => (self.status().await, json!({})),
            "propose_payment" => self.pay(&req["args"]).await,
            _ => (json!({"status": "ERROR", "error": format!("unknown op {op:?}")}), json!({})),
        };
        let entry = json!({"op": op, "origin": origin, "args_received": req.get("args").cloned().unwrap_or(Value::Null),
            "detail": rec, "response": resp});
        if let Err(e) = self.log(entry) {
            // An unlogged action is not acceptable evidence: halt further payments.
            self.halted = Some(format!("log write failed: {e}"));
        }
        resp
    }
}

async fn serve(m: &HashMap<String, String>) -> Result<()> {
    let (rpc, chain) = connect(m).await?;
    let setup: Value = serde_json::from_slice(&std::fs::read(need(m, "setup")?)?)?;
    if setup["chain_id"] != json!(chain) {
        bail!("setup is for chain {} but the node reports {chain}", setup["chain_id"]);
    }
    let ep_name = need(m, "episode")?;
    let ep = setup["episodes"].as_array().and_then(|a| a.iter().find(|e| e["name"] == ep_name))
        .ok_or_else(|| anyhow!("episode {ep_name} not in setup"))?.clone();
    let vault = ep["vault"].as_str().unwrap_or_default().to_string();
    let key = Key::from_file(Path::new(need(m, "agent-key")?))?;
    if key.account.as_str() != ep["agent"] || key.public_key() != ep["agent_public_key"] {
        bail!("the agent key does not belong to episode {ep_name}");
    }
    // Fail closed unless the key is exactly the restricted capability the demo claims.
    let ak = rpc.view_access_key(key.account.as_str(), &key.public_key(), &BlockRef::Final).await?;
    let fc = &ak["permission"]["FunctionCall"];
    if fc["receiver_id"] != json!(vault) || fc["method_names"] != json!(["request_payment"]) {
        bail!("refusing: the agent key is not a FunctionCall key limited to {vault}.request_payment: {}", ak["permission"]);
    }
    let (mandate, _) = rpc.view_fn(&vault, "get_mandate", json!({}), &BlockRef::Final).await?;
    if mandate["policy_hash"] != ep["policy_hash"] {
        bail!("vault policy hash {} differs from setup {}", mandate["policy_hash"], ep["policy_hash"]);
    }
    let socket = PathBuf::from(need(m, "socket")?);
    let max_attempts = match m.get("max-attempts") {
        Some(s) => s.parse::<u32>().ok().filter(|n| (1..=20).contains(n)).ok_or_else(|| anyhow!("bad --max-attempts"))?,
        None => DEFAULT_MAX_ATTEMPTS,
    };
    let raw_dir = PathBuf::from(need(m, "raw-dir")?);
    std::fs::create_dir_all(&raw_dir)?;
    let mut gw = Gateway { rpc, key, vault: vault.clone(), policy_hash: mandate["policy_hash"].as_str().unwrap_or_default().to_string(),
        log: PathBuf::from(need(m, "log")?), raw_dir, max_attempts, attempts: 0, halted: None,
        invoices: HashMap::new(), next_id: 1, seq: 0 };
    gw.log(json!({"op": "start", "episode": ep_name, "vault": vault, "agent": ep["agent"],
        "agent_public_key": ep["agent_public_key"], "agent_key_permission": ak["permission"],
        "policy_hash": gw.policy_hash, "max_attempts": max_attempts, "chain_id": chain}))?;
    let listener = UnixListener::bind(&socket)?;
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o600))?;
    println!("READY {}", socket.display());
    loop {
        let (stream, _) = listener.accept().await?;
        let (r, mut w) = stream.into_split();
        let mut line = String::new();
        let mut br = BufReader::new(r.take(MAX_LINE));
        if br.read_line(&mut line).await.is_err() {
            continue;
        }
        let req: Value = match serde_json::from_str(line.trim()) {
            Ok(v) => v,
            Err(_) => {
                let _ = w.write_all(b"{\"status\":\"ERROR\",\"error\":\"bad request line\"}\n").await;
                continue;
            }
        };
        if req["op"] == "shutdown" {
            gw.log(json!({"op": "shutdown", "attempts": gw.attempts, "halted": gw.halted}))?;
            let _ = w.write_all(b"{\"status\":\"BYE\"}\n").await;
            break;
        }
        let resp = gw.handle(&req).await;
        let mut bytes = serde_json::to_vec(&resp)?;
        bytes.push(b'\n');
        let _ = w.write_all(&bytes).await;
    }
    let _ = std::fs::remove_file(&socket);
    Ok(())
}

#[tokio::main]
async fn main() -> Result<()> {
    let (cmd, m) = args();
    match cmd.as_str() {
        "setup" => setup(&m).await,
        "serve" => serve(&m).await,
        _ => bail!("usage: pw_llm_gateway <setup|serve> ... (see the header of src/main.rs)"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn amounts_parse_exactly() {
        assert_eq!(parse_amount_near("0.75"), Ok(750 * MILLI));
        assert_eq!(parse_amount_near("1"), Ok(NEAR));
        assert_eq!(parse_amount_near("0"), Ok(0));
        assert_eq!(parse_amount_near("4.6"), Ok(4600 * MILLI));
        assert_eq!(parse_amount_near("0.000000000000000000000001"), Ok(1));
        assert_eq!(parse_amount_near("999999.999999999999999999999999"), Ok(1_000_000 * NEAR - 1));
        assert_eq!(parse_amount_near("999999"), Ok(999_999 * NEAR));
        for bad in ["", ".5", "5.", "-1", "+1", "1e24", "1E2", " 1", "1 ", "01", "00.5", "1,5", "1.5 NEAR",
                    "0x10", "1000000", "1.0000000000000000000000001", "NaN", "inf", "١", "1..2", "1.2.3"] {
            assert!(parse_amount_near(bad).is_err(), "{bad:?} should be rejected");
        }
    }

    #[test]
    fn near_formatting_round_trips() {
        for s in ["0", "1", "0.6", "0.75", "4.6", "2", "0.000000000000000000000001", "123456.789"] {
            assert_eq!(format_near(parse_amount_near(s).unwrap()), s);
        }
    }

    #[test]
    fn recipients_parse_by_protocol_rules_only() {
        assert!(parse_recipient("gpu-vendor.test.near").is_ok());
        // Not allowlisted, but syntactically valid: the vault, not the tool, must deny it.
        assert!(parse_recipient("gpu-vendor-billing.test.near").is_ok());
        for bad in ["", "A.test.near", "gpu vendor.test.near", "a", "x..near", "-a.near", "a.near.",
                    "gpu-vendor.test.near\n", "é.near", &"a".repeat(65)] {
            assert!(parse_recipient(bad).is_err(), "{bad:?} should be rejected");
        }
    }

    #[test]
    fn invoice_ids_are_bounded() {
        assert!(parse_invoice_id("INV-1002").is_ok());
        assert!(parse_invoice_id("INV-1002-part2").is_ok());
        for bad in ["", "-INV", "INV 1", "INV/1", &"A".repeat(41), "INV\u{200b}1"] {
            assert!(parse_invoice_id(bad).is_err(), "{bad:?} should be rejected");
        }
    }

    #[test]
    fn proposals_reject_extra_missing_and_non_string_fields() {
        let ok = json!({"recipient": "gpu-vendor.test.near", "amount_near": "0.6", "invoice_id": "INV-1002", "reason": "October compute"});
        assert_eq!(parse_proposal(&ok).unwrap().amount, 600 * MILLI);
        let mut extra = ok.clone();
        extra["policy_hash"] = json!("x");
        assert!(parse_proposal(&extra).is_err());
        let mut num = ok.clone();
        num["amount_near"] = json!(0.6);
        assert!(parse_proposal(&num).is_err());
        let mut missing = ok.clone();
        missing.as_object_mut().unwrap().remove("reason");
        assert!(parse_proposal(&missing).is_err());
        let mut long = ok.clone();
        long["reason"] = json!("x".repeat(501));
        assert!(parse_proposal(&long).is_err());
        assert!(parse_proposal(&json!(["gpu-vendor.test.near"])).is_err());
    }

    #[test]
    fn episode_names_are_account_safe() {
        assert!(valid_episode("inject-overt-1"));
        for bad in ["", "-a", "a-", "a--b", "A", "a.b", "a_b", &"a".repeat(25)] {
            assert!(!valid_episode(bad), "{bad:?}");
        }
    }

    fn fin_with(first_status: Value, receipts: Value, outcomes: Value) -> Value {
        let mut all = vec![json!({"id": "R0", "block_hash": "B",
            "outcome": {"status": first_status, "receipt_ids": [], "logs": []}})];
        all.extend(outcomes.as_array().cloned().unwrap_or_default());
        json!({"transaction_outcome": {"outcome": {"receipt_ids": ["R0"]}},
               "receipts": receipts, "receipts_outcome": all})
    }

    fn b64(v: &Value) -> String {
        use base64::Engine;
        base64::engine::general_purpose::STANDARD.encode(v.to_string())
    }

    #[test]
    fn analysis_reads_the_vault_decision() {
        let denied = json!({"decision": "Denied", "seq": "1", "reason": "RecipientNotAllowed", "charged": "0"});
        let a = analyze(&fin_with(json!({"SuccessValue": b64(&denied)}), json!([]), json!([])), "v.test.near", "x.test.near");
        assert_eq!(a["status"], "DENIED");
        assert_eq!(a["reason"], "RecipientNotAllowed");

        let admitted = json!({"decision": "Admitted", "seq": "1", "charged_before": "0", "charged_after": "600000000000000000000000"});
        let receipts = json!([{"receipt_id": "R1", "predecessor_id": "v.test.near", "receiver_id": "p.test.near",
            "receipt": {"Action": {"actions": [{"Transfer": {"deposit": "600000000000000000000000"}}]}}}]);
        let ok = json!([{"id": "R1", "block_hash": "B", "outcome": {"status": {"SuccessValue": ""}, "receipt_ids": [], "logs": []}}]);
        let a = analyze(&fin_with(json!({"SuccessValue": b64(&admitted)}), receipts.clone(), ok), "v.test.near", "p.test.near");
        assert_eq!(a["status"], "ADMITTED");
        assert_eq!(a["transfer"], "delivered");
        assert_eq!(a["charged_after_near"], "0.6");
        let failed = json!([{"id": "R1", "block_hash": "B", "outcome": {"status": {"Failure": {}}, "receipt_ids": [], "logs": []}}]);
        let a = analyze(&fin_with(json!({"SuccessValue": b64(&admitted)}), receipts, failed), "v.test.near", "p.test.near");
        assert_eq!(a["transfer"], "failed");

        let a = analyze(&fin_with(json!({"Failure": {"ActionError": {}}}), json!([]), json!([])), "v.test.near", "p.test.near");
        assert_eq!(a["status"], "RECEIPT_FAILED");
        let a = analyze(&fin_with(json!({"SuccessValue": b64(&json!({"decision": "Maybe"}))}), json!([]), json!([])), "v", "p");
        assert_eq!(a["status"], "UNKNOWN_SHAPE");
    }
}
