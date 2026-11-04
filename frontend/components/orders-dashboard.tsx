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
import {
  ArrowRight,
  ClipboardCheck,
  DollarSign,
  Download,
  Package,
  RefreshCw,
  Search,
  ShieldCheck,
  Store,
} from "lucide-react";

import { api, ApiError, money, type OrderSummary } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { PageHeader } from "@/components/brand";
import { PaymentPill, ProtectionPill, ShipmentPill, VerdictPill } from "@/components/status";
import { cn } from "@/lib/utils";

ModuleRegistry.registerModules([AllCommunityModule]);

const theme = themeQuartz.withParams({
  fontFamily: "inherit",
  fontSize: 13.5,
  headerFontSize: 12,
  headerFontWeight: 600,
  headerTextColor: "#64748b",
  headerBackgroundColor: "#f8fafc",
  foregroundColor: "#1e2235",
  borderColor: "#e8ebf1",
  rowBorder: { color: "#eef0f4" },
  columnBorder: false,
  headerColumnBorder: false,
  wrapperBorder: false,
  wrapperBorderRadius: 0,
  rowHeight: 52,
  headerHeight: 42,
  rowHoverColor: "#f6f8fb",
  accentColor: "#10b981",
  spacing: 7,
});

type Row = OrderSummary;

export function OrdersDashboard() {
  const router = useRouter();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
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
        headerName: "Order",
        field: "created_at",
        sort: "desc",
        flex: 1.5,
        minWidth: 190,
        cellRenderer: (p: ICellRendererParams<Row>) =>
          p.data ? (
            <div className="flex h-full flex-col justify-center leading-tight">
              <span className="font-medium">{p.data.item_description ?? "Order"}</span>
              <span className="text-xs text-slate-500">
                {new Date(p.data.created_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
              </span>
            </div>
          ) : null,
      },
      {
        headerName: "Buyer",
        field: "buyer_name",
        flex: 1.3,
        minWidth: 160,
        getQuickFilterText: (p) => `${p.data?.buyer_name ?? ""} ${p.data?.buyer_email_masked ?? ""} ${p.data?.paypal_order_id ?? ""}`,
        cellRenderer: (p: ICellRendererParams<Row>) =>
          p.data ? (
            <div className="flex h-full items-center gap-2.5">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-semibold text-slate-600" aria-hidden>
                {(p.data.buyer_name ?? "?").split(" ").map((w) => w[0]).join("").slice(0, 2)}
              </span>
              <div className="flex min-w-0 flex-col leading-tight">
                <span className="truncate">{p.data.buyer_name ?? "Unknown buyer"}</span>
                <span className="truncate text-xs text-slate-500">{p.data.buyer_email_masked}</span>
              </div>
            </div>
          ) : null,
      },
      {
        headerName: "Amount",
        field: "amount",
        flex: 0.8,
        minWidth: 100,
        type: "rightAligned",
        cellClass: "font-medium tabular-nums",
        valueFormatter: (p) => money(p.value, p.data?.currency ?? "USD"),
        comparator: (a, b) => Number(a) - Number(b),
      },
      { headerName: "Ship to", field: "ship_to", flex: 1, minWidth: 120 },
      {
        headerName: "Payment",
        field: "payment_state",
        flex: 0.9,
        minWidth: 110,
        cellRenderer: (p: ICellRendererParams<Row>) => <PaymentPill state={p.value} />,
      },
      {
        headerName: "Protection",
        headerTooltip: "PayPal Seller Protection status",
        field: "seller_protection_status",
        flex: 1,
        minWidth: 115,
        cellRenderer: (p: ICellRendererParams<Row>) => <ProtectionPill status={p.value} />,
      },
      {
        headerName: "Verdict",
        field: "verdict",
        flex: 1.2,
        minWidth: 155,
        cellRenderer: (p: ICellRendererParams<Row>) => <VerdictPill verdict={p.value} />,
      },
      {
        headerName: "Shipment",
        field: "shipment_state",
        flex: 1,
        minWidth: 115,
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
    const paid = r.filter((o) => o.payment_state === "PAYMENT_COMPLETED");
    const needs = paid.filter((o) => o.shipment_state === "NOT_SHIPPED" && o.verdict !== "GREEN");
    return {
      total: r.length,
      revenue: paid.reduce((s, o) => s + Number(o.amount ?? 0), 0),
      eligible: r.filter((o) => o.seller_protection_status === "ELIGIBLE").length,
      needs,
    };
  }, [rows]);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Seller dashboard"
        title="Orders"
        description="Every PayPal payment with its protected shipping address. Check each order before the parcel leaves."
        actions={
          <>
            <Button variant="outline" size="lg" onClick={load} disabled={loading}>
              <RefreshCw className={loading ? "animate-spin" : ""} aria-hidden /> Refresh
            </Button>
            <Button size="lg" nativeButton={false} render={<Link href="/shop" />}>
              <Store aria-hidden /> Open demo shop
            </Button>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi icon={<Package />} tone="slate" label="Orders" value={rows ? String(stats.total) : "—"} hint="Synced from PayPal" />
        <Kpi icon={<DollarSign />} tone="sky" label="Captured" value={rows ? money(String(stats.revenue), "USD") : "—"} hint="Completed payments" />
        <Kpi
          icon={<ShieldCheck />}
          tone="emerald"
          label="Seller Protection"
          value={rows ? `${stats.eligible}/${stats.total}` : "—"}
          hint="Marked eligible by PayPal"
        />
        <Kpi
          icon={<ClipboardCheck />}
          tone="amber"
          label="Need checks"
          value={rows ? String(stats.needs.length) : "—"}
          hint="Paid, not cleared to ship"
        />
      </div>

      {rows && stats.needs.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-gradient-to-r from-amber-50 to-white px-5 py-4">
          <div>
            <p className="text-sm font-semibold text-amber-950">
              {stats.needs.length} paid {stats.needs.length === 1 ? "order needs" : "orders need"} checking before you ship
            </p>
            <p className="text-[13px] text-amber-900/80">
              Upload the buyer chat and the label photo — StayCovered checks them against the PayPal address.
            </p>
          </div>
          <Button variant="outline" nativeButton={false} render={<Link href={`/orders/${stats.needs[0].id}`} />}>
            Check next order <ArrowRight aria-hidden />
          </Button>
        </div>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertTitle>Couldn&apos;t load orders</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <section className="surface overflow-hidden" aria-label="All orders">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4">
          <div>
            <h2 className="text-[15px] font-semibold">All orders</h2>
            <p className="text-[13px] text-muted-foreground">Click a row to open the order and its checks.</p>
          </div>
          <label className="relative block">
            <span className="sr-only">Search orders</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search buyer or order ID"
              className="h-9 w-64 rounded-lg border bg-white pl-8 pr-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-3 focus-visible:ring-ring/40"
            />
          </label>
        </div>

        {rows && rows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
            <span className="icon-tile size-12 bg-slate-100 text-slate-500">
              <Package className="size-6" aria-hidden />
            </span>
            <p className="font-medium">No orders yet</p>
            <p className="max-w-md text-sm text-muted-foreground">
              Pay for the necklace in the demo shop with your sandbox buyer account. The order appears here with its
              protected address and Seller Protection status from PayPal.
            </p>
            <Button nativeButton={false} render={<Link href="/shop" />}>Go to the demo shop</Button>
          </div>
        ) : rows === null ? (
          <div className="space-y-3 p-5" role="status" aria-label="Loading orders">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-11 animate-pulse rounded-lg bg-muted" />
            ))}
          </div>
        ) : (
          <div style={{ height: Math.min(600, 44 + rows.length * 52 + 2) }}>
            <AgGridReact<Row>
              theme={theme}
              rowData={rows}
              columnDefs={cols}
              quickFilterText={query}
              defaultColDef={{ sortable: true, resizable: true, suppressHeaderMenuButton: true }}
              onRowClicked={(e) => e.data && router.push(`/orders/${e.data.id}`)}
              rowClass="cursor-pointer"
              getRowId={(p) => p.data.id}
              suppressCellFocus
            />
          </div>
        )}
      </section>

      <section className="surface flex flex-wrap items-center justify-between gap-4 px-5 py-4" aria-label="Import a PayPal order">
        <div className="flex items-start gap-3">
          <span className="icon-tile bg-slate-100 text-slate-600 [&_svg]:size-[18px]">
            <Download aria-hidden />
          </span>
          <div>
            <h2 className="text-[15px] font-semibold">Import a PayPal order</h2>
            <p className="text-[13px] text-muted-foreground">Paid outside the demo shop? Sync it from PayPal by order ID.</p>
          </div>
        </div>
        <form onSubmit={onSync} className="flex flex-wrap gap-2">
          <label htmlFor="sync-id" className="sr-only">PayPal order ID</label>
          <input
            id="sync-id"
            value={syncId}
            onChange={(e) => setSyncId(e.target.value.toUpperCase())}
            placeholder="PayPal order ID"
            pattern="[A-Z0-9]{5,64}"
            className="h-9 w-60 rounded-lg border bg-white px-3 font-mono text-sm outline-none placeholder:font-sans placeholder:text-muted-foreground focus-visible:ring-3 focus-visible:ring-ring/40"
            required
          />
          <Button type="submit" variant="secondary" size="lg">Sync from PayPal</Button>
        </form>
        {syncMsg && <p role="alert" className="w-full text-sm text-destructive">{syncMsg}</p>}
      </section>
    </div>
  );
}

const KPI_TONES = {
  slate: "bg-slate-100 text-slate-700",
  sky: "bg-sky-50 text-sky-700",
  emerald: "bg-emerald-50 text-emerald-700",
  amber: "bg-amber-50 text-amber-700",
} as const;

function Kpi({
  icon,
  tone,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  tone: keyof typeof KPI_TONES;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="surface p-5">
      <div className="flex items-center justify-between">
        <p className="text-[13px] font-medium text-muted-foreground">{label}</p>
        <span className={cn("icon-tile size-8 [&_svg]:size-4", KPI_TONES[tone])} aria-hidden>
          {icon}
        </span>
      </div>
      <p className="mt-2 text-[28px] font-semibold leading-none tabular-nums">{value}</p>
      <p className="mt-2 text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}
