# Final publication handoff

**Status (2026-11-11): PUBLIC and LIVE.** The repository is public at **https://github.com/mickeyjoes/pursewarden**. The Attack Lab is live at **https://pursewarden.com**. Nothing has been posted on X or submitted, and the `hackathon-submission` tag does not exist yet.

## Production website (verified 2026-11-11)

| Check | Result |
| --- | --- |
| Routes | Overview, 3-step tour, Attack Lab, Burst (G2), Verifier, Testnet, Reproduce: 9 routes × desktop (1280×900) and mobile (390×844) × dark and light = **36 route views**. 0 console errors or warnings, 0 CSP violations, 0 failed requests or HTTP errors, 0 horizontal overflow, 0 images without alt text. |
| Navigation and keyboard | The first Tab reaches "Skip to content", and every focusable element shows a visible focus ring. Enter on a nav link navigates. The tour responds to → → ← Esc (`/tour/2`, `/tour/3`, `/tour/2`, `/`). The theme toggle switches and persists across a reload. |
| Provenance labels | `#/testnet` shows REPLAY · TESTNET and never SANDBOX. The tour and `#/burst` show SANDBOX. |
| Live testnet viewer | "Read live from testnet" through the production CSP: code SHA-256, 0 access keys, policy hash, C = 0.80, headroom 0.20, 2 admitted, sequence 9 and frozen all equal the recorded inspection. It queried `rpc.testnet.near.org` only. |
| HTTPS | Let's Encrypt certificate for `pursewarden.com` and `www.pursewarden.com`, valid to 2027-02-09. HTTPS enforced; `http://` returns 301 to `https://`. |
| `www` | `https://www.pursewarden.com/…` and `http://www…` return 301 to `https://pursewarden.com/…`, path kept. |
| Old URL | `https://mickeyjoes.github.io/pursewarden/` returns 301 to `https://pursewarden.com/`. |
| DNS | Apex: four GitHub Pages `A` records; `www`: `CNAME` to `mickeyjoes.github.io.`. Served directly by GitHub. IPv6 `AAAA` records are optional and not set. |
| Assets | All 15 deployed files (HTML, JS, CSS, 11 fonts, `bundle.json`) are byte-identical to a local build of `ae69b91`, with correct content types. |
| Outbound links | All 12 GitHub links on the site return 200 now that the repository is public. The four testnet accounts exist on chain, and the live viewer confirms the vault's code matches the artifact. A nearblocks API lookup of the freeze transaction returns 200; all 14 explorer links were checked on 2026-11-10. |

## Changes in this round

- **Domain first.** The README, `docs/SUBMISSION.md`, `docs/DEPLOY.md` and `docs/RELEASE_CHECKLIST.md` now point at https://pursewarden.com. Source links still point at https://github.com/mickeyjoes/pursewarden. The stale "domain not registered" and "Pages not enabled" text is gone. `docs/DEPLOY.md` now records the verified production configuration.
- **Link previews.** `web/index.html` has `canonical`, `og:url`, `og:site_name`, `og:image` (with type, size and alt) and Twitter `summary_large_image` metadata, all with absolute `https://pursewarden.com/` URLs. The `<title>` before hydration is now descriptive.
- **Preview image** `web/public/og.png` (1200×630, 67 KB, 256-colour PNG, no metadata). It is an unedited capture of the production tour step 1: 5 NEAR vs 17 NEAR, with the REPLAY · SANDBOX label visible. It deploys at `https://pursewarden.com/og.png`.
- **Video plan.** `docs/SUBMISSION.md` §4 has a 2:00 shot list on the live site covering all six required beats, with capture settings, exact narration, burned-in captions, a title and a description. The X drafts in §5 come as a 278-character version plus a reply, and a long version.
- **Workflow comment.** The `pages` workflow header now describes its triggers accurately: manual dispatch, or a push to `master` that changes the workflow file.

## Unchanged on purpose

- The contract, the protected artifact `c7c772635acea0938bd88450d02bcdb9215d9aa65fc407b4070459cd225dd768` and its embedded NEP-330 link (`…/near-agent-vault-lab`, which redirects).
- The domain separators `near-agent-vault-lab/{mandate,request}/v1\0` and the event standard.
- All G1, G2 and testnet evidence under `evidence/`, the review reports under `reports/`, and the deployed testnet accounts.
- The legacy `license = "UNLICENSED"` fields in the frozen contract and fixture manifests (explained in the README License section).

## Repository rename (2026-11-10, recorded)

Renamed `mickeyjoes/near-agent-vault-lab` → `mickeyjoes/pursewarden` while private. The 10 refs (8 branches, 2 tags) were identical before and after the rename, and old git, API, CI-run and file URLs redirect. The CI cross-machine rebuild under the new name still produced `c7c77263…`.

## Owner steps remaining (each needs your go-ahead)

0. Publish the release candidate.
   - **What it is.** Local branch `release/final-rc2` merges:
     - `fix/final-audit-findings` (`9f894db`);
     - the PW-01b disclosure;
     - `demo/llm-agent`: Agent B's `f54a227`, plus `5f481be`. `5f481be` is Agent B's `d9c9f94` with the transcripts' account identifiers redacted before publication (`demo/llm-agent/evidence/llm-20261111T043717Z/REDACTION.md`).
   - **Steps.**
     1. Push the branch.
     2. Wait for green CI.
     3. Fast-forward `master` to it.
     4. Check the live site's hashes (`docs/DEPLOY.md`), because the push to `master` redeploys Pages.
   - **Then the video.** Record it only after the deploy, because beat 5 shows the updated live viewer. The sequence and the reasons are in the release handoff.
1. Record the 2-minute video on https://pursewarden.com (`docs/SUBMISSION.md` §4).
2. Post it on X (`docs/SUBMISSION.md` §5). The post URL becomes `demoUrl`.
3. Tag the final commit: `git tag -a hackathon-submission -m "NEAR HACKATHON 2026 submission" master && git push origin hackathon-submission`.
4. Submit once before **2026-11-14 23:59 UTC** (`docs/SUBMISSION.md` §6), with your own details and a **mainnet** payout account.
5. Keep the site up until at least 2026-11-18, ideally 2026-11-25.

Optional:
- Upload `web/public/og.png` as the repository's social preview (Settings → General → Social preview), so that shared GitHub links show the same image. GitHub has no API for this.
- Add the IPv6 `AAAA` records listed in `docs/DEPLOY.md`.
