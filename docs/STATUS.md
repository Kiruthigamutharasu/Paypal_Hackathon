# StayCovered — build status

_Last updated: Nov 5, 2026_

| Feature | Status |
| --- | --- |
| F1 Payment Intake & Order Hub | **Done locally; not yet deployed (Render pending approval)** |
| F2 Evidence Intake & AI Extraction | Not started |
| F3 Decision Engine & Risk Report | Not started |
| F4 Safe Fix, Shipment & Tracking | Not started |
| F5 Dispute Defense & Launch | Not started |

## F1 — Payment Intake & Order Hub

### Done
- Backend scaffold (`backend/`): FastAPI, SQLAlchemy 2, Alembic, pydantic-settings reading the **root** `.env` with the exact `.env.example` names.
- Startup guard: refuses to start unless `PAYPAL_ENVIRONMENT=sandbox` and `PAYPAL_BASE_URL` host is `api-m.sandbox.paypal.com` (AC1.4).
- PayPal client (`services/paypal/client.py`): token cache with 5-min refresh margin, one transparent refresh on 401, retries with exponential backoff on 429/5xx/network (max 3, honours `Retry-After`), `PayPal-Request-Id` on every POST, `paypal-debug-id` captured, every call written to `audit_logs` as `PAYPAL_API_CALL` without secrets.
- Demo shop API: fixed catalog ($300 Handmade Silver Necklace); amount always from the server; stable capture request ID (`shop-capture-{order_id}`) so double clicks can't double-capture; `ORDER_ALREADY_CAPTURED` handled; `INSTRUMENT_DECLINED` returns a clear message.
- Reconciliation: re-fetches order + each capture; upserts orders/captures; versioned protected address (new version only when PayPal's address changes); `seller_protection` stored or `UNKNOWN`; idempotent (no duplicate rows or audit entries).
- Webhooks: signature verified via PayPal, rejected → 400 + `SECURITY_WEBHOOK_SIGNATURE_INVALID` audit; dedupe by event ID (unique constraint + race handling); background processing always re-fetches from PayPal; dispute events stored (`STORED`) for F5; failures kept as `FAILED` and re-runnable via `POST /api/admin/webhooks/reprocess`.
- Orders API: list, detail (with timeline), refresh from PayPal, sync by PayPal order ID, health.
- Frontend (`frontend/`): Next.js 16 (App Router, TS), Tailwind 4, shadcn/ui (Base UI), AG Grid Community dashboard, order detail (PayPal panel, protected address, checklist, timeline), demo shop with **PayPal JS SDK v6**, How it works page.
- `render.yaml` blueprint (backend, frontend, Postgres).

### Tests
- `backend`: **48 passing** (`pytest`) — config guard, token cache/refresh, retries/backoff, error mapping, status mapping, reconcile idempotency + address versioning, create→capture→reconcile, webhook valid / invalid / missing headers / replayed 3× / out-of-order / dispute stored / failed→reprocess, PayPal-down → SYS-02.
- `frontend`: `tsc`, `eslint` and `next build` clean.
- Live sandbox smoke (Nov 5): token OK, real order created via `/api/shop/orders`, real 404 → PAY-09 with debug ID, unsigned webhook rejected, CORS only allows `FRONTEND_ORIGIN`.

### Acceptance criteria
| AC | Status |
| --- | --- |
| AC1.1 one payment → one order, COMPLETED, address + Seller Protection | Automated with mocks ✅ · **manual sandbox payment pending** |
| AC1.2 webhook replayed 3× → one row, processed once | ✅ test |
| AC1.3 invalid signature → 400, audit, no change | ✅ test + live |
| AC1.4 non-sandbox config refuses to start | ✅ test |
| AC1.5 token expiry handled transparently | ✅ test |
| AC1.6 dashboard + detail show PayPal data and timeline | ✅ built · pending visual check with a real payment |
| AC1.7 deployed on Render, health OK, README ≤ 5 commands | README ✅ · **deploy pending** |

### Not done / known issues
- Render deploy not done (needs seller approval + Render env values).
- `PAYPAL_WEBHOOK_ID` is empty: webhooks are rejected until a webhook is registered at `${PUBLIC_BASE_URL}/api/webhooks/paypal` (needs a public URL: ngrok/cloudflared or Render).
- Admin webhook endpoints are unauthenticated (single-seller demo, documented MVP limitation).
- Local dev uses SQLite (no Postgres/Docker on the dev machine); Render uses Postgres. Migrations are generated so they work on both.
- Render free tier has no persistent disk: uploads (F2) will need a paid disk or another store — decide before F2 deploy.
