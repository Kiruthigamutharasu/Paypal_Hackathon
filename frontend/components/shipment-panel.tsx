"use client";

/** Shipment & PayPal tracking (F4). "Label checked" ≠ "Shipped (tracking on PayPal)" ≠ "Delivered". */
import { useEffect, useState } from "react";
import { Ban, CheckCircle2, Loader2, Lock, PackageCheck, Truck } from "lucide-react";

import { api, ApiError, when, type DecisionOut, type ShipmentOut } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { SectionTitle } from "@/components/brand";
import { Pill } from "@/components/status";

const STATUS: Record<string, [Parameters<typeof Pill>[0]["tone"], string]> = {
  SHIPPED: ["blue", "Shipped · tracking on PayPal"],
  DELIVERED: ["green", "Delivered (seller-reported)"],
  CANCELLED: ["grey", "Cancelled"],
};

export function ShipmentPanel({ orderId, decision, onChanged }: { orderId: string; decision: DecisionOut | null; onChanged: () => void }) {
  const [ships, setShips] = useState<ShipmentOut[] | null>(null);
  const [carriers, setCarriers] = useState<{ code: string; name: string }[]>([]);
  const [carrier, setCarrier] = useState("USPS");
  const [other, setOther] = useState("");
  const [num, setNum] = useState("");
  const [notify, setNotify] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.shipments(orderId).then((s) => !cancelled && setShips(s)).catch(() => !cancelled && setShips([]));
    api.carriers().then((c) => !cancelled && setCarriers(c)).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [orderId]);

  const allowed = !!decision?.can_ship;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const s = await api.createShipment(orderId, { carrier, tracking_number: num, carrier_name_other: carrier === "OTHER" ? other : undefined, notify_payer: notify });
      setShips((x) => [...(x ?? []).filter((y) => y.id !== s.id), s]);
      setNum("");
      onChanged();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : "Could not register tracking.");
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(id: string, status: "CANCELLED" | "DELIVERED") {
    try {
      const s = await api.updateShipment(id, status);
      setShips((x) => (x ?? []).map((y) => (y.id === s.id ? s : y)));
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Update failed.");
    }
  }

  return (
    <section className="surface p-5" aria-label="Shipment and tracking">
      <SectionTitle icon={<Truck />} tone="sky" sub="Register tracking with PayPal at dispatch — this is your proof of shipment if a dispute comes.">
        Ship &amp; register tracking
      </SectionTitle>

      {!!ships?.length && (
        <ul className="mt-4 space-y-2">
          {ships.map((s) => {
            const [tone, label] = STATUS[s.status] ?? ["grey", s.status];
            return (
              <li key={s.id} className="rounded-xl border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <PackageCheck className="size-4 text-sky-700" aria-hidden />
                  <span className="text-sm font-semibold">{s.carrier === "OTHER" ? s.carrier_name_other : s.carrier}</span>
                  <span className="font-mono text-xs">{s.tracking_number}</span>
                  <Pill tone={tone} className="ml-auto">{label}</Pill>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  PayPal tracker <span className="font-mono">{s.paypal_tracker_id}</span> · registered {when(s.registered_at)}
                  {s.decision_basis && s.decision_basis !== "GREEN" && <> · shipped after {s.decision_basis.toLowerCase()}</>}
                </p>
                {s.status === "SHIPPED" && (
                  <div className="mt-2 flex gap-2">
                    <Button size="sm" variant="outline" onClick={() => setStatus(s.id, "DELIVERED")}><CheckCircle2 /> Mark delivered</Button>
                    <Button size="sm" variant="ghost" onClick={() => setStatus(s.id, "CANCELLED")}><Ban /> Cancel tracker</Button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {!allowed ? (
        <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-dashed bg-slate-50/70 p-3 text-sm text-muted-foreground">
          <Lock className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p><span className="font-medium text-foreground">Shipping is locked.</span> {decision?.can_ship_reason ?? "Waiting for the checks."}</p>
        </div>
      ) : (
        <form onSubmit={submit} className="mt-4 grid gap-3 sm:grid-cols-[150px_1fr]">
          <label className="text-xs text-muted-foreground">
            Carrier
            <select value={carrier} onChange={(e) => setCarrier(e.target.value)}
              className="mt-1 h-9 w-full rounded-lg border bg-white px-2 text-sm text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/40">
              {(carriers.length ? carriers : [{ code: "USPS", name: "USPS" }]).map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
            </select>
          </label>
          <label className="text-xs text-muted-foreground">
            Tracking number
            <input value={num} onChange={(e) => setNum(e.target.value)} required placeholder="e.g. 9400 1118 9922 3344 5566 77"
              className="mt-1 h-9 w-full rounded-lg border bg-white px-2.5 font-mono text-sm text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/40" />
          </label>
          {carrier === "OTHER" && (
            <label className="text-xs text-muted-foreground sm:col-span-2">
              Carrier name
              <input value={other} onChange={(e) => setOther(e.target.value)} required
                className="mt-1 h-9 w-full rounded-lg border bg-white px-2.5 text-sm text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/40" />
            </label>
          )}
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} className="size-4 accent-emerald-600" />
            Let PayPal notify the buyer
          </label>
          <div className="sm:col-span-2">
            <Button type="submit" disabled={busy || !num.trim()}>{busy ? <Loader2 className="animate-spin" /> : <Truck />} Register tracking with PayPal</Button>
          </div>
        </form>
      )}
      {err && <p role="alert" className="mt-3 text-sm text-destructive">{err}</p>}
    </section>
  );
}
