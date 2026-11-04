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

export interface UploadInfo {
  id: string;
  kind: "CHAT_IMAGE" | "CHAT_TEXT" | "LABEL_IMAGE";
  mime: string;
  size: number;
  sha256: string;
  sequence: number;
  original_filename: string | null;
  superseded_by: string | null;
  created_at: string;
  url: string;
}

export interface SourceRef {
  upload_id: string;
  position: number;
}

export interface ChatRequestOut {
  type: "ADDRESS_CHANGE" | "PICKUP_OR_COURIER" | "OFF_PLATFORM_PAYMENT" | "NAME_CHANGE" | "OTHER_RISK";
  speaker: "BUYER" | "SELLER" | "UNKNOWN";
  status: "EXPLICIT" | "AMBIGUOUS" | "CANCELLED";
  quote: string;
  source_ref: SourceRef;
  timestamp_text: string | null;
  requested_address: Record<string, string | null> | null;
}

export interface ConversationOutput {
  messages_observed: number;
  conversation_complete: boolean;
  requests: ChatRequestOut[];
  addresses_mentioned: { text: string; source_ref: SourceRef }[];
  issues: string[];
  confidence: number;
}

export interface LabelOutput {
  labels_detected: number;
  recipient_name: string | null;
  address: Record<string, string | null>;
  tracking_number_visible: string | null;
  carrier_visible: string | null;
  readable: boolean;
  issues: string[];
  field_confidence: Record<string, number | null>;
  confidence: number;
}

export interface Extraction<T> {
  id: string;
  agent: string;
  upload_ids: string[];
  provider: string;
  model: string;
  prompt_version: string;
  status: "SUCCEEDED" | "EXTRACTION_FAILED" | "PROVIDER_UNAVAILABLE";
  output: T | null;
  validation_notes: string[] | null;
  confidence: number | null;
  error: string | null;
  attempts: number;
  latency_ms: number | null;
  created_at: string;
}

export interface Evidence {
  verification_state: string;
  uploads: UploadInfo[];
  conversation: Extraction<ConversationOutput>[];
  label: Extraction<LabelOutput>[];
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

async function upload(path: string, form: FormData): Promise<Evidence> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { method: "POST", body: form });
  } catch {
    throw new ApiError("NETWORK", "Can't reach the StayCovered server. Is the backend running?", 0);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(body.error_code || "HTTP_" + res.status, body.message || "Upload failed.", res.status, body.details || {});
  return body as Evidence;
}

export const fileUrl = (u: UploadInfo) => `${API_BASE}${u.url}`;

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
  evidence: (id: string) => request<Evidence>(`/api/orders/${encodeURIComponent(id)}/evidence`),
  rerunExtractions: (id: string) =>
    request<Evidence>(`/api/orders/${encodeURIComponent(id)}/extractions/run`, { method: "POST" }),
  uploadFiles: (id: string, kind: "CHAT_IMAGE" | "LABEL_IMAGE", files: File[]) => {
    const form = new FormData();
    form.append("kind", kind);
    files.forEach((f) => form.append("files", f, f.name));
    return upload(`/api/orders/${encodeURIComponent(id)}/uploads`, form);
  },
  uploadChatText: (id: string, text: string) => {
    const form = new FormData();
    form.append("kind", "CHAT_TEXT");
    form.append("text", text);
    return upload(`/api/orders/${encodeURIComponent(id)}/uploads`, form);
  },
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
