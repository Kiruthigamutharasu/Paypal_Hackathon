"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AgGridReact } from "ag-grid-react";
import {
  AllCommunityModule,
  ModuleRegistry,
  themeQuartz,
  type ColDef,
  type ICellRendererParams,
} from "ag-grid-community";
import { RefreshCw, Store } from "lucide-react";

import { api, ApiError, money, type OrderSummary } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { PaymentPill, ProtectionPill, ShipmentPill, VerdictPill } from "@/components/status";

ModuleRegistry.registerModules([AllCommunityModule]);

const theme = themeQuartz.withParams({
  fontFamily: "inherit",
  headerFontWeight: 600,
  borderRadius: 8,
  wrapperBorderRadius: 12,
  rowHeight: 48,
});

type Row = OrderSummary;

export function OrdersDashboard() {
  const router = useRouter();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncId, setSyncId] = useState("");
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRows(await api.listOrders());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load orders.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .listOrders()
      .then((r) => !cancelled && setRows(r))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load orders."));
    return () => {
      cancelled = true;
    };
  }, []);

  const cols = useMemo<ColDef<Row>[]>(
    () => [
      {
        headerName: "Created",
        field: "created_at",
        sort: "desc",
        width: 150,
        valueFormatter: (p) =>
          p.value ? new Date(p.value).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "",
      },
      {
        headerName: "Buyer",
        field: "buyer_email_masked",
        flex: 1,
        minWidth: 180,
        valueGetter: (p) => [p.data?.buyer_name, p.data?.buyer_email_masked].filter(Boolean).join(" · "),
      },
      {
        headerName: "Amount",
        field: "amount",
        width: 110,
        type: "rightAligned",
        valueFormatter: (p) => money(p.value, p.data?.currency ?? "USD"),
        comparator: (a, b) => Number(a) - Number(b),
      },
      { headerName: "Ship to", field: "ship_to", width: 140 },
      {
        headerName: "Payment",
        field: "payment_state",
        width: 150,
        cellRenderer: (p: ICellRendererParams<Row>) => <PaymentPill state={p.value} />,
      },
      {
        headerName: "Seller Protection",
        field: "seller_protection_status",
        width: 160,
        cellRenderer: (p: ICellRendererParams<Row>) => <ProtectionPill status={p.value} />,
      },
      {
        headerName: "Verdict",
        field: "verdict",
        width: 170,
        cellRenderer: (p: ICellRendererParams<Row>) => <VerdictPill verdict={p.value} />,
      },
      {
        headerName: "Shipment",
        field: "shipment_state",
        width: 150,
        cellRenderer: (p: ICellRendererParams<Row>) => <ShipmentPill state={p.value} />,
      },
    ],
    [],
  );

  async function onSync(e: React.FormEvent) {
    e.preventDefault();
    setSyncMsg(null);
    try {
      const o = await api.syncOrder(syncId.trim());
      router.push(`/orders/${o.id}`);
    } catch (err) {
      setSyncMsg(err instanceof ApiError ? err.message : "Sync failed.");
    }
  }

  const stats = useMemo(() => {
    const r = rows ?? [];
    return {
      total: r.length,
      paid: r.filter((o) => o.payment_state === "PAYMENT_COMPLETED").length,
      awaiting: r.filter((o) => o.payment_state === "PAYMENT_COMPLETED" && o.shipment_state === "NOT_SHIPPED").length,
    };
  }, [rows]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Orders</h1>
          <p className="text-sm text-muted-foreground">
            PayPal payments and their protected shipping address. Check every order before you ship.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className={loading ? "animate-spin" : ""} aria-hidden /> Refresh
          </Button>
          <Button nativeButton={false} render={<Link href="/shop" />}>
            <Store aria-hidden /> Open demo shop
          </Button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Orders" value={stats.total} />
        <Stat label="Paid" value={stats.paid} />
        <Stat label="Paid, not shipped yet" value={stats.awaiting} />
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertTitle>Couldn&apos;t load orders</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardContent className="p-0">
          {rows && rows.length === 0 ? (
            <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
              <p className="font-medium">No orders yet</p>
              <p className="max-w-md text-sm text-muted-foreground">
                Pay for the necklace in the demo shop with your sandbox buyer account. The order appears here with its
                protected address and Seller Protection status from PayPal.
              </p>
              <Button nativeButton={false} render={<Link href="/shop" />}>Go to the demo shop</Button>
            </div>
          ) : (
            <div style={{ height: Math.min(560, 56 + (rows?.length ?? 6) * 48 + 8) }}>
              <AgGridReact<Row>
                theme={theme}
                rowData={rows ?? undefined}
                loading={rows === null}
                columnDefs={cols}
                defaultColDef={{ sortable: true, filter: true, resizable: true }}
                onRowClicked={(e) => e.data && router.push(`/orders/${e.data.id}`)}
                rowClass="cursor-pointer"
                getRowId={(p) => p.data.id}
              />
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Import a PayPal order</CardTitle>
          <CardDescription>Paid outside the demo shop? Paste its PayPal order ID to sync it from PayPal.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSync} className="flex flex-wrap gap-2">
            <label htmlFor="sync-id" className="sr-only">PayPal order ID</label>
            <input
              id="sync-id"
              value={syncId}
              onChange={(e) => setSyncId(e.target.value.toUpperCase())}
              placeholder="e.g. 5O190127TN364715T"
              pattern="[A-Z0-9]{5,64}"
              className="h-8 w-72 rounded-lg border bg-background px-2.5 font-mono text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              required
            />
            <Button type="submit" variant="secondary">Sync from PayPal</Button>
          </form>
          {syncMsg && <p role="alert" className="mt-2 text-sm text-destructive">{syncMsg}</p>}
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Card size="sm">
      <CardContent>
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="text-2xl font-semibold tabular-nums">{value}</p>
      </CardContent>
    </Card>
  );
}
