# Pursewarden: fixed-budget NEAR vaults for AI agents

> **Status: experimental hackathon prototype (NEAR HACKATHON 2026, track `security`).** All evidence comes from a **local NEAR sandbox**. Nothing here is deployed to testnet or mainnet. Not audited. Do not use it for real custody. "Pursewarden" is a provisional name.

## What it is

An AI agent that can pay for things needs spending authority. A wallet key gives it unlimited authority, and an off-chain policy layer can be bypassed. Pursewarden puts the limit on chain and keeps the keys away from the agent:

1. **A vault contract (Rust, NEAR).** The owner creates it once, **keyless**, in a single `CreateAccount + Transfer + DeployContract + new` batch. Its mandate is immutable:
   - budget **B**;
   - per-request cap **M**;
   - recipient allowlist;
   - expiry;
   - at most **K** accepted requests.

   On each request the vault does, in one receipt:
   - charges the cumulative total **C** before sending;
   - records the request ID;
   - schedules one native transfer plus a callback.

   **Nothing ever decreases C.** A transfer that fails and is refunded stays charged, so authority cannot be recycled. The vault has no withdraw, upgrade, key or policy-change code path. The owner can only freeze it, irreversibly.
2. **A restricted agent.** The agent account holds only NEAR **function-call access keys**, limited to `request_payment` on the vault with zero deposit. It cannot transfer, deploy, add keys or call anything else.
3. **An independent verifier (Python, stdlib only).** "Independent" here means it gathers its own evidence and does not trust the runner's report. It is **not** an external audit: one team wrote the verifier, the runner and the contract, and in the recorded runs both roles shared one machine, separated by Linux namespaces. It rebuilds what happened from a reviewer-chosen node, scanning every block and chunk in a window. It reconciles:
   - receipts;
   - native transfer outcomes and refunds;
   - raw contract storage;
   - the policy hash;
   - committed events;
   - the per-block state history.

   If a runner hands over a bundle that silently omits a transaction, the verifier finds the transaction on its own and marks the bundle **FAIL**.
4. **An Attack Lab (static web app).** A read-only replay of the recorded runs: decisions, receipt trees and the verifier catching a forged bundle.

How NEAR fits: function-call access keys give the agent a capability without custody. Keyless contract accounts and the receipt model let one receipt charge the budget and schedule the payment atomically. Failed transfers are refunded by `system` receipts that the verifier can tell apart from gas refunds.

## Try it: "do X → see Y"

Prerequisites:
- **Steps 1–2:** Python ≥ 3.10 (standard library only).
- **Step 3:** Node ≥ 20.
- **Steps 4–5:** Linux x86-64, `rustup`, `bubblewrap` (`bwrap`) and `curl`.

No wallet, account or funds are needed for any step.

### 1. Re-verify the recorded evidence (about 2 s)

```bash
python3 -m unittest discover -s tests/evidence -t .
```

**See:** `Ran 61 tests … OK`.
- 43 synthetic adversarial tests run against a fake RPC oracle.
- 11 runner-boundary regressions: runner-planted symlinks must never make the reviewer read a private file. 3 of them run through the real sandbox and skip if `bwrap` is unavailable.
- 7 tests run against **actual recorded nearcore 2.13.4 responses**. They replay every committed independent run and check:
  - the exact ledger: C = 3, S = 1, F = 2, U = 0 NEAR, headroom 2;
  - recovery of the omitted transaction root;
  - that 18 tamperings of the genuine responses are all rejected.

### 2. Re-run the verifier comparison by hand (under 1 s)

```bash
R=evidence/g1-independent/g1i-20261110T135044Z-a
python3 -m packages.verifier mutate --rpc-records $R/independent/rpc.jsonl.gz \
  --descriptor $R/reviewer-descriptor.json --out /tmp/mutations.json
```

**See:** `"all_applied_and_rejected": true`, with each tampering mapped to the verifier finding that rejected it. Examples: `WRONG_GENESIS`, `TRANSFER_TERMS`, `CHARGE_DECREASED`, `VAULT_HAS_KEYS`, `UNMATCHED_ADMISSIONS`.

Then open `$R/compare-forged.json`. **See:** `"evidence": "FAIL"` and an `OMITTED_ROOT` entry. That entry holds the payment the runner hid: class `F`, `AccountDoesNotExist`, and its 2 NEAR principal refund receipt.

### 3. Open the Attack Lab (about 1 min)

```bash
cd web && npm ci && npm run build && npx vite preview --port 4173
```

Then open `http://127.0.0.1:4173/#/lab`. **See:**
- The mandate: B = 5, M = 2, K = 2, vault with **0 keys**.
- The authority bar: 1 NEAR settled, 2 NEAR failed but charged, 2 NEAR headroom.
- The attack trace: two admissions, then four denials (DuplicateRequest, AboveMaxPerRequest, RecipientNotAllowed, RecordQuotaExhausted), one malformed-input receipt failure, the owner freeze, and four key abuses rejected before reaching the chain.
- Clicking a row opens its receipt tree.

`#/verify` shows the forged bundle next to the independent capture. Every page is labelled **REPLAY · SANDBOX**.

`web/public/bundle.json` is regenerated from the committed raw RPC by `python3 scripts/build_web_bundle.py`.

### 4. Rebuild the contract and compare bytes (about 2 min with a warm toolchain)

```bash
rustup toolchain install 1.93.0 --target wasm32-unknown-unknown --profile minimal
cargo +1.93.0 install cargo-near --version =0.22.0 --locked --no-default-features \
  --root ~/.local/share/near-agent-vault-lab/cargo-near-0.22.0
cargo test -p near-agent-vault --locked     # 12 tests: SPEC vectors, canonical parsing, storage bound
scripts/build-contract.sh                   # prints sha256 c7c77263…dd768 and "capability gate: PASS"
git diff --exit-code artifacts/             # the rebuilt WASM equals the committed one
```

**See:**
- The artifact SHA-256 is `c7c772635acea0938bd88450d02bcdb9215d9aa65fc407b4070459cd225dd768`.
- The capability gate passes: there are no key, deploy, delete or stake host imports, and exactly 8 callable exports.

A byte-identical rebuild has been shown from two checkout paths on one machine. **Cross-machine reproduction has not been tested yet.**

### 5. Run a fresh independent G1 experiment yourself (about 5 min)

```bash
cargo +1.93.0 build -p g1-sandbox-tests --locked --bin g1_actor
python3 scripts/g1-independent/run_g1.py my-run --rpc-port 3240 --net-port 24777
```

This command:
- downloads the pinned nearcore 2.13.4 sandbox and checks its SHA-256;
- starts a fresh local chain;
- creates the vault keyless;
- runs the agent workload inside `bwrap` with only agent keys and a filtered RPC socket;
- freezes the vault and picks the final cut Q;
- collects independently;
- forges an omission;
- runs the 18 mutations;
- waits 2,000 blocks and re-reads.

**See:** `isolation PASS`, then independent verdicts `safety/settlement/evidence/scenario_coverage: PASS`, then the forged bundle `evidence: FAIL` with `omitted_root_matches_forger: true`. Results land in `evidence/g1-independent/my-run/`. Private keys stay under `~/.local/share/near-agent-vault-lab/g1-independent/my-run/`.

## What the recorded runs show

Three fresh sandbox chains were used: `test-chain-d8AyA` (run C, after the review fix), `test-chain-6J4eY` and `test-chain-oJOg4`. All three used the same artifact and the same scenario.

| Step | Request | Decision | Effect (from the reviewer's own capture) |
| --- | --- | --- | --- |
| 1 | ID 1: 1 NEAR → `alice.test.near` | Admitted | Transfer succeeded. C = 1. |
| 2 | ID 2: 2 NEAR → `missing.test.near` (allowlisted, does not exist) | Admitted | Transfer failed (`AccountDoesNotExist`). A `system` receipt refunded 2 NEAR to the vault. **C = 3 anyway.** |
| 3 | ID 1 again | Denied `DuplicateRequest` | No transfer |
| 4 | 2 NEAR + 1 yocto | Denied `AboveMaxPerRequest` | No transfer |
| 5 | 1 NEAR → `attacker.test.near` | Denied `RecipientNotAllowed` | No transfer |
| 6 | 2 NEAR → alice (C + 2 = 5 ≤ B, but K = 2 is used up) | Denied `RecordQuotaExhausted` | No transfer. The refund did not restore authority. |
| 7 | amount `"1e24"` | Receipt failure (`MalformedInput`) | No vault data committed, checked against per-block history (gas and nonce are still spent) |
| 8–11 | Agent key calls `freeze`, transfers, attaches a deposit, calls another receiver | Rejected by NEAR before inclusion | No chain trace |
| 12 | Owner `freeze` | Frozen | No further admissions |

Final cut: count = 2, C = 3, S = 1, F = 2, U = 0, headroom = 2 NEAR. The vault has zero keys from creation to Q, and its code was deployed exactly once. Details: [`docs/G1_INDEPENDENT_RESULT.md`](docs/G1_INDEPENDENT_RESULT.md).

## Claims and limits

| Claimed (tested on local sandbox) | Assumed | Not claimed |
| --- | --- | --- |
| C ≤ B, and C never decreases, including after refunds | The NEAR runtime executes receipts as specified | Prompt-injection defence: an agent can still waste its budget on allowlisted payees |
| A failed transfer is charged (F) even though its principal is refunded | The owner sets an honest mandate and allowlist | Testnet or mainnet enforcement, or custody safety |
| Denied requests (replay, cap, allowlist, quota) make no transfer, don't increase C and don't use up an admission slot; each denial advances the audit sequence. Malformed-input failures commit no vault data. | The reviewer's node reports the chain truthfully (no light-client or consensus proofs) | Audit or formal verification |
| The vault stays keyless, with code deployed once | The deployed bytes are the reviewed source (checked by hash and rebuild) | Late-failure atomicity under FAULT builds, forced callback failure on chain, K = 64 storage, insufficient liquidity, executed expiry (not run) |
| The independent collector recovers a root that a runner omitted, without being given its hash | Runner isolation is by Linux namespaces on one host | Concurrency comparisons against other designs (G2, not run) |

Residual vault funds have **no** withdrawal path by design, so this is a research vault, not a product wallet.

## Repository map

| Path | What |
| --- | --- |
| `contracts/vault/` | The vault contract (near-sdk 5.29.1, low-level promise host calls only) |
| `artifacts/` | The committed WASM, its SHA-256 and the capability report. `legacy/` holds the pre-remap `5b05246b` build. |
| `scripts/build-contract.sh`, `scripts/inspect_wasm.py` | Pinned build and fail-closed import/export gate |
| `packages/collector`, `packages/verifier` | Independent acquisition and verification (stdlib Python) |
| `tests/evidence/` | Synthetic adversarial tests and replay regressions on real responses |
| `tests/sandbox/` | Rust sandbox harness: sign-once transactions, independent encoder/decoder, `g1_actor` role binary |
| `scripts/g1-independent/` | Run orchestrator, filter proxy, sandbox bridge, isolation probe, retention comparison |
| `scripts/sandbox-setup/` | Pinned nearcore 2.13.4 sandbox start/stop |
| `evidence/g1-independent/` | Two evidence runs and two retained development attempts |
| `evidence/g1/` | Agent A's original Oct 29 runner evidence. Its node history has since been pruned. |
| `web/` | Attack Lab (Vite, React) |
| `docs/` | Gate results, interface, review handoff, submission notes |

## Timeline, provenance and disclosures

- **Timeline.**
  - The hackathon was announced on 2026-10-19.
  - This repository's first commit (`2ca4b51`, README only) is from 2026-10-29.
  - All code was written on or after 2026-10-29, so all of it falls inside the window in which "code written since the announcement counts".
  - Research and specification documents from 2026-10-20 onward are not part of this repository.
  - The `integration/g1-recovery` history shows each step: contract (`c9da90c`), evidence collector (`90506c0`), integration and repair (`e1e5257` onward).
- **AI-generated code.** Most of the code, tests and documentation were written by AI coding agents (Claude Code with Claude Opus, and OpenAI Codex) under the owner's direction, with separate agents for contract, evidence, review and recovery. An independent AI review (OpenAI Codex, 2026-11-10, `reports/G1_CODEX_REVIEW_2026-11-10.md`) found one flaw in the run tooling: the reviewer followed runner-planted symlinks when importing runner output. It also found inaccurate wording about denials. Both are fixed; see `docs/G1_INDEPENDENT_RESULT.md`.
- **Libraries.**
  - Contract: `near-sdk` 5.29.1 is its only direct dependency (with its transitive `borsh` and `serde_json`). It is built with `cargo-near` 0.22.0 and `wasm-opt`.
  - Harness: `near-primitives`/`near-crypto` 0.37.4, `reqwest`, `tokio`, `anyhow`, `borsh`, `bs58`, `sha2`, `base64`.
  - Verifier: Python standard library only.
  - Web: React 19, Vite 8, `lucide-react`, Geist fonts (OFL-1.1) via Fontsource.
  - Runner isolation: bubblewrap.
  - Exact versions are in `Cargo.lock` and `web/package-lock.json`.
- **NEAR node.** The official nearcore 2.13.4 sandbox binary, from the URL that `near-sandbox` 0.3.16 uses, pinned by SHA-256.

## License

See [`LICENSE`](LICENSE).
