import { useCallback, useEffect, useState } from "react";
import {
  fetchOrders,
  sendSms as sendSmsApi,
  syncOrders,
  type Order,
} from "@/lib/api";
import { toast } from "@/hooks/use-toast";

interface UseOrdersReturn {
  orders: Order[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  sendSms: (orderId: number) => Promise<void>;
  sendingId: number | null;
}

export function useOrders(): UseOrdersReturn {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sendingId, setSendingId] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      // Pull new orders from Clover first, then reload the local list.
      // A Clover failure must not blank the dashboard, so continue anyway.
      let synced = { created: 0, updated: 0, skipped: 0, errors: 0 };
      try {
        synced = await syncOrders();
      } catch (err) {
        toast({
          title: "Clover sync failed",
          description:
            err instanceof Error ? err.message : "Could not reach Clover",
          variant: "destructive",
        });
      }
      const newOrUpdated = synced.created + synced.updated;
      if (newOrUpdated > 0) {
        toast({
          title: "Orders pulled from Clover",
          description: `${newOrUpdated} new or updated order${newOrUpdated > 1 ? "s" : ""}.`,
        });
      }
      const data = await fetchOrders();
      setOrders(data.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load orders");
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load — a single fetch on mount, then manual refreshes only
  useEffect(() => {
    refresh();
  }, [refresh]);

  const sendSms = useCallback(
    async (orderId: number) => {
      setSendingId(orderId);
      try {
        const result = await sendSmsApi(orderId);
        if (result.status === "sent") {
          // Optimistically update the order in local state
          setOrders((prev) =>
            prev.map((o) =>
              o.id === orderId
                ? { ...o, status: "notified" as const, notified_at: new Date().toISOString() }
                : o
            )
          );
          toast({
            title: "SMS sent!",
            description: "Customer has been notified.",
          });
        } else {
          toast({
            title: "SMS failed",
            description: result.error_message || "Unknown error",
            variant: "destructive",
          });
        }
      } catch (err) {
        toast({
          title: "SMS failed",
          description:
            err instanceof Error ? err.message : "Could not send SMS",
          variant: "destructive",
        });
      } finally {
        setSendingId(null);
      }
    },
    []
  );

  return { orders, loading, error, refresh, sendSms, sendingId };
}
