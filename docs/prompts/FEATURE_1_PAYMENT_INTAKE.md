# Claude Code prompt — Feature 1: PayPal Payment Intake & Order Hub

You are a senior full-stack engineer and AI agent developer working on **StayCovered** for the PayPal AI Hackathon. This is Feature 1 of 5.

## Before you write any code
1. Read `CLAUDE.md` and `docs/PRD.md` fully (focus: sections 1, 5, 6, 9, 10, 11, 12 and 13-F1).
2. Inspect the repository (tree, existing files, `.env.example`). Do not modify or delete `.env.example`.
3. Reply in plan mode with: your understanding of F1, the files/folders you will create, the libraries and versions you'll use, open questions, and anything in the PRD you think is wrong. **Wait for my approval before implementing.**

## Objective
Build the project foundation and a trustworthy payment intake: a demo shop that creates real PayPal sandbox payments, persistence of each order's capture, protected shipping address and Seller Protection status, verified and idempotent webhooks with reconciliation, an audit log, and an orders dashboard. Deploy to Render.

## Scope
**In:** monorepo scaffold, config, database + migrations, PayPal client, demo shop checkout, order persistence, webhooks, reconciliation, audit log, dashboard + order detail (PayPal panel, timeline), README run steps, Render deployment.
**Out (later features):** uploads, AI, rule engine, remediation, tracking, disputes.

## Implementation tasks

### 1. Scaffold
- `/backend` (FastAPI, Python 3.11+), `/frontend` (Next.js App Router, TypeScript, Tailwind, shadcn/ui, AG Grid Community), `/docs` (`STATUS.md`, `VERIFICATION.md` created if missing).
- Root `.gitignore` (include `.env`, `uploads/`, `node_modules/`, `.venv/`, `__pycache__/`). Root `LICENSE` (MIT) if missing.
- Both apps read config from the **root** `.env` (backend via pydantic-settings with `env_file="../.env"`; frontend via `next.config` loading the root `.env` for `NEXT_PUBLIC_*` only).

### 2. Config (`backend/app/config.py`)
- Pydantic Settings using **exactly** these names: `PAYPAL_ENVIRONMENT`, `PAYPAL_BASE_URL`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, `AI_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `AI_CONFIDENCE_THRESHOLD`, `PUBLIC_BASE_URL`, `FRONTEND_ORIGIN`, `DATABASE_URL`, `FILE_STORAGE_PATH`, `SIGNATURE_THRESHOLD_USD`, `AUTO_SUBMIT_EVIDENCE`.
- Startup guard: refuse to start unless `PAYPAL_ENVIRONMENT == "sandbox"` and `PAYPAL_BASE_URL` host is `api-m.sandbox.paypal.com`.
- CORS allows only `FRONTEND_ORIGIN`.

### 3. Database
- SQLAlchemy 2.x + Alembic. Tables for F1: `orders`, `captures`, `protected_addresses`, `webhook_events`, `audit_logs` (columns and constraints per PRD §10, include `seller_id` with a single default seller).
- Separate state columns: `payment_state` (PAYMENT_PENDING, PAYMENT_COMPLETED, PAYMENT_FAILED, PARTIALLY_REFUNDED, REFUNDED, REVERSED), `verification_state` (default AWAITING_DOCUMENTS), `shipment_state` (default NOT_SHIPPED).
- Audit helper `audit(order_id, actor, action, details)` used for every state change.

### 4. PayPal client (`backend/app/services/paypal/`)
- `client.py`: OAuth client-credentials token with in-memory cache (refresh ~5 min before expiry); `request()` with timeouts, retries with exponential backoff on 429/5xx (max 3), `PayPal-Request-Id` header support for POSTs, captures `paypal-debug-id`, writes audit entries without secrets.
- `orders.py`: `create_order(items, amount, shipping)`, `capture_order(order_id, request_id)`, `get_order(order_id)`.
- `payments.py`: `get_capture(capture_id)`.
- `webhooks.py`: `verify_signature(headers, body)` via `POST /v1/notifications/verify-webhook-signature` using `PAYPAL_WEBHOOK_ID`.
- Verify request/response fields against the official docs (use the PayPal AI Toolkit / MCP if available). Record unverified points in `docs/VERIFICATION.md`.

### 5. Demo shop
- Backend: `POST /api/shop/orders` creates an order for a fixed catalog item ("Handmade Silver Necklace", $300.00 USD) with intent CAPTURE; `POST /api/shop/orders/{paypal_order_id}/capture` captures, then calls the reconciliation service.
- Frontend `/shop`: product card + PayPal button via the PayPal JS SDK using `NEXT_PUBLIC_PAYPAL_CLIENT_ID` (createOrder/onApprove call our backend; never call PayPal REST from the browser). Show a "Sandbox demo" notice and a success state linking to the seller dashboard.
- Choose the JS SDK version consistently (v6 is current; if you use v5, note why in `VERIFICATION.md`).

### 6. Reconciliation service
- `reconcile_order(paypal_order_id)`: fetch order + capture from PayPal; upsert `orders`, `captures` (status, amount, `seller_protection.status` and `dispute_categories` — store `UNKNOWN` if absent), and `protected_addresses` (from `purchase_units[].shipping`; version it). Map capture status to `payment_state`. Idempotent.

### 7. Webhooks (`POST /api/webhooks/paypal`)
- Read raw body; verify signature; on failure return 400 and audit a security warning.
- Deduplicate by `paypal_event_id` (unique constraint); duplicates return 200 with no processing.
- Store event, return 200 quickly, process in a background task: for payment events (`PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.PENDING`, `PAYMENT.CAPTURE.DENIED`, `PAYMENT.CAPTURE.REFUNDED`, `PAYMENT.CAPTURE.REVERSED` — verify names) always **re-fetch** the capture/order and reconcile; never trust webhook payload state alone. Dispute events are accepted and stored now; processing comes in F5.
- Mark `processed_at`/`status`; failures are retried by re-processing stored events (a small admin endpoint or CLI is fine).

### 8. Orders API + UI
- `GET /api/orders`, `GET /api/orders/{id}`, `POST /api/orders/{id}/refresh`, `GET /api/health`.
- Dashboard `/`: AG Grid (Community) with columns: created, buyer (masked email), amount, payment state, Seller Protection status, verdict (placeholder "—"), shipment state; sorting/filtering; row click → detail.
- Order detail `/orders/[id]`: PayPal panel (order ID, capture ID, status, amount, Seller Protection status with explanation text, protected address), "Refresh from PayPal" button, timeline from `audit_logs`.
- "How it works" page with a placeholder architecture diagram.

### 9. Deployment
- `render.yaml` (backend web service, frontend web service, Postgres). Document env vars to set in Render (same names). Note the webhook URL `${PUBLIC_BASE_URL}/api/webhooks/paypal`.

## Testing requirements
- Unit: config guard; token caching/refresh (mock time); retry/backoff; status mapping; reconciliation upsert idempotency.
- Integration (mock PayPal with respx): create→capture→reconcile; webhook valid/invalid signature; duplicate event 3× → one row; out-of-order events (REFUNDED before COMPLETED) end in correct state after re-fetch.
- Manual sandbox test: pay as the sandbox US buyer; order appears with COMPLETED and Seller Protection status.

## Acceptance criteria (must all pass)
- AC1.1 One sandbox payment → exactly one order with capture COMPLETED, protected address and Seller Protection status (or UNKNOWN).
- AC1.2 Same webhook replayed 3× → one `webhook_events` row, processed once.
- AC1.3 Invalid signature → 400, security audit entry, no state change.
- AC1.4 Non-sandbox config → backend refuses to start.
- AC1.5 Expired token is refreshed transparently (test).
- AC1.6 Dashboard and order detail show PayPal data and timeline.
- AC1.7 Deployed on Render; `/api/health` OK; README local run works from a fresh clone in ≤ 5 commands.

## Deliverables
Code, migrations, tests passing, `README.md` (setup, sandbox accounts, run steps, deploy), `docs/STATUS.md` updated, `docs/VERIFICATION.md` updated, and a short manual test script in your final message.
