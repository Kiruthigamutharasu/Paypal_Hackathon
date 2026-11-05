# PayPal facts — verification log

Status key: **VERIFIED-LIVE** (seen in the sandbox) · **DOCS** (from PayPal reference/AI Toolkit, not yet seen live) · **OPEN** (unverified; how to test given).

## Feature 1

| # | Fact we rely on | Status | Evidence / how to test |
| --- | --- | --- | --- |
| 1 | `POST /v1/oauth2/token` client credentials returns `access_token`, `expires_in` | VERIFIED-LIVE | Nov 5: `expires_in` = 32400 s. Code reads `expires_in`, never assumes. |
| 2 | `POST /v2/checkout/orders` with `payment_source.paypal.experience_context` (`shipping_preference`, `user_action`, `brand_name`, `return_url`, `cancel_url`) returns `status: PAYER_ACTION_REQUIRED` and a `payer-action` link | VERIFIED-LIVE | Nov 5 sandbox order `6H043577BF482753H`, `1WF28646N5213022D`. |
| 3 | `shipping_preference: GET_FROM_FILE` → buyer's PayPal address is on the order (`purchase_units[0].shipping.address`, fields `address_line_1/2`, `admin_area_2` city, `admin_area_1` state, `postal_code`, `country_code`; `shipping.name.full_name`) | VERIFIED-LIVE | Nov 5: buyer paid orders `3BL4494784605340C`, `0HE222123G478402U`; address parsed (San Jose, CA, US). |
| 4 | Capture object includes `seller_protection.status` (`ELIGIBLE`/`PARTIALLY_ELIGIBLE`/`NOT_ELIGIBLE`) and `dispute_categories` | VERIFIED-LIVE | Nov 5: `seller_protection.status=ELIGIBLE`, `dispute_categories=[ITEM_NOT_RECEIVED, UNAUTHORIZED_TRANSACTION]`. If absent we store `UNKNOWN`. |
| 5 | Capture `supplementary_data.related_ids.order_id` links a capture to its order | VERIFIED-LIVE | Nov 5: present on `GET /v2/payments/captures/{id}`. |
| 6 | Capture status enum: COMPLETED, DECLINED, PARTIALLY_REFUNDED, PENDING, REFUNDED, FAILED | DOCS | Mapped in `services/reconcile.py`. |
| 7 | A reversal shows as capture status `REVERSED` | OPEN | Not in the documented capture enum. We map it if it appears; otherwise a reversal will look REFUNDED after re-fetch. Test: Webhooks Simulator `PAYMENT.CAPTURE.REVERSED` + inspect resource `status`. |
| 8 | 422 issues `INSTRUMENT_DECLINED`, `ORDER_ALREADY_CAPTURED`, `ORDER_NOT_APPROVED` on capture | DOCS | Handled in `api/shop.py`. Test declined: sandbox negative testing. |
| 9 | Webhook verification: `POST /v1/notifications/verify-webhook-signature` with `auth_algo`, `cert_url`, `transmission_id`, `transmission_sig`, `transmission_time` (from `PAYPAL-*` headers), `webhook_id`, `webhook_event` → `verification_status: SUCCESS` | DOCS | Register the webhook, set `PAYPAL_WEBHOOK_ID`, make a payment, check `GET /api/admin/webhooks` shows `PROCESSED`. Note: the Webhooks Simulator's mock events cannot be verified by this API (known PayPal behaviour) — test with a real sandbox payment. |
| 10 | Event names `PAYMENT.CAPTURE.COMPLETED`, `.DENIED`, `.REFUNDED` | DOCS | Listed in the PayPal AI Toolkit reference. |
| 11 | Event names `PAYMENT.CAPTURE.PENDING`, `PAYMENT.CAPTURE.REVERSED`, `CUSTOMER.DISPUTE.UPDATED` | OPEN | Check the event list when registering the webhook in the dashboard; subscribe only to names that exist. |
| 12 | Refund/reversal webhook resource links to its capture via a link whose href contains `/v2/payments/captures/{id}` | OPEN | Refund a sandbox payment in the seller account; inspect the stored raw event. |
| 13 | JS SDK v6: script `https://www.sandbox.paypal.com/web-sdk/v6/core`, `createInstance({clientId, components:["paypal-payments"]})`, `findEligibleMethods`, `createPayPalOneTimePaymentSession({onApprove,onCancel,onError})`, `session.start({presentationMode:"auto"}, promise)` with `{orderId}`, `<paypal-button>` | VERIFIED-LIVE | Nov 5: buyer paid via `<paypal-button>` popup (SDK 6.71.1), onApprove → server capture. `start()` receives an invoked Promise. |
| 15 | Refund: `POST /v2/payments/captures/{id}/refund`, empty body = full refund, `PayPal-Request-Id` idempotency | VERIFIED-LIVE | Nov 5: refund `4NY88480VY6457019` status COMPLETED; a repeated confirm made no second refund. |
| 16 | Create order with `shipping_preference: SET_PROVIDED_ADDRESS` + `purchase_units[0].shipping` | VERIFIED-LIVE | Nov 5: orders `7BP0540820135115W` and `43G92137RP757972C` created with the Austin address. The buyer still needs to pay one via `/pay/{id}`. |
| 17 | Add tracking `POST /v2/checkout/orders/{id}/track` returns the order; tracker id `{capture_id}-{tracking_number}`, status SHIPPED, link rel `update` | VERIFIED-LIVE | Nov 5 on order `3BL4494784605340C`. |
| 18 | Carrier enums `USPS`, `UPS`, `FEDEX`, `DHL`, `DHL_API`, `OTHER` + `carrier_name_other` | VERIFIED-LIVE | Nov 5 (FEDEX from the docs example). |
| 19 | Cancel tracker: `PATCH .../trackers/{tracker_id}` with `[{"op":"replace","path":"/status","value":"CANCELLED"}]` (only CANCELLED is supported) | VERIFIED-LIVE | Nov 5: status changed to CANCELLED. |
| 20 | Provide evidence multipart: JSON part `input` with `{"evidences":[{"evidence_type":"PROOF_OF_FULFILLMENT","evidence_info":{"tracking_info":[{"carrier_name","tracking_number"}]},"notes"}]}` + file parts `evidence-file` | OPEN | The docs page lists only an `evidence-file` part and says the evidence is "in the JSON request body". Test: open a sandbox item-not-received dispute as the buyer, Sync, Prepare, Submit; on a 4xx read the debug_id and adjust the part name. |
| 21 | Dispute fields: `dispute_id`, `reason`, `status`, `dispute_life_cycle_stage`, `seller_response_due_date`, `dispute_amount`, `disputed_transactions[].seller_transaction_id`, `evidences[].source=REQUESTED_FROM_SELLER`, HATEOAS `links` | DOCS | developer.paypal.com/api/customer-disputes/v1/disputes-get. Allowed actions are taken from the POST link URLs (robust to rel naming). |
| 22 | No API to create a dispute; sandbox `adjudicate` (`adjudication_outcome` SELLER_FAVOR/BUYER_FAVOR, needs UNDER_REVIEW) and `require-evidence` (`action` SELLER_EVIDENCE/BUYER_EVIDENCE) | DOCS | The Disputes v1 endpoint list has no create; the sandbox disputes guide URL returned 404. The buyer opens the dispute on sandbox.paypal.com. |
| 23 | Disputes API enabled for the app | VERIFIED-LIVE | Nov 5: `GET /v1/customer/disputes` → 200 (0 items). |
| 14 | Seller Protection rules (ship to transaction address; signature over $750 for US transactions before Jan 26, 2026, recommended after) | OPEN | Implemented in `rules/policy.py` (cutoff 2026-01-26 as a constant); still re-read PayPal's current US Seller Protection page before submission. |

## Manual verification still needed (F1)
1. ~~Pay in `/shop` as the sandbox buyer~~ — done Nov 5 (rows 3, 4, 5, 13 verified).
2. Register a webhook (needs public URL) → confirm rows 9–12.

## Manual verification still needed (F4/F5)
1. Pay the re-pay order as the sandbox buyer at `/pay/43G92137RP757972C` → the order shows protected address v2 (Austin) and `REPAY_PAID`.
2. Open an "item not received" dispute as the sandbox buyer → Sync → Prepare evidence → Submit → confirm row 20.
3. If PayPal moves the dispute to UNDER_REVIEW, use "Settle in seller's favour" (row 22).
