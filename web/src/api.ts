// Typed client for the review API (server/app.py), reached through the /api proxy.

export type Severity = "high" | "medium" | "low";
export type SyncStatus = "pending" | "done" | "failed" | null;

export interface FormSummary {
  id: number;
  filename: string;
  uploaded_at: string;
  status: "processing" | "needs_review" | "approved" | "rejected";
  approved_at: string | null;
  open_flags: Record<Severity, number>;
  top_severity: Severity | null;
  sync_status: SyncStatus;
  extraction_error: string | null;
}

export interface Flag {
  id: number;
  line_index: number | null;
  field: string | null;
  severity: Severity;
  check: string;
  reason: string;
  resolved: boolean;
}

export interface Evidence {
  quote: string;
  page: number | null;
}

export const ITEM_FIELDS = ["sku", "qty", "unit_price", "amount", "service_start", "service_end", "billing_terms"] as const;
export type ItemField = (typeof ITEM_FIELDS)[number];

export interface Item {
  id: number;
  line_index: number;
  sku: string | null;
  description: string | null;
  qty: number | null;
  unit_price: number | null;
  amount: number | null;
  service_start: string | null;
  service_end: string | null;
  billing_terms: string | null;
  currency: string | null;
  payment_terms: string | null;
  original: Record<ItemField, string | number | null>;
  edited_fields: string[];
  flag_severity: Severity | null;
  flags: Flag[];
  source_page: number | null;
  source_text: string | null;
  evidence: Record<string, Evidence>;
  reviewer_action: "accepted" | "edited" | null;
  checks: string[];
}

export const HEADER_FIELDS = [
  "customer_name",
  "vendor_name",
  "effective_date",
  "contract_signed_date_buying_company",
  "contract_signed_date_selling_company",
  "grand_total",
] as const;
export type HeaderField = (typeof HEADER_FIELDS)[number];
export const HEADER_EDITABLE: HeaderField[] = [
  "effective_date",
  "contract_signed_date_buying_company",
  "contract_signed_date_selling_company",
  "grand_total",
];

export interface FormDetail extends FormSummary {
  header: {
    values: Record<string, string | number | null>;
    evidence: Record<string, Evidence>;
    edited_fields: string[];
    reviewer_action: "accepted" | "edited" | null;
    flags: Flag[];
  };
  items: Item[];
  form_checks: string[];
  can_approve: boolean;
  sync_errors: string[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public fields: Record<string, string> = {},
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : response.statusText;
    throw new ApiError(detail, response.status, body.fields ?? {});
  }
  return response.json() as Promise<T>;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  listForms: (status?: string) => call<FormSummary[]>(`/forms${status ? `?status=${status}` : ""}`),
  getForm: (id: number) => call<FormDetail>(`/forms/${id}?review=true`),
  upload: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return call<{ form_id: number }>("/forms", { method: "POST", body });
  },
  reviewItem: (formId: number, itemId: number, action: "accept" | "edit", values?: Record<string, unknown>) =>
    call<FormDetail>(`/forms/${formId}/items/${itemId}`, json("PATCH", { action, values })),
  reviewHeader: (formId: number, action: "accept" | "edit", values?: Record<string, unknown>) =>
    call<FormDetail>(`/forms/${formId}/header`, json("PATCH", { action, values })),
  acceptMinor: (formId: number) => call<FormDetail>(`/forms/${formId}/accept-minor`, json("POST")),
  approve: (formId: number) => call<FormDetail>(`/forms/${formId}/approve`, json("POST")),
  retrySync: (formId: number) => call<unknown>(`/forms/${formId}/sync`, json("POST")),
  catalog: () => call<{ sku: string; name: string }[]>("/catalog"),
  pdfUrl: (formId: number) => `/api/forms/${formId}/pdf`,
};
