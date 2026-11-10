//! Role-separated actor for the G2 concurrency comparison (scripts/g2-independent/run_g2.py).
//!
//! Three targets on one fresh local sandbox chain, each with its own agent account holding nine
//! function-call keys restricted to `request_payment` on that target:
//!   protected   vault.owner.test.near      protected vault, B = 5 NEAR,  M = 2, K = 9
//!   generous    generous.owner.test.near   protected vault, B = 100 NEAR, M = 2, K = 9 (control)
//!   vulnerable  vulnerable.owner.test.near VULNERABLE TEACHING FIXTURE (settled-only check), B = 5
//! Workload per target: one 1 NEAR payment (FINAL), then eight 2 NEAR requests pre-signed with
//! eight different keys and submitted concurrently. Sandbox only: refuses non-loopback RPC.
use anyhow::{anyhow, bail, Context, Result};
use base64::Engine;
use g1_sandbox_tests::*;
use near_crypto::{KeyType, SecretKey};
use near_primitives::hash::CryptoHash;
use near_primitives::transaction::{SignedTransaction, Transaction, TransactionV0};
use near_primitives::types::AccountId;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

const OWNER: &str = "owner.test.near";
const ALICE: &str = "alice.test.near";
const KEYS: usize = 9;
const KEY_ALLOWANCE: u128 = NEAR / 4;
const REQ_GAS_TGAS: u64 = 100;
const RESERVE_MARGIN: u128 = 10_000_000_000_000_000_000_000;
const STATE_ENTRY_MAX: u64 = 5 + 1024 + 40;
const PER_ADMISSION: u64 = 128;

struct Target {
    name: &'static str,
    vault: &'static str,
    agent: &'static str,
    budget: u128,
    protected: bool,
}
const TARGETS: [Target; 3] = [
    Target { name: "protected", vault: "vault.owner.test.near", agent: "agent.owner.test.near", budget: 5 * NEAR, protected: true },
    Target { name: "generous", vault: "generous.owner.test.near", agent: "agent-gen.owner.test.near", budget: 100 * NEAR, protected: true },
    Target { name: "vulnerable", vault: "vulnerable.owner.test.near", agent: "agent-vuln.owner.test.near", budget: 5 * NEAR, protected: false },
];
const M: u128 = 2 * NEAR;
const K: u32 = 9;

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
fn loopback(url: &str) -> Result<Rpc> {
    let host = url.strip_prefix("http://").and_then(|r| r.split(['/', ':']).next()).unwrap_or_default();
    if host != "127.0.0.1" && host != "localhost" {
        bail!("refusing non-loopback RPC {url}: sandbox-only tool");
    }
    Ok(Rpc::new(url))
}
fn write_json(path: &Path, v: &Value) -> Result<()> {
    if let Some(p) = path.parent() {
        std::fs::create_dir_all(p)?;
    }
    let mut b = serde_json::to_vec_pretty(v)?;
    b.push(b'\n');
    std::fs::write(path, b).with_context(|| format!("write {}", path.display()))
}
fn save_key(path: &Path, account: &str, sk: &SecretKey) -> Result<()> {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    if let Some(p) = path.parent() {
        std::fs::create_dir_all(p)?;
    }
    let v = json!({"account_id": account, "public_key": sk.public_key().to_string(), "secret_key": sk.to_string()});
    let mut f = std::fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(path)
        .with_context(|| format!("create {}", path.display()))?;
    f.write_all(serde_json::to_string(&v)?.as_bytes())?;
    Ok(())
}
fn now_ms() -> u128 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis()).unwrap_or(0)
}

async fn exec(rpc: &Rpc, key: &Key, receiver: &str, actions: Vec<near_primitives::action::Action>, label: &str) -> Result<Value> {
    let sent = sign_and_send(rpc, key, receiver, actions, label).await?;
    let mut out = json!({"label": label, "tx_hash": sent.hash, "signer": sent.sender, "receiver": sent.receiver, "nonce": sent.nonce});
    match &sent.submit {
        Err(e) => out["validation_rejected"] = e.clone(),
        Ok(_) => out["final"] = rpc.tx_final(&sent.hash, &sent.sender).await?,
    }
    Ok(out)
}
fn decision(fin: &Value) -> Value {
    let tv = TxView::new(fin.clone());
    tv.success_json(&tv.first_receipt_id()).unwrap_or(Value::Null)
}

async fn reviewer_prepare(m: &HashMap<String, String>) -> Result<()> {
    let rpc = loopback(need(m, "rpc")?)?;
    let root = Key::from_file(&PathBuf::from(need(m, "node-home")?).join("validator_key.json"))?;
    let reviewer = PathBuf::from(need(m, "reviewer-dir")?);
    let sk = SecretKey::from_random(KeyType::ED25519);
    save_key(&reviewer.join("owner.key.json"), OWNER, &sk)?;
    let owner = Key::from_secret(OWNER, sk);
    let a = exec(&rpc, &root, OWNER, vec![act::create_account(), act::transfer(400 * NEAR), act::add_full_access_key(owner.near_public_key())], "reviewer_setup_owner").await?;
    let b = exec(&rpc, &root, ALICE, vec![act::create_account(), act::transfer(NEAR)], "reviewer_setup_alice_keyless").await?;
    for t in [&a, &b] {
        if t.get("final").is_none() {
            bail!("setup rejected: {t}");
        }
    }
    write_json(&PathBuf::from(need(m, "out")?), &json!({"schema": "g2-independent/prepare/v1", "owner": OWNER,
        "owner_public_key": owner.public_key(), "recipient": ALICE, "transactions": [a, b]}))
}

async fn reviewer_construct(m: &HashMap<String, String>) -> Result<()> {
    let rpc = loopback(need(m, "rpc")?)?;
    let reviewer = PathBuf::from(need(m, "reviewer-dir")?);
    let runner = PathBuf::from(need(m, "runner-dir")?);
    let wasm = std::fs::read(need(m, "wasm")?)?;
    let fixture = std::fs::read(need(m, "fixture-wasm")?)?;
    let owner = Key::from_file(&reviewer.join("owner.key.json"))?;
    let chain_id = rpc.status().await?["chain_id"].as_str().ok_or_else(|| anyhow!("chain_id"))?.to_string();
    let now_ns = json_u64(&rpc.final_block().await?["header"]["timestamp_nanosec"]);
    let expires = now_ns + 24 * 3600 * 1_000_000_000;
    let recipients = [ALICE];
    let mut public_targets = vec![];
    let mut txs = vec![];
    for t in TARGETS.iter() {
        let mut agent_actions = vec![act::create_account(), act::transfer(5 * NEAR)];
        let mut pks = vec![];
        for i in 0..KEYS {
            let sk = SecretKey::from_random(KeyType::ED25519);
            pks.push(sk.public_key().to_string());
            agent_actions.push(act::add_fc_key(sk.public_key(), t.vault, &["request_payment"], KEY_ALLOWANCE));
            save_key(&runner.join(t.name).join(format!("agent-key-{i}.json")), t.agent, &sk)?;
        }
        txs.push(exec(&rpc, &owner, t.agent, agent_actions, &format!("reviewer_create_agent_{}", t.name)).await?);
        let mut entry = json!({"name": t.name, "vault": t.vault, "agent": t.agent, "budget": t.budget.to_string(),
            "max_per_request": M.to_string(), "recipients": recipients, "agent_public_keys": pks, "protected": t.protected});
        let create = if t.protected {
            let s_max = 100 + wasm.len() as u64 + STATE_ENTRY_MAX + u64::from(K) * PER_ADMISSION;
            let r_total = u128::from(s_max) * 10_000_000_000_000_000_000 + RESERVE_MARGIN;
            let init = json!({"agent": t.agent, "budget": t.budget.to_string(), "max_per_request": M.to_string(),
                "allowed_recipients": recipients, "expires_at_ns": expires.to_string(), "max_accepted_requests": K.to_string()});
            let r = exec(&rpc, &owner, t.vault, vec![act::create_account(), act::transfer(t.budget + r_total + NEAR),
                act::deploy(&wasm), act::call("new", &init, 100, 0)], &format!("reviewer_create_{}", t.name)).await?;
            let fin = r.get("final").ok_or_else(|| anyhow!("vault creation rejected: {r}"))?;
            let ph = b58(&policy_hash(&PolicyInput { chain_id: &chain_id, vault: t.vault, owner: OWNER, agent: t.agent,
                budget: t.budget, max_per_request: M, recipients: &recipients, expires_at_ns: expires, k: K }));
            if decision(fin).as_str() != Some(ph.as_str()) {
                bail!("policy hash mismatch for {}", t.name);
            }
            entry["policy_hash"] = json!(ph);
            entry["expires_at_ns"] = json!(expires.to_string());
            entry["max_accepted_requests"] = json!(K);
            entry["wasm_sha256"] = json!(hex(&sha256(&[&wasm])));
            r
        } else {
            let init = json!({"agent": t.agent, "budget": t.budget.to_string(), "max_per_request": M.to_string(),
                "allowed_recipients": recipients});
            entry["wasm_sha256"] = json!(hex(&sha256(&[&fixture])));
            exec(&rpc, &owner, t.vault, vec![act::create_account(), act::transfer(30 * NEAR),
                act::deploy(&fixture), act::call("new", &init, 100, 0)], "reviewer_create_vulnerable_fixture").await?
        };
        if create.get("final").is_none() {
            bail!("creation rejected for {}", t.name);
        }
        txs.push(create);
        public_targets.push(entry);
    }
    write_json(&PathBuf::from(need(m, "out")?), &json!({"schema": "g2-independent/construct/v1", "chain_id": chain_id,
        "owner": OWNER, "targets": public_targets, "transactions": txs}))?;
    write_json(&runner.join("public-setup.json"), &json!({"targets": TARGETS.iter().map(|t| json!({
        "name": t.name, "vault": t.vault, "agent": t.agent})).collect::<Vec<_>>(), "recipient": ALICE}))
}

fn request_args(t: &Target, ph: &Option<String>, id: &str, amount: u128) -> Value {
    match ph {
        Some(ph) => json!({"request_id": id, "recipient": ALICE, "amount": amount.to_string(), "policy_hash": ph}),
        None => {
            let _ = t;
            json!({"request_id": id, "recipient": ALICE, "amount": amount.to_string()})
        }
    }
}

/// Sign once (fresh nonce + recent block hash) without submitting.
async fn presign(rpc: &Rpc, key: &Key, receiver: &str, args: &Value) -> Result<(String, String)> {
    let ak = rpc.view_access_key(key.account.as_str(), &key.public_key(), &BlockRef::Final).await?;
    let nonce = ak["nonce"].as_u64().ok_or_else(|| anyhow!("nonce"))? + 1;
    let fb = rpc.final_block().await?;
    let block_hash: CryptoHash = fb["header"]["hash"].as_str().unwrap().parse().map_err(|e| anyhow!("{e:?}"))?;
    let receiver_id: AccountId = receiver.parse()?;
    let tx = Transaction::V0(TransactionV0 { signer_id: key.account.clone(), public_key: key.near_public_key(), nonce,
        receiver_id, block_hash, actions: vec![act::call("request_payment", args, REQ_GAS_TGAS, 0)] });
    let (hash, _) = tx.get_hash_and_size();
    let stx = SignedTransaction::new(key.signer.sign(hash.as_ref()), tx);
    Ok((hash.to_string(), base64::engine::general_purpose::STANDARD.encode(borsh::to_vec(&stx)?)))
}

/// The untrusted workload. Runs inside the runner sandbox with agent FC keys only.
async fn runner_burst(m: &HashMap<String, String>) -> Result<()> {
    let url = need(m, "rpc")?;
    let rpc = Arc::new(loopback(url)?);
    let runner = PathBuf::from(need(m, "runner-dir")?);
    let setup: Value = serde_json::from_slice(&std::fs::read(runner.join("public-setup.json"))?)?;
    let hashes: Value = serde_json::from_slice(&std::fs::read(runner.join("policy-hashes.json"))?)?;
    let mut scenarios = vec![];
    for t in TARGETS.iter() {
        let ph = hashes.get(t.name).and_then(|v| v.as_str()).map(|s| s.to_string());
        let keys: Vec<Key> = (0..KEYS).map(|i| Key::from_file(&runner.join(t.name).join(format!("agent-key-{i}.json")))).collect::<Result<_>>()?;
        // 1. One normal payment, settled before the burst.
        let first = exec(&rpc, &keys[0], t.vault, vec![act::call("request_payment", &request_args(t, &ph, "1", NEAR), REQ_GAS_TGAS, 0)], &format!("{}_initial_1near", t.name)).await?;
        // 2. Eight 2 NEAR requests, pre-signed with eight different keys, then submitted concurrently.
        let mut signed = vec![];
        for i in 1..=8usize {
            signed.push(presign(&rpc, &keys[i], t.vault, &request_args(t, &ph, &(i + 1).to_string(), 2 * NEAR)).await?);
        }
        let mut set = tokio::task::JoinSet::new();
        for (i, (hash, b64)) in signed.iter().cloned().enumerate() {
            let rpc = rpc.clone();
            set.spawn(async move {
                let t0 = now_ms();
                let r = rpc.raw("send_tx", json!({"signed_tx_base64": b64, "wait_until": "NONE"})).await;
                (i, hash, t0, now_ms(), r.map(|v| v.get("error").cloned()).unwrap_or_else(|e| Some(json!(e.to_string()))))
            });
        }
        let mut submits = vec![];
        while let Some(res) = set.join_next().await {
            let (i, hash, t0, t1, err) = res?;
            submits.push(json!({"key_index": i + 1, "request_id": (i + 2).to_string(), "tx_hash": hash,
                "submit_start_ms": t0.to_string(), "submit_end_ms": t1.to_string(), "submit_error": err}));
        }
        let agent = t.agent.to_string();
        let mut burst = vec![];
        for s in submits.iter() {
            let h = s["tx_hash"].as_str().unwrap();
            let fin = if s["submit_error"].is_null() { rpc.tx_final(h, &agent).await.ok() } else { None };
            let mut e = s.clone();
            if let Some(f) = fin {
                e["decision"] = decision(&f);
                e["final"] = f;
            }
            eprintln!("[runner] {} burst id {}: {}", t.name, s["request_id"], e["decision"]);
            burst.push(e);
        }
        scenarios.push(json!({"target": t.name, "vault": t.vault, "initial": first, "burst": burst}));
    }
    let _ = setup;
    write_json(&PathBuf::from(need(m, "out")?), &json!({"schema": "g2-independent/runner-log/v1",
        "trust": "UNTRUSTED runner output", "scenarios": scenarios}))
}

async fn reviewer_freeze(m: &HashMap<String, String>) -> Result<()> {
    let rpc = loopback(need(m, "rpc")?)?;
    let owner = Key::from_file(&PathBuf::from(need(m, "reviewer-dir")?).join("owner.key.json"))?;
    let mut out = vec![];
    for t in TARGETS.iter().filter(|t| t.protected) {
        let r = exec(&rpc, &owner, t.vault, vec![act::call("freeze", &json!({}), 30, 0)], &format!("reviewer_freeze_{}", t.name)).await?;
        if r.get("final").is_none() {
            bail!("freeze rejected: {r}");
        }
        out.push(r);
    }
    write_json(&PathBuf::from(need(m, "out")?), &json!({"schema": "g2-independent/freeze/v1", "transactions": out}))
}

#[tokio::main]
async fn main() -> Result<()> {
    let (cmd, m) = args();
    match cmd.as_str() {
        "reviewer-prepare" => reviewer_prepare(&m).await,
        "reviewer-construct" => reviewer_construct(&m).await,
        "reviewer-freeze" => reviewer_freeze(&m).await,
        "runner-burst" => runner_burst(&m).await,
        _ => bail!("usage: g2_actor <reviewer-prepare|reviewer-construct|reviewer-freeze|runner-burst> ..."),
    }
}
