import { Suspense } from "react";
import { DemoShop } from "@/components/demo-shop";

export default function ShopPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading shop…</p>}>
      <DemoShop />
    </Suspense>
  );
}
