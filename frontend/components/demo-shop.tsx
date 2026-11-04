"use client";

/**
 * Demo buyer shop. PayPal JS SDK v6 (web-sdk/v6/core) with client ID auth.
 * Orders are created and captured by OUR backend (createOrder/onApprove call /api/shop/*);
 * the browser never calls PayPal REST and never sends an amount.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Script from "next/script";
import Link from "next/link";
import { CheckCircle2, Gem, Info, Loader2 } from "lucide-react";

import { api, ApiError, money, type Product } from "@/lib/api";
import type { PayPalOneTimeSession } from "@/types/paypal";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
    <div className="mx-auto max-w-3xl space-y-6">
      <Script src={SDK_URL} strategy="afterInteractive" onReady={() => setSdkLoaded(true)} />

      <Alert>
        <Info aria-hidden />
        <AlertTitle>Sandbox demo shop</AlertTitle>
        <AlertDescription>
          This is a pretend store that takes fake money from the PayPal sandbox. Log in with a sandbox <em>buyer</em> account.
          Your buyer account&apos;s shipping address becomes the protected address on the payment.
        </AlertDescription>
      </Alert>

      {phase === "done" && result ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400">
              <CheckCircle2 aria-hidden /> Payment complete
            </CardTitle>
            <CardDescription>
              PayPal order <span className="font-mono">{result.paypal_order_id}</span> was captured and recorded by StayCovered.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex items-center gap-2 text-sm">
            Seller Protection from PayPal: <ProtectionPill status={result.seller_protection_status} />
          </CardContent>
          <CardFooter className="gap-2">
            <Button nativeButton={false} render={<Link href={`/orders/${result.order_id}`} />}>
              View in seller dashboard
            </Button>
            <Button variant="outline" onClick={() => { setResult(null); setPhase("ready"); }}>
              Buy another
            </Button>
          </CardFooter>
        </Card>
      ) : (
        <Card>
          <div className="grid gap-0 sm:grid-cols-2">
            <div className="flex aspect-square items-center justify-center bg-gradient-to-br from-zinc-100 to-zinc-200 dark:from-zinc-800 dark:to-zinc-900 sm:aspect-auto">
              <Gem className="size-20 text-zinc-400" aria-hidden />
              <span className="sr-only">Product image placeholder</span>
            </div>
            <div className="flex flex-col gap-4 p-6">
              {product ? (
                <>
                  <div>
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Priya&apos;s Jewellery</p>
                    <h1 className="text-xl font-semibold">{product.name}</h1>
                    <p className="mt-1 text-sm text-muted-foreground">{product.description}</p>
                  </div>
                  <p className="text-2xl font-semibold">{money(product.price, product.currency)}</p>
                  <div className="mt-auto space-y-2">
                    {phase === "ready" || phase === "paying" ? (
                      <paypal-button
                        type="pay"
                        className="paypal-gold"
                        onClick={phase === "ready" ? onPay : undefined}
                        aria-disabled={phase !== "ready"}
                        style={{ display: "block", width: "100%", maxWidth: 350 }}
                      />
                    ) : phase === "capturing" ? (
                      <p className="flex items-center gap-2 text-sm" role="status">
                        <Loader2 className="size-4 animate-spin" aria-hidden /> Confirming payment with PayPal…
                      </p>
                    ) : phase === "loading" ? (
                      <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
                        <Loader2 className="size-4 animate-spin" aria-hidden /> Loading PayPal…
                      </p>
                    ) : null}
                  </div>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">Loading product…</p>
              )}
            </div>
          </div>
        </Card>
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
