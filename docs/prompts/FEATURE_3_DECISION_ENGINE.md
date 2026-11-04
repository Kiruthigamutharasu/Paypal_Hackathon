# Claude Code prompt — Feature 3: Shipment Decision Engine & Explainable Risk Report

You are a senior backend engineer and product-minded AI agent developer on **StayCovered**. F1 and F2 are complete. This is Feature 3 of 5.

## Before you write any code
1. Read `CLAUDE.md`, `docs/PRD.md` (sections 2.2, 8 entirely, 10, 11, 12, 13-F3) and `docs/STATUS.md`.
2. Inspect existing models, extraction outputs and UI. Reuse patterns. Do not modify `.env.example`.
3. Reply in plan mode with your understanding, module design, migration, the full flag→verdict table you'll implement, open questions. **Wait for approval.**

## Objective
Build a deterministic, explainable decision engine that turns PayPal data (F1) and AI extractions (F2) into a versioned verdict — **GREEN, YELLOW, RED, GREY** — with coded flags, plain-language reasons, source references and recommended actions. Add the seller acknowledgement/override flow and the Explainable Risk Report UI. **No LLM is used in this feature.**

## Implementation tasks

### 1. Address normalization & comparison (`backend/app/rules/address.py`)
- Normalization per PRD §8.2 (uppercase, punctuation, USPS-style abbreviations, state names → codes, ZIP5).
- Field comparison and overall result: `MATCH`, `FORMAT_ONLY_DIFFERENCE`, `FUZZY`, `MISMATCH`, `INSUFFICIENT_DATA`. Use `rapidfuzz` token-sort ratio for `line1` (≥ 0.90 match, 0.75–0.90 fuzzy).
- Non-US country → `INSUFFICIENT_DATA` (documented limitation).
- Persist to `address_comparisons` with field-level results.

### 2. Policy module (`backend/app/rules/policy.py`)
- Seller Protection status from the stored capture (`ELIGIBLE`, `PARTIALLY_ELIGIBLE`, `NOT_ELIGIBLE`, `UNKNOWN`) → flags SP-01/SP-02 (INFO + banner text).
- Signature rule keyed by country and transaction date: for US transactions with total ≥ `SIGNATURE_THRESHOLD_USD`: processed before 2026-01-26 → YELLOW "signature confirmation required"; on/after 2026-01-26 → INFO "signature confirmation recommended". Keep the cutoff date as a constant with a comment to VERIFY on PayPal's US Seller Protection page; note it in `docs/VERIFICATION.md`.
- `RULES_VERSION = "1.0.0"`.

### 3. Flag registry (`backend/app/rules/flags.py`)
- Implement every flag in PRD §8.3 as a declarative registry entry: code, name, category, severity, verdict effect, detected_by (AI/Rule/System), blocks_shipping, requires_review, seller_message, recommended_action.
- Evaluators are pure functions taking an `EvaluationContext` (payment state, capture, protected address, latest label extraction, chat extractions, comparison) and returning zero or more flags with `source_ref`.
- Key rules: ADD-03 only when request type ADDRESS_CHANGE, status EXPLICIT, speaker BUYER, not cancelled; seller-initiated suggestions → YELLOW ADD-03A; AI-15 discards unsourced candidates; AI-20 uses `AI_CONFIDENCE_THRESHOLD`.

### 4. Decision engine (`backend/app/rules/engine.py`, `workflows/verification.py`)
- Precedence RED > GREY > YELLOW > GREEN; INFO flags never change the verdict.
- GREEN requires: payment COMPLETED, protected address present, label extraction readable, comparison `MATCH` or `FORMAT_ONLY_DIFFERENCE`, no blocking/review flags.
- Compute `input_hash` (capture status, protected address version, latest label extraction ID, chat extraction IDs, rules version). If an ACTIVE decision with the same hash exists, return it; otherwise mark previous ACTIVE as SUPERSEDED and insert a new immutable decision with flags and an `explanation` object (checks passed/failed, address diff, quotes, recommended action).
- Trigger evaluation automatically after F2 extractions complete and after any payment-state change (hook into F1 reconciliation). Expose `POST /api/orders/{id}/evaluate` and `GET /api/orders/{id}/decision`.
- Update `orders.verification_state` accordingly.

### 5. Acknowledge / override (`POST /api/orders/{id}/decision/acknowledge`)
- YELLOW: seller ticks each review item → status `ACKNOWLEDGED`.
- RED: requires typed reason (≥ 15 chars) and explicit checkbox "I understand Seller Protection is likely void" → status `OVERRIDDEN`; audit with reason.
- GREY: cannot be acknowledged.
- Any new input invalidates acknowledgements (new decision).

### 6. Explainable Risk Report UI
- Verdict banner with label text (not colour alone): "Checks passed — not a guarantee of Seller Protection" / "Manual review needed" / "Shipment blocked" / "Cannot evaluate yet".
- Checklist: Payment verified · Protected address present · Seller Protection status (from PayPal) · Chat checked · Label readable · Address match · Signature advisory.
- Field-by-field address diff (PayPal vs label) with highlights.
- Flags list: code, message, quote with link to source thumbnail, recommended action.
- Actions: Acknowledge (YELLOW), Override (RED, modal), "Fix this" button (enabled for ADD-03/ADD-12; implemented in F4 — show disabled with tooltip for now).
- Dashboard grid: verdict badge column wired to the active decision.

## Testing requirements
- Table-driven unit tests covering every flag and verdict combination in PRD §8.3 (at least 40 cases), including: explicit change + matching label → RED; ambiguous → YELLOW; cancelled request → no ADD-03; seller suggestion → YELLOW; missing label → GREY; low confidence → YELLOW; ZIP mismatch → RED; format-only difference → GREEN; payment PENDING → GREY; REFUNDED → RED; signature advisory INFO vs YELLOW by date.
- Decision versioning tests: same inputs → same decision; new label → supersede; payment change → re-evaluate.
- Property test for normalization idempotency.
- Manual test using F2 fixtures end to end.

## Acceptance criteria
- AC3.1 All flag tests pass.
- AC3.2 "Ship to my friend" + matching label → RED with ADD-03 and recommended action.
- AC3.3 Clean case → GREEN with explicit "not a guarantee" text.
- AC3.4 New label supersedes the previous ACTIVE decision and re-evaluates.
- AC3.5 Missing label → GREY; low confidence → YELLOW.
- AC3.6 RED override requires a reason and is audited.
- AC3.7 Signature advisory behaves by transaction date as specified.

## Deliverables
Code, migration, tests passing, risk report UI, `docs/STATUS.md` and `docs/VERIFICATION.md` updated, manual test script.
