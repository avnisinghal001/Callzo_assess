/** First, last, and the neighbours of the current page; 0 marks a gap. */
export function pageList(page: number, pages: number): number[] {
  const want = [...new Set([1, page - 1, page, page + 1, pages])].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  return want.flatMap((n, i) => (i && n - want[i - 1] > 1 ? [0, n] : [n]));
}
