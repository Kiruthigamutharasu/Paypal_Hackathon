// Status pills: always a text label + colour dot (never colour alone), WCAG AA contrast.
import { cn } from "@/lib/utils";

export type Tone = "green" | "amber" | "red" | "grey" | "blue" | "violet";

const TONES: Record<Tone, { pill: string; dot: string }> = {
  green: { pill: "bg-emerald-50 text-emerald-800 ring-emerald-600/15", dot: "bg-emerald-500" },
  amber: { pill: "bg-amber-50 text-amber-900 ring-amber-600/20", dot: "bg-amber-500" },
  red: { pill: "bg-red-50 text-red-800 ring-red-600/15", dot: "bg-red-500" },
  grey: { pill: "bg-slate-100 text-slate-700 ring-slate-500/15", dot: "bg-slate-400" },
  blue: { pill: "bg-sky-50 text-sky-800 ring-sky-600/15", dot: "bg-sky-500" },
  violet: { pill: "bg-violet-50 text-violet-800 ring-violet-600/15", dot: "bg-violet-500" },
};

export function Pill({
  tone,
  children,
  className,
  dot = true,
}: {
  tone: Tone;
  children: React.ReactNode;
  className?: string;
  dot?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        TONES[tone].pill,
        className,
      )}
    >
      {dot && <span className={cn("size-1.5 rounded-full", TONES[tone].dot)} aria-hidden />}
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
  LABEL_CHECKED: ["green", "Label checked"],
  SHIPPED: ["green", "Shipped"],
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
  if (!verdict) return <Pill tone="violet">Awaiting checks</Pill>;
  const [tone, label] = VERDICT[verdict] ?? ["grey", verdict];
  return <Pill tone={tone}>{label}</Pill>;
}
