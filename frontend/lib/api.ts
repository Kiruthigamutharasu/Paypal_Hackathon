// Typed client for the StayCovered FastAPI backend. The browser never calls PayPal REST.

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export type PaymentState =
  | "PAYMENT_PENDING"
  | "PAYMENT_COMPLETED"
  | "PAYMENT_FAILED"
  | "PARTIALLY_REFUNDED"
  | "REFUNDED"
  | "REVERSED";

export interface OrderSummary {
  id: string;
  paypal_order_id: string;
  created_at: string;
  buyer_name: string | null;
  buyer_email_masked: string | null;
  amount: string | null;
  currency: string | null;
  item_description: string | null;
  payment_state: PaymentState;
  verification_state: string;
  shipment_state: string;
  seller_protection_status: string;
  verdict: string | null;
  dispute_state: string | null;
  ship_to: string | null;
}

export interface Address {
  version: number;
  name: string | null;
  line1: string | null;
  line2: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  country: string | null;
  source: string;
  created_at: string;
}

export interface CaptureInfo {
  paypal_capture_id: string;
  status: string;
  status_reason: string | null;
  amount: string | null;
  currency: string | null;
  seller_protection_status: string;
  dispute_categories: string[] | null;
  paypal_create_time: string | null;
  fetched_at: string;
}

export interface AuditEntry {
  id: string;
  actor: string;
  action: string;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface OrderDetail extends OrderSummary {
  paypal_status: string | null;
  last_synced_at: string | null;
  capture: CaptureInfo | null;
  captures: CaptureInfo[];
  protected_address: Address | null;
  address_history: Address[];
  timeline: AuditEntry[];
}

export interface Product {
  sku: string;
  name: string;
  description: string;
  price: string;
  currency: string;
}

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError("NETWORK", "Can't reach the StayCovered server. Is the backend running?", 0);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(
      body.error_code || "HTTP_" + res.status,
      body.message || "Request failed.",
      res.status,
      body.details || {},
    );
  }
  return body as T;
}

export const api = {
  listOrders: () => request<OrderSummary[]>("/api/orders"),
  getOrder: (id: string) => request<OrderDetail>(`/api/orders/${encodeURIComponent(id)}`),
  refreshOrder: (id: string) =>
    request<OrderDetail>(`/api/orders/${encodeURIComponent(id)}/refresh`, { method: "POST" }),
  syncOrder: (paypalOrderId: string) =>
    request<OrderDetail>("/api/orders/sync", {
      method: "POST",
      body: JSON.stringify({ paypal_order_id: paypalOrderId }),
    }),
  products: () => request<Product[]>("/api/shop/products"),
  createShopOrder: (sku: string) =>
    request<{ orderId: string }>("/api/shop/orders", {
      method: "POST",
      body: JSON.stringify({ sku, quantity: 1 }),
    }),
  captureShopOrder: (paypalOrderId: string) =>
    request<{ order_id: string; paypal_order_id: string; payment_state: string; seller_protection_status: string }>(
      `/api/shop/orders/${encodeURIComponent(paypalOrderId)}/capture`,
      { method: "POST" },
    ),
};

export function money(amount: string | null, currency: string | null): string {
  if (amount == null) return "—";
  const n = Number(amount);
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "USD" }).format(n);
  } catch {
    return `${amount} ${currency ?? ""}`.trim();
  }
}

export function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
