import Link from "next/link";
import { ShieldCheck } from "lucide-react";

const NAV = [
  { href: "/", label: "Orders" },
  { href: "/shop", label: "Demo shop" },
  { href: "/how-it-works", label: "How it works" },
];

export function SiteHeader() {
  return (
    <header className="border-b bg-background/80 backdrop-blur sticky top-0 z-20">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <ShieldCheck className="size-5 text-emerald-600" aria-hidden />
          StayCovered
        </Link>
        <nav aria-label="Main" className="flex items-center gap-1 text-sm">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className="rounded-md px-2.5 py-1.5 text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <span className="ml-auto rounded-full border border-amber-500/40 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          PayPal sandbox
        </span>
      </div>
    </header>
  );
}
