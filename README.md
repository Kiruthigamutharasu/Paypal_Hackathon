# StayCovered

AI assistant that helps PayPal sellers stay covered by Seller Protection: it checks orders,
sends tracking to PayPal, and helps answer disputes with the right evidence.

Built for the PayPal AI Hackathon (Devpost). Uses the PayPal sandbox only.

## Run locally
Needs Python 3.11+ and Node 20+. Both apps read the single root `.env`.

```bash
cp .env.example .env        # fill PAYPAL_CLIENT_ID/SECRET, NEXT_PUBLIC_PAYPAL_CLIENT_ID (same client ID)
python -m venv .venv && .venv/Scripts/pip install -r backend/requirements.txt   # macOS/Linux: .venv/bin/pip
cd backend && ../.venv/Scripts/alembic upgrade head && ../.venv/Scripts/uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev        # in a second terminal
```
Open http://localhost:3000 (seller dashboard) and http://localhost:3000/shop (demo shop).
With `DATABASE_URL` empty the backend uses a local SQLite file; on Render it uses Postgres.

**Webhooks (optional locally):** expose port 8000 (e.g. `cloudflared tunnel --url http://localhost:8000`),
register `https://<public-url>/api/webhooks/paypal` on your sandbox app, and put its ID in `PAYPAL_WEBHOOK_ID`.
Without it, webhooks are rejected (safe default) and orders still sync on capture or via "Refresh from PayPal".

**Tests:** `cd backend && ../.venv/Scripts/python -m pytest` (PayPal and the AI model are mocked; no network needed).

**AI eval (real model):** `cd backend && ../.venv/Scripts/python scripts/eval_extraction.py` runs the Conversation
Analyst and Label Reader on 24 synthetic chats and 12 synthetic labels and writes [docs/EVAL_RESULTS.md](docs/EVAL_RESULTS.md).
Note: the Gemini free tier allows only ~20 requests/day per model.

**PayPal AI Toolkit in Claude Code (developer tool, optional):** `python scripts/paypal_token.py`
writes a sandbox token to `~/.claude/settings.json` (expires after ~9h).

## Deploy (Render)
`render.yaml` defines the API, the web app and Postgres. Enter the `sync: false` values in the Render
dashboard (same names as `.env.example`), then register the webhook at `${PUBLIC_BASE_URL}/api/webhooks/paypal`.

## PayPal APIs used (so far)
| Purpose | API |
| --- | --- |
| Auth | `POST /v1/oauth2/token` |
| Demo shop checkout | Orders v2 `POST /v2/checkout/orders`, `POST /v2/checkout/orders/{id}/capture`, JS SDK v6 |
| Protected address, status | `GET /v2/checkout/orders/{id}`, `GET /v2/payments/captures/{id}` (`seller_protection`) |
| Webhooks | `POST /v1/notifications/verify-webhook-signature`; `PAYMENT.CAPTURE.*`, `CUSTOMER.DISPUTE.*` |

## AI used (so far)
| Agent | Model | What it does | What it can't do |
| --- | --- | --- | --- |
| Conversation Analyst | Gemini (`GEMINI_MODEL`, fallback `gemini-3.5-flash-lite`) or Claude | Reads chat screenshots/text; extracts address-change, pickup, off-platform-payment and other risky requests with exact quotes and sources | Approve or block shipping, move money, call PayPal |
| Label Reader | same | Reads the recipient address from a label photo/PDF with per-field confidence | Compare addresses (plain code does that) |

AI output is schema-constrained JSON validated with Pydantic; uploaded content is treated as untrusted data
(prompt-injection text is reported, never followed); anything the model can't trace to the evidence is discarded.

## How to test (sandbox)
| Role | Sandbox account |
| --- | --- |
| Seller (US Business) | `sb-bbqbj53656419@business.example.com` |
| Buyer (US Personal) | `sb-tpsd4753696841@personal.example.com` |

Sandbox accounts use fake money only. The buyer password will be shared here for judges before submission.

## Docs
- [Product requirements (PRD)](docs/PRD.md) · [Feature prompts](docs/prompts/) · [Project rules](CLAUDE.md)
- [Build status](docs/STATUS.md) · [PayPal verification log](docs/VERIFICATION.md)
- Earlier drafts (superseded): [brief](docs/STAYCOVERED_BRIEF.md) · [spec](docs/STAYCOVERED_SPEC.md)
- PayPal AI Toolkit: https://github.com/paypal/AI-Toolkit

## License
MIT — see [LICENSE](LICENSE).
