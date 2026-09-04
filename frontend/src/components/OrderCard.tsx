import {
  CheckCircle2,
  Clock,
  Loader2,
  MessageSquare,
  Phone,
  User,
} from "lucide-react";
import type { Order } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface OrderCardProps {
  order: Order;
  onSendSms: (orderId: number) => void;
  isSending: boolean;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

const statusConfig: Record<
  Order["status"],
  { label: string; variant: "warning" | "success" | "muted" }
> = {
  pending: { label: "Pending", variant: "warning" },
  notified: { label: "Notified", variant: "success" },
  cancelled: { label: "Cancelled", variant: "muted" },
};

export function OrderCard({ order, onSendSms, isSending }: OrderCardProps) {
  const { label, variant } = statusConfig[order.status];

  return (
    <Card
      className={cn(
        "relative overflow-hidden border-border/40 bg-surface-low shadow-none transition-opacity hover:border-border hover:shadow-md",
        order.status === "notified" && "opacity-75"
      )}
    >
      {order.status === "pending" && (
        <div
          aria-hidden
          className="absolute inset-y-0 left-0 w-1 bg-primary"
        />
      )}

      <CardHeader className="space-y-3 p-5 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Order #{order.clover_order_id.slice(-8)}
            </p>
            {order.items_summary && (
              <CardTitle className="line-clamp-2 text-base font-semibold leading-snug">
                {order.items_summary}
              </CardTitle>
            )}
          </div>
          <Badge variant={variant} className="shrink-0">
            {label}
          </Badge>
        </div>

        <div className="grid grid-cols-2 divide-x divide-border/60 overflow-hidden rounded-md border border-border/40 bg-background/60 text-xs text-muted-foreground">
          <div className="flex min-w-0 items-center gap-1.5 px-3 py-2">
            <User className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{order.customer_name}</span>
          </div>
          <div className="flex min-w-0 items-center gap-1.5 px-3 py-2">
            <Phone className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">
              {order.customer_phone || "No phone"}
            </span>
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-5 pt-0">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock className="h-3 w-3 shrink-0" />
          <span>Ordered {timeAgo(order.created_at)}</span>
          {order.notified_at && (
            <span>· Notified {timeAgo(order.notified_at)}</span>
          )}
        </div>
      </CardContent>

      <CardFooter className="p-5 pt-0">
        {order.status === "pending" ? (
          <Button
            onClick={() => onSendSms(order.id)}
            disabled={isSending || !order.customer_phone}
            size="sm"
            className="w-full"
          >
            {isSending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <MessageSquare className="mr-2 h-4 w-4" />
            )}
            {isSending ? "Sending..." : "Send SMS"}
          </Button>
        ) : order.status === "notified" ? (
          <p className="flex w-full items-center justify-center gap-1.5 text-sm text-tertiary">
            <CheckCircle2 className="h-4 w-4" />
            SMS sent
          </p>
        ) : (
          <p className="w-full text-center text-sm text-muted-foreground">
            Order cancelled
          </p>
        )}
      </CardFooter>
    </Card>
  );
}
