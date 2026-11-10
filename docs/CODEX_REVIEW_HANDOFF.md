# Independent review handoff (for one focused Codex session)

**Goal:** an adversarial, bounded review of whether the G1 PASS claim in `docs/G1_INDEPENDENT_RESULT.md` holds. Return **GO** (publish as scoped), **NARROW** (name one blocker and its fix) or **STOP** (give a decisive counterexample). Review only: do not push, merge, deploy, sign or publish.

## Exact revisions

| What | Revision |
| --- | --- |
| Branch under review | `integration/g1-recovery`, worktree `~/Dev/Hackathons/NEAR/near-agent-vault-integration` (resolve HEAD with `git -C … rev-parse HEAD`) |
| Common baseline | `2ca4b51121e01dcb29d090bf37541f4ea537c82b` |
| Contract implementation (Agent A, unchanged since) | `c9da90ceb8676e81d96620f45d40ace2aa3a8914`. `git diff c9da90c HEAD -- contracts/ Cargo.toml Cargo.lock rust-toolchain.toml` is empty. |
| Evidence implementation (Agent B) | `90506c0c20ee9783bb03cee9ab7ec97f4537f49f` |
| Integration merge | `e1e5257` (`.gitignore` was the only conflict) |
| Artifact remap | `670dbf6` (`c7c77263…` replaces `5b05246b…`) |
| Verifier repair and run tooling | `91c4ce6` |
| Fixture, tests, failed-callback handling | `e783dac` |
| Evidence runs A and B | `bbf7924` (runs executed at `91c4ce6` and `e783dac`, respectively) |
| Web, docs, submission kit | `5ecb5cd`, `58a28db`, `f2f8cce`, `106f9c2` and later |

The prior decision being answered is `~/Dev/Hackathons/NEAR/reports/G1_Independent_Integration_Decision_2026-10-29.md` (§4 acceptance gate).

## Commands (all local; no funds; about 10 minutes in total)

```bash
cd ~/Dev/Hackathons/NEAR/near-agent-vault-integration
python3 -m unittest discover -s tests/evidence -t .                  # expect 50 OK
cargo +1.93.0 test -p near-agent-vault --locked                      # expect 12 OK
scripts/build-contract.sh && git diff --exit-code artifacts/         # expect c7c77263…, gate PASS
R=evidence/g1-independent/g1i-20261110T135044Z-a
python3 -m packages.verifier mutate --rpc-records $R/independent/rpc.jsonl.gz \
  --descriptor $R/reviewer-descriptor.json --out /tmp/mut.json      # expect all_applied_and_rejected
cargo +1.93.0 build -p g1-sandbox-tests --locked --bin g1_actor
python3 scripts/g1-independent/run_g1.py review-$(date +%s) --rpc-port 3270 --net-port 24807   # fresh run, about 5 min
```

## Highest-risk areas (please attack these first)

1. **Completeness of discovery** (`packages/collector/__init__.py:collect`). Roots come only from chunks newly included in (H0, Q]. Questions to answer:
   - Can a vault-affecting receipt originate from a root outside the window and so stay invisible? The current defence is H0 absence of the vault and agent, plus `STATE_CAUSE_UNMAPPED` on every vault/agent state change.
   - Do local receipts, delayed receipts or self-transactions break the model?
   - Is the bounded-finality substitute sound: Q must be the canonical block at `q_height` and ≤ the final head, instead of crawling head→Q?
2. **Verifier soundness** (`packages/verifier/__init__.py:analyze`, `history_check`, `one_cut`). Look for an internally consistent but false capture that still yields all-PASS. The trust model is the reviewer's own node, so focus on logic gaps rather than node lies. Candidate gaps:
   - `failure_summary` classifies failures by string matching. It is used only for labels; confirm it never gates safety.
   - `vault_events` allows at most one event per receipt.
   - Plain inbound deposits are allowed as `InboundDeposit`.
   - View-method transactions are allowed if they have no effect.
   - `compare_bundle` compares a fixed field list.
3. **Isolation** (`scripts/g1-independent/run_g1.py:bwrap`, `rpc_filter_proxy.py`, `sandbox_bridge.py`). Can the runner reach the node, the admin RPC, the node home or the owner key by any path? Ideas to try:
   - `/proc`;
   - abstract Unix sockets;
   - JSON-RPC batch arrays;
   - method-name variants;
   - `query` request types;
   - large bodies;
   - the socket file sitting in the writable runner directory.

   Also judge whether "same host, same UID, kernel namespaces" is an adequate claim for a hackathon G1.
4. **Orchestration claims.** Is H0 truly before construction with no unknown application work? Is Q after all effects (freeze outcome + 20 blocks)? Is ingress closed before the freeze (the submit proxy stops before `reviewer-freeze`)? The retention comparison bug (live `status` compared byte-for-byte) is disclosed in `evidence/g1-independent/ATTEMPTS.md`. Confirm that `retention-compare.json` is the right comparison.
5. **Artifact equivalence.** Same source, with one extra `--remap-path-prefix`. Is "documented, independently rebuilt equivalent" justified? Cross-machine rebuild is untested.
6. **Contract** (`contracts/vault/src/lib.rs`, `canonical.rs`, `policy.rs`), unchanged since Agent E reviewed it. Re-check:
   - admission ordering and atomicity;
   - that the callback cannot decrease C;
   - the freeze idempotent rewrite;
   - the reserve / `InsufficientLiquidity` arithmetic (not executed on chain).
7. **Public presentation** (`README.md`, `web/src/pages.tsx`, `docs/SUBMISSION.md`). Flag any sentence that claims more than the evidence supports. Examples to check:
   - "9 attacks stopped" counts 4 denials, 1 receipt failure and 4 pre-inclusion rejections;
   - "Repeated on 1 more fresh node";
   - the claims ledger.

## Known limitations (already disclosed; do not re-report unless mis-stated)

- Trusted-node observations; there are no light-client or consensus proofs.
- Runner/reviewer separation is by namespace on one host, and the same author wrote both.
- Not executed: R3 FAULT builds, R4 forced callback failure on chain, K = 64, InsufficientLiquidity, expiry, G2 concurrency or native-pending witness, testnet, mainnet.
- Runner-reported pre-inclusion rejections are shown as runner-reported.

## Open questions for the reviewer

1. Is G1 PASS, as scoped in `docs/G1_INDEPENDENT_RESULT.md`, acceptable? Or should the published wording be narrower?
2. Is any of the 18 mutations rejected for an incidental reason that would hide a real gap (see `mutations.json` → `issues`)?
3. Should the public README avoid the word "independent" given that one author wrote the reviewer and runner code? It currently says "independent verifier", meaning it does not trust the agent or runner.
4. Is the web bundle's data derivation (`scripts/build_web_bundle.py`, a replay through the verifier) faithful, with no UI number that lacks a source?
