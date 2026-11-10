//! Testnet-ready smoke of the PROTECTED vault (same artifact c7c77263…). It is rehearsed on a local
//! sandbox of the same protocol version first.
//!
//!   smoke_actor plan --network sandbox|testnet --rpc http://127.0.0.1:PORT --owner ACCOUNT
//!   smoke_actor run  --network sandbox|testnet --rpc http://127.0.0.1:PORT --owner ACCOUNT \
//!                    --owner-key FILE --wasm FILE --out FILE --confirm-network NETWORK \
//!                    [--owner-approved-testnet-broadcast yes]
//!
//! Safety:
//! - The RPC URL must be loopback. Testnet traffic goes through scripts/testnet/https_rpc_forwarder.py,
//!   which only forwards to allowlisted TESTNET hosts.
//! - The node's reported chain_id must match --network ("testnet", or a "test-chain-*" sandbox).
//!   Anything else, including "mainnet", is refused before any key is loaded.
//! - `plan` is read-only and never loads a key.
//! - `run` on testnet additionally requires --owner-approved-testnet-broadcast yes.
//! - --wasm must hash to the reviewed artifact c7c77263…; anything else is refused.
//! - The owner key must be a FullAccess key of --owner on chain. It is never printed or written.
//! - `run` stops at the first transaction whose result differs from the plan and still writes what it
//!   has, marked "stopped".
//! - Small amounts only: B = 1 NEAR, M = 0.4 NEAR, K = 3. The owner sends about 3.27 testnet NEAR plus
//!   gas, and none of it can come back (keyless vault and payee, FunctionCall-only agent).
use anyhow::{anyhow, bail, Context, Result};
use g1_sandbox_tests::*;
use near_crypto::{KeyType, SecretKey};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::PathBuf;

const MILLI: u128 = NEAR / 1000;
const B: u128 = NEAR;
const M: u128 = 400 * MILLI;
const K: u32 = 3;
const AGENT_KEYS: usize = 3;
const KEY_ALLOWANCE: u128 = NEAR / 4;
const RESERVE_MARGIN: u128 = 10_000_000_000_000_000_000_000;
const STATE_ENTRY_MAX: u64 = 5 + 1024 + 40;
const PER_ADMISSION: u64 = 128;
/// Owner-approved ceiling on everything the owner account spends, gas included (3.5 testnet NEAR).
const SPEND_CAP: u128 = 3500 * MILLI;
const OWNER_TXS: u64 = 4;
/// Generous per-transaction gas bound for the owner's transactions (the largest attaches 100 Tgas).
const OWNER_GAS_BOUND_TGAS: u64 = 400;
const ARTIFACT_SHA256: &str = "c7c772635acea0938bd88450d02bcdb9215d9aa65fc407b4070459cd225dd768";
const EXPECT: [(&str, &str, &str); 6] = [("pay_1_payee", "Admitted", "native transfer succeeds"),
    ("pay_2_missing", "Admitted", "native transfer fails"), ("replay_1", "Denied", "DuplicateRequest"),
    ("over_cap", "Denied", "AboveMaxPerRequest"), ("exfiltrate", "Denied", "RecipientNotAllowed"),
    ("budget_exceeded", "Denied", "BudgetExceeded")];

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

struct Names { owner: String, vault: String, agent: String, payee: String, missing: String, attacker: String }
fn names(owner: &str) -> Names {
    Names { owner: owner.to_string(), vault: format!("pw-vault.{owner}"), agent: format!("pw-agent.{owner}"),
            payee: format!("pw-payee.{owner}"), missing: format!("pw-missing.{owner}"), attacker: format!("pw-attacker.{owner}") }
}

/// Loopback RPC + chain identity check. Refuses mainnet and anything not matching --network.
async fn connect(m: &HashMap<String, String>) -> Result<(Rpc, String, String)> {
    let network = need(m, "network")?.to_string();
    let url = need(m, "rpc")?;
    let host = url.strip_prefix("http://").and_then(|r| r.split(['/', ':']).next()).unwrap_or_default();
    if host != "127.0.0.1" && host != "localhost" {
        bail!("RPC must be loopback (use scripts/testnet/https_rpc_forwarder.py for testnet)");
    }
    let rpc = Rpc::new(url);
    let chain = rpc.status().await?["chain_id"].as_str().unwrap_or_default().to_string();
    let ok = match network.as_str() {
        "testnet" => chain == "testnet",
        "sandbox" => chain.starts_with("test-chain-"),
        _ => false,
    };
    if chain == "mainnet" || !ok {
        bail!("refusing: --network {network} but node reports chain_id {chain:?}");
    }
    Ok((rpc, network, chain))
}

/// Reads --wasm and refuses anything but the reviewed artifact.
fn artifact(m: &HashMap<String, String>) -> Result<Vec<u8>> {
    let wasm = std::fs::read(need(m, "wasm")?)?;
    let h: String = sha256(&[&wasm]).iter().map(|b| format!("{b:02x}")).collect();
    if h != ARTIFACT_SHA256 {
        bail!("refusing: --wasm sha256 {h} is not the reviewed artifact {ARTIFACT_SHA256}");
    }
    Ok(wasm)
}

/// Loads the owner key without printing it. Accepts the near-cli KeyFile shape
/// ({account_id, public_key, secret_key}) and the near-cli-rs shape (private_key, no account_id).
fn owner_key(path: &str, owner: &str) -> Result<Key> {
    let v: Value = serde_json::from_slice(&std::fs::read(path).with_context(|| format!("read {path}"))?)
        .map_err(|_| anyhow!("owner key file is not valid JSON"))?;
    if let Some(a) = v.get("account_id") {
        if a.as_str() != Some(owner) {
            bail!("owner key file is for {a}, not {owner}");
        }
    }
    let s = v.get("secret_key").or_else(|| v.get("private_key")).and_then(|s| s.as_str())
        .ok_or_else(|| anyhow!("owner key file has no secret_key / private_key"))?;
    let sk: SecretKey = s.parse().map_err(|_| anyhow!("owner key file: the secret key does not parse"))?;
    if v.get("public_key").and_then(|p| p.as_str()) != Some(sk.public_key().to_string().as_str()) {
        bail!("owner key file: the secret key does not match its public_key");
    }
    Ok(Key::from_secret(owner, sk))
}

/// The vault's native transfer to `to` in this transaction: Some(true) success, Some(false) failure.
fn native(fin: &Value, vault: &str, to: &str) -> Option<bool> {
    let r = fin["receipts"].as_array()?.iter().find(|r| r["predecessor_id"] == vault && r["receiver_id"] == to
        && r["receipt"]["Action"]["actions"].as_array().is_some_and(|a| a.iter().any(|x| x.get("Transfer").is_some())))?;
    Some(TxView::new(fin.clone()).is_success(r["receipt_id"].as_str()?))
}

fn write(path: &PathBuf, out: &Value) -> Result<()> {
    if let Some(d) = path.parent() {
        std::fs::create_dir_all(d)?;
    }
    std::fs::write(path, serde_json::to_vec_pretty(out)?).with_context(|| format!("write {}", path.display()))?;
    eprintln!("[smoke] wrote {}", path.display());
    Ok(())
}

fn reserve(wasm_len: u64) -> (u64, u128) {
    let s_max = 100 + wasm_len + STATE_ENTRY_MAX + u64::from(K) * PER_ADMISSION;
    (s_max, u128::from(s_max) * 10_000_000_000_000_000_000 + RESERVE_MARGIN)
}

async fn absent(rpc: &Rpc, id: &str) -> Result<bool> {
    let r = rpc.query_raw(json!({"request_type": "view_account", "account_id": id}), &BlockRef::Final).await?;
    Ok(r.to_string().contains("UNKNOWN_ACCOUNT"))
}

async fn plan(m: &HashMap<String, String>) -> Result<Value> {
    let (rpc, network, chain) = connect(m).await?;
    let n = names(need(m, "owner")?);
    let wasm_len = artifact(m)?.len() as u64;
    let (s_max, r_total) = reserve(wasm_len);
    let vault_funding = B + r_total + 100 * MILLI;
    let owner_view = rpc.query_raw(json!({"request_type": "view_account", "account_id": n.owner}), &BlockRef::Final).await?;
    let balance = owner_view["result"]["amount"].as_str().and_then(|s| s.parse::<u128>().ok());
    let sent_total = vault_funding + 100 * MILLI + 500 * MILLI;
    let need_total = sent_total + 200 * MILLI; // + gas headroom
    let mut free = json!({});
    for id in [&n.vault, &n.agent, &n.payee, &n.missing, &n.attacker] {
        free[id.as_str()] = json!(absent(&rpc, id).await?);
    }
    Ok(json!({
        "schema": "pursewarden-smoke-plan/v1", "network": network, "chain_id": chain,
        "artifact_sha256": ARTIFACT_SHA256, "artifact_bytes": wasm_len,
        "owner": n.owner, "owner_exists": balance.is_some(), "owner_balance_yocto": balance.map(|b| b.to_string()),
        "required_owner_balance_yocto": need_total.to_string(),
        "sufficient": balance.map(|b| b >= need_total),
        "accounts_must_not_exist": free,
        "policy": {"budget": B.to_string(), "max_per_request": M.to_string(), "max_accepted_requests": K,
                   "recipients": [n.missing.clone(), n.payee.clone()], "expiry": "+24 h from the final block"},
        "storage_bound_bytes": s_max, "reserve_total": r_total.to_string(),
        "transactions": [
            {"signer": n.owner, "receiver": n.payee, "actions": ["CreateAccount", "Transfer 0.1 NEAR"], "why": "keyless allowlisted payee"},
            {"signer": n.owner, "receiver": n.agent, "actions": ["CreateAccount", "Transfer 0.5 NEAR", "AddKey FunctionCall(vault, request_payment, 0.25 NEAR) x3"], "why": "restricted agent"},
            {"signer": n.owner, "receiver": n.vault, "actions": ["CreateAccount", format!("Transfer {} yocto", vault_funding), "DeployContract c7c77263", "FunctionCall new(B=1, M=0.4, K=3)"], "why": "keyless vault in one batch"},
            {"signer": n.agent, "receiver": n.vault, "call": "request_payment id 1: 0.4 NEAR -> payee", "expect": "Admitted, transfer succeeds"},
            {"signer": n.agent, "receiver": n.vault, "call": "request_payment id 2: 0.4 NEAR -> pw-missing (does not exist)", "expect": "Admitted, transfer fails, principal refunded, C stays 0.8"},
            {"signer": n.agent, "receiver": n.vault, "call": "request_payment id 1 again", "expect": "Denied DuplicateRequest"},
            {"signer": n.agent, "receiver": n.vault, "call": "request_payment id 3: 0.5 NEAR", "expect": "Denied AboveMaxPerRequest"},
            {"signer": n.agent, "receiver": n.vault, "call": "request_payment id 4: 0.4 NEAR -> pw-attacker", "expect": "Denied RecipientNotAllowed"},
            {"signer": n.agent, "receiver": n.vault, "call": "request_payment id 5: 0.3 NEAR -> payee (C 0.8 + 0.3 > B 1; a slot is still free)", "expect": "Denied BudgetExceeded"},
            {"signer": n.owner, "receiver": n.vault, "call": "freeze", "expect": "Frozen"}
        ],
        "expected_final": {"C": "0.8 NEAR", "S": "0.4 NEAR", "F": "0.4 NEAR", "headroom": "0.2 NEAR", "vault_keys": 0},
        "owner_sends_yocto": sent_total.to_string(),
        "funds_left_locked": "Nothing comes back to the owner. The vault has no withdrawal path by design (about 2.27 stays in pw-vault), the payee is keyless (0.1 + 0.4 received) and the agent holds only FunctionCall keys that are discarded after the run (0.5 less its gas). The owner also pays gas for 4 transactions; the 0.2 headroom is a balance precondition, not a transfer."
    }))
}

/// Signs and submits once, then waits for FINAL by hash. It never re-signs and never returns an error
/// once something may have been broadcast; problems are recorded in the returned JSON instead.
async fn exec(rpc: &Rpc, key: &Key, receiver: &str, actions: Vec<near_primitives::action::Action>, label: &str) -> Value {
    let sent = match sign_and_send(rpc, key, receiver, actions, label).await {
        Ok(s) => s,
        Err(e) => {
            eprintln!("[smoke] {label}: not sent ({e})");
            return json!({"label": label, "not_sent": e.to_string()});
        }
    };
    let mut out = json!({"label": label, "tx_hash": sent.hash, "signer": sent.sender, "receiver": sent.receiver, "nonce": sent.nonce});
    let poll = match &sent.submit {
        Err(e) if e["cause"]["name"] == "INVALID_TRANSACTION" => {
            out["validation_rejected"] = e.clone();
            false
        }
        Err(e) => {
            out["uncertain_submit"] = e.clone();
            true
        }
        Ok(r) => {
            out["submit"] = r.clone();
            true
        }
    };
    if poll {
        for attempt in 1..=3 {
            match rpc.tx_final(&sent.hash, &sent.sender).await {
                Ok(f) => {
                    out["final"] = f;
                    break;
                }
                Err(e) => {
                    eprintln!("[smoke] {label}: polling attempt {attempt} by hash failed: {e}");
                    out[format!("poll_error_{attempt}")] = json!(e.to_string());
                }
            }
        }
    }
    eprintln!("[smoke] {label} {}: {}", sent.hash, if out.get("final").is_some() { "FINAL" } else { "NOT FINAL (stopping)" });
    out
}

async fn run(m: &HashMap<String, String>) -> Result<()> {
    let (rpc, network, chain) = connect(m).await?;
    if need(m, "confirm-network")? != network {
        bail!("--confirm-network must repeat --network");
    }
    if network == "testnet" && m.get("owner-approved-testnet-broadcast").map(|s| s.as_str()) != Some("yes") {
        bail!("testnet broadcast requires --owner-approved-testnet-broadcast yes (owner approval)");
    }
    let path = PathBuf::from(need(m, "out")?);
    if path.exists() {
        bail!("{} already exists; use a fresh run id", path.display());
    }
    let p = plan(m).await?;
    if p["sufficient"] != json!(true) || p["accounts_must_not_exist"].as_object().map(|o| o.values().any(|v| v != &json!(true))).unwrap_or(true) {
        bail!("preconditions not met: {}", serde_json::to_string_pretty(&p)?);
    }
    let n = names(need(m, "owner")?);
    let owner = owner_key(need(m, "owner-key")?, &n.owner)?;
    let ak = rpc.view_access_key(&n.owner, &owner.public_key(), &BlockRef::Final).await?;
    if ak["permission"] != json!("FullAccess") {
        bail!("the owner key is not a FullAccess key of {}", n.owner);
    }
    let wasm = artifact(m)?;
    let (_s, r_total) = reserve(wasm.len() as u64);
    let gas_price: u128 = rpc.call("gas_price", json!([null])).await?["gas_price"].as_str()
        .and_then(|g| g.parse().ok()).ok_or_else(|| anyhow!("gas_price unavailable"))?;
    let sent_total: u128 = p["owner_sends_yocto"].as_str().and_then(|v| v.parse().ok()).ok_or_else(|| anyhow!("plan"))?;
    let worst = sent_total + u128::from(OWNER_TXS * OWNER_GAS_BOUND_TGAS * TGAS) * gas_price;
    // Enforced on testnet. A local sandbox's genesis gas price is higher, so there it is only reported.
    if network == "testnet" && worst >= SPEND_CAP {
        bail!("refusing: worst-case owner spend {worst} yocto at gas price {gas_price} is not below the approved cap {SPEND_CAP}");
    }
    eprintln!("[smoke] gas price {gas_price}; worst-case owner spend {worst} yocto < cap {SPEND_CAP}");
    let recipients = [n.missing.as_str(), n.payee.as_str()];
    let keys: Vec<Key> = (0..AGENT_KEYS).map(|_| Key::from_secret(&n.agent, SecretKey::from_random(KeyType::ED25519))).collect();
    let mut out = json!({"schema": "pursewarden-smoke-run/v1", "network": network, "chain_id": chain, "plan": p,
        "artifact_sha256": ARTIFACT_SHA256, "owner": n.owner, "owner_public_key": owner.public_key(), "vault": n.vault,
        "agent": n.agent, "recipients": recipients, "budget": B.to_string(), "max_per_request": M.to_string(),
        "max_accepted_requests": K, "agent_public_keys": keys.iter().map(|k| k.public_key()).collect::<Vec<_>>(),
        "trust": "Runner-recorded transaction list (the inspector re-reads every hash from the node).",
        "gas_price_at_start": gas_price.to_string(), "worst_case_owner_spend_yocto": worst.to_string(), "spend_cap_yocto": SPEND_CAP.to_string()});
    let mut txs: Vec<Value> = vec![];
    let stop = |out: &mut Value, txs: &[Value], why: String| -> anyhow::Error {
        out["transactions"] = json!(txs);
        out["stopped"] = json!(why);
        if let Err(e) = write(&path, out) {
            eprintln!("[smoke] could not write partial evidence: {e}");
        }
        anyhow!("STOPPED: {why}")
    };
    let ok_first = |t: &Value| t.get("final").is_some_and(|f| { let tv = TxView::new(f.clone()); tv.is_success(&tv.first_receipt_id()) });
    let t = exec(&rpc, &owner, &n.payee, vec![act::create_account(), act::transfer(100 * MILLI)], "create_payee").await;
    txs.push(t.clone());
    if !ok_first(&t) {
        return Err(stop(&mut out, &txs, "create_payee did not succeed".into()));
    }
    let mut a = vec![act::create_account(), act::transfer(500 * MILLI)];
    for k in &keys {
        a.push(act::add_fc_key(k.near_public_key(), &n.vault, &["request_payment"], KEY_ALLOWANCE));
    }
    let t = exec(&rpc, &owner, &n.agent, a, "create_agent").await;
    txs.push(t.clone());
    if !ok_first(&t) {
        return Err(stop(&mut out, &txs, "create_agent did not succeed".into()));
    }
    let now_ns = match rpc.final_block().await {
        Ok(b) => json_u64(&b["header"]["timestamp_nanosec"]),
        Err(e) => return Err(stop(&mut out, &txs, format!("could not read the final block for the expiry: {e}"))),
    };
    let expires = now_ns + 24 * 3600 * 1_000_000_000;
    let init = json!({"agent": n.agent, "budget": B.to_string(), "max_per_request": M.to_string(),
        "allowed_recipients": recipients, "expires_at_ns": expires.to_string(), "max_accepted_requests": K.to_string()});
    let create = exec(&rpc, &owner, &n.vault, vec![act::create_account(), act::transfer(B + r_total + 100 * MILLI),
        act::deploy(&wasm), act::call("new", &init, 100, 0)], "create_vault").await;
    txs.push(create.clone());
    out["expires_at_ns"] = json!(expires.to_string());
    let Some(fin) = create.get("final").cloned() else {
        return Err(stop(&mut out, &txs, "create_vault did not reach FINAL".into()));
    };
    let tv = TxView::new(fin);
    let Some(ph) = tv.success_json(&tv.first_receipt_id()).and_then(|v| v.as_str().map(|s| s.to_string())) else {
        return Err(stop(&mut out, &txs, "vault init did not return a policy hash".into()));
    };
    let independent = b58(&policy_hash(&PolicyInput { chain_id: &chain, vault: &n.vault, owner: &n.owner, agent: &n.agent,
        budget: B, max_per_request: M, recipients: &recipients, expires_at_ns: expires, k: K }));
    out["policy_hash"] = json!(ph);
    if ph != independent {
        return Err(stop(&mut out, &txs, format!("policy hash mismatch: contract {ph} vs independent {independent}")));
    }
    let req = |id: &str, to: &str, amt: u128| json!({"request_id": id, "recipient": to, "amount": amt.to_string(), "policy_hash": ph});
    let steps = [req("1", &n.payee, M), req("2", &n.missing, M), req("1", &n.payee, M), req("3", &n.payee, 500 * MILLI),
                 req("4", &n.attacker, M), req("5", &n.payee, 300 * MILLI)];
    for (i, (args, (label, want, detail))) in steps.iter().zip(EXPECT).enumerate() {
        let t = exec(&rpc, &keys[i % AGENT_KEYS], &n.vault, vec![act::call("request_payment", args, 100, 0)], label).await;
        txs.push(t.clone());
        let fin = t.get("final").cloned().unwrap_or(Value::Null);
        let tv = TxView::new(fin.clone());
        let dec = if fin.is_null() { None } else { tv.success_json(&tv.first_receipt_id()) };
        let got = dec.as_ref().map(|d| (d["decision"].as_str().unwrap_or_default().to_string(),
            if d["decision"] == "Denied" { d["reason"].as_str().unwrap_or_default().to_string() } else {
                match native(&fin, &n.vault, args["recipient"].as_str().unwrap_or_default()) {
                    Some(true) => "native transfer succeeds".into(), Some(false) => "native transfer fails".into(), None => "no native transfer".into() }
            }));
        if got.as_ref().map(|(d, r)| (d.as_str(), r.as_str())) != Some((want, detail)) {
            return Err(stop(&mut out, &txs, format!("{label}: expected {want} / {detail}, observed {got:?}")));
        }
    }
    let t = exec(&rpc, &owner, &n.vault, vec![act::call("freeze", &json!({}), 30, 0)], "freeze").await;
    txs.push(t.clone());
    if !ok_first(&t) {
        return Err(stop(&mut out, &txs, "freeze did not succeed".into()));
    }
    out["transactions"] = json!(txs);
    write(&path, &out)
}

#[tokio::main]
async fn main() -> Result<()> {
    let (cmd, m) = args();
    match cmd.as_str() {
        "plan" => {
            println!("{}", serde_json::to_string_pretty(&plan(&m).await?)?);
            Ok(())
        }
        "run" => run(&m).await,
        _ => bail!("usage: smoke_actor <plan|run> --network sandbox|testnet --rpc http://127.0.0.1:PORT --owner ACCOUNT ..."),
    }
}
