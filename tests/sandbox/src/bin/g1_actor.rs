//! Role-separated actor for the independent G1 run (scripts/g1-independent/run-g1.sh).
//!
//! The reviewer and the runner are different capabilities:
//!
//! * `reviewer-prepare`, `reviewer-construct`, `reviewer-freeze` run OUTSIDE the runner sandbox.
//!   They read the node's validator key and the reviewer-held owner key.
//! * `runner-attack` runs INSIDE the bubblewrap sandbox. It sees only the runner directory
//!   (eight agent function-call keys + public setup facts) and a filtered RPC endpoint that
//!   forwards only ordinary read and submission methods. It never sees the node home, the
//!   validator key, the owner key or the sandbox admin RPC.
//!
//! Every transaction is signed exactly once (see `sign_and_send`); a transport error is never
//! retried with a new signature. Nothing here talks to testnet or mainnet: the binary refuses
//! any RPC URL whose host is not loopback.
use anyhow::{anyhow, bail, Context, Result};
use g1_sandbox_tests::*;
use near_crypto::{KeyType, SecretKey};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

const OWNER: &str = "owner.test.near";
const ALICE: &str = "alice.test.near";
const MISSING: &str = "missing.test.near";
const ATTACKER: &str = "attacker.test.near";
const VAULT: &str = "vault.owner.test.near";
const AGENT: &str = "agent.owner.test.near";
const AGENT_KEYS: usize = 8;
const KEY_ALLOWANCE: u128 = NEAR / 4;
const REQ_GAS_TGAS: u64 = 100;
// Same constants as tests/sandbox/tests/g1.rs (SPEC-V1.1 storage bound and reserve).
const RESERVE_MARGIN: u128 = 10_000_000_000_000_000_000_000;
const STATE_ENTRY_MAX: u64 = 5 + 1024 + 40;
const PER_ADMISSION: u64 = 128;

fn args() -> (String, HashMap<String, String>) {
    let mut it = std::env::args().skip(1);
    let cmd = it.next().unwrap_or_default();
    let mut m = HashMap::new();
    while let Some(k) = it.next() {
        let v = it.next().unwrap_or_default();
        m.insert(k.trim_start_matches("--").to_string(), v);
    }
    (cmd, m)
}

fn need<'a>(m: &'a HashMap<String, String>, k: &str) -> Result<&'a str> {
    m.get(k).map(|s| s.as_str()).ok_or_else(|| anyhow!("missing --{k}"))
}

fn loopback_rpc(url: &str) -> Result<Rpc> {
    let host = url
        .strip_prefix("http://")
        .and_then(|r| r.split(['/', ':']).next())
        .unwrap_or_default();
    if !(host == "127.0.0.1" || host == "localhost") {
        bail!("refusing non-loopback RPC {url}: this tool is sandbox-only");
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

fn read_json(path: &Path) -> Result<Value> {
    Ok(serde_json::from_slice(
        &std::fs::read(path).with_context(|| format!("read {}", path.display()))?,
    )?)
}

/// Secret key file in the near-crypto KeyFile shape, created with mode 0600.
fn save_key(path: &Path, account: &str, sk: &SecretKey) -> Result<()> {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    if let Some(p) = path.parent() {
        std::fs::create_dir_all(p)?;
    }
    let v = json!({"account_id": account, "public_key": sk.public_key().to_string(),
                   "secret_key": sk.to_string()});
    let mut f = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .with_context(|| format!("create {}", path.display()))?;
    f.write_all(serde_json::to_string(&v)?.as_bytes())?;
    Ok(())
}

/// Sign once, submit once, then wait for FINAL when the node accepted the transaction.
async fn exec(rpc: &Rpc, key: &Key, receiver: &str, actions: Vec<near_primitives::action::Action>, label: &str) -> Result<Value> {
    let sent = sign_and_send(rpc, key, receiver, actions, label).await?;
    let mut out = json!({"label": label, "tx_hash": sent.hash, "signer": sent.sender,
                         "receiver": sent.receiver, "nonce": sent.nonce});
    match &sent.submit {
        Err(e) => {
            out["validation_rejected"] = e.clone();
        }
        Ok(_) => {
            let fin = rpc.tx_final(&sent.hash, &sent.sender).await?;
            out["final"] = fin;
        }
    }
    Ok(out)
}

fn first_receipt_status(fin: &Value) -> Value {
    let tv = TxView::new(fin.clone());
    let rid = tv.first_receipt_id();
    tv.outcome(&rid)["outcome"]["status"].clone()
}

fn decision(fin: &Value) -> Value {
    let tv = TxView::new(fin.clone());
    let rid = tv.first_receipt_id();
    tv.success_json(&rid).unwrap_or(Value::Null)
}

async fn reviewer_prepare(m: &HashMap<String, String>) -> Result<()> {
    let rpc = loopback_rpc(need(m, "rpc")?)?;
    let node_home = PathBuf::from(need(m, "node-home")?);
    let reviewer = PathBuf::from(need(m, "reviewer-dir")?);
    let out = PathBuf::from(need(m, "out")?);
    let root = Key::from_file(&node_home.join("validator_key.json"))?;
    let owner_sk = SecretKey::from_random(KeyType::ED25519);
    save_key(&reviewer.join("owner.key.json"), OWNER, &owner_sk)?;
    let owner = Key::from_secret(OWNER, owner_sk);
    let absent = rpc
        .query_raw(json!({"request_type": "view_account", "account_id": MISSING}), &BlockRef::Final)
        .await?;
    if !absent.to_string().contains("UNKNOWN_ACCOUNT") {
        bail!("{MISSING} unexpectedly exists: {absent}");
    }
    let setup_owner = exec(
        &rpc,
        &root,
        OWNER,
        vec![act::create_account(), act::transfer(60 * NEAR), act::add_full_access_key(owner.near_public_key())],
        "reviewer_setup_owner",
    )
    .await?;
    let setup_alice = exec(&rpc, &root, ALICE, vec![act::create_account(), act::transfer(NEAR)], "reviewer_setup_alice_keyless").await?;
    let setup_attacker = exec(&rpc, &root, ATTACKER, vec![act::create_account(), act::transfer(NEAR)], "reviewer_setup_attacker_keyless").await?;
    for s in [&setup_owner, &setup_alice, &setup_attacker] {
        if s.get("final").is_none() {
            bail!("setup transaction rejected: {s}");
        }
    }
    write_json(
        &out,
        &json!({"schema": "g1-independent/prepare/v1", "owner": OWNER, "owner_public_key": owner.public_key(),
                "recipients_created": [ALICE], "attacker_created": ATTACKER,
                "missing_recipient": MISSING, "missing_absent_before": absent,
                "transactions": [setup_owner, setup_alice, setup_attacker]}),
    )
}

async fn reviewer_construct(m: &HashMap<String, String>) -> Result<()> {
    let rpc = loopback_rpc(need(m, "rpc")?)?;
    let reviewer = PathBuf::from(need(m, "reviewer-dir")?);
    let runner = PathBuf::from(need(m, "runner-dir")?);
    let out = PathBuf::from(need(m, "out")?);
    let wasm = std::fs::read(need(m, "wasm")?)?;
    let owner = Key::from_file(&reviewer.join("owner.key.json"))?;

    // Agent: code-free account with eight finite-allowance FunctionCall keys, created by the
    // owner. Only these secret keys ever leave the reviewer directory (into the runner dir).
    let mut agent_actions = vec![act::create_account(), act::transfer(5 * NEAR)];
    let mut agent_pks = vec![];
    for i in 0..AGENT_KEYS {
        let sk = SecretKey::from_random(KeyType::ED25519);
        agent_pks.push(sk.public_key().to_string());
        agent_actions.push(act::add_fc_key(sk.public_key(), VAULT, &["request_payment"], KEY_ALLOWANCE));
        save_key(&runner.join(format!("agent-key-{i}.json")), AGENT, &sk)?;
    }
    let create_agent = exec(&rpc, &owner, AGENT, agent_actions, "reviewer_create_agent").await?;

    // Vault: one keyless creation batch [CreateAccount, Transfer, DeployContract, new].
    let budget = 5 * NEAR;
    let max_per = 2 * NEAR;
    let k: u32 = 2;
    let recipients = [ALICE, MISSING];
    let status = rpc.status().await?;
    let chain_id = status["chain_id"].as_str().ok_or_else(|| anyhow!("chain_id"))?.to_string();
    let now_ns = json_u64(&rpc.final_block().await?["header"]["timestamp_nanosec"]);
    let expires = now_ns + 24 * 3600 * 1_000_000_000;
    let s_max = 100 + wasm.len() as u64 + STATE_ENTRY_MAX + u64::from(k) * PER_ADMISSION;
    let r_total = u128::from(s_max) * 10_000_000_000_000_000_000 + RESERVE_MARGIN;
    let funding = budget + r_total + NEAR;
    let init_args = json!({
        "agent": AGENT, "budget": budget.to_string(), "max_per_request": max_per.to_string(),
        "allowed_recipients": recipients, "expires_at_ns": expires.to_string(), "max_accepted_requests": k.to_string(),
    });
    let create_vault = exec(
        &rpc,
        &owner,
        VAULT,
        vec![act::create_account(), act::transfer(funding), act::deploy(&wasm), act::call("new", &init_args, 100, 0)],
        "reviewer_create_vault",
    )
    .await?;
    let fin = create_vault.get("final").ok_or_else(|| anyhow!("vault creation rejected: {create_vault}"))?;
    let returned = decision(fin);
    let independent = b58(&policy_hash(&PolicyInput {
        chain_id: &chain_id,
        vault: VAULT,
        owner: OWNER,
        agent: AGENT,
        budget,
        max_per_request: max_per,
        recipients: &recipients,
        expires_at_ns: expires,
        k,
    }));
    if returned.as_str() != Some(independent.as_str()) {
        bail!("policy hash mismatch: contract {returned} vs independent {independent}");
    }
    let public = json!({
        "schema": "g1-independent/construct/v1", "chain_id": chain_id, "vault": VAULT, "owner": OWNER,
        "agent": AGENT, "agent_public_keys": agent_pks, "recipients": recipients,
        "budget": budget.to_string(), "max_per_request": max_per.to_string(), "max_accepted_requests": k,
        "expires_at_ns": expires.to_string(), "funding": funding.to_string(), "storage_bound_bytes": s_max,
        "reserve_total": r_total.to_string(), "policy_hash": independent,
        "wasm_sha256": hex(&sha256(&[&wasm])), "transactions": [create_agent, create_vault],
    });
    write_json(&out, &public)?;
    // What the runner is allowed to know: public facts only.
    write_json(
        &runner.join("public-setup.json"),
        &json!({"vault": VAULT, "agent": AGENT, "policy_hash": independent, "recipients": recipients,
                "attacker": ATTACKER, "budget": budget.to_string(), "max_per_request": max_per.to_string(),
                "max_accepted_requests": k}),
    )
}

/// The untrusted agent workload. Runs inside the runner sandbox with agent FC keys only.
async fn runner_attack(m: &HashMap<String, String>) -> Result<()> {
    let rpc = loopback_rpc(need(m, "rpc")?)?;
    let runner = PathBuf::from(need(m, "runner-dir")?);
    let out = PathBuf::from(need(m, "out")?);
    let setup = read_json(&runner.join("public-setup.json"))?;
    let vault = setup["vault"].as_str().unwrap().to_string();
    let ph = setup["policy_hash"].as_str().unwrap().to_string();
    let keys: Vec<Key> = (0..AGENT_KEYS)
        .map(|i| Key::from_file(&runner.join(format!("agent-key-{i}.json"))))
        .collect::<Result<_>>()?;
    let req = |id: &str, to: &str, amount: u128| {
        json!({"request_id": id, "recipient": to, "amount": amount.to_string(), "policy_hash": ph})
    };
    // (label, intent, expected, key index, receiver, actions)
    let plan: Vec<(&str, &str, &str, usize, Value)> = vec![
        ("pay_1_alice_1near", "Legitimate payment within mandate", "Admitted; transfer succeeds", 0, req("1", ALICE, NEAR)),
        ("pay_2_missing_2near", "Legitimate request to an allowlisted account that does not exist", "Admitted; transfer fails; principal refunded; budget stays charged", 1, req("2", MISSING, 2 * NEAR)),
        ("replay_id_1", "Replay an already-paid request ID", "Denied DuplicateRequest", 2, req("1", ALICE, NEAR)),
        ("over_per_request_cap", "Exceed max_per_request by 1 yoctoNEAR", "Denied AboveMaxPerRequest", 3, req("3", ALICE, 2 * NEAR + 1)),
        ("exfiltrate_to_attacker", "Pay an account outside the allowlist", "Denied RecipientNotAllowed", 4, req("4", ATTACKER, NEAR)),
        ("refund_reuse_quota", "Spend the refunded 2 NEAR again after the record quota is used", "Denied RecordQuotaExhausted (budget charge is permanent)", 5, req("5", ALICE, 2 * NEAR)),
    ];
    let mut attempts = vec![];
    for (label, intent, expected, ki, args) in plan {
        let r = exec(&rpc, &keys[ki], &vault, vec![act::call("request_payment", &args, REQ_GAS_TGAS, 0)], label).await?;
        let mut e = json!({"label": label, "intent": intent, "expected": expected, "args": args, "result": r});
        if let Some(fin) = e["result"].get("final").cloned() {
            e["first_receipt_status"] = first_receipt_status(&fin);
            e["decision"] = decision(&fin);
        }
        eprintln!("[runner] {label}: {}", e["decision"]);
        attempts.push(e);
    }
    // A malformed request: canonical-parser failure must be a receipt failure with no effect.
    let bad = exec(
        &rpc,
        &keys[6],
        &vault,
        vec![act::call_raw(
            "request_payment",
            format!("{{\"request_id\":\"6\",\"recipient\":\"{ALICE}\",\"amount\":\"1e24\",\"policy_hash\":\"{ph}\"}}").into_bytes(),
            REQ_GAS_TGAS,
            0,
        )],
        "malformed_amount_exponent",
    )
    .await?;
    let mut be = json!({"label": "malformed_amount_exponent", "intent": "Non-canonical amount \"1e24\"",
                         "expected": "Receipt failure before admission; no state change", "result": bad});
    if let Some(fin) = be["result"].get("final").cloned() {
        be["first_receipt_status"] = first_receipt_status(&fin);
    }
    attempts.push(be);
    // Capability abuse that must be rejected before it reaches the chain.
    let k7 = &keys[7];
    let abuse = vec![
        ("agent_calls_freeze", vec![act::call("freeze", &json!({}), 30, 0)], vault.clone(), "Rejected: key restricted to request_payment"),
        ("agent_direct_transfer", vec![act::transfer(1)], vault.clone(), "Rejected: function-call key cannot transfer"),
        ("agent_attaches_deposit", vec![act::call("request_payment", &req("7", ALICE, NEAR), REQ_GAS_TGAS, 1)], vault.clone(), "Rejected: function-call key cannot attach deposit"),
        ("agent_calls_other_receiver", vec![act::call("request_payment", &req("8", ALICE, NEAR), REQ_GAS_TGAS, 0)], ALICE.to_string(), "Rejected: key restricted to the vault"),
    ];
    for (label, actions, receiver, expected) in abuse {
        let r = exec(&rpc, k7, &receiver, actions, label).await?;
        eprintln!("[runner] {label}: rejected={}", r.get("validation_rejected").is_some());
        attempts.push(json!({"label": label, "intent": "Use the agent key outside its permission", "expected": expected, "result": r}));
    }
    write_json(
        &out,
        &json!({"schema": "g1-independent/runner-log/v1", "trust": "UNTRUSTED runner output",
                "vault": vault, "policy_hash": ph, "attempts": attempts,
                "rpc_calls": rpc.calls.load(std::sync::atomic::Ordering::Relaxed)}),
    )
}

async fn reviewer_freeze(m: &HashMap<String, String>) -> Result<()> {
    let rpc = loopback_rpc(need(m, "rpc")?)?;
    let reviewer = PathBuf::from(need(m, "reviewer-dir")?);
    let out = PathBuf::from(need(m, "out")?);
    let owner = Key::from_file(&reviewer.join("owner.key.json"))?;
    let r = exec(&rpc, &owner, VAULT, vec![act::call("freeze", &json!({}), 30, 0)], "reviewer_freeze").await?;
    if r.get("final").is_none() {
        bail!("freeze rejected: {r}");
    }
    write_json(&out, &json!({"schema": "g1-independent/freeze/v1", "transaction": r}))
}

#[tokio::main]
async fn main() -> Result<()> {
    let (cmd, m) = args();
    match cmd.as_str() {
        "reviewer-prepare" => reviewer_prepare(&m).await,
        "reviewer-construct" => reviewer_construct(&m).await,
        "reviewer-freeze" => reviewer_freeze(&m).await,
        "runner-attack" => runner_attack(&m).await,
        _ => bail!("usage: g1_actor <reviewer-prepare|reviewer-construct|reviewer-freeze|runner-attack> --rpc URL ..."),
    }
}
