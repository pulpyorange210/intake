import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type FormSummary, type Severity } from "./api";
import { SeverityChip, SyncBadge, formatTime } from "./ui";

const FILTERS = [
  { key: "needs_review", label: "Needs review" },
  { key: "", label: "All" },
  { key: "approved", label: "Approved" },
  { key: "sync_failed", label: "Sync failed" },
];

export default function QueuePage() {
  const [filter, setFilter] = useState("needs_review");
  const [forms, setForms] = useState<FormSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const load = useCallback(() => {
    api
      .listForms(filter || undefined)
      .then((f) => {
        setForms(f);
        setError(null);
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, [filter]);

  useEffect(load, [load]);
  useEffect(() => {
    // keep the queue fresh while uploads are processing and syncs are running
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [load]);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    try {
      for (const file of Array.from(files)) await api.upload(file);
      setFilter("");
      load();
    } catch (e) {
      setError(`Upload failed: ${(e as Error).message}`);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Order forms</h1>
          <p className="text-sm text-slate-500">Flagged forms first, highest severity, then oldest.</p>
        </div>
        <label className="btn-primary cursor-pointer">
          {uploading ? "Uploading…" : "Upload PDF"}
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf"
            multiple
            className="hidden"
            data-testid="upload-input"
            onChange={(e) => upload(e.target.files)}
          />
        </label>
      </header>

      <nav className="mb-3 flex gap-1" role="tablist">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            role="tab"
            aria-selected={filter === f.key}
            onClick={() => setFilter(f.key)}
            className={`rounded px-3 py-1.5 text-sm font-medium ${
              filter === f.key ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-200"
            }`}
          >
            {f.label}
          </button>
        ))}
      </nav>

      {error && <p className="mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2">File</th>
              <th className="px-4 py-2">Uploaded</th>
              <th className="px-4 py-2">Open flags</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Sync</th>
            </tr>
          </thead>
          <tbody>
            {forms?.map((form) => (
              <tr
                key={form.id}
                data-testid="queue-row"
                className="cursor-pointer border-b border-slate-100 last:border-0 hover:bg-slate-50"
                onClick={() => navigate(`/forms/${form.id}`)}
              >
                <td className="px-4 py-2 font-medium">
                  <Link to={`/forms/${form.id}`} onClick={(e) => e.stopPropagation()}>
                    {form.filename}
                  </Link>
                </td>
                <td className="px-4 py-2 text-slate-600">{formatTime(form.uploaded_at)}</td>
                <td className="px-4 py-2">
                  <div className="flex gap-1">
                    {(["high", "medium", "low"] as Severity[]).map((s) =>
                      form.open_flags[s] ? <SeverityChip key={s} severity={s} count={form.open_flags[s]} /> : null,
                    )}
                    {form.status === "needs_review" && !form.top_severity && (
                      <span className="text-xs text-emerald-700">clean</span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-2 text-slate-600">
                  {form.status === "processing" ? "extracting…" : form.status.replace("_", " ")}
                </td>
                <td className="px-4 py-2">
                  <SyncBadge status={form.sync_status} />
                </td>
              </tr>
            ))}
            {forms && forms.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                  Nothing here.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
