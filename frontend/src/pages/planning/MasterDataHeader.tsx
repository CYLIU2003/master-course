// ── MasterDataHeader ──────────────────────────────────────────
// Title row with add button and view mode switch.
// Mode availability:
//   depots / vehicles: 表 | 地図 | 分割
//   routes:            表 | ノード | 地図 | 分割

import { useTranslation } from "react-i18next";
import { useImportOdptRoutes, useRoutes } from "@/hooks";
import { useMasterUiStore } from "@/stores/master-ui-store";
import type { ViewMode, MasterTabKey } from "@/types/master";

interface Props {
  scenarioId: string;
}

type ModeSpec = { key: ViewMode; label: string };

const MODES_DEPOTS_VEHICLES: ModeSpec[] = [
  { key: "table", label: "表" },
  { key: "map", label: "地図" },
  { key: "split", label: "分割" },
];

const MODES_ROUTES: ModeSpec[] = [
  { key: "table", label: "表" },
  { key: "node", label: "ノード" },
  { key: "map", label: "地図" },
  { key: "split", label: "分割" },
];

export function MasterDataHeader({ scenarioId }: Props) {
  const { t } = useTranslation();
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const viewMode = useMasterUiStore((s) => s.viewMode);
  const setViewMode = useMasterUiStore((s) => s.setViewMode);
  const openDrawer = useMasterUiStore((s) => s.openDrawer);
  const importOdptRoutes = useImportOdptRoutes(scenarioId);
  const { data: routesData } = useRoutes(scenarioId);
  const odptImportMeta = routesData?.meta?.imports?.odpt;

  const addLabel: Record<MasterTabKey, string> = {
    depots: t("master.add_depot", "+ 営業所追加"),
    vehicles: t("master.add_vehicle", "+ 車両追加"),
    routes: t("master.add_route", "+ 路線追加"),
  };

  const modes = activeTab === "routes" ? MODES_ROUTES : MODES_DEPOTS_VEHICLES;

  const handleAdd = () => {
    openDrawer({ isCreate: true });
  };

  const handleImportOdpt = () => {
    if (
      !confirm(
        t(
          "master.import_odpt_confirm",
          "ODPTから東急バスの路線を取り込みます。既存のODPT取込路線は置き換えます。続行しますか？",
        ),
      )
    ) {
      return;
    }

    importOdptRoutes.mutate(
      {
        operator: "odpt.Operator:TokyuBus",
        dump: false,
      },
      {
        onSuccess: (result) => {
          const details = [
            t(
              "master.import_odpt_success",
              "{{count}} 件のODPT路線を取り込みました。",
              { count: result.total },
            ),
            t("master.import_odpt_all_routes", "シナリオ内の総路線数: {{count}}", {
              count: result.allRoutesTotal,
            }),
            t("master.import_odpt_zero_duration", "所要時間 0 分の路線: {{count}}", {
              count: result.meta.quality.zeroDurationCount,
            }),
          ];

          if (result.meta.warnings.length > 0) {
            details.push("", result.meta.warnings.join("\n"));
          }

          alert(details.join("\n"));
        },
        onError: (error) => {
          alert(String(error));
        },
      },
    );
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
        {activeTab === "routes" && odptImportMeta && (
          <p className="mt-1 text-xs text-slate-500">
            {t(
              "master.import_odpt_status",
              "ODPT最終取込: {{generatedAt}} / {{count}} 路線 / 所要時間0分 {{zeroCount}} 件",
              {
                generatedAt: odptImportMeta.generatedAt ?? "-",
                count: odptImportMeta.quality.routeCount,
                zeroCount: odptImportMeta.quality.zeroDurationCount,
              },
            )}
            {odptImportMeta.warnings.length > 0 && (
              <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">
                {t("master.import_odpt_warning_badge", "warning {{count}}", {
                  count: odptImportMeta.warnings.length,
                })}
              </span>
            )}
          </p>
        )}
      </div>

      <div className="flex items-center gap-3">
        {activeTab === "routes" && (
          <button
            onClick={handleImportOdpt}
            disabled={importOdptRoutes.isPending}
            className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
          >
            {importOdptRoutes.isPending
              ? t("master.importing_odpt_routes", "ODPT取込中…")
              : t("master.import_odpt_routes", "ODPTから取込")}
          </button>
        )}

        {/* View mode switch */}
        <div className="flex rounded-lg border border-border">
          {modes.map((m) => (
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
