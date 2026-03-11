import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useEffect, useState } from "react";
import { useScenario } from "@/hooks";
import { useUIStore } from "@/stores/ui-store";
import { usePlanningDatasetStore } from "@/stores/planning-dataset-store";
import { PageSection } from "@/features/common";
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
  const { data: scenario } = useScenario(scenarioId ?? "");
  const selectedDepotId = useUIStore((s) => s.selectedDepotId);
  const [showAllRoutes, setShowAllRoutes] = useState(false);
  const setActiveDepotId = usePlanningDatasetStore((s) => s.setActiveDepotId);
  const setShowAllRoutesStore = usePlanningDatasetStore((s) => s.setShowAllRoutes);
  const setFeedContext = usePlanningDatasetStore((s) => s.setFeedContext);

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
          <DepotListPanel scenarioId={scenarioId} />
        </div>

        {/* Right: Depot detail or placeholder */}
        <div className="flex-1 rounded-lg border border-border bg-surface-raised">
          {selectedDepotId ? (
            <DepotDetailPanel
              scenarioId={scenarioId}
              depotId={selectedDepotId}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">
              {t("planning.select_depot")}
            </div>
          )}
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
            depotId={selectedDepotId && !showAllRoutes ? selectedDepotId : undefined}
          />
        ) : (
          <div className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-slate-500">
            営業所を選択すると、対象 route 一覧を遅延読み込みします。
          </div>
        )}
      </PageSection>

      {/* Depot-Route permission matrix */}
      {selectedDepotId && (
        <PageSection
          title="営業所-路線許可"
          description="選択中の営業所で扱う路線を明示的に切り替えます。配車前処理ではこの許可集合を起点に subset を絞ります。"
        >
          <DepotRouteMatrix
            scenarioId={scenarioId}
            depotId={selectedDepotId}
          />
        </PageSection>
      )}

      {/* Vehicle-Route permission matrix */}
      {selectedDepotId && (
        <PageSection
          title={t("planning.permissions_title")}
          description="営業所で許可された路線のうち、どの車両が担当できるかを制御します。"
        >
          <VehicleRouteMatrix
            scenarioId={scenarioId}
            depotId={selectedDepotId}
          />
        </PageSection>
      )}
    </div>
  );
}
