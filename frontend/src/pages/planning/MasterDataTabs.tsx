// ── MasterDataTabs ────────────────────────────────────────────
// Sub-tab bar: 営業所 / 車両 / 路線

import { useTranslation } from "react-i18next";
import { useMasterUiStore } from "@/stores/master-ui-store";
import type { MasterTabKey } from "@/types/master";

const TABS: { key: MasterTabKey; i18nKey: string; fallback: string }[] = [
  { key: "depots", i18nKey: "master.tab_depots", fallback: "営業所" },
  { key: "vehicles", i18nKey: "master.tab_vehicles", fallback: "車両" },
  { key: "routes", i18nKey: "master.tab_routes", fallback: "路線" },
  { key: "stops", i18nKey: "master.tab_stops", fallback: "停留所" },
];

export function MasterDataTabs() {
  const { t } = useTranslation();
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const setActiveTab = useMasterUiStore((s) => s.setActiveTab);

  return (
    <div className="flex border-b border-border px-4">
      {TABS.map((tab) => (
        <button
          key={tab.key}
          onClick={() => setActiveTab(tab.key)}
          className={`px-4 py-2.5 text-sm font-medium transition-colors ${
            activeTab === tab.key
              ? "border-b-2 border-primary-500 text-primary-700"
              : "text-slate-500 hover:text-slate-700"
          }`}
        >
          {t(tab.i18nKey, tab.fallback)}
        </button>
      ))}
    </div>
  );
}
