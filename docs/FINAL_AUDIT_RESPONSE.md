# Response to the final independent review (2026-11-11)

An independent AI review (Claude, acting as reviewer, 2026-11-11) of `master` at `7c27293` reported nine findings, PW-01 to PW-09. A delta review by the same reviewer of the fix branch (`9f894db`) confirmed the PW-01 fix against the original attack and found one more variant, PW-01b. None of these is in the contract's enforcement logic. This file records what changed on branch `fix/final-audit-findings` (with the PW-01b disclosure added on the release branch) and what did not.

**Unchanged:**
- the contract and its artifact `c7c772635acea0938bd88450d02bcdb9215d9aa65fc407b4070459cd225dd768`;
- the domain separators;
- the deployed testnet accounts;
- all committed evidence, including the testnet run's raw RPC capture and its committed v1 `inspection.json`;
- G1 and G2 results.

No transaction was sent to testnet or mainnet.

## Findings and responses

| ID | Finding (short) | Response | Where |
| --- | --- | --- | --- |
| PW-01 | The testnet inspector accepted a vault without checking how it was created. A creation batch with an extra deploy-and-call can plant a delayed `AddKey` that no state query shows. | **Fixed for the reported creation-batch attack.** A same-name re-creation variant remains (PW-01b, next row). `inspect-smoke` now requires the `create_vault` transaction and re-reads it. It fails closed unless all of these hold: the transaction is FINAL; the batch is exactly `[CreateAccount, Transfer, DeployContract(reviewed artifact), FunctionCall(new, no deposit)]` from the owner; `new` returned the policy hash; the only other receipt is the system's gas refund to the owner. The shape rule is the one the sandbox verifier already used, now a shared function. Output schema `pursewarden-smoke-inspection/v2` adds a `construction` block. | `packages/verifier/inspect_smoke.py`, `packages/verifier/__init__.py` (`keyless_construction_actions`), `tests/evidence/test_testnet_smoke.py`, `tests/evidence/data/` |
| PW-01b | Found by the delta review. The same attack through an earlier account of the same name: create the name with the prelude, delete it, re-create it with the exact approved batch. The planted receipt survives the deletion. | **Not fixed; disclosed.** Confirmed on a sandbox (section below). Standard RPC cannot list an account's earlier lives, so ruling this out needs the account's history or trust in its creator. We do not attempt a protocol-level fix before the deadline. For our own testnet vault, the recorded account history shows no earlier life. | `README.md`, `packages/verifier/inspect_smoke.py` (docstring), `web/src/testnet.tsx`, `evidence/testnet-smoke/account-history-20261111/` |
| PW-02 | Every failure mode strands funds; an agent can use up all K slots with 1-yoctoNEAR payments. | **Documented** (design unchanged; a change would alter the artifact). README "Security limitations" now covers the permanent lockup, the testnet reserve figure and slot exhaustion. | `README.md` |
| PW-03 | The allowlist binds account names, not parties. | **Documented**, including why the demo allowlists a missing account. | `README.md` |
| PW-04 | Live viewer trust, labels and robustness. | **Fixed.** Faster endpoint first, with fallback. Every answer is type-checked and must be for the pinned block; a bad answer shows the error message, never a blank page. Code SHA-256 is computed in the browser from the bytes `view_code` returns. The nine mandate terms are now compared too. The wording says whose answer it is and that both endpoints have one operator. "Nothing should change" is corrected (denied requests still advance `seq`). | `web/src/testnet.tsx`, `web/src/data.ts` |
| PW-05 | Stale counts ("70 tests") and "Three paths … everything runs on your machine". | **Fixed.** All counts say 87, and the Reproduce page says five ways, the fifth needing internet. The CI step name no longer carries a count. | `web/src/pages.tsx`, `.github/workflows/ci.yml`, `README.md`, `docs/SUBMISSION.md`, `docs/RELEASE_CHECKLIST.md` |
| PW-06 | The verifier's fixed limitation "No native-pending witness" sits next to six witnesses in G2 `result.json`. | **Clarified**, not regenerated. A note in `docs/G2_RESULT.md` and a code comment explain that the sentence predates G2 and concerns RPC submission timing. | `docs/G2_RESULT.md`, `packages/verifier/__init__.py` |
| PW-07 | `run_g1.py` / `run_g2.py` die mid-run with "AF_UNIX path too long" under long paths. | **Mitigated.** Both stop immediately with a clear message when the socket path would exceed 107 bytes, and README steps 5–6 document `NEAR_VAULT_TOOLS`. The socket location itself is unchanged, so the G1/G2 tooling behaves exactly as before for valid paths. | `scripts/g1-independent/run_g1.py`, `scripts/g2-independent/run_g2.py`, `README.md` |
| PW-08 | Pages did not redeploy on web changes; actions pinned by tag. | **Fixed.** A push to `master` touching `web/**`, `evidence/**`, `packages/**` or `scripts/build_web_bundle.py` now deploys. All actions in both workflows are pinned to the commit SHAs their tags pointed to on 2026-11-11. | `.github/workflows/pages.yml`, `.github/workflows/ci.yml`, `docs/DEPLOY.md` |
| PW-09 | X draft "A settled-only design paid out 17" lacks "our own". | **Fixed.** Version A says "A deliberately broken control paid out 17." and is still 278 characters. Version B says "our own deliberately broken control". | `docs/SUBMISSION.md` |

## PW-01: the review's proof of concept, before and after

Run on a fresh local nearcore 2.13.4 sandbox with the review's driver and its prelude contract (SHA-256 `90ad37d9…f89e`). The creation batch was `[CreateAccount, Transfer, DeployContract(prelude), FunctionCall(arm), DeployContract(c7c77263), FunctionCall(new)]`. Sandbox only; nothing touched testnet.

| Moment | Previous inspector (`master` `7c27293`) | Fixed inspector |
| --- | --- | --- |
| Before the planted key fires (0 keys, code `c7c77263`, frozen); the run file without a creation record, exactly as an attacker would hand it over | **PASS** (the false pass) | **FAIL** `CREATION_TX_MISSING` |
| Same moment, with the real creation transaction listed | (not checked) | **INCONCLUSIVE** `CREATION_TX_UNAVAILABLE`: a batch with an outstanding postponed receipt is not FINAL, so the node cannot return it as FINAL |
| After the key fires (~200 blocks later), with the creation transaction listed | FAIL `WRONG_CONTRACT`, only because the planted key had already replaced the code and emptied the vault | **FAIL** `KEYLESS_CONSTRUCTION` (six actions) |

The creation graph recorded after the key fired is committed as regression data (`tests/evidence/data/pw01_timebomb_creation.json`, sandbox only; not project evidence).

The genuine public testnet inspection still passes. Replaying its committed raw RPC capture reproduces every field of the committed PASS. It adds only the `construction` block, derived from the creation transaction `BQfmcRW9…2YVw` already in that capture: exactly four actions, `new` returned `fAFXFPi7…G3rQZhzL`, and one other receipt (the owner's gas refund).

## PW-01b: an earlier account of the same name (confirmed, not fixed)

The delta review ran this on a fresh local sandbox (`vault.rb.test.near`), with its own driver. We did not re-run it. Its evidence is in the reviewer's report, not in this repository.

1. The owner creates the vault name with `[CreateAccount, Transfer, DeployContract(prelude), FunctionCall(arm), AddKey(temporary)]`. `arm` schedules a delayed `AddKey`.
2. The temporary key deletes the account. The balance returns to the owner.
3. The owner creates the name again with exactly the approved four-action batch. That transaction is FINAL at once and passes every construction check.
4. The agent pays once and the owner freezes.

**Results.**
- At final block 307, the fixed `inspect-smoke` returned **PASS**: code `c7c77263…`, 0 keys, frozen, and a `construction` block showing four actions and nothing scheduled.
- At block 337, about 200 blocks after step 1, a full-access key appeared on the vault.
- By block 601, that key had replaced the code and moved 5.6204 NEAR out.

**What this means.**
- **What a PASS covers.** A PASS covers the listed creation transaction and the state at the inspected block. It is **not** proof that a vault created by someone else can never acquire a key.
- **Who can do this.** The attacker is whoever can create the name, which is the name's parent. That is normally the vault's owner, the very party a third party would be checking.
- **No time limit.** The delay is not bounded by 200 blocks in general.

**Our testnet vault.**
- `evidence/testnet-smoke/account-history-20261111/` records the indexer history of the vault and its owner, and the owner key's nonce.
- The owner's only key has signed at most four transactions, and the four recorded in `run.json` account for all of them.
- The vault's first transaction is the four-action creation.
- This rests on one indexer and one RPC operator. It is not a proof.

**The sandbox verifier.**
- It reads every block from its pinned start block and requires the vault name to be absent there.
- By code reading, it would fail on an earlier account created inside that window; we did not run this.
- It would not see one created before the window.
- The G1 and G2 evidence comes from fresh sandbox chains started by the run tooling.

## Regressions added (12, in `tests/evidence/test_testnet_smoke.py`)

The creation record is omitted, listed twice, listed with another signer, unavailable from the node, or not FINAL. The creation batch includes the review's prelude deploy-and-call. Six other altered batches: an extra `AddKey`, a second deploy, wrong code, another init method, a deposit on `new`, reordered actions. The receipt's actions differ from the signed transaction. A delayed `AddKey` or a yielded receipt from the vault is grafted onto the creation receipt. `new` returned a different policy hash. Finally, the real recorded creation graph from the review's sandbox attack is checked.

Three of these inputs (omitted record, prelude batch, delayed `AddKey`) were also run through the previous inspector. It returned PASS for all three.

Evidence tests: 87, all passing. Contract tests: 12, unchanged.

## Known residual limitations

- **Earlier accounts with the same name (PW-01b, confirmed).**
  - The testnet inspector cannot see receipts left by an earlier account of the same name, created, deleted and re-created before this vault.
  - The delta review showed on a sandbox that such a receipt survives the deletion, that the fixed inspector passes the re-created vault, and that the receipt adds a full-access key about 200 blocks later.
  - Only the name's parent can create the name, and the parent is normally the owner being checked. So a PASS does not prove keylessness against the vault's creator without the account's history.
  - Our testnet vault's recorded history shows no earlier life.
- **One RPC node.** The testnet inspection trusts one RPC node. The live viewer trusts one operator: both endpoints are FastNear. Only the code hash is computed in the browser.
- **Live viewer shows current state.** It does not re-read the creation transaction live; the creation check comes from the inspector and is shown from the recorded inspection.
- **Runner-listed transactions.** The testnet inspection still lists only the runner's transactions. It remains a smoke inspection, not a completeness proof.
- **Unchanged by choice.** PW-02 and PW-03 are design properties and stay as they are for this submission. The PW-06 sentence stays in the committed results. PW-07's socket location is unchanged.
- **Review's extra scenarios.** The review's four newly executed sandbox scenarios (expiry, liquidity, top-up, K = 64) have not been re-run by us. The README attributes them.
