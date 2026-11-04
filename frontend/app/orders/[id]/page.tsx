import { Suspense } from "react";
import { OrderDetailView } from "@/components/order-detail";

export default function OrderPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading order…</p>}>
      <OrderDetailView />
    </Suspense>
  );
}
