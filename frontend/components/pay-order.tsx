"use client";

/**
 * Buyer pays an EXISTING PayPal order (Safe re-pay). PayPal JS SDK v6: the session starts with a promise that
 * resolves to the existing order ID; capture happens on our server. Also handles PayPal's redirect back
 * (/pay/return?token=ORDER_ID) when the buyer used the approve link directly.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Script from "next/script";
import { useParams, useSearchParams } from "next/navigation";
import { CheckCircle2, Info, Loader2, MapPin } from "lucide-react";

import { api, ApiError, money, type PayInfo } from "@/lib/api";
import type { PayPalOneTimeSession } from "@/types/paypal";

const SDK_URL = "https://www.sandbox.paypal.com/web-sdk/v6/core";
const CLIENT_ID = process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID || "";

export function PayOrder() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const orderId = params.id === "return" ? search.get("token") ?? "" : params.id;
  const [info, setInfo] = useState<PayInfo | null>(null);
  const [phase, setPhase] = useState<"loading" | "ready" | "paying" | "capturing" | "done">("loading");
  const [err, setErr] = useState<string | null>(null);
  const [sdkLoaded, setSdkLoaded] = useState(false);
  const session = useRef<PayPalOneTimeSession | null>(null);

  const capture = useCallback(async () => {
    setPhase("capturing");
    try {
      await api.captureShopOrder(orderId);
      setPhase("done");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Payment could not be completed.");
      setPhase("ready");
    }
  }, [orderId]);

  useEffect(() => {
    if (!orderId) return;
    let cancelled = false;
    api.payInfo(orderId).then((i) => {
      if (cancelled) return;
      setInfo(i);
      if (i.paid) setPhase("done");
      else if (params.id === "return" && search.get("status") !== "cancel") capture(); // back from PayPal's approve page
    }).catch((e) => !cancelled && setErr(e instanceof ApiError ? e.message : "This payment link is not valid."));
    return () => {
      cancelled = true;
    };
  }, [orderId, params.id, search, capture]);

  useEffect(() => {
    if (!sdkLoaded || !info || info.paid || !CLIENT_ID) return;
    let cancelled = false;
    (async () => {
      try {
        const sdk = await window.paypal!.createInstance({ clientId: CLIENT_ID, components: ["paypal-payments"], pageType: "checkout" });
        if (cancelled) return;
        session.current = sdk.createPayPalOneTimePaymentSession({
          onApprove: async () => capture(),
          onCancel: () => { setPhase("ready"); setErr("Payment cancelled — nothing was charged."); },
          onError: (e) => { setPhase("ready"); setErr(e?.message || "PayPal reported an error."); },
        });
        setPhase((p) => (p === "loading" ? "ready" : p));
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Could not start PayPal.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sdkLoaded, info, capture]);

  async function pay() {
    if (!session.current) return;
    setErr(null);
    setPhase("paying");
    try {
      await session.current.start({ presentationMode: "auto" }, Promise.resolve({ orderId }));
    } catch (e) {
      setPhase("ready");
      setErr(e instanceof Error ? e.message : "Could not open PayPal.");
    }
  }

  return (
    <div className="mx-auto max-w-lg space-y-5">
      <Script src={SDK_URL} strategy="afterInteractive" onReady={() => setSdkLoaded(true)} />
      <div className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50/70 px-4 py-3 text-[13px] text-amber-950">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
        <p><span className="font-semibold">Buyer view · sandbox.</span> Your seller refunded your first payment so they can ship to your new address. Pay this new PayPal payment to continue.</p>
      </div>

      <section className="surface p-7">
        {phase === "done" ? (
          <div className="text-center">
            <span className="mx-auto flex size-14 items-center justify-center rounded-full bg-emerald-50 text-emerald-600"><CheckCircle2 className="size-7" /></span>
            <h1 className="mt-4 text-xl font-semibold">Paid — thank you!</h1>
            <p className="mt-1 text-sm text-muted-foreground">The seller will ship to your new address with tracking.</p>
          </div>
        ) : info ? (
          <div className="space-y-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-strong">BrightCounter Supply</p>
              <h1 className="text-2xl font-semibold">{info.item}</h1>
              <p className="mt-1 text-3xl font-semibold tabular-nums">{money(info.amount, info.currency)}</p>
            </div>
            <p className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50/50 p-3 text-sm">
              <MapPin className="size-4 text-emerald-700" aria-hidden />
              Ships to <span className="font-semibold">{info.ship_to.name} · {info.ship_to.city}, {info.ship_to.state}</span>
            </p>
            {phase === "capturing" ? (
              <p className="flex items-center gap-2 text-sm" role="status"><Loader2 className="size-4 animate-spin" /> Confirming payment with PayPal…</p>
            ) : phase === "loading" ? (
              <div className="h-11 animate-pulse rounded-md bg-muted" role="status" aria-label="Loading PayPal" />
            ) : (
              <paypal-button type="pay" className="paypal-gold" onClick={phase === "ready" ? pay : undefined}
                style={{ display: "block", width: "100%" }} />
            )}
          </div>
        ) : !err ? (
          <div className="h-40 animate-pulse rounded-xl bg-muted" />
        ) : null}
        {err && <p role="alert" className="mt-3 text-sm text-destructive">{err}</p>}
      </section>
    </div>
  );
}
