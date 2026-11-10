# Submission kit (owner actions)

Nothing in this file has been sent, posted or published. The rules were re-checked against the live https://nearhackathon.com/HACKATHON.md on 2026-11-10 (twice):
- Deadline: **2026-11-14T23:59:00Z**. Judging starts 2026-11-16.
- The repository must be public by the deadline ("Judges cannot open a private one").
- The X post must say the project was built at NEAR HACKATHON, tag **@NEARProtocol** and **#NEARHackathon**, and attach a demo video or screenshots. Q-012 adds that screenshots are not enough when judges cannot open the demo, so attach a **video** or host the Attack Lab. Optional tags: @NearLegion, @NearBuilders.
- **One submission per project**, at most 2 per email; `projectUrl` must be unique. A submission cannot be edited (changes go through https://nearhackathon.com/request-changes).
- The payout account must be a **mainnet** NEAR account.
- Code written since the announcement (2026-10-19) counts.
- Claude Code and Codex screen every entry: "they check that it runs and does what the README says". Humans decide.

## 1. Owner checklist, in order

1. Follow `docs/RELEASE_CHECKLIST.md`. Engineering items are verified; the owner items remain.
2. License: MIT, "Copyright (c) 2026 The Pursewarden contributors" (confirmed). Edit the copyright line only if you want your name or organisation instead.
3. Make the repository public: `https://github.com/mickeyjoes/pursewarden`. It was renamed from `near-agent-vault-lab`, and old links redirect.
4. Hosted demo, in the same sitting: Settings → Pages → Source: **GitHub Actions**, then Actions → `pages` → Run workflow. The URL will be `https://mickeyjoes.github.io/pursewarden/`, which the README already links. Keep it up until at least 2026-11-18, ideally 2026-11-25. The custom domain `pursewarden.com` is unregistered; see `docs/DEPLOY.md`.
5. Record the demo video (§4) and publish the X post (§5) yourself.
6. Create the `hackathon-submission` tag on the final commit, push it, then fill in the payload (§6) and submit once.

## 2. Project description (`idea`, 20–2000 characters)

Draft, 1,662 characters:

> AI agents that pay for things need spending authority, but a wallet key gives them all of it. Pursewarden puts the limit on NEAR itself. An owner creates a keyless vault contract with an immutable mandate: total budget, per-payment cap, recipient allowlist, expiry and a maximum number of payments. The agent holds only NEAR function-call keys that can call request_payment with zero deposit. It cannot transfer, deploy or add keys. The vault charges every admitted payment against the budget before scheduling the transfer, in one receipt. A failed and refunded transfer stays charged, so authority cannot be recycled. When eight payment requests hit a 5 NEAR budget at once, the vault admits exactly two. The other six are denied while the two admitted transfers are still in flight. A deliberately broken control that checks only settled spend overspends 17 NEAR against the same 5 NEAR budget. An independent verifier rebuilds each run from the chain by scanning every block and chunk, decoding raw contract storage, recomputing the policy hash and reconciling receipts, refunds and events. When an operator hands over evidence that silently omits a payment, the verifier finds the missing transaction itself and fails the bundle. These results come from fresh local-sandbox runs with committed raw RPC data that anyone can replay. The same contract also passed a 10-transaction smoke test on public NEAR testnet (pw-vault.pursewarden.testnet): keyless, one payment, one failed and refunded payment that stays charged, four denials and a freeze, each a public transaction. A read-only Attack Lab shows the evidence. Prototype: not audited, no mainnet claims.

## 3. Tracks

- **`security`** (AI Security & Defense). The track brief reads "spending limits, policy engines, sandboxed wallets … Give AI money without giving it the keys to everything", and its hints name FUNCTION CALL KEYS. This is the primary fit.
- **`agents`** (Agent Economy). A secondary fit: spending infrastructure for agents that pay for APIs, compute or data. It does not use NEAR Intents.

**Recommendation: `["security", "agents"]`.** Use `["security"]` alone if you prefer the narrowest framing.

## 4. Demo video (2:00): storyboard

**Story.** Three proofs, each shown from recorded data and then checkable by the viewer:
1. the budget holds under concurrency (G2);
2. a hidden payment cannot be hidden from the verifier (G1);
3. the same contract runs on public NEAR testnet.

Every number below is from the committed evidence; say nothing that the screen does not show.

**Setup.**
- Record the hosted site (`https://mickeyjoes.github.io/pursewarden/`) or a local preview (`cd web && npm ci && npm run build && npx vite preview --port 4173`).
- Use a 1440×900 browser window at 100 % zoom, dark theme, and export at 1080p.
- Use a clean browser profile: no bookmarks bar, extensions, other tabs, notifications or personal accounts in view.
- Keep the provenance bar visible. It reads REPLAY · SANDBOX on the tour and TESTNET on the testnet page.
- Advance the tour with the → key. Before recording, click "Read live from testnet" once to warm the connection.
- Keep the cursor still unless you are pointing at something.

| Time | Screen and action | On-screen caption (lower third) | Voice-over (about 300 words in total) |
| --- | --- | --- | --- |
| 0:00–0:10 | Overview hero. Slow push toward "Your agent can spend. It can't overspend." | Pursewarden · built at NEAR HACKATHON | "Give an AI agent a wallet key and it can spend everything. Pursewarden gives it a NEAR vault with one fixed budget. The agent's only key can ask; the vault itself has no keys." |
| 0:10–0:22 | Click **Take the 3-step tour**. Tour step 1 opens. | G2 · 8 requests × 2 NEAR · budget 5 NEAR | "Here's the attack. After one normal 1 NEAR payment, a compromised agent fires eight 2 NEAR requests at once, each from a different key, against a 5 NEAR budget." |
| 0:22–0:42 | Step 1: point at the protected bar (5), then the fixture bar (17, +12). | Protected: 2 of 8 admitted, C = 5 = B · Settled-only fixture: 17 NEAR delivered | "Our vault admits exactly two and stops at five. For contrast, a deliberately broken contract we wrote ourselves, which only counts payments that have already settled, lets all eight through: 17 NEAR out of a 5 NEAR budget." |
| 0:42–1:02 | → Step 2. Point at block #74 (six denials), then #75 (two transfers). | 6 of 6 denials while transfers were still in flight | "Why? All six denials executed in block 74. The two approved transfers hadn't landed yet; they ran in block 75. Only 1 NEAR had settled, so a balance check would say yes. Pursewarden charges the budget at approval, so it says no. The verifier proves this from the receipts, and refuses to count any case it can't order." |
| 1:02–1:27 | → Step 3. Point at the struck-out row #55 on the left, then the recovered row on the right, then the callout. | G1 · operator hides a failed 2 NEAR payment → evidence FAIL | "Now don't trust the operator either. In this test the operator hands over evidence with one failed payment removed and every checksum recomputed. The verifier was never told that transaction existed. It scans every block and chunk on its own node, recovers the payment and its refund, and fails the bundle. Eighteen other tamperings are rejected too." |
| 1:27–1:47 | Nav → **Testnet**. Scroll to the transaction table. Click **Read live from testnet**; the LIVE chip and the "yes" column appear. | Public NEAR testnet · pw-vault.pursewarden.testnet · 0 keys | "And it's not just a sandbox. The same contract, byte for byte, is live on public NEAR testnet with no keys. A payment, a failed payment that stays charged, then a replay, a cap overrun, an outsider and an over-budget request are all refused: each one a public transaction. This reads its state live, and it still matches." |
| 1:47–2:00 | Terminal: `python3 -m unittest discover -s tests/evidence -t .` → `Ran 75 tests … OK`. End card: repository URL and demo URL. | github.com/mickeyjoes/pursewarden · experimental, not audited | "Every result replays from committed chain data with one command. Pursewarden: an agent that can spend, but can't overspend. Experimental and not audited. Built at NEAR HACKATHON." |

**Do not say:**
- that the testnet run proves concurrency or completeness (the sandbox results do that);
- that the fixture is anyone else's code;
- that the forged bundle was an observed attack (it is a test of the verifier);
- anything about mainnet, audits or production custody.

Optional B-roll, sped up: `python3 scripts/g2-independent/run_g2.py demo` (a fresh chain in about 25 s), or the Attack Lab trace with a receipt tree open.

## 5. X post draft (you publish it)

> Built at NEAR HACKATHON: Pursewarden. Your AI agent can spend. It can't overspend.
>
> 🔑 Keyless NEAR vault, fixed budget, agent holds only function-call keys
> ⚡ 8 payment requests at once against a 5 NEAR budget → exactly 2 admitted; a settled-only design overspends by 12
> 🔎 An independent verifier rebuilds every run from the chain and catches a report that hides a payment
> 🌐 Also on NEAR testnet: https://testnet.nearblocks.io/address/pw-vault.pursewarden.testnet
>
> Sandbox evidence plus a testnet smoke test, not audited. Reproducible evidence: https://github.com/mickeyjoes/pursewarden
>
> @NEARProtocol #NEARHackathon

Attach the 2-minute video. Optional: @NearLegion @NearBuilders, and the demo URL `https://mickeyjoes.github.io/pursewarden/`.

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
