//! near-agent-vault — G1 fixed-mandate native-NEAR vault (SPEC-V1.1).
//!
//! One immutable mandate, one agent, a bounded allowlist and at most K accepted requests.
//! Admission permanently charges `C`; callbacks, failed transfers and refunds never
//! restore budget. There is no withdrawal, sweep, upgrade, key, re-initialization or
//! policy-mutation path. Residual funds are locked by design.
//!
//! Promise construction uses only the low-level `promise_batch_create`,
//! `promise_batch_action_transfer`, `promise_batch_then` and
//! `promise_batch_action_function_call` host calls (Phase0_A §1.2); near-sdk's high-level
//! `Promise`, `ext_contract` and `Self::ext` must not be used because they link every
//! action host import.

pub mod canonical;
pub mod policy;

use canonical::{to_b58, to_hex, CanonU128, CanonU32, CanonU64, Hash32B58};
use near_sdk::json_types::{U128, U64};
use near_sdk::serde_json::{self, json};
use near_sdk::{env, near, require, AccountId, Gas, NearToken, PanicOnDefault, PromiseError};
use policy::{
    index_key, policy_hash, record_key, request_digest, reserve_total, storage_bound_bytes, Asset,
    Policy, DEFAULT_MAX_ACCEPTED_REQUESTS, MAX_ACCEPTED_REQUESTS, MAX_CHAIN_ID_BYTES,
    MAX_RECIPIENTS, MIN_RECIPIENTS, RESERVE_MARGIN_YOCTO,
};

pub const CONTRACT_VERSION: &str = "g1-0.1.0";
pub const EVENT_STANDARD: &str = "near-agent-vault-lab";
pub const EVENT_VERSION: &str = "1.0.0";
/// Static gas prepaid for `on_payment_result`. G1 measures `gas_burnt` and requires >= 3x margin.
pub const CALLBACK_GAS: Gas = Gas::from_tgas(20);
pub const CALLBACK_METHOD: &str = "on_payment_result";

#[near(serializers = [borsh, json])]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CallbackStatus {
    Pending,
    CbSucceeded,
    CbFailed,
}

/// Fixed-shape retained record; the request ID is the map key, never stored as a string.
#[near(serializers = [borsh])]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Record {
    pub recipient_index: u8,
    pub amount: u128,
    pub admission_seq: u64,
    pub status: CallbackStatus,
}

#[near(serializers = [json])]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DenyReason {
    PolicyMismatch,
    Frozen,
    Expired,
    DuplicateRequest,
    RecipientNotAllowed,
    ZeroAmount,
    AboveMaxPerRequest,
    BudgetExceeded,
    RecordQuotaExhausted,
    InsufficientLiquidity,
}

#[near(serializers = [json])]
#[serde(tag = "decision")]
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Decision {
    Admitted {
        seq: U64,
        request_id: U64,
        recipient: AccountId,
        amount: U128,
        request_digest_hex: String,
        charged_before: U128,
        charged_after: U128,
    },
    Denied {
        seq: U64,
        request_id: U64,
        recipient: AccountId,
        amount: U128,
        reason: DenyReason,
        charged: U128,
        /// DuplicateRequest only: admission sequence of the retained ID and whether terms match.
        original_admission_seq: Option<U64>,
        terms_match: Option<bool>,
    },
}

#[near(serializers = [json])]
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RequestView {
    pub request_id: U64,
    pub recipient: AccountId,
    pub recipient_index: u8,
    pub amount: U128,
    pub admission_seq: U64,
    pub callback_status: CallbackStatus,
    pub request_digest_hex: String,
}

#[near(serializers = [json])]
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MandateView {
    pub contract_version: String,
    pub chain_id: String,
    pub vault: AccountId,
    pub owner: AccountId,
    pub agent: AccountId,
    pub asset: String,
    pub budget: U128,
    pub max_per_request: U128,
    pub allowed_recipients: Vec<AccountId>,
    pub expires_at_ns: U64,
    pub max_accepted_requests: u32,
    pub policy_hash: String,
    pub policy_hash_hex: String,
    pub storage_bound_bytes: U64,
    pub reserve_margin: U128,
    pub reserve_total: U128,
    pub callback_gas: U64,
    pub charged: U128,
    pub headroom: U128,
    pub cb_succeeded_amount: U128,
    pub cb_failed_amount: U128,
    pub callback_unconfirmed: U128,
    pub accepted_count: u32,
    pub seq: U64,
    pub frozen: bool,
    pub expired: bool,
    pub block_height: U64,
    pub block_timestamp_ns: U64,
    pub account_balance: U128,
    pub storage_usage: U64,
}

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct Vault {
    policy: Policy,
    policy_hash: [u8; 32],
    storage_bound_bytes: u64,
    reserve_total: u128,
    /// C: cumulative principal of accepted requests. Only admission increases it; nothing decreases it.
    charged: u128,
    cb_succeeded_amount: u128,
    cb_failed_amount: u128,
    frozen: bool,
    accepted_count: u32,
    seq: u64,
}

fn emit(event: &str, data: serde_json::Value) {
    let ev = json!({
        "standard": EVENT_STANDARD,
        "version": EVENT_VERSION,
        "event": event,
        "data": data,
    });
    env::log_str(&format!("EVENT_JSON:{ev}"));
}

fn checked_inc_u64(v: u64) -> u64 {
    v.checked_add(1)
        .unwrap_or_else(|| env::panic_str("Overflow"))
}

#[near]
impl Vault {
    /// One-time initializer, called as the last action of the vault's creation batch
    /// `[CreateAccount, Transfer, DeployContract, FunctionCall(new)]`. Nonpayable; not private
    /// (the predecessor is the owner). Writes the policy hash (base58) as the return value.
    #[init]
    #[deny_unknown_arguments]
    pub fn new(
        agent: AccountId,
        budget: CanonU128,
        max_per_request: CanonU128,
        allowed_recipients: Vec<AccountId>,
        expires_at_ns: CanonU64,
        max_accepted_requests: Option<CanonU32>,
    ) -> Self {
        let owner = env::predecessor_account_id();
        let vault = env::current_account_id();
        let chain_id = env::chain_id();
        require!(
            !chain_id.is_empty() && chain_id.len() <= MAX_CHAIN_ID_BYTES,
            "InvalidPolicy: chain_id"
        );
        require!(
            vault.is_sub_account_of(&owner),
            "InvalidPolicy: vault must be a direct subaccount of owner"
        );
        require!(agent != owner && agent != vault, "InvalidPolicy: agent");

        let budget = budget.0;
        let max_per_request = max_per_request.0;
        require!(budget > 0, "InvalidPolicy: budget");
        require!(
            max_per_request > 0 && max_per_request <= budget,
            "InvalidPolicy: max_per_request"
        );

        let n = allowed_recipients.len();
        require!(
            (MIN_RECIPIENTS..=MAX_RECIPIENTS).contains(&n),
            "InvalidPolicy: recipient count"
        );
        for r in &allowed_recipients {
            require!(
                r.as_str().contains('.'),
                "InvalidPolicy: recipient must be a named account"
            );
            require!(
                *r != owner && *r != agent && *r != vault,
                "InvalidPolicy: recipient is a role account"
            );
        }
        for w in allowed_recipients.windows(2) {
            require!(
                w[0].as_str().as_bytes() < w[1].as_str().as_bytes(),
                "InvalidPolicy: recipients must be strictly increasing UTF-8 byte order"
            );
        }

        let expires_at_ns = expires_at_ns.0;
        require!(
            expires_at_ns > env::block_timestamp(),
            "InvalidPolicy: expiry"
        );
        let k = max_accepted_requests.map_or(DEFAULT_MAX_ACCEPTED_REQUESTS, |k| k.0);
        require!(
            (1..=MAX_ACCEPTED_REQUESTS).contains(&k),
            "InvalidPolicy: max_accepted_requests"
        );

        let policy = Policy {
            chain_id,
            vault,
            owner,
            agent,
            asset: Asset::NativeNear,
            budget,
            max_per_request,
            allowed_recipients,
            expires_at_ns,
            max_accepted_requests: k,
        };
        let policy_hash = policy_hash(&policy);

        // Account record + deployed code at this point; no contract data written yet.
        let base_usage = env::storage_usage();
        let s_max =
            storage_bound_bytes(base_usage, k).unwrap_or_else(|| env::panic_str("Overflow"));
        let r_total = reserve_total(s_max, env::storage_byte_cost().as_yoctonear())
            .unwrap_or_else(|| env::panic_str("Overflow"));
        require!(
            env::account_balance().as_yoctonear() >= r_total,
            "InsufficientInitialFunding"
        );

        let this = Self {
            policy,
            policy_hash,
            storage_bound_bytes: s_max,
            reserve_total: r_total,
            charged: 0,
            cb_succeeded_amount: 0,
            cb_failed_amount: 0,
            frozen: false,
            accepted_count: 0,
            seq: 0,
        };
        emit(
            "init",
            json!({
                "seq": "0",
                "vault": this.policy.vault,
                "policy_hash": to_b58(&this.policy_hash),
                "owner": this.policy.owner,
                "agent": this.policy.agent,
                "chain_id": this.policy.chain_id,
                "budget": this.policy.budget.to_string(),
                "max_per_request": this.policy.max_per_request.to_string(),
                "allowed_recipients": this.policy.allowed_recipients,
                "expires_at_ns": this.policy.expires_at_ns.to_string(),
                "max_accepted_requests": k,
                "storage_base_bytes": base_usage.to_string(),
                "storage_bound_bytes": s_max.to_string(),
                "reserve_total": r_total.to_string(),
            }),
        );
        // Init methods cannot return a value through the generated wrapper; return it directly.
        env::value_return(serde_json::to_vec(&to_b58(&this.policy_hash)).unwrap_or_default());
        this
    }

    /// Agent-only, nonpayable. Returns a structured decision. Invalid caller, deposit or
    /// encoding fails the receipt and is not a committed denial.
    #[deny_unknown_arguments]
    pub fn request_payment(
        &mut self,
        request_id: CanonU64,
        recipient: AccountId,
        amount: CanonU128,
        policy_hash: Hash32B58,
    ) -> Decision {
        require!(
            env::predecessor_account_id() == self.policy.agent,
            "Unauthorized"
        );
        let request_id = request_id.0;
        let amount = amount.0;
        match self.check_admission(request_id, &recipient, amount, &policy_hash.0) {
            Ok(recipient_index) => self.admit(request_id, recipient, recipient_index, amount),
            Err((reason, dup)) => self.deny(request_id, recipient, amount, reason, dup),
        }
    }

    /// Private callback; must never change C, policy, count, the ID index or `frozen`.
    #[private]
    #[deny_unknown_arguments]
    pub fn on_payment_result(&mut self, request_id: CanonU64) {
        require!(
            env::promise_results_count() == 1,
            "UnexpectedPromiseResultCount"
        );
        let request_id = request_id.0;
        let mut record =
            read_record(request_id).unwrap_or_else(|| env::panic_str("UnknownRequest"));
        if record.status != CallbackStatus::Pending {
            return; // terminal duplicate: no-op, no event, no seq change
        }
        // A Transfer receipt's success value is empty; `TooLong` can only follow success.
        let succeeded = !matches!(env::promise_result_checked(0, 0), Err(PromiseError::Failed));
        let (status, counter) = if succeeded {
            (CallbackStatus::CbSucceeded, &mut self.cb_succeeded_amount)
        } else {
            (CallbackStatus::CbFailed, &mut self.cb_failed_amount)
        };
        *counter = counter
            .checked_add(record.amount)
            .unwrap_or_else(|| env::panic_str("Overflow"));
        record.status = status;
        write_record(request_id, &record);
        self.seq = checked_inc_u64(self.seq);
        emit(
            "callback",
            json!({
                "seq": self.seq.to_string(),
                "vault": self.policy.vault,
                "policy_hash": to_b58(&self.policy_hash),
                "request_id": request_id.to_string(),
                "amount": record.amount.to_string(),
                "callback_status": status,
                "charged": self.charged.to_string(),
                "cb_succeeded_amount": self.cb_succeeded_amount.to_string(),
                "cb_failed_amount": self.cb_failed_amount.to_string(),
            }),
        );
    }

    /// Owner-only, nonpayable, irreversible and idempotent.
    pub fn freeze(&mut self) {
        require!(
            env::predecessor_account_id() == self.policy.owner,
            "Unauthorized"
        );
        if self.frozen {
            return;
        }
        self.frozen = true;
        self.seq = checked_inc_u64(self.seq);
        emit(
            "freeze",
            json!({
                "seq": self.seq.to_string(),
                "vault": self.policy.vault,
                "policy_hash": to_b58(&self.policy_hash),
                "charged": self.charged.to_string(),
                "accepted_count": self.accepted_count,
            }),
        );
    }

    pub fn get_mandate(&self) -> MandateView {
        let p = &self.policy;
        let now = env::block_timestamp();
        MandateView {
            contract_version: CONTRACT_VERSION.into(),
            chain_id: p.chain_id.clone(),
            vault: p.vault.clone(),
            owner: p.owner.clone(),
            agent: p.agent.clone(),
            asset: "NativeNear".into(),
            budget: U128(p.budget),
            max_per_request: U128(p.max_per_request),
            allowed_recipients: p.allowed_recipients.clone(),
            expires_at_ns: U64(p.expires_at_ns),
            max_accepted_requests: p.max_accepted_requests,
            policy_hash: to_b58(&self.policy_hash),
            policy_hash_hex: to_hex(&self.policy_hash),
            storage_bound_bytes: U64(self.storage_bound_bytes),
            reserve_margin: U128(RESERVE_MARGIN_YOCTO),
            reserve_total: U128(self.reserve_total),
            callback_gas: U64(CALLBACK_GAS.as_gas()),
            charged: U128(self.charged),
            headroom: U128(p.budget - self.charged),
            cb_succeeded_amount: U128(self.cb_succeeded_amount),
            cb_failed_amount: U128(self.cb_failed_amount),
            callback_unconfirmed: U128(
                self.charged - self.cb_succeeded_amount - self.cb_failed_amount,
            ),
            accepted_count: self.accepted_count,
            seq: U64(self.seq),
            frozen: self.frozen,
            expired: now >= p.expires_at_ns,
            block_height: U64(env::block_height()),
            block_timestamp_ns: U64(now),
            account_balance: U128(env::account_balance().as_yoctonear()),
            storage_usage: U64(env::storage_usage()),
        }
    }

    pub fn get_request(&self, request_id: CanonU64) -> Option<RequestView> {
        read_record(request_id.0).map(|r| self.request_view(request_id.0, &r))
    }

    /// Entire accepted index in admission order (at most K <= 64 entries).
    pub fn get_admissions(&self) -> Vec<RequestView> {
        (0..self.accepted_count)
            .map(|pos| {
                let id = read_index(pos).unwrap_or_else(|| env::panic_str("CorruptIndex"));
                let r = read_record(id).unwrap_or_else(|| env::panic_str("CorruptIndex"));
                self.request_view(id, &r)
            })
            .collect()
    }
}

impl Vault {
    /// SPEC-V1.1 §4 admission order. Returns the recipient's allowlist index on success.
    fn check_admission(
        &self,
        request_id: u64,
        recipient: &AccountId,
        amount: u128,
        supplied_policy_hash: &[u8; 32],
    ) -> Result<u8, (DenyReason, Option<(Record, bool)>)> {
        let p = &self.policy;
        if supplied_policy_hash != &self.policy_hash {
            return Err((DenyReason::PolicyMismatch, None));
        }
        if self.frozen {
            return Err((DenyReason::Frozen, None));
        }
        if env::block_timestamp() >= p.expires_at_ns {
            return Err((DenyReason::Expired, None));
        }
        if let Some(r) = read_record(request_id) {
            let terms_match = p.allowed_recipients.get(usize::from(r.recipient_index))
                == Some(recipient)
                && r.amount == amount;
            return Err((DenyReason::DuplicateRequest, Some((r, terms_match))));
        }
        let recipient_index = match p.allowed_recipients.iter().position(|a| a == recipient) {
            Some(i) => i as u8,
            None => return Err((DenyReason::RecipientNotAllowed, None)),
        };
        if amount == 0 {
            return Err((DenyReason::ZeroAmount, None));
        }
        if amount > p.max_per_request {
            return Err((DenyReason::AboveMaxPerRequest, None));
        }
        let after = self
            .charged
            .checked_add(amount)
            .unwrap_or_else(|| env::panic_str("Overflow"));
        if after > p.budget {
            return Err((DenyReason::BudgetExceeded, None));
        }
        if self.accepted_count >= p.max_accepted_requests {
            return Err((DenyReason::RecordQuotaExhausted, None));
        }
        let needed = amount
            .checked_add(self.reserve_total)
            .unwrap_or_else(|| env::panic_str("Overflow"));
        if env::account_balance().as_yoctonear() < needed {
            return Err((DenyReason::InsufficientLiquidity, None));
        }
        Ok(recipient_index)
    }

    fn deny(
        &mut self,
        request_id: u64,
        recipient: AccountId,
        amount: u128,
        reason: DenyReason,
        dup: Option<(Record, bool)>,
    ) -> Decision {
        self.seq = checked_inc_u64(self.seq);
        let original_admission_seq = dup.map(|(r, _)| U64(r.admission_seq));
        let terms_match = dup.map(|(_, m)| m);
        emit(
            "denial",
            json!({
                "seq": self.seq.to_string(),
                "vault": self.policy.vault,
                "policy_hash": to_b58(&self.policy_hash),
                "request_id": request_id.to_string(),
                "recipient": recipient,
                "amount": amount.to_string(),
                "reason": reason,
                "charged": self.charged.to_string(),
                "cb_succeeded_amount": self.cb_succeeded_amount.to_string(),
                "cb_failed_amount": self.cb_failed_amount.to_string(),
                "original_admission_seq": original_admission_seq,
                "terms_match": terms_match,
            }),
        );
        Decision::Denied {
            seq: U64(self.seq),
            request_id: U64(request_id),
            recipient,
            amount: U128(amount),
            reason,
            charged: U128(self.charged),
            original_admission_seq,
            terms_match,
        }
    }

    fn admit(
        &mut self,
        request_id: u64,
        recipient: AccountId,
        recipient_index: u8,
        amount: u128,
    ) -> Decision {
        let charged_before = self.charged;
        self.charged = charged_before
            .checked_add(amount)
            .unwrap_or_else(|| env::panic_str("Overflow"));
        let position = self.accepted_count;
        self.accepted_count = position
            .checked_add(1)
            .unwrap_or_else(|| env::panic_str("Overflow"));
        self.seq = checked_inc_u64(self.seq);

        let record = Record {
            recipient_index,
            amount,
            admission_seq: self.seq,
            status: CallbackStatus::Pending,
        };
        write_record(request_id, &record);
        env::storage_write(&index_key(position), &request_id.to_le_bytes());

        let p = &self.policy;
        let digest = request_digest(
            &p.vault,
            &self.policy_hash,
            &p.agent,
            request_id,
            &recipient,
            amount,
        );

        // Exactly one application Transfer to the allowlisted recipient, then a zero-deposit
        // callback to this vault. Both are immediate host calls inside this receipt.
        let transfer = env::promise_batch_create(&recipient);
        env::promise_batch_action_transfer(transfer, NearToken::from_yoctonear(amount));
        let callback = env::promise_batch_then(transfer, &p.vault);
        let cb_args = format!("{{\"request_id\":\"{request_id}\"}}");
        env::promise_batch_action_function_call(
            callback,
            CALLBACK_METHOD,
            cb_args.as_bytes(),
            NearToken::from_yoctonear(0),
            CALLBACK_GAS,
        );

        emit(
            "admission",
            json!({
                "seq": self.seq.to_string(),
                "vault": p.vault,
                "policy_hash": to_b58(&self.policy_hash),
                "request_id": request_id.to_string(),
                "recipient": recipient,
                "amount": amount.to_string(),
                "request_digest_hex": to_hex(&digest),
                "charged_before": charged_before.to_string(),
                "charged_after": self.charged.to_string(),
                "cb_succeeded_amount_before": self.cb_succeeded_amount.to_string(),
                "cb_failed_amount_before": self.cb_failed_amount.to_string(),
                "accepted_count": self.accepted_count,
            }),
        );
        Decision::Admitted {
            seq: U64(self.seq),
            request_id: U64(request_id),
            recipient,
            amount: U128(amount),
            request_digest_hex: to_hex(&digest),
            charged_before: U128(charged_before),
            charged_after: U128(self.charged),
        }
    }

    fn request_view(&self, request_id: u64, r: &Record) -> RequestView {
        let p = &self.policy;
        let recipient = p.allowed_recipients[usize::from(r.recipient_index)].clone();
        let digest = request_digest(
            &p.vault,
            &self.policy_hash,
            &p.agent,
            request_id,
            &recipient,
            r.amount,
        );
        RequestView {
            request_id: U64(request_id),
            recipient,
            recipient_index: r.recipient_index,
            amount: U128(r.amount),
            admission_seq: U64(r.admission_seq),
            callback_status: r.status,
            request_digest_hex: to_hex(&digest),
        }
    }
}

fn read_record(request_id: u64) -> Option<Record> {
    env::storage_read(&record_key(request_id)).map(|v| {
        near_sdk::borsh::from_slice(&v).unwrap_or_else(|_| env::panic_str("CorruptRecord"))
    })
}

fn write_record(request_id: u64, r: &Record) {
    let v = near_sdk::borsh::to_vec(r).unwrap_or_else(|_| env::panic_str("Serialize"));
    env::storage_write(&record_key(request_id), &v);
}

fn read_index(position: u32) -> Option<u64> {
    env::storage_read(&index_key(position)).map(|v| {
        u64::from_le_bytes(
            v.try_into()
                .unwrap_or_else(|_| env::panic_str("CorruptIndex")),
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use policy::{RECORD_VALUE_BYTES, STATE_VALUE_MAX_BYTES};

    fn acc_of_len(prefix: &str, len: usize) -> AccountId {
        let suffix = ".test.near";
        let s = format!(
            "{}{}{}",
            prefix,
            "a".repeat(len - prefix.len() - suffix.len()),
            suffix
        );
        assert_eq!(s.len(), len);
        s.parse().unwrap()
    }

    #[test]
    fn record_encoding_is_fixed_width() {
        let r = Record {
            recipient_index: 7,
            amount: u128::MAX,
            admission_seq: u64::MAX,
            status: CallbackStatus::CbFailed,
        };
        assert_eq!(
            near_sdk::borsh::to_vec(&r).unwrap().len() as u64,
            RECORD_VALUE_BYTES
        );
    }

    #[test]
    fn maximal_state_fits_declared_bound() {
        let recipients: Vec<AccountId> = (0..MAX_RECIPIENTS)
            .map(|i| acc_of_len(&format!("r{i}"), policy::MAX_ACCOUNT_ID_BYTES))
            .collect();
        let v = Vault {
            policy: Policy {
                chain_id: "c".repeat(MAX_CHAIN_ID_BYTES),
                vault: acc_of_len("v", 64),
                owner: acc_of_len("o", 64),
                agent: acc_of_len("g", 64),
                asset: Asset::NativeNear,
                budget: u128::MAX,
                max_per_request: u128::MAX,
                allowed_recipients: recipients,
                expires_at_ns: u64::MAX,
                max_accepted_requests: MAX_ACCEPTED_REQUESTS,
            },
            policy_hash: [0xff; 32],
            storage_bound_bytes: u64::MAX,
            reserve_total: u128::MAX,
            charged: u128::MAX,
            cb_succeeded_amount: u128::MAX,
            cb_failed_amount: u128::MAX,
            frozen: true,
            accepted_count: u32::MAX,
            seq: u64::MAX,
        };
        let len = near_sdk::borsh::to_vec(&v).unwrap().len() as u64;
        assert!(
            len <= STATE_VALUE_MAX_BYTES,
            "max STATE {len} > {STATE_VALUE_MAX_BYTES}"
        );
    }

    #[test]
    fn decision_json_shape() {
        let d = Decision::Denied {
            seq: U64(3),
            request_id: U64(9),
            recipient: "alice.test.near".parse().unwrap(),
            amount: U128(1),
            reason: DenyReason::BudgetExceeded,
            charged: U128(5),
            original_admission_seq: None,
            terms_match: None,
        };
        let v = serde_json::to_value(&d).unwrap();
        assert_eq!(v["decision"], "Denied");
        assert_eq!(v["reason"], "BudgetExceeded");
        assert_eq!(v["amount"], "1");
    }
}
