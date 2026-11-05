import { cn } from "@/lib/utils";

/** StayCovered logo mark: a shield with a check — blue tile, gold check. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex size-8 items-center justify-center rounded-[10px] bg-gradient-to-br from-[#1f8bff] to-[#0b3a9c] text-white shadow-sm ring-1 ring-white/20",
        className,
      )}
      aria-hidden
    >
      <svg viewBox="0 0 24 24" className="size-[18px]" fill="none" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 3 5 6v5.5c0 4.2 2.9 7.9 7 9 4.1-1.1 7-4.8 7-9V6l-7-3Z" fill="white" fillOpacity={0.16} stroke="white" strokeWidth={1.8} />
        <path d="m8.8 12.2 2.2 2.2 4.3-4.6" stroke="#ffc439" strokeWidth={2.4} />
      </svg>
    </span>
  );
}

export function Wordmark({ light = false }: { light?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark />
      <span className={cn("text-[15px] font-semibold tracking-tight", light ? "text-white" : "text-foreground")}>
        Stay<span className={light ? "text-[#ffc439]" : "text-brand-strong"}>Covered</span>
      </span>
    </span>
  );
}

const TILE = {
  slate: "bg-slate-100 text-slate-700",
  emerald: "bg-emerald-50 text-emerald-700",
  violet: "bg-violet-50 text-violet-700",
  sky: "bg-sky-50 text-sky-700",
  amber: "bg-amber-50 text-amber-700",
  blue: "bg-blue-50 text-blue-700",
} as const;

/** Section title with a tinted icon tile — used across cards for a consistent rhythm. */
export function SectionTitle({
  icon,
  tone = "slate",
  children,
  sub,
}: {
  icon: React.ReactNode;
  tone?: keyof typeof TILE;
  children: React.ReactNode;
  sub?: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className={cn("icon-tile [&_svg]:size-[18px]", TILE[tone])}>{icon}</span>
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold leading-tight">{children}</h2>
        {sub && <p className="mt-0.5 text-[13px] text-muted-foreground">{sub}</p>}
      </div>
    </div>
  );
}

/** Page header that sits on the navy hero band (white text, gold eyebrow). */
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
    <div className="flex flex-wrap items-end justify-between gap-4 pb-2">
      <div className="min-w-0 space-y-1.5">
        {eyebrow && <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#ffc439]">{eyebrow}</p>}
        <h1 className="text-[28px] font-semibold leading-tight text-white">{title}</h1>
        {description && <p className="max-w-2xl text-sm text-blue-100/85">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2 [&_[data-slot=button][data-variant=outline]]:border-white/25 [&_[data-slot=button][data-variant=outline]]:bg-white/10 [&_[data-slot=button][data-variant=outline]]:text-white [&_[data-slot=button][data-variant=outline]:hover]:bg-white/20">{actions}</div>}
    </div>
  );
}

/** Small link that sits on the hero band (e.g. "← All orders"). */
export function BandLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-100/90 hover:text-white">
      {children}
    </a>
  );
}
