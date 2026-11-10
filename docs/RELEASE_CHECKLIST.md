# Release checklist (deadline 2026-11-14 23:59 UTC)

Items marked ✅ are verified by the agent. Items marked ☐ are owner actions. None of the ☐ items has been done.

## Engineering

- ✅ CI green at `d2dc2d2` (run 42850602121 and the branch run): evidence tests, web reproducibility and build, contract tests, **cross-machine WASM rebuild = `c7c77263…`**.
- ✅ 70 evidence tests pass locally. 12 contract tests pass. The web bundle regenerates byte-identically from committed raw RPC.
- ✅ Independent reviews addressed: C1 (runner symlink import) fixed in `71a679c`; W1 (witness same-block ambiguity) fixed in `71dfc47`. Both review reports are committed under `reports/`.
- ✅ Testnet smoke plan rehearsed on a local protocol-88 sandbox (testnet's nearcore): PASS. Not broadcast.
- ✅ Secret scan: every blob reachable from every ref checked against all real keys on disk, with no matches. The commit email and historical home-path strings are known and were accepted by the owner.
- ✅ UI: all routes on desktop and mobile, dark and light; tour keyboard navigation; CSP with no violations; root and sub-path hosting; no console errors.
- ☐ Push the release branch, then fast-forward `master` after CI is green on it.

## Publication (owner)

1. ☐ **Make the repository public:** `gh repo edit mickeyjoes/near-agent-vault-lab --visibility public --accept-visibility-change-consequences`.
2. ☐ **Enable Pages:** Settings → Pages → Source: GitHub Actions. Then `gh workflow run pages -R mickeyjoes/near-agent-vault-lab --ref master` and check `https://mickeyjoes.github.io/near-agent-vault-lab/#/tour/1`. The custom domain `pursewarden.com` is not registered; see `docs/DEPLOY.md` §B if you buy it.
3. ☐ Optional: **testnet smoke.** Approve and run `docs/TESTNET_SMOKE_PLAN.md` with your funded testnet account (about 3.5 testnet NEAR). Add the explorer links to the README.
4. ☐ **Record the 2-minute video** (`docs/SUBMISSION.md` §4) from the hosted site or a local preview.
5. ☐ **Post on X** with the video. It must say "built at NEAR HACKATHON" and tag @NEARProtocol and #NEARHackathon (`docs/SUBMISSION.md` §5).
6. ☐ **Tag the final commit:** `git tag -a hackathon-submission -m "NEAR HACKATHON 2026 submission" master && git push origin hackathon-submission`.
7. ☐ **Submit once** (`docs/SUBMISSION.md` §6) with your name, email, team size and **mainnet** payout account, after reading the consent notice.

## Do not

- Force-push, rewrite history, or delete evidence.
- Claim testnet results before the smoke is actually run, or claim mainnet, audit or production custody.
- Describe the vulnerable fixture as another project's code, or the forged bundle and tamperings as observed attacks.
