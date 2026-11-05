import { Suspense } from "react";
import { PayOrder } from "@/components/pay-order";

export default function PayPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading payment…</p>}>
      <PayOrder />
    </Suspense>
  );
}
