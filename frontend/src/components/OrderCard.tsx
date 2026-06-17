import { Loader2, Phone, ShoppingBag, User } from "lucide-react";
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
  { label: string; variant: "warning" | "success" | "destructive" }
> = {
  pending: { label: "Pending", variant: "warning" },
  notified: { label: "Notified", variant: "success" },
  cancelled: { label: "Cancelled", variant: "destructive" },
};

export function OrderCard({ order, onSendSms, isSending }: OrderCardProps) {
  const { label, variant } = statusConfig[order.status];

  return (
    <Card
      className={cn(
        "transition-opacity",
        order.status === "notified" && "opacity-75"
      )}
    >
      <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
        <div className="space-y-1">
          <CardTitle className="text-base font-semibold">
            {order.items_summary || `Order #${order.clover_order_id.slice(-8)}`}
          </CardTitle>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <User className="h-3.5 w-3.5" />
            <span>{order.customer_name}</span>
          </div>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Phone className="h-3.5 w-3.5" />
            <span>{order.customer_phone || "No phone"}</span>
          </div>
        </div>
        <Badge variant={variant}>{label}</Badge>
      </CardHeader>

      <CardContent className="pb-2">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <ShoppingBag className="h-3 w-3" />
          <span>Ordered {timeAgo(order.created_at)}</span>
          {order.notified_at && (
            <span>
              · Notified {timeAgo(order.notified_at)}
            </span>
          )}
        </div>
      </CardContent>

      <CardFooter>
        {order.status === "pending" ? (
          <Button
            onClick={() => onSendSms(order.id)}
            disabled={isSending || !order.customer_phone}
            size="sm"
            className="w-full"
          >
            {isSending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {isSending ? "Sending..." : "Send SMS"}
          </Button>
        ) : order.status === "notified" ? (
          <p className="w-full text-center text-sm text-muted-foreground">
            ✓ SMS sent
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
