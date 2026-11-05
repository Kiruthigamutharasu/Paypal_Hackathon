"use client";

/**
 * Demo buyer shop. PayPal JS SDK v6 (web-sdk/v6/core) with client ID auth.
 * Orders are created and captured by OUR backend (createOrder/onApprove call /api/shop/*);
 * the browser never calls PayPal REST and never sends an amount.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Script from "next/script";
import Link from "next/link";
import { CheckCircle2, Info, Loader2, Lock, ShieldCheck, Sparkles, Truck } from "lucide-react";

import { api, ApiError, money, type Product } from "@/lib/api";
import type { PayPalOneTimeSession } from "@/types/paypal";
import { Button } from "@/components/ui/button";
import { Alert, AlertTitle } from "@/components/ui/alert";
import { ProtectionPill } from "@/components/status";

const SDK_URL = "https://www.sandbox.paypal.com/web-sdk/v6/core"; // sandbox only
const CLIENT_ID = process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID || "";

type Phase = "loading" | "ready" | "paying" | "capturing" | "done" | "unavailable";
type Result = { order_id: string; paypal_order_id: string; payment_state: string; seller_protection_status: string };

export function DemoShop() {
  const [product, setProduct] = useState<Product | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [sdkLoaded, setSdkLoaded] = useState(false);
  const sessionRef = useRef<PayPalOneTimeSession | null>(null);

  useEffect(() => {
    api
      .products()
      .then((p) => setProduct(p[0] ?? null))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load the product."));
  }, []);

  const capture = useCallback(async (orderId: string) => {
    setPhase("capturing");
    try {
      const r = await api.captureShopOrder(orderId);
      setResult(r);
      setPhase("done");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Payment could not be completed.");
      setPhase("ready");
    }
  }, []);

  // Initialise the v6 SDK once the script has loaded and we know the product.
  useEffect(() => {
    if (!sdkLoaded || !product) return;
    if (!CLIENT_ID) return; // shown as a config error below
    let cancelled = false;
    (async () => {
      try {
        const sdk = await window.paypal!.createInstance({
          clientId: CLIENT_ID,
          components: ["paypal-payments"],
          pageType: "checkout",
          locale: "en-US",
        });
        const methods = await sdk.findEligibleMethods({ currencyCode: product.currency, amount: product.price });
        if (cancelled) return;
        if (!methods.isEligible("paypal")) {
          setPhase("unavailable");
          setError("PayPal is not available for this browser or account.");
          return;
        }
        const session = sdk.createPayPalOneTimePaymentSession({
          onApprove: async ({ orderId }) => capture(orderId),
          onCancel: () => {
            setPhase("ready");
            setError("Payment cancelled — nothing was charged.");
          },
          onError: (err) => {
            setPhase("ready");
            setError(err?.message || "PayPal reported an error. Please try again.");
          },
        });
        sessionRef.current = session;
        if (session.hasReturned?.()) {
          await session.resume?.(); // redirect flow (mobile) returns here
        } else {
          setPhase("ready");
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not start PayPal.");
          setPhase("unavailable");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sdkLoaded, product, capture]);

  async function onPay() {
    if (!sessionRef.current || !product) return;
    setError(null);
    setPhase("paying");
    // v6: pass the *Promise* (invoked), not the function reference.
    const orderPromise = api.createShopOrder(product.sku).then((r) => ({ orderId: r.orderId }));
    try {
      await sessionRef.current.start({ presentationMode: "auto" }, orderPromise);
    } catch (e) {
      setPhase("ready");
      setError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Could not open PayPal.");
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <Script src={SDK_URL} strategy="afterInteractive" onReady={() => setSdkLoaded(true)} />

      <div className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50/70 px-4 py-3 text-[13px] text-amber-950">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
        <p>
          <span className="font-semibold">Buyer view · sandbox demo.</span> This pretend store takes fake money from the PayPal
          sandbox. Log in with a sandbox <em>buyer</em> account — its shipping address becomes the protected address on the payment.
        </p>
      </div>

      {phase === "done" && result ? (
        <section className="surface mx-auto max-w-xl p-8 text-center">
          <span className="mx-auto flex size-14 items-center justify-center rounded-full bg-emerald-50 text-emerald-600 ring-8 ring-emerald-50/50">
            <CheckCircle2 className="size-7" aria-hidden />
          </span>
          <h1 className="mt-4 text-xl font-semibold">Payment complete</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            PayPal order <span className="font-mono text-foreground">{result.paypal_order_id}</span> was captured and recorded by StayCovered.
          </p>
          <div className="mt-4 inline-flex items-center gap-2 rounded-full border bg-slate-50 px-3 py-1.5 text-sm">
            Seller Protection from PayPal <ProtectionPill status={result.seller_protection_status} />
          </div>
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            <Button size="lg" nativeButton={false} render={<Link href={`/orders/${result.order_id}`} />}>
              View in seller dashboard
            </Button>
            <Button size="lg" variant="outline" onClick={() => { setResult(null); setPhase("ready"); }}>
              Buy another
            </Button>
          </div>
        </section>
      ) : (
        <section className="surface overflow-hidden">
          <div className="grid md:grid-cols-[1.1fr_1fr]">
            <ProductArt />
            <div className="flex flex-col gap-6 p-8">
              {product ? (
                <>
                  <div className="space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-strong">BrightCounter Supply</p>
                    <h1 className="text-[28px] font-semibold leading-tight">{product.name}</h1>
                    <p className="text-sm text-muted-foreground">Ships from Edison, NJ · free US delivery</p>
                  </div>
                  <p className="text-3xl font-semibold tabular-nums">{money(product.price, product.currency)}</p>
                  <p className="text-[15px] leading-relaxed text-muted-foreground">{product.description}</p>
                  <ul className="grid gap-2.5 text-sm">
                    <Feature icon={<Sparkles />}>Card reader, receipt printer and swivel stand</Feature>
                    <Feature icon={<Truck />}>Ships in 2 business days with tracking</Feature>
                    <Feature icon={<ShieldCheck />}>Secure checkout with PayPal</Feature>
                  </ul>
                  <div className="mt-auto space-y-3 border-t pt-6">
                    {phase === "ready" || phase === "paying" ? (
                      <paypal-button
                        type="pay"
                        className="paypal-gold"
                        onClick={phase === "ready" ? onPay : undefined}
                        aria-disabled={phase !== "ready"}
                        style={{ display: "block", width: "100%", maxWidth: 420 }}
                      />
                    ) : phase === "capturing" ? (
                      <p className="flex items-center gap-2 text-sm" role="status">
                        <Loader2 className="size-4 animate-spin" aria-hidden /> Confirming payment with PayPal…
                      </p>
                    ) : phase === "loading" ? (
                      <div className="h-11 w-full max-w-[420px] animate-pulse rounded-md bg-muted" role="status" aria-label="Loading PayPal" />
                    ) : null}
                    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <Lock className="size-3.5" aria-hidden /> Payment details are handled by PayPal, never by this shop.
                    </p>
                  </div>
                </>
              ) : (
                <div className="space-y-3" role="status" aria-label="Loading product">
                  <div className="h-4 w-32 animate-pulse rounded bg-muted" />
                  <div className="h-8 w-3/4 animate-pulse rounded bg-muted" />
                  <div className="h-24 animate-pulse rounded bg-muted" />
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {!CLIENT_ID && (
        <Alert variant="destructive">
          <AlertTitle>NEXT_PUBLIC_PAYPAL_CLIENT_ID is not set in the root .env, so PayPal can&apos;t load.</AlertTitle>
        </Alert>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertTitle>{error}</AlertTitle>
        </Alert>
      )}
    </div>
  );
}

function Feature({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <li className="flex items-center gap-2.5">
      <span className="flex size-7 items-center justify-center rounded-lg bg-slate-100 text-slate-600 [&_svg]:size-4" aria-hidden>
        {icon}
      </span>
      {children}
    </li>
  );
}

/** Illustrated product image: card reader + receipt printer on a stand (original SVG art, no logos). */
function ProductArt() {
  return (
    <div className="relative flex min-h-[360px] items-center justify-center overflow-hidden bg-gradient-to-br from-[#0b1f4b] via-[#123a8a] to-[#0b65c2]">
      <div className="absolute -left-20 -top-24 size-80 rounded-full bg-[#3aa0ff]/30 blur-3xl" aria-hidden />
      <div className="absolute -bottom-24 -right-16 size-80 rounded-full bg-[#ffc439]/25 blur-3xl" aria-hidden />
      <svg viewBox="0 0 360 300" className="relative w-[86%] max-w-[420px] drop-shadow-[0_24px_40px_rgba(0,0,0,0.35)]" role="img" aria-label="Card reader and receipt printer on a stand">
        <defs>
          <linearGradient id="body" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#ffffff" />
            <stop offset="1" stopColor="#dfe6f1" />
          </linearGradient>
          <linearGradient id="screen" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#0b1f4b" />
            <stop offset="1" stopColor="#1650b8" />
          </linearGradient>
          <linearGradient id="gold" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#ffd774" />
            <stop offset="1" stopColor="#f2a900" />
          </linearGradient>
        </defs>
        {/* stand */}
        <path d="M70 262 h120 l-14 -18 h-92 z" fill="#c9d3e3" />
        <rect x="118" y="214" width="24" height="32" rx="6" fill="#aebbd0" />
        {/* card reader */}
        <rect x="78" y="40" width="104" height="182" rx="18" fill="url(#body)" stroke="#c4cfe0" strokeWidth="2" />
        <rect x="90" y="56" width="80" height="64" rx="8" fill="url(#screen)" />
        <text x="130" y="84" textAnchor="middle" fill="#ffffff" fontSize="13" fontFamily="Inter, Arial" fontWeight="700">$300.00</text>
        <text x="130" y="104" textAnchor="middle" fill="#9cc7ff" fontSize="8.5" fontFamily="Inter, Arial">Tap, insert or swipe</text>
        <path d="M122 132 q8 8 0 16 M129 128 q12 12 0 24 M136 124 q16 16 0 32" stroke="#1650b8" strokeWidth="2.6" fill="none" strokeLinecap="round" />
        {[0, 1, 2].map((r) =>
          [0, 1, 2].map((c) => <rect key={`${r}-${c}`} x={98 + c * 22} y={164 + r * 15} width="18" height="10" rx="3" fill="#e6ecf5" />),
        )}
        <rect x="104" y="226" width="52" height="6" rx="3" fill="#0b1f4b" opacity="0.15" />
        {/* card */}
        <g transform="rotate(-14 246 92)">
          <rect x="196" y="62" width="104" height="64" rx="10" fill="url(#gold)" />
          <rect x="208" y="78" width="22" height="16" rx="3" fill="#fff3c4" opacity="0.9" />
          <rect x="208" y="104" width="64" height="5" rx="2.5" fill="#7a5200" opacity="0.35" />
        </g>
        {/* receipt printer */}
        <rect x="206" y="176" width="112" height="70" rx="14" fill="url(#body)" stroke="#c4cfe0" strokeWidth="2" />
        <path d="M228 176 v-44 h68 v44" fill="#ffffff" stroke="#dbe3ef" strokeWidth="2" />
        <path d="M238 146 h48 M238 156 h36 M238 166 h44" stroke="#9fb0c8" strokeWidth="3" strokeLinecap="round" />
        <rect x="222" y="196" width="80" height="6" rx="3" fill="#0b1f4b" opacity="0.2" />
        <circle cx="300" cy="226" r="5" fill="#22c55e" />
      </svg>
      <span className="absolute left-5 top-5 rounded-full bg-white/15 px-2.5 py-1 text-xs font-medium text-white ring-1 ring-white/25 backdrop-blur">
        Starter kit · 3 devices
      </span>
    </div>
  );
}
