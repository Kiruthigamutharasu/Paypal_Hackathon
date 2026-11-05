"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  Check,
  FileText,
  FlaskConical,
  Gavel,
  Loader2,
  MessageSquare,
  PackageCheck,
  RefreshCw,
  Send,
  ShieldCheck,
  X,
} from "lucide-react";

import { api, ApiError, money, when, type DisputeDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { SectionTitle } from "@/components/brand";
import { Pill } from "@/components/status";
import { DeadlineChip, DisputeStatusPill, REASON } from "@/components/dispute-bits";
import { cn } from "@/lib/utils";

export function DisputeDetailView() {
  const { id } = useParams<{ id: string }>();
  const [d, setD] = useState<DisputeDetail | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.dispute(id).then((x) => !cancelled && setD(x)).catch((e) => !cancelled && setErr(e instanceof ApiError ? e.message : "Could not load the dispute."));
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function run(label: string, fn: () => Promise<DisputeDetail>) {
    setBusy(label);
    setErr(null);
    try {
      const x = await fn();
      setD(x);
      return x;
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }

  if (!d) return err ? <p className="text-sm text-destructive">{err}</p> : <div className="h-64 animate-pulse rounded-2xl bg-muted" />;

  const pack = d.pack;
  const submitted = pack?.status === "SUBMITTED";
  const canSubmit = pack?.status === "READY" && d.allowed_actions.includes("provide-evidence") && d.deadline_flag !== "DIS-11";

  return (
    <div className="space-y-6">
      <Link href="/disputes" className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> All disputes
      </Link>

      <section className="surface p-6">
        <div className="flex flex-wrap items-start gap-5">
          <span className="icon-tile size-14 rounded-2xl bg-amber-50 text-amber-700 [&_svg]:size-7"><Gavel /></span>
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-[22px] font-semibold">{REASON[d.reason ?? ""] ?? d.reason}</h1>
              <DisputeStatusPill status={d.status} outcome={d.outcome} />
              <DeadlineChip due={d.seller_response_due_date} flag={d.deadline_flag} hoursLeft={d.hours_left} />
            </div>
            <p className="text-sm text-muted-foreground">
              PayPal dispute <span className="font-mono">{d.paypal_dispute_id}</span> · stage {d.stage?.toLowerCase()} · opened {when(d.create_time)}
              {d.order && <> · <Link className="underline" href={`/orders/${d.order.id}`}>{d.order.item} order</Link></>}
            </p>
            {d.buyer_message && (
              <p className="flex items-start gap-2 text-sm"><MessageSquare className="mt-0.5 size-4 text-muted-foreground" /> Buyer: “{d.buyer_message}”</p>
            )}
          </div>
          <div className="text-right">
            <p className="text-[28px] font-semibold tabular-nums">{money(d.amount, d.currency)}</p>
            <Button variant="ghost" size="sm" onClick={() => run("refresh", () => api.refreshDispute(id))} disabled={!!busy}>
              <RefreshCw className={busy === "refresh" ? "animate-spin" : ""} /> Refresh
            </Button>
          </div>
        </div>
      </section>

      {err && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">{err}</p>}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <section className="surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <SectionTitle icon={<Bot />} tone="violet" sub="Facts come from your records. Rules pick the evidence for this reason; AI drafts the note; a checker verifies every claim.">
                Dispute Defense Agent
              </SectionTitle>
              {!submitted && (
                <Button onClick={() => run("plan", () => api.planDispute(id))} disabled={!!busy} variant={pack ? "outline" : "default"}>
                  {busy === "plan" ? <Loader2 className="animate-spin" /> : <Bot />} {pack ? `Re-prepare (v${pack.version + 1})` : "Prepare evidence"}
                </Button>
              )}
            </div>

            {!pack ? (
              <p className="mt-4 text-sm text-muted-foreground">Prepare the evidence to see the plan, files and note before anything is sent.</p>
            ) : !pack.supported ? (
              <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/60 p-4 text-sm">
                <p className="font-semibold">Manual response needed</p>
                <ul className="mt-2 list-disc space-y-1 pl-5">{[...pack.plan.missing, ...pack.plan.manual_checklist].map((m) => <li key={m}>{m}</li>)}</ul>
              </div>
            ) : (
              <div className="mt-5 space-y-5">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border p-3">
                    <p className="text-xs font-medium text-muted-foreground">Evidence type</p>
                    <p className="mt-0.5 font-semibold">{pack.plan.evidence_type?.replaceAll("_", " ").toLowerCase()}</p>
                    {pack.plan.tracking_info.map((t) => (
                      <p key={t.tracking_number} className="mt-1 flex items-center gap-1.5 text-sm"><PackageCheck className="size-4 text-sky-700" />{t.carrier_name} <span className="font-mono text-xs">{t.tracking_number}</span></p>
                    ))}
                  </div>
                  <div className="rounded-xl border p-3">
                    <p className="text-xs font-medium text-muted-foreground">Why this evidence</p>
                    <ul className="mt-1 space-y-1 text-[13px]">{pack.plan.rationale.map((r) => <li key={r} className="flex gap-1.5"><Check className="mt-0.5 size-3.5 shrink-0 text-emerald-600" />{r}</li>)}</ul>
                  </div>
                </div>
                {[...pack.plan.missing, ...pack.plan.info].length > 0 && (
                  <ul className="space-y-1 rounded-xl border border-amber-200 bg-amber-50/60 p-3 text-[13px]">
                    {[...pack.plan.missing, ...pack.plan.info].map((m) => <li key={m} className="flex gap-1.5"><AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-600" />{m}</li>)}
                  </ul>
                )}

                <div>
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-[13px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Note to PayPal <span className="normal-case tracking-normal">· {pack.note_source === "AI" ? "drafted by AI" : pack.note_source === "SELLER" ? "edited by you" : "template"}</span>
                    </h3>
                    {!submitted && !editing && <Button variant="ghost" size="sm" onClick={() => { setNote(pack.note ?? ""); setEditing(true); }}>Edit</Button>}
                  </div>
                  {editing ? (
                    <div className="mt-2 space-y-2">
                      <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={6} maxLength={1000}
                        className="w-full rounded-xl border p-3 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/40" />
                      <div className="flex gap-2">
                        <Button size="sm" onClick={async () => { if (await run("note", () => api.editNote(id, note))) setEditing(false); }} disabled={!!busy}>Save &amp; re-check</Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-2 space-y-1.5 rounded-xl border bg-slate-50/50 p-3">
                      {pack.claim_check?.sentences.map((s, i) => (
                        <div key={i} className="flex gap-2 text-sm">
                          {s.ok ? <Check className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-label="verified" /> : <X className="mt-0.5 size-4 shrink-0 text-red-600" aria-label="not verified" />}
                          <span className={cn(!s.ok && "rounded bg-red-50 text-red-900")}>
                            {s.text}
                            {!s.ok && <span className="block text-xs text-red-700">{s.problems.join(" · ")}</span>}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                  <p className={cn("mt-2 text-xs font-medium", pack.claim_check?.passed ? "text-emerald-700" : "text-red-700")}>
                    {pack.claim_check?.passed ? "✓ Every claim is backed by your records." : "✕ EVD-08: some claims can't be backed by your records — edit the note."}
                  </p>
                </div>

                <div>
                  <h3 className="text-[13px] font-semibold uppercase tracking-wider text-muted-foreground">Files ({pack.files.length})</h3>
                  <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                    {pack.files.map((f) => (
                      <li key={f.id}>
                        <a href={api.disputeFileUrl(id, f.id)} target="_blank" rel="noreferrer" className="flex items-center gap-2.5 rounded-xl border p-3 hover:bg-slate-50">
                          <FileText className="size-5 text-slate-500" />
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-medium">{f.filename}</span>
                            <span className="block truncate text-xs text-muted-foreground">{f.description} · {(f.size / 1024).toFixed(0)} KB</span>
                          </span>
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </section>
        </div>

        <aside className="space-y-6">
          <section className="surface p-5">
            <SectionTitle icon={<Send />} tone="emerald" sub="Nothing is sent until you confirm. PayPal makes the final decision.">Submit to PayPal</SectionTitle>
            <div className="mt-4 space-y-3 text-sm">
              <Gate ok={!!pack && pack.supported} label="Supported dispute reason" />
              <Gate ok={!!pack?.claim_check?.passed} label="Note passes the claim check" />
              <Gate ok={d.allowed_actions.includes("provide-evidence")} label="PayPal allows evidence now" />
              <Gate ok={d.deadline_flag !== "DIS-11"} label="Before the deadline" />
              {submitted ? (
                <p className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 font-medium text-emerald-800"><ShieldCheck className="size-4" /> Evidence submitted (v{pack?.version})</p>
              ) : (
                <Button className="w-full" size="lg" disabled={!canSubmit || !!busy} onClick={() => setConfirmOpen(true)}><Send /> Submit to PayPal</Button>
              )}
              {pack?.submissions.map((s) => (
                <p key={s.id} className="text-xs text-muted-foreground">
                  {when(s.submitted_at)} · {s.status.toLowerCase()} {s.http_status ? `(${s.http_status})` : ""} {s.paypal_debug_id && `· debug ${s.paypal_debug_id}`}
                </p>
              ))}
            </div>
          </section>

          <section className="rounded-2xl border border-dashed border-amber-300 bg-amber-50/50 p-5">
            <SectionTitle icon={<FlaskConical />} tone="amber" sub="Sandbox-only helpers for the demo. They call PayPal's sandbox endpoints.">Sandbox demo tools</SectionTitle>
            <div className="mt-4 grid gap-2">
              <Button variant="outline" size="sm" disabled={!!busy} onClick={() => run("sb", () => api.sandboxDispute(id, "SELLER_EVIDENCE"))}>Ask seller for evidence</Button>
              <Button variant="outline" size="sm" disabled={!!busy} onClick={() => run("sb", () => api.sandboxDispute(id, "SELLER_FAVOR"))}>Settle in seller&apos;s favour</Button>
              <Button variant="outline" size="sm" disabled={!!busy} onClick={() => run("sb", () => api.sandboxDispute(id, "BUYER_FAVOR"))}>Settle in buyer&apos;s favour</Button>
              <p className="text-[11px] text-amber-900/80">Settling needs the dispute to be “PayPal reviewing” (UNDER_REVIEW).</p>
            </div>
          </section>
        </aside>
      </div>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Submit evidence to PayPal?</DialogTitle>
            <DialogDescription>This sends the note and {pack?.files.length} file(s) to PayPal for dispute {d.paypal_dispute_id}. You can&apos;t unsend it.</DialogDescription>
          </DialogHeader>
          <pre className="max-h-48 overflow-auto rounded-lg bg-slate-50 p-3 text-[11px]">{pack?.evidence_preview}</pre>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>Cancel</Button>
            <Button disabled={!!busy} onClick={async () => { await run("submit", () => api.submitEvidence(id, pack!.id)); setConfirmOpen(false); }}>
              {busy === "submit" && <Loader2 className="animate-spin" />} Submit to PayPal
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Gate({ ok, label }: { ok: boolean; label: string }) {
  return (
    <p className="flex items-center gap-2">
      {ok ? <Check className="size-4 text-emerald-600" aria-label="ok" /> : <X className="size-4 text-slate-400" aria-label="not yet" />}
      <span className={ok ? "" : "text-muted-foreground"}>{label}</span>
      <Pill tone={ok ? "green" : "grey"} dot={false} className="ml-auto">{ok ? "OK" : "Not yet"}</Pill>
    </p>
  );
}
