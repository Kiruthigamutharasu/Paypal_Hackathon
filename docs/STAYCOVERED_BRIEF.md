> **SUPERSEDED:** this is an earlier draft kept for history. `docs/PRD.md` and `CLAUDE.md` are authoritative; where they differ (verdict rules, env names, API paths, auto-submit), follow the PRD. Do not implement from this file.

# Project brief for Claude Code: StayCovered

You are helping me build **StayCovered** for the PayPal AI Hackathon on Devpost. Read this whole brief before writing any code. Where something is marked **VERIFY**, check it against PayPal's official docs (use the PayPal AI Toolkit / sandbox MCP server if available) before relying on it. Never invent API endpoints, fields or webhook names. If something is unclear, ask me before assuming.

---

## 1. Hackathon constraints (non-negotiable)

- **Deadline:** Nov 12, 2026, 12:00 PM PT (1:30 AM IST, Nov 13). Plan to finish a day early.
- **Hard rule:** the project must meaningfully use **both PayPal and AI**, and PayPal must be central, not bolted on.
- **Everything runs in the free PayPal sandbox.** No live credentials, no real money.
- **Submission needs:** a working hosted demo (or clear run instructions), a public GitHub repo with an **MIT license** visible in the repo's About section, a demo video under 3 minutes, a text description, and a list of AI tools used and how.
- **Judging (equal weight):** Technological Implementation, Design (complete product experience), Potential Impact, Innovation, Presentation.

---

## 2. The problem

Small online sellers (Instagram, WhatsApp, small websites) get paid through PayPal. PayPal **Seller Protection** lets a seller keep the money if a buyer falsely claims "item not received", but only if the seller follows PayPal's rules:

1. Ship to the **exact shipping address on the PayPal transaction**. If the item goes to a different address, or is redirected later, protection is lost.
2. Have **online, verifiable tracking** showing delivery to that address.
3. For high-value orders, get **signature confirmation**. US threshold: **$750 USD** including shipping and tax (**VERIFY** in PayPal's current Seller Protection policy; make it a config value).

**The scam:** after paying, the buyer messages "it's a gift, please ship to my friend's address" or "my courier will pick it up". The seller agrees, ships elsewhere, the buyer files "item not received", PayPal finds the address mismatch, protection is void, and the seller loses the item and the money.

## 3. The solution

**StayCovered** is an AI agent that checks every shipment **before** it goes out, so the sale stays covered by PayPal Seller Protection, and that answers disputes with proof if they come anyway.

### Core user story (the demo)

1. A buyer pays the seller $300 through PayPal checkout (sandbox). The protected address is in New York.
2. The buyer messages: "It's a gift! Please ship to my friend in Texas."
3. The seller uploads a screenshot of that chat. StayCovered flags it: **"⛔ Shipping to a different address cancels your PayPal protection."**
4. The seller photographs the shipping label. StayCovered reads it and compares it with the PayPal address: **red** if it doesn't match, **green** if it does.
5. The seller ships to the PayPal address and enters the tracking number. StayCovered sends it to PayPal automatically.
6. The buyer files a fake "item not received" dispute (created in the sandbox). StayCovered gathers the proof and submits it through PayPal's Disputes API automatically.

---

## 4. Scope

### MVP (must have)
- A seller dashboard listing PayPal orders (synced from the sandbox).
- A **demo buyer shop page**: one product, PayPal JS SDK checkout, so a real sandbox order exists.
- An order detail page showing the protected shipping address, amount, Seller Protection status (if the API exposes it, see 6.3) and a checklist.
- **Chat check:** upload a screenshot or paste text; AI detects address-change, off-platform-payment or pickup requests.
- **Label check:** upload a label photo; AI reads the recipient address; **plain code** compares it with the PayPal address.
- **Signature rule:** warn when the amount is at or over the configured threshold.
- **Add tracking to PayPal** when the seller enters carrier and tracking number.
- **Webhooks:** receive and verify PayPal webhooks (payment captured, dispute created/updated/resolved).
- **Dispute responder:** when a dispute arrives, build an evidence pack (tracking, label photo, address match, timeline), let AI draft a short factual note, and submit it through the Disputes API. Show the status on the dashboard.
- **Audit log:** every check, warning and API call with timestamps.

### Stretch (only if MVP is done)
- WhatsApp Cloud API test number: the seller forwards a buyer's message to a WhatsApp number and the chat check runs automatically.
- An eval page: run the AI checks on 20–30 sample chats and labels and show the accuracy.

### Out of scope
- Live PayPal, real money, Instagram API, mobile apps, multi-seller accounts.

---

## 5. Tech stack

| Layer | Choice |
| --- | --- |
| Front end | Next.js (App Router, TypeScript), Tailwind |
| Back end | FastAPI (Python 3.11+) |
| Database | Postgres (SQLAlchemy + Alembic) |
| AI | **Gemini Flash via Google AI Studio (free tier)**, behind a provider interface so I can switch to Claude by changing an env var |
| Payments | PayPal sandbox REST APIs + PayPal JS SDK |
| Hosting | Render (web service for the back end, static/web for the front end, managed Postgres) |
| Dev tunnel | ngrok or Cloudflare Tunnel for webhooks during local development |

Put the AI behind one module, `ai_provider.py`, with functions like `analyze_chat(image_or_text) -> ChatCheck` and `read_label(image) -> LabelRead`, so the model can be swapped.

---

## 6. PayPal integration (sandbox)

Base URL: `https://api-m.sandbox.paypal.com`. Credentials come from env vars; the secret must never reach the front end or the repo.

### 6.1 Auth
- `POST /v1/oauth2/token` with client credentials. Cache the token and refresh before it expires.

### 6.2 Demo checkout (buyer side)
- PayPal JS SDK on the demo shop page. The server creates and captures the order with Orders v2: `POST /v2/checkout/orders` (intent CAPTURE, include a shipping address) and `POST /v2/checkout/orders/{id}/capture`.
- Store `order_id`, `capture_id`, amount, currency and shipping address.

### 6.3 Reading the protected address and protection status
- `GET /v2/checkout/orders/{id}` for the shipping address and purchase units.
- **VERIFY:** the capture response may include a `seller_protection` object (status such as ELIGIBLE / PARTIALLY_ELIGIBLE / NOT_ELIGIBLE). If present, show it. If not, show "check in PayPal" and don't fake it.

### 6.4 Add tracking
- `POST /v2/checkout/orders/{id}/track` with the `capture_id`, carrier and tracking number. **VERIFY** the request body and which order states allow it.

### 6.5 Disputes
- Enable **Disputes** on the sandbox app (Dashboard → app features → Save; it can take up to 10 minutes).
- `GET /v1/customer/disputes` and `GET /v1/customer/disputes/{id}`.
- Read the allowed responses from the dispute details and only call actions PayPal says are allowed.
- `POST /v1/customer/disputes/{id}/provide-evidence` (multipart: JSON plus files; **VERIFY** the exact format and evidence types, e.g. proof of fulfillment with tracking).
- Optional branch: `POST /v1/customer/disputes/{id}/accept-claim`.
- **Sandbox test disputes:** merchants can create disputes in the sandbox. **VERIFY** the exact call or dashboard method and document it in the README so judges can reproduce it.

### 6.6 Webhooks
- Subscribe to: `PAYMENT.CAPTURE.COMPLETED`, `CUSTOMER.DISPUTE.CREATED`, `CUSTOMER.DISPUTE.UPDATED`, `CUSTOMER.DISPUTE.RESOLVED` (**VERIFY** the names).
- **Verify every webhook** with `POST /v1/notifications/verify-webhook-signature` before acting on it.
- Return 200 quickly and process in the background. PayPal retries failed deliveries many times, so handlers must be **idempotent**: store event IDs and ignore duplicates.

### 6.7 Testing
- Use sandbox US Business (seller) and US Personal (buyer) accounts in the same country.
- Test unhappy paths: declined payment, wrong address, duplicate webhook, dispute on an order with no tracking.

---

## 7. AI tasks (strict JSON outputs)

The AI **only reads and writes words**. It never decides money matters or calls PayPal. All final decisions are made by plain code using the AI's structured output.

### 7.1 `analyze_chat`
Input: a chat screenshot or pasted text, plus the protected PayPal address for context.
Output JSON:
```json
{
  "address_change_requested": true,
  "requested_address_text": "string or null",
  "pickup_or_courier_requested": false,
  "off_platform_payment_requested": false,
  "other_risk_signals": ["string"],
  "evidence_quotes": ["short exact phrases from the chat"],
  "confidence": 0.0
}
```

### 7.2 `read_label`
Input: a label photo.
Output JSON:
```json
{
  "recipient_name": "string or null",
  "address_line1": "string or null",
  "address_line2": "string or null",
  "city": "string or null",
  "state": "string or null",
  "postal_code": "string or null",
  "country": "string or null",
  "tracking_number_visible": "string or null",
  "readable": true,
  "confidence": 0.0
}
```

### 7.3 `draft_dispute_note`
Input: the evidence pack (facts only, from the database).
Output: a short, factual note (under 1,000 characters) with no claims not supported by the evidence pack.

### Rules
- Validate every AI response against a schema (Pydantic). If validation fails or confidence is low, show **"Couldn't verify, please check manually"** rather than guessing.
- Never put model text into amounts, addresses sent to PayPal, or API decisions without passing through validation and code rules.

---

## 8. Decision rules (plain code, not AI)

- **Address match:** normalize both addresses (case, punctuation, abbreviations like St/Street, Apt/Unit). Postal code and city must match exactly after normalization, and the street must match closely (a small typo distance is allowed). The result is MATCH, MISMATCH or UNREADABLE.
- **Overall status per order:**
  - 🔴 **Don't ship:** address mismatch, address change requested in chat, or pickup/courier requested.
  - 🟡 **Needs attention:** signature confirmation needed but not confirmed, label unreadable, or low AI confidence.
  - 🟢 **Safe to ship:** label matches, no risky chat signals, and the signature requirement is satisfied.
- Signature threshold is a config value (default 750 USD).

---

## 9. Data model (minimum)

- `orders`: id, paypal_order_id, capture_id, amount, currency, shipping_address (JSON), seller_protection_status, status, created_at
- `checks`: id, order_id, type (chat | label), input_ref (file path), ai_output (JSON), result, created_at
- `shipments`: id, order_id, carrier, tracking_number, paypal_tracking_status, created_at
- `disputes`: id, paypal_dispute_id, order_id, reason, status, evidence_submitted_at, raw (JSON)
- `webhook_events`: id, paypal_event_id (unique), type, verified, processed_at, raw (JSON)
- `audit_log`: id, order_id, actor (system | seller | ai), action, details (JSON), created_at

Store uploaded images on disk or Render's disk for the demo, and reference them by path.

---

## 10. Screens

1. **Dashboard:** orders with a red/yellow/green badge, plus a disputes panel.
2. **Order detail:** PayPal address and amount, protection status, checklist, chat check, label check, tracking entry, timeline.
3. **Dispute detail:** reason, evidence pack preview, AI draft note (editable), "Submit to PayPal" button and result.
4. **Demo shop:** one product with PayPal checkout (to create real sandbox orders).
5. **About/architecture page** (helps the judges).

Keep the UI clean and clear; Design is a full fifth of the score.

---

## 11. Security and quality

- Secrets only in env vars; commit a `.env.example`.
- Verify all webhooks; make handlers idempotent.
- Use a `PayPal-Request-Id` header on PayPal POST calls where supported, to avoid duplicate actions.
- Log every PayPal call (request ID, status) in the audit log, never logging secrets.
- Handle PayPal errors gracefully and show readable messages.
- Unit tests for address normalization/matching and the decision rules. One end-to-end sandbox test script.

---

## 12. Repository deliverables

- MIT `LICENSE` file at the root.
- `README.md` with: the hosted demo URL and video link at the top; a 90-second "try it" path; sandbox test account setup; how to create a sandbox dispute; local run steps (five commands or fewer); an architecture diagram; a table of the PayPal APIs used; the AI tools used and how; known limits.
- `.env.example` listing all variables (PayPal client ID/secret, webhook ID, AI provider and key, database URL, signature threshold).

---

## 13. Build order

1. Repo skeleton (Next.js + FastAPI + Postgres), MIT license, `.env.example`, and a deploy to Render early.
2. PayPal auth + demo shop checkout + order sync into the database.
3. Webhook endpoint with signature verification and idempotency.
4. Order detail page + address display + signature rule.
5. AI provider module + `read_label` + address matching + status badge.
6. `analyze_chat` + chat check UI.
7. Add tracking to PayPal.
8. Disputes: list/detail sync, evidence pack, AI note, provide-evidence submission.
9. Audit log + timeline UI + polish.
10. README, tests, end-to-end run on the hosted URL.
11. Stretch items only after everything above works.

After each step, tell me what you built, what you verified against the docs, and anything you're unsure about.

---

## 14. How to work with me

- Ask before making assumptions that change scope, cost or architecture.
- Prefer simple, readable code over clever code; this is a 9-day hackathon.
- When a PayPal detail is uncertain, check the docs or the sandbox first, then tell me what you found.
- Keep the demo story in section 3 working end to end at all times.
