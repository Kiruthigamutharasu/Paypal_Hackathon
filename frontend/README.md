# StayCovered — frontend

Next.js (App Router, TypeScript) seller app and demo shop. See the [root README](../README.md) for the full project.

```bash
npm install
npm run dev      # http://localhost:3000
npm run build    # production build
npm run lint
```

Configuration comes from the root `.env`; only `NEXT_PUBLIC_PAYPAL_CLIENT_ID` and `NEXT_PUBLIC_API_BASE_URL`
reach the browser (see `next.config.ts`).

| Path | Page |
| --- | --- |
| `/` | Seller dashboard (orders, KPIs) |
| `/orders/[id]` | Order detail: PayPal facts, protected address, evidence check, activity |
| `/shop` | Demo shop (buyer view) with PayPal JS SDK v6 |
| `/how-it-works` | Architecture and seller journey |
