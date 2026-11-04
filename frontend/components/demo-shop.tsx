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
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-strong">Priya&apos;s Jewellery</p>
                    <h1 className="text-[28px] font-semibold leading-tight">{product.name}</h1>
                    <p className="text-sm text-muted-foreground">Ships from Edison, NJ · US delivery</p>
                  </div>
                  <p className="text-3xl font-semibold tabular-nums">{money(product.price, product.currency)}</p>
                  <p className="text-[15px] leading-relaxed text-muted-foreground">{product.description}</p>
                  <ul className="grid gap-2.5 text-sm">
                    <Feature icon={<Sparkles />}>Handmade in small batches · 925 sterling silver</Feature>
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

/** Illustrated product image (original SVG art, no stock photos). */
function ProductArt() {
  return (
    <div className="relative flex min-h-[340px] items-center justify-center overflow-hidden bg-gradient-to-br from-[#eef2f7] via-[#f6f1ea] to-[#e9eef5]">
      <div className="absolute -left-16 -top-16 size-64 rounded-full bg-white/60 blur-2xl" aria-hidden />
      <div className="absolute -bottom-20 -right-10 size-72 rounded-full bg-amber-100/50 blur-3xl" aria-hidden />
      <svg viewBox="0 0 320 320" className="relative w-[78%] max-w-[360px] drop-shadow-[0_18px_30px_rgba(30,34,53,0.18)]" role="img" aria-label="Handmade silver necklace with a teardrop pendant">
        <defs>
          <linearGradient id="silver" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#f8fafc" />
            <stop offset="0.45" stopColor="#c7ced8" />
            <stop offset="1" stopColor="#8a94a3" />
          </linearGradient>
          <radialGradient id="stone" cx="0.35" cy="0.3" r="0.8">
            <stop offset="0" stopColor="#d1fae5" />
            <stop offset="0.5" stopColor="#34d399" />
            <stop offset="1" stopColor="#047857" />
          </radialGradient>
        </defs>
        <path d="M40 40 C 60 170, 260 170, 280 40" fill="none" stroke="url(#silver)" strokeWidth="3.2" strokeDasharray="1 5.5" strokeLinecap="round" />
        <path d="M40 40 C 60 170, 260 170, 280 40" fill="none" stroke="#aab3bf" strokeWidth="1" opacity="0.6" />
        <circle cx="160" cy="139" r="7" fill="none" stroke="url(#silver)" strokeWidth="3" />
        <path d="M160 150 C 135 185, 132 215, 160 240 C 188 215, 185 185, 160 150 Z" fill="url(#silver)" />
        <path d="M160 166 C 145 190, 144 210, 160 226 C 176 210, 175 190, 160 166 Z" fill="url(#stone)" />
        <path d="M153 186 C 151 196, 152 205, 156 212" stroke="#ecfdf5" strokeWidth="2.5" strokeLinecap="round" fill="none" opacity="0.8" />
      </svg>
      <span className="absolute left-5 top-5 rounded-full bg-white/80 px-2.5 py-1 text-xs font-medium text-slate-700 shadow-xs backdrop-blur">
        Handmade
      </span>
    </div>
  );
}
