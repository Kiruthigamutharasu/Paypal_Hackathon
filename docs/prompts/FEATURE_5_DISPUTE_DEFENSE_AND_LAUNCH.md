# Claude Code prompt — Feature 5: Dispute Defense Agent & Launch

You are a senior AI agent engineer and release lead on **StayCovered**. F1–F4 are complete. This is Feature 5 of 5: dispute handling, then final integration and launch for the PayPal AI Hackathon.

## Before you write any code
1. Read `CLAUDE.md`, `docs/PRD.md` (sections 1, 5 steps 9–10, 7 entirely, 8.3 DIS/EVD flags, 9, 10, 11, 12, 13-F5, 14–17) and `docs/STATUS.md`.
2. Verify against official PayPal docs (AI Toolkit/MCP if available): dispute details fields (reason, `dispute_life_cycle_stage`, status, `seller_response_due_date`, requested evidences, HATEOAS action links); `provide-evidence` multipart format and evidence types (`PROOF_OF_FULFILLMENT` with `evidence_info.tracking_info`, `OTHER`); file limits (jpg/jpeg/gif/png/pdf, < 10 MB each, ≤ 50 MB per call); sandbox-only dispute creation (`POST /v1/customer/disputes`) and settlement (`POST /v1/customer/disputes/{id}/adjudicate`); dispute webhook event names. Record results in `docs/VERIFICATION.md`.
3. Reply in plan mode with understanding, agent design, tools, state machine, demo plan, open questions. **Wait for approval.**

## Part A — Dispute Defense

### 1. Dispute sync (`services/paypal/disputes.py`, `workflows/disputes.py`)
- Handle stored `CUSTOMER.DISPUTE.CREATED/UPDATED/RESOLVED` events from F1's webhook pipeline: always re-fetch `GET /v1/customer/disputes/{id}`; upsert `disputes` (reason, stage, status, amount, due date, allowed actions from links, requested evidence, raw); link to the order via the disputed transaction/capture ID; audit.
- Manual "Sync disputes" (`GET /v1/customer/disputes`) for missed events.
- Multiple disputes per order supported; each has its own state.
- Deadline checker (on request + background loop or cron-like task): DIS-10 (< 48 h) and DIS-11 (passed).

### 2. Dispute Defense Agent (`ai/agents/dispute_defense.py`)
- Bounded tool loop (max 6 calls) via the provider abstraction's `run_tool_loop`. Read-only tools: `get_order`, `get_capture`, `get_shipments`, `get_decision_history`, `get_conversation_extraction`, `list_evidence_files`. No write tools; no PayPal write access.
- Output `EvidencePlan` (PRD §7.4): supported flag, evidence items with type, tracking info, file references, rationale, missing items, deadline.
- Reason-specific rules enforced in code after the agent returns:
  - `MERCHANDISE_OR_SERVICE_NOT_RECEIVED` → `PROOF_OF_FULFILLMENT` with registered tracking (carrier + number); attach label photo; include decision history showing the shipment went to the protected address.
  - `UNAUTHORISED` → tracking + transaction/shipping evidence.
  - Any other reason → `supported_in_mvp=false`; show a guided manual checklist; disable automatic submission.
  - If the sandbox scenario's test-data condition requires `OTHER`, allow selecting `OTHER` explicitly.
- Evidence Writer: factual note (≤ 1,000 chars) generated from the plan's facts only.
- **Claim verifier** (deterministic): extract tracking numbers, dates, amounts, addresses and order IDs mentioned in the note; each must match stored facts; otherwise EVD-08 blocks submission and highlights the sentence.

### 3. Evidence pack builder
- `evidence_packs` (versioned), `evidence_files` (references to original uploads or generated PDFs). Generate a one-page PDF summary (order, protected address, label extraction, tracking, timeline) with a simple PDF library.
- Validate types/sizes (convert images to JPEG/PNG under 10 MB; total ≤ 50 MB); compute SHA-256.
- New evidence or a new requested-evidence request → new pack version (DIS-12, EVD-12).

### 4. Submission (`POST /api/disputes/{id}/submit`)
- Preconditions: pack READY, claim check passed, deadline not passed, `provide-evidence` action present in the latest synced links, seller confirmation token from the modal. `AUTO_SUBMIT_EVIDENCE` is ignored in the MVP (always manual confirmation).
- Multipart request: `input` JSON part with `evidences[]` (+ `notes`) and file parts. Stable request ID per pack version; store `evidence_submissions` with HTTP status, debug ID and response; on network timeout, re-fetch the dispute before any retry (API-12).
- On success: pack SUBMITTED; dispute status refreshed; audit. On PayPal error: show message + debug ID; keep draft (EVD-14, DIS-20).

### 5. Sandbox demo controls (sandbox only)
- `POST /api/sandbox/disputes` creates a test dispute for an order (reason INR) via the sandbox endpoint; fallback documented: open a dispute as the sandbox buyer on the sandbox site.
- `POST /api/sandbox/disputes/{id}/settle` calls the sandbox adjudicate endpoint when status is `UNDER_REVIEW`.
- These routes return 404 unless `PAYPAL_ENVIRONMENT=sandbox`; UI shows them in a clearly labelled "Sandbox demo tools" box.

### 6. UI
- Disputes list (reason, amount, stage, status, deadline countdown, linked order).
- Dispute detail: PayPal details, requested evidence, agent plan with rationale, files (thumbnails), note with claim-check results (verified sentences ticked), "Submit to PayPal" confirmation modal, submission history, outcome.
- Dashboard: dispute state column and deadline chips.

## Part B — Launch

### 7. End-to-end integration
- Playwright (or scripted API) E2E: shop payment (mock or real sandbox with a flag) → uploads → RED → re-pay → GREEN → tracking → sandbox dispute → plan → submit.
- Fix integration issues; keep each feature's tests passing.

### 8. Demo readiness
- `backend/scripts/seed_demo.py`: creates demo fixtures (chat screenshot with "ship to my friend in Austin", matching/mismatching labels) and helper instructions; never stores secrets.
- `docs/DEMO_SCRIPT.md` following PRD §15 (timings, clicks, what to say).
- Visual polish: consistent spacing, empty states, loading states, error states, accessible labels.

### 9. README (judges must succeed in ≤ 5 minutes)
- First lines: hosted demo URL, YouTube video link, one-sentence pitch.
- What it does (5 features), architecture diagram (Mermaid), "AI extracts, rules decide, you approve".
- **Try it:** hosted URL; sandbox buyer email/password (sandbox only) for the demo shop; the 90-second click path.
- Local run in ≤ 5 commands; required sandbox setup (US Business/Personal, Disputes enabled, webhook URL); env vars (point to `.env.example`, unchanged).
- Table of PayPal APIs used; AI models used and how; known limitations (US policy only, single-seller demo, sandbox only, PayPal decides outcomes); MIT license.

### 10. Deploy & verify
- Render deploy with all env vars; webhook registered to the Render URL; run the demo script on the hosted build; fix issues; update `docs/STATUS.md` to "release candidate".

## Testing requirements
- Unit: reason → evidence mapping, claim verifier (true/false cases), file validation/conversion, deadline logic, submission preconditions, idempotency.
- Integration (mock PayPal): dispute created → synced → plan → submit; duplicate/late webhooks; action not available → submit disabled; PayPal error → draft preserved; timeout → re-fetch before retry.
- Manual sandbox: create INR dispute for a shipped order → submit PROOF_OF_FULFILLMENT → see status update → settle (sandbox).

## Acceptance criteria
- AC5.1 INR dispute on a shipped order → plan with PROOF_OF_FULFILLMENT and the registered tracking.
- AC5.2 Note passes the claim verifier; an injected unsupported claim blocks submission (EVD-08).
- AC5.3 Submission only after confirmation, only when the action is available, once per pack version.
- AC5.4 Invalid files are converted or rejected before submission.
- AC5.5 Duplicate dispute webhooks create no duplicates; late webhooks trigger re-fetch.
- AC5.6 The demo script runs end to end on the hosted URL; README lets a new user run the demo in ≤ 5 minutes.

## Deliverables
Code, migrations, tests passing (unit, integration, E2E), README, `docs/DEMO_SCRIPT.md`, `docs/STATUS.md` (release candidate), `docs/VERIFICATION.md`, deployed hosted URL.
