import { Pill } from "@/components/status";

export const REASON: Record<string, string> = {
  MERCHANDISE_OR_SERVICE_NOT_RECEIVED: "Item not received",
  UNAUTHORISED: "Unauthorised payment",
  UNAUTHORIZED: "Unauthorised payment",
  MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED: "Not as described",
  DUPLICATE_TRANSACTION: "Duplicate transaction",
  CREDIT_NOT_PROCESSED: "Credit not processed",
};

export function DisputeStatusPill({ status, outcome }: { status: string | null; outcome?: string | null }) {
  if (outcome) {
    const seller = /SELLER/i.test(outcome);
    return <Pill tone={seller ? "green" : "red"}>{seller ? "Resolved in your favour" : "Resolved for buyer"}</Pill>;
  }
  const map: Record<string, [Parameters<typeof Pill>[0]["tone"], string]> = {
    WAITING_FOR_SELLER_RESPONSE: ["amber", "Your response needed"],
    WAITING_FOR_BUYER_RESPONSE: ["blue", "Waiting for buyer"],
    UNDER_REVIEW: ["violet", "PayPal reviewing"],
    OPEN: ["amber", "Open"],
    RESOLVED: ["grey", "Resolved"],
  };
  const [tone, label] = map[status ?? ""] ?? ["grey", status ?? "—"];
  return <Pill tone={tone}>{label}</Pill>;
}

export function DeadlineChip({ due, flag, hoursLeft }: { due: string | null; flag: string | null; hoursLeft: number | null }) {
  if (!due || hoursLeft == null) return null;
  const d = new Date(due);
  const hours = hoursLeft;
  if (flag === "DIS-11") return <Pill tone="red">Deadline passed</Pill>;
  const text = hours < 48 ? `${Math.max(hours, 0)} h left` : `${Math.round(hours / 24)} days left`;
  return <Pill tone={flag === "DIS-10" ? "red" : "grey"}>{flag === "DIS-10" ? `Due soon · ${text}` : `Respond by ${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })} · ${text}`}</Pill>;
}
