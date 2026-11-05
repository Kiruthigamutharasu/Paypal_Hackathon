# Demo kit — files to upload while testing

All files are synthetic. Labels assume the PayPal sandbox buyer address
**John Doe, 2211 N First St, San Jose, CA 95131** (regenerate with `--name/--line1/...` if yours differs).

| File | Upload where | Expected result |
| --- | --- | --- |
| `01-chat-buyer-asks-ship-to-friend.png` | Evidence check → Screenshots | **RED** · ADD-03 "Buyer requested a different address" with the exact quote |
| `02-chat-safe-no-risk.png` | Evidence check → Screenshots | No risky requests |
| `03-chat-paste-text.txt` | Evidence check → Paste text (copy the text in) | **YELLOW** · AI-30 suspicious instruction + OFF-01 payment outside PayPal (the AI does **not** obey it) |
| `04-label-WRONG-street.png` | Evidence check → Shipping label | **RED** · ADD-08 street differs (1 Main St vs 2211 N First St) |
| `05-label-CORRECT-paypal-address.png` | Evidence check → Replace shipping label | Address matches → **GREEN** if the chat is safe |
| `06-label-NEW-austin-address-after-repay.png` | After Safe re-pay is paid → Replace shipping label | Matches the new protected address (Austin) → **GREEN** |

Tracking numbers to type when registering the shipment (USPS):
- shipping to the PayPal address: `9400 1118 9922 3344 5566 77`
- shipping to Austin after Safe re-pay: `9400 1118 9922 5555 6666 77`
