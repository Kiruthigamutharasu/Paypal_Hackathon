"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { FlaskConical } from "lucide-react";
import { Wordmark } from "@/components/brand";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Orders", match: (p: string) => p === "/" || p.startsWith("/orders") },
  { href: "/disputes", label: "Disputes", match: (p: string) => p.startsWith("/disputes") },
  { href: "/shop", label: "Demo shop", match: (p: string) => p.startsWith("/shop") || p.startsWith("/pay") },
  { href: "/how-it-works", label: "How it works", match: (p: string) => p.startsWith("/how-it-works") },
];

export function SiteHeader() {
  const pathname = usePathname() || "/";
  return (
    <header className="sticky top-0 z-30 border-b border-white/10 bg-[#0a1a40]/95 text-white backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-8 px-4 sm:px-6">
        <Link href="/" aria-label="StayCovered home" className="rounded-lg focus-visible:outline-2 focus-visible:outline-[#ffc439]">
          <Wordmark light />
        </Link>
        <nav aria-label="Main" className="hidden items-center gap-1 text-sm sm:flex">
          {NAV.map((n) => {
            const active = n.match(pathname);
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative whitespace-nowrap rounded-lg px-3 py-2 font-medium transition-colors focus-visible:outline-2 focus-visible:outline-[#ffc439]",
                  active ? "text-white" : "text-blue-100/75 hover:bg-white/10 hover:text-white",
                )}
              >
                {n.label}
                {active && <span className="absolute inset-x-3 -bottom-[13px] h-[3px] rounded-full bg-[#ffc439]" aria-hidden />}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden items-center gap-1.5 rounded-full bg-[#ffc439] px-2.5 py-1 text-xs font-semibold text-[#3a2a00] md:inline-flex">
            <FlaskConical className="size-3.5" aria-hidden /> Sandbox
          </span>
          <span className="flex items-center gap-2 rounded-full bg-white/10 py-1 pl-1 pr-3 text-xs font-medium ring-1 ring-white/15">
            <span className="flex size-6 items-center justify-center rounded-full bg-gradient-to-br from-[#ffd774] to-[#f2a900] text-[10px] font-bold text-[#3a2a00]" aria-hidden>
              PJ
            </span>
            <span className="hidden sm:inline">Priya&apos;s Jewellery</span>
          </span>
        </div>
      </div>
      <nav aria-label="Main mobile" className="flex gap-1 overflow-x-auto border-t border-white/10 px-4 py-1.5 text-sm sm:hidden">
        {NAV.map((n) => (
          <Link key={n.href} href={n.href}
            className={cn("rounded-md px-2.5 py-1.5", n.match(pathname) ? "bg-white/15 font-medium text-white" : "text-blue-100/75")}>
            {n.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
