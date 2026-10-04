import { Card } from "@/components/ui";

export function DonePage() {
  return (
    <div className="mx-auto max-w-lg p-8">
      <Card className="p-8 text-center">
        <h1 className="text-lg font-semibold">Thank you</h1>
        <p className="mt-2 text-sm text-muted">
          Your responses have been recorded. The link you used is now closed.
        </p>
      </Card>
    </div>
  );
}
