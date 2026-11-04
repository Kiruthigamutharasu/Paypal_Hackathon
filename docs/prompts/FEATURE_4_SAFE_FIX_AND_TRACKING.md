# Claude Code prompt — Feature 4: Safe Fix, Shipment & PayPal Tracking

You are a senior engineer and AI agent developer on **StayCovered**. F1–F3 are complete. This is Feature 4 of 5.

## Before you write any code
1. Read `CLAUDE.md`, `docs/PRD.md` (sections 5 steps 6–8, 7.1 Remediation Assistant, 9, 10, 11, 13-F4, 17) and `docs/STATUS.md`.
2. Inspect existing services (PayPal client, reconciliation, decision engine). Reuse them. Do not modify `.env.example`.
3. Verify against official PayPal docs (AI Toolkit/MCP if available): refund capture request/response; create order with `shipping_preference: SET_PROVIDED_ADDRESS` and a preset shipping address; Add Tracking body (`capture_id`, `tracking_number`, `carrier`, the field used with carrier `OTHER`, `notify_payer`, `items`); tracker update. Record findings in `docs/VERIFICATION.md`.
4. Reply in plan mode with understanding, design, state transitions, open questions. **Wait for approval.**

## Objective
When a shipment is blocked because the buyer wants a different address (ADD-03) or pickup (ADD-12), offer a **PayPal-native fix**. Then, once the order is cleared, register the shipment's tracking with PayPal so proof of shipment exists from dispatch.

## Implementation tasks

### 1. Remediation Assistant (`ai/agents/remediation_assistant.py`)
- Generates a short, polite buyer message (≤ 900 chars) explaining that the seller can only ship to the address on the PayPal payment, and offering the chosen fix. Inputs: order facts and chosen fix only (no raw chat content). Output schema: `{subject, message}`. Validate; no promises about PayPal decisions.
- Seller copies the message; StayCovered never messages buyers directly in the MVP.

### 2. Fix options (`workflows/remediation.py`, `remediations` table)
- `POST /api/orders/{id}/remediations` with `type`:
  - `SHIP_TO_PROTECTED`: records the choice, returns the message draft; seller then uploads a label for the protected address (F2/F3 re-run).
  - `REPAY`: creates a remediation in `PENDING_CONFIRMATION` with a preview: refund amount, original capture ID, new shipping address (from the chat extraction's `requested_address`, editable and validated: line1, city, state, ZIP, country required), and the message draft.
- `POST /api/remediations/{id}/confirm` (seller confirmation token from the modal):
  1. Refund the original capture in full (`POST /v2/payments/captures/{id}/refund`) with a stable `PayPal-Request-Id` derived from the remediation ID (double clicks → one refund).
  2. Create a new PayPal order for the same item and amount with the requested address preset (`SET_PROVIDED_ADDRESS`); link it to the same StayCovered order (`new_paypal_order_id`); return the approval link for the seller to send.
  3. Buyer approves and pays (demo: via the shop's "pay this order" page that renders the PayPal button for an existing order ID); capture → reconciliation creates a new protected address **version**; previous decisions are superseded; verification re-runs (seller uploads the new label).
- Failure handling: refund fails → stop, show PayPal error and debug ID, no new order; order creation fails after refund → status `REFUNDED_AWAITING_NEW_ORDER` with retry button; buyer never pays → order stays unshippable (payment REFUNDED → RED PAY-05).
- If sandbox doesn't support the preset address flow as expected, implement the documented fallback (order without preset address + instruction to the buyer) and note it.

### 3. Shipment registration (`services/paypal/tracking.py`, `workflows/shipment.py`)
- `POST /api/orders/{id}/shipments`: allowed only if the active decision is GREEN, ACKNOWLEDGED (YELLOW) or OVERRIDDEN (RED, logged), and payment COMPLETED.
- Inputs: carrier (PayPal carrier enum list; include `OTHER` with a carrier-name field as the docs specify), tracking number, ship date, notify buyer (default true), optional items.
- Validate: tracking number format (basic per-carrier regex for USPS/UPS/FedEx/DHL, otherwise length/charset), uniqueness across orders (SHP-04), capture status COMPLETED.
- Call `POST /v2/checkout/orders/{paypal_order_id}/track` with `capture_id`; store tracker ID/links and raw response; set `shipment_state = SHIPPED` ("tracking registered with PayPal"), audit.
- Idempotent: same capture + tracking returns existing record.
- Multiple parcels: allow multiple shipments per order (one call per parcel).
- `PATCH /api/shipments/{id}` for status updates (e.g. CANCELLED, DELIVERED as seller-reported) using the tracker update endpoint where supported; otherwise local status with a note.
- Distinguish states clearly in UI: Label checked ≠ Shipped (tracking registered) ≠ Delivered.

### 4. UI
- Risk report "Fix this" button (enabled for ADD-03/ADD-12) → fix chooser with two cards explaining trade-offs.
- Re-pay confirmation modal: refund amount, new address, consequences, "Confirm refund and create new payment" button.
- New payment link panel with copy button and status (waiting for buyer → paid).
- Shipment form + shipment cards (carrier, tracking, PayPal tracker ID, status, registered time).
- Timeline entries for every step.

## Testing requirements
- Unit: remediation state machine, idempotent refund request IDs, address validation, tracking validation, uniqueness, gating by verdict.
- Integration (mock PayPal): REPAY happy path; refund failure; order-creation failure after refund; duplicate confirm clicks → one refund; tracking registration; non-COMPLETED capture blocked; idempotent tracking.
- Manual sandbox: full re-pay with the sandbox buyer; tracking registered and visible on the sandbox order (`GET /v2/checkout/orders/{id}`).

## Acceptance criteria
- AC4.1 Re-pay requires explicit confirmation; one refund even with repeated clicks.
- AC4.2 After the buyer pays the new order, the protected address is the new address and the decision is re-evaluated.
- AC4.3 Tracking registration succeeds for a COMPLETED capture and is idempotent.
- AC4.4 Tracking for a non-COMPLETED capture is blocked with a clear message.
- AC4.5 Reused tracking number is blocked (SHP-04).
- AC4.6 Shipping is disabled unless the decision allows it; overrides are audited.

## Deliverables
Code, migrations, tests passing, UI, `docs/STATUS.md` and `docs/VERIFICATION.md` updated, manual test script.
