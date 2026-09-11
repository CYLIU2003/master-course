import { ChevronLeft, ChevronRight } from "lucide-react";
export function ErrorBox({ error }: { error: Error | null }) {
  return error ? (
    <div role="alert" className="error">
      {error.message}
    </div>
  ) : null;
}
export function Pager({
  offset,
  total,
  size,
  set,
}: {
  offset: number;
  total: number;
  size: number;
  set: (n: number) => void;
}) {
  return (
    <div className="pager">
      <span>
        {total ? offset + 1 : 0}–{Math.min(offset + size, total)} /{" "}
        {total.toLocaleString()} 件
      </span>
      <button
        aria-label="前のページ"
        disabled={!offset}
        onClick={() => set(Math.max(0, offset - size))}
      >
        <ChevronLeft size={16} />
      </button>
      <button
        aria-label="次のページ"
        disabled={offset + size >= total}
        onClick={() => set(offset + size)}
      >
        <ChevronRight size={16} />
      </button>
    </div>
  );
}
