import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useUIStore } from "@/stores/ui-store";

interface SidebarProps {
  open: boolean;
  scenarioId: string;
}

interface NavItem {
  labelKey: string;
  to: string;
  fallbackLabel?: string;
}

// ── Tab button component ──────────────────────────────────────

function TabButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 py-2 text-xs font-medium transition-colors ${
        active
          ? "border-b-2 border-primary-500 text-primary-700"
          : "text-slate-500 hover:text-slate-700"
      }`}
    >
      {label}
    </button>
  );
}

// ── Nav section component ─────────────────────────────────────

function NavSection({
  title,
  items,
  scenarioId,
}: {
  title: string;
  items: { label: string; to: string }[];
  scenarioId: string;
}) {
  return (
    <div className="mb-4">
      <h3 className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        {title}
      </h3>
      <ul className="space-y-0.5">
        {items.map((item) => (
          <li key={item.to}>
            <NavLink
              to={`/scenarios/${scenarioId}/${item.to}`}
              className={({ isActive }) =>
                `block rounded-md px-3 py-1.5 text-sm transition-colors ${
                  isActive
                    ? "bg-primary-50 font-medium text-primary-700"
                    : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                }`
              }
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Main sidebar ──────────────────────────────────────────────

export function Sidebar({ open, scenarioId }: SidebarProps) {
  const { t } = useTranslation();
  const activeTab = useUIStore((s) => s.activeTab);
  const setActiveTab = useUIStore((s) => s.setActiveTab);

  // Nav arrays defined inside component to pick up live translations
  const planningNavItems: NavItem[] = [
    { labelKey: "sidebar.depots_vehicles_routes", to: "planning" },
    {
      labelKey: "nav.odpt_explorer",
      to: "public-data",
      fallbackLabel: "公開情報",
    },
    {
      labelKey: "sidebar.vehicle_templates",
      to: "vehicle-templates",
      fallbackLabel: "車両テンプレート",
    },
    { labelKey: "sidebar.timetable", to: "timetable" },
    { labelKey: "sidebar.deadhead_rules", to: "deadhead" },
    { labelKey: "sidebar.turnaround_rules", to: "rules" },
  ];

  const simulationNavItems: NavItem[] = [
    { labelKey: "sidebar.environment_config", to: "simulation-env" },
  ];

  const dispatchNavItems: NavItem[] = [
    { labelKey: "sidebar.trips", to: "trips" },
    { labelKey: "sidebar.graph", to: "graph" },
    { labelKey: "sidebar.duties", to: "duties" },
    { labelKey: "sidebar.precheck", to: "precheck" },
    { labelKey: "sidebar.simulation_run", to: "simulation" },
    { labelKey: "sidebar.optimization", to: "optimization" },
  ];

  const resultsNavItems: NavItem[] = [
    { labelKey: "sidebar.dispatch_results", to: "results/dispatch" },
    { labelKey: "sidebar.energy_results", to: "results/energy" },
    { labelKey: "sidebar.cost_results", to: "results/cost" },
  ];

  const resolve = (items: NavItem[]) =>
    items.map((item) => ({
      label: item.fallbackLabel ? t(item.labelKey, item.fallbackLabel) : t(item.labelKey),
      to: item.to,
    }));

  if (!open) return null;

  return (
    <aside className="flex w-52 shrink-0 flex-col overflow-y-auto border-r border-border bg-surface-raised">
      {/* Overview link */}
      <div className="px-3 pt-3 pb-2">
        <NavLink
          to={`/scenarios/${scenarioId}`}
          end
          className={({ isActive }) =>
            `block rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              isActive
                ? "bg-primary-50 text-primary-700"
                : "text-slate-700 hover:bg-slate-50"
            }`
          }
        >
          {t("nav.overview")}
        </NavLink>
      </div>

      {/* Tab switcher */}
      <div className="flex border-b border-border px-2">
        <TabButton
          label={t("nav.planning_tab")}
          active={activeTab === "planning"}
          onClick={() => setActiveTab("planning")}
        />
        <TabButton
          label={t("nav.simulation_tab")}
          active={activeTab === "simulation"}
          onClick={() => setActiveTab("simulation")}
        />
      </div>

      {/* Tab-specific navigation */}
      <div className="flex-1 overflow-y-auto py-3">
        {activeTab === "planning" && (
          <NavSection
            title={t("nav.master_data")}
            items={resolve(planningNavItems)}
            scenarioId={scenarioId}
          />
        )}

        {activeTab === "simulation" && (
          <NavSection
            title={t("nav.configuration")}
            items={resolve(simulationNavItems)}
            scenarioId={scenarioId}
          />
        )}

        {/* Dispatch & Results always visible */}
        <NavSection
          title={t("nav.dispatch")}
          items={resolve(dispatchNavItems)}
          scenarioId={scenarioId}
        />
        <NavSection
          title={t("nav.results")}
          items={resolve(resultsNavItems)}
          scenarioId={scenarioId}
        />
      </div>
    </aside>
  );
}
