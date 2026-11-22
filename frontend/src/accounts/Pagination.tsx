import { formatCount } from "../lib/format.ts";
import { pageList } from "../lib/pages.ts";
import { Button, IconButton } from "../ui/primitives.tsx";
import { Icon } from "../ui/Icon.tsx";

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages === 1) return <div className="h-3" />;
  return (
    <nav aria-label="Pages" className="flex items-center justify-between gap-2 p-3 sm:px-5 sm:py-4">
      <Button icon="back" disabled={page <= 1} onClick={() => onPage(page - 1)} className="max-sm:hidden">Previous</Button>
      <IconButton icon="back" label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)} className="sm:hidden" />
      <div className="flex items-center gap-0.5">
        {pageList(page, pages).map((n, i) => n === 0
          ? <span key={`g${i}`} className="px-1 text-faint" aria-hidden="true">…</span>
          : <button key={n} type="button" aria-label={`Page ${n}`} aria-current={n === page ? "page" : undefined} onClick={() => onPage(n)}
              className={`tnum h-10 min-w-10 rounded-xl px-2 text-sm font-semibold transition-colors ${n === page ? "bg-primary text-white" : "text-muted hover:bg-card hover:text-ink"}`}>{formatCount(n)}</button>)}
      </div>
      <Button disabled={page >= pages} onClick={() => onPage(page + 1)} className="max-sm:hidden">Next<Icon name="next" size={17} /></Button>
      <IconButton icon="next" label="Next page" disabled={page >= pages} onClick={() => onPage(page + 1)} className="sm:hidden" />
    </nav>
  );
}
