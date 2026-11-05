"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Gavel, Info, RefreshCw } from "lucide-react";

import { api, ApiError, money, type DisputeRow } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/brand";
import { DeadlineChip, DisputeStatusPill, REASON } from "@/components/dispute-bits";

export function DisputesList() {
  const [rows, setRows] = useState<DisputeRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.disputes().then((r) => !cancelled && setRows(r)).catch((e) => !cancelled && setMsg(e instanceof ApiError ? e.message : "Could not load disputes."));
    return () => {
      cancelled = true;
    };
  }, []);

  async function sync() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.syncDisputes();
      setRows(await api.disputes());
      setMsg(r.synced.length ? `Synced ${r.synced.length} dispute(s) from PayPal.` : "No disputes found in PayPal.");
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : "Sync failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Dispute defense"
        title="Disputes"
        description="When a buyer opens a PayPal dispute, StayCovered prepares reason-specific evidence from your records. You review it and submit it to PayPal."
        actions={<Button size="lg" variant="outline" onClick={sync} disabled={busy}><RefreshCw className={busy ? "animate-spin" : ""} /> Sync from PayPal</Button>}
      />
      {msg && <p className="text-sm text-muted-foreground" role="status">{msg}</p>}

      <section className="surface overflow-hidden">
        {rows === null ? (
          <div className="space-y-3 p-5">{[0, 1].map((i) => <div key={i} className="h-14 animate-pulse rounded-lg bg-muted" />)}</div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <span className="icon-tile size-12 bg-slate-100 text-slate-500"><Gavel className="size-6" /></span>
            <p className="font-medium">No disputes — good news</p>
            <p className="max-w-lg text-sm text-muted-foreground">
              Disputes arrive automatically through PayPal webhooks, or press <b>Sync from PayPal</b>.
            </p>
            <div className="mt-2 max-w-lg rounded-xl border border-amber-200 bg-amber-50/70 p-4 text-left text-[13px] text-amber-950">
              <p className="flex items-center gap-1.5 font-semibold"><Info className="size-4" /> Sandbox: how to create a test dispute</p>
              <ol className="mt-2 list-decimal space-y-1 pl-5">
                <li>Open <a className="underline" href="https://www.sandbox.paypal.com" target="_blank" rel="noreferrer">sandbox.paypal.com</a> and log in as the sandbox <b>buyer</b>.</li>
                <li>Find the necklace payment → <b>Report a problem</b> → <b>I didn&apos;t receive it</b>.</li>
                <li>Come back here and press <b>Sync from PayPal</b>.</li>
              </ol>
              <p className="mt-2 text-xs">PayPal has no API to create disputes, so this one step is done as the buyer.</p>
            </div>
          </div>
        ) : (
          <ul className="divide-y">
            {rows.map((d) => (
              <li key={d.id}>
                <Link href={`/disputes/${d.id}`} className="flex flex-wrap items-center gap-4 px-5 py-4 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-ring">
                  <span className="icon-tile bg-amber-50 text-amber-700 [&_svg]:size-[18px]"><Gavel /></span>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{REASON[d.reason ?? ""] ?? d.reason} · {money(d.amount, d.currency)}</p>
                    <p className="text-[13px] text-muted-foreground">
                      {d.item ?? "Unlinked order"}{d.buyer_name && <> · {d.buyer_name}</>} · <span className="font-mono">{d.paypal_dispute_id}</span>
                    </p>
                  </div>
                  <DisputeStatusPill status={d.status} outcome={d.outcome} />
                  <DeadlineChip due={d.seller_response_due_date} flag={d.deadline_flag} hoursLeft={d.hours_left} />
                  <ArrowRight className="size-4 text-muted-foreground" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
