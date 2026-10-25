// Find a supporting quote in a page's pdf.js text items, so the viewer can mark exactly those items.
//
// Quotes come from the parser's `evidence` and match the PDF text with whitespace ignored (the checker compares
// the same way). A quote may join non-adjacent fragments with "..." (e.g. a party name and the date in its
// signature block); each fragment must appear, in order.

const normalize = (s: string) => s.replace(/\s+/g, "").toLowerCase();

export function quoteFragments(quote: string): string[] {
  return quote
    .split(/\.\.\.|…/)
    .map(normalize)
    .filter((f) => f.length > 0);
}

/** Indexes of the text items covering the quote, or null if it isn't on this page. */
export function matchItems(items: string[], quote: string): Set<number> | null {
  const owner: number[] = [];
  let text = "";
  items.forEach((item, index) => {
    const n = normalize(item);
    text += n;
    for (let i = 0; i < n.length; i++) owner.push(index);
  });
  const marked = new Set<number>();
  let from = 0;
  for (const fragment of quoteFragments(quote)) {
    const at = text.indexOf(fragment, from);
    if (at < 0) return null;
    for (let i = at; i < at + fragment.length; i++) marked.add(owner[i]);
    from = at + fragment.length;
  }
  return marked.size ? marked : null;
}

export function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
