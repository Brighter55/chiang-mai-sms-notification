const BASE_URL = import.meta.env.VITE_API_URL || "/api";

// ---------------------------------------------------------------------------
// CSRF helper — Django requires the CSRF token as a header on unsafe methods
// when using session authentication across origins.
// ---------------------------------------------------------------------------
// CSRF token for cross-origin session auth — captured from the login/me
// JSON responses because the csrftoken cookie is host-scoped to the API
// domain and is not readable from this origin's JavaScript.
let csrfToken: string | null = null;

function setCsrfToken(token?: string) {
  if (token) csrfToken = token;
}

function getCsrfToken(): string {
  if (csrfToken) return csrfToken;
  // Fallback for local dev (localhost:5173 -> localhost:8000 share a host,
  // so the cookie IS readable there)
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
  return match ? match[1] : "";
}

function isUnsafe(method: string): boolean {
  return ["POST", "PUT", "PATCH", "DELETE"].includes(method.toUpperCase());
}

// ---------------------------------------------------------------------------
// Auth state
// ---------------------------------------------------------------------------
let onAuthError: (() => void) | null = null;

export function setOnAuthError(callback: (() => void) | null) {
  onAuthError = callback;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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
  /**
   * When this order's *phone* was last sent a review request, or null.
   * Keyed on the phone, so a repeat customer carries it on every order they
   * place — the staff member opening the newest one still sees they were asked.
   */
  review_last_sent_at: string | null;
  notifications?: NotificationLog[];
}

export interface ReviewRequest {
  id: number;
  /** Null when the order it referred to has since been deleted. */
  order: number | null;
  recipient_phone: string;
  message_body: string;
  status: "sent" | "failed";
  twilio_sid: string | null;
  error_message: string | null;
  created_at: string;
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

export interface User {
  id: number;
  username: string;
  csrf_token?: string;
}

// ---------------------------------------------------------------------------
// Fetch wrapper
// ---------------------------------------------------------------------------

async function request<T>(
  url: string,
  options?: RequestInit
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string> | undefined),
  };

  // Attach CSRF token for unsafe methods (Django session auth)
  if (!options?.method || isUnsafe(options.method)) {
    const token = getCsrfToken();
    if (token) {
      headers["X-CSRFToken"] = token;
    }
  }

  const res = await fetch(`${BASE_URL}${url}`, {
    credentials: "include",
    ...options,
    headers,
  });

  if (res.status === 401 && onAuthError) {
    onAuthError();
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      (body as { error?: string }).error || `Request failed: ${res.status}`
    );
  }

  return res.json();
}

// ---------------------------------------------------------------------------
// Auth API
// ---------------------------------------------------------------------------

export function login(username: string, password: string): Promise<User> {
  return request<User>("/login/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  }).then((user) => {
    setCsrfToken(user.csrf_token);
    return user;
  });
}

export function logout(): Promise<{ ok: boolean }> {
  return request("/logout/", { method: "POST" });
}

export function fetchMe(): Promise<User> {
  return request<User>("/me/").then((user) => {
    setCsrfToken(user.csrf_token);
    return user;
  });
}

// ---------------------------------------------------------------------------
// Orders API
// ---------------------------------------------------------------------------

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

/**
 * Text the order's customer a Google review link.
 *
 * Unlike `sendSms` this never 409s: asking twice is a decision the confirmation
 * dialog puts to staff, so the API accepts it.
 */
export function sendReview(orderId: number): Promise<ReviewRequest> {
  return request(`/orders/${orderId}/review/`, { method: "POST" });
}

export interface SyncResult {
  created: number;
  updated: number;
  skipped: number;
  errors: number;
}

/** Pull recent orders from Clover into the local database (manual refresh). */
export function syncOrders(): Promise<SyncResult> {
  return request("/orders/sync/", { method: "POST" });
}

export function fetchLogs(): Promise<{ count: number; results: NotificationLog[] }> {
  return request("/logs/");
}
