# Release checklist (deadline 2026-11-14 23:59 UTC)

Items marked ✅ are done and verified. Items marked ☐ are owner actions that have not been done yet. Final state: `docs/FINAL_PUBLICATION_HANDOFF.md`.

## Engineering

- ✅ CI green on every pushed release commit, including the **cross-machine WASM rebuild = `c7c77263…`**: `d2dc2d2`, `7b69c0a`, `a87eee2` (runs 42894171563 and 42898838670). The current commit's run is in the handoff.
- ✅ 87 evidence tests pass locally (including 17 on the public-testnet inspection, 12 of them creation-batch regressions). 12 contract tests pass. The real-LLM demo's offline check and 10 unit tests pass (in CI), and its 7 gateway tests pass (by hand). The web bundle regenerates byte-identically from committed raw RPC.
- ✅ Independent reviews addressed: C1 (runner symlink import) fixed in `71a679c`; W1 (witness same-block ambiguity) fixed in `71dfc47`. Both review reports are committed under `reports/`.
- ☐ Final independent review (2026-11-11) and its delta review.
  - **PW-01.** The testnet inspector did not check the creation batch. Fixed for that attack.
  - **PW-01b.** A same-name re-creation variant was confirmed by the delta review. It is disclosed, not fixed.
  - **PW-02 to PW-09.** Addressed. See `docs/FINAL_AUDIT_RESPONSE.md`.
  - **Release candidate.** Integrated with the real-LLM demo (`demo/llm-agent/`, optional appendix) on branch `release/final-rc2` (demo transcripts redacted of account identifiers).
  - **To publish.** Push it, wait for green CI, then fast-forward `master`. That push redeploys Pages; then confirm that the live `bundle.json` and JS hashes equal a clean build.
- ✅ Testnet smoke plan rehearsed on a local protocol-88 sandbox (testnet's nearcore): PASS.
- ✅ **Public testnet smoke executed with owner approval: PASS** (`tn-20261110T195542Z`, `pw-vault.pursewarden.testnet`). Explorer links are in the README. Owner spend 3.2925 testnet NEAR (cap 3.5).
- ✅ Testnet page (`#/testnet`) with recorded proof and a click-to-read live viewer; the live read matches the recorded inspection.
- ✅ Secret scan: every blob reachable from every ref checked against all real keys on disk, with no matches. The commit email and historical home-path strings are known and were accepted by the owner.
- ✅ UI: all routes on desktop and mobile, dark and light; tour keyboard navigation; CSP with no violations; root and sub-path hosting; no console errors.
- ✅ `release/testnet-proof` pushed and `master` fast-forwarded after green CI (owner-approved).
- ✅ Repository renamed `mickeyjoes/near-agent-vault-lab` → **`mickeyjoes/pursewarden`** while private. All branches and tags were preserved and old URLs redirect. Public-facing links were updated. The WASM's embedded source link still names the old URL (it is part of the protected artifact) and redirects.
- ✅ Screenshots in `docs/media/` (Overview, G2 Burst, G1 Verifier, Public Testnet Proof) with alt text; the README leads with the G2 image and quick links.

## Publication (owner)

1. ✅ **Repository public** (owner, 2026-11-11): `https://github.com/mickeyjoes/pursewarden`.
2. ✅ **Hosted demo live at https://pursewarden.com** (owner, 2026-11-11): Pages via GitHub Actions, custom domain verified, HTTPS enforced. `www`, `http://` and the old `mickeyjoes.github.io/pursewarden/` URL redirect to it.
3. ✅ **Post-launch production check** (2026-11-11): 36 route views (desktop and mobile × dark and light), with 0 console errors, 0 CSP violations, 0 failed requests and 0 overflow. Keyboard navigation works, the theme toggle persists, and the live testnet viewer matches the recorded inspection. Every deployed file is byte-identical to a local build. Link-preview metadata and `og.png` were added; see `docs/DEPLOY.md`.
4. ✅ **Testnet smoke**: done with owner approval (see Engineering).
5. ☐ **Record the 2-minute video** on the live site (`docs/SUBMISSION.md` §4).
6. ☐ **Post on X** with the video. It must say "built at NEAR HACKATHON" and tag @NEARProtocol and #NEARHackathon (`docs/SUBMISSION.md` §5).
7. ☐ **Tag the final commit:** `git tag -a hackathon-submission -m "NEAR HACKATHON 2026 submission" master && git push origin hackathon-submission`.
8. ☐ **Submit once** (`docs/SUBMISSION.md` §6) with your name, email, team size and **mainnet** payout account, after reading the consent notice.
9. ☐ Keep `pursewarden.com` up until at least 2026-11-18, ideally 2026-11-25, and keep the repository public through judging.

## Do not

- Force-push, rewrite history, or delete evidence.
- Present the testnet smoke as a completeness, concurrency or adversarial-runner result, or claim mainnet, audit or production custody.
- Describe the vulnerable fixture as another project's code, or the forged bundle and tamperings as observed attacks.
