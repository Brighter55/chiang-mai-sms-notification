import {
  CheckCircle2,
  Clock,
  EllipsisVertical,
  Loader2,
  MessageSquare,
  Phone,
  Star,
  User,
} from "lucide-react";
import { useState } from "react";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SendReviewDialog } from "@/components/SendReviewDialog";
import { timeAgo } from "@/lib/time";
import { cn } from "@/lib/utils";

interface OrderCardProps {
  order: Order;
  onSendSms: (orderId: number) => void;
  isSending: boolean;
  onSendReview: (orderId: number) => void;
  isSendingReview: boolean;
}

const statusConfig: Record<
  Order["status"],
  { label: string; variant: "warning" | "success" | "muted" }
> = {
  pending: { label: "Pending", variant: "warning" },
  notified: { label: "Notified", variant: "success" },
  cancelled: { label: "Cancelled", variant: "muted" },
};

export function OrderCard({
  order,
  onSendSms,
  isSending,
  onSendReview,
  isSendingReview,
}: OrderCardProps) {
  const { label, variant } = statusConfig[order.status];
  const [confirmReview, setConfirmReview] = useState(false);

  return (
    <Card
      data-testid="order-card"
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
          <div className="flex shrink-0 items-center gap-1">
            <Badge variant={variant}>{label}</Badge>
            {/* Cancelled orders get no menu: there is nothing left to act on,
                and asking someone to review food they never received is worse
                than useless. */}
            {order.status !== "cancelled" && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0 text-muted-foreground"
                    aria-label="More actions"
                    title="More actions"
                  >
                    <EllipsisVertical className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    // Disabled rather than hidden, so the menu explains itself
                    // instead of a click that appears to do nothing.
                    disabled={!order.customer_phone || isSendingReview}
                    onSelect={() => setConfirmReview(true)}
                  >
                    <Star className="h-4 w-4" />
                    Send Review
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
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
          {/* Falsy, not `=== null`: a stub that omits the field entirely has to
              read as "never asked" rather than render "Review sent NaN". */}
          {order.review_last_sent_at && (
            <span>· Review sent {timeAgo(order.review_last_sent_at)}</span>
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

      {/* A sibling of the menu, never a child of its content: Radix unmounts the
          menu on select, and nesting the two makes their focus traps fight.
          Portalled, so the card's `overflow-hidden` cannot clip it. */}
      <SendReviewDialog
        open={confirmReview}
        onOpenChange={setConfirmReview}
        customerName={order.customer_name}
        reviewSentAt={order.review_last_sent_at}
        onConfirm={() => {
          setConfirmReview(false);
          onSendReview(order.id);
        }}
      />
    </Card>
  );
}
