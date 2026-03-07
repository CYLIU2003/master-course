// ── MasterDataTabs ────────────────────────────────────────────
// Operator selector + Sub-tab bar: 営業所 / 車両 / 路線 / 停留所

import { useTranslation } from "react-i18next";
import { useMasterUiStore, OPERATOR_OPTIONS } from "@/stores/master-ui-store";
import type { MasterTabKey } from "@/types/master";

const TABS: { key: MasterTabKey; i18nKey: string; fallback: string }[] = [
  { key: "depots", i18nKey: "master.tab_depots", fallback: "営業所" },
  { key: "vehicles", i18nKey: "master.tab_vehicles", fallback: "車両" },
  { key: "routes", i18nKey: "master.tab_routes", fallback: "路線" },
  { key: "stops", i18nKey: "master.tab_stops", fallback: "停留所" },
];

export function MasterDataTabs() {
  const { t, i18n } = useTranslation();
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const setActiveTab = useMasterUiStore((s) => s.setActiveTab);
  const selectedOperator = useMasterUiStore((s) => s.selectedOperator);
  const setSelectedOperator = useMasterUiStore((s) => s.setSelectedOperator);
  const isJa = i18n.language === "ja";

  return (
    <div className="border-b border-border">
      {/* Operator selector row */}
      <div className="flex items-center gap-2 px-4 pt-2 pb-1">
        <span className="text-xs font-medium text-slate-500">
          {isJa ? "事業者:" : "Operator:"}
        </span>
        {OPERATOR_OPTIONS.map((op) => (
          <button
            key={op.key}
            onClick={() => setSelectedOperator(op.key)}
            className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
              selectedOperator === op.key
                ? "bg-primary-100 text-primary-700 ring-1 ring-primary-300"
                : "bg-slate-100 text-slate-500 hover:bg-slate-200 hover:text-slate-700"
            }`}
          >
            {isJa ? op.label_ja : op.label_en}
          </button>
        ))}
      </div>
      {/* Tab bar */}
      <div className="flex px-4">
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
    </div>
  );
}
