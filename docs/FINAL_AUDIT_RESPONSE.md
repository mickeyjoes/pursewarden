# Response to the final independent review (2026-11-11)

An independent AI review (Claude, acting as reviewer, 2026-11-11) of `master` at `7c27293` reported nine findings, PW-01 to PW-09. None is in the contract's enforcement logic. This file records what changed on branch `fix/final-audit-findings` and what did not.

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
| PW-01 | The testnet inspector accepted a vault without checking how it was created. A creation batch with an extra deploy-and-call can plant a delayed `AddKey` that no state query shows. | **Fixed.** `inspect-smoke` now requires the `create_vault` transaction and re-reads it. It fails closed unless all of these hold: the transaction is FINAL; the batch is exactly `[CreateAccount, Transfer, DeployContract(reviewed artifact), FunctionCall(new, no deposit)]` from the owner; `new` returned the policy hash; the only other receipt is the system's gas refund to the owner. The shape rule is the one the sandbox verifier already used, now a shared function. Output schema `pursewarden-smoke-inspection/v2` adds a `construction` block. | `packages/verifier/inspect_smoke.py`, `packages/verifier/__init__.py` (`keyless_construction_actions`), `tests/evidence/test_testnet_smoke.py`, `tests/evidence/data/` |
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

## Regressions added (12, in `tests/evidence/test_testnet_smoke.py`)

The creation record is omitted, listed twice, listed with another signer, unavailable from the node, or not FINAL. The creation batch includes the review's prelude deploy-and-call. Six other altered batches: an extra `AddKey`, a second deploy, wrong code, another init method, a deposit on `new`, reordered actions. The receipt's actions differ from the signed transaction. A delayed `AddKey` or a yielded receipt from the vault is grafted onto the creation receipt. `new` returned a different policy hash. Finally, the real recorded creation graph from the review's sandbox attack is checked.

Three of these inputs (omitted record, prelude batch, delayed `AddKey`) were also run through the previous inspector. It returned PASS for all three.

Evidence tests: 87, all passing. Contract tests: 12, unchanged.

## Known residual limitations

- **Earlier accounts with the same name.** Neither the inspector nor the sandbox verifier can see receipts left by an earlier account of the same name, created, deleted and re-created before this vault. We have not tested whether a postponed receipt survives an account's deletion. Only the name's parent account (here the owner) can create the name.
- **One RPC node.** The testnet inspection trusts one RPC node. The live viewer trusts one operator: both endpoints are FastNear. Only the code hash is computed in the browser.
- **Live viewer shows current state.** It does not re-read the creation transaction live; the creation check comes from the inspector and is shown from the recorded inspection.
- **Runner-listed transactions.** The testnet inspection still lists only the runner's transactions. It remains a smoke inspection, not a completeness proof.
- **Unchanged by choice.** PW-02 and PW-03 are design properties and stay as they are for this submission. The PW-06 sentence stays in the committed results. PW-07's socket location is unchanged.
- **Review's extra scenarios.** The review's four newly executed sandbox scenarios (expiry, liquidity, top-up, K = 64) have not been re-run by us. The README attributes them.
