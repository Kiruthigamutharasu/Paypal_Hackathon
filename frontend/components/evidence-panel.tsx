"use client";

/**
 * Evidence panel (F2): upload buyer chats + shipping label, see what the AI extracted.
 * The AI only extracts facts; verdicts come from the rule engine (Feature 3).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  FileText,
  ImageUp,
  Loader2,
  MessageSquareText,
  Quote,
  RotateCcw,
  ScanLine,
  Sparkles,
} from "lucide-react";

import {
  api,
  ApiError,
  fileUrl,
  type ChatRequestOut,
  type ConversationOutput,
  type Evidence,
  type Extraction,
  type LabelOutput,
  type UploadInfo,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Pill } from "@/components/status";
import { cn } from "@/lib/utils";

const REQUEST_LABEL: Record<ChatRequestOut["type"], string> = {
  ADDRESS_CHANGE: "Different delivery address",
  PICKUP_OR_COURIER: "Pickup / courier hand-over",
  OFF_PLATFORM_PAYMENT: "Payment outside PayPal",
  NAME_CHANGE: "Different recipient name",
  OTHER_RISK: "Other risk signal",
};

const ISSUE_LABEL: Record<string, string> = {
  CROPPED: "Looks cropped",
  OUT_OF_ORDER: "Out of order",
  LOW_RESOLUTION: "Low resolution",
  MULTIPLE_THREADS: "Several chats",
  ROTATED: "Rotated",
  BLURRY: "Blurry",
  HANDWRITTEN: "Handwritten",
  MULTIPLE_LABELS: "More than one label",
};

const POLL_MS = 2000;
const POLL_MAX = 45;

export function EvidencePanel({ orderId }: { orderId: string }) {
  const [ev, setEv] = useState<Evidence | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [polls, setPolls] = useState(0);

  const pending = ev ? isPending(ev) : false;

  useEffect(() => {
    let cancelled = false;
    api
      .evidence(orderId)
      .then((e) => !cancelled && setEv(e))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load evidence."));
    return () => {
      cancelled = true;
    };
  }, [orderId]);

  // Poll while the agents are working (they run in the background after an upload).
  useEffect(() => {
    if (!pending || polls >= POLL_MAX) return;
    const t = setTimeout(() => {
      api
        .evidence(orderId)
        .then((e) => {
          setEv(e);
          setPolls((n) => n + 1);
        })
        .catch(() => setPolls((n) => n + 1));
    }, POLL_MS);
    return () => clearTimeout(t);
  }, [pending, polls, orderId]);

  const run = useCallback(async (label: string, fn: () => Promise<Evidence>) => {
    setBusy(label);
    setError(null);
    try {
      setEv(await fn());
      setPolls(0);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }, []);

  const active = (ev?.uploads ?? []).filter((u) => !u.superseded_by);
  const chats = active.filter((u) => u.kind !== "LABEL_IMAGE");
  const label = active.find((u) => u.kind === "LABEL_IMAGE");
  const replacedLabels = (ev?.uploads ?? []).filter((u) => u.kind === "LABEL_IMAGE" && u.superseded_by);
  const uploadIndex = new Map(chats.map((u, i) => [u.id, i + 1]));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="size-4 text-violet-600" aria-hidden /> Evidence check
        </CardTitle>
        <CardDescription>
          Upload the buyer chat and a photo of the shipping label. AI reads them and quotes what it found — it never
          approves a shipment.
        </CardDescription>
        {pending && (
          <CardAction>
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
              <Loader2 className="size-3.5 animate-spin" aria-hidden /> AI is reading…
            </span>
          </CardAction>
        )}
      </CardHeader>
      <CardContent className="space-y-6">
        {error && (
          <Alert variant="destructive">
            <AlertTriangle aria-hidden />
            <AlertTitle>{error}</AlertTitle>
          </Alert>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <ChatUploader
            disabled={!!busy}
            busy={busy === "chat"}
            onFiles={(files) => run("chat", () => api.uploadFiles(orderId, "CHAT_IMAGE", files))}
            onText={(text) => run("chat", () => api.uploadChatText(orderId, text))}
          />
          <DropZone
            id="label-upload"
            title={label ? "Replace shipping label" : "Shipping label photo"}
            hint="One photo or PDF of the label (PNG, JPG, GIF, PDF · max 10 MB)"
            accept="image/png,image/jpeg,image/gif,application/pdf"
            icon={<ScanLine className="size-5" aria-hidden />}
            disabled={!!busy}
            busy={busy === "label"}
            onFiles={(files) => run("label", () => api.uploadFiles(orderId, "LABEL_IMAGE", files.slice(0, 1)))}
          />
        </div>

        {(chats.length > 0 || label) && (
          <div className="flex flex-wrap gap-3" aria-label="Uploaded evidence">
            {chats.map((u, i) => (
              <Thumb key={u.id} u={u} caption={`Chat ${i + 1}`} />
            ))}
            {label && <Thumb u={label} caption="Label" />}
            {replacedLabels.map((u) => (
              <Thumb key={u.id} u={u} caption="Replaced" faded />
            ))}
          </div>
        )}

        {ev && (
          <div className="grid gap-4 lg:grid-cols-2">
            <ChatFindings
              rows={ev.conversation}
              hasChats={chats.length > 0}
              pending={pending}
              uploadIndex={uploadIndex}
            />
            <LabelFindings rows={ev.label} hasLabel={!!label} pending={pending} />
          </div>
        )}

        {ev && hasFailure(ev) && !pending && (
          <Button variant="outline" onClick={() => run("rerun", () => api.rerunExtractions(orderId))} disabled={!!busy}>
            <RotateCcw aria-hidden /> Retry AI check
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function isPending(ev: Evidence): boolean {
  if (ev.verification_state === "AI_PROCESSING") return true;
  const active = ev.uploads.filter((u) => !u.superseded_by);
  const covered = new Set([...ev.conversation, ...ev.label].flatMap((x) => x.upload_ids));
  return active.some((u) => !covered.has(u.id));
}

function hasFailure(ev: Evidence) {
  return [...ev.conversation, ...ev.label].some((x) => x.status !== "SUCCEEDED");
}

// ---------------- uploaders ----------------
function DropZone(props: {
  id: string;
  title: string;
  hint: string;
  accept: string;
  multiple?: boolean;
  icon: React.ReactNode;
  disabled?: boolean;
  busy?: boolean;
  onFiles: (files: File[]) => void;
}) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (!props.disabled && e.dataTransfer.files.length) props.onFiles(Array.from(e.dataTransfer.files));
      }}
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-5 text-center transition-colors",
        over ? "border-primary bg-primary/5" : "border-border",
      )}
    >
      <span className="text-muted-foreground">{props.busy ? <Loader2 className="size-5 animate-spin" /> : props.icon}</span>
      <label htmlFor={props.id} className="cursor-pointer text-sm font-medium underline-offset-4 hover:underline">
        {props.title}
      </label>
      <p className="text-xs text-muted-foreground">{props.hint}</p>
      <p className="text-xs text-muted-foreground">Drag & drop or click</p>
      <input
        ref={input}
        id={props.id}
        type="file"
        className="sr-only"
        accept={props.accept}
        multiple={props.multiple}
        disabled={props.disabled}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length) props.onFiles(files);
          e.target.value = "";
        }}
      />
    </div>
  );
}

function ChatUploader(props: {
  disabled: boolean;
  busy: boolean;
  onFiles: (files: File[]) => void;
  onText: (text: string) => void;
}) {
  const [mode, setMode] = useState<"image" | "text">("image");
  const [text, setText] = useState("");
  return (
    <div className="space-y-2">
      <div role="tablist" aria-label="Chat input" className="inline-flex rounded-lg bg-muted p-0.5 text-xs">
        {(["image", "text"] as const).map((m) => (
          <button
            key={m}
            role="tab"
            aria-selected={mode === m}
            onClick={() => setMode(m)}
            className={cn("rounded-md px-2.5 py-1", mode === m ? "bg-background shadow-sm" : "text-muted-foreground")}
          >
            {m === "image" ? "Screenshots" : "Paste text"}
          </button>
        ))}
      </div>
      {mode === "image" ? (
        <DropZone
          id="chat-upload"
          title="Buyer chat screenshots"
          hint="Up to 5 at a time, in order (PNG or JPG · max 10 MB each)"
          accept="image/png,image/jpeg"
          multiple
          icon={<ImageUp className="size-5" aria-hidden />}
          disabled={props.disabled}
          busy={props.busy}
          onFiles={props.onFiles}
        />
      ) : (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) {
              props.onText(text);
              setText("");
            }
          }}
        >
          <label htmlFor="chat-text" className="sr-only">Paste the chat</label>
          <textarea
            id="chat-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={6}
            placeholder={"Buyer: Hi! Just paid :)\nMe: Thanks!\nBuyer: Could you ship it to my friend instead?"}
            className="w-full resize-y rounded-xl border bg-background p-3 font-mono text-xs outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          <Button type="submit" size="sm" disabled={props.disabled || !text.trim()}>
            {props.busy ? <Loader2 className="animate-spin" aria-hidden /> : <MessageSquareText aria-hidden />} Check this chat
          </Button>
        </form>
      )}
    </div>
  );
}

function Thumb({ u, caption, faded }: { u: UploadInfo; caption: string; faded?: boolean }) {
  const isImage = u.mime.startsWith("image/");
  return (
    <a
      href={fileUrl(u)}
      target="_blank"
      rel="noreferrer"
      id={`upload-${u.id}`}
      className={cn("group w-24 shrink-0 text-center", faded && "opacity-50")}
      title={u.original_filename ?? caption}
    >
      <div className="flex h-24 w-24 items-center justify-center overflow-hidden rounded-lg border bg-muted">
        {isImage ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={fileUrl(u)} alt={`${caption} preview`} className="h-full w-full object-cover object-top" />
        ) : (
          <FileText className="size-8 text-muted-foreground" aria-hidden />
        )}
      </div>
      <span className="mt-1 block truncate text-xs text-muted-foreground group-hover:text-foreground">{caption}</span>
    </a>
  );
}

// ---------------- findings ----------------
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 rounded-xl border p-4" aria-label={title}>
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function Failure({ x }: { x: Extraction<unknown> }) {
  return (
    <Alert variant="destructive">
      <AlertTitle>{x.status === "PROVIDER_UNAVAILABLE" ? "AI check unavailable — retry (SYS-01)" : "We couldn't read this — please retry or check manually"}</AlertTitle>
      {x.error && <AlertDescription className="text-xs">{x.error.slice(0, 160)}</AlertDescription>}
    </Alert>
  );
}

function Meta({ x }: { x: Extraction<unknown> }) {
  return (
    <p className="text-[11px] text-muted-foreground">
      {x.model} · {x.prompt_version} · {x.latency_ms != null ? `${(x.latency_ms / 1000).toFixed(1)} s` : ""}
    </p>
  );
}

function ConfidencePill({ c }: { c: number }) {
  const tone = c >= 0.85 ? "green" : c >= 0.7 ? "amber" : "red";
  return <Pill tone={tone}>Confidence {Math.round(c * 100)}%</Pill>;
}

function ChatFindings({
  rows,
  hasChats,
  pending,
  uploadIndex,
}: {
  rows: Extraction<ConversationOutput>[];
  hasChats: boolean;
  pending: boolean;
  uploadIndex: Map<string, number>;
}) {
  if (!hasChats) return <Section title="Chat findings"><p className="text-sm text-muted-foreground">No chat uploaded yet.</p></Section>;
  if (!rows.length) return <Section title="Chat findings"><p className="text-sm text-muted-foreground">{pending ? "Reading the chat…" : "Not checked yet."}</p></Section>;
  return (
    <Section title="Chat findings">
      {rows.map((x) =>
        x.output ? (
          <div key={x.id} className="space-y-3">
            <div className="flex flex-wrap gap-1.5">
              <ConfidencePill c={x.output.confidence} />
              {!x.output.conversation_complete && <Pill tone="amber">Chat may be incomplete</Pill>}
              {x.output.issues.map((i) => (
                <Pill key={i} tone="amber">{ISSUE_LABEL[i] ?? i}</Pill>
              ))}
            </div>
            {x.output.requests.length === 0 ? (
              <p className="text-sm">No risky requests found in {x.output.messages_observed} messages.</p>
            ) : (
              <ul className="space-y-3">
                {x.output.requests.map((r, i) => (
                  <RequestItem key={i} r={r} chatNo={uploadIndex.get(r.source_ref.upload_id)} />
                ))}
              </ul>
            )}
            {!!x.validation_notes?.length && (
              <p className="text-xs text-muted-foreground">
                {x.validation_notes.length} item(s) discarded because they couldn&apos;t be traced to the uploaded chat.
              </p>
            )}
            <Meta x={x} />
          </div>
        ) : (
          <Failure key={x.id} x={x} />
        ),
      )}
    </Section>
  );
}

function RequestItem({ r, chatNo }: { r: ChatRequestOut; chatNo?: number }) {
  const tone = r.status === "CANCELLED" ? "grey" : r.type === "ADDRESS_CHANGE" || r.type === "PICKUP_OR_COURIER" ? "red" : "amber";
  const where = r.requested_address
    ? [r.requested_address.line1, r.requested_address.city, r.requested_address.state, r.requested_address.postal_code].filter(Boolean).join(", ")
    : "";
  return (
    <li className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <Pill tone={tone}>{REQUEST_LABEL[r.type]}</Pill>
        <span className="text-xs text-muted-foreground">
          {r.status.toLowerCase()} · from {r.speaker.toLowerCase()}
        </span>
      </div>
      <blockquote className="flex gap-2 rounded-lg bg-muted/60 p-2.5 text-sm">
        <Quote className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span>{r.quote}</span>
      </blockquote>
      <p className="text-xs text-muted-foreground">
        {where && <>Requested: {where} · </>}
        <a href={`#upload-${r.source_ref.upload_id}`} className="underline underline-offset-2">
          Chat {chatNo ?? "?"}{r.source_ref.position ? `, message ${r.source_ref.position}` : ""}
        </a>
      </p>
    </li>
  );
}

const LABEL_FIELDS: [string, string][] = [
  ["line1", "Street"],
  ["line2", "Apt / unit"],
  ["city", "City"],
  ["state", "State"],
  ["postal_code", "ZIP"],
  ["country", "Country"],
];

function LabelFindings({ rows, hasLabel, pending }: { rows: Extraction<LabelOutput>[]; hasLabel: boolean; pending: boolean }) {
  if (!hasLabel) return <Section title="Label reading"><p className="text-sm text-muted-foreground">No label uploaded yet.</p></Section>;
  const x = rows[0];
  if (!x) return <Section title="Label reading"><p className="text-sm text-muted-foreground">{pending ? "Reading the label…" : "Not checked yet."}</p></Section>;
  if (!x.output) return <Section title="Label reading"><Failure x={x} /></Section>;
  const o = x.output;
  return (
    <Section title="Label reading">
      <div className="flex flex-wrap gap-1.5">
        <ConfidencePill c={o.confidence} />
        {!o.readable && <Pill tone="red">Not readable — upload a clearer photo</Pill>}
        {o.issues.map((i) => (
          <Pill key={i} tone="amber">{ISSUE_LABEL[i] ?? i}</Pill>
        ))}
      </div>
      <dl className="grid grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-1.5 text-sm">
        <dt className="text-xs text-muted-foreground">Recipient</dt>
        <dd className="col-span-2">{o.recipient_name ?? <span className="text-muted-foreground">—</span>}</dd>
        {LABEL_FIELDS.map(([k, name]) => {
          const c = o.field_confidence[k];
          return (
            <div key={k} className="contents">
              <dt className="text-xs text-muted-foreground">{name}</dt>
              <dd>{o.address[k] ?? <span className="text-muted-foreground">—</span>}</dd>
              <dd className="text-right">
                {c != null && (
                  <span className={cn("text-xs tabular-nums", c < 0.7 ? "text-red-700 dark:text-red-400" : "text-muted-foreground")}>
                    {Math.round(c * 100)}%
                  </span>
                )}
              </dd>
            </div>
          );
        })}
        {(o.carrier_visible || o.tracking_number_visible) && (
          <>
            <dt className="text-xs text-muted-foreground">Carrier</dt>
            <dd className="col-span-2 font-mono text-xs">
              {[o.carrier_visible, o.tracking_number_visible].filter(Boolean).join(" · ")}
            </dd>
          </>
        )}
      </dl>
      <p className="text-xs text-muted-foreground">The address comparison with PayPal is done by plain code, not AI.</p>
      <Meta x={x} />
    </Section>
  );
}
