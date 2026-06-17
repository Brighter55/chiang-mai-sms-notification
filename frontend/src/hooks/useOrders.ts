import { useCallback, useEffect, useState } from "react";
import { fetchOrders, sendSms as sendSmsApi, type Order } from "@/lib/api";
import { toast } from "@/hooks/use-toast";

interface UseOrdersReturn {
  orders: Order[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
  sendSms: (orderId: number) => Promise<void>;
  sendingId: number | null;
}

export function useOrders(pollIntervalMs = 15_000): UseOrdersReturn {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sendingId, setSendingId] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const data = await fetchOrders();
      setOrders(data.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load orders");
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load + polling
  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, pollIntervalMs);
    return () => clearInterval(interval);
  }, [refresh, pollIntervalMs]);

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
