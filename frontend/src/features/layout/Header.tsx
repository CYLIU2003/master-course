import { Link } from "react-router-dom";
import { useUIStore } from "@/stores/ui-store";

export function Header() {
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const scenarioId = useUIStore((s) => s.activeScenarioId);

  return (
    <header className="flex h-12 items-center justify-between border-b border-border bg-surface-raised px-4">
      <div className="flex items-center gap-3">
        <button
          onClick={toggleSidebar}
          className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
          aria-label="Toggle sidebar"
        >
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <Link to="/scenarios" className="text-sm font-semibold text-slate-800 hover:text-primary-600">
          EV Bus Scheduling
        </Link>
        {scenarioId && (
          <span className="text-xs text-slate-400">/</span>
        )}
        {scenarioId && (
          <span className="text-xs font-medium text-slate-500 truncate max-w-48">
            {scenarioId}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Link
          to="/compare"
          className="rounded px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
        >
          Compare
        </Link>
      </div>
    </header>
  );
}
