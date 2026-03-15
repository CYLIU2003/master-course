import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useEffect, useState } from "react";
import { useEditorBootstrap, useDispatchScope, useUpdateDispatchScope } from "@/hooks";
import { useUIStore } from "@/stores/ui-store";
import { usePlanningDatasetStore } from "@/stores/planning-dataset-store";
import { PageSection } from "@/features/common";
import type { UpdateDispatchScopeRequest } from "@/types";
import {
  DepotListPanel,
  DepotDetailPanel,
  DepotRouteMatrix,
  RouteTable,
  VehicleRouteMatrix,
} from "@/features/planning";

export function MasterPlanningPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: bootstrap, isLoading, error } = useEditorBootstrap(scenarioId ?? "");
  const scenario = bootstrap?.scenario;
  const selectedDepotId = useUIStore((s) => s.selectedDepotId);
  const [showAllRoutes, setShowAllRoutes] = useState(false);
  const [showDepotRouteMatrix, setShowDepotRouteMatrix] = useState(false);
  const [showVehicleRouteMatrix, setShowVehicleRouteMatrix] = useState(false);
  const setActiveDepotId = usePlanningDatasetStore((s) => s.setActiveDepotId);
  const setShowAllRoutesStore = usePlanningDatasetStore((s) => s.setShowAllRoutes);
  const setFeedContext = usePlanningDatasetStore((s) => s.setFeedContext);
  const syncDepots = usePlanningDatasetStore((s) => s.syncDepots);

  // Dispatch scope — for reading/writing swap permissions and tripSelection
  const { data: dispatchScope } = useDispatchScope(scenarioId ?? "");
  const updateScope = useUpdateDispatchScope(scenarioId ?? "");
  const intraSwap = dispatchScope?.allowIntraDepotRouteSwap ?? false;
  const interSwap = dispatchScope?.allowInterDepotSwap ?? false;
  const includeShortTurn = dispatchScope?.tripSelection?.includeShortTurn ?? true;
  const includeDepotMoves = dispatchScope?.tripSelection?.includeDepotMoves ?? true;

  function handleScopeToggle(patch: UpdateDispatchScopeRequest) {
    updateScope.mutate(patch);
  }

  useEffect(() => {
    if (bootstrap?.depots) {
      syncDepots(bootstrap.depots);
    }
  }, [bootstrap?.depots, syncDepots]);

  useEffect(() => {
    setActiveDepotId(selectedDepotId);
  }, [selectedDepotId, setActiveDepotId]);

  useEffect(() => {
    setShowAllRoutesStore(showAllRoutes);
  }, [showAllRoutes, setShowAllRoutesStore]);

  useEffect(() => {
    setFeedContext(scenario?.feedContext ?? null);
  }, [scenario?.feedContext, setFeedContext]);

  if (!scenarioId) return null;

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-sm text-slate-500">{t("common.loading")}...</div>
      </div>
    );
  }

  if (error || !bootstrap) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-sm text-red-500">{error?.message ?? "Failed to load"}</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page title */}
      <div>
        <h1 className="text-lg font-semibold text-slate-800">
          {t("planning.title")}
        </h1>
        <p className="text-sm text-slate-500">
          {t("planning.description")}
        </p>
        {scenario?.feedContext && (
          <p className="mt-2 text-xs text-slate-500">
            {scenario.feedContext.feedId ?? "unscoped"}
            {" / "}
            {scenario.feedContext.snapshotId ?? "no-snapshot"}
            {scenario.feedContext.datasetId
              ? ` / ${scenario.feedContext.datasetId}`
              : ""}
          </p>
        )}
      </div>

      {/* Main 2-column layout: depot list + detail */}
      <div className="flex gap-4" style={{ minHeight: "400px" }}>
        {/* Left: Depot list */}
        <div className="w-56 shrink-0 rounded-lg border border-border bg-surface-raised">
          <DepotListPanel scenarioId={scenarioId} depots={bootstrap.depots} />
        </div>

        {/* Right: Depot detail or placeholder */}
        <div className="flex-1 rounded-lg border border-border bg-surface-raised">
          {selectedDepotId ? (
            <DepotDetailPanel
              scenarioId={scenarioId}
              depotId={selectedDepotId}
              depotData={bootstrap.depots.find(d => d.id === selectedDepotId)}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">
              {t("planning.select_depot")}
            </div>
          )}
        </div>
      </div>

      {/* Dispatch scope: swap permissions and trip selection */}
      <div className="rounded-lg border border-border bg-surface-raised px-4 py-3">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">配車スコープ設定</h3>
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          {/* Trip selection */}
          <div className="flex items-center gap-4">
            <span className="text-xs font-medium text-slate-500">便種:</span>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-700">
              <input
                type="checkbox"
                checked={includeShortTurn}
                onChange={(e) => handleScopeToggle({ tripSelection: { includeShortTurn: e.target.checked, includeDepotMoves, includeDeadhead: true } })}
                className="h-3.5 w-3.5 rounded border-slate-300 text-primary-600"
              />
              区間便
            </label>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-700">
              <input
                type="checkbox"
                checked={includeDepotMoves}
                onChange={(e) => handleScopeToggle({ tripSelection: { includeShortTurn, includeDepotMoves: e.target.checked, includeDeadhead: true } })}
                className="h-3.5 w-3.5 rounded border-slate-300 text-primary-600"
              />
              入出庫便
            </label>
          </div>
          {/* Swap permissions */}
          <div className="flex items-center gap-4">
            <span className="text-xs font-medium text-slate-500">車両トレード:</span>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-700">
              <input
                type="checkbox"
                checked={intraSwap}
                onChange={(e) => handleScopeToggle({ allowIntraDepotRouteSwap: e.target.checked })}
                className="h-3.5 w-3.5 rounded border-slate-300 text-amber-500"
                disabled={updateScope.isPending}
              />
              <span className={intraSwap ? "font-semibold text-amber-700" : ""}>路線内</span>
            </label>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-700">
              <input
                type="checkbox"
                checked={interSwap}
                onChange={(e) => handleScopeToggle({ allowInterDepotSwap: e.target.checked })}
                className="h-3.5 w-3.5 rounded border-slate-300 text-red-500"
                disabled={updateScope.isPending}
              />
              <span className={interSwap ? "font-semibold text-red-700" : ""}>営業所間</span>
            </label>
          </div>
        </div>
      </div>

      {/* Routes section (not depot-scoped) */}
      <PageSection
        title={t("planning.routes_title")}
        description={
          selectedDepotId && !showAllRoutes
            ? "Explorer で最後に確定した営業所に関係する route を優先表示しています。"
            : "営業所を確定してから route 一覧を読み込みます。未選択時は重い route 明細を取得しません。"
        }
        actions={
          selectedDepotId ? (
            <label className="flex items-center gap-2 text-xs text-slate-600">
              <input
                type="checkbox"
                checked={showAllRoutes}
                onChange={(e) => setShowAllRoutes(e.target.checked)}
              />
              すべて表示
            </label>
          ) : undefined
        }
      >
        {selectedDepotId ? (
          <RouteTable
            scenarioId={scenarioId}
            depotId={!showAllRoutes ? selectedDepotId : undefined}
            showAll={showAllRoutes}
          />
        ) : (
          <div className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-slate-500">
            営業所を選択すると、対象 route 一覧を遅延読み込みします。
          </div>
        )}
      </PageSection>

      {/* Depot-Route permission matrix - lazy loaded */}
      {selectedDepotId && (
        <PageSection
          title="営業所-路線許可"
          description="選択中の営業所で扱う路線を明示的に切り替えます。配車前処理ではこの許可集合を起点に subset を絞ります。"
          defaultExpanded={false}
          onExpandChange={(expanded) => setShowDepotRouteMatrix(expanded)}
        >
          {showDepotRouteMatrix ? (
            <DepotRouteMatrix
              scenarioId={scenarioId}
              depotId={selectedDepotId}
            />
          ) : (
            <div className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-slate-500">
              クリックして許可設定を編集
            </div>
          )}
        </PageSection>
      )}

      {/* Vehicle-Route permission matrix - lazy loaded */}
      {selectedDepotId && (
        <PageSection
          title={t("planning.permissions_title")}
          description="営業所で許可された路線のうち、どの車両が担当できるかを制御します。"
          defaultExpanded={false}
          onExpandChange={(expanded) => setShowVehicleRouteMatrix(expanded)}
        >
          {showVehicleRouteMatrix ? (
            <VehicleRouteMatrix
              scenarioId={scenarioId}
              depotId={selectedDepotId}
            />
          ) : (
            <div className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-slate-500">
              クリックして車両許可設定を編集
            </div>
          )}
        </PageSection>
      )}
    </div>
  );
}
