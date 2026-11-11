# Submission kit (owner actions)

Nothing in this file has been sent, posted or submitted. The repository is public and the Attack Lab is live at **https://pursewarden.com**. The rules were re-checked against the live https://nearhackathon.com/HACKATHON.md on 2026-11-10 (twice) and again on 2026-11-11 (unchanged):
- Deadline: **2026-11-14T23:59:00Z**. Judging starts 2026-11-16.
- The repository must be public by the deadline ("Judges cannot open a private one").
- The X post must say the project was built at NEAR HACKATHON, tag **@NEARProtocol** and **#NEARHackathon**, and attach a demo video or screenshots. Q-012 adds that screenshots are not enough when judges cannot open the demo; we have both a hosted demo and (once recorded) a video. Optional tags: @NearLegion, @NearBuilders. A good post leads with the user problem, shows one complete moment, says concretely what NEAR enables, links the demo and repository, and asks a genuine question.
- Keep the hosted demo up until at least 2026-11-18, ideally 2026-11-25 (Q-012). The repository stays public through judging (Q-014).
- **One submission per project**, at most 2 per email; `projectUrl` must be unique. A submission cannot be edited (changes go through https://nearhackathon.com/request-changes).
- The payout account must be a **mainnet** NEAR account.
- Code written since the announcement (2026-10-19) counts.
- Claude Code and Codex screen every entry: "they check that it runs and does what the README says". Humans decide.

## 1. Owner checklist, in order

1. ✅ License: MIT, "Copyright (c) 2026 The Pursewarden contributors" (confirmed). Edit the copyright line only if you want your name or organisation instead.
2. ✅ Repository public: `https://github.com/mickeyjoes/pursewarden` (renamed from `near-agent-vault-lab`; old links redirect).
3. ✅ Hosted demo live: **https://pursewarden.com** (GitHub Pages, HTTPS enforced; `www` and the old `mickeyjoes.github.io/pursewarden/` URL redirect to it). Verified on 2026-11-11; details in `docs/DEPLOY.md`.
4. ☐ Record the demo video (§4).
5. ☐ Publish the X post with the video (§5) yourself. Its URL becomes `demoUrl`.
6. ☐ Create the `hackathon-submission` tag on the final commit and push it (`docs/RELEASE_CHECKLIST.md`).
7. ☐ Fill in the payload (§6) with your own details and a **mainnet** payout account, read the consent notice, and submit once before 2026-11-14 23:59 UTC.

## 2. Project description (`idea`, 20–2000 characters)

Draft, 1,681 characters:

> AI agents that pay for things need spending authority, but a wallet key gives them all of it. Pursewarden puts the limit on NEAR itself. An owner creates a keyless vault contract with an immutable mandate: total budget, per-payment cap, recipient allowlist, expiry and a maximum number of payments. The agent holds only NEAR function-call keys that can call request_payment with zero deposit. It cannot transfer, deploy or add keys. The vault charges every admitted payment against the budget before scheduling the transfer, in one receipt. A failed and refunded transfer stays charged, so authority cannot be recycled. When eight payment requests hit a 5 NEAR budget at once, the vault admits exactly two. The other six are denied while the two admitted transfers are still in flight. A deliberately broken control that checks only settled spend overspends 17 NEAR against the same 5 NEAR budget. An independent verifier rebuilds each run from the chain by scanning every block and chunk, decoding raw contract storage, recomputing the policy hash and reconciling receipts, refunds and events. When an operator hands over evidence that silently omits a payment, the verifier finds the missing transaction itself and fails the bundle. These results come from fresh local-sandbox runs with committed raw RPC data that anyone can replay. The same contract also passed a 10-transaction smoke test on public NEAR testnet (pw-vault.pursewarden.testnet): keyless, one payment, one failed and refunded payment that stays charged, four denials and a freeze, each a public transaction. A read-only Attack Lab at pursewarden.com shows the evidence. Prototype: not audited, no mainnet claims.

## 3. Tracks

- **`security`** (AI Security & Defense). The track brief reads "spending limits, policy engines, sandboxed wallets … Give AI money without giving it the keys to everything", and its hints name FUNCTION CALL KEYS. This is the primary fit.
- **`agents`** (Agent Economy). A secondary fit: spending infrastructure for agents that pay for APIs, compute or data. It does not use NEAR Intents.

**Recommendation: `["security", "agents"]`.** Use `["security"]` alone if you prefer the narrowest framing.

## 4. Demo video (2:00), recorded on the live site

**Story.** One complete moment per beat, each from recorded or public chain data that the viewer can check:
1. a compromised agent fires eight concurrent payment requests;
2. the vault stops at 5 NEAR, while our deliberately broken teaching contract delivers 17;
3. the six denials were verified while the admitted native transfers were still pending;
4. the independent verifier catches a transaction the operator left out;
5. the same contract on public NEAR testnet, read live in the browser;
6. one-command reproducibility and the honest limits.

Every number below is on the screen at that moment. Say nothing the screen does not show. The framing was checked against production on 2026-11-11: at the setup below, each beat fits the screen with at most one short scroll.

### Capture setup

| Item | Setting |
| --- | --- |
| Source | **https://pursewarden.com** (production). Keep the address bar visible: it shows the demo is live. Fallback if the network is unreliable: a local preview of the same build (`cd web && npm ci && npm run build && npx vite preview --port 4173`). |
| Browser | Chrome or Chromium with a fresh profile (`--user-data-dir=$(mktemp -d)`): no extensions, bookmarks bar hidden (Ctrl+Shift+B), one tab. Dark theme. OS notifications off. |
| Framing | A 1920×1080 display (or a 1920×1080 window), browser maximised, page zoom **125 %**. The page is then 1536 CSS px wide, the framing this plan was checked at. Body text is large enough to read after X's compression. |
| Recorder | OBS Studio: canvas and output 1920×1080, **60 fps**, x264 CRF 16–18 (or NVENC CQ 18), MKV, then remux to MP4. Microphone on a separate track, 48 kHz. |
| Cursor | Keep it still unless you are pointing. Move slowly and pause on what you point at. |
| Warm-up | Open every route once before recording. Click **Read live from testnet** once to warm the connection, then reload the page so the button is fresh. |
| Terminal (beat 6) | A clean clone, a dark theme, a font of 20 pt or larger, and a prompt with no username, hostname or home path, e.g. `PS1='$ '`. |
| Takes | Record each beat as its own take and cut them together. Record the voice-over separately against the cut (quiet room, about 145 words per minute), or live if you prefer. |
| Captions | **Burn the lower-third captions in.** X autoplays muted. Use a plain sans font at 40–48 px with a semi-transparent dark band. |
| Export | MP4, H.264 High, 1920×1080, 30 or 60 fps, AAC 48 kHz at 160 kbps or more. Length about 2:00: X allows 2:20 on standard accounts, and the file must be under 512 MB. |

Since 2026-11-11 19:57 UTC the live viewer's **Expired** row reads `true` (marked *info*). That is expected: the vault is frozen and keyless either way. The enforcement rows still show "yes". Do not comment on it.

### Shot list

| Time | Screen and action | Lower-third caption | Voice-over (≈ 285 words, about 145 per minute) |
| --- | --- | --- | --- |
| 0:00–0:09 | `pursewarden.com` Overview hero, address bar visible. Cursor parked. | Pursewarden · built at NEAR HACKATHON | "Give an AI agent a wallet key and it can spend everything. Pursewarden gives it a NEAR vault with one fixed budget." |
| 0:09–0:21 | **Beat 1.** Click **Take the 3-step tour**. On step 1, point at the line "A compromised agent sends eight 2 NEAR requests in parallel…". | Compromised agent · 8 concurrent 2 NEAR requests · budget 5 NEAR | "Here's the attack. After one normal 1 NEAR payment, a compromised agent fires eight 2 NEAR payment requests at once, each signed with a different key, against a 5 NEAR budget." |
| 0:21–0:37 | **Beat 2.** Point at the **Pursewarden vault** bar (5 NEAR, "2 of 8 admitted · stops exactly at B"), then at the **Teaching fixture** bar (17 NEAR, red). | Pursewarden: 2 of 8 admitted, stops at 5 NEAR · our broken teaching contract: 17 NEAR delivered | "Our vault admits exactly two and stops at five. Same burst, same chain, against a deliberately broken contract we wrote ourselves, one that only counts settled payments: all eight go through. Seventeen NEAR out of a five NEAR budget." |
| 0:37–0:57 | **Beat 3.** Press **→** (step 2). Scroll down about 175 px (one or two wheel notches) so that block #74, block #75 and the green callout are all visible. Point at the six BudgetExceeded rows, then at the two transfers in block #75, then at "6 of 6 denials are verified witnesses". | 6 of 6 denials, verified while the admitted transfers were still pending | "Why? All six denials executed in block 74, before the two approved transfers landed in block 75. Only 1 NEAR had settled, so a balance check would have said yes. Pursewarden charges the budget at approval, so it said no. The verifier proves that order from the receipts." |
| 0:57–1:17 | **Beat 4.** Press **→** (step 3). Point at the struck-out row **#55 … hidden** under *evidence: FAIL*, then at **#55 … recovered** under *evidence: PASS*, then at the green callout. | Operator hides a failed 2 NEAR payment → the verifier recovers it → evidence FAIL | "Now distrust the operator. In this test the operator removes one real failed payment from its evidence and recomputes every checksum. The verifier is never told that transaction exists. It scans every block and chunk on its own node, recovers the payment and its refund, and fails the bundle." |
| 1:17–1:43 | **Beat 5.** Click **Testnet** in the nav. Hold on the TESTNET chip and contract identity (code SHA-256 = `c7c77263…`, 0 access keys, **Created by** exactly four actions) for 3 s. Scroll to **10 public transactions, 6 vault decisions** and hold for 4 s. Scroll to **Live state viewer**, click **Read live from testnet**, and hold until the LIVE · block chip and the "yes" column appear. | Public NEAR testnet · pw-vault.pursewarden.testnet · same bytes, 0 keys · read live | "And it isn't just a sandbox. The same contract, byte for byte, is deployed keyless on public NEAR testnet. Ten public transactions, including a payment, a failed payment that stays charged, then a replay, a cap overrun, a payee off the allowlist and an over-budget request: all four refused. Click, and your browser reads the vault live and hashes its code. It still matches." |
| 1:43–1:55 | **Beat 6a.** Terminal in a clean clone: `python3 -m unittest discover -s tests/evidence -t .` and hold on `Ran 87 tests … OK`. Then cut to Overview → scroll to **What we claim, what we assume, what we don't** and hold. | Replays committed chain data · 87 tests OK · claims ledger on the site | "Every result replays from committed chain data with one command. The limits are on the page: sandbox attack tests, a narrow testnet smoke test, no audit, no mainnet." |
| 1:55–2:00 | **Beat 6b.** End card: `pursewarden.com` · `github.com/mickeyjoes/pursewarden` · "Experimental · not audited · built at NEAR HACKATHON". | — | "Pursewarden. Your agent can spend. It can't overspend." |

**Do not say:**
- that the testnet run proves concurrency or completeness (the sandbox results do that);
- that the fixture is anyone else's code, or name another project;
- that the forged bundle was an observed attack (it is a test of the verifier);
- anything about mainnet, audits, production custody or prompt-injection defence.

Optional B-roll (sped up, only if time allows): `python3 scripts/g2-independent/run_g2.py demo` (a fresh chain in about 25 s), or the Attack Lab trace with a receipt tree open.

**Automation, assessed.** The repository's Playwright tooling captures the site well as stills, and it produced the framing checks for this plan. It is not good enough for the final video. Playwright's built-in recorder writes 25 fps VP8 at a fixed low bitrate, there is no natural voice, and scripted pointer movement looks robotic. A human-driven OBS capture at the settings above, with a recorded voice-over, will be clearly better. Use automation only to rehearse timing.

**Suggested title:** "Pursewarden: your AI agent can spend. It can't overspend. (NEAR HACKATHON, 2 min)"

**Suggested description** (for YouTube or another host, if you upload there as well):

> Pursewarden gives an AI agent a keyless NEAR vault with one fixed, non-refillable budget. In this 2-minute demo: eight concurrent payment requests against a 5 NEAR budget (exactly 2 admitted, while a deliberately broken settled-only contract of our own delivers 17); six denials verified while the admitted transfers were still pending; an independent verifier that catches a payment the operator left out of its evidence; and the same contract on public NEAR testnet, read live in the browser.
>
> Live demo: https://pursewarden.com · Code and reproducible evidence: https://github.com/mickeyjoes/pursewarden
>
> Experimental hackathon prototype, built at NEAR HACKATHON. The adversarial results come from a local NEAR sandbox; the testnet run is a narrow smoke test. Not audited. No mainnet.

## 5. X post drafts (you publish them)

**Version A: a standard account (280 characters).** Main post, 278 characters by X's count (each URL counts 23). Attach the video.

> AI agents that pay need a budget, not a wallet key.
>
> Pursewarden: a keyless NEAR vault with a fixed budget. 8 requests at once vs 5 NEAR: exactly 2 admitted. A deliberately broken control paid out 17.
>
> Built at NEAR HACKATHON @NEARProtocol #NEARHackathon
> https://pursewarden.com

Reply in the same thread (264 characters):

> An independent verifier rebuilds every run from the chain and catches a hidden payment. Same contract on public NEAR testnet, readable live. Sandbox evidence, not audited:
> https://github.com/mickeyjoes/pursewarden
>
> What spending rule would you want enforced on-chain for your agent?

**Version B: one long post** (needs an account that allows posts longer than 280 characters):

> AI agents that pay for things need spending authority, but a wallet key gives them all of it. Built at NEAR HACKATHON: Pursewarden. Your AI agent can spend. It can't overspend.
>
> 🔑 Keyless NEAR vault, fixed budget; the agent holds only function-call keys
> ⚡ 8 payment requests at once against a 5 NEAR budget → exactly 2 admitted; our own deliberately broken control pays out 17
> 🔎 An independent verifier rebuilds every run from the chain and catches a report that hides a payment
> 🌐 The same contract on NEAR testnet, readable live: https://pursewarden.com/#/testnet
>
> Live demo: https://pursewarden.com
> Code and reproducible evidence: https://github.com/mickeyjoes/pursewarden
> Sandbox evidence plus a testnet smoke test. Not audited.
>
> What spending rule would you want enforced on-chain before you give an agent money?
>
> @NEARProtocol #NEARHackathon

Optional tags: @NearLegion @NearBuilders. Post the video natively: attach it to the post rather than linking to it.

## 6. Submission payload template (do not send until confirmed)

Every `<…>` value is yours to supply; they are deliberately left as placeholders. Nothing is pre-filled with personal data. Generate `requestId` once (`uuidgen | tr A-Z a-z`) and reuse it on retries. Do not commit the filled payload.

```json
{
  "requestId": "<uuid, generated once>",
  "projectName": "Pursewarden",
  "leadName": "<your name>",
  "email": "<your contact email>",
  "size": "<1 | 2 - 4 | 4 - 6 | 6 - 8 | 8+>",
  "tracks": ["security", "agents"],
  "nearAddress": "<your MAINNET payout account, e.g. name.near>",
  "projectUrl": "https://github.com/mickeyjoes/pursewarden",
  "demoUrl": "<https://x.com/…/status/… of your demo post>",
  "idea": "<§2 text>",
  "consent": true
}
```

- `consent: true` only after you have read and agreed to: "I agree that the organizers may use these details to review our submission and contact us about this hackathon."
- Do not add a `website` field. It is a spam trap.
- Brand clearance for "Pursewarden" is incomplete. If you are unsure, use the repository name as `projectName`.
