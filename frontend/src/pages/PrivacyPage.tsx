import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function PrivacyPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="mx-auto max-w-2xl">
        <CardHeader>
          <CardTitle className="text-2xl">Privacy Policy</CardTitle>
          <CardDescription>Last updated: July 2026</CardDescription>
        </CardHeader>
        <CardContent className="prose prose-sm dark:prose-invert space-y-4 text-muted-foreground">
          <section>
            <h3 className="text-base font-semibold text-foreground">
              Information We Collect
            </h3>
            <p>
              When a customer places an online order through your Clover POS
              system, we collect the following information from your Clover
              merchant account:
            </p>
            <ul className="list-disc pl-5 space-y-1">
              <li>Customer name (first and last name)</li>
              <li>Customer phone number</li>
              <li>Order details (items ordered, order type, order ID)</li>
            </ul>
          </section>

          <section>
            <h3 className="text-base font-semibold text-foreground">
              How We Use This Information
            </h3>
            <p>
              The sole purpose of collecting this data is to send SMS
              notifications to customers informing them that their online order
              is ready for pickup. We do not use this data for any other purpose.
            </p>
          </section>

          <section>
            <h3 className="text-base font-semibold text-foreground">
              Data Storage & Retention
            </h3>
            <p>
              Customer name, phone number, and order information are stored
              securely in our database. We retain order records and their
              corresponding notification history for operational purposes.
              You may request deletion of your data at any time by contacting
              us.
            </p>
          </section>

          <section>
            <h3 className="text-base font-semibold text-foreground">
              Third-Party Services
            </h3>
            <p>We use the following third-party services to operate:</p>
            <ul className="list-disc pl-5 space-y-1">
              <li>
                <strong>Clover</strong> &mdash; We retrieve order and customer
                information via the Clover REST API to process notifications.
              </li>
              <li>
                <strong>Twilio</strong> &mdash; We transmit customer phone
                numbers and names to Twilio for the purpose of delivering SMS
                messages. Twilio&apos;s privacy policy governs how they handle
                this data.
              </li>
            </ul>
          </section>

          <section>
            <h3 className="text-base font-semibold text-foreground">
              Data Sharing
            </h3>
            <p>
              We do not sell, rent, or share customer data with any third
              parties except as required to deliver the SMS notification
              service (Twilio) or as required by law.
            </p>
          </section>

          <section>
            <h3 className="text-base font-semibold text-foreground">
              Contact
            </h3>
            <p>
              If you have any questions about this privacy policy or wish to
              request deletion of your data, please contact the merchant or
              reach out to us through your point of contact.
            </p>
          </section>
        </CardContent>
      </Card>
    </div>
  );
}
