//! VULNERABLE TEACHING FIXTURE: local sandbox only, project-owned. It is not, and does not model,
//! any other project's code. It exists only as the negative control of the G2 comparison.
//!
//! The deliberate bug: admission checks the budget against SETTLED spend only. `settled` grows
//! in the transfer callback, one or more blocks after admission, so every request admitted in
//! the same block sees the same stale value. A burst of requests can therefore commit more
//! principal than the budget. The protected vault charges C at admission instead.
use near_sdk::json_types::U128;
use near_sdk::serde_json::json;
use near_sdk::{env, near, require, AccountId, Gas, NearToken, PanicOnDefault, Promise, PromiseError};

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct Fixture {
    agent: AccountId,
    budget: u128,
    max_per_request: u128,
    allowed_recipients: Vec<AccountId>,
    settled: u128,
    admitted: u32,
    seq: u64,
}

fn event(kind: &str, data: near_sdk::serde_json::Value) {
    env::log_str(&format!(
        "FIXTURE_EVENT:{}",
        json!({"fixture": "vulnerable-settled-only", "event": kind, "data": data})
    ));
}

#[near]
impl Fixture {
    #[init]
    pub fn new(agent: AccountId, budget: U128, max_per_request: U128, allowed_recipients: Vec<AccountId>) -> Self {
        Self { agent, budget: budget.0, max_per_request: max_per_request.0, allowed_recipients,
               settled: 0, admitted: 0, seq: 0 }
    }

    pub fn request_payment(&mut self, request_id: String, recipient: AccountId, amount: U128) -> String {
        require!(env::predecessor_account_id() == self.agent, "Unauthorized");
        let amount = amount.0;
        self.seq += 1;
        let reason = if !self.allowed_recipients.contains(&recipient) {
            Some("RecipientNotAllowed")
        } else if amount == 0 || amount > self.max_per_request {
            Some("AboveMaxPerRequest")
        } else if self.settled + amount > self.budget {
            // BUG (deliberate): in-flight transfers are invisible to this check.
            Some("BudgetExceeded")
        } else {
            None
        };
        if let Some(r) = reason {
            event("denial", json!({"seq": self.seq.to_string(), "request_id": request_id, "reason": r,
                                   "settled": self.settled.to_string()}));
            return format!("Denied:{r}");
        }
        self.admitted += 1;
        event("admission", json!({"seq": self.seq.to_string(), "request_id": request_id,
                                  "amount": amount.to_string(), "settled_seen": self.settled.to_string()}));
        Promise::new(recipient)
            .transfer(NearToken::from_yoctonear(amount))
            .then(Self::ext(env::current_account_id()).with_static_gas(Gas::from_tgas(10)).on_settled(U128(amount)));
        "Admitted".to_string()
    }

    #[private]
    pub fn on_settled(&mut self, amount: U128) {
        if !matches!(env::promise_result_checked(0, 0), Err(PromiseError::Failed)) {
            self.settled += amount.0;
        }
    }

    pub fn get_state(&self) -> near_sdk::serde_json::Value {
        json!({"fixture": "vulnerable-settled-only", "budget": self.budget.to_string(),
               "settled": self.settled.to_string(), "admitted": self.admitted, "seq": self.seq.to_string()})
    }
}
