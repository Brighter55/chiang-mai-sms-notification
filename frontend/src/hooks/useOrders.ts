import { useCallback, useEffect, useRef, useState } from "react";
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
  syncing: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  sendSms: (orderId: number) => Promise<void>;
  sendingId: number | null;
}

/**
 * What a refresh is for. The distinction that matters is that only two of these
 * touch Clover: a sync costs 2 Clover API requests, a list read costs nothing.
 *
 * - "manual" — a person clicked Refresh. Always runs, always reports back.
 * - "sync"   — the Clover timer. Same pull, but invisible.
 * - "list"   — the list timer. Re-reads local orders only.
 */
type RefreshMode = "manual" | "sync" | "list";

interface UseOrdersOptions {
  /** How often to pull from Clover. Each run costs 2 Clover requests. */
  syncIntervalMs: number;
  /** How often to re-read the local order list. No Clover round trip. */
  listIntervalMs: number;
}

export function useOrders({
  syncIntervalMs,
  listIntervalMs,
}: UseOrdersOptions): UseOrdersReturn {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sendingId, setSendingId] = useState<number | null>(null);

  // Timer callbacks close over their values once. Reading `sendingId` state
  // directly in them would see whatever it was when the timer was created, so
  // the guards below consult refs instead.
  const sendingIdRef = useRef<number | null>(null);
  const busyRef = useRef(false);
  // null until the first sync completes — Date.now() is impure and cannot be
  // called during render to seed a ref.
  const lastSyncAtRef = useRef<number | null>(null);
  const latestLoadRef = useRef(0);

  useEffect(() => {
    sendingIdRef.current = sendingId;
  }, [sendingId]);

  /** Reload the orders we already have. No Clover round trip, so this is fast. */
  const loadOrders = useCallback(async () => {
    const requestId = (latestLoadRef.current += 1);
    const data = await fetchOrders();
    // Drop a response that is no longer the newest. Without this, a poll that
    // started before a Send can resolve after the optimistic update in sendSms
    // below and revert the card to "pending".
    if (requestId !== latestLoadRef.current) return;
    setOrders(data.results);
  }, []);

  const runRefresh = useCallback(
    async (mode: RefreshMode) => {
      if (mode !== "manual") {
        // A hidden tab is not being watched: polling it would spend Clover
        // quota and DB reads on nobody's behalf. Coming back into view runs a
        // catch-up instead.
        if (document.visibilityState === "hidden") return;
        // A Send is mid-flight, and reloading now could race its optimistic
        // update. The next tick picks it up.
        if (sendingIdRef.current !== null) return;
        // One cycle at a time, so a slow sync cannot have a poll pile onto it.
        if (busyRef.current) return;
      }

      busyRef.current = true;
      if (mode === "manual") setSyncing(true);

      try {
        if (mode === "manual") setError(null);

        if (mode !== "list") {
          // Stamped on attempt, not success: a failing Clover should not make
          // the next visibility change retry immediately.
          lastSyncAtRef.current = Date.now();
          try {
            const synced = await syncOrders();
            if (mode === "manual") {
              const newOrUpdated = synced.created + synced.updated;
              if (newOrUpdated > 0) {
                toast({
                  title: "Orders pulled from Clover",
                  description: `${newOrUpdated} new or updated order${newOrUpdated > 1 ? "s" : ""}.`,
                });
              }
            }
          } catch (err) {
            // Only a person who asked for a sync needs to hear that it failed.
            // A background one stays quiet: the list below still shows local
            // orders, and the next tick retries.
            if (mode === "manual") {
              toast({
                title: "Clover sync failed",
                description:
                  err instanceof Error ? err.message : "Could not reach Clover",
                variant: "destructive",
              });
            }
          }
        }

        await loadOrders();
        // Clears a banner left by an earlier failure. Setting null when it is
        // already null is a no-op for React, so this costs nothing when healthy.
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load orders");
      } finally {
        busyRef.current = false;
        if (mode === "manual") setSyncing(false);
      }
    },
    [loadOrders]
  );

  /** The Refresh button. Takes no arguments on purpose — `onClick={refresh}`
   *  in Dashboard.tsx would otherwise hand it the click event. */
  const refresh = useCallback(() => runRefresh("manual"), [runRefresh]);

  // Each timer owns one cadence and depends only on its own value, so editing
  // the Clover box restarts the Clover countdown and leaves the list alone.
  useEffect(() => {
    const id = window.setInterval(
      () => void runRefresh("sync"),
      syncIntervalMs
    );
    return () => window.clearInterval(id);
  }, [runRefresh, syncIntervalMs]);

  useEffect(() => {
    const id = window.setInterval(
      () => void runRefresh("list"),
      listIntervalMs
    );
    return () => window.clearInterval(id);
  }, [runRefresh, listIntervalMs]);

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState !== "visible") return;
      // Catch up on the way back, but only pay for Clover if the sync timer is
      // genuinely overdue — otherwise every alt-tab would cost 2 requests.
      const lastSyncAt = lastSyncAtRef.current;
      const overdue =
        lastSyncAt === null || Date.now() - lastSyncAt >= syncIntervalMs;
      void runRefresh(overdue ? "sync" : "list");
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () =>
      document.removeEventListener("visibilitychange", onVisibilityChange);
  }, [runRefresh, syncIntervalMs]);

  // Show what we already have straight away, then pull from Clover in the
  // background — opening the dashboard never waits on the Clover API.
  useEffect(() => {
    // Deliberate. This effect is the bootstrap: paint the local orders we
    // already have, then start the Clover pull in the background, so opening
    // the dashboard never waits on the Clover API.
    loadOrders()
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load orders");
      })
      .finally(() => setLoading(false));
    // refresh() sets `syncing` before it awaits, which is what the rule objects
    // to. That flag is the point — it drives the button's spinner for the first
    // sync — and deferring it to dodge a heuristic would change visible
    // behaviour. The alternative the rule implies (a framework data-loader) is
    // not available to a plain client-side SPA.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, [loadOrders, refresh]);

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

  return { orders, loading, syncing, error, refresh, sendSms, sendingId };
}
