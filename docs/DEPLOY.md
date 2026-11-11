# Hosting the Attack Lab (GitHub Pages, https://pursewarden.com)

The site is a static, read-only build of `web/`. It has no backend, wallet or keys. All recorded data comes from `web/public/bundle.json`, which `scripts/build_web_bundle.py` regenerates by replaying the committed raw RPC captures through the verifier. The `pages` workflow re-checks that before it builds.

The build uses relative asset paths and hash routes (`#/tour/1`, `#/lab`, `#/burst`, `#/verify`, `#/testnet`, `#/docs`), so the same artifact works at a domain root and under a sub-path. There are no 404 rewrites to configure.

Security note: GitHub Pages cannot set response headers. `web/index.html` therefore declares a Content-Security-Policy meta tag:
- same-origin scripts, fonts and data only;
- one exception for `connect-src`: `https://rpc.testnet.near.org` and `https://test.rpc.fastnear.com`. The Testnet page's live state viewer uses them, only when the visitor clicks "Read live from testnet". It sends read-only JSON-RPC queries (`block`, `view_account`, `view_access_key_list`, `get_mandate`) without credentials or a referrer;
- no inline scripts, no forms, no `base` changes;
- `Referrer-Policy: no-referrer`.

No CSP violations were observed on any route, including the live viewer. Production check of `https://pursewarden.com` (headless Chrome, 2026-11-11): 36 route views (9 routes × desktop and mobile × dark and light), with 0 console errors, 0 CSP violations, 0 failed requests and 0 horizontal overflow. Earlier pre-release check (2026-11-10): 72 route checks at a domain root and a sub-path.

## Production: https://pursewarden.com

Live since 2026-11-11. Configuration as verified on 2026-11-11:

| Item | Value |
| --- | --- |
| Pages source | GitHub Actions (`build_type: workflow`), workflow `pages` |
| Custom domain | `pursewarden.com`, verified on the GitHub account (`protected_domain_state: verified`) |
| Certificate | Let's Encrypt, `pursewarden.com` and `www.pursewarden.com`, issued by GitHub, valid to 2027-02-09 (GitHub renews it) |
| HTTPS | Enforced. `http://` returns 301 to `https://pursewarden.com/` |
| DNS | Apex: four `A` records to GitHub Pages (`185.199.108.153`, `.109.153`, `.110.153`, `.111.153`). `www`: `CNAME` to `mickeyjoes.github.io.` Not proxied: responses come straight from GitHub (`server: GitHub.com`). |
| Redirects | `https://www.pursewarden.com/…` and `http://www…` return 301 to `https://pursewarden.com/…` (path kept). `https://mickeyjoes.github.io/pursewarden/` returns 301 to `https://pursewarden.com/`. |
| Deployed bytes | Every file served (HTML, JS, CSS, fonts, `bundle.json`) is byte-identical to a local `npm run build` of the deployed commit. |

Optional, owner DNS decision: GitHub also publishes IPv6 addresses for the apex (`AAAA` `2606:50c0:8000::153`, `8001::153`, `8002::153`, `8003::153`). None are set now, and IPv4 works for everyone.

With GitHub Actions deployments a `CNAME` file in the artifact is not needed; the repository's Pages setting holds the domain. If the domain is ever removed, the same build works at `https://mickeyjoes.github.io/pursewarden/` without a rebuild (relative asset paths, hash routes).

### Redeploy

The `pages` workflow runs on manual dispatch, and on a push to `master` that changes `.github/workflows/pages.yml`. It refuses to build unless `web/public/bundle.json` regenerates byte-identically from the committed raw RPC.

```bash
gh workflow run pages -R mickeyjoes/pursewarden --ref master
gh run watch -R mickeyjoes/pursewarden --exit-status "$(gh run list -R mickeyjoes/pursewarden --workflow pages --limit 1 --json databaseId --jq '.[0].databaseId')"
```

Then open `https://pursewarden.com/#/tour/1` (provenance bar: REPLAY · SANDBOX) and `https://pursewarden.com/#/testnet` (TESTNET; "Read live from testnet" should report that every enforcement field matches). GitHub Pages caches HTML for up to 10 minutes (`cache-control: max-age=600`).

Keep the site online until at least 2026-11-18, ideally 2026-11-25 (hackathon FAQ Q-012).

### Link previews

`web/index.html` declares `canonical`, `og:*` and Twitter Card (`summary_large_image`) metadata with absolute `https://pursewarden.com/` URLs. The preview image `web/public/og.png` is deployed at `https://pursewarden.com/og.png`. It is an unedited capture of the production page `#/tour/1`: viewport 1200×630 at 2× in dark mode, downscaled to 1200×630 with Lanczos, saved as a 256-colour PNG with no metadata. Its provenance bar (REPLAY · SANDBOX) stays visible. Re-capture it only if that page changes. Social networks cache previews per URL, so after a change post a URL they have not seen yet, or use the network's own refresh tool.

## Local preview (identical artifact)

```bash
cd web && npm ci && npm run build && npx vite preview --port 4173   # http://127.0.0.1:4173/#/tour/1
```
