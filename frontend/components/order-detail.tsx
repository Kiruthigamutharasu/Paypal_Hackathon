"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Check, Clock, FileSearch, MapPin, RefreshCw, ShieldCheck, Truck } from "lucide-react";

import { api, ApiError, money, when, type AuditEntry, type OrderDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { PaymentPill, ProtectionPill, ShipmentPill, VerdictPill, protectionText } from "@/components/status";
import { EvidencePanel } from "@/components/evidence-panel";

export function OrderDetailView() {
  const { id } = useParams<{ id: string }>();
  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getOrder(id)
      .then((o) => {
        if (cancelled) return;
        setOrder(o);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e : new ApiError("UNKNOWN", "Could not load the order.", 0));
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function refresh() {
    setRefreshing(true);
    try {
      setOrder(await api.refreshOrder(id));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError("UNKNOWN", "Refresh failed.", 0));
    } finally {
      setRefreshing(false);
    }
  }

  if (error && !order) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Couldn&apos;t load this order</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  if (!order) return <p className="text-sm text-muted-foreground">Loading order…</p>;

  const cap = order.capture;
  const addr = order.protected_address;

  return (
    <div className="space-y-6">
      <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden /> All orders
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">
            {order.item_description ?? "Order"} · {money(order.amount, order.currency)}
          </h1>
          <p className="text-sm text-muted-foreground">
            {[order.buyer_name, order.buyer_email_masked].filter(Boolean).join(" · ") || "Buyer unknown"} · paid{" "}
            {when(cap?.paypal_create_time ?? order.created_at)}
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            <PaymentPill state={order.payment_state} />
            <VerdictPill verdict={order.verdict} />
            <ShipmentPill state={order.shipment_state} />
          </div>
        </div>
        <Button variant="outline" onClick={refresh} disabled={refreshing}>
          <RefreshCw className={refreshing ? "animate-spin" : ""} aria-hidden />
          {refreshing ? "Refreshing…" : "Refresh from PayPal"}
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertTitle>{error.message}</AlertTitle>
          {typeof error.details?.paypal_debug_id === "string" && (
            <AlertDescription>PayPal debug ID: {error.details.paypal_debug_id}</AlertDescription>
          )}
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="size-4 text-emerald-600" aria-hidden /> PayPal
              </CardTitle>
              <CardDescription>Source of truth: fetched from the PayPal sandbox {when(order.last_synced_at)}.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 text-sm">
                <Field label="PayPal order ID" mono>{order.paypal_order_id}</Field>
                <Field label="Order status">{order.paypal_status ?? "—"}</Field>
                <Field label="Capture ID" mono>{cap?.paypal_capture_id ?? "Not captured yet"}</Field>
                <Field label="Capture status">
                  {cap ? `${cap.status}${cap.status_reason ? ` (${cap.status_reason})` : ""}` : "—"}
                </Field>
                <Field label="Amount">{money(cap?.amount ?? order.amount, cap?.currency ?? order.currency)}</Field>
                <Field label="Seller Protection">
                  <ProtectionPill status={cap?.seller_protection_status ?? "UNKNOWN"} />
                </Field>
              </dl>
              <p className="rounded-lg bg-muted/60 p-3 text-sm text-muted-foreground">
                {protectionText(cap?.seller_protection_status ?? "UNKNOWN")}
                {cap?.dispute_categories?.length ? (
                  <> Covered claim types: {cap.dispute_categories.map((c) => c.replaceAll("_", " ").toLowerCase()).join(", ")}.</>
                ) : null}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <MapPin className="size-4" aria-hidden /> Protected shipping address
              </CardTitle>
              <CardDescription>
                Ship only to this address — it is the address on the PayPal transaction.
              </CardDescription>
              {addr && order.address_history.length > 1 && (
                <CardAction className="text-xs text-muted-foreground">Version {addr.version}</CardAction>
              )}
            </CardHeader>
            <CardContent>
              {addr ? (
                <address className="not-italic leading-relaxed">
                  <span className="font-medium">{addr.name}</span>
                  <br />
                  {addr.line1}
                  {addr.line2 && (
                    <>
                      <br />
                      {addr.line2}
                    </>
                  )}
                  <br />
                  {[addr.city, addr.state, addr.postal_code].filter(Boolean).join(", ")}
                  <br />
                  {addr.country}
                </address>
              ) : (
                <Alert>
                  <AlertTitle>PayPal has no shipping address for this payment</AlertTitle>
                  <AlertDescription>Without one, there is no protected address to ship to (flag ADD-01).</AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>

          <EvidencePanel orderId={order.id} />

          <Card>
            <CardHeader>
              <CardTitle>Before you ship</CardTitle>
              <CardDescription>Upcoming steps for this order.</CardDescription>
            </CardHeader>
            <CardContent>
              <ol className="space-y-3 text-sm">
                <Step done={order.payment_state === "PAYMENT_COMPLETED"} icon={<Check className="size-4" />}>
                  Payment completed on PayPal
                </Step>
                <Step done={!!addr} icon={<MapPin className="size-4" />}>Protected address recorded</Step>
                <Step icon={<FileSearch className="size-4" />}>
                  Upload buyer chats and the shipping label (above)
                </Step>
                <Step icon={<ShieldCheck className="size-4" />} soon>
                  Shipping verdict from the rule engine
                </Step>
                <Step icon={<Truck className="size-4" />} soon>
                  Register tracking with PayPal
                </Step>
              </ol>
            </CardContent>
          </Card>
        </div>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Clock className="size-4" aria-hidden /> Timeline
            </CardTitle>
            <CardDescription>Every check and PayPal sync, newest first.</CardDescription>
          </CardHeader>
          <CardContent>
            <Timeline entries={order.timeline} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Field({ label, children, mono }: { label: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={mono ? "font-mono text-[13px] break-all" : ""}>{children}</dd>
    </div>
  );
}

function Step({ done, soon, icon, children }: { done?: boolean; soon?: boolean; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <li className="flex items-center gap-3">
      <span
        className={
          "flex size-7 items-center justify-center rounded-full ring-1 " +
          (done ? "bg-emerald-50 text-emerald-700 ring-emerald-600/30 dark:bg-emerald-950 dark:text-emerald-300" : "bg-muted text-muted-foreground ring-border")
        }
        aria-hidden
      >
        {icon}
      </span>
      <span className={done ? "" : "text-muted-foreground"}>
        {children}
        <span className="sr-only">{done ? " — done" : " — not done"}</span>
      </span>
      {soon && <span className="ml-auto text-xs text-muted-foreground">Coming next</span>}
    </li>
  );
}

const ACTION_LABELS: Record<string, string> = {
  ORDER_CREATED: "Order recorded from PayPal",
  CAPTURE_SYNCED: "Payment capture synced",
  PROTECTED_ADDRESS_RECORDED: "Protected address recorded",
  PAYMENT_STATE_CHANGED: "Payment state changed",
  REFRESH_REQUESTED: "Seller refreshed from PayPal",
  WEBHOOK_PROCESSED: "PayPal notification processed",
  WEBHOOK_FAILED: "PayPal notification failed",
  EVIDENCE_UPLOADED: "Evidence uploaded",
  AI_EXTRACTION_COMPLETED: "AI read the evidence",
  AI_EXTRACTION_FAILED: "AI check failed",
};

function describe(e: AuditEntry): string | null {
  const d = (e.details ?? {}) as Record<string, unknown>;
  switch (e.action) {
    case "PAYMENT_STATE_CHANGED":
      return `${d.from} → ${d.to}`;
    case "CAPTURE_SYNCED":
      return `${d.status} · Seller Protection ${d.seller_protection}`;
    case "PROTECTED_ADDRESS_RECORDED":
      return `v${d.version} · ${[d.city, d.state].filter(Boolean).join(", ")}`;
    case "WEBHOOK_PROCESSED":
      return String(d.event_type ?? "");
    case "ORDER_CREATED":
      return String(d.source ?? "");
    case "EVIDENCE_UPLOADED":
      return `${d.count} × ${String(d.kind).replace("_", " ").toLowerCase()}`;
    case "AI_EXTRACTION_COMPLETED":
    case "AI_EXTRACTION_FAILED": {
      const agent = d.agent === "label_reader" ? "Label" : d.agent === "conversation_analyst" ? "Chat" : "";
      const found = Array.isArray(d.requests) && d.requests.length ? ` · found ${(d.requests as string[]).join(", ")}` : "";
      return `${agent} ${String(d.status ?? "").toLowerCase()}${found}`.trim();
    }
    default:
      return null;
  }
}

function Timeline({ entries }: { entries: AuditEntry[] }) {
  if (!entries.length) return <p className="text-sm text-muted-foreground">No events yet.</p>;
  return (
    <ol className="space-y-4">
      {entries.map((e, i) => (
        <li key={e.id}>
          {i > 0 && <Separator className="mb-4" />}
          <p className="text-sm font-medium">{ACTION_LABELS[e.action] ?? e.action.replaceAll("_", " ").toLowerCase()}</p>
          {describe(e) && <p className="text-sm text-muted-foreground">{describe(e)}</p>}
          <p className="text-xs text-muted-foreground">
            {when(e.created_at)} · {e.actor.toLowerCase()}
          </p>
        </li>
      ))}
    </ol>
  );
}
