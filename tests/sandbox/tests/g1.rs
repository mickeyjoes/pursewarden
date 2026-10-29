//! G1 vault + sandbox feasibility scenario (SPEC-V1.1, Phase0_E §3 steps 2-3).
//!
//! Requires a fresh node started by `scripts/sandbox-setup/start-node.sh <run-id>`:
//!   G1_RUN_ID=<run-id> cargo test -p g1-sandbox-tests --test g1 -- --nocapture
//! Optional: G1_RPC_URL (default http://127.0.0.1:3130), G1_WASM.
//!
//! Every check is recorded in evidence/g1/<run-id>/checks.json with its supporting data. A
//! failed CRITICAL check writes the evidence collected so far and stops the run.

use anyhow::{anyhow, Result};
use g1_sandbox_tests::*;
use serde_json::{json, Value};
use std::path::PathBuf;
use std::time::Instant;

const OWNER: &str = "owner.test.near";
const ALICE: &str = "alice.test.near";
const BOB: &str = "bob.test.near";
const MISSING: &str = "missing.test.near";
const VAULT: &str = "vault.owner.test.near";
const AGENT: &str = "agent.owner.test.near";
const VAULT2: &str = "vault2.owner.test.near";
const AGENT2: &str = "agent2.owner.test.near";
const REQ_GAS_TGAS: u64 = 100;
const CALLBACK_GAS: u64 = 20 * TGAS;
const AGENT_KEYS: usize = 8;
const KEY_ALLOWANCE: u128 = NEAR / 4;
const RESERVE_MARGIN: u128 = 10_000_000_000_000_000_000_000;
const STATE_ENTRY_MAX: u64 = 5 + 1024 + 40;
const PER_ADMISSION: u64 = 128;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap()
}

struct Ctx {
    rpc: Rpc,
    ev: Evidence,
    checks: Vec<Value>,
    txs: Vec<Value>,
    balance_log: Vec<Value>,
    started: Instant,
}

impl Ctx {
    fn check(&mut self, id: &str, critical: bool, ok: bool, detail: Value) -> bool {
        println!(
            "[{}] {}{}",
            if ok { "PASS" } else { "FAIL" },
            id,
            if critical { " (critical)" } else { "" }
        );
        if !ok {
            println!("    detail: {detail}");
        }
        self.checks.push(json!({"id": id, "critical": critical, "result": if ok {"PASS"} else {"FAIL"}, "detail": detail}));
        if !ok && critical {
            self.flush().ok();
            panic!(
                "STOP: critical invariant {id} failed; evidence written to {}",
                self.ev.dir.display()
            );
        }
        ok
    }

    fn flush(&self) -> Result<()> {
        let passed = self.checks.iter().filter(|c| c["result"] == "PASS").count();
        self.ev.write(
            "checks.json",
            &json!({"total": self.checks.len(), "passed": passed, "failed": self.checks.len() - passed, "checks": self.checks}),
        )?;
        self.ev.write("transactions.json", &json!(self.txs))?;
        self.ev
            .write("balance_log.json", &json!(self.balance_log))?;
        Ok(())
    }

    async fn send(
        &mut self,
        key: &Key,
        receiver: &str,
        actions: Vec<near_primitives::action::Action>,
        label: &str,
    ) -> Result<Sent> {
        sign_and_send(&self.rpc, key, receiver, actions, label).await
    }

    /// Submit, require acceptance, wait for FINAL, store the raw outcome and a summary row.
    async fn exec(
        &mut self,
        key: &Key,
        receiver: &str,
        actions: Vec<near_primitives::action::Action>,
        label: &str,
    ) -> Result<TxView> {
        let sent = self.send(key, receiver, actions, label).await?;
        if let Err(e) = &sent.submit {
            let timeout = e.to_string().contains("TIMEOUT_ERROR");
            if !timeout {
                return Err(anyhow!("{label}: transaction rejected at submission: {e}"));
            }
        }
        let raw = self.rpc.tx_final(&sent.hash, &sent.sender).await?;
        let file = format!("txs/{}.json", label);
        self.ev.write(&file, &raw)?;
        let tv = TxView::new(raw);
        let mut receipts = vec![];
        for (id, o) in &tv.outcomes {
            let body = tv.receipts.get(id);
            receipts.push(json!({
                "receipt_id": id,
                "predecessor": body.map(|b| b["predecessor_id"].clone()),
                "receiver": body.map(|b| b["receiver_id"].clone()),
                "actions": tv.actions(id).iter().map(action_kind).collect::<Vec<_>>(),
                "executor": o["outcome"]["executor_id"],
                "status": status_kind(&o["outcome"]["status"]),
                "block_hash": o["block_hash"],
                "gas_burnt": o["outcome"]["gas_burnt"],
            }));
        }
        receipts.sort_by_key(|r| r["receipt_id"].as_str().unwrap_or_default().to_string());
        self.txs.push(json!({
            "label": label, "tx_hash": sent.hash, "sender": sent.sender, "receiver": sent.receiver, "nonce": sent.nonce,
            "tx_block_hash": tv.raw["transaction_outcome"]["block_hash"], "first_receipt_id": tv.first_receipt_id(),
            "final_execution_status": tv.raw["final_execution_status"], "evidence_file": file,
            "graph_closure": tv.graph_closure(), "receipts": receipts,
        }));
        Ok(tv)
    }

    async fn mandate(&self, vault: &str) -> Result<Value> {
        Ok(self
            .rpc
            .view_fn(vault, "get_mandate", json!({}), &BlockRef::Final)
            .await?
            .0)
    }

    async fn log_balance(&mut self, vault: &str, label: &str) -> Result<()> {
        let acct = self.rpc.view_account(vault, &BlockRef::Final).await?;
        let m = self.mandate(vault).await?;
        self.balance_log.push(json!({
            "label": label, "vault": vault, "block_height": acct["block_height"], "block_hash": acct["block_hash"],
            "amount": acct["amount"], "storage_usage": acct["storage_usage"],
            "charged": m["charged"], "seq": m["seq"], "accepted_count": m["accepted_count"],
        }));
        Ok(())
    }

    /// Contract data vs balance: a failed vault receipt must leave no contract-data change;
    /// its balance effect (gas reward) is recorded separately.
    async fn state_effects_of(&self, tv: &TxView, vault: &str) -> Result<Value> {
        let rid = tv.first_receipt_id();
        let bh = tv.block_hash_of(&rid);
        let caused = |v: &Value| -> Vec<Value> {
            v["changes"]
                .as_array()
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .filter(|c| c["cause"]["receipt_hash"] == rid.as_str())
                .collect()
        };
        let data = self
            .rpc
            .changes(&bh, "data_changes", &[vault], Some(b""))
            .await?;
        let acct = self
            .rpc
            .changes(&bh, "account_changes", &[vault], None)
            .await?;
        Ok(json!({
            "receipt_id": rid, "block_hash": bh,
            "data_changes_from_receipt": caused(&data),
            "account_changes_from_receipt": caused(&acct)
                .iter()
                .map(|c| json!({"cause": c["cause"]["type"], "amount": c["change"]["amount"]}))
                .collect::<Vec<_>>(),
        }))
    }
}

fn status_kind(s: &Value) -> String {
    match s {
        Value::Object(m) => m.keys().next().cloned().unwrap_or_default(),
        Value::String(x) => x.clone(),
        _ => "?".into(),
    }
}

fn find_key<'a>(v: &'a Value, key: &str) -> Option<&'a Value> {
    match v {
        Value::Object(m) => m
            .get(key)
            .or_else(|| m.values().find_map(|x| find_key(x, key))),
        Value::Array(a) => a.iter().find_map(|x| find_key(x, key)),
        _ => None,
    }
}

fn req_args(id: &str, recipient: &str, amount: u128, ph: &str) -> Value {
    json!({"request_id": id, "recipient": recipient, "amount": amount.to_string(), "policy_hash": ph})
}

fn predicted_reserve(code_len: usize, k: u32) -> (u64, u128) {
    let s_max = 100 + code_len as u64 + STATE_ENTRY_MAX + u64::from(k) * PER_ADMISSION;
    (
        s_max,
        u128::from(s_max) * 10_000_000_000_000_000_000 + RESERVE_MARGIN,
    )
}

#[tokio::test(flavor = "multi_thread")]
async fn g1_vault_feasibility() -> Result<()> {
    let run_id =
        std::env::var("G1_RUN_ID").expect("set G1_RUN_ID to the run id passed to start-node.sh");
    let root = repo_root();
    let rpc_url = std::env::var("G1_RPC_URL").unwrap_or_else(|_| "http://127.0.0.1:3130".into());
    let wasm_path = std::env::var("G1_WASM")
        .map(PathBuf::from)
        .unwrap_or_else(|_| root.join("artifacts/near_agent_vault.wasm"));
    let node_home = root.join(".sandbox").join(&run_id);
    let mut cx = Ctx {
        rpc: Rpc::new(&rpc_url),
        ev: Evidence::new(root.join("evidence/g1").join(&run_id))?,
        checks: vec![],
        txs: vec![],
        balance_log: vec![],
        started: Instant::now(),
    };

    // ---------------------------------------------------------------- identity
    let status = cx.rpc.status().await?;
    let genesis = cx.rpc.call("genesis_config", json!({})).await?;
    let protocol = cx
        .rpc
        .call("EXPERIMENTAL_protocol_config", json!({"finality": "final"}))
        .await?;
    let client_cfg = cx.rpc.call("client_config", json!([])).await?;
    let h0 = cx.rpc.final_block().await?;
    cx.ev.write("node/status.json", &status)?;
    cx.ev.write("node/genesis_config.json", &genesis)?;
    cx.ev.write("node/protocol_config.json", &protocol)?;
    cx.ev
        .write("node/client_config_at_test_start.json", &client_cfg)?;
    cx.ev.write("node/h0_block.json", &h0)?;
    let chain_id = status["chain_id"].as_str().unwrap().to_string();
    let start_status: Value =
        serde_json::from_slice(&std::fs::read(cx.ev.dir.join("node/status-at-start.json"))?)?;
    cx.check(
        "node.identity_stable",
        true,
        start_status["result"]["genesis_hash"] == status["genesis_hash"] && start_status["result"]["chain_id"] == status["chain_id"],
        json!({"chain_id": chain_id, "genesis_hash": status["genesis_hash"], "at_start": start_status["result"]["genesis_hash"]}),
    );
    cx.check(
        "node.version_2_13_4_pv86",
        true,
        status["version"]["version"] == "2.13.4" && status["protocol_version"] == 86,
        json!({"version": status["version"], "protocol_version": status["protocol_version"]}),
    );
    cx.check(
        "node.retention_config",
        true,
        client_cfg["archive"] == false
            && client_cfg["save_tx_outcomes"] == true
            && client_cfg["save_receipt_to_tx"] == true
            && client_cfg["save_state_changes"] == true
            && client_cfg["epoch_length"] == 100000
            && client_cfg["tracked_shards_config"] == "AllShards",
        json!({"archive": client_cfg["archive"], "epoch_length": client_cfg["epoch_length"], "gc": client_cfg["gc"],
               "save_tx_outcomes": client_cfg["save_tx_outcomes"], "save_receipt_to_tx": client_cfg["save_receipt_to_tx"],
               "save_state_changes": client_cfg["save_state_changes"]}),
    );
    let per_byte = find_key(&protocol, "storage_amount_per_byte")
        .cloned()
        .unwrap_or(Value::Null);
    let extra = find_key(&protocol, "num_extra_bytes_record")
        .cloned()
        .unwrap_or(Value::Null);
    let acct_bytes = find_key(&protocol, "num_bytes_account")
        .cloned()
        .unwrap_or(Value::Null);
    cx.check(
        "runtime.storage_params_match_contract_constants",
        true,
        json_u128(&per_byte) == 10_000_000_000_000_000_000 && json_u64(&extra) == 40 && json_u64(&acct_bytes) == 100,
        json!({"storage_amount_per_byte": per_byte, "num_extra_bytes_record": extra, "num_bytes_account": acct_bytes,
               "contract_assumes": {"byte_cost": "10000000000000000000", "extra_bytes_record": 40, "account_bytes": 100}}),
    );
    let shard_layout = find_key(&protocol, "shard_layout")
        .cloned()
        .unwrap_or(Value::Null);

    // ---------------------------------------------------------------- artifact
    let wasm = std::fs::read(&wasm_path)?;
    let wasm_sha = sha256(&[&wasm]);
    let code_hash_b58 = b58(&wasm_sha);
    println!(
        "wasm {} bytes sha256 {} code_hash {}",
        wasm.len(),
        hex(&wasm_sha),
        code_hash_b58
    );
    let recorded = std::fs::read_to_string(root.join("artifacts/near_agent_vault.wasm.sha256"))
        .unwrap_or_default();
    let inspect: Value = serde_json::from_slice(&std::fs::read(
        root.join("artifacts/near_agent_vault.inspect.json"),
    )?)?;
    cx.check(
        "artifact.hash_matches_recorded_and_capability_gate_passed",
        true,
        recorded.split_whitespace().next() == Some(hex(&wasm_sha).as_str())
            && inspect["sha256_hex"] == hex(&wasm_sha).as_str()
            && inspect["verdict"] == "PASS",
        json!({"sha256_hex": hex(&wasm_sha), "recorded": recorded.trim(), "inspect_verdict": inspect["verdict"],
               "imports": inspect["imports"], "exports": inspect["exports"]}),
    );

    // ---------------------------------------------------------------- reviewer setup (root)
    let rootk = Key::from_file(&node_home.join("validator_key.json"))?;
    let owner = Key::random(OWNER);
    let bob = Key::random(BOB);
    let absent_before = cx
        .rpc
        .query_raw(
            json!({"request_type": "view_account", "account_id": MISSING}),
            &BlockRef::Final,
        )
        .await?;
    cx.check(
        "setup.missing_recipient_absent_before",
        true,
        absent_before.to_string().contains("UNKNOWN_ACCOUNT"),
        absent_before.clone(),
    );
    cx.exec(
        &rootk,
        OWNER,
        vec![
            act::create_account(),
            act::transfer(60 * NEAR),
            act::add_full_access_key(owner.near_public_key()),
        ],
        "setup_owner",
    )
    .await?;
    cx.exec(
        &rootk,
        ALICE,
        vec![act::create_account(), act::transfer(NEAR)],
        "setup_alice_keyless_recipient",
    )
    .await?;
    cx.exec(
        &rootk,
        BOB,
        vec![
            act::create_account(),
            act::transfer(5 * NEAR),
            act::add_full_access_key(bob.near_public_key()),
        ],
        "setup_bob_stranger",
    )
    .await?;

    // ---------------------------------------------------------------- agent (code-free, FC keys only)
    let agent_keys: Vec<Key> = (0..AGENT_KEYS).map(|_| Key::random(AGENT)).collect();
    let mut actions = vec![act::create_account(), act::transfer(5 * NEAR)];
    for k in &agent_keys {
        actions.push(act::add_fc_key(
            k.near_public_key(),
            VAULT,
            &["request_payment"],
            KEY_ALLOWANCE,
        ));
    }
    cx.exec(&owner, AGENT, actions, "create_agent").await?;

    // ---------------------------------------------------------------- vault: keyless creation batch
    let budget = 5 * NEAR;
    let max_per = 2 * NEAR;
    let k: u32 = 2;
    let recipients = [ALICE, MISSING];
    let now_ns = json_u64(&cx.rpc.final_block().await?["header"]["timestamp_nanosec"]);
    let expires = now_ns + 24 * 3600 * 1_000_000_000;
    let (s_pred, r_pred) = predicted_reserve(wasm.len(), k);
    let funding = budget + r_pred + NEAR;
    let init_args = json!({
        "agent": AGENT, "budget": budget.to_string(), "max_per_request": max_per.to_string(),
        "allowed_recipients": recipients, "expires_at_ns": expires.to_string(), "max_accepted_requests": k.to_string(),
    });
    let create = cx
        .exec(
            &owner,
            VAULT,
            vec![
                act::create_account(),
                act::transfer(funding),
                act::deploy(&wasm),
                act::call("new", &init_args, 100, 0),
            ],
            "create_vault",
        )
        .await?;
    let rid = create.first_receipt_id();
    let acts = create.actions(&rid);
    let kinds: Vec<String> = acts.iter().map(action_kind).collect();
    let deploy_hash_b64 = acts
        .get(2)
        .and_then(|a| a["DeployContract"]["code"].as_str())
        .unwrap_or_default()
        .to_string();
    let fc = acts
        .get(3)
        .map(|a| a["FunctionCall"].clone())
        .unwrap_or(Value::Null);
    cx.check(
        "construction.single_batch_create_transfer_deploy_init",
        true,
        create.is_success(&rid)
            && kinds == ["CreateAccount", "Transfer", "DeployContract", "FunctionCall"]
            && json_u128(&acts[1]["Transfer"]["deposit"]) == funding
            && b64d(&deploy_hash_b64) == wasm_sha.to_vec()
            && fc["method_name"] == "new"
            && json_u128(&fc["deposit"]) == 0
            && !kinds.iter().any(|k| k == "AddKey"),
        json!({"tx": create.tx_hash(), "receipt": rid, "actions": kinds, "deploy_code_hash_b64": deploy_hash_b64,
               "status": create.outcome(&rid)["status"]}),
    );
    let creation_block = create.block_hash_of(&rid);
    let creation_height = json_u64(&cx.rpc.block(json!(creation_block)).await?["header"]["height"]);
    let expected_ph = policy_hash(&PolicyInput {
        chain_id: &chain_id,
        vault: VAULT,
        owner: OWNER,
        agent: AGENT,
        budget,
        max_per_request: max_per,
        recipients: &recipients,
        expires_at_ns: expires,
        k,
    });
    let ph = b58(&expected_ph);
    cx.check(
        "construction.policy_hash_matches_independent_encoding",
        true,
        create.success_json(&rid) == Some(json!(ph)),
        json!({"contract_returned": create.success_json(&rid), "independent": ph, "independent_hex": hex(&expected_ph),
               "observed_chain_id": chain_id}),
    );
    let keys_at_creation = cx
        .rpc
        .view_access_key_list(VAULT, &BlockRef::Hash(creation_block.clone()))
        .await?;
    cx.check(
        "construction.vault_zero_keys_at_creation_block",
        true,
        keys_at_creation["keys"].as_array().map(|a| a.is_empty()) == Some(true),
        keys_at_creation.clone(),
    );
    let acct = cx.rpc.view_account(VAULT, &BlockRef::Final).await?;
    let code = cx.rpc.view_code(VAULT, &BlockRef::Final).await?;
    cx.check(
        "construction.deployed_code_is_artifact",
        true,
        acct["code_hash"] == code_hash_b58.as_str() && b64d(code["code_base64"].as_str().unwrap_or("")) == wasm,
        json!({"code_hash": acct["code_hash"], "expected": code_hash_b58, "view_code_hash": code["hash"]}),
    );
    let m0 = cx.mandate(VAULT).await?;
    cx.ev.write("state/vault_mandate_after_init.json", &m0)?;
    cx.check(
        "construction.mandate_initialized_as_specified",
        true,
        m0["policy_hash"] == ph.as_str()
            && m0["owner"] == OWNER
            && m0["agent"] == AGENT
            && m0["chain_id"] == chain_id.as_str()
            && json_u128(&m0["budget"]) == budget
            && json_u128(&m0["max_per_request"]) == max_per
            && m0["allowed_recipients"] == json!(recipients)
            && m0["max_accepted_requests"] == k
            && json_u128(&m0["charged"]) == 0
            && json_u64(&m0["seq"]) == 0
            && m0["accepted_count"] == 0
            && m0["frozen"] == false,
        m0.clone(),
    );
    let usage0 = json_u64(&acct["storage_usage"]);
    cx.check(
        "storage.reserve_matches_declared_bound",
        true,
        json_u64(&m0["storage_bound_bytes"]) == s_pred && json_u128(&m0["reserve_total"]) == r_pred,
        json!({"storage_bound_bytes": m0["storage_bound_bytes"], "predicted": s_pred, "reserve_total": m0["reserve_total"],
               "predicted_reserve": r_pred.to_string(), "code_bytes": wasm.len()}),
    );
    cx.check(
        "storage.post_init_usage_within_zero_admission_bound",
        true,
        usage0 <= s_pred - u64::from(k) * PER_ADMISSION,
        json!({"storage_usage_after_init": usage0, "bound_with_zero_admissions": s_pred - u64::from(k) * PER_ADMISSION}),
    );
    let init_events = create.events(&rid);
    cx.check(
        "events.init_seq0",
        false,
        init_events.len() == 1
            && init_events[0]["event"] == "init"
            && init_events[0]["data"]["seq"] == "0",
        json!(init_events),
    );

    // Agent shape.
    let agent_acct = cx.rpc.view_account(AGENT, &BlockRef::Final).await?;
    let agent_keys_view = cx.rpc.view_access_key_list(AGENT, &BlockRef::Final).await?;
    let ks = agent_keys_view["keys"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let all_fc = ks.iter().all(|k| {
        let fc = &k["access_key"]["permission"]["FunctionCall"];
        fc["receiver_id"] == VAULT
            && fc["method_names"] == json!(["request_payment"])
            && json_u128(&fc["allowance"]) == KEY_ALLOWANCE
    });
    cx.check(
        "construction.agent_code_free_eight_fc_keys_only",
        true,
        agent_acct["code_hash"] == "11111111111111111111111111111111"
            && ks.len() == AGENT_KEYS
            && all_fc,
        json!({"code_hash": agent_acct["code_hash"], "keys": ks}),
    );
    cx.log_balance(VAULT, "after_init").await?;

    // ---------------------------------------------------------------- agent misuse: rejected at validation
    let k0 = &agent_keys[0];
    let nonce_before = cx
        .rpc
        .view_access_key(AGENT, &k0.public_key(), &BlockRef::Final)
        .await?["nonce"]
        .clone();
    let probe = req_args("900", ALICE, NEAR, &ph);
    let misuse: Vec<(&str, &str, Vec<near_primitives::action::Action>, &str)> = vec![
        (
            "agentkey_calls_freeze",
            VAULT,
            vec![act::call("freeze", &json!({}), 30, 0)],
            "MethodNameMismatch",
        ),
        (
            "agentkey_calls_get_mandate",
            VAULT,
            vec![act::call("get_mandate", &json!({}), 30, 0)],
            "MethodNameMismatch",
        ),
        (
            "agentkey_request_with_1yocto_deposit",
            VAULT,
            vec![act::call("request_payment", &probe, REQ_GAS_TGAS, 1)],
            "DepositWithFunctionCall",
        ),
        (
            "agentkey_other_receiver",
            ALICE,
            vec![act::call("request_payment", &probe, REQ_GAS_TGAS, 0)],
            "ReceiverMismatch",
        ),
        // Observed on 2.13.4 (dry run 1): the allowance check precedes the permission check, so a
        // transfer larger than the key allowance reports NotEnoughAllowance; both are validation rejections.
        (
            "agentkey_plain_transfer_1near",
            VAULT,
            vec![act::transfer(NEAR)],
            "NotEnoughAllowance",
        ),
        (
            "agentkey_plain_transfer_1yocto",
            VAULT,
            vec![act::transfer(1)],
            "RequiresFullAccess",
        ),
        (
            "agentkey_two_actions",
            VAULT,
            vec![
                act::call("request_payment", &probe, 50, 0),
                act::call("request_payment", &probe, 50, 0),
            ],
            "RequiresFullAccess",
        ),
        (
            "agentkey_add_full_access_key",
            AGENT,
            vec![act::add_full_access_key(
                Key::random(AGENT).near_public_key(),
            )],
            "RequiresFullAccess",
        ),
    ];
    for (label, receiver, actions, expect) in misuse {
        let sent = cx.send(k0, receiver, actions, label).await?;
        let err = sent.submit.clone().err().unwrap_or(Value::Null);
        cx.check(
            &format!("authority.validation_rejects.{label}"),
            true,
            err.to_string().contains(expect),
            json!({"tx_hash_never_included": sent.hash, "expected": expect, "error": err}),
        );
    }
    let nonce_after = cx
        .rpc
        .view_access_key(AGENT, &k0.public_key(), &BlockRef::Final)
        .await?["nonce"]
        .clone();
    let m_after_misuse = cx.mandate(VAULT).await?;
    cx.check(
        "authority.validation_rejections_leave_no_trace",
        true,
        nonce_before == nonce_after && m_after_misuse["seq"] == m0["seq"],
        json!({"agent_key0_nonce_before": nonce_before, "after": nonce_after, "seq": m_after_misuse["seq"]}),
    );

    // ---------------------------------------------------------------- on-chain authority / method failures
    let mut failures: Vec<(String, TxView, &str)> = vec![];
    let valid = req_args("901", ALICE, NEAR, &ph);
    let cases: Vec<(&Key, &str, near_primitives::action::Action, &str)> = vec![
        (
            &owner,
            "owner_request_payment",
            act::call("request_payment", &valid, REQ_GAS_TGAS, 0),
            "Unauthorized",
        ),
        (
            &bob,
            "stranger_request_payment",
            act::call("request_payment", &valid, REQ_GAS_TGAS, 0),
            "Unauthorized",
        ),
        (
            &bob,
            "stranger_freeze",
            act::call("freeze", &json!({}), 30, 0),
            "Unauthorized",
        ),
        (
            &owner,
            "owner_calls_private_callback",
            act::call("on_payment_result", &json!({"request_id": "1"}), 30, 0),
            "Method on_payment_result is private",
        ),
        (
            &owner,
            "owner_freeze_with_deposit",
            act::call("freeze", &json!({}), 30, 1),
            "Method freeze doesn't accept deposit",
        ),
        (
            &owner,
            "owner_request_with_deposit",
            act::call("request_payment", &valid, REQ_GAS_TGAS, 1),
            "Method request_payment doesn't accept deposit",
        ),
        (
            &owner,
            "owner_reinitialize",
            act::call("new", &init_args, 100, 0),
            "The contract has already been initialized",
        ),
    ];
    for (key, label, action, expect) in cases {
        let tv = cx.exec(key, VAULT, vec![action], label).await?;
        failures.push((label.to_string(), tv, expect));
    }
    for m in [
        "withdraw",
        "transfer",
        "sweep",
        "upgrade",
        "migrate",
        "add_key",
        "delete_key",
        "delete_account",
        "deploy",
        "stake",
        "set_policy",
        "unfreeze",
        "reset_budget",
    ] {
        let label = format!("owner_calls_nonexistent_{m}");
        let tv = cx
            .exec(&owner, VAULT, vec![act::call(m, &json!({}), 30, 0)], &label)
            .await?;
        failures.push((label, tv, "MethodNotFound"));
    }

    // ---------------------------------------------------------------- malformed agent requests
    let base = |id: &str, amount: &str, phs: &str| {
        format!(
            r#"{{"request_id":{id},"recipient":"{ALICE}","amount":{amount},"policy_hash":{phs}}}"#
        )
    };
    let q = |s: &str| format!("\"{s}\"");
    let one = q(&NEAR.to_string());
    let phq = q(&ph);
    let malformed: Vec<(&str, String)> = vec![
        ("id_plus_sign", base(&q("+7"), &one, &phq)),
        ("id_leading_zero", base(&q("07"), &one, &phq)),
        ("id_leading_space", base(&q(" 7"), &one, &phq)),
        ("id_trailing_space", base(&q("7 "), &one, &phq)),
        ("id_json_number", base("7", &one, &phq)),
        ("id_decimal_point", base(&q("7.0"), &one, &phq)),
        ("id_exponent", base(&q("1e1"), &one, &phq)),
        ("id_negative", base(&q("-7"), &one, &phq)),
        ("id_empty", base(&q(""), &one, &phq)),
        ("id_hex", base(&q("0x7"), &one, &phq)),
        (
            "id_u64_overflow",
            base(&q("18446744073709551616"), &one, &phq),
        ),
        ("amount_plus_sign", base(&q("7"), &q("+1"), &phq)),
        ("amount_leading_zero", base(&q("7"), &q("01"), &phq)),
        ("amount_json_number", base(&q("7"), "1", &phq)),
        ("amount_exponent", base(&q("7"), &q("1e24"), &phq)),
        (
            "amount_u128_overflow",
            base(&q("7"), &q("340282366920938463463374607431768211456"), &phq),
        ),
        (
            "policy_hash_hex_encoding",
            base(&q("7"), &one, &q(&hex(&expected_ph))),
        ),
        (
            "policy_hash_45_chars",
            base(&q("7"), &one, &q(&format!("1{ph}"))),
        ),
        (
            "policy_hash_not_base58",
            base(&q("7"), &one, &q("0OIl0OIl0OIl0OIl0OIl0OIl0OIl0OIl")),
        ),
        (
            "duplicate_request_id_key",
            format!(
                r#"{{"request_id":"1","request_id":"2","recipient":"{ALICE}","amount":{one},"policy_hash":{phq}}}"#
            ),
        ),
        (
            "unknown_field",
            format!(
                r#"{{"request_id":"7","recipient":"{ALICE}","amount":{one},"policy_hash":{phq},"deposit":"1"}}"#
            ),
        ),
        (
            "missing_policy_hash",
            format!(r#"{{"request_id":"7","recipient":"{ALICE}","amount":{one}}}"#),
        ),
        (
            "invalid_account_id",
            format!(
                r#"{{"request_id":"7","recipient":"Alice.test.near","amount":{one},"policy_hash":{phq}}}"#
            ),
        ),
        ("not_json", "request_payment please".to_string()),
    ];
    for (i, (label, args)) in malformed.iter().enumerate() {
        let key = &agent_keys[i % AGENT_KEYS];
        let l = format!("malformed_{label}");
        let tv = cx
            .exec(
                key,
                VAULT,
                vec![act::call_raw(
                    "request_payment",
                    args.clone().into_bytes(),
                    REQ_GAS_TGAS,
                    0,
                )],
                &l,
            )
            .await?;
        failures.push((l, tv, "Failed to deserialize input from JSON"));
    }

    let m_before_fail_checks = cx.mandate(VAULT).await?;
    for (label, tv, expect) in &failures {
        let rid = tv.first_receipt_id();
        let fail = tv.failure(&rid).cloned().unwrap_or(Value::Null);
        let effects = cx.state_effects_of(tv, VAULT).await?;
        let no_data = effects["data_changes_from_receipt"]
            .as_array()
            .map(|a| a.is_empty())
            == Some(true);
        let no_app = tv.receipts_from(VAULT).is_empty();
        cx.check(
            &format!("failure_no_effect.{label}"),
            true,
            !fail.is_null() && fail.to_string().contains(expect) && no_data && no_app,
            json!({"tx": tv.tx_hash(), "expected": expect, "failure": fail, "application_receipts": tv.receipts_from(VAULT).len(),
                   "state_effects": effects}),
        );
    }
    cx.check(
        "failure_no_effect.mandate_unchanged",
        true,
        m_before_fail_checks["seq"] == m0["seq"]
            && m_before_fail_checks["charged"] == m0["charged"]
            && m_before_fail_checks["accepted_count"] == 0,
        json!({"seq": m_before_fail_checks["seq"], "charged": m_before_fail_checks["charged"]}),
    );
    cx.log_balance(VAULT, "after_failed_calls").await?;
    let bal_init = json_u128(&cx.balance_log[0]["amount"]);
    let bal_after_fail = json_u128(&cx.balance_log[1]["amount"]);
    cx.check(
        "accounting.failed_calls_change_balance_not_contract_state",
        false,
        bal_after_fail > bal_init,
        json!({"note": "gas rewards credit the vault for failed receipts; contract data unchanged (see failure_no_effect.*)",
               "balance_after_init": bal_init.to_string(), "balance_after_failures": bal_after_fail.to_string(),
               "delta": (bal_after_fail - bal_init.min(bal_after_fail)).to_string()}),
    );

    // ---------------------------------------------------------------- denied ID is retryable
    let tv = cx
        .exec(
            &agent_keys[1],
            VAULT,
            vec![act::call(
                "request_payment",
                &req_args("1", ALICE, 0, &ph),
                REQ_GAS_TGAS,
                0,
            )],
            "deny_id1_zero_amount",
        )
        .await?;
    let d = tv
        .success_json(&tv.first_receipt_id())
        .unwrap_or(Value::Null);
    let r1 = cx
        .rpc
        .view_fn(
            VAULT,
            "get_request",
            json!({"request_id": "1"}),
            &BlockRef::Final,
        )
        .await?
        .0;
    cx.check(
        "denial.zero_amount_not_retained",
        true,
        d["decision"] == "Denied"
            && d["reason"] == "ZeroAmount"
            && tv.receipts_from(VAULT).is_empty()
            && r1.is_null()
            && d["seq"] == "1",
        json!({"decision": d, "get_request_1": r1}),
    );

    // ---------------------------------------------------------------- payment 1: 1 NEAR to existing recipient
    cx.log_balance(VAULT, "before_payment_1").await?;
    let p1 = cx
        .exec(
            &agent_keys[2],
            VAULT,
            vec![act::call(
                "request_payment",
                &req_args("1", ALICE, NEAR, &ph),
                REQ_GAS_TGAS,
                0,
            )],
            "payment_1_success",
        )
        .await?;
    let p1r = p1.first_receipt_id();
    let d1 = p1.success_json(&p1r).unwrap_or(Value::Null);
    let dig1 = hex(&request_digest(VAULT, &expected_ph, AGENT, 1, ALICE, NEAR));
    let apps1 = p1.receipts_from(VAULT);
    let transfer1 = apps1
        .iter()
        .find(|r| r["receiver_id"] == ALICE)
        .cloned()
        .cloned()
        .unwrap_or(Value::Null);
    let cb1 = apps1
        .iter()
        .find(|r| r["receiver_id"] == VAULT)
        .cloned()
        .cloned()
        .unwrap_or(Value::Null);
    let t1_id = transfer1["receipt_id"]
        .as_str()
        .unwrap_or_default()
        .to_string();
    let cb1_id = cb1["receipt_id"].as_str().unwrap_or_default().to_string();
    let cb1_fc = &cb1["receipt"]["Action"]["actions"][0]["FunctionCall"];
    cx.check(
        "payment1.admitted_with_independent_digest",
        true,
        d1["decision"] == "Admitted"
            && d1["charged_before"] == "0"
            && json_u128(&d1["charged_after"]) == NEAR
            && d1["request_digest_hex"] == dig1.as_str(),
        json!({"decision": d1, "independent_digest": dig1}),
    );
    cx.check(
        "payment1.exactly_one_transfer_and_one_callback",
        true,
        apps1.len() == 2
            && p1.actions(&t1_id).len() == 1
            && json_u128(&p1.actions(&t1_id)[0]["Transfer"]["deposit"]) == NEAR
            && p1.actions(&cb1_id).len() == 1
            && cb1_fc["method_name"] == "on_payment_result"
            && json_u128(&cb1_fc["deposit"]) == 0
            && json_u64(&cb1_fc["gas"]) == CALLBACK_GAS
            && b64d(cb1_fc["args"].as_str().unwrap_or("")) == br#"{"request_id":"1"}"#.to_vec(),
        json!({"application_receipts": apps1, "transfer_receipt": t1_id, "callback_receipt": cb1_id}),
    );
    let cb1_gas = json_u64(&p1.outcome(&cb1_id)["gas_burnt"]);
    cx.check(
        "payment1.transfer_succeeded_callback_succeeded",
        true,
        p1.is_success(&t1_id) && p1.is_success(&cb1_id) && p1.events(&cb1_id).first().map(|e| e["data"]["callback_status"].clone()) == Some(json!("CbSucceeded")),
        json!({"transfer_status": p1.outcome(&t1_id)["status"], "transfer_block": p1.block_hash_of(&t1_id),
               "callback_status": p1.outcome(&cb1_id)["status"], "callback_events": p1.events(&cb1_id)}),
    );

    // ---------------------------------------------------------------- payment 2: 2 NEAR to absent recipient
    let p2 = cx
        .exec(
            &agent_keys[3],
            VAULT,
            vec![act::call(
                "request_payment",
                &req_args("2", MISSING, 2 * NEAR, &ph),
                REQ_GAS_TGAS,
                0,
            )],
            "payment_2_to_missing",
        )
        .await?;
    let p2r = p2.first_receipt_id();
    let d2 = p2.success_json(&p2r).unwrap_or(Value::Null);
    let dig2 = hex(&request_digest(
        VAULT,
        &expected_ph,
        AGENT,
        2,
        MISSING,
        2 * NEAR,
    ));
    let apps2 = p2.receipts_from(VAULT);
    let transfer2 = apps2
        .iter()
        .find(|r| r["receiver_id"] == MISSING)
        .cloned()
        .cloned()
        .unwrap_or(Value::Null);
    let cb2 = apps2
        .iter()
        .find(|r| r["receiver_id"] == VAULT)
        .cloned()
        .cloned()
        .unwrap_or(Value::Null);
    let t2_id = transfer2["receipt_id"]
        .as_str()
        .unwrap_or_default()
        .to_string();
    let cb2_id = cb2["receipt_id"].as_str().unwrap_or_default().to_string();
    let refunds: Vec<Value> = p2
        .receipts_from("system")
        .into_iter()
        .filter(|r| r["receiver_id"] == VAULT)
        .cloned()
        .collect();
    let refund_ok = refunds.len() == 1
        && p2.actions(refunds[0]["receipt_id"].as_str().unwrap()).len() == 1
        && json_u128(
            &p2.actions(refunds[0]["receipt_id"].as_str().unwrap())[0]["Transfer"]["deposit"],
        ) == 2 * NEAR
        && p2.is_success(refunds[0]["receipt_id"].as_str().unwrap());
    cx.check(
        "payment2.admitted_with_independent_digest",
        true,
        d2["decision"] == "Admitted"
            && json_u128(&d2["charged_before"]) == NEAR
            && json_u128(&d2["charged_after"]) == 3 * NEAR
            && d2["request_digest_hex"] == dig2.as_str(),
        json!({"decision": d2, "independent_digest": dig2}),
    );
    cx.check(
        "payment2.exactly_one_transfer_and_one_callback",
        true,
        apps2.len() == 2
            && p2.actions(&t2_id).len() == 1
            && json_u128(&p2.actions(&t2_id)[0]["Transfer"]["deposit"]) == 2 * NEAR,
        json!({"application_receipts": apps2}),
    );
    cx.check(
        "payment2.transfer_failed_account_does_not_exist",
        true,
        p2.failure(&t2_id).map(|f| f.to_string().contains("AccountDoesNotExist")) == Some(true),
        json!({"transfer_receipt": t2_id, "status": p2.outcome(&t2_id)["status"], "block": p2.block_hash_of(&t2_id)}),
    );
    cx.check(
        "payment2.refund_exact_principal_to_vault_from_system",
        true,
        refund_ok,
        json!({"refund_receipts": refunds, "refund_block": refunds.first().map(|r| p2.block_hash_of(r["receipt_id"].as_str().unwrap()))}),
    );
    let cb2_gas = json_u64(&p2.outcome(&cb2_id)["gas_burnt"]);
    cx.check(
        "payment2.callback_recorded_cb_failed",
        true,
        p2.is_success(&cb2_id) && p2.events(&cb2_id).first().map(|e| e["data"]["callback_status"].clone()) == Some(json!("CbFailed")),
        json!({"callback_receipt": cb2_id, "status": p2.outcome(&cb2_id)["status"], "events": p2.events(&cb2_id)}),
    );
    cx.check(
        "gas.callback_prepaid_at_least_3x_burnt",
        false,
        CALLBACK_GAS >= 3 * cb1_gas.max(cb2_gas),
        json!({"callback_gas_prepaid": CALLBACK_GAS, "burnt_success_path": cb1_gas, "burnt_failure_path": cb2_gas}),
    );
    cx.log_balance(VAULT, "after_payment_2_settled").await?;

    // ---------------------------------------------------------------- ledgers after settlement
    let m2 = cx.mandate(VAULT).await?;
    let adm = cx
        .rpc
        .view_fn(VAULT, "get_admissions", json!({}), &BlockRef::Final)
        .await?
        .0;
    cx.ev
        .write("state/vault_mandate_after_payments.json", &m2)?;
    let s_principal: u128 = if p1.is_success(&t1_id) { NEAR } else { 0 }
        + if p2.is_success(&t2_id) { 2 * NEAR } else { 0 };
    let f_principal: u128 = if p1.failure(&t1_id).is_some() {
        NEAR
    } else {
        0
    } + if p2.failure(&t2_id).is_some() {
        2 * NEAR
    } else {
        0
    };
    let c = json_u128(&m2["charged"]);
    cx.check(
        "ledger.C_equals_3_after_failed_transfer_and_refund",
        true,
        c == 3 * NEAR && m2["accepted_count"] == 2,
        json!({"charged": m2["charged"], "accepted_count": m2["accepted_count"]}),
    );
    cx.check(
        "ledger.headroom_equals_2_on_5_mandate",
        true,
        json_u128(&m2["headroom"]) == 2 * NEAR && json_u128(&m2["budget"]) == 5 * NEAR,
        json!({"budget": m2["budget"], "headroom": m2["headroom"]}),
    );
    cx.check(
        "ledger.native_outcomes_S1_F2_U0",
        true,
        s_principal == NEAR && f_principal == 2 * NEAR && c == s_principal + f_principal,
        json!({"S": s_principal.to_string(), "F": f_principal.to_string(), "U": (c - s_principal - f_principal).to_string(),
               "source": "transfer receipt outcomes in FINAL tx status, not balances"}),
    );
    cx.check(
        "ledger.callback_counters_separate",
        false,
        json_u128(&m2["cb_succeeded_amount"]) == NEAR && json_u128(&m2["cb_failed_amount"]) == 2 * NEAR && json_u128(&m2["callback_unconfirmed"]) == 0,
        json!({"cb_succeeded_amount": m2["cb_succeeded_amount"], "cb_failed_amount": m2["cb_failed_amount"]}),
    );
    let adm_ok = adm.as_array().map(|a| {
        a.len() == 2
            && a[0]["request_id"] == "1"
            && a[0]["recipient"] == ALICE
            && json_u128(&a[0]["amount"]) == NEAR
            && a[0]["callback_status"] == "CbSucceeded"
            && a[1]["request_id"] == "2"
            && a[1]["recipient"] == MISSING
            && json_u128(&a[1]["amount"]) == 2 * NEAR
            && a[1]["callback_status"] == "CbFailed"
            && a[0]["request_digest_hex"] == dig1.as_str()
            && a[1]["request_digest_hex"] == dig2.as_str()
    }) == Some(true);
    cx.check(
        "ledger.admissions_enumerate_both_records",
        true,
        adm_ok,
        adm.clone(),
    );

    // ---------------------------------------------------------------- replay and logical denials
    let seq_start = json_u64(&m2["seq"]);
    let denial_cases: Vec<(&str, Vec<u8>, &str, Option<bool>)> = vec![
        ("replay_id1_same_terms", req_args("1", ALICE, NEAR, &ph).to_string().into_bytes(), "DuplicateRequest", Some(true)),
        ("replay_id2_failed_transfer_same_terms", req_args("2", MISSING, 2 * NEAR, &ph).to_string().into_bytes(), "DuplicateRequest", Some(true)),
        ("replay_id1_different_terms", req_args("1", MISSING, 2 * NEAR, &ph).to_string().into_bytes(), "DuplicateRequest", Some(false)),
        ("replay_id1_json_escape_alias", format!(r#"{{"request_id":"1","recipient":"{ALICE}","amount":"{NEAR}","policy_hash":"{ph}"}}"#).into_bytes(), "DuplicateRequest", Some(true)),
        ("policy_mismatch_tv1_hash", req_args("3", ALICE, NEAR, "Huh1JW694BmEy8JARZmcDGptfBWCw2whpnzE9NugpBKc").to_string().into_bytes(), "PolicyMismatch", None),
        ("recipient_not_allowed_bob", req_args("3", BOB, NEAR, &ph).to_string().into_bytes(), "RecipientNotAllowed", None),
        ("recipient_not_allowed_owner", req_args("3", OWNER, NEAR, &ph).to_string().into_bytes(), "RecipientNotAllowed", None),
        ("recipient_not_allowed_vault_itself", req_args("3", VAULT, NEAR, &ph).to_string().into_bytes(), "RecipientNotAllowed", None),
        ("zero_amount", req_args("3", ALICE, 0, &ph).to_string().into_bytes(), "ZeroAmount", None),
        ("above_max_per_request", req_args("3", ALICE, 2 * NEAR + 1, &ph).to_string().into_bytes(), "AboveMaxPerRequest", None),
        ("record_quota_exhausted_within_budget", req_args("3", ALICE, 2 * NEAR, &ph).to_string().into_bytes(), "RecordQuotaExhausted", None),
    ];
    let mut expect_seq = seq_start;
    for (i, (label, args, reason, terms)) in denial_cases.into_iter().enumerate() {
        let l = format!("deny_{label}");
        let tv = cx
            .exec(
                &agent_keys[(4 + i) % AGENT_KEYS],
                VAULT,
                vec![act::call_raw("request_payment", args, REQ_GAS_TGAS, 0)],
                &l,
            )
            .await?;
        let d = tv
            .success_json(&tv.first_receipt_id())
            .unwrap_or(Value::Null);
        expect_seq += 1;
        let terms_ok = match terms {
            Some(t) => d["terms_match"] == t && d["original_admission_seq"].is_string(),
            None => d["terms_match"].is_null(),
        };
        let m = cx.mandate(VAULT).await?;
        cx.check(
            &format!("denial.{label}"),
            true,
            d["decision"] == "Denied"
                && d["reason"] == reason
                && terms_ok
                && json_u64(&d["seq"]) == expect_seq
                && tv.receipts_from(VAULT).is_empty()
                && json_u128(&m["charged"]) == 3 * NEAR
                && m["accepted_count"] == 2,
            json!({"tx": tv.tx_hash(), "decision": d, "application_receipts": tv.receipts_from(VAULT).len(), "charged_after": m["charged"]}),
        );
    }
    let r3 = cx
        .rpc
        .view_fn(
            VAULT,
            "get_request",
            json!({"request_id": "3"}),
            &BlockRef::Final,
        )
        .await?
        .0;
    cx.check(
        "denial.denied_ids_not_retained",
        true,
        r3.is_null(),
        json!({"get_request_3": r3}),
    );

    // ---------------------------------------------------------------- freeze
    let fz = cx
        .exec(
            &owner,
            VAULT,
            vec![act::call("freeze", &json!({}), 30, 0)],
            "owner_freeze",
        )
        .await?;
    let mf = cx.mandate(VAULT).await?;
    cx.check(
        "freeze.owner_freezes_once",
        true,
        fz.is_success(&fz.first_receipt_id())
            && mf["frozen"] == true
            && json_u64(&mf["seq"]) == expect_seq + 1
            && fz.receipts_from(VAULT).is_empty(),
        json!({"seq": mf["seq"], "events": fz.events(&fz.first_receipt_id())}),
    );
    let fz2 = cx
        .exec(
            &owner,
            VAULT,
            vec![act::call("freeze", &json!({}), 30, 0)],
            "owner_freeze_again_noop",
        )
        .await?;
    let mf2 = cx.mandate(VAULT).await?;
    cx.check(
        "freeze.idempotent_noop",
        true,
        fz2.is_success(&fz2.first_receipt_id())
            && mf2["seq"] == mf["seq"]
            && fz2.events(&fz2.first_receipt_id()).is_empty(),
        json!({"seq_before": mf["seq"], "seq_after": mf2["seq"]}),
    );
    let mut fseq = json_u64(&mf2["seq"]);
    for (label, args) in [
        ("frozen_new_id", req_args("3", ALICE, NEAR, &ph)),
        ("frozen_replay_id1", req_args("1", ALICE, NEAR, &ph)),
    ] {
        let l = format!("deny_{label}");
        let tv = cx
            .exec(
                &agent_keys[7],
                VAULT,
                vec![act::call("request_payment", &args, REQ_GAS_TGAS, 0)],
                &l,
            )
            .await?;
        let d = tv
            .success_json(&tv.first_receipt_id())
            .unwrap_or(Value::Null);
        fseq += 1;
        cx.check(
            &format!("denial.{label}"),
            true,
            d["decision"] == "Denied"
                && d["reason"] == "Frozen"
                && json_u64(&d["seq"]) == fseq
                && tv.receipts_from(VAULT).is_empty(),
            json!({"decision": d}),
        );
    }

    // ---------------------------------------------------------------- final cut Q (single block)
    let qb = cx.rpc.final_block().await?;
    let q_hash = qb["header"]["hash"].as_str().unwrap().to_string();
    let q_height = json_u64(&qb["header"]["height"]);
    let at_q = BlockRef::Hash(q_hash.clone());
    let (mq, mq_raw) = cx
        .rpc
        .view_fn(VAULT, "get_mandate", json!({}), &at_q)
        .await?;
    let (aq, aq_raw) = cx
        .rpc
        .view_fn(VAULT, "get_admissions", json!({}), &at_q)
        .await?;
    let state_q = cx.rpc.view_state(VAULT, b"", &at_q).await?;
    let keys_q = cx.rpc.view_access_key_list(VAULT, &at_q).await?;
    let acct_q = cx.rpc.view_account(VAULT, &at_q).await?;
    let agent_keys_q = cx.rpc.view_access_key_list(AGENT, &at_q).await?;
    let missing_q = cx
        .rpc
        .query_raw(
            json!({"request_type": "view_account", "account_id": MISSING}),
            &at_q,
        )
        .await?;
    let mut raw_state = json!({});
    let mut records = vec![];
    let mut index = vec![];
    for kv in state_q["values"].as_array().cloned().unwrap_or_default() {
        let key = b64d(kv["key"].as_str().unwrap());
        let val = b64d(kv["value"].as_str().unwrap());
        if key == b"STATE" {
            raw_state = decode_state(&val)?;
        } else if key.len() == 9 && key[0] == b'r' {
            let id = u64::from_le_bytes(key[1..].try_into()?);
            let mut r = decode_record(&val)?;
            r["request_id"] = json!(id.to_string());
            records.push(r);
        } else if key.len() == 5 && key[0] == b'i' && val.len() == 8 {
            index.push(json!({"position": u32::from_le_bytes(key[1..].try_into()?), "request_id": u64::from_le_bytes(val[..].try_into()?).to_string()}));
        } else {
            records.push(json!({"UNEXPECTED_KEY_HEX": hex(&key)}));
        }
    }
    let cut = json!({
        "block_hash": q_hash, "block_height": q_height,
        "get_mandate": mq, "get_mandate_query_block": {"hash": mq_raw["block_hash"], "height": mq_raw["block_height"]},
        "get_admissions": aq, "get_admissions_query_block": {"hash": aq_raw["block_hash"], "height": aq_raw["block_height"]},
        "raw_state_decoded": {"STATE": raw_state, "records": records, "index": index},
        "raw_state_query_block": {"hash": state_q["block_hash"], "height": state_q["block_height"]},
        "vault_access_keys": keys_q, "vault_account": acct_q, "agent_access_keys": agent_keys_q, "missing_recipient": missing_q,
    });
    cx.ev.write("state/final_cut_vault1.json", &cut)?;
    let same_block = [
        &mq_raw["block_hash"],
        &aq_raw["block_hash"],
        &state_q["block_hash"],
        &keys_q["block_hash"],
        &acct_q["block_hash"],
    ]
    .iter()
    .all(|h| **h == q_hash.as_str());
    let sum_adm: u128 = aq
        .as_array()
        .unwrap()
        .iter()
        .map(|a| json_u128(&a["amount"]))
        .sum();
    cx.check(
        "cut.views_at_single_block",
        true,
        same_block,
        json!({"q": q_hash, "mandate": mq_raw["block_hash"], "admissions": aq_raw["block_hash"], "state": state_q["block_hash"]}),
    );
    cx.check(
        "cut.raw_state_matches_views",
        true,
        raw_state["charged"] == mq["charged"]
            && raw_state["seq"] == mq["seq"]
            && raw_state["accepted_count"] == mq["accepted_count"]
            && raw_state["policy_hash"] == ph.as_str()
            && raw_state["frozen"] == true
            && json_u128(&raw_state["charged"]) == sum_adm
            && sum_adm == 3 * NEAR
            && records.len() == 2
            && index == vec![json!({"position": 0, "request_id": "1"}), json!({"position": 1, "request_id": "2"})],
        json!({"raw": raw_state, "records": records, "index": index, "sum_admissions": sum_adm.to_string()}),
    );
    cx.check(
        "cut.vault_still_keyless",
        true,
        keys_q["keys"].as_array().map(|a| a.is_empty()) == Some(true)
            && acct_q["code_hash"] == code_hash_b58.as_str(),
        json!({"keys": keys_q["keys"], "code_hash": acct_q["code_hash"]}),
    );
    cx.check(
        "cut.missing_recipient_still_absent",
        true,
        missing_q.to_string().contains("UNKNOWN_ACCOUNT"),
        missing_q.clone(),
    );
    let usage_q = json_u64(&acct_q["storage_usage"]);
    cx.check(
        "storage.usage_within_bound_after_k_admissions",
        true,
        usage_q <= s_pred && usage_q == usage0 + 2 * PER_ADMISSION,
        json!({"usage_at_q": usage_q, "usage_after_init": usage0, "per_admission": PER_ADMISSION, "bound": s_pred,
               "note": "K=2 only; the K=64 bound is a G2 deliverable"}),
    );

    // ---------------------------------------------------------------- interval scan: C never decreases, no key/code/migration changes
    let mut prev_c: u128 = 0;
    let mut c_series = vec![];
    let mut key_changes = vec![];
    let mut code_changes = vec![];
    let mut migrations = vec![];
    let mut blocks_scanned = 0u64;
    let mut missing_heights = 0u64;
    let mut c_monotone = true;
    for h in creation_height..=q_height {
        let b = match cx.rpc.raw("block", json!({"block_id": h})).await? {
            r if r.get("result").is_some() => r["result"].clone(),
            _ => {
                missing_heights += 1;
                continue;
            }
        };
        blocks_scanned += 1;
        let bh = b["header"]["hash"].as_str().unwrap().to_string();
        let touched = cx
            .rpc
            .call("EXPERIMENTAL_changes_in_block", json!({"block_id": bh}))
            .await?;
        let touches_vault = touched["changes"]
            .as_array()
            .map(|a| a.iter().any(|c| c["account_id"] == VAULT))
            == Some(true);
        if !touches_vault {
            continue;
        }
        let data = cx
            .rpc
            .changes(&bh, "data_changes", &[VAULT], Some(b"STATE"))
            .await?;
        for ch in data["changes"].as_array().cloned().unwrap_or_default() {
            if ch["type"] == "data_update" {
                let st = decode_state(&b64d(ch["change"]["value_base64"].as_str().unwrap()))?;
                let cval = json_u128(&st["charged"]);
                if cval < prev_c {
                    c_monotone = false;
                }
                prev_c = cval;
                c_series.push(json!({"height": h, "charged": st["charged"], "seq": st["seq"], "cause": ch["cause"]}));
            }
        }
        let kc = cx
            .rpc
            .changes(&bh, "all_access_key_changes", &[VAULT], None)
            .await?;
        key_changes.extend(kc["changes"].as_array().cloned().unwrap_or_default());
        let cc = cx
            .rpc
            .changes(&bh, "contract_code_changes", &[VAULT], None)
            .await?;
        code_changes.extend(
            cc["changes"]
                .as_array()
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .map(|c| json!({"height": h, "cause": c["cause"]})),
        );
        let ac = cx
            .rpc
            .changes(&bh, "account_changes", &[VAULT], None)
            .await?;
        for ch in ac["changes"]
            .as_array()
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .chain(data["changes"].as_array().cloned().unwrap_or_default())
        {
            if ch["cause"]["type"] == "migration" {
                migrations.push(json!({"height": h, "change": ch}));
            }
        }
    }
    cx.ev.write("state/vault1_interval_scan.json", &json!({
        "from_height": creation_height, "to_height": q_height, "blocks_scanned": blocks_scanned, "missing_heights": missing_heights,
        "charged_series": c_series, "access_key_changes": key_changes, "code_changes": code_changes, "migration_changes": migrations,
    }))?;
    cx.check(
        "interval.C_never_decreases",
        true,
        c_monotone && prev_c == 3 * NEAR,
        json!({"points": c_series.len(), "final_charged": prev_c.to_string(), "blocks_scanned": blocks_scanned}),
    );
    cx.check(
        "interval.no_vault_key_changes_one_code_change_no_migration",
        true,
        key_changes.is_empty() && code_changes.len() == 1 && code_changes[0]["height"] == creation_height && migrations.is_empty(),
        json!({"key_changes": key_changes.len(), "code_changes": code_changes, "migrations": migrations.len()}),
    );

    // ---------------------------------------------------------------- authority probe: remaining authority is exactly 2 NEAR
    let agent2_keys: Vec<Key> = (0..2).map(|_| Key::random(AGENT2)).collect();
    let mut a2 = vec![act::create_account(), act::transfer(3 * NEAR)];
    for kk in &agent2_keys {
        a2.push(act::add_fc_key(
            kk.near_public_key(),
            VAULT2,
            &["request_payment"],
            KEY_ALLOWANCE,
        ));
    }
    cx.exec(&owner, AGENT2, a2, "create_agent2").await?;
    let (k2, max2) = (4u32, 3 * NEAR);
    let (s2_pred, r2_pred) = predicted_reserve(wasm.len(), k2);
    let init2 = json!({
        "agent": AGENT2, "budget": budget.to_string(), "max_per_request": max2.to_string(),
        "allowed_recipients": recipients, "expires_at_ns": expires.to_string(), "max_accepted_requests": k2.to_string(),
    });
    let c2 = cx
        .exec(
            &owner,
            VAULT2,
            vec![
                act::create_account(),
                act::transfer(budget + r2_pred + NEAR),
                act::deploy(&wasm),
                act::call("new", &init2, 100, 0),
            ],
            "create_vault2",
        )
        .await?;
    let ph2_bytes = policy_hash(&PolicyInput {
        chain_id: &chain_id,
        vault: VAULT2,
        owner: OWNER,
        agent: AGENT2,
        budget,
        max_per_request: max2,
        recipients: &recipients,
        expires_at_ns: expires,
        k: k2,
    });
    let ph2 = b58(&ph2_bytes);
    let keys2 = cx
        .rpc
        .view_access_key_list(VAULT2, &BlockRef::Final)
        .await?;
    cx.check(
        "probe2.created_keyless_with_independent_hash",
        true,
        c2.success_json(&c2.first_receipt_id()) == Some(json!(ph2))
            && keys2["keys"].as_array().map(|a| a.is_empty()) == Some(true),
        json!({"policy_hash": ph2, "storage_bound": s2_pred, "keys": keys2["keys"]}),
    );
    let steps: Vec<(&str, &str, &str, u128, &str)> = vec![
        ("probe2_id1_1near_alice", "1", ALICE, NEAR, "Admitted"),
        (
            "probe2_id2_2near_missing",
            "2",
            MISSING,
            2 * NEAR,
            "Admitted",
        ),
        (
            "probe2_id3_3near_after_refund",
            "3",
            ALICE,
            3 * NEAR,
            "BudgetExceeded",
        ),
        (
            "probe2_id4_2near_remaining",
            "4",
            ALICE,
            2 * NEAR,
            "Admitted",
        ),
        ("probe2_id5_1yocto_over", "5", ALICE, 1, "BudgetExceeded"),
    ];
    let mut s2: u128 = 0;
    let mut f2: u128 = 0;
    for (i, (label, id, rcpt, amount, expect)) in steps.into_iter().enumerate() {
        let bal_before = json_u128(&cx.rpc.view_account(VAULT2, &BlockRef::Final).await?["amount"]);
        let tv = cx
            .exec(
                &agent2_keys[i % 2],
                VAULT2,
                vec![act::call(
                    "request_payment",
                    &req_args(id, rcpt, amount, &ph2),
                    REQ_GAS_TGAS,
                    0,
                )],
                label,
            )
            .await?;
        let d = tv
            .success_json(&tv.first_receipt_id())
            .unwrap_or(Value::Null);
        let decision_ok = if expect == "Admitted" {
            d["decision"] == "Admitted"
        } else {
            d["decision"] == "Denied" && d["reason"] == expect
        };
        for r in tv.receipts_from(VAULT2) {
            let rid = r["receipt_id"].as_str().unwrap();
            if r["receiver_id"] != VAULT2 {
                if tv.is_success(rid) {
                    s2 += json_u128(&tv.actions(rid)[0]["Transfer"]["deposit"])
                } else {
                    f2 += json_u128(&tv.actions(rid)[0]["Transfer"]["deposit"])
                }
            }
        }
        let m = cx.mandate(VAULT2).await?;
        cx.check(
            &format!("probe2.{label}"),
            true,
            decision_ok,
            json!({"decision": d, "charged_after": m["charged"], "headroom_after": m["headroom"],
                   "vault_balance_before": bal_before.to_string(), "liquidity_needed": (amount + json_u128(&m["reserve_total"])).to_string()}),
        );
    }
    let mp2 = cx.mandate(VAULT2).await?;
    cx.ev.write("state/vault2_mandate_final.json", &mp2)?;
    cx.check(
        "probe2.refund_never_restores_authority",
        true,
        json_u128(&mp2["charged"]) == 5 * NEAR && json_u128(&mp2["headroom"]) == 0 && s2 == 3 * NEAR && f2 == 2 * NEAR && mp2["accepted_count"] == 3,
        json!({"charged": mp2["charged"], "headroom": mp2["headroom"], "S": s2.to_string(), "F": f2.to_string(), "accepted_count": mp2["accepted_count"]}),
    );

    // ---------------------------------------------------------------- summary
    let end = cx.rpc.final_block().await?;
    cx.ev.write("summary.json", &json!({
        "run_id": run_id, "rpc_url": rpc_url, "chain_id": chain_id, "genesis_hash": status["genesis_hash"],
        "node_version": status["version"], "protocol_version": status["protocol_version"], "shard_layout": shard_layout,
        "h0": {"height": h0["header"]["height"], "hash": h0["header"]["hash"]},
        "end": {"height": end["header"]["height"], "hash": end["header"]["hash"]},
        "q_vault1": {"height": q_height, "hash": q_hash},
        "artifact": {"path": wasm_path, "bytes": wasm.len(), "sha256_hex": hex(&wasm_sha), "code_hash_b58": code_hash_b58},
        "accounts": {"root": rootk.account.to_string(), "owner": OWNER, "vault": VAULT, "agent": AGENT, "recipients": recipients,
                     "stranger": BOB, "vault2": VAULT2, "agent2": AGENT2},
        "vault1": {"policy_hash_b58": ph, "policy_hash_hex": hex(&expected_ph), "budget": budget.to_string(), "max_per_request": max_per.to_string(),
                   "k": k, "expires_at_ns": expires.to_string(), "funding": funding.to_string(), "storage_bound_bytes": s_pred,
                   "reserve_total": r_pred.to_string(), "creation_tx": create.tx_hash(), "creation_block": creation_block, "creation_height": creation_height,
                   "payment1": {"tx": p1.tx_hash(), "admission_receipt": p1r, "transfer_receipt": t1_id, "callback_receipt": cb1_id},
                   "payment2": {"tx": p2.tx_hash(), "admission_receipt": p2r, "transfer_receipt": t2_id, "callback_receipt": cb2_id,
                                "refund_receipts": refunds.iter().map(|r| r["receipt_id"].clone()).collect::<Vec<_>>()}},
        "vault2": {"policy_hash_b58": ph2, "budget": budget.to_string(), "max_per_request": max2.to_string(), "k": k2, "creation_tx": c2.tx_hash()},
        "metrics": {"rpc_calls": cx.rpc.calls.load(std::sync::atomic::Ordering::Relaxed),
                    "rpc_response_bytes": cx.rpc.bytes.load(std::sync::atomic::Ordering::Relaxed),
                    "elapsed_secs": cx.started.elapsed().as_secs_f64(), "transactions": cx.txs.len()},
    }))?;
    cx.flush()?;
    let failed: Vec<&Value> = cx.checks.iter().filter(|c| c["result"] != "PASS").collect();
    println!("checks: {} total, {} failed", cx.checks.len(), failed.len());
    assert!(failed.is_empty(), "non-critical checks failed: {failed:?}");
    Ok(())
}
