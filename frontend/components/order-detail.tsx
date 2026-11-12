"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Check,
  Copy,
  CreditCard,
  FileSearch,
  Package,
  History,
  MapPin,
  RefreshCw,
  ShieldCheck,
  Truck,
} from "lucide-react";

import { api, ApiError, money, when, type AuditEntry, type OrderDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { SectionTitle } from "@/components/brand";
import { PaymentPill, ProtectionPill, ShipmentPill, VerdictPill, protectionText } from "@/components/status";
import { EvidencePanel } from "@/components/evidence-panel";
import { RiskReport } from "@/components/risk-report";
import { FixPanel } from "@/components/fix-panel";
import { ShipmentPanel } from "@/components/shipment-panel";
import type { DecisionOut } from "@/lib/api";
import { cn } from "@/lib/utils";

export function OrderDetailView() {
  const { id } = useParams<{ id: string }>();
  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [evidenceVersion, setEvidenceVersion] = useState(0);
  const [decision, setDecision] = useState<DecisionOut | null>(null);
  // A new verdict (e.g. GREEN after the new label is read) also refreshes the order summary, checklist and
  // activity, so the seller never has to re-check or reload by hand.
  const lastDecisionId = useRef<string | null>(null);
  const onDecision = useCallback((d: DecisionOut) => {
    setDecision(d);
    if (lastDecisionId.current !== null && lastDecisionId.current !== d.id) api.getOrder(id).then(setOrder).catch(() => {});
    lastDecisionId.current = d.id;
  }, [id]);
  const onEvidenceChange = useCallback(() => {
    setEvidenceVersion((n) => n + 1);
    api.getOrder(id).then(setOrder).catch(() => {});
  }, [id]);
  const [showFix, setShowFix] = useState(false);
  const reloadOrder = useCallback(() => {
    api.getOrder(id).then(setOrder).catch(() => {});
    setEvidenceVersion((n) => n + 1);
  }, [id]);

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
  if (!order) return <DetailSkeleton />;

  const cap = order.capture;
  const addr = order.protected_address;
  const paid = order.payment_state === "PAYMENT_COMPLETED";

  return (
    <div className="space-y-6">
      <Link href="/" className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-100/90 hover:text-white">
        <ArrowLeft className="size-4" aria-hidden /> All orders
      </Link>

      {/* Summary hero */}
      <section className="surface overflow-hidden">
        <div className="flex flex-wrap items-center gap-5 p-6">
          <span className="flex size-16 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-50 to-blue-100 text-blue-700" aria-hidden>
            <Package className="size-7" />
          </span>
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-[22px] font-semibold leading-tight">{order.item_description ?? "Order"}</h1>
              <PaymentPill state={order.payment_state} />
            </div>
            <p className="text-sm text-muted-foreground">
              {order.buyer_name ?? "Unknown buyer"}
              {order.buyer_email_masked && <> · {order.buyer_email_masked}</>} · paid {when(cap?.paypal_create_time ?? order.created_at)}
            </p>
          </div>
          <div className="text-right">
            <p className="text-[28px] font-semibold leading-none tabular-nums">{money(order.amount, order.currency)}</p>
            <p className="mt-1 text-xs text-muted-foreground">{order.currency ?? "USD"} · PayPal</p>
          </div>
        </div>
        <div className="grid divide-y border-t bg-slate-50/60 sm:grid-cols-4 sm:divide-x sm:divide-y-0">
          <HeroStat label="Seller Protection"><ProtectionPill status={cap?.seller_protection_status ?? "UNKNOWN"} /></HeroStat>
          <HeroStat label="Shipping verdict"><VerdictPill verdict={decision?.verdict ?? order.verdict} /></HeroStat>
          <HeroStat label="Shipment"><ShipmentPill state={order.shipment_state} /></HeroStat>
          <HeroStat label="Ship to">
            <span className="text-sm font-medium">{order.ship_to ?? "—"}</span>
          </HeroStat>
        </div>
      </section>

      {error && (
        <Alert variant="destructive">
          <AlertTitle>{error.message}</AlertTitle>
          {typeof error.details?.paypal_debug_id === "string" && (
            <AlertDescription>PayPal debug ID: {error.details.paypal_debug_id}</AlertDescription>
          )}
        </Alert>
      )}

      <RiskReport
        orderId={order.id}
        refreshKey={evidenceVersion + (refreshing ? 0 : 1)}
        onDecision={onDecision}
        onFix={() => {
          setShowFix(true);
          setTimeout(() => document.getElementById("fix")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
        }}
      />

      <FixPanel
        orderId={order.id}
        amount={order.amount}
        currency={order.currency}
        protectedCity={addr ? `${addr.city}, ${addr.state}` : null}
        open={showFix}
        onChanged={reloadOrder}
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <div className="grid gap-6 md:grid-cols-2">
            {/* Protected address */}
            <section className="surface p-5">
              <SectionTitle icon={<MapPin />} tone="emerald" sub="The address on the PayPal transaction — ship only here.">
                Protected address
              </SectionTitle>
              <div className="mt-4">
                {addr ? (
                  <address className="rounded-xl border border-emerald-200/70 bg-emerald-50/40 p-4 not-italic leading-relaxed">
                    <span className="font-semibold">{addr.name}</span>
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
                    <span className="text-muted-foreground">{addr.country}</span>
                    {order.address_history.length > 1 && (
                      <span className="mt-2 block text-xs text-muted-foreground">Version {addr.version} (updated by PayPal)</span>
                    )}
                  </address>
                ) : (
                  <Alert>
                    <AlertTitle>PayPal has no shipping address for this payment</AlertTitle>
                    <AlertDescription>There is no protected address to ship to (ADD-01).</AlertDescription>
                  </Alert>
                )}
              </div>
            </section>

            {/* PayPal facts */}
            <section className="surface p-5">
              <div className="flex items-start justify-between gap-2">
                <SectionTitle icon={<CreditCard />} tone="sky" sub={`Synced ${when(order.last_synced_at)}`}>
                  PayPal payment
                </SectionTitle>
                <Button variant="ghost" size="sm" onClick={refresh} disabled={refreshing} aria-label="Refresh from PayPal">
                  <RefreshCw className={refreshing ? "animate-spin" : ""} aria-hidden />
                  <span className="hidden sm:inline">{refreshing ? "Syncing" : "Refresh"}</span>
                </Button>
              </div>
              <dl className="mt-4 space-y-2.5 text-sm">
                <Fact label="Order ID" mono copy={order.paypal_order_id}>{order.paypal_order_id}</Fact>
                <Fact label="Capture ID" mono copy={cap?.paypal_capture_id}>{cap?.paypal_capture_id ?? "Not captured"}</Fact>
                <Fact label="Capture status">
                  {cap ? `${cap.status}${cap.status_reason ? ` · ${cap.status_reason}` : ""}` : "—"}
                </Fact>
                <Fact label="Amount">{money(cap?.amount ?? order.amount, cap?.currency ?? order.currency)}</Fact>
              </dl>
              <p className="mt-4 rounded-xl bg-slate-50 p-3 text-[13px] leading-relaxed text-muted-foreground">
                {protectionText(cap?.seller_protection_status ?? "UNKNOWN")}
                {cap?.dispute_categories?.length ? (
                  <> Covers: {cap.dispute_categories.map((c) => c.replaceAll("_", " ").toLowerCase()).join(", ")}.</>
                ) : null}
              </p>
            </section>
          </div>

          <EvidencePanel orderId={order.id} onChange={onEvidenceChange} />

          <ShipmentPanel orderId={order.id} decision={decision} onChanged={reloadOrder} />
        </div>

        <aside className="space-y-6">
          <section className="surface p-5">
            <SectionTitle icon={<ShieldCheck />} tone="emerald" sub="What has to be true before you ship.">
              Ship-safe checklist
            </SectionTitle>
            <ol className="mt-4 space-y-1">
              <Step done={paid}>Payment completed on PayPal</Step>
              <Step done={!!addr}>Protected address recorded</Step>
              <Step done={!!decision && decision.checks.some((c) => c.key === "label" && c.status === "pass")} icon={<FileSearch />}>Label checked by AI</Step>
              <Step done={!!decision?.can_ship} icon={<ShieldCheck />}>Verdict allows shipping</Step>
              <Step done={["SHIPPED", "DELIVERED"].includes(order.shipment_state)} icon={<Truck />}>Tracking registered with PayPal</Step>
            </ol>
          </section>

          <section className="surface p-5">
            <SectionTitle icon={<History />} tone="slate" sub="Every check and PayPal sync.">
              Activity
            </SectionTitle>
            <div className="mt-4">
              <Timeline entries={order.timeline} />
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

function HeroStat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5 px-6 py-3.5">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
      <div>{children}</div>
    </div>
  );
}

function Fact({ label, children, mono, copy }: { label: string; children: React.ReactNode; mono?: boolean; copy?: string | null }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className={cn("flex min-w-0 items-center gap-1.5 text-right", mono && "font-mono text-[12.5px]")}>
        <span className="truncate">{children}</span>
        {copy && (
          <button
            type="button"
            onClick={() => {
              navigator.clipboard?.writeText(copy);
              setCopied(true);
              setTimeout(() => setCopied(false), 1200);
            }}
            className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label={`Copy ${label}`}
          >
            {copied ? <Check className="size-3.5 text-emerald-600" /> : <Copy className="size-3.5" />}
          </button>
        )}
      </dd>
    </div>
  );
}

function Step({ done, soon, icon, children }: { done?: boolean; soon?: boolean; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <li className="flex items-center gap-3 rounded-lg px-2 py-2">
      <span
        className={cn(
          "flex size-6 shrink-0 items-center justify-center rounded-full [&_svg]:size-3.5",
          done ? "bg-emerald-500 text-white" : "bg-slate-100 text-slate-500",
        )}
        aria-hidden
      >
        {done ? <Check strokeWidth={3} /> : icon ?? <span className="size-1.5 rounded-full bg-slate-400" />}
      </span>
      <span className={cn("text-sm", done ? "font-medium" : "text-muted-foreground")}>
        {children}
        <span className="sr-only">{done ? " — done" : " — not done"}</span>
      </span>
      {soon && <span className="ml-auto rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">Soon</span>}
    </li>
  );
}

const ACTION_LABELS: Record<string, string> = {
  ORDER_CREATED: "Order recorded from PayPal",
  CAPTURE_SYNCED: "Payment capture synced",
  PROTECTED_ADDRESS_RECORDED: "Protected address recorded",
  PAYMENT_STATE_CHANGED: "Payment state changed",
  REFRESH_REQUESTED: "Refreshed from PayPal",
  WEBHOOK_PROCESSED: "PayPal notification processed",
  WEBHOOK_FAILED: "PayPal notification failed",
  EVIDENCE_UPLOADED: "Evidence uploaded",
  AI_EXTRACTION_COMPLETED: "AI read the evidence",
  AI_EXTRACTION_FAILED: "AI check failed",
  DECISION_MADE: "Verdict updated",
  DECISION_ACKNOWLEDGED: "Review acknowledged by seller",
  DECISION_OVERRIDDEN: "Blocked shipment overridden",
  REMEDIATION_STARTED: "Fix started",
  REPAY_CONFIRMED: "Re-pay confirmed by seller",
  REPAY_REFUNDED: "Original payment refunded",
  REPAY_REFUND_FAILED: "Refund failed",
  REPAY_ORDER_CREATED: "New PayPal payment created",
  REPAY_ORDER_FAILED: "New payment could not be created",
  REPAY_PAID: "Buyer paid the new payment",
  TRACKING_REGISTERED: "Tracking registered with PayPal",
  TRACKING_FAILED: "Tracking registration failed",
  SHIPMENT_STATUS_CHANGED: "Shipment status changed",
  DISPUTE_OPENED: "Dispute opened by buyer",
  DISPUTE_UPDATED: "Dispute updated",
  EVIDENCE_PLANNED: "Dispute evidence prepared",
  EVIDENCE_NOTE_EDITED: "Dispute note edited",
  EVIDENCE_SUBMITTED: "Evidence submitted to PayPal",
  EVIDENCE_SUBMIT_FAILED: "Evidence submission failed",
};

const REQ_HUMAN: Record<string, string> = {
  ADDRESS_CHANGE: "address change",
  PICKUP_OR_COURIER: "pickup request",
  OFF_PLATFORM_PAYMENT: "off-PayPal payment",
  NAME_CHANGE: "name change",
  OTHER_RISK: "risk signal",
};

const ACTOR_DOT: Record<string, string> = {
  PAYPAL: "bg-sky-500",
  AI: "bg-violet-500",
  SELLER: "bg-slate-800",
  SYSTEM: "bg-slate-400",
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
    case "DECISION_MADE": {
      const flags = Array.isArray(d.flags) && d.flags.length ? ` · ${(d.flags as string[]).join(", ")}` : "";
      return `${String(d.verdict ?? "")}${flags}`;
    }
    case "DECISION_OVERRIDDEN":
      return `“${String(d.reason ?? "")}”`;
    case "REPAY_REFUNDED":
      return `refund ${String(d.refund_id ?? "")}`;
    case "REPAY_ORDER_CREATED":
      return `ships to ${String(d.city ?? "")}, ${String(d.state ?? "")}`;
    case "TRACKING_REGISTERED":
      return `${String(d.carrier ?? "")} ${String(d.tracking_number ?? "")}`;
    case "DISPUTE_OPENED":
      return String(d.reason ?? "").replaceAll("_", " ").toLowerCase();
    case "EVIDENCE_UPLOADED":
      return `${d.count} × ${String(d.kind).replace("_", " ").toLowerCase()}`;
    case "AI_EXTRACTION_COMPLETED":
    case "AI_EXTRACTION_FAILED": {
      const agent = d.agent === "label_reader" ? "Label" : d.agent === "conversation_analyst" ? "Chat" : "Evidence";
      const status = { SUCCEEDED: "read", EXTRACTION_FAILED: "couldn't be read", PROVIDER_UNAVAILABLE: "AI unavailable — retry" }[String(d.status)] ?? "";
      const reqs = Array.isArray(d.requests) ? (d.requests as string[]).filter((r) => !r.endsWith("/CANCELLED")) : [];
      const counts = new Map<string, number>();
      reqs.forEach((r) => {
        const t = REQ_HUMAN[r.split("/")[0]] ?? "risk";
        counts.set(t, (counts.get(t) ?? 0) + 1);
      });
      const found = counts.size ? ` · found ${[...counts].map(([t, n]) => `${n} ${t}`).join(", ")}` : d.status === "SUCCEEDED" && d.agent === "conversation_analyst" ? " · nothing risky" : "";
      return `${agent} ${status}${found}`;
    }
    default:
      return null;
  }
}

function Timeline({ entries }: { entries: AuditEntry[] }) {
  if (!entries.length) return <p className="text-sm text-muted-foreground">No activity yet.</p>;
  return (
    <ol className="relative space-y-4 before:absolute before:bottom-1 before:left-[5px] before:top-1 before:w-px before:bg-border">
      {entries.slice(0, 25).map((e) => (
        <li key={e.id} className="relative pl-6">
          <span className={cn("absolute left-0 top-1.5 size-[11px] rounded-full ring-4 ring-white", ACTOR_DOT[e.actor] ?? "bg-slate-400")} aria-hidden />
          <p className="text-sm font-medium leading-snug">{ACTION_LABELS[e.action] ?? e.action.replaceAll("_", " ").toLowerCase()}</p>
          {describe(e) && <p className="text-[13px] text-muted-foreground">{describe(e)}</p>}
          <p className="text-[11px] text-muted-foreground">
            {when(e.created_at)} · {e.actor.toLowerCase()}
          </p>
        </li>
      ))}
    </ol>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading order">
      <div className="h-5 w-24 animate-pulse rounded bg-muted" />
      <div className="h-40 animate-pulse rounded-2xl bg-muted" />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="h-72 animate-pulse rounded-2xl bg-muted lg:col-span-2" />
        <div className="h-72 animate-pulse rounded-2xl bg-muted" />
      </div>
    </div>
  );
}
