# Submission kit (owner actions)

Nothing in this file has been sent, posted or published. The rules were checked against the live https://nearhackathon.com/HACKATHON.md on 2026-11-10:
- Deadline: **2026-11-14T23:59:00Z**.
- The repository must be public by then.
- The X post must say the project was built at NEAR HACKATHON, tag **@NEARProtocol** and **#NEARHackathon**, and attach a demo **video**. Screenshots alone are not enough when judges cannot open a demo.
- **One submission per project.** A submission cannot be edited afterwards.
- Code written since the announcement (2026-10-19) counts.
- Claude Code and Codex screen every entry for "runs and does what the README says".

## 1. Owner checklist, in order

1. Review the independent Codex review (`docs/CODEX_REVIEW_HANDOFF.md`) and fix anything blocking.
2. Confirm the license. The MIT `LICENSE` file is a proposal. Change the copyright line if needed.
3. Approve the push and set the repository to public (commands in `reports/RECOVERY_IMPLEMENTATION_RESULT_2026-11-10.md`, §Git).
4. Optional: enable GitHub Pages (Settings → Pages → Source: GitHub Actions), then run the `pages` workflow manually. This gives a hosted Attack Lab.
5. Record the demo video (§3) and publish the X post (§4) yourself.
6. Fill in the payload (§5) with your own details, read the consent text, then submit once.

## 2. Project description (`idea`, 20–2000 characters)

Draft, 1,163 characters:

> AI agents that pay for things need spending authority, but a wallet key gives them all of it. Pursewarden puts the limit on NEAR itself. An owner creates a keyless vault contract with an immutable mandate: total budget, per-payment cap, recipient allowlist, expiry and a maximum number of payments. The agent holds only NEAR function-call keys that can call request_payment with zero deposit. It cannot transfer, deploy or add keys. The vault charges every admitted payment against the budget before scheduling the transfer, in one receipt. A failed and refunded transfer stays charged, so authority cannot be recycled. An independent verifier rebuilds each run from the chain by scanning every block and chunk, decoding raw contract storage, recomputing the policy hash and reconciling receipts, refunds and events. When a runner hands over evidence that silently omits a payment, the verifier finds the missing transaction itself and fails the bundle. Two fresh local-sandbox runs pass this gate, and 18 tamperings of the recorded data are rejected. A read-only Attack Lab replays the evidence. Sandbox prototype only: not audited, no testnet or mainnet claims.

## 3. Tracks

- **`security`** (AI Security & Defense). The track brief reads: "spending limits, policy engines, sandboxed wallets … Give AI money without giving it the keys to everything". It names FUNCTION CALL KEYS as a hint. This is the primary fit.
- **`agents`** (Agent Economy). Optional. It fits as spending infrastructure for agents that pay for APIs, compute or data. It does not use NEAR Intents.

Recommendation: `["security", "agents"]`, or `["security"]` alone if you prefer a narrow framing.

## 4. Demo video (about 2 min) and recording instructions

Record from the local build (`cd web && npm ci && npm run build && npx vite preview --port 4173`) or the GitHub Pages URL. Use a 1440×900 window, dark theme, browser zoom at 100 %. Keep the REPLAY · SANDBOX chips in frame. Voice-over draft:

1. **(0:00–0:15) Overview.** "AI agents need to pay for things. Give one a wallet key and it can spend everything. Pursewarden gives it a NEAR vault with a fixed budget instead. The agent only holds a key that can *ask*."
2. **(0:15–0:40) Attack Lab: mandate and bar.** "Five NEAR budget, two per payment, two payments maximum. The vault has zero keys. One NEAR payment goes through. The second, two NEAR to an allowlisted account that doesn't exist, fails, and NEAR refunds it. The vault still counts it. Charged is three, headroom two. Refunds never restore authority."
3. **(0:40–1:05) Trace.** Click the `pay_2_missing_2near` row to show the receipt tree: the failed transfer, the system refund and the callback. "Then the agent turns hostile: a replay, a cap overrun, a payment to an attacker, an attempt to reuse the refund, malformed input, and four attempts to use its key for something else. Every one is stopped, either on chain with a recorded reason or by NEAR before inclusion."
4. **(1:05–1:40) Verifier.** "Now the operator lies. Their evidence bundle drops the failed payment and recomputes every checksum. Our verifier was never told that transaction exists. It scans every block and chunk on its own node, finds it, and fails the bundle." Scroll to the mutation table: "18 tamperings of the real data, 18 rejected."
5. **(1:40–2:00) Honesty and reproduce.** "This is a local sandbox prototype: not audited, no testnet or mainnet claims. Everything in this video replays committed raw data. Clone the repo and run one command to check it yourself." Show `python3 -m unittest discover -s tests/evidence -t .` → `Ran 50 tests … OK`.

Optional terminal cut (adds about 5 min, best sped up): `python3 scripts/g1-independent/run_g1.py demo-run --rpc-port 3240 --net-port 24777` live, showing `isolation PASS` and the independent verdicts.

## 5. X post draft (you publish it)

> Built at NEAR HACKATHON: Pursewarden 🛡️ Your AI agent can spend. It can't overspend.
>
> A keyless NEAR vault with a fixed, non-refillable budget. The agent only holds function-call keys. Failed payments still count. An independent verifier rebuilds every run from the chain and catches a bundle that hides a payment.
>
> Local sandbox prototype, not audited. Code + reproducible evidence: <REPO_URL>
>
> @NEARProtocol #NEARHackathon

Attach the demo video. Optional tags: @NearLegion, @NearBuilders.

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
  "nearAddress": "<your mainnet payout account, e.g. name.near>",
  "projectUrl": "https://github.com/mickeyjoes/near-agent-vault-lab",
  "demoUrl": "<https://x.com/…/status/… of your demo post>",
  "idea": "<§2 text>",
  "consent": true
}
```

- `consent: true` only after you have read and agreed to: "I agree that the organizers may use these details to review our submission and contact us about this hackathon."
- Do not add a `website` field. It is a spam trap.
- Brand clearance for "Pursewarden" is incomplete. If you are unsure, use the repository name as `projectName`.
