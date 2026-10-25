import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  HEADER_EDITABLE,
  HEADER_FIELDS,
  api,
  type Evidence,
  type Flag,
  type FormDetail,
  type HeaderField,
  type Item,
  type ItemField,
} from "./api";
import PdfViewer, { type Target } from "./PdfViewer";
import { SEVERITY_STYLE, SeverityChip, SyncBadge, formatMoney } from "./ui";

const LABELS: Record<string, string> = {
  sku: "SKU",
  qty: "Qty",
  unit_price: "Unit price",
  amount: "Amount",
  service_start: "Start",
  service_end: "End",
  billing_terms: "Billing",
  customer_name: "Customer",
  vendor_name: "Vendor",
  effective_date: "Effective date",
  contract_signed_date_buying_company: "Signed by customer",
  contract_signed_date_selling_company: "Signed by vendor",
  grand_total: "Grand total",
};
const NUMBER_FIELDS = new Set(["qty", "unit_price", "amount", "grand_total"]);
const DATE_FIELDS = new Set([
  "service_start",
  "service_end",
  "effective_date",
  "contract_signed_date_buying_company",
  "contract_signed_date_selling_company",
]);
const FREQUENCIES = ["monthly", "quarterly", "biannually", "yearly", "one-time"];
const COLUMNS: ItemField[] = ["sku", "qty", "unit_price", "amount", "service_start", "service_end", "billing_terms"];

type Draft = Record<string, string>;
type RowKey = number | "header"; // item id, or the order-form header

const openFlags = (flags: Flag[]) => flags.filter((f) => !f.resolved);
const topSeverity = (flags: Flag[]) =>
  (["high", "medium", "low"] as const).find((s) => flags.some((f) => f.severity === s)) ?? null;

/** Client-side validation: numbers stay numbers, dates are ISO. The server validates again. */
function validate(draft: Draft): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const [field, raw] of Object.entries(draft)) {
    const value = raw.trim();
    if (NUMBER_FIELDS.has(field)) {
      if (!/^\d+(\.\d+)?$/.test(value)) errors[field] = "Enter a number, e.g. 1200.50";
    } else if (DATE_FIELDS.has(field)) {
      const ok = /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`));
      if (!ok) errors[field] = "Use YYYY-MM-DD";
    }
  }
  if (draft.service_start && draft.service_end && !errors.service_start && !errors.service_end &&
      draft.service_start > draft.service_end)
    errors.service_end = "Must not be before start";
  return errors;
}

/** Same rule as the server: edit qty or unit price and the amount keeps its number of billing periods. */
function previewAmount(item: Item, draft: Draft): number | null {
  const qty = Number(draft.qty), unit = Number(draft.unit_price), amount = Number(draft.amount);
  const changedQtyOrUnit = qty !== item.qty || unit !== item.unit_price;
  if (!changedQtyOrUnit || amount !== item.amount || !item.qty || !item.unit_price || item.amount === null)
    return Number.isFinite(amount) ? amount : null;
  const periods = item.amount / (item.qty * item.unit_price);
  if (Math.abs(periods - Math.round(periods)) > 0.001) return amount;
  return Math.round(qty * unit * Math.round(periods) * 100) / 100;
}

/** The checker's arithmetic check: amount is a whole number of qty x unit price periods. */
function arithmeticProblem(qty: number, unit: number, amount: number): string | null {
  if (!qty || !unit || !Number.isFinite(amount)) return null;
  const ratio = amount / (qty * unit);
  const n = Math.round(ratio);
  return n < 1 || Math.abs(ratio - n) > 0.001
    ? `Amount isn't a whole number of periods of qty × unit price (${ratio.toFixed(3)})`
    : null;
}

export default function FormPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const [form, setForm] = useState<FormDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<RowKey | null>(null);
  const [editing, setEditing] = useState<RowKey | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [target, setTarget] = useState<Target | null>(null);
  const [busy, setBusy] = useState(false);
  const [catalog, setCatalog] = useState<{ sku: string; name: string }[]>([]);

  const load = useCallback(() => {
    api.getForm(id).then(setForm).catch((e) => setError(String(e.message ?? e)));
  }, [id]);
  useEffect(load, [load]);
  useEffect(() => {
    api.catalog().then(setCatalog).catch(() => setCatalog([]));
  }, []);
  useEffect(() => {
    // poll while extraction or the sync is still running
    if (form?.status !== "processing" && form?.sync_status !== "pending") return;
    const timer = setTimeout(load, 2000);
    return () => clearTimeout(timer);
  }, [form, load]);

  const reviewable = form?.status === "needs_review";

  // rows with unresolved flags, in display order; j/k move between these
  const flaggedRows = useMemo<RowKey[]>(() => {
    if (!form) return [];
    const rows: RowKey[] = [];
    if (openFlags(form.header.flags).length) rows.push("header");
    for (const item of form.items) if (openFlags(item.flags).length) rows.push(item.id);
    return rows;
  }, [form]);

  const run = async (action: () => Promise<FormDetail>) => {
    setBusy(true);
    setError(null);
    try {
      setForm(await action());
      return true;
    } catch (e) {
      const err = e as ApiError;
      setError(err.message);
      if (err.fields) setFieldErrors(err.fields);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const accept = (row: RowKey) =>
    run(() => (row === "header" ? api.reviewHeader(id, "accept") : api.reviewItem(id, row, "accept")));

  const startEdit = (row: RowKey) => {
    if (!form || !reviewable) return;
    const source: Record<string, unknown> =
      row === "header" ? form.header.values : (form.items.find((i) => i.id === row) as unknown as Record<string, unknown>);
    const fields: string[] = row === "header" ? HEADER_EDITABLE : COLUMNS;
    setDraft(Object.fromEntries(fields.map((f) => [f, source[f] === null || source[f] === undefined ? "" : String(source[f])])));
    setFieldErrors({});
    setSelected(row);
    setEditing(row);
  };

  const saveEdit = async () => {
    if (!form || editing === null) return;
    const errors = validate(Object.fromEntries(Object.entries(draft).filter(([, v]) => v.trim() !== "")));
    setFieldErrors(errors);
    if (Object.keys(errors).length) return;
    const before: Record<string, unknown> =
      editing === "header"
        ? form.header.values
        : (form.items.find((i) => i.id === editing) as unknown as Record<string, unknown>);
    const changed: Record<string, unknown> = {};
    for (const [field, raw] of Object.entries(draft)) {
      const value = raw.trim();
      if (value === "" || value === String(before[field] ?? "")) continue;
      changed[field] = NUMBER_FIELDS.has(field) ? Number(value) : value;
    }
    const ok = await run(() =>
      editing === "header"
        ? api.reviewHeader(id, "edit", changed)
        : Object.keys(changed).length
          ? api.reviewItem(id, editing, "edit", changed)
          : api.reviewItem(id, editing, "accept"),
    );
    if (ok) setEditing(null);
  };

  const approve = async () => {
    setBusy(true);
    try {
      await api.approve(id);
      navigate("/");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  // keyboard: j/k move between flagged rows, a accepts, e edits, Esc cancels an edit
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const typing = (event.target as HTMLElement).closest("input, select, textarea");
      if (event.key === "Escape" && editing !== null) {
        setEditing(null);
        return;
      }
      if (typing || event.metaKey || event.ctrlKey || event.altKey || !reviewable) return;
      if (event.key === "j" || event.key === "k") {
        if (!flaggedRows.length) return;
        const at = selected === null ? -1 : flaggedRows.indexOf(selected);
        const next =
          event.key === "j"
            ? flaggedRows[(at + 1) % flaggedRows.length]
            : flaggedRows[(at - 1 + flaggedRows.length) % flaggedRows.length];
        setSelected(next);
        document.querySelector(`[data-row="${next}"]`)?.scrollIntoView({ block: "nearest" });
      } else if (event.key === "a" && selected !== null && editing === null) {
        event.preventDefault();
        accept(selected);
      } else if (event.key === "e" && selected !== null && editing === null) {
        event.preventDefault();
        startEdit(selected);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const show = (label: string, evidence: Evidence | undefined, fallback?: { page: number | null; quote: string | null }) => {
    const quote = evidence?.quote ?? fallback?.quote;
    if (!quote) return;
    setTarget({ label, quote, page: evidence?.page ?? fallback?.page ?? null, nonce: Date.now() });
  };

  if (error && !form) return <p className="p-6 text-red-700">{error}</p>;
  if (!form) return <p className="p-6 text-slate-500">Loading…</p>;

  const highOpen = [...form.header.flags, ...form.items.flatMap((i) => i.flags)].filter(
    (f) => !f.resolved && f.severity === "high",
  ).length;
  const minorOpen = flaggedRows.filter((row) => {
    const flags = row === "header" ? form.header.flags : form.items.find((i) => i.id === row)!.flags;
    return topSeverity(openFlags(flags)) !== "high";
  }).length;
  const currency = form.items[0]?.currency;

  // live totals, with the row being edited previewed from the draft
  const amounts = form.items.map((item) =>
    editing === item.id ? previewAmount(item, draft) ?? 0 : item.amount ?? 0,
  );
  const lineTotal = amounts.reduce((a, b) => a + b, 0);
  const grandTotal =
    editing === "header" && draft.grand_total ? Number(draft.grand_total) : (form.header.values.grand_total as number | null);
  const totalMismatch = grandTotal !== null && Math.abs(lineTotal - grandTotal) > 0.005;

  return (
    <div className="flex h-screen flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5">
        <Link to="/" className="text-sm text-slate-500 hover:text-slate-900">
          ← Queue
        </Link>
        <h1 className="font-semibold" data-testid="form-title">
          {form.filename}
        </h1>
        <span className="text-sm text-slate-500">{form.status.replace("_", " ")}</span>
        <SyncBadge status={form.sync_status} />
        {form.sync_status === "failed" && (
          <button className="btn" onClick={() => api.retrySync(id).then(load)}>
            Retry sync
          </button>
        )}
        <div className="ml-auto flex items-center gap-2">
          {reviewable && (
            <>
              <span className="hidden text-xs text-slate-400 lg:inline">j/k move · a accept · e edit</span>
              <button className="btn" disabled={busy || !minorOpen} onClick={() => run(() => api.acceptMinor(id))}>
                Accept all low/medium
              </button>
              <button
                className="btn-primary"
                disabled={busy || !form.can_approve || editing !== null}
                onClick={approve}
                title={form.can_approve ? "" : `${highOpen} high-severity flag(s) still open`}
                data-testid="approve"
              >
                Approve form
              </button>
            </>
          )}
        </div>
      </header>

      {error && <p className="bg-red-50 px-4 py-2 text-sm text-red-800">{error}</p>}
      {form.sync_errors.length > 0 && (
        <p className="bg-red-50 px-4 py-2 text-sm text-red-800">Sync failed: {form.sync_errors.join("; ")}</p>
      )}
      {form.extraction_error && (
        <p className="bg-red-50 px-4 py-2 text-sm text-red-800">Extraction failed: {form.extraction_error}</p>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-2">
        <section className="min-h-0 overflow-auto p-4">
          {reviewable && highOpen > 0 && (
            <p className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              Approve is blocked until {highOpen} high-severity flag{highOpen > 1 ? "s are" : " is"} accepted or edited.
            </p>
          )}

          <HeaderCard
            form={form}
            selected={selected === "header"}
            editing={editing === "header"}
            draft={draft}
            fieldErrors={fieldErrors}
            reviewable={reviewable}
            onSelect={() => setSelected("header")}
            onDraft={(field, value) => setDraft((d) => ({ ...d, [field]: value }))}
            onAccept={() => accept("header")}
            onEdit={() => startEdit("header")}
            onSave={saveEdit}
            onCancel={() => setEditing(null)}
            onShow={(field) => show(LABELS[field] ?? field, form.header.evidence[field])}
            busy={busy}
          />

          <h2 className="mb-2 mt-5 text-sm font-semibold uppercase tracking-wide text-slate-500">Line items</h2>
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  {COLUMNS.map((c) => (
                    <th key={c} className={`px-2 py-2 ${NUMBER_FIELDS.has(c) ? "text-right" : ""}`}>
                      {LABELS[c]}
                    </th>
                  ))}
                  <th className="px-2 py-2" />
                </tr>
              </thead>
              {form.items.map((item) => (
                <ItemRows
                  key={item.id}
                  item={item}
                  selected={selected === item.id}
                  editing={editing === item.id}
                  draft={draft}
                  fieldErrors={fieldErrors}
                  catalog={catalog}
                  reviewable={reviewable}
                  busy={busy}
                  onSelect={() => setSelected(item.id)}
                  onDraft={(field, value) => setDraft((d) => ({ ...d, [field]: value }))}
                  onAccept={() => accept(item.id)}
                  onEdit={() => startEdit(item.id)}
                  onSave={saveEdit}
                  onCancel={() => setEditing(null)}
                  onShow={(field) =>
                    show(`${LABELS[field]} (${item.sku})`, item.evidence[field], {
                      page: item.source_page,
                      quote: item.source_text,
                    })
                  }
                />
              ))}
              <tfoot className="border-t border-slate-200 bg-slate-50 text-sm">
                <tr>
                  <td className="px-2 py-2 font-medium" colSpan={3}>
                    Line total
                  </td>
                  <td className="px-2 py-2 text-right font-semibold" data-testid="line-total">
                    {formatMoney(lineTotal, currency)}
                  </td>
                  <td className="px-2 py-2 text-slate-500" colSpan={4}>
                    {totalMismatch
                      ? `≠ grand total ${formatMoney(grandTotal, currency)}`
                      : grandTotal !== null
                        ? "matches the grand total"
                        : ""}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
          {form.form_checks.map((c) => (
            <p key={c} className="mt-2 text-sm text-amber-800">
              ⚠ {c}
            </p>
          ))}
        </section>

        <section className="min-h-[60vh] border-l border-slate-200 lg:min-h-0">
          <PdfViewer url={api.pdfUrl(id)} target={target} />
        </section>
      </div>
    </div>
  );
}

interface RowProps {
  selected: boolean;
  editing: boolean;
  draft: Draft;
  fieldErrors: Record<string, string>;
  reviewable: boolean;
  busy: boolean;
  onSelect: () => void;
  onDraft: (field: string, value: string) => void;
  onAccept: () => void;
  onEdit: () => void;
  onSave: () => void;
  onCancel: () => void;
  onShow: (field: string) => void;
}

function Actions(props: RowProps & { flags: Flag[]; action: string | null; testId: string }) {
  const { editing, reviewable, busy, flags, action } = props;
  if (!reviewable) return action ? <span className="text-xs text-slate-500">{action}</span> : null;
  if (editing)
    return (
      <div className="flex gap-1">
        <button className="btn-primary !py-1" disabled={busy} onClick={props.onSave} data-testid={`${props.testId}-save`}>
          Save
        </button>
        <button className="btn" onClick={props.onCancel}>
          Cancel
        </button>
      </div>
    );
  return (
    <div className="flex items-center gap-1">
      {openFlags(flags).length > 0 && (
        <button className="btn" disabled={busy} onClick={props.onAccept} data-testid={`${props.testId}-accept`}>
          Accept
        </button>
      )}
      <button className="btn" disabled={busy} onClick={props.onEdit} data-testid={`${props.testId}-edit`}>
        Edit
      </button>
      {action && <span className="text-xs text-emerald-700">{action}</span>}
    </div>
  );
}

function FlagList({ flags }: { flags: Flag[] }) {
  if (!flags.length) return null;
  return (
    <ul className="space-y-0.5">
      {flags.map((f) => (
        <li key={f.id} className={`text-xs ${f.resolved ? "text-slate-400 line-through" : SEVERITY_STYLE[f.severity].text}`}>
          <SeverityChip severity={f.severity} /> {f.reason}
        </li>
      ))}
    </ul>
  );
}

function EditInput(props: {
  field: string;
  value: string;
  error?: string;
  onChange: (v: string) => void;
  catalog?: { sku: string; name: string }[];
}) {
  const { field, value, error, onChange, catalog } = props;
  let input;
  if (field === "billing_terms")
    input = (
      <select className="field-input" value={value} onChange={(e) => onChange(e.target.value)} aria-label={LABELS[field]}>
        <option value="">—</option>
        {FREQUENCIES.map((f) => (
          <option key={f}>{f}</option>
        ))}
      </select>
    );
  else if (field === "sku" && catalog?.length)
    input = (
      <select className="field-input" value={value} onChange={(e) => onChange(e.target.value)} aria-label={LABELS[field]}>
        {catalog.map((c) => (
          <option key={c.sku} value={c.sku}>
            {c.name}
          </option>
        ))}
      </select>
    );
  else
    input = (
      <input
        className={`field-input ${error ? "border-red-500" : ""} ${NUMBER_FIELDS.has(field) ? "text-right" : ""}`}
        value={value}
        inputMode={NUMBER_FIELDS.has(field) ? "decimal" : undefined}
        placeholder={DATE_FIELDS.has(field) ? "YYYY-MM-DD" : undefined}
        onChange={(e) => onChange(e.target.value)}
        aria-label={LABELS[field]}
        data-testid={`edit-${field}`}
      />
    );
  return (
    <div>
      {input}
      {error && <p className="mt-0.5 text-xs text-red-700">{error}</p>}
    </div>
  );
}

function ItemRows(props: RowProps & { item: Item; catalog: { sku: string; name: string }[] }) {
  const { item, selected, editing, draft, fieldErrors } = props;
  const open = openFlags(item.flags);
  const severity = topSeverity(open);
  const tint = severity ? SEVERITY_STYLE[severity].row : "";
  const previewed = editing ? previewAmount(item, draft) : null;
  const problem = editing
    ? arithmeticProblem(Number(draft.qty), Number(draft.unit_price), previewed ?? Number(draft.amount))
    : null;

  const display = (field: ItemField) => {
    const value = item[field];
    if (field === "unit_price" || field === "amount") return formatMoney(value as number | null, item.currency);
    if (field === "sku") return item.description ?? item.sku ?? "—";
    return value === null || value === undefined ? "—" : String(value);
  };

  return (
    <tbody
      data-row={item.id}
      data-testid="item-row"
      className={`border-b border-slate-100 ${tint} ${selected ? "outline outline-2 -outline-offset-2 outline-indigo-500" : ""}`}
      onClick={props.onSelect}
    >
      <tr>
        {COLUMNS.map((field) => (
          <td key={field} className={`px-2 py-1.5 align-top ${NUMBER_FIELDS.has(field) ? "text-right" : ""}`}>
            {editing ? (
              field === "amount" && previewed !== null && String(previewed) !== draft.amount ? (
                <div>
                  <EditInput field={field} value={draft[field] ?? ""} error={fieldErrors[field]} onChange={(v) => props.onDraft(field, v)} />
                  <p className="mt-0.5 text-xs text-indigo-700" data-testid="amount-preview">
                    → {formatMoney(previewed, item.currency)}
                  </p>
                </div>
              ) : (
                <EditInput
                  field={field}
                  value={draft[field] ?? ""}
                  error={fieldErrors[field]}
                  onChange={(v) => props.onDraft(field, v)}
                  catalog={props.catalog}
                />
              )
            ) : (
              <button
                className={`text-left hover:underline ${item.edited_fields.includes(field) ? "font-semibold text-indigo-700" : ""} ${
                  field === "sku" ? "max-w-[14rem]" : "whitespace-nowrap"
                }`}
                onClick={() => props.onShow(field)}
                title={item.evidence[field]?.quote ?? item.source_text ?? ""}
                data-testid={`cell-${field}`}
              >
                {display(field)}
              </button>
            )}
          </td>
        ))}
        <td className="px-2 py-1.5 align-top">
          <Actions {...props} flags={item.flags} action={item.reviewer_action} testId="item" />
        </td>
      </tr>
      {(item.flags.length > 0 || item.checks.length > 0 || problem) && (
        <tr>
          <td colSpan={COLUMNS.length + 1} className="px-2 pb-2">
            <FlagList flags={item.flags} />
            {[...(problem ? [problem] : []), ...(editing ? [] : item.checks)].map((c) => (
              <p key={c} className="text-xs text-amber-800">
                ⚠ {c}
              </p>
            ))}
          </td>
        </tr>
      )}
    </tbody>
  );
}

function HeaderCard(props: RowProps & { form: FormDetail }) {
  const { form, selected, editing, draft, fieldErrors } = props;
  const { values, evidence, flags } = form.header;
  const severity = topSeverity(openFlags(flags));
  const flaggedFields = new Set(openFlags(flags).map((f) => f.field));
  return (
    <div
      data-row="header"
      data-testid="header-card"
      onClick={props.onSelect}
      className={`rounded-lg border border-slate-200 bg-white p-3 ${severity ? SEVERITY_STYLE[severity].row : ""} ${
        selected ? "outline outline-2 -outline-offset-2 outline-indigo-500" : ""
      }`}
    >
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Order form</h2>
        <Actions {...props} flags={flags} action={form.header.reviewer_action} testId="header" />
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-3">
        {HEADER_FIELDS.map((field: HeaderField) => (
          <div key={field}>
            <dt className={`text-xs ${flaggedFields.has(field) ? "font-semibold text-red-700" : "text-slate-500"}`}>
              {LABELS[field]}
            </dt>
            <dd>
              {editing && HEADER_EDITABLE.includes(field) ? (
                <EditInput field={field} value={draft[field] ?? ""} error={fieldErrors[field]} onChange={(v) => props.onDraft(field, v)} />
              ) : (
                <button
                  className={`text-left hover:underline ${form.header.edited_fields.includes(field) ? "font-semibold text-indigo-700" : ""}`}
                  onClick={() => props.onShow(field)}
                  title={evidence[field]?.quote ?? ""}
                  data-testid={`header-${field}`}
                >
                  {field === "grand_total"
                    ? formatMoney(values[field] as number | null, values.currency as string)
                    : (values[field] ?? "—")}
                </button>
              )}
            </dd>
          </div>
        ))}
      </dl>
      {flags.length > 0 && (
        <div className="mt-2">
          <FlagList flags={flags} />
        </div>
      )}
    </div>
  );
}
