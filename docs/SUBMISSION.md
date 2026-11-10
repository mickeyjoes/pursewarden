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
2. Confirm the license. The MIT `LICENSE` file is a proposal ("The near-agent-vault-lab contributors"). Edit the copyright line if you want your name or organisation.
3. Approve pushing `feat/g2-concurrency` and fast-forwarding `master` (commands in the readiness report). Then make the repository public.
4. Hosted demo (recommended): Settings → Pages → Source: **GitHub Actions**, then Actions → `pages` → Run workflow. The URL will be `https://mickeyjoes.github.io/near-agent-vault-lab/`. Keep it up until at least 2026-11-18, ideally 2026-11-25. The custom domain `pursewarden.com` is unregistered; see `docs/DEPLOY.md`.
5. Record the demo video (§4) and publish the X post (§5) yourself.
6. Create the `hackathon-submission` tag on the final commit, push it, then fill in the payload (§6) and submit once.

## 2. Project description (`idea`, 20–2000 characters)

Draft, 1,445 characters:

> AI agents that pay for things need spending authority, but a wallet key gives them all of it. Pursewarden puts the limit on NEAR itself. An owner creates a keyless vault contract with an immutable mandate: total budget, per-payment cap, recipient allowlist, expiry and a maximum number of payments. The agent holds only NEAR function-call keys that can call request_payment with zero deposit. It cannot transfer, deploy or add keys. The vault charges every admitted payment against the budget before scheduling the transfer, in one receipt. A failed and refunded transfer stays charged, so authority cannot be recycled. When eight payment requests hit a 5 NEAR budget at once, the vault admits exactly two. The other six are denied while the two admitted transfers are still in flight. A deliberately broken control that checks only settled spend overspends 17 NEAR against the same 5 NEAR budget. An independent verifier rebuilds each run from the chain by scanning every block and chunk, decoding raw contract storage, recomputing the policy hash and reconciling receipts, refunds and events. When an operator hands over evidence that silently omits a payment, the verifier finds the missing transaction itself and fails the bundle. Every result comes from fresh local-sandbox runs with committed raw RPC data that anyone can replay. A read-only Attack Lab shows the evidence. Sandbox prototype only: not audited, no testnet or mainnet claims.

## 3. Tracks

- **`security`** (AI Security & Defense). The track brief reads "spending limits, policy engines, sandboxed wallets … Give AI money without giving it the keys to everything", and its hints name FUNCTION CALL KEYS. This is the primary fit.
- **`agents`** (Agent Economy). A secondary fit: spending infrastructure for agents that pay for APIs, compute or data. It does not use NEAR Intents.

**Recommendation: `["security", "agents"]`.** Use `["security"]` alone if you prefer the narrowest framing.

## 4. Demo video (2:00) and recording instructions

Record from the hosted site (`https://mickeyjoes.github.io/near-agent-vault-lab/`) or a local preview (`cd web && npm ci && npm run build && npx vite preview --port 4173`). Use a 1440×900 window, dark theme and 100 % zoom. Keep the REPLAY · SANDBOX chips visible. The guided tour is the spine of the video: use the → key to advance.

| Time | Screen | Voice-over |
| --- | --- | --- |
| 0:00–0:12 | Overview hero and proof strip | "AI agents need to pay for things. Give one a wallet key and it can spend everything. Pursewarden gives it a NEAR vault with a fixed budget. The agent's only key can *ask*, and the vault has no keys at all." |
| 0:12–0:45 | Tour step 1: the 5 vs 17 NEAR bars | "A compromised agent fires eight 2 NEAR payment requests at once, from eight different keys, against a 5 NEAR budget. Our vault admits exactly two and stops at 5. A deliberately broken contract we wrote as a control counts only completed payments. It lets all eight through: 17 NEAR out of a 5 NEAR budget." |
| 0:45–1:15 | Tour step 2: block #74 → #75 | "Here's why. All six denials happened in this block, while the two approved transfers hadn't even landed yet; they landed in the next block. Only 1 NEAR had actually settled. A balance-based check says yes. Pursewarden charges the budget the moment it approves, so it says no. The verifier proves this from receipts, and it refuses to count cases it can't order." |
| 1:15–1:45 | Tour step 3: hidden vs recovered lists | "Don't trust the operator's report either. In this test, the operator hands over evidence with one failed payment removed and every checksum recomputed. The verifier was never told that transaction existed. It scans every block on its own node, finds it, and fails the bundle." |
| 1:45–2:00 | Reproduce page, then a terminal: `python3 -m unittest discover -s tests/evidence -t .` → `Ran 70 tests … OK` | "All of this is local-sandbox evidence that you can replay from committed raw chain data, with one command. Experimental, not audited. Built at NEAR HACKATHON." |

Optional B-roll, sped up: `python3 scripts/g2-independent/run_g2.py demo` (a fresh chain in about 25 s), or the Attack Lab trace with a receipt tree open.

## 5. X post draft (you publish it)

> Built at NEAR HACKATHON: Pursewarden. Your AI agent can spend. It can't overspend.
>
> 🔑 Keyless NEAR vault, fixed budget, agent holds only function-call keys
> ⚡ 8 payment requests at once against a 5 NEAR budget → exactly 2 admitted; a settled-only design overspends by 12
> 🔎 An independent verifier rebuilds every run from the chain and catches a report that hides a payment
>
> Local sandbox prototype, not audited. Reproducible evidence: <REPO_URL>
>
> @NEARProtocol #NEARHackathon

Attach the 2-minute video. Optional: @NearLegion @NearBuilders, and the Pages URL.

## 6. Submission payload template (do not send until confirmed)

Every `<…>` value is yours to supply. Nothing is pre-filled with personal data. Generate `requestId` once (`uuidgen | tr A-Z a-z`) and reuse it on retries. Do not commit the filled payload.

```json
{
  "requestId": "<uuid, generated once>",
  "projectName": "Pursewarden",
  "leadName": "<your name>",
  "email": "<your contact email>",
  "size": "<1 | 2 - 4 | 4 - 6 | 6 - 8 | 8+>",
  "tracks": ["security", "agents"],
  "nearAddress": "<your MAINNET payout account, e.g. name.near>",
  "projectUrl": "https://github.com/mickeyjoes/near-agent-vault-lab",
  "demoUrl": "<https://x.com/…/status/… of your demo post>",
  "idea": "<§2 text>",
  "consent": true
}
```

- `consent: true` only after you have read and agreed to: "I agree that the organizers may use these details to review our submission and contact us about this hackathon."
- Do not add a `website` field. It is a spam trap.
- Brand clearance for "Pursewarden" is incomplete. If you are unsure, use the repository name as `projectName`.
