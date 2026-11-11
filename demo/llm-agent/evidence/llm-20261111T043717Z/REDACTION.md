# Second redaction pass (release integration, 2026-11-11)

**What changed.** Before publication, the five model transcripts (`episodes/*/transcript.jsonl`) went through a second redaction pass. Every other file in this run is unchanged: each still matches its run-time hash in `SHA256SUMS.at-run`.

**Removed.** These identifiers link the run to the operator's Claude account and are not needed to check the run:

| Field | Where | Replaced by |
| --- | --- | --- |
| `session_id`, `uuid` | every event | removed |
| `request_id` | assistant events | removed |
| `message.id` | assistant events | removed |
| `rate_limit_info` (account usage) | `rate_limit_event` | `"<redacted>"` |
| tool-use IDs (`toolu_…`), as values and as keys | wherever they occur | `tool-ref-N`, numbered by first appearance in that transcript |

The tool-use IDs are replaced consistently and one-to-one, so every tool call still links to its tool result.

**Kept.** Everything else keeps the same value:
- model IDs, tool names and inputs;
- tool results;
- text;
- timestamps, token counts and cost.

The lines are re-serialized exactly as the run wrote them.

**How it was done.** With `../../redact_ids.py`:
- `python3 -I demo/llm-agent/redact_ids.py <run>` applies the pass.
- `--verify <original run>` structurally compares every event against the original. It allows no other difference.

**Checks after the pass.**
- `--verify` against the pre-redaction files: no problems.
- `evidence_check.py`: output byte-identical to before the pass (`"ok": true`). Its per-episode decisions equal the run-time `check.json`.
- `show_run.py`: output byte-identical to before the pass.
- `python3 -m unittest discover -s demo/llm-agent/tests`: OK.

**Manifests.**
- `SHA256SUMS.at-run` is the manifest written at the end of the run. It is kept unchanged, and its five transcript lines are the hashes of the pre-redaction transcripts.
- `SHA256SUMS` covers the files as published.
- The pre-redaction transcripts and the raw ones from before the first pass are kept privately by the operator. Anyone given them can re-run `--verify`.

| Transcript | Pre-redaction SHA-256 (run time) | Published SHA-256 |
| --- | --- | --- |
| `bec-1` | `540b730b…` | `0cd51a37…` |
| `bec-2` | `cade8aed…` | `c166fc3f…` |
| `inject-1` | `5470aa13…` | `f8f5058a…` |
| `inject-2` | `6a42f62c…` | `ef0f3d79…` |
| `legit-1` | `0b661ed5…` | `fbe5052f…` |
