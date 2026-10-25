import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import { escapeHtml, matchItems } from "./highlight";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

export interface Target {
  page: number | null;
  quote: string;
  label: string;
  /** bumps on every click, so clicking the same field again re-scrolls to it */
  nonce: number;
}

interface Props {
  url: string;
  target: Target | null;
}

/** One page at a time; a target jumps to its page and marks the quote using the pdf.js text layer. */
export default function PdfViewer({ url, target }: Props) {
  const [pages, setPages] = useState(0);
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<string[] | null>(null);
  const [width, setWidth] = useState(600);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!box.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(320, entry.contentRect.width - 24)));
    observer.observe(box.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (target?.page) setPage(target.page);
  }, [target]);

  const marked = useMemo(
    () => (target && items && target.page === page ? matchItems(items, target.quote) : null),
    [target, items, page],
  );

  const renderText = useCallback(
    ({ str, itemIndex }: { str: string; itemIndex: number }) =>
      marked?.has(itemIndex) ? `<mark class="pdf-mark">${escapeHtml(str)}</mark>` : escapeHtml(str),
    [marked],
  );

  const scrollToMark = useCallback(() => {
    box.current?.querySelector(".pdf-mark")?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, []);

  useEffect(scrollToMark, [marked, target, scrollToMark]);

  let status: string | null = null;
  if (target) {
    if (target.page === null) status = `Couldn't locate the quote for ${target.label} in the PDF text: “${target.quote}”`;
    else if (items && target.page === page && !marked)
      status = `Quote for ${target.label} not found on page ${page}: “${target.quote}”`;
    else if (marked) status = `${target.label}: page ${page}`;
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-slate-200 bg-white px-3 py-2 text-sm">
        <button className="btn" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} aria-label="Previous page">
          ‹
        </button>
        <span data-testid="pdf-page">
          Page {page} / {pages || "…"}
        </span>
        <button className="btn" disabled={page >= pages} onClick={() => setPage((p) => p + 1)} aria-label="Next page">
          ›
        </button>
        {status && (
          <span className={`ml-2 truncate ${marked ? "text-slate-600" : "text-amber-700"}`} data-testid="pdf-status">
            {status}
          </span>
        )}
      </div>
      <div ref={box} className="flex-1 overflow-auto bg-slate-200 p-3">
        <Document file={url} onLoadSuccess={({ numPages }) => setPages(numPages)} loading="Loading PDF…">
          <Page
            pageNumber={page}
            width={width}
            customTextRenderer={renderText}
            onLoadSuccess={() => setItems(null)}
            onGetTextSuccess={({ items: textItems }) =>
              setItems(textItems.map((item) => ("str" in item ? item.str : "")))
            }
            onRenderTextLayerSuccess={scrollToMark}
            renderAnnotationLayer={false}
          />
        </Document>
      </div>
    </div>
  );
}
