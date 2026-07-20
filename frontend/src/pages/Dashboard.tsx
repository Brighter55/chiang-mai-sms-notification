import { useState } from "react";
import { BellRing, Calendar, ChevronDown, ChevronUp, RefreshCcw } from "lucide-react";
import { OrderCard } from "@/components/OrderCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useOrders } from "@/hooks/useOrders";
import type { Order } from "@/lib/api";

/** Returns true if the ISO date string falls on today's date (local tz). */
function isToday(dateStr: string): boolean {
  const d = new Date(dateStr);
  const now = new Date();
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  );
}

export function Dashboard() {
  const { orders, loading, error, refresh, sendSms, sendingId } = useOrders();
  const [showOlder, setShowOlder] = useState(false);

  const todayOrders = orders.filter((o) => isToday(o.created_at));
  const olderOrders = orders.filter((o) => !isToday(o.created_at));

  const pendingCount = orders.filter((o) => o.status === "pending").length;
  const olderPendingCount = olderOrders.filter((o) => o.status === "pending").length;

  function renderOrder(order: Order) {
    return (
      <OrderCard
        key={order.id}
        order={order}
        onSendSms={sendSms}
        isSending={sendingId === order.id}
      />
    );
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container flex h-14 max-w-4xl items-center justify-between">
          <div className="flex items-center gap-3">
            <BellRing className="h-5 w-5" />
            <h1 className="text-lg font-semibold">Order Notifications</h1>
            {pendingCount > 0 && (
              <Badge variant="warning">{pendingCount} pending</Badge>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={refresh}
            disabled={loading}
          >
            <RefreshCcw
              className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`}
            />
            Refresh
          </Button>
        </div>
      </header>

      {/* Content */}
      <main className="container max-w-4xl py-6">
        {error && (
          <div className="mb-6 rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
            {error}
            <Button
              variant="link"
              size="sm"
              className="ml-2 h-auto p-0"
              onClick={refresh}
            >
              Retry
            </Button>
          </div>
        )}

        {loading && orders.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
            <BellRing className="mb-4 h-10 w-10 animate-pulse" />
            <p className="text-lg">Loading orders...</p>
          </div>
        ) : orders.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
            <BellRing className="mb-4 h-10 w-10" />
            <p className="text-lg font-medium">No orders yet</p>
            <p className="text-sm">
              Orders from Clover will appear here automatically.
            </p>
          </div>
        ) : (
          <ScrollArea className="h-[calc(100vh-8rem)]">
            {/* Today's orders */}
            {todayOrders.length > 0 && (
              <div className="mb-6">
                <div className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
                  <Calendar className="h-4 w-4" />
                  <span>Today ({todayOrders.length})</span>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  {todayOrders.map(renderOrder)}
                </div>
              </div>
            )}

            {/* Older orders — hidden behind a toggle */}
            {olderOrders.length > 0 && (
              <div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="mb-3 flex items-center gap-2 text-muted-foreground"
                  onClick={() => setShowOlder(!showOlder)}
                >
                  {showOlder ? (
                    <ChevronUp className="h-4 w-4" />
                  ) : (
                    <ChevronDown className="h-4 w-4" />
                  )}
                  {showOlder
                    ? "Hide older orders"
                    : `Show ${olderOrders.length} older order${olderOrders.length > 1 ? "s" : ""}`}
                  {olderPendingCount > 0 && !showOlder && (
                    <Badge variant="warning" className="ml-1">
                      {olderPendingCount} pending
                    </Badge>
                  )}
                </Button>

                {showOlder && (
                  <div className="grid gap-4 sm:grid-cols-2">
                    {olderOrders.map(renderOrder)}
                  </div>
                )}
              </div>
            )}
          </ScrollArea>
        )}
      </main>
    </div>
  );
}
