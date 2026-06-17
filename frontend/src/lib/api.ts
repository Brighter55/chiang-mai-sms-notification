const BASE_URL = "/api";

export interface Order {
  id: number;
  clover_order_id: string;
  customer_name: string;
  customer_phone: string;
  items_summary: string;
  status: "pending" | "notified" | "cancelled";
  created_at: string;
  notified_at: string | null;
  notification_count: number;
  notifications?: NotificationLog[];
}

export interface NotificationLog {
  id: number;
  order: number;
  recipient_phone: string;
  message_body: string;
  status: "sent" | "failed";
  twilio_sid: string | null;
  error_message: string | null;
  created_at: string;
}

async function request<T>(
  url: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE_URL}${url}`, {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      (body as { error?: string }).error || `Request failed: ${res.status}`
    );
  }

  return res.json();
}

export function fetchOrders(params?: {
  status?: string;
}): Promise<{ count: number; results: Order[] }> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set("status", params.status);
  const qs = searchParams.toString();
  return request(`/orders/${qs ? `?${qs}` : ""}`);
}

export function fetchOrder(id: number): Promise<Order> {
  return request(`/orders/${id}/`);
}

export function sendSms(orderId: number): Promise<NotificationLog> {
  return request(`/orders/${orderId}/send/`, { method: "POST" });
}

export function fetchLogs(): Promise<{ count: number; results: NotificationLog[] }> {
  return request("/logs/");
}
