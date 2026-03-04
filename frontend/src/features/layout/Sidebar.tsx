import { NavLink, useLocation } from "react-router-dom";
import { useUIStore, type ActiveTab } from "@/stores/ui-store";

interface SidebarProps {
  open: boolean;
  scenarioId: string;
}

interface NavItem {
  label: string;
  to: string;
}

// ── Tab 1 sub-nav: planning-related pages ─────────────────────
const planningNav: NavItem[] = [
  { label: "Depots / Vehicles / Routes", to: "planning" },
  { label: "Timetable", to: "timetable" },
  { label: "Deadhead Rules", to: "deadhead" },
  { label: "Turnaround Rules", to: "rules" },
];

// ── Tab 2 sub-nav: simulation-related pages ───────────────────
const simulationNav: NavItem[] = [
  { label: "Environment Config", to: "simulation-env" },
];

// ── Dispatch pipeline sub-nav (available from both tabs) ──────
const dispatchNav: NavItem[] = [
  { label: "Trips", to: "trips" },
  { label: "Graph", to: "graph" },
  { label: "Duties", to: "duties" },
  { label: "Precheck", to: "precheck" },
  { label: "Simulation Run", to: "simulation" },
  { label: "Optimization", to: "optimization" },
];

const resultsNav: NavItem[] = [
  { label: "Dispatch Results", to: "results/dispatch" },
  { label: "Energy Results", to: "results/energy" },
  { label: "Cost Results", to: "results/cost" },
];

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
  items: NavItem[];
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
  const activeTab = useUIStore((s) => s.activeTab);
  const setActiveTab = useUIStore((s) => s.setActiveTab);

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
          Overview
        </NavLink>
      </div>

      {/* Tab switcher */}
      <div className="flex border-b border-border px-2">
        <TabButton
          label="Planning"
          active={activeTab === "planning"}
          onClick={() => setActiveTab("planning")}
        />
        <TabButton
          label="Simulation"
          active={activeTab === "simulation"}
          onClick={() => setActiveTab("simulation")}
        />
      </div>

      {/* Tab-specific navigation */}
      <div className="flex-1 overflow-y-auto py-3">
        {activeTab === "planning" && (
          <NavSection
            title="Master Data"
            items={planningNav}
            scenarioId={scenarioId}
          />
        )}

        {activeTab === "simulation" && (
          <NavSection
            title="Configuration"
            items={simulationNav}
            scenarioId={scenarioId}
          />
        )}

        {/* Dispatch & Results always visible */}
        <NavSection
          title="Dispatch"
          items={dispatchNav}
          scenarioId={scenarioId}
        />
        <NavSection
          title="Results"
          items={resultsNav}
          scenarioId={scenarioId}
        />
      </div>
    </aside>
  );
}
