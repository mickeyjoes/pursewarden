# Release checklist (deadline 2026-11-14 23:59 UTC)

Items marked ✅ are done and verified. Items marked ☐ are owner actions that have not been done yet. Final state: `docs/FINAL_PUBLICATION_HANDOFF.md`.

## Engineering

- ✅ CI green on every pushed release commit, including the **cross-machine WASM rebuild = `c7c77263…`**: `d2dc2d2`, `7b69c0a`, `a87eee2` (runs 42894171563 and 42898838670). The current commit's run is in the handoff.
- ✅ 75 evidence tests pass locally (including 5 replays of the public-testnet inspection). 12 contract tests pass. The web bundle regenerates byte-identically from committed raw RPC.
- ✅ Independent reviews addressed: C1 (runner symlink import) fixed in `71a679c`; W1 (witness same-block ambiguity) fixed in `71dfc47`. Both review reports are committed under `reports/`.
- ✅ Testnet smoke plan rehearsed on a local protocol-88 sandbox (testnet's nearcore): PASS.
- ✅ **Public testnet smoke executed with owner approval: PASS** (`tn-20261110T195542Z`, `pw-vault.pursewarden.testnet`). Explorer links are in the README. Owner spend 3.2925 testnet NEAR (cap 3.5).
- ✅ Testnet page (`#/testnet`) with recorded proof and a click-to-read live viewer; the live read matches the recorded inspection.
- ✅ Secret scan: every blob reachable from every ref checked against all real keys on disk, with no matches. The commit email and historical home-path strings are known and were accepted by the owner.
- ✅ UI: all routes on desktop and mobile, dark and light; tour keyboard navigation; CSP with no violations; root and sub-path hosting; no console errors.
- ✅ `release/testnet-proof` pushed and `master` fast-forwarded after green CI (owner-approved).
- ✅ Repository renamed `mickeyjoes/near-agent-vault-lab` → **`mickeyjoes/pursewarden`** while private. All branches and tags were preserved and old URLs redirect. Public-facing links were updated. The WASM's embedded source link still names the old URL (it is part of the protected artifact) and redirects.
- ✅ Screenshots in `docs/media/` (Overview, G2 Burst, G1 Verifier, Public Testnet Proof) with alt text; the README leads with the G2 image and quick links.

## Publication (owner)

1. ☐ **Make the repository public:** `gh repo edit mickeyjoes/pursewarden --visibility public --accept-visibility-change-consequences`.
2. ☐ **Enable Pages:** Settings → Pages → Source: GitHub Actions (or `gh api -X POST repos/mickeyjoes/pursewarden/pages -f build_type=workflow`). Then `gh workflow run pages -R mickeyjoes/pursewarden --ref master` and check `https://mickeyjoes.github.io/pursewarden/#/tour/1`. The custom domain `pursewarden.com` is not registered; see `docs/DEPLOY.md` §B if you buy it.
3. ✅ **Testnet smoke**: done with owner approval (see Engineering).
4. ☐ **Record the 2-minute video** (`docs/SUBMISSION.md` §4) from the hosted site or a local preview.
5. ☐ **Post on X** with the video. It must say "built at NEAR HACKATHON" and tag @NEARProtocol and #NEARHackathon (`docs/SUBMISSION.md` §5).
6. ☐ **Tag the final commit:** `git tag -a hackathon-submission -m "NEAR HACKATHON 2026 submission" master && git push origin hackathon-submission`.
7. ☐ **Submit once** (`docs/SUBMISSION.md` §6) with your name, email, team size and **mainnet** payout account, after reading the consent notice.

## Do not

- Force-push, rewrite history, or delete evidence.
- Present the testnet smoke as a completeness, concurrency or adversarial-runner result, or claim mainnet, audit or production custody.
- Describe the vulnerable fixture as another project's code, or the forged bundle and tamperings as observed attacks.
