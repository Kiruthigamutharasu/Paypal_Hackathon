import { Suspense } from "react";
import type { Metadata } from "next";
import { Inter, Geist_Mono } from "next/font/google";
import { SiteHeader } from "@/components/site-header";
import { LogoMark } from "@/components/brand";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const inter = Inter({ variable: "--font-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "StayCovered — keep your PayPal Seller Protection",
  description:
    "AI assistant that checks chats and shipping labels against the PayPal protected address before you ship.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <TooltipProvider>
          <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-white focus:px-3 focus:py-2">
            Skip to content
          </a>
          <Suspense fallback={<div className="h-16 border-b bg-white" />}>
            <SiteHeader />
          </Suspense>
          <div className="relative flex-1">
            <div className="hero-band absolute inset-x-0 top-0 h-[300px]" aria-hidden />
            <main id="main" className="relative mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
              {children}
            </main>
          </div>
          <footer className="border-t bg-[#0a1a40] text-blue-100/80">
            <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-6 text-xs sm:px-6">
              <span className="flex items-center gap-2">
                <LogoMark className="size-6 rounded-md [&_svg]:size-3.5" /> StayCovered · PayPal sandbox demo
              </span>
              <span>PayPal decides Seller Protection eligibility and dispute outcomes. A passed check is not a guarantee.</span>
            </div>
          </footer>
        </TooltipProvider>
      </body>
    </html>
  );
}
