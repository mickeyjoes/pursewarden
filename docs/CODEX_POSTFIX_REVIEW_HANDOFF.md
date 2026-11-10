# Focused post-fix review handoff (one Codex session)

**Goal:** a bounded adversarial review of the work since the first Codex review (`reports/G1_CODEX_REVIEW_2026-11-10.md`, of `7fa66e2`, which returned NARROW). Return **GO**, **NARROW** with one blocker and its fix, or **STOP** with a counterexample. Review only: do not push, merge, deploy, sign or publish.

## Exact revisions

| What | Revision |
| --- | --- |
| Released G1 baseline (pushed, private) | `master` = `integration/g1-recovery` = `d948613` |
| C1 fix (safe import, read-only socket directories, probe first) | `71a679c` (in `d948613`) |
| Post-fix G1 run C | `evidence/g1-independent/g1i-20261110T144905Z-c` (at `71a679c`) |
| **Under review:** branch `feat/g2-concurrency`, worktree `~/Dev/Hackathons/NEAR/near-agent-vault-g2` | `d948613..HEAD` (resolve HEAD with `git -C … rev-parse HEAD`) |
| G2 implementation | `acd6ba6`: fixture, `g2_actor`, collector refactor, `pending_witness`, control audit, `run_g2.py` |
| G2 evidence | `e4bda7a`: runs `g2i-20261110T154252Z-a` and `-b`, at `acd6ba6`, clean tree |
| UI, docs, CI | `f2261ac`, `9092c74` and later |

## Commands (local, no funds, about 5 minutes)

```bash
cd ~/Dev/Hackathons/NEAR/near-agent-vault-g2
python3 -m unittest discover -s tests/evidence -t .          # expect 68 OK (bubblewrap tests need unprivileged userns)
cargo +1.93.0 test -p near-agent-vault --locked              # expect 12 OK (contract unchanged since c9da90c)
python3 scripts/build_web_bundle.py && git diff --exit-code web/public/bundle.json
cargo +1.93.0 build -p g1-sandbox-tests --locked --bin g2_actor
python3 scripts/g2-independent/run_g2.py review-g2-$(date +%s) --rpc-port 3330 --net-port 24867   # about 25 s
python3 reports/codex-review-20261110/reproduce_output_boundary.py   # NOTE: targets the OLD bwrap(runner_dir, script) API; expected to break. The equivalent regressions are tests/evidence/test_runner_boundary.py
```

## Attack these first

1. **C1 fix completeness** (`scripts/g1-independent/safe_import.py`, `run_g1.py:sandbox/fresh_dir`, phases 4a/4b/8). Are there any remaining reviewer-side reads of, or writes to, a runner-writable tree that bypass `read_untrusted`? Look at the probe, workload and presentation phases, and at `run_g2.py`, which reuses them. Questions:
   - Is the descriptor-relative `O_NOFOLLOW` walk sufficient? Consider `/proc/self/fd` tricks, bind-mount aliasing, a TOCTOU between `fstat` and `read`, and hard links (rejected via `st_nlink`).
   - Do read-only socket directories plus fresh-directory-per-phase close the write-through-symlink path?
2. **The pending-witness logic** (`packages/verifier/__init__.py:pending_witness`). The definition:
   - earlier admissions are those with admission seq below the denial's seq;
   - an earlier admission is pending when its native transfer outcome is in a block **strictly higher** than the denial's block;
   - settled spend counts successful transfers in **strictly lower** blocks;
   - witness = some admission is pending AND settled + amount ≤ B.

   Is this sound evidence of "denied while an earlier native transfer was unresolved"? Could same-block receipt ordering or delayed receipts make it misleading? Edge cases are in `tests/evidence/test_g2_replay.py::PendingWitnessLogic`.
3. **G2 concurrency claim scope** (`docs/G2_RESULT.md`, README, `web/src/pages.tsx:Burst`). Points to judge:
   - In both runs all eight burst transactions landed in one block. Requests to one vault execute sequentially by protocol.
   - Is "concurrent" accurately qualified as pre-signed and submitted in parallel, single shard, single validator?
   - Does the UI or README overstate anything? Check the wording of the six "witness" denials and "a settled-only check would have admitted".
4. **Vulnerable fixture and control audit** (`fixtures/vulnerable-settled-only/src/lib.rs`, `packages/verifier/control.py`). Points to check:
   - The fixture must be clearly labelled as project-owned, sandbox-only and not modelling any other project.
   - Does the outflow audit count delivered principal only from vault-predecessor Transfer receipt outcomes found by independent chunk discovery?
   - Gap to assess: the audit does not decode fixture state beyond a view. Is that acceptable for a control?
5. **Collector refactor** (`packages/collector/__init__.py`: `check_identity`, `walk_window`, `discover_roots`, `vault_capture`). It must be a pure refactor. Evidence: G1 replay tests pass, and the committed G1 bundle (including replay capture digests) is byte-identical. Confirm.
6. **UI honesty** (`#/burst`, `#/lab` "Spendable now", `#/verify` wording). Are the forged bundle and the 18 tamperings described as test-orchestrator inputs and not observed attacks? Is "Spendable now" correct when K is exhausted or the vault is frozen?
7. **CI** (`.github/workflows/ci.yml`). It is read-only, with no secrets. Will the `contract` job's cross-machine rebuild work as written? It installs cargo-near 0.22.0 with `--no-default-features`.

## Known limitations (do not re-report unless mis-stated)

- Local sandbox only; trusted-node observations.
- Runner/reviewer isolation is by namespaces on one host; one team wrote all code.
- Runs A and B of G1 predate the C1 fix (documented). Run C and both G2 runs use the fixed import path.
- Not executed: FAULT builds, forced callback failure on chain, K = 64, insufficient liquidity, expiry, multi-shard, testnet, and the LLM-driven scenario (no API key was available).
