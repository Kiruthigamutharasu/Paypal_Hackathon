import { Suspense } from "react";
import { DisputeDetailView } from "@/components/dispute-detail";

export default function DisputeDetailPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading dispute…</p>}>
      <DisputeDetailView />
    </Suspense>
  );
}
