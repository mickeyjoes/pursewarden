//! G1 retention check (Phase0_E §3.1): after at least G1_RETENTION_BLOCKS (default 2000)
//! further blocks, without fast-forward, the node must still serve every run transaction's
//! FINAL outcome unchanged, the creation block and chunk, historical state at the creation
//! block, receipt bodies and receipt -> root mapping.
//!
//!   G1_RUN_ID=<run-id> cargo test -p g1-sandbox-tests --test retention -- --nocapture

use anyhow::Result;
use g1_sandbox_tests::*;
use serde_json::{json, Value};
use std::path::PathBuf;

#[tokio::test(flavor = "multi_thread")]
async fn g1_retention() -> Result<()> {
    let run_id = std::env::var("G1_RUN_ID").expect("G1_RUN_ID");
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()?;
    let rpc =
        Rpc::new(&std::env::var("G1_RPC_URL").unwrap_or_else(|_| "http://127.0.0.1:3130".into()));
    let ev = Evidence::new(root.join("evidence/g1").join(&run_id))?;
    let gap: u64 = std::env::var("G1_RETENTION_BLOCKS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(2000);
    let summary: Value = serde_json::from_slice(&std::fs::read(ev.dir.join("summary.json"))?)?;
    let txs: Vec<Value> =
        serde_json::from_slice(&std::fs::read(ev.dir.join("transactions.json"))?)?;
    let end_height = json_u64(&summary["end"]["height"]);
    let target = end_height + gap;
    println!("waiting for final height {target} (run end {end_height} + {gap})");
    let head = rpc.wait_until_final_height(target).await?;
    let mut checks = vec![];
    let mut check = |id: &str, ok: bool, detail: Value| {
        println!("[{}] {id}", if ok { "PASS" } else { "FAIL" });
        checks.push(json!({"id": id, "result": if ok {"PASS"} else {"FAIL"}, "detail": detail}));
    };

    let status = rpc.status().await?;
    check(
        "retention.same_chain",
        status["genesis_hash"] == summary["genesis_hash"]
            && status["chain_id"] == summary["chain_id"],
        json!({"genesis_hash": status["genesis_hash"], "chain_id": status["chain_id"]}),
    );

    // Every transaction's FINAL outcome must be served and identical to the captured one.
    let mut mismatched = vec![];
    for t in &txs {
        let saved: Value = serde_json::from_slice(&std::fs::read(
            ev.dir.join(t["evidence_file"].as_str().unwrap()),
        )?)?;
        let now = rpc
            .tx_final(
                t["tx_hash"].as_str().unwrap(),
                t["sender"].as_str().unwrap(),
            )
            .await;
        match now {
            Ok(v) if v == saved => {}
            Ok(_) => mismatched.push(json!({"tx": t["tx_hash"], "why": "differs"})),
            Err(e) => mismatched.push(json!({"tx": t["tx_hash"], "why": e.to_string()})),
        }
    }
    check(
        "retention.all_tx_outcomes_identical_after_gap",
        mismatched.is_empty(),
        json!({"transactions": txs.len(), "mismatched": mismatched}),
    );

    let v1 = &summary["vault1"];
    let creation_block = v1["creation_block"].as_str().unwrap();
    let blk = rpc.block(json!(creation_block)).await;
    check(
        "retention.creation_block_served",
        blk.is_ok(),
        json!({"block": creation_block, "ok": blk.is_ok()}),
    );

    // The block that included the creation transaction, and its chunk.
    let create_row = txs.iter().find(|t| t["label"] == "create_vault").unwrap();
    let incl = rpc.block(create_row["tx_block_hash"].clone()).await?;
    let chunk = rpc
        .call(
            "chunk",
            json!({"block_id": incl["header"]["hash"], "shard_id": 0}),
        )
        .await?;
    let in_chunk = chunk["transactions"]
        .as_array()
        .map(|a| a.iter().any(|t| t["hash"] == create_row["tx_hash"]))
        == Some(true);
    check(
        "retention.creation_tx_in_old_chunk",
        in_chunk,
        json!({"inclusion_block": incl["header"]["hash"], "height": incl["header"]["height"], "chunk_txs": chunk["transactions"].as_array().map(|a| a.len())}),
    );

    // Historical state at the creation block.
    let at = BlockRef::Hash(creation_block.to_string());
    let acct = rpc.view_account("vault.owner.test.near", &at).await;
    let keys = rpc.view_access_key_list("vault.owner.test.near", &at).await;
    let m = rpc
        .view_fn("vault.owner.test.near", "get_mandate", json!({}), &at)
        .await;
    check(
        "retention.historical_state_at_creation_block",
        acct.is_ok()
            && keys
                .as_ref()
                .map(|k| k["keys"].as_array().map(|a| a.is_empty()) == Some(true))
                .unwrap_or(false)
            && m.as_ref()
                .map(|(m, _)| m["seq"] == "0" && m["charged"] == "0")
                .unwrap_or(false),
        json!({"account": acct.as_ref().ok(), "keys": keys.as_ref().ok(), "mandate": m.as_ref().ok().map(|x| &x.0)}),
    );

    // Receipt body and receipt -> root mapping for the refund of the failed transfer.
    let refund = v1["payment2"]["refund_receipts"][0]
        .as_str()
        .unwrap_or_default();
    let body = rpc
        .call("EXPERIMENTAL_receipt", json!({"receipt_id": refund}))
        .await;
    let root_tx = rpc
        .call("EXPERIMENTAL_receipt_to_tx", json!({"receipt_id": refund}))
        .await;
    check(
        "retention.refund_receipt_body_and_root",
        body.as_ref()
            .map(|b| b["predecessor_id"] == "system")
            .unwrap_or(false)
            && root_tx
                .as_ref()
                .map(|r| find(r, "transaction_hash") == Some(&v1["payment2"]["tx"]))
                .unwrap_or(false),
        json!({"receipt": refund, "body": body.as_ref().ok(), "receipt_to_tx": root_tx.as_ref().map_err(|e| e.to_string())}),
    );

    // Old state changes are still served.
    let transfer2_row = txs
        .iter()
        .find(|t| t["label"] == "payment_2_to_missing")
        .unwrap();
    let refund_block = transfer2_row["receipts"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["receipt_id"] == refund)
        .map(|r| r["block_hash"].clone());
    let ch = match &refund_block {
        Some(Value::String(b)) => rpc
            .changes(b, "account_changes", &["vault.owner.test.near"], None)
            .await
            .ok(),
        _ => None,
    };
    check(
        "retention.state_changes_at_refund_block",
        ch.as_ref()
            .map(|c| c["changes"].as_array().map(|a| !a.is_empty()) == Some(true))
            .unwrap_or(false),
        json!({"refund_block": refund_block, "changes": ch}),
    );

    let failed = checks.iter().filter(|c| c["result"] != "PASS").count();
    ev.write(
        "retention.json",
        &json!({"gap_blocks": gap, "run_end_height": end_height, "head_at_check": {"height": head["header"]["height"], "hash": head["header"]["hash"]},
                "fast_forward_used": false, "total": checks.len(), "failed": failed, "checks": checks,
                "rpc_calls": rpc.calls.load(std::sync::atomic::Ordering::Relaxed)}),
    )?;
    assert_eq!(failed, 0, "retention checks failed");
    Ok(())
}

fn find<'a>(v: &'a Value, key: &str) -> Option<&'a Value> {
    match v {
        Value::Object(m) => m.get(key).or_else(|| m.values().find_map(|x| find(x, key))),
        Value::Array(a) => a.iter().find_map(|x| find(x, key)),
        _ => None,
    }
}
