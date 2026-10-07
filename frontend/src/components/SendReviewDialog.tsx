import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { timeAgo } from "@/lib/time";

interface SendReviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  customerName: string;
  /**
   * When this customer was last asked. Optional as well as nullable: a caller
   * whose data predates the field omits it, and that has to mean "never asked".
   */
  reviewSentAt?: string | null;
  onConfirm: () => void;
}

/**
 * Confirmation before a review request goes out.
 *
 * The only guard on a repeat send — the API deliberately allows asking twice,
 * because "this customer already got one" is a judgement staff need to make
 * (they may have been asked months ago, or by a different location). So the
 * wording changes rather than the action being blocked: it says plainly that
 * this customer has already been asked, and by when.
 */
export function SendReviewDialog({
  open,
  onOpenChange,
  customerName,
  reviewSentAt,
  onConfirm,
}: SendReviewDialogProps) {
  // Naming the customer here is safe — this is staff-facing. The *message* stays
  // generic, because that one lands on whatever lock screen it reaches.
  const title = reviewSentAt ? "Already sent a review" : "Send a review request?";
  const description = reviewSentAt
    ? `${customerName} was sent a review request ${timeAgo(reviewSentAt)}. Send a second one?`
    : `This texts ${customerName} a link to leave a 5-star Google review.`;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>
            {reviewSentAt ? "Send again" : "Send review"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
