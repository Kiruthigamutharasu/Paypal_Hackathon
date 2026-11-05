import { Suspense } from "react";
import { DisputesList } from "@/components/disputes-list";

export default function DisputesPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading disputes…</p>}>
      <DisputesList />
    </Suspense>
  );
}
