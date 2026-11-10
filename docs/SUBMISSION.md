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

1. Read `reports/FINAL_RELEASE_READINESS_2026-11-10.md` (research folder), and optionally run the focused review in `docs/CODEX_POSTFIX_REVIEW_HANDOFF.md`.
2. Confirm the license. The MIT `LICENSE` file is a proposal ("The near-agent-vault-lab contributors"). Edit the copyright line if you want your name or organisation.
3. Approve pushing `feat/g2-concurrency` and fast-forwarding `master` (commands in the readiness report). Then make the repository public.
4. Hosted demo (recommended): Settings → Pages → Source: **GitHub Actions**, then Actions → `pages` → Run workflow. The URL will be `https://mickeyjoes.github.io/near-agent-vault-lab/`. Keep it up until at least 2026-11-18, ideally 2026-11-25.
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

Record from the hosted Pages URL or the local build (`cd web && npm ci && npm run build && npx vite preview --port 4173`). Use a 1440×900 window, dark theme and 100 % zoom. Keep the REPLAY · SANDBOX chips in frame and leave the cursor still while narrating.

| Time | Screen | Voice-over |
| --- | --- | --- |
| 0:00–0:12 | Overview hero | "AI agents need to pay for things. Give one a wallet key and it can spend everything. Pursewarden gives it a NEAR vault with a fixed budget. The agent only holds a key that can *ask*." |
| 0:12–0:35 | Attack Lab: mandate, authority bar, "Spendable now" | "Five NEAR budget, two per payment. The vault has zero keys. A 1 NEAR payment goes through. A 2 NEAR payment to an account that doesn't exist fails, and NEAR refunds it, but the vault still counts it. Charged is three. Refunds never restore authority." |
| 0:35–0:55 | Trace rows, then open `pay_2_missing_2near` | "Then the agent turns hostile: a replay, a cap overrun, a payment to an attacker, reuse of the refund, malformed input, and four attempts to use its key for something else. All are stopped, on chain with a recorded reason, or by NEAR before inclusion." |
| 0:55–1:30 | Burst (G2): three cards, then block #74 → #75, then the witness callout | "Now eight 2 NEAR requests at once, from eight different keys. The vault admits exactly two and denies six, all in the same block, while the two admitted transfers haven't even executed yet. Our deliberately broken control counts only settled spend. Under the same burst it lets all eight through: 17 NEAR out of a 5 NEAR budget." |
| 1:30–1:50 | Verifier: forged vs independent lists, recovered callout, mutation table | "Don't trust the operator's report. In this test the orchestrator plays a dishonest operator: its bundle hides the failed payment and recomputes every checksum. The verifier was never told that transaction exists. It scans every block, finds it, and fails the bundle. Eighteen test tamperings of real data, all rejected." |
| 1:50–2:00 | Reproduce page, then a terminal: `python3 -m unittest discover -s tests/evidence -t .` → `Ran 70 tests … OK` | "Local sandbox prototype, not audited. Every number here replays committed raw chain data. Clone it and check." |

Optional B-roll (speed it up 4×): `python3 scripts/g2-independent/run_g2.py demo --rpc-port 3290 --net-port 24827` shows a fresh chain, isolation PASS and the three results in about 25 s.

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
