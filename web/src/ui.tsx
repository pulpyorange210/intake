import type { Severity, SyncStatus } from "./api";

export const SEVERITY_STYLE: Record<Severity, { chip: string; row: string; text: string }> = {
  high: { chip: "bg-red-100 text-red-800 ring-red-300", row: "bg-red-50", text: "text-red-800" },
  medium: { chip: "bg-amber-100 text-amber-800 ring-amber-300", row: "bg-amber-50", text: "text-amber-800" },
  low: { chip: "bg-sky-100 text-sky-800 ring-sky-300", row: "bg-sky-50", text: "text-sky-800" },
};

export function SeverityChip({ severity, count }: { severity: Severity; count?: number }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${SEVERITY_STYLE[severity].chip}`}>
      {count !== undefined ? `${count} ${severity}` : severity}
    </span>
  );
}

export function SyncBadge({ status }: { status: SyncStatus }) {
  if (!status) return <span className="text-xs text-slate-400">–</span>;
  const style = {
    done: "bg-emerald-100 text-emerald-800",
    pending: "bg-slate-100 text-slate-700",
    failed: "bg-red-600 text-white",
  }[status];
  const text = { done: "synced", pending: "syncing", failed: "sync failed" }[status];
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${style}`}>{text}</span>;
}

export const formatTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export const formatMoney = (value: number | null | undefined, currency?: string | null) =>
  value === null || value === undefined
    ? "—"
    : `${currency && currency !== "USD" ? `${currency} ` : "$"}${value.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;
