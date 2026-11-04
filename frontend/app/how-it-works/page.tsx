import {
  ArrowDown,
  ArrowRight,
  Bot,
  CreditCard,
  Database,
  FileSearch,
  Gavel,
  Lock,
  Scale,
  ShieldCheck,
  Store,
  Truck,
  UserCheck,
} from "lucide-react";
import { PageHeader } from "@/components/brand";
import { cn } from "@/lib/utils";

const STEPS = [
  { icon: <CreditCard />, tone: "sky", title: "Buyer pays with PayPal", body: "The order is created and captured on our server. PayPal records the buyer's shipping address on the transaction — the protected address.", tag: "Live" },
  { icon: <Database />, tone: "slate", title: "PayPal facts recorded", body: "Capture status, amount, Seller Protection status and the protected address come from PayPal. Webhooks are verified, deduplicated and re-fetched.", tag: "Live" },
  { icon: <FileSearch />, tone: "violet", title: "AI reads chats and labels", body: "Gemini extracts requests like “ship to my friend” and the label address — with exact quotes and sources. Embedded instructions are ignored.", tag: "Live" },
  { icon: <Scale />, tone: "emerald", title: "Rules decide, you approve", body: "Plain code compares everything with the protected address and explains the verdict. Nothing that moves money happens without your click.", tag: "Next" },
  { icon: <Truck />, tone: "amber", title: "Tracking and dispute defense", body: "Tracking is registered with PayPal at dispatch. If a dispute arrives, evidence is prepared and submitted after you approve.", tag: "Next" },
] as const;

const TONES = {
  sky: "bg-sky-50 text-sky-700",
  slate: "bg-slate-100 text-slate-700",
  violet: "bg-violet-50 text-violet-700",
  emerald: "bg-emerald-50 text-emerald-700",
  amber: "bg-amber-50 text-amber-700",
} as const;

export default function HowItWorks() {
  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="How it works"
        title="AI extracts. Rules decide. You approve."
        description="StayCovered stops the “please ship it to my friend” scam before the parcel leaves — and keeps the evidence ready if a dispute comes anyway. PayPal moves the money and makes the final call."
      />

      {/* Flow */}
      <section className="surface p-6" aria-label="Architecture">
        <h2 className="text-[15px] font-semibold">Architecture</h2>
        <p className="text-[13px] text-muted-foreground">PayPal is the source of truth for payments, addresses and disputes.</p>
        <div className="mt-6 grid items-stretch gap-3 lg:grid-cols-[1fr_auto_1.3fr_auto_1fr]">
          <Column title="People">
            <Node icon={<UserCheck />} label="Seller app" note="Next.js · AG Grid" />
            <Node icon={<Store />} label="Demo shop" note="PayPal JS SDK v6" />
          </Column>
          <Arrow />
          <Column title="StayCovered backend" accent>
            <Node icon={<Lock />} label="API + webhook receiver" note="FastAPI · signature-verified" />
            <div className="grid grid-cols-2 gap-2">
              <Node icon={<Bot />} label="AI agents" note="extract only" tone="violet" />
              <Node icon={<Scale />} label="Rule engine" note="deterministic" tone="emerald" />
            </div>
            <Node icon={<Database />} label="Postgres + audit log" note="every change recorded" />
          </Column>
          <Arrow />
          <Column title="External">
            <Node icon={<CreditCard />} label="PayPal sandbox" note="Orders · Payments · Webhooks · Tracking · Disputes" tone="sky" />
            <Node icon={<Bot />} label="Gemini (free tier)" note="or Claude" tone="violet" />
          </Column>
        </div>
      </section>

      {/* Steps */}
      <section aria-label="The seller journey">
        <h2 className="text-[15px] font-semibold">The seller journey</h2>
        <ol className="mt-4 grid gap-4 md:grid-cols-2 lg:grid-cols-5">
          {STEPS.map((s, i) => (
            <li key={s.title} className="surface flex flex-col gap-3 p-5">
              <div className="flex items-center justify-between">
                <span className={cn("icon-tile [&_svg]:size-[18px]", TONES[s.tone])} aria-hidden>
                  {s.icon}
                </span>
                <span className="text-xs font-medium text-muted-foreground">Step {i + 1}</span>
              </div>
              <h3 className="text-sm font-semibold leading-snug">{s.title}</h3>
              <p className="text-[13px] leading-relaxed text-muted-foreground">{s.body}</p>
              <span
                className={cn(
                  "mt-auto w-fit rounded-full px-2 py-0.5 text-[11px] font-medium",
                  s.tag === "Live" ? "bg-emerald-50 text-emerald-800" : "bg-slate-100 text-slate-600",
                )}
              >
                {s.tag === "Live" ? "Working now" : "Coming next"}
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section className="grid gap-4 md:grid-cols-3" aria-label="Principles">
        <Principle icon={<ShieldCheck />} title="Sandbox only, no real money">
          Runs entirely on the PayPal sandbox. The backend refuses to start with live credentials.
        </Principle>
        <Principle icon={<Lock />} title="Your data, minimised">
          Buyer emails are masked; the audit log stores only city and state. Uploads are processed by the configured AI provider.
        </Principle>
        <Principle icon={<Gavel />} title="PayPal has the final word">
          PayPal decides Seller Protection eligibility and dispute outcomes. A passed check is not a guarantee.
        </Principle>
      </section>
    </div>
  );
}

function Column({ title, children, accent }: { title: string; children: React.ReactNode; accent?: boolean }) {
  return (
    <div className={cn("flex flex-col gap-2 rounded-2xl border p-3", accent ? "border-emerald-200 bg-emerald-50/40" : "bg-slate-50/70")}>
      <p className="px-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{title}</p>
      {children}
    </div>
  );
}

function Node({
  icon,
  label,
  note,
  tone = "slate",
}: {
  icon: React.ReactNode;
  label: string;
  note: string;
  tone?: keyof typeof TONES;
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border bg-white p-3 shadow-xs">
      <span className={cn("icon-tile size-8 [&_svg]:size-4", TONES[tone])} aria-hidden>
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-medium leading-tight">{label}</p>
        <p className="text-xs text-muted-foreground">{note}</p>
      </div>
    </div>
  );
}

function Arrow() {
  return (
    <div className="flex items-center justify-center text-slate-300" aria-hidden>
      <ArrowRight className="hidden size-5 lg:block" />
      <ArrowDown className="size-5 lg:hidden" />
    </div>
  );
}

function Principle({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="surface flex gap-3 p-5">
      <span className="icon-tile bg-slate-100 text-slate-700 [&_svg]:size-[18px]" aria-hidden>
        {icon}
      </span>
      <div>
        <h3 className="text-sm font-semibold">{title}</h3>
        <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{children}</p>
      </div>
    </div>
  );
}
