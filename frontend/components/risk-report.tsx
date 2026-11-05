"use client";

/**
 * Explainable Risk Report (F3). The verdict comes from deterministic rules on the server — never from AI.
 * Labels are always text + colour (never colour alone).
 */
import { useEffect, useState } from "react";
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  CircleHelp,
  Info,
  Loader2,
  MinusCircle,
  Quote,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import { api, ApiError, type DecisionOut, type FlagOut } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

const BANNER = {
  GREEN: { cls: "border-emerald-200 bg-gradient-to-r from-emerald-50 to-white", icon: <ShieldCheck className="size-6 text-emerald-600" />, title: "Checks passed" },
  YELLOW: { cls: "border-amber-200 bg-gradient-to-r from-amber-50 to-white", icon: <AlertTriangle className="size-6 text-amber-600" />, title: "Review needed" },
  RED: { cls: "border-red-200 bg-gradient-to-r from-red-50 to-white", icon: <AlertOctagon className="size-6 text-red-600" />, title: "Shipment blocked" },
  GREY: { cls: "border-slate-200 bg-gradient-to-r from-slate-50 to-white", icon: <CircleHelp className="size-6 text-slate-500" />, title: "Cannot evaluate yet" },
} as const;

const CHECK_ICON: Record<string, React.ReactNode> = {
  pass: <CheckCircle2 className="size-4 text-emerald-600" aria-label="passed" />,
  fail: <XCircle className="size-4 text-red-600" aria-label="failed" />,
  warn: <AlertTriangle className="size-4 text-amber-600" aria-label="needs review" />,
  pending: <Loader2 className="size-4 animate-spin text-slate-500" aria-label="in progress" />,
  info: <Info className="size-4 text-sky-600" aria-label="information" />,
  na: <MinusCircle className="size-4 text-slate-400" aria-label="not applicable" />,
};

const FIELD_NAMES: Record<string, string> = {
  line1: "Street", line2: "Apt / unit", city: "City", state: "State", postal_code: "ZIP", country: "Country",
};

export function RiskReport({ orderId, refreshKey, onDecision, onFix }: {
  orderId: string;
  refreshKey: number;
  onDecision?: (d: DecisionOut) => void;
  onFix?: () => void;
}) {
  const [d, setD] = useState<DecisionOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ackOpen, setAckOpen] = useState(false);
  const [polls, setPolls] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api
      .decision(orderId)
      .then((x) => {
        if (cancelled) return;
        setD(x);
        setError(null);
        onDecision?.(x);
      })
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load the verdict."));
    return () => {
      cancelled = true;
    };
  }, [orderId, refreshKey, polls, onDecision]);

  // Keep polling while the AI is still reading (SYS-03), so the verdict updates by itself.
  const waiting = d?.flags.some((f) => f.code === "SYS-03");
  useEffect(() => {
    if (!waiting || polls > 40) return;
    const t = setTimeout(() => setPolls((n) => n + 1), 2500);
    return () => clearTimeout(t);
  }, [waiting, polls]);

  async function recheck() {
    setBusy(true);
    try {
      const x = await api.reevaluate(orderId);
      setD(x);
      onDecision?.(x);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Re-check failed.");
    } finally {
      setBusy(false);
    }
  }

  if (error && !d) return <section className="surface p-5 text-sm text-destructive">{error}</section>;
  if (!d) return <section className="surface h-48 animate-pulse" aria-label="Loading verdict" />;

  const b = BANNER[d.verdict];
  const visibleFlags = d.flags.filter((f) => f.effect !== "NONE");
  const order = { RED: 0, GREY: 1, YELLOW: 2, INFO: 3, NONE: 4 } as const;
  visibleFlags.sort((a, z) => order[a.effect] - order[z.effect]);
  const fixable = d.flags.some((f) => ["ADD-03", "ADD-12", "ADD-04", "ADD-05", "ADD-06", "ADD-08"].includes(f.code));

  return (
    <section className="surface overflow-hidden" aria-label="Shipping verdict">
      {/* Verdict banner */}
      <div className={cn("flex flex-wrap items-start gap-4 border-b p-5", b.cls)}>
        <span className="mt-0.5" aria-hidden>{b.icon}</span>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Shipping verdict · rule engine</p>
          <h2 className="text-lg font-semibold">
            {b.title}
            {d.resolution === "ACKNOWLEDGED" && <span className="ml-2 text-sm font-medium text-emerald-700">· reviewed by you</span>}
            {d.resolution === "OVERRIDDEN" && <span className="ml-2 text-sm font-medium text-red-700">· overridden by you</span>}
          </h2>
          <p className="text-sm text-muted-foreground">{d.verdict === "GREEN" ? d.headline : d.recommended_action}</p>
          {d.resolution === "OVERRIDDEN" && d.override_reason && (
            <p className="mt-1 text-xs text-red-800">Your reason: “{d.override_reason}” — Seller Protection is likely void.</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {fixable && onFix && d.resolution !== "OVERRIDDEN" && (
            <Button onClick={onFix}>Fix this safely</Button>
          )}
          {d.verdict === "YELLOW" && d.resolution === "NONE" && (
            <Button variant="outline" onClick={() => setAckOpen(true)}>Review &amp; acknowledge</Button>
          )}
          {d.verdict === "RED" && d.resolution === "NONE" && (
            <Button variant="outline" onClick={() => setAckOpen(true)}>Override…</Button>
          )}
          <Button variant="ghost" size="sm" onClick={recheck} disabled={busy} aria-label="Re-run checks">
            <RotateCcw className={busy ? "animate-spin" : ""} aria-hidden /> Re-check
          </Button>
        </div>
      </div>

      <div className="grid gap-0 lg:grid-cols-[1fr_1.35fr]">
        {/* Checklist */}
        <div className="border-b p-5 lg:border-b-0 lg:border-r">
          <h3 className="text-[13px] font-semibold uppercase tracking-wider text-muted-foreground">Checks</h3>
          <ul className="mt-3 space-y-2.5">
            {d.checks.map((c) => (
              <li key={c.key} className="flex items-start gap-2.5 text-sm">
                <span className="mt-0.5 shrink-0">{CHECK_ICON[c.status] ?? <CircleDashed className="size-4" />}</span>
                <span>
                  <span className="font-medium">{c.label}</span>
                  <span className="block text-xs text-muted-foreground">{c.detail}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>

        {/* Address diff + flags */}
        <div className="space-y-5 p-5">
          {d.comparison && (
            <div>
              <h3 className="text-[13px] font-semibold uppercase tracking-wider text-muted-foreground">PayPal address vs. label</h3>
              <div className="mt-3 overflow-hidden rounded-xl border">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-medium">Field</th>
                      <th className="px-3 py-2 font-medium">PayPal (protected)</th>
                      <th className="px-3 py-2 font-medium">Label</th>
                      <th className="px-3 py-2 font-medium sr-only sm:not-sr-only">Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.comparison.fields.filter((f) => f.result !== "NOT_COMPARED").map((f) => {
                      const bad = ["MISMATCH", "MISSING_ON_LABEL", "MISSING"].includes(f.result);
                      const warn = f.result === "FUZZY" || f.result === "EXTRA_ON_LABEL";
                      return (
                        <tr key={f.field} className={cn("border-t", bad && "bg-red-50/60", warn && "bg-amber-50/60")}>
                          <td className="px-3 py-2 text-muted-foreground">{FIELD_NAMES[f.field] ?? f.field}</td>
                          <td className="px-3 py-2">{f.paypal ?? "—"}</td>
                          <td className={cn("px-3 py-2", bad && "font-semibold text-red-700", warn && "font-semibold text-amber-800")}>{f.label ?? "—"}</td>
                          <td className="px-3 py-2 text-xs">
                            {bad ? <span className="text-red-700">✕ differs</span> : warn ? <span className="text-amber-800">≈ check</span> : <span className="text-emerald-700">✓ match</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div>
            <h3 className="text-[13px] font-semibold uppercase tracking-wider text-muted-foreground">
              {visibleFlags.length ? "Why" : "Findings"}
            </h3>
            {visibleFlags.length === 0 ? (
              <p className="mt-2 text-sm text-muted-foreground">Nothing to flag on the evidence provided.</p>
            ) : (
              <ul className="mt-3 space-y-3">
                {visibleFlags.map((f, i) => <FlagItem key={`${f.code}-${i}`} f={f} />)}
              </ul>
            )}
            {d.ignored.length > 0 && (
              <p className="mt-3 text-xs text-muted-foreground">Not counted: {d.ignored.join(" · ")}</p>
            )}
          </div>
        </div>
      </div>

      <p className="border-t bg-slate-50/60 px-5 py-2.5 text-[11px] text-muted-foreground">
        Decided by deterministic rules v{d.rules_version} on the evidence provided. PayPal makes the final decision on Seller Protection.
      </p>

      <AcknowledgeDialog
        open={ackOpen}
        onOpenChange={setAckOpen}
        decision={d}
        onDone={(x) => {
          setD(x);
          onDecision?.(x);
          setAckOpen(false);
        }}
        orderId={orderId}
      />
    </section>
  );
}

const EFFECT_STYLE: Record<string, string> = {
  RED: "border-red-200 bg-red-50/50",
  GREY: "border-slate-200 bg-slate-50",
  YELLOW: "border-amber-200 bg-amber-50/50",
  INFO: "border-sky-200 bg-sky-50/40",
};
const EFFECT_LABEL: Record<string, string> = { RED: "Blocks shipping", GREY: "Missing input", YELLOW: "Needs review", INFO: "For your information" };

function FlagItem({ f }: { f: FlagOut }) {
  const isQuote = !!f.source_ref;
  return (
    <li className={cn("rounded-xl border p-3", EFFECT_STYLE[f.effect])}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-md bg-white px-1.5 py-0.5 font-mono text-[11px] font-semibold ring-1 ring-black/10">{f.code}</span>
        <span className="text-sm font-semibold">{f.name.replace(" (ext)", "")}</span>
        <span className="ml-auto text-[11px] font-medium text-muted-foreground">{EFFECT_LABEL[f.effect]}</span>
      </div>
      <p className="mt-1 text-sm">{f.message}</p>
      {f.detail && (
        isQuote ? (
          <blockquote className="mt-2 flex gap-2 rounded-lg bg-white/80 p-2 text-sm">
            <Quote className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <span>{f.detail}</span>
            <a href={`#upload-${f.source_ref!.upload_id}`} className="ml-auto shrink-0 self-end text-xs text-muted-foreground underline">source</a>
          </blockquote>
        ) : (
          <p className="mt-1 text-xs text-muted-foreground">{f.detail}</p>
        )
      )}
      <p className="mt-2 text-xs"><span className="font-semibold">What to do: </span>{f.recommended_action}</p>
    </li>
  );
}

function AcknowledgeDialog({ open, onOpenChange, decision, orderId, onDone }: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  decision: DecisionOut;
  orderId: string;
  onDone: (d: DecisionOut) => void;
}) {
  const red = decision.verdict === "RED";
  const items = decision.flags.filter((f) => f.effect === "YELLOW");
  const [ticked, setTicked] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ready = red ? reason.trim().length >= 15 && confirm : items.every((f) => ticked.includes(f.code));

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      onDone(await api.acknowledge(orderId, red ? { reason, confirm_void: confirm } : { items: ticked }));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {red ? <ShieldAlert className="size-5 text-red-600" /> : <AlertTriangle className="size-5 text-amber-600" />}
            {red ? "Override a blocked shipment" : "Acknowledge review items"}
          </DialogTitle>
          <DialogDescription>
            {red
              ? "Shipping anyway means the parcel may not go to the protected address. PayPal Seller Protection will likely not apply. This is recorded in the order's audit log."
              : "Confirm you have checked each item. This is recorded in the order's audit log."}
          </DialogDescription>
        </DialogHeader>

        {red ? (
          <div className="space-y-3">
            <label className="block text-sm font-medium" htmlFor="override-reason">Why are you overriding? (at least 15 characters)</label>
            <textarea
              id="override-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              className="w-full rounded-lg border p-2.5 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/40"
            />
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} className="mt-0.5 size-4 accent-red-600" />
              I understand Seller Protection is likely void for this shipment.
            </label>
          </div>
        ) : (
          <ul className="space-y-2">
            {items.map((f) => (
              <li key={f.code}>
                <label className="flex items-start gap-2 rounded-lg border p-2.5 text-sm">
                  <input
                    type="checkbox"
                    className="mt-0.5 size-4 accent-emerald-600"
                    checked={ticked.includes(f.code)}
                    onChange={(e) => setTicked((t) => (e.target.checked ? [...t, f.code] : t.filter((c) => c !== f.code)))}
                  />
                  <span>
                    <span className="font-medium">{f.code} · {f.name.replace(" (ext)", "")}</span>
                    <span className="block text-xs text-muted-foreground">{f.recommended_action}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {err && <p role="alert" className="text-sm text-destructive">{err}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant={red ? "destructive" : "default"} onClick={submit} disabled={!ready || busy}>
            {busy && <Loader2 className="animate-spin" />} {red ? "Override and allow shipping" : "Acknowledge"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
