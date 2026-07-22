import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function EulaPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="mx-auto max-w-2xl">
        <CardHeader>
          <CardTitle className="text-2xl">
            End User License Agreement
          </CardTitle>
          <CardDescription>Last updated: July 2026</CardDescription>
        </CardHeader>
        <CardContent className="prose prose-sm dark:prose-invert space-y-4 text-muted-foreground">
          <section>
            <h3 className="text-base font-semibold text-foreground">
              1. Grant of License
            </h3>
            <p>
              This application is licensed, not sold, to you for use solely in
              connection with your Clover POS system. Subject to the terms of
              this agreement, you are granted a limited, non-exclusive,
              non-transferable, revocable license to use the application for
              the purpose of sending SMS order-ready notifications to your
              customers.
            </p>
          </section>

          <section>
            <h3 className="text-base font-semibold text-foreground">
              2. Restrictions
            </h3>
            <p>You may not:</p>
            <ul className="list-disc pl-5 space-y-1">
              <li>
                Copy, modify, or create derivative works of the application
                except as expressly permitted.
              </li>
              <li>
                Reverse engineer, decompile, or disassemble the application.
              </li>
              <li>
                Use the application for any unlawful purpose or in violation
                of any applicable laws or regulations.
              </li>
              <li>
                Use the application to send unsolicited messages (spam) or
                messages for any purpose other than legitimate order-ready
                notifications.
              </li>
              <li>
                Transfer, sublicense, or lease the application to any third
                party.
              </li>
            </ul>
          </section>

          <section>
            <h3 className="text-base font-semibold text-foreground">
              3. Disclaimer of Warranties
            </h3>
            <p>
              The application is provided &quot;as is&quot; and &quot;as
              available&quot; without warranty of any kind, express or implied,
              including but not limited to the warranties of merchantability,
              fitness for a particular purpose, and non-infringement. The
              developer does not warrant that the application will be
              uninterrupted or error-free.
            </p>
          </section>

          <section>
            <h3 className="text-base font-semibold text-foreground">
              4. Limitation of Liability
            </h3>
            <p>
              In no event shall the developer be liable for any indirect,
              incidental, special, consequential, or punitive damages arising
              out of or relating to your use of the application, including but
              not limited to failed message delivery, data loss, or business
              interruption, even if advised of the possibility of such damages.
            </p>
          </section>

          <section>
            <h3 className="text-base font-semibold text-foreground">
              5. Compliance with Laws
            </h3>
            <p>
              You are responsible for ensuring that your use of this
              application complies with all applicable laws and regulations,
              including but not limited to telephone consumer protection laws
              and data privacy regulations. You must obtain any necessary
              consent from customers before sending SMS notifications.
            </p>
          </section>

          <section>
            <h3 className="text-base font-semibold text-foreground">
              6. Termination
            </h3>
            <p>
              This license is effective until terminated. Your rights under
              this agreement will terminate automatically without notice if
              you fail to comply with any of its terms. Upon termination, you
              must cease all use of the application.
            </p>
          </section>

          <section>
            <h3 className="text-base font-semibold text-foreground">
              7. Governing Law
            </h3>
            <p>
              This agreement shall be governed by and construed in accordance
              with the applicable laws, without regard to its conflict of law
              provisions.
            </p>
          </section>
        </CardContent>
      </Card>
    </div>
  );
}
