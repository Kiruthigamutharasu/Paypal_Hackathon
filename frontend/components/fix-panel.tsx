"use client";

/** Safe fix (F4): ship to the PayPal address, or Safe re-pay (refund + new PayPal payment at the new address). */
import { useEffect, useState } from "react";
import { Check, Copy, CreditCard, ExternalLink, Loader2, MapPin, RotateCcw, Undo2, Wrench } from "lucide-react";

import { api, ApiError, money, type AddressIn, type RemediationOut } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { SectionTitle } from "@/components/brand";
import { Pill } from "@/components/status";
import { cn } from "@/lib/utils";

const STATUS: Record<string, [Parameters<typeof Pill>[0]["tone"], string]> = {
  DRAFTED: ["blue", "Message ready"],
  PENDING_CONFIRMATION: ["amber", "Waiting for your confirmation"],
  REFUND_FAILED: ["red", "Refund failed"],
  REFUNDED_AWAITING_NEW_ORDER: ["amber", "Refunded — new payment not created"],
  AWAITING_BUYER_PAYMENT: ["violet", "Waiting for buyer to pay"],
  COMPLETED: ["green", "Buyer paid — new address protected"],
  CANCELLED: ["grey", "Cancelled"],
};

const EMPTY: AddressIn = { name: "", line1: "", line2: "", city: "", state: "", postal_code: "", country: "US" };

export function FixPanel({ orderId, amount, currency, protectedCity, open, onChanged }: {
  orderId: string;
  amount: string | null;
  currency: string | null;
  protectedCity: string | null;
  open: boolean;
  onChanged: () => void;
}) {
  const [rems, setRems] = useState<RemediationOut[] | null>(null);
  const [suggested, setSuggested] = useState<AddressIn | null>(null);
  const [mode, setMode] = useState<"choose" | "repay">("choose");
  const [addr, setAddr] = useState<AddressIn>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmFor, setConfirmFor] = useState<RemediationOut | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api.remediations(orderId).then((r) => {
      if (cancelled) return;
      setRems(r.remediations);
      setSuggested(r.suggested_address);
    }).catch(() => !cancelled && setRems([]));
    return () => {
      cancelled = true;
    };
  }, [orderId, tick]);

  const latest = rems?.[0];
  // while waiting for the buyer, poll so "paid" appears by itself
  useEffect(() => {
    if (latest?.status !== "AWAITING_BUYER_PAYMENT") return;
    const t = setTimeout(() => setTick((n) => n + 1), 5000);
    return () => clearTimeout(t);
  }, [latest, tick]);
  useEffect(() => {
    if (latest?.status === "COMPLETED") onChanged();
  }, [latest?.status, onChanged]);

  if (!open && !latest) return null;

  async function start(type: "SHIP_TO_PROTECTED" | "REPAY") {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.startRemediation(orderId, type, type === "REPAY" ? addr : undefined);
      setRems((x) => [r, ...(x ?? []).filter((y) => y.id !== r.id)]);
      if (r.status === "PENDING_CONFIRMATION") setConfirmFor(r);
      setMode("choose");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not start the fix.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="surface p-5" id="fix" aria-label="Fix this safely">
      <SectionTitle icon={<Wrench />} tone="emerald" sub="Resolve the problem the PayPal-native way, so the parcel goes to an address on a PayPal payment.">
        Fix this safely
      </SectionTitle>

      {latest && latest.status !== "CANCELLED" ? (
        <RemediationCard r={latest} amount={amount} currency={currency} onConfirm={() => setConfirmFor(latest)}
          onRetry={async () => {
            try {
              const r = await api.retryRemediation(latest.id);
              setRems((x) => [r, ...(x ?? []).slice(1)]);
            } catch (e) {
              setErr(e instanceof ApiError ? e.message : "Retry failed.");
            }
          }} />
      ) : mode === "choose" ? (
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <button type="button" onClick={() => start("SHIP_TO_PROTECTED")} disabled={busy}
            className="group rounded-xl border p-4 text-left transition hover:border-emerald-300 hover:bg-emerald-50/40 focus-visible:outline-2 focus-visible:outline-ring">
            <span className="icon-tile size-8 bg-emerald-50 text-emerald-700 [&_svg]:size-4"><MapPin /></span>
            <p className="mt-3 text-sm font-semibold">Ship to the PayPal address</p>
            <p className="mt-1 text-[13px] text-muted-foreground">
              Keep the sale, ship to {protectedCity ?? "the PayPal address"}. We draft a polite message explaining why. No money moves.
            </p>
            <p className="mt-2 text-xs font-medium text-emerald-700">Recommended · fastest</p>
          </button>
          <button type="button" disabled={busy} onClick={() => {
              const fill = (s: AddressIn | null) => setAddr(s ? { ...EMPTY, ...s, name: s.name ?? "" } : EMPTY);
              fill(suggested);
              setMode("repay");
              // the chat may have been read after this panel loaded: fetch the latest suggestion
              api.remediations(orderId).then((r) => { setSuggested(r.suggested_address); fill(r.suggested_address); }).catch(() => {});
            }}
            className="group rounded-xl border p-4 text-left transition hover:border-violet-300 hover:bg-violet-50/40 focus-visible:outline-2 focus-visible:outline-ring">
            <span className="icon-tile size-8 bg-violet-50 text-violet-700 [&_svg]:size-4"><CreditCard /></span>
            <p className="mt-3 text-sm font-semibold">Safe re-pay to the new address</p>
            <p className="mt-1 text-[13px] text-muted-foreground">
              Refund this payment and send the buyer a new PayPal payment with their requested address — so the new address is protected.
            </p>
            <p className="mt-2 text-xs font-medium text-violet-700">Moves money · needs your confirmation</p>
          </button>
        </div>
      ) : (
        <form className="mt-4 space-y-3" onSubmit={(e) => { e.preventDefault(); start("REPAY"); }}>
          <p className="text-sm font-medium">New shipping address {suggested && <span className="text-xs font-normal text-muted-foreground">(pre-filled from the buyer&apos;s chat — check it)</span>}</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Recipient name" v={addr.name} on={(v) => setAddr({ ...addr, name: v })} required />
            <Field label="Street address" v={addr.line1} on={(v) => setAddr({ ...addr, line1: v })} required />
            <Field label="Apt / unit (optional)" v={addr.line2} on={(v) => setAddr({ ...addr, line2: v })} />
            <Field label="City" v={addr.city} on={(v) => setAddr({ ...addr, city: v })} required />
            <Field label="State (2 letters)" v={addr.state} on={(v) => setAddr({ ...addr, state: v.toUpperCase().slice(0, 2) })} required />
            <Field label="ZIP code" v={addr.postal_code} on={(v) => setAddr({ ...addr, postal_code: v })} required />
          </div>
          <div className="flex gap-2">
            <Button type="submit" disabled={busy}>{busy && <Loader2 className="animate-spin" />} Review re-pay</Button>
            <Button type="button" variant="ghost" onClick={() => setMode("choose")}>Back</Button>
          </div>
        </form>
      )}
      {err && <p role="alert" className="mt-3 text-sm text-destructive">{err}</p>}

      <ConfirmRepayDialog r={confirmFor} amount={amount} currency={currency} onClose={() => setConfirmFor(null)}
        onDone={(r) => { setRems((x) => [r, ...(x ?? []).filter((y) => y.id !== r.id)]); setConfirmFor(null); onChanged(); }} />
    </section>
  );
}

function Field({ label, v, on, required }: { label: string; v: string | null; on: (v: string) => void; required?: boolean }) {
  const id = `f-${label.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <label htmlFor={id} className="block text-xs text-muted-foreground">
      {label}
      <input id={id} value={v ?? ""} onChange={(e) => on(e.target.value)} required={required}
        className="mt-1 h-9 w-full rounded-lg border bg-white px-2.5 text-sm text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/40" />
    </label>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button variant="outline" size="sm" onClick={() => { navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }}>
      {done ? <Check className="text-emerald-600" /> : <Copy />} {done ? "Copied" : label}
    </Button>
  );
}

function RemediationCard({ r, amount, currency, onConfirm, onRetry }: {
  r: RemediationOut; amount: string | null; currency: string | null; onConfirm: () => void; onRetry: () => void;
}) {
  const [tone, label] = STATUS[r.status] ?? ["grey", r.status];
  const payLink = r.pay_page_path ? `${typeof window !== "undefined" ? window.location.origin : ""}${r.pay_page_path}` : null;
  const a = r.requested_address;
  return (
    <div className="mt-4 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone={tone}>{label}</Pill>
        <span className="text-xs text-muted-foreground">{r.type === "REPAY" ? "Safe re-pay" : "Ship to the PayPal address"}</span>
      </div>

      {r.type === "REPAY" && (
        <ol className="grid gap-2 text-sm sm:grid-cols-3">
          <Stage done={!!r.refund_id} label="Original payment refunded" detail={r.refund_id ? `${money(r.refund_amount, currency)} · ${r.refund_id}` : money(r.refund_amount ?? amount, currency)} />
          <Stage done={!!r.new_paypal_order_id} label="New PayPal payment created" detail={a ? `Ships to ${a.city}, ${a.state}` : ""} />
          <Stage done={r.status === "COMPLETED"} label="Buyer paid" detail={r.status === "COMPLETED" ? "New protected address recorded" : "Waiting…"} />
        </ol>
      )}

      {r.status === "PENDING_CONFIRMATION" && <Button onClick={onConfirm}>Review and confirm</Button>}
      {r.status === "REFUNDED_AWAITING_NEW_ORDER" && <Button variant="outline" onClick={onRetry}><RotateCcw /> Retry creating the new payment</Button>}
      {r.error && <p className="text-sm text-destructive">{r.error}{r.paypal_debug_id && <span className="block text-xs">PayPal debug ID: {r.paypal_debug_id}</span>}</p>}

      {payLink && r.status !== "COMPLETED" && (
        <div className="rounded-xl border border-violet-200 bg-violet-50/40 p-3">
          <p className="text-xs font-medium text-violet-900">Send this payment link to the buyer</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-md bg-white px-2 py-1.5 text-xs ring-1 ring-violet-200">{payLink}</code>
            <CopyButton text={payLink} label="Copy link" />
            <Button variant="ghost" size="sm" nativeButton={false} render={<a href={r.pay_page_path!} target="_blank" rel="noreferrer" />}>
              <ExternalLink /> Open
            </Button>
          </div>
        </div>
      )}

      {r.buyer_message && (
        <div className="rounded-xl border bg-slate-50/60 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-medium text-muted-foreground">
              Message to the buyer {r.message_source === "AI" ? "· drafted by AI" : "· template"} — you send it, we never message buyers
            </p>
            <CopyButton text={`${r.buyer_message_subject ?? ""}\n\n${r.buyer_message}`} label="Copy message" />
          </div>
          {r.buyer_message_subject && <p className="mt-2 text-sm font-semibold">{r.buyer_message_subject}</p>}
          <p className="mt-1 whitespace-pre-line text-sm">{r.buyer_message}</p>
        </div>
      )}
      {r.type === "SHIP_TO_PROTECTED" && (
        <p className="text-[13px] text-muted-foreground">Next: print a label with the PayPal address and upload it in Evidence check — the verdict re-runs automatically.</p>
      )}
      {r.status === "COMPLETED" && (
        <p className="text-[13px] text-muted-foreground">Next: print a label for the new address and upload it in Evidence check.</p>
      )}
    </div>
  );
}

function Stage({ done, label, detail }: { done: boolean; label: string; detail: string }) {
  return (
    <li className={cn("rounded-lg border p-2.5", done ? "border-emerald-200 bg-emerald-50/50" : "bg-white")}>
      <p className="flex items-center gap-1.5 font-medium">
        {done ? <Check className="size-4 text-emerald-600" /> : <span className="size-2 rounded-full bg-slate-300" />} {label}
      </p>
      <p className="mt-0.5 truncate text-xs text-muted-foreground">{detail}</p>
    </li>
  );
}

function ConfirmRepayDialog({ r, amount, currency, onClose, onDone }: {
  r: RemediationOut | null; amount: string | null; currency: string | null; onClose: () => void; onDone: (r: RemediationOut) => void;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const a = r?.requested_address;
  async function go() {
    if (!r) return;
    setBusy(true);
    setErr(null);
    try {
      onDone(await api.confirmRemediation(r.id, code));
      setCode("");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Confirmation failed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={!!r} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Undo2 className="size-5 text-violet-600" /> Confirm Safe re-pay</DialogTitle>
          <DialogDescription>This moves real money in your PayPal account (sandbox: test money). Please check the details.</DialogDescription>
        </DialogHeader>
        {r && (
          <div className="space-y-3 text-sm">
            <dl className="divide-y rounded-xl border">
              <Row k="Refund to the buyer" v={money(r.refund_amount ?? amount, currency)} />
              <Row k="New payment amount" v={money(r.refund_amount ?? amount, currency)} />
              <Row k="New shipping address" v={a ? [a.name, a.line1, a.line2, `${a.city}, ${a.state} ${a.postal_code}`].filter(Boolean).join(", ") : "—"} />
            </dl>
            <ul className="list-disc space-y-1 pl-5 text-[13px] text-muted-foreground">
              <li>The original payment is refunded in full right away.</li>
              <li>You only ship after the buyer pays the new payment.</li>
              <li>If the buyer never pays, the order stays unshippable (refunded).</li>
            </ul>
            <label className="block text-sm">
              Type <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono font-semibold">{r.confirmation_code}</span> to confirm
              <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} autoComplete="off"
                className="mt-1.5 h-9 w-full rounded-lg border px-2.5 font-mono tracking-widest outline-none focus-visible:ring-3 focus-visible:ring-ring/40" />
            </label>
            {err && <p role="alert" className="text-destructive">{err}</p>}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={go} disabled={busy || !r || code !== r.confirmation_code}>
            {busy && <Loader2 className="animate-spin" />} Confirm refund and create new payment
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3 px-3 py-2">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="text-right font-medium">{v}</dd>
    </div>
  );
}
