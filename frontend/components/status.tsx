// Status pills: always text + colour (never colour alone), WCAG AA contrast.
import { cn } from "@/lib/utils";

type Tone = "green" | "amber" | "red" | "grey" | "blue";

const TONES: Record<Tone, string> = {
  green: "bg-emerald-50 text-emerald-800 ring-emerald-600/20 dark:bg-emerald-950 dark:text-emerald-200",
  amber: "bg-amber-50 text-amber-900 ring-amber-600/20 dark:bg-amber-950 dark:text-amber-200",
  red: "bg-red-50 text-red-800 ring-red-600/20 dark:bg-red-950 dark:text-red-200",
  grey: "bg-zinc-100 text-zinc-700 ring-zinc-500/20 dark:bg-zinc-800 dark:text-zinc-200",
  blue: "bg-sky-50 text-sky-800 ring-sky-600/20 dark:bg-sky-950 dark:text-sky-200",
};

export function Pill({ tone, children, className }: { tone: Tone; children: React.ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

const PAYMENT: Record<string, [Tone, string]> = {
  PAYMENT_COMPLETED: ["green", "Paid"],
  PAYMENT_PENDING: ["amber", "Pending"],
  PAYMENT_FAILED: ["red", "Failed"],
  PARTIALLY_REFUNDED: ["amber", "Partly refunded"],
  REFUNDED: ["red", "Refunded"],
  REVERSED: ["red", "Reversed"],
};

export function PaymentPill({ state }: { state: string }) {
  const [tone, label] = PAYMENT[state] ?? ["grey", state];
  return <Pill tone={tone}>{label}</Pill>;
}

const PROTECTION: Record<string, [Tone, string, string]> = {
  ELIGIBLE: ["green", "Eligible", "PayPal marks this payment as eligible for Seller Protection (item-not-received and unauthorized claims), if PayPal's requirements are met."],
  PARTIALLY_ELIGIBLE: ["amber", "Partially eligible", "PayPal marks this payment as partially eligible — it covers item-not-received claims only."],
  NOT_ELIGIBLE: ["red", "Not eligible", "PayPal marks this payment as not eligible for Seller Protection. Our checks still reduce your risk."],
  UNKNOWN: ["grey", "Unknown", "PayPal did not return a Seller Protection status for this payment. Check it in your PayPal account."],
};

export function protectionText(status: string): string {
  return (PROTECTION[status] ?? PROTECTION.UNKNOWN)[2];
}

export function ProtectionPill({ status }: { status: string }) {
  const [tone, label] = PROTECTION[status] ?? PROTECTION.UNKNOWN;
  return <Pill tone={tone}>{label}</Pill>;
}

const SHIPMENT: Record<string, [Tone, string]> = {
  NOT_SHIPPED: ["grey", "Not shipped"],
  LABEL_CHECKED: ["blue", "Label checked"],
  SHIPPED: ["blue", "Shipped · tracking on PayPal"],
  DELIVERED: ["green", "Delivered"],
  CANCELLED: ["grey", "Cancelled"],
};

export function ShipmentPill({ state }: { state: string }) {
  const [tone, label] = SHIPMENT[state] ?? ["grey", state];
  return <Pill tone={tone}>{label}</Pill>;
}

const VERDICT: Record<string, [Tone, string]> = {
  GREEN: ["green", "Checks passed"],
  YELLOW: ["amber", "Review needed"],
  RED: ["red", "Blocked"],
  GREY: ["grey", "Cannot evaluate"],
};

export function VerdictPill({ verdict }: { verdict: string | null }) {
  if (!verdict) return <Pill tone="grey">Awaiting documents</Pill>;
  const [tone, label] = VERDICT[verdict] ?? ["grey", verdict];
  return <Pill tone={tone}>{label}</Pill>;
}
