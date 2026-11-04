import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { SiteHeader } from "@/components/site-header";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const geistSans = Geist({ variable: "--font-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "StayCovered — keep your PayPal Seller Protection",
  description:
    "AI assistant that checks chats and shipping labels against the PayPal protected address before you ship.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-muted/30">
        <TooltipProvider>
          <SiteHeader />
          <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
          <footer className="border-t py-6 text-center text-xs text-muted-foreground">
            StayCovered · PayPal sandbox demo · PayPal decides Seller Protection eligibility and dispute outcomes.
          </footer>
        </TooltipProvider>
      </body>
    </html>
  );
}
