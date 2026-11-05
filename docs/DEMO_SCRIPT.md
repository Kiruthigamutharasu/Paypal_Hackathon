# StayCovered — demo video script (target 2:50)

Record on the hosted build (or localhost). Close `.env` and any tab that shows keys. No music with copyright.
Use a **fresh** sandbox order for the recording so every step is live.

## Before recording (10 minutes)
1. Backend and frontend running; open http://localhost:3000 in a clean browser window at 1400×900.
2. Have ready: `backend/tests/fixtures/chats/c01_gift_friend_austin.png`, `backend/tests/fixtures/labels/l01_clean_ny.png` (wrong address) and a label for the new address (`l03_clean_austin.png`).
3. Sandbox buyer email/password at hand (not on screen).
4. Gemini: record early in the day (free-tier quota resets daily). A full run uses about 4–6 AI calls.
5. For the dispute scene, open an "item not received" dispute as the sandbox buyer on sandbox.paypal.com **before** recording (PayPal has no API to create one), on an order you have already shipped in StayCovered.

## Scenes

| Time | On screen | Say (roughly) |
| --- | --- | --- |
| 0:00–0:18 | How it works page, title | "Priya sells handmade jewellery on Instagram. A buyer paid $300, then asked her to ship to a friend in Austin. She did. The buyer said it never arrived — and PayPal couldn't protect her, because the parcel didn't go to the address on the payment. She lost the necklace and the money." |
| 0:18–0:35 | Demo shop → PayPal popup → Payment complete | "The buyer pays with PayPal. StayCovered records PayPal's protected address and Seller Protection status straight from the PayPal API — here, Eligible." |
| 0:35–1:05 | Order page → Evidence check: drop the chat screenshot and the label | "Before shipping, Priya uploads the chat and the label photo. Gemini reads them and quotes the buyer word for word: *ship to my friend in Austin*. Plain code compares the label with the PayPal address — and blocks the shipment, with the reason." Point at the RED banner and the PayPal-vs-label table. |
| 1:05–1:30 | "Fix this safely" → Safe re-pay → confirm code → pay link | "Instead of breaking the rule, Priya uses Safe re-pay: one confirmation refunds the payment and creates a new PayPal payment with the Austin address. The AI drafts a polite message to send." Open the pay link, pay as the buyer. |
| 1:30–1:50 | Upload the Austin label → GREEN → register tracking | "Now the new address is the protected address. New label — checks passed. Not a guarantee, but every rule is met. Tracking is registered with PayPal at dispatch." Show the PayPal tracker ID. |
| 1:50–2:30 | Disputes → dispute → Prepare evidence → verified note → Submit | "A week later: 'item not received'. The Dispute Defense Agent picks proof of fulfilment with the tracking, attaches the label and a summary, and the AI drafts the note. Every sentence is checked against our records — try adding a false claim and submission is blocked. Priya reviews and submits to PayPal." |
| 2:30–2:50 | How it works architecture | "AI extracts. Rules decide. You approve. PayPal moves the money. Built on PayPal Orders, Payments, Tracking, Disputes and Webhooks, with Google Gemini — all in the PayPal sandbox." |

## If something goes wrong while recording
- AI says "unavailable — retry": wait a minute and press **Retry AI check** (free-tier 503s are common).
- Dispute shows "PayPal does not allow providing evidence right now": use **Ask seller for evidence** in Sandbox demo tools, then Refresh.
- Settle the dispute at the end with **Settle in seller's favour** (needs status "PayPal reviewing").
