//! G1 sandbox harness: raw JSON-RPC client, sign-once transaction submission, FINAL
//! receipt-graph analysis, an independent policy encoder and an independent raw-state
//! decoder. Nothing here reuses the contract crate's code.

use anyhow::{anyhow, bail, Context, Result};
use base64::engine::general_purpose::STANDARD as B64;
use base64::Engine;
use near_crypto::{InMemorySigner, KeyType, SecretKey, Signer};
use near_primitives::action::Action;
use near_primitives::hash::CryptoHash;
use near_primitives::transaction::{SignedTransaction, Transaction, TransactionV0};
use near_primitives::types::AccountId;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

pub const NEAR: u128 = 1_000_000_000_000_000_000_000_000;
pub const TGAS: u64 = 1_000_000_000_000;
/// SPEC-V1.1 §6 observation deadline per attempt.
pub const FINAL_DEADLINE: Duration = Duration::from_secs(300);

// ------------------------------------------------------------------------------------
// Evidence
// ------------------------------------------------------------------------------------

pub struct Evidence {
    pub dir: PathBuf,
}

impl Evidence {
    pub fn new(dir: impl Into<PathBuf>) -> Result<Self> {
        let dir = dir.into();
        std::fs::create_dir_all(&dir)?;
        Ok(Self { dir })
    }

    pub fn write(&self, rel: &str, v: &Value) -> Result<PathBuf> {
        let p = self.dir.join(rel);
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let mut bytes = serde_json::to_vec_pretty(v)?;
        bytes.push(b'\n');
        std::fs::write(&p, bytes).with_context(|| format!("write {}", p.display()))?;
        Ok(p)
    }
}

// ------------------------------------------------------------------------------------
// JSON-RPC
// ------------------------------------------------------------------------------------

pub struct Rpc {
    pub url: String,
    http: reqwest::Client,
    pub calls: AtomicU64,
    pub bytes: AtomicU64,
    next_id: AtomicU64,
}

impl Rpc {
    pub fn new(url: &str) -> Self {
        Self {
            url: url.to_string(),
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(30))
                .build()
                .unwrap(),
            calls: AtomicU64::new(0),
            bytes: AtomicU64::new(0),
            next_id: AtomicU64::new(1),
        }
    }

    /// Full JSON-RPC response (either `result` or `error` present).
    pub async fn raw(&self, method: &str, params: Value) -> Result<Value> {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let body =
            json!({"jsonrpc": "2.0", "id": id.to_string(), "method": method, "params": params});
        let resp = self
            .http
            .post(&self.url)
            .json(&body)
            .send()
            .await
            .with_context(|| format!("rpc {method}"))?;
        let bytes = resp.bytes().await?;
        self.calls.fetch_add(1, Ordering::Relaxed);
        self.bytes.fetch_add(bytes.len() as u64, Ordering::Relaxed);
        Ok(serde_json::from_slice(&bytes).with_context(|| format!("rpc {method} json"))?)
    }

    pub async fn call(&self, method: &str, params: Value) -> Result<Value> {
        let r = self.raw(method, params).await?;
        match r.get("result") {
            Some(v) => Ok(v.clone()),
            None => bail!(
                "rpc {method} error: {}",
                r.get("error").cloned().unwrap_or(r.clone())
            ),
        }
    }

    pub async fn status(&self) -> Result<Value> {
        self.call("status", json!([])).await
    }

    pub async fn final_block(&self) -> Result<Value> {
        self.call("block", json!({"finality": "final"})).await
    }

    pub async fn block(&self, block_id: Value) -> Result<Value> {
        self.call("block", json!({"block_id": block_id})).await
    }

    pub async fn query(&self, mut params: Value, at: &BlockRef) -> Result<Value> {
        at.apply(&mut params);
        self.call("query", params).await
    }

    /// `query` returning the raw response so callers can inspect error kinds (e.g. UNKNOWN_ACCOUNT).
    pub async fn query_raw(&self, mut params: Value, at: &BlockRef) -> Result<Value> {
        at.apply(&mut params);
        self.raw("query", params).await
    }

    pub async fn view_account(&self, id: &str, at: &BlockRef) -> Result<Value> {
        self.query(
            json!({"request_type": "view_account", "account_id": id}),
            at,
        )
        .await
    }

    pub async fn view_access_key_list(&self, id: &str, at: &BlockRef) -> Result<Value> {
        self.query(
            json!({"request_type": "view_access_key_list", "account_id": id}),
            at,
        )
        .await
    }

    pub async fn view_access_key(&self, id: &str, pk: &str, at: &BlockRef) -> Result<Value> {
        self.query(
            json!({"request_type": "view_access_key", "account_id": id, "public_key": pk}),
            at,
        )
        .await
    }

    pub async fn view_code(&self, id: &str, at: &BlockRef) -> Result<Value> {
        self.query(json!({"request_type": "view_code", "account_id": id}), at)
            .await
    }

    pub async fn view_state(&self, id: &str, prefix: &[u8], at: &BlockRef) -> Result<Value> {
        self.query(
            json!({"request_type": "view_state", "account_id": id, "prefix_base64": B64.encode(prefix)}),
            at,
        )
        .await
    }

    /// Calls a view method and returns (parsed JSON result, full query response).
    pub async fn view_fn(
        &self,
        id: &str,
        method: &str,
        args: Value,
        at: &BlockRef,
    ) -> Result<(Value, Value)> {
        let r = self
            .query(
                json!({"request_type": "call_function", "account_id": id, "method_name": method,
                       "args_base64": B64.encode(args.to_string())}),
                at,
            )
            .await?;
        let bytes: Vec<u8> = r["result"]
            .as_array()
            .ok_or_else(|| anyhow!("call_function: no result bytes: {r}"))?
            .iter()
            .map(|b| b.as_u64().unwrap() as u8)
            .collect();
        Ok((serde_json::from_slice(&bytes)?, r))
    }

    pub async fn changes(
        &self,
        block_hash: &str,
        changes_type: &str,
        accounts: &[&str],
        prefix: Option<&[u8]>,
    ) -> Result<Value> {
        let mut p =
            json!({"block_id": block_hash, "changes_type": changes_type, "account_ids": accounts});
        if let Some(pre) = prefix {
            p["key_prefix_base64"] = json!(B64.encode(pre));
        }
        self.call("EXPERIMENTAL_changes", p).await
    }

    /// Polls `EXPERIMENTAL_tx_status(wait_until=FINAL)` for a known hash until FINAL or the deadline.
    pub async fn tx_final(&self, hash: &str, sender: &str) -> Result<Value> {
        let start = Instant::now();
        loop {
            let r = self
                .raw(
                    "EXPERIMENTAL_tx_status",
                    json!({"tx_hash": hash, "sender_account_id": sender, "wait_until": "FINAL"}),
                )
                .await?;
            if let Some(res) = r.get("result") {
                if res["final_execution_status"] == "FINAL" {
                    return Ok(res.clone());
                }
            }
            if start.elapsed() > FINAL_DEADLINE {
                bail!("tx {hash} not FINAL within deadline; last response {r}");
            }
            tokio::time::sleep(Duration::from_millis(250)).await;
        }
    }

    pub async fn wait_until_final_height(&self, h: u64) -> Result<Value> {
        loop {
            let b = self.final_block().await?;
            if b["header"]["height"].as_u64().unwrap_or(0) >= h {
                return Ok(b);
            }
            tokio::time::sleep(Duration::from_millis(200)).await;
        }
    }
}

#[derive(Clone, Debug)]
pub enum BlockRef {
    Final,
    Height(u64),
    Hash(String),
}

impl BlockRef {
    fn apply(&self, p: &mut Value) {
        match self {
            BlockRef::Final => p["finality"] = json!("final"),
            BlockRef::Height(h) => p["block_id"] = json!(h),
            BlockRef::Hash(h) => p["block_id"] = json!(h),
        }
    }
}

// ------------------------------------------------------------------------------------
// Keys and sign-once submission
// ------------------------------------------------------------------------------------

pub struct Key {
    pub account: AccountId,
    pub signer: Signer,
    nonce: Mutex<Option<u64>>,
}

impl Key {
    pub fn random(account: &str) -> Self {
        let sk = SecretKey::from_random(KeyType::ED25519);
        Self::from_secret(account, sk)
    }

    pub fn from_secret(account: &str, sk: SecretKey) -> Self {
        let account: AccountId = account.parse().expect("account id");
        Self {
            signer: InMemorySigner::from_secret_key(account.clone(), sk),
            account,
            nonce: Mutex::new(None),
        }
    }

    pub fn from_file(path: &Path) -> Result<Self> {
        let signer = InMemorySigner::from_file(path)?;
        let account = match &signer {
            Signer::InMemory(s) => s.account_id.clone(),
            _ => bail!("unexpected signer kind"),
        };
        Ok(Self {
            signer,
            account,
            nonce: Mutex::new(None),
        })
    }

    pub fn public_key(&self) -> String {
        self.signer.public_key().to_string()
    }

    pub fn near_public_key(&self) -> near_crypto::PublicKey {
        self.signer.public_key()
    }
}

/// Result of a single signed submission. The transaction is signed exactly once; a
/// transport failure never triggers a re-sign (SPEC-V1.1 §9: an RPC timeout cannot prove
/// no submission).
pub struct Sent {
    pub label: String,
    pub hash: String,
    pub sender: String,
    pub receiver: String,
    pub nonce: u64,
    /// `Ok(response)` when the node accepted the transaction; `Err(error JSON)` when it was
    /// rejected at validation (no on-chain trace).
    pub submit: std::result::Result<Value, Value>,
}

pub async fn sign_and_send(
    rpc: &Rpc,
    key: &Key,
    receiver: &str,
    actions: Vec<Action>,
    label: &str,
) -> Result<Sent> {
    let receiver_id: AccountId = receiver.parse()?;
    let nonce = {
        let cached = *key.nonce.lock().unwrap();
        match cached {
            Some(n) => n + 1,
            None => {
                let ak = rpc
                    .view_access_key(key.account.as_str(), &key.public_key(), &BlockRef::Final)
                    .await?;
                ak["nonce"].as_u64().ok_or_else(|| anyhow!("nonce"))? + 1
            }
        }
    };
    *key.nonce.lock().unwrap() = Some(nonce);
    let fb = rpc.final_block().await?;
    let block_hash: CryptoHash = fb["header"]["hash"]
        .as_str()
        .unwrap()
        .parse()
        .map_err(|e| anyhow!("{e:?}"))?;
    let tx = Transaction::V0(TransactionV0 {
        signer_id: key.account.clone(),
        public_key: key.near_public_key(),
        nonce,
        receiver_id,
        block_hash,
        actions,
    });
    let (hash, _) = tx.get_hash_and_size();
    let signature = key.signer.sign(hash.as_ref());
    let stx = SignedTransaction::new(signature, tx);
    let b64 = B64.encode(borsh::to_vec(&stx)?);
    let resp = rpc
        .raw(
            "send_tx",
            json!({"signed_tx_base64": b64, "wait_until": "INCLUDED"}),
        )
        .await;
    let submit = match resp {
        Ok(r) if r.get("error").is_some() => Err(r["error"].clone()),
        Ok(r) => Ok(r.get("result").cloned().unwrap_or(Value::Null)),
        // Transport failure: outcome unknown; caller must poll by hash, never re-sign.
        Err(e) => Ok(json!({"transport_error": e.to_string()})),
    };
    Ok(Sent {
        label: label.to_string(),
        hash: hash.to_string(),
        sender: key.account.to_string(),
        receiver: receiver.to_string(),
        nonce,
        submit,
    })
}

// ------------------------------------------------------------------------------------
// Actions
// ------------------------------------------------------------------------------------

pub mod act {
    use super::*;
    use near_primitives::account::{AccessKey, AccessKeyPermission, FunctionCallPermission};
    use near_primitives::action::{
        AddKeyAction, CreateAccountAction, DeployContractAction, FunctionCallAction, TransferAction,
    };
    use near_primitives::gas::Gas;
    use near_primitives::types::Balance;

    pub fn create_account() -> Action {
        Action::CreateAccount(CreateAccountAction {})
    }
    pub fn transfer(yocto: u128) -> Action {
        Action::Transfer(TransferAction {
            deposit: Balance::from_yoctonear(yocto),
        })
    }
    pub fn deploy(code: &[u8]) -> Action {
        Action::DeployContract(DeployContractAction {
            code: code.to_vec(),
        })
    }
    pub fn call_raw(method: &str, args: Vec<u8>, gas_tgas: u64, deposit: u128) -> Action {
        Action::FunctionCall(Box::new(FunctionCallAction {
            method_name: method.to_string(),
            args,
            gas: Gas::from_gas(gas_tgas * TGAS),
            deposit: Balance::from_yoctonear(deposit),
        }))
    }
    pub fn call(method: &str, args: &Value, gas_tgas: u64, deposit: u128) -> Action {
        call_raw(method, args.to_string().into_bytes(), gas_tgas, deposit)
    }
    pub fn add_full_access_key(pk: near_crypto::PublicKey) -> Action {
        Action::AddKey(Box::new(AddKeyAction {
            public_key: pk,
            access_key: AccessKey {
                nonce: 0,
                permission: AccessKeyPermission::FullAccess,
            },
        }))
    }
    pub fn add_fc_key(
        pk: near_crypto::PublicKey,
        receiver: &str,
        methods: &[&str],
        allowance: u128,
    ) -> Action {
        Action::AddKey(Box::new(AddKeyAction {
            public_key: pk,
            access_key: AccessKey {
                nonce: 0,
                permission: AccessKeyPermission::FunctionCall(FunctionCallPermission {
                    allowance: Some(Balance::from_yoctonear(allowance)),
                    receiver_id: receiver.to_string(),
                    method_names: methods.iter().map(|m| m.to_string()).collect(),
                }),
            },
        }))
    }
}

// ------------------------------------------------------------------------------------
// FINAL outcome analysis
// ------------------------------------------------------------------------------------

/// Parsed `EXPERIMENTAL_tx_status(FINAL)` response.
pub struct TxView {
    pub raw: Value,
    pub receipts: HashMap<String, Value>,
    pub outcomes: HashMap<String, Value>,
}

impl TxView {
    pub fn new(raw: Value) -> Self {
        let mut receipts = HashMap::new();
        for r in raw["receipts"].as_array().cloned().unwrap_or_default() {
            receipts.insert(r["receipt_id"].as_str().unwrap_or_default().to_string(), r);
        }
        let mut outcomes = HashMap::new();
        for o in raw["receipts_outcome"]
            .as_array()
            .cloned()
            .unwrap_or_default()
        {
            outcomes.insert(o["id"].as_str().unwrap_or_default().to_string(), o);
        }
        Self {
            raw,
            receipts,
            outcomes,
        }
    }

    pub fn tx_hash(&self) -> String {
        self.raw["transaction"]["hash"]
            .as_str()
            .unwrap_or_default()
            .to_string()
    }

    /// The receipt the transaction converted into (executes on the receiver).
    pub fn first_receipt_id(&self) -> String {
        self.raw["transaction_outcome"]["outcome"]["receipt_ids"][0]
            .as_str()
            .unwrap_or_default()
            .to_string()
    }

    pub fn outcome(&self, receipt_id: &str) -> &Value {
        &self.outcomes[receipt_id]["outcome"]
    }

    pub fn block_hash_of(&self, receipt_id: &str) -> String {
        self.outcomes[receipt_id]["block_hash"]
            .as_str()
            .unwrap_or_default()
            .to_string()
    }

    pub fn is_success(&self, receipt_id: &str) -> bool {
        let s = &self.outcome(receipt_id)["status"];
        s.get("SuccessValue").is_some() || s.get("SuccessReceiptId").is_some()
    }

    pub fn failure(&self, receipt_id: &str) -> Option<&Value> {
        self.outcome(receipt_id)["status"].get("Failure")
    }

    pub fn success_json(&self, receipt_id: &str) -> Option<Value> {
        let v = self.outcome(receipt_id)["status"]
            .get("SuccessValue")?
            .as_str()?;
        let bytes = B64.decode(v).ok()?;
        serde_json::from_slice(&bytes).ok()
    }

    pub fn actions(&self, receipt_id: &str) -> Vec<Value> {
        self.receipts
            .get(receipt_id)
            .and_then(|r| r["receipt"]["Action"]["actions"].as_array().cloned())
            .unwrap_or_default()
    }

    /// Receipts created by `predecessor` (application receipts when predecessor = vault).
    pub fn receipts_from(&self, predecessor: &str) -> Vec<&Value> {
        let mut v: Vec<&Value> = self
            .receipts
            .values()
            .filter(|r| r["predecessor_id"] == predecessor)
            .collect();
        v.sort_by_key(|r| r["receipt_id"].as_str().unwrap_or_default().to_string());
        v
    }

    pub fn events(&self, receipt_id: &str) -> Vec<Value> {
        self.outcome(receipt_id)["logs"]
            .as_array()
            .cloned()
            .unwrap_or_default()
            .iter()
            .filter_map(|l| {
                l.as_str()?
                    .strip_prefix("EVENT_JSON:")
                    .map(|s| serde_json::from_str(s).ok())
            })
            .flatten()
            .collect()
    }

    /// Every receipt ID referenced by outcomes must have an outcome, and every outcome a body.
    pub fn graph_closure(&self) -> Value {
        let mut missing_outcomes = vec![];
        let mut missing_bodies = vec![];
        let mut refs: Vec<String> = self.raw["transaction_outcome"]["outcome"]["receipt_ids"]
            .as_array()
            .cloned()
            .unwrap_or_default()
            .iter()
            .map(|x| x.as_str().unwrap().to_string())
            .collect();
        for o in self.outcomes.values() {
            for r in o["outcome"]["receipt_ids"]
                .as_array()
                .cloned()
                .unwrap_or_default()
            {
                refs.push(r.as_str().unwrap().to_string());
            }
        }
        for r in &refs {
            if !self.outcomes.contains_key(r) {
                missing_outcomes.push(r.clone());
            }
        }
        for id in self.outcomes.keys() {
            if !self.receipts.contains_key(id) {
                missing_bodies.push(id.clone());
            }
        }
        json!({"referenced": refs.len(), "outcomes": self.outcomes.len(), "bodies": self.receipts.len(),
               "missing_outcomes": missing_outcomes, "missing_bodies": missing_bodies})
    }
}

pub fn action_kind(a: &Value) -> String {
    match a {
        Value::String(s) => s.clone(),
        Value::Object(m) => m.keys().next().cloned().unwrap_or_default(),
        _ => "?".into(),
    }
}

pub fn json_u128(v: &Value) -> u128 {
    match v {
        Value::String(s) => s.parse().unwrap_or(u128::MAX),
        Value::Number(n) => n.as_u64().map(u128::from).unwrap_or(u128::MAX),
        _ => u128::MAX,
    }
}

pub fn json_u64(v: &Value) -> u64 {
    match v {
        Value::String(s) => s.parse().unwrap_or(u64::MAX),
        Value::Number(n) => n.as_u64().unwrap_or(u64::MAX),
        _ => u64::MAX,
    }
}

// ------------------------------------------------------------------------------------
// Independent policy encoder (SPEC-V1.1 §3), written separately from the contract.
// ------------------------------------------------------------------------------------

pub const POLICY_DOMAIN: &[u8] = b"near-agent-vault-lab/mandate/v1\0";
pub const REQUEST_DOMAIN: &[u8] = b"near-agent-vault-lab/request/v1\0";

fn put_str(v: &mut Vec<u8>, s: &str) {
    v.extend_from_slice(&(s.len() as u32).to_le_bytes());
    v.extend_from_slice(s.as_bytes());
}

pub struct PolicyInput<'a> {
    pub chain_id: &'a str,
    pub vault: &'a str,
    pub owner: &'a str,
    pub agent: &'a str,
    pub budget: u128,
    pub max_per_request: u128,
    pub recipients: &'a [&'a str],
    pub expires_at_ns: u64,
    pub k: u32,
}

pub fn policy_body(p: &PolicyInput) -> Vec<u8> {
    let mut v = Vec::new();
    put_str(&mut v, p.chain_id);
    put_str(&mut v, p.vault);
    put_str(&mut v, p.owner);
    put_str(&mut v, p.agent);
    v.push(0); // asset NativeNear
    v.extend_from_slice(&p.budget.to_le_bytes());
    v.extend_from_slice(&p.max_per_request.to_le_bytes());
    v.extend_from_slice(&(p.recipients.len() as u32).to_le_bytes());
    for r in p.recipients {
        put_str(&mut v, r);
    }
    v.extend_from_slice(&p.expires_at_ns.to_le_bytes());
    v.extend_from_slice(&p.k.to_le_bytes());
    v
}

pub fn sha256(parts: &[&[u8]]) -> [u8; 32] {
    let mut h = Sha256::new();
    for p in parts {
        h.update(p);
    }
    h.finalize().into()
}

pub fn policy_hash(p: &PolicyInput) -> [u8; 32] {
    sha256(&[POLICY_DOMAIN, &policy_body(p)])
}

pub fn request_digest(
    vault: &str,
    ph: &[u8; 32],
    agent: &str,
    id: u64,
    recipient: &str,
    amount: u128,
) -> [u8; 32] {
    let mut v = Vec::new();
    put_str(&mut v, vault);
    v.extend_from_slice(ph);
    put_str(&mut v, agent);
    v.extend_from_slice(&id.to_le_bytes());
    put_str(&mut v, recipient);
    v.extend_from_slice(&amount.to_le_bytes());
    sha256(&[REQUEST_DOMAIN, &v])
}

pub fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

pub fn b58(b: &[u8]) -> String {
    bs58::encode(b).into_string()
}

// ------------------------------------------------------------------------------------
// Independent raw-state decoder (layout documented in docs/G1_CONTRACT_RESULT.md).
// ------------------------------------------------------------------------------------

struct Rd<'a>(&'a [u8], usize);
impl<'a> Rd<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8]> {
        let s = self
            .0
            .get(self.1..self.1 + n)
            .ok_or_else(|| anyhow!("short state"))?;
        self.1 += n;
        Ok(s)
    }
    fn u8(&mut self) -> Result<u8> {
        Ok(self.take(1)?[0])
    }
    fn u32(&mut self) -> Result<u32> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into()?))
    }
    fn u64(&mut self) -> Result<u64> {
        Ok(u64::from_le_bytes(self.take(8)?.try_into()?))
    }
    fn u128(&mut self) -> Result<u128> {
        Ok(u128::from_le_bytes(self.take(16)?.try_into()?))
    }
    fn string(&mut self) -> Result<String> {
        let n = self.u32()? as usize;
        Ok(String::from_utf8(self.take(n)?.to_vec())?)
    }
}

/// Decode the `STATE` value into JSON with decimal-string integers.
pub fn decode_state(bytes: &[u8]) -> Result<Value> {
    let mut r = Rd(bytes, 0);
    let chain_id = r.string()?;
    let vault = r.string()?;
    let owner = r.string()?;
    let agent = r.string()?;
    let asset = r.u8()?;
    let budget = r.u128()?;
    let max_per_request = r.u128()?;
    let n = r.u32()?;
    let mut recipients = vec![];
    for _ in 0..n {
        recipients.push(r.string()?);
    }
    let expires_at_ns = r.u64()?;
    let k = r.u32()?;
    let policy_hash = r.take(32)?.to_vec();
    let storage_bound_bytes = r.u64()?;
    let reserve_total = r.u128()?;
    let charged = r.u128()?;
    let cb_s = r.u128()?;
    let cb_f = r.u128()?;
    let frozen = r.u8()?;
    let accepted_count = r.u32()?;
    let seq = r.u64()?;
    if r.1 != bytes.len() {
        bail!("trailing bytes in STATE: {} of {}", r.1, bytes.len());
    }
    Ok(json!({
        "chain_id": chain_id, "vault": vault, "owner": owner, "agent": agent, "asset": asset,
        "budget": budget.to_string(), "max_per_request": max_per_request.to_string(),
        "allowed_recipients": recipients, "expires_at_ns": expires_at_ns.to_string(),
        "max_accepted_requests": k, "policy_hash": b58(&policy_hash),
        "storage_bound_bytes": storage_bound_bytes.to_string(), "reserve_total": reserve_total.to_string(),
        "charged": charged.to_string(), "cb_succeeded_amount": cb_s.to_string(),
        "cb_failed_amount": cb_f.to_string(), "frozen": frozen == 1,
        "accepted_count": accepted_count, "seq": seq.to_string(),
    }))
}

/// Decode a `b'r' || u64 LE id` record value.
pub fn decode_record(bytes: &[u8]) -> Result<Value> {
    let mut r = Rd(bytes, 0);
    let recipient_index = r.u8()?;
    let amount = r.u128()?;
    let admission_seq = r.u64()?;
    let status = match r.u8()? {
        0 => "Pending",
        1 => "CbSucceeded",
        2 => "CbFailed",
        x => bail!("bad status {x}"),
    };
    if r.1 != bytes.len() {
        bail!("trailing bytes in record");
    }
    Ok(
        json!({"recipient_index": recipient_index, "amount": amount.to_string(),
              "admission_seq": admission_seq.to_string(), "callback_status": status}),
    )
}

pub fn b64d(s: &str) -> Vec<u8> {
    B64.decode(s).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    // Independent re-check of SPEC-V1.1 TV1 with this crate's own encoder.
    #[test]
    fn independent_encoder_matches_tv1() {
        let p = PolicyInput {
            chain_id: "localnet",
            vault: "vault.owner.test.near",
            owner: "owner.test.near",
            agent: "agent.owner.test.near",
            budget: 5 * NEAR,
            max_per_request: 2 * NEAR,
            recipients: &["recipient.test.near"],
            expires_at_ns: 1_798_761_600_000_000_000,
            k: 64,
        };
        let h = policy_hash(&p);
        assert_eq!(
            hex(&h),
            "fb3a6d4aa6755c36304fafceaa998ad51939bf83f3cf7a501e968e21c6ca3127"
        );
        assert_eq!(
            hex(&request_digest(
                p.vault,
                &h,
                p.agent,
                2,
                "recipient.test.near",
                2 * NEAR
            )),
            "b3811fe8c34565f87141c8af6b1b7ea59a26b5eab5d32fb658a2531221e9bdc7"
        );
    }
}
