import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const STEPS = [
  { n: 1, title: "Buyer pays with PayPal", body: "The demo shop creates and captures a PayPal sandbox order on our server. PayPal records the buyer's shipping address on the transaction — the protected address." },
  { n: 2, title: "StayCovered records the PayPal facts", body: "Capture status, amount, Seller Protection status and the protected address are fetched from PayPal. Webhooks are signature-verified, deduplicated, and always re-fetched from PayPal before we trust them." },
  { n: 3, title: "AI reads chats and labels", body: "The seller uploads chat screenshots and a label photo. AI extracts requests like 'ship to my friend' and the label address — with exact quotes and sources. (Feature 2)" },
  { n: 4, title: "Rules decide, you approve", body: "Plain code compares everything with the protected address and gives a verdict with reasons. Nothing that moves money happens without your click. (Features 3–4)" },
  { n: 5, title: "Tracking and dispute defense", body: "Tracking is registered with PayPal at dispatch. If a dispute arrives, StayCovered prepares the evidence and submits it after you approve. (Features 4–5)" },
];

export default function HowItWorks() {
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">How StayCovered works</h1>
        <p className="text-muted-foreground">
          AI extracts. Rules decide. You approve. PayPal moves the money.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Architecture</CardTitle>
          <CardDescription>Simplified. PayPal is the source of truth for payments, addresses and disputes.</CardDescription>
        </CardHeader>
        <CardContent>
          <pre className="overflow-x-auto rounded-lg bg-muted p-4 font-mono text-xs leading-relaxed" aria-label="Architecture diagram">
{`  Seller app (Next.js) ─┐                 ┌─> PayPal sandbox
  Demo shop (JS SDK v6) ┼──> FastAPI API ─┤   Orders · Payments · Webhooks
                        │     │  │  │     └─> (Tracking · Disputes — later features)
  PayPal webhooks ──────┘     │  │  └─> Rule engine (deterministic)
                              │  └────> AI agents (Gemini / Claude) — extract only
                              └───────> Postgres + audit log`}
          </pre>
        </CardContent>
      </Card>

      <ol className="space-y-4">
        {STEPS.map((s) => (
          <li key={s.n} className="flex gap-4">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground" aria-hidden>
              {s.n}
            </span>
            <div>
              <h2 className="font-medium">{s.title}</h2>
              <p className="text-sm text-muted-foreground">{s.body}</p>
            </div>
          </li>
        ))}
      </ol>

      <Card>
        <CardHeader>
          <CardTitle>Data handling</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>This demo runs on the PayPal sandbox only — no real money and no live credentials.</p>
          <p>Buyer emails are masked in the dashboard, and the audit log stores only city and state, never full street addresses.</p>
          <p>Uploaded chats and labels (from Feature 2) are processed by the configured AI provider. Use synthetic data in the demo.</p>
          <p className="font-medium text-foreground">PayPal decides Seller Protection eligibility and dispute outcomes. A passed check is not a guarantee.</p>
        </CardContent>
      </Card>
    </div>
  );
}
