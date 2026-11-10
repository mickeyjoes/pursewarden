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
//! - Small amounts only: B = 1 NEAR, M = 0.4 NEAR, K = 3. About 3.3 testnet NEAR in total.
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
    let wasm_len = m.get("wasm").map(|p| std::fs::metadata(p).map(|x| x.len()).unwrap_or(154_346)).unwrap_or(154_346);
    let (s_max, r_total) = reserve(wasm_len);
    let vault_funding = B + r_total + 100 * MILLI;
    let owner_view = rpc.query_raw(json!({"request_type": "view_account", "account_id": n.owner}), &BlockRef::Final).await?;
    let balance = owner_view["result"]["amount"].as_str().and_then(|s| s.parse::<u128>().ok());
    let need_total = vault_funding + 100 * MILLI + 500 * MILLI + 200 * MILLI; // + gas headroom
    let mut free = json!({});
    for id in [&n.vault, &n.agent, &n.payee, &n.missing, &n.attacker] {
        free[id.as_str()] = json!(absent(&rpc, id).await?);
    }
    Ok(json!({
        "schema": "pursewarden-smoke-plan/v1", "network": network, "chain_id": chain,
        "artifact": "artifacts/near_agent_vault.wasm (c7c77263…, same as all sandbox evidence)",
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
        "funds_left_locked": "The vault has no withdrawal path by design: about 2.3 testnet NEAR stays in pw-vault."
    }))
}

async fn exec(rpc: &Rpc, key: &Key, receiver: &str, actions: Vec<near_primitives::action::Action>, label: &str) -> Result<Value> {
    let sent = sign_and_send(rpc, key, receiver, actions, label).await?;
    let mut out = json!({"label": label, "tx_hash": sent.hash, "signer": sent.sender, "receiver": sent.receiver});
    match &sent.submit {
        Err(e) => out["validation_rejected"] = e.clone(),
        Ok(_) => out["final"] = rpc.tx_final(&sent.hash, &sent.sender).await?,
    }
    eprintln!("[smoke] {label}: {}", if out.get("final").is_some() { "FINAL" } else { "rejected at validation" });
    Ok(out)
}

async fn run(m: &HashMap<String, String>) -> Result<()> {
    let (rpc, network, chain) = connect(m).await?;
    if need(m, "confirm-network")? != network {
        bail!("--confirm-network must repeat --network");
    }
    if network == "testnet" && m.get("owner-approved-testnet-broadcast").map(|s| s.as_str()) != Some("yes") {
        bail!("testnet broadcast requires --owner-approved-testnet-broadcast yes (owner approval)");
    }
    let p = plan(m).await?;
    if p["sufficient"] != json!(true) || p["accounts_must_not_exist"].as_object().map(|o| o.values().any(|v| v != &json!(true))).unwrap_or(true) {
        bail!("preconditions not met: {}", serde_json::to_string_pretty(&p)?);
    }
    let n = names(need(m, "owner")?);
    let owner = Key::from_file(&PathBuf::from(need(m, "owner-key")?))?;
    if owner.account.as_str() != n.owner {
        bail!("owner key is for {}, not {}", owner.account, n.owner);
    }
    let wasm = std::fs::read(need(m, "wasm")?)?;
    let (_s, r_total) = reserve(wasm.len() as u64);
    let mut txs = vec![];
    txs.push(exec(&rpc, &owner, &n.payee, vec![act::create_account(), act::transfer(100 * MILLI)], "create_payee").await?);
    let keys: Vec<Key> = (0..AGENT_KEYS).map(|_| Key::from_secret(&n.agent, SecretKey::from_random(KeyType::ED25519))).collect();
    let mut a = vec![act::create_account(), act::transfer(500 * MILLI)];
    for k in &keys {
        a.push(act::add_fc_key(k.near_public_key(), &n.vault, &["request_payment"], KEY_ALLOWANCE));
    }
    txs.push(exec(&rpc, &owner, &n.agent, a, "create_agent").await?);
    let now_ns = json_u64(&rpc.final_block().await?["header"]["timestamp_nanosec"]);
    let expires = now_ns + 24 * 3600 * 1_000_000_000;
    let recipients = [n.missing.as_str(), n.payee.as_str()];
    let init = json!({"agent": n.agent, "budget": B.to_string(), "max_per_request": M.to_string(),
        "allowed_recipients": recipients, "expires_at_ns": expires.to_string(), "max_accepted_requests": K.to_string()});
    let create = exec(&rpc, &owner, &n.vault, vec![act::create_account(), act::transfer(B + r_total + 100 * MILLI),
        act::deploy(&wasm), act::call("new", &init, 100, 0)], "create_vault").await?;
    let fin = create.get("final").ok_or_else(|| anyhow!("vault creation rejected: {create}"))?.clone();
    let tv = TxView::new(fin);
    let ph = tv.success_json(&tv.first_receipt_id()).and_then(|v| v.as_str().map(|s| s.to_string()))
        .ok_or_else(|| anyhow!("vault init did not return a policy hash"))?;
    let independent = b58(&policy_hash(&PolicyInput { chain_id: &chain, vault: &n.vault, owner: &n.owner, agent: &n.agent,
        budget: B, max_per_request: M, recipients: &recipients, expires_at_ns: expires, k: K }));
    if ph != independent {
        bail!("policy hash mismatch: contract {ph} vs independent {independent}");
    }
    txs.push(create);
    let req = |id: &str, to: &str, amt: u128| json!({"request_id": id, "recipient": to, "amount": amt.to_string(), "policy_hash": ph});
    let steps = [("pay_1_payee", req("1", &n.payee, M)), ("pay_2_missing", req("2", &n.missing, M)),
                 ("replay_1", req("1", &n.payee, M)), ("over_cap", req("3", &n.payee, 500 * MILLI)),
                 ("exfiltrate", req("4", &n.attacker, M)), ("budget_exceeded", req("5", &n.payee, 300 * MILLI))];
    for (i, (label, args)) in steps.iter().enumerate() {
        txs.push(exec(&rpc, &keys[i % AGENT_KEYS], &n.vault, vec![act::call("request_payment", args, 100, 0)], label).await?);
    }
    txs.push(exec(&rpc, &owner, &n.vault, vec![act::call("freeze", &json!({}), 30, 0)], "freeze").await?);
    let out = json!({"schema": "pursewarden-smoke-run/v1", "network": network, "chain_id": chain, "plan": p,
        "policy_hash": ph, "expires_at_ns": expires.to_string(), "owner": n.owner, "vault": n.vault, "agent": n.agent,
        "recipients": recipients, "budget": B.to_string(), "max_per_request": M.to_string(), "max_accepted_requests": K,
        "agent_public_keys": keys.iter().map(|k| k.public_key()).collect::<Vec<_>>(),
        "trust": "Runner-recorded transaction list (the inspector re-reads every hash from the node).", "transactions": txs});
    let path = PathBuf::from(need(m, "out")?);
    if let Some(d) = path.parent() {
        std::fs::create_dir_all(d)?;
    }
    std::fs::write(&path, serde_json::to_vec_pretty(&out)?).with_context(|| format!("write {}", path.display()))?;
    eprintln!("[smoke] wrote {}", path.display());
    Ok(())
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
