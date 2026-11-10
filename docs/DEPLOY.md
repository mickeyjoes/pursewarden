# Hosting the Attack Lab (GitHub Pages)

The site is a static, read-only build of `web/`. It has no backend, wallet or keys. All recorded data comes from `web/public/bundle.json`, which `scripts/build_web_bundle.py` regenerates by replaying the committed raw RPC captures through the verifier. The `pages` workflow re-checks that before it builds.

The build uses relative asset paths and hash routes (`#/tour/1`, `#/lab`, `#/burst`, `#/verify`, `#/testnet`, `#/docs`), so the same artifact works at a domain root and under a sub-path. There are no 404 rewrites to configure.

Security note: GitHub Pages cannot set response headers. `web/index.html` therefore declares a Content-Security-Policy meta tag:
- same-origin scripts, fonts and data only;
- one exception for `connect-src`: `https://rpc.testnet.near.org` and `https://test.rpc.fastnear.com`. The Testnet page's live state viewer uses them, only when the visitor clicks "Read live from testnet". It sends read-only JSON-RPC queries (`block`, `view_account`, `view_access_key_list`, `get_mandate`) without credentials or a referrer;
- no inline scripts, no forms, no `base` changes;
- `Referrer-Policy: no-referrer`.

No CSP violations were observed on any route, including the live viewer (headless Chrome, 2026-11-10: 72 route checks at a root and a sub-path, desktop and mobile, dark and light).

## Option A: default URL (no domain needed)

Requires the repository to be **public**, because Pages on private repositories needs a paid plan.

1. GitHub → repository → Settings → Pages → Build and deployment → Source: **GitHub Actions**. Or: `gh api -X POST repos/mickeyjoes/pursewarden/pages -f build_type=workflow`.
2. Actions → `pages` → **Run workflow** on `master`. Or from a terminal:

   ```bash
   gh workflow run pages -R mickeyjoes/pursewarden --ref master
   gh run watch -R mickeyjoes/pursewarden "$(gh run list -R mickeyjoes/pursewarden --workflow pages --limit 1 --json databaseId --jq '.[0].databaseId')"
   ```

3. Open `https://mickeyjoes.github.io/pursewarden/`. Check that the tour loads (`#/tour/1`) with REPLAY · SANDBOX in the provenance bar, and that `#/testnet` shows TESTNET and its "Read live from testnet" button returns matching values.

Keep it online until at least 2026-11-18, ideally 2026-11-25 (hackathon FAQ Q-012).

## Option B: custom domain `pursewarden.com` (owner decision)

**Status on 2026-11-10: `pursewarden.com` is not registered.** DNS returns NXDOMAIN and the Verisign RDAP lookup returns 404. The brand is also provisional, because trademark clearance is incomplete. Registering the domain is an owner purchase. Nothing here registers or changes DNS.

If you register it:

1. **Verify the domain for your GitHub account first.** Profile Settings → Pages → Add a domain, then publish the TXT record GitHub shows. This prevents someone else's Pages site from claiming it.
2. DNS at your registrar:

   | Type | Host | Value |
   | --- | --- | --- |
   | A | `@` | `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153` |
   | AAAA | `@` | `2606:50c0:8000::153`, `2606:50c0:8001::153`, `2606:50c0:8002::153`, `2606:50c0:8003::153` |
   | CNAME | `www` | `mickeyjoes.github.io.` |

3. Set the custom domain on the repository (Settings → Pages → Custom domain), or:

   ```bash
   gh api -X PUT repos/mickeyjoes/pursewarden/pages -f cname=pursewarden.com
   ```

   With GitHub Actions deployments a `CNAME` file in the artifact is ignored and not needed. The repository setting is what counts.
4. After the certificate is issued, tick **Enforce HTTPS**. Then re-run the `pages` workflow and check `https://pursewarden.com/#/tour/1`.
5. If you use the domain, set `og:url`/`og:image` in `web/index.html` to absolute `https://pursewarden.com/…` URLs. They are omitted now on purpose, because they need a final origin.

## Local preview (identical artifact)

```bash
cd web && npm ci && npm run build && npx vite preview --port 4173   # http://127.0.0.1:4173/#/tour/1
```
