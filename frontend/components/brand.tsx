import { cn } from "@/lib/utils";

/** StayCovered logo mark: a shield with a check, on an emerald tile. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex size-8 items-center justify-center rounded-[10px] bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-sm ring-1 ring-black/5",
        className,
      )}
      aria-hidden
    >
      <svg viewBox="0 0 24 24" className="size-[18px]" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 3 5 6v5.5c0 4.2 2.9 7.9 7 9 4.1-1.1 7-4.8 7-9V6l-7-3Z" fill="currentColor" fillOpacity={0.18} />
        <path d="m8.8 12.2 2.2 2.2 4.3-4.6" />
      </svg>
    </span>
  );
}

export function Wordmark() {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark />
      <span className="text-[15px] font-semibold tracking-tight">
        Stay<span className="text-brand-strong">Covered</span>
      </span>
    </span>
  );
}

/** Section title with a tinted icon tile — used across cards for a consistent rhythm. */
export function SectionTitle({
  icon,
  tone = "slate",
  children,
  sub,
}: {
  icon: React.ReactNode;
  tone?: "slate" | "emerald" | "violet" | "sky" | "amber";
  children: React.ReactNode;
  sub?: React.ReactNode;
}) {
  const tones = {
    slate: "bg-slate-100 text-slate-700",
    emerald: "bg-emerald-50 text-emerald-700",
    violet: "bg-violet-50 text-violet-700",
    sky: "bg-sky-50 text-sky-700",
    amber: "bg-amber-50 text-amber-700",
  } as const;
  return (
    <div className="flex items-start gap-3">
      <span className={cn("icon-tile [&_svg]:size-[18px]", tones[tone])}>{icon}</span>
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold leading-tight">{children}</h2>
        {sub && <p className="mt-0.5 text-[13px] text-muted-foreground">{sub}</p>}
      </div>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0 space-y-1">
        {eyebrow && <p className="text-xs font-medium uppercase tracking-wider text-brand-strong">{eyebrow}</p>}
        <h1 className="text-[26px] font-semibold leading-tight">{title}</h1>
        {description && <p className="max-w-2xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
