# Final publication handoff

**Verdict: READY for publication.** The repository is still **PRIVATE**. GitHub Pages is not enabled. Nothing has been published, posted or submitted.

## Repository

| | |
| --- | --- |
| URL | **https://github.com/mickeyjoes/pursewarden** (renamed from `mickeyjoes/near-agent-vault-lab` on 2026-11-10, while private) |
| Old URL | Redirects. Verified for git (`git ls-remote` on the old URL returns the identical 10 refs), the repo API, a CI run URL and file contents. |
| History | Preserved. The 10 refs (8 branches, 2 tags) were identical before and after the rename. No rewrite or force-push. |
| `master` | `release/testnet-proof` fast-forwarded to this commit; the final SHA is in the owner report |
| Local | `origin` = `https://github.com/mickeyjoes/pursewarden.git`, shared by all worktrees. All worktrees are clean. Local directory names are unchanged. |

**Deliberately unchanged** (renaming them would alter the protected artifact or recorded evidence):
- the WASM's embedded NEP-330 source link `https://github.com/mickeyjoes/near-agent-vault-lab` (redirects);
- the policy and request domain separators `near-agent-vault-lab/{mandate,request}/v1\0`;
- the event standard `near-agent-vault-lab`;
- the local tools path `~/.local/share/near-agent-vault-lab`;
- every file under `evidence/` and `reports/`;
- the legacy `license = "UNLICENSED"` fields in the frozen contract and fixture manifests (explained in the README License section).

## Verification (this release)

| Check | Result |
| --- | --- |
| GitHub CI, `3501c71` (run 42909497375, first run under the new name) | All 3 jobs success: evidence regressions, web bundle reproducibility and build, contract tests plus **cross-machine WASM rebuild = `c7c77263…`** |
| Earlier CI | `a87eee2`: runs 42894171563 and 42898838670, green |
| Evidence tests | 75 OK, including 5 public-testnet replay regressions |
| Web bundle | Byte-identical rebuild from committed raw RPC |
| UI | 72 route checks (domain root and `/pursewarden/` sub-path × desktop and mobile × dark and light): 0 horizontal overflow, 0 console errors, 0 CSP violations. Live testnet viewer: every enforcement field matches the recorded inspection. Tour keyboard navigation OK. |
| Links | 65 repo-relative links and paths resolve; 14 nearblocks links resolve via the explorer API |
| Secrets and privacy | Full history on all refs (926 blobs): 0 matches against 286 real secrets from local key files, and 0 credential patterns. Screenshots carry no metadata. The commit email and historical home paths in early evidence are known and accepted by the owner. |
| Artifact | `c7c772635acea0938bd88450d02bcdb9215d9aa65fc407b4070459cd225dd768` (unchanged) |

## Screenshots (`docs/media/`, real captures of the built site, 1440 px, 256-colour PNG)

| File | Shows | Size |
| --- | --- | --- |
| `g2-burst.png` | **README hero.** G2: 2 of 8 admitted vs 17 NEAR delivered by the settled-only fixture; block-by-block witness | 77 KB |
| `overview.png` | Landing hero, recorded-run card, headline results | 63 KB |
| `g1-verifier.png` | Forged bundle (payment hidden, evidence FAIL) vs the verifier's own capture (recovered, PASS) | 63 KB |
| `testnet-proof.png` | TESTNET identity, mandate, ledger, 10 public transactions | 122 KB |

## README changes

- A quick-link bar under the title: live demo, 3-step guided tour, testnet contract on nearblocks, and "Reproduce it yourself".
- The G2 screenshot as the hero, with full alt text and a caption.
- A screenshots gallery (Overview, G1 Verifier, Public Testnet Proof).
- All GitHub and Pages URLs now use `mickeyjoes/pursewarden`.
- The License section lists third-party licenses and explains the legacy manifest fields.
- The `reports/` row notes that the reports' old URLs redirect.
- Also fixed: the landing-page qualifier rendered its "public testnet" link as a separate column.

`docs/SUBMISSION.md` has:
- a refreshed owner checklist;
- a production-ready **2:00 storyboard** (G2 concurrency → G1 hidden-payment recovery → public testnet, with captions, voice-over and a do-not-say list);
- the real repository URL in the X draft;
- an idea text of 1,662 characters.

Payload placeholders (name, email, team size, mainnet payout account, demo post URL, request ID) are deliberately left for the owner.

## Recommended demo URL

**https://mickeyjoes.github.io/pursewarden/#/tour/1** (the guided tour). The testnet page is `#/testnet`. It goes live only after Pages is enabled and the `pages` workflow runs; until then the README's demo links return 404.

## Next owner steps (each needs your explicit go-ahead)

Do steps 1–3 in one sitting, so the README's demo links work as soon as the repository is public.

```bash
# 1. Publish the repository (all branches and tags become public)
gh repo edit mickeyjoes/pursewarden --visibility public --accept-visibility-change-consequences
# 2. Enable Pages with GitHub Actions as the source (or Settings → Pages → Source: GitHub Actions)
gh api -X POST repos/mickeyjoes/pursewarden/pages -f build_type=workflow
# 3. Deploy (manual workflow) and watch it
gh workflow run pages -R mickeyjoes/pursewarden --ref master
gh run watch "$(gh run list -R mickeyjoes/pursewarden --workflow pages --limit 1 --json databaseId -q '.[0].databaseId')" -R mickeyjoes/pursewarden --exit-status
#    then open https://mickeyjoes.github.io/pursewarden/#/tour/1 and #/testnet
```

4. Record the 2:00 video (`docs/SUBMISSION.md` §4). Post on X with @NEARProtocol and #NEARHackathon (§5).
5. Tag the final commit: `git tag -a hackathon-submission -m "NEAR HACKATHON 2026 submission" master && git push origin hackathon-submission`.
6. Submit once before **2026-11-14 23:59 UTC** (§6) with your own details and a **mainnet** payout account.

No DNS change is needed. `pursewarden.com` is unregistered; see `docs/DEPLOY.md` §B if you buy it.
