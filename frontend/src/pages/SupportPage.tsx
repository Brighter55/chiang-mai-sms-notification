import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function SupportPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="mx-auto max-w-2xl">
        <CardHeader>
          <CardTitle className="text-2xl">Support</CardTitle>
          <CardDescription>
            Get help with the Order Notifications app
          </CardDescription>
        </CardHeader>
        <CardContent className="prose prose-sm dark:prose-invert space-y-4 text-muted-foreground">
          <section>
            <h3 className="text-base font-semibold text-foreground">
              Contact
            </h3>
            <p>
              For support, questions, or feedback, please email:
            </p>
            <p className="font-medium text-foreground">
              sriphrakhunpiyawit@gmail.com
            </p>
            <p>
              We aim to respond within 1&ndash;2 business days.
            </p>
          </section>

          <section>
            <h3 className="text-base font-semibold text-foreground">
              Common Questions
            </h3>

            <h4 className="text-sm font-medium text-foreground">
              I&apos;m not receiving notifications
            </h4>
            <p>
              Make sure your device has an active internet connection and that
              notifications are enabled in your browser or device settings. If
              using SMS, verify that your Twilio account has sufficient credits.
            </p>

            <h4 className="text-sm font-medium text-foreground">
              Orders aren&apos;t showing up
            </h4>
            <p>
              Verify that your Clover POS is connected and processing online
              orders. Try refreshing the dashboard. If orders still don&apos;t
              appear, check that your API credentials are correct.
            </p>

            <h4 className="text-sm font-medium text-foreground">
              How do I log out?
            </h4>
            <p>
              Click the logout icon (arrow) in the top-right corner of the
              dashboard.
            </p>
          </section>

          <section>
            <h3 className="text-base font-semibold text-foreground">
              Additional Resources
            </h3>
            <ul className="list-disc pl-5 space-y-1">
              <li>
                <a href="/privacy" className="text-primary hover:underline">
                  Privacy Policy
                </a>
              </li>
              <li>
                <a href="/eula" className="text-primary hover:underline">
                  End User License Agreement
                </a>
              </li>
            </ul>
          </section>
        </CardContent>
      </Card>
    </div>
  );
}
