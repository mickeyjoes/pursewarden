//! Policy identity, request digest and persisted-storage bound (SPEC-V1.1 §3, §4, §5).
//!
//! Everything here is pure apart from `sha256`, so the exact bytes the deployed contract
//! hashes are covered by native unit tests against the SPEC-V1.1 test vectors.

use near_sdk::{borsh, near, AccountId};

/// `near-agent-vault-lab/mandate/v1\0` — 32 bytes including the final NUL.
pub const POLICY_DOMAIN: &[u8; 32] = b"near-agent-vault-lab/mandate/v1\0";
/// `near-agent-vault-lab/request/v1\0` — 32 bytes including the final NUL.
pub const REQUEST_DOMAIN: &[u8; 32] = b"near-agent-vault-lab/request/v1\0";

pub const MIN_RECIPIENTS: usize = 1;
pub const MAX_RECIPIENTS: usize = 8;
pub const DEFAULT_MAX_ACCEPTED_REQUESTS: u32 = 64;
pub const MAX_ACCEPTED_REQUESTS: u32 = 64;
/// Protocol maximum AccountId length.
pub const MAX_ACCOUNT_ID_BYTES: usize = 64;
/// DESIGN ASSUMPTION: initialization rejects a runtime chain ID longer than this so the
/// persisted STATE size has a static bound.
pub const MAX_CHAIN_ID_BYTES: usize = 64;

/// Asset tag. Borsh encodes the single variant as one byte `0` (SPEC-V1.1 field 5).
#[near(serializers = [borsh])]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Asset {
    NativeNear,
}

/// Immutable policy fields, in exact SPEC-V1.1 Borsh order. Do not reorder.
#[near(serializers = [borsh])]
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Policy {
    pub chain_id: String,
    pub vault: AccountId,
    pub owner: AccountId,
    pub agent: AccountId,
    pub asset: Asset,
    pub budget: u128,
    pub max_per_request: u128,
    pub allowed_recipients: Vec<AccountId>,
    pub expires_at_ns: u64,
    pub max_accepted_requests: u32,
}

/// On wasm32 with `--cfg near` (set by cargo-near) this is the `sha256` host function;
/// in native test builds near-sdk-env computes the same digest in pure Rust.
pub fn sha256(data: &[u8]) -> [u8; 32] {
    near_sdk::env::sha256_array(data)
}

fn domain_hash(domain: &[u8; 32], body: &[u8]) -> [u8; 32] {
    let mut buf = Vec::with_capacity(domain.len() + body.len());
    buf.extend_from_slice(domain);
    buf.extend_from_slice(body);
    sha256(&buf)
}

pub fn policy_body(p: &Policy) -> Vec<u8> {
    borsh::to_vec(p).expect("policy borsh")
}

/// `policy_hash = SHA256(POLICY_DOMAIN || Borsh(policy_fields))`; also the mandate ID.
pub fn policy_hash(p: &Policy) -> [u8; 32] {
    domain_hash(POLICY_DOMAIN, &policy_body(p))
}

/// `Borsh(vault, policy_hash:[u8;32], agent, request_id:u64, recipient, amount:u128)`.
pub fn request_body(
    vault: &AccountId,
    policy_hash: &[u8; 32],
    agent: &AccountId,
    request_id: u64,
    recipient: &AccountId,
    amount: u128,
) -> Vec<u8> {
    borsh::to_vec(&(vault, policy_hash, agent, request_id, recipient, amount))
        .expect("request borsh")
}

pub fn request_digest(
    vault: &AccountId,
    policy_hash: &[u8; 32],
    agent: &AccountId,
    request_id: u64,
    recipient: &AccountId,
    amount: u128,
) -> [u8; 32] {
    domain_hash(
        REQUEST_DOMAIN,
        &request_body(vault, policy_hash, agent, request_id, recipient, amount),
    )
}

// ---------------------------------------------------------------------------------------
// Persisted storage bound (SPEC-V1.1 §5 "Storage and liquidity").
//
// S_max = base_usage + STATE_ENTRY_MAX_BYTES + K * PER_ADMISSION_MAX_BYTES, where
// base_usage is the account's storage usage observed inside `new` after CreateAccount and
// DeployContract (account record + code; no contract data has been written yet).
// Each trie entry costs key + value + NUM_EXTRA_BYTES_RECORD. The constants below are
// checked by unit tests against maximal encodings and must be revalidated against the
// runtime's `storage_usage_config` (G1 harness compares them with
// EXPERIMENTAL_protocol_config) and against post-receipt `view_account.storage_usage`.
// ---------------------------------------------------------------------------------------

/// Protocol `storage_usage_config.num_extra_bytes_record` (40 on PV86).
pub const NUM_EXTRA_BYTES_RECORD: u64 = 40;
/// Upper bound on Borsh(Vault) for any accepted policy (unit-tested with maximal inputs).
pub const STATE_VALUE_MAX_BYTES: u64 = 1024;
pub const STATE_KEY: &[u8] = b"STATE";
pub const STATE_ENTRY_MAX_BYTES: u64 =
    STATE_KEY.len() as u64 + STATE_VALUE_MAX_BYTES + NUM_EXTRA_BYTES_RECORD;

/// Admission index entry: key `b'i' || u32 LE position`, value `u64 LE request_id`.
pub const INDEX_PREFIX: u8 = b'i';
pub const INDEX_KEY_BYTES: u64 = 1 + 4;
pub const INDEX_VALUE_BYTES: u64 = 8;
/// Request record entry: key `b'r' || u64 LE request_id`, value `Borsh(Record)`.
pub const RECORD_PREFIX: u8 = b'r';
pub const RECORD_KEY_BYTES: u64 = 1 + 8;
/// Borsh(Record) = u8 recipient_index + u128 amount + u64 admission_seq + u8 status.
pub const RECORD_VALUE_BYTES: u64 = 1 + 16 + 8 + 1;
pub const PER_ADMISSION_MAX_BYTES: u64 =
    (INDEX_KEY_BYTES + INDEX_VALUE_BYTES + NUM_EXTRA_BYTES_RECORD)
        + (RECORD_KEY_BYTES + RECORD_VALUE_BYTES + NUM_EXTRA_BYTES_RECORD);

/// Declared reserve margin on top of `p * S_max` (0.01 NEAR). Recorded in `get_mandate`.
pub const RESERVE_MARGIN_YOCTO: u128 = 10_000_000_000_000_000_000_000;

pub fn index_key(position: u32) -> [u8; 5] {
    let mut k = [0u8; 5];
    k[0] = INDEX_PREFIX;
    k[1..].copy_from_slice(&position.to_le_bytes());
    k
}

pub fn record_key(request_id: u64) -> [u8; 9] {
    let mut k = [0u8; 9];
    k[0] = RECORD_PREFIX;
    k[1..].copy_from_slice(&request_id.to_le_bytes());
    k
}

/// Returns `None` on overflow.
pub fn storage_bound_bytes(base_usage: u64, max_accepted_requests: u32) -> Option<u64> {
    base_usage
        .checked_add(STATE_ENTRY_MAX_BYTES)?
        .checked_add(u64::from(max_accepted_requests).checked_mul(PER_ADMISSION_MAX_BYTES)?)
}

/// `R_total = p * S_max + margin`; `None` on overflow.
pub fn reserve_total(storage_bound_bytes: u64, byte_cost: u128) -> Option<u128> {
    u128::from(storage_bound_bytes)
        .checked_mul(byte_cost)?
        .checked_add(RESERVE_MARGIN_YOCTO)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::canonical::{to_b58, to_hex};

    const NEAR: u128 = 1_000_000_000_000_000_000_000_000;

    fn acc(s: &str) -> AccountId {
        s.parse().unwrap()
    }

    fn tv1() -> Policy {
        Policy {
            chain_id: "localnet".into(),
            vault: acc("vault.owner.test.near"),
            owner: acc("owner.test.near"),
            agent: acc("agent.owner.test.near"),
            asset: Asset::NativeNear,
            budget: 5 * NEAR,
            max_per_request: 2 * NEAR,
            allowed_recipients: vec![acc("recipient.test.near")],
            expires_at_ns: 1_798_761_600_000_000_000,
            max_accepted_requests: 64,
        }
    }

    #[test]
    fn domains_are_32_bytes_with_trailing_nul() {
        assert_eq!(POLICY_DOMAIN.len(), 32);
        assert_eq!(REQUEST_DOMAIN.len(), 32);
        assert_eq!(POLICY_DOMAIN[31], 0);
        assert_eq!(REQUEST_DOMAIN[31], 0);
    }

    // SPEC-V1.1 §3 "Policy test vectors", reproduced byte-for-byte with the Rust/Borsh build.
    #[test]
    fn spec_tv1() {
        let p = tv1();
        let body = policy_body(&p);
        assert_eq!(body.len(), 153);
        assert_eq!(
            to_hex(&body),
            "080000006c6f63616c6e6574150000007661756c742e6f776e65722e746573742e6e6561720f0000006f776e65722e746573742e6e656172150000006167656e742e6f776e65722e746573742e6e6561720000000025a4000a8bca2204000000000000000042db999d3784a70100000000000100000013000000726563697069656e742e746573742e6e65617200009d1b257cf61840000000"
        );
        let h = policy_hash(&p);
        assert_eq!(
            to_hex(&h),
            "fb3a6d4aa6755c36304fafceaa998ad51939bf83f3cf7a501e968e21c6ca3127"
        );
        assert_eq!(to_b58(&h), "Huh1JW694BmEy8JARZmcDGptfBWCw2whpnzE9NugpBKc");
    }

    #[test]
    fn spec_tv2() {
        let mut p = tv1();
        p.budget = 17 * NEAR;
        p.allowed_recipients = [
            "a-b.test.near",
            "a.test.near",
            "a_b.test.near",
            "missing.test.near",
        ]
        .into_iter()
        .map(acc)
        .collect();
        let body = policy_body(&p);
        assert_eq!(body.len(), 200);
        assert_eq!(
            to_hex(&body),
            "080000006c6f63616c6e6574150000007661756c742e6f776e65722e746573742e6e6561720f0000006f776e65722e746573742e6e656172150000006167656e742e6f776e65722e746573742e6e65617200000000b1c79bbbd8e30f0e000000000000000042db999d3784a7010000000000040000000d000000612d622e746573742e6e6561720b000000612e746573742e6e6561720d000000615f622e746573742e6e656172110000006d697373696e672e746573742e6e65617200009d1b257cf61840000000"
        );
        let h = policy_hash(&p);
        assert_eq!(
            to_hex(&h),
            "33d831635e86376b3a1892e107192bf0a69d713a880b3e388ae4dd81dc602469"
        );
        assert_eq!(to_b58(&h), "4VNzhBPJV7Y21JqfKyQWTFf1RQzGegon6trisrkN3KhJ");
    }

    #[test]
    fn spec_tv3() {
        let p = Policy {
            chain_id: "testnet".into(),
            vault: acc("v.o.test.near"),
            owner: acc("o.test.near"),
            agent: acc("g.o.test.near"),
            asset: Asset::NativeNear,
            budget: u128::MAX,
            max_per_request: 1,
            allowed_recipients: vec![acc(&format!("{}.test.near", "a".repeat(54)))],
            expires_at_ns: u64::MAX,
            max_accepted_requests: 1,
        };
        assert_eq!(p.allowed_recipients[0].as_str().len(), 64);
        let body = policy_body(&p);
        assert_eq!(body.len(), 177);
        assert_eq!(
            to_hex(&body),
            "07000000746573746e65740d000000762e6f2e746573742e6e6561720b0000006f2e746573742e6e6561720d000000672e6f2e746573742e6e65617200ffffffffffffffffffffffffffffffff0100000000000000000000000000000001000000400000006161616161616161616161616161616161616161616161616161616161616161616161616161616161616161616161616161616161612e746573742e6e656172ffffffffffffffff01000000"
        );
        let h = policy_hash(&p);
        assert_eq!(
            to_hex(&h),
            "0b514f78b3b47243fedff39f8a72fc1a6b058ec42b6f5fad92239e48b6df23a7"
        );
        assert_eq!(to_b58(&h), "mBPyGXA3GdZp5qGfcGUecKKPZsMcts5dU1nqo9HT9JW");
    }

    #[test]
    fn spec_additional_vectors() {
        let mut p = tv1();
        p.budget += 1;
        assert_eq!(
            to_hex(&policy_hash(&p)),
            "6d70efbeb7c49881c6518321062d31e2b26cbcc330ea0ecb0a2d2c2773463e9f"
        );

        let p = tv1();
        let ph = policy_hash(&p);
        let r = acc("recipient.test.near");
        assert_eq!(
            to_hex(&request_digest(&p.vault, &ph, &p.agent, 1, &r, NEAR)),
            "139aee296449d83e91fe89fb4eff80b0cbcf53c17e9cf4c70858fff5460e4ce7"
        );
        assert_eq!(
            to_hex(&request_digest(&p.vault, &ph, &p.agent, 2, &r, 2 * NEAR)),
            "b3811fe8c34565f87141c8af6b1b7ea59a26b5eab5d32fb658a2531221e9bdc7"
        );
    }

    #[test]
    fn storage_constants_match_encodings() {
        assert_eq!(index_key(7).len() as u64, INDEX_KEY_BYTES);
        assert_eq!(record_key(7).len() as u64, RECORD_KEY_BYTES);
        assert_eq!(PER_ADMISSION_MAX_BYTES, 128);
        assert_eq!(STATE_ENTRY_MAX_BYTES, 5 + 1024 + 40);
        assert_eq!(index_key(0x0403_0201), [b'i', 1, 2, 3, 4]);
        assert_eq!(record_key(1)[0], b'r');
        assert_eq!(storage_bound_bytes(u64::MAX, 1), None);
        assert_eq!(reserve_total(u64::MAX, u128::MAX), None);
    }
}
