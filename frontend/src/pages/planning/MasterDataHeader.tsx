import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  useScenario,
} from "@/hooks";
import { useMasterUiStore } from "@/stores/master-ui-store";
import { useTabWarmStore } from "@/stores/tab-warm-store";
import { ImportLogPanel } from "@/features/explorer/ImportLogPanel";
import { ImportProgressPanel } from "@/features/explorer/ImportProgressPanel";
import { useRenderTrace } from "@/utils/perf/useRenderTrace";
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

const MODES_STOPS: ModeSpec[] = [{ key: "table", label: "表" }];

export function MasterDataHeader({ scenarioId }: Props) {
  const { t } = useTranslation();
  useRenderTrace("MasterDataHeader");
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const viewMode = useMasterUiStore((s) => s.viewMode);
  const setViewMode = useMasterUiStore((s) => s.setViewMode);
  const openDrawer = useMasterUiStore((s) => s.openDrawer);
  const { data: scenario } = useScenario(scenarioId);
  const warmTabs = useTabWarmStore((state) => state.tabs);

  const addLabel: Partial<Record<MasterTabKey, string>> = {
    depots: t("master.add_depot", "+ 営業所追加"),
    vehicles: t("master.add_vehicle", "+ 車両追加"),
    routes: t("master.add_route", "+ 路線追加"),
  };

  const modes =
    activeTab === "routes"
      ? MODES_ROUTES
      : activeTab === "stops"
        ? MODES_STOPS
        : MODES_DEPOTS_VEHICLES;

  const canAdd = activeTab !== "stops";
  const summaryCards = [
    { label: t("master.summary_routes", "路線"), value: scenario?.stats?.routeCount ?? 0 },
    { label: t("master.summary_stops", "停留所"), value: scenario?.stats?.stopCount ?? 0 },
    {
      label: t("master.summary_timetable", "時刻表"),
      value: scenario?.stats?.timetableRowCount ?? 0,
    },
    {
      label: t("master.summary_stop_timetables", "バス停時刻表"),
      value: "-",
    },
  ];

  return (
    <div className="border-b border-border px-4 py-3">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">
            {t("master.title", "営業所・車両・路線・停留所")}
          </h1>
          <p className="text-xs text-slate-500">
            {t(
              "master.description",
              "事前構築済みの Tokyu データセットを前提に、営業所・車両・路線設定を調整します。",
            )}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link
            to={`/scenarios/${scenarioId}/timetable`}
            className="rounded-lg border border-border bg-surface px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            {t("master.open_timetable", "時刻表タブへ")}
          </Link>
          <div className="flex rounded-lg border border-border">
            {modes.map((mode) => (
              <button
                key={mode.key}
                onClick={() => setViewMode(mode.key)}
                className={`px-3 py-1 text-xs font-medium transition-colors first:rounded-l-lg last:rounded-r-lg ${
                  viewMode === mode.key
                    ? "bg-primary-600 text-white"
                    : "text-slate-600 hover:bg-slate-50"
                }`}
              >
                {mode.label}
              </button>
            ))}
          </div>

          {canAdd && (
            <button
              onClick={() => openDrawer({ isCreate: true })}
              className="rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700"
            >
              {addLabel[activeTab]}
            </button>
          )}
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-xs text-slate-600">
          <div className="flex flex-wrap items-center gap-2">
            <span>
              {t(
                "master.explorer_note",
                "main app は seed + built dataset の consumer です。raw ODPT / GTFS 更新は data-prep 側で実行してください。",
              )}
            </span>
            <span className="font-mono text-slate-500">{scenarioId}</span>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {summaryCards.map((card) => (
              <div
                key={card.label}
                className="rounded-md border border-slate-200 bg-white px-3 py-2"
              >
                <div className="text-[11px] text-slate-500">{card.label}</div>
                <div className="mt-1 text-base font-semibold text-slate-800">
                  {card.value}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {(
              Object.entries(warmTabs) as Array<
                [keyof typeof warmTabs, { status: string; detail?: string }]
              >
            ).map(([tab, state]) => (
              <span
                key={tab}
                className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-slate-600"
                title={state.detail}
              >
                {tab}: {state.status}
              </span>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-sky-700">
            {t("master.snapshot_sync", "Dataset readiness")}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Link
              to={`/scenarios/${scenarioId}/timetable`}
              className="rounded-md border border-sky-300 bg-white px-3 py-1.5 text-xs font-medium text-sky-700"
            >
              {t("master.open_timetable_imports", "時刻表データを確認")}
            </Link>
          </div>
          <p className="mt-2 text-[11px] text-sky-900/80">
            `data/built/` が空の場合は timetable / optimization が無効になります。dataset 生成は data-prep CLI で実行してください。
          </p>
        </div>
      </div>

      {(activeTab === "routes" || activeTab === "stops") && (
        <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <ImportProgressPanel />
          <ImportLogPanel />
        </div>
      )}
    </div>
  );
}
