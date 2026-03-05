// ── MasterDataHeader ──────────────────────────────────────────
// Title row with add button and view mode switch.

import { useTranslation } from "react-i18next";
import { useMasterUiStore } from "@/stores/master-ui-store";
import type { ViewMode, MasterTabKey } from "@/types/master";

interface Props {
  scenarioId: string;
}

const VIEW_MODES: { key: ViewMode; label: string }[] = [
  { key: "table", label: "表" },
  { key: "node", label: "ノード" },
  // { key: "map", label: "地図" },    // Phase 3
  // { key: "split", label: "分割" },  // Phase 3
];

export function MasterDataHeader({ scenarioId }: Props) {
  const { t } = useTranslation();
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const viewMode = useMasterUiStore((s) => s.viewMode);
  const setViewMode = useMasterUiStore((s) => s.setViewMode);
  const openDrawer = useMasterUiStore((s) => s.openDrawer);

  const addLabel: Record<MasterTabKey, string> = {
    depots: t("master.add_depot", "+ 営業所追加"),
    vehicles: t("master.add_vehicle", "+ 車両追加"),
    routes: t("master.add_route", "+ 路線追加"),
  };

  const handleAdd = () => {
    openDrawer({ isCreate: true });
  };

  return (
    <div className="flex items-center justify-between border-b border-border px-4 py-3">
      <div>
        <h1 className="text-lg font-semibold text-slate-800">
          {t("master.title", "営業所・車両・路線")}
        </h1>
        <p className="text-xs text-slate-500">
          {t("master.description", "マスタデータを一元管理します")}
        </p>
      </div>

      <div className="flex items-center gap-3">
        {/* View mode switch (only show for routes tab) */}
        {activeTab === "routes" && (
          <div className="flex rounded-lg border border-border">
            {VIEW_MODES.map((m) => (
              <button
                key={m.key}
                onClick={() => setViewMode(m.key)}
                className={`px-3 py-1 text-xs font-medium transition-colors first:rounded-l-lg last:rounded-r-lg ${
                  viewMode === m.key
                    ? "bg-primary-600 text-white"
                    : "text-slate-600 hover:bg-slate-50"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        )}

        {/* Add button */}
        <button
          onClick={handleAdd}
          className="rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700"
        >
          {addLabel[activeTab]}
        </button>
      </div>
    </div>
  );
}
