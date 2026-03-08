import { Link, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useUIStore } from "@/stores/ui-store";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { useScenario, useScenarios } from "@/hooks";

export function Header() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const scenarioId = useUIStore((s) => s.activeScenarioId);
  const { data: scenario } = useScenario(scenarioId ?? "");
  const { data: scenarios } = useScenarios();
  const currentScenarioLabel = scenario?.name ?? scenarioId ?? "";
  const currentScenarioPath = scenarioId
    ? location.pathname.replace(`/scenarios/${scenarioId}`, "").replace(/^\/+/, "")
    : "";

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
          {t("app.name")}
        </Link>
        {scenarioId && (
          <span className="text-xs text-slate-400">/</span>
        )}
        {scenarioId && (
          <div className="flex items-center gap-2">
            <span className="max-w-48 truncate text-xs font-medium text-slate-500">
              {currentScenarioLabel}
            </span>
            <select
              value={scenarioId}
              onChange={(e) => {
                const nextId = e.target.value;
                if (!nextId) return;
                const nextPath = currentScenarioPath || "planning";
                navigate(`/scenarios/${nextId}/${nextPath}`);
              }}
              className="rounded border border-border bg-white px-2 py-0.5 text-xs text-slate-600"
              aria-label="Switch scenario"
            >
              {(scenarios?.items ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>
      <div className="flex items-center gap-3">
        <LanguageSwitcher />
        <Link
          to={scenarioId ? `/scenarios/${scenarioId}/public-data` : "/scenarios"}
          className="rounded px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
        >
          {t("nav.odpt_explorer")}
        </Link>
        <Link
          to="/compare"
          className="rounded px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
        >
          {t("nav.compare")}
        </Link>
      </div>
    </header>
  );
}
